"""Secret Garden: the west Antechamber segment lever.

Split out of the old test_antechamber_levers.py; see
tests/test_antechamber_levers.py for the cross-cutting lever-gate invariants
that stayed there.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, S, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED


def _game(*, levers: bool = True, registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``."""
    cfg = GameConfig(antechamber_levers=levers, **extra)
    return Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))


def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to cell and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


def test_secret_garden_opens_west(registry):
    """Entering the Secret Garden opens the west Antechamber segment (41, E)."""
    g = _game(levers=True, registry=registry,
              satisfied_conditions=frozenset({"secret_garden_key"}))
    _place_at(g, "secret_garden", 41, E | W)
    _enter_at(g, 41)

    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_OPEN
    # South and East remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED
