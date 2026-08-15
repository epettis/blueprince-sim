"""Utility Closet: registers the breaker box capability.

``Capability.BREAKER_BOX`` is read by ``Game._capability_cell`` (via
``Game._utility_closet_cell``) to resolve the breaker box's grid cell
generically, without ``game.py`` naming this room's id directly. The
Keycard Entry switch, the Darkroom fuse switch, and the Garage-route
security-door shortcut all gate on standing at that cell.
"""

from __future__ import annotations

from .. import Capability, provides

provides("utility_closet", Capability.BREAKER_BOX)
