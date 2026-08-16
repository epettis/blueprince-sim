"""Shelter's gem safe and red-room negation.

See tests/rooms/test_office.py, test_study.py, test_drawing_room.py, and
test_boudoir.py for the other gem-safe rooms.

The sim assumes every puzzle in an entered room gets solved, so the safe in
this room just hands over a gem the moment the player walks in - see
docs/doctrine.md. That doctrine is why the Shelter is included
despite its real-time time-lock (owner decision): solving the
lock is assumed, so it pays out.
"""

import itertools

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game

# Three red rooms whose penalty is entry-triggered, so the test can resolve
# them in any order it likes, at fixed cells so no scenario depends on a seed
# for its layout.
ENTRY_PENALTY_CELLS = {"chapel": 7, "gymnasium": 8, "darkroom": 12}
MAIDS_CHAMBER_CELL = 13
ANTI_LUCK = 7  # data/rooms.json: the Maid's Chamber's anti_luck amount


def _shelter_at_the_doorstep() -> Game:
    """Draft the Shelter as today's outer room, left at the West Path doorstep.

    Seed 0 deals the Shelter, so this goes through the real draft (firing
    ON_PLACE) instead of poking placed_ids, which would skip that hook and
    make the negate_red_rooms assertion below vacuous.
    """
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=0)
    g.open_outer_draft()
    g.choose(0)
    assert g.drafted_outer_room is not None and g.drafted_outer_room.id == "shelter", (
        "setup: seed 0 must deal the Shelter"
    )
    assert not g.state.outer_room_entered, "setup: drafted but not yet entered"
    return g


def test_shelter_grants_its_gem_through_the_outer_room_entry_path():
    """The Shelter is an OUTER room, entered by travelling off-grid rather than
    by walking the grid, so its grant rides travel_to's ON_ENTER rather than
    _enter's. Without that path the data edit would be silently inert."""
    g = _shelter_at_the_doorstep()
    gems0 = g.state.gems
    g.travel_to("shelter")
    assert g.state.outer_room_entered
    assert g.state.gems == gems0 + 1


def test_shelter_keeps_its_red_room_negation():
    """The Shelter's negate_red_rooms effect fires alongside its gem grant -
    the append-vs-replace guard for the one safe room whose effects list is not
    empty. The two ride DIFFERENT hooks (negation on ON_PLACE at draft time,
    the gem on ON_ENTER), so both are checked."""
    g = _shelter_at_the_doorstep()
    assert g.red_negations >= 3, "negate_red_rooms fires on ON_PLACE, at draft time"
    gems0 = g.state.gems
    g.travel_to("shelter")
    assert g.state.gems == gems0 + 1, "and the safe still pays out on entry"


def test_shelter_category_does_not_activate_the_outer_shop_dead_branch():
    """Shelter's category is "blueprint" (corrected from the pool name
    "outer"), not "shop": entering it off-grid must not resolve a
    current_shop_id -- that branch (game.py:994 / shops.py:359) only fires
    for Trading Post. See tests/rooms/test_trading_post.py for the
    positive case."""
    g = _shelter_at_the_doorstep()
    assert g.registry.by_id["shelter"].category == "blueprint"
    g.travel_to("shelter")
    assert shops.current_shop_id(g) is None


def test_shelter_has_no_effect_on_a_red_room_already_drafted():
    """"It has no effect on rooms I have already drafted" (docs/rooms.md's
    shelter entry): a Chapel placed on the grid BEFORE the Shelter
    is drafted keeps paying its -1 coin penalty on first entry, even though
    that entry happens after the Shelter is on the board with charges to
    spend -- protection is scoped by draft order, not by which event happens
    to fire the penalty first. Built inline rather than via
    ``_shelter_at_the_doorstep`` because that helper already drafts the
    Shelter -- the Chapel must land on the grid BEFORE it. ``_enter`` fires
    ON_ENTER directly, so the test does not depend on the two rooms' cells
    actually connecting."""
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=0)
    chapel = g.registry.by_id["chapel"]
    g._place_room(chapel, 7, 0)
    assert "chapel" in g.placed_ids
    g.state.coins = 5

    g.open_outer_draft()
    g.choose(0)
    assert g.drafted_outer_room is not None and g.drafted_outer_room.id == "shelter", (
        "setup: seed 0 must deal the Shelter"
    )
    g.travel_to("shelter")
    assert g.red_negations >= 3

    coins_before = g.state.coins
    g._enter(7)
    assert g.state.coins == coins_before - 1, (
        "the Chapel was drafted before the Shelter, so its penalty must still apply"
    )


def test_shelter_still_protects_a_red_room_drafted_after_it():
    """The forward-looking half of the same ruling: a red room placed AFTER
    the Shelter is drafted has its penalty negated."""
    g = _shelter_at_the_doorstep()
    g.travel_to("shelter")
    assert g.red_negations >= 3
    gymnasium = g.registry.by_id["gymnasium"]
    g._place_room(gymnasium, 7, 0)  # drafted AFTER the Shelter
    g.state.steps = 20
    steps_before = g.state.steps
    g._enter(7)
    assert g.state.steps == steps_before, (
        "a red room drafted after the Shelter is still protected"
    )


def _shelter_then_four_red_rooms() -> Game:
    """Draft the Shelter, then four red rooms, all after it, in a fixed order.

    Chapel, Gymnasium and Darkroom are drafted first and carry entry-triggered
    penalties the caller can resolve in any order; the Maid's Chamber is
    drafted fourth and its anti-luck resolves immediately, at its own
    placement. That split is the scenario's whole point: the fourth room's
    penalty resolves BEFORE any of the first three's, so protection following
    draft order rather than resolution order is directly observable.

    Coins and steps are stocked so the Chapel's and Gymnasium's penalties have
    something to take; none of the four rooms spawns an item
    (``data/rooms.json``), so entering them moves no other resource.
    """
    g = _shelter_at_the_doorstep()
    g.state.coins = 5
    g.state.steps = 40
    for room_id, cell in ENTRY_PENALTY_CELLS.items():
        g._place_room(g.registry.by_id[room_id], cell, 0)
    g._place_room(g.registry.by_id["maids_chamber"], MAIDS_CHAMBER_CELL, 0)
    return g


@pytest.mark.parametrize("entry_order", list(itertools.permutations(ENTRY_PENALTY_CELLS)))
def test_the_protected_three_do_not_change_with_penalty_resolution_order(entry_order):
    """"The Shelter protects against the next three red rooms that I draft":
    with four red rooms drafted after the Shelter, the first three drafted are
    protected and the fourth is not, in every one of the six orders the three
    entry-triggered penalties can resolve in.

    The Maid's Chamber is drafted fourth yet resolves first of the four, so a
    Shelter that spent charges whenever a penalty happened to resolve would
    protect it and leave whichever of the other three resolved last exposed --
    a different answer per order. Parametrizing the order is what turns that
    into a proof rather than one lucky arrangement.
    """
    g = _shelter_at_the_doorstep()
    g.state.coins = 5
    g.state.steps = 40
    for room_id, cell in ENTRY_PENALTY_CELLS.items():
        g._place_room(g.registry.by_id[room_id], cell, 0)

    luck_before = g.state.luck
    g._place_room(g.registry.by_id["maids_chamber"], MAIDS_CHAMBER_CELL, 0)
    assert g.state.luck == luck_before - ANTI_LUCK, (
        "the fourth red room drafted is unprotected even though its penalty "
        "is the first of the four to resolve"
    )

    coins_before, steps_before = g.state.coins, g.state.steps
    for room_id in entry_order:
        cell = ENTRY_PENALTY_CELLS[room_id]
        g.state.pos = cell
        g._enter(cell)

    assert g.state.coins == coins_before, "the Chapel's coin penalty was negated"
    assert g.state.steps == steps_before, "the Gymnasium's step penalty was negated"
    assert g.state.darkroom_lights_on, "the Darkroom's fuse was negated"


def test_the_charges_are_claimed_at_draft_time_by_the_rooms_that_hold_them():
    """Each of the first three red rooms drafted after the Shelter takes one
    charge at its own draft, naming itself in ``shelter_protected_ids``; the
    fourth takes none.

    Reading the claim directly is what pins the mechanism the ordering proof
    above rests on: the three protected rooms are identified at draft time, so
    nothing later can reassign them.
    """
    g = _shelter_then_four_red_rooms()
    assert g.shelter_protected_ids == {"chapel", "gymnasium", "darkroom"}, (
        "the first three drafted hold their claims, none of which has resolved "
        "a penalty yet; the Maid's Chamber, drafted fourth, never had one"
    )
    assert g.red_negations == 0, "all three charges were claimed at draft time"


def test_the_shelter_claims_no_charge_for_its_own_draft():
    """The Shelter is a blueprint room, not a red one, so drafting it leaves
    all three charges unclaimed and nothing protected -- it cannot spend a
    charge on itself and shorten its own protection to two rooms."""
    g = _shelter_at_the_doorstep()
    assert not g.registry.by_id["shelter"].is_category("red")
    assert g.red_negations == 3
    assert g.shelter_protected_ids == set()


def test_a_red_room_drafted_before_the_shelter_never_holds_a_charge():
    """"It has no effect on rooms I have already drafted": a red room on the
    board before the Shelter is drafted is never offered a charge, so it is
    absent from ``shelter_protected_ids`` while all three charges stay
    unclaimed for rooms drafted later."""
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=0)
    g._place_room(g.registry.by_id["gymnasium"], 7, 0)
    g.open_outer_draft()
    g.choose(0)
    assert g.drafted_outer_room is not None and g.drafted_outer_room.id == "shelter", (
        "setup: seed 0 must deal the Shelter"
    )
    assert "gymnasium" not in g.shelter_protected_ids
    assert g.red_negations == 3


def test_a_shelter_claim_does_not_survive_the_day():
    """A claim is scoped to the day that made it: ``Game.reset`` starts the
    next day with no protected rooms and no charges, so protection cannot ride
    the attempt wrap into a day whose Shelter was never drafted."""
    g = _shelter_then_four_red_rooms()
    assert g.shelter_protected_ids, "setup: claims exist to be cleared"
    g.reset()
    assert g.shelter_protected_ids == set()
    assert g.red_negations == 0
