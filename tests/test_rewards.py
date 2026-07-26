"""The phased reward: keys appreciate with depth, frontier breadth pays.

Covers the observable shaping behaviors of the ``phased`` reward function:
holding keys is worth more the deeper the run has pushed, spending a key
late costs more than spending it early, only passable frontier doorways
carry potential (a key in hand makes a locked doorway count again), rank
progress is back-loaded past rank 4, and the mode is selectable through
the env config.
"""

from __future__ import annotations

import numpy as np
import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.locks import DOOR_LOCKED, segment_key
from blueprince_sim.env.rewards import phased, snapshot


def _game(registry, **cfg) -> Game:
    return Game(GameConfig(**cfg), seed=1, registry=registry)


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    """Overwrite a doorway segment's state, bumping door_version so caches
    (distance maps, action masks) notice the change."""
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


def test_keys_appreciate_with_depth(registry):
    """The same deepest-rank advance pays strictly more phased reward when
    keys are held: carrying keys into lock territory is itself rewarded."""
    g = _game(registry)

    g.state.keys = 2
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 6
    with_keys = phased(g, prev, False)

    g.state.keys = 0
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 6
    without_keys = phased(g, prev, False)

    assert with_keys > without_keys


def test_no_appreciation_below_lock_territory(registry):
    """Advancing within ranks 1-3, where locks never roll by chance, pays the
    same whether or not keys are held: appreciation starts at rank 4."""
    g = _game(registry)

    g.state.keys = 2
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 3
    with_keys = phased(g, prev, False)

    g.state.keys = 0
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 3
    without_keys = phased(g, prev, False)

    assert with_keys == pytest.approx(without_keys)


def test_spending_a_key_costs_more_late(registry):
    """Losing a key at deepest rank 8 is penalized more than at rank 2, so an
    early spend must clear a lower bar than a late one."""
    g = _game(registry)

    g.deepest_rank = 2
    g.state.keys = 2
    prev = snapshot(g)
    g.state.keys = 1
    early = phased(g, prev, False)

    g.deepest_rank = 8
    g.state.keys = 2
    prev = snapshot(g)
    g.state.keys = 1
    late = phased(g, prev, False)

    assert late < early < 0


def test_frontier_potential_counts_only_passable_doorways(registry):
    """A locked frontier doorway with no key in hand drops out of the frontier
    potential; holding a key makes it count again (a banked key literally buys
    back a pathway)."""
    g = _game(registry)
    g.state.keys = 0
    doorways = g.frontier_doorways()
    assert doorways, "fresh game should have frontier doorways off the Entrance Hall"
    assert all(g.doorway_passable(c, d) for c, d in doorways)
    open_phi = snapshot(g)["phi_frontier"]
    assert open_phi > 0

    cell, d = doorways[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    assert snapshot(g)["phi_frontier"] < open_phi

    g.state.keys = 1
    assert snapshot(g)["phi_frontier"] == pytest.approx(open_phi)


def test_rank_progress_backloaded(registry):
    """One rank of progress deep in the house (4 -> 5) out-pays one rank early
    (1 -> 2), leaving the resource terms dominant during the gathering phase."""
    g = _game(registry)
    g.state.keys = 0

    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 2
    early = phased(g, prev, False)

    g.deepest_rank = 4
    prev = snapshot(g)
    g.deepest_rank = 5
    late = phased(g, prev, False)

    assert late > early > 0


def test_phased_selectable_via_env():
    """The phased reward mode is selectable via config and yields plain float
    rewards from step()."""
    env = make_env(GameConfig(reward="phased"))
    env.reset(seed=3)
    mask = env.action_masks()
    action = int(np.flatnonzero(mask)[0])
    _, reward, *_ = env.step(action)
    assert isinstance(reward, float)


# ------------------------------------------------- special-item valuation

def test_inventory_value_uses_tier_values(registry):
    """A held item is worth its Trading Post tier's value; untradeable items
    use the flat value; counts multiply.

    Items must carry shaping worth or every purchase reads as a coin loss.
    royal_scepter_found=False is explicit because the default is now True (the unlock
    puzzle is unmodeled; False keeps the starting inventory empty for this test).
    """
    from blueprince_sim.engine.special_items import inventory_value
    g = _game(registry, royal_scepter_found=False)
    values = registry.item_rules["special_item_values"]
    assert inventory_value(g.state, registry) == 0.0
    g.state.inventory["magnifying_glass"] = 1  # tier 1
    g.state.inventory["master_key"] = 1        # tier 5
    g.state.inventory["royal_scepter"] = 1     # untradeable (tier null)
    g.state.inventory["microchip"] = 2         # tier 2, stacks
    expected = (values["by_tier"]["1"] + values["by_tier"]["5"]
                + values["untradeable"] + 2 * values["by_tier"]["2"])
    assert inventory_value(g.state, registry) == expected


def test_buying_an_item_is_roughly_reward_neutral(registry):
    """Under both shaped and phased, a fair-priced purchase trades coin value
    for item value instead of reading as a pure loss.

    Before this valuation, every buy cost 0.01*price reward and made shopping
    look strictly bad to the policy.
    """
    from blueprince_sim.engine import shops
    from blueprince_sim.env.rewards import shaped
    g = _game(registry)
    room = registry.by_id["commissary"]
    st = g.state
    cell = 7
    st.grid[cell] = room.idx
    st.placed_doors[cell] = room.door_mask
    st.entered[cell] = True
    st.pos = cell
    st.coins = 50
    shops.on_enter_shop(g, room)
    stock = shops.stock_for(g)
    idx, entry = next((i, d) for i, d in enumerate(stock) if d["kind"] == "item")
    for fn in (shaped, phased):
        prev = snapshot(g)
        g_coins = st.coins
        shops.buy(g, idx)
        r = fn(g, prev, terminated=False)
        # Coin spend really happened, but the reward is near the time-pressure
        # floor, not the old -0.01*price cliff.
        assert st.coins < g_coins
        assert r > -0.001 - 0.01 * entry["price"] / 2
        st.inventory.clear()  # reset for the second reward fn
        st.coins = 50
        g.state.shops.stock.clear()
        shops.on_enter_shop(g, room)


def test_losing_an_item_costs_reward(registry):
    """An item vanishing from the inventory (Lost & Found steal, consumption)
    shows up as a negative shaped delta.

    The same valuation that credits acquisition must charge for loss, so the
    Lost & Found's steal is a real pathing cost to the policy.
    """
    from blueprince_sim.engine.special_items import grant, remove
    from blueprince_sim.env.rewards import shaped
    g = _game(registry)
    grant(g.state, registry, "shovel", source="test")
    prev = snapshot(g)
    remove(g.state, "shovel", consumed=True)
    assert shaped(g, prev, terminated=False) < -0.001  # worse than time pressure alone
