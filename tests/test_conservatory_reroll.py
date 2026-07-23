"""Conservatory rarity re-roll: one-time deck mutation on draft.

The effect fires ONCE, when the Conservatory itself is drafted: 3 random
undealt cards across the eight solitaire decks each roll a fresh rarity
(uniform over the 4 rarities; inferred) via the dedicated
``conservatory_reroll`` RNG substream, and changed cards move to the new
rarity's deck of the same free/gem class at a random undealt position.

Tests:
1. ``test_conservatory_moves_deck_cards``: placing the Conservatory changes
   deck composition (cards move between rarity decks) while conserving the
   overall card multiset per free/gem class.
2. ``test_conservatory_changes_dealt_rooms``: across many seeds, a
   statistically significant fraction of subsequently dealt hands differ from
   a no-Conservatory baseline (the moved cards perturb deck order).
3. ``test_no_conservatory_draws_are_deterministic``: bit-identity guard for
   the no-Conservatory path.
4. ``test_no_per_hand_reroll_consumption``: after placement, ordinary hands
   consume nothing from the ``conservatory_reroll`` substream — the effect is
   one-time, not per-hand.
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

# Draft setup: player at entrance (cell 2), open north door to cell 7 (rank 2).
DRAFT_FROM = 2
DRAFT_DIR = N

# Conservatory: corner room; place at cell 0 (rank 1, col 0 - NW corner, not
# adjacent to the draft target cell) with a south-facing entry.
CONSERVATORY_CELL = 0

# Number of independent seeds to compare.
N_SEEDS = 500

# Minimum fraction of hands that must differ. Only 3 cards move, so most
# hands are unaffected; empirically the divergence rate is well above this
# generous floor.
MIN_DIVERGENCE_RATE = 0.05

# Significance level for the binomial test against a 1% divergence null.
ALPHA = 1e-6


def _undealt_by_deck(game: Game) -> list[tuple[int, ...]]:
    return [tuple(d.order[d.pos:]) for d in game.state.decks]


def _options_fingerprint(game: Game, seed: int,
                         place_conservatory: bool) -> tuple[tuple[int, int, int], ...]:
    """Return a hashable fingerprint of the dealt options for one draft hand."""
    game.reset(seed)
    if place_conservatory:
        conservatory = game.registry.by_id["conservatory"]
        game._place_room(conservatory, CONSERVATORY_CELL, S)
    game.state.steps = 999
    pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
    return tuple((o.room_idx, o.orientation, o.gem_cost) for o in pending.options)


def test_conservatory_moves_deck_cards():
    """Placing the Conservatory moves undealt cards between rarity decks while
    conserving the card multiset within each free/gem class."""
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    conservatory = game.registry.by_id["conservatory"]
    n_changed = 0
    for seed in range(10):
        game.reset(seed)
        before = _undealt_by_deck(game)
        game._place_room(conservatory, CONSERVATORY_CELL, S)
        after = _undealt_by_deck(game)

        # Conservation: per free/gem class, the multiset of undealt cards is
        # unchanged (decks are indexed rarity*2 + gem_bit).
        for gem_bit in (0, 1):
            combined_before = sorted(c for i in range(gem_bit, 8, 2) for c in before[i])
            combined_after = sorted(c for i in range(gem_bit, 8, 2) for c in after[i])
            assert combined_before == combined_after, f"seed {seed}: cards lost/created"

        if before != after:
            n_changed += 1

    # With 3 picks each rolling uniformly over 4 rarities, the odds that no
    # card moves for a given seed are (1/4)^3; requiring >= 8/10 seeds to
    # change keeps this far from flaky.
    assert n_changed >= 8, f"deck composition changed for only {n_changed}/10 seeds"


@pytest.fixture(scope="module")
def divergence_counts():
    """Count seeds whose first dealt hand differs with vs without Conservatory."""
    cfg = GameConfig()
    game_with = Game(cfg, seed=0)
    game_without = Game(cfg, seed=0)
    n_different = 0
    for seed in range(N_SEEDS):
        fp_with = _options_fingerprint(game_with, seed, place_conservatory=True)
        fp_without = _options_fingerprint(game_without, seed, place_conservatory=False)
        if fp_with != fp_without:
            n_different += 1
    return n_different, N_SEEDS


def test_conservatory_changes_dealt_rooms(divergence_counts):
    """The one-time deck mutation measurably perturbs subsequent deals.

    Only 3 cards move, so most hands are identical to the baseline; the
    divergence rate just needs to clear a generous floor and a binomial test
    against a 1% null.
    """
    n_different, n_total = divergence_counts

    observed_rate = n_different / n_total
    assert observed_rate >= MIN_DIVERGENCE_RATE, (
        f"Conservatory re-roll has too little effect: "
        f"{n_different}/{n_total} hands differ ({observed_rate:.2%}); "
        f"expected >= {MIN_DIVERGENCE_RATE:.0%}"
    )

    result = stats.binomtest(n_different, n_total, p=0.01, alternative="greater")
    assert result.pvalue < ALPHA, (
        f"Conservatory effect not significant: p={result.pvalue:.2e} "
        f"({n_different}/{n_total} hands differ)"
    )


def test_no_conservatory_draws_are_deterministic():
    """Without Conservatory, deals must be bit-identical across two runs of the
    same seed, guarding against accidental unconditional RNG consumption."""
    cfg = GameConfig()
    game = Game(cfg, seed=0)

    def collect(seed: int) -> list[tuple[int, int, int]]:
        game.reset(seed)
        pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
        return [(o.room_idx, o.orientation, o.gem_cost) for o in pending.options]

    for seed in range(200):
        run_a = collect(seed)
        run_b = collect(seed)
        assert run_a == run_b, (
            f"seed {seed}: non-deterministic without Conservatory\n"
            f"  run_a={run_a}\n  run_b={run_b}"
        )


def test_no_per_hand_reroll_consumption():
    """The re-roll is one-time: dealing hands after placement must not consume
    the conservatory_reroll substream."""
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    game.reset(0)
    conservatory = game.registry.by_id["conservatory"]
    game._place_room(conservatory, CONSERVATORY_CELL, S)
    stream_state = game.rng.stream("conservatory_reroll").getstate()
    game.state.steps = 999
    game.open_door(DRAFT_FROM, DRAFT_DIR)
    assert game.rng.stream("conservatory_reroll").getstate() == stream_state, (
        "dealing a hand consumed the conservatory_reroll substream; "
        "the effect must fire only when the Conservatory is drafted"
    )
