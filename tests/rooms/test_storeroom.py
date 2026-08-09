"""Storeroom guaranteed items, for the base room and its three upgrade variants.

Nothing is inherited through ``variant_of``, so each record states its own
key/gem/coin counts and each is pinned separately here. The coin entries differ
in kind: ``storeroom__ix146`` grants a literal amount, while the base room and
the other two variants grant coin PILES whose sizes roll per pile.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game

PILE_MIN, PILE_MAX = 1, 5


def _game_with_room(room_id: str, cell: int, seed: int = 0, **cfg_kwargs) -> Game:
    """Return a Game with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` extra-item roll never
    fires, keeping the guaranteed-item assertions deterministic.
    """
    g = Game(GameConfig(**cfg_kwargs), seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_storeroom_ix144_grants_two_keys_one_gem_one_coin():
    """storeroom__ix144 grants +2 keys, +1 gem and one coin pile on first entry.

    The coin assertion is a lower bound because the pile size rolls."""
    cell = 5
    g = _game_with_room("storeroom__ix144", cell, special_items=True)
    keys0, gems0, coins0 = g.state.keys, g.state.gems, g.state.coins

    g._enter(cell)
    assert g.state.keys == keys0 + 2
    assert g.state.gems == gems0 + 1
    assert g.state.coins > coins0


def test_storeroom_ix145_grants_one_key_two_gems_one_coin():
    """storeroom__ix145 grants +1 key, +2 gems and one coin pile on first entry.

    The coin assertion is a lower bound because the pile size rolls."""
    cell = 5
    g = _game_with_room("storeroom__ix145", cell, special_items=True)
    keys0, gems0, coins0 = g.state.keys, g.state.gems, g.state.coins

    g._enter(cell)
    assert g.state.keys == keys0 + 1
    assert g.state.gems == gems0 + 2
    assert g.state.coins > coins0


def test_storeroom_ix146_entry_grants_exactly_10_coins_every_seed():
    """storeroom__ix146 grants a literal 10 coins on entry, identically on every seed.

    Swept across seeds because the property is the absence of variance: a pile
    roll would land on a range instead of a single value."""
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("storeroom__ix146", cell, seed=seed)
        g._enter(cell)
        assert g.state.coins == 10, f"seed {seed}: expected exactly 10 coins, got {g.state.coins}"


def test_base_storeroom_coins_still_roll_a_pile_range():
    """The base Storeroom's coin entry is a pile, so its payout is a distribution.

    Asserts every seed lands within the pile range and that at least two totals
    appear, which distinguishes a live roll from a value pinned by accident."""
    cell = 5
    totals = set()
    for seed in range(1, 31):
        g = _game_with_room("storeroom", cell, seed=seed)
        g._enter(cell)
        assert PILE_MIN <= g.state.coins <= PILE_MAX, (
            f"seed {seed}: coins {g.state.coins} outside pile range {PILE_MIN}-{PILE_MAX}")
        totals.add(g.state.coins)
    assert len(totals) >= 2, f"expected a spread of pile rolls across seeds, got only {totals}"
