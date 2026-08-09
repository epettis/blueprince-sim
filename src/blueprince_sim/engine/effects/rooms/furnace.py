"""Furnace: while placed, biases room draws toward the red category."""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("furnace", Hook.ON_PLACE)
def mark_furnace_placed(game, room, ctx_room) -> None:
    game.state.furnace_placed = True
