"""Silver Spoon: doubles food step gains while held (applied after Salt
Shaker's flat +1 bonus -- see FOOD_STEPS_PIPELINE in special_items.py).
"""

from __future__ import annotations

from .. import ItemCapability, ItemHook, item_capability_any, item_hook, item_provides

item_provides("silver_spoon", ItemCapability.FOOD_MULTIPLIER)


@item_hook("silver_spoon", ItemHook.FOOD_STEP_BONUS)
def _double(state, registry, total):
    """Doubles the running food-step total."""
    if not item_capability_any(state, registry, ItemCapability.FOOD_MULTIPLIER):
        return None
    return total * 2
