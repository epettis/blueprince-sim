"""Tests for the Mechanarium's derived door mask and diagonal compartments.

draft.py::_mechanarium_orientation implements the wiki's cardinal-door
algorithm (blueprince.wiki.gg/wiki/Mechanarium): one doorway per Mechanical
room in the estate including itself, back door first, then forward/left/right
in that order, with an owner ruling that a doorway skipped for lack of a
facing door does not consume its slot. Once those four cardinal doors are
accounted for, further Mechanical rooms open up to four diagonal
compartments instead -- modelled as containers at the Mechanarium's cell
(engine/effects/rooms/mechanarium.py seeds the per-placement count;
engine/special_items.py's containers.kinds mechanarium_lever/_key/_upgrade/
_sanctum hold each compartment's deterministic, priority-ordered loot).
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.draft import DraftContext, MECHANARIUM_ID, _mechanarium_orientation
from blueprince_sim.engine.effects.rooms.tomb import OFF_GRID_CELL as TOMB_OFF_GRID_CELL
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, OPPOSITE, W, neighbor
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED, segment_key
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


# Cells for compartment-count tests, which need more than the five distinct
# ids _MECHANICAL_IDS offers -- never neighbors CELL (17/21/23/27) or CELL
# itself, and never the Entrance Hall's rank-1-center cell (2).
_MANY_SAFE_CELLS = [0, 1, 3, 4, 6, 8, 9, 10]


def _add_n_mechanical_rooms(state: GameState, registry: Registry, n: int) -> None:
    """Place ``n`` Mechanical rooms (one id, reused) at cells that never
    neighbor CELL -- only the *count* of Mechanical rooms standing matters
    for the diagonal-compartment threshold, not their variety."""
    room = registry.by_id["utility_closet"]
    assert n <= len(_MANY_SAFE_CELLS), f"need {n} safe cells, only {len(_MANY_SAFE_CELLS)} defined"
    for cell in _MANY_SAFE_CELLS[:n]:
        state.grid[cell] = room.idx
        state.placed_doors[cell] = room.door_mask


def _place_mechanarium_with_n_others(game: Game, registry: Registry, others: int):
    """Place ``others`` extra Mechanical rooms, then the Mechanarium itself at
    CELL with its derived mask; return the derived mask."""
    _add_n_mechanical_rooms(game.state, registry, others)
    mechanarium = registry.by_id[MECHANARIUM_ID]
    derived = _mechanarium_orientation(_ctx(registry, game.state), CELL, ENTRY)
    game._place_room(mechanarium, CELL, derived)
    return derived


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
    door count -- drafting a 1-door Mechanarium while the Tomb is drafted must
    park no pile, matching "the Mechanarium never counts as a Dead End."

    Asserted on GameState.spread_pending rather than on state.coins: the Tomb's
    coins are parked until the player walks in, so a coins assertion would hold
    here whatever the Mechanarium did.
    """
    game = Game(GameConfig(), seed=0, registry=registry)
    tomb = registry.by_id["tomb"]
    game._place_room(tomb, 5, tomb.door_mask)
    parked_by_the_tomb_itself = list(game.state.spread_pending[TOMB_OFF_GRID_CELL])
    assert parked_by_the_tomb_itself, "setup: the Tomb's own self-count must have parked a pile"

    derived = _mechanarium_orientation(_ctx(registry, game.state), CELL, ENTRY)
    assert derived == OPPOSITE[ENTRY], "setup: must actually be a 1-door Mechanarium"
    mechanarium = registry.by_id[MECHANARIUM_ID]
    game._place_room(mechanarium, CELL, derived)

    assert game.state.spread_pending[TOMB_OFF_GRID_CELL] == parked_by_the_tomb_itself, \
        "a 1-door Mechanarium must not count as a Dead End"


# ------------------------------------------------------- diagonal compartments


def test_compartment_count_follows_min4_of_mechanical_rooms_minus_cardinal_doors(
        registry: Registry):
    """compartments = min(4, mechanical_rooms_total_incl_self - cardinal_doors_spawned):
    zero at 4 total Mechanical rooms (all four cardinal doors spawn), one more per extra
    Mechanical room once the cardinal doors are maxed out, capped at 4 diagonal doors."""
    # (others placed besides the Mechanarium, expected compartment count)
    cases = [(3, 0), (4, 1), (5, 2), (7, 4), (8, 4)]
    for others, expected in cases:
        game = Game(GameConfig(special_items=True), seed=0, registry=registry)
        derived = _place_mechanarium_with_n_others(game, registry, others)
        assert derived == OPPOSITE[ENTRY] | FORWARD | LEFT | RIGHT, (
            f"setup: others={others} must fill all four cardinal doors"
        )
        got = game.state.special.mechanarium_compartments.get(CELL, -1)
        assert got == expected, f"others={others} (total={others + 1}): got {got}, want {expected}"


def test_first_compartment_grants_the_west_antechamber_lever(registry: Registry):
    """The first diagonal compartment "contains a West Antechamber Lever" (wiki):
    opening it pulls the same Antechamber west segment Secret Garden's own
    on-entry lever opens, via secret_garden.pull_west_lever."""
    game = Game(GameConfig(special_items=True), seed=0, registry=registry)
    _place_mechanarium_with_n_others(game, registry, 4)  # total 5 -> 1 compartment
    assert game.state.special.mechanarium_compartments[CELL] == 1

    seg = segment_key(41, E)
    assert game.state.door_state.get(seg) == DOOR_SEALED, "setup: west lever starts sealed"

    game.state.pos = CELL
    tag = game.open_container()

    assert tag == "lever:west_antechamber"
    assert game.state.door_state.get(seg) == DOOR_OPEN, (
        "opening the first compartment must pull the west Antechamber lever"
    )


def test_opening_a_compartment_costs_no_key(registry: Registry):
    """The wiki names no key, step, or gem cost for opening a diagonal
    compartment door -- only the ordinary OPEN_CONTAINER_ACTION."""
    game = Game(GameConfig(special_items=True), seed=0, registry=registry)
    _place_mechanarium_with_n_others(game, registry, 4)
    game.state.pos = CELL
    game.state.keys = 3

    game.open_container()

    assert game.state.keys == 3, "opening a compartment must not spend a key"


def test_second_compartment_falls_through_to_keycard_when_silver_key_already_held(
        registry: Registry):
    """Compartment 2's priority list is Silver Key, Keycard, Secret Garden Key,
    Vault Key 233, then a basic key. Silver Key is not a `unique` item (the
    general spawn system allows more than one in the house at once), so this
    compartment's own "already held" check -- layered on top of
    `_is_available` -- is what makes it fall through to the Keycard instead
    of handing over a second Silver Key."""
    game = Game(GameConfig(special_items=True), seed=0, registry=registry)
    si.configure(game.state, game.cfg)
    _place_mechanarium_with_n_others(game, registry, 5)  # total 6 -> 2 compartments
    assert game.state.special.mechanarium_compartments[CELL] == 2
    game.state.pos = CELL
    game.open_container()  # compartment 1 (the lever) -- not under test here

    si.grant(game.state, game.registry, "silver_key", source="test")
    tag = game.open_container()  # compartment 2

    assert tag == "keycard", f"expected fallthrough to keycard, got {tag!r}"
    assert game.state.has_keycard is True


def test_third_compartment_yields_the_upgrade_disk_then_the_next_item_once_spent(
        registry: Registry):
    """Compartment 3 yields the Upgrade Disk; once THAT disk is recorded as
    spent (GameConfig.collected_disks, the cross-day carry-over gate a real
    terminal insertion sets), a fresh Mechanarium's compartment 3 falls
    through to the chain's next item, the Battery Pack."""
    game = Game(GameConfig(special_items=True), seed=0, registry=registry)
    si.configure(game.state, game.cfg)
    _place_mechanarium_with_n_others(game, registry, 6)  # total 7 -> 3 compartments
    assert game.state.special.mechanarium_compartments[CELL] == 3
    game.state.pos = CELL
    game.open_container()  # compartment 1
    game.open_container()  # compartment 2
    tag = game.open_container()  # compartment 3

    assert tag == "upgrade_disk_mechanarium"
    assert si.has(game.state, "upgrade_disk_mechanarium")

    spent_cfg = GameConfig(
        special_items=True, collected_disks=frozenset({"upgrade_disk_mechanarium"}))
    game2 = Game(spent_cfg, seed=1, registry=registry)
    si.configure(game2.state, game2.cfg)
    _place_mechanarium_with_n_others(game2, registry, 6)
    assert game2.state.special.mechanarium_compartments[CELL] == 3
    game2.state.pos = CELL
    game2.open_container()
    game2.open_container()
    tag2 = game2.open_container()

    assert tag2 == "battery_pack", (
        f"disk already spent must fall through to the chain's next item, got {tag2!r}"
    )


def test_fourth_compartment_yields_the_sanctum_key_then_dice_once_unavailable(
        registry: Registry):
    """Compartment 4 "contains a Sanctum Key, or 8 dice if the Sanctum Key
    has already been used or is otherwise unavailable" (wiki) -- exercised
    here via room46_reached=False, which gates every Sanctum Key id out."""
    reached_cfg = GameConfig(special_items=True, room46_reached=True)
    game = Game(reached_cfg, seed=0, registry=registry)
    si.configure(game.state, game.cfg)
    _place_mechanarium_with_n_others(game, registry, 7)  # total 8 -> 4 compartments
    assert game.state.special.mechanarium_compartments[CELL] == 4
    game.state.pos = CELL
    game.open_container()  # compartment 1
    game.open_container()  # compartment 2
    game.open_container()  # compartment 3
    tag = game.open_container()  # compartment 4

    assert tag == "sanctum_key_mechanarium"

    unreached_cfg = GameConfig(special_items=True, room46_reached=False)
    game2 = Game(unreached_cfg, seed=1, registry=registry)
    si.configure(game2.state, game2.cfg)
    _place_mechanarium_with_n_others(game2, registry, 7)
    assert game2.state.special.mechanarium_compartments[CELL] == 4
    game2.state.pos = CELL
    game2.open_container()
    game2.open_container()
    game2.open_container()
    tag2 = game2.open_container()

    assert tag2 == "dice:8", f"Sanctum Key unavailable must fall through to 8 dice, got {tag2!r}"
