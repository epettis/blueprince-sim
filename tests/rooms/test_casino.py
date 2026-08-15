"""Casino: the slot machine and roulette table (data/casino.json,
engine/effects/rooms/casino.py).

Both games are ordinary Casino shop-buy entries (BUY_BASE, env/actions.py),
not a new Phase or GameState field -- see casino.py's module docstring.
This supersedes the room's old "grants 1 die as approximation" stand-in and
the Broken Lever's old "20 coins + 2 gems" invented golden-slot payout; see
tests/test_ignition.py for the broken_lever item's generic consumption
rules, shared by any machine room.
"""

from __future__ import annotations

from collections import Counter

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.effects.rooms import casino as casino_room
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from luck_utils import suppress_luck


# --------------------------------------------------------------------- helpers

def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, rng, cfg: GameConfig | None = None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = rng
    g.cfg = cfg or GameConfig()
    return g


def _place_room(state, registry, room_id: str, cell: int) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


def _enter_casino(game: Game, cell: int = 7):
    casino = game.registry.by_id["casino"]
    game._place_room(casino, cell, casino.door_mask)
    game.state.pos = cell
    game.phase = Phase.NAVIGATE
    shops.on_enter_shop(game, casino)
    return casino


class _ScriptedRng:
    """Returns pre-programmed values for each label, in call order, so slot
    and roulette resolution can be pinned exactly without hunting a seed.
    Duck-types the three ``Rng`` methods casino.py actually calls."""

    def __init__(self, **queues):
        self._queues = {k: list(v) for k, v in queues.items()}

    def _next(self, label):
        q = self._queues[label]
        assert q, f"scripted queue for {label!r} ran out"
        return q.pop(0)

    def roll_weighted(self, label, weights):
        del weights
        return self._next(label)

    def chance(self, label, p):
        del p
        return self._next(label)

    def randint(self, label, lo, hi):
        del lo, hi
        return self._next(label)


def _rules():
    reg = Registry.load()
    return casino_room.load_casino_rules(reg.data_dir)


def _symbol_index(name: str) -> int:
    return _rules().slot.symbols.index(name)


# ------------------------------------------------------- slot payout scoring
# score_slot is a pure function of symbol counts -> the interaction rules
# data/casino.json's meta.notes transcribes from the wiki's raw wikitext.

def _counts(*symbols: str) -> Counter:
    return Counter(symbols)


def test_three_coins_pays_but_four_coins_pays_more_and_the_three_rule_is_excluded():
    """3 coins -> 3; 4 coins -> 5, not 3+5 -- the wiki's explicit "doesn't
    apply if there are 4 coins" exclusivity."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("coin", "coin", "coin", "dash"), payouts) == 3
    assert casino_room.score_slot(_counts("coin", "coin", "coin", "coin"), payouts) == 5


def test_three_coin_stacks_pays_but_four_coin_stacks_pays_more_and_excludes_three():
    """Same 3-vs-4 exclusivity, independently, for coin stacks (9 vs 15)."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(
        _counts("coin_stack", "coin_stack", "coin_stack", "dash"), payouts) == 9
    assert casino_room.score_slot(
        _counts("coin_stack", "coin_stack", "coin_stack", "coin_stack"), payouts) == 15


def test_clover_adds_to_an_existing_match_rather_than_replacing_it():
    """Clover's 10-per-clover is ADDED to any other match, not exclusive
    with it (unlike the coin/coin-stack 3-vs-4 rule): 3 coins (3) + 1
    clover (10) = 13."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("coin", "coin", "coin", "clover"), payouts) == 13


def test_clover_pays_per_clover_with_no_exclusivity_at_two():
    """Two clovers is simply 2x10 = 20, with nothing else to add -- clover
    has no 3-vs-4-style count-exclusivity of its own."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("clover", "clover", "dash", "dash"), payouts) == 20


def test_double_applies_after_clover_and_multiplies_the_whole_base():
    """Clover (10) doubled once = 20; 3 coins (3) doubled once = 6 -- Double
    has no coin value of its own, it only multiplies whatever base the
    other symbols already produced."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("clover", "double", "dash", "dash"), payouts) == 20
    assert casino_room.score_slot(_counts("coin", "coin", "coin", "double"), payouts) == 6


def test_three_doubles_gives_exactly_8x():
    """The wiki's own worked example: three Doubles gives 8x (2**3), not 6x
    or some other linear stacking."""
    payouts = _rules().slot.payouts
    # 1 clover (10) + 3 doubles: base=10, multiplier=2**3=8 -> 80.
    counts = Counter({"clover": 1, "double": 3})
    assert casino_room.score_slot(counts, payouts) == 80


def test_snake_zeroes_the_payout_unless_a_net_is_present():
    """Snake sets the payout to 0, applied AFTER clover -- a clover+snake
    spin pays 0, not 10. A net disables that zeroing entirely."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("clover", "snake", "dash", "dash"), payouts) == 0
    # With a net present, snake's zeroing is disabled and clover still counts,
    # plus 3 per snake from the net.
    got = casino_room.score_slot(_counts("clover", "snake", "net", "dash"), payouts)
    assert got == payouts["clover_each"] + payouts["net_per_snake"]  # 10 + 3 = 13


def test_net_pays_per_snake_and_does_not_stack_across_multiple_nets():
    """Net pays 3 per snake present; a second net does not double that
    payout -- the wiki's own disclosed (buggy, per its open question)
    non-stacking rule, modelled literally as stated."""
    payouts = _rules().slot.payouts
    one_net = casino_room.score_slot(_counts("net", "snake", "snake", "dash"), payouts)
    two_nets = casino_room.score_slot(_counts("net", "net", "snake", "snake"), payouts)
    assert one_net == payouts["net_per_snake"] * 2  # 2 snakes, 1 net -> 6
    assert two_nets == one_net  # a second net changes nothing


def test_four_crowns_pays_100_but_three_crowns_pays_nothing_on_their_own():
    """4 crowns -> 100; unlike coins/coin stacks, there is no lesser payout
    for 3 crowns -- the table only publishes the 4-of-a-kind row."""
    payouts = _rules().slot.payouts
    assert casino_room.score_slot(_counts("crown", "crown", "crown", "crown"), payouts) == 100
    assert casino_room.score_slot(_counts("crown", "crown", "crown", "dash"), payouts) == 0


def test_reel_weights_sum_to_100_and_match_the_datamined_table():
    """data/casino.json's reel weights transcribe the wiki's DataMinedBox
    verbatim: Dash 27, Coin 30, Coin Stack 10, Clover 1, Double 10,
    Snake 10, Net 4, Crown 8 -- summing to 100."""
    slot = _rules().slot
    weights = dict(zip(slot.symbols, slot.weights))
    assert weights == {
        "dash": 27, "coin": 30, "coin_stack": 10, "clover": 1,
        "double": 10, "snake": 10, "net": 4, "crown": 8,
    }
    assert sum(slot.weights) == 100


# --------------------------------------------------------- reel RNG: reachable set

def test_every_reel_symbol_is_reachable_over_a_sweep():
    """All 8 symbols appear at least once across many independent seeds --
    the reachable SET, never a bound on a random count (per instructions:
    no seed-hunting, no bar on a random quantity)."""
    slot = _rules().slot
    seen = set()
    for seed in range(300):
        rng = Rng(seed)
        seen.add(casino_room._roll_reel(rng, slot))
        if seen == set(slot.symbols):
            break
    assert seen == set(slot.symbols)


# --------------------------------------------------------------- reroll target

def test_pick_reroll_target_prefers_dash_then_an_unnetted_snake_then_stops():
    """The disclosed greedy heuristic: reroll a Dash first; with no Dash,
    reroll a Snake only if no Net is present; with neither, stop (None)."""
    assert casino_room._pick_reroll_target(["dash", "coin", "coin", "coin"]) == 0
    assert casino_room._pick_reroll_target(["snake", "coin", "coin", "coin"]) == 0
    assert casino_room._pick_reroll_target(["snake", "net", "coin", "coin"]) is None
    assert casino_room._pick_reroll_target(["coin", "coin", "coin", "coin"]) is None


# ------------------------------------------------------------ slot resolution

def test_quick_spin_never_spends_on_a_bonus_reroll():
    """max_bonus=0 (the "quick spin" entry) never enters the reroll loop,
    regardless of symbols -- pinned with an always-Dash scripted RNG so the
    heuristic would otherwise keep rerolling forever."""
    st, reg = _state_with_registry()
    dash_idx = _symbol_index("dash")
    rng = _ScriptedRng(casino_slot_reel=[dash_idx] * 4)
    game = _fake_game(st, reg, rng)
    st.coins = 100
    before = st.coins
    casino_room.resolve_slot_purchase(game, {"max_bonus": 0})
    # 4 dashes pay 0, and no reroll was ever spent -- coins unchanged.
    assert st.coins == before


def test_spin_and_reroll_spends_up_to_the_normal_cap_of_3():
    """An always-Dash scripted RNG forces the greedy heuristic to keep
    rerolling every reel it draws -- with the normal (non-golden) cap this
    must stop at exactly 3 bonus rerolls, spending exactly 3 coins, since
    the 4th reel is still visible as a Dash target but the budget is gone."""
    st, reg = _state_with_registry()
    dash_idx = _symbol_index("dash")
    rng = _ScriptedRng(casino_slot_reel=[dash_idx] * 8)  # 4 initial + up to 3 rerolls
    game = _fake_game(st, reg, rng)
    st.coins = 100
    before = st.coins
    casino_room.resolve_slot_purchase(game, {"max_bonus": None})
    # 3 rerolls at 1 coin each spent chasing a Dash that never stops being a
    # Dash; final result is still 4 dashes, which pays 0.
    assert st.coins == before - 3


def test_golden_slot_raises_the_cap_to_5():
    """Once the Casino's lever has been fixed today (state.special.
    machines_used contains "casino"), the same always-Dash scenario spends
    5 bonus rerolls instead of 3."""
    st, reg = _state_with_registry()
    st.special.machines_used.append("casino")
    dash_idx = _symbol_index("dash")
    rng = _ScriptedRng(casino_slot_reel=[dash_idx] * 20)
    game = _fake_game(st, reg, rng)
    st.coins = 100
    before = st.coins
    casino_room.resolve_slot_purchase(game, {"max_bonus": None})
    assert st.coins == before - 5


def test_reroll_stops_early_when_coins_run_out():
    """A budget of 3 is available but only 2 coins are held -- the reroll
    loop must stop the moment it can no longer afford the next 1-coin
    reroll, not overdraw."""
    st, reg = _state_with_registry()
    dash_idx = _symbol_index("dash")
    rng = _ScriptedRng(casino_slot_reel=[dash_idx] * 8)
    game = _fake_game(st, reg, rng)
    st.coins = 2
    casino_room.resolve_slot_purchase(game, {"max_bonus": None})
    assert st.coins == 0


def test_payout_is_granted_and_logged():
    """A scripted 4-crowns result grants exactly 100 coins and logs the pickup."""
    st, reg = _state_with_registry()
    crown_idx = _symbol_index("crown")
    rng = _ScriptedRng(casino_slot_reel=[crown_idx] * 4)
    game = _fake_game(st, reg, rng)
    st.coins = 0
    casino_room.resolve_slot_purchase(game, {"max_bonus": 0})
    assert st.coins == 100
    assert ("coins", 100) in st.items_found_log


# --------------------------------------------------------- roulette resolution

def test_red_spot_grants_nothing():
    """A scripted red result changes no resource and disables the tier
    entry, but grants nothing -- 'half of them are red and give nothing'."""
    st, reg = _state_with_registry()
    rng = _ScriptedRng(casino_roulette_red=[True])
    game = _fake_game(st, reg, rng)
    tier = _rules().roulette_tiers[0]
    stored = [{"kind": "casino_roulette", "price": tier.cost}]
    before_coins = st.coins
    casino_room.resolve_roulette_purchase(game, {"price": tier.cost}, stored)
    assert st.coins == before_coins
    assert stored[0]["disabled"] is True


def test_non_red_spot_grants_the_scripted_prize():
    """A non-red result picks the tier's prize at the scripted index -- the
    5-coin tier's row 0 is 10 coins."""
    st, reg = _state_with_registry()
    rng = _ScriptedRng(casino_roulette_red=[False], casino_roulette_prize=[0])
    game = _fake_game(st, reg, rng)
    tier = _rules().roulette_tiers[0]
    stored = [{"kind": "casino_roulette", "price": tier.cost}]
    before = st.coins
    casino_room.resolve_roulette_purchase(game, {"price": tier.cost}, stored)
    assert st.coins == before + 10


def test_multi_prize_grants_every_sub_resource():
    """The 100-coin tier's 4th row ('10 of each: steps, keys, gems, gold,
    dice') grants all five resources from a single "multi" prize."""
    st, reg = _state_with_registry()
    rng = _ScriptedRng(casino_roulette_red=[False], casino_roulette_prize=[3])
    game = _fake_game(st, reg, rng)
    tier = next(t for t in _rules().roulette_tiers if t.cost == 100)
    stored = [{"kind": "casino_roulette", "price": tier.cost}]
    st.coins, st.keys, st.gems, st.dice, st.steps = 0, 0, 0, 0, 0
    casino_room.resolve_roulette_purchase(game, {"price": tier.cost}, stored)
    assert (st.coins, st.keys, st.gems, st.dice, st.steps) == (10, 10, 10, 10, 10)


def test_free_spins_resolve_immediately_on_the_same_wheel_and_stack():
    """Landing on 'free spins' (row 5 of the 20-coin tier) queues 2 more
    spins of the SAME tier's wheel; if one of those ALSO lands on free
    spins, 2 more are queued again (stacking), per the wiki's own wording."""
    st, reg = _state_with_registry()
    tier = next(t for t in _rules().roulette_tiers if t.cost == 20)
    free_spin_row = next(i for i, p in enumerate(tier.prizes) if p.kind == "free_spins")
    # Spin 1 (the purchase itself): free spins -> queues 2 more (pending=2).
    # Spin 2: free spins AGAIN -> queues 2 more on top (pending=1+2=3),
    # proving the stack. Spins 3-5: red (nothing). 5 spins resolved in total
    # (1 + 2 + 2), consuming 5 chance() calls and 2 randint() calls.
    rng = _ScriptedRng(
        casino_roulette_red=[False, False, True, True, True],
        casino_roulette_prize=[free_spin_row, free_spin_row],
    )
    game = _fake_game(st, reg, rng)
    stored = [{"kind": "casino_roulette", "price": tier.cost}]
    before = st.coins
    casino_room.resolve_roulette_purchase(game, {"price": tier.cost}, stored)
    # No coin-paying spot was ever drawn in this script, so coins are
    # unchanged -- the point of this test is that the scripted queues drain
    # to EXACTLY empty (5 chance() calls, 2 randint() calls), which pins the
    # exact recursive-stacking count: too few loop iterations would leave
    # queue items unused, too many would raise from an exhausted queue.
    assert st.coins == before
    assert rng._queues["casino_roulette_red"] == []
    assert rng._queues["casino_roulette_prize"] == []


def test_roulette_disables_all_three_tiers_after_any_play():
    """'It can only be spun once per day' is total across every cost tier:
    playing the 5-coin tier disables the 20- and 100-coin entries too."""
    st, reg = _state_with_registry()
    rng = _ScriptedRng(casino_roulette_red=[True])
    game = _fake_game(st, reg, rng)
    stored = [
        {"id": "roulette_5", "kind": "casino_roulette", "price": 5},
        {"id": "roulette_20", "kind": "casino_roulette", "price": 20},
        {"id": "roulette_100", "kind": "casino_roulette", "price": 100},
    ]
    casino_room.resolve_roulette_purchase(game, stored[0], stored)
    assert all(e.get("disabled") for e in stored)


def test_roulette_outcomes_over_a_sweep_cover_both_red_and_a_prize():
    """Real Rng, many seeds: both a red (no coin change) and at least one
    non-red prize are reachable outcomes -- the SET of outcomes, not a rate
    bound on a random quantity."""
    tier = _rules().roulette_tiers[0]
    saw_red = False
    saw_prize = False
    for seed in range(200):
        st, reg = _state_with_registry()
        rng = Rng(seed)
        game = _fake_game(st, reg, rng)
        stored = [{"kind": "casino_roulette", "price": tier.cost}]
        before = (st.coins, st.keys, st.gems)
        casino_room.resolve_roulette_purchase(game, {"price": tier.cost}, stored)
        after = (st.coins, st.keys, st.gems)
        if after == before:
            saw_red = True
        else:
            saw_prize = True
        if saw_red and saw_prize:
            break
    assert saw_red and saw_prize


# --------------------------------------------------------------- stock builder

def test_casino_stock_has_two_slot_entries_and_one_per_roulette_tier():
    """on_enter_shop rolls exactly 5 entries: quick spin, spin-and-reroll,
    and one roulette entry per data/casino.json tier (5/20/100) -- replacing
    the pre-implementation empty stock this room used to roll."""
    reg = Registry.load()
    game = Game(GameConfig(special_items=True), seed=0, registry=reg)
    _enter_casino(game)
    entries = game.state.shops.stock["casino"]
    ids = [e["id"] for e in entries]
    assert ids == [
        "slot_quick_spin", "slot_spin_and_reroll",
        "roulette_5", "roulette_20", "roulette_100",
    ]
    assert [e["price"] for e in entries] == [1, 1, 5, 20, 100]


def test_casino_stock_not_rolled_when_special_items_disabled():
    """shops.on_enter_shop only runs behind cfg.special_items (game.py's own
    gate); with it off, the Casino's stock is never rolled at all."""
    reg = Registry.load()
    game = Game(GameConfig(special_items=False), seed=0, registry=reg)
    casino = reg.by_id["casino"]
    game._place_room(casino, 7, casino.door_mask)
    game.state.pos = 7
    game.phase = Phase.NAVIGATE
    assert shops.current_shop_id(game) == "casino"
    assert game.state.shops.stock.get("casino") is None


def test_no_shop_registers_a_stock_builder_unexpectedly_includes_casino():
    """Companion to tests/test_shops.py's own _CUSTOM_STOCK_SHOPS pin: this
    room module is expected to register a builder now."""
    import blueprince_sim.engine.effects.rooms  # noqa: F401  (registers builders)
    assert "casino" in shops._STOCK_BUILDERS


# --------------------------------------------------------- end-to-end via buy()

def test_buying_the_quick_spin_deducts_exactly_the_base_price_or_more_on_payout():
    """shops.buy() deducts the 1-coin base price up front; casino.py may add
    a payout on top, but never spends a bonus reroll for the 0-budget entry."""
    reg = Registry.load()
    game = Game(GameConfig(), seed=3, registry=reg)
    _enter_casino(game)
    game.state.coins = 50
    before = game.state.coins
    stock = shops.stock_for(game)
    idx = next(i for i, d in enumerate(stock) if d["id"] == "slot_quick_spin")
    shops.buy(game, idx)
    # Base price (1) always leaves; payout (>=0) may return some or all of it.
    assert game.state.coins >= before - 1


def test_buying_a_roulette_tier_disables_the_others_end_to_end():
    """End-to-end through shops.buy(): playing the 5-coin tier via the real
    purchase path also disables the 20- and 100-coin display entries."""
    reg = Registry.load()
    game = Game(GameConfig(), seed=5, registry=reg)
    _enter_casino(game)
    game.state.coins = 1000
    stock = shops.stock_for(game)
    idx5 = next(i for i, d in enumerate(stock) if d["id"] == "roulette_5")
    shops.buy(game, idx5)
    stock_after = shops.stock_for(game)
    for entry_id in ("roulette_5", "roulette_20", "roulette_100"):
        d = next(d for d in stock_after if d["id"] == entry_id)
        assert d["sold_out"] is True


# ------------------------------------------------------------- room record

def test_casino_grants_no_guaranteed_items_on_first_entry():
    """The old "grants 1 die as approximation" stand-in is gone now that the
    real games are modelled -- items.guaranteed is empty, and first entry
    grants no dice on its own (luck suppressed so the separate
    additional_max=1 luck slot cannot mask the assertion)."""
    reg = Registry.load()
    casino = reg.by_id["casino"]
    assert casino.items.guaranteed == ()

    game = Game(GameConfig(special_items=False), seed=0, registry=reg)
    suppress_luck(game)
    game._place_room(casino, 7, N | S)
    dice_before = game.state.dice
    game.move(N)
    assert game.state.pos == 7
    assert game.state.dice == dice_before


def test_casino_lever_grants_no_coins_or_gems_but_unlocks_golden_bonus_spins():
    """Installing the Broken Lever in the Casino grants nothing directly
    (special_items.json's machines.casino.grants is now empty -- the old 20
    coins + 2 gems was an invented placeholder, not a sourced value); its
    real effect is the 3-vs-5 bonus-spin cap, read live from
    state.special.machines_used by casino.py, not from a grants list."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    _place_room(st, reg, "casino", 5)
    st.pos = 5
    game = _fake_game(st, reg, Rng(0))
    before_coins, before_gems = st.coins, st.gems
    si.install_lever(game)
    assert st.coins == before_coins
    assert st.gems == before_gems
    assert "casino" in st.special.machines_used
