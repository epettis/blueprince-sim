"""Great Hall: the east Antechamber segment lever and its key cost.

Split out of the old test_antechamber_levers.py; see
tests/test_antechamber_levers.py for the cross-cutting lever-gate invariants
that stayed there.

The Great Hall is the only lever room whose pull costs a key, so its cost is
charged to the walk itself (key_cost_map, the action mask's key budget, and
end-to-end masked play all agree with what move_to actually deducts) rather
than just to the door being opened.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.env import actions as A


def _game(*, levers: bool = True, keys: int = 0, registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``."""
    cfg = GameConfig(antechamber_levers=levers, **extra)
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


def test_great_hall_opens_east_costs_key(registry):
    """Entering the Great Hall with a key opens the east Antechamber segment
    (43, W) and consumes exactly one key."""
    g = _game(levers=True, keys=3, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_OPEN
    assert g.state.keys == 2  # one key spent
    # South and West remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED


def test_great_hall_no_key_stays_sealed(registry):
    """Entering the Great Hall with zero keys does not open the east segment:
    the lever requires a key to access and cannot be pulled without one."""
    g = _game(levers=True, keys=0, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED
    assert g.state.keys == 0  # no key spent


def test_walking_into_the_great_hall_is_charged_to_the_route(registry):
    """key_cost_map() prices in the Great Hall's on-arrival lever key spend
    before the caller ever walks - and move_to actually deducts exactly that
    many keys - so a caller budgeting off key_cost_map is never surprised."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    # Force the entrance -> Great Hall segment open so the only key spend on
    # this walk is the lever, not a locked door on the way in.
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    # Setup assertion: the lever has not been pulled yet, so the test can't
    # silently stop testing anything.
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED

    assert g.key_cost_map()[7] == 1  # the route to the Great Hall spends the lever key

    g.move_to(7)
    assert g.state.keys == 0  # the map matched what the walk actually spent


def test_the_nav_cache_notices_a_lever_room_that_has_already_been_entered(registry):
    """The nav memo must key on state.entered: an already-entered Great Hall
    charges nothing, because its lever only ever fires on first entry, and a
    map cached from before that entry would over-charge the route and could
    strand the player behind a road it wrongly reads as unaffordable."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled
    assert g.key_cost_map()[7] == 1  # unentered: walking in will pull the lever

    # Entry is the only thing that changes here, and the lever cannot fire twice.
    g.state.entered[7] = True
    assert g.key_cost_map()[7] == 0


def test_the_mask_never_offers_a_draft_the_lever_key_has_already_paid_for(registry):
    """A locked frontier doorway past the Great Hall needs two keys: one the
    walk itself spends pulling the lever, one for the door. The mask must
    not let the lever spend ride free on the door's own key budget."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    # Lock one of the Great Hall's own frontier doorways.
    g.state.door_state[segment_key(7, E)] = DOOR_LOCKED
    g.state.door_version += 1

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled

    action = A.OPEN_BASE + 7 * 4 + A.DIR_INDEX[E]

    g.state.keys = 1
    mask = A.action_mask(g)
    assert not mask[action], "1 key covers only the lever pull, not the locked door too"

    g.state.keys = 2
    mask = A.action_mask(g)  # _maps() fingerprints on st.keys, so this recomputes
    assert mask[action], "2 keys cover both the lever pull and the locked door"
