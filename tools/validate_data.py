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
KNOWN_ITEM_EFFECT_TAGS = {
    # PR1 functional set
    "lockpick", "luck_bonus", "coin_interest", "coin_multiplier",
    "food_bonus", "food_multiplier", "free_hallway_moves", "free_move_interval",
    "stopwatch", "sleeping_mask", "watering_can", "master_key", "silver_key_bias",
    "compass", "ornate_compass", "emerald_bracelet", "dig_tool", "treasure_map",
    "metal_detector_spawns", "auto_collect", "mask_red_room", "paper_crown",
    "set_steps_on_pickup", "steps_at_rank", "negate_red_once_per_day",
    # PR2+ / inert tags
    "shop_discount", "smash", "repellent", "scepter", "chronograph",
    "crown_of_blueprints", "gear_wrench", "dowsing_rod", "locksmith_rob",
    # Multi-day carry-over (PR2 item persistence)
    "moon_pendant_carry",
}
VALID_ITEM_KINDS = {"standard", "special_key", "contraption", "showroom", "armory", "unique"}
VALID_ITEM_PERSISTENCE = {"day", "until_used", "permanent"}
VALID_DIG_OUTCOME_KINDS = {"junk", "nothing", "coins", "gold_coin", "turnip", "key", "item", "gems"}

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
        for rid in item.get("meta", {}).get("absent_spawn_rooms", []):
            if rid in by_id:
                errors.append(
                    f"{where}: absent_spawn_rooms {rid!r} exists in rooms.json — move to spawn_rooms"
                )
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
    VALID_GRANT_KINDS = {"coins", "keys", "gems", "dice", "item", "keycard"}

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

    # parlor_boxes: rooms exist, count positive int, loot weights ~100, item ids resolve
    parlor_boxes = containers_doc.get("parlor_boxes", {})
    if parlor_boxes:
        for rid in parlor_boxes.get("rooms", []):
            if rid not in by_id:
                errors.append(f"special_items/containers/parlor_boxes: room {rid!r} not in rooms.json")
        count = parlor_boxes.get("count")
        if not isinstance(count, int) or count < 1:
            errors.append(f"special_items/containers/parlor_boxes: count must be a positive int, got {count!r}")
        loot = parlor_boxes.get("loot", [])
        if loot:
            total_w = sum(entry.get("weight", 0) for entry in loot)
            if abs(total_w - 100.0) > 0.5:
                errors.append(
                    f"special_items/containers/parlor_boxes: loot weights sum to {total_w:.4f}, expected ~100"
                )
            for entry in loot:
                if entry.get("kind") == "item":
                    iid = entry.get("id")
                    if iid not in si_resolvable:
                        errors.append(
                            f"special_items/containers/parlor_boxes: loot item id {iid!r} not in special_items"
                        )

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

    base = [r for r in rooms if r.get("pool") == "base"]
    n_shops = len(shops)
    print(f"{len(rooms)} rooms ({len(base)} base pool); "
          f"{len(si_items)} special items; "
          f"{n_shops} shops; "
          f"{len(errors)} errors, {len(warnings)} warnings")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
