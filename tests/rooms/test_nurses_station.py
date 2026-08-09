"""Nurse's Station, an upgrade variant of the Nursery.

Entering with fewer than 10 steps sets steps to 20; entering with 10 or more
leaves them untouched. Driven by the ``set_resource_on_enter`` effect with an
``if_below`` threshold.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0, **cfg_kw) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered."""
    cfg = GameConfig(special_items=True, **cfg_kw)
    g = Game(cfg, seed=seed)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_nurses_station_tops_up_steps_when_below_threshold():
    """Entering with fewer than 10 steps sets the step count to exactly 20."""
    cell = 5
    g = _make_game_with_room("nurses_station__ix102", cell, starting_steps=5)
    assert g.state.steps < 10

    g._enter(cell)
    assert g.state.steps == 20


def test_nurses_station_does_nothing_at_or_above_threshold():
    """Entering with 10 or more steps leaves the step count untouched -- the
    Nurse's Station only tops up a player who is running low, it never docks
    a player who already has plenty."""
    cell = 5
    g = _make_game_with_room("nurses_station__ix102", cell, starting_steps=50)
    steps0 = g.state.steps
    assert steps0 >= 10

    g._enter(cell)
    assert g.state.steps == steps0
