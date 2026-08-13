"""The Axe: consumed at use to permanently remove one floorplan family's gem
cost. Unlike Repellent/Sledge Hammer, the discount it grants OUTLIVES the
item -- it is not a held-item modifier, so it does not register on
ItemHook.GEM_COST the way Emerald Bracelet/Hall Pass do (both of those chains
guard on the item still being held; registering the Axe there would mean a
handler that fires after its own item is gone). game.py::can_axe_room/
axe_room own the target validation and the permanent record
(GameState.axed_rooms); this module owns only the item id/tag and the
held/consume/cap primitives, the same split repellent.py gives its own item.
"""

from __future__ import annotations

ITEM_ID = "the_axe"
TAG = "axe_room"


def held(state) -> bool:
    """True while at least one Axe is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0


def consume(state) -> None:
    """Spends one Axe (consumed, not returned to the spawn pool)."""
    from ...special_items import remove
    remove(state, ITEM_ID, consumed=True)


def max_active(registry) -> int:
    """Max simultaneously-axed floorplan families.

    Published cap of 3, read from data (the_axe's own "axe_room" effect
    record's ``max_active`` param) rather than a Python constant, per the
    owner ruling that a published table belongs in special_items.json. Falls
    back to 3 if the record is missing or malformed, so a data regression
    degrades gracefully instead of crashing the cap check.
    """
    item = registry.special.by_id.get(ITEM_ID)
    if item is None:
        return 3
    eff = item.effect(TAG)
    return eff.param("max_active", 3) if eff is not None else 3
