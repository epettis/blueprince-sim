"""Parlor gem-grant system.

Split out of the old test_vault_parlor.py -- see tests/rooms/test_vault.py
for the Vault Key deposit-box tests that used to share this file.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=seed)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_parlor_entry_grants_two_gems():
    """Entering a base Parlor grants exactly 2 gems on first entry via the guaranteed pipeline."""
    cell = 5
    g = _make_game_with_room("parlor", cell)
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 2


def test_parlor_entry_grants_once_only():
    """The Parlor gem grant fires only on the first entry; Game._enter is idempotent."""
    cell = 5
    g = _make_game_with_room("parlor", cell)
    g._enter(cell)
    gems_after_first = g.state.gems

    g._enter(cell)  # second call — must be a no-op
    assert g.state.gems == gems_after_first, "re-entering Parlor must not grant gems again"


def test_parlor_upgrade_ix108_grants_three_gems():
    """Entering parlor__ix108 ('3ð Prize' upgrade) grants exactly 3 gems on first entry.

    ix108 is identified as the gems upgrade by its datamined effect_text '3ð Prize'.
    """
    cell = 5
    g = _make_game_with_room("parlor__ix108", cell)
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 3


def test_parlor_upgrade_ix108_grants_once_only():
    """parlor__ix108 gem grant fires only on first entry; Game._enter is idempotent."""
    cell = 5
    g = _make_game_with_room("parlor__ix108", cell)
    g._enter(cell)
    gems_after_first = g.state.gems

    g._enter(cell)  # second call — must be a no-op
    assert g.state.gems == gems_after_first, "re-entering parlor__ix108 must not grant gems again"


# --------------------------------------------------------- Funeral Parlor


def test_funeral_parlor_alone_grants_one_gem():
    """With only itself placed, funeral_parlor__ix110 grants 1 gem: its own
    record is category "red", so the count is never zero."""
    cell = 5
    g = _make_game_with_room("funeral_parlor__ix110", cell)
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 1


def test_funeral_parlor_counts_every_red_room_in_the_house():
    """Adding two more Red Rooms besides the Funeral Parlor itself raises the
    grant to 3 gems -- the count is taken at entry, not at draft time."""
    cell = 5
    g = _make_game_with_room("funeral_parlor__ix110", cell)
    chapel = g.registry.by_id["chapel"]
    g.state.grid[6] = chapel.idx
    g.state.placed_doors[6] = chapel.door_mask
    lavatory = g.registry.by_id["lavatory"]
    g.state.grid[7] = lavatory.idx
    g.state.placed_doors[7] = lavatory.door_mask
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 3


def test_funeral_parlor_counts_aquarium_as_red():
    """An Aquarium counts toward the Red Room total: it is every colour, via
    Room.is_category("red"), not the primary "category" field."""
    cell = 5
    g = _make_game_with_room("funeral_parlor__ix110", cell)
    aquarium = g.registry.by_id["aquarium"]
    g.state.grid[6] = aquarium.idx
    g.state.placed_doors[6] = aquarium.door_mask
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 2


def test_funeral_parlor_prize_capped_at_sixteen_gems():
    """The prize gem count never exceeds 16, the box's physical limit, even
    with far more than 16 Red Rooms on the grid."""
    cell = 5
    g = _make_game_with_room("funeral_parlor__ix110", cell)
    lavatory = g.registry.by_id["lavatory"]
    for other_cell in range(45):
        if other_cell != cell and g.state.grid[other_cell] < 0:
            g.state.grid[other_cell] = lavatory.idx
            g.state.placed_doors[other_cell] = lavatory.door_mask
    gems_before = g.state.gems

    g._enter(cell)
    assert g.state.gems == gems_before + 16


def test_funeral_parlor_grants_once_only():
    """The Funeral Parlor's gem grant fires only on first entry."""
    cell = 5
    g = _make_game_with_room("funeral_parlor__ix110", cell)
    g._enter(cell)
    gems_after_first = g.state.gems

    g._enter(cell)  # second call — must be a no-op
    assert g.state.gems == gems_after_first, (
        "re-entering the Funeral Parlor must not grant gems again"
    )
