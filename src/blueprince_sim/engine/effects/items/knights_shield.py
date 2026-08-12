"""Knight's Shield: negates the first negative red-room effect each day,
once per day (simplification #6 in docs/special-items-design.md).
"""

from __future__ import annotations

from .. import ItemHook, item_hook


@item_hook("knights_shield", ItemHook.RED_ROOM_NEGATE)
def _negate(state, registry):
    """Spends the daily charge and negates, if it has not already been spent
    today and the item's own data record still carries either tag."""
    if state.inventory.get("knights_shield", 0) <= 0:
        return None
    item = registry.special.by_id.get("knights_shield")
    if item is None:
        return None
    if item.effect("mask_red_room") is None and item.effect("negate_red_once_per_day") is None:
        return None
    if state.special.shield_used:
        return None
    state.special.shield_used = True
    return True
