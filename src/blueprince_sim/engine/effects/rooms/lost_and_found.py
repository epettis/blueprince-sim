"""Lost & Found: registers the steal-and-draw capability special_items.py's
shared on_enter dispatcher keys off.

``special_items.on_enter`` reads ``Capability.LOST_AND_FOUND`` (via
``provides_capability``) to decide whether to run
``lost_and_found_on_enter`` -- see that function for the steal-then-draw
mechanic itself.
"""

from __future__ import annotations

from .. import Capability, provides

provides("lost_and_found", Capability.LOST_AND_FOUND)
