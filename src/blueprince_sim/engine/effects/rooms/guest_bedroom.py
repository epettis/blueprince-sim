"""Guest Bedroom variants: the Geist Bedroom's Tomb-conditional dice.

Implemented:
  - geist_bedroom__ix69 -- +2 dice on first entry; +4 more (6 total) if a
    Tomb was already on the estate at the moment the Geist Bedroom was
    drafted -- a strict BEFORE ordering, not merely "on the estate today".
    Marked at ON_PLACE against whatever is already placed at that instant
    (mirroring the Closet-family adjacency check, effects/rooms/closet.py),
    then paid out at ON_ENTER (mirroring quest_bedroom.py's own
    mark-at-one-hook, pay-at-another shape).

Judgment call:
  - The wiki states only that the extra dice "spawns", not whether that
    happens at draft or on entry. This module grants at ON_ENTER, the same
    hook every other item/resource spawn in this room family uses
    (items.roll_room_items also fires at ON_ENTER) -- see the room_hook
    wiring below.

Not modelled here:
  - The base Guest Bedroom's +10 steps grant and its luck-rolled
    ``additional_max`` item slot are both removed for this variant directly
    in rooms.json (empty ``effects``, ``additional_max: 0``), not by any code
    in this module. With ``additional_max`` at 0, items.roll_room_items's
    luck-rolled loop never runs at all for this room, so luck (including the
    two-plus-items penalty) is never touched -- "luck ... does not get
    processed" falls out of that data change with no dedicated code path.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

GEIST_DICE_BASE = 2        # geist_bedroom__ix69's own effect_text: "+2[dice]"
GEIST_DICE_TOMB_BONUS = 4  # "...gain an additional 4[dice]" when TOMB is on the estate
TOMB_ID = "tomb"


@room_hook("geist_bedroom__ix69", Hook.ON_PLACE)
def mark_tomb_present(game, room, ctx_room) -> None:
    """Records whether a Tomb was already drafted at the instant this Geist
    Bedroom was placed -- "The additional 4 dice only spawns if the Tomb was
    drafted before the Geist Bedroom" (a draft-time snapshot, never
    re-checked later)."""
    cell = game.room_cells.get(room.id)
    if cell is not None and TOMB_ID in game.room_cells:
        game.state.geist_bedroom_tomb_cells.add(cell)


@room_hook("geist_bedroom__ix69", Hook.ON_ENTER)
def grant_dice(game, room, ctx_room) -> None:
    """"+2[dice] If you have TOMB on the estate today, gain an additional
    4[dice]." -- the Tomb bonus requires it to have been drafted first (see
    mark_tomb_present above)."""
    cell = game.room_cells.get(room.id)
    amount = GEIST_DICE_BASE
    if cell is not None and cell in game.state.geist_bedroom_tomb_cells:
        amount += GEIST_DICE_TOMB_BONUS
    _grant(game, "dice", amount)
