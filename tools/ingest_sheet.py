#!/usr/bin/env python3
"""Build data/rooms.json from the raw TFMurphy room-table dump.

Reads tools/raw/tfmurphy_room_table.md (verbatim extraction of the decompiled
v1.3 room table), applies:
  - column mappings (rarity, layout, draft conditions, flags) - mechanical
  - GLYPH_MAP: resolves the ambiguous bare-mojibake currency glyph per room
  - EFFECT_MAP: hand-authored structured effect tags per room id
  - tools/supplemental_rooms.json: rooms absent from the decompiled table
    (Red Rooms page, Studio Additions, Outer Rooms) with their own
    confidence annotations
and writes src/blueprince_sim/data/rooms.json.

Run: python tools/ingest_sheet.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "tools" / "raw" / "tfmurphy_room_table.md"
SUPPLEMENTAL = ROOT / "tools" / "supplemental_rooms.json"
OUT = ROOT / "src" / "blueprince_sim" / "data" / "rooms.json"

LAYOUT_MAP = {
    "Dead End": "dead_end",
    "Straight": "straight",
    "L": "corner",
    "T": "t",
    "4-Door": "cross",
}

# Wiki-sourced shape corrections where the datamined layout column disagrees
# with the observed in-game room shape (blueprince.wiki.gg/wiki/Category:Room_shapes).
# The raw sheet stays verbatim; these override its parsed layout by room id.
# Each entry: id -> {"layout", "alt_layouts", "note"}.
LAYOUT_OVERRIDE: dict[str, dict] = {
    # Datamine "Dead End / Straight"; wiki lists it as a straight-shape room.
    # (Its special end-of-room draw lets you pick the next room's color.)
    "secret_passage": {"layout": "straight", "alt_layouts": [],
                       "note": "wiki: straight-shape"},
    # Datamine "Dead End"; wiki lists it as 4-way (cross). OPEN ITEM: the cross
    # arms have gated traversal (each door entered from outside), so its
    # connectivity is not a normal cross and is not yet modeled.
    "chamber_of_mirrors": {"layout": "cross", "alt_layouts": [],
                           "note": "wiki: 4-way; OPEN: gated arm traversal not modeled"},
}

CONDITION_MAP = {
    "West Wing": ["west_wing"],
    "East Wing": ["east_wing"],
    "West Wing or East Wing": ["west_or_east_wing"],
    "West Wing From South-Facing Door": ["west_wing_from_south_door"],
    "Pool Drafted": ["pool_drafted"],
    "Draft From Library": ["library_only"],
    "Antechamber North Door": ["antechamber_north_door"],
    "Room 8 Key": ["room8_key"],
    "Knight Chess Piece Active": ["knight_chess_piece"],
    "Secret Garden Key  West Wing or East Wing": ["secret_garden_key", "west_or_east_wing"],
    "Eat Bacon & Eggs in Kitchen or Breakfast Nook": ["breakfast"],
}

CATEGORY_FROM_TYPE1 = {
    "Blueprint": "blueprint",
    "Bedroom": "bedroom",
    "Hallway": "hallway",
    "Green Room": "green",
    "Shop": "shop",
    "Red Room": "red",
    "Blackprint": "blackprint",
}

# --- glyph disambiguation ---------------------------------------------------
# The export mojibake renders both keys (U+1F511) and gems (U+1F48E) as a bare
# "ð" (their trailing UTF-8 bytes are invisible C1 controls). Resolved
# DEFINITIVELY by byte inspection of the cached export: 3rd byte 0x94 = key,
# 0x92 = gem. All entries below are therefore confidence=datamined. Each
# entry: room name -> resolution per bare-glyph occurrence in its Effect text.
GLYPH_MAP: dict[str, list[tuple[str, str]]] = {
    # keys (bytes F0 9F 94 91)
    "Nook": [("key", "datamined")],
    "Breakfast Nook": [("key", "datamined")],
    "Reading Nook": [("key", "datamined")],
    "Garage": [("key", "datamined")],
    "Music Room": [("key", "datamined"), ("key", "datamined")],
    "Locker Room": [("key", "datamined")],
    "Servant's Quarters": [("key", "datamined")],
    "Servant's Spare Quarters": [("key", "datamined")],
    "Hallway": [("key", "datamined")],
    "Storeroom": [("key", "datamined"), ("gem", "datamined")],  # key then gem
    # gems (bytes F0 9F 92 8E)
    "Den": [("gem", "datamined")],
    "Wine Cellar": [("gem", "datamined")],
    "Trophy Room": [("gem", "datamined")],
    "Ballroom": [("gem", "datamined"), ("gem", "datamined")],
    "Her Ladyship's Chamber": [("gem", "datamined")],
    "Her Ladyship's Spare Room": [("gem", "datamined")],
    "Boudoir": [("gem", "datamined")],
    "Courtyard": [("gem", "datamined")],
    "Patio": [("gem", "datamined")],
    "Spare Patio": [("gem", "datamined")],
    "Indoor Nursery": [("gem", "datamined")],
    "Morning Room": [("gem", "datamined"), ("gem", "datamined")],
    "Parlor": [("gem", "datamined")],
    "Funeral Parlor": [("gem", "datamined")],
    "Study": [("gem", "datamined")],
    "Freezer": [("gem", "datamined")],
    "Terrace": [("gem", "datamined")],
    "Spare Terrace": [("gem", "datamined")],
    "Cloister of Rynna": [("luck", "datamined")],
    # Bunk Room variants: idx 20 doubles keys, 21 doubles gems, 22 doubles coins
    "Bunk Room": [("key", "datamined"), ("gem", "datamined")],
}

# --- structured effects -----------------------------------------------------
# Hand-authored per room id: what the engine actually simulates. Resource
# CONTENTS go in "items" (rolled on first entry); behavioral effects go in
# "effects". Rooms not listed get no effects (their prose is out of scope).
EFFECT_MAP: dict[str, dict] = {
    "nook": {"items": {"guaranteed": [{"item": "key", "count": 1}]}},
    "garage": {"items": {"guaranteed": [{"item": "key", "count": 3}]}},
    "music_room": {"items": {"guaranteed": [{"item": "key", "count": 2}]}},
    "den": {"items": {"guaranteed": [{"item": "gem", "count": 1}]}},
    "wine_cellar": {"items": {"guaranteed": [{"item": "gem", "count": 3}]}},
    "trophy_room": {"items": {"guaranteed": [{"item": "gem", "count": 8}]}},
    "pantry": {"items": {"guaranteed": [{"item": "coins", "count": 1}]}},  # 4 coins: one pile approximated
    "rumpus_room": {"items": {"guaranteed": [{"item": "coins", "count": 2}]}},
    "vault": {"items": {"guaranteed": [{"item": "coins", "count": 8}]}},
    "storeroom": {"items": {"guaranteed": [
        {"item": "key", "count": 1}, {"item": "gem", "count": 1}, {"item": "coins", "count": 1}]}},
    "closet": {"items": {"guaranteed": [{"item": "random", "count": 2}]}},
    "walk_in_closet": {"items": {"guaranteed": [{"item": "random", "count": 4}]}},
    "attic": {"items": {"guaranteed": [{"item": "random", "count": 8}]}},
    "guest_bedroom": {"effects": [{"tag": "grant", "resource": "steps", "amount": 10}]},
    "bedroom": {"effects": [{"tag": "grant", "resource": "steps", "amount": 2}]},
    "bunk_room": {"effects": [{"tag": "counts_as_bedrooms", "amount": 2}]},
    "master_bedroom": {"effects": [
        {"tag": "grant_per_category", "resource": "steps", "amount": 1, "category": "any"}]},
    "servants_quarters": {"effects": [
        {"tag": "grant_per_category", "resource": "keys", "amount": 1, "category": "bedroom"}]},
    "nursery": {"effects": [
        {"tag": "grant_on_draft_category", "resource": "steps", "amount": 5, "category": "bedroom"}]},
    "ballroom": {"effects": [{"tag": "set_resource_on_enter", "resource": "gems", "value": 2}]},
    "study": {"effects": [{"tag": "study_redraws"}]},
    "drawing_room": {"effects": [{"tag": "counts_as_drafting_room"}]},
    "library": {"effects": [{"tag": "counts_as_drafting_room"}]},
    "drafting_studio": {"effects": [{"tag": "counts_as_drafting_room"}]},
    "chamber_of_mirrors": {"effects": [{"tag": "allow_duplicates"}]},
    "the_pool": {"effects": [
        {"tag": "counts_as_drafting_room"},
        {"tag": "inject_pool", "rooms": ["locker_room", "sauna", "pump_room"]}]},
    "greenhouse": {"effects": [{"tag": "greenhouse_bias"}, {"tag": "counts_as_drafting_room"}]},
    "terrace": {"effects": [{"tag": "free_green_drafts"}]},
    "morning_room": {"items": {"guaranteed": [{"item": "gem", "count": 2}]}},
    "veranda": {"effects": [{"tag": "grant", "resource": "luck", "amount": 3}]},  # inferred magnitude
    "courtyard": {"items": {"guaranteed": []}},
    "secret_garden": {"items": {"guaranteed": [{"item": "gem", "count": 2}]}},
    "observatory": {"effects": []},  # stars out of scope
    "dining_room": {"effects": []},
    "her_ladyships_chamber": {"effects": []},  # cross-room promise; Tier 2
    "freezer": {"effects": []},  # cross-day; out of scope
    "sauna": {"effects": []},    # cross-day; out of scope
}

# Per-category default for luck-scaled extra items (Item Spawns table is
# Cloudflare-blocked; these are community-informed estimates, confidence
# inferred, editable in data/overrides/).
ADDITIONAL_MAX_DEFAULT = {
    "blueprint": 1, "bedroom": 1, "hallway": 1, "green": 1,
    "shop": 0, "red": 0, "blackprint": 0, "objective": 0,
}

GLYPH_STEPS = "ð£"   # mojibake for U+1F463
GLYPH_COINS = "ð°"   # U+1F4B0
GLYPH_DICE = "ð²"    # U+1F3B2
GLYPH_BARE = "ð"          # key or gem (ambiguous)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


def clean(cell: str) -> str:
    return cell.replace("\\", "").strip()


def parse_rows() -> list[dict]:
    rows = []
    for line in RAW.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [clean(c) for c in line.strip("|").split("|")]
        if len(cells) < 17 or cells[0] in ("#", ""):
            continue
        rows.append(dict(zip(
            ["num", "name", "page", "rarity", "gem_cost", "effect", "color", "type1",
             "type2", "type3", "unlock", "conditions", "layout", "no_library",
             "powered", "duct", "internal_index"], cells)))
    return rows


def build_room(row: dict) -> dict | None:
    name = row["name"]
    rid = slugify(name)
    rarity = row["rarity"].lower() if row["rarity"] not in ("-", "") else None
    if rarity not in (None, "commonplace", "standard", "unusual", "rare"):
        raise ValueError(f"bad rarity {row['rarity']!r} for {name}")

    layouts = [LAYOUT_MAP[p.strip()] for p in row["layout"].split("/")]
    layout_note = None
    if rid in LAYOUT_OVERRIDE:
        ov = LAYOUT_OVERRIDE[rid]
        layouts = [ov["layout"], *ov["alt_layouts"]]
        layout_note = ov["note"]
    category = CATEGORY_FROM_TYPE1.get(row["type1"].split("/")[0].strip(), "blueprint")
    if row["type2"] == "Objective" or name in ("Antechamber", "Room 46"):
        category = "objective"

    conds = CONDITION_MAP.get(row["conditions"], []) if row["conditions"] not in ("-", "") else []
    gem_cost = 0 if row["gem_cost"] in ("-", "") else int(row["gem_cost"])

    # Only "Upgrade X" unlock strings are upgrade-disk variants; other unlock
    # text (e.g. The Armory's "Knight Chess Piece Active") is a draft gate.
    is_variant = row["unlock"].startswith("Upgrade ")
    if row["unlock"] == "Knight Chess Piece Active":
        conds = conds + ["knight_chess_piece"]
    entry = {
        "id": rid,
        "name": name,
        "category": category,
        "rarity": rarity,
        "gem_cost": gem_cost,
        "layout": layouts[0],
        "alt_layouts": layouts[1:],
        "draft_conditions": conds,
        "flags": {
            "no_library_draft": row["no_library"] == "Yes",
            "powered": row["powered"] == "Yes",
            "duct": row["duct"] == "Yes",
        },
        "deck_copies": 1,
        "effects": [],
        "items": {"guaranteed": [], "additional_max": ADDITIONAL_MAX_DEFAULT.get(category, 0),
                  "dig_spots": 0},
        "pool": "base",
        "meta": {
            "source": "tfmurphy_sheet_v1.3",
            "confidence": "datamined",
            "directory_number": row["num"],
            "internal_index": int(row["internal_index"]),
            "effect_text": row["effect"] if row["effect"] not in ("-", "") else "",
        },
    }
    if is_variant:
        entry["pool"] = "upgrade_variant"
        entry["meta"]["unlock"] = row["unlock"]
        entry["id"] = rid + "__ix" + row["internal_index"]
        entry["variant_of"] = slugify(row["unlock"].replace("Upgrade ", ""))
    if name in ("Entrance Hall", "Antechamber", "Room 46", "The Foundation"):
        entry["pool"] = "none"
    if "pool_drafted" in conds:
        entry["pool"] = "pool_temp"
    # library_only and item/unlock-gated rooms stay in the base decks - the
    # draft-condition filter decides whether they can be dealt (item/unlock
    # gates are satisfied via GameConfig.satisfied_conditions). Room 46 is
    # only reachable through the Antechamber and never deals normally.
    if "antechamber_north_door" in conds:
        entry["pool"] = "none"

    overrides = EFFECT_MAP.get(rid if not is_variant else slugify(name))
    if overrides:
        if "effects" in overrides:
            entry["effects"] = overrides["effects"]
        if "items" in overrides:
            entry["items"].update(overrides["items"])
    if name in GLYPH_MAP:
        entry["meta"]["glyph_resolution"] = [
            {"icon": icon, "confidence": conf} for icon, conf in GLYPH_MAP[name]]
    if layout_note:
        entry["meta"]["layout_note"] = layout_note
    return entry


def main() -> None:
    rows = parse_rows()
    rooms, seen = [], set()
    for row in rows:
        r = build_room(row)
        if r is None or r["id"] in seen:
            continue
        seen.add(r["id"])
        rooms.append(r)

    # Second-level upgrades name their parent variant by plain slug; resolve
    # to the actual (suffixed) id so variant chains reference real records.
    by_slug = {}
    for r in rooms:
        slug = r["id"].split("__ix")[0]
        if r["id"] == slug or slug not in by_slug:
            by_slug.setdefault(slug, r["id"])
    for r in rooms:
        v = r.get("variant_of")
        if v and v not in seen and v in by_slug:
            r["variant_of"] = by_slug[v]

    if SUPPLEMENTAL.exists():
        for r in json.loads(SUPPLEMENTAL.read_text())["rooms"]:
            if r["id"] not in seen:
                seen.add(r["id"])
                rooms.append(r)

    out = {
        "schema_version": 1,
        "source": "TFMurphy decompiled sheet v1.3 (rooms 1-77 + variants) + supplemental_rooms.json",
        "rooms": rooms,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    base = [r for r in rooms if r["pool"] == "base"]
    print(f"Wrote {len(rooms)} rooms ({len(base)} in base pool) -> {OUT}")


if __name__ == "__main__":
    main()
