"""tools/validate_data.py's room-fidelity divergence audit.

Exercises the detector (``find_divergences``) against constructed inputs rather
than the live ``rooms.json``, so these tests keep pinning the *rule*, not
today's finding count -- the count is expected to shrink as the audit's
worklist gets fixed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tools/ is not a proper package; insert the repo root so the import works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate_data import (  # noqa: E402
    _AUDIT_COMMERCE_EXTRA_IDS,
    _AUDIT_DATA_EXEMPT_IDS,
    _AUDIT_PYTHON_EXEMPT_IDS,
    _AUDIT_STRUCTURAL_EXEMPT_IDS,
    _assert_python_exemptions_live,
    find_divergences,
    main,
)

from blueprince_sim.engine.effects import (  # noqa: E402
    Hook,
    _ROOM_REGISTRY,
    room_hook,
)


def _room(id, variant_of=None, text="", effects=None, guaranteed=None):
    """Build a minimal rooms.json-shaped record with only the fields
    find_divergences reads (id, variant_of, meta.effect_text, effects,
    items.guaranteed)."""
    return {
        "id": id,
        "variant_of": variant_of,
        "meta": {"effect_text": text},
        "effects": effects or [],
        "items": {"guaranteed": guaranteed or []},
    }


EMPTY_LOCKS = {"always_unlocked_rooms": {"rooms": []}}


@pytest.fixture()
def room_probe():
    """Register a temporary ``room_hook`` handler and remove it at teardown.

    ``_ROOM_REGISTRY`` is module-global in ``engine.effects``, shared with
    every other suite that imports it, so a registration leaked past a test
    would silently change ``find_divergences`` (and ``fire()``) behaviour
    elsewhere. Mirrors the identical fixture in ``tests/test_room_registry.py``.
    """
    registered: list[tuple[str, Hook]] = []

    def _register(room_id: str, hook: Hook = Hook.ON_ENTER) -> None:
        room_hook(room_id, hook)(lambda game, room, context_room: None)
        registered.append((room_id, hook))

    yield _register

    for room_id, hook in registered:
        _ROOM_REGISTRY.pop((room_id, hook), None)


def test_variant_identical_to_parent_with_differing_text_is_flagged():
    """An upgrade variant whose effects/items match its parent's but whose
    effect_text differs is a kind-1 finding: the variant step was never
    authored even though the flavor text promises something new."""
    base = _room("base", text="")
    variant = _room("var", variant_of="base", text="gain 5 steps")
    rooms = [base, variant]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert any("var" in f for f in kind1)


def test_variant_with_genuinely_different_modelling_is_not_flagged():
    """A variant whose effects actually differ from its parent's is not a
    kind-1 finding, since it demonstrably does something the parent doesn't."""
    base = _room("base", text="gain 5 steps",
                  effects=[{"tag": "grant", "resource": "steps", "amount": 5}])
    variant = _room("var", variant_of="base", text="gain 8 steps",
                     effects=[{"tag": "grant", "resource": "steps", "amount": 8}])
    rooms = [base, variant]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert not any("var" in f for f in kind1)


def test_record_with_effect_text_and_no_modelling_is_flagged():
    """A record with non-empty effect_text but no effects and no
    items.guaranteed is a kind-2 finding: it describes unmodelled behaviour."""
    room = _room("unmodelled", text="Whenever something happens, do a thing.")
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert any("unmodelled" in f for f in kind2)


def test_record_with_registered_room_handler_is_not_flagged(room_probe):
    """A record with effect_text and no data modelling is not a kind-2
    finding once its own room id has a room_hook registration -- the
    behaviour is implemented in Python (engine/effects/rooms/), not in
    effects/items.guaranteed, so the audit must not call it unmodelled."""
    room = _room("handled_in_python", text="Whenever something happens, do a thing.")
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}
    room_probe("handled_in_python")

    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)

    assert not any("handled_in_python" in f for f in kind2)


def test_record_without_any_handler_is_still_flagged():
    """The same shape of record with no room_hook registration at all stays
    a kind-2 finding -- confirms the registry-awareness only suppresses
    rooms that are actually registered, not every record unconditionally."""
    room = _room("nobody_implements_this", text="Whenever something happens, do a thing.")
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}

    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)

    assert any("nobody_implements_this" in f for f in kind2)


def test_variant_of_a_registered_root_is_still_flagged(room_probe):
    """A variant whose chain root has a room_hook handler, but which has no
    handler registered for its own id, stays a kind-2 finding -- a handler
    only covers the exact room id it was registered for, so the variant's
    own text is still unmodelled from this check's point of view."""
    base = _room("registered_root", text="")
    variant = _room("registered_root__ix1", variant_of="registered_root",
                     text="Whenever something happens, do a thing.")
    rooms = [base, variant]
    by_id = {r["id"]: r for r in rooms}
    room_probe("registered_root")

    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)

    assert any("registered_root__ix1" in f for f in kind2)


def test_record_with_no_effect_text_is_not_flagged():
    """A room with a blank effect_text and no modelling is not a kind-2
    finding -- there is no described behaviour for it to be missing."""
    room = _room("plain", text="")
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert not any("plain" in f for f in kind2)


def test_blank_text_variant_is_not_flagged():
    """A variant whose own effect_text is blank cannot diverge from its
    parent's text, so it is excluded from kind-1 even if modelling matches."""
    base = _room("base", text="")
    variant = _room("mid_stage", variant_of="base", text="")
    rooms = [base, variant]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert not any("mid_stage" in f for f in kind1)
    assert not any("mid_stage" in f for f in kind2)


def test_second_level_variant_compares_against_immediate_parent():
    """A two-level variant chain (root -> mid -> child, e.g. the Spare Room)
    is judged against its immediate parent's modelling, not the chain root:
    child copies mid's effects verbatim while promising new text, which is
    only visible by diffing against mid -- diffing against the blank-slate
    root would miss it entirely, since root's effects don't match either."""
    root = _room("root", text="")
    mid = _room("mid", variant_of="root", text="gain 5 steps",
                effects=[{"tag": "grant", "resource": "steps", "amount": 5}])
    child = _room("child", variant_of="mid", text="gain 5 steps and glow",
                  effects=[{"tag": "grant", "resource": "steps", "amount": 5}])
    rooms = [root, mid, child]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)
    assert any("child" in f for f in kind1)


def test_variant_with_own_handler_is_not_a_kind1_finding(room_probe):
    """A variant whose effects/items.guaranteed match its parent's, and whose
    effect_text differs, is not a kind-1 finding once its own room id has a
    room_hook registration -- the upgrade step is authored in Python even
    though the data comparison alone would call it identical to the parent."""
    base = _room("base", text="")
    variant = _room("var", variant_of="base", text="gain 5 steps")
    rooms = [base, variant]
    by_id = {r["id"]: r for r in rooms}
    room_probe("var")

    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS)

    assert not any("var" in f for f in kind1)


def test_structural_exemption_suppresses_locks_json_implemented_rooms():
    """Rooms whose 'always unlocked' behaviour lives in locks.json's
    always_unlocked_rooms table (not effects/items) are excluded from both
    finding kinds by exact id, so the audit doesn't flag mechanics that are
    modelled elsewhere in the engine."""
    exempt_id = next(iter(_AUDIT_STRUCTURAL_EXEMPT_IDS))
    room = _room(exempt_id, text="This room's doors are always unlocked.")
    lock_rules = {"always_unlocked_rooms": {"rooms": list(_AUDIT_STRUCTURAL_EXEMPT_IDS)}}
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}
    kind1, kind2 = find_divergences(rooms, by_id, lock_rules)
    assert not any(exempt_id in f for f in kind1)
    assert not any(exempt_id in f for f in kind2)


def test_priced_shops_from_shops_json_are_exempt():
    """A room named in shops.json's "shops" table is excluded from both finding
    kinds: its effect_text says only that it trades, and engine/shops.py
    implements that in full, so flagging it would measure the audit's blind
    spot rather than a gap in the sim."""
    room = _room("locksmith", text="Keys for Sale")
    rooms = [room]
    by_id = {r["id"]: r for r in rooms}

    kind1, kind2 = find_divergences(rooms, by_id, EMPTY_LOCKS,
                                    shop_rules={"shops": {"locksmith": {}}})

    assert not any("locksmith" in f for f in kind1)
    assert not any("locksmith" in f for f in kind2)


def test_commerce_rooms_absent_from_the_shops_table_are_still_exempt():
    """The Trading Post and Workshop have no shops.json "shops" entry but their
    behaviour still lives in engine/shops.py, so they are exempt by id."""
    for rid in _AUDIT_COMMERCE_EXTRA_IDS:
        room = _room(rid, text="Combine inventory to create new items")
        by_id = {rid: room}

        kind1, kind2 = find_divergences([room], by_id, EMPTY_LOCKS, shop_rules={})

        assert not any(rid in f for f in kind1), rid
        assert not any(rid in f for f in kind2), rid


def test_a_non_commerce_room_is_not_exempted_by_the_shops_table():
    """The exemption keys off the room id, never off the effect text, so an
    ordinary room claiming to sell something is still flagged -- otherwise a
    genuinely unmodelled shop-like mechanic would vanish from the worklist."""
    room = _room("some_other_room", text="Items for Sale")
    by_id = {"some_other_room": room}

    _kind1, kind2 = find_divergences([room], by_id, EMPTY_LOCKS,
                                     shop_rules={"shops": {"locksmith": {}}})

    assert any("some_other_room" in f for f in kind2)


def test_omitting_shop_rules_exempts_only_the_by_id_commerce_rooms():
    """With no shop_rules passed, a priced shop is flagged again -- the
    exemption follows the data handed in, so a caller cannot silently inherit
    a shops table it never supplied."""
    room = _room("locksmith", text="Keys for Sale")
    by_id = {"locksmith": room}

    _kind1, kind2 = find_divergences([room], by_id, EMPTY_LOCKS)

    assert any("locksmith" in f for f in kind2)


def test_python_and_data_exempt_rooms_are_excluded_from_both_kinds():
    """A room modelled by a hand-written branch keyed on its id, or one whose
    text merely restates a field it already carries, is not a finding -- those
    are channels the audit cannot introspect, not gaps in the sim."""
    for rid in list(_AUDIT_PYTHON_EXEMPT_IDS) + list(_AUDIT_DATA_EXEMPT_IDS):
        room = _room(rid, text="Something this room does.")
        by_id = {rid: room}

        kind1, kind2 = find_divergences([room], by_id, EMPTY_LOCKS)

        assert not any(rid in f for f in kind1), rid
        assert not any(rid in f for f in kind2), rid


def test_python_exemption_liveness_check_fires_when_the_id_is_gone(tmp_path):
    """The liveness check must fail when an exempt room's id no longer appears
    in the module it names.

    The exemption is a claim that the room is modelled somewhere the audit
    cannot see, and that claim rots silently the moment the implementation
    moves or is deleted -- the room would simply stay off the worklist. This
    pins that the guard actually catches it."""
    rid, rel = next(iter(sorted(_AUDIT_PYTHON_EXEMPT_IDS.items())))
    stub = tmp_path / rel
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("# an implementation that no longer mentions the room\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=rid):
        _assert_python_exemptions_live(tmp_path)


def test_python_exemption_liveness_check_passes_on_the_real_tree():
    """Every Python-exempt id really does still appear in the module it names,
    so the shipped exemption list is not already stale."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "blueprince_sim"
    _assert_python_exemptions_live(src_root)


def test_default_validate_data_run_reports_zero_warnings():
    """python tools/validate_data.py with no flags must still report 0 errors
    and 0 warnings and exit 0 -- the divergence audit's ~100+ findings must
    never leak into the errors/warnings counts that gate every commit."""
    rc = main([])
    assert rc == 0


def test_default_run_prints_zero_errors_and_warnings_in_summary(capsys):
    """The printed summary line reports 0 errors, 0 warnings by default, and
    no 'warning:'/'ERROR:' detail lines are emitted -- confirming the audit
    findings are not merely uncounted but genuinely not printed either."""
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 errors, 0 warnings" in out
    assert "warning:" not in out
    assert "ERROR:" not in out


def test_audit_flag_prints_findings_and_still_exits_zero(capsys):
    """--audit prints the divergence worklist under its own labelled section
    and still exits 0, since a worklist of unfinished audit items is not a
    validation failure."""
    rc = main(["--audit"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "divergence audit" in out
    assert "audit[kind1]:" in out or "audit[kind2]:" in out
