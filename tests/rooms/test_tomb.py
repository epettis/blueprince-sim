"""Tomb: lighting does not require the Diary Key it rewards, plus its
coins_per_deadend accumulation.

See tests/test_ignition.py for the generic ignition system tests (can_light
rules, action mask wiring).

The coins_per_deadend tests below drive the Tomb through the real outer-room
pipeline, because that is the only way it is ever drafted: it is a
``pool: "outer"`` room, so it occupies no grid cell, its coins park under
``tomb.OFF_GRID_CELL`` in ``GameState.spread_pending``, and they are collected
when the player arrives at it.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.effects.rooms.tomb import COINS_PER_DEAD_END, OFF_GRID_CELL
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DraftOption, GameState

PARKED_PILE = ("coins_exact", COINS_PER_DEAD_END)


def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _outer_cfg() -> GameConfig:
    """Config for the outer-draft tests: the West Gate shortcut keeps the walk
    to the doorstep cheap enough that the day survives it, and special items
    stay off so no item hook adds coins alongside the ones under test."""
    return GameConfig(west_gate_unlatched=True, special_items=False)


def _draft_tomb_as_the_outer_room(game: Game, registry: Registry) -> None:
    """Draft the Tomb through Game.open_outer_draft/choose, deterministically.

    The dealt hand is replaced with a single Tomb option rather than hunting a
    seed that happens to offer one -- the outer deal's shuffle is not the
    property under test, and a seed is not a scenario constructor.
    """
    pending = game.open_outer_draft()
    assert pending is not None, "setup: the walk to the doorstep must not end the day"
    tomb = registry.by_id["tomb"]
    pending.options = [DraftOption(room_idx=tomb.idx, orientation=tomb.door_mask,
                                   gem_cost=0, slot=0)]
    game.choose(0)
    assert game.drafted_outer_room is tomb, "setup: the Tomb must be today's outer room"


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


def test_the_tomb_counts_itself_and_parks_its_own_five_coins_at_its_draft(registry):
    """Drafting the Tomb as the outer room parks one 5-coin pile for the Tomb
    itself: it is a one-door Dead End card and counts among the Dead Ends it
    collects for. Nothing reaches the player yet -- this is a spread, so the
    coins sit in the room until someone walks in."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    coins_before = g.state.coins
    _draft_tomb_as_the_outer_room(g, registry)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE]
    assert g.state.coins == coins_before, "a spread does not pay at the draft"


def test_entering_the_tomb_with_no_other_dead_end_drafted_pays_five(registry):
    """The owner's ruling stated directly: because the Tomb counts itself, a
    Tomb entered on a day when no other Dead End was drafted still pays +5.
    This is the whole of the effect the player can observe, so it is asserted
    on state.coins rather than on the parking dict."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    coins_before = g.state.coins
    g.travel_to("tomb")
    assert g.state.outer_room_entered, "setup: the walk into the Tomb must succeed"
    assert g.state.coins == coins_before + COINS_PER_DEAD_END


def test_a_dead_end_drafted_after_the_tomb_parks_a_second_pile(registry):
    """Every further Dead End drafted in the house parks its own 5 coins, so
    entering the Tomb after one grid Dead End pays 10: the Tomb's own pile
    plus that room's."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    closet = registry.by_id["closet"]
    assert closet.layout == "dead_end", "setup: Closet must be a Dead End"
    g._place_room(closet, 11, closet.door_mask)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE, PARKED_PILE]
    coins_before = g.state.coins
    g.travel_to("tomb")
    assert g.state.coins == coins_before + 2 * COINS_PER_DEAD_END


def test_a_dead_end_drafted_before_the_tomb_pays_nothing(registry):
    """The trigger is each Dead End's *draft*, so the effect is draft-ordered:
    a Dead End already standing when the Tomb is drafted parks nothing, there
    having been no Tomb on the estate to spread into at its draft moment. The
    Tomb's own self-count is the only pile in this scenario."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    closet = registry.by_id["closet"]
    g._place_room(closet, 11, closet.door_mask)
    assert g.state.spread_pending == {}, "no Tomb yet: nothing to spread into"
    _draft_tomb_as_the_outer_room(g, registry)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE]


def test_a_non_dead_end_drafted_after_the_tomb_parks_nothing(registry):
    """A room drafted after the Tomb that is NOT a Dead End parks no coins --
    coins_per_deadend is keyed on the room's actual drafted orientation having
    exactly one door, not on drafting alone."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    not_dead_end = next(r for r in registry.rooms
                        if r.layout != "dead_end" and r.rarity is not None)
    g._place_room(not_dead_end, 11, not_dead_end.door_mask)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE], "only the Tomb's own pile"


def test_a_greenhouse_drafted_in_a_corner_orientation_parks_nothing(registry):
    """The Greenhouse's ``layout`` is "dead_end", but its ``alt_layouts``
    include "corner", so it can be drafted with two doors (once its Power
    Hammer wall break, ``Room.alt_layouts_gate``, admits ``Room.
    gated_rotations`` at draft time -- ``_place_room`` itself takes any
    orientation directly and does not re-check legality). A Greenhouse
    drafted in one of its corner rotations (door mask 3, 6, 9, or 12) is not
    a Dead End and must not pay the Tomb, even though its frozen Room.layout
    still reads "dead_end"."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    greenhouse = registry.by_id["greenhouse"]
    corner_mask = 3  # S|E -- one of the Greenhouse's gated corner rotations
    assert corner_mask in greenhouse.gated_rotations, "setup: corner rotation must be a real shape"
    g._place_room(greenhouse, 11, corner_mask)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE], "only the Tomb's own pile"


def test_a_greenhouse_drafted_as_a_genuine_dead_end_parks_its_pile(registry):
    """The same Greenhouse, drafted in its one-door canonical orientation
    (its own ``layout`` value), IS a Dead End and pays the Tomb -- the
    contrast with the corner case above proves the check follows the
    drafted orientation, not a blanket exemption for the Greenhouse id."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    greenhouse = registry.by_id["greenhouse"]
    g._place_room(greenhouse, 11, greenhouse.door_mask)
    assert g.state.spread_pending[OFF_GRID_CELL] == [PARKED_PILE, PARKED_PILE]


def test_the_tomb_pays_out_again_on_a_later_arrival(registry):
    """Coins parked by a Dead End drafted *after* the player has already been
    in the Tomb are collected on the next arrival, not lost -- the Tomb rides
    _collect_spread's every-arrival rule, exactly as a grid room does."""
    g = Game(_outer_cfg(), seed=1, registry=registry)
    _draft_tomb_as_the_outer_room(g, registry)
    g.travel_to("tomb")
    coins_after_first_visit = g.state.coins
    closet = registry.by_id["closet"]
    g._place_room(closet, 11, closet.door_mask)
    assert g.state.coins == coins_after_first_visit, "still parked, not yet collected"
    g.travel_to("west_path")
    g.travel_to("tomb")
    assert g.state.coins == coins_after_first_visit + COINS_PER_DEAD_END
    assert g.state.spread_pending == {}
