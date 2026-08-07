"""Rotating Gear (upstairs) -- the `upper_rotating_gear` area node.

Owner spec (docs/open_tasks.md decisions log, 2026-08-06): a room reached
through a hallway off the Underpass, opened by Boiler Room steam. The player
unlocks it permanently the first time they enter the Boiler Room; from the
Underpass it is 1 step to retrieve a gem and the Treasure Trove blackprint,
then a free step back down. It is explicitly NOT reachable from the
pre-existing `rotating_gear` node.

This graduates the `boiler_room_steam` gate from an open stub
(`kind: "unmodelled", stub: true`) to a real one (`kind: "flag", stub: false`),
which TIGHTENS reachability -- so this file also pins that the tightening does
not stand up an empty action mask anywhere around the gate.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import GateContext, reachable
from blueprince_sim.engine.game import Game
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain

# A cell with no neighbours placed yet (rank 2, col 2); used only to plant the
# Boiler Room directly, bypassing the draft, the way test_sanctum_route.py's
# _place_at/_enter_at helpers bypass it for the Foundation.
_SCRATCH_CELL = 7


def _place_and_enter(g: Game, room_id: str, cell: int) -> None:
    """Plant ``room_id`` at ``cell`` (no doors) and fire its ON_ENTER bookkeeping.

    Bypasses drafting and walking entirely -- only the entry-triggered
    bookkeeping (game.py::_enter) matters for these tests, not path legality.
    """
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = 0
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1
    g.state.pos = cell
    g._enter(cell)


def test_upper_rotating_gear_unreachable_before_boiler_room(registry):
    """Standing at the Underpass with boiler_room_steam never earned, Upper
    Rotating Gear is unreachable -- the gate is a real closed gate, not the
    open stub it used to be."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.area = "underpass"
    assert g.area_route_cost("upper_rotating_gear") is None


def test_upper_rotating_gear_reachable_one_step_after_boiler_room(registry):
    """Entering the Boiler Room (a real production entry point, game.py::_enter)
    permanently opens the gate; from the Underpass, Upper Rotating Gear is then
    exactly 1 step away, matching the owner's 'walk one step from the
    Underpass' description."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    _place_and_enter(g, "boiler_room", _SCRATCH_CELL)
    assert g.state.boiler_room_steam, "entering the Boiler Room must set the flag"

    g.state.area = "underpass"
    dist = reachable(g.registry.area_graph, "underpass", g._gate_ctx())
    assert dist.get("upper_rotating_gear") == 1


def test_boiler_room_steam_persists_across_days_before_any_room_entered(registry):
    """The unlock survives a day boundary through the real carryover()/DayChain
    path, and is live in _gate_ctx().flags on day 2 BEFORE any room is entered.

    This is the cfg-vs-state trap candlestick_stairway_lit also has to guard
    against: state.boiler_room_steam resets to False on a fresh GameState, so
    if _gate_ctx() only consulted state (not cfg), a carried-over unlock would
    read as unset until some other room's entry happened to run first.
    """
    chain = DayChain(GameConfig(), n_days=3)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    g1.state.steps = 200
    _place_and_enter(g1, "boiler_room", _SCRATCH_CELL)
    assert g1.state.boiler_room_steam

    chain.advance(g1.carryover())
    cfg_day2 = chain.next_config()
    assert cfg_day2.boiler_room_steam, "must survive carryover into day 2's GameConfig"

    g2 = Game(cfg_day2, seed=2, registry=registry)
    assert not g2.state.boiler_room_steam, "setup: fresh day state, nothing entered yet"
    assert "boiler_room_steam" in g2._gate_ctx().flags, (
        "the flag must be live on day 2 from carried-over cfg alone, before any "
        "room entry"
    )
    g2.state.area = "underpass"
    assert g2.area_route_cost("upper_rotating_gear") is not None, (
        "the route must stay open on day 2 without re-entering the Boiler Room"
    )


def test_arrival_grants_gem_once_per_day_and_blackprint(registry):
    """Arriving at Upper Rotating Gear grants +1 gem (once per day, not once
    per revisit) and permanently unlocks the Treasure Trove blackprint."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.area = "underpass"
    g.state.boiler_room_steam = True
    gems_before = g.state.gems

    g.travel_to("upper_rotating_gear")
    assert g.state.gems == gems_before + 1
    assert g.state.treasure_trove_blackprint

    # Leaving and coming back the same day must not re-pay the gem.
    g.travel_to("underpass")
    g.travel_to("upper_rotating_gear")
    assert g.state.gems == gems_before + 1, "the gem is once per day, not once per visit"


def test_treasure_trove_blackprint_adds_room_to_draft_pool(registry):
    """The blackprint flag actually makes the Treasure Trove draftable: a
    fresh GameConfig with treasure_trove_blackprint=True includes it in
    decks.py::eligible_pool, and without the flag it does not."""
    from blueprince_sim.engine.decks import eligible_pool

    pool_without = eligible_pool(registry, GameConfig())
    pool_with = eligible_pool(registry, GameConfig(treasure_trove_blackprint=True))
    assert "treasure_trove" not in {r.id for r in pool_without}
    assert "treasure_trove" in {r.id for r in pool_with}


def test_rotating_gear_and_upper_rotating_gear_have_no_direct_edge(registry):
    """Rotating Gear and Rotating Gear (upstairs) have NO direct edge -- per the
    owner spec, 'It is not reachable from the existing Rotating Gear room.'

    Checked against the parsed graph's own adjacency (the structure BFS
    traversal uses), not by grepping the JSON edge list. Under a maximally
    permissive context, upper_rotating_gear IS reachable from rotating_gear
    (2 hops, via the pre-existing rotating_gear -> underpass edge, itself
    gated on mine_south_visited) -- that indirect route through the Underpass
    is real and expected; only a direct 1-hop shortcut is ruled out.
    """
    graph = registry.area_graph
    rg_direct_neighbors = {n for n, _ in graph.adjacency.get("rotating_gear", [])}
    urg_direct_neighbors = {n for n, _ in graph.adjacency.get("upper_rotating_gear", [])}
    assert "upper_rotating_gear" not in rg_direct_neighbors
    assert "rotating_gear" not in urg_direct_neighbors

    ctx = GateContext(
        held_items={iid: 99 for iid in
                     ("sanctum_key", "burning_glass", "torch", "microchip", "basement_key")},
        flags=frozenset(graph.gates.keys()),
        rooms_entered=frozenset(r.id for r in registry.rooms),
    )
    dist = reachable(graph, "rotating_gear", ctx)
    assert dist.get("upper_rotating_gear") == 2, (
        "the only route is the 2-hop path through underpass, never a 1-hop shortcut"
    )


def test_no_state_around_the_gate_yields_an_empty_action_mask(registry):
    """Tightening boiler_room_steam from an open stub to a real gate must not
    strand a player with zero legal actions -- the MaskablePPO-killing failure
    mode this repo hit earlier today. Checked for both nodes touched by the
    gate, with the gate both closed and open."""
    for steam in (False, True):
        cfg = GameConfig(boiler_room_steam=steam)
        for node in ("upper_rotating_gear", "underpass"):
            g = Game(cfg, seed=1, registry=registry)
            g.state.steps = 200
            g.state.area = node
            mask = A.action_mask(g)
            assert any(mask), f"empty action mask at {node!r} (boiler_room_steam={steam})"
