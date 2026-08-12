"""Watering Can: fills its water charges to capacity on pickup, then
converts one stored charge into one gem on entering a green room while any
charge remains.

Both fire for effect (mutating state.special.water and state.gems directly)
rather than returning a value, so neither fits any of the six ItemHook
members; nothing else competes for either event. Called directly from
special_items._on_pickup and special_items.on_enter, the same direct-dispatch
shape as sleeping_mask.
"""

from __future__ import annotations

ITEM_ID = "watering_can"


def on_pickup(state, item) -> None:
    """Fills the Watering Can's water charges to capacity on pickup."""
    e = item.effect(ITEM_ID)
    if e is not None:
        state.special.water = e.param("capacity", 3)


def apply_on_enter(state, registry, room) -> None:
    """Converts one water charge to one gem on entering a green room, for
    the first held item carrying the tag, while any charge remains."""
    if not room.is_category("green"):
        return
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        if item.effect(ITEM_ID) is not None:
            if state.special.water > 0:
                state.special.water -= 1
                state.gems += 1
            break
