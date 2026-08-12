"""Moon Pendant: at day end, while held, carries two uniformly random
distinct held items (the pendant itself is eligible) into tomorrow's
starting_items, alongside the day's other carry channels.

Fires for effect (mutating the carry-result set the caller already builds)
rather than returning a value through any ItemHook, and nothing else
competes for the day-end carry draw, so it is called directly from
special_items.end_of_day_carry at its existing call site -- the same
direct-dispatch shape as watering_can and sleeping_mask.
"""

from __future__ import annotations

ITEM_ID = "moon_pendant"


def carry_over(state, rng, result: set[str]) -> None:
    """Adds the Moon Pendant's day-end carry picks to ``result`` in place.

    With 2 or fewer items held, every held item carries with no draw needed.
    Otherwise draws 2 distinct ids uniformly at random from the held set on
    the "moon_pendant_carry" rng substream.
    """
    if state.inventory.get(ITEM_ID, 0) <= 0:
        return
    held_ids = sorted(iid for iid, cnt in state.inventory.items() if cnt > 0)
    if len(held_ids) <= 2:
        result.update(held_ids)
        return
    indices = list(range(len(held_ids)))
    rng.shuffle("moon_pendant_carry", indices)
    result.add(held_ids[indices[0]])
    result.add(held_ids[indices[1]])
