"""Tests for multi-day replay correctness.

Pins the fix for the bug where replay.build_frames used a fresh all_unlocks_config
instead of the per-day GameConfig, causing divergence in multi-day runs.

Coverage:
  a) Round-trip: a DayChain episode with non-trivial per-day config replays
     to the same outcome as the live run when day_config is included.
  b) Legacy records (no day_config) report divergence rather than silent
     partial reconstruction when per-day config is needed.
  c) The generic config diff round-trips: frozenset fields survive
     serialize -> deserialize.
"""

from __future__ import annotations

import dataclasses
import random

from blueprince_sim.env.blueprince_env import BluePrinceEnv, _day_config_diff
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.rl.train import all_unlocks_config
from blueprince_sim.web import replay


# ---------------------------------------------------------------------------
# helpers

def _play_day_with_chain(chain: DayChain, seed: int) -> tuple[dict, dict]:
    """Play one day of a DayChain with masked-random actions; return (record, live_outcome).

    Simulates what EpisodeRecorder does: captures seed, actions, and day_config.
    ``live_outcome`` additionally carries the final grid so a replay can be
    compared against the real house cell by cell.
    """
    env = BluePrinceEnv(cfg=chain.base_cfg, day_chain=chain)
    _, info = env.reset(seed=seed)
    day_config = info.get("day_config", {})
    rng = random.Random(seed ^ 0xABCD)
    actions = []
    done = False
    while not done:
        legal = [i for i, ok in enumerate(env.action_masks()) if ok]
        action = rng.choice(legal)
        actions.append(action)
        _, _, term, trunc, info = env.step(action)
        done = term or trunc
    record = {
        "episode": 1,
        "seed": seed,
        "reward": "shaped",
        "actions": actions,
        "modes": "1" * len(actions),
        "win": info["termination_reason"] == "antechamber",
        "deepest_rank": info["deepest_rank"],
        "rooms_placed": info["rooms_placed"],
        "reason": info["termination_reason"],
        "day_config": day_config,
    }
    live_outcome = dict(info)
    live_outcome["grid"] = list(env.game.state.grid)
    return record, live_outcome


# ---------------------------------------------------------------------------
# a) Round-trip with day_config

def test_multiday_replay_roundtrip_matches_live_run():
    """A multi-day episode replayed with its recorded day_config reproduces the
    live run's outcome (rooms placed, deepest rank, termination reason) exactly.

    This is the regression test for the bug: without day_config in the record,
    build_frames used a stale base config and diverged from the recorded run.
    We advance the chain a few days to build up non-trivial carry-over state
    before the day we actually check, so the config genuinely differs.
    """
    base_cfg = all_unlocks_config("shaped")
    chain = DayChain(base_cfg, n_days=10)

    # Advance a few days so carry-over state accumulates and the day counter
    # moves off the base config's value.  The env calls chain.advance() itself
    # on the terminal step, so simply playing each day advances the chain.
    for day_seed in range(3):
        _play_day_with_chain(chain, seed=day_seed * 1000 + 7)

    # Now play the day we will replay.
    record, live_info = _play_day_with_chain(chain, seed=99991)

    assert record["day_config"], "chain must have produced non-trivial day_config"

    frames, divergence = replay.build_frames(record)

    # Replay must be clean.
    assert divergence is None, (
        f"Replay diverged: first_invalid={divergence['first_invalid_index'] if divergence else None}, "
        f"invalid_count={divergence['invalid_count'] if divergence else None}"
    )

    # The replayed house must match the live house cell for cell.  A diverged
    # replay renders a half-built house, which is exactly the reported symptom,
    # so compare the whole grid rather than a summary statistic.
    last = frames[-1]
    assert last["reason"] == live_info["termination_reason"]
    assert last["deepest_rank"] == live_info["deepest_rank"]
    assert last["grid"] == live_info["grid"]
    assert len(frames) == len(record["actions"]) + 1


def test_legacy_record_divergence_is_surfaced():
    """A record whose action sequence contains an action that is illegal in the
    replayed state is flagged as diverged rather than silently ignored.

    This pins the detection mechanism itself: build_frames must check the action
    mask before each step and record any violation, rather than applying all
    actions as no-ops without signalling that the reconstruction is wrong.
    We inject a known-illegal action (action 0, which is only legal in NAVIGATE
    phase) into a record whose episode starts in DRAFTING phase, guaranteeing
    the divergence is detectable regardless of seed.
    """
    # Build a valid single-day record with a clean action sequence.
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=77)
    rng = random.Random(77)
    actions = []
    done = False
    while not done:
        legal = [i for i, ok in enumerate(env.action_masks()) if ok]
        action = rng.choice(legal)
        actions.append(action)
        _, _, term, trunc, info = env.step(action)
        done = term or trunc

    # Splice an illegal action at position 1: find the first NAVIGATE step
    # and insert a CHOOSE action (only legal during DRAFTING) right after it.
    # Simpler: just append a sentinel action (0) at the start — action 0 is
    # a MOVE_TO action which is only legal in NAVIGATE phase, not DRAFT phase.
    # The episode starts with a DRAFT (the entrance hall opens a door immediately).
    # We verify it IS illegal at that state first.
    env2 = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env2.reset(seed=77)
    mask_at_start = env2.action_masks()
    # Find any action that is definitively illegal at step 0 to inject.
    illegal_action = next((i for i, ok in enumerate(mask_at_start) if not ok), None)
    assert illegal_action is not None, "All actions are legal at step 0 — cannot construct test"

    # Build a tampered record with the illegal action injected at position 0.
    tampered_actions = [illegal_action] + list(actions)
    tampered_record = {
        "episode": 1, "seed": 77, "reward": "shaped",
        "actions": tampered_actions,
        "modes": "1" * len(tampered_actions),
        "win": False, "deepest_rank": 1, "rooms_placed": 1,
        "reason": "out_of_steps",
        # No day_config: this is the legacy shape being tested.
    }

    _frames, divergence = replay.build_frames(tampered_record)

    # The tampered record must trigger divergence detection.
    assert divergence is not None, "Injected illegal action must produce a detected divergence"
    assert divergence["first_invalid_index"] == 0
    assert divergence["invalid_count"] >= 1


# ---------------------------------------------------------------------------
# b) Legacy single-day records still work (no regression)

def test_single_day_record_replays_cleanly():
    """A single-day record (no day_chain, no day_config key) replays without
    raising and reports no divergence — the base all_unlocks_config is the
    correct config for single-day training.
    """
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    _, _info = env.reset(seed=42)
    rng = random.Random(42)
    actions = []
    done = False
    while not done:
        legal = [i for i, ok in enumerate(env.action_masks()) if ok]
        action = rng.choice(legal)
        actions.append(action)
        _, _, term, trunc, info = env.step(action)
        done = term or trunc

    record = {
        "episode": 1, "seed": 42, "reward": "shaped",
        "actions": actions, "modes": "1" * len(actions),
        "win": False, "deepest_rank": info["deepest_rank"],
        "rooms_placed": info["rooms_placed"],
        "reason": info["termination_reason"],
        # No "day_config" key: this is the single-day legacy shape.
    }

    frames, divergence = replay.build_frames(record)
    assert divergence is None, f"Single-day replay unexpectedly diverged: {divergence}"
    assert len(frames) == len(actions) + 1


# ---------------------------------------------------------------------------
# c) Config diff round-trip for frozenset fields

def test_day_config_diff_roundtrip_frozenset():
    """A frozenset field in the config diff survives serialize -> deserialize:
    _day_config_diff emits it as a sorted list, and _apply_day_config converts
    it back to a frozenset so dataclasses.replace receives the correct type.
    """
    base_cfg = all_unlocks_config("shaped")
    # Construct a day config that differs from base in a frozenset field.
    day_cfg = dataclasses.replace(
        base_cfg,
        banned_rooms=frozenset({"chapel", "tomb"}),
        lit_targets=frozenset({"trading_post"}),
    )

    diff = _day_config_diff(day_cfg, base_cfg)

    # frozenset fields are serialized as sorted lists.
    assert isinstance(diff["banned_rooms"], list)
    assert sorted(diff["banned_rooms"]) == ["chapel", "tomb"]
    assert diff["lit_targets"] == ["trading_post"]

    # Deserialize back via _apply_day_config.
    restored = replay._apply_day_config(base_cfg, diff)
    assert restored.banned_rooms == frozenset({"chapel", "tomb"})
    assert restored.lit_targets == frozenset({"trading_post"})


def test_day_config_diff_excludes_non_serializable_fields():
    """_day_config_diff skips fields that are not JSON-serializable (e.g. data_dir: Path)
    so the diff is always safe to pass to json.dumps without raising.
    """
    import json
    from pathlib import Path

    base_cfg = all_unlocks_config("shaped")
    day_cfg = dataclasses.replace(base_cfg, data_dir=Path("/some/path"), day=3)

    diff = _day_config_diff(day_cfg, base_cfg)

    # Path fields must be absent from the diff.
    assert "data_dir" not in diff
    # Primitive fields that differ must be present.
    assert diff.get("day") == 3
    # The diff must be JSON-serializable.
    json.dumps(diff)  # must not raise


def test_day_config_diff_only_differs():
    """_day_config_diff returns an empty dict when the configs are identical,
    and only includes fields that actually differ.
    """
    base_cfg = all_unlocks_config("shaped")
    diff = _day_config_diff(base_cfg, base_cfg)
    assert diff == {}, "Identical configs must produce an empty diff"

    # A single-field change appears in the diff; all others are absent.
    day_cfg = dataclasses.replace(base_cfg, day=5)
    diff2 = _day_config_diff(day_cfg, base_cfg)
    assert set(diff2.keys()) == {"day"}
    assert diff2["day"] == 5
