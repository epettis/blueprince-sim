"""Coin Purse: pays 1 bonus coin per 3 coins collected (data: coin_interest
per/bonus), tracked cumulatively across the day in state.special.coin_interest.
Superseded outright by Lucky Purse (see COINS_GRANTED_PRIORITY).
"""

from __future__ import annotations

from .. import ItemHook, item_hook


@item_hook("coin_purse", ItemHook.COINS_GRANTED)
def _accumulate_interest(state, registry, amount):
    """Adds ``amount`` to the running total and pays out ``bonus`` for every
    ``per`` coins accumulated, carrying any remainder to the next call."""
    if state.inventory.get("coin_purse", 0) <= 0:
        return None
    item = registry.special.by_id.get("coin_purse")
    e = item.effect("coin_interest") if item is not None else None
    if e is None:
        return None
    per = e.param("per", 3)
    bonus_per = e.param("bonus", 1)
    state.special.coin_interest += amount
    earned = state.special.coin_interest // per
    state.special.coin_interest %= per
    return earned * bonus_per
