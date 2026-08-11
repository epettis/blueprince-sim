"""Tests for the Mechanarium's derived, per-Mechanical-room door mask.

draft.py::_mechanarium_orientation implements the wiki's algorithm
(blueprince.wiki.gg/wiki/Mechanarium): one doorway per Mechanical room in the
estate including itself, back door first, then forward/left/right in that
order, with an owner ruling that a doorway skipped for lack of a facing door
does not consume its slot. Diagonal compartments (doors beyond the four
cardinal ones) are a separate, unmodelled slice -- see draft.py's module
docstring.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, MECHANARIUM_ID, _mechanarium_orientation
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, OPPOSITE, W, neighbor
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.placement import satisfies_draft_conditions
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

# Rank 5, center column -- interior (all four cardinal neighbors are on-grid),
# so interior_only never disqualifies the setup itself.
CELL = 22
ENTRY = N  # the player moved north into CELL; the back door faces OPPOSITE[N]

# Independently-derived forward/left/right, NOT via engine.grid.rotate_mask
# (which the code under test also uses) -- facing north, left hand points
# west, right hand points east.
FORWARD, LEFT, RIGHT = N, W, E

# Distinct Mechanical-category room ids (other than the Mechanarium itself),
# and cells far from CELL and its neighbors (17/21/23/27) that never interfere.
_MECHANICAL_IDS = ["utility_closet", "boiler_room", "security", "workshop", "laboratory"]
_FAR_CELLS = [0, 1, 3, 4, 6]


def _ctx(registry: Registry, state: GameState) -> DraftContext:
    return DraftContext(state, registry, GameConfig(), Rng(0), set(), None)


def _place(state: GameState, registry: Registry, room_id: str, cell: int,
          mask: int | None = None) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask if mask is None else mask


def _add_mechanical_rooms(state: GameState, registry: Registry, n: int) -> None:
    """Place ``n`` distinct Mechanical rooms (not the Mechanarium) at cells
    that never neighbor CELL, each with its normal door mask."""
    for room_id, cell in zip(_MECHANICAL_IDS[:n], _FAR_CELLS[:n]):
        _place(state, registry, room_id, cell)


def test_lone_mechanarium_gets_only_the_back_door(registry: Registry):
    """With no other Mechanical room on the estate, the derived mask is just
    the back door -- the wiki's "effectively a Dead End without additional
    Mechanical Rooms" (the room's own layout still isn't dead_end; see below)."""
    state = GameState()
    mask = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)
    assert mask == OPPOSITE[ENTRY]


def test_additional_mechanical_rooms_add_doors_in_forward_left_right_order(registry: Registry):
    """Each extra placed Mechanical room adds exactly one more cardinal door,
    in the wiki's forward/left/right order, with every target neighbor left
    empty so none of them are ever skipped."""
    expected_progression = [
        OPPOSITE[ENTRY],
        OPPOSITE[ENTRY] | FORWARD,
        OPPOSITE[ENTRY] | FORWARD | LEFT,
        OPPOSITE[ENTRY] | FORWARD | LEFT | RIGHT,
    ]
    for n, expected in enumerate(expected_progression):
        state = GameState()
        _add_mechanical_rooms(state, registry, n)
        mask = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)
        assert mask == expected, f"n={n}: got {mask:#06b}, want {expected:#06b}"


def test_five_or_more_mechanical_rooms_caps_at_four_cardinal_doors(registry: Registry):
    """Beyond four placed Mechanical rooms the derived mask stops growing --
    a fifth (and any later) Mechanical room is meant to open a diagonal
    compartment instead of a fifth cardinal door (not modelled here)."""
    all_four = OPPOSITE[ENTRY] | FORWARD | LEFT | RIGHT
    for n in (4, 5):
        state = GameState()
        _add_mechanical_rooms(state, registry, n)
        mask = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)
        assert mask == all_four


def test_blocked_neighbor_is_skipped_without_consuming_its_slot(registry: Registry):
    """A candidate direction whose neighboring room has no door facing back is
    skipped, and the NEXT candidate gets the door instead of the slot being
    lost -- the owner's ruling and the subtlest rule in this mechanic."""
    state = GameState()
    _add_mechanical_rooms(state, registry, 1)  # n=2 total -> one extra door: forward
    fwd_cell = neighbor(CELL, FORWARD)
    # A room at the forward neighbor whose only door points away from CELL.
    _place(state, registry, "closet", fwd_cell, mask=FORWARD)

    mask = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)

    assert not mask & FORWARD, "forward must be skipped: its neighbor has no facing door"
    assert mask & LEFT, "the skipped slot must carry over to the next candidate (left)"
    assert mask == OPPOSITE[ENTRY] | LEFT


def test_neighbor_with_a_facing_door_gets_a_door_normally(registry: Registry):
    """A candidate whose neighboring room DOES have a door facing back is not
    skipped -- the door spawns there exactly like an open-space candidate."""
    state = GameState()
    _add_mechanical_rooms(state, registry, 1)  # one extra door: forward
    fwd_cell = neighbor(CELL, FORWARD)
    _place(state, registry, "closet", fwd_cell, mask=OPPOSITE[FORWARD])

    mask = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)

    assert mask == OPPOSITE[ENTRY] | FORWARD


def test_door_count_is_frozen_once_placed(registry: Registry):
    """Drafting more Mechanical rooms after the Mechanarium is already on the
    grid does not change its stored door mask -- "set in stone the moment it
    is drafted" -- because placed_doors is written once, at draft time, and
    nothing recomputes it later."""
    state = GameState()
    derived = _mechanarium_orientation(_ctx(registry, state), CELL, ENTRY)  # n=1: back only
    game = Game(GameConfig(), seed=0, registry=registry)
    mechanarium = registry.by_id[MECHANARIUM_ID]
    game._place_room(mechanarium, CELL, derived)
    assert game.state.placed_doors[CELL] == derived

    _add_mechanical_rooms(game.state, registry, 3)  # more Mechanical rooms drafted afterward

    assert game.state.placed_doors[CELL] == derived, (
        "the placed Mechanarium's mask must not change after later Mechanical drafts"
    )


def test_interior_only_still_blocks_a_1_door_mechanarium_on_an_edge(registry: Registry):
    """The wiki's "center 21 tiles" rule is unconditional, not derived from
    door geometry: even a Mechanarium that would need only its single back
    door -- which fits perfectly well on an edge -- is still rejected there
    via the room's own interior_only draft condition."""
    state = GameState()
    mechanarium = registry.by_id[MECHANARIUM_ID]
    edge_cell = 0  # rank 1, col 0: a corner tile, never interior
    assert not satisfies_draft_conditions(
        mechanarium, edge_cell, N, state, GameConfig(), set(), False)
    assert satisfies_draft_conditions(
        mechanarium, CELL, ENTRY, state, GameConfig(), set(), False)


def test_one_door_mechanarium_does_not_trigger_the_tombs_dead_end_bonus(registry: Registry):
    """Tomb.py's Dead-End coin spread keys off Room.layout, not the derived
    door count -- drafting a 1-door Mechanarium next to a placed Tomb must not
    pay out, matching "the Mechanarium never counts as a Dead End.\""""
    game = Game(GameConfig(), seed=0, registry=registry)
    tomb = registry.by_id["tomb"]
    game._place_room(tomb, 5, tomb.door_mask)
    game.state.coins = 0  # zero out whatever the Tomb's own self-fire granted

    derived = _mechanarium_orientation(_ctx(registry, game.state), CELL, ENTRY)
    assert derived == OPPOSITE[ENTRY], "setup: must actually be a 1-door Mechanarium"
    mechanarium = registry.by_id[MECHANARIUM_ID]
    game._place_room(mechanarium, CELL, derived)

    assert game.state.coins == 0, "a 1-door Mechanarium must not count as a Dead End"
