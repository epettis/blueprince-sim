"""Boiler Room: entering it permanently opens the "boiler_room_steam" gate
(Underpass -> Upper Rotating Gear, see docs/areas.md).
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("boiler_room", Hook.ON_ENTER)
def open_steam_gate(game, room, ctx_room) -> None:
    game.state.boiler_room_steam = True
