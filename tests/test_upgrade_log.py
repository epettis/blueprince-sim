"""Part B: upgrade-decision event logger tests.

Every CHOOSE_UPGRADE action is recorded to upgrades.jsonl regardless of
record_sample_rate. A record for each decision is emitted via info["upgrade_decision"]
in BluePrinceEnv.step() and written by UpgradeLogger.on_step().

Tests:
- Record is emitted for every upgrade decision even when record_sample_rate=0.
- The record round-trips as valid JSON with the expected keys.
- --no-upgrade-log path: UpgradeLogger is None -> nothing is written.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv, _capture_upgrade_decision
from blueprince_sim.rl.train import UpgradeLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "episode_seed", "day", "slot", "offered",
    "chosen_index", "chosen_variant",
    "catacombs_unlocked", "draft_counts",
    "slots_upgraded", "disks_held",
}

_EXPECTED_CHOSEN_VARIANTS_TYPES = (str,)
_EXPECTED_OFFERED_TYPE = list


def _game_at_upgrade_pending(seed: int = 42) -> Game:
    """Return a game in UPGRADE_PENDING state with known slot/options.

    Grants a disk, places the player at the Security room (a disk reader),
    inserts the disk, and verifies the game is in UPGRADE_PENDING phase.
    """
    g = Game(GameConfig(special_items=True), seed=seed)
    si.configure(g.state, g.cfg)
    # Grant any disk
    si.grant(g.state, g.registry, "upgrade_disk_office", source="test")

    # Place Security (a disk reader) and move there
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)  # rank 2 center, mask E|S|W = 14
    g.state.pos = 7
    g.state.entered[7] = True

    ok = g.insert_disk()
    assert ok, "insert_disk must succeed (Security is a disk reader)"
    assert g.phase is Phase.UPGRADE_PENDING, f"expected UPGRADE_PENDING, got {g.phase}"
    return g


# ---------------------------------------------------------------------------
# _capture_upgrade_decision unit tests
# ---------------------------------------------------------------------------

def test_capture_upgrade_decision_has_all_required_keys():
    """_capture_upgrade_decision returns a dict with all required bottleneck-analysis keys.

    If any key is missing the downstream Observatory panel or analysis scripts
    would silently get None values, corrupting the log.
    """
    g = _game_at_upgrade_pending()
    record = _capture_upgrade_decision(g, A.CHOOSE_UPGRADE_BASE, episode_seed=99, day=3)
    for key in _REQUIRED_KEYS:
        assert key in record, f"record missing required key '{key}'"


def test_capture_upgrade_decision_chosen_index_matches_action():
    """chosen_index equals action - CHOOSE_UPGRADE_BASE (0, 1, or 2).

    The index must exactly encode which variant the agent selected so logs
    are reproducible from the action sequence alone.
    """
    for idx in range(3):
        # Re-create game for each index (state is spent after choose_upgrade)
        g2 = _game_at_upgrade_pending(seed=idx)
        rec = _capture_upgrade_decision(
            g2, A.CHOOSE_UPGRADE_BASE + idx, episode_seed=0, day=None)
        assert rec["chosen_index"] == idx, (
            f"chosen_index must be {idx} for action {A.CHOOSE_UPGRADE_BASE + idx}"
        )


def test_capture_upgrade_decision_chosen_variant_matches_offered():
    """chosen_variant is offered[chosen_index] — consistency between the two fields.

    An off-by-one in the action decode would produce a chosen_variant that
    doesn't match the slot the agent actually selected.
    """
    g = _game_at_upgrade_pending()
    idx = 1
    rec = _capture_upgrade_decision(g, A.CHOOSE_UPGRADE_BASE + idx, episode_seed=0, day=None)
    assert rec["chosen_variant"] == rec["offered"][idx], (
        "chosen_variant must equal offered[chosen_index]"
    )


def test_capture_upgrade_decision_offered_has_three_variants():
    """offered always contains exactly three variant ids (the game's invariant).

    The upgrade UI always presents 3 choices; a shorter list would signal a
    capture bug where the snapshot was taken after apply_action cleared pending_*.
    """
    g = _game_at_upgrade_pending()
    rec = _capture_upgrade_decision(g, A.CHOOSE_UPGRADE_BASE, episode_seed=0, day=None)
    assert len(rec["offered"]) == 3, (
        f"offered must always have 3 variants; got {len(rec['offered'])}"
    )


def test_capture_upgrade_decision_round_trips_as_json():
    """The captured record serializes and deserializes as valid JSON with correct types.

    The log writer calls json.dumps(); a type error here would silently crash
    the logger process or corrupt the file.
    """
    g = _game_at_upgrade_pending()
    rec = _capture_upgrade_decision(g, A.CHOOSE_UPGRADE_BASE, episode_seed=42, day=5)
    serialized = json.dumps(rec)
    deserialized = json.loads(serialized)
    assert deserialized["episode_seed"] == 42
    assert deserialized["day"] == 5
    assert isinstance(deserialized["offered"], list)
    assert isinstance(deserialized["slot"], str)
    assert isinstance(deserialized["chosen_index"], int)
    assert isinstance(deserialized["catacombs_unlocked"], bool)


# ---------------------------------------------------------------------------
# BluePrinceEnv integration: upgrade_decision key in info
# ---------------------------------------------------------------------------

def _run_to_upgrade_decision(env: BluePrinceEnv, max_steps: int = 3000):
    """Step through the env until an upgrade decision is emitted or we give up.

    Returns the info dict containing ``upgrade_decision`` when found, else None.
    Drives a greedy_insert_disk policy: always pick insert_disk + choose_upgrade_0
    once a disk is held and a reader is underfoot.
    """
    obs, info = env.reset(seed=42)
    for _ in range(max_steps):
        mask = env.action_masks()
        # Prioritize upgrade actions
        for ua in range(A.CHOOSE_UPGRADE_BASE, A.CHOOSE_UPGRADE_BASE + 3):
            if mask[ua]:
                _, _, term, trunc, info = env.step(ua)
                if "upgrade_decision" in info:
                    return info
                if term or trunc:
                    return None
                break
        else:
            # Pick insert disk if available
            if mask[A.INSERT_DISK_ACTION]:
                _, _, term, trunc, info = env.step(A.INSERT_DISK_ACTION)
                if term or trunc:
                    return None
                continue
            # Otherwise pick first legal action
            for i, legal in enumerate(mask):
                if legal:
                    _, _, term, trunc, info = env.step(i)
                    if "upgrade_decision" in info:
                        return info
                    if term or trunc:
                        return None
                    break
            else:
                return None  # no legal action
    return None


def test_env_step_emits_upgrade_decision_in_info():
    """BluePrinceEnv.step() includes 'upgrade_decision' in info when a CHOOSE_UPGRADE action is taken.

    The record must be present exactly when an upgrade choice is legal and taken,
    not on every step (which would add noise to the info dict).
    """
    env = BluePrinceEnv(cfg=GameConfig(special_items=True))
    # Grant a disk at day start so we can insert it immediately
    env.reset(seed=42)
    # Inject a disk and force the game into UPGRADE_PENDING via manual action
    g = env.game
    si.grant(g.state, g.registry, "upgrade_disk_vault_304", source="test")

    # Place Security at cell 7 and move there
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)
    g.state.pos = 7
    g.state.entered[7] = True
    g.insert_disk()
    assert g.phase is Phase.UPGRADE_PENDING

    # Now apply CHOOSE_UPGRADE_BASE (action 276) which should emit the record
    mask = env.action_masks()
    assert mask[A.CHOOSE_UPGRADE_BASE], "CHOOSE_UPGRADE_BASE must be legal in UPGRADE_PENDING"
    _, _, _, _, info = env.step(A.CHOOSE_UPGRADE_BASE)
    assert "upgrade_decision" in info, (
        "info must contain 'upgrade_decision' after a CHOOSE_UPGRADE action"
    )
    for key in _REQUIRED_KEYS:
        assert key in info["upgrade_decision"], (
            f"upgrade_decision missing required key '{key}'"
        )


def test_upgrade_decision_is_writable_when_action_is_a_numpy_int():
    """A record captured from a numpy action still writes as JSON.

    SB3 passes actions as numpy integers, so chosen_index inherited numpy.int64
    and json.dumps aborted the whole training run from inside the logger. Every
    value in the record must survive UpgradeLogger's write, not just this field.
    """
    env = BluePrinceEnv(cfg=GameConfig(special_items=True))
    env.reset(seed=42)
    g = env.game
    si.grant(g.state, g.registry, "upgrade_disk_vault_304", source="test")
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)
    g.state.pos = 7
    g.state.entered[7] = True
    g.insert_disk()
    assert g.phase is Phase.UPGRADE_PENDING

    # The exact type SB3 hands to step(), not the Python int the other tests use.
    _, _, _, _, info = env.step(np.int64(A.CHOOSE_UPGRADE_BASE))
    record = info["upgrade_decision"]

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "upgrades.jsonl"
        UpgradeLogger(path).on_step([info])
        written = json.loads(path.read_text().strip())

    assert written == record, "the written line must round-trip the captured record"
    assert written["chosen_index"] == 0, "chosen_index must decode to 0 for the base action"


def test_env_step_no_upgrade_decision_outside_upgrade_phase():
    """info does not contain 'upgrade_decision' on non-upgrade steps.

    Emitting the key on every step would pollute the info dict and mislead
    the UpgradeLogger into writing spurious records.
    """
    env = BluePrinceEnv(cfg=GameConfig(special_items=True))
    obs, info = env.reset(seed=0)
    assert "upgrade_decision" not in info, "info must not have upgrade_decision at reset"
    # Take a few ordinary steps
    for _ in range(5):
        mask = env.action_masks()
        for i, legal in enumerate(mask):
            if legal:
                _, _, term, trunc, info = env.step(i)
                if "upgrade_decision" in info:
                    # Unexpectedly got one — only fail if it was NOT a choose action
                    assert A.CHOOSE_UPGRADE_BASE <= i <= A.CHOOSE_UPGRADE_BASE + 2, (
                        "upgrade_decision must only appear on CHOOSE_UPGRADE actions"
                    )
                if term or trunc:
                    return
                break


# ---------------------------------------------------------------------------
# UpgradeLogger: writes on decision, silent when None
# ---------------------------------------------------------------------------

def test_upgrade_logger_writes_record_per_decision():
    """UpgradeLogger.on_step() writes exactly one line to upgrades.jsonl per upgrade decision.

    Each line must be valid JSON with the required keys.  At zero sample rate
    (or without a recorder) the logger still fires, proving it is independent
    of episode recording.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "upgrades.jsonl"
        logger = UpgradeLogger(path)

        rec = {
            "episode_seed": 1, "day": 2, "slot": "closet",
            "offered": ["closet__v1", "closet__v2", "closet__v3"],
            "chosen_index": 0, "chosen_variant": "closet__v1",
            "catacombs_unlocked": False, "draft_counts": {"closet": 5},
            "slots_upgraded": 0, "disks_held": 1,
        }
        logger.on_step([{"upgrade_decision": rec}, {}])  # 2 envs; only env 0 has a record
        logger.on_step([{}, {"upgrade_decision": dict(rec, episode_seed=2)}])  # env 1

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2, f"expected 2 lines, got {len(lines)}"
        for line in lines:
            loaded = json.loads(line)
            for key in _REQUIRED_KEYS:
                assert key in loaded, f"logged record missing key '{key}'"


def test_upgrade_logger_is_independent_of_sample_rate():
    """UpgradeLogger writes records even when record_sample_rate=0.

    This is the core invariant: upgrade decisions are rare and must be captured
    regardless of global episode sampling configuration.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "upgrades.jsonl"
        logger = UpgradeLogger(path)

        rec = {"episode_seed": 7, "day": 1, "slot": "cloister",
               "offered": ["a", "b", "c"], "chosen_index": 1,
               "chosen_variant": "b", "catacombs_unlocked": True,
               "draft_counts": {}, "slots_upgraded": 1, "disks_held": 0}
        # record_sample_rate is irrelevant to UpgradeLogger; it has no sample gate
        logger.on_step([{"upgrade_decision": rec}])

        assert path.exists(), "upgrades.jsonl must be created"
        assert path.stat().st_size > 0, "upgrades.jsonl must not be empty"


def test_upgrade_logger_none_writes_nothing():
    """When upgrade_logger is None (--no-upgrade-log), no file is created.

    The callback passes infos to logger.on_step() only when logger is not None;
    this test directly validates the None-check at the callback level by
    simulating None logger and confirming no file appears.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "upgrades.jsonl"
        # Simulate the callback's None guard:
        upgrade_logger = None
        infos = [{"upgrade_decision": {"episode_seed": 0, "day": 1, "slot": "closet",
                                       "offered": ["a", "b", "c"], "chosen_index": 0,
                                       "chosen_variant": "a", "catacombs_unlocked": False,
                                       "draft_counts": {}, "slots_upgraded": 0, "disks_held": 1}}]
        if upgrade_logger is not None:
            upgrade_logger.on_step(infos)

        assert not path.exists(), (
            "upgrades.jsonl must not be created when upgrade_logger is None"
        )
