"""Workshop: registers the fabrication-menu capability and the first-entry
free-component stock builder.

``Capability.FABRICATION`` is read by ``shops._inside_workshop`` to gate the
fabricate menu (``Capability.COMMERCE``, which commerce.py also registers
for the Workshop, is too broad -- see that function's own docstring). The
stock builder is registered via ``shops.register_stock_builder``, the same
shape ``commissary.py`` uses; it stores an empty stock list purely to
satisfy ``on_enter_shop``'s once-per-day guard, since the Workshop itself
has nothing to sell.
"""

from __future__ import annotations

from .. import Capability, provides
from ... import shops
from ... import special_items as si

provides("workshop", Capability.FABRICATION)


def _roll_workshop(game, table: dict) -> None:
    """First-entry Workshop effect: grant one free component (or 5 coins fallback).

    Components are the union of all fabrication recipe input ids. One is
    selected uniformly from those still available (substream "shop_stock").
    Fallback: 5 coins when no component is available. The once-per-day guard
    is satisfied by storing an empty list under state.shops.stock["workshop"].
    ``table`` is unused -- the Workshop's grant is not data-driven the way
    every other shop's stock is.
    """
    state = game.state
    registry = game.registry

    comp_ids = sorted(shops._component_ids(registry))  # sorted for determinism
    available = [c for c in comp_ids if si._is_available(state, c, registry)]

    if available:
        idx = game.rng.randint("shop_stock", 0, len(available) - 1)
        chosen = available[idx]
        si.grant(state, registry, chosen, source="workshop")
    else:
        # Fallback: grant 5 coins
        bonus = si.on_coins_granted(state, registry, 5)
        state.coins += 5 + bonus
        state.items_found_log.append(("coins", 5))

    state.shops.stock["workshop"] = []


shops.register_stock_builder("workshop", _roll_workshop)
