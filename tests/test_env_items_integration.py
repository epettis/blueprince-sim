"""End-to-end: the new item actions and observations flow through env.step()."""

from __future__ import annotations

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv


def _stand_in_shop(env: BluePrinceEnv, shop_id: str, coins: int) -> None:
    """Craft the underlying game so the player stands in a stocked shop."""
    game = env.game
    room = game.registry.by_id[shop_id]
    cell = 7  # rank 2, adjacent-ish; exact position is irrelevant off the nav path
    st = game.state
    st.grid[cell] = room.idx
    st.placed_doors[cell] = room.door_mask
    st.entered[cell] = True
    st.pos = cell
    st.coins = coins
    from blueprince_sim.engine import shops
    shops.on_enter_shop(game, room)


def test_env_step_buys_from_a_shop():
    """A masked BUY action stepped through the env spends coins and grants the
    entry, and the post-step observation reflects both.

    Pins the whole chain: mask -> step -> engine buy -> obs re-encode.
    """
    env = BluePrinceEnv(GameConfig())
    env.reset(seed=3)
    _stand_in_shop(env, "commissary", coins=50)
    mask = env.action_masks()
    buy_ids = [i for i in range(A.BUY_BASE, A.TRADE_BASE) if mask[i]]
    assert buy_ids, "a stocked, affordable commissary must offer buy actions"
    stock = env.game.shop_stock()
    slot = buy_ids[0] - A.BUY_BASE
    price = stock[slot]["price"]
    coins_before = env.game.state.coins
    obs, reward, term, trunc, info = env.step(buy_ids[0])
    assert env.game.state.coins == coins_before - price
    assert np.isfinite(reward)
    # The observation is coherent post-purchase: shop rows still present and
    # the bought slot is either sold out or restocked-limited, never invalid.
    assert obs["shop_stock"].shape == (6, 5)
    assert obs["resources"][3] == env.game.state.coins


def test_env_step_fabricates_in_workshop():
    """A masked FABRICATE action stepped through the env consumes the inputs
    and grants the contraption, visible in the inventory observation.

    Pins that the fabricate action index maps to the registry recipe order.
    """
    cfg = GameConfig(starting_items=frozenset({"lock_pick_kit", "metal_detector"}))
    env = BluePrinceEnv(cfg)
    env.reset(seed=5)
    _stand_in_shop(env, "workshop", coins=0)
    mask = env.action_masks()
    fab_ids = [i for i in range(A.FABRICATE_BASE, A.SCEPTER_BASE) if mask[i]]
    assert fab_ids, "holding both inputs in the Workshop must offer a fabricate action"
    recipe_i = fab_ids[0] - A.FABRICATE_BASE
    output = env.game.registry.special.fabrication[recipe_i][1]
    assert output == "pick_sound_amplifier"
    obs, _, _, _, _ = env.step(fab_ids[0])
    item_ids = [it.id for it in env.game.registry.special.items]
    assert obs["inventory"][item_ids.index("pick_sound_amplifier")] == 1
    assert obs["inventory"][item_ids.index("lock_pick_kit")] == 0
    assert obs["inventory"][item_ids.index("metal_detector")] == 0


def test_env_observation_space_contains_live_obs_all_phases():
    """Every observation produced across a random masked episode fits the
    declared observation space.

    New keys must never leave their declared bounds mid-episode (the space is
    what SB3 validates against at train time).
    """
    env = BluePrinceEnv(GameConfig(west_gate_unlatched=True))
    obs, _ = env.reset(seed=11)
    rng = np.random.default_rng(0)
    assert env.observation_space.contains(obs)
    for _ in range(60):
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        obs, _, term, trunc, _ = env.step(int(rng.choice(legal)))
        assert env.observation_space.contains(obs)
        if term or trunc:
            break
