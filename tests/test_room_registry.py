"""Observable-firing tests for the room-id-keyed effect handler registry.

Phase 2 of docs/open_tasks.md task 17: a second registry, alongside the
existing tag registry, that keys a handler by room id directly rather than by
a data tag, with per-handler opt-in inheritance across upgrade variants. No
handler is registered in shipped code by this change, so this file registers
its own temporary probes via the importable ``room_hook`` decorator and tears
them down after every test (see the ``room_probe`` fixture) -- the registry
in engine/effects/__init__.py is module-global, and a leaked registration
would corrupt unrelated suites. This mirrors tests/test_effect_hooks.py's
``probe`` fixture, which solves the identical problem for the tag registry.
"""

from __future__ import annotations

import dataclasses

import pytest

from blueprince_sim.engine.effects import (
    Hook,
    _ROOM_INHERIT,
    _ROOM_REGISTRY,
    fire,
    room_hook,
    validate_room_registry,
)
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Effect


@pytest.fixture()
def room_probe():
    """Register a temporary ``room_hook`` handler and return a call log,
    private to that registration, of ``(hook, room.id)`` pairs.

    Every registration this fixture makes is removed from the module-global
    _ROOM_REGISTRY/_ROOM_INHERIT dicts at teardown (in a plain function body
    after ``yield``, so it always runs even if the test raises) -- the
    registry is shared process-wide, so a leaked entry here would silently
    change fire() behaviour for every other test file that imports
    engine.effects.
    """
    registered: list[tuple[str, Hook]] = []

    def _register(room_id: str, hook: Hook, *, inherit: bool = False) -> list[tuple[Hook, str]]:
        calls: list[tuple[Hook, str]] = []

        def handler(game, room, context_room):
            calls.append((hook, room.id))

        room_hook(room_id, hook, inherit=inherit)(handler)
        registered.append((room_id, hook))
        return calls

    yield _register

    for room_id, hook in registered:
        _ROOM_REGISTRY.pop((room_id, hook), None)
        _ROOM_INHERIT.pop((room_id, hook), None)


def _with_effect(room, tag: str):
    """A copy of ``room`` with one extra effect tag appended.

    Room is a frozen dataclass, so this builds a standalone copy rather than
    mutating the shared session-scoped registry's room -- the copy keeps the
    same id/variant_of, so room-id and inheritance lookups behave exactly as
    they would for the real record.
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


def test_default_inherit_false_variant_gets_nothing(registry, cfg, room_probe):
    """With inherit=False (the default), a handler registered on a base room
    id does not fire for that room's upgrade variants."""
    boudoir_variant = registry.by_id["boudoir__ix16"]
    calls = room_probe("boudoir", Hook.ON_ENTER, inherit=False)
    g = Game(cfg, seed=1, registry=registry)

    fire(g, boudoir_variant, Hook.ON_ENTER)

    assert calls == [], "inherit=False must not reach an upgrade variant"


@pytest.mark.parametrize(
    "variant_id",
    ["spare_bedroom__ix131", "servants_spare_quarters__ix134"],
    ids=["first_level", "second_level"],
)
def test_inherit_true_reaches_every_chain_depth(registry, cfg, room_probe, variant_id):
    """With inherit=True, a handler registered on the Spare Room's root id
    fires for variants at any depth of its variant_of chain -- both the
    first-level pick (spare_bedroom) and its own second-level sub-variant
    (servants_spare_quarters), since the chain is two deep and root_base_id
    resolves the whole chain in one step."""
    variant = registry.by_id[variant_id]
    calls = room_probe("spare_room", Hook.ON_ENTER, inherit=True)
    g = Game(cfg, seed=1, registry=registry)

    fire(g, variant, Hook.ON_ENTER)

    assert calls == [(Hook.ON_ENTER, variant_id)], (
        "the inherited handler must receive the variant's own Room, not the base's"
    )


def test_variants_own_handler_shadows_the_inherited_one(registry, cfg, room_probe):
    """A variant that registers its own handler at the same hook is called
    instead of the inherited base handler -- the base's handler must not
    also fire for that variant."""
    variant = registry.by_id["spare_bedroom__ix131"]
    base_calls = room_probe("spare_room", Hook.ON_ENTER, inherit=True)
    own_calls = room_probe("spare_bedroom__ix131", Hook.ON_ENTER)
    g = Game(cfg, seed=1, registry=registry)

    fire(g, variant, Hook.ON_ENTER)

    assert own_calls == [(Hook.ON_ENTER, "spare_bedroom__ix131")]
    assert base_calls == [], "the variant's own handler must shadow the inherited one"


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
        _ROOM_INHERIT.pop(("corridor", Hook.ON_ENTER), None)


def test_unknown_room_id_validator_rejects_a_bogus_id(registry, room_probe):
    """validate_room_registry flags a room_hook registration whose room id
    does not exist in the Registry -- the failure mode a typo like
    ``room_hook("dovecot", ...)`` would otherwise hit silently, since the
    handler would simply never have a matching room to fire for."""
    assert validate_room_registry(registry) == []

    room_probe("dovecot", Hook.ON_ENTER)

    assert "dovecot" in validate_room_registry(registry)
