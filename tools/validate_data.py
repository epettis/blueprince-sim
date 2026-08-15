#!/usr/bin/env python3
"""Validate the committed data files: referential integrity + sanity checks.

Run: python tools/validate_data.py  (exit 1 on any error)
Run: python tools/validate_data.py --audit  (also prints the room-fidelity
     divergence worklist; still exits 0 -- it is a worklist, not a
     validation failure)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Only needed for the kind-2 divergence check below: a room whose behaviour
# is registered via room_hook (engine/effects/rooms/) is modelled even though
# rooms.json carries no effects/items.guaranteed for it. Importing the package
# pulls in engine.effects.rooms, which is how handlers register themselves --
# that is the point, not a side effect to work around. Needs blueprince_sim
# on the import path (editable install, or PYTHONPATH=src), same as every
# other tools/ script that imports it (e.g. benchmark_env.py).
from blueprince_sim.engine.effects import (
    registered_capability_rooms,
    registered_container_rooms,
    registered_item_capability_ids,
    registered_item_hook_ids,
    registered_rooms,
    validate_capability_registry,
    validate_container_registry,
    validate_item_hook_registry,
    validate_item_registry,
    validate_room_registry,
)
from blueprince_sim.engine.effects.tier1 import RESOURCES as TIER1_RESOURCES
from blueprince_sim.engine.model import Registry

DATA = Path(__file__).resolve().parent.parent / "src" / "blueprince_sim" / "data"
# Offline snapshot of each item's wiki.gg |Locations= field (see that file's
# own header for fetch method/scope/honest-limit) -- the notes-decay checker's
# only source for the "wiki lists N rooms" shape below.
WIKI_LOCATIONS_TSV = Path(__file__).resolve().parent / "raw" / "wiki_item_locations.tsv"

VALID_RARITIES = {"commonplace", "standard", "unusual", "rare", None}
VALID_LAYOUTS = {"dead_end", "straight", "corner", "t", "cross"}
VALID_CATEGORIES = {"blueprint", "bedroom", "hallway", "green", "shop", "red",
                    "blackprint", "studio_addition", "outer", "objective", "mechanical",
                    "tomorrow"}
VALID_POOLS = {"base", "studio_addition", "outer", "pool_temp", "upgrade_variant",
               "conditional", "none"}
VALID_CONFIDENCE = {"datamined", "wiki", "inferred", "placeholder"}
KNOWN_CONDITIONS = {"west_wing", "east_wing", "west_or_east_wing", "not_on_wing",
                    "no_corner", "corner_only", "interior_only",
                    "west_wing_from_south_door", "garage", "boiler_room",
                    "morning_room", "room8_placement", "gift_shop",
                    "experiment_aquarium",
                    "no_north_on_wing", "no_horizontal_end_rank", "north_south_only",
                    "pool_drafted", "library_only", "antechamber_north_door", "room8_key",
                    "knight_chess_piece", "secret_garden_key", "breakfast", "the_foundation"}
# priority_draws.json "condition" tags that _active_conditions (engine/draft.py)
# emits but that carry no matching category_biases entry to source the
# vocabulary from below -- add_aquariums gates two priority_draws entries
# directly, with no category-bias counterpart (it targets a fixed room list,
# not a category); chronograph likewise gates a priority draw selected by
# category rather than by a room list, so it has no category-bias entry either.
KNOWN_PRIORITY_DRAW_ONLY_CONDITIONS = {"add_aquariums", "chronograph"}
# Item kinds engine/items.py::grant_item and roll_room_items actually handle
# for a room's items.guaranteed list. "coins_exact" grants the literal count
# as coins with no pile roll; "coins" rolls each of count PILES from
# items.json's pile_min..pile_max range; "random" resolves count table-rolled
# items (Closet/Walk-In/Attic style); "fruit" resolves count weighted rolls
# from items.json's food.fruit_weights, each eaten as that dish immediately.
KNOWN_GUARANTEED_ITEM_KINDS = {"coins", "coins_exact", "key", "gem", "die", "steps",
                                "food", "fruit", "random"}
KNOWN_ITEM_EFFECT_TAGS = {
    # PR1 functional set
    "lockpick", "luck_bonus", "coin_interest",
    "food_bonus", "free_move_interval",
    "stopwatch", "sleeping_mask", "watering_can",
    "dig_tool",
    "metal_detector_spawns", "auto_collect", "mask_red_room",
    "set_steps_on_pickup", "steps_at_rank", "negate_red_once_per_day",
    "allowance", "battery_pack",
    # Read via item.effect()/_has_item_effect() in shops.py and
    # special_items.py, and crown_of_the_blueprints.py's own
    # item.effect(TAG) check.
    "smash", "crown_of_blueprints", "locksmith_rob",
    # The Axe: permanent gem-cost override, capped at max_active
    # (effects/items/the_axe.py). Read directly via item.effect(TAG); not an
    # engine/effects hook registration (the discount outlives the item).
    "axe_room",
}
VALID_ITEM_KINDS = {"standard", "special_key", "contraption", "showroom", "armory", "unique"}
VALID_ITEM_PERSISTENCE = {"day", "until_used", "permanent"}
# meta.reachability, required whenever implemented=false: "inert" (the engine
# spawns/grants/reads the item but it does nothing, or only partly what it
# should) vs "absent" (nothing in the engine touches it; unobtainable in play).
VALID_ITEM_REACHABILITY = {"inert", "absent"}
VALID_DIG_OUTCOME_KINDS = {"junk", "nothing", "coins", "gold_coin", "turnip", "key", "item", "gems"}

KNOWN_EFFECT_TAGS = {"grant", "grant_per_category", "grant_on_draft_category",
                     "set_resource_on_enter",
                     "counts_as_drafting_room",
                     "counts_as_bedrooms", "inject_pool",
                     "free_green_drafts",
                     "archive_floorplan", "conceal_all_floorplans",
                     "anti_luck", "mark_visited", "draft_luck"}

# Room ids whose "always unlocked"/"always locked" effect_text is implemented
# via locks.json's always_unlocked_rooms/always_locked_rooms tables rather
# than effects/items -- excluded from the divergence audit below by exact id,
# not by text pattern, so any other room's unmodelled locking claim still
# surfaces.
_AUDIT_STRUCTURAL_EXEMPT_IDS = {"corridor", "corriyard__ix50", "great_hall"}

# Commerce rooms whose behaviour lives in engine/shops.py, driven by shops.json,
# rather than in effects/items. The eight priced shops come from shops.json's own
# "shops" table, so that half of the set cannot drift from the data. These two
# have no entry there and are listed by id:
#   trading_post -- the tiered trade graph (shops.py::_inside_trading_post)
#   workshop     -- fabrication recipes (shops.py::fabricate)
_AUDIT_COMMERCE_EXTRA_IDS = {"trading_post", "workshop"}

# Rooms whose effect_text is implemented in Python that the audit cannot
# introspect -- a hand-written branch keyed on the room id, rather than an
# effects tag, an items.guaranteed entry or a room_hook. Each value is the
# module the behaviour lives in, relative to src/blueprince_sim/;
# _assert_python_exemptions_live checks the id still appears there, so deleting
# an implementation trips the check instead of leaving the room silently
# "modelled".
_AUDIT_PYTHON_EXEMPT_IDS = {
    # Every color of room is `extra_categories`/`Room.is_category()`, not an
    # effects/items.guaranteed/room_hook site the audit can see.
    "aquarium": "engine/model.py",
    "chamber_of_mirrors": "engine/draft.py",     # duplicate-room drafting
    "clock_tower": "engine/game.py",             # day-end Tomorrow-room key tally
    # Absorbing a spread is implemented by each spreader's own branch rather
    # than by the Conference Room; the Patio's is the representative one.
    "conference_room": "engine/effects/rooms/patio.py",
    # The main course is rank-8 gated and re-checked on every arrival, not
    # just first entry, so it stays a hand-written branch rather than a
    # room_hook (which only fires once, on first entry).
    "dining_room": "engine/special_items.py",    # rank-8 main course
    "dovecote": "engine/effects/rooms/dovecote.py",  # rotation while drawn
    # The trunk is declared entirely in the containers.rooms table, read
    # generically by engine/special_items.py, so the guard points at the table
    # itself: deleting the entry is what should trip it.
    "hallway__ix75": "data/special_items.json",
    # The Experimental Setup terminal is a hand-written room-id check
    # (Game.at_laboratory_terminal), not an effects tag or room_hook -- the
    # Laboratory itself carries no per-experiment data, only the disk_reader flag.
    "laboratory": "engine/game.py",
    # The steal must be able to draw the room's own guaranteed Allowance
    # Token, granted earlier in the same on_enter call, so it stays ordered
    # against that grant rather than moving to an earlier-firing room_hook.
    "lost_and_found": "engine/special_items.py",  # steal one item, grant two
    "reading_nook__ix99": "engine/draft.py",     # LIBRARY forced into slot 2
    "the_foundation": "engine/game.py",          # persists across days
    "the_kennel": "engine/effects/rooms/the_kennel.py",  # digging unlocks that room
    "utility_closet": "engine/game.py",          # breaker box
    # Donate/take-back are action-driven (Game.donate_shrine/take_back_shrine_offering),
    # not a room_hook -- the room's own identity/state queries, the curse's
    # resource-loss table and Berry Picker's random-pick pool all live here; the
    # per-draft/per-redraw/per-rotation blessing effects dispatch from their own
    # existing call sites in engine/game.py (see that module's own comments).
    "shrine": "engine/effects/rooms/shrine.py",
}

# Rooms whose real effect is a no-op under the sim's assumed-solved doctrine:
# the player is taken to solve any puzzle in a room they enter, so an effect
# that only changes a puzzle's difficulty changes nothing here. Listed by exact
# id with its reason, because "modelled as nothing" is a claim worth stating
# rather than a gap worth carrying on the worklist forever.
_AUDIT_DOCTRINE_EXEMPT_IDS = {
    # "Basic Addition" drops the Dartboard Puzzle to one board, one ring and
    # two numbers. The puzzle is not modelled and its reward is assumed won, so
    # an easier puzzle pays exactly what the Billiard Room already pays.
    "speakeasy__ix10": "Dartboard Puzzle difficulty only",
}

# Rooms whose effect_text merely restates a value already carried in their own
# record, so there is nothing to implement. Listed by exact id rather than
# matched on the field, because a generic "has dig_spots" or "has a flag" rule
# wrongly clears rooms whose text promises something beyond the field.
_AUDIT_DATA_EXEMPT_IDS = {
    "courtyard__ix49": "items.dig_spots",        # "5 dig spots"
    "electric_eel_aquarium__ix4": "flags.powered",  # "Power Source"
    "lavatory": "items.additional_max",          # "Has no items (never spawns loot)"
    # "AQUARIUM is every color of room" -- carried by the record's own
    # extra_categories, read generically through Room.is_category. The base
    # Aquarium's identical text is Python-exempt against engine/model.py,
    # which names the family only in prose, so this id needs the field itself.
    "aquarium__experiment": "extra_categories",
}

# Rooms whose effect is genuinely unmodelled and deliberately deferred, with a
# stated reason -- distinct from the other three channels, which all claim the
# behaviour IS modelled somewhere the audit can't see. These four claim the
# opposite: the gap is real, and staying on the worklist forever would just
# make the audit noisy rather than actionable. _assert_deferred_exemptions_live
# checks each id would still be flagged without this channel, so the entry
# stays honest if the room is ever actually implemented.
_AUDIT_DEFERRED_EXEMPT_IDS = {
    "parlor__ix109": (
        "Ruled deliberately permanent by the owner. Its effect ('2 Wind-up "
        "Keys') has no grid-level representation."
    ),
    "pump_room": (
        "Blocked on the Pump Room water model: six independent source "
        "levels, two tanks, four pumps, permanent carryover and a new "
        "action set."
    ),
    "closed_exhibit": (
        "Blocked on the security-lock puzzle subsystem. Its own "
        "effect_text already says the lock system is out of scope."
    ),
    "root_cellar": (
        "Its effect spreads dig spots to OTHER rooms, which needs a "
        "house-wide dig-spot model this sim does not have; the room keeps "
        "only its own dig_spots."
    ),
    "throne_room": (
        "Blocked on cross-day meta-progression (reclaiming the crown, the "
        "Throne of the Blue Prince transformation). Its Antechamber lever "
        "IS modelled (effects/rooms/throne_room.py, dispatched by hand in "
        "game.py rather than a room_hook the audit can see); only the "
        "crown objective is missing."
    ),
}


def _assert_python_exemptions_live(src_root: Path) -> None:
    """Fail if a Python-exempt room's id no longer appears in its named module.

    The exemption asserts that a room is modelled somewhere the audit cannot
    see. That claim rots the moment the implementation moves or is deleted, and
    nothing else would notice -- the room would simply stay off the worklist.
    """
    for rid, rel in sorted(_AUDIT_PYTHON_EXEMPT_IDS.items()):
        path = src_root / rel
        assert path.exists(), f"_AUDIT_PYTHON_EXEMPT_IDS: {rid} names missing module {rel}"
        if rid.lower() not in path.read_text(encoding="utf-8").lower():
            raise AssertionError(
                f"_AUDIT_PYTHON_EXEMPT_IDS: {rid!r} no longer appears in {rel}; "
                f"either the implementation moved or the exemption is stale"
            )


def find_divergences(
    rooms: list[dict],
    by_id: dict[str, dict],
    lock_rules: dict,
    registered_room_ids: set[str] | None = None,
    shop_rules: dict | None = None,
    deferred_exempt_ids: dict[str, str] | None = None,
    python_exempt_ids: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (kind1, kind2) room-fidelity divergence findings (an audit worklist).

    Kind 1: an upgrade variant whose ``effects`` and ``items.guaranteed`` are
    identical to its immediate parent's while its ``meta.effect_text`` differs.
    Upgrade variants are by construction rooms that do something different from
    their parent, so identical modelling plus differing text means the variant
    step was never authored. Comparison is against the immediate ``variant_of``
    parent, not the chain root: a two-level variant (e.g. the Spare Room's
    second-stage rooms) is judged against what its own upgrade step was supposed
    to add, not against the original base room three steps back. A variant whose
    own ``effect_text`` is blank is excluded -- it cannot diverge from anything.

    A variant is also excluded if it has its own ``room_hook`` handler
    registered directly at its own id (``registered_room_ids``) -- that
    handler is authored specifically for this variant's upgrade step,
    whatever ``effects``/``items.guaranteed`` say, so the record is modelled
    even though the data comparison alone can't see it.

    Kind 2: any record whose ``meta.effect_text`` is non-empty, which has no
    ``effects`` and no ``items.guaranteed``, AND whose behaviour is not covered
    by a registered ``room_hook`` handler (``engine/effects/rooms/``) either. A
    room can be modelled entirely in Python rather than in data; a handler
    registered for the room's own id, at any hook, is enough to count as
    modelled -- this check does not try to match a specific hook against the
    effect text. ``registered_room_ids`` defaults to the live ``room_hook``
    registry (``engine.effects``); tests may pass an explicit set instead.

    Both kinds exclude five exemption sets, each covering a channel the audit
    cannot introspect: ``_AUDIT_STRUCTURAL_EXEMPT_IDS`` (implemented in
    locks.json), ``python_exempt_ids`` (a hand-written branch keyed on the
    room id, in the module each entry names -- defaults to
    ``_AUDIT_PYTHON_EXEMPT_IDS``; callers may pass ``{}`` to see what the
    audit would report without that channel), ``_AUDIT_DATA_EXEMPT_IDS``
    (the text merely restates a field the record already carries),
    ``_AUDIT_DOCTRINE_EXEMPT_IDS`` (the effect is a no-op under the
    assumed-solved doctrine), and ``deferred_exempt_ids`` (the effect is
    genuinely unmodelled and deliberately deferred, with a stated reason --
    defaults to ``_AUDIT_DEFERRED_EXEMPT_IDS``; callers may pass ``{}`` to see
    what the audit would report without that channel).

    Both kinds also exclude commerce rooms, whose behaviour lives in
    ``engine/shops.py``: the ids in ``shop_rules``'s "shops" table plus
    ``_AUDIT_COMMERCE_EXTRA_IDS``. A shop's ``effect_text`` states only that it
    trades ("Items for Sale", "Launder Currency"), which shops.py implements in
    full, so counting them as unmodelled measures the audit's blind spot rather
    than the sim's. ``shop_rules`` defaults to no shops, which keeps every
    caller that does not pass it on the pre-existing behaviour.
    """
    if deferred_exempt_ids is None:
        deferred_exempt_ids = _AUDIT_DEFERRED_EXEMPT_IDS
    if python_exempt_ids is None:
        python_exempt_ids = _AUDIT_PYTHON_EXEMPT_IDS
    locks_backed = frozenset(rid for rid in _AUDIT_STRUCTURAL_EXEMPT_IDS if rid in by_id)
    # Sanity-check the locks-backed list so it can't silently rot: every id in
    # it must actually be exempt from locks.json's own always_unlocked/always_locked tables.
    lock_exempt = (set(lock_rules.get("always_unlocked_rooms", {}).get("rooms", []))
                   | set(lock_rules.get("always_locked_rooms", {}).get("rooms", [])))
    assert locks_backed <= lock_exempt, (
        f"_AUDIT_STRUCTURAL_EXEMPT_IDS has ids not in locks.json "
        f"always_unlocked_rooms/always_locked_rooms: {locks_backed - lock_exempt}"
    )
    structural = locks_backed | frozenset(
        rid for rid in (set(python_exempt_ids) | set(_AUDIT_DATA_EXEMPT_IDS)
                        | set(_AUDIT_DOCTRINE_EXEMPT_IDS) | set(deferred_exempt_ids))
        if rid in by_id)
    priced_shops = set((shop_rules or {}).get("shops", {}))
    commerce = frozenset(
        rid for rid in priced_shops | _AUDIT_COMMERCE_EXTRA_IDS if rid in by_id)

    if registered_room_ids is None:
        registered_room_ids = registered_rooms()

    kind1: list[str] = []
    kind2: list[str] = []
    for r in rooms:
        rid = r["id"]
        if rid in structural or rid in commerce:
            continue
        text = (r.get("meta", {}).get("effect_text") or "").strip()
        effects = r.get("effects", [])
        guaranteed = r.get("items", {}).get("guaranteed", [])

        variant_of = r.get("variant_of")
        if variant_of and text:
            parent = by_id.get(variant_of)
            if parent is not None:
                parent_text = (parent.get("meta", {}).get("effect_text") or "").strip()
                parent_effects = parent.get("effects", [])
                parent_guaranteed = parent.get("items", {}).get("guaranteed", [])
                if (effects == parent_effects and guaranteed == parent_guaranteed
                        and text != parent_text and rid not in registered_room_ids):
                    kind1.append(
                        f"{rid}: identical modelling to parent {variant_of!r} but "
                        f"effect_text differs ({text!r} vs parent's {parent_text!r})"
                    )

        if text and not effects and not guaranteed:
            if rid in registered_room_ids:
                continue
            kind2.append(
                f"{rid}: effect_text {text!r} present but no effects and no "
                f"items.guaranteed"
            )

    return kind1, kind2


_NO_EFFECT_CLAIM = re.compile(r"no effect model", re.IGNORECASE)


def find_empty_effects_findings(
    rooms: list[dict],
    si_items: list[dict],
    room_registered_ids: frozenset,
    item_registered_ids: frozenset,
) -> tuple[list[str], int, int, int, int]:
    """Census every room/item with an empty ``effects`` list against the
    engine/effects registries, and flag prose that contradicts its own
    registration.

    Task 22 moved a lot of behaviour OUT of the ``effects`` array and into
    per-room/per-item Python (``room_hook``, ``Capability`` via
    ``provides``/``provides_lever``, ``ItemCapability`` via
    ``item_provides``, ``ItemHook`` via ``item_hook``). The cost: ``effects:
    []`` no longer means "does nothing" -- it means "does nothing HERE".
    Rather than trust that distinction stays documented correctly by hand,
    this derives it: for every room/item whose ``effects`` list is empty, it
    asks whether the id is registered in ``room_registered_ids`` (rooms) /
    ``item_registered_ids`` (items) -- callers pass
    ``registered_rooms() | registered_capability_rooms()`` and
    ``registered_item_capability_ids() | registered_item_hook_ids()``
    respectively, so this function itself never imports ``engine.effects``
    and stays testable against constructed sets.

    Being empty-but-registered is not itself a finding -- that is the
    intended shape, and a record can also be modelled by a hand-written
    branch these two registries can't see (engine/game.py,
    engine/special_items.py; see ``_AUDIT_PYTHON_EXEMPT_IDS`` and --audit
    above), so "not found here" does not mean "genuinely does nothing", only
    "not found in these registries". A warning fires in exactly one case:
    the record IS registered, but its own prose (``meta.effect_text`` for
    rooms, ``meta.notes`` for items) claims no effect is modelled anyway --
    prose that has drifted out of sync with a room or item that is actually
    wired up and running.

    Returns ``(warnings, n_empty_rooms, n_room_registered, n_empty_items,
    n_item_registered)``.
    """
    findings: list[str] = []

    empty_rooms = [r for r in rooms if not r.get("effects")]
    n_room_registered = 0
    for r in empty_rooms:
        rid = r["id"]
        if rid not in room_registered_ids:
            continue
        n_room_registered += 1
        text = r.get("meta", {}).get("effect_text") or ""
        if _NO_EFFECT_CLAIM.search(text):
            findings.append(
                f"{rid}: effects=[] and effect_text claims no effect is modelled, but the "
                f"room IS registered in engine/effects (room_hook or Capability) -- prose "
                f"has drifted from the code"
            )

    empty_items = [it for it in si_items if not it.get("effects")]
    n_item_registered = 0
    for it in empty_items:
        iid = it["id"]
        if iid not in item_registered_ids:
            continue
        n_item_registered += 1
        notes = it.get("meta", {}).get("notes") or ""
        if _NO_EFFECT_CLAIM.search(notes):
            findings.append(
                f"{iid}: effects=[] and meta.notes claims no effect is modelled, but the "
                f"item IS registered in engine/effects (item_provides or item_hook) -- "
                f"prose has drifted from the code"
            )

    return findings, len(empty_rooms), n_room_registered, len(empty_items), n_item_registered


# The mechanically decidable subset of special_items.json's prose notes: a
# note that names a field together with an explicit value, in one of the four
# shapes _NOTES_*_RE below match. Everything else in the corpus is narrative
# (what a wiki page says in prose, why an id was split, what is out of
# scope...) and is not attempted -- a false positive here is worse than no
# checker at all.
_NOTES_FIELD_EMPTY_RE = re.compile(
    r"\b(spawn_rooms_high_luck|spawn_rooms|guaranteed_in|effects)\s+is\s+empty\b")
_NOTES_AREA_MODELLED_RE = re.compile(
    r"\b([a-z][a-z0-9_]*) is areas\.json modelled=(true|false)\b")
_NOTES_FIELD_VALUE_RE = re.compile(
    r"\b(guaranteed_in|spawn_rooms_high_luck|spawn_rooms|tier|kind)\s*=\s*"
    r"(?:\[(?P<list>[^\]]*)\]|(?P<val>[a-z0-9_]+))")
_NOTES_WIKI_COUNT_RE = re.compile(r"\bwiki lists (\d+) rooms\b")


def _load_wiki_locations(path: Path) -> dict[str, str]:
    """Load tools/raw/wiki_item_locations.tsv into ``{item_id: locations_raw}``.

    Skips the file's leading ``#`` comment block and the column-header row.
    Returns ``{}`` if the file is missing, so a caller with no snapshot to
    check against just finds nothing rather than erroring.
    """
    if not path.exists():
        return {}
    rows: dict[str, str] = {}
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#")]
    for ln in lines[1:]:  # lines[0] is the item_id/locations_raw/... header
        parts = ln.split("\t")
        if len(parts) >= 2:
            rows[parts[0]] = parts[1]
    return rows


def _resolve_notes_owner(note: str, si_items: list[dict]) -> dict | None:
    """Find the single special_items.json record a file-level ``_notes``
    entry is about, by the entry's own leading text.

    The corpus uses two conventions: the item's ``id`` followed by ``:``
    (e.g. ``"master_key: ..."``), or the item's ``name`` case-insensitively
    (e.g. ``"Car keys spawn rooms: ..."`` for ``car_keys``/"Car Keys"). An
    entry matching neither returns ``None`` rather than a guess -- a
    file-level aside can legitimately be about more than one item (e.g. the
    pre-split shared "sanctum_key" id), and this resolver only feeds checks
    that require one unambiguous owner.
    """
    for item in si_items:
        if note.startswith(item["id"] + ":") or note.lower().startswith(item["name"].lower()):
            return item
    return None


def _parse_notes_value(match: re.Match) -> object:
    """Turn a ``_NOTES_FIELD_VALUE_RE`` match into the Python value it names,
    so it can be compared against the record's own field with ``==``."""
    if match.group("list") is not None:
        return [v.strip() for v in match.group("list").split(",") if v.strip()]
    val = match.group("val")
    if val.isdigit():
        return int(val)
    return {"true": True, "false": False, "null": None}.get(val, val)


def find_notes_decay_findings(
    si_items: list[dict],
    si_notes: list[str],
    area_by_id: dict[str, dict],
    wiki_locations: dict[str, str],
) -> list[str]:
    """Check special_items.json's prose notes against the data they describe.

    Two channels: each item's own ``meta.notes`` (about that one item) and
    the file-level ``_notes`` array (asides not tied to a record by the JSON
    structure itself). Four shapes are checked, each an ERROR on mismatch --
    see the module comment above the ``_NOTES_*_RE`` patterns for why the
    rest of the corpus is left alone:

    1. ``meta.notes`` claiming one of the item's own list fields
       (spawn_rooms/spawn_rooms_high_luck/guaranteed_in/effects) "is empty".
    2. ``meta.notes`` claiming an areas.json node's ``modelled`` flag
       ("<id> is areas.json modelled=true/false"), checked against
       ``area_by_id``.
    3. A ``_notes`` entry naming a field=value or field=[a, b] assignment,
       resolved to its owning item via ``_resolve_notes_owner`` and checked
       against that item's own field.
    4. A ``_notes`` entry naming a "wiki lists N rooms" count, resolved the
       same way and checked against ``wiki_locations``'s raw comma-token
       count for that item (when the item has a snapshot row at all).

    ``wiki_locations`` is a pinned snapshot (see WIKI_LOCATIONS_TSV / that
    file's own header) -- this catches a note drifting from the snapshot, not
    the snapshot drifting from the live wiki.
    """
    findings: list[str] = []

    for item in si_items:
        note = item.get("meta", {}).get("notes")
        if not isinstance(note, str):
            continue
        for m in _NOTES_FIELD_EMPTY_RE.finditer(note):
            field = m.group(1)
            actual = item.get(field, [])
            if actual:
                findings.append(
                    f"special_items/{item['id']} meta.notes claims {field!r} is empty, "
                    f"but it is {actual!r}"
                )
        for m in _NOTES_AREA_MODELLED_RE.finditer(note):
            aid, claimed = m.group(1), m.group(2) == "true"
            area = area_by_id.get(aid)
            if area is None:
                continue
            actual = area.get("modelled")
            if actual != claimed:
                findings.append(
                    f"special_items/{item['id']} meta.notes claims areas.json "
                    f"{aid!r} modelled={claimed}, but it is modelled={actual!r}"
                )

    for note in si_notes:
        owner = _resolve_notes_owner(note, si_items)
        if owner is None:
            continue
        for m in _NOTES_FIELD_VALUE_RE.finditer(note):
            field = m.group(1)
            claimed = _parse_notes_value(m)
            actual = owner.get(field)
            if actual != claimed:
                findings.append(
                    f"special_items/_notes claims {owner['id']}.{field}={claimed!r}, "
                    f"but it is {actual!r}"
                )
        for m in _NOTES_WIKI_COUNT_RE.finditer(note):
            claimed_n = int(m.group(1))
            raw = wiki_locations.get(owner["id"])
            if raw is None:
                continue
            actual_n = len([t for t in raw.split(",") if t.strip()])
            if actual_n != claimed_n:
                findings.append(
                    f"special_items/_notes claims the wiki lists {claimed_n} rooms for "
                    f"{owner['id']!r}, but tools/raw/wiki_item_locations.tsv's snapshot "
                    f"has {actual_n}"
                )

    return findings


# ── spawn-table checker (tools/raw/wiki_item_locations.tsv) ─────────────────
# Diffs special_items.json's spawn_rooms/spawn_rooms_high_luck against the
# pinned wiki snapshot -- see that file's own header for the fetch method and
# the honest limit (it catches sim drift from the snapshot, never the wiki
# drifting after the snapshot's fetch_date).

# Non-room mechanic tokens the wiki's Locations= field carries alongside real
# rooms (a Dig Spot, the Trunk/Car Trunk, a delivered Package, the
# Experimental Setup, the Spiral staircase, a Locker, a Crate, the Billiard
# Room's Dartboard) -- matched case-insensitively, since the snapshot itself
# is not consistently cased ("Dig spot" vs "Dig Spot").
_WIKI_MECHANIC_TOKENS = frozenset({
    "experiment", "spiral", "dartboard", "package", "trunk", "car trunk",
    "dig spot", "locker", "crate",
})
# Shop rooms already modelled through their own stock/trade channel
# (shops.py), not the generic spawn pool -- matched case-sensitively, same as
# every other room name.
_WIKI_SHOP_EXCLUDED_NAMES = frozenset({"Commissary", "Locksmith", "Lost & Found",
                                       "Trading Post"})
# Items whose wiki Locations= names a single fixed spot that this sim models
# as a guaranteed find or a shop purchase, never a spawn_rooms roll -- see
# each item's own meta.notes for which. Excluded from the diff entirely
# rather than compared against guaranteed_in, so a real gap in THEIR
# guaranteed_in/shop wiring surfaces only through special_items.json's own
# field checks (or the notes-decay checker above), not a duplicate finding
# here.
_WIKI_FIXED_LOCATION_EXEMPT_IDS = frozenset({"key_8", "basement_key", "master_key"})


def _room_name_to_id_map(rooms: list[dict]) -> dict[str, str]:
    """Build a {wiki room name: rooms.json id} map, one id per display name.

    Several rooms.json records share a display name -- a base room and its
    upgrade variants all keep the room's real-world name (e.g. all four
    "Mail Room" records: mail_room, mail_room__ix89/90/91). The wiki's spawn
    listing names the room family once; this sim's own convention is to
    record that family's spawn entry against the BASE id (no "__" in it),
    never an individual variant's id -- confirmed against every current
    special_items.json spawn_rooms list, none of which names a variant id.
    When a name has only one record this is moot.
    """
    by_name: dict[str, list[str]] = {}
    for r in rooms:
        by_name.setdefault(r["name"], []).append(r["id"])
    name_to_id: dict[str, str] = {}
    for name, ids in by_name.items():
        canon = [i for i in ids if "__" not in i]
        name_to_id[name] = canon[0] if canon else min(ids, key=len)
    # "Spare Servant's Quarters" (wiki word order) vs this sim's
    # "Servant's Spare Quarters" (rooms.json's actual name field).
    name_to_id["Spare Servant's Quarters"] = "servants_spare_quarters__ix134"
    return name_to_id


def _parse_wiki_locations_row(
    raw: str,
    name_to_id: dict[str, str],
    mechanic_tokens: frozenset[str],
    shop_names: frozenset[str],
) -> tuple[set[str], set[str], list[str]]:
    """Split one locations_raw string into (normal, high_luck, unresolved).

    A "!" prefix marks the high-luck tier. mechanic_tokens and shop_names are
    dropped before resolution and never reach ``unresolved`` -- they are
    deliberately excluded, not unrecognised. A token that is neither of
    those AND resolves to no rooms.json room name goes into ``unresolved``
    instead of being silently dropped: without this, lifting a mechanic
    token from ``mechanic_tokens`` (e.g. testing that "Spiral" is excluded
    because it is genuinely not a room, not because the checker forgot to
    look) would fall through to the same silent drop and change nothing,
    making the exclusion category untestable for necessity.
    """
    normal: set[str] = set()
    high: set[str] = set()
    unresolved: list[str] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        is_high = tok.startswith("!")
        name = tok[1:].strip() if is_high else tok
        if name.lower() in mechanic_tokens or name in shop_names:
            continue
        rid = name_to_id.get(name)
        if rid is None:
            unresolved.append(name)
            continue
        (high if is_high else normal).add(rid)
    return normal, high, unresolved


def find_spawn_table_findings(
    si_items: list[dict],
    rooms: list[dict],
    wiki_locations: dict[str, str],
    mechanic_tokens: frozenset[str] = _WIKI_MECHANIC_TOKENS,
    shop_names: frozenset[str] = _WIKI_SHOP_EXCLUDED_NAMES,
    fixed_location_exempt_ids: frozenset[str] = _WIKI_FIXED_LOCATION_EXEMPT_IDS,
) -> list[str]:
    """Diff each item's spawn_rooms/spawn_rooms_high_luck against
    ``wiki_locations`` (tools/raw/wiki_item_locations.tsv's
    {item_id: locations_raw}), after dropping mechanic tokens, the 4-shop
    exclusion set and the 3 fixed-location items.

    Five kinds of mismatch, all ERRORs:

    - unresolved: a snapshot token is neither a mechanic token, a shop
      exclusion, nor a known rooms.json room name -- surfaced instead of
      silently dropped, so lifting a mechanic token out of
      ``mechanic_tokens`` (proving it is excluded because it does not
      resolve, not because the checker forgot to look) has something to
      flag; see ``_parse_wiki_locations_row``.
    - missing (normal): the snapshot names a room neither spawn_rooms NOR
      guaranteed_in covers -- guaranteed_in counts here because a room the
      sim models as a guaranteed find (rather than a probabilistic roll) is
      still modelled, just via a stronger channel than spawn_rooms.
    - extra (normal): spawn_rooms has a room the snapshot's normal tier does
      not. guaranteed_in is NOT consulted for this direction -- it names a
      separate mechanic (e.g. a Cloister-of-Mila bedroom bonus, a puzzle
      reward) that generally is not part of the wiki's Locations= listing at
      all, so comparing it against that listing would be a category error,
      not a real extra.
    - missing/extra (high-luck): spawn_rooms_high_luck vs. the snapshot's "!"
      tier, symmetric, no guaranteed_in involved (nothing in this sim's
      guaranteed_in is high-luck-gated).

    Every parameter has a default so a bare call checks the real data;
    callers/tests can pass ``frozenset()`` for any exclusion channel to see
    what the checker would flag without it (the necessity guard).
    """
    findings: list[str] = []
    name_to_id = _room_name_to_id_map(rooms)
    si_by_id = {i["id"]: i for i in si_items}
    for item_id, raw in sorted(wiki_locations.items()):
        if item_id in fixed_location_exempt_ids:
            continue
        item = si_by_id.get(item_id)
        if item is None:
            continue
        wiki_normal, wiki_high, unresolved = _parse_wiki_locations_row(
            raw, name_to_id, mechanic_tokens, shop_names)
        for name in unresolved:
            findings.append(
                f"special_items/{item_id}: wiki snapshot token {name!r} is not a "
                f"known mechanic token, shop exclusion, or rooms.json room name"
            )
        sim_normal = set(item.get("spawn_rooms", []))
        sim_high = set(item.get("spawn_rooms_high_luck", []))
        sim_guaranteed = set(item.get("guaranteed_in", []))
        for rid in sorted(wiki_normal - sim_normal - sim_guaranteed):
            findings.append(
                f"special_items/{item_id}: wiki snapshot lists {rid!r} but it is in "
                f"neither spawn_rooms nor guaranteed_in"
            )
        for rid in sorted(sim_normal - wiki_normal):
            findings.append(
                f"special_items/{item_id}: spawn_rooms has {rid!r}, not in the wiki "
                f"snapshot's normal-tier locations"
            )
        for rid in sorted(wiki_high - sim_high):
            findings.append(
                f"special_items/{item_id}: wiki snapshot lists {rid!r} as high-luck "
                f"but spawn_rooms_high_luck does not"
            )
        for rid in sorted(sim_high - wiki_high):
            findings.append(
                f"special_items/{item_id}: spawn_rooms_high_luck has {rid!r}, not in "
                f"the wiki snapshot's high-luck locations"
            )
    return findings


def _assert_data_exemptions_live(by_id: dict[str, dict]) -> None:
    """Fail if a data-exempt room no longer carries the field its entry names.

    The exemption asserts the room's text merely restates a value its own
    record already holds. Delete or empty that value and the claim is false,
    but nothing else would notice -- the room would simply stay off the
    worklist while its text promised something no longer there.
    """
    for rid, path in sorted(_AUDIT_DATA_EXEMPT_IDS.items()):
        rec = by_id.get(rid)
        assert rec is not None, f"_AUDIT_DATA_EXEMPT_IDS: {rid} is not a room"
        node = rec
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, (
                f"_AUDIT_DATA_EXEMPT_IDS: {rid!r} no longer carries {path!r}; "
                f"either the field moved or the exemption is stale"
            )
            node = node[part]
        assert node not in (None, "", [], {}), (
            f"_AUDIT_DATA_EXEMPT_IDS: {rid!r}'s {path!r} is empty, so the "
            f"exemption's claim that its text restates a real value is false"
        )


def _assert_deferred_exemptions_live(
    rooms: list[dict],
    by_id: dict[str, dict],
    lock_rules: dict,
    shop_rules: dict | None,
) -> None:
    """Fail if a deferred-exempt room's id is gone, or the exemption no longer
    suppresses anything.

    Unlike the other three channels, a deferred exemption doesn't claim the
    room is modelled somewhere the audit can't see -- it claims the opposite,
    that the gap is real and deliberately postponed. That claim rots if the
    room is deleted, or if it quietly becomes modelled (an effect/room_hook
    lands) without the exemption being retired: the entry would then suppress
    nothing, which is dead weight at best and, per prior incidents, a sign
    someone added a no-op hook purely to dodge this audit rather than fixing
    it. Reruns find_divergences with the deferred channel disabled (passing
    ``{}``) and requires every exempted id to actually appear in the raw
    kind1/kind2 findings -- the exact same rule the audit itself uses, so this
    can't drift from what "would otherwise flag" means.
    """
    for rid in sorted(_AUDIT_DEFERRED_EXEMPT_IDS):
        assert rid in by_id, f"_AUDIT_DEFERRED_EXEMPT_IDS: {rid} no longer exists in rooms.json"
    raw_kind1, raw_kind2 = find_divergences(
        rooms, by_id, lock_rules, shop_rules=shop_rules, deferred_exempt_ids={})
    raw = raw_kind1 + raw_kind2
    for rid in sorted(_AUDIT_DEFERRED_EXEMPT_IDS):
        if not any(f.startswith(f"{rid}:") for f in raw):
            raise AssertionError(
                f"_AUDIT_DEFERRED_EXEMPT_IDS: {rid!r} is no longer flagged by the audit "
                f"without this exemption; either it is now modelled (retire the entry) "
                f"or the exemption is stale"
            )


def main(argv: list[str] | None = None) -> int:
    """Check every data/*.json file and print a report; return 1 if any error, else 0.

    Errors are schema/range/referential violations that must block a commit;
    warnings (unknown draft-condition tags, unhandled effect tags) are printed
    but do not affect the exit code. The room-fidelity divergence audit is a
    separate, opt-in channel: its findings are worklist entries, not
    validation failures, so they are never counted as errors or warnings and
    are only printed with ``--audit``. Always exits 0 when there are no
    errors, with or without ``--audit``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit", action="store_true",
        help="also print the room-fidelity divergence worklist; "
             "informational only, does not affect the exit code",
    )
    args = parser.parse_args(argv)

    # --audit prints raw meta.effect_text, which carries in-game currency
    # glyphs (steps/gems icons) outside the Windows console's default cp1252
    # codepage; widen stdout to UTF-8 so --audit can't crash mid-report.
    if args.audit and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    errors: list[str] = []
    warnings: list[str] = []

    rooms_doc = json.loads((DATA / "rooms.json").read_text())
    weights = json.loads((DATA / "weights.json").read_text())
    priority = json.loads((DATA / "priority_draws.json").read_text())
    items_doc = json.loads((DATA / "items.json").read_text())
    lock_rules = json.loads((DATA / "locks.json").read_text())

    rooms = rooms_doc["rooms"]
    ids = [r["id"] for r in rooms]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        errors.append(f"duplicate room ids: {dupes}")
    by_id = {r["id"]: r for r in rooms}

    # (where, item id) pairs from items.dig_guaranteed, checked against
    # si_by_id once special_items.json is loaded further down — same deferred
    # pattern as absent_area_refs (rooms are validated before special_items).
    dig_guaranteed_refs: list[tuple[str, str]] = []

    for r in rooms:
        where = r["id"]
        if r.get("rarity") not in VALID_RARITIES:
            errors.append(f"{where}: bad rarity {r.get('rarity')}")
        if r["layout"] not in VALID_LAYOUTS:
            errors.append(f"{where}: bad layout {r['layout']}")
        for alt in r.get("alt_layouts", []):
            if alt not in VALID_LAYOUTS:
                errors.append(f"{where}: bad alt layout {alt}")
        if r["category"] not in VALID_CATEGORIES:
            errors.append(f"{where}: bad category {r['category']}")
        for extra_cat in r.get("extra_categories", []):
            if extra_cat not in VALID_CATEGORIES:
                errors.append(f"{where}: extra_categories has unknown category {extra_cat!r}")
            if extra_cat == r["category"]:
                warnings.append(
                    f"{where}: extra_categories restates the primary category {extra_cat!r}")
        if r.get("pool", "base") not in VALID_POOLS:
            errors.append(f"{where}: bad pool {r.get('pool')}")
        conf = r.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: bad confidence {conf}")
        if conf == "placeholder" and r.get("pool") == "base":
            errors.append(f"{where}: placeholder room in default pool")
        gem = r.get("gem_cost", 0)
        if not isinstance(gem, int) or gem < 0 or gem > 9:
            errors.append(f"{where}: bad gem_cost {gem}")
        for cond in r.get("draft_conditions", []):
            if (cond not in KNOWN_CONDITIONS and not cond.startswith("rank_gte_")
                    and not cond.startswith("rank_lte_")):
                warnings.append(f"{where}: unknown draft condition {cond!r} (permissive)")
        for eff in r.get("effects", []):
            if eff["tag"] not in KNOWN_EFFECT_TAGS:
                warnings.append(f"{where}: effect tag {eff['tag']!r} has no handler")
            if eff["tag"] == "inject_pool":
                for rid in eff.get("rooms", []):
                    if rid not in by_id:
                        errors.append(f"{where}: inject_pool references unknown room {rid}")
        if r.get("variant_of") and r["variant_of"] not in by_id:
            warnings.append(f"{where}: variant_of {r['variant_of']!r} not a known id")
        guaranteed = r.get("items", {}).get("guaranteed", [])
        guaranteed_kinds = []
        for g in guaranteed:
            gitem, gcount = g.get("item"), g.get("count")
            # engine/items.py::grant_item silently no-ops on an item id it
            # doesn't recognise (logs the pickup but grants nothing) -- a typo
            # here would fail silently at runtime, so it is caught here at
            # data-validation time instead.
            if gitem not in KNOWN_GUARANTEED_ITEM_KINDS:
                errors.append(f"{where}: items.guaranteed has unknown item kind {gitem!r}")
            if not isinstance(gcount, int) or gcount < 0:
                errors.append(f"{where}: items.guaranteed {gitem!r} has bad count {gcount!r}")
            guaranteed_kinds.append(gitem)
        if "coins" in guaranteed_kinds and "coins_exact" in guaranteed_kinds:
            errors.append(
                f"{where}: items.guaranteed has both 'coins' (pile roll) and "
                f"'coins_exact' (literal amount) -- ambiguous, pick one"
            )
        dig_guaranteed = r.get("items", {}).get("dig_guaranteed")
        if dig_guaranteed is not None:
            if not r.get("items", {}).get("dig_spots"):
                errors.append(
                    f"{where}: items.dig_guaranteed {dig_guaranteed!r} set but dig_spots is 0"
                )
            dig_guaranteed_refs.append((where, dig_guaranteed))

    # weights
    for stage, slots in weights["tables"].items():
        for slot_class, rows in slots.items():
            if set(rows) != {str(i) for i in range(1, 10)}:
                errors.append(f"weights {stage}/{slot_class}: missing ranks")
            for rank, row in rows.items():
                if len(row) != 4:
                    errors.append(f"weights {stage}/{slot_class}/{rank}: not 4 values")
                elif abs(sum(row) - 100.0) > 0.02:
                    errors.append(f"weights {stage}/{slot_class}/{rank}: sums to {sum(row)}")
    for rank, row in weights["solarium_slot23"].items():
        if abs(sum(row) - 100.0) > 0.02:
            errors.append(f"solarium row {rank} sums to {sum(row)}")
    # The Library override is one flat rank-independent row, unlike the tables
    # above; same shape rules apply. Its VALUES are pinned behaviourally in
    # tests/test_library_rarity_override.py -- this is the schema/range half.
    lib_row = weights["library_override"]["weights"]
    if len(lib_row) != 4:
        errors.append(f"library_override: not 4 values ({len(lib_row)})")
    elif abs(sum(lib_row) - 100.0) > 0.02:
        errors.append(f"library_override sums to {sum(lib_row)}")
    if any(w < 0 for w in lib_row):
        errors.append(f"library_override has a negative weight: {lib_row}")

    # free_gem_draws (Drafting/Advanced "Free/Gem Draws"): unlike the rarity
    # tables above, each value here is an independent Gem-vs-Free Bernoulli
    # chance, not one slice of a 100%-exhaustive row -- so rows are range-
    # checked (0-100), never sum-checked. slot2_gem_chance is rank x
    # [0 gems, 1-3 gems, 4+ gems]; slot3_rank_chance is rank -> a single
    # percentage; slot3_low_gem_chance is one flat percentage (see
    # draft.py::_resolve_free_gem for how the three combine).
    fgd = weights["free_gem_draws"]
    ranks = {str(i) for i in range(1, 10)}
    slot2 = fgd["slot2_gem_chance"]
    if set(slot2) != ranks:
        errors.append("free_gem_draws.slot2_gem_chance: missing ranks")
    for rank, row in slot2.items():
        if len(row) != 3:
            errors.append(f"free_gem_draws.slot2_gem_chance/{rank}: not 3 values")
        elif any(not 0.0 <= w <= 100.0 for w in row):
            errors.append(f"free_gem_draws.slot2_gem_chance/{rank}: out of range {row}")
    low = fgd["slot3_low_gem_chance"]
    if not 0.0 <= low <= 100.0:
        errors.append(f"free_gem_draws.slot3_low_gem_chance out of range: {low}")
    rank3 = fgd["slot3_rank_chance"]
    if set(rank3) != ranks:
        errors.append("free_gem_draws.slot3_rank_chance: missing ranks")
    for rank, p in rank3.items():
        if not 0.0 <= p <= 100.0:
            errors.append(f"free_gem_draws.slot3_rank_chance/{rank} out of range: {p}")
    conf = fgd.get("meta", {}).get("confidence")
    if conf not in VALID_CONFIDENCE:
        errors.append(f"free_gem_draws.meta: bad confidence {conf}")

    # priority draws reference real rooms; an optional "condition" tag must be
    # one _active_conditions can actually emit -- reuse category_biases' own
    # condition values as that vocabulary, plus KNOWN_PRIORITY_DRAW_ONLY_CONDITIONS
    # for tags (like add_aquariums) that gate a priority_draws entry directly
    # and have no category_biases entry to source the vocabulary from.
    active_condition_tags = {e["condition"] for e in priority.get("category_biases", [])
                             if "condition" in e} | KNOWN_PRIORITY_DRAW_ONLY_CONDITIONS
    for entry in priority["priority_draws"]:
        for rid in entry["rooms"]:
            if rid not in by_id:
                errors.append(f"priority draw references unknown room {rid}")
        condition = entry.get("condition")
        if condition is not None and condition not in active_condition_tags:
            warnings.append(
                f"priority draw {entry['label']!r}: unknown condition {condition!r} (permissive)")
    for rid in priority["forced_draw_precedence"]["order"]:
        if rid not in by_id:
            warnings.append(f"forced-draw precedence references unknown room {rid}")
    for entry in priority.get("forced_draws", []):
        if entry["room"] not in by_id:
            errors.append(f"forced draw references unknown room {entry['room']}")
        for key in ("chance", "chance_with_west_gate"):
            if key in entry and not 0 <= entry[key] <= 1:
                errors.append(f"forced draw {entry['room']}/{key} out of range: {entry[key]}")
        if "chance_with_west_gate" in entry and entry["chance_with_west_gate"] < entry["chance"]:
            errors.append(f"forced draw {entry['room']}: chance_with_west_gate below base chance")

    # items.json: food.fruit_weights must only name real dishes, with
    # positive weights -- a typo'd fruit id would otherwise silently fall
    # back to food.default_steps forever (grant_item's "fruit" case).
    fruit_weights = items_doc.get("food", {}).get("fruit_weights", {})
    dishes = items_doc.get("food", {}).get("dishes", {})
    if not fruit_weights:
        # expected_yields divides by the weight total on every room it prices.
        errors.append("food.fruit_weights: must name at least one dish")
    for fruit_id, weight in fruit_weights.items():
        if fruit_id not in dishes:
            errors.append(f"food.fruit_weights: {fruit_id!r} not in food.dishes")
        if not isinstance(weight, (int, float)) or weight <= 0:
            errors.append(f"food.fruit_weights: {fruit_id!r} has non-positive weight {weight!r}")

    # items.json: item_ladder -- the published item-count ladder engine/items.py's
    # roll_ladder_count reads (an unvalidated data section fails open); checks band
    # coverage/contiguity, per-kind row shape, and percentage ranges. See
    # items.json's item_ladder.meta for the wiki source.
    VALID_LADDER_BAND_KINDS = {"flat", "chain", "variable_mix", "always_variable", "fixed"}
    VALID_LADDER_VARIABLE_KINDS = {"fixed", "roll"}
    VALID_CHAIN_CONDITIONS = {"room46_reached", "day_gte",
                              "day1_veteran_by_fast_early_drafts", "veteran_mode", "otherwise"}

    def _pct(where: str, val) -> None:
        if not isinstance(val, (int, float)) or not 0 <= val <= 100:
            errors.append(f"{where}: percentage out of range 0-100: {val!r}")

    def _check_ladder_rows(rows: list, valid_kinds: set, label: str) -> None:
        if not rows:
            errors.append(f"{label}: must be non-empty")
        prev_max = None
        for i, band in enumerate(rows):
            where = f"{label}[{i}]"
            kind = band.get("kind")
            if kind not in valid_kinds:
                errors.append(f"{where}: bad kind {kind!r}")
            lo, hi = band.get("min"), band.get("max")
            if i == 0 and lo is not None:
                errors.append(f"{where}: first row must be unbounded below (no 'min')")
            if i == len(rows) - 1 and hi is not None:
                errors.append(f"{where}: last row must be unbounded above (no 'max')")
            if lo is not None and hi is not None and lo > hi:
                errors.append(f"{where}: min {lo} > max {hi}")
            if prev_max is not None and lo != prev_max + 1:
                errors.append(
                    f"{where}: not contiguous with previous row "
                    f"(prev max {prev_max}, this min {lo})")
            prev_max = hi
            if kind == "fixed":
                items_n = band.get("items")
                if not isinstance(items_n, int) or items_n < 0:
                    errors.append(f"{where}.items: bad value {items_n!r}")
                penalty = band.get("penalty")
                if not isinstance(penalty, int) or penalty < 0:
                    errors.append(f"{where}.penalty: bad value {penalty!r}")
            elif kind == "flat":
                _pct(f"{where}.p_one_pct", band.get("p_one_pct"))
            elif kind == "chain":
                chain = band.get("chain", [])
                if not chain or chain[-1].get("if") != "otherwise":
                    errors.append(f"{where}.chain: last row must be the 'otherwise' fallback")
                for j, row in enumerate(chain):
                    cwhere = f"{where}.chain[{j}]"
                    cond = row.get("if")
                    if cond not in VALID_CHAIN_CONDITIONS:
                        errors.append(f"{cwhere}: unknown condition {cond!r}")
                    _pct(f"{cwhere}.p_one_pct", row.get("p_one_pct"))
                    if cond == "day_gte" and not isinstance(row.get("day"), int):
                        errors.append(f"{cwhere}: day_gte row needs an integer 'day'")
            elif kind == "variable_mix":
                _pct(f"{where}.p_variable_pct", band.get("p_variable_pct"))
                _pct(f"{where}.p_one_pct", band.get("p_one_pct"))
                total = (band.get("p_variable_pct") or 0) + (band.get("p_one_pct") or 0)
                if total > 100:
                    errors.append(f"{where}: p_variable_pct + p_one_pct exceeds 100 ({total})")
            elif kind == "roll":
                _pct(f"{where}.p_three_pct", band.get("p_three_pct"))
                for key in ("three_penalty", "two_penalty"):
                    val = band.get(key)
                    if not isinstance(val, int) or val < 0:
                        errors.append(f"{where}.{key}: bad value {val!r}")
            # "always_variable" carries no extra fields to check.

    ladder = items_doc.get("item_ladder", {})
    lconf = ladder.get("meta", {}).get("confidence")
    if lconf not in VALID_CONFIDENCE:
        errors.append(f"item_ladder.meta: bad confidence {lconf!r}")
    _check_ladder_rows(ladder.get("bands", []), VALID_LADDER_BAND_KINDS, "item_ladder.bands")
    _check_ladder_rows(ladder.get("variable", []), VALID_LADDER_VARIABLE_KINDS,
                       "item_ladder.variable")

    # items.json: never_roll_rooms -- engine/items.py's roll_room_items reads
    # this BEFORE ever calling roll_ladder_count for a listed room. An
    # unvalidated data section fails open: a typo'd id here would silently
    # mean "this room isn't special" and nothing would notice.
    never_roll = items_doc.get("never_roll_rooms", {})
    nr_conf = never_roll.get("meta", {}).get("confidence")
    if nr_conf not in VALID_CONFIDENCE:
        errors.append(f"never_roll_rooms.meta: bad confidence {nr_conf!r}")
    nr_rooms = never_roll.get("rooms", [])
    if not nr_rooms:
        errors.append("never_roll_rooms.rooms: must be non-empty")
    if len(nr_rooms) != len(set(nr_rooms)):
        errors.append("never_roll_rooms.rooms: duplicate room ids")
    for rid in nr_rooms:
        if rid not in by_id:
            errors.append(f"never_roll_rooms references unknown room {rid!r}")

    # items.json: count_transforms -- per-room item_ladder.raw-count
    # transforms (Nook/Study/Guest Bedroom/Den/Lost & Found's published
    # wiki quotes). Same fail-open concern as never_roll_rooms above.
    VALID_TRANSFORM_KINDS = {"reduce_by_one_chance", "zero_becomes_one",
                             "zero_becomes_one_or_gem", "one_becomes_trunk", "not_modeled",
                             "deferred_ladder"}
    transforms = items_doc.get("count_transforms", {})
    ct_conf = transforms.get("meta", {}).get("confidence")
    if ct_conf not in VALID_CONFIDENCE:
        errors.append(f"count_transforms.meta: bad confidence {ct_conf!r}")
    ct_rooms = transforms.get("rooms", {})
    if not ct_rooms:
        errors.append("count_transforms.rooms: must be non-empty")
    for rid, spec in ct_rooms.items():
        if rid not in by_id:
            errors.append(f"count_transforms references unknown room {rid!r}")
        if rid in nr_rooms:
            errors.append(f"count_transforms/{rid}: also in never_roll_rooms (contradictory)")
        kind = spec.get("kind")
        if kind not in VALID_TRANSFORM_KINDS:
            errors.append(f"count_transforms/{rid}: bad kind {kind!r}")
            continue
        if kind == "reduce_by_one_chance":
            _pct(f"count_transforms/{rid}.p_pct", spec.get("p_pct"))
        elif kind == "zero_becomes_one_or_gem":
            _pct(f"count_transforms/{rid}.p_one_pct", spec.get("p_one_pct"))
            _pct(f"count_transforms/{rid}.p_gem_pct", spec.get("p_gem_pct"))
        elif kind == "deferred_ladder":
            add, lo, hi = spec.get("add"), spec.get("min"), spec.get("max")
            guaranteed_add = spec.get("guaranteed_add")
            if not isinstance(add, int) or add < 0:
                errors.append(f"count_transforms/{rid}.add: must be a non-negative int, "
                              f"got {add!r}")
            if not isinstance(lo, int) or not isinstance(hi, int) or lo > hi or lo < 0:
                errors.append(f"count_transforms/{rid}.min/max: must be ints with 0 <= min <= max, "
                              f"got {lo!r}/{hi!r}")
            if not isinstance(guaranteed_add, int) or guaranteed_add < 0:
                errors.append(f"count_transforms/{rid}.guaranteed_add: must be a non-negative int, "
                              f"got {guaranteed_add!r}")
        # "zero_becomes_one", "one_becomes_trunk", "not_modeled" carry no extra fields.

    # items.json: dowsing_rod -- the Dowsing Rod's own +32-luck/own-Dowsing-
    # Penalty item-count table (engine/items.py's roll_dowsed_count) plus its
    # two room lists (draft.py's slot-pick avoid_rooms; this table's own
    # variable_items_rooms). Same fail-open concern as never_roll_rooms/
    # count_transforms above. Deliberately NOT cross-checked against
    # never_roll_rooms/count_transforms/each other:
    # the wiki publishes these as separate, independently-curated lists (a
    # room may legitimately sit on more than one, or on none).
    VALID_DOWSING_RESULTS = {"one", "variable", "fixed", "recurse_0_2"}
    dowsing = items_doc.get("dowsing_rod", {})
    dw_conf = dowsing.get("meta", {}).get("confidence")
    if dw_conf not in VALID_CONFIDENCE:
        errors.append(f"dowsing_rod.meta: bad confidence {dw_conf!r}")
    rod_luck_bonus = dowsing.get("rod_luck_bonus")
    if not isinstance(rod_luck_bonus, int) or rod_luck_bonus <= 0:
        errors.append(f"dowsing_rod.rod_luck_bonus: must be a positive int, "
                      f"got {rod_luck_bonus!r}")
    luck_max = dowsing.get("regular_routine_luck_max")
    if not isinstance(luck_max, int):
        errors.append(f"dowsing_rod.regular_routine_luck_max: must be an int, got {luck_max!r}")

    def _check_dowsing_room_list(key: str) -> None:
        room_ids = dowsing.get(key, [])
        if not room_ids:
            errors.append(f"dowsing_rod.{key}: must be non-empty")
        if len(room_ids) != len(set(room_ids)):
            errors.append(f"dowsing_rod.{key}: duplicate room ids")
        for rid in room_ids:
            if rid not in by_id:
                errors.append(f"dowsing_rod.{key} references unknown room {rid!r}")
            elif by_id[rid].get("variant_of") is not None:
                # These lists are matched generically at runtime via a
                # variant_of walk to the family ROOT (upgrades.root_base_id)
                # -- an upgrade-variant id here would never match anything
                # (an already-upgraded room's own id is never re-checked
                # against the list, only its root's), silently.
                errors.append(f"dowsing_rod.{key}: {rid!r} is an upgrade variant, "
                              f"not a family root -- list the base room instead")

    _check_dowsing_room_list("avoid_rooms")
    _check_dowsing_room_list("variable_items_rooms")

    bands = dowsing.get("penalty_bands", [])
    prev_max = None
    for i, band in enumerate(bands):
        where = f"dowsing_rod.penalty_bands[{i}]"
        lo, hi = band.get("min"), band.get("max")
        if i == 0 and lo is not None:
            errors.append(f"{where}: first row must be unbounded below (no 'min')")
        if i == len(bands) - 1 and hi is not None:
            errors.append(f"{where}: last row must be unbounded above (no 'max')")
        if lo is not None and hi is not None and lo > hi:
            errors.append(f"{where}: min {lo} > max {hi}")
        if prev_max is not None and lo != prev_max + 1:
            errors.append(f"{where}: not contiguous with previous row "
                          f"(prev max {prev_max}, this min {lo})")
        prev_max = hi
        outcomes = band.get("outcomes", [])
        if not outcomes:
            errors.append(f"{where}.outcomes: must be non-empty")
        total = 0.0
        for j, outcome in enumerate(outcomes):
            owhere = f"{where}.outcomes[{j}]"
            result = outcome.get("result")
            if result not in VALID_DOWSING_RESULTS:
                errors.append(f"{owhere}: bad result {result!r}")
            if result == "recurse_0_2" and i == 0:
                errors.append(f"{owhere}: 'recurse_0_2' is only valid outside the first "
                              f"(0-2 Dowsing Penalty) band")
            p_pct = outcome.get("p_pct")
            _pct(f"{owhere}.p_pct", p_pct)
            if isinstance(p_pct, (int, float)):
                total += p_pct
            if result == "fixed":
                for fkey in ("items", "penalty", "dowsing_penalty"):
                    val = outcome.get(fkey)
                    if not isinstance(val, int) or val < 0:
                        errors.append(f"{owhere}.{fkey}: bad value {val!r}")
        if outcomes and abs(total - 100.0) > 1e-9:
            errors.append(f"{where}.outcomes: p_pct sums to {total}, expected 100")
    if not bands:
        errors.append("dowsing_rod.penalty_bands: must be non-empty")

    # locks.json: table shape, referential integrity, sane probabilities
    ew = lock_rules["lock_chance"]["ew_by_rank"]
    if set(ew) != {str(i) for i in range(1, 10)}:
        errors.append("locks ew_by_rank: missing ranks")
    ns = lock_rules["lock_chance"]["ns_boundary"]
    if set(ns) != {str(i) for i in range(1, 9)}:
        errors.append("locks ns_boundary: expected boundary ranks 1-8")
    for rank, band in ns.items():
        if set(band) != {"edge", "center"}:
            errors.append(f"locks ns_boundary/{rank}: need edge+center")
    for chance in [*ew.values(),
                   *(v for band in ns.values() for v in band.values())]:
        if not 0 <= chance <= 200:
            errors.append(f"locks lock_chance out of range: {chance}")
    for key in ("locked_delta", "unlocked_delta",
                "low_second_roll_below", "high_second_roll_above"):
        if key not in lock_rules["bias"]:
            errors.append(f"locks bias: missing {key}")
    sec = lock_rules["security"]
    if set(sec["spawn_limit"]) != {"low", "normal", "high"}:
        errors.append("locks spawn_limit: need low/normal/high")
    for rid, chance in sec["room_door_chance"].items():
        if rid not in by_id:
            errors.append(f"locks room_door_chance references unknown room {rid}")
        if not 0 <= chance <= 100:
            errors.append(f"locks room_door_chance/{rid} out of range: {chance}")
    if not 0 <= lock_rules["keycard"]["chance"] <= 100:
        errors.append("locks keycard chance out of range")
    always_locked = lock_rules.get("always_locked_rooms", {})
    for rid in [*lock_rules["keycard"]["source_rooms"],
                *lock_rules["always_unlocked_rooms"]["rooms"],
                *always_locked.get("rooms", [])]:
        if rid not in by_id:
            errors.append(f"locks references unknown room {rid}")
    both = (set(lock_rules["always_unlocked_rooms"]["rooms"]) & set(always_locked.get("rooms", [])))
    if both:
        errors.append(f"locks: rooms in both always_unlocked_rooms and always_locked_rooms: {both}")
    if always_locked:
        ssc = always_locked.get("side_search_cost", {})
        extra_keys = ssc.get("extra_keys", [])
        weights = ssc.get("weights", [])
        if not extra_keys or len(extra_keys) != len(weights):
            errors.append("locks always_locked_rooms.side_search_cost: "
                          "extra_keys/weights missing or length mismatch")
        if any(k < 0 for k in extra_keys):
            errors.append("locks always_locked_rooms.side_search_cost: negative extra_keys value")
        if any(w < 0 for w in weights):
            errors.append("locks always_locked_rooms.side_search_cost: negative weight")

    # required special rooms exist
    for required in ("entrance_hall", "antechamber", "closet"):
        if required not in by_id:
            errors.append(f"required room missing: {required}")

    # ── special_items.json ─────────────────────────────────────────────────
    si_doc = json.loads((DATA / "special_items.json").read_text())
    si_items = si_doc.get("items", [])
    si_ids = [item["id"] for item in si_items]
    if len(si_ids) != len(set(si_ids)):
        dupes = {i for i in si_ids if si_ids.count(i) > 1}
        errors.append(f"special_items: duplicate ids: {dupes}")
    si_by_id = {item["id"]: item for item in si_items}
    # "die" is a resource token allowed in lost_and_found pool and fabrication
    si_resolvable = set(si_by_id) | {"die"}

    # (where, area id) pairs from meta.absent_spawn_areas, checked against the area
    # graph further down — areas.json is not loaded until the areas section below.
    absent_area_refs: list[tuple[str, str]] = []

    for item in si_items:
        where = f"special_items/{item['id']}"
        if item.get("kind") not in VALID_ITEM_KINDS:
            errors.append(f"{where}: invalid kind {item.get('kind')!r}")
        if item.get("persistence") not in VALID_ITEM_PERSISTENCE:
            errors.append(f"{where}: invalid persistence {item.get('persistence')!r}")
        conf = item.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: invalid confidence {conf!r}")
        tier = item.get("tier")
        if tier is not None and (not isinstance(tier, int) or tier < 1 or tier > 5):
            errors.append(f"{where}: tier must be 1-5 or null, got {tier!r}")
        receive = item.get("receive", True)
        if not isinstance(receive, bool):
            errors.append(f"{where}: receive must be a bool, got {receive!r}")
        elif not receive and tier is None:
            errors.append(
                f"{where}: receive=false requires a tier — a give-only item with "
                f"no tier is unreachable by the trade graph and therefore meaningless"
            )
        for rid in item.get("spawn_rooms", []):
            if rid not in by_id:
                errors.append(f"{where}: spawn_rooms references unknown room {rid!r}")
        for rid in item.get("spawn_rooms_high_luck", []):
            if rid not in by_id:
                errors.append(f"{where}: spawn_rooms_high_luck references unknown room {rid!r}")
        for rid in item.get("guaranteed_in", []):
            if rid not in by_id:
                errors.append(f"{where}: guaranteed_in references unknown room {rid!r}")
        req_item = item.get("requires_item")
        if req_item is not None:
            if req_item not in si_by_id:
                errors.append(f"{where}: requires_item {req_item!r} not in special_items")
            elif req_item == item["id"]:
                errors.append(f"{where}: requires_item cannot reference itself")
        # absent_spawn_areas names OFF-GRID areas an item comes from — places the
        # sim models as area-graph nodes rather than draftable rooms.  Both
        # directions are errors: a room id here belongs in spawn_rooms, and an id
        # that is neither a room nor an area node is simply a typo.
        for aid in item.get("meta", {}).get("absent_spawn_areas", []):
            if aid in by_id:
                errors.append(
                    f"{where}: absent_spawn_areas {aid!r} is a room in rooms.json "
                    f"— move it to spawn_rooms"
                )
            else:
                absent_area_refs.append((where, aid))
        wont = item.get("meta", {}).get("wont_implement")
        if wont is not None and item.get("implemented", True):
            errors.append(
                f"{where}: meta.wont_implement is only meaningful while "
                "implemented=false"
            )
        if not item.get("implemented", True):
            # wont_implement records a DECISION never to build this, so it stands in
            # for blocked_on: there is no blocker to name, only a reason to decline.
            if not (item.get("meta", {}).get("blocked_on") or wont):
                errors.append(
                    f"{where}: implemented=false requires meta.blocked_on "
                    "or meta.wont_implement"
                )
            if wont and item.get("meta", {}).get("blocked_on"):
                errors.append(
                    f"{where}: meta.wont_implement and meta.blocked_on are "
                    "mutually exclusive -- a decision not to build is not a blocker"
                )
            if wont is not None and not str(wont).strip():
                errors.append(f"{where}: meta.wont_implement must state the reason")
            reachability = item.get("meta", {}).get("reachability")
            if reachability not in VALID_ITEM_REACHABILITY:
                errors.append(
                    f"{where}: implemented=false requires meta.reachability to be "
                    f"one of {sorted(VALID_ITEM_REACHABILITY)}, got {reachability!r}"
                )
        for eff in item.get("effects", []):
            tag = eff.get("tag")
            if tag not in KNOWN_ITEM_EFFECT_TAGS:
                warnings.append(f"{where}: unknown effect tag {tag!r}")

    # lost_and_found pool — ids must resolve (die allowed)
    for pool_id in si_doc.get("lost_and_found", {}).get("pool", []):
        if pool_id not in si_resolvable:
            errors.append(f"special_items lost_and_found pool: unknown id {pool_id!r}")

    # fabrication — inputs and output must be item ids
    for recipe in si_doc.get("fabrication", []):
        for iid in recipe.get("inputs", []):
            if iid not in si_by_id:
                errors.append(f"special_items fabrication: unknown input id {iid!r}")
        oid = recipe.get("output")
        if oid not in si_by_id:
            errors.append(f"special_items fabrication: unknown output id {oid!r}")

    # dig tables — weights sum to 100 ± 0.5; item ids resolve
    for table_name, table in si_doc.get("dig", {}).get("tables", {}).items():
        total = sum(row["weight"] for row in table)
        if abs(total - 100.0) > 0.5:
            errors.append(f"special_items dig/{table_name}: weights sum to {total:.4f}, expected ~100")
        for row in table:
            if row.get("kind") not in VALID_DIG_OUTCOME_KINDS:
                errors.append(
                    f"special_items dig/{table_name}: unknown outcome kind {row.get('kind')!r}"
                )
            if row.get("kind") == "item":
                rid = row.get("id")
                if rid not in si_by_id:
                    errors.append(
                        f"special_items dig/{table_name}: item outcome references unknown id {rid!r}"
                    )

    # rooms.json items.dig_guaranteed — deferred from the room loop above,
    # same pattern as absent_area_refs (special_items.json loads after rooms).
    for where, dig_guaranteed in dig_guaranteed_refs:
        if dig_guaranteed not in si_by_id:
            errors.append(
                f"{where}: items.dig_guaranteed references unknown special item {dig_guaranteed!r}"
            )

    # Valid grant kinds inside a loot entry's grants list. The four
    # mechanarium_* kinds dispatch to Mechanarium compartment resolvers
    # (engine/special_items.py) rather than a plain grant.
    VALID_GRANT_KINDS = {
        "coins", "keys", "gems", "dice", "item", "keycard", "food",
        "mechanarium_lever", "mechanarium_key_chain", "mechanarium_upgrade_chain",
        "mechanarium_sanctum_chain",
    }

    # containers section
    containers_doc = si_doc.get("containers", {})
    containers_kinds = containers_doc.get("kinds", {})
    for kind_name, kind_cfg in containers_kinds.items():
        where = f"special_items/containers/kinds/{kind_name}"
        loot = kind_cfg.get("loot", [])
        if loot:
            total_w = sum(entry.get("weight", 0) for entry in loot)
            # Weights can use any consistent scale (normalised at runtime); just
            # require positive total and no negative entries.
            if total_w <= 0:
                errors.append(f"{where}: loot weights sum to {total_w:.4f}, must be > 0")
            for entry in loot:
                if entry.get("weight", 0) < 0:
                    errors.append(f"{where}: loot entry has negative weight")
            for entry in loot:
                # New schema: grants list
                grants = entry.get("grants")
                if grants is not None:
                    for g in grants:
                        gkind = g.get("kind")
                        if gkind not in VALID_GRANT_KINDS:
                            errors.append(f"{where}: grant kind {gkind!r} not in {sorted(VALID_GRANT_KINDS)}")
                        if gkind == "item":
                            iid = g.get("id")
                            if iid not in si_by_id:
                                errors.append(f"{where}: grant item id {iid!r} not in special_items")
                else:
                    # Legacy single-grant top-level kind
                    if entry.get("kind") == "item":
                        iid = entry.get("id")
                        if iid not in si_by_id:
                            errors.append(f"{where}: loot item id {iid!r} not in special_items")
        for opener in kind_cfg.get("opener", []):
            if opener not in ("smash", "key", "key_only"):
                errors.append(f"{where}: unknown opener {opener!r}")
    containers_rooms = containers_doc.get("rooms", {})
    for room_id, kinds in containers_rooms.items():
        if room_id not in by_id:
            errors.append(f"special_items/containers/rooms: unknown room id {room_id!r}")
        for kind_name in kinds:
            if kind_name not in containers_kinds:
                errors.append(
                    f"special_items/containers/rooms/{room_id}: unknown kind {kind_name!r}"
                )
    garage_car = containers_doc.get("garage_car", {})
    for entry in garage_car.get("first_loot", []):
        if entry.get("kind") == "item":
            iid = entry.get("id")
            if iid not in si_by_id:
                errors.append(
                    f"special_items/containers/garage_car first_loot: unknown item {iid!r}"
                )
    for iid in garage_car.get("later_pool", []):
        if iid not in si_by_id and iid != "keycard":
            errors.append(
                f"special_items/containers/garage_car later_pool: unknown item {iid!r}"
            )

    # vault_boxes: room exists, key ids exist as items, grant ids exist
    vault_boxes = containers_doc.get("vault_boxes", {})
    if vault_boxes:
        vb_room = vault_boxes.get("room", "")
        if vb_room not in by_id:
            errors.append(f"special_items/containers/vault_boxes: room {vb_room!r} not in rooms.json")
        for key_id, box_data in vault_boxes.get("boxes", {}).items():
            where = f"special_items/containers/vault_boxes/boxes/{key_id}"
            if key_id not in si_by_id:
                errors.append(f"{where}: key id {key_id!r} not in special_items")
            for grant_id in box_data.get("grants", []):
                if grant_id not in si_resolvable:
                    errors.append(f"{where}: grant id {grant_id!r} not in special_items")

    # mail_packages: the Mail Room's slot1/slot2/slot3 package tables.
    mail_packages = si_doc.get("mail_packages", {})
    mail_food_dishes = items_doc.get("food", {}).get("dishes", {})

    def _check_mail_grant(where: str, g: dict) -> None:
        gkind = g.get("kind")
        if gkind not in VALID_GRANT_KINDS:
            errors.append(f"{where}: grant kind {gkind!r} not in {sorted(VALID_GRANT_KINDS)}")
            return
        if gkind == "item" and g.get("id") not in si_by_id:
            errors.append(f"{where}: grant item id {g.get('id')!r} not in special_items")
        elif gkind == "food" and g.get("id") not in mail_food_dishes:
            errors.append(f"{where}: grant food id {g.get('id')!r} not in items.json food.dishes")

    def _check_mail_chain(where: str, chain: list) -> None:
        # Every chain must end on a non-item entry: a special item can be
        # unavailable (already held, gated out) but a resource/food grant
        # cannot, so a chain that did not end this way could fail to resolve.
        if not chain:
            errors.append(f"{where}: empty chain")
            return
        for g in chain:
            _check_mail_grant(where, g)
        if chain[-1].get("kind") == "item":
            errors.append(f"{where}: chain's last entry must be a non-item unconditional fallback")

    for i, chain in enumerate(mail_packages.get("slot1", {}).get("chains", [])):
        _check_mail_chain(f"special_items/mail_packages/slot1/chains[{i}]", chain)

    mail_slot2 = mail_packages.get("slot2", {})
    shortcut_pct = mail_slot2.get("gems_shortcut_chance_pct")
    if not isinstance(shortcut_pct, (int, float)) or not 0 <= shortcut_pct <= 100:
        errors.append(
            f"special_items/mail_packages/slot2: gems_shortcut_chance_pct {shortcut_pct!r} "
            f"out of range 0-100"
        )
    _check_mail_grant("special_items/mail_packages/slot2/gems_shortcut_grant",
                       mail_slot2.get("gems_shortcut_grant", {}))
    slot2_outcomes = {"gems"}  # the flat gems-shortcut always resolves to this outcome key
    for i, chain in enumerate(mail_slot2.get("chains", [])):
        _check_mail_chain(f"special_items/mail_packages/slot2/chains[{i}]", chain)
        for g in chain:
            slot2_outcomes.add(g["id"] if g.get("kind") == "item" else g.get("kind"))

    slot3_outcomes = mail_packages.get("slot3", {}).get("outcomes", {})
    if "default" not in slot3_outcomes:
        errors.append("special_items/mail_packages/slot3/outcomes: missing required 'default' entry")
    for outcome_id in slot2_outcomes:
        if outcome_id not in slot3_outcomes and "default" not in slot3_outcomes:
            errors.append(
                f"special_items/mail_packages/slot3/outcomes: no coverage for "
                f"slot2 outcome {outcome_id!r}"
            )
    for outcome_name, outcome_cfg in slot3_outcomes.items():
        where = f"special_items/mail_packages/slot3/outcomes/{outcome_name}"
        table = outcome_cfg.get("table", [])
        if not table:
            errors.append(f"{where}: empty table")
        total_w = sum(row.get("weight", 0) for row in table)
        if total_w <= 0:
            errors.append(f"{where}: table weights sum to {total_w}, must be > 0")
        for row in table:
            if row.get("weight", 0) < 0:
                errors.append(f"{where}: negative weight in table")
            if row.get("result") not in ("gems", "keys", "none"):
                errors.append(f"{where}: unknown result {row.get('result')!r}")

    # freight_packages: Freight Shipping's (mail_room__ix91) special-item pool,
    # drop-one-of-two rule, and resource top-up table.
    freight = si_doc.get("freight_packages", {})
    if freight:
        where = "special_items/freight_packages"
        f_pool = freight.get("special_item_pool", [])
        for iid in f_pool:
            if iid not in si_by_id:
                errors.append(f"{where}/special_item_pool: unknown item id {iid!r}")
        f_drop = freight.get("drop_one_pair", [])
        if len(f_drop) != 2:
            errors.append(f"{where}/drop_one_pair: must have exactly 2 entries, got {len(f_drop)}")
        for iid in f_drop:
            if iid not in f_pool:
                errors.append(f"{where}/drop_one_pair: {iid!r} not in special_item_pool")
        specials_target = freight.get("specials_target")
        package_size = freight.get("package_size")
        keys_top_up_cap = freight.get("keys_top_up_cap")
        if not isinstance(specials_target, int) or specials_target <= 0:
            errors.append(f"{where}: specials_target {specials_target!r} must be a positive int")
        if not isinstance(package_size, int) or package_size <= 0:
            errors.append(f"{where}: package_size {package_size!r} must be a positive int")
        if not isinstance(keys_top_up_cap, int) or keys_top_up_cap < 0:
            errors.append(
                f"{where}: keys_top_up_cap {keys_top_up_cap!r} must be a non-negative int"
            )
        configs = freight.get("resource_configs", [])
        if not configs:
            errors.append(f"{where}/resource_configs: must be non-empty")
        base_resource_count = (
            (package_size - specials_target)
            if isinstance(package_size, int) and isinstance(specials_target, int)
            else None
        )
        for i, cfg_row in enumerate(configs):
            row_where = f"{where}/resource_configs[{i}]"
            keys, gems = cfg_row.get("keys"), cfg_row.get("gems")
            if not isinstance(keys, int) or keys < 0:
                errors.append(f"{row_where}: keys {keys!r} must be a non-negative int")
            if not isinstance(gems, int) or gems < 0:
                errors.append(f"{row_where}: gems {gems!r} must be a non-negative int")
            if cfg_row.get("weight", 0) <= 0:
                errors.append(f"{row_where}: weight {cfg_row.get('weight')!r} must be > 0")
            if (base_resource_count is not None and isinstance(keys, int) and isinstance(gems, int)
                    and keys + gems != base_resource_count):
                errors.append(
                    f"{row_where}: keys+gems={keys + gems} != "
                    f"package_size-specials_target={base_resource_count}"
                )

    # planetarium_planets: the Telescope's Planetarium-upgrade table. Exactly
    # five planets, Mora the sole forced_last entry and pinned last in the
    # list, every payload id resolvable. An unvalidated section fails open,
    # so this block is required, not optional.
    planetarium_planets = si_doc.get("planetarium_planets", {}).get("planets", [])
    where = "special_items/planetarium_planets"
    if len(planetarium_planets) != 5:
        errors.append(f"{where}: expected exactly 5 planets, got {len(planetarium_planets)}")
    forced_last_ids = [p.get("id") for p in planetarium_planets if p.get("forced_last")]
    if forced_last_ids != ["mora"]:
        errors.append(
            f"{where}: exactly one planet (mora) must carry forced_last: true, "
            f"got {forced_last_ids!r}"
        )
    if planetarium_planets and planetarium_planets[-1].get("id") != "mora":
        errors.append(f"{where}: mora must be the last entry in the list")
    containers_kinds_for_planets = containers_doc.get("kinds", {})
    for p in planetarium_planets:
        pwhere = f"{where}/{p.get('id')}"
        payload = p.get("payload", {})
        pkind = payload.get("kind")
        if pkind == "item":
            iid = payload.get("id")
            if iid not in si_by_id:
                errors.append(f"{pwhere}: payload item id {iid!r} not in special_items")
        elif pkind == "food":
            fid = payload.get("id")
            if fid not in mail_food_dishes:
                errors.append(f"{pwhere}: payload food id {fid!r} not in items.json food.dishes")
        elif pkind == "container":
            ckind = payload.get("container_kind")
            if ckind not in containers_kinds_for_planets:
                errors.append(
                    f"{pwhere}: payload container_kind {ckind!r} not in "
                    f"special_items/containers/kinds"
                )
        elif pkind in ("dice", "dig_bonus"):
            pass  # amount only, nothing to resolve
        else:
            errors.append(f"{pwhere}: unknown payload kind {pkind!r}")

    # ignition section: tools and targets exist. A target is either a rooms.json
    # room id (default) or, when marked "area": true, an areas.json node id
    # (e.g. mine_south, which has no rooms.json record) -- checked against
    # a_node_id_set once areas.json is loaded further down, same deferred
    # pattern as absent_area_refs above.
    ignition_doc = si_doc.get("ignition", {})
    ignition_area_refs: list[tuple[str, str]] = []
    for tool_id in ignition_doc.get("tools", []):
        if tool_id not in si_by_id:
            errors.append(f"special_items/ignition/tools: unknown item id {tool_id!r}")
    for target_id, target_cfg in ignition_doc.get("targets", {}).items():
        where = f"special_items/ignition/targets/{target_id}"
        if target_cfg.get("area"):
            ignition_area_refs.append((where, target_id))
        elif target_id not in by_id:
            errors.append(f"{where}: target room {target_id!r} not in rooms.json")
        req = target_cfg.get("requires_item")
        if req is not None and req not in si_by_id:
            errors.append(f"{where}: requires_item {req!r} not in special_items")
        reqs = target_cfg.get("requires_items")
        if reqs is not None:
            if req is not None:
                errors.append(f"{where}: requires_item and requires_items are mutually exclusive")
            if not isinstance(reqs, dict) or not reqs:
                errors.append(f"{where}: requires_items must be a non-empty object")
            else:
                for item_id, count in reqs.items():
                    if item_id not in si_by_id:
                        errors.append(f"{where}: requires_items {item_id!r} not in special_items")
                    if not isinstance(count, int) or count < 1:
                        errors.append(
                            f"{where}: requires_items[{item_id!r}]={count!r} must be a positive int"
                        )
        for reward in target_cfg.get("grants", []):
            if reward.get("kind") == "item":
                iid = reward.get("id")
                if iid not in si_by_id:
                    errors.append(f"{where}: grant item {iid!r} not in special_items")
    for absent_id in ignition_doc.get("meta", {}).get("absent_targets", []):
        if absent_id in by_id:
            errors.append(
                f"special_items/ignition/meta.absent_targets: {absent_id!r} exists in rooms.json — move to targets"
            )

    # machines section: item and rooms exist
    machines_doc = si_doc.get("machines", {})
    for machine_id, machine_cfg in machines_doc.items():
        if machine_id == "meta":
            continue
        where = f"special_items/machines/{machine_id}"
        if machine_id not in by_id:
            errors.append(f"{where}: machine room {machine_id!r} not in rooms.json")
        item_id = machine_cfg.get("item")
        if item_id is not None and item_id not in si_by_id:
            errors.append(f"{where}: item {item_id!r} not in special_items")
        for reward in machine_cfg.get("grants", []):
            if reward.get("kind") == "item":
                iid = reward.get("id")
                if iid not in si_by_id:
                    errors.append(f"{where}: grant item {iid!r} not in special_items")

    # ── experiments.json (Laboratory/Experiments; see engine/experiments.py) ─────
    VALID_EXPERIMENT_POOLS = {"base", "packet"}
    experiments_doc = json.loads((DATA / "experiments.json").read_text())
    ex_triggers = experiments_doc.get("triggers", [])
    ex_effects = experiments_doc.get("effects", [])
    ex_trigger_ids = {t["id"] for t in ex_triggers}
    ex_effect_ids = {e["id"] for e in ex_effects}

    ex_all_ids = [r["id"] for r in ex_triggers] + [r["id"] for r in ex_effects]
    if len(ex_all_ids) != len(set(ex_all_ids)):
        dupes = {i for i in ex_all_ids if ex_all_ids.count(i) > 1}
        errors.append(f"experiments: duplicate ids: {dupes}")

    n_base_triggers = sum(1 for t in ex_triggers if t.get("pool") == "base")
    n_packet_triggers = sum(1 for t in ex_triggers if t.get("pool") == "packet")
    n_base_effects = sum(1 for e in ex_effects if e.get("pool") == "base")
    n_packet_effects = sum(1 for e in ex_effects if e.get("pool") == "packet")
    if n_base_triggers != 12:
        errors.append(f"experiments: base triggers must be exactly 12, got {n_base_triggers}")
    if n_packet_triggers != 8:
        errors.append(f"experiments: packet triggers must be exactly 8, got {n_packet_triggers}")
    if n_base_effects != 12:
        errors.append(f"experiments: base effects must be exactly 12, got {n_base_effects}")
    if n_packet_effects != 8:
        errors.append(f"experiments: packet effects must be exactly 8, got {n_packet_effects}")

    def _check_experiment_record(kind: str, rec: dict) -> None:
        """Validate one trigger or effect record: pool, cap, availability, id refs."""
        where = f"experiments/{kind}/{rec.get('id')}"
        if rec.get("pool") not in VALID_EXPERIMENT_POOLS:
            errors.append(f"{where}: invalid pool {rec.get('pool')!r}")
        if not rec.get("implemented", False):
            if not rec.get("meta", {}).get("blocked_on"):
                errors.append(f"{where}: implemented=false requires meta.blocked_on")
        conf = rec.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: invalid confidence {conf!r}")
        cap = rec.get("cap")
        if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0):
            errors.append(f"{where}: cap must be a positive int or null, got {cap!r}")
        for rid in rec.get("rooms", []):
            if rid not in by_id:
                errors.append(f"{where}: rooms references unknown room {rid!r}")
        av = rec.get("availability")
        if av is not None:
            if "room_id" in av and av["room_id"] not in by_id:
                errors.append(
                    f"{where}: availability.room_id {av['room_id']!r} not in rooms.json"
                )
            if "item_id" in av and av["item_id"] not in si_by_id:
                errors.append(
                    f"{where}: availability.item_id {av['item_id']!r} not in special_items"
                )
            if "excludes_trigger_id" in av and av["excludes_trigger_id"] not in ex_trigger_ids:
                errors.append(
                    f"{where}: availability.excludes_trigger_id "
                    f"{av['excludes_trigger_id']!r} not a known trigger id"
                )
            if "removes_effect_id" in av and av["removes_effect_id"] not in ex_effect_ids:
                errors.append(
                    f"{where}: availability.removes_effect_id "
                    f"{av['removes_effect_id']!r} not a known effect id"
                )
            pct = av.get("chance_pct")
            if pct is not None and (not isinstance(pct, (int, float)) or not 0 <= pct <= 100):
                errors.append(f"{where}: availability.chance_pct out of range 0-100: {pct!r}")
        magnitude = rec.get("magnitude") or {}
        pct_list = magnitude.get("priority_draw_chance_pct")
        if pct_list is not None:
            for p in pct_list:
                if not isinstance(p, (int, float)) or not 0 <= p <= 100:
                    errors.append(
                        f"{where}: magnitude.priority_draw_chance_pct out of range: {p!r}"
                    )

    for t in ex_triggers:
        _check_experiment_record("triggers", t)
    for e in ex_effects:
        _check_experiment_record("effects", e)

    # ── shops.json ─────────────────────────────────────────────────────────────
    VALID_STOCK_KINDS = {"resource", "item", "container"}
    VALID_GRANT_KEYS = {"coins", "keys", "gems", "food", "dice"}

    shops_doc = json.loads((DATA / "shops.json").read_text())

    # trading block sanity
    trading = shops_doc.get("trading", {})
    tpd = trading.get("trades_per_day")
    if tpd is None or not isinstance(tpd, int) or tpd < 0:
        errors.append(f"shops trading.trades_per_day must be a non-negative int, got {tpd!r}")
    for knob in ("dice_chance", "t5_special_chance"):
        val = trading.get(knob)
        if val is None or not isinstance(val, int) or not 0 <= val <= 100:
            errors.append(f"shops trading.{knob} must be 0-100 int, got {val!r}")

    shops = shops_doc.get("shops", {})

    # sale block sanity: days must be positive ints, shops must be scoped to
    # known shop ids. An unvalidated typo here fails open (sale.get("shops", [])
    # silently means "no sale anywhere"), so this must catch it.
    sale = shops_doc.get("sale", {})
    sale_days = sale.get("days", [])
    if not isinstance(sale_days, list) or not all(
        isinstance(d, int) and d > 0 for d in sale_days
    ):
        errors.append(f"shops sale.days must be a list of positive ints, got {sale_days!r}")
    sale_shops = sale.get("shops", [])
    if not isinstance(sale_shops, list):
        errors.append(f"shops sale.shops must be a list, got {sale_shops!r}")
    else:
        for sid in sale_shops:
            if sid not in shops:
                errors.append(f"shops sale.shops: {sid!r} is not a known shop id in shops.json")
    for shop_id, shop in shops.items():
        where = f"shops/{shop_id}"
        if shop_id not in by_id:
            errors.append(f"{where}: shop key is not a known room id")

        stock = shop.get("stock", [])
        seen_stock_ids: list[str] = []
        for entry in stock:
            eid = entry.get("id")
            ekind = entry.get("kind")
            eprice = entry.get("price")

            if eid is None:
                errors.append(f"{where} stock: entry missing 'id'")
            if ekind not in VALID_STOCK_KINDS:
                errors.append(f"{where} stock/{eid}: kind must be resource/item/container, got {ekind!r}")
            if eprice is None or not isinstance(eprice, int) or eprice < 0:
                errors.append(f"{where} stock/{eid}: price must be a non-negative int, got {eprice!r}")

            if ekind == "item":
                if eid not in si_by_id:
                    errors.append(f"{where} stock/{eid}: kind=item id not in special_items.json")
            elif ekind == "resource":
                grant = entry.get("grant")
                if not isinstance(grant, dict) or not grant:
                    errors.append(f"{where} stock/{eid}: kind=resource must have a non-empty 'grant' dict")
                else:
                    for gkey, gval in grant.items():
                        if gkey not in VALID_GRANT_KEYS:
                            errors.append(
                                f"{where} stock/{eid}: grant key {gkey!r} not in "
                                f"{sorted(VALID_GRANT_KEYS)}"
                            )
                        if not isinstance(gval, int) or gval <= 0:
                            errors.append(
                                f"{where} stock/{eid}: grant[{gkey!r}] must be a positive int, got {gval!r}"
                            )
            elif ekind == "container":
                gi = entry.get("grants_item")
                if gi is None or gi not in si_by_id:
                    errors.append(
                        f"{where} stock/{eid}: kind=container grants_item {gi!r} not in special_items.json"
                    )
                ri = entry.get("requires_item")
                if ri is not None and ri not in si_by_id:
                    errors.append(
                        f"{where} stock/{eid}: kind=container requires_item {ri!r} not in special_items.json"
                    )

            limit = entry.get("limit")
            if limit is not None and (not isinstance(limit, int) or limit <= 0):
                errors.append(f"{where} stock/{eid}: limit must be a positive int, got {limit!r}")

            if eid is not None:
                if eid in seen_stock_ids:
                    errors.append(f"{where}: duplicate stock id {eid!r}")
                else:
                    seen_stock_ids.append(eid)

        # kitchen special_roll block
        special_roll = shop.get("special_roll")
        if special_roll is not None:
            sr_total = sum(s.get("chance", 0) for s in special_roll)
            if sr_total != 100:
                errors.append(
                    f"{where} special_roll: chances sum to {sr_total}, expected 100"
                )
            for sr in special_roll:
                sr_id = sr.get("id")
                sr_kind = sr.get("kind")
                sr_price = sr.get("price")
                if sr_id is None:
                    errors.append(f"{where} special_roll entry missing 'id'")
                if sr_kind not in VALID_STOCK_KINDS:
                    errors.append(
                        f"{where} special_roll/{sr_id}: kind must be resource/item/container, got {sr_kind!r}"
                    )
                if sr_price is None or not isinstance(sr_price, int) or sr_price < 0:
                    errors.append(
                        f"{where} special_roll/{sr_id}: price must be a non-negative int, got {sr_price!r}"
                    )
                if sr_kind == "resource":
                    grant = sr.get("grant")
                    if not isinstance(grant, dict) or not grant:
                        errors.append(
                            f"{where} special_roll/{sr_id}: kind=resource must have a non-empty 'grant' dict"
                        )

        # locksmith special_key block
        special_key = shop.get("special_key")
        if special_key is not None:
            sk_price = special_key.get("price")
            if sk_price is None or not isinstance(sk_price, int) or sk_price < 0:
                errors.append(f"{where} special_key: price must be a non-negative int, got {sk_price!r}")
            rolls = special_key.get("rolls", [])
            total_chance = sum(r.get("chance", 0) for r in rolls)
            if total_chance != 100:
                errors.append(f"{where} special_key rolls: chances sum to {total_chance}, expected 100")
            for roll in rolls:
                for kid in roll.get("order", []):
                    if kid not in si_by_id:
                        errors.append(
                            f"{where} special_key roll order: {kid!r} not in special_items.json"
                        )
            fallback = special_key.get("fallback", [])
            if not isinstance(fallback, list):
                errors.append(f"{where} special_key fallback: expected a list")
            else:
                for fid in fallback:
                    if fid not in si_by_id:
                        errors.append(
                            f"{where} special_key fallback: {fid!r} not in special_items.json"
                        )

        # showroom tier arrays
        for tier_field in ("tier_a", "tier_b"):
            tier_entries = shop.get(tier_field, [])
            for te in tier_entries:
                tid = te.get("id")
                if tid not in si_by_id:
                    errors.append(f"{where} {tier_field}: id {tid!r} not in special_items.json")
                tprice = te.get("price")
                if tprice is None or not isinstance(tprice, int) or tprice < 0:
                    errors.append(
                        f"{where} {tier_field}/{tid}: price must be a non-negative int, got {tprice!r}"
                    )
        trophy = shop.get("trophy")
        if trophy is not None:
            troph_id = trophy.get("id")
            if troph_id not in si_by_id:
                errors.append(f"{where} trophy: id {troph_id!r} not in special_items.json")
            troph_price = trophy.get("price")
            if troph_price is None or not isinstance(troph_price, int) or troph_price < 0:
                errors.append(
                    f"{where} trophy/{troph_id}: price must be a non-negative int, got {troph_price!r}"
                )

    # ── shrine.json (Shrine blessings/curse; see engine/effects/rooms/shrine.py) ─
    shrine_doc = json.loads((DATA / "shrine.json").read_text())
    sh_bands = shrine_doc.get("bands", [])
    sh_blessings = shrine_doc.get("blessings", [])
    if len(sh_bands) != 5:
        errors.append(f"shrine: bands must be exactly 5, got {len(sh_bands)}")
    if len(sh_blessings) != 8:
        errors.append(f"shrine: blessings must be exactly 8, got {len(sh_blessings)}")

    # Bands must tile 1..80 contiguously, ascending duration, no gaps or overlaps.
    prev_max = 0
    for b in sh_bands:
        lo, hi, days = b.get("min_coins"), b.get("max_coins"), b.get("duration_days")
        if lo != prev_max + 1:
            errors.append(f"shrine/bands: band {b!r} does not start at {prev_max + 1}")
        if not isinstance(hi, int) or not isinstance(lo, int) or hi < lo:
            errors.append(f"shrine/bands: invalid coin range in {b!r}")
        if not isinstance(days, int) or days <= 0:
            errors.append(f"shrine/bands: invalid duration_days in {b!r}")
        prev_max = hi if isinstance(hi, int) else prev_max
    if sh_bands and prev_max != 80:
        errors.append(f"shrine/bands: bands must cover up to 80 coins, last ends at {prev_max}")

    sh_ids = [b.get("id") for b in sh_blessings]
    if len(sh_ids) != len(set(sh_ids)):
        dupes = {i for i in sh_ids if sh_ids.count(i) > 1}
        errors.append(f"shrine/blessings: duplicate ids: {dupes}")
    for b in sh_blessings:
        where = f"shrine/blessings/{b.get('id')}"
        costs = b.get("costs", [])
        if len(costs) != len(sh_bands):
            errors.append(f"{where}: costs must have {len(sh_bands)} entries, got {len(costs)}")
        for i, (cost, band) in enumerate(zip(costs, sh_bands)):
            lo, hi = band.get("min_coins"), band.get("max_coins")
            if not isinstance(cost, int) or not (lo <= cost <= hi):
                errors.append(f"{where}: costs[{i}]={cost!r} outside band range {lo}-{hi}")
        if not b.get("implemented", False):
            if not b.get("meta", {}).get("blocked_on"):
                errors.append(f"{where}: implemented=false requires meta.blocked_on")

    sh_curse = shrine_doc.get("curse", {})
    for rid in sh_curse.get("exempt_room_ids", []):
        if rid not in by_id:
            errors.append(f"shrine/curse: exempt_room_ids references unknown room {rid!r}")
    for cat in sh_curse.get("resource_loss_per_category", {}):
        if cat not in VALID_CATEGORIES:
            errors.append(f"shrine/curse: resource_loss_per_category has unknown category {cat!r}")

    # ── constellations.json (night-sky partition; see docs/rl-environment.md) ─
    # A night sky is the unique SET of constellations whose star values sum to
    # the viewing star count, not everything at or below a threshold, so the
    # 0-49 table is a partition table and the sum is the property worth
    # checking. Star count 0 is the one count that does not sum (the North
    # Star is 1 star), and it is asserted positively below so the exception
    # cannot silently widen to a second count.
    con_doc = json.loads((DATA / "constellations.json").read_text(encoding="utf-8"))
    con_recs = con_doc.get("constellations", [])
    con_table = con_doc.get("appearances", {})
    if len(con_recs) != 13:
        errors.append(f"constellations: must be exactly 13 records, got {len(con_recs)}")

    con_ids = [c.get("id") for c in con_recs]
    if len(con_ids) != len(set(con_ids)):
        dupes = sorted({i for i in con_ids if con_ids.count(i) > 1})
        errors.append(f"constellations: duplicate ids: {dupes}")

    # The two published per-day caps (Observatory/Multiple's SpoilerBox). They
    # are separate rules: 8 is how many skies can be viewed, 7 is how many of
    # them can hold constellations, and an eighth sky is viewable-but-empty.
    # Checked here so neither can quietly become a Python constant, and so the
    # ordering that makes the empty eighth sky reachable at all is asserted.
    con_max_skies = con_doc.get("max_skies_per_day")
    con_max_con_skies = con_doc.get("max_constellation_skies_per_day")
    for label, value in (("max_skies_per_day", con_max_skies),
                         ("max_constellation_skies_per_day", con_max_con_skies)):
        if not isinstance(value, int) or value <= 0:
            errors.append(f"constellations/{label}: must be a positive int, got {value!r}")
    if isinstance(con_max_skies, int) and isinstance(con_max_con_skies, int):
        if con_max_con_skies > con_max_skies:
            errors.append(
                f"constellations: max_constellation_skies_per_day "
                f"({con_max_con_skies}) cannot exceed max_skies_per_day "
                f"({con_max_skies}) -- a sky that cannot be viewed cannot hold "
                f"constellations")

    # Record order is the action-block and obs-vector order (env/actions.py's
    # ACTIVATE_CONSTELLATION_BASE), so a reorder would silently repoint every
    # id -- strictly ascending stars pins it to one arrangement.
    con_stars = {}
    prev_stars = 0
    for c in con_recs:
        where = f"constellations/{c.get('id')}"
        stars = c.get("stars")
        if not isinstance(stars, int) or stars <= 0:
            errors.append(f"{where}: stars must be a positive int, got {stars!r}")
            continue
        if stars <= prev_stars:
            errors.append(
                f"{where}: stars must be strictly ascending in record order, "
                f"got {stars} after {prev_stars}"
            )
        prev_stars = stars
        con_stars[c.get("id")] = stars
        if not c.get("name"):
            errors.append(f"{where}: missing name")
        if not c.get("effect_text"):
            errors.append(f"{where}: missing effect_text")
        if not isinstance(c.get("stacks"), bool):
            errors.append(f"{where}: stacks must be a bool, got {c.get('stacks')!r}")
        implemented = c.get("implemented", False)
        if not implemented and not c.get("meta", {}).get("blocked_on"):
            errors.append(f"{where}: implemented=false requires meta.blocked_on")
        if implemented and c.get("meta", {}).get("blocked_on"):
            errors.append(f"{where}: implemented records must not carry meta.blocked_on")
        # An implemented constellation carries EXACTLY ONE payload, and the
        # payload lives here rather than in Python: 'grant' for an immediate
        # resource delta (handed to effects/tier1.py::_grant) or 'effect' for
        # anything else (dispatched by engine/constellations.py::apply_effect).
        # The biconditional is what stops a record being flipped implemented
        # without a payload -- a silent no-op activation -- or carrying a
        # payload nothing ever reads. Both at once would be ambiguous about
        # what one activation does, so it is an error rather than a sum.
        grant = c.get("grant")
        effect = c.get("effect")
        payloads = [k for k, v in (("grant", grant), ("effect", effect)) if v is not None]
        if implemented != (len(payloads) == 1):
            errors.append(
                f"{where}: an implemented record must carry exactly one of 'grant' "
                f"and 'effect', and an unimplemented one neither; got "
                f"implemented={implemented!r} with {payloads or 'neither'}")
        if grant is not None:
            if grant.get("resource") not in TIER1_RESOURCES:
                errors.append(
                    f"{where}/grant: resource must be one of "
                    f"{sorted(TIER1_RESOURCES)}, got {grant.get('resource')!r}")
            if not isinstance(grant.get("amount"), int) or grant.get("amount") <= 0:
                errors.append(
                    f"{where}/grant: amount must be a positive int, got "
                    f"{grant.get('amount')!r}")
        if effect is not None:
            # Each kind is checked against the file that OWNS the thing it
            # names, which is the whole point of keeping the payload in data:
            # a draft_bias whose condition tag no longer has a category_biases
            # entry would activate a bias that can never fire, and a
            # food_step_bonus naming a dish that is not in items.json would
            # silently never apply.
            kind = effect.get("kind")
            match kind:
                case "draft_bias":
                    if effect.get("condition") not in active_condition_tags:
                        errors.append(
                            f"{where}/effect: condition "
                            f"{effect.get('condition')!r} has no priority_draws.json "
                            f"category_biases entry to activate")
                case "entrance_hall_trunks":
                    trunks = effect.get("trunks")
                    if not isinstance(trunks, int) or trunks <= 0:
                        errors.append(
                            f"{where}/effect: trunks must be a positive int, got {trunks!r}")
                case "food_step_bonus":
                    if effect.get("food_id") not in dishes:
                        errors.append(
                            f"{where}/effect: food_id {effect.get('food_id')!r} is not "
                            f"in items.json food.dishes")
                    steps = effect.get("steps")
                    if not isinstance(steps, int) or steps <= 0:
                        errors.append(
                            f"{where}/effect: steps must be a positive int, got {steps!r}")
                case "shop_half_price":
                    # An ALLOWLIST, so an id that no longer names a shop
                    # silently drops that shop out of the sale rather than
                    # erroring at runtime -- exactly the drift this catches.
                    sale_shops = effect.get("shops")
                    if not isinstance(sale_shops, list) or not sale_shops:
                        errors.append(
                            f"{where}/effect: shops must be a non-empty list, got "
                            f"{sale_shops!r}")
                    else:
                        unknown = [s for s in sale_shops if s not in shops]
                        if unknown:
                            errors.append(
                                f"{where}/effect: shops names {unknown}, which have no "
                                f"shops.json entry to put on sale")
                case "green_room_gems":
                    gems = effect.get("gems")
                    if not isinstance(gems, int) or gems <= 0:
                        errors.append(
                            f"{where}/effect: gems must be a positive int, got {gems!r}")
                    # Keyed by ROOT BASE id (engine/upgrades.py::root_base_id),
                    # which is what game.py looks the amount up by: a key
                    # naming a variant would never be hit, and a key naming a
                    # non-Green room could never be reached at all, since the
                    # call site asks only about Green rooms.
                    for room_id, amount in (effect.get("gems_by_room") or {}).items():
                        rec = by_id.get(room_id)
                        if rec is None:
                            errors.append(
                                f"{where}/effect: gems_by_room names unknown room "
                                f"{room_id!r}")
                        elif rec.get("variant_of") is not None:
                            errors.append(
                                f"{where}/effect: gems_by_room key {room_id!r} is a "
                                f"variant of {rec['variant_of']!r}; keys must be root "
                                f"base ids, which is what the amount is looked up by")
                        elif rec.get("category") != "green":
                            errors.append(
                                f"{where}/effect: gems_by_room key {room_id!r} is not a "
                                f"green room, so the lookup can never reach it")
                        if not isinstance(amount, int) or amount <= 0:
                            errors.append(
                                f"{where}/effect: gems_by_room[{room_id!r}] must be a "
                                f"positive int, got {amount!r}")
                case _:
                    errors.append(
                        f"{where}/effect: unknown kind {kind!r}; "
                        f"engine/constellations.py::apply_effect would ignore it")

    # The two constellations outside the 0-49 table. Both are inert: the Ink
    # Well spends stars to redraw and the Spiral grows a word per generated
    # sky, and neither mechanic exists in the engine.
    for special_id in ("ink_well", "spiral_of_stars"):
        rec = next((c for c in con_recs if c.get("id") == special_id), None)
        if rec is None:
            errors.append(f"constellations: missing the {special_id!r} record")
        elif rec.get("implemented", False):
            errors.append(f"constellations/{special_id}: must carry implemented=false")

    expected_counts = {str(n) for n in range(50)}
    if set(con_table) != expected_counts:
        missing = sorted(expected_counts - set(con_table), key=int)
        extra = sorted(set(con_table) - expected_counts)
        errors.append(
            f"constellations/appearances: keys must be exactly '0'..'49'; "
            f"missing {missing}, unexpected {extra}"
        )

    for key in sorted(set(con_table) & expected_counts, key=int):
        count = int(key)
        sky = con_table[key]
        where = f"constellations/appearances/{count}"
        unknown = [i for i in sky if i not in con_stars]
        if unknown:
            errors.append(f"{where}: unknown constellation ids {unknown}")
            continue
        if len(sky) != len(set(sky)):
            repeated = sorted({i for i in sky if sky.count(i) > 1})
            errors.append(f"{where}: constellation repeated within one sky: {repeated}")
            continue
        if count == 0:
            if sky != ["north_star"]:
                errors.append(
                    f"{where}: the 0-star sky is the sole non-summing count and must be "
                    f"exactly ['north_star'], got {sky}"
                )
            continue
        total = sum(con_stars[i] for i in sky)
        if total != count:
            errors.append(
                f"{where}: star values must sum to {count}, got {total} from "
                f"{[(i, con_stars[i]) for i in sky]}"
            )

    # Every constellation inside the table's range appears alone at its own
    # star count -- the wiki's "each constellation always appears by itself
    # once", and the base case the whole partition is built out of.
    for cid, stars in con_stars.items():
        if stars > 49:
            continue
        sky = con_table.get(str(stars))
        if sky is not None and sky != [cid]:
            errors.append(
                f"constellations/appearances/{stars}: {cid} has {stars} stars so this "
                f"count must be exactly [{cid!r}], got {sky}"
            )

    # ── Upgrade Disk terminals ────────────────────────────────────────────────
    # The rooms whose terminal accepts an Upgrade Disk (docs/upgrade-disks-design.md).
    # Blackbridge Grotto is a fifth in the real game but has no record yet.
    # Mirrored in tools/ingest_sheet.py's DISK_READER_IDS; this check is what
    # catches the two drifting apart, or the flag being dropped from a record.
    DISK_READER_ROOMS = {"security", "laboratory", "office", "shelter"}
    actual_readers = {r["id"] for r in rooms if r.get("flags", {}).get("disk_reader")}
    if actual_readers != DISK_READER_ROOMS:
        missing = DISK_READER_ROOMS - actual_readers
        extra = actual_readers - DISK_READER_ROOMS
        errors.append(
            f"disk_reader flag mismatch: missing {sorted(missing)}, unexpected {sorted(extra)}"
        )

    # ── unlocks_catacombs flag ────────────────────────────────────────────────
    # Only the Tomb carries this flag; it must be a boolean when present.
    # Mirrored in tools/ingest_sheet.py's UNLOCKS_CATACOMBS_IDS.
    UNLOCKS_CATACOMBS_ROOMS = {"tomb"}
    actual_unlockers = {r["id"] for r in rooms if r.get("flags", {}).get("unlocks_catacombs")}
    if actual_unlockers != UNLOCKS_CATACOMBS_ROOMS:
        missing = UNLOCKS_CATACOMBS_ROOMS - actual_unlockers
        extra = actual_unlockers - UNLOCKS_CATACOMBS_ROOMS
        errors.append(
            f"unlocks_catacombs flag mismatch: missing {sorted(missing)}, unexpected {sorted(extra)}"
        )
    for r in rooms:
        val = r.get("flags", {}).get("unlocks_catacombs")
        if val is not None and not isinstance(val, bool):
            errors.append(f"room {r['id']!r}: flags.unlocks_catacombs must be bool, got {val!r}")

    # ── has_animal / has_fireplace flags ──────────────────────────────────────
    # Cloister of Dauja/Veia (effects/rooms/cloister.py) key off these ad-hoc
    # wiki enumerations, carried as flags.has_animal/flags.has_fireplace rather
    # than a Python literal so the lists stay data and editable. This check is
    # what catches the two drifting apart, or a flag being dropped from a record.
    HAS_ANIMAL_ROOMS = {"rumpus_room", "aquarium", "aquarium__experiment",
                        "nursery", "bunk_room",
                        "dovecote", "the_kennel"}
    actual_animal = {r["id"] for r in rooms if r.get("flags", {}).get("has_animal")}
    if actual_animal != HAS_ANIMAL_ROOMS:
        missing = HAS_ANIMAL_ROOMS - actual_animal
        extra = actual_animal - HAS_ANIMAL_ROOMS
        errors.append(
            f"has_animal flag mismatch: missing {sorted(missing)}, unexpected {sorted(extra)}"
        )
    # The Dining Room's fireplace is cell-conditional (centre columns or Rank 9
    # only; windows on the wings or Rank 1), decided in effects/rooms/cloister.py
    # against the drafted cell -- it deliberately carries no static flag.
    HAS_FIREPLACE_ROOMS = {"parlor", "den", "trophy_room", "drawing_room",
                           "furnace", "the_armory"}
    actual_fireplace = {r["id"] for r in rooms if r.get("flags", {}).get("has_fireplace")}
    if actual_fireplace != HAS_FIREPLACE_ROOMS:
        missing = HAS_FIREPLACE_ROOMS - actual_fireplace
        extra = actual_fireplace - HAS_FIREPLACE_ROOMS
        errors.append(
            f"has_fireplace flag mismatch: missing {sorted(missing)}, unexpected {sorted(extra)}"
        )

    # ── no_locker_keys flag ───────────────────────────────────────────────────
    # effects/rooms/locker_room.py's key spread excludes these 18 rooms, an
    # exact wiki enumeration, from ever receiving a spread key. Carried as
    # flags.no_locker_keys per room (not a Python list in the engine) so the
    # set stays data and editable; this check is what catches the two
    # drifting apart, or a flag being dropped from a record.
    NO_LOCKER_KEYS_ROOMS = {"antechamber", "room_46", "the_foundation", "spare_room",
                            "gift_shop", "passageway", "dovecote", "the_armory",
                            "rotunda", "darkroom", "pump_room", "vestibule",
                            "mechanarium", "maids_chamber", "lavatory", "furnace",
                            "freezer", "bookshop"}
    actual_no_locker_keys = {r["id"] for r in rooms if r.get("flags", {}).get("no_locker_keys")}
    if actual_no_locker_keys != NO_LOCKER_KEYS_ROOMS:
        missing = NO_LOCKER_KEYS_ROOMS - actual_no_locker_keys
        extra = actual_no_locker_keys - NO_LOCKER_KEYS_ROOMS
        errors.append(
            f"no_locker_keys flag mismatch: missing {sorted(missing)}, "
            f"unexpected {sorted(extra)}"
        )

    # ── extra_categories (multi-category membership) ─────────────────────────
    # "AQUARIUM is every color of room": the base Aquarium and its three
    # upgrade variants each list every colour but their own primary
    # ("blueprint"). Maid's Chamber's own effect text has always said "Counts
    # as red room AND bedroom" -- bedroom is its lone addition. The eight
    # Mechanical rooms (wiki's definitive list) carry "mechanical", a room
    # role rather than a colour; the Electric Eel Aquarium gains it on top of
    # its existing every-colour membership. Room.categories (engine/model.py)
    # is what turns this into the membership set Room.is_category() checks.
    # Mirrored in tools/ingest_sheet.py's CATEGORY_OVERRIDE for the
    # sheet-sourced rooms (the Aquarium family, Utility Closet, Boiler Room,
    # Pump Room, Security, Workshop, Laboratory, and the ten Tomorrow-typed
    # rooms below); Maid's Chamber, the Mechanarium, Clock Tower and
    # Planetarium are supplemental-sourced and carry their own
    # extra_categories directly.
    EXPECTED_EXTRA_CATEGORIES = {
        "aquarium": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "aquarium__experiment": {
            "red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "goldfish_aquarium__ix2": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "starfish_aquarium__ix3": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "electric_eel_aquarium__ix4": {
            "red", "green", "hallway", "bedroom", "shop", "blackprint", "mechanical"},
        "maids_chamber": {"bedroom"},
        "utility_closet": {"mechanical"},
        "boiler_room": {"mechanical"},
        "pump_room": {"mechanical"},
        "security": {"mechanical"},
        "workshop": {"mechanical"},
        "laboratory": {"mechanical"},
        "mechanarium": {"mechanical"},
        "clock_tower": {"tomorrow"},
        "coat_check": {"tomorrow"},
        "freezer": {"tomorrow"},
        "mail_room": {"tomorrow"},
        "mail_room__ix89": {"tomorrow"},
        "mail_room__ix90": {"tomorrow"},
        "mail_room__ix91": {"tomorrow"},
        "morning_room": {"tomorrow"},
        "planetarium": {"tomorrow"},
        "sauna": {"tomorrow"},
        "hallway__ix76": {"tomorrow"},
        "break_room__ix11": {"tomorrow"},
    }
    actual_extra_categories = {
        r["id"]: set(r["extra_categories"]) for r in rooms if r.get("extra_categories")
    }
    if actual_extra_categories != EXPECTED_EXTRA_CATEGORIES:
        missing = set(EXPECTED_EXTRA_CATEGORIES) - set(actual_extra_categories)
        extra = set(actual_extra_categories) - set(EXPECTED_EXTRA_CATEGORIES)
        mismatched = {
            rid for rid in set(EXPECTED_EXTRA_CATEGORIES) & set(actual_extra_categories)
            if EXPECTED_EXTRA_CATEGORIES[rid] != actual_extra_categories[rid]
        }
        errors.append(
            f"extra_categories mismatch: missing {sorted(missing)}, "
            f"unexpected {sorted(extra)}, mismatched {sorted(mismatched)}"
        )

    # ── Upgrade Disk persistence ──────────────────────────────────────────────
    # Every Upgrade Disk respawns at its source until spent, so each must carry
    # persistence "day" — that is the value fixed_disks_spent_today dispatches on
    # to decide which disks the collected_disks carryover retires. The sole
    # exemption is the repeatable tier-5 trade disk, which stays "permanent" so it
    # can be traded for again after being spent.
    #
    # This lives here rather than in tests because it is a data-content check:
    # the behaviour it protects (each disk returning until spent, the trade disk
    # staying obtainable afterwards) is pinned per-source in tests/test_disk_respawn.py.
    DISK_PERSISTENCE_EXEMPT = {"upgrade_disk_trade"}
    for item in si_items:
        iid = item["id"]
        if not iid.startswith("upgrade_disk_"):
            continue
        expected = "permanent" if iid in DISK_PERSISTENCE_EXEMPT else "day"
        actual = item.get("persistence")
        if actual != expected:
            errors.append(
                f"special_items/{iid}: Upgrade Disks must have persistence "
                f"{expected!r} (respawn until spent"
                f"{'; exempt as repeatable' if iid in DISK_PERSISTENCE_EXEMPT else ''}"
                f"), got {actual!r}"
            )

    # ── upgrade_selection.json ─────────────────────────────────────────────────
    KNOWN_CHECKS = {"room_drafts", "catacombs_unlocked", "always_false"}
    us_doc = json.loads((DATA / "upgrade_selection.json").read_text())

    # Validate slot definitions.
    us_slots = us_doc.get("slots", {})
    for slot_id, slot_info in us_slots.items():
        room_id = slot_info.get("room")
        if room_id not in by_id:
            errors.append(f"upgrade_selection/slots/{slot_id}: room {room_id!r} not in rooms.json")
        # Every slot but the two Spare Room stages is named after the room it
        # upgrades; upgrades.offer_variants relies on that to resolve a slot to
        # its variants without consulting the tables.
        elif not slot_id.startswith("spare_") and slot_id != room_id:
            errors.append(
                f"upgrade_selection/slots/{slot_id}: slot id must equal its room id {room_id!r}"
            )

    known_slots = set(us_slots.keys())

    # Validate non_veteran.first_upgrade weights sum to 1.0.
    nv_fu = us_doc.get("non_veteran", {}).get("first_upgrade", {})
    fu_weights = nv_fu.get("weights", {})
    for slot_id in fu_weights:
        if slot_id not in known_slots:
            errors.append(f"upgrade_selection/non_veteran/first_upgrade: unknown slot {slot_id!r}")
    weight_total = sum(fu_weights.values())
    if abs(weight_total - 1.0) > 1e-9:
        errors.append(
            f"upgrade_selection/non_veteran/first_upgrade weights sum to {weight_total:.10f}, expected 1.0"
        )

    # Validate chains for both modes.
    def _validate_chains(chains: list, label: str) -> None:
        for chain_line in chains:
            line_label = chain_line.get("line", "?")
            where = f"upgrade_selection/{label}/chains/line {line_label}"
            for entry in chain_line.get("entries", []):
                if "slot" in entry:
                    slot_id = entry["slot"]
                    if slot_id not in known_slots:
                        errors.append(f"{where}: unknown slot {slot_id!r}")
                elif "check" in entry:
                    check_kind = entry["check"]
                    if check_kind not in KNOWN_CHECKS:
                        errors.append(f"{where}: unknown check kind {check_kind!r}")
                    if check_kind == "room_drafts":
                        room_id = entry.get("room")
                        if room_id not in by_id:
                            errors.append(f"{where}: room_drafts references unknown room {room_id!r}")
                else:
                    errors.append(f"{where}: entry has neither 'slot' nor 'check'")

    _validate_chains(us_doc.get("non_veteran", {}).get("chains", []), "non_veteran")
    _validate_chains(us_doc.get("veteran", {}).get("chains", []), "veteran")

    # Validate veteran first_upgrade.
    vet_fu = us_doc.get("veteran", {}).get("first_upgrade", {})
    if vet_fu.get("uniform_over") not in (None, "all_slots"):
        errors.append(
            f"upgrade_selection/veteran/first_upgrade: unexpected uniform_over value "
            f"{vet_fu.get('uniform_over')!r}"
        )

    # Validate veteran day1_shortcut order contains real room ids.
    vet_sc = us_doc.get("veteran", {}).get("day1_shortcut", {})
    for room_id in vet_sc.get("order", []):
        if room_id not in by_id:
            errors.append(f"upgrade_selection/veteran/day1_shortcut: unknown room {room_id!r}")

    # Validate meta.confidence on all top-level and mode-level metas.
    for meta_path, meta in [
        ("upgrade_selection", us_doc.get("meta", {})),
        ("upgrade_selection/non_veteran", us_doc.get("non_veteran", {}).get("meta", {})),
        ("upgrade_selection/non_veteran/first_upgrade", nv_fu.get("meta", {})),
        ("upgrade_selection/veteran", us_doc.get("veteran", {}).get("meta", {})),
        ("upgrade_selection/veteran/first_upgrade", vet_fu.get("meta", {})),
    ]:
        conf = meta.get("confidence")
        if meta and conf not in VALID_CONFIDENCE:
            errors.append(f"{meta_path}: invalid meta.confidence {conf!r}")

    # ── areas.json ─────────────────────────────────────────────────────────────
    # Referential integrity for the outside-area connectivity graph (docs/areas.md).
    # Checks: unique node/edge ids; every edge endpoint declared; every requires
    # tag declared; every anchor id in rooms.json; every item gate id in
    # special_items.json; every gate is referenced by at least one edge (warn if not).

    areas_doc = json.loads((DATA / "areas.json").read_text())
    a_nodes = areas_doc.get("nodes", [])
    a_edges = areas_doc.get("edges", [])
    a_gates = areas_doc.get("gates", [])

    VALID_AREA_NODE_KINDS = {"area", "anchor"}
    VALID_GATE_KINDS = {"item", "flag", "room", "puzzle", "unmodelled", "outer_room"}
    VALID_PERMANENCE = {"permanent", "daily", "none"}

    # Node uniqueness
    a_node_ids = [n["id"] for n in a_nodes]
    if len(a_node_ids) != len(set(a_node_ids)):
        dupes = {i for i in a_node_ids if a_node_ids.count(i) > 1}
        errors.append(f"areas: duplicate node ids: {dupes}")
    a_node_id_set = set(a_node_ids)

    # Deferred from the special-items loop: every absent_spawn_areas id must name a
    # real area-graph node.  Before areas.json existed these ids were unvalidated in
    # both directions, which is how 'reservoir' (the graph splits it north/south) and
    # 'precipice' (the Key of Aries clock is in the Unknown) went unnoticed.
    for where, aid in absent_area_refs:
        if aid not in a_node_id_set:
            errors.append(
                f"{where}: absent_spawn_areas {aid!r} is neither a room in rooms.json "
                f"nor a node in areas.json"
            )

    # Deferred from the ignition-targets loop: every "area": true target id must
    # name a real area-graph node (e.g. mine_south, which has no rooms.json record).
    for where, tid in ignition_area_refs:
        if tid not in a_node_id_set:
            errors.append(f"{where}: area ignition target {tid!r} not a node in areas.json")

    for n in a_nodes:
        where = f"areas/nodes/{n['id']}"
        if n.get("kind") not in VALID_AREA_NODE_KINDS:
            errors.append(f"{where}: invalid kind {n.get('kind')!r}")
        # Required, not defaulted: a new node must state whether its contents are
        # modelled, because that decides whether the env offers a travel action to it.
        # Silently defaulting would let an empty area be advertised as a destination.
        if not isinstance(n.get("modelled"), bool):
            errors.append(f"{where}: 'modelled' must be present and boolean")
        conf = n.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: invalid meta.confidence {conf!r}")
        # Anchor nodes must exist as room ids in rooms.json.
        # Exception: "house" represents the entire 5x9 grid (the Entrance Hall
        # complex), not a single draftable room, and has no rooms.json record.
        if n.get("kind") == "anchor" and n["id"] != "house":
            if n["id"] not in by_id:
                errors.append(f"{where}: anchor id {n['id']!r} not in rooms.json")

    # Gate uniqueness and schema
    a_gate_ids = [g["id"] for g in a_gates]
    if len(a_gate_ids) != len(set(a_gate_ids)):
        dupes = {i for i in a_gate_ids if a_gate_ids.count(i) > 1}
        errors.append(f"areas: duplicate gate ids: {dupes}")
    a_gate_id_set = set(a_gate_ids)

    for g in a_gates:
        where = f"areas/gates/{g['id']}"
        if g.get("kind") not in VALID_GATE_KINDS:
            errors.append(f"{where}: invalid kind {g.get('kind')!r}")
        if g.get("permanence") not in VALID_PERMANENCE:
            errors.append(f"{where}: invalid permanence {g.get('permanence')!r}")
        if not isinstance(g.get("stub"), bool):
            errors.append(f"{where}: stub must be bool, got {g.get('stub')!r}")
        conf = g.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: invalid meta.confidence {conf!r}")
        # item gates: item_ids list must be non-empty; every id must exist in special_items.json
        if g.get("kind") == "item":
            iids = g.get("item_ids")
            if not iids:
                errors.append(f"{where}: kind=item gate missing or empty item_ids field")
            else:
                for iid in iids:
                    if iid not in si_by_id:
                        errors.append(f"{where}: item_ids entry {iid!r} not in special_items.json")
        # counts_flag: only meaningful on kind=item gates (gate_open only reads it in the
        # "item" arm). It is a synthetic engine flag name (set by game.py::_gate_ctx), not
        # a gate id, so it is deliberately NOT checked against a_gate_id_set.
        if g.get("counts_flag") is not None and g.get("kind") != "item":
            errors.append(f"{where}: counts_flag is only meaningful on kind=item gates")
        # room gates: room_id field must exist and name a real room
        if g.get("kind") == "room":
            rid = g.get("room_id")
            if rid is None:
                errors.append(f"{where}: kind=room gate missing room_id field")
            elif rid not in by_id:
                errors.append(f"{where}: room_id {rid!r} not in rooms.json")
        # stub invariants:
        # 1. A stub gate must carry retire_in (the only record of what retires it).
        # 2. kind=unmodelled must carry retire_in regardless of stub, and must declare
        #    which way it fails, EXACTLY ONE of:
        #      stub=true           default-OPEN (the standing convention). Passes
        #                          unconditionally, so no node is stranded, and
        #                          anything measured through it is an upper bound.
        #      default_closed=true default-CLOSED (the exception, e.g. reservoir_water_13).
        #                          gate_open returns False for kind=unmodelled, so the
        #                          edge is shut until the real mechanism lands.
        #    Demanding an explicit declaration is the point: inferring intent from an
        #    absent flag would let an accidental stub=false silently kill an edge and
        #    strand whatever sits behind it. Naming it means a closed gate is always
        #    somebody's stated decision.
        # 3. retire_in must NOT be present on any other (non-unmodelled) non-stub gate
        #    -- a live gate with a real mechanism has nothing left to retire.
        if g.get("stub") is True and not g.get("retire_in"):
            errors.append(f"{where}: stub=true gate missing retire_in field")
        if g.get("kind") == "unmodelled":
            if not g.get("retire_in"):
                errors.append(f"{where}: kind=unmodelled gate missing retire_in field")
            if g.get("stub") is True and g.get("default_closed") is True:
                errors.append(f"{where}: kind=unmodelled gate cannot be both stub=true "
                              f"(passes) and default_closed=true (never passes)")
            if g.get("stub") is not True and g.get("default_closed") is not True:
                errors.append(f"{where}: kind=unmodelled gate must declare either "
                              f"stub=true (default-open) or default_closed=true "
                              f"(default-closed); a bare stub=false silently kills "
                              f"the edge")
        elif g.get("stub") is False and g.get("retire_in"):
            errors.append(f"{where}: stub=false gate must not have retire_in field")
        if g.get("default_closed") is True and g.get("kind") != "unmodelled":
            errors.append(f"{where}: default_closed is only meaningful on "
                          f"kind=unmodelled gates")

    # Edge uniqueness and referential integrity
    a_edge_pairs = [(e["from"], e["to"]) for e in a_edges]
    if len(a_edge_pairs) != len(set(a_edge_pairs)):
        dupes = {p for p in a_edge_pairs if a_edge_pairs.count(p) > 1}
        errors.append(f"areas: duplicate edges: {dupes}")

    # Build a lookup: node id -> node dict (for kind and outer-pool checks below)
    a_node_by_id = {n["id"]: n for n in a_nodes}
    # Set of room ids with pool == "outer" from rooms.json (used for outer_room gate check)
    outer_room_ids = {r["id"] for r in rooms if r.get("pool") == "outer"}
    # Gate kind lookup for edge-level checks
    a_gate_by_id = {g["id"]: g for g in a_gates}

    gates_used: set[str] = set()
    for e in a_edges:
        where = f"areas/edges/{e['from']}->{e['to']}"
        conf = e.get("meta", {}).get("confidence")
        if conf not in VALID_CONFIDENCE:
            errors.append(f"{where}: invalid meta.confidence {conf!r}")
        if e["from"] not in a_node_id_set:
            errors.append(f"{where}: from {e['from']!r} not a declared node")
        if e["to"] not in a_node_id_set:
            errors.append(f"{where}: to {e['to']!r} not a declared node")
        for gid in e.get("requires", []):
            if gid not in a_gate_id_set:
                errors.append(f"{where}: requires unknown gate {gid!r}")
            else:
                # outer_room gates: the destination node must be an anchor with pool=="outer"
                if a_gate_by_id[gid].get("kind") == "outer_room":
                    to_node = a_node_by_id.get(e["to"], {})
                    if to_node.get("kind") != "anchor":
                        errors.append(
                            f"{where}: outer_room gate requires destination to be an anchor node "
                            f"(got kind={to_node.get('kind')!r})"
                        )
                    elif e["to"] not in outer_room_ids:
                        errors.append(
                            f"{where}: outer_room gate destination {e['to']!r} "
                            f"is not a room with pool='outer' in rooms.json"
                        )
            gates_used.add(gid)

    # Warn on declared gates that no edge references (likely a stale or orphaned gate).
    for gid in a_gate_id_set:
        if gid not in gates_used:
            warnings.append(f"areas/gates/{gid}: gate declared but not referenced by any edge")

    # Node and edge count consistency: 38 nodes (26 area + 12 anchors) and 77 directed
    # edges. A mismatch means the data and spec have drifted.
    #
    # 77: includes the reservoir_north<->reservoir_south crossing (gated CLOSED by
    # reservoir_water_13). Not 79: the antechamber anchor deliberately has NO area
    # edges to the house. Reaching rank 9 center is a GRID walk through a
    # lever-opened door, and an area edge would let travel_to() hop there for
    # ~0 steps straight past the seal.
    SPEC_NODE_COUNT = 38
    SPEC_EDGE_COUNT = 77
    actual_node_count = len(a_node_ids)
    actual_edge_count = len(a_edges)
    if actual_node_count != SPEC_NODE_COUNT:
        errors.append(
            f"areas: node count is {actual_node_count}, spec says {SPEC_NODE_COUNT} "
            f"(26 area nodes + 12 anchors); update docs/areas.md if the graph has changed"
        )
    if actual_edge_count != SPEC_EDGE_COUNT:
        errors.append(
            f"areas: edge count is {actual_edge_count}, spec says {SPEC_EDGE_COUNT}; "
            f"update docs/areas.md if the graph has changed"
        )

    # ── special_items.json notes-decay check ──────────────────────────────────
    # Needs area_by_id (areas.json, just loaded above) and the wiki locations
    # snapshot, so it runs here rather than inside the special_items loop.
    area_by_id = {n["id"]: n for n in a_nodes}
    wiki_locations = _load_wiki_locations(WIKI_LOCATIONS_TSV)
    for finding in find_notes_decay_findings(
            si_items, si_doc.get("_notes", []), area_by_id, wiki_locations):
        errors.append(finding)

    # ── special_items.json spawn-table check ──────────────────────────────────
    for finding in find_spawn_table_findings(si_items, rooms, wiki_locations):
        errors.append(finding)

    # ── engine/effects registries ─────────────────────────────────────────────
    # Four registries (room_hook, Capability via provides/provides_lever,
    # ItemCapability via item_provides, ItemHook via item_hook) all register ids
    # at IMPORT TIME, before any Registry exists -- so a typo'd id (a mistyped
    # room_hook("dovecot", ...) or item_provides("emerlad_bracelet", ...))
    # cannot be checked at the call site; it would otherwise just never match
    # anything real and silently never fire. Wiring these four validate_*
    # functions in here (they also back tests/test_room_registry.py,
    # test_item_registry.py and test_item_hook_registry.py) means a bare
    # `validate_data.py` run catches a typo too, not only pytest.
    effects_registry = Registry.load()
    for rid in validate_room_registry(effects_registry):
        errors.append(f"engine/effects: room_hook registered for unknown room id {rid!r}")
    for rid in validate_capability_registry(effects_registry):
        errors.append(
            f"engine/effects: provides/provides_lever registered for unknown room id {rid!r}")
    for iid in validate_item_registry(effects_registry):
        errors.append(f"engine/effects: item_provides registered for unknown item id {iid!r}")
    for iid in validate_item_hook_registry(effects_registry):
        errors.append(f"engine/effects: item_hook registered for unknown item id {iid!r}")
    for rid in validate_container_registry(effects_registry):
        errors.append(
            f"engine/effects: provides_containers registered for unknown room id {rid!r}")

    # Necessity check for the effect-tag vocabulary. The per-record loop above
    # only asks whether a tag a record carries is known; nothing asked whether
    # a known tag is still carried by anything, so an entry could outlive the
    # last record using it and sit here as dead vocabulary.
    carried_tags = {eff.get("tag") for item in si_doc.get("items", [])
                    for eff in item.get("effects", [])}
    for tag in sorted(KNOWN_ITEM_EFFECT_TAGS - carried_tags):
        errors.append(
            f"KNOWN_ITEM_EFFECT_TAGS: {tag!r} is carried by no item record -- "
            f"behaviour lives in engine/effects, so an unused tag is dead "
            f"vocabulary rather than a source of truth"
        )

    # Necessity check, not just liveness: a room registered via
    # provides_containers should never ALSO carry a static containers.rooms
    # entry -- _container_kinds_at prefers the overlay unconditionally, so a
    # static entry alongside a registered overlay is dead data no code path
    # can ever reach, and its presence would silently mask the overlay if the
    # registration were ever removed.
    container_overlap = sorted(registered_container_rooms() & set(containers_rooms))
    for rid in container_overlap:
        errors.append(
            f"special_items/containers/rooms/{rid}: has a static entry AND a "
            f"provides_containers overlay -- the static entry is unreachable "
            f"dead data (engine/effects prefers the overlay unconditionally)"
        )

    # ── effects=[] census (derived, not a data marker) ────────────────────────
    # See find_empty_effects_findings' docstring for what this measures and
    # why: informational counts, plus a warning only where a record's own
    # prose claims no effect is modelled while it IS registered above.
    room_registered_ids = registered_rooms() | registered_capability_rooms()
    item_registered_ids = registered_item_capability_ids() | registered_item_hook_ids()
    (empty_effects_warnings, n_empty_rooms, n_room_registered,
     n_empty_items, n_item_registered) = find_empty_effects_findings(
        rooms, si_items, room_registered_ids, item_registered_ids)
    warnings.extend(empty_effects_warnings)

    print(
        f"effects=[] census: {n_empty_rooms} rooms with empty effects "
        f"({n_room_registered} registered via room_hook/Capability, "
        f"{n_empty_rooms - n_room_registered} not found in those registries); "
        f"{n_empty_items} items with empty effects "
        f"({n_item_registered} registered via item_provides/item_hook, "
        f"{n_empty_items - n_item_registered} not found in those registries)"
    )

    # Room-fidelity divergence audit: its own channel, always computed so the
    # summary line can advertise the count, but only printed under --audit and
    # never folded into errors/warnings -- see find_divergences' docstring.
    _assert_python_exemptions_live(DATA.parent)
    _assert_data_exemptions_live(by_id)
    _assert_deferred_exemptions_live(rooms, by_id, lock_rules, shops_doc)
    audit_kind1, audit_kind2 = find_divergences(rooms, by_id, lock_rules,
                                                shop_rules=shops_doc)
    n_audit = len(audit_kind1) + len(audit_kind2)

    base = [r for r in rooms if r.get("pool") == "base"]
    n_shops = len(shops)
    audit_note = (
        f"; {n_audit} divergence-audit findings (run with --audit to list)"
        if n_audit else ""
    )
    # Unimplemented items split into work still queued vs decisions never to build,
    # so the backlog number reflects what is actually left rather than counting
    # deliberate exclusions forever.
    _unimpl = [i for i in si_items if not i.get("implemented", True)]
    _wont = [i for i in _unimpl if i.get("meta", {}).get("wont_implement")]
    print(f"{len(rooms)} rooms ({len(base)} base pool); "
          f"{len(si_items)} special items "
          f"({len(_unimpl) - len(_wont)} unimplemented, "
          f"{len(_wont)} deliberately not modelled); "
          f"{n_shops} shops; "
          f"{len(ex_triggers)} experiment triggers, {len(ex_effects)} experiment effects; "
          f"{len(errors)} errors, {len(warnings)} warnings{audit_note}")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if args.audit:
        print()
        print(f"--- divergence audit worklist, NOT validation failures "
              f"({n_audit} findings) ---")
        print(f"kind 1 -- variant identical to parent, effect_text differs "
              f"({len(audit_kind1)}):")
        for f in audit_kind1:
            print(f"  audit[kind1]: {f}")
        print(f"kind 2 -- effect_text present, no modelling "
              f"({len(audit_kind2)}):")
        for f in audit_kind2:
            print(f"  audit[kind2]: {f}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
