"""Boudoir's gem safe, including its upgrade variants.

Split out of the old test_room_safes.py, which covered every gem-safe room
(office, study, drawing_room, boudoir, shelter) in one file -- see
tests/rooms/test_office.py, test_study.py, test_drawing_room.py, and
test_shelter.py for the others.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3. That doctrine is why the Boudoir is included
despite its 1225 code (owner decision, 2026-08-06): solving the lock is
assumed, so it pays out.

The Boudoir's safe is a fixture of the room, so it survives every upgrade -
and room effects are NOT inherited through variant_of, so each variant record
carries the grant in its own right. That is what BOUDOIR_VARIANT_IDS pins.
"""

import pytest

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

# Upgrade variants of the Boudoir; each must keep the base room's safe.
BOUDOIR_VARIANT_IDS = ["boudoir__ix16", "boudoir__ix17", "boudoir__ix18"]
BOUDOIR_IDS = ["boudoir"] + BOUDOIR_VARIANT_IDS


@pytest.mark.parametrize("room_id", BOUDOIR_IDS)
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


@pytest.mark.parametrize("room_id", BOUDOIR_IDS)
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
