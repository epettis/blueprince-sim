"""Master Key: opens any locked door for free while held -- no key is spent
and passability checks never budget a key for a door it can clear.
"""

from .. import ItemCapability, item_provides

item_provides("master_key", ItemCapability.MASTER_KEY)
