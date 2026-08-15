"""Laboratory: registers the Experimental Setup terminal capability.

``Capability.EXPERIMENT_TERMINAL`` is read by ``Game.at_laboratory_terminal``
to gate the Experimental Setup menu (``can_start_setup`` and the rest of the
experiment-configuration actions) to this room -- the same shape as the
Planetarium's Telescope-reveal capability (``effects/rooms/planetarium.py``):
both terminals are single-room mechanics with no shared tag handler to hang
off, so a dedicated ``Capability`` replaces the room-id-literal check
``Game`` used to make directly.
"""

from __future__ import annotations

from .. import Capability, provides

provides("laboratory", Capability.EXPERIMENT_TERMINAL)
