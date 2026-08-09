"""Schoolhouse: while placed, biases room draws toward the Classroom category.

The 8 Classroom copies it adds to today's draft pool are the room's
``inject_pool`` effect, still declared in data.
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("schoolhouse", Hook.ON_PLACE)
def mark_schoolhouse_placed(game, room, ctx_room) -> None:
    game.state.schoolhouse_placed = True
