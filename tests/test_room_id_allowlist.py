"""Enforces the capability-architecture invariant from docs/architecture.md:
"no engine module may branch on a room id" -- room-specific behaviour belongs
in `engine/effects/rooms/<room_id>.py`, registered rather than hardcoded.

The scanner is deliberately dumb: it flags every string literal in
`engine/*.py` that equals a real room id, with no attempt to guess whether
the site is a behaviour branch (``room.id == "chapel"``), a fixture lookup
(``registry.by_id["entrance_hall"]``), or incidental data that happens to
collide with a room id (Blue Prince has literal rooms named "Bedroom" and
"Hallway", so a Royal Scepter colour tuple or an ``is_category("bedroom")``
call is textually indistinguishable from an id branch). Guessing that
distinction from syntax would hide exactly the cases a human most needs to
re-examine after a refactor. Instead every occurrence must be justified by
an entry on one of the two allowlists below, and the comment on that entry
records the judgement call.

Mirrors ``tests/test_item_id_allowlist.py`` in shape: the allowlist is split
into two dicts of ``module filename -> {room ids}``. Per-line tracking would
be more precise but brittle to line-shuffling refactors that don't change
which ids a module names; per-module-id is the coarsest grain that still
answers "did this module stop naming this room".

- ``ROOM_ARCHITECTURE`` holds ids that are not really per-room behaviour
  branches at all: a category name that happens to collide with a real
  room's id ("bedroom"/"hallway" -- Blue Prince has rooms literally named
  Bedroom and Hallway), a data-section or JSON-table name that collides the
  same way (``locks.json``'s "security" section, unrelated to the Security
  room), an id-prefix family matched by ``str.startswith`` (the Garage and
  its upgrade variants), an ``Enum`` member that happens to be spelled like a
  room id, a small closed wiki-documented exemption set, a draft-condition
  tag emitted into a generic condition vocabulary, or an engine-owned
  enumeration (draft.py's published Guaranteed/Priority/Forced-Draw special
  rules, upgrades.py's Upgrade-Disk room table, placement.py's named
  placement conditions) that IS the module's own reason to exist rather than
  a carve-out bolted onto an otherwise room-agnostic mechanism. These entries
  are not expected to shrink.
- ``ROOM_DEBT`` holds ids that name a genuine per-room behaviour branch --
  a room-specific carve-out hardcoded into an otherwise shared/generic
  mechanism (a tag handler serving many rooms, a per-room dispatch table, a
  general predicate with one hardcoded exception) that belongs in
  ``engine/effects/rooms/<id>.py`` instead, registered via ``room_hook`` or a
  ``Capability`` the way ``effects/rooms/chapel.py`` now does. This is the
  number later phases drive down.

Both dicts are scanned together (see ``_combined_allowlist``), so splitting
the list does not narrow what the bidirectional checks cover. Three failure
modes are load-bearing:
- a room-id literal appears in a scanned module for an id not listed in
  either dict for that module (the architecture is regressing -- a new
  hardcoded id landed and nobody updated a list),
- an id listed in either dict no longer appears in its module (the refactor
  already happened and nobody shrank the list -- left unchecked a list only
  ever grows and stops measuring anything, per docs/architecture.md), and
- the same id is listed in both dicts for the same module (the split itself
  has become ambiguous about which bucket the id's debt belongs in).

A fourth check, ``test_room_id_debt_matches_the_cap``, pins ``ROOM_DEBT``'s
total at ``ROOM_ID_DEBT_CAP`` in BOTH directions -- unlike
``test_item_id_allowlist.py``'s ``ITEM_DEBT_CAP`` (which only bounds
``ITEM_DEBT`` from above, since a genuinely one-off id can always be added to
``ITEM_ARCHITECTURE`` later without that being suspicious), a total below the
cap here is also a bug: it means a refactor already shrank ``ROOM_DEBT`` and
nobody lowered the cap to match, which would silently let the debt grow back
up to the stale ceiling without this test ever noticing -- the exact
flat-since-launch blind spot ``ROOM_ID_ALLOWLIST_CAP`` (#332) was added to
close, now carried over onto the debt half of the split.
"""

from __future__ import annotations

import ast
from pathlib import Path

from blueprince_sim.engine import model as _model_module

#: Direct children of engine/ only (non-recursive) -- matches
#: docs/architecture.md's own "measured starting point" table, which
#: enumerates top-level engine modules and nothing under effects/. This
#: also means engine/effects/tier1.py is in scan scope even though it
#: sits outside effects/rooms/ (see :func:`_scanned_paths`).
ENGINE_DIR = Path(_model_module.__file__).resolve().parent

#: Room-specific behaviour is meant to live here, so ids named inside it are
#: the goal, not the debt this test measures.
EFFECTS_ROOMS_DIR = ENGINE_DIR / "effects" / "rooms"

#: module filename -> room ids that module names as string literals for a
#: reason that is not really a per-room behaviour branch -- see the module
#: docstring for the categories this covers. Not expected to shrink.
ROOM_ARCHITECTURE: dict[str, set[str]] = {
    "effects/tier1.py": {
        # Category name, not a room reference: grant_per_category adds
        # game.bedroom_bonus when counting the bedroom category. Blue
        # Prince has a room literally named Bedroom, so the two are
        # textually identical and the scanner cannot tell them apart.
        "bedroom",
    },
    "draft.py": {
        # This module's own published taxonomy of "Guaranteed Draws" /
        # "Priority Draws" / "Forced Draws" (see the module docstring's
        # opening paragraphs) -- the wiki's own closed, named set of
        # drafting-mechanic special rules that draft.py exists to
        # implement, not room behaviour bolted onto an otherwise
        # room-agnostic mechanism the way Chapel's tithe was. Module-level
        # *_ID constants (CLOSET_ID, TUNNEL_ID, LIBRARY_ID, MECHANARIUM_ID,
        # DARKROOM_ID, READING_NOOK_ID, AQUARIUM_EXPERIMENT_ID) each name
        # one such rule: the forced-Closet fallback (attempt 4 of the
        # four-attempt draw procedure), the Tunnel chain-draft guarantee,
        # the Reading Nook Library guarantee, the Mechanarium's
        # draft-time-derived door mask, and the Darkroom concealment pass.
        "closet", "tunnel", "library", "mechanarium", "darkroom",
        "reading_nook__ix99", "aquarium__experiment",
        # Same-hand dedup exemption so a Tunnel chain / Aquarium experiment
        # copy can be dealt more than once -- part of the same taxonomy.
        "chamber_of_mirrors",
        # Garage forced-draw roll (dead-end gate + priority_draws entry) --
        # the taxonomy's own Forced Draw mechanism.
        "garage",
        # Schoolhouse-placed category-bias condition tag: emitted into
        # _active_conditions' generic vocabulary (alongside non-room tags
        # like "furnace_or_king"), read by data-driven category_biases
        # entries -- a vocabulary key, not a code branch on this room.
        "schoolhouse",
        # Rank-3 90% Foundation removal-from-pool roll -- the taxonomy's own
        # rule, keyed to this one room by the wiki itself.
        "the_foundation",
        # SECRET_PASSAGE_IDS: the Secret Passage and its Spare, exempt from
        # normal drafting and from being drawn during a colour-selective
        # draft -- the taxonomy's colour-selective drafting rule.
        "secret_passage", "spare_secret_passage__ix138",
        # Category names, not room references: the colour-selective filter
        # names the five selectable colours. Blue Prince has rooms called
        # Bedroom and Hallway, so the two are textually identical here.
        "bedroom", "hallway",
    },
    "experiments.py": {
        # Category names, not room references: is_category("bedroom") /
        # is_category("hallway") arguments -- "bedroom" and "hallway"
        # collide with real room ids only because those categories also
        # name an undecorated base room.
        "bedroom", "hallway",
        # AQUARIUM_BASE_ID/AQUARIUM_EXPERIMENT_ID: add_aquariums's own fixed
        # targets, not a carve-out bolted onto a room-agnostic mechanism --
        # apply_effect's `match effect_id:` dispatch never branches on a
        # room id, only on the effect's own id, and hands off to
        # _apply_add_aquariums, whose entire content is injecting Aquarium
        # copies and moving them to the Commonplace bucket (the wiki's own
        # description of this one effect). Mirrors draft.py's
        # ROOM_ARCHITECTURE entry, which already treats
        # "aquarium__experiment" as this effect's own published taxonomy
        # rule rather than room-specific debt.
        "aquarium", "aquarium__experiment",
    },
    "game.py": {
        # Fixture lookups in reset(): the day always starts in the Entrance
        # Hall and the Antechamber is placed as a fixture, unconditionally --
        # no "if this room" branch, just direct unconditional instantiation.
        "entrance_hall", "antechamber",
        # _garage_ids: an id-prefix family (every id starting with "garage"),
        # matched by str.startswith rather than a single literal -- an
        # engine-owned prefix family, the same category as
        # special_items.py's own garage_ids use below.
        "garage",
        # RedrawKind.STUDY = "study": an enum tag, not a room.id comparison
        # -- happens to spell the Study's id because that room names the
        # mechanic (gem-cost redraws).
        "study",
        # room_46: an area-graph node id (areas.json's "room_46", kind
        # "area"), not a room.id branch -- travel_to's `dest == "room_46"`
        # arm (first-arrival bookkeeping) and area_route_cost("room_46") both
        # dispatch on the SAME destination-id parameter every other area node
        # in travel_to does (west_path, mine_south, orindian_ruins, ...),
        # none of which are room ids at all. "room_46" collides with a real
        # room id only because rooms.json also carries a Room 46 record for
        # reference (items/wiki data), even though it is never placed on the
        # grid -- the same collision class as bedroom/hallway's category
        # names above, just against the area graph instead of a category.
        "room_46",
    },
    "locks.py": {
        # rules["security"]: a locks.json data-SECTION name (room_door_chance
        # table, spawn limits, distance cutoffs for security-door spawning
        # near ANY room), not a reference to the Security room itself -- the
        # table happens to be named "security" the same way
        # special_items.py's "treasure_map"/"battery_pack" section reads
        # collide with those item ids (test_item_id_allowlist.py).
        "security",
    },
    "placement.py": {
        # Named draft-condition primitives (satisfies_draft_conditions), a
        # generic `match cond:` dispatch over rooms.json's per-room
        # "conditions" data -- most cases ("no_corner", "interior_only",
        # "north_south_only", ...) are not room ids at all; these six happen
        # to be named after the one room whose data declares them, purely as
        # a naming convention, not a room.id branch -- exempted by
        # docs/architecture.md itself ("placement.py's named conditions
        # legitimately name rooms as data").
        "garage", "boiler_room", "gift_shop", "morning_room",
        "the_foundation", "the_pool",
    },
    "shops.py": {
        # _REPELLENT_ILLEGAL_TARGETS frozenset member (the day-start room,
        # the win room, the secret room): a small, closed, wiki-documented
        # exemption set, never expected to grow. "entrance_hall" names no
        # other behaviour branch in this module -- can_smash_vase reads
        # Capability.VASE (registered by effects/rooms/entrance_hall.py)
        # instead of comparing the room id directly.
        "entrance_hall", "antechamber", "room_46",
        # SCEPTER_COLORS tuple: floorplan *category* names for the Royal
        # Scepter, not room ids -- "bedroom"/"hallway" collide with real
        # room ids the same way experiments.py's is_category() calls do.
        "bedroom", "hallway",
        # _DISCOUNT_EXEMPT_SHOPS frozenset: the two shops where the Coupon
        # Book (SHOP_DISCOUNT) has no effect (wiki-confirmed for both), a
        # small closed exemption set of the same shape as
        # _REPELLENT_ILLEGAL_TARGETS above.
        "casino", "laundry_room",
    },
    "special_items.py": {
        # can_open_car_trunk's garage_ids: the same id-prefix family
        # (str.startswith("garage")) as game.py's _garage_ids above, not a
        # single-id branch.
        "garage",
        # KINDS = (..., "showroom", ...): an inventory-item *kind* tag
        # ("showroom exhibit" items), not a room id -- collides with the
        # real Showroom room's id the same way the category names do.
        "showroom",
        # lost_and_found: the on_enter steal-trigger branch itself moved to
        # Capability.LOST_AND_FOUND (see ROOM_DEBT's former entry for this
        # module), but this module's own RNG substream label
        # (rng.choice("lost_and_found", ...)), data-section key
        # (item_rules["count_transforms"]["rooms"]["lost_and_found"]), and
        # guaranteed_by_room lookup all remain -- none of those are a
        # room.id comparison, just this room's own id used as a dict/RNG
        # key the same way every other room's id is, so they are not a
        # behaviour branch to convert.
        "lost_and_found",
    },
    "state.py": {
        # is_category("bedroom"): plus_one_per_bedroom dynamic gem cost.
        "bedroom",
    },
    "upgrades.py": {
        # The Upgrade Disk slot table (module-level room-id lists selecting
        # which base rooms have disk variants): an engine-owned enumeration,
        # not per-room behaviour -- exempted by docs/architecture.md
        # itself ("upgrades.py's selection tables ... legitimately name
        # rooms as data").
        "aquarium", "billiard_room", "boudoir", "bunk_room", "cloister",
        "closet", "courtyard", "guest_bedroom", "hallway", "mail_room",
        "nook", "nursery", "parlor", "spare_room", "storeroom",
    },
}

#: module filename -> room ids that module names as string literals for a
#: genuine per-room behaviour branch. Shrink an entry's set when the id's
#: behaviour moves to effects/rooms/<id>.py; never grow one just to make a
#: new branch pass -- add a room module instead.
ROOM_DEBT: dict[str, set[str]] = {
    "effects/tier1.py": set(
        # chapel moved off this list: the Keeper of Tithes coin-banking
        # carve-out inside the shared "grant" tag handler now reads
        # Capability.TITHE (registered by effects/rooms/chapel.py) instead
        # of comparing room.id/variant_of to a literal, so grant() no
        # longer names "chapel" at all.
    ),
    "decks.py": set(
        # treasure_trove/throne_room moved off this list: eligible_pool's pool
        # gate no longer carves out the rooms whose found_floorplan unlock is a
        # dedicated GameConfig bool. config.py::FOUND_FLOORPLAN_FLAGS pairs each
        # flag with its room and GameConfig.unlocked_found_floorplans() unions
        # that with cfg.found_floorplans, so decks.py runs one membership test
        # and names no room. Not a room module -- a room module registers
        # behaviour for a room already in play, and this decides whether the
        # room may be dealt at all -- but the binding now lives beside the flags
        # themselves, which are already named for their rooms.
    ),
    "experiments.py": set(
        # aquarium/aquarium__experiment moved to ROOM_ARCHITECTURE above:
        # add_aquariums's whole job, per the wiki, is injecting copies of
        # these two specific rooms and moving them to the Commonplace
        # bucket -- unlike a generic mechanism with one room carved out
        # (Chapel's former tithe check, the Conference Room cell lookup
        # below), apply_effect's `match effect_id:` dispatch never branches
        # on a room id at all; it dispatches on the effect's own id and
        # hands off to _apply_add_aquariums, whose entire content IS the
        # Aquarium the same way draft.py's own AQUARIUM_EXPERIMENT_ID names
        # this effect's guaranteed-copy taxonomy rule (see draft.py's
        # ROOM_ARCHITECTURE entry, which already treats
        # "aquarium__experiment" this way).
        # conference_room moved off this list: spread_dig_spots's cell
        # lookup now reads Game._capability_cell(Capability.DIG_SPOTS)
        # (registered by effects/rooms/conference_room.py) instead of
        # game.room_cells.get("conference_room") directly.
        # dining_room moved off this list: _room_has_fireplace now reads
        # Capability.DINING_ROOM (registered by
        # effects/rooms/dining_room.py, matched on the room's own id or its
        # variant_of) instead of comparing room.id/variant_of to a literal
        # -- one registration that also clears special_items.py's own
        # "dining_room" entry below.
    ),
    "game.py": {
        # _place_room's carve-out (room.id == "the_foundation"): records the
        # cell/orientation for next-day carryover inside the otherwise
        # generic per-room placement function every drafted room goes
        # through -- the Foundation's own cross-day-persistence behaviour.
        # clock_tower/laboratory/planetarium/room_46/security/utility_closet
        # moved off this list: the Clock Tower's day-end tally now reads
        # Hook.ON_DAY_END_ALL (registered by effects/rooms/clock_tower.py);
        # at_laboratory_terminal/at_planetarium/can_set_security_level/
        # _utility_closet_cell now read dedicated Capability facts
        # (EXPERIMENT_TERMINAL/TELESCOPE_REVEAL/SECURITY_LEVEL/BREAKER_BOX,
        # each registered by that room's own effects/rooms/<id>.py module)
        # instead of comparing a room id directly; room_46 moved to
        # ROOM_ARCHITECTURE above (an area-graph node id, not a room.id
        # branch).
        "the_foundation",
    },
    "shops.py": set(
        # commissary/gift_shop/kitchen/locksmith/showroom/workshop moved off
        # this list: on_enter_shop's `match room.id:` stock-roll dispatch is
        # now a registry (_STOCK_BUILDERS) that each shop's own
        # effects/rooms/<id>.py module populates via
        # shops.register_stock_builder, the same registration shape as
        # room_hook/provides -- shops.py itself no longer names any of the
        # six ids. The Showroom's Trophy of Wealth overlay (formerly a
        # second "showroom" branch in stock_display/buy) moved the same way,
        # via shops.register_stock_overlay. trading_post moved off this list
        # too: _inside_trading_post now reads Capability.TRADE (registered
        # by effects/rooms/trading_post.py) instead of comparing the outer
        # room's id directly. entrance_hall moved off this list:
        # can_smash_vase now reads Capability.VASE (registered by
        # effects/rooms/entrance_hall.py) instead of comparing the room id
        # directly -- see ROOM_ARCHITECTURE above for this module's one
        # remaining "entrance_hall" use.
    ),
    "special_items.py": set(
        # dining_room moved off this list: _maybe_serve_main_course now reads
        # Capability.DINING_ROOM (registered by effects/rooms/dining_room.py)
        # instead of comparing room.id/variant_of to a literal -- the same
        # registration that clears experiments.py's own "dining_room" entry
        # above.
        # lost_and_found moved off this list: the on_enter steal trigger now
        # reads Capability.LOST_AND_FOUND (registered by
        # effects/rooms/lost_and_found.py) instead of comparing room.id
        # directly.
        # vault moved off this list: can_open_vault_box's gate now reads
        # Capability.VAULT (registered by effects/rooms/vault.py) instead of
        # comparing room.id directly.
    ),
}

#: ROOM_DEBT's total entry count. The remaining entry is game.py's
#: the_foundation; decks.py's treasure_trove/throne_room were paid down by
#: moving the found-floorplan flag/room pairing to
#: config.py::FOUND_FLOORPLAN_FLAGS, leaving eligible_pool naming no room.
#: test_room_id_debt_matches_the_cap fails in BOTH directions: above means a
#: new debt entry landed and nobody paid it down; below means a conversion
#: already shrank ROOM_DEBT and nobody lowered this constant to match, which
#: would hide room for the debt to regress back up unnoticed -- see the
#: module docstring for why this mirrors #332's original bidirectional
#: ROOM_ID_ALLOWLIST_CAP rather than test_item_id_allowlist.py's
#: upper-bound-only ITEM_DEBT_CAP.
ROOM_ID_DEBT_CAP = 1


def _combined_allowlist() -> dict[str, set[str]]:
    """Union of ``ROOM_ARCHITECTURE`` and ``ROOM_DEBT`` per module: the single
    view the bidirectional-coverage tests scan against, so splitting the list
    into two does not narrow what is checked."""
    combined: dict[str, set[str]] = {}
    for source in (ROOM_ARCHITECTURE, ROOM_DEBT):
        for module, ids in source.items():
            combined.setdefault(module, set()).update(ids)
    return combined


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant node that is a module/class/function
    docstring, so the scan can skip documentation mentions of a room id
    without needing to strip comments (comments are simply absent from the
    AST already -- this only handles the docstring case, which is a real
    Constant node in the tree)."""
    docstring_ids: set[int] = set()
    containers = [tree] + [n for n in ast.walk(tree)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in containers:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstring_ids.add(id(body[0].value))
    return docstring_ids


def _room_id_literals(path: Path, room_ids: set[str]) -> set[str]:
    """Room-id string literals ``path`` contains outside docstrings.

    Any string ``ast.Constant`` whose value equals a real room id counts,
    regardless of the surrounding expression -- see the module docstring
    for why the scan doesn't try to tell a behaviour branch apart from data
    at the syntax level.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_node_ids(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value in room_ids and id(node) not in skip):
            found.add(node.value)
    return found


def _module_key(path) -> str:
    """Allowlist key: the module's path relative to ``engine/``, slash-joined."""
    return path.relative_to(ENGINE_DIR).as_posix()


def _scanned_paths() -> list:
    """Every engine module the invariant covers, in a stable order.

    ``engine/*.py`` plus ``engine/effects/*.py``: the latter holds shared
    effect-tag handlers, which are engine code and so may not branch on a
    room id. ``engine/effects/rooms/`` is excluded -- that package is where
    room-id binding belongs. ``__init__.py`` files are skipped.
    """
    paths = [p for p in ENGINE_DIR.glob("*.py") if p.name != "__init__.py"]
    paths += [p for p in (ENGINE_DIR / "effects").glob("*.py") if p.name != "__init__.py"]
    return sorted(paths)


def _scan_engine_modules(room_ids: set[str]) -> dict[str, set[str]]:
    """Room-id literal hits per scanned module, keyed by :func:`_module_key`."""
    hits: dict[str, set[str]] = {}
    for path in _scanned_paths():
        found = _room_id_literals(path, room_ids)
        if found:
            hits[_module_key(path)] = found
    return hits


def test_effects_rooms_directory_is_excluded_by_construction():
    """The scan targets ``engine/*.py`` (non-recursive), so
    ``effects/rooms/`` -- where room-id binding belongs -- is never walked;
    this pins that the exclusion holds by construction, not by an
    allowlist entry that could silently rot."""
    assert EFFECTS_ROOMS_DIR.is_dir()
    assert not any(EFFECTS_ROOMS_DIR == p.parent for p in _scanned_paths())


def test_allowlist_keys_are_scanned_modules():
    """A typo'd or stale filename key in either allowlist would silently
    never be checked; every key in ROOM_ARCHITECTURE or ROOM_DEBT must name a
    file the scanner actually walks."""
    scanned = {_module_key(p) for p in _scanned_paths()}
    unknown = set(_combined_allowlist()) - scanned
    assert not unknown, (
        "ROOM_ARCHITECTURE/ROOM_DEBT keys not found under engine/: "
        f"{sorted(unknown)}")


def test_no_room_id_literals_outside_the_allowlist(registry):
    """A room-id literal in a module, or an id within a listed module, that
    isn't on ROOM_ARCHITECTURE or ROOM_DEBT means a new hardcoded room id
    landed in the engine -- the exact regression docs/architecture.md
    exists to catch."""
    room_ids = {r.id for r in registry.rooms}
    hits = _scan_engine_modules(room_ids)
    allowlist = _combined_allowlist()
    unexpected = {
        module: sorted(found - allowlist.get(module, set()))
        for module, found in hits.items()
        if found - allowlist.get(module, set())
    }
    assert not unexpected, (
        "room-id literals found with no ROOM_ARCHITECTURE/ROOM_DEBT entry "
        "(add a room module under engine/effects/rooms/ instead of "
        "extending these lists):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(unexpected.items())))


def test_allowlist_has_no_stale_entries(registry):
    """An id listed in ROOM_ARCHITECTURE or ROOM_DEBT that no longer appears
    in its module means the refactor already happened and nobody shrank the
    list -- left unchecked the allowlist only grows and stops measuring the
    architecture rule."""
    room_ids = {r.id for r in registry.rooms}
    hits = _scan_engine_modules(room_ids)
    stale = {
        module: sorted(ids - hits.get(module, set()))
        for module, ids in _combined_allowlist().items()
        if ids - hits.get(module, set())
    }
    assert not stale, (
        "ROOM_ARCHITECTURE/ROOM_DEBT entries no longer found by the scan -- "
        "shrink the list (the refactor moving these ids to effects/rooms/ "
        "already landed):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(stale.items())))


def test_allowlisted_ids_are_real_rooms(registry):
    """Every id on either allowlist must be a real room id. A typo'd id would
    also fail test_allowlist_has_no_stale_entries (it never appears in a
    scan), but that failure reads as "shrink the list" when the actual fix
    is "fix the typo" -- this gives the accurate message."""
    room_ids = {r.id for r in registry.rooms}
    bad = {module: sorted(ids - room_ids) for module, ids in _combined_allowlist().items()
           if ids - room_ids}
    assert not bad, f"ROOM_ARCHITECTURE/ROOM_DEBT ids that are not real room ids: {bad}"


def test_architecture_and_debt_do_not_overlap():
    """The same id must not be listed in both ROOM_ARCHITECTURE and
    ROOM_DEBT for one module -- an id in both would mean the split can't
    tell whether that occurrence is permanent or migratable, defeating the
    point of separating the two."""
    overlap = {
        module: sorted(ROOM_ARCHITECTURE[module] & ROOM_DEBT[module])
        for module in set(ROOM_ARCHITECTURE) & set(ROOM_DEBT)
        if ROOM_ARCHITECTURE[module] & ROOM_DEBT[module]
    }
    assert not overlap, (
        "ids listed in both ROOM_ARCHITECTURE and ROOM_DEBT for the same "
        f"module: {overlap}")


def test_room_id_debt_matches_the_cap():
    """ROOM_DEBT's total entry count must equal ROOM_ID_DEBT_CAP, not merely
    stay under it -- see the module docstring for why this stays
    bidirectional (the #332 behaviour) even though the split now separates
    architecture from debt: above the cap means a new debt entry landed and
    nobody paid it down; below means a conversion already shrank ROOM_DEBT
    and nobody lowered the cap to match, which would silently let the debt
    grow back up to the stale ceiling without this test ever noticing."""
    total = sum(len(ids) for ids in ROOM_DEBT.values())
    assert total <= ROOM_ID_DEBT_CAP, (
        f"ROOM_DEBT grew to {total} entries, above the {ROOM_ID_DEBT_CAP} "
        "cap -- a new room-id literal landed instead of moving behaviour to "
        "effects/rooms/")
    assert total >= ROOM_ID_DEBT_CAP, (
        f"ROOM_DEBT shrank to {total} entries, below the {ROOM_ID_DEBT_CAP} "
        "cap -- lower ROOM_ID_DEBT_CAP to match, or the cap stops measuring "
        "real debt and hides room for it to regress back up")
