"""Conference Room: registers the capability the Spread Dig Spots experiment
effect's cell lookup keys off.

``experiments._apply_spread_dig_spots`` resolves this room's cell via
``Game._capability_cell(Capability.DIG_SPOTS)`` (itself backed by
``effects.rooms_with_capability``) instead of looking up "conference_room"
directly in ``game.room_cells`` -- see that function's own docstring for the
dig-spot mechanic.
"""

from __future__ import annotations

from .. import Capability, provides

provides("conference_room", Capability.DIG_SPOTS)
