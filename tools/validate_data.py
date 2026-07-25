#!/usr/bin/env python3
"""Validate the committed data files: referential integrity + sanity checks.

Run: python tools/validate_data.py  (exit 1 on any error)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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
                    "knight_chess_piece", "secret_garden_key", "breakfast"}
KNOWN_EFFECT_TAGS = {"grant", "grant_per_category", "grant_on_draft_category",
                     "set_resource_on_enter", "solarium_weights", "greenhouse_bias",
                     "furnace_bias", "conservatory_rerolls", "study_redraws",
                     "counts_as_drafting_room",
                     "counts_as_bedrooms", "inject_pool", "allow_duplicates",
                     "free_green_drafts", "halve_steps", "coins_per_deadend",
                     "negate_red_rooms", "pay_gems_with_steps", "reduce_draft_options",
                     "anti_luck"}


def main() -> int:
    """Check every data/*.json file and print a report; return 1 if any error, else 0.

    Errors are schema/range/referential violations that must block a commit;
    warnings (unknown draft-condition tags, unhandled effect tags) are printed
    but do not affect the exit code.
    """
    errors: list[str] = []
    warnings: list[str] = []

    rooms_doc = json.loads((DATA / "rooms.json").read_text())
    weights = json.loads((DATA / "weights.json").read_text())
    priority = json.loads((DATA / "priority_draws.json").read_text())
    json.loads((DATA / "items.json").read_text())
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

    # priority draws reference real rooms
    for entry in priority["priority_draws"]:
        for rid in entry["rooms"]:
            if rid not in by_id:
                errors.append(f"priority draw references unknown room {rid}")
    for rid in priority["forced_draw_precedence"]["order"]:
        if rid not in by_id:
            warnings.append(f"forced-draw precedence references unknown room {rid}")

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

    base = [r for r in rooms if r.get("pool") == "base"]
    print(f"{len(rooms)} rooms ({len(base)} base pool); "
          f"{len(errors)} errors, {len(warnings)} warnings")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
