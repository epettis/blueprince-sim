"""Sleeping Mask: grants steps on entering a bedroom room (including Bunk
Room, whose ``counts_as_bedrooms`` tag doubles the amount).

Fires for effect (mutates state.steps directly) rather than returning a
value, so it does not fit any of the six ItemHook members -- those all
arbitrate a returned cost/bonus/negation between competing items, and
nothing else competes for this event. Called directly from
special_items.on_enter, the same shape game.py already uses to dispatch to
a specific room module (dovecote, foyer, ...) when no generic hook fits.
"""

from __future__ import annotations

ITEM_ID = "sleeping_mask"


def apply_on_enter(state, registry, room) -> None:
    """Grants Sleeping Mask steps once, for the first held item carrying the
    tag, on entering a bedroom room."""
    if not room.is_category("bedroom"):
        return
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect(ITEM_ID)
        if e is None:
            continue
        steps_per = e.param("steps", 5)
        bed_count_effect = next(
            (ef for ef in room.effects if ef.tag == "counts_as_bedrooms"), None)
        amount = bed_count_effect.param("amount", 1) if bed_count_effect is not None else 1
        state.steps += steps_per * amount
        break  # only one sleeping mask can be held (unique)
