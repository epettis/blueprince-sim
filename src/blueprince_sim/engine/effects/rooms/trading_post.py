"""Trading Post: registers the interior trade-menu capability.

shops.py's ``_inside_trading_post`` reads ``Capability.TRADE`` (via
``provides_capability``) to gate the trade menu. ``Capability.COMMERCE``
(which commerce.py already registers for the Trading Post, alongside ten
other rooms) is too broad for this: every commerce room would satisfy it,
but only the Trading Post has a trade menu -- so this room needs its own
dedicated fact.
"""

from __future__ import annotations

from .. import Capability, provides

provides("trading_post", Capability.TRADE)
