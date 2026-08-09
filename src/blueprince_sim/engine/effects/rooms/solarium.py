"""Solarium: while placed, drafting options 2 and 3 use flatter rarity odds."""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("solarium", Hook.ON_PLACE)
def mark_solarium_placed(game, room, ctx_room) -> None:
    game.state.solarium_placed = True
