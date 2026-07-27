"""RL env integration tests for the Upgrade Disk action space and observation (chunk 3).

Pins observable behaviour: mask legality, phase transitions, observation round-trips,
and crash-free random rollouts with the new INSERT_DISK / CHOOSE_UPGRADE actions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.env import actions as A
from blueprince_sim.env import obs as O
from blueprince_sim.env.blueprince_env import BluePrinceEnv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game_at_security(seed: int = 0) -> Game:
    """Fresh game with the player positioned inside the Security room (disk_reader=True)."""
    g = Game(GameConfig(special_items=True), seed=seed)
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)
    g.state.pos = 7
    g.state.entered[7] = True
    return g


def _grant_disk(game: Game, disk_id: str = "upgrade_disk_vault_304") -> None:
    """Add one upgrade disk to the game's inventory."""
    si.grant(game.state, game.registry, disk_id, source="test")


def _space(game: Game):
    """Build the declared observation space for ``game``."""
    return O.observation_space(
        len(game.registry.rooms),
        len(game.registry.special.items),
        len(game.registry.special.fabrication),
    )


def _mask(game: Game) -> list[bool]:
    return A.action_mask(game)


# ---------------------------------------------------------------------------
# INSERT_DISK mask legality
# ---------------------------------------------------------------------------

def test_insert_disk_masked_on_at_disk_reader_with_disk():
    """INSERT_DISK is legal exactly when NAVIGATE + disk_reader room + disk held.

    Confirms the mask enables action 275 only when all three preconditions hold,
    so the agent can rely on this bit to know when insertion is possible.
    """
    g = _game_at_security()
    _grant_disk(g)
    mask = _mask(g)
    assert mask[A.INSERT_DISK_ACTION], "should be legal: at disk reader, holding a disk"


def test_insert_disk_not_masked_without_disk():
    """INSERT_DISK is masked off when no upgrade disk is held.

    Protects against phantom insert actions when the player visits Security empty-handed.
    """
    g = _game_at_security()
    # no disk granted
    mask = _mask(g)
    assert not mask[A.INSERT_DISK_ACTION], "no disk in inventory; INSERT_DISK must be off"


def test_insert_disk_not_masked_at_entrance_hall():
    """INSERT_DISK is masked off at the Entrance Hall (not a disk-reader room).

    The Entrance Hall is the default starting position; this confirms that
    room position, not just disk possession, is gating the action.
    """
    g = Game(GameConfig(special_items=True), seed=0)
    _grant_disk(g)
    # Player is at Entrance Hall (no disk_reader)
    mask = _mask(g)
    assert not mask[A.INSERT_DISK_ACTION], "Entrance Hall has no disk reader; action must be off"


# ---------------------------------------------------------------------------
# INSERT_DISK phase transition
# ---------------------------------------------------------------------------

def test_insert_disk_action_transitions_to_upgrade_pending():
    """Applying INSERT_DISK moves the game into UPGRADE_PENDING phase.

    The phase transition is the gate that enables the CHOOSE_UPGRADE actions;
    if it doesn't fire, the agent is stuck in NAVIGATE with no valid disk choices.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    assert g.phase is Phase.UPGRADE_PENDING


def test_upgrade_pending_mask_has_exactly_three_legal_actions():
    """In UPGRADE_PENDING the mask enables exactly the three CHOOSE_UPGRADE slots.

    A masked-PPO agent crashes on an all-zero mask; exactly three actions must
    always be available when the phase is UPGRADE_PENDING.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    assert g.phase is Phase.UPGRADE_PENDING
    mask = _mask(g)
    legal = [i for i, m in enumerate(mask) if m]
    assert len(legal) == 3
    for action in legal:
        assert A.CHOOSE_UPGRADE_BASE <= action < A.CHOOSE_UPGRADE_BASE + 3, (
            f"unexpected legal action {action} in UPGRADE_PENDING"
        )


def test_upgrade_pending_mask_never_all_zero():
    """The mask in UPGRADE_PENDING is never all-False across multiple seeds.

    A masked-PPO agent with an all-zero mask crashes. Since exactly 3 options
    are always offered, this is a structural guarantee — but we confirm it here
    across seeds so a data-driven edge case cannot silence three variants.
    """
    for seed in range(5):
        g = _game_at_security(seed=seed)
        _grant_disk(g)
        inserted = g.insert_disk()
        if not inserted:
            continue  # no selectable slot this seed; skip
        mask = _mask(g)
        assert any(mask), f"all-zero mask in UPGRADE_PENDING at seed {seed}"


# ---------------------------------------------------------------------------
# CHOOSE_UPGRADE: applies upgrade and returns to NAVIGATE
# ---------------------------------------------------------------------------

def test_choose_upgrade_returns_to_navigate():
    """Applying a CHOOSE_UPGRADE action returns the game to NAVIGATE phase.

    The agent must return to normal navigation after choosing; UPGRADE_PENDING
    is a modal sub-phase, not a permanent state.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    assert g.phase is Phase.UPGRADE_PENDING
    A.apply_action(g, A.CHOOSE_UPGRADE_BASE)  # choose slot 0
    assert g.phase is Phase.NAVIGATE


def test_choose_upgrade_applies_variant_to_applied_upgrades():
    """Choosing an upgrade adds its variant id to state.applied_upgrades.

    applied_upgrades is the persistent record of all chosen disk upgrades; the
    variant chosen here must appear in it so subsequent disk draws exclude it.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    offered = g.state.pending_upgrade_options
    A.apply_action(g, A.CHOOSE_UPGRADE_BASE)  # choose slot 0
    assert offered[0] in g.state.applied_upgrades, (
        "chosen variant must be recorded in applied_upgrades"
    )


def test_navigate_mask_after_choose_upgrade_has_no_choose_upgrade_bits():
    """After choosing, the mask returned to NAVIGATE has no CHOOSE_UPGRADE bits set.

    Ensures the UPGRADE_PENDING-only branch does not leak into NAVIGATE.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    A.apply_action(g, A.CHOOSE_UPGRADE_BASE)
    assert g.phase is Phase.NAVIGATE
    mask = _mask(g)
    for i in range(3):
        assert not mask[A.CHOOSE_UPGRADE_BASE + i], (
            f"CHOOSE_UPGRADE_BASE+{i} must be off in NAVIGATE"
        )


# ---------------------------------------------------------------------------
# Observation round-trips
# ---------------------------------------------------------------------------

def test_upgrade_options_all_minus_one_outside_upgrade():
    """upgrade_options is [-1, -1, -1] when no upgrade selection is pending.

    The sentinel must hold at game start and in normal NAVIGATE / DRAFTING
    so the agent only sees live choices during the actual selection phase.
    """
    g = _game_at_security()
    obs = O.encode(g)
    assert list(obs["upgrade_options"]) == [-1, -1, -1]


def test_upgrade_options_has_three_distinct_nonneg_entries_while_pending():
    """upgrade_options holds three distinct non-negative room indices+1 in UPGRADE_PENDING.

    Each slot must identify a real room (idx+1 >= 1) and all three must differ,
    because the engine always offers three distinct upgrade variants.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    assert g.phase is Phase.UPGRADE_PENDING
    obs = O.encode(g)
    opts = list(obs["upgrade_options"])
    assert all(v >= 1 for v in opts), f"all entries must be >= 1 (room idx+1); got {opts}"
    assert len(set(opts)) == 3, f"all three entries must be distinct; got {opts}"


def test_upgrade_options_clears_after_choose():
    """upgrade_options resets to [-1, -1, -1] after the upgrade choice is made.

    Confirms the sentinel is restored in the next NAVIGATE encode so the
    agent sees a clean slate after the selection.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    A.apply_action(g, A.CHOOSE_UPGRADE_BASE)
    obs = O.encode(g)
    assert list(obs["upgrade_options"]) == [-1, -1, -1]


def test_disks_held_zero_without_disk():
    """disks_held is 0 at game start when no upgrade disk is in inventory."""
    g = _game_at_security()
    obs = O.encode(g)
    assert obs["disks_held"] == 0


def test_disks_held_increments_after_grant():
    """disks_held reflects the actual count of upgrade_disk_* items held.

    The agent uses disks_held to decide whether to head toward a disk reader;
    it must match the real inventory count up to the observation cap.
    """
    g = _game_at_security()
    _grant_disk(g, "upgrade_disk_vault_304")
    obs = O.encode(g)
    assert obs["disks_held"] == 1


def test_disks_held_decrements_after_insert():
    """disks_held drops by 1 after insert_disk() consumes the disk.

    The disk is consumed during insertion; the immediately-next encode must
    show one fewer disk so the agent knows it is out of insertable disks.
    """
    g = _game_at_security()
    _grant_disk(g)
    obs_before = O.encode(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    obs_after = O.encode(g)
    assert obs_after["disks_held"] == obs_before["disks_held"] - 1


def test_obs_contained_in_space_at_upgrade_pending():
    """The observation emitted in UPGRADE_PENDING fits the declared space.

    This catches the Discrete(3)->Discrete(4) phase mismatch and any
    upgrade_options bound violations in one space.contains() call.
    """
    g = _game_at_security()
    _grant_disk(g)
    A.apply_action(g, A.INSERT_DISK_ACTION)
    assert g.phase is Phase.UPGRADE_PENDING
    space = _space(g)
    obs = O.encode(g)
    assert space.contains(obs), "UPGRADE_PENDING observation must lie within declared space"


def test_obs_contained_in_space_throughout_upgrade_cycle():
    """Every observation across the full insert->choose cycle fits the declared space.

    Covers NAVIGATE (before and after), UPGRADE_PENDING, and the NAVIGATE
    return, so no transient state slips outside the declared bounds.
    """
    g = _game_at_security()
    _grant_disk(g)
    space = _space(g)

    obs = O.encode(g)
    assert space.contains(obs), "pre-insert NAVIGATE obs out of space"

    A.apply_action(g, A.INSERT_DISK_ACTION)
    obs = O.encode(g)
    assert space.contains(obs), "UPGRADE_PENDING obs out of space"

    A.apply_action(g, A.CHOOSE_UPGRADE_BASE)
    obs = O.encode(g)
    assert space.contains(obs), "post-choose NAVIGATE obs out of space"


# ---------------------------------------------------------------------------
# Env-level integration: through BluePrinceEnv.step()
# ---------------------------------------------------------------------------

def _env_at_security_with_disk(seed: int = 0) -> BluePrinceEnv:
    """Create a BluePrinceEnv whose underlying game is already positioned at Security
    with one upgrade disk in inventory.

    Bypasses the action sequence needed to reach Security, letting tests focus
    on the disk mechanics rather than navigation.
    """
    env = BluePrinceEnv(GameConfig(special_items=True))
    env.reset(seed=seed)
    g = env.game
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)
    g.state.pos = 7
    g.state.entered[7] = True
    _grant_disk(g)
    return env


def test_env_insert_disk_transitions_to_upgrade_pending():
    """env.step(INSERT_DISK) puts the game in UPGRADE_PENDING with 3 legal choices.

    End-to-end: the action goes through the env's illegal-action guard, apply_action,
    and the mask reported next must reflect UPGRADE_PENDING semantics.
    """
    env = _env_at_security_with_disk()
    obs, reward, term, trunc, info = env.step(A.INSERT_DISK_ACTION)
    assert env.game.phase is Phase.UPGRADE_PENDING
    mask = env.action_masks()
    legal = [i for i, m in enumerate(mask) if m]
    assert len(legal) == 3
    assert all(A.CHOOSE_UPGRADE_BASE <= a < A.CHOOSE_UPGRADE_BASE + 3 for a in legal)


def test_env_choose_upgrade_returns_to_navigate():
    """env.step(CHOOSE_UPGRADE_BASE) after inserting a disk returns to NAVIGATE.

    The env must emit a coherent NAVIGATE-phase observation and allow normal
    navigation actions on the following step.
    """
    env = _env_at_security_with_disk()
    env.step(A.INSERT_DISK_ACTION)
    obs, reward, term, trunc, info = env.step(A.CHOOSE_UPGRADE_BASE)
    assert env.game.phase is Phase.NAVIGATE
    assert env.observation_space.contains(obs)


# ---------------------------------------------------------------------------
# Random masked rollout — crash-free safety net
# ---------------------------------------------------------------------------

def test_random_masked_rollout_never_crashes_or_selects_illegal_action():
    """A random masked rollout over 10 seeds never selects an illegal action or crashes.

    Samples uniformly from the legal mask at each step, so the INSERT_DISK and
    CHOOSE_UPGRADE paths are exercised whenever they appear in the mask.
    Pins the structural invariant: the mask is always non-empty.
    """
    rng = np.random.default_rng(42)
    for seed in range(10):
        env = BluePrinceEnv(GameConfig(special_items=True))
        obs, info = env.reset(seed=seed)
        assert env.observation_space.contains(obs)
        for _step in range(300):
            mask = env.action_masks()
            legal = np.flatnonzero(mask)
            assert len(legal) > 0, (
                f"seed {seed}: all-zero mask in phase {env.game.phase.name}"
            )
            action = int(rng.choice(legal))
            obs, reward, term, trunc, info = env.step(action)
            assert env.observation_space.contains(obs)
            if term or trunc:
                break


def test_insert_disk_is_offered_inside_the_shelter() -> None:
    """The Shelter is a disk reader too, so its insert action must be maskable.

    Shelter is the one terminal that lives in the outer-room abstraction rather
    than on the 5x9 grid, so a mask that only handles on-grid rooms silently
    strands it and the agent can never spend a disk there.
    """
    g = Game(GameConfig(outer_rooms_unlocked=True, special_items=True), seed=0)
    g.placed_ids.add("shelter")
    g.state.outer_loc = 2  # standing inside the outer room
    si.grant(g.state, g.registry, "upgrade_disk_vault_304", source="test")

    assert g.can_insert_disk(), "engine must consider the Shelter a disk reader"
    assert A.action_mask(g)[A.INSERT_DISK_ACTION], \
        "the mask must offer the action wherever the engine allows it"
