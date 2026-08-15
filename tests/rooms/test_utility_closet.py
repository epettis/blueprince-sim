"""Utility Closet: the breaker box's role in Game._action_in_budget's
day-continuation check.

tests/test_locks.py already pins the Utility Closet's switch itself
(can_toggle_keycard_power / set_keycard_power gated on standing inside it,
the offline-mode truth table, control rooms staying revisitable) -- that
coverage is left alone. What nothing exercises is _action_in_budget's own
"detour to the Utility Closet" branch (game.py's toggle_ok local): a
security-locked doorway that is not currently openable, but that flipping
the closet's power would open, still counts as a purposeful action within
the step budget, so the day does not end early just because the only
frontier doorway is momentarily blocked.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_SECURITY, segment_key

CLOSET_CELL = 7  # rank 2, col 2: interior, doorway north targets cell 12 (empty)


def _game_at_closet(registry, cfg) -> Game:
    """Fresh game standing in a placed Utility Closet whose only doorway is
    security-locked. The closet cell is never connected to the Entrance
    Hall, so this doorway is the day's only frontier action -- the same
    disconnected-island technique tests/test_locks.py's own
    _place_and_stand helper uses."""
    g = Game(cfg, seed=1, registry=registry)
    uc = g.registry.by_id["utility_closet"]
    g._place_room(uc, CLOSET_CELL, N)
    g.state.pos = CLOSET_CELL
    g.state.keys = 0
    g.state.door_state[segment_key(CLOSET_CELL, N)] = DOOR_SECURITY
    g.state.door_version += 1
    g.state.offline_unlocked = True  # Security already visited once today
    return g


def test_toggle_within_reach_counts_as_a_purposeful_action(registry, cfg):
    """Standing in the Utility Closet with a reachable security door that
    cutting power would open, and nothing else available, still counts as a
    purposeful action: the day does not end even though the door itself is
    not openable yet."""
    g = _game_at_closet(registry, cfg)
    assert g.state.keycard_power_on, "starts powered: the toggle is a power-down"
    assert not g.security_openable(), "the door must start out unopenable"
    g.state.steps = 2  # dist to the closet is 0; the branch needs steps - 2 >= 0
    assert g._action_in_budget(), "cutting power here would open the only door"
    g._check_termination()
    assert g.phase is not Phase.TERMINAL


def test_toggle_out_of_reach_does_not_keep_the_day_alive(registry, cfg):
    """The same layout one step short of affording the detour: the toggle no
    longer counts as purposeful, and with nothing else available the day
    ends -- proving the branch actually gates on distance rather than
    granting a free pass whenever the closet exists somewhere."""
    g = _game_at_closet(registry, cfg)
    g.state.steps = 1  # dist(closet) - 2 == -1: the detour no longer fits
    assert not g._action_in_budget()
    g._check_termination()
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"
