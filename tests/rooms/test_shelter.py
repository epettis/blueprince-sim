"""Shelter's gem safe and red-room negation.

Split out of the old test_room_safes.py, which covered every gem-safe room
(office, study, drawing_room, boudoir, shelter) in one file -- see
tests/rooms/test_office.py, test_study.py, test_drawing_room.py, and
test_boudoir.py for the others.

The sim assumes every puzzle in an entered room gets solved, so the safe in
this room just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3. That doctrine is why the Shelter is included
despite its real-time time-lock (owner decision, 2026-08-06): solving the
lock is assumed, so it pays out.
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game


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
    """The Shelter's pre-existing negate_red_rooms effect still fires alongside
    the new gem grant - the append-vs-replace guard for the one safe room whose
    effects list was not empty. The two ride DIFFERENT hooks (negation on
    ON_PLACE at draft time, the gem on ON_ENTER), so both are checked."""
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
