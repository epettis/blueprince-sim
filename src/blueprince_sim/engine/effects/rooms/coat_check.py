"""Coat Check: on entry, auto-stores the most valuable held item overnight.

Implemented:
  - on_enter -- delegates to special_items.coat_check_on_enter, which holds
    the storage bookkeeping (inventory tiering, the one-per-day guard) as a
    special-items subsystem concern rather than a room-module one. Fires
    before roll_room_items runs for this room, and before this room's own
    guaranteed items (if any) would be granted -- safe because the Coat
    Check has no items of its own in the luck-spawn pool and no items
    guaranteed in it, so nothing about that earlier firing is observable.

Not modelled:
  - Player choice of which item to store and when to retrieve it: the sim
    auto-stores the highest-tier held item and auto-returns it the next day
    (special_items.py's own simplification, documented in
    docs/special-items-behaviour.md).
"""

from __future__ import annotations

from ... import special_items as si
from .. import Hook, room_hook


@room_hook("coat_check", Hook.ON_ENTER)
def on_enter(game, room, ctx_room) -> None:
    """Store the best held item overnight; a no-op if one is already stored."""
    si.coat_check_on_enter(game)
