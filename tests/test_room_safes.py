"""Gem-safe rooms grant +1 gem on entry.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3. That doctrine is why the Shelter is included
despite its real-time time-lock and the Boudoir despite its 1225 code
(owner decision, 2026-08-06): solving the lock is assumed, so both pay out.

The Boudoir's safe is a fixture of the room, so it survives every upgrade -
and room effects are NOT inherited through variant_of, so each variant record
carries the grant in its own right. That is what BOUDOIR_VARIANT_IDS pins.
"""

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import E, N, S

# Grid rooms: placed on the 5x9 grid and entered by walking.
SAFE_ROOM_IDS = ["office", "study", "drawing_room", "boudoir"]
# Upgrade variants of the Boudoir; each must keep the base room's safe.
BOUDOIR_VARIANT_IDS = ["boudoir__ix16", "boudoir__ix17", "boudoir__ix18"]


@pytest.mark.parametrize("room_id", SAFE_ROOM_IDS + BOUDOIR_VARIANT_IDS)
def test_entering_the_safe_room_grants_a_gem(registry, cfg, room_id):
    """Walking into a gem-safe room for the first time leaves the player with
    one more gem than before, regardless of which of the three rooms it is."""
    g = Game(cfg, seed=1)
    room = registry.by_id[room_id]
    g._place_room(room, 7, N | S)  # placed north of the Entrance Hall
    gems0 = g.state.gems
    g.move(N)
    assert g.state.pos == 7
    assert g.state.gems == gems0 + 1


@pytest.mark.parametrize("room_id", SAFE_ROOM_IDS + BOUDOIR_VARIANT_IDS)
def test_gem_grant_fires_only_on_first_entry(registry, cfg, room_id):
    """Leaving a gem-safe room and walking back in does not grant a second
    gem - the safe was already emptied on the first visit, same as any other
    ON_ENTER grant gated on ``state.entered``."""
    g = Game(cfg, seed=1)
    room = registry.by_id[room_id]
    g._place_room(room, 7, N | S)
    g.move(N)  # first entry: grants the gem
    gems_after_first_entry = g.state.gems
    g.move(S)  # step back into the Entrance Hall
    g.move(N)  # re-enter the safe room
    assert g.state.pos == 7
    assert g.state.gems == gems_after_first_entry


def test_study_still_offers_paid_redraws(registry, cfg):
    """Study's pre-existing study_redraws effect (spend a gem to redraw the
    drafting hand, up to 8 times) still fires alongside the new gem grant -
    guards against the grant being spliced in by replacing the effects list
    instead of appending to it."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["study"], 7, N | S)
    g.move(N)  # entering also banks the safe's gem
    assert g.state.study_placed  # study_redraws' ON_PLACE flag is still set
    g.open_door(7, N)
    assert g.phase is Phase.DRAFTING
    # Fund the redraw independently of the safe: otherwise deleting the grant
    # would fail this test merely for lack of a gem to spend, making it a
    # guard for the wrong property.
    g.state.gems += 1
    gems_before_redraw = g.state.gems
    g.redraw(RedrawKind.STUDY)
    assert g.state.gems == gems_before_redraw - 1  # redraw actually consumed a gem


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


def test_drawing_room_still_counts_as_a_drafting_room(registry, cfg):
    """Drawing Room's pre-existing counts_as_drafting_room effect still raises
    the house's drafting-room count (which the Classroom reads for its free
    redraws) - guards against the grant replacing rather than extending the
    effects list."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["classroom"], 1, E)  # west of the Entrance Hall
    count_with_classroom_only = g.state.drafting_room_count
    g._place_room(registry.by_id["drawing_room"], 7, N | S)
    assert g.state.drafting_room_count == count_with_classroom_only + 1
