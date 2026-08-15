"""Showroom: registers its daily stock builder and the Trophy of Wealth
stock overlay.

The stock builder is registered via ``shops.register_stock_builder``, the
same shape ``commissary.py`` uses. The trophy -- previously a
``shop_id == "showroom"`` branch in both ``shops.stock_display`` (appending
it once every stored entry sells out) and ``shops.buy`` (granting it, since
it has no stored entry of its own) -- is registered via
``shops.register_stock_overlay`` instead: it returns one extra raw entry for
``stock_display`` to price and append through the same pipeline as every
stored entry, and ``buy`` grants any entry beyond the stored list the same
way regardless of which shop it came from.
"""

from __future__ import annotations

from ... import shops
from ... import special_items as si


def _roll_showroom(game, table: dict) -> None:
    """Pick 2 from tier_a + 2 from tier_b avoiding already-owned items."""
    state = game.state
    registry = game.registry

    entries = []
    for tier_key in ("tier_a", "tier_b"):
        tier = table.get(tier_key, [])
        available = [
            dict(raw, sold=0, kind="item")
            for raw in tier
            if si._is_available(state, raw["id"], registry)
        ]
        # Shuffle for uniform selection
        game.rng.shuffle("shop_stock", available)
        entries.extend(available[:2])

    state.shops.stock["showroom"] = entries


def _trophy_overlay(game, display: list[dict]) -> dict | None:
    """The Trophy of Wealth: offered once all 4 stored entries are sold out
    and the trophy itself is not already owned."""
    state = game.state
    registry = game.registry
    trophy_data = registry.shop_rules.shops.get("showroom", {}).get("trophy")
    if not trophy_data:
        return None
    if not si._is_available(state, trophy_data["id"], registry):
        return None
    if not all(d["sold_out"] for d in display):
        return None
    return {"id": trophy_data["id"], "kind": "item", "price": trophy_data["price"]}


shops.register_stock_builder("showroom", _roll_showroom)
shops.register_stock_overlay("showroom", _trophy_overlay)
