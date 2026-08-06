"""Equivalence and memo-invalidation tests for Game.area_route_costs().

area_route_cost(dest) used to run a full per-anchor area-graph BFS for every
single destination it was asked about; env/actions.py's travel mask loop and
Game._outer_action_in_budget each called it once per area node, so one env
step ran on the order of 40 BFS sweeps. area_route_costs() computes every
destination's cost in one pass (one reachable() call per anchor, on grid; one
off grid) and area_route_cost() becomes a lookup into it. This file pins:
  1. the batch result agrees with an independent per-destination oracle
     across a spread of game states, including hundreds of masked-random-play
     states, and
  2. the new memo (keyed on GateContext, since the _maps() fingerprint alone
     doesn't cover everything gates read) does not go stale.
"""

from __future__ import annotations

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import reachable
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.rl.train import all_unlocks_config

CORRIDOR_CHAIN = (7, 12, 17)  # rank2..rank4, col 2 -- climbs north from the Entrance Hall
FOUNDATION_CELL = 22          # rank 5, col 2


def _place_foundation_connected(g: Game) -> None:
    """Chain inert Corridor fillers north from the Entrance Hall to rank 5 col 2,
    then place the Foundation there directly -- gives the Foundation a grid
    anchor genuinely walkable from the house (same shape as test_sanctum_route's
    helper), so area_route_costs() has a third grid anchor besides house/garage
    to exercise the tie-break and multi-anchor-min logic."""
    corridor = g.registry.by_id["corridor"]
    for cell in CORRIDOR_CHAIN:
        g._place_room(corridor, cell, N | S)
    foundation = g.registry.by_id["the_foundation"]
    g._place_room(foundation, FOUNDATION_CELL, N | S)


def _oracle_area_route_costs(g: Game) -> dict[str, tuple[int, str]]:
    """Independent per-destination area-route computation: the pre-batching
    algorithm, one BFS sweep per (anchor, dest) pair, spelled out plainly here
    so it stands as its own check on area_route_costs() rather than sharing
    code with it. This is the test's oracle, not production code."""
    graph = g.registry.area_graph
    ctx = g._gate_ctx()
    if g.off_grid:
        assert g.state.area is not None
        dist = reachable(graph, g.state.area, ctx)
        return {node_id: (steps, "") for node_id, steps in dist.items()}
    dist_grid = g.distance_map()
    costs: dict[str, tuple[int, str]] = {}
    for dest in graph.nodes:
        best_cost: int | None = None
        best_anchor = ""
        # "house" is visited first (insertion order of _grid_anchors()); the
        # strict "<" below means a later, equal-cost anchor never displaces it.
        for anchor_id, anchor_cell in g._grid_anchors().items():
            g_dist = dist_grid[anchor_cell]
            if g_dist < 0:
                continue
            area_dist = reachable(graph, anchor_id, ctx)
            a_dist = area_dist.get(dest)
            if a_dist is None:
                continue
            cost = g_dist + a_dist
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_anchor = anchor_id
        if best_cost is not None:
            costs[dest] = (best_cost, best_anchor)
    return costs


def _assert_matches_oracle(g: Game, label: str) -> None:
    batch = g.area_route_costs()
    oracle = _oracle_area_route_costs(g)
    assert batch == oracle, f"{label}: area_route_costs() diverged from the per-destination oracle"


# ---------------------------------------------------------------------------
# 1. Equivalence across varied hand-built states
# ---------------------------------------------------------------------------

def test_area_route_costs_matches_oracle_fresh_day(registry):
    """A brand-new day's batch result equals the independent per-destination oracle."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    _assert_matches_oracle(g, "fresh day")


def test_area_route_costs_matches_oracle_foundation_connected(registry):
    """With the Foundation drafted and grid-connected (a third grid anchor),
    the batch result still equals the oracle -- exercises the multi-anchor min."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    _place_foundation_connected(g)
    _assert_matches_oracle(g, "foundation connected")


def test_area_route_costs_matches_oracle_holding_basement_key(registry):
    """Holding a Basement Key opens an item gate the batch and oracle must agree on."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    _place_foundation_connected(g)
    _assert_matches_oracle(g, "basement_key held")


def test_area_route_costs_matches_oracle_holding_power_hammer(registry):
    """Holding a Power Hammer live-breaks the Sealed Entrance flag gate for today only."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["power_hammer"] = 1
    g.state.west_gate_unlatched = True
    _assert_matches_oracle(g, "power_hammer held")


def test_area_route_costs_matches_oracle_off_grid(registry):
    """Off grid (the single-BFS-from-state.area branch) also matches the oracle."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    g.travel_to("grounds")
    assert g.off_grid
    _assert_matches_oracle(g, "off grid")


def test_area_route_costs_matches_oracle_after_mine_south_visited(registry):
    """Once mine_south_visited flips (earned this day, not just carried in from
    cfg), the underpass route opens and the batch result must track it."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    # mine_south is gated behind the (unlit) candlestick_stairway_lit flag, so a
    # bare Game cannot travel straight there from the house; place the player at
    # Catacombs first (one of the mine's real entrances, draxus_scythe always
    # passes) so the arrival at mine_south below is a genuine travel_to() call.
    g.state.area = "catacombs"
    g.travel_to("mine_south")
    assert g.state.mine_south_visited is True
    g.travel_to("reservoir_south")
    _assert_matches_oracle(g, "mine_south_visited")


# ---------------------------------------------------------------------------
# 2. Equivalence across hundreds of masked-random-play states
# ---------------------------------------------------------------------------

def test_area_route_costs_matches_oracle_under_random_masked_play():
    """Drive BluePrinceEnv with uniform-random legal actions under
    all_unlocks_config() and check every step's area_route_costs() against the
    oracle -- the same style of broad state coverage as
    test_antechamber_levers.py's masked-random-play regression, but checking
    route-cost agreement instead of absence of engine assertions."""
    checked = 0
    for seed in range(8):
        env = BluePrinceEnv(cfg=all_unlocks_config())
        env.reset(seed=seed)
        rng = random.Random(seed)
        for _step in range(60):
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            _assert_matches_oracle(env.game, f"seed={seed} step={_step}")
            checked += 1
            action = rng.choice(legal)
            _, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                break
    assert checked >= 200, "setup: expected a few hundred checked states, got too few"


# ---------------------------------------------------------------------------
# 3. Memo invalidation: the GateContext comparison must catch what _maps() misses
# ---------------------------------------------------------------------------

def test_area_route_costs_memo_reacts_to_a_freshly_granted_power_hammer(registry):
    """Granting a Power Hammer changes only the gate context, not any field in
    the _maps() fingerprint (position/area/grid/doors/keys/security/entered),
    so a stale memo would silently keep serving the pre-grant costs -- this is
    exactly the failure mode that would corrupt a training run."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.west_gate_unlatched = True
    before = g.area_route_costs()
    assert "basement" not in before or "the_foundation" not in before, (
        "setup: the Sealed Entrance route must be closed before the hammer is granted"
    )

    g.state.inventory["power_hammer"] = 1
    after = g.area_route_costs()
    assert after != before, "the memo must recompute once the Power Hammer is granted"
    assert "basement" in after, "the hammer must open the Sealed Entrance route into the Basement"


def test_area_route_costs_memo_reacts_to_mine_south_visited_flag(registry):
    """Setting state.mine_south_visited directly (bypassing travel_to, the way
    tests are allowed to poke state) must invalidate the memo just as much as
    earning it through travel -- pins the GateContext equality check, not just
    the _maps() fingerprint, as the source of invalidation. The route to
    underpass runs house -> ... -> basement (Foundation + Basement Key) ->
    reservoir_north -> mine_north -> rotating_gear -> underpass, and the last
    two hops are exactly the edges mine_south_visited gates (docs/areas.md)."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    _place_foundation_connected(g)
    before = g.area_route_costs()
    assert "underpass" not in before, (
        "setup: underpass must be unreachable before mine_south_visited"
    )

    g.state.mine_south_visited = True
    after = g.area_route_costs()
    assert after != before, "the memo must recompute once mine_south_visited flips"
    assert "underpass" in after, "the underpass route must open once mine_south_visited is set"


def test_area_route_costs_memo_is_reused_when_gate_context_is_unchanged(registry):
    """The flip side of invalidation: repeated calls between state changes must
    return the identical cached dict object, not silently recompute every time
    -- otherwise the memo buys nothing and the perf fix does not fix anything."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    first = g.area_route_costs()
    second = g.area_route_costs()
    assert second is first, "an unchanged GateContext must serve the cached dict, not recompute"
