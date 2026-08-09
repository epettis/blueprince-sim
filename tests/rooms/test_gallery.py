"""Gallery puzzle-reward grants.

The sim assumes the player solves every puzzle in a room they enter, so the
Gallery's art-naming puzzle chain (four solves, unlocking two chests) folds
into a single flat grant on first entry: 2 gems and 4 coins. Key 8 is a
separate guaranteed_in special-item spawn covered by
tests/test_item_persistence.py, not re-tested here.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` extra-item roll never
    fires, isolating the guaranteed grant from the ordinary luck pipeline.
    """
    g = Game(GameConfig(special_items=True), seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_gallery_entry_grants_two_gems_and_four_coins():
    """Entering the Gallery grants 2 gems and 4 coins, identically on every seed.

    The coins are an exact figure rather than a pile roll, so the totals carry
    no variance; sweeping seeds is what distinguishes the two."""
    cell = 5
    for seed in range(30):
        g = _make_game_with_room("gallery", cell, seed=seed)
        gems_before, coins_before = g.state.gems, g.state.coins

        g._enter(cell)
        assert g.state.gems == gems_before + 2, f"seed {seed}: gems"
        assert g.state.coins == coins_before + 4, f"seed {seed}: coins"


def test_gallery_entry_grants_once_only():
    """The Gallery's gem/coin grant fires only on first entry; Game._enter is idempotent."""
    cell = 5
    g = _make_game_with_room("gallery", cell)
    g._enter(cell)
    gems_after_first, coins_after_first = g.state.gems, g.state.coins

    g._enter(cell)  # second call — must be a no-op
    assert g.state.gems == gems_after_first, "re-entering Gallery must not grant gems again"
    assert g.state.coins == coins_after_first, "re-entering Gallery must not grant coins again"
