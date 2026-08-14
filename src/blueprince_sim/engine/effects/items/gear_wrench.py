"""Gear Wrench: each time a Mechanical Room is drafted while held, the player
may permanently adjust its rarity to any of the four rarity levels.

Not consumed, reusable, unlimited while held. Game.choose detects the
trigger (a just-placed Room.is_category("mechanical") room, this item held)
and parks Phase.WRENCH_PENDING instead of returning to NAVIGATE; Game.
set_wrench_rarity resolves the pick via decks.set_dynamic_rarity (the same
card-move primitive experiments.py's add_aquariums and battery_pack.py
already use) and records the permanent choice in state.permanent_rarity /
GameConfig.permanent_rarity. This module owns only the item id and the
held() primitive, the same split repellent.py/the_axe.py give their own item.

The wiki's separate pickup side effect (Workshop + Boiler Room -> Standard,
that day) is NOT built here: decks.set_dynamic_rarity needs ``rng`` (to place
moved undealt cards), and special_items._on_pickup -- the only pickup-time
hook -- is called with no rng in scope, the same constraint battery_pack.py
works around by recording a pending trigger (on_pickup) resolved later where
rng IS available (resolve_pending, fired from Game._deal_and_cache). Building
the Gear Wrench's own pickup effect would need that same deferred-trigger
shape; left as a named, tracked gap (data/special_items.json's meta.notes)
rather than silently dropped.
"""

from __future__ import annotations

ITEM_ID = "gear_wrench"


def held(state) -> bool:
    """True while at least one Gear Wrench is in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0
