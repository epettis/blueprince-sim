"""Pool Hall (an upgrade variant of the Billiard Room): injects the Great
Hall, Foyer and Secret Passage into today's draft pool.

Restored per the room fidelity audit (docs/open_tasks.md task 15) -- the
variant's ``effects`` list had regressed to empty. This is the highest-value
fix in the audit: the Great Hall is an Antechamber lever room, and the
project measured victory as structurally unreachable on ~89% of days for
lack of lever rooms. Mirrors The Pool's already-working ``inject_pool``
pattern (see tests/rooms/test_the_pool.py).
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game


def test_pool_hall_injects_lever_rooms(registry, cfg):
    """Placing Pool Hall injects one copy each of the Great Hall, Foyer and
    Secret Passage into the day's draft decks, growing total deck size by 3."""
    g = Game(cfg, seed=2)
    pool_hall = registry.by_id["pool_hall__ix12"]
    sizes0 = [d.size() for d in g.state.decks]
    g._place_room(pool_hall, 7, 4)
    sizes1 = [d.size() for d in g.state.decks]
    assert sum(sizes1) == sum(sizes0) + 3  # great hall, foyer, secret passage


def test_pool_hall_injected_rooms_are_actually_draftable(registry, cfg):
    """The injected Great Hall becomes a real, drawable card: its room index
    appears in the deck matching its rarity/free-gem class after injection,
    not just an effect tag with no observable consequence."""
    g = Game(cfg, seed=2)
    pool_hall = registry.by_id["pool_hall__ix12"]
    great_hall = registry.by_id["great_hall"]
    deck = g.state.deck(great_hall.rarity_idx, not great_hall.is_free)
    count_before = deck.order.count(great_hall.idx)

    g._place_room(pool_hall, 7, 4)

    count_after = deck.order.count(great_hall.idx)
    assert count_after == count_before + great_hall.deck_copies
