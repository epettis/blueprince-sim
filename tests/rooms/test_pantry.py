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


def test_pantry_entry_grants_exactly_one_fruit_every_seed():
    """The Pantry's fruit grant is exactly one dish's worth of steps.

    Luck is pinned to the floor so the room's additional_max=1 luck-rolled
    bonus item never fires, isolating the guaranteed fruit grant from an
    unrelated extra-item roll. The step delta must be one of the three known
    fruit values (apple=2, banana=3, orange=5) -- never 0 (no fruit) and
    never a value outside that set (e.g. a sum of two fruit).
    """
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("pantry", cell, seed=seed)
        g.state.luck = 0
        before = g.state.steps
        g._enter(cell)
        delta = g.state.steps - before
        assert delta in {2, 3, 5}, f"seed {seed}: expected a single fruit's steps, got {delta}"


def test_pantry_fruit_distribution_favors_apple():
    """Across many seeds, all three fruit appear and apple is the most common.

    Ordering is the observable the weights buy: a uniform roll across the
    three fruit would not produce an apple-heavy distribution, and the
    ordering survives editing the exact weights. 500 seeds gives a comfortable
    margin: apple lands around 240-250 hits versus banana's 150-160 and
    orange's 90-100, well clear of ties or reordering from sampling noise.
    """
    cell = 5
    counts = {2: 0, 3: 0, 5: 0}
    for seed in range(1, 501):
        g = _game_with_room("pantry", cell, seed=seed)
        g.state.luck = 0
        before = g.state.steps
        g._enter(cell)
        delta = g.state.steps - before
        counts[delta] += 1

    assert all(n > 0 for n in counts.values()), f"a fruit never appeared: {counts}"
    assert counts[2] > counts[3] > counts[5], (
        f"expected apple (2) > banana (3) > orange (5) in hit count, got {counts}"
    )
