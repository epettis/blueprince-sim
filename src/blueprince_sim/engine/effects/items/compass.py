"""Compass: while held, biases the floorplan-orientation roll toward
north-facing doors -- the same fact ``ItemCapability.COMPASS_BIAS`` the
Powered Electromagnet also registers, since its own compass effect persists
while held (a genuine multi-carrier capability, not a single-item one).
"""

from __future__ import annotations

from .. import ItemCapability, item_provides

item_provides("compass", ItemCapability.COMPASS_BIAS)
