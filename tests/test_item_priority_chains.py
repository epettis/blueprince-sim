"""Characterisation tests for task 22 phase 4: pin today's item-conflict
arithmetic in special_items.py's six priority/fold functions before any of
their per-item logic moves into engine/effects/items/. These must pass
unchanged before and after the migration -- if one needs editing afterwards,
the migration changed behaviour, not just its location.

Each test targets one conflict a priority order (or, for food_steps, a fixed
pipeline order) decides between two simultaneously-held items.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N


def _game(items: frozenset[str] = frozenset(), seed: int = 0) -> Game:
    return Game(GameConfig(starting_items=items), seed=seed)


# --------------------------------------------------- gem_cost_modifier chain

def test_emerald_bracelet_and_hall_pass_both_applicable_waive_exactly_once():
    """Holding both Emerald Bracelet and Hall Pass while drafting a hallway
    room from a hallway doorway still waives the gem cost to exactly 0 --
    two applicable waivers must not double-count (there is nothing left to
    subtract twice, but the priority order must still resolve to a single
    winner rather than erroring or stacking).
    """
    game = _game(frozenset({"emerald_bracelet", "hall_pass"}))
    reg = game.registry
    hallway = reg.by_id["hallway"]
    # A hallway room that also carries a gem cost, so Hall Pass's own
    # hallway-from-hallway condition is genuinely satisfied too -- not just
    # trivially true because Emerald Bracelet alone would waive it.
    gem_hallway = reg.by_id["passageway"]
    assert gem_hallway.is_category("hallway") and gem_hallway.gem_cost > 0
    from blueprince_sim.engine.state import PendingDraft
    game.state.grid[7] = hallway.idx
    game.state.pending = PendingDraft(from_cell=7, direction=N, target_cell=6)

    result = si.gem_cost_modifier(game, gem_hallway, gem_hallway.gem_cost)

    assert result == 0


# --------------------------------------------------- move_step_cost chain

def test_stopwatch_and_running_shoes_both_held_stopwatch_wins_first():
    """With both Stopwatch and Running Shoes held, the Stopwatch's higher
    priority spends its own charge on a free move and leaves the Running
    Shoes cadence counter untouched -- only one item's charge is spent per
    move, and it is always the higher-priority one while its charges last.
    """
    game = _game(frozenset({"stopwatch", "running_shoes"}))
    reg = game.registry
    entrance = reg.by_id["entrance_hall"]
    left_before = game.state.special.stopwatch_left
    moves_before = game.state.special.moves_since_free

    cost = si.move_step_cost(game, game.state.pos, N, entrance)

    assert cost == 0
    assert game.state.special.stopwatch_left == left_before - 1
    assert game.state.special.moves_since_free == moves_before, (
        "Running Shoes cadence must not advance while the Stopwatch is covering the move")


def test_hall_pass_and_stopwatch_both_held_hall_pass_wins_free_hallway_move():
    """Hall Pass's free hallway-to-hallway move takes priority over an active
    Stopwatch, and does not spend a Stopwatch charge -- Hall Pass must be
    checked, and satisfied, before the Stopwatch is even touched.
    """
    game = _game(frozenset({"hall_pass", "stopwatch"}))
    reg = game.registry
    hallway = reg.by_id["hallway"]
    game.state.grid[7] = hallway.idx
    left_before = game.state.special.stopwatch_left

    cost = si.move_step_cost(game, 7, N, hallway)

    assert cost == 0
    assert game.state.special.stopwatch_left == left_before, (
        "Hall Pass's free move must not consume a Stopwatch charge")


# --------------------------------------------------- on_coins_granted chain

def test_lucky_purse_and_coin_purse_both_held_lucky_purse_wins():
    """With both Lucky Purse and Coin Purse held, Lucky Purse's flat doubling
    wins and the Coin Purse interest accumulator is not advanced -- holding
    the superseded item alongside the winner must not leak a partial effect.
    """
    from blueprince_sim.engine.model import Registry
    from blueprince_sim.engine.state import GameState
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    st.inventory["lucky_purse"] = 1
    st.inventory["coin_purse"] = 1

    bonus = si.on_coins_granted(st, reg, 5)

    assert bonus == 5
    assert st.special.coin_interest == 0


# --------------------------------------------------- gem-payment waiver guard

def test_stopwatch_waives_gems_does_not_spend_a_charge_on_a_free_payment():
    """stopwatch_waives_gems(game, 0) returns False and leaves stopwatch_left
    untouched -- a zero-cost payment must never burn one of the Stopwatch's
    limited free-cost events, the same guard gem_cost_modifier applies on
    its own query path.
    """
    game = _game(frozenset({"stopwatch"}))
    left_before = game.state.special.stopwatch_left

    result = si.stopwatch_waives_gems(game, 0)

    assert result is False
    assert game.state.special.stopwatch_left == left_before
