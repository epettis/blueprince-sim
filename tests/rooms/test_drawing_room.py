"""Drawing Room's gem safe and drafting-room count.

See tests/rooms/test_office.py, test_study.py, test_boudoir.py, and
test_shelter.py for the other gem-safe rooms.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/doctrine.md.
"""

from blueprince_sim.engine.game import Game, RedrawKind
from blueprince_sim.engine.grid import E, N, S


def test_entering_the_safe_room_grants_a_gem(registry, cfg):
    """First entry into the Drawing Room banks its safe, leaving the player one gem
    up. The sim assumes the puzzle is solved, so entry alone is the trigger."""
    g = Game(cfg, seed=1)
    room = registry.by_id["drawing_room"]
    g._place_room(room, 7, N | S)  # placed north of the Entrance Hall
    gems0 = g.state.gems
    g.move(N)
    assert g.state.pos == 7
    assert g.state.gems == gems0 + 1


def test_gem_grant_fires_only_on_first_entry(registry, cfg):
    """Re-entering the Drawing Room grants nothing: the safe was emptied on the first
    visit, like every other ON_ENTER grant gated on ``state.entered``."""
    g = Game(cfg, seed=1)
    room = registry.by_id["drawing_room"]
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


def test_drawing_room_grants_one_free_redraw_for_a_hand_dealt_from_its_door(registry, cfg):
    """Opening a doorway from the Drawing Room grants +1 redraws_left on that
    hand, independent of the Classroom's drafting_room_count grant - the
    owner's ruling ("one free reroll per door") names the Drawing Room's own
    doorway, not a day-scoped flag or a Classroom-style headcount."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["drawing_room"], 7, N | S)
    g.move(N)
    pending = g.open_door(7, N)
    assert pending.redraws_left == 1


def test_the_free_redraw_is_spent_by_a_redraw_of_the_same_door_and_not_replenished(registry, cfg):
    """The free redraw is a one-shot credit on this doorway's hand: spending it
    via RedrawKind.FREE leaves redraws_left at 0, and it does not top back up
    on its own for a second redraw of the SAME door (per door, not per
    redraw)."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["drawing_room"], 7, N | S)
    g.move(N)
    g.open_door(7, N)
    assert g.state.pending.redraws_left == 1
    g.redraw(RedrawKind.FREE)
    assert g.state.pending.redraws_left == 0


def test_a_second_doorway_from_the_drawing_room_the_same_day_grants_its_own_free_redraw(
        registry, cfg):
    """The grant is per door, not a once-per-day flag: a second doorway opened
    from the same placed Drawing Room later the same day gets its own fresh
    +1, unaffected by the first door's charge having already been spent."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["drawing_room"], 7, N | S | E)  # t-layout: 3 doors
    g.move(N)
    g.open_door(7, N)
    g.choose(0)  # place whatever slot 0 dealt, freeing the doorway
    second = g.open_door(7, E)
    assert second.redraws_left == 1
