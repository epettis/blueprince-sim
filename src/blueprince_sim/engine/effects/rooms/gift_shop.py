"""Gift Shop: registers its daily stock builder.

Registered via ``shops.register_stock_builder``, the same shape
``commissary.py`` uses.
"""

from __future__ import annotations

from ..items import lunch_box
from ... import shops


def _roll_gift_shop(game, table: dict) -> None:
    """Build the Gift Shop's stock, filtering one-time purchases by config."""
    state = game.state
    cfg = game.cfg

    entries = []
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        # Lunch Box: only when not already unlocked
        if lunch_box.hide_from_gift_shop(raw.get("id"), cfg):
            continue
        # cursed_coffers: only when not already unlocked
        if raw.get("id") == "cursed_coffers" and cfg.cursed_effigy_unlocked:
            continue
        entries.append(entry)

    state.shops.stock["gift_shop"] = entries


shops.register_stock_builder("gift_shop", _roll_gift_shop)
