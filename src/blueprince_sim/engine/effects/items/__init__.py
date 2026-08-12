"""Per-item capability modules, keyed by item id via ``item_provides``.

A room has a natural event boundary -- the player standing in it -- so
``room_hook`` in the parent package fires a handler at that boundary. Items
have no such boundary: item behaviour is overwhelmingly a fold over the
currently-held inventory ("the engine is about to charge N coins -- ask
every held item whether it changes N"), which is a modifier pipeline the
engine owns and runs in one explicit order (``item_capability_sum`` in
``engine/effects/__init__.py``), not a hook a module registers a handler
function for. So each module in this package registers only the *fact and
parameters* of one item's contribution via ``item_provides`` -- never a
handler -- mirroring how ``effects/rooms/commerce.py`` registers the
``Capability.COMMERCE`` fact for eleven rooms via ``provides`` rather than a
per-room handler.
"""

from __future__ import annotations

from . import coupon_book  # noqa: F401  (registers shop_discount capability on import)
