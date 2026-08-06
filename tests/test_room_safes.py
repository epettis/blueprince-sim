"""Gem-safe rooms: Office, Study, and Drawing Room grant +1 gem on entry.

The sim assumes every puzzle in an entered room gets solved, so the
permanently-open safe in these three rooms just hands over a gem the moment
the player walks in - see docs/open_tasks.md task 3.
"""

import pytest

from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import E, N, S

SAFE_ROOM_IDS = ["office", "study", "drawing_room"]


@pytest.mark.parametrize("room_id", SAFE_ROOM_IDS)
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


@pytest.mark.parametrize("room_id", SAFE_ROOM_IDS)
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
