"""Boiler Room: a steam-power source, and entering it permanently opens the
"boiler_room_steam" gate (Underpass -> Upper Rotating Gear, see docs/areas.md).

Two separate mechanisms on two separate edges. ``Capability.POWER_SOURCE``
seeds ``engine/power.py``'s propagation from wherever this room is placed
(docs/power.md); the gate below is an owner-ruled one-time unlock that needs no
power at all.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

provides("boiler_room", Capability.POWER_SOURCE)


@room_hook("boiler_room", Hook.ON_ENTER)
def open_steam_gate(game, room, ctx_room) -> None:
    game.state.boiler_room_steam = True
