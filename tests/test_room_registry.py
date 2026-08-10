"""Observable-firing tests for the room-id-keyed effect handler registry.

``room_hook`` keys a handler by room id directly, alongside the tag registry
that keys by a data tag. These tests exercise the registry's own mechanics
rather than any shipped room's behaviour, so they register temporary probes
through the importable ``room_hook`` decorator and tear them down after every
test (see the ``room_probe`` fixture) -- the registry in
engine/effects/__init__.py is module-global, and a leaked registration would
corrupt unrelated suites. This mirrors tests/test_effect_hooks.py's ``probe``
fixture, which solves the identical problem for the tag registry.
"""

from __future__ import annotations

import dataclasses

import pytest

from blueprince_sim.engine.effects import (
    Capability,
    Hook,
    _CAPABILITY_REGISTRY,
    _ROOM_REGISTRY,
    fire,
    provides,
    room_hook,
    validate_capability_registry,
    validate_room_registry,
)
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Effect


@pytest.fixture()
def room_probe():
    """Register a temporary ``room_hook`` handler and return a call log,
    private to that registration, of ``(hook, room.id)`` pairs.

    Every registration this fixture makes is removed from the module-global
    _ROOM_REGISTRY dict at teardown (in a plain function body after
    ``yield``, so it always runs even if the test raises) -- the registry is
    shared process-wide, so a leaked entry here would silently change fire()
    behaviour for every other test file that imports engine.effects.
    """
    registered: list[tuple[str, Hook]] = []

    def _register(room_id: str, hook: Hook) -> list[tuple[Hook, str]]:
        calls: list[tuple[Hook, str]] = []

        def handler(game, room, context_room):
            calls.append((hook, room.id))

        room_hook(room_id, hook)(handler)
        registered.append((room_id, hook))
        return calls

    yield _register

    for room_id, hook in registered:
        _ROOM_REGISTRY.pop((room_id, hook), None)


def _with_effect(room, tag: str):
    """A copy of ``room`` with one extra effect tag appended.

    Room is a frozen dataclass, so this builds a standalone copy rather than
    mutating the shared session-scoped registry's room -- the copy keeps the
    same id, so the room-id lookup behaves exactly as it would for the real
    record.
    """
    return dataclasses.replace(room, effects=room.effects + (Effect(tag=tag),))


def test_handler_fires_only_for_its_own_room_and_hook(registry, cfg, room_probe):
    """A room_hook handler registered for one (room id, hook) pair fires
    when that exact pair is fired, and stays silent for a different room or
    a different hook on the same room."""
    corridor = registry.by_id["corridor"]
    closet = registry.by_id["closet"]
    calls = room_probe("corridor", Hook.ON_ENTER)
    g = Game(cfg, seed=1, registry=registry)

    fire(g, corridor, Hook.ON_ENTER)
    assert calls == [(Hook.ON_ENTER, "corridor")]

    fire(g, corridor, Hook.ON_PLACE)
    assert calls == [(Hook.ON_ENTER, "corridor")], "must not fire at a different hook"

    fire(g, closet, Hook.ON_ENTER)
    assert calls == [(Hook.ON_ENTER, "corridor")], "must not fire for a different room"


def test_variant_does_not_get_base_rooms_handler(registry, cfg, room_probe):
    """A handler registered on a base room id does not fire for that room's
    upgrade variants -- lookup is by the room's own id only."""
    boudoir_variant = registry.by_id["boudoir__ix16"]
    calls = room_probe("boudoir", Hook.ON_ENTER)
    g = Game(cfg, seed=1, registry=registry)

    fire(g, boudoir_variant, Hook.ON_ENTER)

    assert calls == [], "a base room's handler must not reach an upgrade variant"


def test_tag_loop_runs_before_the_room_lookup(registry, cfg):
    """fire() still runs every tag handler in room.effects, and it runs the
    whole tag loop before the room-id lookup -- a tag handler and a room_hook
    handler on the same room and hook both write into one shared
    order-recording list, so the tag entry is provably first."""
    from blueprince_sim.engine.effects import DEFAULT_HOOK, _REGISTRY, effect

    order: list[str] = []
    tag = "__test_room_registry_tag_probe__"
    added_default = tag not in DEFAULT_HOOK

    def tag_handler(game, room, eff, context_room):
        order.append("tag")

    def room_handler(game, room, context_room):
        order.append("room")

    effect(tag, Hook.ON_ENTER)(tag_handler)
    room_hook("corridor", Hook.ON_ENTER)(room_handler)
    try:
        corridor = _with_effect(registry.by_id["corridor"], tag)
        g = Game(cfg, seed=1, registry=registry)

        fire(g, corridor, Hook.ON_ENTER)

        assert order == ["tag", "room"]
    finally:
        _REGISTRY.pop((tag, Hook.ON_ENTER), None)
        if added_default:
            DEFAULT_HOOK.pop(tag, None)
        _ROOM_REGISTRY.pop(("corridor", Hook.ON_ENTER), None)


def test_unknown_room_id_validator_rejects_a_bogus_id(registry, room_probe):
    """validate_room_registry flags a room_hook registration whose room id
    does not exist in the Registry -- the failure mode a typo like
    ``room_hook("dovecot", ...)`` would otherwise hit silently, since the
    handler would simply never have a matching room to fire for."""
    assert validate_room_registry(registry) == []

    room_probe("dovecot", Hook.ON_ENTER)

    assert "dovecot" in validate_room_registry(registry)


def test_unknown_room_id_capability_validator_rejects_a_bogus_id(registry):
    """validate_capability_registry flags a ``provides`` registration whose
    room id does not exist in the Registry, the same class of typo bug
    validate_room_registry catches for room_hook -- a bad id here would
    otherwise just never match a real room, silently.
    """
    assert validate_capability_registry(registry) == []

    provides("dovecot", Capability.COMMERCE)
    try:
        assert "dovecot" in validate_capability_registry(registry)
    finally:
        _CAPABILITY_REGISTRY.discard(("dovecot", Capability.COMMERCE))
