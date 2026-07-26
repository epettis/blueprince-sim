"""Security-setpoint repeat guard: env mask and _prev_action tracking.

Covers the guard that prevents a policy from thrashing security level setpoints
back-and-forth for free (a run with seed 1099560591 spent hundreds of actions
doing exactly this).  The guard lives in action_mask(prev_action=...) and is
threaded through BluePrinceEnv._prev_action.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_OPEN, segment_key
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv


# ------------------------------------------------------------------ helpers


def _game_in_security(registry) -> Game:
    """Return a Game with the player standing inside the Security room.

    Security is placed at cell 7 (rank-2 center), and the entrance's north
    doorway is forced open so the player can walk in.  door_locks is on so the
    setpoint actions are meaningful.
    """
    g = Game(GameConfig(door_locks=True), seed=1, registry=registry)
    sec = registry.by_id["security"]
    g._place_room(sec, 7, sec.door_mask)
    # Force the N doorway of the entrance open so the walk is legal.
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.move_to(7)
    assert g.can_set_security_level(), "setup: player must be inside Security"
    return g


def _env_in_security(registry) -> BluePrinceEnv:
    """Env wrapper around the same setup; reuses the already-loaded registry."""
    cfg = GameConfig(door_locks=True)
    env = BluePrinceEnv(cfg=cfg)
    sec = registry.by_id["security"]
    env.game._place_room(sec, 7, sec.door_mask)
    env.game.state.door_state[segment_key(2, N)] = DOOR_OPEN
    env.game.state.door_version += 1
    env.game.move_to(7)
    return env


# ------------------------------------------------ action_mask back-compat


def test_action_mask_no_prev_is_unchanged(registry):
    """action_mask() with no prev_action argument is backward-compatible:
    the setpoint actions are legal while standing in Security (unchanged)."""
    g = _game_in_security(registry)
    mask = A.action_mask(g)  # no prev_action kwarg
    set_ids = [A.SET_LEVEL_BASE + i for i in range(3)]
    # At least two of the three levels must be legal (the current level is a
    # no-op and is masked out by the regular logic, but the others are open).
    assert sum(mask[i] for i in set_ids) >= 2


def test_action_mask_prev_non_setpoint_does_not_block(registry):
    """prev_action pointing to a non-setpoint action does not suppress the
    setpoint ids: the guard only fires on SET_LEVEL_BASE..+2."""
    g = _game_in_security(registry)
    # Use TOGGLE_POWER_ACTION as an arbitrary non-setpoint previous action.
    mask = A.action_mask(g, prev_action=A.TOGGLE_POWER_ACTION)
    set_ids = [A.SET_LEVEL_BASE + i for i in range(3)]
    assert sum(mask[i] for i in set_ids) >= 2


# ------------------------------------------------- guard: pure action_mask


def test_action_mask_prev_setpoint_blocks_all_three(registry):
    """After a set-level action (prev_action in SET_LEVEL_BASE..+2), all three
    setpoint ids are forced False regardless of current security level, while
    other actions the position warrants remain legal (frontier drafts are open)."""
    g = _game_in_security(registry)
    for prev in range(A.SET_LEVEL_BASE, A.SET_LEVEL_BASE + 3):
        mask = A.action_mask(g, prev_action=prev)
        for i in range(3):
            assert not mask[A.SET_LEVEL_BASE + i], \
                f"SET_LEVEL_BASE+{i} should be blocked when prev={prev}"
        # Frontier drafts from the entrance are still reachable; confirm at
        # least one action other than setpoints is legal.
        assert any(mask[i] for i in range(A.N_ACTIONS) if i < A.SET_LEVEL_BASE
                   or i >= A.SET_LEVEL_BASE + 3)


def test_action_mask_prev_setpoint_guard_released_after_other_action(registry):
    """After a non-setpoint prev_action the setpoint ids are legal again: the
    guard lasts exactly one action, not the whole episode."""
    g = _game_in_security(registry)
    # First confirm the guard fires.
    mask_blocked = A.action_mask(g, prev_action=A.SET_LEVEL_BASE)
    assert not any(mask_blocked[A.SET_LEVEL_BASE + i] for i in range(3))
    # Now "take" a non-setpoint action (we pass any non-set-level id).
    mask_free = A.action_mask(g, prev_action=A.MOVE_TO_BASE + 2)  # e.g. go-to entrance
    assert sum(mask_free[A.SET_LEVEL_BASE + i] for i in range(3)) >= 2


# ------------------------------------------------- guard: env integration


def test_env_setpoint_step_activates_guard(registry):
    """Stepping a set-level action through the env masks all three setpoint ids
    on the very next action_masks() call, while other actions remain legal."""
    env = _env_in_security(registry)
    # Find a legal setpoint action (one whose level != current).
    mask0 = list(env.action_masks())
    legal_set = next(
        (A.SET_LEVEL_BASE + i for i in range(3) if mask0[A.SET_LEVEL_BASE + i]),
        None,
    )
    assert legal_set is not None, "setup: at least one setpoint must be legal"
    env.step(legal_set)
    # After the step the guard must block all three.
    post = list(env.action_masks())
    for i in range(3):
        assert not post[A.SET_LEVEL_BASE + i], \
            f"SET_LEVEL_BASE+{i} should be masked after setpoint step"
    # Some non-setpoint actions (frontier drafts) must still be available.
    assert any(post[i] for i in range(A.N_ACTIONS) if i < A.SET_LEVEL_BASE
               or i >= A.SET_LEVEL_BASE + 3)


def test_env_guard_cleared_after_legal_non_setpoint(registry):
    """After any other legal non-setpoint action the guard resets: _prev_action
    is updated to the new action so a subsequent setpoint step becomes legal."""
    env = _env_in_security(registry)
    mask0 = list(env.action_masks())
    legal_set = next(
        (A.SET_LEVEL_BASE + i for i in range(3) if mask0[A.SET_LEVEL_BASE + i]),
        None,
    )
    assert legal_set is not None
    env.step(legal_set)
    assert env._prev_action == legal_set
    # Find a legal non-setpoint action (a frontier draft from Security's position).
    mid = list(env.action_masks())
    other = next(
        (i for i in range(A.N_ACTIONS)
         if mid[i] and not (A.SET_LEVEL_BASE <= i < A.SET_LEVEL_BASE + 3)),
        None,
    )
    assert other is not None, "setup: a non-setpoint legal action must exist"
    env.step(other)
    # After the non-setpoint step _prev_action is now 'other', not a setpoint.
    assert env._prev_action == other
    # The guard must be cleared: mask will not suppress setpoints due to the guard
    # Confirm the guard itself is off: prev_action is not a setpoint id.
    assert not (A.SET_LEVEL_BASE <= env._prev_action < A.SET_LEVEL_BASE + 3)


def test_env_illegal_action_does_not_clear_guard(registry):
    """An illegal (masked-out) action attempt is a no-op and must not update
    _prev_action, so the setpoint repeat guard remains active after it."""
    env = _env_in_security(registry)
    mask0 = list(env.action_masks())
    legal_set = next(
        (A.SET_LEVEL_BASE + i for i in range(3) if mask0[A.SET_LEVEL_BASE + i]),
        None,
    )
    assert legal_set is not None
    env.step(legal_set)  # fires the guard
    # Attempt an illegal action: action 0 (draft N from cell 0) is never legal
    # at this point (no frontier doorway there).
    assert not list(env.action_masks())[0], "setup: action 0 must be illegal here"
    env.step(0)  # illegal no-op
    # Guard must still be active: prev_action should still be the setpoint id.
    assert env._prev_action == legal_set
    post = list(env.action_masks())
    for i in range(3):
        assert not post[A.SET_LEVEL_BASE + i], \
            "guard must persist after an illegal action attempt"


def test_env_reset_clears_prev_action(registry):
    """reset() sets _prev_action back to None so no carry-over from the
    previous episode can suppress actions in the new one."""
    env = _env_in_security(registry)
    mask0 = list(env.action_masks())
    legal_set = next(
        (A.SET_LEVEL_BASE + i for i in range(3) if mask0[A.SET_LEVEL_BASE + i]),
        None,
    )
    assert legal_set is not None
    env.step(legal_set)
    assert env._prev_action == legal_set
    env.reset()
    assert env._prev_action is None
