"""Weight Room: the power_hammer lever (south Antechamber segment) and the
red-room halved-steps penalty.

See tests/test_antechamber_levers.py for the cross-cutting lever-gate
invariants (sealed-segment reset, antechamber_levers=False baseline, etc.),
which use the Weight Room only as a vehicle.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED


# ---------------------------------------------------------------------------
# helpers

def _game(*, levers: bool = True, keys: int = 0, items: frozenset | None = None,
          registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``.

    Passes ``registry`` through when provided to avoid repeated loads.
    """
    kwargs: dict = dict(antechamber_levers=levers, **extra)
    if items is not None:
        kwargs["starting_items"] = items
    cfg = GameConfig(**kwargs)
    g = Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))
    g.state.keys = keys
    return g


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


# ---------------------------------------------------------------------------
# Test 2: Weight Room with power_hammer opens South and only South

def test_weight_room_with_hammer_opens_south(registry):
    """Entering the Weight Room while holding power_hammer opens the south
    Antechamber segment (37, N) and leaves west and east sealed."""
    g = _game(levers=True, items=frozenset({"power_hammer"}), registry=registry)
    # Place the Weight Room at rank 8 center (cell 37) with N and S doors
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    # South segment should now be open
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN
    # West and East segments remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED


# Test 3: Weight Room without hammer and without wall-break flag does NOT open

def test_weight_room_no_hammer_no_break_stays_sealed(registry):
    """Entering the Weight Room without power_hammer and without the permanent
    wall-break flag leaves the south segment sealed (no lever pull)."""
    g = _game(levers=True, registry=registry)  # no power_hammer, no wall_broken flag
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED


# Test 4: wall-break carry-over lets Weight Room open South on a later day

def test_weight_room_wall_broken_carryover_opens_south(registry):
    """Once weight_room_wall_broken is carried over, entering the Weight Room on
    a future day opens the south segment without needing the hammer again."""
    g = _game(levers=True, weight_room_wall_broken=True, registry=registry)
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN


def test_weight_room_halves_steps(registry, cfg):
    """Placing the Weight Room (a red room) halves the remaining steps."""
    g = Game(cfg, seed=1)
    g.state.steps = 40
    room = registry.by_id["weight_room"]
    g._place_room(room, 7, 4)
    assert g.state.steps == 20
