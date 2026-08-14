"""Dowsing Rod: while held, points at one of the three dealt floorplans on
every deal/redraw -- the same fact ``ItemCapability.DOWSING_ROD`` registers,
consumed by ``engine/draft.py``'s ``_pick_dowsing_slot`` (the pick itself)
and ``engine/items.py``'s ``roll_dowsed_count`` (that slot's own item-count
table, once drafted and entered). See data/items.json's ``dowsing_rod``
table for the published mechanics this capability's data feeds.
"""

from __future__ import annotations

from .. import ItemCapability, item_provides

item_provides("dowsing_rod", ItemCapability.DOWSING_ROD)
