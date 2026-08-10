"""Commerce capability registrations.

Eleven rooms let the player buy, sell, trade, or fabricate: the eight
``shops.json`` shop rooms, the Trading Post and the Casino (both
``category: "shop"`` but absent from ``shops.json``), and the Workshop
(``category: "blueprint"``). The Casino's stock table is empty --
its minigames are unmodelled -- so registering it is currently a no-op,
same as the Trading Post. Each registration is a single fact rather than
room-specific behaviour, so they share one module instead of eleven
near-empty per-room files.
"""

from __future__ import annotations

from .. import Capability, provides

_COMMERCE_ROOMS = (
    "bookshop",
    "casino",
    "commissary",
    "gift_shop",
    "kitchen",
    "laundry_room",
    "locksmith",
    "showroom",
    "the_armory",
    "trading_post",
    "workshop",
)

for _room_id in _COMMERCE_ROOMS:
    provides(_room_id, Capability.COMMERCE)
