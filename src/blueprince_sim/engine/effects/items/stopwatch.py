"""Stopwatch: once activated (on pickup, handled in special_items._on_pickup),
spends its ``free_costs`` charges on the next moves and/or gem payments,
whichever it is asked to cover first, until they run out. Also unobtainable
again today, including as a Trading Post return, once it has already run.
"""

from __future__ import annotations

from .. import ItemHook, item_hook

ITEM_ID = "stopwatch"


@item_hook("stopwatch", ItemHook.MOVE_STEP_COST)
def _free_move(state, registry, from_cell, direction, to_room):
    """Spends one charge to make this move free, while any remain."""
    if state.special.stopwatch_left > 0:
        state.special.stopwatch_left -= 1
        return 0
    return None


@item_hook("stopwatch", ItemHook.GEM_PAYMENT_WAIVER)
def _waive_gem_payment(state, registry, cost):
    """Spends one charge to waive a gem payment, if a charge remains and
    enough gems are in hand (the wiki: gems are kept, not spent)."""
    if state.special.stopwatch_left > 0 and state.gems >= cost:
        state.special.stopwatch_left -= 1
        return True
    return None


def blocks_as_trade_return(item, state) -> bool:
    """True once today's Stopwatch has already run: ``item`` (a trade-graph
    candidate, which may or may not be the Stopwatch) becomes untradeable as
    a return for the rest of the day."""
    return item.effect(ITEM_ID) is not None and state.special.stopwatch_used
