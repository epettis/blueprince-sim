"""Tests for the Treasure Trove's per-draft coin-pile accumulation.

Owner ruling: the Treasure Trove permanently
gains a 5-coin pile every time it is drafted, and each draft collects the whole
surface -- so the Nth draft this attempt pays ``5 * N``. The pile count caps at
32 (blueprince.wiki.gg/wiki/Treasure_Trove: "One pile appears per time the room
is drafted..., to a maximum of 32 piles (160 Gold Coin total)"), which bounds
what a SINGLE draft is worth, not what the room earns over the attempt: past the
cap every further draft keeps paying the full 160 rather than nothing.

The grant fires on draft/placement (Hook.ON_PLACE), reusing ``state.draft_counts``
-- the existing cumulative per-attempt draft counter that DayChain already
carries across days and clears on chain wrap -- rather than a bespoke counter.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import obs as O
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain


def _place_trove(g: Game, cell: int = 7) -> None:
    """Place the Treasure Trove at ``cell`` via the direct test helper.

    ``_place_room`` bypasses draft legality (as in the Hovel/Nursery tests in
    test_game.py) so the effect can be exercised without a full draft/choose
    sequence; it still runs the real placement bookkeeping (draft_counts
    increment) and fires the real ON_PLACE hook.
    """
    g._place_room(g.registry.by_id["treasure_trove"], cell, N | S)


def test_first_draft_grants_one_5_coin_pile(registry, cfg):
    """The first Treasure Trove draft this attempt grants exactly one 5-coin pile."""
    g = Game(cfg, seed=1)
    coins0 = g.state.coins
    _place_trove(g)
    assert g.state.coins == coins0 + 5


def test_each_draft_pays_five_times_the_running_count():
    """Draft N pays 5*N, so the room's payout grows every time it is drafted.

    This is the whole point of the mechanic and the thing that makes the Trove
    valuable: the piles are permanent and every draft collects all of them, so
    the 4th draft is worth four times the 1st, not the same as it.
    """
    g = Game(GameConfig(), seed=1)
    for expected in (5, 10, 15, 20):
        coins0 = g.state.coins
        _place_trove(g)
        assert g.state.coins - coins0 == expected


def test_coins_accumulate_across_days_within_an_attempt():
    """The draft count that sets the payout survives the day boundary, so day 2 pays more.

    Drafting on day 1 pays 5 and drafting again on day 2 pays 10, for an attempt
    total of 15 -- the accumulation is attempt-wide, not reset overnight.
    """
    chain = DayChain(GameConfig(), n_days=200)

    g1 = Game(chain.next_config(), seed=1)
    coins_before_day1 = g1.state.coins
    _place_trove(g1)
    assert g1.state.coins == coins_before_day1 + 5
    chain.advance(carryover(g1))

    cfg2 = chain.next_config()
    assert cfg2.draft_counts.get("treasure_trove", 0) == 1, \
        "the day-1 draft must be visible in day 2's carried-over draft_counts"

    g2 = Game(cfg2, seed=2)
    coins_before_day2 = g2.state.coins
    _place_trove(g2)
    assert g2.state.coins == coins_before_day2 + 10, \
        "the second draft this attempt is the second pile, so it pays 10, not 5"

    day1_gain = g1.state.coins - coins_before_day1
    day2_gain = g2.state.coins - coins_before_day2
    assert day1_gain + day2_gain == 15


def test_the_32nd_draft_pays_the_full_160():
    """The 32nd draft fills the last pile and pays the maximum single-draft 160 coins."""
    cfg = GameConfig(draft_counts={"treasure_trove": 31})
    g = Game(cfg, seed=3)
    coins0 = g.state.coins
    _place_trove(g)
    assert g.state.coins == coins0 + 160


def test_drafts_past_the_cap_keep_paying_160():
    """Past 32 piles the payout stops GROWING but does not stop: it stays at 160.

    The distinguishing case for the cap's meaning. An earlier reading had the
    cap end the payout entirely, which would make every draft after the 32nd
    worthless; the room instead plateaus at its maximum.
    """
    cfg = GameConfig(draft_counts={"treasure_trove": 32})
    g = Game(cfg, seed=3)
    for _ in range(3):
        coins0 = g.state.coins
        _place_trove(g)
        assert g.state.coins - coins0 == 160


def test_attempt_total_is_not_capped_at_160():
    """160 caps a single draft, not the attempt: 32 drafts come to 2640 coins.

    Pins the difference between "the room is worth 160 in total" and "the room
    is worth up to 160 each time", which is what the cap actually bounds.
    """
    g = Game(GameConfig(), seed=4)
    coins0 = g.state.coins
    for _ in range(32):
        _place_trove(g)
    assert g.state.draft_counts["treasure_trove"] == 32
    assert g.state.coins - coins0 == 2640, "5 * (1+2+...+32) = 5 * 528"


def test_draft_count_resets_on_chain_wrap():
    """After the attempt wraps, drafting the Trove again pays the fresh first-draft rate.

    Same shape as the generic draft_counts wrap-reset in test_upgrade_disks.py,
    but pinned against the Treasure Trove's actual coin payout so a future
    refactor of the counter can't silently break the economic reset.
    """
    chain = DayChain(GameConfig(), n_days=1)

    g1 = Game(chain.next_config(), seed=5)
    _place_trove(g1)
    chain.advance(carryover(g1))  # day 1 of a 1-day chain wraps immediately

    cfg2 = chain.next_config()
    assert cfg2.draft_counts == {}, "draft_counts must be cleared by the wrap"

    g2 = Game(cfg2, seed=6)
    coins0 = g2.state.coins
    _place_trove(g2)
    assert g2.state.coins == coins0 + 5, \
        "a fresh attempt pays the first-draft pile again, not a continuation of the old count"


def test_same_seed_same_payout():
    """Same seed and same starting draft count produce an identical coin payout (determinism)."""
    cfg = GameConfig(draft_counts={"treasure_trove": 10})
    g_a = Game(cfg, seed=42)
    g_b = Game(cfg, seed=42)
    _place_trove(g_a)
    _place_trove(g_b)
    assert g_a.state.coins == g_b.state.coins


def test_treasure_trove_piles_observable_and_clamped_at_32():
    """The observation surfaces the cumulative draft count, clamped to the 32-pile cap.

    Clamping is right here even though the attempt total is unbounded: the pile
    count is what sets the payout, and it genuinely stops at 32, so the agent
    loses nothing by not seeing drafts beyond it.
    """
    plain = BluePrinceEnv(cfg=GameConfig())
    plain.reset(seed=1)
    assert int(O.encode(plain.game)["treasure_trove_piles"][0]) == 0, \
        "nothing drafted yet, so the observed pile count must be zero"

    over_cap = BluePrinceEnv(cfg=GameConfig(draft_counts={"treasure_trove": 50}))
    over_cap.reset(seed=1)
    assert int(O.encode(over_cap.game)["treasure_trove_piles"][0]) == 32, \
        "the observation must clamp at the 32-pile cap, not report the raw draft count"
