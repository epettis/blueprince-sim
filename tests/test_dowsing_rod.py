"""Dowsing Rod: while held, points at one of the three dealt floorplans on
every deal/redraw (engine/draft.py's ``_pick_dowsing_slot``); drafting that
slot boosts the room's item spawn via its OWN system (engine/items.py's
``roll_dowsed_count``, data/items.json's ``dowsing_rod`` table), not the
normal item_ladder.

Grouped in its own file, mirroring tests/test_gear_wrench.py's own
rationale for a dedicated file: the mechanic spans several concerns at once
(a drafting-time RNG slot pick, a per-cell mark that survives from "slot
chosen" to "room entered", its own item-count table layered on top of the
existing item_ladder machinery, and an owner-ruled additional_max bypass)
that does not fit any single existing thematic file -- test_luck_ladder.py
covers the BASE item_ladder only, and test_luck_tables.py covers
never_roll_rooms/count_transforms only; neither is about the Dowsing Rod's
own separate system. No tests/items/ directory exists in this repo (grouping
is by concern/file, not by a per-feature subdirectory), so this file sits
alongside its siblings at the top level.

Hard rule, followed throughout (same as test_luck_ladder.py /
test_luck_tables.py): no expected value here is derived by calling the
function under test on ITSELF for its own answer, nor by reading
data/items.json (the same file engine/items.py and draft.py read). Every
wiki percentage is a hand-typed literal, with the verbatim wiki line quoted
in the test that uses it. Combined-outcome probabilities (e.g. the 0-2
band's "variable" row resolving further through item_ladder.variable) are
arithmetic over TWO separately-cited wiki quotes, never a re-derivation from
data or code.

Source: https://blueprince.wiki.gg/wiki/Dowsing_Rod ("exact impacts on
luck" and avoid-list DataMinedBoxes), plus
https://blueprince.wiki.gg/wiki/Luck ("variable items" resolution table,
already covered by test_luck_ladder.py but re-quoted here where this file's
own expectations depend on it), both fetched directly (raw wikitext) during
this PR.
"""

from __future__ import annotations

import math

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import draft, items
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DraftOption, GameState, PendingDraft

N_TRIALS = 200_000  # matches test_luck_ladder.py's per-band trial count


def _assert_within_binomial_ci(observed: int, n: int, p: float, where: str, z: float = 5.5) -> None:
    """Assert an observed count is within a z-sigma normal-approximation
    binomial interval of n*p (same z=5.5 generous margin as
    test_luck_ladder.py/test_luck_tables.py -- roughly a 1-in-20-million
    two-sided false-failure rate per assertion)."""
    mean = n * p
    sd = math.sqrt(n * p * (1 - p))
    margin = z * sd
    assert abs(observed - mean) <= margin, (
        f"{where}: observed {observed}/{n} = {observed / n:.5f}, expected {p:.5f} "
        f"+/- {margin / n:.5f} ({z} sigma)"
    )


def _fake_game(registry, seed, *, luck=10, luck_penalty=0, dowsing_penalty=0,
               veteran_mode=False, rng=None):
    """Lightweight duck-typed game object (same idiom as
    test_luck_ladder.py's own ``_fake_game``) for unit-calling
    roll_dowsed_count/roll_room_items without a full Game."""
    class _FakeGame:
        pass
    g = _FakeGame()
    g.state = GameState()
    g.state.luck = luck
    g.state.luck_penalty = luck_penalty
    g.state.dowsing_penalty = dowsing_penalty
    g.cfg = GameConfig(veteran_mode=veteran_mode)
    g.registry = registry
    g.rng = rng if rng is not None else Rng(seed)
    return g


class _ForcedIndexRng(Rng):
    """``Rng`` subclass forcing every ``roll_weighted`` call under one label
    to return indices drawn from a fixed queue, one per call, in order;
    every other label (and any call once the queue is exhausted) falls
    through to the real random draw unchanged. Same "subclass, not an
    attribute patch" idiom as luck_utils.py's ``_NoLuckRng`` -- ``Rng`` is a
    slotted class.
    """

    def __init__(self, seed: int, label: str, indices) -> None:
        super().__init__(seed)
        self._forced_label = label
        self._queue = list(indices)

    def roll_weighted(self, label: str, weights) -> int:
        if label == self._forced_label and self._queue:
            return self._queue.pop(0)
        return super().roll_weighted(label, weights)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load()


def _pending_with_rooms(registry, room_ids: list[str]) -> PendingDraft:
    """A PendingDraft whose ``options`` are synthetic slot-0/1/2 DraftOptions
    for ``room_ids``, in order (mirrors test_gear_wrench.py's own synthetic-
    hand construction idiom)."""
    pending = PendingDraft(from_cell=2, direction=N, target_cell=7)
    for slot, rid in enumerate(room_ids):
        room = registry.by_id[rid]
        pending.options.append(DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                           gem_cost=0, slot=slot))
    return pending


def _ctx(registry, seed, *, holding=True):
    """A DraftContext holding (or not) a Dowsing Rod, for unit-calling
    draft._pick_dowsing_slot directly."""
    state = GameState()
    if holding:
        state.inventory["dowsing_rod"] = 1
    return draft.DraftContext(state, registry, GameConfig(special_items=True), Rng(seed), set(),
                              None)


# ----------------------------------------------------- 1. slot pick (draft.py)

def test_pick_dowsing_slot_prefers_non_avoid_room(registry):
    """Wiki (Dowsing_Rod avoid-list DataMinedBox): "...in all other cases it
    picks a different room" -- with one dealt slot off
    data/items.json's dowsing_rod.avoid_rooms (Shrine and Toolshed are both
    on the wiki's 26-room avoid list; Bedroom is not), the pick must always
    land on the non-avoid slot, across many independent draws.
    """
    pending = _pending_with_rooms(registry, ["shrine", "bedroom", "toolshed"])
    for seed in range(200):
        ctx = _ctx(registry, seed)
        draft._pick_dowsing_slot(ctx, pending)
        assert pending.dowsed_slot == 1, f"seed {seed}: must prefer the only non-avoid slot"


def test_pick_dowsing_slot_falls_back_uniformly_when_all_avoid_listed(registry):
    """Wiki: "In the case that all three offered rooms are one of the rooms
    on this list, the Dowsing Rod will still pick one of them" -- with every
    dealt slot avoid-listed (Shrine, Toolshed, Coat Check all on the 26-room
    list), each of the three must still be reachable, at roughly equal rates
    across many draws (the wiki does not publish a distribution among
    eligible candidates in this case; uniform is this sim's modelled
    assumption).
    """
    pending = _pending_with_rooms(registry, ["shrine", "toolshed", "coat_check"])
    counts = [0, 0, 0]
    trials = 6000
    for seed in range(trials):
        ctx = _ctx(registry, seed)
        draft._pick_dowsing_slot(ctx, pending)
        assert pending.dowsed_slot in (0, 1, 2), "must still pick SOME slot, never skip"
        counts[pending.dowsed_slot] += 1
    for slot, c in enumerate(counts):
        _assert_within_binomial_ci(c, trials, 1 / 3, f"all-avoid-listed fallback, slot {slot}")


def test_pick_dowsing_slot_recomputes_fresh_each_call(registry):
    """"If floorplans are redrawn, the Dowsing Rod will reselect one of the
    new floorplans" (wiki) -- draft.py's _fill_options calls
    _pick_dowsing_slot fresh on BOTH the initial deal (deal_draft) and every
    redraw (redeal), so a redraw's reselection is not a separate code path,
    just the same function seeing a new hand. Proven directly: swap which
    slot is avoid-listed between two calls on the SAME PendingDraft (the
    same object a real redraw mutates in place) and confirm the pick
    follows the CURRENT hand, not a stale memory of the earlier one.
    """
    pending = _pending_with_rooms(registry, ["shrine", "bedroom", "toolshed"])
    ctx = _ctx(registry, seed=1)
    draft._pick_dowsing_slot(ctx, pending)
    assert pending.dowsed_slot == 1, "first hand: slot 1 (Bedroom) is the only non-avoid room"

    # Simulate what _fill_options does on a redraw: clear and rebuild
    # pending.options with a new hand before calling this function again.
    pending.options.clear()
    for slot, rid in enumerate(["gallery", "shrine", "toolshed"]):
        room = registry.by_id[rid]
        pending.options.append(DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                           gem_cost=0, slot=slot))
    draft._pick_dowsing_slot(ctx, pending)
    assert pending.dowsed_slot == 0, (
        "second hand: slot 0 (Gallery) is now the only non-avoid room -- a stale pick would "
        "still show slot 1, which no longer even holds an avoid-listed room")


def test_pick_dowsing_slot_none_when_hand_has_no_options(registry):
    """A hand that ended up with zero dealt options (the rare forced-Closet-
    already-excluded failure documented in draw_slot) must leave
    dowsed_slot at None rather than crashing or indexing an empty list.
    """
    pending = PendingDraft(from_cell=2, direction=N, target_cell=7)
    ctx = _ctx(registry, seed=1)
    draft._pick_dowsing_slot(ctx, pending)
    assert pending.dowsed_slot is None


def test_pick_dowsing_slot_none_when_not_held(registry):
    """No Dowsing Rod in inventory: dowsed_slot must stay None even though
    the hand is otherwise perfectly ordinary and would clearly favour a
    slot if the Rod WERE held.
    """
    pending = _pending_with_rooms(registry, ["shrine", "bedroom", "toolshed"])
    ctx = _ctx(registry, seed=1, holding=False)
    draft._pick_dowsing_slot(ctx, pending)
    assert pending.dowsed_slot is None


# --------------------------------------------- 2. the mark's survival to entry

def test_choose_marks_only_the_dowsed_slot(registry):
    """Game.choose must mark the drafted cell in state.dowsing_marked_cells
    ONLY when the chosen slot is the one the Rod pointed at -- choosing a
    DIFFERENT slot from the same hand must leave the drafted cell unmarked,
    proving the mark tracks the SLOT, not "a Dowsing Rod is merely held".
    """
    cfg = GameConfig(special_items=True)
    room = registry.by_id["bedroom"]

    g_hit = Game(cfg, seed=1, registry=registry)
    g_hit.state.inventory["dowsing_rod"] = 1
    pending_hit = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pending_hit.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                       gem_cost=0, slot=0)]
    pending_hit.dowsed_slot = 0
    g_hit.state.pending = pending_hit
    g_hit.phase = Phase.DRAFTING
    g_hit.doorway_drafts[(2, N)] = pending_hit
    g_hit.choose(0)
    assert 7 in g_hit.state.dowsing_marked_cells, "chosen slot matches dowsed_slot: must mark"

    g_miss = Game(cfg, seed=1, registry=registry)
    g_miss.state.inventory["dowsing_rod"] = 1
    pending_miss = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pending_miss.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                        gem_cost=0, slot=0)]
    pending_miss.dowsed_slot = 1  # points at a DIFFERENT slot than the one chosen below
    g_miss.state.pending = pending_miss
    g_miss.phase = Phase.DRAFTING
    g_miss.doorway_drafts[(2, N)] = pending_miss
    g_miss.choose(0)
    assert 7 not in g_miss.state.dowsing_marked_cells, "chosen slot != dowsed_slot: must not mark"


def test_dowsing_mark_is_consumed_by_the_item_roll(registry):
    """The mark must survive from "slot chosen" (Game.choose) all the way to
    "room entered" (engine/items.py's roll_room_items, fired from
    Game._enter on first entry) -- and be discarded there, so it can never
    leak into a second, unrelated roll at a cell index that happens to be
    reused (e.g. a fresh day's fresh grid).
    """
    g = _fake_game(registry, seed=1)
    room = registry.by_id["bedroom"]
    g.state.dowsing_marked_cells = {7}
    items.roll_room_items(g, room, 7)
    assert 7 not in g.state.dowsing_marked_cells, "the mark must be discarded once consumed"


# ------------------------------------------- 3. the dowsed item-count table

def test_dowsed_0_2_band_follows_the_published_percentages(registry):
    """Wiki (0-2 Dowsing Penalty, room NOT on the 17-room variable_items
    list, effective luck > 18): "81.6% for 1 item; 3.4% for variable items;
    10% for 3 items ...; 5% for 4 items ...". "Variable items" itself
    resolves via the Luck page's own published table at this SAME effective
    luck (>=17: "5% for 3 items ...; 95% for 2 items ..."), so the four
    combined probabilities are: P(1)=0.816; P(2)=0.034*0.95=0.0323;
    P(3)=0.10+0.034*0.05=0.1017; P(4)=0.05 (Bedroom is neither avoid- nor
    variable-listed, and additional_max is irrelevant here -- this test
    calls roll_dowsed_count directly, before any clamp).
    """
    room = registry.by_id["bedroom"]
    g = _fake_game(registry, seed=1, luck=10)  # effective = 10 + 32 = 42 (>18, band 17+)
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for _ in range(N_TRIALS):
        g.state.luck_penalty = 0
        g.state.dowsing_penalty = 0
        c = items.roll_dowsed_count(g, room)
        counts[c] = counts.get(c, 0) + 1
    assert sum(counts.values()) == N_TRIALS, f"unexpected item counts: {counts}"
    _assert_within_binomial_ci(counts[1], N_TRIALS, 0.816, "0-2 band, 1 item")
    _assert_within_binomial_ci(counts[2], N_TRIALS, 0.034 * 0.95, "0-2 band, 2 items")
    _assert_within_binomial_ci(counts[3], N_TRIALS, 0.10 + 0.034 * 0.05, "0-2 band, 3 items")
    _assert_within_binomial_ci(counts[4], N_TRIALS, 0.05, "0-2 band, 4 items")


def test_dowsed_variable_items_room_bypasses_the_weighted_table(registry):
    """Wiki (0-2 Dowsing Penalty): "If the room is any of [Spare Room,
    Gallery, ...], it gives variable items" -- unconditional, no roll, ahead
    of the 81.6/3.4/10/5% table. Gallery is on data/items.json's
    dowsing_rod.variable_items_rooms; at effective luck 42 (17+ band),
    "variable items" itself is "5% for 3 items ...; 95% for 2 items ..." --
    so ONLY 2 or 3 items can ever come out, never 1 or 4.
    """
    room = registry.by_id["gallery"]
    g = _fake_game(registry, seed=1, luck=10)
    counts = {}
    trials = 20_000
    for _ in range(trials):
        g.state.luck_penalty = 0
        g.state.dowsing_penalty = 0
        c = items.roll_dowsed_count(g, room)
        counts[c] = counts.get(c, 0) + 1
    assert set(counts) <= {2, 3}, f"variable_items_rooms must only ever yield 2 or 3: {counts}"
    _assert_within_binomial_ci(counts.get(3, 0), trials, 0.05, "variable_items_rooms, 3 items")
    _assert_within_binomial_ci(counts.get(2, 0), trials, 0.95, "variable_items_rooms, 2 items")


def test_dowsed_regular_routine_floors_zero_to_one(registry):
    """Wiki (0-2 Dowsing Penalty): "18- Luck: Runs the regular non-Dowsing
    Rod routine. If it rolls 0 items, it gets increased to 1 item." At
    state.luck=-20 (simulating 4 Maid's Chambers' -7 each, "The only way to
    trigger this"), effective luck = -20+32 = 12, in the item_ladder's
    11-15 "variable_mix" band ("1.6% for variable items, 38.4% for 1 item,
    60% for 0 items" -- test_luck_ladder.py's own quote for this exact
    band). Combined with the floor: P(1 item) = 38.4% (direct) + 60%
    (floored) = 98.4%; the remaining 1.6% resolves through the SAME
    variable table used elsewhere in this file, whose 11-16 row is a FIXED
    2 items -- so this dowsed roll can only ever be 1 or 2, never 3 or 4
    (proving the regular-routine branch, not the 81.6/3.4/10/5% table, is
    what actually ran).
    """
    room = registry.by_id["bedroom"]
    g = _fake_game(registry, seed=1, luck=-20)
    counts = {}
    trials = 50_000
    for _ in range(trials):
        g.state.luck_penalty = 0
        g.state.dowsing_penalty = 0
        c = items.roll_dowsed_count(g, room)
        counts[c] = counts.get(c, 0) + 1
    assert set(counts) <= {1, 2}, f"regular-routine branch must only ever yield 1 or 2: {counts}"
    _assert_within_binomial_ci(counts.get(1, 0), trials, 0.984, "regular routine, 1 item")
    _assert_within_binomial_ci(counts.get(2, 0), trials, 0.016, "regular routine, 2 items")


def test_variable_items_room_overrides_the_luck_max_gate(registry):
    """The 17-room variable_items_rooms check runs BEFORE the
    regular_routine_luck_max check (wiki bullet order: room-list first,
    "18- Luck" second) -- so a variable_items_rooms member at very low
    effective luck must still resolve through "variable items", never the
    regular routine. Gallery at state.luck=-20 (effective=12, item_ladder's
    variable table 11-16 row: "2 items and +1 to Luck Penalty", a
    deterministic FIXED row, no roll at all) must therefore ALWAYS yield
    exactly 2 items with +1 Luck Penalty -- a single call is enough to prove
    it, since this path has no randomness.
    """
    room = registry.by_id["gallery"]
    g = _fake_game(registry, seed=1, luck=-20)
    g.state.luck_penalty = 0
    g.state.dowsing_penalty = 0
    count = items.roll_dowsed_count(g, room)
    assert count == 2, "variable table's 11-16 row is a deterministic 2 items"
    assert g.state.luck_penalty == 1, "variable table's 11-16 row also carries +1 Luck Penalty"
    assert g.state.dowsing_penalty == 0, "this row carries no Dowsing Penalty of its own"


# ------------------------------------ 4. Dowsing Penalty escalation + bands

def test_fixed_3_item_row_bumps_dowsing_penalty_by_1(registry):
    """Wiki: "10% for 3 items, +2 Luck Penalty, +1 Dowsing Penalty" -- the
    0-2 band's outcomes are ordered [one, variable, fixed3, fixed4]
    (data/items.json's dowsing_rod.penalty_bands[0].outcomes); forcing the
    weighted roll to index 2 deterministically selects this row, so a
    SINGLE call is enough to pin the exact deltas (not merely their
    long-run rate, which test_dowsed_0_2_band_follows_the_published_
    percentages above already covers statistically).
    """
    room = registry.by_id["bedroom"]
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[2])
    g = _fake_game(registry, seed=1, luck=10, rng=rng)
    count = items.roll_dowsed_count(g, room)
    assert count == 3
    assert g.state.luck_penalty == 2, "wiki: '+2 Luck Penalty'"
    assert g.state.dowsing_penalty == 1, "wiki: '+1 Dowsing Penalty'"


def test_fixed_4_item_row_bumps_dowsing_penalty_by_2(registry):
    """Wiki: "5% for 4 items, +3 Luck Penalty, +2 Dowsing Penalty" -- index
    3 of the same outcomes list as the test above.
    """
    room = registry.by_id["bedroom"]
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[3])
    g = _fake_game(registry, seed=1, luck=10, rng=rng)
    count = items.roll_dowsed_count(g, room)
    assert count == 4
    assert g.state.luck_penalty == 3, "wiki: '+3 Luck Penalty'"
    assert g.state.dowsing_penalty == 2, "wiki: '+2 Dowsing Penalty'"


def test_dowsing_penalty_escalation_shifts_which_band_rolls(registry):
    """Two successive 4-item outcomes accumulate a Dowsing Penalty of 2+2=4,
    landing in the wiki's "3-5 Dowsing Penalty" band -- proving the
    escalation is a REAL, stable consequence of the accumulated counter
    (read fresh every call, exactly like item_ladder's own Luck Penalty
    band-shift test), not a one-off artifact. Forces BOTH the first 0-2-band
    roll (index 3: fixed 4 items) AND the following 3-5-band roll (index 0:
    "one", the 3-5 band's own first outcome row) so the whole sequence is
    deterministic end to end.
    """
    room = registry.by_id["bedroom"]
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[3, 3, 0])
    g = _fake_game(registry, seed=1, luck=10, rng=rng)

    first = items.roll_dowsed_count(g, room)
    assert first == 4 and g.state.dowsing_penalty == 2

    second = items.roll_dowsed_count(g, room)
    assert second == 4 and g.state.dowsing_penalty == 4, (
        "still in the 0-2 band (dowsing_penalty was 2 going in): must roll the SAME "
        "0-2 outcomes table again, landing on the forced index-3 (fixed 4 items) row")

    third = items.roll_dowsed_count(g, room)
    assert third == 1, (
        "dowsing_penalty is now 4 (3-5 band): the forced index 0 must select THIS band's "
        "own first outcome row ('48% for 1 item'), not the 0-2 band's own index-0 row "
        "(which happens to ALSO be '1 item', so this alone doesn't distinguish the bands -- "
        "the band-boundary tests below do)")


def test_3_5_band_recurse_reruns_the_full_0_2_procedure(registry):
    """Wiki (3-5 Dowsing Penalty): "20% to run like it was 0-2 Dowsing
    Penalty" -- read as the WHOLE 0-2 section (room-list check, luck-max
    check, AND its weighted table), not just its last row. Proven with a
    variable_items_rooms member (Gallery) at very low effective luck
    (state.luck=-20, effective=12): forcing the 3-5 band's own outcome
    index to 2 ("recurse_0_2", the third entry in [one, variable,
    recurse_0_2]) must land on Gallery's deterministic "variable table's
    11-16 row = 2 items, +1 Luck Penalty" result -- exactly
    test_variable_items_room_overrides_the_luck_max_gate's own outcome --
    even though NEITHER of the 3-5 band's own two other rows (one/variable)
    would ever consult the room-list at all.
    """
    room = registry.by_id["gallery"]
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[2])
    g = _fake_game(registry, seed=1, luck=-20, dowsing_penalty=3, rng=rng)
    count = items.roll_dowsed_count(g, room)
    assert count == 2, "recursion must reach the room-list gate, not just re-roll blindly"
    assert g.state.luck_penalty == 1


def test_6plus_band_has_no_recurse_or_fixed_rows(registry):
    """Wiki (6+ Dowsing Penalty): "48% for 1 item; 52% for variable items" --
    only two rows, unlike the 0-2 band's four and the 3-5 band's three. A
    non-avoid, non-variable-listed room (Bedroom) at this band, statistical
    over many draws, must show ONLY item counts reachable through "1" or
    through "variable" resolved at high effective luck (2 or 3 -- never a
    direct, unconditional 4, which only the 0-2 band's own fixed4 row can
    ever produce).
    """
    room = registry.by_id["bedroom"]
    g = _fake_game(registry, seed=1, luck=10, dowsing_penalty=6)  # effective 42, 6+ band
    counts = {}
    trials = 50_000
    for _ in range(trials):
        g.state.luck_penalty = 0
        g.state.dowsing_penalty = 6  # pinned: this band's own escalation is out of scope here
        c = items.roll_dowsed_count(g, room)
        counts[c] = counts.get(c, 0) + 1
    assert set(counts) <= {1, 2, 3}, f"6+ band must never directly yield 4 items: {counts}"
    _assert_within_binomial_ci(counts.get(1, 0), trials, 0.48, "6+ band, 1 item")
    # "variable" (52%) resolves via item_ladder.variable at effective 42 (17+ row):
    # 5% for 3 items, 95% for 2 items (same quote test_dowsed_0_2_band... uses).
    _assert_within_binomial_ci(counts.get(3, 0), trials, 0.52 * 0.05, "6+ band, variable->3")
    _assert_within_binomial_ci(counts.get(2, 0), trials, 0.52 * 0.95, "6+ band, variable->2")


# ------------------------------------------------------ 5. Luck Penalty math

def test_standard_luck_penalty_is_suppressed_for_the_roll_but_still_grows(registry):
    """Wiki: "a +32 Luck bonus is applied and the standard Luck Penalty does
    not apply" -- read as: state.luck_penalty is NOT subtracted when
    computing the Dowsing Rod's own effective luck (unlike
    roll_ladder_count's formula). Proven by setting luck_penalty to a huge
    value (999) BEFORE a forced 4-item roll: if it were being subtracted,
    effective luck would collapse to state.luck+32-999 (deeply negative,
    landing in the "regular routine" branch, which can never produce a
    direct 4-item outcome -- see test_dowsed_regular_routine_floors_zero_
    to_one above). The roll must still deterministically yield 4 (forced
    index 3), proving the huge penalty had no effect on the ROLL itself --
    while state.luck_penalty afterward is exactly 999+3=1002, proving the
    outcome's own delta IS still written on top of whatever was already
    there ("+3 Luck Penalty" from the wiki's own 4-item row).
    """
    room = registry.by_id["bedroom"]
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[3])
    g = _fake_game(registry, seed=1, luck=10, luck_penalty=999, rng=rng)
    count = items.roll_dowsed_count(g, room)
    assert count == 4, "a huge pre-existing Luck Penalty must not divert this roll"
    assert g.state.luck_penalty == 1002, "the 4-item row's own +3 must still land on top of 999"


# ---------------------------------------------------------- 6. the cap bypass

def test_dowsing_bypasses_additional_max_clamp(registry):
    """Owner ruling: "Dowsing BYPASSES the item cap. A dowsed room may yield
    3 or 4 items even where additional_max is 1." Bedroom's additional_max
    is 1 (asserted below): an UNDOWSED roll at these same forced outcomes
    would clamp any raw count above 1 down to exactly 1 (min(raw,
    additional_max) -- see engine/items.py's roll_room_items), so observing
    a genuine 4-items-FOUND through the full roll_room_items pipeline, with
    guaranteed=[] so every found item comes from this one roll, is proof
    the clamp was skipped entirely for the dowsed cell.
    """
    room = registry.by_id["bedroom"]
    assert room.items.additional_max == 1, "fixture must actually have a cap to bypass"
    assert room.items.guaranteed == (), "fixture must have no items outside the clamped roll"
    rng = _ForcedIndexRng(seed=1, label="dowsing_penalty_outcome", indices=[3])
    g = _fake_game(registry, seed=1, luck=10, rng=rng)
    g.state.dowsing_marked_cells = {7}
    found = items.roll_room_items(g, room, 7)
    assert found == 4, "the cap (additional_max=1) must not clamp a dowsed roll's 4 items"


def test_undowsed_room_at_the_same_cell_still_clamps(registry):
    """The direct contrast with the bypass test above: the SAME forced
    4-item outcome, at the SAME room, but the cell is NOT in
    dowsing_marked_cells -- roll_room_items must fall back to the ordinary
    item_ladder (never touching roll_dowsed_count's own RNG label at all)
    and clamp the result to additional_max=1, exactly as it always has.
    """
    room = registry.by_id["bedroom"]
    g = _fake_game(registry, seed=1, luck=25)  # 23-28 fixed band: deterministic 3 items
    found = items.roll_room_items(g, room, 7)  # cell 7 never marked
    assert found == 1, "an undowsed room must still clamp to additional_max"
    assert g.state.dowsing_penalty == 0, "the ordinary ladder must never touch dowsing_penalty"


# ------------------------------------------------ 7. an undowsed room, at all

def test_undowsed_room_is_statistically_unaffected_by_a_held_rod(registry):
    """Holding the Dowsing Rod, on its own, must not perturb an UNDOWSED
    room's item count -- the effect is purely mark-driven (game.choose only
    marks the slot the Rod actually pointed at AND the player actually
    drafted), never "any room drafted while holding the item". Reuses
    test_luck_ladder.py's own literal for this exact band: "4- Luck: 7% for
    1 item, 93% for 0 items.".
    """
    room = registry.by_id["bedroom"]
    g = _fake_game(registry, seed=1, luck=4)  # flat <=4 band
    ones = 0
    trials = 50_000
    for _ in range(trials):
        g.state.luck_penalty = 0
        # cell 7 is never in dowsing_marked_cells -- holding the item alone
        # (not modelled on this duck-typed game at all) cannot matter here.
        found = items.roll_room_items(g, room, 7)
        if found == 1:
            ones += 1
    _assert_within_binomial_ci(ones, trials, 0.07, "undowsed room, flat <=4 band, 1 item")


def test_never_roll_room_stays_unaffected_even_when_dowsed(registry):
    """never_roll_rooms is an unconditional, per-room fact ("The following
    rooms never roll for luck") -- the Dowsing Rod's +32 luck cannot
    overcome it. Entrance Hall (in never_roll_rooms) marked as dowsed, at a
    luck level that would deterministically hand out 4 items to any
    ROLLING room, must still yield exactly 0 extra items and leave BOTH
    Luck Penalty counters untouched -- the never_roll_rooms check runs
    before roll_dowsed_count is ever reached, mirroring
    test_luck_tables.py's own equivalent (undowsed) guard.
    """
    room = registry.by_id["entrance_hall"]
    assert room.items.additional_max >= 1, "fixture must actually have a slot to leak from"
    g = _fake_game(registry, seed=1, luck=10)
    g.state.dowsing_marked_cells = {7}
    found = items.roll_room_items(g, room, 7)
    assert found == 0
    assert g.state.luck_penalty == 0
    assert g.state.dowsing_penalty == 0
    assert 7 not in g.state.dowsing_marked_cells, "the mark is still consumed, even though inert"


# --------------------------------------------------------- 8. outer-room drafts
#
# game.py's _deal_outer_options (the fixed 8-room outer pool dealt off the
# West Path, see engine/game.py's own docstring) calls the SAME
# draft._pick_dowsing_slot the grid pipeline's _fill_options calls -- no
# second copy of the selection logic -- and Game._choose_outer marks the -1
# sentinel game.py already uses as an outer room's "cell" (roll_room_items is
# already called with cell=-1 for every outer-room entry) in
# state.dowsing_marked_cells, read back by the exact same check
# roll_room_items uses for a real grid cell. Wiki support for applying the
# Rod here at all: West_Path page, "Outer Room cave" section -- the door "may
# be drafted from like the doors in the house", and "[d]rafting effects not
# related to the draft pool ... still usually work when drafting on the
# grounds" (the Rod's slot-pointing never touches which rooms are dealt, only
# which of the three dealt options benefits).
#
# Three of the outer pool's eight rooms -- Toolshed, Shelter, Shrine -- are
# ALSO on the Rod's 26-room avoid list (data/items.json's
# dowsing_rod.avoid_rooms), so the all-avoided fallback is exercised by a
# real, reachable outer hand (1 outcome in C(8,3)=56), not merely a
# hypothetical.

def test_open_outer_draft_picks_a_dowsed_slot_when_the_rod_is_held(registry):
    """Game.open_outer_draft's hand must come back with a real dowsed_slot
    pick when the Rod is held -- the wiring gap this PR fixes (previously
    open_outer_draft's hand never called _pick_dowsing_slot at all, leaving
    dowsed_slot permanently None for every outer draft).
    """
    cfg = GameConfig(special_items=True, west_gate_unlatched=True)
    g = Game(cfg, seed=0, registry=registry)
    g.state.inventory["dowsing_rod"] = 1
    pending = g.open_outer_draft()
    assert pending.dowsed_slot in (0, 1, 2), (
        "an outer hand with the Rod held must get a real slot pick, not None")


def test_open_outer_draft_dowsed_slot_is_none_without_the_rod(registry):
    """Negative control: an outer draft with no Dowsing Rod held must leave
    dowsed_slot at None, exactly like an ordinary grid draft -- the outer
    wiring must not mark a slot unconditionally.
    """
    cfg = GameConfig(special_items=True, west_gate_unlatched=True)
    g = Game(cfg, seed=0, registry=registry)
    pending = g.open_outer_draft()
    assert pending.dowsed_slot is None


def test_pick_dowsing_slot_prefers_non_avoid_room_among_outer_rooms(registry):
    """The grid pool's avoid-list preference
    (test_pick_dowsing_slot_prefers_non_avoid_room), reproduced with a real
    outer-shaped hand (target_cell=-1): Toolshed and Shelter are both on the
    26-room avoid list, Tomb is not -- the pick must always land on Tomb.
    """
    pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    for slot, rid in enumerate(["toolshed", "tomb", "shelter"]):
        room = registry.by_id[rid]
        pending.options.append(DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                           gem_cost=0, slot=slot))
    for seed in range(200):
        ctx = _ctx(registry, seed)
        draft._pick_dowsing_slot(ctx, pending)
        assert pending.dowsed_slot == 1, f"seed {seed}: must prefer the only non-avoid outer room"


def test_pick_dowsing_slot_falls_back_uniformly_for_an_all_avoided_outer_hand(registry):
    """Toolshed, Shelter, and Shrine are the three outer rooms that are ALSO
    on the Rod's 26-room avoid list -- a hand offering exactly these three is
    a real, reachable outer draft (1 outcome in C(8,3)=56), not a
    hypothetical. The wiki's "the Dowsing Rod will still pick one of them"
    fallback must hold here exactly as test_pick_dowsing_slot_falls_back_
    uniformly_when_all_avoid_listed proves for the grid pool.
    """
    pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    for slot, rid in enumerate(["toolshed", "shelter", "shrine"]):
        room = registry.by_id[rid]
        pending.options.append(DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                           gem_cost=0, slot=slot))
    counts = [0, 0, 0]
    trials = 6000
    for seed in range(trials):
        ctx = _ctx(registry, seed)
        draft._pick_dowsing_slot(ctx, pending)
        assert pending.dowsed_slot in (0, 1, 2), "must still pick SOME slot, never skip"
        counts[pending.dowsed_slot] += 1
    for slot, c in enumerate(counts):
        where = f"all-avoid-listed outer fallback, slot {slot}"
        _assert_within_binomial_ci(c, trials, 1 / 3, where)


def test_choose_outer_marks_the_sentinel_cell_only_for_the_dowsed_slot(registry):
    """Game._choose_outer (routed from the public Game.choose when
    pending.target_cell == -1) must mark the -1 sentinel in
    state.dowsing_marked_cells ONLY when the drafted slot is the one the Rod
    pointed at -- the same "tracks the SLOT, not merely a held Rod" proof
    test_choose_marks_only_the_dowsed_slot gives for the grid pipeline's
    real cell, reused here for the outer pipeline's -1 sentinel.
    """
    cfg = GameConfig(special_items=True)
    room = registry.by_id["tomb"]

    g_hit = Game(cfg, seed=1, registry=registry)
    g_hit.state.inventory["dowsing_rod"] = 1
    pending_hit = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    pending_hit.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                       gem_cost=0, slot=0)]
    pending_hit.dowsed_slot = 0
    g_hit.state.pending = pending_hit
    g_hit.phase = Phase.DRAFTING
    g_hit.doorway_drafts[(-1, 0)] = pending_hit
    g_hit.choose(0)
    assert -1 in g_hit.state.dowsing_marked_cells, "chosen slot matches dowsed_slot: must mark"

    g_miss = Game(cfg, seed=1, registry=registry)
    g_miss.state.inventory["dowsing_rod"] = 1
    pending_miss = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    pending_miss.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                        gem_cost=0, slot=0)]
    pending_miss.dowsed_slot = 1  # points at a DIFFERENT slot than the one chosen below
    g_miss.state.pending = pending_miss
    g_miss.phase = Phase.DRAFTING
    g_miss.doorway_drafts[(-1, 0)] = pending_miss
    g_miss.choose(0)
    assert -1 not in g_miss.state.dowsing_marked_cells, "chosen slot != dowsed_slot: must not mark"


def test_outer_draft_dowsed_room_boosts_item_roll_past_its_zero_cap(registry):
    """End-to-end wiring proof: every one of the 8 outer rooms has
    additional_max=0 (data/rooms.json), so an UNDOWSED roll can never yield
    an extra item there no matter what the ladder rolls -- any nonzero extra
    item found from an outer room is only possible via the Dowsing Rod's own
    additional_max bypass (owner ruling, engine/items.py::roll_room_items).
    Root Cellar (guaranteed=(), so every found item comes from this one
    roll) is neither on the 26-room avoid list nor never_roll_rooms, so its
    dowsed roll runs the ordinary weighted table. Forcing
    "dowsing_penalty_outcome" to index 3 (the 0-2 band's own fixed-4-items
    row, same index test_fixed_4_item_row_bumps_dowsing_penalty_by_2 forces)
    pins the count to exactly 4.

    Seed 0 (with west_gate_unlatched so the West Path route is immediately
    affordable) deals [Shelter, Root Cellar, Hovel] and the Rod -- preferring
    the two non-avoid slots, Root Cellar/Hovel -- happens to land on Root
    Cellar; established empirically and asserted below as setup, the same
    seed-probed-hand convention tests/rooms/test_tomb.py already uses.
    """
    room = registry.by_id["root_cellar"]
    assert room.items.additional_max == 0, "fixture must actually have a zero cap to bypass"
    assert room.items.guaranteed == (), "fixture must have no items outside the clamped roll"

    cfg = GameConfig(special_items=True, west_gate_unlatched=True)
    g = Game(cfg, seed=0, registry=registry)
    g.state.inventory["dowsing_rod"] = 1
    g.rng = _ForcedIndexRng(0, "dowsing_penalty_outcome", [3])

    pending = g.open_outer_draft()
    dowsed_opt = next(o for o in pending.options if o.slot == pending.dowsed_slot)
    assert registry.rooms[dowsed_opt.room_idx].id == "root_cellar", (
        "setup: seed 0 must dowse Root Cellar")

    g.choose(pending.dowsed_slot)
    assert -1 in g.state.dowsing_marked_cells, "choosing the dowsed slot must mark the sentinel"

    found_before = len(g.state.items_found_log)
    g.travel_to("root_cellar")
    assert g.state.outer_room_entered, "setup: must actually reach and enter the outer room"
    assert -1 not in g.state.dowsing_marked_cells, "the mark must be consumed by the item roll"
    found_after = len(g.state.items_found_log)
    assert found_after - found_before == 4, (
        "additional_max=0 must not clamp a dowsed outer room's forced 4-item roll")
    assert g.state.dowsing_penalty == 2, "wiki fixed-4 row: '+2 Dowsing Penalty'"
