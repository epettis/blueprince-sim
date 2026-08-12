"""Office's gem safe.

See tests/rooms/test_study.py, test_drawing_room.py, test_boudoir.py, and
test_shelter.py for the other gem-safe rooms.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S


def test_entering_the_safe_room_grants_a_gem(registry, cfg):
    """First entry into the Office banks its safe, leaving the player one gem
    up. The sim assumes the puzzle is solved, so entry alone is the trigger."""
    g = Game(cfg, seed=1)
    room = registry.by_id["office"]
    g._place_room(room, 7, N | S)  # placed north of the Entrance Hall
    gems0 = g.state.gems
    g.move(N)
    assert g.state.pos == 7
    assert g.state.gems == gems0 + 1


def test_gem_grant_fires_only_on_first_entry(registry, cfg):
    """Re-entering the Office grants nothing: the safe was emptied on the first
    visit, like every other ON_ENTER grant gated on ``state.entered``."""
    g = Game(cfg, seed=1)
    room = registry.by_id["office"]
    g._place_room(room, 7, N | S)
    g.move(N)  # first entry: grants the gem
    gems_after_first_entry = g.state.gems
    g.move(S)  # step back into the Entrance Hall
    g.move(N)  # re-enter the safe room
    assert g.state.pos == 7
    assert g.state.gems == gems_after_first_entry
