"""Greenhouse: while placed, biases room draws toward the green category, and
entering it while holding a Power Hammer permanently breaks its back wall --
revealing the corner-layout rotations gated behind Room.alt_layouts_gate
(engine/model.py, engine/placement.py). Same shape as the Weight Room's own
Power Hammer wall break (effects/rooms/weight_room.py): no player action
beyond arriving in the room while holding the item.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..items import power_hammer


@room_hook("greenhouse", Hook.ON_PLACE)
def mark_greenhouse_placed(game, room, ctx_room) -> None:
    game.state.greenhouse_placed = True


@room_hook("greenhouse", Hook.ON_ENTER)
def break_wall(game, room, ctx_room) -> None:
    if game.cfg.special_items and power_hammer.held(game.state):
        game.state.shops.greenhouse_wall_broken = True
