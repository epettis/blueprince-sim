"""Upgrade Disk selection: tables, slot eligibility, and variant offering.

This module is PURE — it imports no Game, mutates no engine state, and carries
no per-episode side effects. It can be exercised in isolation from the rest of
the engine.

## Known simplifications / documented deviations

1. **Catacombs check** — non-veteran line 7 begins with ``(Unlocked Catacombs)``.
   The check passes when today's Tomb has been drafted AND entered (same-day only);
   it is not a permanent carry-over flag.

2. **Veteran day-1 shortcut ignores 'already drafted'** — the wiki's shortcut
   skips a room that is already drafted as well as one already upgraded. Every
   other selection path provably ignores house state, so the drafted test would
   be the only place the roll consults the grid; it is modelled as
   upgraded-only. Note this is NOT a limitation of ``draft_counts``, which is
   cumulative for the whole attempt — it is a deliberate omission.

3. **Exhaustion fallback** — if no entry is selectable after walking every line
   in both the veteran and non-veteran chains, ``select_slot`` falls back to a
   uniform pick over all selectable slots. The wiki does not specify the
   exhaustion case.

4. **Cloister sample assumed uniform** — the game samples 3 of 8 Cloister
   variants; whether the 8 are equally likely is unknown. This implementation
   assumes uniform without replacement.

5. **Already-applied variants not excluded at saturation** — the wiki does not
   state that the current variant is excluded when a room is re-offered at
   saturation. Excluding it would leave a 3-variant room with only 2 options,
   which contradicts the "always 3" invariant. All variants are offered.

## Version skew

This repo reproduces the datamined v1.3 draft algorithm. The tables in
``upgrade_selection.json`` are post-Patch-1.7; the wiki states these behaviours
"were changed significantly in Patch 1.7". This is an accepted deliberate skew:
upgrade selection is a separate subsystem from the draft core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .model import DEFAULT_DATA_DIR, Registry
from .rng import Rng

# ---------------------------------------------------------------------------
# Data-layer frozen dataclasses
# ---------------------------------------------------------------------------

ALL_SLOTS: tuple[str, ...] = (
    "closet", "storeroom", "courtyard", "boudoir", "nook",
    "hallway", "nursery", "bunk_room", "parlor", "cloister",
    "billiard_room", "mail_room", "guest_bedroom", "aquarium",
    "spare_1", "spare_2",
)

# The 15 room ids that map to slots (spare_room appears for both spare_1/spare_2).
_SLOT_ROOM_ORDER: tuple[str, ...] = (
    "spare_room", "bunk_room", "closet", "billiard_room", "parlor",
    "storeroom", "courtyard", "mail_room", "hallway", "boudoir",
    "guest_bedroom", "nursery", "aquarium", "nook", "cloister",
)


@dataclass(frozen=True, slots=True)
class SlotEntry:
    slot: str       # slot id from ALL_SLOTS
    min_drafts: int  # minimum times the slot's base room must have been drafted (0 = no gate)


@dataclass(frozen=True, slots=True)
class CheckEntry:
    check: str   # check kind: "room_drafts" | "catacombs_unlocked" | "always_false"
    room: str    # room id to check (only used when check == "room_drafts")
    count: int   # minimum draft count (only used when check == "room_drafts")


@dataclass(frozen=True, slots=True)
class ChainLine:
    line: str                          # label, e.g. "1", "5a", "10a"
    sub: bool                          # True if this is a fallthrough-only sub-line
    entries: tuple[SlotEntry | CheckEntry, ...]  # ordered entries in the line
    note: str                          # optional annotation (e.g. bug notes)


@dataclass(frozen=True, slots=True)
class FirstUpgradeTable:
    # Non-veteran: list of (slot, weight) in declaration order; weights sum to 1.0.
    # Veteran: empty list (uniform_over_all is True).
    weighted: tuple[tuple[str, float], ...]  # (slot_id, weight) pairs, non-veteran
    uniform_over_all: bool                   # True for veteran (uniform over all 16 slots)


@dataclass(frozen=True, slots=True)
class Day1Shortcut:
    chance: float             # probability of taking the shortcut (0.70)
    order: tuple[str, ...]    # fixed room-id fallback order (15 room ids)


@dataclass(frozen=True, slots=True)
class ModeTable:
    first_upgrade: FirstUpgradeTable   # how the very first upgrade is selected
    chains: tuple[ChainLine, ...]      # all chain lines in written order (top-level + sub)
    day1_shortcut: Day1Shortcut | None  # veteran only; None for non-veteran


@dataclass(frozen=True, slots=True)
class SlotDef:
    slot: str   # slot id
    room: str   # base room id this slot upgrades


@dataclass(frozen=True, slots=True)
class UpgradeTables:
    slots: tuple[SlotDef, ...]       # 16 slot definitions in ALL_SLOTS order
    slot_by_id: dict[str, SlotDef]   # slot id -> SlotDef
    non_veteran: ModeTable           # non-veteran selection tables
    veteran: ModeTable               # veteran selection tables


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _parse_entry(raw: dict) -> SlotEntry | CheckEntry:
    """Convert one raw JSON entry dict into the appropriate dataclass."""
    if "slot" in raw:
        return SlotEntry(slot=raw["slot"], min_drafts=raw.get("min_drafts", 0))
    # check entry
    return CheckEntry(
        check=raw["check"],
        room=raw.get("room", ""),
        count=raw.get("count", 0),
    )


def _parse_chain(raw_lines: list[dict]) -> tuple[ChainLine, ...]:
    """Parse a JSON chains list into a tuple of ChainLine dataclasses."""
    out = []
    for raw in raw_lines:
        entries = tuple(_parse_entry(e) for e in raw["entries"])
        out.append(ChainLine(
            line=raw["line"],
            sub=raw.get("sub", False),
            entries=entries,
            note=raw.get("note", ""),
        ))
    return tuple(out)


def _parse_mode(raw: dict, has_shortcut: bool) -> ModeTable:
    """Parse one mode block (non_veteran or veteran) from raw JSON."""
    fu_raw = raw["first_upgrade"]
    if fu_raw.get("uniform_over") == "all_slots":
        first_upgrade = FirstUpgradeTable(weighted=(), uniform_over_all=True)
    else:
        w = fu_raw["weights"]
        first_upgrade = FirstUpgradeTable(
            weighted=tuple((slot, w[slot]) for slot in w),
            uniform_over_all=False,
        )

    shortcut = None
    if has_shortcut and "day1_shortcut" in raw:
        sc = raw["day1_shortcut"]
        shortcut = Day1Shortcut(
            chance=sc["chance"],
            order=tuple(sc["order"]),
        )

    return ModeTable(
        first_upgrade=first_upgrade,
        chains=_parse_chain(raw["chains"]),
        day1_shortcut=shortcut,
    )


def parse_tables(raw: dict) -> UpgradeTables:
    """Build ``UpgradeTables`` from an already-decoded table document.

    Split out from :func:`load_tables` so callers can supply tables directly
    instead of reading the packaged file. Tests use this to exercise the walk
    against purpose-built tables: asserting the algorithm's behaviour against
    the shipped tables would only pin what the data file happens to say today.
    """
    slot_defs = tuple(
        SlotDef(slot=slot_id, room=info["room"])
        for slot_id, info in raw["slots"].items()
    )

    return UpgradeTables(
        slots=slot_defs,
        slot_by_id={sd.slot: sd for sd in slot_defs},
        non_veteran=_parse_mode(raw["non_veteran"], has_shortcut=False),
        veteran=_parse_mode(raw["veteran"], has_shortcut=True),
    )


def load_tables(data_dir: Path | None = None) -> UpgradeTables:
    """Load and parse upgrade_selection.json from ``data_dir``.

    ``data_dir`` follows the same convention as ``Registry.load``: defaults to
    the packaged data directory and can be overridden for testing.
    """
    d = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    return parse_tables(json.loads((d / "upgrade_selection.json").read_text()))


# ---------------------------------------------------------------------------
# Selection context
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SelectionContext:
    upgraded_slots: frozenset[str]   # slot ids already upgraded this attempt
    # Root base room id -> times that floorplan has been drafted THIS ATTEMPT
    # (cumulative across days, cleared on chain wrap). Keyed by the root base id
    # so an upgraded room keeps counting toward brackets that name it: drafts of
    # mail_room__ix89 must still satisfy "[4] Mail Room".
    draft_counts: Mapping[str, int]
    veteran: bool                    # True if veteran mode is active
    day: int                         # current day number (1-based)
    catacombs_unlocked: bool         # True when today's Tomb has been drafted AND entered (same-day only)


# ---------------------------------------------------------------------------
# Slot eligibility
# ---------------------------------------------------------------------------

def slot_is_selectable(slot: str, ctx: SelectionContext) -> bool:
    """Return True if ``slot`` can be selected given ``ctx``.

    A slot is unselectable when it is already upgraded, or when it is
    ``spare_2`` but ``spare_1`` has not yet been applied (spare_2 requires
    the first spare upgrade to be in place).
    """
    if slot in ctx.upgraded_slots:
        return False
    if slot == "spare_2" and "spare_1" not in ctx.upgraded_slots:
        return False
    return True


# ---------------------------------------------------------------------------
# Check evaluation
# ---------------------------------------------------------------------------

def _open_slot_for_room(room_id: str, tables: UpgradeTables, ctx: SelectionContext) -> str | None:
    """The room's first still-upgradable slot, or None when the room is exhausted.

    Only Spare Room has more than one slot, and the wiki's veteran shortcut skips
    a room when it is "already upgraded (twice in the case of Spare Room)" — so a
    Spare Room whose first stage is applied is still open at its second stage.
    """
    for sd in tables.slots:
        if sd.room == room_id and slot_is_selectable(sd.slot, ctx):
            return sd.slot
    return None


def _eval_check(entry: CheckEntry, ctx: SelectionContext) -> bool:
    """Evaluate a check entry against the current context.

    Returns True if the check passes (line walk continues), False to abandon
    the rest of the line.
    """
    match entry.check:
        case "room_drafts":
            return ctx.draft_counts.get(entry.room, 0) >= entry.count
        case "catacombs_unlocked":
            return ctx.catacombs_unlocked
        case "always_false":
            return False
        case _:
            # Unknown check kinds are treated as failing to be safe.
            return False


# ---------------------------------------------------------------------------
# Chain-walk helpers
# ---------------------------------------------------------------------------

def _walk_line(
    line: ChainLine,
    tables: UpgradeTables,
    ctx: SelectionContext,
) -> str | None:
    """Walk a single chain line; return the selected slot id or None.

    None means either a check failed (line abandoned) or every slot was
    already upgraded and the end of the line was reached.
    """
    for entry in line.entries:
        match entry:
            case CheckEntry():
                if not _eval_check(entry, ctx):
                    # Failed check: abandon the whole line.
                    return None
            case SlotEntry():
                if entry.min_drafts > 0:
                    # Bracketed slot: treat as an implicit check on the draft
                    # count for the slot's base room.
                    room_id = tables.slot_by_id[entry.slot].room
                    if ctx.draft_counts.get(room_id, 0) < entry.min_drafts:
                        # Failed bracket: abandon the whole line (same as check).
                        return None
                if slot_is_selectable(entry.slot, ctx):
                    return entry.slot
                # Already upgraded: advance within the line.
    return None


def _walk_chains(
    chain: tuple[ChainLine, ...],
    start_idx: int,
    tables: UpgradeTables,
    ctx: SelectionContext,
) -> str | None:
    """Walk ``chain`` starting at ``start_idx`` and return the first selected slot.

    Includes sub-lines encountered naturally (they are walked in order after
    the lines that precede them).
    """
    for line in chain[start_idx:]:
        result = _walk_line(line, tables, ctx)
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# Top-level selection
# ---------------------------------------------------------------------------

def select_slot(tables: UpgradeTables, ctx: SelectionContext, rng: Rng) -> str | None:
    """Select the upgrade slot for one Upgrade Disk insertion.

    Returns the slot id (always a member of ALL_SLOTS), or None only when
    there are no selectable slots at all and no fallback applies (should not
    happen in a well-formed game state, but callers should guard against it).

    Selection algorithm (steps numbered as in the design doc):

    1. Saturation (all 16 slots upgraded): uniform over the 15 upgradable
       rooms; map to a slot; spare_room -> spare_2.
    2. No slot upgraded yet (first upgrade): weighted roll (non-veteran) or
       uniform over all 16 (veteran, filtered to selectable).
    3. Veteran day-1 shortcut (70% chance, day == 1): uniform pick over the
       15 rooms; walk fixed fallback order if the pick is already upgraded.
    4. Uniform line pick from non-sub lines of the active table, then walk
       from that line through the end (including sub-lines). Veteran: on
       exhaustion continues into non-veteran chains from index 0.
    5. Fallback: uniform over all selectable slots (exhaustion case).
    """
    selectable = [s for s in ALL_SLOTS if slot_is_selectable(s, ctx)]

    # Step 1 — saturation.
    if len(ctx.upgraded_slots) >= 16:
        # Pick uniformly over the 15 upgradable rooms; spare_room -> spare_2.
        rooms15 = list(_SLOT_ROOM_ORDER)
        chosen_room = rng.choice("upgrade_saturation", rooms15)
        if chosen_room == "spare_room":
            return "spare_2"
        # Map room -> slot id (use the non-spare_2 slot for all others).
        for sd in tables.slots:
            if sd.room == chosen_room and sd.slot != "spare_2":
                return sd.slot
        return "spare_2"  # unreachable given well-formed tables

    # Step 2 — first upgrade (no slot upgraded yet).
    if not ctx.upgraded_slots:
        if ctx.veteran:
            # Uniform over all 16 slots, filtered to selectable.
            if selectable:
                return rng.choice("upgrade_first", selectable)
            return None
        else:
            # Weighted roll over the non-veteran first-upgrade table.
            weights_data = tables.non_veteran.first_upgrade.weighted
            slots_w = [wd[0] for wd in weights_data]
            weights = tuple(wd[1] for wd in weights_data)
            idx = rng.roll_weighted("upgrade_first", weights)
            return slots_w[idx]

    # Step 3 — veteran day-1 shortcut.
    if ctx.veteran and ctx.day == 1:
        shortcut = tables.veteran.day1_shortcut
        if shortcut is not None and rng.chance("upgrade_vet_shortcut", shortcut.chance):
            # Uniform pick over 15 rooms.
            chosen = rng.choice("upgrade_vet_shortcut", list(shortcut.order))
            chosen_slot = _open_slot_for_room(chosen, tables, ctx)
            if chosen_slot is not None:
                return chosen_slot
            # The pick was fully upgraded: walk the fixed room order instead.
            for room_id in shortcut.order:
                slot = _open_slot_for_room(room_id, tables, ctx)
                if slot is not None:
                    return slot
            # Exhausted — fall through to step 4.

    # Step 4 — uniform line pick + walk.
    active_table = tables.veteran if ctx.veteran else tables.non_veteran
    top_level = [i for i, ln in enumerate(active_table.chains) if not ln.sub]
    if top_level:
        pick_idx = top_level[rng.randint("upgrade_line", 0, len(top_level) - 1)]
        result = _walk_chains(active_table.chains, pick_idx, tables, ctx)
        if result is not None:
            return result
        # Veteran: exhausted the veteran list; continue into non-veteran from idx 0.
        if ctx.veteran:
            result = _walk_chains(tables.non_veteran.chains, 0, tables, ctx)
            if result is not None:
                return result

    # Step 5 — exhaustion fallback.
    if selectable:
        return rng.choice("upgrade_fallback", selectable)
    return None


# ---------------------------------------------------------------------------
# Variant offering
# ---------------------------------------------------------------------------

def _three_variants_of(registry: Registry, base_id: str) -> list[str]:
    """The three upgrade variants of ``base_id``, in file order.

    Raises if the count is not exactly three. Silently slicing would turn a data
    error into a wrong-but-plausible option set, which is far harder to notice
    than a crash; Cloister is the one room with a different count and it never
    reaches here.
    """
    variants = sorted(
        (r for r in registry.rooms if r.variant_of == base_id), key=lambda r: r.idx
    )
    if len(variants) != 3:
        raise ValueError(f"{base_id} has {len(variants)} upgrade variants, expected 3")
    return [r.id for r in variants]


def offer_variants(
    slot: str,
    applied_variants: frozenset[str],
    registry: Registry,
    rng: Rng,
) -> list[str]:
    """Return exactly 3 variant room ids to offer for ``slot``.

    Parameters
    ----------
    slot:
        The slot id being upgraded (a member of ALL_SLOTS).
    applied_variants:
        Set of variant room ids already applied (used for spare_2 to know which
        first-level spare variant is in place).
    registry:
        The loaded room registry.
    rng:
        The episode RNG; consumed only for the Cloister 3-of-8 sample.

    Notes
    -----
    - For the 14 ordinary slots: the 3 registry rooms whose ``variant_of``
      equals the slot's base room id, in registry/file order.
    - For ``cloister``: 8 variants exist; 3 are sampled uniformly without
      replacement, then returned sorted by ``Room.idx`` for canonical order.
    - For ``spare_1``: the 3 first-level spare variants (``variant_of ==
      "spare_room"``).
    - For ``spare_2``: whichever first-level spare variant is in
      ``applied_variants``, then its 3 sub-variants.  Raises ``ValueError``
      if no first-level spare variant is applied.
    - Already-applied variants are NOT excluded — at saturation, a room is
      re-offered so the player can change their upgrade choice, and a 3-variant
      room must always present 3 options.
    """
    match slot:
        case "spare_1":
            return _three_variants_of(registry, "spare_room")

        case "spare_2":
            # Find the applied first-level spare variant.
            first_level_ids = {
                r.id for r in registry.rooms if r.variant_of == "spare_room"
            }
            applied_first = applied_variants & first_level_ids
            if not applied_first:
                raise ValueError(
                    "offer_variants called for spare_2 but no first-level spare "
                    "variant is in applied_variants — callers must apply spare_1 first"
                )
            # Exactly one should be present; sort so a malformed set still picks
            # deterministically (frozenset order over strings varies per process).
            base_id = sorted(applied_first)[0]
            return _three_variants_of(registry, base_id)

        case "cloister":
            all_variants = [r for r in registry.rooms if r.variant_of == "cloister"]
            all_variants.sort(key=lambda r: r.idx)
            # Sample 3 of 8 uniformly without replacement.
            sampled = rng.stream("upgrade_options").sample(all_variants, 3)
            sampled.sort(key=lambda r: r.idx)
            return [r.id for r in sampled]

        case _:
            # The fourteen ordinary slots are named after the room they upgrade;
            # validate_data.py pins that correspondence in upgrade_selection.json.
            return _three_variants_of(registry, slot)


# ---------------------------------------------------------------------------
# Helpers for engine wiring (chunk 2)
# ---------------------------------------------------------------------------

def root_base_id(registry: Registry, room) -> str:
    """Walk variant_of to the root; return the root base room id.

    A non-variant room returns its own id. Upgraded variants count toward
    [N] brackets naming their base room — a Mail Room variant must still
    increment the 'mail_room' draft counter.
    """
    current = room
    while current.variant_of is not None:
        parent = registry.by_id.get(current.variant_of)
        if parent is None:
            break
        current = parent
    return current.id


def upgraded_slots(applied_variants: frozenset[str], registry: Registry) -> frozenset[str]:
    """Map applied variant ids to slot ids.

    A variant whose variant_of is 'spare_room' implies 'spare_1'.
    A variant whose variant_of is itself a first-level spare variant implies
    both 'spare_2' and 'spare_1'. Every other variant implies the slot named
    by its variant_of.
    """
    first_level_spare_ids = frozenset(
        r.id for r in registry.rooms if r.variant_of == "spare_room"
    )
    slots: set[str] = set()
    for vid in applied_variants:
        room = registry.by_id.get(vid)
        if room is None or room.variant_of is None:
            continue
        if room.variant_of == "spare_room":
            slots.add("spare_1")
        elif room.variant_of in first_level_spare_ids:
            slots.add("spare_1")
            slots.add("spare_2")
        else:
            slots.add(room.variant_of)
    return frozenset(slots)
