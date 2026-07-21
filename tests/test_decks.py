"""Deck (solitaire) semantics and pool construction."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import build_decks, eligible_pool
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState


def test_deal_no_repeat_until_depletion():
    deck = DeckState(order=[1, 2, 3, 4, 5])
    dealt = [deck.deal_next(lambda c: True) for _ in range(5)]
    assert sorted(dealt) == [1, 2, 3, 4, 5]
    assert deck.deal_next(lambda c: True) is None  # depleted
    deck.reshuffle(lambda lst: None)
    assert deck.deal_next(lambda c: True) in (1, 2, 3, 4, 5)


def test_deal_respects_predicate_and_preserves_skipped():
    deck = DeckState(order=[1, 2, 3])
    assert deck.deal_next(lambda c: c == 3) == 3
    # 3 was swapped behind the cursor; 1 and 2 still dealable
    remaining = {deck.deal_next(lambda c: True) for _ in range(2)}
    assert remaining == {1, 2}


def test_reshuffle_drops_filtered():
    deck = DeckState(order=[1, 2, 3, 4])
    deck.reshuffle(lambda lst: None, drop={2, 4})
    assert sorted(deck.order) == [1, 3]
    assert deck.pos == 0


def test_pool_respects_unlock_config(registry):
    base = {r.id for r in eligible_pool(registry, GameConfig())}
    assert "solarium" not in base
    assert "locker_room" not in base       # pool_temp: only via The Pool
    assert "tomb" not in base              # outer rooms never in normal decks
    assert "entrance_hall" not in base
    assert "antechamber" not in base
    assert "closet" in base
    assert "bookshop" in base              # library-gated at deal time, not pool time

    with_solarium = {r.id for r in eligible_pool(
        registry, GameConfig(studio_additions=frozenset({"solarium"})))}
    assert "solarium" in with_solarium


def test_upgrade_variant_replaces_base(registry):
    # Boudoir dice variant (internal index 17) replaces the base Boudoir.
    variant_id = "boudoir__ix17"
    assert variant_id in registry.by_id
    pool = {r.id for r in eligible_pool(
        registry, GameConfig(upgrade_disks=frozenset({variant_id})))}
    assert variant_id in pool
    assert "boudoir" not in pool


def test_deck_copies_and_build(registry):
    cfg = GameConfig()
    decks = build_decks(registry, cfg, Rng(0))
    assert len(decks) == 8
    total = sum(d.size() for d in decks)
    assert total == len(eligible_pool(registry, cfg))  # all copies=1 in base data
    # free/gem split is consistent
    for rarity_idx in range(4):
        free = decks[rarity_idx * 2]
        gem = decks[rarity_idx * 2 + 1]
        for card in free.order:
            assert registry.rooms[card].is_free
        for card in gem.order:
            assert not registry.rooms[card].is_free
