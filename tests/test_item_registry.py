"""Observable-firing tests for the item-id-keyed capability registry.

``item_provides`` keys a summed capability by item id, the way ``room_hook``
keys a fire-on-hook handler by room id in ``tests/test_room_registry.py`` --
but unlike a room hook, an item's registration carries no handler function,
only a fact and its parameters (``item_capability_sum`` is the fold the
engine owns). These tests exercise the registry's own mechanics rather than
any shipped item's behaviour, so they register temporary probes -- on real
item ids that carry no capability of their own, never on ``coupon_book``
itself, so a probe's teardown cannot pop coupon_book.py's real production
registration -- through the importable ``item_provides`` function and tear
them down after every test (the ``item_capability_probe`` fixture).
``_ITEM_CAPABILITY_REGISTRY`` in engine/effects/__init__.py is module-global,
and a leaked registration would corrupt unrelated suites. This mirrors
tests/test_room_registry.py's ``room_probe`` fixture, which solves the
identical problem for room_hook.

``validate_capability_registry``/``validate_room_registry`` back
tools/validate_data.py's "engine/effects registries" check, in addition to
their dedicated tests in test_room_registry.py. ``validate_item_registry``
is exercised the same way here, directly, as well as through that same
tools/validate_data.py call site.

``item_capability_any`` is the boolean sibling of ``item_capability_sum``
(an OR over held items' registrations rather than a sum of one param), added
for the eight pure-boolean item migrations below. Its own mechanics
get the same probe-based tests as ``item_capability_sum`` above; each real
module's registration then gets a dedicated liveness test -- importing
``blueprince_sim.engine.game`` (the production import path every real
registration flows through, the same way ``test_coupon_book_is_registered...``
does above) and checking the query flips true only while the carrier item is
actually held, so a popped registration would fail loudly rather than pass
vacuously.
"""

from __future__ import annotations

import pytest

import blueprince_sim.engine.game  # noqa: F401  (production import path; registers items)
from blueprince_sim.engine.effects import (
    ItemCapability,
    _ITEM_CAPABILITY_REGISTRY,
    item_capability_any,
    item_capability_sum,
    item_provides,
    validate_item_registry,
)
from blueprince_sim.engine.state import GameState


@pytest.fixture()
def item_capability_probe():
    """Register a temporary ``item_provides`` capability and remove it at
    teardown, so a probe registration never leaks into another test file
    that imports the module-global ``_ITEM_CAPABILITY_REGISTRY``."""
    registered: list[tuple[str, ItemCapability]] = []

    def _register(item_id: str, capability: ItemCapability, **params) -> None:
        item_provides(item_id, capability, **params)
        registered.append((item_id, capability))

    yield _register

    for item_id, capability in registered:
        _ITEM_CAPABILITY_REGISTRY.pop((item_id, capability), None)


def test_sum_folds_only_held_items_with_a_positive_count(registry, item_capability_probe):
    """item_capability_sum adds a registered item's param only while its
    inventory count is positive -- a zero or absent count contributes
    nothing, matching how special_items._has_item_effect decides "held".

    Probes register on ``stopwatch``, a real item id that carries no
    capability registration of its own, rather than ``coupon_book`` --
    reusing coupon_book's id here would let this fixture's teardown pop the
    real production registration coupon_book.py made at import time.
    """
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT, amount=1)
    state = GameState()

    assert item_capability_sum(state, registry, ItemCapability.SHOP_DISCOUNT, "amount") == 0

    state.inventory["stopwatch"] = 0
    assert item_capability_sum(state, registry, ItemCapability.SHOP_DISCOUNT, "amount") == 0

    state.inventory["stopwatch"] = 1
    assert item_capability_sum(state, registry, ItemCapability.SHOP_DISCOUNT, "amount") == 1


def test_sum_adds_every_held_item_registering_the_capability(registry, item_capability_probe):
    """item_capability_sum is a genuine sum across distinct held items, not a
    boolean-style "any held" check -- two different registered items each
    contribute their own param value. Uses two real, otherwise-unregistered
    item ids for the same reason as the previous test."""
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT, amount=1)
    item_capability_probe("master_key", ItemCapability.SHOP_DISCOUNT, amount=2)
    state = GameState()
    state.inventory["stopwatch"] = 1
    state.inventory["master_key"] = 1

    total = item_capability_sum(state, registry, ItemCapability.SHOP_DISCOUNT, "amount")

    assert total == 3


def test_sum_ignores_a_different_capability(registry, item_capability_probe):
    """A capability registration only contributes to a fold over that same
    capability -- querying a different capability for the same held item
    returns 0, not the unrelated param."""
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT, amount=1)
    state = GameState()
    state.inventory["stopwatch"] = 1

    other_capability = object()  # anything that cannot equal SHOP_DISCOUNT

    assert item_capability_sum(state, registry, other_capability, "amount") == 0


def test_unknown_item_id_validator_rejects_a_bogus_id(registry, item_capability_probe):
    """validate_item_registry flags an item_provides registration whose item
    id does not exist in the Registry -- the failure mode a typo'd id would
    otherwise hit silently, since the registration would simply never match
    a real item."""
    assert validate_item_registry(registry) == []

    item_capability_probe("__bogus_item_id__", ItemCapability.SHOP_DISCOUNT, amount=1)

    assert "__bogus_item_id__" in validate_item_registry(registry)


def test_coupon_book_is_registered_with_amount_one(registry):
    """The real coupon_book module registers SHOP_DISCOUNT amount=1 at
    import time -- pins that engine.effects.items actually got imported
    (registration is not silently skipped) and that the parameter value
    matches the item's documented -1-coin-per-price effect."""
    state = GameState()
    state.inventory["coupon_book"] = 1

    assert item_capability_sum(state, registry, ItemCapability.SHOP_DISCOUNT, "amount") == 1


def test_any_true_only_while_held_with_a_positive_count(registry, item_capability_probe):
    """item_capability_any is False with no registration, False at count 0,
    and True at a positive count -- the same "held" rule item_capability_sum
    uses, just folded with OR instead of +."""
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT)
    state = GameState()

    assert item_capability_any(state, registry, ItemCapability.SHOP_DISCOUNT) is False

    state.inventory["stopwatch"] = 0
    assert item_capability_any(state, registry, ItemCapability.SHOP_DISCOUNT) is False

    state.inventory["stopwatch"] = 1
    assert item_capability_any(state, registry, ItemCapability.SHOP_DISCOUNT) is True


def test_any_is_true_if_any_one_of_several_held_items_registers(registry, item_capability_probe):
    """item_capability_any is a genuine OR: holding just one of two
    registered items is enough to flip it true, unlike a sum which would
    need both to reach a larger total."""
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT)
    item_capability_probe("master_key", ItemCapability.SHOP_DISCOUNT)
    state = GameState()
    state.inventory["master_key"] = 1

    assert item_capability_any(state, registry, ItemCapability.SHOP_DISCOUNT) is True


def test_any_ignores_a_different_capability(registry, item_capability_probe):
    """A capability registration only answers a query for that same
    capability -- querying a different capability for the same held item
    returns False, not True."""
    item_capability_probe("stopwatch", ItemCapability.SHOP_DISCOUNT)
    state = GameState()
    state.inventory["stopwatch"] = 1

    other_capability = object()  # anything that cannot equal SHOP_DISCOUNT

    assert item_capability_any(state, registry, other_capability) is False


# item id -> ItemCapability member registered by its real
# engine/effects/items/<item_id>.py module (the eight pure-boolean item
# migrations).
_PHASE_3_CARRIERS = {
    "powered_electromagnet": ItemCapability.ELECTROMAGNET,
    "chronograph": ItemCapability.CHRONOGRAPH,
    "ornate_compass": ItemCapability.ORNATE_COMPASS,
    "master_key": ItemCapability.MASTER_KEY,
    "emerald_bracelet": ItemCapability.EMERALD_BRACELET,
    "silver_spoon": ItemCapability.FOOD_MULTIPLIER,
    "hall_pass": ItemCapability.FREE_HALLWAY_MOVES,
    "lucky_purse": ItemCapability.COIN_MULTIPLIER,
}


@pytest.mark.parametrize("item_id,capability", sorted(_PHASE_3_CARRIERS.items(), key=str))
def test_phase_3_carrier_is_registered_and_reachable(registry, item_id, capability):
    """Each of the eight phase-3 item modules actually registers its
    capability at import time -- through the production import path
    (``import blueprince_sim.engine.game`` at module scope above) -- and the
    query it backs is False before the carrier is held and True once it is.
    A capability that were registered but never reachable (or never
    registered at all, e.g. a module missing from effects/items/__init__.py)
    would fail here rather than pass vacuously."""
    state = GameState()

    assert item_capability_any(state, registry, capability) is False

    state.inventory[item_id] = 1
    assert item_capability_any(state, registry, capability) is True
