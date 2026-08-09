"""Greenhouse: while placed, biases room draws toward the green category."""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("greenhouse", Hook.ON_PLACE)
def mark_greenhouse_placed(game, room, ctx_room) -> None:
    game.state.greenhouse_placed = True
