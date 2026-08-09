"""Tests for the Throne Room's lever: the backup path to Room 46.

Split out of the old test_room46.py (see tests/rooms/test_room_46.py for the
Room 46 objective itself and its Inner Sanctum route) because this behaviour
belongs to the Throne Room, not to Room 46 or the Antechamber lever system.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED


def _game(seed: int = 1, **cfg_kwargs) -> Game:
    """Return a fresh game with antechamber_levers=True and enough steps."""
    defaults = {"antechamber_levers": True, "starting_steps": 100}
    defaults.update(cfg_kwargs)
    return Game(GameConfig(**defaults), seed=seed)


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to *cell* and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


def _place_room(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Plant a room in the grid at *cell* with *mask* doors, without drafting."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def test_throne_room_lever_opens_north_door():
    """Entering the Throne Room opens the Antechamber north door (backup lever).

    Throne Room is a studio_additions room; its lever behaviour is the backup
    path to Room 46 for runs that cannot reach Inner Sanctum in time.
    """
    g = _game(studio_additions=frozenset({"throne_room"}))
    _place_room(g, "throne_room", cell=37, mask=0xF)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED
    _enter_at(g, 37)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN
