"""Running Shoes: every n-th move (``free_move_interval.n`` in data, 3) costs
no step counter, for as long as it is held.
"""

from __future__ import annotations

from .. import ItemHook, item_hook


@item_hook("running_shoes", ItemHook.MOVE_STEP_COST)
def _cadence_move(state, registry, from_cell, direction, to_room):
    """Every n-th move is free; every other move costs 1 and still advances
    the cadence counter -- unlike the other MOVE_STEP_COST items, this one
    always decides the outcome once held, never declining with None."""
    if state.inventory.get("running_shoes", 0) <= 0:
        return None
    item = registry.special.by_id.get("running_shoes")
    e = item.effect("free_move_interval") if item is not None else None
    if e is None:
        return None
    n = e.param("n", 3)
    if (state.special.moves_since_free + 1) % n == 0:
        state.special.moves_since_free = 0
        return 0
    state.special.moves_since_free += 1
    return 1
