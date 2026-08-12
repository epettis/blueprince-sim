"""Powered Electromagnet: four effects while held, split across two systems.

Registered here as two capabilities:
- ``ItemCapability.ELECTROMAGNET``: biases drafting toward the Mechanical
  Rooms plus the Rotunda (data/priority_draws.json's 'electromagnet'
  category-bias entry, gated by draft.py's
  ``electromagnet_active_from_state``).
- ``ItemCapability.COMPASS_BIAS``: the same north-bias-on-orientation-roll
  fact the Compass item registers (its own compass effect persists while
  held, same as the Compass's) -- see effects/items/compass.py.

Left as data tags on the item's own ``effects`` list in special_items.json
-- NOT part of this registry, out of scope for this migration:
- ``auto_collect``: metal-detector-style spawn grant.
- ``locksmith_rob``: robs the Locksmith's 24 basic wall keys on approach.
"""

from .. import ItemCapability, item_provides

item_provides("powered_electromagnet", ItemCapability.ELECTROMAGNET)
item_provides("powered_electromagnet", ItemCapability.COMPASS_BIAS)
