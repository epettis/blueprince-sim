"""Statistical verification of the Free/Gem Draw axis against the datamined
table (weights.json's ``free_gem_draws``), plus the invariants around it.

Companion to test_draft_stats.py, which only guards the RARITY axis: its
chi-square tests recompute their expected weights through the same
``rarity_deck_ok`` the engine uses, so they self-adjust and would never catch
a Free/Gem regression -- an entire decision step (this one) shipped
unmodelled for a long time without anything here going red. Every expectation
below is read straight from ``registry.weights["free_gem_draws"]`` (a plain
dict lookup, not a call into draft.py), so there is no engine-side logic a
regression in ``_resolve_free_gem`` could drag the expectation along with.
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _resolve_free_gem
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

N_TRIALS = 20_000
# Bonferroni over the 5 (rank, gem) cells parametrized below.
ALPHA = 0.001 / 5


def _ctx(day: int, gems: int, drafts_today: int, registry, cfg) -> DraftContext:
    """A bare DraftContext/GameState combo with just the fields _resolve_free_gem reads."""
    state = GameState()
    state.day = day
    state.gems = gems
    state.drafts_today = drafts_today
    return DraftContext(state, registry, cfg, Rng(0), set(), None)


# ------------------------------------------------------- Slot 2 (engine slot 1)

@pytest.mark.parametrize("rank,gems,bucket", [
    (1, 2, 1),   # 1-3 gems row  -> 2.0%
    (4, 0, 0),   # 0 gems row    -> 6.0%
    (6, 2, 1),   # 1-3 gems row  -> 16.21%
    (8, 5, 2),   # 4+ gems row   -> 59.26%
    (9, 0, 0),   # 0 gems row    -> 32.32%
])
def test_slot2_gem_rate_matches_table(registry, cfg, rank, gems, bucket):
    """Over N_TRIALS rounds at a fixed rank/gem bucket (day 20, so the day-1-3
    early-Free carve-out never intervenes), the observed rate of engine slot 1
    ("Slot 2" on the wiki) coming back a Gem Draw matches
    weights.json's free_gem_draws.slot2_gem_chance table within a proper
    statistical tolerance (binomial test, Bonferroni-corrected). A regression
    in the table lookup or the roll itself moves this rate; a self-adjusting
    guard that re-derived the expectation from the same code could not."""
    ctx = _ctx(day=20, gems=gems, drafts_today=1, registry=registry, cfg=cfg)
    expected_p = registry.weights["free_gem_draws"]["slot2_gem_chance"][str(rank)][bucket] / 100.0
    assert expected_p > 0, "setup: pick a nonzero cell for the binomial test"

    hits = sum(_resolve_free_gem(ctx, rank, round_num=1)[0] for _ in range(N_TRIALS))

    result = stats.binomtest(hits, N_TRIALS, expected_p)
    assert result.pvalue > ALPHA, (
        f"rank={rank} gems={gems}: observed {hits}/{N_TRIALS} "
        f"({hits / N_TRIALS:.4f}) vs expected {expected_p:.4f}, p={result.pvalue:.2e}"
    )


@pytest.mark.parametrize("rank,gems", [(1, 0), (2, 0), (3, 0)])
def test_slot2_gem_chance_zero_cells_never_fire(registry, cfg, rank, gems):
    """A table cell that is exactly 0% (ranks 1-3 at 0 gems) is a deterministic
    "never", not a very-low probability -- rng.chance(label, 0.0) can never
    return True, so this asserts an exact zero rather than a statistical
    bound (the right check for a value that is 0% BY THE TABLE, not merely
    rare)."""
    ctx = _ctx(day=20, gems=gems, drafts_today=1, registry=registry, cfg=cfg)
    assert registry.weights["free_gem_draws"]["slot2_gem_chance"][str(rank)][0] == 0.0

    hits = sum(_resolve_free_gem(ctx, rank, round_num=1)[0] for _ in range(2000))

    assert hits == 0, f"rank={rank}: a 0%-table cell fired {hits}/2000 times"


# ------------------------------------------------------- Slot 3 (engine slot 2)

def test_slot3_gem_rate_matches_rank_table_after_the_fifth_draft(registry, cfg):
    """Beyond the fifth draft of the day, Slot 3's Gem Draw rate -- CONDITIONAL
    on Slot 2 having stayed Free, which is how the wiki's cascade actually
    reaches Slot 3's own roll ("Otherwise, Slot 2 is a Free Draw, and there is
    an additional chance...") -- matches free_gem_draws.slot3_rank_chance for
    a rank whose row is neither the "third round" nor the low-gem carve-out.
    Rank 7 also has a nonzero Slot-2 chance (15.4% at 0 gems), so this test
    filters to the slot-2-stayed-free trials rather than forcing that
    branch, which the single shared ``rank`` argument cannot do independently
    of Slot 3's own rank-keyed row."""
    ctx = _ctx(day=20, gems=0, drafts_today=6, registry=registry, cfg=cfg)
    rank = 7
    expected_p = registry.weights["free_gem_draws"]["slot3_rank_chance"][str(rank)] / 100.0

    results = [_resolve_free_gem(ctx, rank, round_num=1) for _ in range(N_TRIALS)]
    conditional = [slot2 for slot1, slot2 in results if not slot1]
    assert len(conditional) > N_TRIALS // 4, "setup: too few slot-2-stayed-free trials"
    hits = sum(conditional)

    result = stats.binomtest(hits, len(conditional), expected_p)
    assert result.pvalue > ALPHA, (
        f"observed {hits}/{len(conditional)} ({hits / len(conditional):.4f}) vs "
        f"expected {expected_p:.4f}, p={result.pvalue:.2e}"
    )


def test_slot3_gem_rate_matches_low_gem_chance_in_first_two_drafts(registry, cfg):
    """In the first two drafts of the day, holding 2+ gems, Slot 3's chance --
    CONDITIONAL on Slot 2 having stayed Free (see the rank-table test above
    for why this conditions rather than forces) -- is the flat
    free_gem_draws.slot3_low_gem_chance (20%), not the rank-keyed table,
    which only applies later."""
    ctx = _ctx(day=20, gems=5, drafts_today=2, registry=registry, cfg=cfg)
    expected_p = registry.weights["free_gem_draws"]["slot3_low_gem_chance"] / 100.0

    results = [_resolve_free_gem(ctx, rank=1, round_num=1) for _ in range(N_TRIALS)]
    conditional = [slot2 for slot1, slot2 in results if not slot1]
    assert len(conditional) > N_TRIALS // 2, "setup: too few slot-2-stayed-free trials"
    hits = sum(conditional)

    result = stats.binomtest(hits, len(conditional), expected_p)
    assert result.pvalue > ALPHA, (
        f"observed {hits}/{len(conditional)} ({hits / len(conditional):.4f}) vs "
        f"expected {expected_p:.4f}, p={result.pvalue:.2e}"
    )


def test_slot3_always_gem_from_the_third_round_of_a_draft(registry, cfg):
    """"If this is the third round or later this draft, Slot 3 is always a
    Gem Draw" -- a deterministic override, so this asserts every one of many
    trials hits rather than a statistical rate (round_num=3, an otherwise
    0%-chance rank/gem/draft combination that would never produce a Gem Draw
    on its own, isolating the round-number override from every other path)."""
    ctx = _ctx(day=20, gems=0, drafts_today=1, registry=registry, cfg=cfg)

    results = [_resolve_free_gem(ctx, rank=1, round_num=3) for _ in range(500)]

    assert all(r[1] for r in results), "round >= 3 must force Slot 3 to Gem every time"


def test_slot3_stays_free_with_low_gems_in_the_first_two_drafts(registry, cfg):
    """In the first two drafts of the day, holding 0-1 gems, Slot 3 is
    deterministically Free once Slot 2 stays Free -- distinct from (and
    stricter than) the 20% chance the same 0-1-gem bucket gets from draft 3
    onward (test_slot3_gem_rate_matches_low_gem_chance_in_first_two_drafts's
    2+ gems case is the OTHER half of this same wiki bullet)."""
    ctx = _ctx(day=20, gems=0, drafts_today=1, registry=registry, cfg=cfg)

    results = [_resolve_free_gem(ctx, rank=1, round_num=1) for _ in range(2000)]

    assert not any(r[0] or r[1] for r in results), "both slots must stay Free every trial"


# ------------------------------------------------------------- Early carve-out

def test_early_carve_out_forces_every_slot_free_on_day_one(registry, cfg):
    """On Day 1, within Veteran Mode's first-2-drafts window, both engine
    slots 1 and 2 are Free Draws unconditionally -- even at a rank/gem
    combination (rank 9, 5 gems) whose ordinary table cells would otherwise
    make a Gem Draw likely, proving the carve-out really does short-circuit
    the table rather than merely lowering the odds."""
    assert cfg.veteran_mode, "setup: this test exercises the Veteran Mode limit (2 drafts)"
    ctx = _ctx(day=1, gems=5, drafts_today=2, registry=registry, cfg=cfg)

    results = [_resolve_free_gem(ctx, rank=9, round_num=1) for _ in range(500)]

    assert not any(r[0] or r[1] for r in results), "early carve-out must force both slots Free"


def test_early_carve_out_expires_after_veteran_moves_first_two_drafts(registry, cfg):
    """The carve-out only covers the first 2 drafts under Veteran Mode -- the
    3rd draft of the same early day goes back to the ordinary table, so a
    rank/gem cell with a high published chance (rank 9, 4+ gems -> 59.26%)
    becomes reachable again."""
    assert cfg.veteran_mode
    ctx = _ctx(day=1, gems=5, drafts_today=3, registry=registry, cfg=cfg)
    expected_p = registry.weights["free_gem_draws"]["slot2_gem_chance"]["9"][2] / 100.0

    hits = sum(_resolve_free_gem(ctx, rank=9, round_num=1)[0] for _ in range(N_TRIALS))

    result = stats.binomtest(hits, N_TRIALS, expected_p)
    assert result.pvalue > 0.001, (
        f"observed {hits}/{N_TRIALS} vs expected {expected_p:.4f}, p={result.pvalue:.2e}"
    )


# --------------------------------------------------------------- Slot 0 invariant

def test_slot0_is_never_a_gem_room():
    """Engine slot 0 ("Slot 1" on the wiki) is a deterministic always-Free
    invariant ("Slot 1 always makes a Free Draw"), not a probabilistic one --
    over 200 seeds' worth of real dealt hands (open_door, default config),
    slot 0 never once holds a room with a nonzero gem cost. An exact zero
    count is the right check here (unlike the Slot-2/3 tests above) because
    the property under test is a hard rule, not a rate."""
    game = Game(GameConfig(), seed=0)
    gem_slot0_count = 0
    total_slot0 = 0
    for seed in range(200):
        game.reset(seed)
        game.state.steps = 999
        pending = game.open_door(2, N)
        slot0 = [o for o in pending.options if o.slot == 0]
        if slot0:
            total_slot0 += 1
            room = game.registry.rooms[slot0[0].room_idx]
            if not room.is_free:
                gem_slot0_count += 1
    assert total_slot0 > 150, "setup: most seeds should deal a slot-0 option"
    assert gem_slot0_count == 0, f"slot 0 held a gem room {gem_slot0_count}/{total_slot0} times"
