"""Measures and freezes the effect-tag debt tracked by task 22, and enforces
the zero-reader rule that catches an authored tag nobody consults (the bug
class that let ``ignition_tool`` carry two sources of truth -- a data table
and code that never read it -- until #199 deleted the tag).

Companion to ``test_item_id_allowlist.py``: read that module's docstring
first for the shared design (deliberately-dumb AST literal scan, per-module
allowlist grain, both load-bearing failure modes). This file is the SEPARATE
tag-side scanner -- required, not stylistic, because 14 of the 37 effect
tags in ``data/special_items.json`` are spelled identically to a real item id
(``compass``, ``stopwatch``, ``treasure_map``, ``master_key``,
``sleeping_mask``, ``watering_can``, ``emerald_bracelet``,
``ornate_compass``, ``paper_crown``, ``repellent``, ``chronograph``,
``dowsing_rod``, ``gear_wrench``, ``battery_pack``). A single merged scanner would see one
string literal like ``"stopwatch"`` and be unable to tell whether the site
names the item or its effect tag, double-counting every collision and
conflating two different kinds of debt.

Two allowlist failure modes, both load-bearing (identical shape to the room
and item-id scanners):
- a tag literal appears in a scanned module with no allowlist entry for it
  (a new hardcoded tag branch landed), and
- an allowlisted tag no longer appears in its module (the refactor landed
  and nobody shrank the list).

A THIRD mechanism lives only in this file: DEFERRED_UNREAD_TAGS.

The architecture pass's original rule was "a tag with zero readers anywhere
in engine/*.py + engine/effects/*.py is a hard failure" -- full stop. Taken
literally that fails immediately: several tags are authored in
special_items.json with no code anywhere consulting the tag string, because
the item is legitimately unimplemented and ``meta.blocked_on`` says why (the
same shape ``implemented: false`` already uses elsewhere, just not
previously audited for the tag itself). Hard-failing on those would make
this file impossible to land without also shipping engine changes, which
this phase explicitly does not do.

So the rule is implemented as a SHRINK-ONLY deferred list instead:
- a zero-reader tag NOT on DEFERRED_UNREAD_TAGS is a hard failure (the
  ignition_tool catch), and
- a tag ON DEFERRED_UNREAD_TAGS that GAINS a reader is *also* a failure,
  demanding the entry be removed -- the same ratchet shape as the two
  allowlists above; the deferred list can only shrink, never grow to wave
  through a new gap.

"Reader" is checked the same deliberately-dumb way as everything else in
this file: an exact string ``ast.Constant`` match, scanned over every ``.py``
file under ``src/`` (broader than the two ``engine/``-only allowlist scans
above, matching the architecture pass's "anywhere in src/" framing) -- not a
semantic check for whether the read site actually *does* anything with the
tag. A read that's itself dead code would still count; that gap is out of
scope for a string-literal scanner and would need a coverage tool instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

from blueprince_sim.engine import model as _model_module

#: Direct children of engine/ only (non-recursive), matching the allowlist
#: scan scope in test_item_id_allowlist.py and test_room_id_allowlist.py.
ENGINE_DIR = Path(_model_module.__file__).resolve().parent

#: engine/src root, for the broader "anywhere in src/" zero-reader scan
#: (see test_zero_reader_tags_are_the_deferred_list below).
SRC_DIR = ENGINE_DIR.parent.parent

#: Room-specific behaviour lives here, excluded from the allowlist scan by
#: construction (non-recursive glob), matching the sibling scanners.
EFFECTS_ROOMS_DIR = ENGINE_DIR / "effects" / "rooms"

#: Where task 22's per-item registry migration puts item behaviour, one
#: module per carrier item -- excluded from the allowlist scan by
#: construction, same as the room-id scanner excludes effects/rooms/. See
#: test_effects_subdirectories_are_excluded_by_construction.
EFFECTS_ITEMS_DIR = ENGINE_DIR / "effects" / "items"

#: module filename -> effect tags that module may name as string literals.
#: Same two-failure-mode contract as ITEM_ALLOWLIST in
#: test_item_id_allowlist.py: every entry must currently appear in its
#: module's scan (test_allowlist_has_no_stale_entries), and no other tag
#: literal may appear anywhere unlisted (test_no_tag_literals_outside_the_allowlist).
ITEM_TAG_ALLOWLIST: dict[str, set[str]] = {
    "effects/tier1.py": {
        # _grant()'s resource-kind dispatch: case "allowance": applies the
        # delta to state.allowance. This is a room-effect currency-kind
        # match (RESOURCES-adjacent), not an item-effect-tag read -- it
        # collides with the Allowance Token's own effect tag only because
        # both name the same underlying resource.
        "allowance",
    },
    # game.py no longer names any tag/id-collision literal (task 22 phase
    # 5a): its former "paper_crown" site is now paper_crown.bonus_redraw in
    # engine/effects/items/paper_crown.py.
    "shops.py": {
        # item.effect("locksmith_rob") gates the Locksmith's rob-on-theft
        # mechanic -- a genuine tag dispatch.
        "locksmith_rob",
        # _has_item_effect(..., "smash") gates smash-capable container
        # opening -- a genuine tag dispatch.
        "smash",
        # "allowance": state.allowance carry-over dict key (day-boundary
        # config export), not a tag read -- collides with the resource name
        # the same way effects/tier1.py's case does.
        "allowance",
        # stopwatch and repellent moved off this entry (phase 5a): their
        # former sites are now stopwatch.blocks_as_trade_return and
        # repellent.held/consume in engine/effects/items/.
    },
    "special_items.py": {
        # The bulk of genuine tag dispatch: every one of these is read via
        # item.effect("<tag>") or _has_item_effect(state, registry, "<tag>")
        # somewhere in this module, gating that item's specific behaviour
        # (spawn/pickup/step/currency/luck modifiers). This is the module
        # task 22's per-item registry would eventually split apart. Eight
        # formerly-listed singleton tags (electromagnet, chronograph,
        # ornate_compass, master_key, emerald_bracelet, food_multiplier,
        # free_hallway_moves, coin_multiplier) moved to per-item
        # ItemCapability registrations in engine/effects/items/ and no
        # longer appear here or in special_items.json. Phase 4 moved five
        # more (coin_interest, food_bonus, free_move_interval,
        # mask_red_room, negate_red_once_per_day) to per-item ItemHook
        # handlers in engine/effects/items/coin_purse.py, salt_shaker.py,
        # running_shoes.py, and knights_shield.py. Phase 5a moved four more
        # (compass -- the tag itself deleted from special_items.json since
        # ItemCapability.COMPASS_BIAS replaced it -- plus sleeping_mask,
        # steps_at_rank, and watering_can, whose reads are now
        # engine/effects/items/sleeping_mask.py, lunch_box.py, and
        # watering_can.py respectively). "moon_pendant_carry" moved off this
        # list (phase 6): its only occurrence was the rng.shuffle substream
        # label, which is now in engine/effects/items/moon_pendant.py.
        "allowance", "auto_collect",
        "dig_tool",
        "lockpick", "luck_bonus",
        "metal_detector_spawns",
        "set_steps_on_pickup",
        "smash", "stopwatch",
        # "treasure_map" section dict key (raw["treasure_map"]: cells,
        # rewards) -- coincides with the tag string spelling, not read via
        # .effect(). The item-id behaviour (has(state, "treasure_map") and
        # both rng.choice draws) moved to
        # engine/effects/items/treasure_map.py (phase 6); this data-section
        # load is the only reason the tag literal still appears here.
        "treasure_map",
        # "battery_pack" section dict key (raw.get("battery_pack", {}): room,
        # options) -- same shape as "treasure_map" directly above. The
        # item-id behaviour (on_pickup/resolve_pending) lives in
        # engine/effects/items/battery_pack.py; this data-section load is the
        # only reason the tag literal still appears here.
        "battery_pack",
    },
}

#: Zero-reader effect tags: authored in data/special_items.json with no
#: code anywhere under src/ reading the tag string, deliberately parked here
#: rather than hard-failing test_zero_reader_tags_are_the_deferred_list.
#: SHRINK-ONLY: removing a tag's last reader without adding it here is a
#: hard failure (the ignition_tool catch); a tag gaining a reader while
#: still listed is *also* a failure, demanding the entry be removed. Every
#: entry names the item that carries the tag and its meta.blocked_on.
DEFERRED_UNREAD_TAGS: frozenset[str] = frozenset({
    # dowsing_rod item: meta.blocked_on=per_slot_luck_boost_not_modeled --
    # effect authored (a per-floorplan-slot luck boost with its own penalty
    # ladder) but per-slot luck isn't modeled; only aggregate luck is.
    "dowsing_rod",
    # gear_wrench item: meta.blocked_on=rarity_change_not_persisted_across_days
    # -- effect authored (a persisted Workshop rarity change) but rarity
    # state doesn't carry across days in the current model.
    "gear_wrench",
})


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant node that is a module/class/function
    docstring, so the scan can skip documentation mentions of a tag without
    needing to strip comments (comments are simply absent from the AST
    already -- this only handles the docstring case, which is a real
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


def _tag_literals(path: Path, tags: set[str]) -> set[str]:
    """Effect-tag string literals ``path`` contains outside docstrings.

    Any string ``ast.Constant`` whose value equals a real effect tag counts,
    regardless of the surrounding expression -- see the module docstring for
    why the scan doesn't try to tell a tag dispatch apart from data at the
    syntax level.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_node_ids(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value in tags and id(node) not in skip):
            found.add(node.value)
    return found


def _module_key(path) -> str:
    """Allowlist key: the module's path relative to ``engine/``, slash-joined."""
    return path.relative_to(ENGINE_DIR).as_posix()


def _scanned_paths() -> list:
    """Every engine module the allowlist covers, in a stable order.

    ``engine/*.py`` plus ``engine/effects/*.py``, excluding
    ``effects/rooms/`` and ``effects/items/`` (both excluded by
    construction: a non-recursive glob never walks into a subdirectory).
    ``__init__.py`` files are skipped. Identical scope to
    test_item_id_allowlist.py's ``_scanned_paths``.
    """
    paths = [p for p in ENGINE_DIR.glob("*.py") if p.name != "__init__.py"]
    paths += [p for p in (ENGINE_DIR / "effects").glob("*.py") if p.name != "__init__.py"]
    return sorted(paths)


def _scan_engine_modules(tags: set[str]) -> dict[str, set[str]]:
    """Tag literal hits per scanned module, keyed by :func:`_module_key`."""
    hits: dict[str, set[str]] = {}
    for path in _scanned_paths():
        found = _tag_literals(path, tags)
        if found:
            hits[_module_key(path)] = found
    return hits


def _all_tags(registry) -> set[str]:
    """Every distinct effect tag named in data/special_items.json."""
    return {e.tag for item in registry.special.items for e in item.effects}


def test_effects_subdirectories_are_excluded_by_construction():
    """The scan targets ``engine/*.py`` (non-recursive), so ``effects/rooms/``
    and ``effects/items/`` are never walked; this pins both exclusions as
    holding by construction (a non-recursive glob), not an allowlist entry
    that could silently rot."""
    assert EFFECTS_ROOMS_DIR.is_dir()
    assert not any(EFFECTS_ROOMS_DIR == p.parent for p in _scanned_paths())
    assert not any(EFFECTS_ITEMS_DIR == p.parent for p in _scanned_paths())


def test_allowlist_keys_are_scanned_modules():
    """A typo'd or stale filename key in ITEM_TAG_ALLOWLIST would silently
    never be checked; every key must name a file the scanner actually
    walks."""
    scanned = {_module_key(p) for p in _scanned_paths()}
    unknown = set(ITEM_TAG_ALLOWLIST) - scanned
    assert not unknown, f"ITEM_TAG_ALLOWLIST keys not found under engine/: {sorted(unknown)}"


def test_no_tag_literals_outside_the_allowlist(registry):
    """A tag literal in a module, or a tag within a listed module, that
    isn't on ITEM_TAG_ALLOWLIST means a new hardcoded effect-tag branch
    landed in the engine -- there was no audit at all for this before task
    22's architecture pass; this closes that hole."""
    tags = _all_tags(registry)
    hits = _scan_engine_modules(tags)
    unexpected = {
        module: sorted(found - ITEM_TAG_ALLOWLIST.get(module, set()))
        for module, found in hits.items()
        if found - ITEM_TAG_ALLOWLIST.get(module, set())
    }
    assert not unexpected, (
        "effect-tag literals found with no ITEM_TAG_ALLOWLIST entry:\n  "
        + "\n  ".join(f"{m}: {tags}" for m, tags in sorted(unexpected.items())))


def test_allowlist_has_no_stale_entries(registry):
    """An allowlisted tag that no longer appears in its module means the
    refactor already happened and nobody shrank the list -- left unchecked
    the allowlist only grows and stops measuring the debt task 22 tracks."""
    tags = _all_tags(registry)
    hits = _scan_engine_modules(tags)
    stale = {
        module: sorted(t - hits.get(module, set()))
        for module, t in ITEM_TAG_ALLOWLIST.items()
        if t - hits.get(module, set())
    }
    assert not stale, (
        "ITEM_TAG_ALLOWLIST entries no longer found by the scan -- shrink "
        "the list:\n  " + "\n  ".join(f"{m}: {t}" for m, t in sorted(stale.items())))


def test_allowlisted_tags_are_real_tags(registry):
    """Every tag on the allowlist must be a real effect tag named in
    data/special_items.json. A typo'd tag would also fail
    test_allowlist_has_no_stale_entries (it never appears in a scan), but
    that failure reads as "shrink the list" when the actual fix is "fix the
    typo" -- this gives the accurate message."""
    tags = _all_tags(registry)
    bad = {module: sorted(t - tags) for module, t in ITEM_TAG_ALLOWLIST.items() if t - tags}
    assert not bad, f"ITEM_TAG_ALLOWLIST tags that are not real effect tags: {bad}"


def _src_py_files() -> list[Path]:
    """Every ``.py`` file under ``src/``, for the broader zero-reader scan
    (wider than the engine-only allowlist scope above, matching the
    architecture pass's "anywhere in src/" framing for this specific
    check)."""
    return sorted(SRC_DIR.rglob("*.py"))


def _tags_with_readers(tags: set[str]) -> set[str]:
    """Tags that appear as an exact string literal anywhere under src/.

    Deliberately a plain AST Constant-equality scan, same as everywhere
    else in this file -- not a semantic "is this read site live code"
    check. See the module docstring for why that's an accepted gap.
    """
    read: set[str] = set()
    for path in _src_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in tags):
                read.add(node.value)
    return read


def test_zero_reader_tags_are_the_deferred_list(registry):
    """A zero-reader tag is either on DEFERRED_UNREAD_TAGS (a known,
    legitimately-unwired gap with a recorded meta.blocked_on) or it's a new
    instance of the ignition_tool bug class: an authored tag nobody
    consults. Either a stray zero-reader tag not on the list, or a listed
    tag that has gained a reader and should have been un-deferred, is a
    failure -- the deferred list may only shrink."""
    tags = _all_tags(registry)
    read = _tags_with_readers(tags)
    unread = tags - read
    undeferred_and_unread = unread - DEFERRED_UNREAD_TAGS
    assert not undeferred_and_unread, (
        "effect tags with zero readers anywhere in src/ and no "
        "DEFERRED_UNREAD_TAGS entry (the ignition_tool bug class -- either "
        "wire a reader or add a justified deferred entry naming "
        "meta.blocked_on):\n  " + "\n  ".join(sorted(undeferred_and_unread)))
    deferred_but_now_read = DEFERRED_UNREAD_TAGS & read
    assert not deferred_but_now_read, (
        "DEFERRED_UNREAD_TAGS entries that now have a reader -- shrink the "
        "list, the gap they were parked for has been closed:\n  "
        + "\n  ".join(sorted(deferred_but_now_read)))


def test_deferred_unread_tags_are_real_tags(registry):
    """Every entry on DEFERRED_UNREAD_TAGS must be a real effect tag; a
    typo'd entry would silently never match anything in
    test_zero_reader_tags_are_the_deferred_list's set difference and stop
    guarding what it claims to."""
    tags = _all_tags(registry)
    bad = DEFERRED_UNREAD_TAGS - tags
    assert not bad, f"DEFERRED_UNREAD_TAGS entries that are not real effect tags: {sorted(bad)}"
