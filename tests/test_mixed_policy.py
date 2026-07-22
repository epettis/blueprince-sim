"""Explore/exploit mixed-sampling policy behavior."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("sb3_contrib")

from sb3_contrib import MaskablePPO  # noqa: E402  (import gated by importorskip above)

from blueprince_sim.rl.mixed_policy import MixedExplorationPolicy  # noqa: E402
from blueprince_sim.rl.train import make_single_env  # noqa: E402


@pytest.fixture(scope="module")
def model_env():
    env = make_single_env("shaped", 0)()
    model = MaskablePPO(
        MixedExplorationPolicy, env, n_steps=64, batch_size=64, seed=0,
        device="cpu",
        policy_kwargs={"exploit_temp": 0.5, "explore_temp": 1.5, "explore_eps": 0.05},
    )
    return model, env


def _obs_and_mask(env):
    obs, _ = env.reset(seed=0)
    mask = env.get_wrapper_attr("action_masks")()
    obs_t = {k: torch.as_tensor(np.asarray(v)[None]) for k, v in obs.items()}
    return obs_t, torch.as_tensor(np.asarray(mask)[None])


def _sample_many(policy, obs_t, mask_t, n=3000):
    # Seed torch's global RNG so sampling is reproducible regardless of the
    # order tests run in (the model fixture is shared across the module).
    torch.manual_seed(0)
    actions = []
    with torch.no_grad():
        for _ in range(n):
            a, _, _ = policy.forward(obs_t, action_masks=mask_t)
            actions.append(int(a))
    return np.array(actions)


def test_never_samples_masked_actions(model_env):
    model, env = model_env
    policy = model.policy
    obs_t, mask_t = _obs_and_mask(env)
    legal = set(np.flatnonzero(mask_t.numpy()[0]))
    for exploit in (True, False):
        policy.set_mode_config(1.0 if exploit else 0.0, False, 1, 0)
        actions = _sample_many(policy, obs_t, mask_t, n=4000)
        assert set(actions) <= legal


def test_exploit_low_temp_matches_argmax(model_env):
    model, env = model_env
    policy = model.policy
    obs_t, mask_t = _obs_and_mask(env)
    old = policy.exploit_temp
    # An untrained net has near-tied logits (~1e-3 apart), so the temperature
    # must be far below the tie scale to make sampling ~deterministic.
    policy.exploit_temp = 1e-5
    try:
        policy.set_mode_config(1.0, False, 1, 0)
        with torch.no_grad():
            argmax_a, _, _ = policy.forward(obs_t, deterministic=True,
                                            action_masks=mask_t)
        actions = _sample_many(policy, obs_t, mask_t, n=500)
        assert (actions == int(argmax_a)).mean() > 0.95
    finally:
        policy.exploit_temp = old


def test_explore_has_higher_entropy(model_env):
    model, env = model_env
    policy = model.policy
    obs_t, mask_t = _obs_and_mask(env)

    def empirical_entropy(actions):
        _, counts = np.unique(actions, return_counts=True)
        p = counts / counts.sum()
        return -(p * np.log(p)).sum()

    policy.set_mode_config(1.0, False, 1, 0)   # all exploit
    h_exploit = empirical_entropy(_sample_many(policy, obs_t, mask_t))
    policy.set_mode_config(0.0, False, 1, 0)   # all explore
    h_explore = empirical_entropy(_sample_many(policy, obs_t, mask_t))
    assert h_explore > h_exploit


def test_vanilla_reduction_matches_policy_distribution(model_env):
    model, env = model_env
    policy = model.policy
    obs_t, mask_t = _obs_and_mask(env)
    old_temp, old_eps = policy.exploit_temp, policy.explore_eps
    policy.exploit_temp = 1.0
    try:
        policy.set_mode_config(1.0, False, 1, 0)
        with torch.no_grad():
            dist = policy.get_distribution(obs_t, action_masks=mask_t)
            expected = dist.distribution.probs.numpy()[0]
        actions = _sample_many(policy, obs_t, mask_t, n=6000)
        counts = np.bincount(actions, minlength=len(expected)).astype(np.float64)
        keep = expected > 0.01
        obs_f = counts[keep]
        exp_f = expected[keep].astype(np.float64)
        exp_f = exp_f / exp_f.sum() * obs_f.sum()  # float64: sums match exactly
        from scipy import stats
        _, p = stats.chisquare(obs_f, exp_f)
        assert p > 1e-4
    finally:
        policy.exploit_temp, policy.explore_eps = old_temp, old_eps


def test_mode_resampling_fraction(model_env):
    model, _ = model_env
    policy = model.policy
    policy.set_mode_config(0.7, False, 8, 0)
    samples = []
    for _ in range(3000):
        policy.resample_modes(range(8))
        samples.append(policy.env_modes.mean())
    assert abs(np.mean(samples) - 0.7) < 0.02


def test_per_decision_mode_fraction(model_env):
    """Per-decision granularity re-rolls the mode for every action in a batch."""
    model, _ = model_env
    policy = model.policy
    policy.set_mode_config(0.9, True, 1, 0)   # per-decision, 90% exploit
    modes = np.concatenate([policy._modes_for_batch(1000) for _ in range(30)])
    assert abs(modes.mean() - 0.9) < 0.02


def test_log_prob_is_behavior_log_prob(model_env):
    """The returned log-prob must describe the adjusted (behavior) dist."""
    model, env = model_env
    policy = model.policy
    obs_t, mask_t = _obs_and_mask(env)
    policy.set_mode_config(0.0, False, 1, 0)  # explore: temp+eps adjusted
    with torch.no_grad():
        vanilla = policy.get_distribution(obs_t, action_masks=mask_t)
        for _ in range(20):
            a, _, logp = policy.forward(obs_t, action_masks=mask_t)
            assert torch.isfinite(logp).all()
            # behavior log-prob generally differs from the vanilla policy's
    # sanity: at least sometimes different (adjusted distribution)
    diffs = []
    with torch.no_grad():
        for _ in range(50):
            a, _, logp = policy.forward(obs_t, action_masks=mask_t)
            diffs.append(abs(float(logp) - float(vanilla.log_prob(a))))
    assert max(diffs) > 1e-4
