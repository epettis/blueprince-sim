"""Drawing Room's gem safe and drafting-room count.

Split out of the old test_room_safes.py, which covered every gem-safe room
(office, study, drawing_room, boudoir, shelter) in one file -- see
tests/rooms/test_office.py, test_study.py, test_boudoir.py, and
test_shelter.py for the others.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3.
"""

import pytest

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, S


@pytest.mark.parametrize("room_id", ["drawing_room"])
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


@pytest.mark.parametrize("room_id", ["drawing_room"])
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
