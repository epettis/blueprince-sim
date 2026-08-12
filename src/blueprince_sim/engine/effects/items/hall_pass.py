"""Hall Pass: hallway-to-hallway moves cost no step counter, and drafting a
hallway room from a hallway doorway costs no gem, for as long as it is held.

Both waivers share one context test -- is the room on each side of the
event a hallway room -- so it lives here as ``_hallway_from_hallway`` rather
than being hardcoded at each engine call site: the item, not the engine,
owns what "applicable" means for its own waiver (owner ruling, task 22
phase 4).
"""

from __future__ import annotations

from .. import ItemCapability, ItemHook, item_capability_any, item_hook, item_provides

item_provides("hall_pass", ItemCapability.FREE_HALLWAY_MOVES)


def _hallway_from_hallway(state, registry, from_cell: int, to_room) -> bool:
    """True when ``to_room`` is a hallway room and the room at ``from_cell``
    (if any) is also a hallway room."""
    if not to_room.is_category("hallway"):
        return False
    if from_cell < 0:
        return False
    from_idx = state.grid[from_cell]
    return from_idx >= 0 and registry.rooms[from_idx].is_category("hallway")


@item_hook("hall_pass", ItemHook.GEM_COST)
def _waive_gem_cost(state, registry, room, cost):
    """Waives the gem cost of drafting a hallway room from a hallway doorway."""
    if not item_capability_any(state, registry, ItemCapability.FREE_HALLWAY_MOVES):
        return None
    from_cell = state.pending.from_cell if state.pending is not None else -1
    if _hallway_from_hallway(state, registry, from_cell, room):
        return 0
    return None


@item_hook("hall_pass", ItemHook.MOVE_STEP_COST)
def _waive_move_step_cost(state, registry, from_cell, direction, to_room):
    """Waives the step cost of a hallway-to-hallway move."""
    if not item_capability_any(state, registry, ItemCapability.FREE_HALLWAY_MOVES):
        return None
    if _hallway_from_hallway(state, registry, from_cell, to_room):
        return 0
    return None
