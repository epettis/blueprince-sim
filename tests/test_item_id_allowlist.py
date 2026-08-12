"""Measures and freezes the item-id debt tracked by task 22: a per-item
registry migration (moving item behaviour out of the shared modules below
into ``engine/effects/items/<item_id>.py``, one file per item, the same shape
``engine/effects/rooms/`` already gives rooms) is planned but has not
started. This test does not implement that migration -- it exists so a later
phase can be *shown* to reduce debt rather than merely claimed to.

Mirrors ``tests/test_room_id_allowlist.py`` in both structure and rationale:
the scanner is deliberately dumb. It flags every string literal in
``engine/*.py`` (plus ``engine/effects/*.py``, excluding ``effects/rooms/``)
that equals a real item id, with no attempt to guess whether the site is a
behaviour branch (``special_items.has(st, "paper_crown")``), a fixture
lookup, or incidental data that happens to collide with an item id --
guessing that distinction from syntax would hide exactly the cases a human
most needs to re-examine after a refactor. Every occurrence must instead be
justified by an entry on the allowlist below, and the comment on that entry
records the judgement call.

This is a SEPARATE scanner from the effect-tag one in
``test_item_tag_allowlist.py``, not a merged one, because 13 of the 37 effect
tags in ``data/special_items.json`` are spelled identically to a real item id
(``compass``, ``stopwatch``, ``treasure_map``, ``master_key``,
``sleeping_mask``, ``watering_can``, ``emerald_bracelet``,
``ornate_compass``, ``paper_crown``, ``repellent``, ``chronograph``,
``dowsing_rod``, ``gear_wrench``). A merged scanner checking one combined
literal universe would double-count every one of those and make the two
kinds of debt (id branches vs. tag branches) impossible to tell apart in the
allowlist. Item ids are DISJOINT from room ids (verified empirically, see
``test_item_ids_are_disjoint_from_room_ids``), so this scanner does not need
the room scanner's category-name-collision handling for that pair -- but it
still needs its own, since an item-id literal can just as easily be a
resource dict key, a data-section name, or an argument that happens to spell
an id.

The allowlist is keyed ``module filename -> {item ids}``, matching
``test_room_id_allowlist.py``'s own grain: per-module-id is the coarsest
grain that still answers "did this module stop naming this item id", without
being brittle to line-shuffling refactors that don't change which ids a
module names.

Two failure modes, both load-bearing:
- an item-id literal appears in a scanned module for an id not listed for
  that module (the architecture is regressing -- a new hardcoded id landed
  and nobody updated the list), and
- an allowlisted id no longer appears in its module (the refactor already
  happened and nobody shrank the list -- left unchecked the list only ever
  grows and stops measuring anything, exactly the failure mode task 22's
  architecture pass flagged as missing entirely for items before this file
  existed).
"""

from __future__ import annotations

import ast
from pathlib import Path

from blueprince_sim.engine import model as _model_module

#: Direct children of engine/ only (non-recursive), matching
#: test_room_id_allowlist.py's own scan scope exactly -- see that module's
#: docstring for why effects/tier1.py is in scope but effects/rooms/ is not.
ENGINE_DIR = Path(_model_module.__file__).resolve().parent

#: Room-specific behaviour lives here and is out of this scanner's business
#: entirely (it is excluded from the scan by construction, not by allowlist
#: entry -- see test_effects_subdirectories_are_excluded_by_construction).
EFFECTS_ROOMS_DIR = ENGINE_DIR / "effects" / "rooms"

#: Where task 22's per-item registry migration puts item behaviour (phase 2
#: landed it, holding only coupon_book.py so far); the scan excludes it by
#: construction (non-recursive glob over effects/*.py) rather than by
#: allowlist entry, so it required no edit here. See
#: test_effects_subdirectories_are_excluded_by_construction.
EFFECTS_ITEMS_DIR = ENGINE_DIR / "effects" / "items"

#: module filename -> item ids that module may name as string literals.
#: Every id here must currently appear in the module's scan (enforced by
#: test_allowlist_has_no_stale_entries) and no other item-id literal may
#: appear in a listed module or in any unlisted engine module (enforced by
#: test_no_item_id_literals_outside_the_allowlist). Shrink an entry's set
#: when the id's behaviour moves to effects/items/<id>.py; never grow one
#: just to make a new branch pass -- that is the debt this file measures.
ITEM_ALLOWLIST: dict[str, set[str]] = {
    "draft.py": {
        # Not an id branch: "chronograph" here is the effect TAG, which is
        # spelled identically to the item id (one of the 13 collisions this
        # file and test_item_tag_allowlist.py are kept separate for). The
        # tag scanner is where it is really accounted for; this entry exists
        # only because a dumb id scanner cannot tell the two apart.
        "chronograph",
    },
    "game.py": {
        # Silver Key: for_draft consumption + silver_key_draft bias flag
        # (locked-door open path) -- a genuine id branch.
        "silver_key",
        # Paper Crown: has(st, "paper_crown") gates the +1 free redraw on an
        # all-non-red initial deal.
        "paper_crown",
        # Power Hammer: has(st, "power_hammer") feeds the sealed-entrance
        # broken flag alongside the config/state fallbacks.
        "power_hammer",
        # registry.lock_rules["keycard"] table lookup + items_found_log
        # label: the Keycard's spawn/state is owned by locks.py rather than
        # the generic special_items pipeline (it is PIPELINE_EXCLUDED), so
        # this is the one place its id is named outside special_items.py.
        "keycard",
    },
    "placement.py": {
        # satisfies_draft_conditions: "secret_garden_key" is a named
        # draft-condition tag (Secret Garden's key gate), rooms/conditions
        # as data rather than an id branch -- the same exemption shape
        # test_room_id_allowlist.py gives placement.py's room conditions.
        "secret_garden_key",
    },
    "shops.py": {
        # _roll_trade_graph's tier-5 special outcome (50/50 with
        # allowance_token) and its item.tier == 5 exclusion of "keycard"
        # from the shuffled cycle (spawned outside the generic pipeline).
        "upgrade_disk_trade", "allowance_token", "keycard",
        # Special-key fallback list (car_keys / silver_key), rolled when no
        # priority-list key is available.
        "car_keys", "silver_key",
        # Gift Shop one-time-purchase filter: lunch_box hidden once
        # cfg.lunch_box_unlocked.
        "lunch_box",
        # Royal Scepter / Entrance Hall vase chip: day-start carry-over
        # grants, plus can_activate_scepter's has() gate and the vase-smash
        # microchip grant.
        "royal_scepter", "microchip",
        # can_use_repellent/use_repellent: has()/remove() on the Repellent
        # item id (illegal-target room ids are a separate allowlist entry on
        # test_room_id_allowlist.py, not this one).
        "repellent",
        # Bacon & Eggs inject_rooms gate-condition frozenset, mirroring
        # placement.py's own condition tags so an injected room's draft
        # condition is satisfied.
        "secret_garden_key",
        # item.effect("stopwatch") argument: the Stopwatch's item id and its
        # own effect tag are spelled identically (one of the 13 collisions),
        # so this same literal also appears on the tag allowlist for the
        # same site.
        "stopwatch",
    },
    "special_items.py": {
        # Not an id branch: the effect TAG "chronograph", spelled identically
        # to the item id, read by chronograph_active_from_state. Accounted
        # for properly in test_item_tag_allowlist.py.
        "chronograph",
        # Sanctum Key family: SANCTUM_KEY_IDS module constant (sorted for
        # deterministic spend order) plus the per-site grant call that names
        # each key individually when its own room/area is first reached.
        "sanctum_key_clock_tower", "sanctum_key_mechanarium",
        "sanctum_key_music_room", "sanctum_key_reservoir_north",
        "sanctum_key_room_46", "sanctum_key_safehouse",
        "sanctum_key_throne_room", "sanctum_key_vault",
        # Vault deposit-box family: the four box-source ids walked in a
        # fixed order when awarding a box.
        "vault_key_149", "vault_key_233", "vault_key_304", "vault_key_370",
        # Upgrade Disk family: per-disk id checks (already spent / still
        # available) that must name their own disk id individually.
        "upgrade_disk_garage", "upgrade_disk_mechanarium",
        "upgrade_disk_mine_south",
        # Fabrication-chain and dig-tool ids: DIG_PRIORITY ordering plus the
        # individual has()/remove() calls each recipe or dig-tool check
        # performs on its own inputs/output.
        "battery_pack", "broken_lever", "cursed_effigy", "detector_shovel",
        "jack_hammer", "lock_pick_kit", "pick_sound_amplifier", "shovel",
        "sledge_hammer",
        # Allowance Token pair: the Underpass-specific grant site names the
        # variant id alongside the base Allowance Token.
        "allowance_token", "allowance_token_underpass",
        # Key-family ids with their own bespoke pickup/spend logic distinct
        # from the generic spawn pipeline.
        "car_keys", "key_8", "keycard", "silver_key", "secret_garden_key",
        # Per-item bespoke behaviour hooks: each item's own effect handler
        # names its id directly (has()/remove()/_is_available() calls)
        # rather than going through a shared tag dispatch.
        "compass", "emerald_bracelet", "lunch_box", "master_key",
        "moon_pendant", "ornate_compass", "royal_scepter", "sleeping_mask",
        "stopwatch", "treasure_map", "watering_can",
    },
}


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant node that is a module/class/function
    docstring, so the scan can skip documentation mentions of an item id
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


def _item_id_literals(path: Path, item_ids: set[str]) -> set[str]:
    """Item-id string literals ``path`` contains outside docstrings.

    Any string ``ast.Constant`` whose value equals a real item id counts,
    regardless of the surrounding expression -- see the module docstring for
    why the scan doesn't try to tell a behaviour branch apart from data at
    the syntax level.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_node_ids(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value in item_ids and id(node) not in skip):
            found.add(node.value)
    return found


def _module_key(path) -> str:
    """Allowlist key: the module's path relative to ``engine/``, slash-joined."""
    return path.relative_to(ENGINE_DIR).as_posix()


def _scanned_paths() -> list:
    """Every engine module the invariant covers, in a stable order.

    ``engine/*.py`` plus ``engine/effects/*.py``: the latter holds shared
    effect-tag handlers, which are engine code and so may not branch on an
    item id any more than a room id. ``engine/effects/rooms/`` (and, when it
    exists, ``engine/effects/items/``) is excluded because both are
    non-recursive-glob subdirectories, not top-level ``.py`` siblings.
    ``__init__.py`` files are skipped.
    """
    paths = [p for p in ENGINE_DIR.glob("*.py") if p.name != "__init__.py"]
    paths += [p for p in (ENGINE_DIR / "effects").glob("*.py") if p.name != "__init__.py"]
    return sorted(paths)


def _scan_engine_modules(item_ids: set[str]) -> dict[str, set[str]]:
    """Item-id literal hits per scanned module, keyed by :func:`_module_key`."""
    hits: dict[str, set[str]] = {}
    for path in _scanned_paths():
        found = _item_id_literals(path, item_ids)
        if found:
            hits[_module_key(path)] = found
    return hits


def test_effects_subdirectories_are_excluded_by_construction():
    """The scan targets ``engine/*.py`` (non-recursive), so ``effects/rooms/``
    and the not-yet-created ``effects/items/`` are never walked; this pins
    both exclusions as holding by construction (a non-recursive glob), not
    an allowlist entry that could silently rot, and not a check that could
    ever start passing vacuously once ``effects/items/`` is created."""
    assert EFFECTS_ROOMS_DIR.is_dir()
    assert not any(EFFECTS_ROOMS_DIR == p.parent for p in _scanned_paths())
    assert not any(EFFECTS_ITEMS_DIR == p.parent for p in _scanned_paths())


def test_allowlist_keys_are_scanned_modules():
    """A typo'd or stale filename key in ITEM_ALLOWLIST would silently never
    be checked; every key must name a file the scanner actually walks."""
    scanned = {_module_key(p) for p in _scanned_paths()}
    unknown = set(ITEM_ALLOWLIST) - scanned
    assert not unknown, f"ITEM_ALLOWLIST keys not found under engine/: {sorted(unknown)}"


def test_no_item_id_literals_outside_the_allowlist(registry):
    """An item-id literal in a module, or an id within a listed module, that
    isn't on ITEM_ALLOWLIST means a new hardcoded item id landed in the
    engine -- the same regression test_room_id_allowlist.py exists to catch
    for rooms, now closed for items too."""
    item_ids = {i.id for i in registry.special.items}
    hits = _scan_engine_modules(item_ids)
    unexpected = {
        module: sorted(found - ITEM_ALLOWLIST.get(module, set()))
        for module, found in hits.items()
        if found - ITEM_ALLOWLIST.get(module, set())
    }
    assert not unexpected, (
        "item-id literals found with no ITEM_ALLOWLIST entry (add an item "
        "module under engine/effects/items/ instead of extending this "
        "list):\n  " + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(unexpected.items())))


def test_allowlist_has_no_stale_entries(registry):
    """An allowlisted id that no longer appears in its module means the
    refactor already happened and nobody shrank the list -- left unchecked
    the allowlist only grows and stops measuring the debt task 22 tracks."""
    item_ids = {i.id for i in registry.special.items}
    hits = _scan_engine_modules(item_ids)
    stale = {
        module: sorted(ids - hits.get(module, set()))
        for module, ids in ITEM_ALLOWLIST.items()
        if ids - hits.get(module, set())
    }
    assert not stale, (
        "ITEM_ALLOWLIST entries no longer found by the scan -- shrink the "
        "list (the refactor moving these ids to effects/items/ already "
        "landed):\n  " + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(stale.items())))


def test_allowlisted_ids_are_real_items(registry):
    """Every id on the allowlist must be a real item id. A typo'd id would
    also fail test_allowlist_has_no_stale_entries (it never appears in a
    scan), but that failure reads as "shrink the list" when the actual fix
    is "fix the typo" -- this gives the accurate message."""
    item_ids = {i.id for i in registry.special.items}
    bad = {module: sorted(ids - item_ids) for module, ids in ITEM_ALLOWLIST.items()
           if ids - item_ids}
    assert not bad, f"ITEM_ALLOWLIST ids that are not real item ids: {bad}"


def test_item_ids_are_disjoint_from_room_ids(registry):
    """Pins the empirical fact this scanner's design leans on: unlike room
    ids (which collide with plain-English category names like "bedroom"),
    no item id currently collides with a room id. If this ever goes false,
    both scanners would double-count that id and the two allowlists would
    need reconciling the way the 13 id/tag collisions already are."""
    item_ids = {i.id for i in registry.special.items}
    room_ids = {r.id for r in registry.rooms}
    overlap = item_ids & room_ids
    assert not overlap, f"item ids that also collide with room ids: {sorted(overlap)}"
