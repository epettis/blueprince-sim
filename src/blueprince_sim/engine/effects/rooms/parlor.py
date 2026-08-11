"""Funeral Parlor: prize gems scale with the house's Red Room count.

Implemented:
  - funeral_parlor__ix110 -- "The number of gems in the prize box is now
    equal to the number of Red Rooms in the house" (counted at the moment
    the box is opened, i.e. this room's own first entry, not at draft time).
    Counted via ``Room.is_category("red")`` rather than ``category == "red"``,
    so the Aquarium family (every colour) and the Funeral Parlor's own record
    (category "red") both count -- the latter is why the grant is never zero.
    Capped at 16, the physical limit on gems in the box.

Not modelled: the 30-step penalty for opening a non-prize box. The sim's
assumed-solved doctrine (the Parlor's box puzzle is always uniquely
solvable) means the box opened is always the prize box, so the penalty
never fires.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

MAX_PRIZE_GEMS = 16  # physical limit on gems the prize box can hold


def _red_room_count(game) -> int:
    """Count of rooms currently on the grid that count as category "red"."""
    registry = game.registry
    return sum(
        1 for room_idx in game.state.grid
        if room_idx >= 0 and registry.rooms[room_idx].is_category("red")
    )


@room_hook("funeral_parlor__ix110", Hook.ON_ENTER)
def grant_prize_gems_for_red_rooms(game, room, ctx_room) -> None:
    """Grants gems equal to the house's Red Room count, capped at 16."""
    amount = min(_red_room_count(game), MAX_PRIZE_GEMS)
    _grant(game, "gems", amount)
