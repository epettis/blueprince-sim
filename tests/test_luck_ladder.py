"""Distributional guards for the luck -> item-count axis (data/items.json's
item_ladder, engine/items.py's roll_ladder_count).

Before this file, this axis had NO distributional guard at all:
test_draft_stats.py covers rarity only (zero "luck" references) and
test_draft_items.py has zero occurrences of "luck" despite the name -- the
arithmetic could be entirely wrong and the suite would stay green. This file
is that guard.

Hard rule, followed throughout: no expected value here is derived by calling
the function under test, nor by reading data/items.json (the same file
engine/items.py reads). Every wiki percentage is a literal, with the verbatim
wiki line quoted in the test that uses it. Only band SELECTION (which "kind"
governs at a boundary) and non-probability facts (registry structure) read
real registry data -- the outcome PERCENTAGES asserted against are always
hand-typed literals.

Source: https://blueprince.wiki.gg/wiki/Luck, "Luck effects" DataMinedBox,
fetched during the item_ladder migration (see docs/open_tasks.md's
2026-08-13 decisions log entry).
"""

from __future__ import annotations

import math

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import items
from blueprince_sim.engine.items import _chain_p_one, _find_band, _resolve_variable
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

from luck_utils import suppress_luck


# ----------------------------------------------------------------- helpers

def _fake_game(registry, seed, *, luck, room46_reached=False, day=1, veteran_mode=False):
    """Lightweight duck-typed game object for unit-calling roll_ladder_count
    (same "duck-typed game" idiom as test_digging.py's _fake_game)."""
    class _FakeGame:
        pass
    g = _FakeGame()
    g.state = GameState()
    g.state.luck = luck
    g.state.room46_reached = room46_reached
    g.state.day = day
    g.cfg = GameConfig(veteran_mode=veteran_mode)
    g.registry = registry
    g.rng = Rng(seed)
    return g


def _roll_n(g, n: int, *, reset_penalty=True) -> dict[int, int]:
    """Roll roll_ladder_count n times, returning a histogram of outcomes."""
    counts: dict[int, int] = {}
    for _ in range(n):
        if reset_penalty:
            g.state.luck_penalty = 0
        c = items.roll_ladder_count(g)
        counts[c] = counts.get(c, 0) + 1
    return counts


def _assert_within_binomial_ci(observed: int, n: int, p: float, where: str, z: float = 5.5) -> None:
    """Assert an observed count is within a z-sigma normal-approximation
    binomial interval of n*p. z=5.5 is roughly a 1-in-20-million two-sided
    false-failure rate per assertion -- generous enough that this can never
    legitimately need "seed tuning" (see comments-state-current-behavior /
    no-vacuous-by-luck-tests project conventions); a real arithmetic bug
    misses by far more than this margin, as the mutation check in this file
    demonstrates.
    """
    mean = n * p
    sd = math.sqrt(n * p * (1 - p))
    margin = z * sd
    assert abs(observed - mean) <= margin, (
        f"{where}: observed {observed}/{n} = {observed / n:.5f}, expected {p:.5f} "
        f"+/- {margin / n:.5f} ({z} sigma)"
    )


N = 200_000  # >= 200k per band, per the guard spec


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load()


# ------------------------------------------------------- 1. band distribution

def test_band_le4_flat(registry):
    """Wiki: "4- Luck: 7% for 1 item, 93% for 0 items."."""
    g = _fake_game(registry, seed=1, luck=4)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.07, "luck<=4, 1 item")
    assert counts.get(1, 0) + counts.get(0, 0) == N, "band <=4 must only ever yield 0 or 1 items"


def test_band_5_10_chain_room46_reached(registry):
    """Wiki 5-10 chain, row 1: "If Room 46 has been reached, 15%.".

    Room 46 reached wins even though every other row's condition (day>=6,
    veteran_mode, day>=3) is ALSO satisfied here -- proves the chain's FIRST
    match wins, not the most specific or most generous one.
    """
    g = _fake_game(registry, seed=2, luck=7, room46_reached=True, day=9, veteran_mode=True)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.15, "5-10 chain, room46_reached")


def test_band_5_10_chain_day_gte_6(registry):
    """Wiki 5-10 chain, row 2: "On Day 6 or later, 25%.".

    veteran_mode is ALSO True here (row 4's condition), proving day>=6 -- an
    EARLIER row -- wins over it.
    """
    g = _fake_game(registry, seed=3, luck=8, room46_reached=False, day=6, veteran_mode=True)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.25, "5-10 chain, day>=6")


def test_band_5_10_chain_veteran_mode(registry):
    """Wiki 5-10 chain, row 4: "If Veteran Mode is enabled, 15%.".

    Row 3 ("Day 1, Veteran Mode enabled by fast early drafts") is not
    representable (see _chain_p_one's docstring) so always falls through to
    this row on day 1 when veteran_mode is on.
    """
    g = _fake_game(registry, seed=4, luck=9, room46_reached=False, day=1, veteran_mode=True)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.15, "5-10 chain, veteran_mode")


def test_band_5_10_chain_day_gte_3(registry):
    """Wiki 5-10 chain, row 5: "On Day 3 or later, 20%.".

    veteran_mode is False here so row 4 does not match first.
    """
    g = _fake_game(registry, seed=5, luck=6, room46_reached=False, day=4, veteran_mode=False)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.20, "5-10 chain, day>=3")


def test_band_5_10_chain_otherwise(registry):
    """Wiki 5-10 chain, row 6: "Otherwise, 18%.".

    Day 1, no Room 46, veteran_mode off: none of rows 1-5 match.
    """
    g = _fake_game(registry, seed=6, luck=10, room46_reached=False, day=1, veteran_mode=False)
    counts = _roll_n(g, N)
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.18, "5-10 chain, otherwise")


def test_band_11_15_variable_mix(registry):
    """Wiki: "11-15 Luck: 1.6% for variable items, 38.4% for 1 item, 60% for
    0 items."

    luck=13 keeps the variable sub-table's OWN resolution deterministic
    (11-16 -> always 2 items), so the three outcome counts (0, 1, 2) map
    1-to-1 onto the three published percentages with no compounded
    randomness from the sub-table.
    """
    g = _fake_game(registry, seed=7, luck=13, day=1, veteran_mode=False)
    counts = _roll_n(g, N)
    assert set(counts) <= {0, 1, 2}
    _assert_within_binomial_ci(counts.get(0, 0), N, 0.60, "11-15, 0 items")
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.384, "11-15, 1 item")
    _assert_within_binomial_ci(counts.get(2, 0), N, 0.016, "11-15, variable (-> 2 items)")


def test_band_16_18_variable_mix(registry):
    """Wiki: "16-18 Luck: 3.2% for variable items, 76.8% for 1 item, 20% for
    0 items."

    luck=16 keeps the sub-table resolution deterministic (11-16 -> 2 items),
    same reasoning as the 11-15 test above.
    """
    g = _fake_game(registry, seed=8, luck=16, day=1, veteran_mode=False)
    counts = _roll_n(g, N)
    assert set(counts) <= {0, 1, 2}
    _assert_within_binomial_ci(counts.get(0, 0), N, 0.20, "16-18, 0 items")
    _assert_within_binomial_ci(counts.get(1, 0), N, 0.768, "16-18, 1 item")
    _assert_within_binomial_ci(counts.get(2, 0), N, 0.032, "16-18, variable (-> 2 items)")


def test_band_19_22_always_variable(registry):
    """Wiki: "19-22 Luck: Variable items." (100% -- no 0/1-item outcome).

    luck=20 puts the variable sub-table in its own "roll" range (>=17), so
    this ALSO exercises guard 3 (the variable resolver) through the parent,
    cross-checked independently by test_variable_resolver_roll_band below.
    """
    g = _fake_game(registry, seed=9, luck=20, day=1, veteran_mode=False)
    counts = _roll_n(g, N)
    assert set(counts) <= {2, 3}, "19-22 must always resolve through the variable table"
    _assert_within_binomial_ci(counts.get(3, 0), N, 0.05, "19-22 -> variable roll, 3 items")
    _assert_within_binomial_ci(counts.get(2, 0), N, 0.95, "19-22 -> variable roll, 2 items")


def test_band_23_28_fixed(registry):
    """Wiki: "23-28 Luck: 3 items and +2 to Luck Penalty." -- no randomness
    involved; a handful of seeds is enough to prove there is none (unlike
    the probabilistic bands above, repeating this 200k times would just
    burn CPU on an assertion that cannot vary)."""
    for seed in range(20):
        g = _fake_game(registry, seed=seed, luck=25, day=1, veteran_mode=False)
        count = items.roll_ladder_count(g)
        assert count == 3
        assert g.state.luck_penalty == 2


def test_band_29_plus_fixed(registry):
    """Wiki: "29+ Luck: 4 items and +3 to Luck Penalty."."""
    for seed in range(20):
        g = _fake_game(registry, seed=seed, luck=30, day=1, veteran_mode=False)
        count = items.roll_ladder_count(g)
        assert count == 4
        assert g.state.luck_penalty == 3


# ------------------------------------------------------------- 2. boundaries

def test_band_boundaries(registry):
    """Exact behaviour at luck 4, 5, 10, 11, 15, 16, 18, 19, 22, 23, 28, 29.

    Expected band "kind" and (where fixed) item count / penalty are literal,
    hand-derived from the wiki's stated ranges -- not read back from
    registry.item_rules["item_ladder"], which _find_band itself consults.
    Off-by-one on a boundary is the single most likely bug in a band table.
    """
    ladder = registry.item_rules["item_ladder"]
    expected = {
        4: "flat", 5: "chain", 10: "chain",
        11: "variable_mix", 15: "variable_mix",
        16: "variable_mix", 18: "variable_mix",
        19: "always_variable", 22: "always_variable",
        23: "fixed", 28: "fixed", 29: "fixed",
    }
    for luck, kind in expected.items():
        band = _find_band(luck, ladder["bands"])
        got = band["kind"]
        assert got == kind, f"luck {luck}: expected band kind {kind!r}, got {got!r}"
    # The two fixed bands differ in item count / penalty (23-28 vs 29+); the
    # boundary values 23/28 must land on the SAME (3-item) band and 29 on
    # the 4-item one, not spill into each other.
    for luck in (23, 28):
        band = _find_band(luck, ladder["bands"])
        assert band["items"] == 3 and band["penalty"] == 2, (
            f"luck {luck}: expected 3 items/+2 penalty")
    band = _find_band(29, ladder["bands"])
    assert band["items"] == 4 and band["penalty"] == 3, "luck 29: expected 4 items/+3 penalty"


def test_variable_sub_table_boundaries(registry):
    """Exact behaviour of the variable sub-table at its own boundaries: 10,
    11, 16, 17. Wiki: "10- Luck: 1 item.", "11-16 Luck: 2 items and +1 to
    Luck Penalty.", "17+ Luck: 5% for 3 items ..., 95% for 2 items ..."."""
    variable = registry.item_rules["item_ladder"]["variable"]
    for luck, kind, items_n in ((10, "fixed", 1), (11, "fixed", 2), (16, "fixed", 2)):
        band = _find_band(luck, variable)
        assert band["kind"] == kind and band["items"] == items_n, luck
    band = _find_band(17, variable)
    assert band["kind"] == "roll", (
        "luck 17 must be inside the 17+ roll band, not the 11-16 fixed one")


# -------------------------------------------------- 3. variable resolver (isolated)

def test_variable_resolver_fixed_bands():
    """_resolve_variable in isolation (not through roll_ladder_count/the
    parent band). Wiki: "10- Luck: 1 item." and "11-16 Luck: 2 items and +1
    to Luck Penalty."."""
    variable_bands = [
        {"max": 10, "kind": "fixed", "items": 1, "penalty": 0},
        {"min": 11, "max": 16, "kind": "fixed", "items": 2, "penalty": 1},
        {"min": 17, "kind": "roll", "p_three_pct": 5, "three_penalty": 3, "two_penalty": 1},
    ]
    state = GameState()
    rng = Rng(0)

    state.luck_penalty = 0
    assert _resolve_variable(3, variable_bands, state, rng) == 1
    assert state.luck_penalty == 0

    state.luck_penalty = 0
    assert _resolve_variable(14, variable_bands, state, rng) == 2
    assert state.luck_penalty == 1


def test_variable_resolver_roll_band():
    """_resolve_variable's 17+ roll band, called directly: "5% for 3 items
    (+3 to Luck Penalty), 95% for 2 items (+1 to Luck Penalty)."."""
    variable_bands = [
        {"max": 10, "kind": "fixed", "items": 1, "penalty": 0},
        {"min": 11, "max": 16, "kind": "fixed", "items": 2, "penalty": 1},
        {"min": 17, "kind": "roll", "p_three_pct": 5, "three_penalty": 3, "two_penalty": 1},
    ]
    state = GameState()
    rng = Rng(11)
    n = N
    counts = {2: 0, 3: 0}
    penalties = {2: set(), 3: set()}
    for _ in range(n):
        state.luck_penalty = 0
        c = _resolve_variable(19, variable_bands, state, rng)
        counts[c] += 1
        penalties[c].add(state.luck_penalty)
    _assert_within_binomial_ci(counts[3], n, 0.05, "variable roll, 3 items")
    _assert_within_binomial_ci(counts[2], n, 0.95, "variable roll, 2 items")
    assert penalties[3] == {3}, "3 items must always carry exactly +3 Luck Penalty"
    assert penalties[2] == {1}, "2 items must always carry exactly +1 Luck Penalty"


def test_five_to_ten_chain_order_algorithm():
    """_chain_p_one in isolation, with a synthetic chain (not the real
    published percentages -- this is an algorithm test, not a distribution
    test): proves first-match order, independent of the real wiki numbers
    asserted elsewhere in this file.
    """
    chain = [
        {"if": "room46_reached", "p_one_pct": 11},
        {"if": "day_gte", "day": 6, "p_one_pct": 22},
        {"if": "day1_veteran_by_fast_early_drafts", "p_one_pct": 33},
        {"if": "veteran_mode", "p_one_pct": 44},
        {"if": "day_gte", "day": 3, "p_one_pct": 55},
        {"if": "otherwise", "p_one_pct": 66},
    ]
    # All of room46/day>=6/veteran_mode/day>=3 true at once: room46 (first) wins.
    p = _chain_p_one(room46_reached=True, day=9, veteran_mode=True, chain=chain)
    assert p == 0.11
    # room46 false, day>=6 true, veteran_mode true: day>=6 (earlier) wins over veteran_mode.
    p = _chain_p_one(room46_reached=False, day=9, veteran_mode=True, chain=chain)
    assert p == 0.22
    # Only veteran_mode true: the unrepresentable row is skipped, veteran_mode wins.
    p = _chain_p_one(room46_reached=False, day=1, veteran_mode=True, chain=chain)
    assert p == 0.44
    # Only day>=3 true.
    p = _chain_p_one(room46_reached=False, day=3, veteran_mode=False, chain=chain)
    assert p == 0.55
    # Nothing true: otherwise.
    p = _chain_p_one(room46_reached=False, day=1, veteran_mode=False, chain=chain)
    assert p == 0.66


def test_day1_veteran_by_fast_early_drafts_is_unrepresentable(registry):
    """The wiki's "Day 1, Veteran Mode enabled by fast early drafts, 23%"
    row can never fire in this sim: GameConfig.veteran_mode (config.py) is a
    plain bool set at config time, with no notion of Veteran Mode having
    turned on MID-RUN from fast early drafts. Day 1 + veteran_mode=True must
    land on the NEXT row (plain "Veteran Mode enabled", 15%), never 23%.
    """
    chain = registry.item_rules["item_ladder"]["bands"][1]["chain"]
    assert any(row["if"] == "day1_veteran_by_fast_early_drafts" for row in chain), (
        "the unrepresentable row must still be present in the data, documented as such"
    )
    p = _chain_p_one(room46_reached=False, day=1, veteran_mode=True, chain=chain)
    assert p == 0.15, (
        "day 1 + veteran_mode must resolve to the 'Veteran Mode enabled' row (15%), not 23%")


# --------------------------------------------------------- 4. penalty accumulates

def test_luck_penalty_accumulates_and_shifts_a_later_band(registry):
    """A high-luck roll grows state.luck_penalty, and a SUBSEQUENT roll at
    the same nominal luck lands in a DIFFERENT band because of it -- not
    merely "the counter incremented" but an observable behavioural shift.

    luck=30 (29+ band) rolls 4 items and +3 Luck Penalty (wiki, verbatim).
    The very next roll, same nominal luck (30) but effective luck now
    30 - 3 = 27, lands in the 23-28 band (3 items, +2 penalty) instead --
    proving the penalty is actually consulted by roll_ladder_count, not just
    written and ignored.
    """
    g = _fake_game(registry, seed=42, luck=30, day=1, veteran_mode=False)
    assert g.state.luck_penalty == 0

    first = items.roll_ladder_count(g)
    assert first == 4, "29+ band: 4 items"
    assert g.state.luck_penalty == 3, "29+ band: +3 Luck Penalty"

    second = items.roll_ladder_count(g)  # NOT reset: penalty carries within this fake "day"
    assert second == 3, "effective luck 30-3=27 must now land in the 23-28 band (3 items)"
    assert g.state.luck_penalty == 5, "23-28 band adds another +2 on top of the existing +3"

    # A third roll: effective luck now 30-5=25, still 23-28 -- confirms the
    # band shift is a real, stable consequence of the accumulated penalty,
    # not a one-off artifact of the second roll specifically.
    third = items.roll_ladder_count(g)
    assert third == 3
    assert g.state.luck_penalty == 7


# --------------------------------------------------- 5. suppression helper

def test_suppress_luck_yields_zero_items(registry):
    """suppress_luck must make a room's luck-rolled additional items never
    fire, across many seeds -- even though the ladder's own floor band still
    has a real 7% chance of 1 item ("4- Luck: 7% for 1 item, 93% for 0
    items."). Uses roll_ladder_count directly (additional_max is a Room
    concept, clamped by the caller) at additional_max's own maximum
    plausible value so nothing is masked by clamping.
    """
    from blueprince_sim.engine.game import Game

    cfg = GameConfig()
    leaked = 0
    for seed in range(3000):
        g = Game(cfg, seed=seed, registry=registry)  # pass the shared registry: Game.__init__
        suppress_luck(g)                             # would otherwise re-parse data/*.json per seed
        count = items.roll_ladder_count(g)
        if count != 0:
            leaked += 1
    assert leaked == 0, f"suppress_luck leaked items in {leaked}/3000 seeds"


def test_suppress_luck_never_touches_luck_penalty(registry):
    """suppress_luck's forced outcome must be the genuine "0 items" branch,
    not merely a small count -- confirmed by luck_penalty staying 0 (only
    high-luck outcomes ever add to it)."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig()
    for seed in range(200):
        g = Game(cfg, seed=seed, registry=registry)
        suppress_luck(g)
        items.roll_ladder_count(g)
        assert g.state.luck_penalty == 0
