"""Behavioural-cloning warm start: demo loading/replay (no torch) and pretraining (torch).

Uses ``rl.behavioral_cloning.synthetic_demo_records`` throughout instead of a
checked-in ``demos.jsonl`` fixture: real demo files (human-played sessions,
via the Play tab) land only under the gitignored ``runs/`` tree, never in the
repo itself, so a seeded uniform-random masked policy stands in as a
reproducible fixture generator for both the loader tests and the BC training
tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from blueprince_sim.config import GameConfig, config_digest
from blueprince_sim.env import actions as A
from blueprince_sim.rl.behavioral_cloning import (
    ConfigDigestError,
    MixedPresetError,
    ReplayDivergenceError,
    StaleDemoError,
    UnstampedDemoError,
    collate,
    config_for_record,
    load_demo_dataset,
    normalize_unlocks,
    replay_dataset,
    replay_demo,
    synthetic_demo_records,
)
from blueprince_sim.web import replay

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


def test_load_demo_dataset_rejects_a_record_missing_the_unlocks_stamp(tmp_path):
    """A record with no 'unlocks' key must be refused loudly rather than
    defaulting to 'all' -- for a legacy fresh-save record, that default IS
    exactly the tampering test_replay_demo_raises_on_wrong_preset simulates."""
    records = synthetic_demo_records("all", "shaped", n_days=1, seed=16, action_rng_seed=0)
    del records[0]["unlocks"]  # simulate a pre-stamp legacy record
    demo_file = tmp_path / "demos.jsonl"
    _write_jsonl(demo_file, records)

    with pytest.raises(UnstampedDemoError):
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


def test_replay_demo_does_not_raise_when_the_last_action_ends_the_day():
    """A genuine record's last recorded action is the one that ends the day
    (PlaySession._close_day/EpisodeRecorder.on_episode_end both append it
    before checking terminated/truncated), so replay reaching Phase.TERMINAL
    with zero actions left over is the NORMAL case and must not raise."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=17,
                                    action_rng_seed=0, use_chain=False)[0]
    triples = replay_demo(record)  # must not raise
    assert len(triples) == len(record["actions"])


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
    """Replaying a record under the WRONG unlocks preset is refused
    deterministically at config reconstruction, before any replay happens:
    config_for_record's digest comparison rejects every tampered record in
    this sweep, by exact type (ConfigDigestError), regardless of whether the
    wrong preset would also have made some recorded action illegal. Swept
    over many trajectories (not pinned to one) to demonstrate this holds
    across the whole population, not just a trajectory that happens to also
    trip the mask-based detector.
    """
    total = 0
    raised = 0
    for seed in (14, 21, 33):
        for action_rng_seed in range(20):
            record = synthetic_demo_records("fresh", "shaped", n_days=1, seed=seed,
                                            action_rng_seed=action_rng_seed,
                                            use_chain=False)[0]
            assert record["actions"], "a demo with no actions cannot diverge"
            tampered = dict(record, unlocks="all")  # lie about the preset
            total += 1
            try:
                replay_demo(tampered)
            except ConfigDigestError:
                raised += 1
    assert raised == total, f"only {raised}/{total} tampered records raised ConfigDigestError"


def test_replay_demo_raises_when_terminal_reached_with_actions_remaining():
    """Reaching Phase.TERMINAL while recorded actions still remain raises
    ReplayDivergenceError (message mentions "terminal state") rather than
    silently truncating the replay -- distinct from the OTHER divergence
    detector in replay_demo (an illegal recorded action; see
    test_replay_demo_raises_on_a_record_with_a_corrupted_action) and from
    config_for_record's digest guard (test_replay_demo_raises_on_wrong_preset,
    which never re-stamps, so ConfigDigestError always fires there first).
    Tested nowhere else.

    Constructed entirely from the CORRECT config (no config_digest re-stamp
    needed -- it already matches), so every real recorded action stays legal
    throughout and the ONLY possible divergence is the one under test. Both
    known record producers append the action that ends the day as the LAST
    list element (replay_demo's own docstring), so a real record's action
    list already stops exactly at its own true terminal step; appending
    padding past that point -- well beyond BluePrinceEnv.max_env_steps
    (1000), the hard per-day truncation bound -- guarantees the replay
    reaches Phase.TERMINAL with actions still queued. Verified deterministic
    across seeds 0-9, not just one pinned seed.
    """
    record = synthetic_demo_records("fresh", "shaped", n_days=1, seed=24,
                                    action_rng_seed=0, use_chain=False)[0]
    assert len(record["actions"]) > 1
    padded = dict(record)
    # Padding value is never actually read: replay_demo checks Phase.TERMINAL
    # before it ever inspects an action, so once terminal fires (guaranteed
    # well before this padding is reached) the padded values are never
    # touched -- their number is what matters, not their content.
    padded["actions"] = list(record["actions"]) + [0] * 2000
    with pytest.raises(ReplayDivergenceError, match="terminal state"):
        replay_demo(padded)


def test_replay_demo_raises_on_a_record_with_a_corrupted_action():
    """The mask-based detector inside replay_demo -- raising
    ReplayDivergenceError when a recorded action is not legal at its
    replayed step -- must still fire on its own, reached via a corrupted
    ``"actions"`` list rather than a wrong ``unlocks``/``config_digest``.

    Both are left correct (the record's own, untouched stamp), so
    config_for_record's digest guard passes and replay proceeds into the
    action loop: the digest guard now sits in front of this detector for
    every replay, so this pins that the mask check underneath it is still
    reachable and still fires, not quietly dead code.
    """
    from blueprince_sim.env.blueprince_env import BluePrinceEnv

    record = synthetic_demo_records("all", "shaped", n_days=1, seed=26,
                                    action_rng_seed=0, use_chain=False)[0]
    env = BluePrinceEnv(cfg=config_for_record(record))
    env.reset(seed=record["seed"])
    mask_at_start = env.action_masks()
    illegal_action = next((i for i, ok in enumerate(mask_at_start) if not ok), None)
    assert illegal_action is not None, "all actions legal at step 0 -- cannot construct test"

    tampered = dict(record, actions=[illegal_action] + list(record["actions"]))
    with pytest.raises(ReplayDivergenceError, match="not legal"):
        replay_demo(tampered)


def test_replay_demo_raises_on_a_record_missing_the_unlocks_stamp():
    """replay_demo goes through config_for_record, which must refuse an
    unstamped record the same way load_demo_dataset does -- a record can
    reach replay directly (e.g. from replay_dataset) without ever passing
    through the loader's own check."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=25,
                                    action_rng_seed=0, use_chain=False)[0]
    del record["unlocks"]  # simulate a pre-stamp legacy record
    with pytest.raises(UnstampedDemoError):
        replay_demo(record)


# --------------------------------------------------------------------------
# config_digest
# --------------------------------------------------------------------------


def test_config_for_record_raises_config_digest_error_on_tampered_unlocks():
    """Replaying a record whose unlocks stamp was tampered with must raise
    ConfigDigestError, by exact type rather than the base DemoError or the
    older ReplayDivergenceError: config_for_record's digest comparison
    catches the wrong reconstruction unconditionally, at reconstruction
    time, rather than only when the wrong config happens to make some
    recorded action illegal.

    Seed 30 is a measured case (seeds 30-59) where a tampered wrong-preset
    replay completes to the end with every recorded action still legal, so a
    config_for_record that computed the digest but never compared it (the
    mutation this test is meant to catch) would let this exact record
    through with no error raised at all -- do not change this seed.
    """
    record = synthetic_demo_records("fresh", "shaped", n_days=1, seed=30,
                                    action_rng_seed=0, use_chain=False)[0]
    tampered = dict(record, unlocks="all")  # lie about the preset
    with pytest.raises(ConfigDigestError):
        replay_demo(tampered)


def test_config_digest_is_stable_across_a_fresh_process():
    """config_digest must never depend on hash(): PYTHONHASHSEED randomises
    str.__hash__ per process, so a digest built from it would differ between
    the process that recorded a demo and the process that later replays it.
    Verified by comparing against a subprocess run under a different, fixed
    PYTHONHASHSEED rather than pinning a literal hex value, which would only
    be a change-detector test."""
    in_process = config_digest(GameConfig())
    code = (
        "from blueprince_sim.config import GameConfig, config_digest\n"
        "print(config_digest(GameConfig()))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ, PYTHONHASHSEED="1"),
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == in_process


def test_config_digest_round_trips_across_a_multiday_chain():
    """config_for_record's reconstructed GameConfig must hash to the exact
    digest its own record was stamped with, independently for every day of a
    multi-day chain, for every dict-typed GameConfig field as well as the
    scalar ones -- nothing here inspects those fields directly, so this only
    holds if config_for_record's diffing reconstructs them correctly too."""
    records = synthetic_demo_records("all", "shaped", n_days=3, seed=40, action_rng_seed=3)
    assert len(records) == 3
    for record in records:
        assert config_digest(config_for_record(record)) == record["config_digest"]


def test_config_digest_ignores_a_field_set_to_its_own_default():
    """A field explicitly set to its own declared default must not change
    the digest, while a genuinely non-default value must: this is what lets
    a new GameConfig field be appended without invalidating every already-
    stamped record, since an old record simply never mentions the new
    field and so is read as its default."""
    base = GameConfig()
    explicit_default = GameConfig(day=base.day)
    non_default = GameConfig(day=base.day + 1)
    assert config_digest(base) == config_digest(explicit_default)
    assert config_digest(base) != config_digest(non_default)


def test_config_for_record_raises_on_a_record_missing_config_digest():
    """A record with no config_digest key must be refused outright rather
    than silently trusting an unverifiable reconstruction -- same refuse-
    don't-guess precedent as UnstampedDemoError for a missing 'unlocks'."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=41,
                                    action_rng_seed=0, use_chain=False)[0]
    del record["config_digest"]  # simulate a pre-stamp legacy record
    with pytest.raises(ConfigDigestError):
        config_for_record(record)


def test_build_frames_flags_a_config_digest_mismatch_without_raising():
    """web/replay.py::build_frames must surface a config_digest mismatch as
    an advisory divergence flag and keep returning frames, never raise --
    unlike config_for_record's refusal, a raise here would turn an
    unviewable historical run into a 500 in the replay UI instead of a
    rendered warning."""
    record = synthetic_demo_records("all", "shaped", n_days=1, seed=42,
                                    action_rng_seed=0, use_chain=False)[0]
    tampered = dict(record, config_digest="deadbeefdeadbeef")
    frames, divergence = replay.build_frames(tampered)
    assert frames
    assert divergence is not None
    assert divergence["config_digest_mismatch"] is True


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
    demonstrator's action far more often than chance -- BC is actually
    learning the demonstrated behaviour, not just reducing a number that
    doesn't correspond to imitation.

    "Chance" here is the mean, over triples, of 1/n_legal (n_legal being the
    number of legal actions under that triple's own mask): the expected
    agreement rate of a policy that answers uniformly at random among the
    legal actions at each step. That is exactly how synthetic_demo_records()
    itself picks the demonstrated action (``rng.choice(np.flatnonzero(mask))``),
    so this is not merely an analogy for "untrained, near-uniform policy" --
    it is the demonstrator-matching probability such a policy would achieve
    against THIS fixture, computed from the triples' masks alone. Unlike a
    multiple of acc_before, it does not depend on the policy network's
    architecture or weight initialisation, so it stays valid as the action
    space grows.

    The 1.5x margin comes from a 15-way sweep (5 policy weight-init seeds x
    3 pretrain seeds) against this exact fixture's triples, which measured
    acc_after/chance ratios of 2.25-2.96 (mean ~2.53); 1.5x sits comfortably
    below the observed minimum without being an inflated, arbitrary bar.

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

    # Chance baseline derived from the data (the triples' own masks), not
    # from an untrained model's weights: see the docstring above for why
    # this is exactly the near-uniform-policy agreement rate for THIS
    # fixture, and thus invariant to architecture/init/action-space width.
    n_legal = np.array([mask.sum() for _obs, _action, mask in triples])
    chance = float(np.mean(1.0 / n_legal))
    assert acc_after > 1.5 * chance


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
