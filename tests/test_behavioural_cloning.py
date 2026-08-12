"""Behavioural-cloning warm start: demo loading/replay (no torch) and pretraining (torch).

Uses ``rl.behavioral_cloning.synthetic_demo_records`` throughout instead of a
checked-in ``demos.jsonl`` fixture: no real human demo file exists anywhere in
this repo yet (the Play tab that records them ships, but nobody has played
and saved a session), so a seeded uniform-random masked policy stands in as
the fixture generator for both the loader tests and the BC training tests.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from blueprince_sim.env import actions as A
from blueprince_sim.rl.behavioral_cloning import (
    MixedPresetError,
    ReplayDivergenceError,
    StaleDemoError,
    collate,
    config_for_record,
    load_demo_dataset,
    normalize_unlocks,
    replay_dataset,
    replay_demo,
    synthetic_demo_records,
)

# --------------------------------------------------------------------------
# normalize_unlocks / synthetic fixtures
# --------------------------------------------------------------------------


def test_normalize_unlocks_treats_none_and_fresh_as_equivalent():
    """The trainer spells fresh-save as 'none', the Play tab as 'fresh';
    web/replay.py already treats both as the same preset, so this loader must too."""
    assert normalize_unlocks("none") == normalize_unlocks("fresh") == "fresh"
    assert normalize_unlocks("all") == "all"
    assert normalize_unlocks("anything-else") == "all"


def test_synthetic_demo_records_match_play_session_schema():
    """Generated fixtures carry every field PlaySession._close_day writes,
    so the loader is exercised against the real producer's schema, not a stub."""
    records = synthetic_demo_records("all", "shaped", n_days=2, seed=1, action_rng_seed=0)
    assert len(records) == 2
    for i, rec in enumerate(records, start=1):
        for key in ("episode", "seed", "reward", "actions", "modes", "win",
                    "deepest_rank", "rooms_placed", "reason", "n_actions",
                    "why", "unlocks", "day_config"):
            assert key in rec
        assert rec["episode"] == i
        assert rec["n_actions"] == A.N_ACTIONS
        assert len(rec["modes"]) == len(rec["actions"])
        assert all(a >= 0 for a in rec["actions"])


def test_synthetic_demo_records_without_chain_omit_day_config():
    """Single-day mode (no DayChain, matching the trainer's multi_day=0 path)
    must omit day_config entirely, mirroring EpisodeRecorder's single-day records."""
    records = synthetic_demo_records("all", "shaped", n_days=1, seed=2,
                                     action_rng_seed=0, use_chain=False)
    assert len(records) == 1
    assert "day_config" not in records[0]


# --------------------------------------------------------------------------
# load_demo_dataset
# --------------------------------------------------------------------------


def _write_jsonl(path, records):
    with path.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_load_demo_dataset_filters_to_the_requested_preset(tmp_path):
    """Passing unlocks= keeps only matching records and silently drops the
    rest -- the deliberate "pick one preset" behaviour the brief calls for."""
    all_recs = synthetic_demo_records("all", "shaped", n_days=1, seed=3, action_rng_seed=0)
    fresh_recs = synthetic_demo_records("fresh", "shaped", n_days=1, seed=4, action_rng_seed=0)
    demo_file = tmp_path / "demos.jsonl"
    _write_jsonl(demo_file, all_recs + fresh_recs)

    loaded_all = load_demo_dataset([demo_file], n_actions=A.N_ACTIONS, unlocks="all")
    loaded_fresh = load_demo_dataset([demo_file], n_actions=A.N_ACTIONS, unlocks="none")
    assert len(loaded_all) == len(all_recs)
    assert len(loaded_fresh) == len(fresh_recs)


def test_load_demo_dataset_rejects_mixed_presets_without_explicit_filter(tmp_path):
    """With no unlocks= given, a set spanning both presets must raise rather
    than silently pick one: day_config only reconstructs against its own base."""
    all_recs = synthetic_demo_records("all", "shaped", n_days=1, seed=5, action_rng_seed=0)
    fresh_recs = synthetic_demo_records("fresh", "shaped", n_days=1, seed=6, action_rng_seed=0)
    demo_file = tmp_path / "demos.jsonl"
    _write_jsonl(demo_file, all_recs + fresh_recs)

    with pytest.raises(MixedPresetError):
        load_demo_dataset([demo_file], n_actions=A.N_ACTIONS)


def test_load_demo_dataset_rejects_stale_n_actions(tmp_path):
    """A demo recorded against a different action-space size must be refused
    loudly (action ids are positional and would be silently reinterpreted)."""
    records = synthetic_demo_records("all", "shaped", n_days=1, seed=7, action_rng_seed=0)
    records[0]["n_actions"] = A.N_ACTIONS + 1  # simulate a stale record
    demo_file = tmp_path / "demos.jsonl"
    _write_jsonl(demo_file, records)

    with pytest.raises(StaleDemoError):
        load_demo_dataset([demo_file], n_actions=A.N_ACTIONS)


def test_load_demo_dataset_reads_a_directory_of_jsonl_files(tmp_path):
    """Directories are expanded to their *.jsonl children, matching a
    per-session demos folder layout rather than requiring one merged file."""
    recs_a = synthetic_demo_records("all", "shaped", n_days=1, seed=8, action_rng_seed=0)
    recs_b = synthetic_demo_records("all", "shaped", n_days=1, seed=9, action_rng_seed=0)
    _write_jsonl(tmp_path / "session_a.jsonl", recs_a)
    _write_jsonl(tmp_path / "session_b.jsonl", recs_b)

    loaded = load_demo_dataset([tmp_path], n_actions=A.N_ACTIONS, unlocks="all")
    assert len(loaded) == len(recs_a) + len(recs_b)


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------


def test_replay_demo_reproduces_the_recorded_action_sequence():
    """Replaying a demo yields one triple per recorded action, in order, with
    the SAME action ids -- the round trip the loader promises before any
    training happens."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=10,
                                    action_rng_seed=0, use_chain=False)[0]
    triples = replay_demo(record)
    assert [a for _obs, a, _mask in triples] == record["actions"]


def test_replay_demo_triples_are_legal_under_their_own_mask():
    """Every replayed triple's action is within its own action_masks() result
    -- this is what a masked BC loss assumes and what a real PlaySession/
    EpisodeRecorder-sourced action always satisfies by construction."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=11,
                                    action_rng_seed=0, use_chain=False)[0]
    triples = replay_demo(record)
    assert triples  # the fixture actually produced some actions
    for _obs, action, mask in triples:
        assert mask[action]


def test_replay_multiday_record_reconstructs_the_correct_day_index():
    """day_config is captured as an ABSOLUTE diff against the chain's base
    config (not incremental), so a later day's record must be independently
    replayable without first replaying earlier days -- config_for_record must
    reproduce the true day index on its own."""
    records = synthetic_demo_records("all", "shaped", n_days=3, seed=12, action_rng_seed=1)
    day2_cfg = config_for_record(records[1])
    day3_cfg = config_for_record(records[2])
    assert day2_cfg.day == 2
    assert day3_cfg.day == 3
    # Independently replayable: day 3 alone, without replaying days 1-2 first.
    triples = replay_demo(records[2])
    assert [a for _obs, a, _mask in triples] == records[2]["actions"]


def test_replay_dataset_flattens_across_records():
    """replay_dataset concatenates every record's triples in order, so its
    length is the sum of each day's action count."""
    records = synthetic_demo_records("all", "shaped", n_days=3, seed=13, action_rng_seed=2)
    triples = replay_dataset(records)
    assert len(triples) == sum(len(r["actions"]) for r in records)


def test_replay_demo_raises_on_wrong_preset():
    """Replaying a record under the WRONG unlocks preset can surface as a
    divergence: forcing a fresh-save record through the all-unlocks base
    changes what doors and rooms are legal, so a recorded action may stop
    being legal at replay time.

    Swept over trajectories rather than pinned to one, because divergence is
    NOT guaranteed -- most tampered records replay to the end without any
    recorded action becoming illegal, so a single trajectory asserts only
    which one it happened to draw. Sweeping proves the detector fires at all;
    that it fires rarely is a known gap, recorded in docs/open_tasks.md.
    """
    raised = 0
    for seed in (14, 21, 33):
        for action_rng_seed in range(20):
            record = synthetic_demo_records("fresh", "shaped", n_days=1, seed=seed,
                                            action_rng_seed=action_rng_seed,
                                            use_chain=False)[0]
            assert record["actions"], "a demo with no actions cannot diverge"
            tampered = dict(record, unlocks="all")  # lie about the preset
            try:
                replay_demo(tampered)
            except ReplayDivergenceError:
                raised += 1
    assert raised, "no tampered record diverged; divergence detection is dead"


# --------------------------------------------------------------------------
# collate
# --------------------------------------------------------------------------


def test_collate_stacks_dict_observations_per_key():
    """The observation space is a Dict, so batching must stack each key
    across triples (matching SB3's own vec-env obs stacking) rather than
    flattening the whole observation into one array."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=15,
                                    action_rng_seed=0, use_chain=False)[0]
    triples = replay_demo(record)
    obs_batch, actions, masks = collate(triples)
    n = len(triples)
    assert actions.shape == (n,)
    assert masks.shape == (n, A.N_ACTIONS)
    single_obs = triples[0][0]
    for key, arr in obs_batch.items():
        assert arr.shape == (n, *np.asarray(single_obs[key]).shape)


# --------------------------------------------------------------------------
# pretraining (torch-gated)
# --------------------------------------------------------------------------

torch = pytest.importorskip("torch")
pytest.importorskip("sb3_contrib")

from sb3_contrib import MaskablePPO  # noqa: E402  (import gated by importorskip above)

from blueprince_sim.rl.behavioral_cloning import masked_accuracy, pretrain  # noqa: E402
from blueprince_sim.rl.mixed_policy import MixedExplorationPolicy  # noqa: E402
from blueprince_sim.rl.train import make_single_env  # noqa: E402


def _fresh_bc_model():
    """A tiny untrained MaskablePPO, freshly constructed (never pretrained)."""
    env = make_single_env("shaped", 0)()
    return MaskablePPO(
        MixedExplorationPolicy, env, n_steps=64, batch_size=64, seed=0, device="cpu",
        policy_kwargs={"exploit_temp": 0.5, "explore_temp": 1.5, "explore_eps": 0.05},
    )


@pytest.fixture(scope="module")
def bc_fixture():
    """A tiny untrained MaskablePPO plus a small replayed demo set to overfit.

    Module-scoped: constructing the torch policy is the slow part of these
    tests, so it is built once and reused (mirrors test_mixed_policy.py).

    Only tests that do NOT call ``pretrain()`` on ``model.policy`` (or that
    don't care about starting from an untrained policy) may share this --
    ``pretrain`` mutates the policy's weights in place, so a test asserting
    "before vs. after" needs its own model (see
    ``test_pretrain_raises_agreement_with_demo_actions``), otherwise its
    "before" is silently whatever an EARLIER test in this module already
    trained the shared policy to.
    """
    model = _fresh_bc_model()
    records = synthetic_demo_records("all", "shaped", n_days=1, seed=100,
                                     action_rng_seed=0, use_chain=False)
    triples = replay_dataset(records)
    return model, triples


def test_pretrain_reduces_masked_cross_entropy_loss(bc_fixture):
    """Supervised pretraining on a fixed demo set must drive the training
    loss down over epochs -- the core BC objective actually optimising."""
    model, triples = bc_fixture
    losses = pretrain(model.policy, triples, epochs=25, batch_size=32, lr=1e-3, seed=0)
    assert losses[-1] < losses[0]


def test_pretrain_raises_agreement_with_demo_actions(bc_fixture):
    """After pretraining, the masked-argmax action should agree with the
    demonstrator's action far more often than an untrained (near-uniform)
    policy does -- BC is actually learning the demonstrated behaviour, not
    just reducing a number that doesn't correspond to imitation.

    Uses its own freshly-constructed model rather than ``bc_fixture``'s
    shared one: other tests in this module also call ``pretrain()`` on the
    shared policy, which mutates its weights in place, so reusing it here
    would measure "already-trained vs. trained-more" instead of the
    untrained-vs-trained comparison this test's name promises, and the
    result would depend on module test execution order.
    """
    model = _fresh_bc_model()
    _, triples = bc_fixture
    acc_before = masked_accuracy(model.policy, triples)
    pretrain(model.policy, triples, epochs=40, batch_size=32, lr=1e-3, seed=1)
    acc_after = masked_accuracy(model.policy, triples)
    assert acc_after > acc_before
    # Relative, not an absolute bar: "far more often than untrained" is the
    # claim, and untrained accuracy tracks 1/(legal actions), so any change
    # to the action space moves an absolute threshold without saying
    # anything about whether BC learned.
    assert acc_after > 2 * acc_before


def test_pretrain_epoch_callback_receives_every_epoch(bc_fixture):
    """on_epoch fires once per epoch with a finite loss, in order -- this is
    the hook blueprince-train uses to stream pretrain progress to the dashboard."""
    model, triples = bc_fixture
    seen = []
    pretrain(model.policy, triples, epochs=5, batch_size=32, lr=1e-3, seed=2,
             on_epoch=lambda e, loss: seen.append((e, loss)))
    assert [e for e, _loss in seen] == list(range(5))
    assert all(np.isfinite(loss) for _e, loss in seen)


def test_pretrain_rejects_an_empty_triple_list(bc_fixture):
    """An empty demo set is a caller error (nothing matched --unlocks, e.g.)
    and must raise rather than silently no-op and report a bogus loss curve."""
    model, _triples = bc_fixture
    with pytest.raises(ValueError):
        pretrain(model.policy, [], epochs=1, batch_size=32, lr=1e-3)


def test_masked_illegal_actions_get_no_probability_mass(bc_fixture):
    """The masked action distribution must assign exactly zero probability to
    illegal actions both before and after BC pretraining -- this is what
    lets the BC loss and PPO's own rollout objective use the same masking
    path safely."""
    model, triples = bc_fixture
    obs_batch, _actions, masks = collate(triples[:8])
    obs_t, _ = model.policy.obs_to_tensor(obs_batch)
    masks_t = torch.as_tensor(masks)
    with torch.no_grad():
        dist = model.policy.get_distribution(obs_t, action_masks=masks_t)
        probs = dist.distribution.probs.numpy()
    illegal = ~masks
    assert probs[illegal].max() == 0.0
