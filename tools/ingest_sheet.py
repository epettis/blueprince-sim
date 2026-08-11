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

# Rooms whose terminal accepts an Upgrade Disk (docs/upgrade-disks-design.md).
# Blackbridge Grotto is a fifth in the real game but has no record yet, so it
# stays gated behind the outside-area work in docs/open_tasks.md task 4.
DISK_READER_IDS = {"security", "laboratory", "office", "shelter"}

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

# Wiki-sourced draft-condition overrides, keyed by room id, for rooms whose raw
# sheet "conditions" column is blank/"-" but whose real placement rule is known
# from the wiki (docs/foundation-design.md). Applied AFTER CONDITION_MAP, so it
# always wins for the listed ids. This is a NEW map: unlike the wing/rank/
# direction refinements on Garage/Boiler Room/etc (which the CONDITION_MAP
# pipeline doesn't encode and which live only as hand edits in the committed
# rooms.json, per CLAUDE.md), The Foundation's condition has no raw-sheet
# source text to derive from at all, so it is hard-coded here to survive re-ingest.
CONDITION_OVERRIDE: dict[str, list[str]] = {
    "the_foundation": ["the_foundation"],
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
# entry: room name -> ambiguous-glyph resolution per BARE "ð" occurrence in its
# Effect text (tailed forms ð², ð°, ð£ are decoded mechanically by resolve_glyphs).
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
    "Storeroom": [("key", "datamined"), ("gem", "datamined")],  # key then gem; ð° decoded mechanically
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
}

# Per-variant overrides for the ambiguous-glyph list, keyed by suffixed record id.
# Mirrors EFFECT_OVERRIDE: used when a variant's Effect text differs from its base
# (different number of bare ð glyphs, or a different icon). Also used for variants
# whose text has NO bare glyphs (empty list) so resolve_glyphs sees no leftovers.
# Bunk Room: base has no glyphs; ix20 doubles keys, ix21 doubles gems, ix22 doubles
# coins (ð° — decoded mechanically, so ambiguous list is empty).
VARIANT_GLYPH_MAP: dict[str, list[tuple[str, str]]] = {
    # Hallway: only ix74 has a bare ð; base and ix75/ix76 have no glyph in text.
    "hallway": [],
    "hallway__ix75": [],
    "hallway__ix76": [],
    # Boudoir: ix17 has ð² (dice, decoded mechanically) — no bare ð to resolve.
    "boudoir": [],
    "boudoir__ix17": [],
    # Courtyard: base and ix49 have no glyph in text.
    "courtyard": [],
    "courtyard__ix49": [],
    # Parlor: base and ix109 have no glyph in text.
    "parlor": [],
    "parlor__ix109": [],
    # Bunk Room: each variant has its own bare-ð icon; base has no glyph.
    "bunk_room": [],
    "bunk_room__ix20": [("key", "datamined")],
    "bunk_room__ix21": [("gem", "datamined")],
    "bunk_room__ix22": [],  # ð° is coins, decoded mechanically
}

# --- structured effects -----------------------------------------------------
# Hand-authored per room id: what the engine actually simulates. Resource
# CONTENTS go in "items" (rolled on first entry); behavioral effects go in
# "effects". Rooms not listed get no effects (their prose is out of scope).
EFFECT_MAP: dict[str, dict] = {
    "nook": {"items": {"guaranteed": [{"item": "key", "count": 1}]}},
    "garage": {"items": {"guaranteed": [{"item": "key", "count": 3}], "dig_spots": 1}},
    "music_room": {"items": {"guaranteed": [{"item": "key", "count": 2}]}},
    "den": {"items": {"guaranteed": [{"item": "gem", "count": 1}]}},
    "wine_cellar": {"items": {"guaranteed": [{"item": "gem", "count": 3}], "dig_spots": 1}},
    "trophy_room": {"items": {"guaranteed": [{"item": "gem", "count": 8}]}},
    "pantry": {"items": {"guaranteed": [{"item": "coins", "count": 1}]}},  # 4 coins: one pile approximated
    "rumpus_room": {"items": {"guaranteed": [{"item": "coins", "count": 2}]}},
    "vault": {"items": {"guaranteed": [{"item": "coins", "count": 8}]}},
    "storeroom": {"items": {"guaranteed": [
        {"item": "key", "count": 1}, {"item": "gem", "count": 1}, {"item": "coins", "count": 1}],
        "dig_spots": 1}},
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
    "study": {"effects": [
        {"tag": "grant", "resource": "gems", "amount": 1}]},
    "drawing_room": {"effects": [
        {"tag": "counts_as_drafting_room"},
        {"tag": "grant", "resource": "gems", "amount": 1}]},
    "office": {"effects": [{"tag": "grant", "resource": "gems", "amount": 1}]},
    "boudoir": {"effects": [{"tag": "grant", "resource": "gems", "amount": 1}]},
    "library": {"effects": [{"tag": "counts_as_drafting_room"}]},
    "drafting_studio": {"effects": [{"tag": "counts_as_drafting_room"}]},
    "the_pool": {"effects": [
        {"tag": "counts_as_drafting_room"},
        {"tag": "inject_pool", "rooms": ["locker_room", "sauna", "pump_room"]}]},
    "greenhouse": {"effects": [{"tag": "counts_as_drafting_room"}],
                   "items": {"dig_spots": 1}},
    "terrace": {"effects": [{"tag": "free_green_drafts"}], "items": {"dig_spots": 1}},
    "morning_room": {"items": {"guaranteed": [{"item": "gem", "count": 2}], "dig_spots": 1}},
    "veranda": {"effects": [{"tag": "grant", "resource": "luck", "amount": 3}],  # inferred magnitude
                "items": {"dig_spots": 1}},
    "courtyard": {"items": {"guaranteed": [], "dig_spots": 1}},
    "secret_garden": {"items": {"guaranteed": [{"item": "gem", "count": 2}], "dig_spots": 1}},
    "observatory": {"effects": []},  # star grant lives in a room_hook, not a data effect tag
    "dining_room": {"effects": []},
    "her_ladyships_chamber": {"effects": []},  # cross-room promise; Tier 2
    "freezer": {"effects": []},  # cross-day; out of scope
    "sauna": {"effects": []},    # cross-day; out of scope
    # Dig spots (wiki source: blueprince.wiki.gg/wiki/Dig_Spot); count 1 when wiki gives no
    # number. Supplemental-sourced rooms (furnace, dovecote, solarium, the_kennel,
    # conservatory, outer rooms) carry theirs in tools/supplemental_rooms.json instead.
    "boiler_room": {"items": {"dig_spots": 1}},
    "pump_room": {"items": {"dig_spots": 1}},
    "workshop": {"items": {"dig_spots": 1}},
    "aquarium": {"items": {"dig_spots": 1}},
    "patio": {"items": {"dig_spots": 1}},
    "cloister": {"items": {"dig_spots": 1}},
    # Parlor: box always contains 2 gems on first entry; Wind-up Key is deliberately
    # not modeled (action-space simplification — see docs/special-items-design.md).
    "parlor": {"items": {"guaranteed": [{"item": "gem", "count": 2}]}},
    # The Foundation: two guaranteed dig spots near the wooden walkways (wiki);
    # the "up to two additional" spots by the elevator are not modeled (no roll
    # invented for them) - see docs/foundation-design.md.
    "the_foundation": {"items": {"dig_spots": 2}},
}

# Per-record overrides for the room-fidelity audit, keyed by the FINAL record id
# (unsuffixed for base-pool rooms like "vault", "__ix"-suffixed for upgrade
# variants like "parlor__ix108"). Applied AFTER EFFECT_MAP, so an entry here
# always wins regardless of what EFFECT_MAP produced from the base slug — this
# is the one place to add the next audited effects/items.guaranteed fix,
# whether the record is base-pool or a variant. Each entry sets "effects"
# and/or "items" (with "guaranteed" only; other item keys like dig_spots stay
# whatever EFFECT_MAP set); a field left out of an entry keeps its pre-override
# value rather than being cleared. validate_effect_override() (called from
# main()) raises if a key here is not among the ids the sheet actually
# produces, so a typo'd id fails the ingest instead of silently doing nothing.
EFFECT_OVERRIDE: dict[str, dict] = {
    # The Gallery's chests pay a fixed 4 coins, so the entry is coins_exact
    # rather than a pile count; Key 8 arrives separately via guaranteed_in.
    "gallery": {"items": {"guaranteed": [
        {"item": "gem", "count": 2},
        {"item": "coins_exact", "count": 4}]}},
    # Tomorrow Rooms: mark_visited records the visit; the bonus is paid at the
    # next day's reset. The Morning Room also pays 2 gems the same day.
    "sauna": {"effects": [{"tag": "mark_visited", "flag": "sauna_visited"}]},
    "freezer": {"effects": [{"tag": "mark_visited", "flag": "freezer_frozen"}]},
    "morning_room": {
        "effects": [{"tag": "mark_visited", "flag": "morning_room_visited"}],
        "items": {"guaranteed": [{"item": "gem", "count": 2}]}},
    # ix108: "3ð Prize" — the upgrade variant that increases the Parlor box to 3 gems.
    "parlor__ix108": {"items": {"guaranteed": [{"item": "gem", "count": 3}]}},
    # Boudoir's safe is a fixture of the room, so it survives every upgrade. Room
    # effects are NOT inherited through variant_of (each record is an independent
    # frozen Room), so the grant has to be repeated per variant rather than left
    # to the base entry. Each variant also adds its own upgrade effect.
    "boudoir__ix16": {"effects": [
        {"tag": "grant", "resource": "gems", "amount": 1},
        {"tag": "grant", "resource": "gems", "amount": 1}]},
    "boudoir__ix17": {"effects": [
        {"tag": "grant", "resource": "gems", "amount": 1},
        {"tag": "grant", "resource": "dice", "amount": 2}]},
    "boudoir__ix18": {"effects": [
        {"tag": "grant", "resource": "gems", "amount": 1},
        {"tag": "grant", "resource": "gems", "amount": 3}]},
    # Quest Bedroom keeps the base Guest Bedroom's +10 steps grant, for the same
    # reason as the Boudoir variants above: room effects are not inherited
    # through variant_of, so the grant has to be repeated here or the upgrade
    # silently loses it. The Antechamber-allowance half of the card is handled
    # by a room_hook, not a data effect.
    "quest_bedroom__ix71": {"effects": [{"tag": "grant", "resource": "steps", "amount": 10}]},
    # Exact coin piles (room-fidelity audit): the raw sheet's Effect text gives a
    # specific coin count per room, but EFFECT_MAP's base entries only emit a
    # generic "coins" pile. "coins_exact" is a plain item kind, not something
    # the ingest pipeline resolves — it is just written here verbatim.
    "vault": {"items": {"guaranteed": [{"item": "coins_exact", "count": 40}]}},
    "rumpus_room": {"items": {"guaranteed": [{"item": "coins_exact", "count": 8}]}},
    # Pantry: the exact 4-coin pile, plus one weighted fruit pick
    # (items.json food.fruit_weights) further down the countertop.
    "pantry": {"items": {"guaranteed": [
        {"item": "coins_exact", "count": 4},
        {"item": "fruit", "count": 1}]}},
    # Goldfish Aquarium's "+10" is a literal coin figure, not a pile count.
    "goldfish_aquarium__ix2": {"items": {"guaranteed": [{"item": "coins_exact", "count": 10}]}},
    # Storeroom upgrade variants each roll a different key/gem/coin mix; ix146's
    # coin pile is also exact rather than a generic pile.
    "storeroom__ix144": {"items": {"guaranteed": [
        {"item": "key", "count": 2}, {"item": "gem", "count": 1}, {"item": "coins", "count": 1}]}},
    "storeroom__ix145": {"items": {"guaranteed": [
        {"item": "key", "count": 1}, {"item": "gem", "count": 2}, {"item": "coins", "count": 1}]}},
    "storeroom__ix146": {"items": {"guaranteed": [
        {"item": "key", "count": 1}, {"item": "gem", "count": 1},
        {"item": "coins_exact", "count": 10}]}},
    # Nook-family variants each have their own name (so EFFECT_MAP's "nook"
    # entry, keyed by base slug, only matches the plain "Nook" record) and their
    # own key count.
    "nook__ix97": {"items": {"guaranteed": [{"item": "key", "count": 2}]}},
    "reading_nook__ix99": {"items": {"guaranteed": [{"item": "key", "count": 1}]}},
    "breakfast_nook__ix98": {"items": {"guaranteed": [{"item": "key", "count": 1}]}},
    # Hallway upgrade variant grants a key; the base Hallway does not.
    "hallway__ix74": {"items": {"guaranteed": [{"item": "key", "count": 1}]}},
    # Closet-family variants each have their own name, so EFFECT_MAP's "closet"
    # entry (keyed by base slug) does not match; they grant the same 2 random
    # items as the base Closet.
    "hallway_closet__ix39": {"items": {"guaranteed": [{"item": "random", "count": 2}]}},
    "bedroom_closet__ix40": {"items": {"guaranteed": [{"item": "random", "count": 2}]}},
    # Nursery-family variants each have their own name, so EFFECT_MAP's
    # "nursery" entry does not match; each variant has its own upgrade effect.
    "indoor_nursery__ix103": {"effects": [
        {"tag": "grant_on_draft_category", "resource": "gems", "amount": 2, "category": "green"}]},
    "nurses_station__ix102": {"effects": [
        {"tag": "set_resource_on_enter", "resource": "steps", "value": 20, "if_below": 10}]},
    # nursery and nursery__ix101 both grant on their own draft (own category is
    # bedroom), unlike indoor_nursery__ix103 above whose text says "another".
    "nursery": {"effects": [
        {"tag": "grant_on_draft_category", "resource": "steps", "amount": 5,
         "category": "bedroom", "include_self": True}]},
    "nursery__ix101": {"effects": [
        {"tag": "grant_on_draft_category", "resource": "steps", "amount": 8,
         "category": "bedroom", "include_self": True}]},
    # Second-level variants (upgrades of an upgrade): each has its own name, so
    # EFFECT_MAP's base-slug entry does not match.
    "spare_master_bedroom__ix136": {"effects": [
        {"tag": "grant_per_category", "resource": "steps", "amount": 1, "category": "any"}]},
    "spare_terrace__ix141": {"effects": [{"tag": "free_green_drafts"}]},
    "pool_hall__ix12": {"effects": [
        {"tag": "inject_pool", "rooms": ["great_hall", "foyer", "secret_passage"]}]},
    # Courtyard upgrade variants: ix48 grants the "+2 gem" prize (glyph resolves
    # to gem per meta.glyph_resolution); ix49 widens the dig-spot count to 5
    # rather than the base's 1. Both share the base's "Courtyard" display name,
    # so EFFECT_MAP's base-slug entry would otherwise apply to all three.
    "courtyard__ix48": {"effects": [{"tag": "grant", "resource": "gems", "amount": 2}]},
    "courtyard__ix49": {"items": {"dig_spots": 5}},
    # Servant's Spare Quarters: second-level variant with its own name, so
    # EFFECT_MAP's "servants_quarters" entry does not match; mirrors the base
    # Servant's Quarters' key-per-Bedroom grant (glyph resolves to key).
    "servants_spare_quarters__ix134": {"effects": [
        {"tag": "grant_per_category", "resource": "keys", "amount": 1, "category": "bedroom"}]},
    # Spare Veranda: second-level variant with its own name, so EFFECT_MAP's
    # "veranda" entry does not match; mirrors the base Veranda's luck grant.
    "spare_veranda__ix140": {"effects": [{"tag": "grant", "resource": "luck", "amount": 3}]},
    # Geist Bedroom disables the base Guest Bedroom's random item spawn (and,
    # by extension, its luck-penalty processing): additional_max 0 rather than
    # the blueprint-category default of 1. Its dice grant is a room_hook
    # (effects/rooms/guest_bedroom.py), not a data effect.
    "geist_bedroom__ix69": {"items": {"additional_max": 0}},
    "bunk_room": {"effects": [{"tag": "counts_as_bedrooms", "amount": 2}]},
    # Parlor/Den/Trophy Room restate their EFFECT_MAP items.guaranteed here since
    # EFFECT_OVERRIDE always wins wholesale over EFFECT_MAP for a given field --
    # see apply_effect_override.
    "parlor": {"items": {"guaranteed": [{"item": "gem", "count": 2}]}},
    "den": {"items": {"guaranteed": [{"item": "gem", "count": 1}]}},
    "trophy_room": {"items": {"guaranteed": [{"item": "gem", "count": 8}]}},
    "drawing_room": {"effects": [
        {"tag": "counts_as_drafting_room"},
        {"tag": "grant", "resource": "gems", "amount": 1}]},
}

# Membership flags, keyed by final record id and merged into the record's
# "flags" object. Kept apart from EFFECT_OVERRIDE because that table REPLACES
# "effects" wholesale, so adding a flag to a room that already has effects
# there would mean restating them.
#
# The has_animal/has_fireplace lists back a Cloister variant
# (effects/rooms/cloister.py): Dauja pays stars for each "room with an animal"
# drafted from it, Veia adds dig spots to each "room with a fireplace". They
# are ad-hoc enumerations from the wiki rather than derivable categories,
# which is why membership is stored per room rather than computed. The Dining
# Room is deliberately absent: its fireplace depends on where it is placed,
# so cloister.py decides it per cell.
#
# no_locker_keys backs effects/rooms/locker_room.py's spread exclusion: the
# 18 rooms the wiki names as never receiving a spread key from the Locker
# Room, again an ad-hoc wiki enumeration rather than a derivable category.
#
# furnace, dovecote, the_kennel, gift_shop, darkroom, vestibule, mechanarium,
# maids_chamber and lavatory are supplemental-sourced, so they carry their
# flags in tools/supplemental_rooms.json; this table never reaches them.
FLAG_OVERRIDE: dict[str, dict] = {
    "rumpus_room": {"has_animal": True},
    "aquarium": {"has_animal": True},
    "nursery": {"has_animal": True},
    "bunk_room": {"has_animal": True},
    "parlor": {"has_fireplace": True},
    "den": {"has_fireplace": True},
    "trophy_room": {"has_fireplace": True},
    "drawing_room": {"has_fireplace": True},
    "the_armory": {"has_fireplace": True, "no_locker_keys": True},
    "antechamber": {"no_locker_keys": True},
    "room_46": {"no_locker_keys": True},
    "the_foundation": {"no_locker_keys": True},
    "spare_room": {"no_locker_keys": True},
    "passageway": {"no_locker_keys": True},
    "rotunda": {"no_locker_keys": True},
    "pump_room": {"no_locker_keys": True},
    "freezer": {"no_locker_keys": True},
    "bookshop": {"no_locker_keys": True},
}

# Extra category memberships, keyed by final record id, fully replacing
# (not merging into) the record's "extra_categories" list -- unlike
# FLAG_OVERRIDE's per-key flags dict, a room's extra-category set has no
# per-key granularity to preserve. Room.categories (engine/model.py) is the
# membership set built from "category" plus this list.
#
# "AQUARIUM is every color of room": the base record and its three upgrade
# variants each list every colour but their own primary ("blueprint") and
# "objective" (a room role, not a colour), since each variant's own
# effect_text repeats the same sentence verbatim alongside its own addition.
#
# The wiki's Mechanical room list adds six sheet-sourced rooms to the
# membership set: Utility Closet, Boiler Room, Pump Room, Security, Workshop
# and Laboratory. The Electric Eel Aquarium is also on that list, gaining
# "mechanical" on top of its existing every-colour membership rather than
# replacing it.
CATEGORY_OVERRIDE: dict[str, list[str]] = {
    "aquarium": ["red", "green", "hallway", "bedroom", "shop", "blackprint"],
    "goldfish_aquarium__ix2": ["red", "green", "hallway", "bedroom", "shop", "blackprint"],
    "starfish_aquarium__ix3": ["red", "green", "hallway", "bedroom", "shop", "blackprint"],
    "electric_eel_aquarium__ix4": [
        "red", "green", "hallway", "bedroom", "shop", "blackprint", "mechanical"],
    "utility_closet": ["mechanical"],
    "boiler_room": ["mechanical"],
    "pump_room": ["mechanical"],
    "security": ["mechanical"],
    "workshop": ["mechanical"],
    "laboratory": ["mechanical"],
}


def apply_effect_override(entry: dict) -> None:
    """Apply EFFECT_OVERRIDE to *entry* in place, keyed by its final ``id``.

    Sets ``entry["effects"]`` and/or ``entry["items"]["guaranteed"]`` from the
    matching EFFECT_OVERRIDE entry, fully replacing rather than merging each
    field, so it is safe to call regardless of what EFFECT_MAP already set. A
    field the override entry omits is left untouched. FLAG_OVERRIDE is applied
    too, merging key by key so naming one flag leaves the room's others alone.
    CATEGORY_OVERRIDE is applied last, replacing ``entry["extra_categories"]``
    wholesale when the id has an entry.
    """
    override = EFFECT_OVERRIDE.get(entry["id"])
    if override:
        if "effects" in override:
            entry["effects"] = override["effects"]
        if "items" in override:
            entry["items"].update(override["items"])
    entry.setdefault("flags", {}).update(FLAG_OVERRIDE.get(entry["id"], {}))
    if entry["id"] in CATEGORY_OVERRIDE:
        entry["extra_categories"] = list(CATEGORY_OVERRIDE[entry["id"]])


def validate_effect_override(seen_ids: set[str]) -> None:
    """Raise if EFFECT_OVERRIDE, FLAG_OVERRIDE or CATEGORY_OVERRIDE keys an id
    the sheet parse did not produce.

    *seen_ids* is the set of ids assembled from the parsed sheet rows only
    (tools/supplemental_rooms.json is merged in separately and none of the
    tables apply to it). A key absent from *seen_ids* would otherwise never be
    looked up by apply_effect_override and would silently do nothing.
    """
    for name, table in (("EFFECT_OVERRIDE", EFFECT_OVERRIDE),
                        ("FLAG_OVERRIDE", FLAG_OVERRIDE),
                        ("CATEGORY_OVERRIDE", CATEGORY_OVERRIDE)):
        unknown = sorted(set(table) - seen_ids)
        if unknown:
            raise ValueError(f"{name} has id(s) not produced by the sheet: {unknown}")


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

# Tail char -> icon. Each tailed form is GLYPH_BARE plus the one trailing byte that
# survived the export as a printable character, so it needs no disambiguation. Derived
# from the constants above so the two never drift apart.
GLYPH_TAILS = {
    GLYPH_DICE[1]: "dice",
    GLYPH_COINS[1]: "coins",
    GLYPH_STEPS[1]: "steps",
}


def resolve_glyphs(text: str, ambiguous: list[tuple[str, str]], room_id: str = "?") -> list[dict]:
    """Decode all mojibake glyph occurrences in *text*, returning one entry per glyph in order.

    Tailed forms are unambiguous and decoded mechanically:
      ð² -> dice, ð° -> coins, ð£ -> steps.
    Bare ð (not followed by ², °, or £) consumes the next entry from *ambiguous*.
    Raises ValueError if *ambiguous* is exhausted before the text is fully scanned,
    or if entries remain in *ambiguous* after the scan completes.
    """
    result = []
    remaining = list(ambiguous)
    i = 0
    while i < len(text):
        if text[i] == GLYPH_BARE:
            tail_icon = GLYPH_TAILS.get(text[i + 1] if i + 1 < len(text) else "")
            if tail_icon is not None:               # tailed form — unambiguous
                result.append({"icon": tail_icon, "confidence": "datamined"})
                i += 2
            else:                                   # bare ð — needs the map
                if not remaining:
                    raise ValueError(
                        f"resolve_glyphs: ran out of ambiguous entries at pos {i} "
                        f"for room {room_id!r} (text={text!r})"
                    )
                icon, conf = remaining.pop(0)
                result.append({"icon": icon, "confidence": conf})
                i += 1
        else:
            i += 1
    if remaining:
        raise ValueError(
            f"resolve_glyphs: {len(remaining)} unused ambiguous entries for room "
            f"{room_id!r} (text={text!r}, leftover={remaining!r})"
        )
    return result


def slugify(name: str) -> str:
    """Room name -> snake_case id; apostrophes vanish ("Servant's" -> "servants")."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


def clean(cell: str) -> str:
    return cell.replace("\\", "").strip()


def parse_rows() -> list[dict]:
    """Parse the raw markdown table into one dict per room row, keyed by column name.

    Only ``|``-prefixed lines with all 17 columns count; the header/separator
    rows are skipped. Cell text keeps the export's mojibake for the glyph maps
    to resolve later.
    """
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
    """Convert one parsed sheet row into a rooms.json record.

    Applies LAYOUT_OVERRIDE, CONDITION_MAP, EFFECT_MAP and GLYPH_MAP, and
    assigns the pool: "Upgrade X" unlocks become ``upgrade_variant`` records
    with an ``__ix<internal_index>`` id suffix, Pool-injected rooms go to
    ``pool_temp``, and fixed/objective rooms to ``none``. Raises on an
    unrecognized rarity so bad raw data fails loudly.
    """
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
    # The two rooms that ARE the objective. The sheet's own "Objective" type2 is
    # wider than that: it also marks a room which merely pays out on reaching one,
    # and such a room keeps its own colour.
    if name in ("Antechamber", "Room 46"):
        category = "objective"

    conds = CONDITION_MAP.get(row["conditions"], []) if row["conditions"] not in ("-", "") else []
    if rid in CONDITION_OVERRIDE:
        conds = CONDITION_OVERRIDE[rid]
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
            "disk_reader": False,
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
    # The Foundation deals from the base pool at its rare rarity (rank-3 removal
    # and the 17-cell placement rule are handled by draft.py / the "the_foundation"
    # draft condition, not by pool exclusion) - see docs/foundation-design.md.
    if name in ("Entrance Hall", "Antechamber", "Room 46"):
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
    # Per-record audit overrides applied after base EFFECT_MAP (may tighten, e.g. gem count).
    apply_effect_override(entry)
    # Resolve glyphs per-record: id-keyed override takes precedence over name-keyed map.
    # VARIANT_GLYPH_MAP entries with an empty list signal "no bare glyphs in this variant"
    # and resolve to [] (no glyph_resolution key written). The name-keyed GLYPH_MAP only
    # supplies the ambiguous list; tailed forms (ð², ð°, ð£) are decoded mechanically.
    # Any room whose text contains a bare GLYPH_BARE but has no map entry raises ValueError.
    record_id = entry["id"]
    effect_text = entry["meta"].get("effect_text", "")
    # A "bare" glyph is ð not immediately followed by one of the GLYPH_TAILS chars.
    has_bare = any(
        effect_text[i] == GLYPH_BARE
        and (i + 1 >= len(effect_text) or effect_text[i + 1] not in GLYPH_TAILS)
        for i in range(len(effect_text))
    )
    has_any_glyph = GLYPH_BARE in effect_text  # includes tailed forms
    if record_id in VARIANT_GLYPH_MAP:
        ambiguous: list[tuple[str, str]] | None = VARIANT_GLYPH_MAP[record_id]
    elif name in GLYPH_MAP:
        ambiguous = GLYPH_MAP[name]
    elif has_bare:
        # Bare glyph with no disambiguation entry — loud failure so nothing slips through.
        raise ValueError(
            f"build_room: room {record_id!r} has bare glyph in effect_text but no "
            f"GLYPH_MAP or VARIANT_GLYPH_MAP entry (text={effect_text!r})"
        )
    else:
        ambiguous = None
    if ambiguous is not None or has_any_glyph:
        resolved = resolve_glyphs(effect_text, ambiguous or [], room_id=record_id)
        if resolved:
            entry["meta"]["glyph_resolution"] = resolved
    if layout_note:
        entry["meta"]["layout_note"] = layout_note
    return entry


def main() -> None:
    """Rebuild data/rooms.json: sheet rows + supplemental rooms, dropping duplicate ids.

    Also rewrites second-level ``variant_of`` references to the suffixed ids of
    the actual variant records. Overwrites the output file (any hand-edits to
    rooms.json not reflected in the sources are lost).
    """
    rows = parse_rows()
    rooms, seen = [], set()
    for row in rows:
        r = build_room(row)
        if r is None or r["id"] in seen:
            continue
        seen.add(r["id"])
        rooms.append(r)

    validate_effect_override(seen)

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

    # Terminals that accept an Upgrade Disk. Applied here rather than in
    # build_room because the raw sheet has no such column and one of the four
    # (shelter) arrives from supplemental_rooms.json, which is copied verbatim.
    # Keyed by id, not name: GLYPH_MAP's name keying is what let the Boudoir
    # dice glyph be recorded as a gem.
    for r in rooms:
        r.setdefault("flags", {})["disk_reader"] = r["id"] in DISK_READER_IDS

    # Rooms whose entry grants same-day Catacombs access (solving the angel-statue puzzle).
    # Keyed by id: the Tomb is the only outer room that unlocks the Catacombs area.
    # Written ONLY when true, unlike disk_reader above: disk_reader is already present on
    # every record, so writing it unconditionally reproduces the committed file, whereas
    # this flag is present on the Tomb alone. Emitting `false` everywhere would make a
    # re-ingest diverge from rooms.json by 168 spurious lines. Room.unlocks_catacombs
    # defaults to False when the key is absent.
    UNLOCKS_CATACOMBS_IDS = {"tomb"}
    for r in rooms:
        if r["id"] in UNLOCKS_CATACOMBS_IDS:
            r.setdefault("flags", {})["unlocks_catacombs"] = True

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
