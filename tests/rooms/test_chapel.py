"""Chapel: the Keeper of Tithes entry penalty and altar payout.

See tests/test_ignition.py for the generic ignition system tests (can_light
rules, action mask wiring), which use the Chapel only as one interchangeable
ignition-target vehicle among several.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.multiday import DayChain


# ----------------------------------------------------------------- helpers

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


def test_light_chapel_grants_accumulated_tithes():
    """Lighting the Chapel grants the Keeper of Tithes accumulated total (coins banked by entry penalty).

    The altar pays out exactly what was banked, not a flat amount.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    # Manually seed some banked tithes (as configure() would inject from cfg.chapel_tithes)
    st.special.chapel_tithes = 7
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins == before + 7, (
        f"Chapel must grant exactly the banked tithes (7); got coins delta {st.coins - before}"
    )


def test_light_chapel_zero_tithes_grants_zero_coins():
    """Lighting the Chapel with no tithes banked grants zero coins (piggy bank is empty)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    st.special.chapel_tithes = 0
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins == before, "empty tithe bank must grant 0 coins"


# ====================================================== Chapel tithes accumulation


def _game_with_chapel_at_cell(cell: int = 5, starting_coins: int = 5) -> Game:
    """Return a Game with the Chapel placed at *cell* and the player standing there.

    Uses a real Game (not _fake_game) so that tier1.grant has access to
    game.shelter_protected_ids and the full effect dispatch infrastructure.
    """
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=0)
    chapel_room = g.registry.by_id["chapel"]
    g.state.grid[cell] = chapel_room.idx
    g.state.placed_doors[cell] = chapel_room.door_mask
    g.state.pos = cell
    g.state.entered[cell] = True
    g.state.coins = starting_coins
    return g


def test_chapel_entry_penalty_banks_coin_when_player_has_coins():
    """The Chapel -1 coin entry penalty increments chapel_tithes when the player has coins.

    The Keeper of Tithes banks each coin actually taken; a player with coins loses one and
    the tithe counter goes up by one.
    """
    from blueprince_sim.engine.effects.tier1 import grant as tier1_grant

    g = _game_with_chapel_at_cell(starting_coins=5)
    chapel_room = g.registry.by_id["chapel"]

    # Find and fire the -1 coin grant effect directly (as on_enter would)
    for eff in chapel_room.effects:
        if eff.tag == "grant" and eff.param("resource") == "coins" and eff.param("amount", 0) < 0:
            tier1_grant(g, chapel_room, eff, None)
            break

    assert g.state.coins == 4, "player must lose 1 coin"
    assert g.state.special.chapel_tithes == 1, "tithe counter must increment by the coin taken"


def test_chapel_entry_penalty_banks_nothing_when_broke():
    """The Chapel -1 coin penalty banks nothing when the player has zero coins.

    No coins to take means the Keeper of Tithes receives nothing.
    """
    from blueprince_sim.engine.effects.tier1 import grant as tier1_grant

    g = _game_with_chapel_at_cell(starting_coins=0)
    chapel_room = g.registry.by_id["chapel"]

    for eff in chapel_room.effects:
        if eff.tag == "grant" and eff.param("resource") == "coins" and eff.param("amount", 0) < 0:
            tier1_grant(g, chapel_room, eff, None)
            break

    assert g.state.coins == 0, "player with no coins must not go negative"
    assert g.state.special.chapel_tithes == 0, "tithe counter must not increment when player is broke"


def test_chapel_tithes_persist_across_days_via_daychain():
    """Chapel tithes accumulated on day N appear in the GameConfig on day N+1.

    The counter must carry through DayChain so the total grows across multiple
    days of entering the Chapel before the altar is lit.
    """
    chain = DayChain(GameConfig(), n_days=5)
    # Simulate day 1: 3 tithes banked
    chain.advance({"chapel_tithes": 3})
    cfg_day2 = chain.next_config()
    assert cfg_day2.chapel_tithes == 3, (
        "chapel_tithes from day 1 must appear in day 2's config"
    )

    # Simulate day 2: 2 more tithes banked (total 5)
    chain.advance({"chapel_tithes": 5})
    cfg_day3 = chain.next_config()
    assert cfg_day3.chapel_tithes == 5, (
        "chapel_tithes must reflect the latest running total (5 after payout update)"
    )


def test_chapel_tithes_reset_on_chain_wrap():
    """DayChain resets chapel_tithes to 0 when wrapping to a fresh attempt."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"chapel_tithes": 10})
    chain.advance({"chapel_tithes": 10})  # this advance wraps the chain
    assert chain.chapel_tithes == 0, "tithe bank must reset when the attempt wraps"
