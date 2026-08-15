"""Commerce capability registry: which rooms provide it, and the sites that
query it instead of branching on room category or id.

Per docs/open_tasks.md task 21, the engine may not branch on a room id or
category to decide what a room does. commerce is the first capability: the
eleven rooms a player can buy, sell, trade, or fabricate at register
``Capability.COMMERCE`` via ``provides`` (engine/effects/rooms/commerce.py),
and the engine sites that decide commerce eligibility ask
``provides_capability(room_id, Capability.COMMERCE)`` instead of checking
``category == "shop"`` (plus the ``or room.id == "workshop"`` special case).
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.effects import Capability, provides_capability
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

# The eleven rooms registered in engine/effects/rooms/commerce.py: the eight
# shops.json shop rooms, the Trading Post and the Casino (both
# category == "shop" but absent from shops.json), and the Workshop
# (category == "blueprint").
COMMERCE_ROOM_IDS = (
    "bookshop",
    "casino",
    "commissary",
    "gift_shop",
    "kitchen",
    "laundry_room",
    "locksmith",
    "showroom",
    "the_armory",
    "trading_post",
    "workshop",
)


@pytest.mark.parametrize("room_id", COMMERCE_ROOM_IDS)
def test_commerce_room_provides_commerce(room_id):
    """Every room in shops.json's shops table, plus trading_post, workshop,
    and casino, is registered as providing Capability.COMMERCE.

    The Casino sells spins rather than goods: its stock is built by
    effects/rooms/casino.py's registered builder from data/casino.json, so
    buying an entry resolves a slot spin or a roulette tier instead of
    handing over an item. The Trading Post is the other shape, riding a
    separate tiered graph rather than shops.json stock. Both are registered
    because the category == "shop" check routes them through
    shops.on_enter_shop and shops.current_shop_id.
    """
    assert provides_capability(room_id, Capability.COMMERCE)


def test_ordinary_room_does_not_provide_commerce(registry):
    """A room with no commerce role (e.g. the Corridor) does not provide
    Capability.COMMERCE -- the registry is opt-in, not a default."""
    assert not provides_capability("corridor", Capability.COMMERCE)


def test_unregistered_room_id_returns_false_not_raise():
    """A room id that was never registered for any capability answers False
    rather than raising -- provides_capability must degrade gracefully for
    ids the registry (or a typo) doesn't know about."""
    assert provides_capability("not_a_real_room_id", Capability.COMMERCE) is False


# ---------------------------------------------------- wiring through Game

def _enter_room_from_entrance(game: Game, room_id: str, cell: int = 7) -> object:
    """Place ``room_id`` just north of the Entrance Hall and walk into it.

    Drives the real ON_ENTER path (Game.move -> Game._enter), the same site
    game.py:1618 fires shops.on_enter_shop from, rather than calling
    shops.on_enter_shop directly -- this is what proves the wiring, not just
    the capability table.
    """
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, N | S)
    game.move(N)
    assert game.state.pos == cell
    return room


def test_entering_a_commerce_room_rolls_its_stock():
    """Walking into a commerce room (the Commissary) for the first time rolls
    its stock via Game.move, proving game.py's ON_ENTER site calls
    shops.on_enter_shop for a commerce-capable room rather than a
    category-keyed or id-keyed special case."""
    game = Game(GameConfig(special_items=True), seed=0)
    _enter_room_from_entrance(game, "commissary")

    assert "commissary" in game.state.shops.stock
    assert len(game.state.shops.stock["commissary"]) == 4


def test_entering_a_non_commerce_room_does_not_roll_stock():
    """Walking into an ordinary room (the Corridor) does not roll any shop
    stock -- the ON_ENTER site's commerce check stays negative for a room
    with no registration."""
    game = Game(GameConfig(special_items=True), seed=0)
    _enter_room_from_entrance(game, "corridor")

    assert game.state.shops.stock == {}


def test_current_shop_id_on_grid():
    """current_shop_id resolves an on-grid commerce room's id while the
    player stands in it, driven through Game.move rather than by placing
    state directly."""
    game = Game(GameConfig(special_items=True), seed=0)
    _enter_room_from_entrance(game, "commissary")

    assert shops.current_shop_id(game) == "commissary"


# Seed 1's outer-room hand deals trading_post at slot 0 (see
# tests/rooms/test_trading_post.py, which established this determinism).
_OUTER_DRAFT_SEED = 1


def test_current_shop_id_off_grid():
    """current_shop_id resolves the drafted outer room's id (Trading Post)
    once the player has walked into it off-grid, via Game's own outer-draft
    and travel API rather than by poking state directly."""
    game = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=_OUTER_DRAFT_SEED)
    pending = game.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 0)
    room = game.registry.rooms[opt.room_idx]
    assert room.id == "trading_post", "setup: seed 1 slot 0 must deal Trading Post"
    game.choose(0)
    game.travel_to("trading_post")

    assert game.state.outer_room_entered
    assert shops.current_shop_id(game) == "trading_post"
