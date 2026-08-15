"""Proves tools/ingest_sheet.py's EFFECT_OVERRIDE table reproduces data/rooms.json.

This module is a deliberate, narrow exception to the CLAUDE.md rule "test
observable behaviour, not data contents": the property under test is that two
representations of the same data - the override table hand-authored in
tools/ingest_sheet.py and the committed src/blueprince_sim/data/rooms.json -
agree with each other. That agreement (a re-ingest reproducing the audited
fixes) is the entire point of the override table, so comparing data to data
is correct here rather than a change-detector test. No other test in this
suite should read this as licence to do the same.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROOMS_JSON = ROOT / "src" / "blueprince_sim" / "data" / "rooms.json"


def _load_ingest_sheet():
    """Import tools/ingest_sheet.py by file path, without running its ``main()``.

    ``spec_from_file_location`` loads the module under a private name so it
    never collides with ``__main__``, and the module only touches disk from
    inside ``main()`` / ``parse_rows()``, neither of which import triggers.
    """
    spec = importlib.util.spec_from_file_location(
        "ingest_sheet_under_test", ROOT / "tools" / "ingest_sheet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingest_sheet = _load_ingest_sheet()


@pytest.fixture(scope="module")
def rooms_by_id() -> dict[str, dict]:
    """The committed rooms.json records, keyed by id."""
    data = json.loads(ROOMS_JSON.read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["rooms"]}


def test_effect_override_ids_all_exist_in_rooms_json(rooms_by_id):
    """Every EFFECT_OVERRIDE key names a record present in rooms.json - the typo guard."""
    missing = sorted(set(ingest_sheet.EFFECT_OVERRIDE) - set(rooms_by_id))
    assert not missing, f"EFFECT_OVERRIDE has id(s) absent from rooms.json: {missing}"


@pytest.mark.parametrize("room_id", sorted(ingest_sheet.EFFECT_OVERRIDE))
def test_effect_override_reproduces_committed_record(room_id, rooms_by_id):
    """Applying EFFECT_OVERRIDE to a blank record reproduces rooms.json's effects and items.guaranteed.

    apply_effect_override fully replaces entry["effects"] and
    entry["items"]["guaranteed"] rather than merging into whatever EFFECT_MAP
    set first, so seeding a blank record and applying the override in
    isolation faithfully simulates what build_room produces for the same id -
    without parsing tools/raw/ or running the full ingest.
    """
    entry = {"id": room_id, "effects": [], "items": {"guaranteed": []}}
    ingest_sheet.apply_effect_override(entry)
    committed = rooms_by_id[room_id]
    assert entry["effects"] == committed["effects"]
    assert entry["items"]["guaranteed"] == committed["items"]["guaranteed"]


def test_flag_override_ids_all_exist_in_rooms_json(rooms_by_id):
    """Every FLAG_OVERRIDE key names a record present in rooms.json - the typo guard."""
    missing = sorted(set(ingest_sheet.FLAG_OVERRIDE) - set(rooms_by_id))
    assert not missing, f"FLAG_OVERRIDE has id(s) absent from rooms.json: {missing}"


@pytest.mark.parametrize("room_id", sorted(ingest_sheet.FLAG_OVERRIDE))
def test_flag_override_reproduces_committed_flags(room_id, rooms_by_id):
    """Applying FLAG_OVERRIDE reproduces the flags rooms.json actually carries.

    The membership flags behind the Cloister of Dauja and Veia lists are there
    only because a human put them there, so without this the committed record
    and the ingest table could drift apart and a re-ingest would quietly drop a
    room out of its list.
    """
    entry = {"id": room_id, "effects": [], "items": {"guaranteed": []}, "flags": {}}
    ingest_sheet.apply_effect_override(entry)
    committed_flags = rooms_by_id[room_id]["flags"]
    assert entry["flags"], f"{room_id}: FLAG_OVERRIDE set nothing"
    for flag, value in entry["flags"].items():
        assert committed_flags.get(flag) == value, f"{room_id}: {flag}"


def test_alt_layouts_gate_ids_all_exist_in_rooms_json(rooms_by_id):
    """Every ALT_LAYOUTS_GATE key names a record present in rooms.json - the typo guard."""
    missing = sorted(set(ingest_sheet.ALT_LAYOUTS_GATE) - set(rooms_by_id))
    assert not missing, f"ALT_LAYOUTS_GATE has id(s) absent from rooms.json: {missing}"


@pytest.mark.parametrize("room_id", sorted(ingest_sheet.ALT_LAYOUTS_GATE))
def test_alt_layouts_gate_reproduces_committed_field(room_id, rooms_by_id):
    """The committed record's alt_layouts_gate matches the ingest table.

    alt_layouts_gate is a TOP-LEVEL field, unlike the effects/flags/
    extra_categories the sibling guards cover, and nothing else in this suite
    reads one. Without this, adding such a field to rooms.json without
    mirroring it here passes every test and is silently dropped by the next
    re-ingest -- the failure mode is a room quietly losing its gate, not a
    crash.
    """
    committed = rooms_by_id[room_id].get("alt_layouts_gate")
    assert committed == ingest_sheet.ALT_LAYOUTS_GATE[room_id], (
        f"{room_id}: rooms.json says {committed!r}, ingest table says "
        f"{ingest_sheet.ALT_LAYOUTS_GATE[room_id]!r}")


def test_no_room_carries_an_unmirrored_alt_layouts_gate(rooms_by_id):
    """No rooms.json record has an alt_layouts_gate the ingest table omits.

    The reverse direction of the guard above: rooms.json is generated, so a
    gate present there but absent from ALT_LAYOUTS_GATE survives only until
    someone regenerates the file.
    """
    unmirrored = sorted(
        rid for rid, rec in rooms_by_id.items()
        if rec.get("alt_layouts_gate") and rid not in ingest_sheet.ALT_LAYOUTS_GATE)
    assert not unmirrored, (
        f"alt_layouts_gate in rooms.json but not in ingest ALT_LAYOUTS_GATE: {unmirrored}")


def test_category_override_ids_all_exist_in_rooms_json(rooms_by_id):
    """Every CATEGORY_OVERRIDE key names a record present in rooms.json - the typo guard."""
    missing = sorted(set(ingest_sheet.CATEGORY_OVERRIDE) - set(rooms_by_id))
    assert not missing, f"CATEGORY_OVERRIDE has id(s) absent from rooms.json: {missing}"


@pytest.mark.parametrize("room_id", sorted(ingest_sheet.CATEGORY_OVERRIDE))
def test_category_override_reproduces_committed_extra_categories(room_id, rooms_by_id):
    """Applying CATEGORY_OVERRIDE reproduces the extra_categories rooms.json actually carries.

    The Aquarium family's "every colour" membership is there only because a
    human put it there, so without this the committed record and the ingest
    table could drift apart and a re-ingest would quietly drop a colour.
    """
    entry = {"id": room_id, "effects": [], "items": {"guaranteed": []}, "flags": {}}
    ingest_sheet.apply_effect_override(entry)
    committed = rooms_by_id[room_id]
    assert entry["extra_categories"], f"{room_id}: CATEGORY_OVERRIDE set nothing"
    assert set(entry["extra_categories"]) == set(committed["extra_categories"]), room_id


def test_meta_override_ids_all_exist_in_rooms_json(rooms_by_id):
    """Every META_OVERRIDE key names a record present in rooms.json - the typo guard."""
    missing = sorted(set(ingest_sheet.META_OVERRIDE) - set(rooms_by_id))
    assert not missing, f"META_OVERRIDE has id(s) absent from rooms.json: {missing}"


@pytest.mark.parametrize("room_id", sorted(ingest_sheet.META_OVERRIDE))
def test_meta_override_reproduces_committed_meta(room_id, rooms_by_id):
    """Applying META_OVERRIDE reproduces the meta.* fields rooms.json actually carries.

    meta.simplification (the Pump Room's macro-action disclosure,
    docs/areas.md's Pump Room section) is there only because a human put it
    there, so without this the committed record and the ingest table could
    drift apart and a re-ingest would quietly drop the disclosure.
    """
    entry = {"id": room_id, "effects": [], "items": {"guaranteed": []},
              "meta": {"source": "x", "confidence": "datamined"}}
    ingest_sheet.apply_effect_override(entry)
    committed_meta = rooms_by_id[room_id]["meta"]
    added = ingest_sheet.META_OVERRIDE[room_id]
    assert added, f"{room_id}: META_OVERRIDE set nothing"
    for key, value in added.items():
        assert committed_meta.get(key) == value, f"{room_id}: meta.{key}"


def test_no_room_carries_an_unmirrored_simplification(rooms_by_id):
    """No rooms.json record has a meta.simplification the ingest table omits.

    The reverse direction of the guard above: rooms.json is generated, so a
    simplification note present there but absent from META_OVERRIDE survives
    only until someone regenerates the file.
    """
    unmirrored = sorted(
        rid for rid, rec in rooms_by_id.items()
        if rec.get("meta", {}).get("simplification")
        and rid not in ingest_sheet.META_OVERRIDE)
    assert not unmirrored, (
        f"meta.simplification in rooms.json but not in ingest META_OVERRIDE: {unmirrored}")


def test_supplemental_member_rooms_carry_their_own_flags():
    """The three supplemental-sourced member rooms carry their membership flag
    in supplemental_rooms.json, which neither override table can reach.

    FLAG_OVERRIDE is validated against the sheet's own ids, so putting one of
    these there would raise rather than silently do nothing; this pins that the
    other source covers them instead.
    """
    supplemental = json.loads(
        (ROOT / "tools" / "supplemental_rooms.json").read_text(encoding="utf-8"))
    records = supplemental["rooms"] if isinstance(supplemental, dict) else supplemental
    by_id = {r["id"]: r for r in records}
    assert by_id["furnace"]["flags"].get("has_fireplace") is True
    assert by_id["dovecote"]["flags"].get("has_animal") is True
    assert by_id["the_kennel"]["flags"].get("has_animal") is True


def test_maids_chamber_carries_its_own_extra_categories():
    """Maid's Chamber is supplemental-sourced, so its "counts as bedroom too"
    membership lives directly in supplemental_rooms.json rather than in
    CATEGORY_OVERRIDE (which is validated against the sheet's own ids and
    would raise on a supplemental-only id rather than silently do nothing).
    """
    supplemental = json.loads(
        (ROOT / "tools" / "supplemental_rooms.json").read_text(encoding="utf-8"))
    records = supplemental["rooms"] if isinstance(supplemental, dict) else supplemental
    by_id = {r["id"]: r for r in records}
    assert by_id["maids_chamber"]["extra_categories"] == ["bedroom"]


def test_effect_override_raises_for_unknown_id():
    """validate_effect_override raises when an override id is missing from seen_ids.

    Simulates a typo'd or renamed EFFECT_OVERRIDE key by dropping a real one
    ("vault") from seen_ids, proving the ingest fails loudly instead of the
    override silently never being looked up.
    """
    seen_ids = set(ingest_sheet.EFFECT_OVERRIDE) - {"vault"}
    with pytest.raises(ValueError, match="vault"):
        ingest_sheet.validate_effect_override(seen_ids)
