"""Emerald Bracelet: waives every gem cost while held."""

from .. import ItemCapability, ItemHook, item_capability_any, item_hook, item_provides

item_provides("emerald_bracelet", ItemCapability.EMERALD_BRACELET)


@item_hook("emerald_bracelet", ItemHook.GEM_COST)
def _waive_gem_cost(state, registry, room, cost):
    """Unconditional waiver: every gem cost is free while held."""
    if not item_capability_any(state, registry, ItemCapability.EMERALD_BRACELET):
        return None
    return 0
