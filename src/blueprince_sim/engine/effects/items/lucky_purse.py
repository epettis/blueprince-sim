"""Lucky Purse: doubles every coin pickup while held (supersedes Coin Purse's
flat interest), plus a flat +3 luck bonus.

Only the coin-doubling registers here as ``ItemCapability.COIN_MULTIPLIER``
(kept for its existing callers) and as the ``ItemHook.COINS_GRANTED``
handler engine code actually chains on. The luck bonus is carried by the
``luck_bonus`` data tag, which also arms the Rabbit's Foot -- a multi-carrier
tag out of scope for this per-item registry (published luck numbers stay in
data).
"""

from __future__ import annotations

from .. import ItemCapability, ItemHook, item_capability_any, item_hook, item_provides

item_provides("lucky_purse", ItemCapability.COIN_MULTIPLIER)


@item_hook("lucky_purse", ItemHook.COINS_GRANTED)
def _double_coins(state, registry, amount):
    """Doubles the incoming coin amount (returned as the bonus on top of it);
    always applies once held, so it always wins COINS_GRANTED_PRIORITY."""
    if not item_capability_any(state, registry, ItemCapability.COIN_MULTIPLIER):
        return None
    return amount
