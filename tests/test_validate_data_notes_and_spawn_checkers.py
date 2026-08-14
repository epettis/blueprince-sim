"""tools/validate_data.py's notes-decay checker and spawn-table checker.

Two independent checks, both against special_items.json:

1. Notes-decay (``find_notes_decay_findings``): checks the mechanically
   decidable subset of special_items.json's prose notes -- a note naming a
   field together with an explicit value, in one of four shapes. The rest of
   the corpus is narrative and deliberately left unchecked; see that
   function's own docstring for exactly which shapes are covered.

2. Spawn-table (``find_spawn_table_findings``): diffs each item's
   spawn_rooms/spawn_rooms_high_luck against the pinned wiki snapshot
   (tools/raw/wiki_item_locations.tsv), after dropping non-room mechanic
   tokens, the 4-shop exclusion set, and the 3 items whose Locations= is a
   single fixed spot modelled as a guaranteed find or shop purchase rather
   than a spawn_rooms roll.

Both are wired into ``main()`` as ERRORs (not warnings) -- see
tests/test_divergence_audit.py's ``test_default_validate_data_run_reports_zero_warnings``
and tests/test_validate_data_registry_wiring.py's
``test_main_is_clean_on_real_data`` for the pinned real-data error count
these two checkers now contribute.
"""

from __future__ import annotations

import sys
from pathlib import Path

# tools/ is not a proper package; insert the repo root so the import works,
# mirroring tests/test_divergence_audit.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate_data import (  # noqa: E402
    DATA,
    WIKI_LOCATIONS_TSV,
    _WIKI_MECHANIC_TOKENS,
    _WIKI_SHOP_EXCLUDED_NAMES,
    _load_wiki_locations,
    _parse_wiki_locations_row,
    _room_name_to_id_map,
    find_notes_decay_findings,
    find_spawn_table_findings,
)

# ─────────────────────────────── builders ───────────────────────────────────


def _item(
    id,
    name=None,
    spawn_rooms=None,
    spawn_rooms_high_luck=None,
    guaranteed_in=None,
    tier=None,
    kind=None,
    notes=None,
):
    """Build a minimal special_items.json-shaped record with only the fields
    the two checkers read."""
    return {
        "id": id,
        "name": name if name is not None else id.replace("_", " ").title(),
        "kind": kind,
        "tier": tier,
        "spawn_rooms": spawn_rooms or [],
        "spawn_rooms_high_luck": spawn_rooms_high_luck or [],
        "guaranteed_in": guaranteed_in or [],
        "meta": {"notes": notes} if notes is not None else {},
    }


def _room(id, name=None):
    """Build a minimal rooms.json-shaped record with only the fields
    _room_name_to_id_map reads."""
    return {"id": id, "name": name if name is not None else id}


def _area(id, modelled):
    """Build a minimal areas.json-shaped node with only the field
    find_notes_decay_findings reads."""
    return {"id": id, "modelled": modelled}


# ────────────────────────── find_notes_decay_findings ───────────────────────


# ── shape 1: item-scoped "<field> is empty" ──────────────────────────────────


def test_field_is_empty_claim_true_is_not_a_finding():
    """A meta.notes claim that a field is empty, when it genuinely is, is
    not a finding -- the real hall_pass shape."""
    items = [_item("hall_pass", guaranteed_in=[],
                    notes="guaranteed_in is empty, unlike the wiki's claim.")]
    assert find_notes_decay_findings(items, [], {}, {}) == []


def test_field_is_empty_claim_false_is_a_finding():
    """A meta.notes claim that a field is empty, when it actually holds
    values, is flagged and names both the field and its real value."""
    items = [_item("gizmo", spawn_rooms_high_luck=["den", "drawing_room"],
                    notes="spawn_rooms_high_luck is empty today.")]
    findings = find_notes_decay_findings(items, [], {}, {})
    assert len(findings) == 1
    assert "gizmo" in findings[0]
    assert "spawn_rooms_high_luck" in findings[0]
    assert "['den', 'drawing_room']" in findings[0]


def test_field_is_empty_only_checks_the_named_fields():
    """A field name outside the four tracked list fields is not a shape this
    checker recognises, even phrased identically -- no false claim, no
    finding, because the claim was never parsed at all."""
    items = [_item("gizmo", notes="tier is empty today.")]
    assert find_notes_decay_findings(items, [], {}, {}) == []


# ── shape 2: item-scoped "<id> is areas.json modelled=<bool>" ────────────────


def test_area_modelled_claim_true_is_not_a_finding():
    """A meta.notes claim about an areas.json node's modelled flag, when
    correct, is not a finding -- the real sanctum_key_safehouse shape."""
    items = [_item("sanctum_key_safehouse",
                    notes="safehouse is areas.json modelled=false today.")]
    area_by_id = {"safehouse": _area("safehouse", False)}
    assert find_notes_decay_findings(items, [], area_by_id, {}) == []


def test_area_modelled_claim_false_is_a_finding():
    """A meta.notes claim about an areas.json node's modelled flag, when the
    node's real flag disagrees, is flagged with both values."""
    items = [_item("sanctum_key_safehouse",
                    notes="safehouse is areas.json modelled=false today.")]
    area_by_id = {"safehouse": _area("safehouse", True)}
    findings = find_notes_decay_findings(items, [], area_by_id, {})
    assert len(findings) == 1
    assert "safehouse" in findings[0]
    assert "modelled=False" in findings[0] and "modelled=True" in findings[0]


def test_area_modelled_claim_about_an_unknown_area_id_is_skipped():
    """An id the claim names that is not in area_by_id at all is not flagged
    -- a resolver returning nothing is not evidence of a contradiction."""
    items = [_item("gizmo", notes="nonexistent_area is areas.json modelled=false.")]
    assert find_notes_decay_findings(items, [], {}, {}) == []


# ── shape 3: file-level _notes "<owner>: ... field=value" ────────────────────


def test_notes_field_value_scalar_claim_true_is_not_a_finding():
    """A file-level _notes claim "id: field=value" for a scalar field,
    when correct, is not a finding."""
    items = [_item("master_key", kind="special_key")]
    si_notes = ["master_key: classified kind=special_key."]
    assert find_notes_decay_findings(items, si_notes, {}, {}) == []


def test_notes_field_value_scalar_claim_false_is_a_finding():
    """A file-level _notes claim "id: field=value" for a scalar field, when
    the record's real field disagrees, is flagged with both values."""
    items = [_item("master_key", kind="standard")]
    si_notes = ["master_key: classified kind=special_key."]
    findings = find_notes_decay_findings(items, si_notes, {}, {})
    assert len(findings) == 1
    assert "master_key.kind='special_key'" in findings[0]
    assert "'standard'" in findings[0]


def test_notes_field_value_list_claim_true_is_not_a_finding():
    """A file-level _notes claim "id: field=[a, b]" for a list field, when
    correct, is not a finding."""
    items = [_item("master_key", guaranteed_in=["showroom"])]
    si_notes = ["master_key: also guaranteed_in=[showroom]."]
    assert find_notes_decay_findings(items, si_notes, {}, {}) == []


def test_notes_field_value_list_claim_false_is_a_finding():
    """The real, known-stale case: master_key's guaranteed_in is empty
    today, contradicting the file-level note."""
    items = [_item("master_key", kind="special_key", guaranteed_in=[])]
    si_notes = ["master_key: classified kind=special_key; also guaranteed_in=[showroom]."]
    findings = find_notes_decay_findings(items, si_notes, {}, {})
    assert len(findings) == 1
    assert "master_key.guaranteed_in=['showroom']" in findings[0]
    assert "but it is []" in findings[0]


def test_notes_entry_resolved_by_display_name_not_only_by_id_prefix():
    """The corpus uses two owner-resolution conventions: id-colon (tested
    above) and the item's own display name -- "Car keys spawn rooms: ..."
    for id car_keys/name "Car Keys"."""
    items = [_item("car_keys", name="Car Keys")]
    si_notes = ["Car keys spawn rooms: digest only names Garage "
                "(wiki lists 15 rooms; full list absent from digest)."]
    wiki_locations = {"car_keys": ", ".join(f"Room{i}" for i in range(25))}
    findings = find_notes_decay_findings(items, si_notes, {}, wiki_locations)
    assert len(findings) == 1
    assert "car_keys" in findings[0] and "15" in findings[0] and "25" in findings[0]


def test_notes_entry_with_no_resolvable_owner_is_skipped():
    """An entry naming no single item (by id-colon or display name) is
    skipped rather than guessed -- a file-level aside can legitimately span
    more than one item (e.g. the pre-split shared "sanctum_key" id)."""
    items = [_item("master_key", kind="standard")]
    si_notes = ["Sanctum key: Reservoir (north) and Safehouse are areas, "
                "not rooms -> in absent_spawn_areas."]
    assert find_notes_decay_findings(items, si_notes, {}, {}) == []


# ── shape 4: file-level _notes "wiki lists N rooms" ───────────────────────────


def test_wiki_count_claim_true_is_not_a_finding():
    """A file-level _notes "wiki lists N rooms" claim, when it matches the
    wiki snapshot's raw token count, is not a finding."""
    items = [_item("car_keys", name="Car Keys")]
    si_notes = ["Car keys spawn rooms: wiki lists 3 rooms."]
    wiki_locations = {"car_keys": "Bedroom, Dining Room, Office"}
    assert find_notes_decay_findings(items, si_notes, {}, wiki_locations) == []


def test_wiki_count_claim_false_is_a_finding():
    """A file-level _notes "wiki lists N rooms" claim, when it disagrees
    with the wiki snapshot's raw token count, is flagged with both counts."""
    items = [_item("car_keys", name="Car Keys")]
    si_notes = ["Car keys spawn rooms: wiki lists 15 rooms."]
    wiki_locations = {"car_keys": "Bedroom, Dining Room, Office"}
    findings = find_notes_decay_findings(items, si_notes, {}, wiki_locations)
    assert len(findings) == 1
    assert "15" in findings[0] and "3" in findings[0]


def test_wiki_count_claim_for_item_absent_from_snapshot_is_skipped():
    """An item with no row in the wiki snapshot at all has nothing to check
    the claim against -- skipped, not flagged."""
    items = [_item("car_keys", name="Car Keys")]
    si_notes = ["Car keys spawn rooms: wiki lists 15 rooms."]
    assert find_notes_decay_findings(items, si_notes, {}, {}) == []


# ── real data ──────────────────────────────────────────────────────────────


def test_real_data_notes_decay_findings_are_exactly_the_three_known_ones():
    """Pin the checker's output against live special_items.json/areas.json
    and the real wiki snapshot: a stale "is empty" claim (magnifying_glass),
    a stale wiki-room-count claim (car_keys), and a stale guaranteed_in
    claim (master_key). A change to this count means either a real note got
    fixed (good -- narrow this test) or a new stale note appeared (also
    real -- extend this test, do not loosen it)."""
    import json

    si_doc = json.loads((DATA / "special_items.json").read_text(encoding="utf-8"))
    areas_doc = json.loads((DATA / "areas.json").read_text(encoding="utf-8"))
    area_by_id = {n["id"]: n for n in areas_doc["nodes"]}
    wiki_locations = _load_wiki_locations(WIKI_LOCATIONS_TSV)

    findings = find_notes_decay_findings(
        si_doc["items"], si_doc.get("_notes", []), area_by_id, wiki_locations)

    assert len(findings) == 3
    joined = "\n".join(findings)
    assert "magnifying_glass" in joined and "spawn_rooms_high_luck" in joined
    assert "car_keys" in joined and "wiki lists 15 rooms" in joined
    assert "master_key.guaranteed_in=" in joined


# ────────────────────────── wiki snapshot / room-name plumbing ──────────────


def test_load_wiki_locations_skips_comments_and_header():
    """Loading the real snapshot skips its leading '#' comment block and the
    item_id/locations_raw/... header row, leaving only real item rows."""
    rows = _load_wiki_locations(WIKI_LOCATIONS_TSV)
    assert "item_id" not in rows  # the header row itself, not a real item
    assert "car_keys" in rows
    assert rows["car_keys"].startswith("Bedroom")


def test_load_wiki_locations_missing_file_returns_empty_dict(tmp_path):
    """A missing snapshot file returns {} rather than raising, so a caller
    with no snapshot to check against just finds nothing."""
    assert _load_wiki_locations(tmp_path / "does_not_exist.tsv") == {}


def test_room_name_to_id_map_prefers_the_base_id_on_a_name_collision():
    """Several rooms.json records can share a display name (a base room and
    its upgrade variants); the map must resolve to the base id (no "__" in
    it), matching how special_items.json's own spawn_rooms lists reference
    room families today."""
    rooms = [
        _room("mail_room", "Mail Room"),
        _room("mail_room__ix91", "Mail Room"),
        _room("mail_room__ix90", "Mail Room"),
    ]
    name_to_id = _room_name_to_id_map(rooms)
    assert name_to_id["Mail Room"] == "mail_room"


def test_room_name_to_id_map_applies_the_servants_quarters_alias():
    """The wiki's "Spare Servant's Quarters" word order resolves to this
    sim's "Servant's Spare Quarters" room via the hardcoded alias."""
    rooms = [_room("servants_spare_quarters__ix134", "Servant's Spare Quarters")]
    name_to_id = _room_name_to_id_map(rooms)
    assert name_to_id["Spare Servant's Quarters"] == "servants_spare_quarters__ix134"


def test_parse_wiki_locations_row_splits_tiers_and_drops_exclusions():
    """A raw locations_raw string splits into normal/high-luck room-id sets,
    with a shop-excluded name and a mechanic token both dropped."""
    name_to_id = {"Bedroom": "bedroom", "Gallery": "gallery"}
    normal, high, unresolved = _parse_wiki_locations_row(
        "Bedroom, Locksmith, Experiment, !Gallery",
        name_to_id, _WIKI_MECHANIC_TOKENS, _WIKI_SHOP_EXCLUDED_NAMES)
    assert normal == {"bedroom"}
    assert high == {"gallery"}
    assert unresolved == []


def test_parse_wiki_locations_row_mechanic_tokens_are_case_insensitive():
    """The real snapshot is not consistently cased ("Dig spot" vs. "Dig
    Spot") -- matching case-insensitively is what makes those rows resolve
    cleanly instead of surfacing as unresolved tokens."""
    normal, high, unresolved = _parse_wiki_locations_row(
        "Dig spot", {}, _WIKI_MECHANIC_TOKENS, _WIKI_SHOP_EXCLUDED_NAMES)
    assert (normal, high, unresolved) == (set(), set(), [])


def test_parse_wiki_locations_row_unresolved_token_is_surfaced():
    """A token that is neither a mechanic token, a shop exclusion, nor a
    known room name is returned in ``unresolved`` rather than dropped."""
    normal, high, unresolved = _parse_wiki_locations_row(
        "Nonexistent Room", {}, _WIKI_MECHANIC_TOKENS, _WIKI_SHOP_EXCLUDED_NAMES)
    assert unresolved == ["Nonexistent Room"]


# ────────────────────────── find_spawn_table_findings ───────────────────────


def test_missing_normal_room_is_a_finding():
    """A wiki-snapshot room absent from both spawn_rooms and guaranteed_in
    is flagged as missing."""
    items = [_item("gizmo", spawn_rooms=[])]
    rooms = [_room("bedroom", "Bedroom")]
    wiki_locations = {"gizmo": "Bedroom"}
    findings = find_spawn_table_findings(items, rooms, wiki_locations)
    assert len(findings) == 1
    assert "'bedroom'" in findings[0] and "neither spawn_rooms nor guaranteed_in" in findings[0]


def test_missing_normal_room_satisfied_by_guaranteed_in_is_not_a_finding():
    """A room modelled as a guaranteed find rather than a spawn_rooms roll
    still counts as modelled -- the real key_8/stopwatch/master_key shape."""
    items = [_item("gizmo", spawn_rooms=[], guaranteed_in=["bedroom"])]
    rooms = [_room("bedroom", "Bedroom")]
    wiki_locations = {"gizmo": "Bedroom"}
    assert find_spawn_table_findings(items, rooms, wiki_locations) == []


def test_extra_normal_room_is_a_finding():
    """A spawn_rooms entry the wiki snapshot's normal tier does not name is
    flagged as extra."""
    items = [_item("gizmo", spawn_rooms=["bedroom"])]
    rooms = [_room("bedroom", "Bedroom")]
    wiki_locations = {"gizmo": ""}
    findings = find_spawn_table_findings(items, rooms, wiki_locations)
    assert len(findings) == 1
    assert "spawn_rooms has 'bedroom'" in findings[0]


def test_extra_room_only_in_guaranteed_in_is_not_a_finding():
    """The real repellent shape: guaranteed_in names a room from a
    completely different mechanic (a Cloister-of-Mila bonus) that the wiki's
    Locations= field never claimed at all -- guaranteed_in is deliberately
    not consulted for the "extra" direction."""
    items = [_item("gizmo", spawn_rooms=[], guaranteed_in=["bedroom"])]
    rooms = [_room("bedroom", "Bedroom")]
    wiki_locations = {"gizmo": ""}
    assert find_spawn_table_findings(items, rooms, wiki_locations) == []


def test_high_luck_missing_and_extra_are_findings():
    """spawn_rooms_high_luck is diffed against the snapshot's "!" tier the
    same way the normal tier is, both directions flagged."""
    items = [_item("gizmo", spawn_rooms_high_luck=["gallery"])]
    rooms = [_room("den", "Den"), _room("gallery", "Gallery")]
    wiki_locations = {"gizmo": "!Den"}
    findings = find_spawn_table_findings(items, rooms, wiki_locations)
    assert len(findings) == 2
    joined = "\n".join(findings)
    assert "'den' as high-luck but spawn_rooms_high_luck does not" in joined
    assert "spawn_rooms_high_luck has 'gallery'" in joined


def test_fixed_location_exempt_item_is_skipped_even_when_mismatched():
    """One of the 3 fixed-location items is skipped entirely, even when its
    spawn_rooms/guaranteed_in would otherwise mismatch the snapshot."""
    items = [_item("master_key", spawn_rooms=[], guaranteed_in=[])]
    rooms = [_room("showroom", "Showroom")]
    wiki_locations = {"master_key": "Showroom"}
    assert find_spawn_table_findings(items, rooms, wiki_locations) == []


def test_item_absent_from_special_items_is_skipped():
    """A wiki-snapshot row for an id that is not in si_items at all (should
    not happen in real data, but the function must not crash on it)."""
    wiki_locations = {"ghost_item": "Bedroom"}
    assert find_spawn_table_findings([], [_room("bedroom", "Bedroom")], wiki_locations) == []


# ── real data ──────────────────────────────────────────────────────────────


def test_real_data_spawn_table_flags_exactly_telescope():
    """Pin the checker's output against live rooms.json/special_items.json
    and the real wiki snapshot: telescope's spawn_rooms carries
    lost_and_found and trading_post, which the wiki snapshot's normal-tier
    locations (after the shop exclusion) do not -- a real, pre-existing,
    deliberately-left-as-is discrepancy (see telescope's own meta.notes),
    not a bug in the checker. Any other item appearing here is a real,
    previously uncaught data/snapshot mismatch worth investigating on its
    own merits, not silenced by loosening this test."""
    import json

    rooms = json.loads((DATA / "rooms.json").read_text(encoding="utf-8"))["rooms"]
    si_items = json.loads((DATA / "special_items.json").read_text(encoding="utf-8"))["items"]
    wiki_locations = _load_wiki_locations(WIKI_LOCATIONS_TSV)

    findings = find_spawn_table_findings(si_items, rooms, wiki_locations)

    assert len(findings) == 2
    assert all("telescope" in f for f in findings)
    assert any("'lost_and_found'" in f for f in findings)
    assert any("'trading_post'" in f for f in findings)


# ────────────────────── necessity guard (real data) ─────────────────────────
#
# Each exclusion category is lifted in turn against the REAL data, and the
# test asserts the checker's output actually changes -- not that the
# exclusion list still contains the expected strings. A category whose
# alternate channel (the shop's own stock/trade modelling, or a token that
# never resolved to a room in the first place) is later deleted must start
# failing here.


def _real_findings(**kwargs) -> set[str]:
    import json

    rooms = json.loads((DATA / "rooms.json").read_text(encoding="utf-8"))["rooms"]
    si_items = json.loads((DATA / "special_items.json").read_text(encoding="utf-8"))["items"]
    wiki_locations = _load_wiki_locations(WIKI_LOCATIONS_TSV)
    return set(find_spawn_table_findings(si_items, rooms, wiki_locations, **kwargs))


_REAL_BASELINE = None


def _baseline() -> set[str]:
    global _REAL_BASELINE
    if _REAL_BASELINE is None:
        _REAL_BASELINE = _real_findings()
    return _REAL_BASELINE


def _lift_shop(name: str) -> set[str]:
    lifted = _real_findings(shop_names=frozenset(_WIKI_SHOP_EXCLUDED_NAMES - {name}))
    return lifted.symmetric_difference(_baseline())


def test_commissary_exclusion_is_load_bearing():
    """Lifting the Commissary shop exclusion flags exactly the 8 pairs it
    currently suppresses, matching the TSV header's own count."""
    changed = _lift_shop("Commissary")
    assert len(changed) == 8
    assert all("'commissary'" in f for f in changed)


def test_locksmith_exclusion_is_load_bearing():
    """Lifting the Locksmith shop exclusion flags exactly the 5 pairs it
    currently suppresses, matching the TSV header's own count."""
    changed = _lift_shop("Locksmith")
    assert len(changed) == 5
    assert all("'locksmith'" in f for f in changed)


def test_lost_and_found_exclusion_is_load_bearing():
    """10 pairs total, matching tools/raw/wiki_item_locations.tsv's own
    header comment -- 9 appear as newly-missing once the exclusion is
    lifted, and 1 (telescope) disappears from the baseline's "extra"
    findings, because telescope's spawn_rooms already names lost_and_found
    directly (see test_real_data_spawn_table_flags_exactly_telescope)."""
    changed = _lift_shop("Lost & Found")
    assert len(changed) == 10
    assert all("lost_and_found" in f for f in changed)
    assert any("telescope" in f for f in changed)


def test_trading_post_exclusion_is_load_bearing():
    """Lifting the Trading Post shop exclusion flags exactly the 5 pairs it
    currently suppresses, matching the TSV header's own count."""
    changed = _lift_shop("Trading Post")
    assert len(changed) == 5
    assert all("'trading_post'" in f for f in changed)
    assert any("telescope" in f for f in changed)


def test_every_mechanic_token_exclusion_is_load_bearing():
    """Lifting any single non-room mechanic token out of the exclusion set
    must change the checker's output -- each token appears in enough wiki
    rows that, unresolved, it now surfaces as an "unresolved token" finding
    (see _parse_wiki_locations_row) instead of being silently dropped."""
    baseline = _baseline()
    for token in sorted(_WIKI_MECHANIC_TOKENS):
        lifted = _real_findings(mechanic_tokens=frozenset(_WIKI_MECHANIC_TOKENS - {token}))
        changed = lifted.symmetric_difference(baseline)
        assert changed, f"lifting {token!r} did not change the checker's output"
        assert all(f"token '{token.title()}'" in f or token in f.lower() for f in changed), (
            token, changed)


def test_fixed_location_exemption_is_load_bearing():
    """Lifting the 3-item fixed-location exemption must surface at least
    master_key's real, pre-existing guaranteed_in gap (also caught
    independently by the notes-decay checker above)."""
    lifted = _real_findings(fixed_location_exempt_ids=frozenset())
    changed = lifted.symmetric_difference(_baseline())
    assert any("master_key" in f for f in changed)
