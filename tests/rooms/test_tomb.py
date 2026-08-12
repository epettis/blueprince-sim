"""Tomb: lighting does not require the Diary Key it rewards, plus its
coins_per_deadend accumulation.

See tests/test_ignition.py for the generic ignition system tests (can_light
rules, action mask wiring).

The coins_per_deadend tests below cover Dead Ends drafted after the Tomb is
placed. The Tomb's own placement is covered separately, alongside the
Nursery's, since both ride the same dispatch.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
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


def test_tomb_category_does_not_activate_the_outer_shop_dead_branch():
    """Tomb's category is "blackprint" (verified from the wiki), not "shop":
    entering it off-grid must not resolve a current_shop_id -- that branch
    (game.py:994 / shops.py:359) only fires for Trading Post, the one outer
    room that really is a Shop. See tests/rooms/test_trading_post.py for the
    positive case."""
    reg = Registry.load()
    tomb = reg.by_id["tomb"]
    assert tomb.category == "blackprint"

    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=1, registry=reg)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 1)
    assert g.registry.rooms[opt.room_idx].id == "tomb", "setup: seed must deal Tomb into slot 1"
    g.choose(1)
    g.travel_to("tomb")

    assert g.state.outer_room_entered
    assert shops.current_shop_id(g) is None


def test_tomb_grants_coins_for_a_dead_end_drafted_after_it(registry, cfg):
    """Once the Tomb is placed, drafting any further Dead End room in the
    house grants +5 coins (coins_per_deadend, Hook.ON_DRAFT_ROOM)."""
    g = Game(cfg, seed=1)
    tomb = registry.by_id["tomb"]
    closet = registry.by_id["closet"]
    assert closet.layout == "dead_end", "setup: Closet must be a Dead End"
    g._place_room(tomb, 6, tomb.door_mask)
    coins_before = g.state.coins
    g._place_room(closet, 11, closet.door_mask)
    assert g.state.coins == coins_before + 5


def test_tomb_grants_nothing_for_a_non_dead_end_drafted_after_it(registry, cfg):
    """A room drafted after the Tomb that is NOT a Dead End grants no coins --
    coins_per_deadend is keyed on ctx_room.layout, not on drafting alone."""
    g = Game(cfg, seed=1)
    tomb = registry.by_id["tomb"]
    not_dead_end = next(r for r in registry.rooms
                        if r.layout != "dead_end" and r.rarity is not None)
    g._place_room(tomb, 6, tomb.door_mask)
    coins_before = g.state.coins
    g._place_room(not_dead_end, 11, not_dead_end.door_mask)
    assert g.state.coins == coins_before


def test_tomb_grants_coins_for_its_own_placement(registry, cfg):
    """The Tomb's own layout is a Dead End, so placing it grants +5 coins
    immediately for itself, not only for Dead Ends drafted afterward."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    tomb = registry.by_id["tomb"]
    coins_before = g.state.coins
    g._place_room(tomb, 6, tomb.door_mask)
    assert g.state.coins == coins_before + 5
