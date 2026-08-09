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
