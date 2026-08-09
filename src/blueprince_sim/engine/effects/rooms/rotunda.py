"""Rotunda: grants free floorplan rotation for as long as it is on the grid --
unlike the Dovecote (see dovecote.py), the grant rides being PLACED, not being
drawn into the current hand.
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("rotunda", Hook.ON_PLACE)
def mark_rotunda_placed(game, room, ctx_room) -> None:
    game.rotunda_placed = True
