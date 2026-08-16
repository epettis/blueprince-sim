"""Laboratory: registers the Experimental Setup terminal capability, and
entering it permanently opens the "lab_visited" gate (Private Drive ->
Blackbridge Grotto, see docs/areas.md).

``Capability.EXPERIMENT_TERMINAL`` is read by ``Game.at_laboratory_terminal``
to gate the Experimental Setup menu (``can_start_setup`` and the rest of the
experiment-configuration actions) to this room -- the same shape as the
Planetarium's Telescope-reveal capability (``effects/rooms/planetarium.py``):
both terminals are single-room mechanics with no shared tag handler to hang
off, so a dedicated ``Capability`` replaces the room-id-literal check
``Game`` used to make directly.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

provides("laboratory", Capability.EXPERIMENT_TERMINAL)


@room_hook("laboratory", Hook.ON_ENTER)
def open_grotto_gate(game, room, ctx_room) -> None:
    game.state.lab_visited = True
