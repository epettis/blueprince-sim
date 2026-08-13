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
justified by an entry on one of the two allowlists below, and the comment on
that entry records the judgement call.

This is a SEPARATE scanner from the effect-tag one in
``test_item_tag_allowlist.py``, not a merged one, because 14 of the 37 effect
tags in ``data/special_items.json`` are spelled identically to a real item id
(``compass``, ``stopwatch``, ``treasure_map``, ``master_key``,
``sleeping_mask``, ``watering_can``, ``emerald_bracelet``,
``ornate_compass``, ``paper_crown``, ``repellent``, ``chronograph``,
``dowsing_rod``, ``gear_wrench``, ``battery_pack``). A merged scanner checking one combined
literal universe would double-count every one of those and make the two
kinds of debt (id branches vs. tag branches) impossible to tell apart in the
allowlists. Item ids are DISJOINT from room ids (verified empirically, see
``test_item_ids_are_disjoint_from_room_ids``), so this scanner does not need
the room scanner's category-name-collision handling for that pair -- but it
still needs its own, since an item-id literal can just as easily be a
resource dict key, a data-section name, or an argument that happens to spell
an id.

The allowlist is split into two dicts of the same shape, ``module filename ->
{item ids}``, matching ``test_room_id_allowlist.py``'s own grain: per-module-id
is the coarsest grain that still answers "did this module stop naming this
item id", without being brittle to line-shuffling refactors that don't change
which ids a module names.

- ``ITEM_ARCHITECTURE`` holds ids that name engine-owned, permanent
  constructs -- a named draft-condition tag, an id-prefix family handled by
  prefix, a table/graph carve-out, or a member of a named total-order tuple
  (an ItemHook priority chain or an equivalent first-applicable-wins tool
  ordering). These entries are not expected to shrink; the module docstring
  on each id-prefix or priority-tuple block explains why the id has to be
  named there.
- ``ITEM_DEBT`` holds ids that name a genuine per-item behaviour branch --
  the kind task 22's migration moves into ``engine/effects/items/<id>.py``.
  This is the number later phases drive down.

Both dicts are scanned together (see ``_combined_allowlist``), so splitting
the list does not narrow what the bidirectional checks cover. Three failure
modes are load-bearing:
- an item-id literal appears in a scanned module for an id not listed in
  either dict for that module (the architecture is regressing -- a new
  hardcoded id landed and nobody updated a list),
- an id listed in either dict no longer appears in its module (the refactor
  already happened and nobody shrank the list -- left unchecked a list only
  ever grows and stops measuring anything), and
- the same id is listed in both dicts for the same module (the split itself
  has become ambiguous about which bucket the id's debt belongs in).

A fourth check, ``test_item_debt_does_not_exceed_the_cap``, pins
``ITEM_DEBT``'s total at its current size: architecture may grow (a new
priority tuple or id-prefix family is a legitimate engine addition), but
debt may not -- that asymmetry is the entire point of the split.
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

#: Where task 22's per-item registry migration puts item behaviour, one
#: module per carrier item; the scan excludes it by construction
#: (non-recursive glob over effects/*.py) rather than by allowlist entry, so
#: it required no edit here. See
#: test_effects_subdirectories_are_excluded_by_construction.
EFFECTS_ITEMS_DIR = ENGINE_DIR / "effects" / "items"

#: module filename -> item ids that module names as string literals for a
#: permanent, engine-owned reason: a named draft-condition tag, an
#: id-prefix family handled by prefix, a table/graph carve-out, or a member
#: of a named total-order tuple. These entries are not expected to shrink.
ITEM_ARCHITECTURE: dict[str, set[str]] = {
    "draft.py": {
        # active_conditions_from_state emits "chronograph" as a
        # priority_draws.json condition-tag name into the draft's active-condition
        # set, right alongside non-item-id condition tags like "electromagnet" --
        # the same condition-vocabulary machinery this function owns for every
        # drafting bias flag, not an item-id branch. (The literal is also
        # accounted for on the tag allowlist in test_item_tag_allowlist.py, since
        # a dumb id scanner cannot tell a same-spelled tag from an id.)
        "chronograph",
    },
    "game.py": {
        # LOCK_PENDING's special-keys-menu dispatch (_special_key_held/
        # _special_key_fits/use_special_key_at_lock): data/locks.json's
        # special_key_menu.order names exactly these six ids (the wiki's
        # published fixed row order), and the dispatch has to name each one
        # to route to its own effects/items/<id>.py held()/fits() pair (or,
        # for the three reserved ids, to decline outright) -- the same
        # engine-owned, first-applicable-wins-shaped table carve-out as
        # special_items.py's DIG_PRIORITY/lock-pick preference order below.
        "basement_key", "key_8", "master_key", "prism_key",
        "secret_garden_key", "silver_key",
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
        # from the shuffled cycle (spawned outside the generic pipeline via
        # special_items.PIPELINE_EXCLUDED) -- table/graph data, not a
        # per-item behaviour branch.
        "upgrade_disk_trade", "allowance_token", "keycard",
        # Bacon & Eggs inject_rooms gate-condition frozenset: the same
        # draft-condition tag vocabulary as placement.py's own condition
        # dispatch above (the set also holds non-item tags "breakfast",
        # "knight_chess_piece", "room8_key"), not an item-id branch.
        "secret_garden_key",
    },
    "special_items.py": {
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
        # Allowance Token pair: the Underpass-specific grant site names the
        # variant id alongside the base Allowance Token.
        "allowance_token", "allowance_token_underpass",
        # DIG_PRIORITY (jack_hammer > detector_shovel > shovel, dig_all's
        # table-selection order, shared with shops.py's doorstep auto-dig) and
        # the lock-pick preference order in open_locked_free (prefer
        # pick_sound_amplifier over lock_pick_kit when both are held): both
        # are engine-owned first-applicable-wins tool orderings, the same
        # shape as the ItemHook priority tuples below, naming their member
        # ids by design.
        "detector_shovel", "jack_hammer", "lock_pick_kit",
        "pick_sound_amplifier", "shovel",
        # The engine-owned total order for each ItemHook chain
        # (GEM_COST_PRIORITY, MOVE_STEP_COST_PRIORITY, COINS_GRANTED_PRIORITY,
        # GEM_PAYMENT_WAIVER_PRIORITY, RED_ROOM_NEGATE_PRIORITY,
        # FOOD_STEPS_PIPELINE) has to name its member item ids somewhere --
        # never a priority= number on the item_hook registration, which
        # would scatter the order across the very modules it ranks. Each
        # item's own applicability logic still lives in its
        # engine/effects/items/<id>.py module.
        "coin_purse", "emerald_bracelet", "hall_pass", "knights_shield",
        "lucky_purse", "running_shoes", "salt_shaker", "silver_spoon",
        "stopwatch",
        # SpecialItemsRegistry.treasure_map field load (raw["treasure_map"]):
        # the "treasure_map" data SECTION (cells/rewards table), a published
        # table this module keeps loading -- not the item-id branch, which
        # moved to effects/items/treasure_map.py (phase 6). Coincidentally
        # spelled the same as the item id, like the 14 id/tag collisions
        # test_item_id_allowlist.py's docstring documents.
        "treasure_map",
        # SpecialItemsRegistry.battery_pack field load
        # (raw.get("battery_pack", {})): the "battery_pack" data SECTION
        # (room id, rarity options), the same table-carve-out shape as
        # treasure_map directly above -- the item-id behaviour branch itself
        # (grant/pickup) lives in effects/items/battery_pack.py, not here.
        "battery_pack",
    },
}

#: module filename -> item ids that module names as string literals for a
#: genuine per-item behaviour branch. Shrink an entry's set when the id's
#: behaviour moves to effects/items/<id>.py; never grow one just to make a
#: new branch pass -- that is the debt this file measures, and
#: test_item_debt_does_not_exceed_the_cap pins the current total as a
#: ceiling so it cannot quietly grow either.
ITEM_DEBT: dict[str, set[str]] = {
    "shops.py": {
        # Royal Scepter / Entrance Hall vase chip: the vase-smash microchip
        # grant belongs to the (out of scope) Microchip branch. royal_scepter
        # moved off this list (phase 5a); car_keys moved off (phase 5b): its
        # locksmith fallback-list literal is now car_keys.ITEM_ID, which
        # names no string literal here.
        "microchip",
        # lunch_box, repellent, and stopwatch moved off this list (phase 5a):
        # their reads are now effects/items/ module functions
        # (lunch_box.hide_from_gift_shop/on_purchased, repellent.held/
        # consume, stopwatch.blocks_as_trade_return), which name no string
        # literal here.
    },
    "special_items.py": set(
        # compass, cursed_effigy, lunch_box, royal_scepter, sleeping_mask,
        # and watering_can moved off this list (phase 5a), alongside
        # chronograph, emerald_bracelet, master_key, and ornate_compass from
        # earlier phases; key_8 and silver_key also moved off in phase 5a.
        # battery_pack, broken_lever, car_keys, keycard, and secret_garden_key
        # moved off this list (phase 5b): their reads are now
        # effects/items/ module functions or ITEM_ID references (keycard.held/
        # grant/steal/roll_source_room_grant, secret_garden_key.held/
        # consume_on_place, battery_pack.ITEM_ID, broken_lever.ITEM_ID,
        # sledge_hammer.ITEM_ID, car_keys.ITEM_ID), which name no string
        # literal here. game.py's own keycard entry moved off entirely
        # (phase 5b): its lock_rules lookup is now
        # keycard.roll_source_room_grant. moon_pendant and treasure_map moved
        # off this list (phase 6): their reads are now
        # effects/items/moon_pendant.py (carry_over) and
        # effects/items/treasure_map.py (resolve_cell/dig_reward). The one
        # remaining "treasure_map" occurrence in special_items.py (the data
        # section load) is a table carve-out, listed on ITEM_ARCHITECTURE
        # instead.
    ),
}

#: ITEM_DEBT's total size after task 22 phase 6's migration (was 3 at the
#: phase 5b split; 1 remains -- microchip -- which belongs to the out-of-scope
#: Microchip branch). test_item_debt_does_not_exceed_the_cap fails if a
#: change raises it, so debt can only ratchet down from here.
ITEM_DEBT_CAP = 1


def _combined_allowlist() -> dict[str, set[str]]:
    """Union of ``ITEM_ARCHITECTURE`` and ``ITEM_DEBT`` per module: the single
    view the bidirectional-coverage tests scan against, so splitting the list
    into two does not narrow what is checked."""
    combined: dict[str, set[str]] = {}
    for source in (ITEM_ARCHITECTURE, ITEM_DEBT):
        for module, ids in source.items():
            combined.setdefault(module, set()).update(ids)
    return combined


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
    and ``effects/items/`` are never walked; this pins both exclusions as
    holding by construction (a non-recursive glob), not an allowlist entry
    that could silently rot."""
    assert EFFECTS_ROOMS_DIR.is_dir()
    assert not any(EFFECTS_ROOMS_DIR == p.parent for p in _scanned_paths())
    assert not any(EFFECTS_ITEMS_DIR == p.parent for p in _scanned_paths())


def test_allowlist_keys_are_scanned_modules():
    """A typo'd or stale filename key in either allowlist would silently
    never be checked; every key in ITEM_ARCHITECTURE or ITEM_DEBT must name a
    file the scanner actually walks."""
    scanned = {_module_key(p) for p in _scanned_paths()}
    unknown = set(_combined_allowlist()) - scanned
    assert not unknown, (
        "ITEM_ARCHITECTURE/ITEM_DEBT keys not found under engine/: "
        f"{sorted(unknown)}")


def test_no_item_id_literals_outside_the_allowlist(registry):
    """An item-id literal in a module, or an id within a listed module, that
    isn't on ITEM_ARCHITECTURE or ITEM_DEBT means a new hardcoded item id
    landed in the engine -- the same regression test_room_id_allowlist.py
    exists to catch for rooms, now closed for items too."""
    item_ids = {i.id for i in registry.special.items}
    hits = _scan_engine_modules(item_ids)
    allowlist = _combined_allowlist()
    unexpected = {
        module: sorted(found - allowlist.get(module, set()))
        for module, found in hits.items()
        if found - allowlist.get(module, set())
    }
    assert not unexpected, (
        "item-id literals found with no ITEM_ARCHITECTURE/ITEM_DEBT entry "
        "(add an item module under engine/effects/items/ instead of "
        "extending these lists):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(unexpected.items())))


def test_allowlist_has_no_stale_entries(registry):
    """An id listed in ITEM_ARCHITECTURE or ITEM_DEBT that no longer appears
    in its module means the refactor already happened and nobody shrank the
    list -- left unchecked a list only grows and stops measuring the debt
    task 22 tracks."""
    item_ids = {i.id for i in registry.special.items}
    hits = _scan_engine_modules(item_ids)
    stale = {
        module: sorted(ids - hits.get(module, set()))
        for module, ids in _combined_allowlist().items()
        if ids - hits.get(module, set())
    }
    assert not stale, (
        "ITEM_ARCHITECTURE/ITEM_DEBT entries no longer found by the scan -- "
        "shrink the list (the refactor moving these ids to effects/items/ "
        "already landed):\n  "
        + "\n  ".join(f"{m}: {ids}" for m, ids in sorted(stale.items())))


def test_architecture_and_debt_do_not_overlap():
    """The same id must not be listed in both ITEM_ARCHITECTURE and ITEM_DEBT
    for one module -- an id in both would mean the split can't tell whether
    that occurrence is permanent or migratable, defeating the point of
    separating the two."""
    overlap = {
        module: sorted(ITEM_ARCHITECTURE[module] & ITEM_DEBT[module])
        for module in set(ITEM_ARCHITECTURE) & set(ITEM_DEBT)
        if ITEM_ARCHITECTURE[module] & ITEM_DEBT[module]
    }
    assert not overlap, (
        "ids listed in both ITEM_ARCHITECTURE and ITEM_DEBT for the same "
        f"module: {overlap}")


def test_item_debt_does_not_exceed_the_cap():
    """ITEM_DEBT's total entry count must not exceed ITEM_DEBT_CAP: debt may
    shrink as items migrate to effects/items/<id>.py, but it may not grow,
    unlike ITEM_ARCHITECTURE which can legitimately gain a new priority-tuple
    member or id-prefix family."""
    total = sum(len(ids) for ids in ITEM_DEBT.values())
    assert total <= ITEM_DEBT_CAP, (
        f"ITEM_DEBT grew to {total} entries, above the {ITEM_DEBT_CAP} cap -- "
        "a new debt entry was added instead of being migrated away")


def test_allowlisted_ids_are_real_items(registry):
    """Every id on either allowlist must be a real item id. A typo'd id would
    also fail test_allowlist_has_no_stale_entries (it never appears in a
    scan), but that failure reads as "shrink the list" when the actual fix
    is "fix the typo" -- this gives the accurate message."""
    item_ids = {i.id for i in registry.special.items}
    bad = {
        module: sorted(ids - item_ids)
        for module, ids in _combined_allowlist().items()
        if ids - item_ids
    }
    assert not bad, f"ITEM_ARCHITECTURE/ITEM_DEBT ids that are not real item ids: {bad}"


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
