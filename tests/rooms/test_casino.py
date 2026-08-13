"""Casino: the Broken Lever machine's slot bonus loot, plus its own
guaranteed die on first entry.

See tests/test_ignition.py for the broken_lever item's generic consumption
rules, shared by any machine room.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from luck_utils import suppress_luck


def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, seed: int = 0, cfg: GameConfig | None = None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    g.cfg = cfg or GameConfig()
    return g


def _place_room(state, registry, room_id: str, cell: int) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


def test_casino_lever_grants_loot():
    """Installing the lever in the Casino grants its configured slot bonus loot."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    _place_room(st, reg, "casino", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    before_coins = st.coins
    before_gems = st.gems
    si.install_lever(game)
    assert st.coins > before_coins or st.gems > before_gems, (
        "Casino lever must grant coins or gems"
    )


def test_casino_activates_shop_stock_roll_on_entry():
    """Casino's category is now "shop" (not the pool name "studio_addition"),
    so shops.current_shop_id recognizes it while standing in it and
    on_enter_shop rolls its stock -- both were unreachable under the old
    category. data/shops.json has no "casino" table, so the rolled stock is
    an empty (harmless) list, mirroring Trading Post's outer-room case."""
    reg = Registry.load()
    game = Game(GameConfig(special_items=False), seed=0, registry=reg)
    casino = reg.by_id["casino"]
    game._place_room(casino, 7, casino.door_mask)
    game.state.pos = 7
    game.phase = Phase.NAVIGATE

    assert shops.current_shop_id(game) == "casino"

    shops.on_enter_shop(game, casino)
    assert game.state.shops.stock.get("casino") == []
    assert shops.stock_for(game) == []


def test_casino_grants_one_die_on_first_entry():
    """Casino's items.guaranteed is [{"die", 1}] (the slot-machine modeled as
    a guaranteed die, per meta.effect_text) -- granted unconditionally on
    first entry, on top of whatever the luck-rolled additional_max=1 slot
    may separately add. Luck is floored to 0 so that slot never fires,
    isolating the guaranteed grant for an exact assertion."""
    reg = Registry.load()
    casino = reg.by_id["casino"]
    assert casino.items.guaranteed == (("die", 1),)

    game = Game(GameConfig(special_items=False), seed=0, registry=reg)
    suppress_luck(game)
    game._place_room(casino, 7, N | S)  # orientation is irrelevant to the grant
    dice_before = game.state.dice
    game.move(N)
    assert game.state.pos == 7
    assert game.state.dice == dice_before + 1
