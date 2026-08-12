"""Coupon Book: every shop price is 1 coin cheaper while it is held.

Not consumed and not per-purchase -- the discount applies to the whole
display for as long as the book is in the inventory, so it registers as a
summed capability rather than a hook.
"""

from .. import ItemCapability, item_provides

item_provides("coupon_book", ItemCapability.SHOP_DISCOUNT, amount=1)
