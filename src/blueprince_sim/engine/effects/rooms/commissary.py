"""Commissary: registers its daily stock builder.

Registered via ``shops.register_stock_builder`` -- the same registration
shape ``room_hook``/``provides`` use elsewhere in ``effects/`` -- so
``shops.py``'s ``on_enter_shop`` dispatch never names this room's id
directly.
"""

from __future__ import annotations

from ... import shops
from ... import special_items as si


def _roll_commissary(game, table: dict) -> None:
    """Build the Commissary's daily stock: slots distinct available entries.

    Every entry competes for the same ``slots`` places. ``kind: "item"`` entries
    are filtered through ``_is_available`` first, so a unique already held — or an
    Upgrade Disk already spent, and hence in collected_disks/gated_out — is never
    displayed. ``kind: "resource"`` entries (gem, key, banana, ...) are unlimited
    and always eligible.
    """
    state = game.state
    registry = game.registry
    slots = table.get("slots", 4)
    raw_stock = table.get("stock", [])

    candidates = []
    for raw in raw_stock:
        entry = dict(raw)
        entry.setdefault("sold", 0)
        if raw.get("kind") == "item":
            if not si._is_available(state, raw["id"], registry):
                continue
        candidates.append(entry)

    # Shuffle indices for deterministic random selection
    indices = list(range(len(candidates)))
    game.rng.shuffle("shop_stock", indices)
    state.shops.stock["commissary"] = [candidates[i] for i in indices[:slots]]


shops.register_stock_builder("commissary", _roll_commissary)
