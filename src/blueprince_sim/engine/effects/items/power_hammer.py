"""Power Hammer: while held, can break a sealed wall on first arrival -- the
grounds<->sealed_entrance<->basement area gate, the Weight Room's south
lever, and the Greenhouse's corner-layout wall all read this as a live "wall
breakable today" fact, on top of the permanent cfg/state flags that make an
already-broken wall stay broken.
"""

from __future__ import annotations

ITEM_ID = "power_hammer"


def held(state) -> bool:
    """True while at least one Power Hammer is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0
