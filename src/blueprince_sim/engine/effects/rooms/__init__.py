"""Per-room effect handler modules, keyed by room id via ``room_hook``.

One module per room, mirroring ``tests/rooms/``. Each module registers its
handlers with ``room_hook`` on import, the same way ``effects/tier1.py``
registers tag handlers with ``effect`` -- so landing a room module here only
requires importing it from this file. ``commerce.py`` is the exception: it
registers the ``Capability.COMMERCE`` fact for eleven rooms via ``provides``
rather than a per-room handler, so it lives as one shared module instead of
eleven near-empty ones. The four Antechamber-lever rooms (Great Hall, Weight
Room, Secret Garden, Throne Room) register via ``provides_lever`` instead of
``room_hook``, since the engine needs to query them by cell rather than fire
them through the tag/hook pipeline. ``commissary.py``/``gift_shop.py``/
``kitchen.py``/``locksmith.py``/``showroom.py``/``workshop.py`` register
their daily stock builder with ``shops.register_stock_builder`` instead of
``room_hook``, since shops.py's ``on_enter_shop`` calls them directly rather
than through the tag/hook ``fire`` pipeline.
"""

from __future__ import annotations

from . import aquarium  # noqa: F401
from . import archives  # noqa: F401
from . import billiard_room  # noqa: F401  (registers room_hook handler on import)
from . import boiler_room  # noqa: F401  (registers room_hook handlers on import)
from . import break_room  # noqa: F401
from . import bunk_room  # noqa: F401
from . import chapel  # noqa: F401  (registers the tithe-banking capability on import)
from . import classroom  # noqa: F401
from . import closet  # noqa: F401
from . import cloister  # noqa: F401
from . import coat_check  # noqa: F401
from . import commerce  # noqa: F401  (registers commerce capability on import)
from . import commissary  # noqa: F401  (registers its stock builder on import)
from . import conservatory  # noqa: F401
from . import darkroom  # noqa: F401
from . import dovecote  # noqa: F401  (no handler; imported for the predicate helper)
from . import drawing_room  # noqa: F401
from . import entrance_hall  # noqa: F401  (registers container-kinds overlay + vase capability)
from . import foyer  # noqa: F401
from . import furnace  # noqa: F401
from . import gift_shop  # noqa: F401  (registers its stock builder on import)
from . import great_hall  # noqa: F401  (registers lever capability on import)
from . import greenhouse  # noqa: F401
from . import guess_bedroom  # noqa: F401
from . import guest_bedroom  # noqa: F401
from . import hallway  # noqa: F401
from . import her_ladyships_chamber  # noqa: F401
from . import hovel  # noqa: F401
from . import kitchen  # noqa: F401  (registers its stock builder on import)
from . import locker_room  # noqa: F401
from . import locksmith  # noqa: F401  (registers its stock builder on import)
from . import mail_room  # noqa: F401
from . import mechanarium  # noqa: F401  (no per-tag handler; seeds the diagonal-compartment count)
from . import nook  # noqa: F401
from . import observatory  # noqa: F401
from . import parlor  # noqa: F401
from . import patio  # noqa: F401
from . import planetarium  # noqa: F401
from . import quest_bedroom  # noqa: F401
from . import room_8  # noqa: F401
from . import rotunda  # noqa: F401
from . import schoolhouse  # noqa: F401
from . import secret_garden  # noqa: F401
from . import secret_passage  # noqa: F401
from . import spare_great_hall  # noqa: F401
from . import security  # noqa: F401
from . import shelter  # noqa: F401
from . import shrine  # noqa: F401  (no room_hook; donate/take-back are action-driven, see game.py)
from . import showroom  # noqa: F401  (registers its stock builder + trophy overlay on import)
from . import solarium  # noqa: F401
from . import study  # noqa: F401
from . import the_kennel  # noqa: F401
from . import throne_room  # noqa: F401  (registers lever capability on import)
from . import tomb  # noqa: F401
from . import trading_post  # noqa: F401  (registers the trade-menu capability on import)
from . import treasure_trove  # noqa: F401
from . import vestibule  # noqa: F401
from . import weight_room  # noqa: F401
from . import workshop  # noqa: F401  (registers fabrication capability + stock builder)
