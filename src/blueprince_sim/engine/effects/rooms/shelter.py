"""Shelter: negates the effects of the next 3 red rooms."""

from __future__ import annotations

from .. import Hook, room_hook

NEGATIONS = 3


@room_hook("shelter", Hook.ON_PLACE)
def negate_next_red_rooms(game, room, ctx_room) -> None:
    game.red_negations += NEGATIONS
