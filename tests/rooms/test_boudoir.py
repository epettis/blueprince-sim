"""Boudoir's gem safe, including its upgrade variants.

See tests/rooms/test_office.py, test_study.py, test_drawing_room.py, and
test_shelter.py for the other gem-safe rooms.

The sim assumes every puzzle in an entered room gets solved, so the safe in
these rooms just hands over a gem the moment the player walks in - see
docs/open_tasks.md task 3. That doctrine is why the Boudoir is included
despite its 1225 code (owner decision): solving the lock is
assumed, so it pays out.

The Boudoir's safe is a fixture of the room, so it survives every upgrade -
and room effects are NOT inherited through variant_of, so each variant record
carries the grant in its own right. That is what BOUDOIR_VARIANT_IDS pins.

Each variant carries two grants: the safe, which is a fixture of the room, and
the variant's own bonus. So ix16 grants 2 gems, ix17 grants 1 gem and 2 dice,
and ix18 grants 4 gems. EXPECTED_GEMS/EXPECTED_DICE pin those totals.
"""

import pytest

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

# Upgrade variants of the Boudoir; each must keep the base room's safe.
BOUDOIR_VARIANT_IDS = ["boudoir__ix16", "boudoir__ix17", "boudoir__ix18"]
BOUDOIR_IDS = ["boudoir"] + BOUDOIR_VARIANT_IDS

# Net resource gain on first entry, per room id: the safe's gem plus the
# variant's own bonus.
EXPECTED_GEMS = {"boudoir": 1, "boudoir__ix16": 2, "boudoir__ix17": 1, "boudoir__ix18": 4}
EXPECTED_DICE = {"boudoir": 0, "boudoir__ix16": 0, "boudoir__ix17": 2, "boudoir__ix18": 0}


@pytest.mark.parametrize("room_id", BOUDOIR_IDS)
def test_entering_the_safe_room_grants_a_gem(registry, cfg, room_id):
    """First entry banks the safe for the Boudoir and for each of its upgrade
    variants, plus each variant's own upgrade bonus (gems or dice). A safe is
    a fixture of the room, and effects are NOT inherited through
    ``variant_of``, so every variant must carry the grant itself."""
    g = Game(cfg, seed=1)
    room = registry.by_id[room_id]
    g._place_room(room, 7, N | S)  # placed north of the Entrance Hall
    gems0, dice0 = g.state.gems, g.state.dice
    g.move(N)
    assert g.state.pos == 7
    assert g.state.gems == gems0 + EXPECTED_GEMS[room_id]
    assert g.state.dice == dice0 + EXPECTED_DICE[room_id]


@pytest.mark.parametrize("room_id", BOUDOIR_IDS)
def test_gem_grant_fires_only_on_first_entry(registry, cfg, room_id):
    """Leaving a gem-safe room and walking back in does not grant a second
    gem - the safe was already emptied on the first visit, same as any other
    ON_ENTER grant gated on ``state.entered``."""
    g = Game(cfg, seed=1)
    room = registry.by_id[room_id]
    g._place_room(room, 7, N | S)
    g.move(N)  # first entry: grants the gem (and any variant bonus)
    gems_after_first_entry = g.state.gems
    dice_after_first_entry = g.state.dice
    g.move(S)  # step back into the Entrance Hall
    g.move(N)  # re-enter the safe room
    assert g.state.pos == 7
    assert g.state.gems == gems_after_first_entry
    assert g.state.dice == dice_after_first_entry
