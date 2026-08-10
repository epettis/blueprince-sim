"""Hallway upgrade variant guaranteed items, plus the Tomorrow Hallway's
cross-day extra-copy carry.

``hallway__ix74`` grants 1 key on first entry. Items are not inherited through
``variant_of``, so the variant carries its own ``items.guaranteed`` entry
rather than picking up the base Hallway's.
"""

from __future__ import annotations

from dataclasses import replace

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.env.multiday import DayChain


def test_hallway_ix74_grants_one_key():
    """hallway__ix74 ("+1 key") grants exactly 1 key on first entry.

    Luck is floored so its additional_max luck-rolled extra item never
    procs, keeping the guaranteed-key assertion deterministic."""
    cell = 5
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=0)
    g.state.luck = 0
    room = g.registry.by_id["hallway__ix74"]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1


# --------------------------------------------------------- Tomorrow Hallway


def test_tomorrow_hallway_draft_carries_one_extra_hallway_via_daychain():
    """Drafting one hallway__ix76 today carries exactly one extra Hallway
    copy into tomorrow's GameConfig.hallway_tomorrow_extra, driven end-to-end
    through DayChain (Game.carryover() -> DayChain.advance() -> next_config())."""
    chain = DayChain(GameConfig(), n_days=200)
    g = Game(chain.next_config(), seed=0)
    room = g.registry.by_id["hallway__ix76"]
    g._place_room(room, 7, room.door_mask)

    chain.advance(g.carryover())

    assert chain.next_config().hallway_tomorrow_extra == 1


def test_tomorrow_hallway_drafted_twice_carries_two():
    """Drafting two hallway__ix76 copies the same day is cumulative: it
    carries two extra Hallways, not one."""
    chain = DayChain(GameConfig(), n_days=200)
    g = Game(chain.next_config(), seed=0)
    room = g.registry.by_id["hallway__ix76"]
    g._place_room(room, 6, room.door_mask)
    g._place_room(room, 7, room.door_mask)

    chain.advance(g.carryover())

    assert chain.next_config().hallway_tomorrow_extra == 2


def test_tomorrow_hallway_carry_injects_extra_copies_into_the_pool(registry, cfg):
    """GameConfig.hallway_tomorrow_extra actually lands that many extra
    Hallway cards in the following day's decks, via the Entrance Hall's own
    ON_PLACE hook firing at day start (independent of GameConfig.special_items)."""
    hallway = registry.by_id["hallway"]
    baseline = Game(cfg, seed=5)
    baseline_deck = baseline.state.deck(hallway.rarity_idx, not hallway.is_free)
    baseline_count = baseline_deck.order.count(hallway.idx)

    carried_cfg = replace(cfg, hallway_tomorrow_extra=2)
    g = Game(carried_cfg, seed=5)
    deck = g.state.deck(hallway.rarity_idx, not hallway.is_free)

    assert deck.order.count(hallway.idx) == baseline_count + 2 * hallway.deck_copies


def test_tomorrow_hallway_carry_resets_on_daychain_attempt_wrap():
    """The carried count does not survive a DayChain attempt wrap -- a fresh
    attempt starts with no Tomorrow Hallway bonus pending."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"hallway_tomorrow_extra": 3})   # day 1 -> day 2
    chain.advance({})                              # day 2 -> wraps to day 1

    assert chain.next_config().hallway_tomorrow_extra == 0
