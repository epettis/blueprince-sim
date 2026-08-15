"""Dining Room: registers the room-identity capability its two behaviour
carve-outs both key off.

``engine/special_items.py``'s Main Course gate (``_maybe_serve_main_course``)
and ``engine/experiments.py``'s fireplace-rank rule (``_room_has_fireplace``)
each run the same "is this room the Dining Room, or an upgrade variant of it"
check -- reading ``Capability.DINING_ROOM`` (via ``provides_capability``,
matched on the room's own id or its ``variant_of`` so an upgrade variant
still qualifies) instead of comparing "dining_room" inline in each mechanism
is what lets one registration here answer both.
"""

from __future__ import annotations

from .. import Capability, provides

provides("dining_room", Capability.DINING_ROOM)
