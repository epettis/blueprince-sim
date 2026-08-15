"""Observable-firing tests for the item-hook chain registry: ``item_hook``
keys a handler by (item id, ItemHook), and unlike
``room_hook`` -- whose exclusivity the grid gives it for free -- more than
one item can register the same hook, so ``fire_item_chain`` (first
applicable item wins) and ``fold_item_chain`` (every applicable item
transforms the value in turn) are the two arbitration primitives engine
code walks its own priority tuple through.

Mirrors ``tests/test_room_registry.py`` and ``tests/test_item_registry.py``:
these tests exercise the registry's own mechanics with temporary probes,
torn down after every test (the ``item_hook_probe`` fixture) so a leaked
registration in the module-global ``_ITEM_HOOK_REGISTRY`` cannot corrupt an
unrelated suite. Probes register on real item ids that carry no ItemHook of
their own (never on emerald_bracelet/hall_pass/stopwatch/salt_shaker/
silver_spoon/etc., the nine phase-4 carriers below) -- reusing one of those
would let a probe's teardown pop the real production registration, the same
trap ``test_item_registry.py``'s own docstring calls out for
``item_provides``. Each real module's registration then gets its own
liveness test, importing ``blueprince_sim.engine.game`` (the production
import path) and checking the chain actually reaches it.
"""

from __future__ import annotations

import pytest

import blueprince_sim.engine.game  # noqa: F401  (production import path; registers items)
from blueprince_sim.engine.effects import (
    ItemHook,
    _ITEM_HOOK_REGISTRY,
    fire_item,
    fire_item_chain,
    fold_item_chain,
    item_hook,
    validate_item_hook_registry,
)
from blueprince_sim.engine.state import GameState


@pytest.fixture()
def item_hook_probe():
    """Register a temporary ``item_hook`` handler and remove it at teardown,
    so a probe registration never leaks into another test file that imports
    the module-global ``_ITEM_HOOK_REGISTRY``."""
    registered: list[tuple[str, ItemHook]] = []

    def _register(item_id: str, hook: ItemHook, fn):
        item_hook(item_id, hook)(fn)
        registered.append((item_id, hook))

    yield _register

    for item_id, hook in registered:
        _ITEM_HOOK_REGISTRY.pop((item_id, hook), None)


def test_fire_item_returns_none_for_an_unregistered_hook(registry):
    """fire_item returns None when item_id has no handler registered for
    hook, regardless of whether the item is held -- there is simply nothing
    to call. Uses the real Shovel, which registers no ItemHook at all."""
    state = GameState()
    state.inventory["shovel"] = 1

    assert fire_item(state, registry, "shovel", ItemHook.RED_ROOM_NEGATE) is None


def test_fire_item_calls_the_handler_even_when_not_held(registry, item_hook_probe):
    """fire_item does not gate on inventory itself -- the handler is called
    regardless, and must decide holding as its own context predicate (owner
    ruling: items own their applicability, the same way Hall Pass owns its
    hallway-from-hallway test). A handler that ignores holding entirely
    (as this probe does) fires anyway; that is the handler author's
    responsibility, not the registry's."""
    calls = []
    item_hook_probe("shovel", ItemHook.RED_ROOM_NEGATE,
                     lambda state, registry: calls.append(1) or True)
    state = GameState()  # shovel NOT held

    result = fire_item(state, registry, "shovel", ItemHook.RED_ROOM_NEGATE)

    assert result is True
    assert calls == [1]


def test_fire_item_chain_returns_first_non_none_result(registry, item_hook_probe):
    """fire_item_chain walks priority in order and returns the first item's
    non-None result -- a lower-priority item registered for the same hook is
    never even reached once a higher one has answered."""
    calls = []
    item_hook_probe("shovel", ItemHook.GEM_COST,
                     lambda state, registry, *a: calls.append("shovel") or 0)
    item_hook_probe("jack_hammer", ItemHook.GEM_COST,
                     lambda state, registry, *a: calls.append("jack_hammer") or 0)
    state = GameState()

    result = fire_item_chain(
        state, registry, ItemHook.GEM_COST, ("shovel", "jack_hammer"), None, 5)

    assert result == 0
    assert calls == ["shovel"], "the second item's handler must not even be called"


def test_fire_item_chain_falls_through_a_declining_item(registry, item_hook_probe):
    """When the first item in priority order declines (returns None), the
    chain moves on to the next and returns its result instead."""
    item_hook_probe("shovel", ItemHook.GEM_COST, lambda state, registry, *a: None)
    item_hook_probe("jack_hammer", ItemHook.GEM_COST, lambda state, registry, *a: 0)
    state = GameState()

    result = fire_item_chain(
        state, registry, ItemHook.GEM_COST, ("shovel", "jack_hammer"), None, 5)

    assert result == 0


def test_fire_item_chain_returns_default_when_nothing_applies(registry, item_hook_probe):
    """With no item in the priority tuple applicable, fire_item_chain returns
    the caller-supplied default rather than None -- callers like
    move_step_cost rely on this to fall back to the un-modified cost."""
    item_hook_probe("shovel", ItemHook.MOVE_STEP_COST, lambda state, registry, *a: None)
    state = GameState()

    result = fire_item_chain(
        state, registry, ItemHook.MOVE_STEP_COST, ("shovel",), 0, 0, None, default=1)

    assert result == 1


def test_fold_item_chain_passes_the_running_value_through_each_stage(registry, item_hook_probe):
    """fold_item_chain is a genuine ordered fold, not first-match-wins: both
    items in the tuple apply, each transforming the previous stage's result
    -- (3 + 1) * 2 = 8, distinguishable from either stage applied alone."""
    item_hook_probe("shovel", ItemHook.FOOD_STEP_BONUS,
                     lambda state, registry, total: total + 1)
    item_hook_probe("jack_hammer", ItemHook.FOOD_STEP_BONUS,
                     lambda state, registry, total: total * 2)
    state = GameState()

    result = fold_item_chain(
        state, registry, ItemHook.FOOD_STEP_BONUS, ("shovel", "jack_hammer"), 3)

    assert result == 8


def test_fold_item_chain_skips_a_declining_stage(registry, item_hook_probe):
    """A stage that declines (returns None) leaves the running value
    unchanged rather than resetting or erroring -- the fold simply moves on
    to the next stage with the same value it had."""
    item_hook_probe("shovel", ItemHook.FOOD_STEP_BONUS,
                     lambda state, registry, total: None)
    item_hook_probe("jack_hammer", ItemHook.FOOD_STEP_BONUS,
                     lambda state, registry, total: total * 2)
    state = GameState()

    result = fold_item_chain(
        state, registry, ItemHook.FOOD_STEP_BONUS, ("shovel", "jack_hammer"), 3)

    assert result == 6


def test_unknown_item_id_hook_validator_rejects_a_bogus_id(registry, item_hook_probe):
    """validate_item_hook_registry flags an item_hook registration whose item
    id does not exist in the Registry, mirroring validate_item_registry's
    catch for item_provides."""
    assert validate_item_hook_registry(registry) == []

    item_hook_probe("__bogus_item_id__", ItemHook.GEM_COST, lambda state, registry, *a: None)

    assert "__bogus_item_id__" in validate_item_hook_registry(registry)


# item id -> the ItemHook(s) its real engine/effects/items/<id>.py module
# registers a handler for.
_PHASE_4_CARRIERS = {
    "emerald_bracelet": (ItemHook.GEM_COST,),
    "hall_pass": (ItemHook.GEM_COST, ItemHook.MOVE_STEP_COST),
    "stopwatch": (ItemHook.MOVE_STEP_COST, ItemHook.GEM_PAYMENT_WAIVER),
    "running_shoes": (ItemHook.MOVE_STEP_COST,),
    "lucky_purse": (ItemHook.COINS_GRANTED,),
    "coin_purse": (ItemHook.COINS_GRANTED,),
    "knights_shield": (ItemHook.RED_ROOM_NEGATE,),
    "salt_shaker": (ItemHook.FOOD_STEP_BONUS,),
    "silver_spoon": (ItemHook.FOOD_STEP_BONUS,),
}


@pytest.mark.parametrize(
    "item_id,hook",
    sorted(((iid, h) for iid, hooks in _PHASE_4_CARRIERS.items() for h in hooks), key=str))
def test_phase_4_carrier_is_registered(registry, item_id, hook):
    """Each of phase 4's nine item modules actually registers a handler for
    its documented hook(s) at import time -- through the production import
    path -- so a module missing from effects/items/__init__.py, or a typo'd
    decorator, fails here rather than passing vacuously."""
    assert (item_id, hook) in _ITEM_HOOK_REGISTRY
