"""Observable-firing tests for the room-id-keyed container-kinds registry.

``provides_containers`` keys a container-kinds overlay function by room id,
mirroring ``room_hook``'s per-room registry in engine/effects/__init__.py --
except it is a query (called on demand by ``_container_kinds_at``) rather
than an event handler ``fire`` calls at a hook. These tests exercise the
registry's own dispatch mechanics through temporary probe registrations,
torn down after every test (see ``container_probe``) -- the registry is
module-global, and a leaked registration would corrupt unrelated suites,
the same risk tests/test_room_registry.py's ``room_probe`` fixture guards
against.
"""

from __future__ import annotations

import pytest

from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.effects import (
    _CONTAINER_REGISTRY,
    container_kinds_for,
    provides_containers,
    registered_container_rooms,
    validate_container_registry,
)
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.state import GameState


@pytest.fixture()
def container_probe():
    """Register a temporary ``provides_containers`` overlay and return a
    registrar so a test can wire multiple room ids to distinct stub
    functions.

    Every registration this fixture makes is popped from the module-global
    ``_CONTAINER_REGISTRY`` dict at teardown, even if the test raises --
    otherwise a leaked stub overlay would silently change
    ``_container_kinds_at``'s behaviour for every later test file that
    imports engine.effects.
    """
    registered: list[str] = []

    def _register(room_id: str, fn) -> None:
        provides_containers(room_id)(fn)
        registered.append(room_id)

    yield _register

    for room_id in registered:
        _CONTAINER_REGISTRY.pop(room_id, None)


def _placed_state(registry, room_id: str, cell: int) -> GameState:
    """A fresh GameState with ``room_id`` placed at ``cell``, nothing opened."""
    state = GameState()
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    return state


def test_registered_overlay_wins_over_a_static_entry_for_the_same_room():
    """When a room id carries BOTH a static containers.rooms entry and a
    registered provides_containers overlay, dispatch must return the
    overlay's kinds, not the static table's -- _container_kinds_at is
    documented to consult the overlay first and fall back to the static
    table only when no overlay is registered, so this pins that ordering
    with two deliberately DIFFERENT kind names, not two values that could
    coincidentally agree.

    Uses its own ``Registry.load()`` (not the shared session ``registry``
    fixture) so the mutated static table can never leak into another test
    file, mirroring tests/test_containers.py's ``_state_with_registry``.
    """
    reg = Registry.load()
    cell = 5
    reg.special.containers["rooms"]["closet"] = {"static_stub_kind": 9}
    provides_containers("closet")(lambda state, reg, cell: {"overlay_stub_kind": 2})
    try:
        state = _placed_state(reg, "closet", cell)
        result = si._container_kinds_at(state, reg, cell)
        assert result == [("overlay_stub_kind", 2)], (
            "a registered overlay must win over a same-room static table entry"
        )
    finally:
        _CONTAINER_REGISTRY.pop("closet", None)


def test_unregistered_room_falls_through_to_the_static_table():
    """A room with no provides_containers overlay reads straight from the
    static containers.rooms table -- the fallback path _container_kinds_at
    takes for every room the Mechanarium/Entrance Hall/Planetarium overlays
    do NOT cover. The stub kind/count are authored directly into a scratch
    copy of the table here, independent of any value the engine itself
    would compute, so a broken fallback (or one that silently swallowed the
    static table) would show up as a mismatch.

    Uses its own ``Registry.load()``, same isolation reason as the test
    above.
    """
    reg = Registry.load()
    cell = 6
    assert "closet" not in registered_container_rooms(), "setup: closet must carry no overlay"
    reg.special.containers["rooms"]["closet"] = {"static_stub_kind": 4}
    state = _placed_state(reg, "closet", cell)
    result = si._container_kinds_at(state, reg, cell)
    assert result == [("static_stub_kind", 4)], (
        "an unregistered room must read its containers from the static table"
    )


def test_container_kinds_for_returns_none_for_an_unregistered_room(registry):
    """container_kinds_for itself (the dispatcher, one level below
    _container_kinds_at) returns None -- not {} -- for a room with no
    registered overlay; None is the sentinel _container_kinds_at's fallback
    branch keys on, so this pins the dispatcher's own contract in isolation
    from the fallback logic tested above.
    """
    assert container_kinds_for(GameState(), registry, "closet", 6) is None


def test_container_kinds_for_calls_the_registered_function_for_its_room(registry, container_probe):
    """container_kinds_for calls exactly the function registered for the
    room id it is asked about, passing (state, registry, cell) through
    unchanged -- proven with a stub that records its own call arguments
    rather than returning a fixed value, so this cannot pass by accident.
    """
    calls = []

    def stub(state, reg, cell):
        calls.append((state, reg, cell))
        return {"probe_kind": 1}

    container_probe("closet", stub)
    state = GameState()
    result = container_kinds_for(state, registry, "closet", 6)

    assert result == {"probe_kind": 1}
    assert calls == [(state, registry, 6)]


def test_registered_container_rooms_reflects_provides_containers(registry, container_probe):
    """registered_container_rooms() includes a room id the moment
    provides_containers registers it, mirroring registered_rooms()'s
    contract for room_hook."""
    assert "closet" not in registered_container_rooms()
    container_probe("closet", lambda state, reg, cell: {})
    assert "closet" in registered_container_rooms()


def test_unknown_room_id_container_validator_rejects_a_bogus_id(registry, container_probe):
    """validate_container_registry flags a provides_containers registration
    whose room id is absent from the Registry -- the failure mode a typo'd
    id would otherwise hit silently, since the overlay would simply never
    be asked about (no room ever has that id)."""
    assert validate_container_registry(registry) == []

    container_probe("dovecot", lambda state, reg, cell: {})

    assert "dovecot" in validate_container_registry(registry)
