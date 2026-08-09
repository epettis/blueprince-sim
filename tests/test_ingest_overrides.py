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


def test_effect_override_raises_for_unknown_id():
    """validate_effect_override raises when an override id is missing from seen_ids.

    Simulates a typo'd or renamed EFFECT_OVERRIDE key by dropping a real one
    ("vault") from seen_ids, proving the ingest fails loudly instead of the
    override silently never being looked up.
    """
    seen_ids = set(ingest_sheet.EFFECT_OVERRIDE) - {"vault"}
    with pytest.raises(ValueError, match="vault"):
        ingest_sheet.validate_effect_override(seen_ids)
