"""Observable-firing tests for the widened effect Hook enum.

Covers ON_DRAFT_FROM, ON_HAND_DEALT, ON_ARRIVE, and ON_DAY_END -- the four
hooks added so Classroom/Library/Archives, Dovecote, the open resource-spread
task, and Tomorrow Rooms/the Break Room no longer need id-hardcoded fire
sites in game.py. No handler is registered for any of them anywhere in the
shipped code, so this file registers its own temporary probes via the
importable ``@effect`` decorator and tears them down after every test (see
the ``probe`` fixture) -- the handler registry in engine/effects/__init__.py
is module-global, and a leaked registration would corrupt unrelated suites.

Room data is mutated too (every room gets a synthetic probe tag appended to
its effects, so whichever room the RNG deals into a hand can be observed
without predicting the draw), but that mutation lives on a private Registry
loaded by this file's own ``probe_registry`` fixture -- never on the shared
session-scoped ``registry`` fixture other test files rely on -- so it cannot
leak either.
"""

from __future__ import annotations

import pytest

from blueprince_sim.engine.effects import DEFAULT_HOOK, Hook, _REGISTRY, effect
from blueprince_sim.engine.game import Game, RedrawKind
from blueprince_sim.engine.grid import ENTRANCE_CELL, N, S
from blueprince_sim.engine.model import Effect, Registry

# One synthetic, never-collides-with-real-data tag per hook under test.
_PROBE_TAGS = {
    Hook.ON_ENTER: "__test_probe_on_enter__",
    Hook.ON_DRAFT_FROM: "__test_probe_on_draft_from__",
    Hook.ON_HAND_DEALT: "__test_probe_on_hand_dealt__",
    Hook.ON_ARRIVE: "__test_probe_on_arrive__",
    Hook.ON_DAY_END: "__test_probe_on_day_end__",
}


@pytest.fixture(scope="module")
def probe_registry() -> Registry:
    """A private Registry, parsed independently of the shared ``registry``
    fixture, with every room's effects carrying one inert probe tag per hook
    under test. Attaching to every room (rather than guessing which room the
    RNG will deal) lets a test observe a real, randomly-dealt hand without
    controlling the draw; the tags have no handler registered anywhere by
    default, so this alone changes no game behaviour (see
    test_new_hooks_are_no_ops_without_a_registered_handler)."""
    reg = Registry.load()
    probe_effects = tuple(Effect(tag=tag) for tag in _PROBE_TAGS.values())
    for room in reg.rooms:
        object.__setattr__(room, "effects", room.effects + probe_effects)
    return reg


@pytest.fixture()
def probe():
    """Register a temporary ``@effect`` handler for one of the probe tags and
    return a call log, private to that hook, of ``(hook, room.id)`` pairs.

    Every registration this fixture makes is removed from the module-global
    _REGISTRY/DEFAULT_HOOK dicts at teardown (in a plain function body after
    ``yield``, so it always runs, even if the test raises) -- the registry
    is shared process-wide, so a leaked entry here would silently change
    fire() behaviour for every other test file that imports engine.effects.
    """
    registered: list[tuple[str, Hook, bool]] = []

    def _register(hook: Hook) -> list[tuple[Hook, str]]:
        # A fresh list per call: registering two different hooks in one test
        # (e.g. ON_HAND_DEALT and ON_DRAFT_FROM together) must not merge
        # their call logs into a single shared list.
        calls: list[tuple[Hook, str]] = []
        tag = _PROBE_TAGS[hook]
        added_default = tag not in DEFAULT_HOOK

        def handler(game, room, eff, context_room):
            calls.append((hook, room.id))

        effect(tag, hook)(handler)
        registered.append((tag, hook, added_default))
        return calls

    yield _register

    for tag, hook, added_default in registered:
        _REGISTRY.pop((tag, hook), None)
        if added_default:
            DEFAULT_HOOK.pop(tag, None)


def test_new_hooks_are_no_ops_without_a_registered_handler(registry, probe_registry, cfg):
    """With no handler registered for any of the four new hooks, attaching
    their probe tags to every room's effects list changes nothing
    observable: playing the same moves against the plain registry and the
    probe-tagged one ends in identical state, confirming the hooks are
    behaviourally inert on their own (this PR is meant to be a no-op)."""
    def _play(reg):
        g = Game(cfg, seed=100, registry=reg)
        corridor = reg.by_id["corridor"]
        a, b = 7, 12
        g._place_room(corridor, a, N | S)
        g._place_room(corridor, b, N | S)
        g.state.pos = a
        g.state.entered[a] = True
        g.move(N)  # N increases rank (toward the Antechamber): a -> b
        return g.state.pos, g.state.gems, g.state.steps, g.state.keys

    assert _play(probe_registry) == _play(registry)


def test_on_draft_from_fires_once_for_the_from_room_on_initial_deal(probe_registry, cfg, probe):
    """ON_DRAFT_FROM fires exactly once, naming the room the doorway belongs
    to, the moment a hand is first dealt from it."""
    calls = probe(Hook.ON_DRAFT_FROM)
    g = Game(cfg, seed=1, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    cell = 12
    g._place_room(corridor, cell, N | S)
    g.state.pos = cell

    g.open_door(cell, S)

    assert calls == [(Hook.ON_DRAFT_FROM, "corridor")]


def test_on_draft_from_does_not_refire_on_redraw(probe_registry, cfg, probe):
    """A redraw deals a fresh hand from the SAME doorway, but ON_DRAFT_FROM
    must not repeat -- the Tunnel chain's real "does not repeat on redraws"
    rule is the precedent this hook is built not to violate, since the
    existing Tunnel code keys only off from_room/direction and re-fires on
    every redeal."""
    calls = probe(Hook.ON_DRAFT_FROM)
    g = Game(cfg, seed=2, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    cell = 12
    g._place_room(corridor, cell, N | S)
    g.state.pos = cell
    g.state.dice = 1

    g.open_door(cell, S)
    assert len(calls) == 1

    g.redraw(RedrawKind.DIE)

    assert len(calls) == 1, "redraw must not refire ON_DRAFT_FROM"


def test_on_hand_dealt_fires_for_options_but_not_the_from_room(probe_registry, cfg, probe):
    """ON_HAND_DEALT fires once per room offered as a hand option, and never
    for the room the hand was drafted from -- the from-room's own event is
    ON_DRAFT_FROM, a distinct hook."""
    calls = probe(Hook.ON_HAND_DEALT)
    g = Game(cfg, seed=3, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    cell = 12
    g._place_room(corridor, cell, N | S)
    g.state.pos = cell

    pending = g.open_door(cell, S)

    option_ids = {g.registry.rooms[o.room_idx].id for o in pending.options}
    fired_ids = {room_id for _, room_id in calls}
    assert fired_ids == option_ids
    assert "corridor" not in fired_ids


def test_on_hand_dealt_refires_for_the_new_options_on_redraw(probe_registry, cfg, probe):
    """Unlike ON_DRAFT_FROM, ON_HAND_DEALT fires again on every redraw: a
    room re-entering the hand is exactly the event it exists to model
    (e.g. the Dovecote's free rotation applies while drawn, not while
    placed, so it needs to know about every hand it appears in)."""
    calls = probe(Hook.ON_HAND_DEALT)
    g = Game(cfg, seed=4, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    cell = 12
    g._place_room(corridor, cell, N | S)
    g.state.pos = cell
    g.state.dice = 1

    g.open_door(cell, S)
    first_count = len(calls)
    assert first_count > 0

    g.redraw(RedrawKind.DIE)

    assert len(calls) > first_count, "a redealt hand must refire ON_HAND_DEALT"


def test_outer_draft_fires_on_hand_dealt_but_never_on_draft_from(probe_registry, cfg, probe):
    """Outer-room drafts sit off the grid with from_cell=-1, so there is no
    from-room to attribute a deal to: ON_DRAFT_FROM must never fire there,
    while ON_HAND_DEALT still fires for each dealt outer-room option (it is
    about the OPTION rooms, which outer drafts have just like grid ones)."""
    hand_calls = probe(Hook.ON_HAND_DEALT)
    from_calls = probe(Hook.ON_DRAFT_FROM)
    g = Game(cfg, seed=5, registry=probe_registry)
    # Bypass the real Garage/breaker navigation puzzle: stand at the
    # doorstep directly, which is all outer_draft_available() requires.
    g.state.area = "west_path"

    pending = g.open_outer_draft()

    assert from_calls == []
    option_ids = {g.registry.rooms[o.room_idx].id for o in pending.options}
    fired_ids = {room_id for _, room_id in hand_calls}
    assert fired_ids == option_ids
    assert len(hand_calls) == len(pending.options)


def test_on_arrive_fires_on_re_entry_where_on_enter_does_not(probe_registry, cfg, probe):
    """ON_ARRIVE fires on a second arrival at an already-entered cell -- the
    property ON_ENTER explicitly lacks, since Game._enter returns early once
    state.entered[cell] is already True."""
    enter_calls = probe(Hook.ON_ENTER)
    arrive_calls = probe(Hook.ON_ARRIVE)
    g = Game(cfg, seed=6, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    a, b, c = 7, 12, 17
    for cell in (a, b, c):
        g._place_room(corridor, cell, N | S)
    g.state.pos = a
    g.state.entered[a] = True

    g.move(N)  # a -> b: first arrival at b (N increases rank)
    g.move(N)  # b -> c: first arrival at c
    enter_count = len(enter_calls)
    arrive_count = len(arrive_calls)

    g.move(S)  # c -> b: SECOND arrival at b

    assert len(enter_calls) == enter_count, "ON_ENTER must not refire on re-entry"
    assert len(arrive_calls) == arrive_count + 1, "ON_ARRIVE must fire again on re-entry"


def test_on_arrive_fires_for_a_grid_anchor_landing_via_travel_to(probe_registry, cfg, probe):
    """travel_to's grid-anchor arrival branch (how the player lands back on
    the grid from an outer area) is a second ON_ARRIVE fire site distinct
    from move(); the Entrance Hall is already entered at day start, so
    travelling back to it here is unambiguously a re-entry, and ON_ARRIVE
    must fire anyway since it is never gated on state.entered."""
    arrive_calls = probe(Hook.ON_ARRIVE)
    g = Game(cfg, seed=7, registry=probe_registry)
    assert g.state.entered[ENTRANCE_CELL]
    g.state.area = "west_path"
    g.state.west_gate_unlatched = True  # opens the west_path->grounds->house route

    g.travel_to("house")

    assert (Hook.ON_ARRIVE, "entrance_hall") in arrive_calls


def test_on_day_end_fires_for_the_room_the_day_ends_in(probe_registry, cfg, probe):
    """ON_DAY_END fires for whichever on-grid room the player is standing in
    when the day terminates -- the fire site Tomorrow Rooms need, since
    today they have no hook at all to hang their end-of-day bonus on."""
    calls = probe(Hook.ON_DAY_END)
    g = Game(cfg, seed=8, registry=probe_registry)
    corridor = probe_registry.by_id["corridor"]
    a, b = 7, 12
    g._place_room(corridor, a, N | S)
    g._place_room(corridor, b, N | S)
    g.state.pos = a
    g.state.entered[a] = True
    g.state.steps = 1

    g.move(N)  # a -> b (N increases rank), spends the last step and ends the day there

    assert g.is_done()[0]
    assert calls == [(Hook.ON_DAY_END, "corridor")]


def test_on_day_end_fires_for_the_drafted_outer_room_when_inside_it(probe_registry, cfg, probe):
    """ON_DAY_END also fires for the off-grid drafted outer room while the
    player stands inside it, not only for on-grid rooms -- Tomorrow-style
    effects are not a grid-only concept."""
    calls = probe(Hook.ON_DAY_END)
    g = Game(cfg, seed=9, registry=probe_registry)
    outer_room = g.outer_rooms[0]
    g.placed_ids.add(outer_room.id)
    g.state.outer_room_drafted = True
    g.state.area = outer_room.id
    g.state.steps = 0

    g._check_termination()

    assert calls == [(Hook.ON_DAY_END, outer_room.id)]
