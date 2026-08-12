"""Lucky Purse: doubles every coin pickup while held (supersedes Coin Purse's
flat interest), plus a flat +3 luck bonus.

Only the coin-doubling registers here as ``ItemCapability.COIN_MULTIPLIER``.
The luck bonus is carried by the ``luck_bonus`` data tag, which also arms
the Rabbit's Foot -- a multi-carrier tag out of scope for this per-item
registry (published luck numbers stay in data).
"""

from .. import ItemCapability, item_provides

item_provides("lucky_purse", ItemCapability.COIN_MULTIPLIER)
