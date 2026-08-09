"""Rumpus Room exact coin grant (2026-08-09 ruling, docs/open_tasks.md).

effect_text states "+8 coins"; items.guaranteed used to spend that as 2 PILES
(each rolling 1-5), ranging 2-10 and averaging 6. This pins the fix: entering
the Rumpus Room now grants exactly 8 coins, unconditional on RNG.
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


def test_rumpus_room_entry_grants_exactly_8_coins_every_seed():
    """The Rumpus Room's guaranteed grant is a literal 8 coins, not a 2-10 pile roll.

    Luck is pinned to the floor so the room's additional_max=1 luck-rolled
    bonus item never fires, isolating the guaranteed coins_exact grant from an
    unrelated (and still probabilistic) extra-item roll. Checked across many
    seeds because under the old pile-roll code this ranged 2-10.
    """
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("rumpus_room", cell, seed=seed)
        g.state.luck = 0
        g._enter(cell)
        assert g.state.coins == 8, f"seed {seed}: expected exactly 8 coins, got {g.state.coins}"
