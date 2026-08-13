"""tools/validate_data.py's registry-typo guard and effects=[] census (task 23).

Task 22 moved a lot of behaviour OUT of rooms.json/special_items.json's
``effects`` arrays and into per-room/per-item Python, registered at import
time through four registries in engine/effects/__init__.py: ``room_hook``,
``Capability`` (via ``provides``/``provides_lever``), ``ItemCapability`` (via
``item_provides``), and ``ItemHook`` (via ``item_hook``). Two things had no
coverage outside the dedicated registry test files
(test_room_registry.py/test_item_registry.py/test_item_hook_registry.py):

1. A typo'd id in any of the four registries -- ``tools/validate_data.py``
   never called ``validate_room_registry``/``validate_capability_registry``/
   ``validate_item_registry``/``validate_item_hook_registry``, so a bad id
   was only ever caught by running pytest.
2. ``effects: []`` no longer means "does nothing" now that behaviour can
   live in one of those four registries instead -- nothing surfaced whether
   an empty-effects record was registered elsewhere or genuinely inert, or
   whether its own prose (effect_text/notes) still agreed with the code.

These tests exercise both: the wiring (probes registered on bogus ids must
make a bare ``main([])`` run fail, mirroring how the dedicated registry test
files probe the raw registries) and the census logic itself
(``find_empty_effects_findings``, a pure function over constructed
room/item dicts and registered-id sets, so it needs no probe teardown).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tools/ is not a proper package; insert the repo root so the import works,
# mirroring tests/test_divergence_audit.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate_data import find_empty_effects_findings, main  # noqa: E402

from blueprince_sim.engine.effects import (  # noqa: E402
    Capability,
    Hook,
    ItemCapability,
    ItemHook,
    _CAPABILITY_REGISTRY,
    _ITEM_CAPABILITY_REGISTRY,
    _ITEM_HOOK_REGISTRY,
    _ROOM_REGISTRY,
    item_hook,
    item_provides,
    provides,
    registered_capability_rooms,
    registered_item_capability_ids,
    registered_item_hook_ids,
    registered_rooms,
    room_hook,
)

# A single id, deliberately absent from rooms.json/special_items.json, reused
# by every probe below -- so a probe's own teardown can never collide with a
# real production registration the way reusing e.g. "coupon_book" would.
_BOGUS_ID = "__task23_bogus_id__"


# ─────────────────────────────── probes ────────────────────────────────────
# Each probe registers on _BOGUS_ID and removes exactly that registration at
# teardown, mirroring room_probe/item_capability_probe/item_hook_probe in the
# three dedicated registry test files -- the registries are module-global, so
# a leaked registration would corrupt any other suite that imports
# engine.effects.


@pytest.fixture()
def room_hook_probe():
    """Register a temporary ``room_hook`` handler on ``_BOGUS_ID`` and remove
    it at teardown."""
    room_hook(_BOGUS_ID, Hook.ON_ENTER)(lambda game, room, context_room: None)
    yield
    _ROOM_REGISTRY.pop((_BOGUS_ID, Hook.ON_ENTER), None)


@pytest.fixture()
def capability_probe():
    """Register a temporary ``provides`` capability on ``_BOGUS_ID`` and
    remove it at teardown."""
    provides(_BOGUS_ID, Capability.COMMERCE)
    yield
    _CAPABILITY_REGISTRY.discard((_BOGUS_ID, Capability.COMMERCE))


@pytest.fixture()
def item_capability_probe():
    """Register a temporary ``item_provides`` capability on ``_BOGUS_ID`` and
    remove it at teardown."""
    item_provides(_BOGUS_ID, ItemCapability.SHOP_DISCOUNT, amount=1)
    yield
    _ITEM_CAPABILITY_REGISTRY.pop((_BOGUS_ID, ItemCapability.SHOP_DISCOUNT), None)


@pytest.fixture()
def item_hook_probe():
    """Register a temporary ``item_hook`` handler on ``_BOGUS_ID`` and remove
    it at teardown."""
    item_hook(_BOGUS_ID, ItemHook.GEM_COST)(lambda state, registry, *args: None)
    yield
    _ITEM_HOOK_REGISTRY.pop((_BOGUS_ID, ItemHook.GEM_COST), None)


# ────────────────────── wiring: main() calls all four ──────────────────────


def test_main_is_clean_on_real_data():
    """Sanity baseline: with no probes registered, a bare run exits 0 -- every
    test below mutates a module-global registry and must leave this true
    again once its probe is torn down."""
    assert main([]) == 0


def test_main_flags_a_bogus_room_hook_registration(capsys, room_hook_probe):
    """A room_hook registered for an id absent from rooms.json makes a bare
    ``validate_data.py`` run fail -- previously this typo class was only
    caught by running pytest (test_room_registry.py), never by the tool
    every commit is gated on."""
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert _BOGUS_ID in out
    assert "room_hook" in out

    _ROOM_REGISTRY.pop((_BOGUS_ID, Hook.ON_ENTER), None)
    assert main([]) == 0, "reverting the mutation must restore a clean run"


def test_main_flags_a_bogus_capability_registration(capsys, capability_probe):
    """A ``provides``/``provides_lever`` registration for an unknown room id
    makes a bare run fail, the same class of typo validate_capability_registry
    exists to catch."""
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert _BOGUS_ID in out
    assert "provides" in out

    _CAPABILITY_REGISTRY.discard((_BOGUS_ID, Capability.COMMERCE))
    assert main([]) == 0, "reverting the mutation must restore a clean run"


def test_main_flags_a_bogus_item_provides_registration(capsys, item_capability_probe):
    """An ``item_provides`` registration for an unknown item id makes a bare
    run fail."""
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert _BOGUS_ID in out
    assert "item_provides" in out

    _ITEM_CAPABILITY_REGISTRY.pop((_BOGUS_ID, ItemCapability.SHOP_DISCOUNT), None)
    assert main([]) == 0, "reverting the mutation must restore a clean run"


def test_main_flags_a_bogus_item_hook_registration(capsys, item_hook_probe):
    """An ``item_hook`` registration for an unknown item id makes a bare run
    fail."""
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert _BOGUS_ID in out
    assert "item_hook" in out

    _ITEM_HOOK_REGISTRY.pop((_BOGUS_ID, ItemHook.GEM_COST), None)
    assert main([]) == 0, "reverting the mutation must restore a clean run"


def test_main_prints_the_empty_effects_census_line(capsys):
    """The effects=[] census prints unconditionally (not gated behind
    --audit) so it is visible on every plain run, not an opt-in flag nobody
    remembers to pass."""
    main([])
    out = capsys.readouterr().out
    assert "effects=[] census:" in out
    assert "registered via room_hook/Capability" in out
    assert "registered via item_provides/item_hook" in out


# ───────────────── registered_* introspection helpers ──────────────────────


def test_registered_capability_rooms_reflects_provides(capability_probe):
    """registered_capability_rooms() includes an id the moment ``provides``
    registers it, and drops it once the probe's teardown pops it -- mirrors
    registered_rooms()'s contract for room_hook."""
    assert _BOGUS_ID in registered_capability_rooms()


def test_registered_capability_rooms_excludes_unregistered_ids():
    """A room id with no ``provides``/``provides_lever`` registration is
    absent from registered_capability_rooms() -- the negative case."""
    assert _BOGUS_ID not in registered_capability_rooms()


def test_registered_item_capability_ids_reflects_item_provides(item_capability_probe):
    """registered_item_capability_ids() includes an id the moment
    ``item_provides`` registers it."""
    assert _BOGUS_ID in registered_item_capability_ids()


def test_registered_item_hook_ids_reflects_item_hook(item_hook_probe):
    """registered_item_hook_ids() includes an id the moment ``item_hook``
    registers a handler for it."""
    assert _BOGUS_ID in registered_item_hook_ids()


def test_throne_room_is_registered_via_capability():
    """Sanity check the real production registration this task's motivating
    incident hinges on: throne_room's Antechamber lever is registered via
    provides_lever (engine/effects/rooms/throne_room.py), so it appears in
    registered_capability_rooms() even though rooms.json's own effects list
    for it is empty."""
    assert "throne_room" in registered_rooms() | registered_capability_rooms()


# ────────────────── find_empty_effects_findings (pure) ─────────────────────


def _room(rid: str, effects=None, text: str = "") -> dict:
    """Build a minimal rooms.json-shaped record with only the fields
    find_empty_effects_findings reads (id, effects, meta.effect_text)."""
    return {"id": rid, "effects": effects or [], "meta": {"effect_text": text}}


def _item(iid: str, effects=None, notes: str = "") -> dict:
    """Build a minimal special_items.json-shaped record with only the fields
    find_empty_effects_findings reads (id, effects, meta.notes)."""
    return {"id": iid, "effects": effects or [], "meta": {"notes": notes}}


def test_registered_empty_room_with_accurate_prose_is_not_a_warning():
    """An empty-effects room that IS registered, whose prose does not claim
    'no effect', produces no warning -- this is exactly what task 22
    intended (behaviour moved to code), not a defect."""
    rooms = [_room("r1", text="Some accurate description of code-side behaviour.")]
    findings, n_empty, n_reg, _, _ = find_empty_effects_findings(
        rooms, [], frozenset({"r1"}), frozenset())
    assert findings == []
    assert (n_empty, n_reg) == (1, 1)


def test_registered_empty_room_whose_prose_denies_any_effect_is_a_warning():
    """The throne_room incident itself: effects=[], registered (room_hook or
    Capability), but effect_text claims 'no effect modeled' -- the prose has
    drifted from the code and must be promoted to a warning, not silently
    counted as fine."""
    rooms = [_room("throne_room", text="Entirely out of scope; no effect modeled.")]
    findings, n_empty, n_reg, _, _ = find_empty_effects_findings(
        rooms, [], frozenset({"throne_room"}), frozenset())
    assert len(findings) == 1
    assert "throne_room" in findings[0]
    assert (n_empty, n_reg) == (1, 1)


def test_unregistered_empty_room_whose_prose_denies_any_effect_is_not_a_warning():
    """An empty-effects room that is genuinely NOT registered and whose prose
    says so (e.g. closed_exhibit's real 'no effect modeled' text) is
    consistent, not contradictory -- no warning, because the warning fires
    only when the registry and the prose disagree."""
    rooms = [_room("closed_exhibit", text="Out of scope; no effect modeled.")]
    findings, n_empty, n_reg, _, _ = find_empty_effects_findings(
        rooms, [], frozenset(), frozenset())
    assert findings == []
    assert (n_empty, n_reg) == (1, 0)


def test_room_with_nonempty_effects_is_excluded_from_the_census():
    """A room whose effects list is non-empty is not part of this census at
    all, regardless of registration or prose -- the whole check is scoped to
    effects=[] records."""
    rooms = [_room("r1", effects=[{"tag": "grant"}], text="no effect modeled")]
    findings, n_empty, n_reg, _, _ = find_empty_effects_findings(
        rooms, [], frozenset({"r1"}), frozenset())
    assert findings == []
    assert (n_empty, n_reg) == (0, 0)


def test_modelled_british_spelling_also_matches():
    """The prose marker matches both 'modeled' and 'modelled' -- the
    codebase's own effect_text strings use the American spelling
    consistently today, but the check must not silently miss the British
    one if a future record uses it."""
    rooms = [_room("r1", text="No effect modelled here.")]
    findings, *_ = find_empty_effects_findings(rooms, [], frozenset({"r1"}), frozenset())
    assert len(findings) == 1


def test_item_registered_with_accurate_notes_is_not_a_warning():
    """The item-side mirror of the room case: coupon_book-shaped -- effects=[],
    registered (item_provides), notes describe the real behaviour -- no
    warning."""
    items = [_item("coupon_book", notes="Registered as SHOP_DISCOUNT amount=1.")]
    findings, _, _, n_empty, n_reg = find_empty_effects_findings(
        [], items, frozenset(), frozenset({"coupon_book"}))
    assert findings == []
    assert (n_empty, n_reg) == (1, 1)


def test_item_registered_whose_notes_deny_any_effect_is_a_warning():
    """The item-side mirror of the throne_room incident: effects=[],
    registered (item_provides or item_hook), but meta.notes claims no effect
    is modelled."""
    items = [_item("gizmo", notes="No effect modeled; purely cosmetic pickup.")]
    findings, _, _, n_empty, n_reg = find_empty_effects_findings(
        [], items, frozenset(), frozenset({"gizmo"}))
    assert len(findings) == 1
    assert "gizmo" in findings[0]
    assert (n_empty, n_reg) == (1, 1)


def test_item_with_nonempty_effects_is_excluded_from_the_census():
    """An item whose effects list is non-empty is excluded from the item
    census the same way a non-empty room is excluded from the room one."""
    items = [_item("gizmo", effects=[{"tag": "luck_bonus"}], notes="no effect modeled")]
    findings, _, _, n_empty, n_reg = find_empty_effects_findings(
        [], items, frozenset(), frozenset({"gizmo"}))
    assert findings == []
    assert (n_empty, n_reg) == (0, 0)


def test_counts_tally_rooms_and_items_independently():
    """The four returned counts track rooms and items in separate columns --
    a registered item must not inflate the room registered count or vice
    versa."""
    rooms = [_room("r1"), _room("r2")]
    items = [_item("i1"), _item("i2"), _item("i3")]

    findings, n_empty_rooms, n_room_reg, n_empty_items, n_item_reg = (
        find_empty_effects_findings(rooms, items, frozenset({"r1"}), frozenset({"i1", "i2"})))

    assert findings == []
    assert (n_empty_rooms, n_room_reg) == (2, 1)
    assert (n_empty_items, n_item_reg) == (3, 2)


def test_real_data_has_no_prose_registry_contradictions():
    """Run the census against the live rooms.json/special_items.json content
    (through Registry.load(), the same source main() itself uses) and assert
    zero contradiction warnings -- pinning that the throne_room-class
    incident is currently fixed on real data, not just in a constructed
    fixture. Complements test_divergence_audit.py's
    test_default_validate_data_run_reports_zero_warnings, which checks the
    same thing indirectly through main()."""
    import json

    from blueprince_sim.engine.model import Registry

    reg = Registry.load()
    rooms = json.loads((reg.data_dir / "rooms.json").read_text())["rooms"]
    si_items = json.loads((reg.data_dir / "special_items.json").read_text())["items"]

    room_registered_ids = registered_rooms() | registered_capability_rooms()
    item_registered_ids = registered_item_capability_ids() | registered_item_hook_ids()

    findings, *_ = find_empty_effects_findings(
        rooms, si_items, room_registered_ids, item_registered_ids)

    assert findings == []
