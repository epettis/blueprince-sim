"""Storeroom coin grants: one upgrade variant switched to an exact figure by the
2026-08-09 ruling (docs/open_tasks.md), the rest left on the original pile roll.

storeroom__ix146's effect_text states "+10 coins"; its items.guaranteed used to
spend that as a single PILE (rolling 1-5). This file pins the fix for ix146
and, separately, confirms the base Storeroom (whose effect_text has no exact
coin figure) still rolls a pile -- proving the exact-grant flag is opt-in, not
a change to the pile-roll default.
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


def test_storeroom_ix146_entry_grants_exactly_10_coins_every_seed():
    """storeroom__ix146's guaranteed grant is a literal 10 coins, not a 1-5 pile roll.

    Luck is pinned to the floor so the room's additional_max=1 luck-rolled
    bonus item never fires, isolating the guaranteed coins_exact grant from an
    unrelated (and still probabilistic) extra-item roll. Checked across many
    seeds because under the old pile-roll code this ranged 1-5.
    """
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("storeroom__ix146", cell, seed=seed)
        g.state.luck = 0
        g._enter(cell)
        assert g.state.coins == 10, f"seed {seed}: expected exactly 10 coins, got {g.state.coins}"


def test_base_storeroom_coins_still_roll_a_pile_range():
    """The base Storeroom (no exact coin figure in its effect_text) still rolls
    a 1-5 coin pile on entry -- the exact-grant flag is opt-in per room, not a
    blanket change to how "coins" behaves.

    Asserts both that every seed lands in [1, 5] and that at least two
    different totals appear across 30 seeds, proving this is still a
    distribution and not (accidentally) pinned to one value.
    """
    cell = 5
    totals = set()
    for seed in range(1, 31):
        g = _game_with_room("storeroom", cell, seed=seed)
        g.state.luck = 0  # isolate the guaranteed pile from the luck-rolled extra item
        g._enter(cell)
        assert 1 <= g.state.coins <= 5, f"seed {seed}: coins {g.state.coins} outside pile range 1-5"
        totals.add(g.state.coins)
    assert len(totals) >= 2, f"expected a spread of pile rolls across seeds, got only {totals}"
