"""Tomb: lighting does not require the Diary Key it rewards.

Split out of the old test_ignition.py, which keeps the generic ignition
system tests (can_light rules, action mask wiring); see tests/test_ignition.py
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


def test_tomb_can_be_lit_without_diary_key():
    """can_light at the Tomb returns True when holding a torch (Diary Key is not required).

    Wiki-verified: the Diary Key is a REWARD of lighting the Tomb, not a prerequisite.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert si.can_light(game), "Tomb must be lightable with only a torch (no diary_key required)"
