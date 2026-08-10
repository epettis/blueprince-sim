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
import sys
from pathlib import Path

# Only needed for the kind-2 divergence check below: a room whose behaviour
# is registered via room_hook (engine/effects/rooms/) is modelled even though
# rooms.json carries no effects/items.guaranteed for it. Importing the package
# pulls in engine.effects.rooms, which is how handlers register themselves --
# that is the point, not a side effect to work around. Needs blueprince_sim
# on the import path (editable install, or PYTHONPATH=src), same as every
# other tools/ script that imports it (e.g. benchmark_env.py).
from blueprince_sim.engine.effects import registered_rooms

DATA = Path(__file__).resolve().parent.parent / "src" / "blueprince_sim" / "data"

VALID_RARITIES = {"commonplace", "standard", "unusual", "rare", None}
VALID_LAYOUTS = {"dead_end", "straight", "corner", "t", "cross"}
VALID_CATEGORIES = {"blueprint", "bedroom", "hallway", "green", "shop", "red",
                    "blackprint", "studio_addition", "outer", "objective"}
VALID_POOLS = {"base", "studio_addition", "outer", "pool_temp", "upgrade_variant",
               "conditional", "none"}
VALID_CONFIDENCE = {"datamined", "wiki", "inferred", "placeholder"}
KNOWN_CONDITIONS = {"west_wing", "east_wing", "west_or_east_wing", "not_on_wing",
                    "no_corner", "corner_only", "interior_only",
                    "west_wing_from_south_door", "garage", "boiler_room",
                    "morning_room", "room8_placement", "gift_shop",
                    "no_north_on_wing", "no_horizontal_end_rank", "north_south_only",
                    "pool_drafted", "library_only", "antechamber_north_door", "room8_key",
                    "knight_chess_piece", "secret_garden_key", "breakfast", "the_foundation"}
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
    "lockpick", "luck_bonus", "coin_interest", "coin_multiplier",
    "food_bonus", "food_multiplier", "free_hallway_moves", "free_move_interval",
    "stopwatch", "sleeping_mask", "watering_can", "master_key", "silver_key_bias",
    "compass", "ornate_compass", "emerald_bracelet", "dig_tool", "treasure_map",
    "metal_detector_spawns", "auto_collect", "mask_red_room", "paper_crown",
    "set_steps_on_pickup", "steps_at_rank", "negate_red_once_per_day",
    "allowance",
    # PR2+ / inert tags
    "shop_discount", "smash", "repellent", "scepter", "chronograph",
    "crown_of_blueprints", "gear_wrench", "dowsing_rod", "locksmith_rob",
    # Multi-day carry-over (PR2 item persistence)
    "moon_pendant_carry",
    "ignition_tool",
}
VALID_ITEM_KINDS = {"standard", "special_key", "contraption", "showroom", "armory", "unique"}
VALID_ITEM_PERSISTENCE = {"day", "until_used", "permanent"}
VALID_DIG_OUTCOME_KINDS = {"junk", "nothing", "coins", "gold_coin", "turnip", "key", "item", "gems"}

KNOWN_EFFECT_TAGS = {"grant", "grant_per_category", "grant_on_draft_category",
                     "set_resource_on_enter",
                     "counts_as_drafting_room",
                     "counts_as_bedrooms", "inject_pool",
                     "free_green_drafts",
                     "reduce_draft_options",
                     "anti_luck", "mark_visited"}

# Room ids whose "always unlocked" effect_text is implemented via
# locks.json's always_unlocked_rooms table rather than effects/items --
# excluded from the divergence audit below by exact id, not by text pattern,
# so any other room's unmodelled "always unlocked" claim still surfaces.
_AUDIT_STRUCTURAL_EXEMPT_IDS = {"corridor", "corriyard__ix50"}

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
    "break_room__ix11": "engine/game.py",        # day-end keycard pulse
    "chamber_of_mirrors": "engine/draft.py",     # duplicate-room drafting
    # Absorbing a spread is implemented by each spreader's own branch rather
    # than by the Conference Room; the Patio's is the representative one.
    "conference_room": "engine/effects/rooms/patio.py",
    # The main course is rank-8 gated and re-checked on every arrival, not
    # just first entry, so it stays a hand-written branch rather than a
    # room_hook (which only fires once, on first entry).
    "dining_room": "engine/special_items.py",    # rank-8 main course
    "dovecote": "engine/effects/rooms/dovecote.py",  # rotation while drawn
    # The steal must be able to draw the room's own guaranteed Allowance
    # Token, granted earlier in the same on_enter call, so it stays ordered
    # against that grant rather than moving to an earlier-firing room_hook.
    "lost_and_found": "engine/special_items.py",  # steal one item, grant two
    "reading_nook__ix99": "engine/draft.py",     # LIBRARY forced into slot 2
    "the_foundation": "engine/game.py",          # persists across days
    "the_kennel": "engine/effects/rooms/the_kennel.py",  # digging unlocks that room
    "utility_closet": "engine/game.py",          # breaker box
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

    Both kinds exclude four exemption sets, each covering a channel the audit
    cannot introspect: ``_AUDIT_STRUCTURAL_EXEMPT_IDS`` (implemented in
    locks.json), ``_AUDIT_PYTHON_EXEMPT_IDS`` (a hand-written branch keyed on
    the room id, in the module each entry names), ``_AUDIT_DATA_EXEMPT_IDS``
    (the text merely restates a field the record already carries) and
    ``_AUDIT_DOCTRINE_EXEMPT_IDS`` (the effect is a no-op under the
    assumed-solved doctrine).

    Both kinds also exclude commerce rooms, whose behaviour lives in
    ``engine/shops.py``: the ids in ``shop_rules``'s "shops" table plus
    ``_AUDIT_COMMERCE_EXTRA_IDS``. A shop's ``effect_text`` states only that it
    trades ("Items for Sale", "Launder Currency"), which shops.py implements in
    full, so counting them as unmodelled measures the audit's blind spot rather
    than the sim's. ``shop_rules`` defaults to no shops, which keeps every
    caller that does not pass it on the pre-existing behaviour.
    """
    locks_backed = frozenset(rid for rid in _AUDIT_STRUCTURAL_EXEMPT_IDS if rid in by_id)
    # Sanity-check the locks-backed list so it can't silently rot: every id in
    # it must actually be exempt from locks.json's own always_unlocked table.
    lock_exempt = set(lock_rules.get("always_unlocked_rooms", {}).get("rooms", []))
    assert locks_backed <= lock_exempt, (
        f"_AUDIT_STRUCTURAL_EXEMPT_IDS has ids not in locks.json "
        f"always_unlocked_rooms: {locks_backed - lock_exempt}"
    )
    structural = locks_backed | frozenset(
        rid for rid in (set(_AUDIT_PYTHON_EXEMPT_IDS) | set(_AUDIT_DATA_EXEMPT_IDS)
                        | set(_AUDIT_DOCTRINE_EXEMPT_IDS))
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
            # here fails exactly the same silent way the exact-coins bug did,
            # so it is worth catching at data-validation time rather than in
            # a low-value round-trip test.
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

    # priority draws reference real rooms
    for entry in priority["priority_draws"]:
        for rid in entry["rooms"]:
            if rid not in by_id:
                errors.append(f"priority draw references unknown room {rid}")
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
    for rid in [*lock_rules["keycard"]["source_rooms"],
                *lock_rules["always_unlocked_rooms"]["rooms"]]:
        if rid not in by_id:
            errors.append(f"locks references unknown room {rid}")

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
        for rid in item.get("spawn_rooms", []):
            if rid not in by_id:
                errors.append(f"{where}: spawn_rooms references unknown room {rid!r}")
        for rid in item.get("spawn_rooms_high_luck", []):
            if rid not in by_id:
                errors.append(f"{where}: spawn_rooms_high_luck references unknown room {rid!r}")
        for rid in item.get("guaranteed_in", []):
            if rid not in by_id:
                errors.append(f"{where}: guaranteed_in references unknown room {rid!r}")
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
        if not item.get("implemented", True):
            if not item.get("meta", {}).get("blocked_on"):
                errors.append(f"{where}: implemented=false requires meta.blocked_on")
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

    # Valid grant kinds inside a loot entry's grants list
    VALID_GRANT_KINDS = {"coins", "keys", "gems", "dice", "item", "keycard", "food"}

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
    HAS_ANIMAL_ROOMS = {"rumpus_room", "aquarium", "nursery", "bunk_room",
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
    # as red room AND bedroom" -- bedroom is its lone addition. Room.categories
    # (engine/model.py) is what turns this into the membership set
    # Room.is_category() checks. Mirrored in tools/ingest_sheet.py's
    # CATEGORY_OVERRIDE (the Aquarium family only; Maid's Chamber is
    # supplemental-sourced and carries its own extra_categories directly).
    EXPECTED_EXTRA_CATEGORIES = {
        "aquarium": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "goldfish_aquarium__ix2": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "starfish_aquarium__ix3": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "electric_eel_aquarium__ix4": {"red", "green", "hallway", "bedroom", "shop", "blackprint"},
        "maids_chamber": {"bedroom"},
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
        #      stub=true           default-OPEN (2026-07-27 convention). Passes
        #                          unconditionally, so no node is stranded, and
        #                          anything measured through it is an upper bound.
        #      default_closed=true default-CLOSED (2026-08-06, reservoir_water_13).
        #                          gate_open returns False for kind=unmodelled, so the
        #                          edge is shut until the real mechanism lands.
        #    Demanding an explicit declaration is the point. Before this, the rule was
        #    "unmodelled implies stub=true", which made an accidental stub=false
        #    silently kill an edge and strand whatever sat behind it -- the exact
        #    failure mode behind the withdrawn basement_key_well PR. Inferring intent
        #    from stub=false would re-open that hole for every future gate; naming it
        #    means a closed gate is always somebody's stated decision.
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
    # 77: the reservoir_north<->reservoir_south crossing (2026-08-06, gated CLOSED by
    # reservoir_water_13) added 2 edges to the prior 75. Not 79: the antechamber
    # anchor deliberately has NO area edges to the house. Reaching rank 9 center is a
    # GRID walk through a lever-opened door, and an area edge would let travel_to()
    # hop there for ~0 steps straight past the seal.
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

    # Room-fidelity divergence audit: its own channel, always computed so the
    # summary line can advertise the count, but only printed under --audit and
    # never folded into errors/warnings -- see find_divergences' docstring.
    _assert_python_exemptions_live(DATA.parent)
    audit_kind1, audit_kind2 = find_divergences(rooms, by_id, lock_rules,
                                                shop_rules=shops_doc)
    n_audit = len(audit_kind1) + len(audit_kind2)

    base = [r for r in rooms if r.get("pool") == "base"]
    n_shops = len(shops)
    audit_note = (
        f"; {n_audit} divergence-audit findings (run with --audit to list)"
        if n_audit else ""
    )
    print(f"{len(rooms)} rooms ({len(base)} base pool); "
          f"{len(si_items)} special items; "
          f"{n_shops} shops; "
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
