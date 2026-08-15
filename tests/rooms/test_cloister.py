"""Cloister variants: "...for each X you draft FROM THIS CLOISTER" tracking.

Covers all eight variants implemented in effects/rooms/cloister.py (Rynna,
Mila, Orinda, Draxus, Lydia, Dauja, Veia, Joya).

Every test bypasses the deal pipeline via Game._place_room directly (as the
other room tests do), but reproduces exactly what Game.choose leaves in place
at the moment ON_DRAFT_ROOM fires: state.pending still set, with from_cell
pointing at the doorway the new room was dealt from. That is the one piece of
state the whole "drafted from THIS Cloister" primitive depends on.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.engine.shops import carryover
from blueprince_sim.engine.state import PendingDraft
from blueprince_sim.env.multiday import DayChain
from luck_utils import suppress_luck

ANTECHAMBER_CELL = 42

# Matches the four segments Game.reset seals when antechamber_levers is True.
ANTECHAMBER_SEGMENTS = (
    segment_key(ANTECHAMBER_CELL, N),
    segment_key(41, E),
    segment_key(37, N),
    segment_key(43, W),
)


def _draft_from(g, from_cell: int, target_cell: int, room) -> None:
    """Place ``room`` at ``target_cell`` as if just dealt from ``from_cell``'s doorway.

    Mirrors the live state of Game.choose at the point it calls
    Game._place_room: state.pending is still populated (choose() only clears
    it afterward), with from_cell/target_cell set to the doorway drafted and
    the cell the new room lands on.
    """
    g.state.pending = PendingDraft(from_cell=from_cell, direction=N, target_cell=target_cell)
    g._place_room(room, target_cell, room.door_mask)


def test_rynna_raises_luck_for_a_green_room_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_rynna__ix29 raises luck when a green room is dealt from its
    own doorway; the base Cloister (identical effects: []) does not react."""
    patio = registry.by_id["patio"]
    assert patio.category == "green", "setup: Patio must be a green room"
    for room_id, expected_luck in (("cloister", 0), ("cloister_of_rynna__ix29", 6)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, patio)
        assert g.state.luck == expected_luck, room_id


def test_rynna_does_not_react_to_a_green_room_drafted_from_elsewhere(registry, cfg):
    """Luck stays put when the green room's doorway is some other placed
    room's, even with Cloister of Rynna elsewhere on the grid."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    closet = registry.by_id["closet"]
    patio = registry.by_id["patio"]
    g._place_room(rynna, 10, rynna.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, patio)  # dealt from Closet's doorway, not Rynna's
    assert g.state.luck == 0


def test_rynna_does_not_react_to_a_non_green_room_from_its_own_doorway(registry, cfg):
    """A non-green room dealt from Rynna's own doorway grants no luck --
    the trigger is ctx_room.category == "green", not the doorway alone."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    closet = registry.by_id["closet"]  # category "blueprint", not green
    g._place_room(rynna, 10, rynna.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.luck == 0


def test_mila_grants_an_item_only_when_its_flagged_bedroom_is_entered(registry, cfg):
    """cloister_of_mila__ix33 grants exactly one extra item on the first entry
    of a Bedroom dealt from its own doorway; the base Cloister does not."""
    bedroom = registry.by_id["bedroom"]
    assert bedroom.category == "bedroom" and bedroom.items.additional_max == 1
    for room_id, expected_extra in (("cloister", 0), ("cloister_of_mila__ix33", 1)):
        g = Game(cfg, seed=1)
        suppress_luck(g)  # floors the room's own luck-gated additional_max roll to 0
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, bedroom)
        found_before = len(g.state.items_found_log)
        g._enter(11)
        assert len(g.state.items_found_log) == found_before + expected_extra, room_id


def test_mila_does_not_mark_a_bedroom_drafted_from_elsewhere(registry, cfg):
    """A Bedroom dealt from a doorway that is not Mila's own is never marked
    for the bonus item, even with Cloister of Mila elsewhere on the grid."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    mila = registry.by_id["cloister_of_mila__ix33"]
    closet = registry.by_id["closet"]
    bedroom = registry.by_id["bedroom"]
    g._place_room(mila, 10, mila.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, bedroom)
    assert 21 not in g.state.cloister_mila_bonus_cells
    found_before = len(g.state.items_found_log)
    g._enter(21)
    assert len(g.state.items_found_log) == found_before


def test_orinda_opens_exactly_one_antechamber_segment_per_blackprint(registry, cfg):
    """cloister_of_orinda__ix35 opens exactly one of the Antechamber's four
    sealed segments per blackprint dealt from its own doorway; the base
    Cloister leaves all four sealed."""
    throne_room = registry.by_id["throne_room"]
    assert throne_room.category == "blackprint"
    for room_id, expect_one_opened in (("cloister", False), ("cloister_of_orinda__ix35", True)):
        g = Game(cfg, seed=1)
        assert all(g.state.door_state[s] == DOOR_SEALED for s in ANTECHAMBER_SEGMENTS)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, throne_room)
        sealed_left = sum(1 for s in ANTECHAMBER_SEGMENTS if g.state.door_state[s] == DOOR_SEALED)
        assert sealed_left == (3 if expect_one_opened else 4), room_id


def test_orinda_does_not_react_to_a_non_blackprint_room_from_its_own_doorway(registry, cfg):
    """A non-blackprint room dealt from Orinda's own doorway opens nothing --
    the trigger is ctx_room.category == "blackprint", not the doorway alone."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    patio = registry.by_id["patio"]  # category "green", not blackprint
    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, patio)
    assert all(g.state.door_state[s] == DOOR_SEALED for s in ANTECHAMBER_SEGMENTS)


def test_draxus_grants_dice_for_a_dead_end_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_draxus__ix36 grants 4 dice when a Dead End is dealt from
    its own doorway; the base Cloister (identical effects: []) does not."""
    closet = registry.by_id["closet"]
    assert closet.layout == "dead_end", "setup: Closet must be a Dead End"
    for room_id, expected_dice in (("cloister", 0), ("cloister_of_draxus__ix36", 4)):
        g = Game(cfg, seed=1)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, closet)
        assert g.state.dice == expected_dice, room_id


def test_draxus_does_not_react_to_a_non_dead_end_room_from_its_own_doorway(registry, cfg):
    """A non-Dead-End room dealt from Draxus's own doorway grants no dice --
    the trigger is the room's actual drafted orientation having exactly one
    door, not the doorway alone."""
    g = Game(cfg, seed=1)
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    patio = registry.by_id["patio"]  # layout "corner", not a dead end
    g._place_room(draxus, 10, draxus.door_mask)
    _draft_from(g, 10, 11, patio)
    assert g.state.dice == 0


def test_draxus_does_not_react_to_a_greenhouse_drafted_in_a_corner_orientation(registry, cfg):
    """The Greenhouse's ``layout`` is "dead_end", but its ``alt_layouts``
    include "corner", so it can be drafted with two doors (once its Power
    Hammer wall break admits ``Room.gated_rotations`` at draft time --
    ``_place_room`` itself takes any orientation directly and does not
    re-check legality). A Greenhouse dealt from Draxus's own doorway in one
    of its corner rotations (door mask 3, 6, 9, or 12) is not a Dead End and
    grants no dice, even though its frozen Room.layout still reads
    "dead_end"."""
    g = Game(cfg, seed=1)
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    greenhouse = registry.by_id["greenhouse"]
    corner_mask = 3  # S|E -- one of the Greenhouse's gated corner rotations
    assert corner_mask in greenhouse.gated_rotations, "setup: corner rotation must be a real shape"
    g._place_room(draxus, 10, draxus.door_mask)
    # Mirrors _draft_from, but with the corner mask instead of the room's
    # canonical door_mask (the one piece _draft_from itself cannot vary).
    g.state.pending = PendingDraft(from_cell=10, direction=N, target_cell=11)
    g._place_room(greenhouse, 11, corner_mask)
    assert g.state.dice == 0


def test_draxus_grants_dice_for_a_greenhouse_drafted_as_a_genuine_dead_end(registry, cfg):
    """The same Greenhouse, dealt from Draxus's own doorway in its one-door
    canonical orientation (its own ``layout`` value), IS a Dead End and
    grants dice -- the contrast with the corner case above proves the check
    follows the drafted orientation, not a blanket exemption for the
    Greenhouse id."""
    g = Game(cfg, seed=1)
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    greenhouse = registry.by_id["greenhouse"]
    g._place_room(draxus, 10, draxus.door_mask)
    _draft_from(g, 10, 11, greenhouse)
    assert g.state.dice == 4


def test_two_cloisters_each_track_only_their_own_doorway(registry, cfg):
    """With Rynna and Draxus both on the grid, a room dealt from Rynna's
    doorway only ever raises luck, and a room dealt from Draxus's doorway
    only ever grants dice -- the two trackers never cross-react."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    patio = registry.by_id["patio"]  # green, for Rynna
    closet = registry.by_id["closet"]  # dead end, for Draxus
    g._place_room(rynna, 10, rynna.door_mask)
    g._place_room(draxus, 30, draxus.door_mask)

    _draft_from(g, 10, 11, patio)  # dealt from Rynna's doorway
    assert (g.state.luck, g.state.dice) == (6, 0)

    _draft_from(g, 30, 31, closet)  # dealt from Draxus's doorway
    assert (g.state.luck, g.state.dice) == (6, 4)


def test_lydia_raises_allowance_for_a_shop_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_lydia__ix34 adds 2 permanent allowance when a Shop is dealt
    from its own doorway; the base Cloister (identical effects: []) does not."""
    commissary = registry.by_id["commissary"]
    assert commissary.category == "shop", "setup: Commissary must be a Shop"
    for room_id, expected_allowance in (("cloister", 0), ("cloister_of_lydia__ix34", 2)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, commissary)
        assert g.state.allowance == expected_allowance, room_id


def test_lydia_does_not_react_to_a_non_shop_room_from_its_own_doorway(registry, cfg):
    """A non-Shop room dealt from Lydia's own doorway raises no allowance --
    the trigger is ctx_room.category == "shop", not the doorway alone."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    lydia = registry.by_id["cloister_of_lydia__ix34"]
    closet = registry.by_id["closet"]  # category "blueprint", not shop
    g._place_room(lydia, 10, lydia.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.allowance == 0


def test_lydia_does_not_react_to_a_shop_drafted_from_elsewhere(registry, cfg):
    """Allowance stays put when the Shop's doorway is some other placed
    room's, even with Cloister of Lydia elsewhere on the grid."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    lydia = registry.by_id["cloister_of_lydia__ix34"]
    closet = registry.by_id["closet"]
    commissary = registry.by_id["commissary"]
    g._place_room(lydia, 10, lydia.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, commissary)  # dealt from Closet's doorway, not Lydia's
    assert g.state.allowance == 0


def test_orinda_opens_a_still_sealed_door_rather_than_one_already_open(registry, cfg):
    """With three of the four segments already open, Orinda opens the fourth.

    The room promises a door, so a trigger that landed on an already-open
    segment would silently deliver nothing. Leaving exactly one sealed makes
    the choice observable without depending on the RNG."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    throne_room = registry.by_id["throne_room"]
    still_sealed = ANTECHAMBER_SEGMENTS[1]
    for seg in ANTECHAMBER_SEGMENTS:
        if seg != still_sealed:
            g.state.door_state[seg] = DOOR_OPEN

    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, throne_room)

    assert g.state.door_state[still_sealed] != DOOR_SEALED


def test_orinda_is_a_no_op_when_every_antechamber_door_is_open(registry, cfg):
    """Orinda leaves the Antechamber alone once nothing is sealed, rather than
    failing on an empty set of candidates."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    throne_room = registry.by_id["throne_room"]
    for seg in ANTECHAMBER_SEGMENTS:
        g.state.door_state[seg] = DOOR_OPEN

    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, throne_room)

    assert all(g.state.door_state[s] == DOOR_OPEN for s in ANTECHAMBER_SEGMENTS)


# --- cloister_of_dauja__ix31 -------------------------------------------------

def test_dauja_grants_two_stars_for_each_animal_room_drafted_from_it(registry, cfg):
    """cloister_of_dauja__ix31 grants 2 stars for each of the six wiki-listed
    animal rooms dealt from its own doorway, accumulating across drafts."""
    dauja = registry.by_id["cloister_of_dauja__ix31"]
    animal_ids = ("rumpus_room", "aquarium", "nursery", "dovecote", "the_kennel")
    g = Game(cfg, seed=1)
    g._place_room(dauja, 10, dauja.door_mask)
    assert g.state.stars == 0
    for i, room_id in enumerate(animal_ids):
        _draft_from(g, 10, 11 + i, registry.by_id[room_id])
        assert g.state.stars == 2 * (i + 1), room_id


def test_dauja_does_not_react_to_a_non_animal_room_from_its_own_doorway(registry, cfg):
    """A non-animal room dealt from Dauja's own doorway grants no stars --
    the trigger is the has_animal flag, not the doorway alone."""
    g = Game(cfg, seed=1)
    dauja = registry.by_id["cloister_of_dauja__ix31"]
    closet = registry.by_id["closet"]  # no has_animal flag
    g._place_room(dauja, 10, dauja.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.stars == 0


def test_dauja_bunk_room_grants_two_stars_not_four(registry, cfg):
    """The Bunk Room "does not activate twice": it counts as two Bedrooms
    elsewhere in the engine, but Dauja still pays exactly one 2-star grant
    per actual draft, never a doubled 4."""
    g = Game(cfg, seed=1)
    dauja = registry.by_id["cloister_of_dauja__ix31"]
    bunk_room = registry.by_id["bunk_room"]
    g._place_room(dauja, 10, dauja.door_mask)
    _draft_from(g, 10, 11, bunk_room)
    assert g.state.stars == 2


def test_dauja_does_not_react_to_an_animal_room_drafted_from_elsewhere(registry, cfg):
    """Stars stay put when an animal room's doorway is some other placed
    room's, even with Cloister of Dauja elsewhere on the grid."""
    g = Game(cfg, seed=1)
    dauja = registry.by_id["cloister_of_dauja__ix31"]
    closet = registry.by_id["closet"]
    aquarium = registry.by_id["aquarium"]
    g._place_room(dauja, 10, dauja.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, aquarium)  # dealt from Closet's doorway, not Dauja's
    assert g.state.stars == 0


# --- cloister_of_veia__ix32 --------------------------------------------------

def test_veia_grants_eight_extra_dig_spots_for_a_fireplace_room(registry, cfg):
    """cloister_of_veia__ix32 adds 8 dig spots to a Parlor (baseline 0) dealt
    from its own doorway, additive on top of the room's own items.dig_spots."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    parlor = registry.by_id["parlor"]
    assert parlor.items.dig_spots == 0, "setup: Parlor's own baseline must be 0"
    g._place_room(veia, 10, veia.door_mask)
    _draft_from(g, 10, 11, parlor)
    assert g.state.special.veia_dig_bonus[11] == 8


def test_veia_furnace_reaches_nine_dig_spots_not_eight(registry, cfg):
    """The Furnace's baseline 1 dig spot plus Veia's +8 reaches 9 total, not
    a flat 8 -- the bonus is additive, proven by actually digging every spot
    with a held tool rather than reading the data fields back."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    furnace = registry.by_id["furnace"]
    assert furnace.items.dig_spots == 1, "setup: Furnace's own baseline must be 1"
    g._place_room(veia, 10, veia.door_mask)
    _draft_from(g, 10, 11, furnace)
    si.grant(g.state, g.registry, "shovel", source="test")
    si.dig_all(g, 11)
    assert g.state.special.dug[11] == 9


def test_veia_dining_room_in_a_centre_column_qualifies(registry, cfg):
    """A Dining Room dealt from Veia's doorway into a centre-column, non-
    Rank-1 cell has a fireplace and gets the +8 dig bonus."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    dining_room = registry.by_id["dining_room"]
    g._place_room(veia, 10, veia.door_mask)
    centre_cell = 22  # rank 5, col 2 (centre column)
    _draft_from(g, 10, centre_cell, dining_room)
    assert g.state.special.veia_dig_bonus.get(centre_cell) == 8


def test_veia_dining_room_on_a_wing_does_not_qualify(registry, cfg):
    """A Dining Room dealt from Veia's doorway into a wing cell (Rank != 9)
    has windows, not a fireplace, so it gets no dig bonus."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    dining_room = registry.by_id["dining_room"]
    g._place_room(veia, 10, veia.door_mask)
    wing_cell = 20  # rank 5, col 0 (West Wing)
    _draft_from(g, 10, wing_cell, dining_room)
    assert wing_cell not in g.state.special.veia_dig_bonus


def test_veia_dining_room_on_a_wing_at_rank_nine_still_qualifies(registry, cfg):
    """Rank 9 is named as its own qualifying alternative alongside the centre
    columns, so a Dining Room on a Rank-9 wing cell still gets the bonus."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    dining_room = registry.by_id["dining_room"]
    g._place_room(veia, 10, veia.door_mask)
    wing_rank9_cell = 40  # rank 9, col 0 (West Wing)
    _draft_from(g, 10, wing_rank9_cell, dining_room)
    assert g.state.special.veia_dig_bonus.get(wing_rank9_cell) == 8


def test_veia_does_not_react_to_a_non_fireplace_room_from_its_own_doorway(registry, cfg):
    """A room with no has_fireplace flag dealt from Veia's own doorway gets
    no dig bonus."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    closet = registry.by_id["closet"]
    g._place_room(veia, 10, veia.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.special.veia_dig_bonus == {}


def test_veia_extra_dig_spots_are_actually_diggable(registry, cfg):
    """The +8 bonus is not just a counter: digging a Parlor dealt from Veia's
    doorway with a held tool actually turns up 8 results."""
    g = Game(cfg, seed=1)
    veia = registry.by_id["cloister_of_veia__ix32"]
    parlor = registry.by_id["parlor"]
    g._place_room(veia, 10, veia.door_mask)
    _draft_from(g, 10, 11, parlor)
    si.grant(g.state, g.registry, "shovel", source="test")
    si.dig_all(g, 11)
    assert g.state.special.dug[11] == 8


# --- cloister_of_joya__ix30 --------------------------------------------------

def test_joya_raises_main_course_bonus_for_kitchen_and_pantry_drafted_from_it(registry, cfg):
    """cloister_of_joya__ix30 adds 5 to the running Main Course bonus for a
    Kitchen dealt from its own doorway, and 5 more for a Pantry (10 total)."""
    g = Game(cfg, seed=1)
    joya = registry.by_id["cloister_of_joya__ix30"]
    kitchen = registry.by_id["kitchen"]
    pantry = registry.by_id["pantry"]
    g._place_room(joya, 10, joya.door_mask)
    assert g.state.main_course_bonus == 0
    _draft_from(g, 10, 11, kitchen)
    assert g.state.main_course_bonus == 5
    _draft_from(g, 10, 12, pantry)
    assert g.state.main_course_bonus == 10


def test_joya_does_not_react_to_a_non_trigger_room_from_its_own_doorway(registry, cfg):
    """A room that is not a Kitchen/Pantry/Furnace dealt from Joya's own
    doorway raises no Main Course bonus."""
    g = Game(cfg, seed=1)
    joya = registry.by_id["cloister_of_joya__ix30"]
    closet = registry.by_id["closet"]
    g._place_room(joya, 10, joya.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.main_course_bonus == 0


def test_joya_bonus_raises_each_main_course_dish_by_five(registry, cfg):
    """The running bonus adds to every one of the five main-course dishes'
    resolved steps, whether that dish's own boost room is on the estate or
    not -- proven on two different dishes, not just one."""
    g = Game(cfg, seed=1)
    g.state.main_course_bonus = 5
    steps_before = g.state.steps
    si.eat_food(g, "lemon_glazed_salmon")  # base 20, no aquarium on estate
    assert g.state.steps == steps_before + 25

    steps_before = g.state.steps
    si.eat_food(g, "wood_fired_pizza")  # base 20, no furnace on estate
    assert g.state.steps == steps_before + 25


def test_joya_bonus_does_not_affect_the_lunch_box(registry, cfg):
    """The Lunch Box resolves its steps through food_steps directly (its own
    item-effect base, not a food.dishes lookup), which Joya's bonus never
    touches -- only main-course dishes eaten through eat_food do."""
    g = Game(cfg, seed=1)
    g.state.main_course_bonus = 5
    assert si.food_steps(g.state, g.registry, 10) == 10  # the Lunch Box's own base steps param


def test_joya_bonus_survives_a_day_boundary_via_daychain(registry):
    """A Kitchen dealt from Cloister of Joya's doorway on day 1 shows up in
    state.main_course_bonus on day 2 unchanged, with no new gain that day --
    a permanent per-attempt total, not a one-day pulse."""
    chain = DayChain(GameConfig(), n_days=200)

    g1 = Game(chain.next_config(), seed=1, registry=registry)
    joya = g1.registry.by_id["cloister_of_joya__ix30"]
    kitchen = g1.registry.by_id["kitchen"]
    g1._place_room(joya, 10, joya.door_mask)
    _draft_from(g1, 10, 11, kitchen)
    assert g1.state.main_course_bonus == 5
    chain.advance(carryover(g1))

    day2_cfg = chain.next_config()
    assert day2_cfg.main_course_bonus == 5
    g2 = Game(day2_cfg, seed=2, registry=registry)
    assert g2.state.main_course_bonus == 5


def test_joya_bonus_survives_an_attempt_wrap():
    """The Main Course bonus is save-scoped: it carries through a fresh attempt
    rather than resetting with it.

    This is the one carried total that behaves this way -- every other one is
    attempt-scoped and returns to its base preset on wrap -- so it is worth
    pinning directly rather than inferring from the day-boundary test."""
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"main_course_bonus": 15})  # day 1 -> wraps immediately

    assert chain.current_day == 1
    assert chain.next_config().main_course_bonus == 15


def test_attempt_wrap_still_clears_the_attempt_scoped_totals():
    """Save-scoped totals are a named pair, not a general loosening: Joya's
    bonus and stars survive a wrap while allowance still resets to its preset.

    Pinned together so adding a third save-scoped total is a deliberate edit
    here rather than something that slips in unnoticed."""
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"main_course_bonus": 15, "allowance": 30, "stars": 4})

    cfg = chain.next_config()
    assert cfg.main_course_bonus == 15
    assert cfg.stars == 4
    assert cfg.allowance == 0
