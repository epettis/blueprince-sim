"""Pantry exact coin grant (2026-08-09 ruling, docs/open_tasks.md).

effect_text states "+4 coins"; items.guaranteed used to spend that as a
single PILE (rolling 1-5), averaging 3 and sometimes falling short of 4. This
pins the fix: entering the Pantry now grants exactly 4 coins, unconditional
on RNG.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell``, not yet entered."""
    g = Game(GameConfig(), seed=seed)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_pantry_entry_grants_exactly_4_coins_every_seed():
    """The Pantry's guaranteed grant is a literal 4 coins, not a 1-5 pile roll.

    Luck is pinned to the floor so the room's additional_max=1 luck-rolled
    bonus item never fires, isolating the guaranteed coins_exact grant from an
    unrelated (and still probabilistic) extra-item roll. Checked across many
    seeds because under the old pile-roll code this ranged 1-5.
    """
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("pantry", cell, seed=seed)
        g.state.luck = 0
        g._enter(cell)
        assert g.state.coins == 4, f"seed {seed}: expected exactly 4 coins, got {g.state.coins}"
