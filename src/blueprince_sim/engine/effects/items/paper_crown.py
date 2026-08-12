"""Paper Crown: while held, an initial deal where every option is a visible
non-red room earns one extra redraw. Hidden options count as potentially
red (no bonus if any option is hidden).

None of the six ItemHook members fits this event (an initial hand being
dealt is not a cost, a coin grant, or a red-room negation), and only this
one item answers it -- no arbitration is needed, so this stays a plain
predicate the caller queries directly rather than a new ItemHook chain.
"""

from __future__ import annotations

ITEM_ID = "paper_crown"


def bonus_redraw(state, registry, pending) -> bool:
    """True when the current deal earns Paper Crown's +1 redraw."""
    if state.inventory.get(ITEM_ID, 0) <= 0:
        return False
    if any(o.hidden for o in pending.options):
        return False
    return all(not registry.rooms[o.room_idx].is_category("red") for o in pending.options)
