"""Tests for the Upgrade Disk selection algorithm in engine/upgrades.py.

These tests pin observable behaviour — what a player or RL agent sees — not
data file contents (those belong in tools/validate_data.py). Every behavioural
test builds its own tables via parse_tables(); only the single integration test
at the bottom touches the shipped data file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from scipy import stats

from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.upgrades import (
    ALL_SLOTS,
    SelectionContext,
    UpgradeTables,
    load_tables,
    offer_variants,
    parse_tables,
    select_slot,
    slot_is_selectable,
)

N_SAMPLES = 30_000
# Bonferroni correction constants
ALPHA_7 = 0.001 / 7   # for 7-slot chi-square (kept for saturation)
ALPHA_3 = 0.001 / 3   # for 3-slot chi-square (weighted first-upgrade)
ALPHA_15 = 0.001 / 15  # for 15-room saturation chi-square


# ---------------------------------------------------------------------------
# Builder helpers — construct synthetic UpgradeTables without touching any file
# ---------------------------------------------------------------------------

def _slot_entry(slot_id: str, min_drafts: int = 0) -> dict:
    """Raw dict for a slot chain entry."""
    e: dict = {"slot": slot_id}
    if min_drafts:
        e["min_drafts"] = min_drafts
    return e


def _check_entry(kind: str, room: str | None = None, count: int | None = None) -> dict:
    """Raw dict for a check chain entry."""
    e: dict = {"check": kind}
    if room is not None:
        e["room"] = room
    if count is not None:
        e["count"] = count
    return e


def _chain_line(line_id: str | int, entries: list, sub: bool = False) -> dict:
    """Raw dict for one chain line."""
    return {"line": str(line_id), "sub": sub, "entries": entries}


def _tables(
    slots: dict[str, str] | None = None,
    nv_weights: dict[str, float] | None = None,
    nv_chains: list | None = None,
    vet_chains: list | None = None,
    vet_shortcut: dict | None = None,
) -> UpgradeTables:
    """Build a synthetic UpgradeTables from purpose-built data.

    ``slots`` maps slot_id -> room_id. When None, a minimal set is built from
    the slot ids referenced in chains (each mapped to a room of the same name).
    ``nv_weights`` defaults to uniform over the first slot in ``slots``.
    ``nv_chains`` and ``vet_chains`` default to a single line with one slot each.
    """
    # Collect slot ids referenced in chains so we can auto-build slots dict.
    referenced_slots: set[str] = set()
    for line in (nv_chains or []) + (vet_chains or []):
        for e in line.get("entries", []):
            if "slot" in e:
                referenced_slots.add(e["slot"])

    if slots is None:
        # Build a minimal slot map: each referenced slot maps to a room named after it,
        # except spare_1/spare_2 which both map to "spare_room".
        # Sorted, not raw set order: string hashing is randomised per process, so
        # iterating the set would make the dict order — and therefore the default
        # weights and `next(iter(slots))` below — vary between runs.
        slots = {}
        for s in sorted(referenced_slots):
            slots[s] = "spare_room" if s in ("spare_1", "spare_2") else s
        # Always include closet as a fallback selectable slot.
        if "closet" not in slots:
            slots["closet"] = "closet"

    # Default non-veteran first-upgrade: uniform over whatever slots are present.
    if nv_weights is None:
        slot_keys = list(slots.keys())
        w = 1.0 / len(slot_keys) if slot_keys else 1.0
        nv_weights = {s: w for s in slot_keys}

    # Default chains: one line per mode with the first slot.
    if nv_chains is None:
        first_slot = next(iter(slots))
        nv_chains = [_chain_line("1", [_slot_entry(first_slot)])]
    if vet_chains is None:
        first_slot = next(iter(slots))
        vet_chains = [_chain_line("1", [_slot_entry(first_slot)])]

    raw: dict = {
        "slots": {sid: {"room": rid} for sid, rid in slots.items()},
        "non_veteran": {
            "first_upgrade": {"weights": nv_weights},
            "chains": nv_chains,
        },
        "veteran": {
            "first_upgrade": {"uniform_over": "all_slots"},
            "chains": vet_chains,
        },
    }
    if vet_shortcut is not None:
        raw["veteran"]["day1_shortcut"] = vet_shortcut

    return parse_tables(raw)


# ---------------------------------------------------------------------------
# Fake registry helpers — for offer_variants tests only
# ---------------------------------------------------------------------------

def _fake_room(id_: str, idx: int, variant_of: str | None = None) -> SimpleNamespace:
    """Minimal room-like object that offer_variants accesses."""
    return SimpleNamespace(id=id_, idx=idx, variant_of=variant_of)


def _fake_registry(rooms: list) -> SimpleNamespace:
    """Minimal registry-like object that offer_variants accesses."""
    return SimpleNamespace(rooms=rooms, by_id={r.id: r for r in rooms})


def _ctx(
    upgraded: frozenset[str] | None = None,
    draft_counts: dict[str, int] | None = None,
    veteran: bool = False,
    day: int = 2,
) -> SelectionContext:
    """Convenience factory for SelectionContext."""
    return SelectionContext(
        upgraded_slots=upgraded if upgraded is not None else frozenset(),
        draft_counts=draft_counts or {},
        veteran=veteran,
        day=day,
    )


# ---------------------------------------------------------------------------
# slot_is_selectable — pure function, no tables needed
# ---------------------------------------------------------------------------

def test_already_upgraded_not_selectable():
    """A slot present in upgraded_slots is never selectable."""
    ctx = _ctx(upgraded=frozenset({"closet"}))
    assert not slot_is_selectable("closet", ctx)


def test_spare_2_blocked_without_spare_1():
    """spare_2 is unselectable until spare_1 is applied — they form a two-stage chain."""
    ctx = _ctx(upgraded=frozenset())
    assert not slot_is_selectable("spare_2", ctx)


def test_spare_2_selectable_after_spare_1():
    """spare_2 becomes selectable once spare_1 is in upgraded_slots."""
    ctx = _ctx(upgraded=frozenset({"spare_1"}))
    assert slot_is_selectable("spare_2", ctx)


def test_ordinary_slot_selectable_when_not_upgraded():
    """Any slot not in upgraded_slots (other than spare_2 gating) is selectable."""
    ctx = _ctx(upgraded=frozenset())
    for slot in ALL_SLOTS:
        if slot != "spare_2":
            assert slot_is_selectable(slot, ctx), f"{slot} should be selectable"


# ---------------------------------------------------------------------------
# Non-veteran first-upgrade: weighted roll with test-defined weights
# ---------------------------------------------------------------------------

def test_non_veteran_first_upgrade_distribution():
    """The first-upgrade roll reproduces the weights the test specifies (0.6/0.3/0.1).

    Deliberately not the shipped split, so this cannot accidentally pass against the real file.
    """
    weights = {"closet": 0.60, "nook": 0.30, "parlor": 0.10}
    t = _tables(
        slots={"closet": "closet", "nook": "nook", "parlor": "parlor"},
        nv_weights=weights,
        nv_chains=[_chain_line("1", [_slot_entry("closet")])],
    )
    counts: dict[str, int] = {k: 0 for k in weights}
    ctx = _ctx()  # no slots upgraded => first-upgrade path
    for seed in range(N_SAMPLES):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot in counts, f"unexpected first-upgrade slot {slot!r}"
        counts[slot] += 1

    obs = [counts[k] for k in weights]
    exp = [p * N_SAMPLES for p in weights.values()]
    _, p = stats.chisquare(obs, exp)
    assert p > ALPHA_3, f"first-upgrade distribution mismatch: counts={counts}"


# ---------------------------------------------------------------------------
# Chain-walk semantics
# ---------------------------------------------------------------------------

def test_check_failure_abandons_entire_line():
    """A failed check must abandon the whole remaining line, not just advance past it.

    Line 1 = [check(always_false), slot(closet)]; line 2 = [slot(nook)].
    closet must never appear; nook must always appear.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_check_entry("always_false"), _slot_entry("closet")]),
            _chain_line("2", [_slot_entry("nook")]),
        ],
    )
    # One slot upgraded to skip first-upgrade path; closet and nook remain fresh.
    ctx2 = _ctx(upgraded=frozenset({"storeroom"}))  # storeroom not in tables — closet/nook free

    seen: set[str] = set()
    for seed in range(200):
        slot = select_slot(t, ctx2, Rng(seed))
        if slot is not None:
            seen.add(slot)

    assert "closet" not in seen, "closet must never appear — line 1 was abandoned"
    assert "nook" in seen, "nook must appear — reachable via line 2"


def test_bracket_failure_abandons_entire_line_not_just_entry():
    """A failed bracket ([N]) must abandon the entire remaining line, not just advance.

    Line 1 = [slot(closet, min_drafts=2), slot(nook)]; line 2 = [slot(parlor)].
    With 0 closet drafts: the bracket fails, so neither closet NOR nook is selected.
    nook is the critical assertion — a naive 'just skip' would select it.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook", "parlor": "parlor"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet", min_drafts=2), _slot_entry("nook")]),
            _chain_line("2", [_slot_entry("parlor")]),
        ],
    )
    ctx = _ctx(upgraded=frozenset({"storeroom"}), draft_counts={})  # 0 closet drafts

    for seed in range(200):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot != "closet", "closet should not be selected (bracket failed)"
        assert slot != "nook", "nook must not be selected — line 1 was abandoned, not advanced"
        assert slot in (None, "parlor"), f"unexpected slot {slot!r}"


def test_passing_bracket_allows_selection():
    """A satisfied bracket ([N]) allows the rest of the line to proceed normally."""
    t = _tables(
        slots={"closet": "closet", "nook": "nook", "parlor": "parlor"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet", min_drafts=2), _slot_entry("nook")]),
            _chain_line("2", [_slot_entry("parlor")]),
        ],
    )
    # Provide enough closet drafts to pass the bracket.
    ctx = _ctx(upgraded=frozenset({"storeroom"}), draft_counts={"closet": 3})

    seen: set[str] = set()
    for seed in range(200):
        slot = select_slot(t, ctx, Rng(seed))
        if slot is not None:
            seen.add(slot)

    # closet or nook should appear (line 1 passes its bracket now).
    assert seen & {"closet", "nook"}, "line 1 should produce closet or nook with passing bracket"


def test_already_upgraded_slot_advances_within_line():
    """An already-upgraded slot must advance to the next entry on the same line, not abandon it."""
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet"), _slot_entry("nook")]),
        ],
    )
    # closet is upgraded → line 1 should advance to nook.
    ctx = _ctx(upgraded=frozenset({"closet"}))

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "nook", f"should advance past closet to nook, got {slot!r}"


def test_end_of_line_falls_through_to_next_line():
    """Exhausting all entries on a line falls through to the next line in written order."""
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet")]),
            _chain_line("2", [_slot_entry("nook")]),
        ],
    )
    # closet is upgraded → line 1 exhausted → falls through to line 2 (nook).
    ctx = _ctx(upgraded=frozenset({"closet"}))

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "nook", f"should fall through to line 2 (nook), got {slot!r}"


def test_sub_lines_never_initial_pick():
    """Sub-lines are never the initial randomly chosen line — they are only reachable by fallthrough.

    With two top-level lines and a sub-line containing a uniquely-identifying slot,
    the sub-line slot never appears unless a top-level line falls through to it.
    """
    # nook is only in the sub-line. closet and parlor are top-level.
    # With neither closet nor parlor upgraded (and closet in line 1 at the initial
    # pick), nook should never be selected because the sub-line is not a pick target.
    t = _tables(
        slots={"closet": "closet", "parlor": "parlor", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet")]),
            _chain_line("2", [_slot_entry("parlor")]),
            _chain_line("2a", [_slot_entry("nook")], sub=True),
        ],
    )
    ctx = _ctx(upgraded=frozenset({"storeroom"}))  # closet and parlor both selectable

    seen: set[str] = set()
    for seed in range(500):
        slot = select_slot(t, ctx, Rng(seed))
        if slot is not None:
            seen.add(slot)

    # closet and parlor should be seen (top-level picks).
    # nook should NOT appear because line "2a" is a sub-line never initially picked,
    # and neither line 1 nor line 2 falls through (they both succeed immediately).
    assert "nook" not in seen, "sub-line slot nook must never be the initial pick"
    assert seen <= {"closet", "parlor"}


def test_sub_lines_reachable_by_fallthrough():
    """Sub-lines are reachable when the preceding top-level line exhausts all its entries.

    Line 1 (top) = [slot(closet)] with closet upgraded → exhausted.
    Line 1a (sub) = [slot(nook)] → reachable by fallthrough.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet")]),
            _chain_line("1a", [_slot_entry("nook")], sub=True),
        ],
    )
    # closet is upgraded so line 1 exhausts; there is only one top-level line,
    # so it is always picked, then falls through to sub-line 1a.
    ctx = _ctx(upgraded=frozenset({"closet"}))

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "nook", f"should reach nook via sub-line fallthrough, got {slot!r}"


# ---------------------------------------------------------------------------
# spare_2 gating in chain walk
# ---------------------------------------------------------------------------

def test_spare_2_skipped_without_spare_1_in_chain():
    """spare_2 in a chain line is skipped (not selected) when spare_1 is unapplied.

    The walk advances past the spare_2 entry and selects the next available slot.
    """
    t = _tables(
        slots={"spare_1": "spare_room", "spare_2": "spare_room", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("spare_2"), _slot_entry("nook")]),
        ],
    )
    # spare_1 not upgraded → spare_2 is not selectable → walk advances to nook.
    ctx = _ctx(upgraded=frozenset({"storeroom"}))

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot != "spare_2", "spare_2 must not be selected before spare_1"
        # nook should be picked instead
        assert slot == "nook", f"expected nook after skipping spare_2, got {slot!r}"


def test_spare_2_selectable_in_chain_after_spare_1():
    """spare_2 in a chain line becomes selectable once spare_1 is upgraded."""
    t = _tables(
        slots={"spare_1": "spare_room", "spare_2": "spare_room", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("spare_2"), _slot_entry("nook")]),
        ],
    )
    # spare_1 upgraded → spare_2 is selectable and should be selected first.
    ctx = _ctx(upgraded=frozenset({"spare_1"}))

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "spare_2", f"expected spare_2 with spare_1 applied, got {slot!r}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_seed_same_result():
    """Given identical seed and context, select_slot always returns the same slot."""
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet")]),
            _chain_line("2", [_slot_entry("nook")]),
        ],
    )
    ctx = _ctx(upgraded=frozenset())
    for seed in range(50):
        rng1 = Rng(seed)
        rng2 = Rng(seed)
        assert select_slot(t, ctx, rng1) == select_slot(t, ctx, rng2)


# ---------------------------------------------------------------------------
# Saturation — all 16 slots upgraded; module-level _SLOT_ROOM_ORDER drives this
# ---------------------------------------------------------------------------

def _full_slots_dict() -> dict[str, str]:
    """All 16 slots mapped to their room ids (spare_1 and spare_2 share spare_room).

    Needed for saturation tests because the saturation branch maps chosen_room -> slot
    by searching tables.slots; if a room is missing from the tables, it falls back to
    spare_2, which would skew the distribution.
    """
    d: dict[str, str] = {s: s for s in ALL_SLOTS}
    d["spare_1"] = "spare_room"
    d["spare_2"] = "spare_room"
    return d


def test_saturation_always_returns_slot():
    """When all 16 slots are upgraded, select_slot still returns a slot for re-offering."""
    t = _tables(slots=_full_slots_dict())
    all_upgraded = frozenset(ALL_SLOTS)
    for seed in range(100):
        slot = select_slot(t, _ctx(upgraded=all_upgraded), Rng(seed))
        assert slot is not None, "saturation should always return a slot"
        assert slot in ALL_SLOTS


def test_saturation_uniform_over_rooms():
    """At saturation the distribution is uniform over the 15 upgradable rooms.

    spare_room maps to spare_2, so spare_2 appears; each of the 15 rooms has
    equal probability, and chi-square should not reject uniformity.
    """
    ROOMS_15 = [
        "spare_room", "bunk_room", "closet", "billiard_room", "parlor",
        "storeroom", "courtyard", "mail_room", "hallway", "boudoir",
        "guest_bedroom", "nursery", "aquarium", "nook", "cloister",
    ]

    def slot_to_room(slot: str) -> str:
        return "spare_room" if slot in ("spare_1", "spare_2") else slot

    t = _tables(slots=_full_slots_dict())
    all_upgraded = frozenset(ALL_SLOTS)
    counts: dict[str, int] = {r: 0 for r in ROOMS_15}
    for seed in range(N_SAMPLES):
        slot = select_slot(t, _ctx(upgraded=all_upgraded), Rng(seed))
        assert slot is not None
        counts[slot_to_room(slot)] += 1

    obs = [counts[r] for r in ROOMS_15]
    exp = [N_SAMPLES / 15] * 15
    _, p = stats.chisquare(obs, exp)
    assert p > ALPHA_15, f"saturation distribution mismatch: counts={counts}"


# ---------------------------------------------------------------------------
# Exhaustion fallback
# ---------------------------------------------------------------------------

def test_exhaustion_fallback_returns_selectable_slot():
    """When no chain line yields a slot, the fallback picks uniformly from selectable slots.

    Tables with only check(always_false) lines guarantee every line fails; select_slot
    must still return a selectable slot via the exhaustion fallback. The fallback
    iterates ALL_SLOTS (not tables.slots), so we upgrade every slot except the two
    we want to see, ensuring only those two are selectable.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_check_entry("always_false"), _slot_entry("closet")]),
            _chain_line("2", [_check_entry("always_false"), _slot_entry("nook")]),
        ],
    )
    # Upgrade everything except closet and nook so only they are selectable.
    upgraded = frozenset(s for s in ALL_SLOTS if s not in ("closet", "nook"))
    ctx = _ctx(upgraded=upgraded)  # skips first-upgrade (some slots already upgraded)

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot in {"closet", "nook"}, f"fallback should pick closet or nook, got {slot!r}"
        assert slot_is_selectable(slot, ctx)


# ---------------------------------------------------------------------------
# select_slot never returns non-selectable
# ---------------------------------------------------------------------------

def test_select_never_returns_non_selectable():
    """Outside saturation, select_slot never returns a slot that fails slot_is_selectable."""
    t = _tables(
        slots={"closet": "closet", "nook": "nook", "parlor": "parlor"},
        nv_chains=[
            _chain_line("1", [_slot_entry("closet"), _slot_entry("nook")]),
            _chain_line("2", [_slot_entry("parlor")]),
        ],
    )
    ctx = _ctx(upgraded=frozenset({"closet"}))
    for seed in range(200):
        slot = select_slot(t, ctx, Rng(seed))
        if slot is not None:
            assert slot_is_selectable(slot, ctx), f"select_slot returned non-selectable {slot!r}"


def test_select_never_returns_spare_2_without_spare_1():
    """spare_2 is never returned unless spare_1 is already in upgraded_slots.

    We use a context with one slot already upgraded (to skip the first-upgrade path
    where weights are applied) and spare_1 not upgraded, ensuring the chain walk
    encounters spare_2 as a candidate but never selects it.
    """
    t = _tables(
        slots={"spare_1": "spare_room", "spare_2": "spare_room", "nook": "nook"},
        nv_chains=[
            _chain_line("1", [_slot_entry("spare_2"), _slot_entry("nook")]),
        ],
    )
    # nook is upgraded to skip first-upgrade; spare_1 is NOT upgraded → spare_2 blocked.
    ctx = _ctx(upgraded=frozenset({"nook"}))
    for seed in range(200):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot != "spare_2", "spare_2 must not be selected before spare_1"


# ---------------------------------------------------------------------------
# Veteran mode
# ---------------------------------------------------------------------------

def test_veteran_uniform_pick_over_top_level_lines():
    """In veteran mode, the initial line pick is uniform over non-sub top-level lines.

    Two lines each with a unique slot: both should be reachable over many seeds.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        vet_chains=[
            _chain_line("1", [_slot_entry("closet")]),
            _chain_line("2", [_slot_entry("nook")]),
        ],
    )
    # Need one upgrade so step 2 (first-upgrade) is skipped.
    ctx = _ctx(upgraded=frozenset({"storeroom"}), veteran=True, day=2)

    seen: set[str] = set()
    for seed in range(200):
        slot = select_slot(t, ctx, Rng(seed))
        if slot is not None:
            seen.add(slot)

    assert "closet" in seen, "line 1 (closet) should be reachable in veteran mode"
    assert "nook" in seen, "line 2 (nook) should be reachable in veteran mode"


def test_veteran_chain_falls_through_to_non_veteran():
    """When veteran chains are exhausted, the walk continues from non-veteran chains.

    Veteran line 1 = [slot(closet)] with closet upgraded → exhausted.
    Non-veteran line 1 = [slot(nook)] → must be reachable.
    """
    t = _tables(
        slots={"closet": "closet", "nook": "nook"},
        nv_chains=[_chain_line("1", [_slot_entry("nook")])],
        vet_chains=[_chain_line("1", [_slot_entry("closet")])],
    )
    # closet upgraded → veteran chain exhausted; fallthrough to non-veteran.
    ctx = _ctx(upgraded=frozenset({"closet"}), veteran=True, day=2)

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "nook", f"should reach nook via non-veteran fallthrough, got {slot!r}"


def test_veteran_day1_shortcut_fires_at_configured_chance():
    """The day-1 shortcut fires at the probability set in its config.

    A shortcut with chance=1.0 should fire on every roll; chance=0.0 should never fire.
    We test by observing whether the shortcut's first-order room appears more than a chain-only
    run would produce, by using chance=1.0 and a shortcut that exhausts immediately
    (so selection falls back to chain), versus chance=0.0 which skips entirely.
    Use a deterministic shortcut order with a single selectable room to verify firing rate.
    """
    # shortcut order: ["nook"] — when it fires and picks nook (selectable), returns nook.
    # veteran chain line 1 = [slot(closet)] (closet is upgraded, so this exhausts).
    # non-veteran chain line 1 = [slot(parlor)].
    # With chance=1.0: shortcut fires, picks nook (selectable) → always nook.
    # With chance=0.0: shortcut skipped, veteran chain exhausts, falls to nv → parlor.
    slots = {"nook": "nook", "closet": "closet", "parlor": "parlor"}

    t_always = _tables(
        slots=slots,
        nv_chains=[_chain_line("1", [_slot_entry("parlor")])],
        vet_chains=[_chain_line("1", [_slot_entry("closet")])],
        vet_shortcut={"chance": 1.0, "order": ["nook"]},
    )
    t_never = _tables(
        slots=slots,
        nv_chains=[_chain_line("1", [_slot_entry("parlor")])],
        vet_chains=[_chain_line("1", [_slot_entry("closet")])],
        vet_shortcut={"chance": 0.0, "order": ["nook"]},
    )

    ctx = _ctx(upgraded=frozenset({"closet"}), veteran=True, day=1)

    always_slots = {select_slot(t_always, ctx, Rng(s)) for s in range(50)}
    never_slots = {select_slot(t_never, ctx, Rng(s)) for s in range(50)}

    assert always_slots == {"nook"}, f"chance=1.0 shortcut should always pick nook: {always_slots}"
    assert "parlor" in never_slots, f"chance=0.0 should skip shortcut and reach parlor: {never_slots}"
    assert "nook" not in never_slots, f"chance=0.0 shortcut must not fire: {never_slots}"


def test_veteran_after_day_1_never_uses_shortcut():
    """Past day 1, the shortcut is never taken — selection comes from the chain walk only."""
    slots = {"nook": "nook", "closet": "closet", "parlor": "parlor"}
    t = _tables(
        slots=slots,
        nv_chains=[_chain_line("1", [_slot_entry("parlor")])],
        vet_chains=[_chain_line("1", [_slot_entry("nook")])],
        vet_shortcut={"chance": 1.0, "order": ["closet"]},
    )
    # day=4: shortcut unavailable even with chance=1.0.
    # nook is selectable; the veteran chain should yield it.
    ctx = _ctx(upgraded=frozenset({"storeroom"}), veteran=True, day=4)

    seen: set[str] = set()
    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        if slot is not None:
            seen.add(slot)

    assert "closet" not in seen, "shortcut (closet) must not fire past day 1"


def test_veteran_shortcut_can_reach_spare_2():
    """Spare Room stays open at its second stage; the shortcut must return spare_2 not nook.

    Regression guard: if _open_slot_for_room wrongly treats spare_room as exhausted once
    spare_1 is applied, the shortcut order [spare_room, nook] always resolves to nook.
    The correct behaviour: spare_room is first, spare_2 is open → spare_2 always wins.
    """
    # spare_1 is upgraded → spare_2 is selectable; upgrade every slot except spare_2 and nook.
    upgraded = frozenset(s for s in ALL_SLOTS if s not in ("spare_2", "nook"))
    assert "spare_1" in upgraded  # spare_2 gating satisfied

    slots_dict: dict[str, str] = {s: "spare_room" if s in ("spare_1", "spare_2") else s
                                   for s in ALL_SLOTS}
    t = _tables(
        slots=slots_dict,
        # Chains don't matter — shortcut (chance=1.0) fires before them.
        nv_chains=[_chain_line("1", [_slot_entry("nook")])],
        vet_chains=[_chain_line("1", [_slot_entry("nook")])],
        # Shortcut order: spare_room first, nook second.
        # Not bugged: shortcut picks uniformly from [spare_room, nook] — 50% each.
        #   When spare_room picked → _open_slot_for_room returns spare_2 → returned.
        #   When nook picked → _open_slot_for_room returns nook → returned.
        # Bugged (spare_room wrongly exhausted after spare_1 applied):
        #   spare_room picked → None → falls through order: spare_room→None, nook→nook.
        #   nook picked → nook.  Either way → always nook, spare_2 never returned.
        vet_shortcut={"chance": 1.0, "order": ["spare_room", "nook"]},
    )
    ctx = _ctx(upgraded=upgraded, veteran=True, day=1)

    picks = [select_slot(t, ctx, Rng(seed)) for seed in range(2000)]
    assert set(picks) <= {"spare_2", "nook"}, f"unexpected slots: {set(picks)}"
    # With correct behaviour, spare_2 appears ~50% of the time.
    # A bug that treats spare_room as exhausted after spare_1 would produce spare_2 never.
    spare2_count = picks.count("spare_2")
    assert spare2_count > 400, (
        f"spare_2 should appear ~50% of the time with spare_room in shortcut order; "
        f"got {spare2_count}/2000 — a bug treating spare_room as exhausted after spare_1 "
        "would give spare_2=0"
    )


def test_veteran_shortcut_skips_fully_upgraded_rooms():
    """The shortcut walks the order list and skips rooms whose slots are all upgraded."""
    # shortcut order: ["closet", "nook"] — closet is upgraded, nook is not.
    slots_dict: dict[str, str] = {s: s for s in ["closet", "nook", "parlor"]}
    t = _tables(
        slots=slots_dict,
        nv_chains=[_chain_line("1", [_slot_entry("parlor")])],
        vet_chains=[_chain_line("1", [_slot_entry("parlor")])],
        vet_shortcut={"chance": 1.0, "order": ["closet", "nook"]},
    )
    ctx = _ctx(upgraded=frozenset({"closet"}), veteran=True, day=1)

    for seed in range(100):
        slot = select_slot(t, ctx, Rng(seed))
        assert slot == "nook", f"shortcut should skip closet and return nook, got {slot!r}"


# ---------------------------------------------------------------------------
# offer_variants — fake registry, no real data files
# ---------------------------------------------------------------------------

def test_offer_variants_exactly_three_for_three_variant_room():
    """offer_variants returns exactly 3 variant ids for a room with exactly 3 variants."""
    rooms = [
        _fake_room("closet", 0),
        _fake_room("closet_v1", 1, variant_of="closet"),
        _fake_room("closet_v2", 2, variant_of="closet"),
        _fake_room("closet_v3", 3, variant_of="closet"),
    ]
    reg = _fake_registry(rooms)
    offered = offer_variants("closet", frozenset(), reg, Rng(0))
    assert len(offered) == 3


def test_offer_variants_for_room_with_more_than_three_variants():
    """For Cloister (8 variants), offer_variants returns exactly 3 distinct ids sorted by idx."""
    rooms = [_fake_room("cloister", 0)]
    for i in range(8):
        rooms.append(_fake_room(f"cloister_v{i}", i + 1, variant_of="cloister"))
    reg = _fake_registry(rooms)

    for seed in range(20):
        offered = offer_variants("cloister", frozenset(), reg, Rng(seed))
        assert len(offered) == 3, f"expected 3 variants, got {len(offered)}"
        assert len(set(offered)) == 3, "offered variants must be distinct"
        cloister_ids = {r.id for r in rooms if r.variant_of == "cloister"}
        for vid in offered:
            assert vid in cloister_ids, f"{vid!r} is not a cloister variant"
        idxes = [reg.by_id[v].idx for v in offered]
        assert idxes == sorted(idxes), "offered variants must be sorted by idx"


def test_offer_variants_cloister_all_reachable():
    """Over many seeds, every one of the 8 Cloister variants appears in the offered set."""
    rooms = [_fake_room("cloister", 0)]
    for i in range(8):
        rooms.append(_fake_room(f"cloister_v{i}", i + 1, variant_of="cloister"))
    reg = _fake_registry(rooms)

    cloister_ids = [r.id for r in rooms if r.variant_of == "cloister"]
    counts: dict[str, int] = {v: 0 for v in cloister_ids}
    N = 5_000
    for seed in range(N):
        for vid in offer_variants("cloister", frozenset(), reg, Rng(seed)):
            counts[vid] += 1

    for v in cloister_ids:
        assert counts[v] > 0, f"cloister variant {v!r} never appeared"

    obs = [counts[v] for v in cloister_ids]
    exp = [(3 / 8) * N] * 8
    _, p = stats.chisquare(obs, exp)
    assert p > ALPHA_7, f"cloister variant distribution mismatch: counts={counts}"


def test_offer_variants_spare_2_error_without_spare_1_applied():
    """Calling offer_variants for spare_2 with no applied first-level spare raises ValueError."""
    # spare_1 variants exist, but none are in applied_variants.
    rooms = [
        _fake_room("spare_room", 0),
        _fake_room("spare_v1", 1, variant_of="spare_room"),
        _fake_room("spare_v2", 2, variant_of="spare_room"),
        _fake_room("spare_v3", 3, variant_of="spare_room"),
    ]
    reg = _fake_registry(rooms)
    with pytest.raises(ValueError):
        offer_variants("spare_2", frozenset(), reg, Rng(0))


def test_offer_variants_spare_1_offers_first_level_variants():
    """spare_1 offers exactly the first-level spare_room variants (variant_of == 'spare_room')."""
    rooms = [
        _fake_room("spare_room", 0),
        _fake_room("spare_v1", 1, variant_of="spare_room"),
        _fake_room("spare_v2", 2, variant_of="spare_room"),
        _fake_room("spare_v3", 3, variant_of="spare_room"),
    ]
    reg = _fake_registry(rooms)
    offered = set(offer_variants("spare_1", frozenset(), reg, Rng(0)))
    expected = {"spare_v1", "spare_v2", "spare_v3"}
    assert offered == expected, f"spare_1 should offer {expected}, got {offered}"


def test_offer_variants_spare_2_uses_applied_base_variant():
    """spare_2 uses the applied first-level spare variant to determine which sub-variants to offer."""
    # spare_v1 has sub-variants; spare_v2 has different sub-variants.
    rooms = [
        _fake_room("spare_room", 0),
        _fake_room("spare_v1", 1, variant_of="spare_room"),
        _fake_room("spare_v2", 2, variant_of="spare_room"),
        _fake_room("spare_v3", 3, variant_of="spare_room"),
        _fake_room("spare_v1_a", 4, variant_of="spare_v1"),
        _fake_room("spare_v1_b", 5, variant_of="spare_v1"),
        _fake_room("spare_v1_c", 6, variant_of="spare_v1"),
    ]
    reg = _fake_registry(rooms)
    applied = frozenset({"spare_v1"})
    offered = set(offer_variants("spare_2", applied, reg, Rng(0)))
    expected = {"spare_v1_a", "spare_v1_b", "spare_v1_c"}
    assert offered == expected, f"spare_2 with spare_v1 applied should offer {expected}, got {offered}"


def test_offer_variants_already_applied_not_excluded():
    """At saturation, offer_variants does not exclude already-applied variants.

    A 3-variant room must always present 3 options even if the current variant is applied.
    """
    rooms = [
        _fake_room("closet", 0),
        _fake_room("closet_v1", 1, variant_of="closet"),
        _fake_room("closet_v2", 2, variant_of="closet"),
        _fake_room("closet_v3", 3, variant_of="closet"),
    ]
    reg = _fake_registry(rooms)
    # closet_v1 is already applied — still must appear in the offered set.
    applied = frozenset({"closet_v1"})
    offered = offer_variants("closet", applied, reg, Rng(0))
    assert len(offered) == 3, "must always offer 3 even when a variant is already applied"
    assert set(offered) == {"closet_v1", "closet_v2", "closet_v3"}


# ---------------------------------------------------------------------------
# Integration test — the only test that touches the shipped data file
# ---------------------------------------------------------------------------

def test_integration_shipped_file_loadable_and_drivable():
    """Integration: load_tables() parses the shipped file and select_slot returns a selectable slot.

    Asserts no specific table values — only that the file is loadable and the algorithm
    produces a well-formed result for a fresh non-veteran context.
    """
    t = load_tables()
    assert isinstance(t, UpgradeTables)

    ctx = _ctx()  # fresh non-veteran context
    slot = select_slot(t, ctx, Rng(42))
    assert slot is not None, "select_slot should return a slot for a fresh context"
    assert slot_is_selectable(slot, ctx), f"returned slot {slot!r} must be selectable"
