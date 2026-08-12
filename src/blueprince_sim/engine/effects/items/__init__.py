"""Per-item modules, keyed by item id via ``item_provides`` and/or ``item_hook``.

Item behaviour fires on game events exactly as room behaviour does -- a
payment, a move, a coin grant are all events, and an item handler on one is
exactly as legitimate as a room handler on ``Hook.ON_ENTER``. The real
difference between the two registries is arity and arbitration: ``fire``
dispatches to *the* one room the event concerns (the grid gives it that
exclusivity for free), while any number of held items can answer the same
``ItemHook`` -- so, unlike ``room_hook``, an item handler must return a
value rather than run for effect, and engine code arbitrates between
multiple applicable items with its own explicit priority tuple
(``fire_item_chain``/``fold_item_chain`` in ``engine/effects/__init__.py``),
never a ``priority=`` number on the registration.

Some items carry no such handler, only a fact: ``item_provides`` registers
the *fact and parameters* of a capability that engine code folds
commutatively over every held item (``item_capability_sum``/``_any``) --
e.g. Coupon Book's flat shop discount, where order can't matter. Use
``item_provides`` when nothing about the outcome depends on order or on
mutating state; use ``item_hook`` the moment order decides a conflict
(two items could both apply) or the item needs to run code (spend a
charge, accumulate interest). A module may register both, for different
facets of the same item.
"""

from __future__ import annotations

from . import chronograph  # noqa: F401  (registers chronograph capability on import)
from . import coin_purse  # noqa: F401  (registers coins_granted handler on import)
from . import compass  # noqa: F401  (registers compass_bias capability on import)
from . import coupon_book  # noqa: F401  (registers shop_discount capability on import)
from . import cursed_effigy  # noqa: F401  (exposes its own spawn-gate predicate)
from . import emerald_bracelet  # noqa: F401  (registers emerald_bracelet capability + hook)
from . import hall_pass  # noqa: F401  (registers free_hallway_moves capability + hooks)
from . import key_8  # noqa: F401  (exposes its own room8_key held-fact predicate)
from . import knights_shield  # noqa: F401  (registers red_room_negate handler on import)
from . import lucky_purse  # noqa: F401  (registers coin_multiplier capability + hook)
from . import lunch_box  # noqa: F401  (exposes its own gate/purchase/consumption functions)
from . import master_key  # noqa: F401  (registers master_key capability on import)
from . import ornate_compass  # noqa: F401  (registers ornate_compass capability on import)
from . import paper_crown  # noqa: F401  (exposes its own bonus-redraw predicate)
from . import powered_electromagnet  # noqa: F401  (registers electromagnet + compass_bias)
from . import power_hammer  # noqa: F401  (exposes its own held-fact predicate)
from . import repellent  # noqa: F401  (exposes its own held/consume functions)
from . import royal_scepter  # noqa: F401  (exposes its own gate/carry-over/held functions)
from . import running_shoes  # noqa: F401  (registers move_step_cost handler on import)
from . import salt_shaker  # noqa: F401  (registers food_step_bonus handler on import)
from . import silver_key  # noqa: F401  (exposes its own draft-consume/mechanarium functions)
from . import silver_spoon  # noqa: F401  (registers food_multiplier capability + hook)
from . import sleeping_mask  # noqa: F401  (exposes its own on-enter effect function)
from . import stopwatch  # noqa: F401  (registers move_step_cost/gem_payment_waiver handlers)
from . import watering_can  # noqa: F401  (exposes its own on-pickup/on-enter effect functions)
