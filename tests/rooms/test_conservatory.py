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
5. ``test_reroll_move_stays_consistent_with_set_dynamic_rarity``: a card the
   reroll moves to a new rarity bucket is where a later ``set_dynamic_rarity``
   call (e.g. a same-day Gear Wrench pick) can find it.
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import set_dynamic_rarity
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


def test_reroll_move_stays_consistent_with_set_dynamic_rarity():
    """A room whose card the Conservatory reroll moves to a new rarity bucket
    must be findable there by a LATER set_dynamic_rarity call on that same
    room (e.g. a same-day Gear Wrench pick) -- not silently missed because
    the reroll left state.dynamic_rarity unset while the card itself sits
    somewhere other than the room's natal bucket. Before this was fixed,
    set_dynamic_rarity trusted state.dynamic_rarity (defaulting to the room's
    static rarity_idx) to find the card's CURRENT deck, so a reroll-moved
    card was searched for in the wrong deck, found zero copies, and the
    requested move was silently dropped -- corrupting decks.py's own
    solitaire invariant (a room's live cards must sit in exactly the bucket
    its bookkeeping claims) without raising anything.
    """
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    game.reset(0)
    conservatory = game.registry.by_id["conservatory"]

    before = [list(d.order) for d in game.state.decks]
    game._place_room(conservatory, CONSERVATORY_CELL, S)
    after = [list(d.order) for d in game.state.decks]

    # Locate a card the reroll actually relocated to a different rarity
    # bucket (test_conservatory_moves_deck_cards already establishes seed 0
    # is one of the >= 8/10 seeds where this happens).
    moved = None
    for gem_bit in (0, 1):
        for r_old in range(4):
            left = set(before[r_old * 2 + gem_bit]) - set(after[r_old * 2 + gem_bit])
            for room_idx in left:
                for r_new in range(4):
                    if r_new != r_old and room_idx in after[r_new * 2 + gem_bit]:
                        moved = (room_idx, gem_bit, r_old, r_new)
    assert moved is not None, "seed 0 must move at least one card for this regression to run"
    room_idx, gem_bit, r_old, r_new = moved
    room = game.registry.rooms[room_idx]
    is_gem = bool(gem_bit)

    # A third bucket, distinct from both the natal rarity and the reroll's
    # destination, so a false pass via set_dynamic_rarity's own no-op
    # idempotence (target == current) is impossible.
    target = next(r for r in range(4) if r not in (r_old, r_new))
    set_dynamic_rarity(game.state, game.registry, room.id, target, game.rng)

    assert game.state.deck(target, is_gem).order.count(room.idx) == 1, (
        f"{room.id}: set_dynamic_rarity did not place the card in the requested "
        f"bucket {target} -- it looked in the wrong (natal) bucket instead of "
        f"where the Conservatory reroll actually left it"
    )
    assert game.state.deck(r_new, is_gem).order.count(room.idx) == 0, (
        f"{room.id}: card is still present in its post-reroll bucket {r_new} "
        f"after being moved -- it now has copies in two buckets at once"
    )


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


def test_conservatory_is_category_green():
    """The Conservatory's own ``category`` is "green" (a plain data fix: the
    wiki's infobox and the Green Rooms page both list it), so is_category
    matches it on "green" without needing any extra_categories."""
    game = Game(GameConfig(), seed=0)
    conservatory = game.registry.by_id["conservatory"]
    assert conservatory.category == "green"
    assert conservatory.is_category("green")
    assert conservatory.categories == frozenset({"green"})


def test_conservatory_counts_as_green_for_indoor_nursery_bonus():
    """Indoor Nursery's "+2 gems for each GREEN ROOM you draft" (not counting
    its own draft) fires when the Conservatory is drafted, now that green
    membership is honoured wherever it matters, not just where convenient.
    """
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    indoor_nursery = game.registry.by_id["indoor_nursery__ix103"]
    conservatory = game.registry.by_id["conservatory"]
    game._place_room(indoor_nursery, 1, indoor_nursery.door_mask)
    before = game.state.gems
    game._place_room(conservatory, CONSERVATORY_CELL, S)
    assert game.state.gems == before + 2, (
        "drafting the Conservatory should grant Indoor Nursery's per-green-room bonus"
    )
