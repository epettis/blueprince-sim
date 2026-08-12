"""Salt Shaker: adds a flat bonus (data: food_bonus.amount) to one food
item's step total, before the Silver Spoon's doubling (see
FOOD_STEPS_PIPELINE in special_items.py).
"""

from __future__ import annotations

from .. import ItemHook, item_hook


@item_hook("salt_shaker", ItemHook.FOOD_STEP_BONUS)
def _add_bonus(state, registry, total):
    """Adds the item's flat food_bonus amount to the running total."""
    if state.inventory.get("salt_shaker", 0) <= 0:
        return None
    item = registry.special.by_id.get("salt_shaker")
    e = item.effect("food_bonus") if item is not None else None
    if e is None:
        return None
    return total + e.param("amount", 0)
