"""Secret Garden Key: while held, satisfies the ``secret_garden_key``
draft-condition gate (placement.py's own tag, named there as data), and is
consumed the moment the Secret Garden itself is placed -- at most one per
day; the key does not return to the spawn pool.
"""

from __future__ import annotations

ITEM_ID = "secret_garden_key"

SECRET_GARDEN_ROOM_ID = "secret_garden"


def held(state) -> bool:
    """True while at least one Secret Garden Key is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0


def consume_on_place(state, room_id: str) -> None:
    """Consumes a held Secret Garden Key when ``room_id`` is the Secret
    Garden itself, at the moment it is placed."""
    from ...special_items import has, remove
    if room_id == SECRET_GARDEN_ROOM_ID and has(state, ITEM_ID):
        remove(state, ITEM_ID, consumed=True)
