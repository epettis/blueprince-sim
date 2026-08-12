"""Key 8: while held, satisfies the ``room8_key`` draft-condition gate. Not
consumed on use -- it stays in inventory, unlike Secret Garden Key which is
spent by ``on_place``.
"""

from __future__ import annotations

ITEM_ID = "key_8"


def held(state) -> bool:
    """True while at least one Key 8 is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0
