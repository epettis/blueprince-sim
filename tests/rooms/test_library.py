"""Verification that drafting through the Library replaces the rarity table.

Every rate here is a table this module INJECTS, then checks the roll reproduces.
Deriving the expectation from ``registry.weight_row`` instead would be a change
detector: it reads the same data the code under test reads, so it agrees with
any table, including a wrong one. The tables below are deliberately lopsided and
mutually exclusive so a roll drawn from the wrong one is impossible to miss.

One test does assert the SHIPPED numbers (Commonplace 0%, Standard 0.01%,
Unusual 49.99%, Rare 50% -- datamined, wiki.gg/Library), written as literals
rather than read back from weights.json, so editing that table has to be a
deliberate act that updates the documented spec too. Standard's 0.01% arm needs
an impractical sample size to pin and is only bounded, not measured.
"""

from __future__ import annotations

import copy
from dataclasses import replace

from scipy import stats

from blueprince_sim.engine.decks import build_decks, rarity_deck_ok, roll_rarity
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

N_DRAWS = 20_000
COMMONPLACE, STANDARD, UNUSUAL, RARE = 0, 1, 2, 3

# Rank/slot the injected base row is written to, and which the tests roll at.
RANK, SLOT, SLOT_CLASS = 5, 1, "slot23"


def _configured(registry, *, library=None, base=None, solarium=None):
    """A registry copy whose rarity tables are exactly what the test specifies.

    ``library`` sets the Library override row, ``base`` the ordinary
    stage/slot/rank row, ``solarium`` the Solarium slot23 row -- each a 4-tuple
    of (Commonplace, Standard, Unusual, Rare) percentages. Anything omitted is
    left as shipped.
    """
    w = copy.deepcopy(registry.weights)
    if library is not None:
        w["library_override"]["weights"] = list(library)
    if base is not None:
        w["tables"]["late"][SLOT_CLASS][str(RANK)] = list(base)
    if solarium is not None:
        w["solarium_slot23"][str(RANK)] = list(solarium)
    return replace(registry, weights=w)


def _fresh_state(registry, cfg, seed=0):
    """A state with freshly built, unconsumed decks.

    Every rarity's deck is large enough to satisfy rarity_deck_ok, so the
    deck-size gating cannot zero a weight and the roll itself is isolated.
    """
    rng = Rng(seed)
    st = GameState()
    st.decks = build_decks(registry, cfg, rng)
    return st, rng


def _roll_many(st, registry, cfg, rng, from_library, n=N_DRAWS, slot=SLOT, rank=RANK):
    counts = [0, 0, 0, 0]
    results = []
    for _ in range(n):
        r = roll_rarity(st, registry, cfg, rng, slot, rank, from_library)
        results.append(r)
        if r is not None:
            counts[r] += 1
    return counts, results


def _assert_matches(counts, expected_pcts, label):
    """Chi-square the observed counts against an explicit percentage table.

    Expectations are renormalised over the non-zero buckets rather than divided
    by 100, because chisquare demands the observed and expected totals agree
    exactly and a compared subset need not sum to 100 (the shipped Library
    table's Unusual+Rare come to 99.99, with Standard's 0.01 left out).
    """
    total = sum(counts)
    for i, pct in enumerate(expected_pcts):
        if pct == 0:
            assert counts[i] == 0, f"{label}: rarity {i} has weight 0 but rolled {counts[i]}"
    pct_total = sum(pct for pct in expected_pcts if pct > 0)
    obs, exp = zip(*[(c, pct / pct_total * total)
                     for c, pct in zip(counts, expected_pcts) if pct > 0])
    _, p = stats.chisquare(list(obs), list(exp))
    assert p > 0.001, f"{label}: counts={counts} do not match {expected_pcts} (p={p})"


def test_library_draft_reproduces_the_configured_library_table(registry, cfg):
    """A Library draft draws from the injected Library table, at its exact rates.

    The 25/75 split is nothing like any shipped row, so matching it proves the
    roll is reading the Library table rather than coincidentally agreeing with
    the ordinary one.
    """
    reg = _configured(registry, library=(0.0, 0.0, 25.0, 75.0))
    st, rng = _fresh_state(reg, cfg)
    counts, _ = _roll_many(st, reg, cfg, rng, from_library=True)
    _assert_matches(counts, (0.0, 0.0, 25.0, 75.0), "library draft")


def test_non_library_draft_reproduces_the_configured_base_table(registry, cfg):
    """An ordinary draft draws from the injected base row, at its exact rates.

    The counterpart to the test above: it pins that the override applies ONLY
    when asked for, using a base row (10/20/30/40) that shares no value with the
    Library table used alongside it.
    """
    reg = _configured(registry, library=(0.0, 0.0, 25.0, 75.0), base=(10.0, 20.0, 30.0, 40.0))
    st, rng = _fresh_state(reg, cfg)
    counts, _ = _roll_many(st, reg, cfg, rng, from_library=False)
    _assert_matches(counts, (10.0, 20.0, 30.0, 40.0), "ordinary draft")


def test_the_two_tables_do_not_leak_into_each_other(registry, cfg):
    """With disjoint tables, each draft kind yields ONLY its own table's rarities.

    The sharpest discrimination available: the base row is Commonplace-only and
    the Library table cannot roll Commonplace at all, so a single misrouted roll
    shows up as an outright illegal rarity rather than a shifted rate.
    """
    reg = _configured(registry, library=(0.0, 0.0, 50.0, 50.0), base=(100.0, 0.0, 0.0, 0.0))
    st, rng = _fresh_state(reg, cfg)

    lib_counts, _ = _roll_many(st, reg, cfg, rng, from_library=True, n=3000)
    assert lib_counts[COMMONPLACE] == 0, "a Library draft rolled the base row's Commonplace"
    assert lib_counts[UNUSUAL] + lib_counts[RARE] == 3000

    base_counts, _ = _roll_many(st, reg, cfg, rng, from_library=False, n=3000)
    assert base_counts[COMMONPLACE] == 3000, "an ordinary draft rolled outside the base row"


def test_library_beats_the_solarium_override(registry, cfg):
    """With a Solarium placed, a slot23 Library draft still uses the Library table.

    This precedence is INFERRED, not sourced -- nothing states what the Library
    does in a house that also holds a Solarium (see Registry.weight_row). The
    test exists so the inference is pinned rather than incidental: if someone
    reorders the two checks, the Solarium's Commonplace-only row would leak in.
    """
    reg = _configured(registry, library=(0.0, 0.0, 50.0, 50.0), solarium=(100.0, 0.0, 0.0, 0.0))
    st, rng = _fresh_state(reg, cfg)
    st.solarium_placed = True

    counts, _ = _roll_many(st, reg, cfg, rng, from_library=True, n=3000)
    assert counts[COMMONPLACE] == 0, "the Solarium's row won over the Library's"
    assert counts[UNUSUAL] + counts[RARE] == 3000


def test_library_override_respects_deck_exhaustion(registry, cfg):
    """An exhausted Rare deck zeroes the Library table's Rare weight like any other.

    The override substitutes the weights but must still pass through the
    deck-size gating, so the Library can never deal from an empty deck -- a far
    worse failure than a slightly wrong distribution.
    """
    reg = _configured(registry, library=(0.0, 0.0, 50.0, 50.0))
    st, rng = _fresh_state(reg, cfg)
    st.deck(RARE, False).order = []
    st.deck(RARE, True).order = []
    assert not rarity_deck_ok(st, reg, cfg, RARE, free_only=False)

    _, results = _roll_many(st, reg, cfg, rng, from_library=True, n=2000)
    for r in results:
        assert r != RARE, "rolled Rare despite an exhausted Rare deck"
        if r is not None:
            assert rarity_deck_ok(st, reg, cfg, r, free_only=False)


def test_shipped_library_table_matches_the_datamined_spec(registry, cfg):
    """The table actually shipped rolls Commonplace never and Unusual/Rare ~50/50.

    Expectations are the documented datamined values written as literals, not
    read back from weights.json, so a silent edit to that file fails here
    instead of quietly redefining what the test checks. Standard's 0.01% is
    only bounded -- pinning it needs a sample size this suite cannot afford.
    """
    st, rng = _fresh_state(registry, cfg)
    counts, _ = _roll_many(st, registry, cfg, rng, from_library=True)

    assert counts[COMMONPLACE] == 0, f"Commonplace rolled {counts[COMMONPLACE]} times"
    assert counts[STANDARD] < N_DRAWS * 0.01, (
        f"Standard rolled {counts[STANDARD]}/{N_DRAWS}, far above its 0.01% weight"
    )
    _assert_matches([0, 0, counts[UNUSUAL], counts[RARE]],
                    (0.0, 0.0, 49.99, 50.0), "shipped Library table")
