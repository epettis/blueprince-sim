"""Trading Post: activating the outer-shop dead branch.

game.py's "fire ON_ENTER" path and shops.current_shop_id both special-case
``outer_room.category == "shop"`` (game.py:994, shops.py:359). Before this
room's category was corrected from the pool name "outer" to "shop", neither
branch could ever fire for any outer room -- Trading Post is the one outer
room whose real category is Shop, so it is the one outer room where these
branches now activate. Its own effect_text ("Counts as a Shop") and
data/shops.json (no "trading_post" table -- its trading rides the separate
"trading" graph) mean the newly-rolled stock is always empty: harmless, not a
crash and not a fake purchase list.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game

# Seed 1's outer-room hand deals exactly these three rooms (verified by
# construction): slot 0 trading_post, slot 1 tomb, slot 2 root_cellar.
OUTER_DRAFT_SEED = 1


def _draft_and_enter_outer(seed: int, slot: int, expected_id: str) -> Game:
    """Draft and walk into the outer room dealt at ``slot`` for ``seed``.

    special_items=True: game.py only fires special_items.on_enter (and, inside
    it, the outer-shop dead branch) when the special-items system is enabled.
    """
    g = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=seed)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == slot)
    room = g.registry.rooms[opt.room_idx]
    assert room.id == expected_id, "setup: seed/slot must deal the expected room"
    g.choose(slot)
    g.travel_to(room.id)
    assert g.state.outer_room_entered
    return g


def test_trading_post_activates_outer_shop_stock_roll():
    """Entering Trading Post now makes shops.current_shop_id resolve it and
    rolls (empty, harmless) stock -- both were unreachable while its category
    was "outer" instead of "shop"."""
    g = _draft_and_enter_outer(OUTER_DRAFT_SEED, 0, "trading_post")

    assert shops.current_shop_id(g) == "trading_post"
    assert g.state.shops.stock.get("trading_post") == [], (
        "Trading Post has no data/shops.json 'stock' table, so the rolled "
        "entry list must be empty rather than erroring"
    )
    assert shops.stock_for(g) == []


@pytest.mark.parametrize("slot,room_id", [(1, "tomb"), (2, "root_cellar")])
def test_non_shop_outer_rooms_do_not_activate_shop_stock(slot, room_id):
    """Tomb (blackprint) and Root Cellar (green) sit in the same outer hand as
    Trading Post but are not Shops: entering them must NOT resolve a
    current_shop_id or roll shop stock, proving the dead branch is keyed on
    the corrected category value, not on "any outer room"."""
    g = _draft_and_enter_outer(OUTER_DRAFT_SEED, slot, room_id)

    assert shops.current_shop_id(g) is None
    assert room_id not in g.state.shops.stock
