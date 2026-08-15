"""tools/validate_data.py's membership_moves checks (find_membership_moves_findings).

priority_draws.json's membership_moves records a room conditionally migrating
from one priority_draws entry's own room list to another's (draft.py::
_apply_membership_moves); a bad record -- an unknown room, an unknown
'from'/'to' label, or a room absent from the 'from' entry's own rooms --
would otherwise fail silently at draft time (a no-op remove/add), so this
pins the validator catching each shape instead. See
tests/test_secret_passage_membership.py for the primitive's own runtime
behaviour.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

# tools/ is not a proper package; insert the repo root so the import works,
# mirroring tests/test_validate_data_registry_wiring.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate_data import find_membership_moves_findings  # noqa: E402

_PATIO = {"label": "patio_rooms", "rooms": ["patio", "secret_passage"]}
_GARAGE = {"label": "garage_classroom", "rooms": ["garage", "classroom"]}
_BY_ID = {"patio": {}, "secret_passage": {}, "garage": {}, "classroom": {}}


def _priority(move: dict) -> dict:
    """A fresh deep copy of the two-entry priority_draws fixture every call --
    a caller mutating the returned dict (see the duplicate-room test below)
    must never leak into another test via these shared module-level fixtures."""
    return {"priority_draws": [copy.deepcopy(_PATIO), copy.deepcopy(_GARAGE)],
            "membership_moves": [move]}


def test_a_well_formed_move_produces_no_findings():
    """Sanity baseline: a move naming a real room, a real 'from' label the
    room is actually in, and a real 'to' label the room is not yet in,
    produces zero errors and zero warnings."""
    move = {"room": "secret_passage", "from": "patio_rooms", "to": "garage_classroom",
            "condition": "greenhouse_placed"}
    errors, warnings = find_membership_moves_findings(_priority(move), _BY_ID)
    assert errors == []
    assert warnings == []


def test_rejects_an_unknown_room():
    """A room id absent from rooms.json (by_id) is an error -- the move would
    otherwise silently reference a room that can never actually be dealt."""
    move = {"room": "no_such_room", "from": "patio_rooms", "to": "garage_classroom",
            "condition": "greenhouse_placed"}
    errors, _ = find_membership_moves_findings(_priority(move), _BY_ID)
    assert any("no_such_room" in e and "unknown room" in e for e in errors)


def test_rejects_an_unknown_from_label():
    """A 'from' label that names no real priority_draws entry is an error --
    _apply_membership_moves would otherwise never match it against any real
    entry's label, silently never removing the room from anywhere."""
    move = {"room": "secret_passage", "from": "no_such_group", "to": "garage_classroom",
            "condition": "greenhouse_placed"}
    errors, _ = find_membership_moves_findings(_priority(move), _BY_ID)
    assert any("no_such_group" in e and "'from' label" in e for e in errors)


def test_rejects_an_unknown_to_label():
    """The 'to' half of the same check: an unresolvable 'to' label is an
    error, symmetric with the 'from' case above."""
    move = {"room": "secret_passage", "from": "patio_rooms", "to": "no_such_group",
            "condition": "greenhouse_placed"}
    errors, _ = find_membership_moves_findings(_priority(move), _BY_ID)
    assert any("no_such_group" in e and "'to' label" in e for e in errors)


def test_rejects_a_room_absent_from_the_from_entrys_rooms():
    """A room the 'from' entry never actually lists is an error -- there is
    nothing for the move to remove, so the record's own claim ('this room
    sits in that group') would be false on its face."""
    move = {"room": "garage", "from": "patio_rooms", "to": "garage_classroom",
            "condition": "greenhouse_placed"}
    errors, _ = find_membership_moves_findings(_priority(move), _BY_ID)
    assert any("garage" in e and "is not in 'patio_rooms'" in e for e in errors)


def test_rejects_a_room_already_present_in_the_to_entrys_rooms():
    """A room already listed in the 'to' entry is an error -- the move would
    duplicate it in that entry's resolved candidate list rather than adding
    it for the first time."""
    move = {"room": "garage", "from": "patio_rooms", "to": "garage_classroom",
            "condition": "greenhouse_placed"}
    by_id = dict(_BY_ID)
    priority = _priority(move)
    priority["priority_draws"][0]["rooms"] = ["patio", "garage"]  # so 'from' still holds
    errors, _ = find_membership_moves_findings(priority, by_id)
    assert any("garage" in e and "already in 'garage_classroom'" in e for e in errors)


def test_warns_on_a_condition_naming_no_gamestate_attribute():
    """A 'condition' that names no real GameState attribute is a permissive
    warning (matching every other condition-tag check in this module) -- at
    draft time, getattr degrades a typo to a silent no-op rather than a
    crash, so it must not be a hard error, but it must be visible."""
    move = {"room": "secret_passage", "from": "patio_rooms", "to": "garage_classroom",
            "condition": "no_such_attribute_xyz"}
    errors, warnings = find_membership_moves_findings(_priority(move), _BY_ID)
    assert errors == []
    assert any("no_such_attribute_xyz" in w for w in warnings)


def test_real_priority_draws_json_has_no_membership_moves_findings():
    """Run the check against the live priority_draws.json content (through
    Registry.load(), the same source main() itself uses) and assert zero
    findings -- pinning that the real Secret Passage record is well-formed,
    not just the constructed fixtures above."""
    from blueprince_sim.engine.model import Registry

    reg = Registry.load()
    by_id = reg.by_id
    errors, warnings = find_membership_moves_findings(reg.priority, by_id)
    assert errors == []
    assert warnings == []
