"""Enforces the capability-architecture invariant from docs/open_tasks.md #21:
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
an entry on the allowlist below, and the comment on that entry records the
judgement call.

The allowlist is keyed ``module filename -> {room ids}``, matching the
granularity docs/open_tasks.md's own "measured starting point" table uses.
Per-line tracking would be more precise but brittle to line-shuffling
refactors that don't change which ids a module names; per-module-id is the
coarsest grain that still answers "did this module stop naming this room".

Two failure modes, both load-bearing:
- a room-id literal appears in a scanned module for an id not listed for
  that module (the architecture is regressing -- a new hardcoded id landed
  and nobody updated the list), and
- an allowlisted id no longer appears in its module (the refactor already
  happened and nobody shrank the list -- left unchecked the list only ever
  grows and stops measuring anything, per docs/open_tasks.md #21).
"""

from __future__ import annotations

import ast
from pathlib import Path

from blueprince_sim.engine import model as _model_module

#: Direct children of engine/ only (non-recursive) -- matches
#: docs/open_tasks.md #21's own "measured starting point" table, which
#: enumerates top-level engine modules and nothing under effects/. This
#: also means engine/effects/tier1.py is out of scan scope even though it
#: sits outside effects/rooms/; see test_effects_tier1_gap_is_tracked below.
ENGINE_DIR = Path(_model_module.__file__).resolve().parent

#: Room-specific behaviour is meant to live here, so ids named inside it are
#: the goal, not the debt this test measures.
EFFECTS_ROOMS_DIR = ENGINE_DIR / "effects" / "rooms"

#: module filename -> room ids that module may name as string literals.
#: Every id here must currently appear in the module's scan (enforced by
#: test_allowlist_has_no_stale_entries) and no other room-id literal may
#: appear in a listed module or in any unlisted engine module (enforced by
#: test_no_room_id_literals_outside_the_allowlist). Shrink an entry's set
#: when the id's behaviour moves to effects/rooms/<id>.py; never grow one
#: just to make a new branch pass -- add a room module instead.
ALLOWLIST: dict[str, set[str]] = {
    "effects/tier1.py": {
        # Keeper of Tithes banks a Chapel coin loss before it is taken,
        # matched on the room and its variants -- a genuine id branch in
        # shared tag-handler code, and the clearest single target for a
        # room module under effects/rooms/.
        "chapel",
        # Category name, not a room reference: grant_per_category adds
        # game.bedroom_bonus when counting the bedroom category. Blue
        # Prince has a room literally named Bedroom, so the two are
        # textually identical and the scanner cannot tell them apart.
        "bedroom",
    },
    "decks.py": {
        # Pool inclusion has an explicit Treasure Trove blackprint carve-out
        # (cfg.treasure_trove_blackprint) alongside the pool-tag rule.
        "treasure_trove",
    },
    "draft.py": {
        # Module-level *_ID constants (CLOSET_ID, TUNNEL_ID, LIBRARY_ID,
        # MECHANARIUM_ID, DARKROOM_ID, READING_NOOK_ID,
        # AQUARIUM_EXPERIMENT_ID, ROTUNDA_ID) -- named constants, still id
        # branches.
        "closet", "tunnel", "library", "mechanarium", "darkroom",
        "reading_nook__ix99", "aquarium__experiment",
        # Same-hand dedup exemption so a Tunnel chain / Aquarium experiment
        # copy can be dealt more than once.
        "chamber_of_mirrors",
        # Garage forced-draw roll (dead-end gate + priority_draws entry).
        "garage",
        # Schoolhouse-placed category-bias condition tag.
        "schoolhouse",
        # Rank-3 90% Foundation removal-from-pool roll.
        "the_foundation",
        # SECRET_PASSAGE_IDS: the Secret Passage and its Spare, exempt from
        # normal drafting and from being drawn during a colour-selective draft.
        "secret_passage", "spare_secret_passage__ix138",
        # Category names, not room references: the colour-selective filter
        # names the five selectable colours. Blue Prince has rooms called
        # Bedroom and Hallway, so the two are textually identical here.
        "bedroom", "hallway",
    },
    "experiments.py": {
        # add_aquariums module constants (AQUARIUM_BASE_ID,
        # AQUARIUM_EXPERIMENT_ID) driving the Aquarium injection effect.
        "aquarium", "aquarium__experiment",
        # is_category("bedroom") / is_category("hallway") arguments --
        # category checks, not id comparisons; "bedroom" and "hallway"
        # collide with real room ids only because those categories also
        # name an undecorated base room.
        "bedroom", "hallway",
        # room_cells.get("conference_room") existence gate for the Grounds
        # dig-spot-cap effect.
        "conference_room",
    },
    "game.py": {
        # Fixture lookups in reset()/anchor-building: the day always starts
        # in the Entrance Hall and the Antechamber is placed as a fixture.
        "entrance_hall", "antechamber",
        # room.id == "break_room__ix11": one-day keycard pulse grant.
        "break_room__ix11",
        # by_id["clock_tower"].idx grid-presence check: day-end Tomorrow-room
        # key tally, gated on the Clock Tower itself being on the grid.
        "clock_tower",
        # Anchor-dict key + r.id.startswith("garage") upgrade-family match
        # (pathfinding hint) alongside the room_cells.get() lookup.
        "garage",
        # room.id == "laboratory" special-move gate.
        "laboratory",
        # dest == "room_46" / area_route_cost("room_46") / room46_reached
        # first-arrival bookkeeping.
        "room_46",
        # room_cells.get("security") position check.
        "security",
        # RedrawKind.STUDY = "study": an enum tag, not a room.id comparison
        # -- happens to spell the Study's id because that room names the
        # mechanic (gem-cost redraws).
        "study",
        # Fixture placement at cfg.foundation_cell + room.id ==
        # "the_foundation" first-draft bookkeeping + anchor-dict key.
        "the_foundation",
        # room_cells.get("utility_closet") lookup (security/power wiring).
        "utility_closet",
    },
    "locks.py": {
        # Security-door capability keyed to the Security room's presence.
        "security",
    },
    "placement.py": {
        # Named draft-condition primitives (satisfies_draft_conditions):
        # rooms as data, not id branches -- exempted by docs/open_tasks.md
        # #21 itself ("placement.py's named conditions legitimately name
        # rooms as data").
        "garage", "boiler_room", "gift_shop", "morning_room",
        "the_foundation", "the_pool",
    },
    "shops.py": {
        # _REPELLENT_ILLEGAL_TARGETS frozenset (the day-start room, the win
        # room, the secret room can never be banned) plus a genuine
        # room.id != "entrance_hall" gate on the vase-smash action.
        "entrance_hall", "antechamber", "room_46",
        # SCEPTER_COLORS tuple: floorplan *category* names for the Royal
        # Scepter, not room ids -- "bedroom"/"hallway" collide with real
        # room ids the same way experiments.py's is_category() calls do.
        "bedroom", "hallway",
        # match room.category / room.id: case "<shop>": per-shop stock
        # builders -- the clearest behaviour branches in the file, and the
        # ones docs/open_tasks.md #21 names as the pattern-setter to fix.
        "commissary", "gift_shop", "kitchen", "locksmith", "showroom",
        "trading_post", "workshop",
    },
    "special_items.py": {
        # room.id == "dining_room" / variant_of == "dining_room": the Dining
        # Room main course check (the same comparison for the Lunch Box's
        # guaranteed grant moved to engine/effects/items/lunch_box.py).
        "dining_room",
        # ENTRANCE_HALL_ROOM_ID constant: containers_in() + room.id ==
        # comparison gating Entrance Hall container spawns.
        "entrance_hall",
        # room.id != "garage" / membership in the Garage upgrade-id family.
        "garage",
        # room.id == "lost_and_found" steal trigger, plus the same string
        # reused as an RNG substream name and a grant() source label.
        "lost_and_found",
        # MECHANARIUM_ROOM_ID constant: room.id == comparison +
        # room_cells.get() gating Mechanarium-specific item behaviour.
        "mechanarium",
        # room.id == "secret_garden" key-consumption branch.
        "secret_garden",
        # KINDS = (..., "showroom", ...): an inventory-item *kind* tag
        # ("showroom exhibit" items), not a room id -- collides with the
        # real Showroom room's id the same way the category names do.
        "showroom",
        # room.id != "vault" gate on vault-box deposit/withdraw actions.
        "vault",
    },
    "state.py": {
        # is_category("bedroom"): plus_one_per_bedroom dynamic gem cost.
        "bedroom",
    },
    "upgrades.py": {
        # Upgrade Disk selection tables: rooms as data, not id branches --
        # exempted by docs/open_tasks.md #21 itself ("upgrades.py's
        # selection tables ... legitimately name rooms as data").
        "aquarium", "billiard_room", "boudoir", "bunk_room", "cloister",
        "closet", "courtyard", "guest_bedroom", "hallway", "mail_room",
        "nook", "nursery", "parlor", "spare_room", "storeroom",
    },
}


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
    """A typo'd or stale filename key in ALLOWLIST would silently never be
    checked; every key must name a file the scanner actually walks."""
    scanned = {_module_key(p) for p in _scanned_paths()}
    unknown = set(ALLOWLIST) - scanned
    assert not unknown, f"ALLOWLIST keys not found under engine/: {sorted(unknown)}"


def test_no_room_id_literals_outside_the_allowlist(registry):
    """A room-id literal in a module, or an id within a listed module, that
    isn't on ALLOWLIST means a new hardcoded room id landed in the engine --
    the exact regression docs/open_tasks.md #21 exists to catch."""
    room_ids = {r.id for r in registry.rooms}
    hits = _scan_engine_modules(room_ids)
    unexpected = {
        module: sorted(found - ALLOWLIST.get(module, set()))
        for module, found in hits.items()
        if found - ALLOWLIST.get(module, set())
    }
    assert not unexpected, (
        "room-id literals found with no ALLOWLIST entry (add a room module "
        "under engine/effects/rooms/ instead of extending this list):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(unexpected.items())))


def test_allowlist_has_no_stale_entries(registry):
    """An allowlisted id that no longer appears in its module means the
    refactor already happened and nobody shrank the list -- left unchecked
    the allowlist only grows and stops measuring the architecture rule."""
    room_ids = {r.id for r in registry.rooms}
    hits = _scan_engine_modules(room_ids)
    stale = {
        module: sorted(ids - hits.get(module, set()))
        for module, ids in ALLOWLIST.items()
        if ids - hits.get(module, set())
    }
    assert not stale, (
        "ALLOWLIST entries no longer found by the scan -- shrink the list "
        "(the refactor moving these ids to effects/rooms/ already landed):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(stale.items())))


def test_allowlisted_ids_are_real_rooms(registry):
    """Every id on the allowlist must be a real room id. A typo'd id would
    also fail test_allowlist_has_no_stale_entries (it never appears in a
    scan), but that failure reads as "shrink the list" when the actual fix
    is "fix the typo" -- this gives the accurate message."""
    room_ids = {r.id for r in registry.rooms}
    bad = {module: sorted(ids - room_ids) for module, ids in ALLOWLIST.items()
           if ids - room_ids}
    assert not bad, f"ALLOWLIST ids that are not real room ids: {bad}"
