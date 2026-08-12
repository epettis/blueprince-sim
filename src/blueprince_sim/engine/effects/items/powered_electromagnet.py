"""Powered Electromagnet: four effects while held, split across two systems.

Registered here as ``ItemCapability.ELECTROMAGNET``: biases drafting toward
the Mechanical Rooms plus the Rotunda (data/priority_draws.json's
'electromagnet' category-bias entry, gated by draft.py's
``electromagnet_active_from_state``).

Left as data tags on the item's own ``effects`` list in special_items.json
-- NOT part of this registry, out of scope for this migration:
- ``compass``: also activates the plain Compass's rotation bias (a tag
  shared with the Compass item, so it stays a multi-carrier data tag).
- ``auto_collect``: metal-detector-style spawn grant.
- ``locksmith_rob``: robs the Locksmith's 24 basic wall keys on approach.
"""

from .. import ItemCapability, item_provides

item_provides("powered_electromagnet", ItemCapability.ELECTROMAGNET)
