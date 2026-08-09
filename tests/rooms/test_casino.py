"""Casino: the Broken Lever machine's slot bonus loot.

Split out of the old test_ignition.py, which keeps the broken_lever item's
generic consumption rules for any machine room; see tests/test_ignition.py
for those.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState


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
