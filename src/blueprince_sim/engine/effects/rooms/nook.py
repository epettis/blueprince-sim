"""Nook variants: the Breakfast Nook's free Bacon & Eggs and the Reading
Nook's guaranteed Library slot.

Both variants' "+1 key" half is already modelled by their own
``items.guaranteed`` entry (rooms.json); this module covers the half the
data schema cannot express. The Reading Nook's own half of the work --
forcing LIBRARY into slot 2 of every hand dealt from its doorway -- lives in
draft.py (``_reading_nook_library_option``), since it has to reach into the
slot-filling loop itself; nothing is registered for it here.

Implemented:
  - breakfast_nook__ix98 -- eats a free Bacon & Eggs on first entry: +10
    steps and a Morning Room added to today's draft pool, via the shared
    ``food.dishes.bacon_and_eggs`` record (items.json). Mirrors shops.py's
    ``buy()`` handling of the Kitchen's own copy of the same dish (eat_food,
    then inject_rooms, then satisfy morning_room's "breakfast" draft-condition
    gate) -- except this plate is free, so no coins move.

Not modelled:
  - reading_nook__ix99's Library forcing: see draft.py, not this module.
"""

from __future__ import annotations

from ... import special_items as si
from .. import Hook, room_hook

BACON_AND_EGGS_DISH = "bacon_and_eggs"
MORNING_ROOM_ID = "morning_room"
BREAKFAST_GATE_CONDITION = "breakfast"  # morning_room's draft_conditions gate


@room_hook("breakfast_nook__ix98", Hook.ON_ENTER)
def eat_free_bacon_and_eggs(game, room, ctx_room) -> None:
    """"The Breakfast Nook has a plate of Bacon & Eggs next to the key ...
    Unlike the Kitchen dish, the Breakfast Nook's Bacon & Eggs does not cost
    gold." (blueprince.wiki.gg/wiki/Nook/Upgrades)
    """
    si.eat_food(game, BACON_AND_EGGS_DISH, 1)
    game.inject_rooms([MORNING_ROOM_ID])
    game.state.special.extra_conditions.add(BREAKFAST_GATE_CONDITION)
