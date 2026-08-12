"""Repellent: while held, can be spent to ban a room from the draft pool for
7 days (shops.use_repellent owns the ban bookkeeping; this module owns only
the held-fact query and the consume step).
"""

from __future__ import annotations

ITEM_ID = "repellent"


def held(state) -> bool:
    """True while at least one Repellent is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0


def consume(state) -> None:
    """Spends one Repellent (consumed, not returned to the spawn pool)."""
    from ...special_items import remove
    remove(state, ITEM_ID, consumed=True)
