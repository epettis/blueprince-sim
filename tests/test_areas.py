"""Tests for the areas graph library (engine/areas.py + data/areas.json).

All tests operate on observable traversal behaviour, not on data-file contents.
No test asserts a literal distance or asserts that a JSON record has a specific
value — those are schema/range checks and belong in tools/validate_data.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import (
    AreaGraph,
    GateContext,
    gate_open,
    load_areas,
    path,
    reachable,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "blueprince_sim" / "data"


@pytest.fixture(scope="module")
def graph() -> AreaGraph:
    """Load the committed areas.json once for all tests in this module."""
    raw = json.loads((DATA_DIR / "areas.json").read_text())
    return load_areas(raw)


def _ctx(
    held_items: dict[str, int] | None = None,
    flags: frozenset[str] = frozenset(),
    rooms_entered: frozenset[str] = frozenset(),
) -> GateContext:
    """Convenience constructor for GateContext."""
    return GateContext(
        held_items=held_items if held_items is not None else {},
        flags=flags,
        rooms_entered=rooms_entered,
    )


def _all_open_ctx() -> GateContext:
    """A context with every item, flag, and room that any gate in the graph checks."""
    return GateContext(
        held_items={
            "microchip": 3,
            "power_hammer": 1,
            "torch": 1,
            "basement_key": 1,
            "sanctum_key": 1,
        },
        flags=frozenset({"west_gate_unlatched", "mine_south_visited"}),
        rooms_entered=frozenset({"tomb"}),
    )


# ---------------------------------------------------------------------------
# 1-step rule reproduces GameConfig constants (the main evidence the graph is right)
# ---------------------------------------------------------------------------


def test_1step_rule_entrance_hall_to_doorstep(graph: AreaGraph) -> None:
    """BFS distance house->grounds->west_path equals GameConfig.outer_path_entrance_cost.

    These three GameConfig values were independently play-verified and must equal
    the BFS distances derived from the graph. This is the primary evidence the
    1-step-per-edge rule and node choices are correct (areas.md, 'The 1-step rule
    reproduces the existing constants').
    """
    ctx = _all_open_ctx()
    dist = reachable(graph, "house", ctx)
    expected = GameConfig().outer_path_entrance_cost  # 2 by default
    assert dist["west_path"] == expected


def test_1step_rule_garage_to_doorstep(graph: AreaGraph) -> None:
    """BFS distance garage->west_path equals GameConfig.outer_path_garage_cost.

    The garage door gate is currently a stub (passes), so the direct edge is
    traversable. The verified play constant is 1 step.
    """
    ctx = _all_open_ctx()
    dist = reachable(graph, "garage", ctx)
    expected = GameConfig().outer_path_garage_cost  # 1 by default
    assert dist["west_path"] == expected


def test_1step_rule_doorstep_to_outer_room(graph: AreaGraph) -> None:
    """BFS distance west_path->tomb equals GameConfig.outer_enter_cost.

    West Path is the outer-room doorstep AND drafting cave in one node; the
    1-step edge into any outer-room anchor reproduces the outer_enter_cost.
    """
    ctx = _all_open_ctx()
    dist = reachable(graph, "west_path", ctx)
    expected = GameConfig().outer_enter_cost  # 1 by default
    assert dist["tomb"] == expected


# ---------------------------------------------------------------------------
# One-way edge tests
# ---------------------------------------------------------------------------


def test_catacombs_to_mine_south_is_one_way(graph: AreaGraph) -> None:
    """catacombs->mine_south exists in the adjacency map but mine_south->catacombs does not.

    areas.md calls this out explicitly: Draxus's scythe shuts at day end and the
    edge is strictly one-directional. We check the adjacency map directly rather
    than reachability, since mine_south can reach catacombs indirectly via the
    Tomb anchor when the Tomb has been entered.
    """
    # Forward: catacombs directly connects to mine_south
    catacombs_neighbours = {n for n, _ in graph.adjacency.get("catacombs", [])}
    assert "mine_south" in catacombs_neighbours

    # Reverse: mine_south has no direct adjacency edge to catacombs
    mine_south_neighbours = {n for n, _ in graph.adjacency.get("mine_south", [])}
    assert "catacombs" not in mine_south_neighbours


def test_mine_north_south_not_directly_connected(graph: AreaGraph) -> None:
    """Mine North and Mine South are not directly connected; no 1-step edge exists.

    areas.md: 'Mine North and Mine South are NOT directly connected. Getting
    between them means going back out through Reservoir South and around via
    Reservoir North.' Checked directly on the adjacency map (no edge between them)
    and confirmed reachable only by a longer route.
    """
    # No direct adjacency edge in either direction
    mine_south_neighbours = {n for n, _ in graph.adjacency.get("mine_south", [])}
    mine_north_neighbours = {n for n, _ in graph.adjacency.get("mine_north", [])}
    assert "mine_north" not in mine_south_neighbours
    assert "mine_south" not in mine_north_neighbours

    # Mine North IS reachable (indirectly) from Mine South with all gates open
    ctx = _all_open_ctx()
    dist = reachable(graph, "mine_south", ctx)
    assert "mine_north" in dist
    assert dist["mine_north"] > 1


def test_mine_north_south_route_via_reservoir_north(graph: AreaGraph) -> None:
    """The path mine_south->mine_north passes through reservoir_north.

    Verifies the detour described in areas.md: getting between the two mine halves
    requires going via Reservoir North. The exact intermediate node confirms
    no shortcut through Reservoir South directly into Mine North.
    """
    ctx = _all_open_ctx()
    p = path(graph, "mine_south", "mine_north", ctx)
    assert p is not None
    # reservoir_north is on the only path to mine_north
    assert "reservoir_north" in p


# ---------------------------------------------------------------------------
# No dead nodes with all stubs open
# ---------------------------------------------------------------------------


def test_no_dead_nodes_all_items_and_flags(graph: AreaGraph) -> None:
    """All 31 nodes are reachable from 'house' when every item and flag is satisfied.

    This is the test that enforces the owner's stub-open decision: deferred
    mechanisms default to OPEN so that no node measures exactly zero reachability.
    A node that is unreachable in an all-items/all-flags context is a design error.
    """
    ctx = _all_open_ctx()
    dist = reachable(graph, "house", ctx)
    all_node_ids = set(graph.nodes)
    unreachable = all_node_ids - set(dist)
    assert unreachable == set(), f"Unreachable nodes with all gates open: {sorted(unreachable)}"


# ---------------------------------------------------------------------------
# Gate semantics
# ---------------------------------------------------------------------------


def test_item_gate_blocks_without_item(graph: AreaGraph) -> None:
    """An 'item' gate returns False from gate_open when the required item is not held.

    Uses basement_key_well (kind=item, stub=False): requires 'basement_key' in
    GateContext.held_items. Tests the gate function directly rather than
    reachability, since alternative paths to reservoir_south exist via precipice.
    """
    ctx_no_key = _ctx(held_items={})
    assert gate_open(graph, "basement_key_well", ctx_no_key) is False


def test_item_gate_opens_with_item(graph: AreaGraph) -> None:
    """An 'item' gate returns True from gate_open when the required item is held."""
    ctx_with_key = _ctx(held_items={"basement_key": 1})
    assert gate_open(graph, "basement_key_well", ctx_with_key) is True


def test_puzzle_gate_always_passes(graph: AreaGraph) -> None:
    """A 'puzzle' gate always returns True regardless of context.

    The sim's standing doctrine: 'the player solves every puzzle in a room they
    enter'. Verified here against the padlock_code gate (campsite->apple_orchard),
    which is kind=puzzle and stub=False.
    """
    ctx_empty = _ctx()
    g = graph.gates["padlock_code"]
    assert g.kind == "puzzle"
    assert not g.stub
    assert gate_open(graph, "padlock_code", ctx_empty) is True


def test_unmodelled_stub_gate_always_passes(graph: AreaGraph) -> None:
    """A stub gate (stub=True) always returns True regardless of context or kind.

    Uses garage_door_breaker (kind=unmodelled, stub=True) as the canonical example.
    This is the mechanism that keeps deferred-mechanism nodes reachable.
    """
    ctx_empty = _ctx()
    g = graph.gates["garage_door_breaker"]
    assert g.kind == "unmodelled"
    assert g.stub is True
    assert gate_open(graph, "garage_door_breaker", ctx_empty) is True


def test_flag_gate_blocks_without_flag(graph: AreaGraph) -> None:
    """A 'flag' gate blocks when the flag is not set in GateContext.flags.

    Uses west_gate_unlatched (kind=flag, stub=False) — grounds->west_path requires
    the gate to have been unlatched from the inside at least once.
    """
    ctx_no_flag = _ctx(held_items={}, flags=frozenset(), rooms_entered=frozenset())
    dist = reachable(graph, "grounds", ctx_no_flag)
    assert "west_path" not in dist


def test_flag_gate_opens_with_flag(graph: AreaGraph) -> None:
    """A 'flag' gate opens when the flag is present in GateContext.flags."""
    ctx_with_flag = _ctx(flags=frozenset({"west_gate_unlatched"}))
    dist = reachable(graph, "grounds", ctx_with_flag)
    assert "west_path" in dist


def test_room_gate_blocks_without_room_entered(graph: AreaGraph) -> None:
    """A 'room' gate blocks when the required room has not been entered today.

    Uses tomb_catacombs (kind=room) — tomb->catacombs is only passable when the
    Tomb was drafted and entered that day.
    """
    ctx_no_tomb = _ctx(held_items={}, flags=frozenset(), rooms_entered=frozenset())
    dist = reachable(graph, "tomb", ctx_no_tomb)
    assert "catacombs" not in dist


def test_room_gate_opens_with_room_entered(graph: AreaGraph) -> None:
    """A 'room' gate opens when the required room id appears in rooms_entered."""
    ctx_tomb_entered = _ctx(rooms_entered=frozenset({"tomb"}))
    dist = reachable(graph, "tomb", ctx_tomb_entered)
    assert "catacombs" in dist


# ---------------------------------------------------------------------------
# West gate directionality — first visit must come via Garage
# ---------------------------------------------------------------------------


def test_west_gate_not_traversable_without_unlatch_flag(graph: AreaGraph) -> None:
    """Without west_gate_unlatched, grounds->west_path is not traversable.

    areas.md: 'The first-ever West Path visit MUST come through the Garage,
    because the west gate only unlatches from the inside.' With the flag unset,
    the only route to West Path from Grounds is blocked; the Garage->West Path
    edge uses a stub gate and is always open.
    """
    ctx_no_flag = _ctx()  # no flags, no items
    # From grounds: west_path should be unreachable (flag gate blocks)
    dist = reachable(graph, "grounds", ctx_no_flag)
    assert "west_path" not in dist

    # But from garage the stub gate passes, so West Path IS reachable
    dist_garage = reachable(graph, "garage", ctx_no_flag)
    assert "west_path" in dist_garage


# ---------------------------------------------------------------------------
# Path function
# ---------------------------------------------------------------------------


def test_path_returns_none_when_unreachable(graph: AreaGraph) -> None:
    """path() returns None when the destination is not reachable in the given context."""
    ctx_empty = _ctx()
    # Without any flags/items, mine_north is not reachable from house
    result = path(graph, "house", "mine_north", ctx_empty)
    assert result is None


def test_path_returns_tuple_including_endpoints(graph: AreaGraph) -> None:
    """path() returns a tuple with origin as first element and dest as last."""
    ctx = _all_open_ctx()
    p = path(graph, "house", "grounds", ctx)
    assert p is not None
    assert p[0] == "house"
    assert p[-1] == "grounds"


def test_path_same_origin_dest(graph: AreaGraph) -> None:
    """path() from a node to itself returns a 1-tuple containing just that node."""
    ctx = _ctx()
    p = path(graph, "grounds", "grounds", ctx)
    assert p == ("grounds",)


def test_path_length_matches_bfs_distance(graph: AreaGraph) -> None:
    """len(path()) - 1 equals the BFS step count returned by reachable()."""
    ctx = _all_open_ctx()
    dist = reachable(graph, "house", ctx)
    p = path(graph, "house", "west_path", ctx)
    assert p is not None
    assert len(p) - 1 == dist["west_path"]


# ---------------------------------------------------------------------------
# B: three_microchips gate requires exactly 3 microchips
# ---------------------------------------------------------------------------


def test_two_microchips_do_not_open_orindian_ruins(graph: AreaGraph) -> None:
    """Holding 2 microchips is insufficient for the three_microchips gate (count=3).

    The gate requires all 3 placed in the pedestal; 2 must be rejected. This pins
    down the count field semantics: the gate checks the total across item_ids >= count.
    """
    ctx_two = _ctx(held_items={"microchip": 2})
    assert gate_open(graph, "three_microchips", ctx_two) is False


def test_three_microchips_open_orindian_ruins(graph: AreaGraph) -> None:
    """Holding exactly 3 microchips satisfies the three_microchips gate (count=3).

    Confirms the boundary condition: count=3 means 3 is the minimum that opens the gate.
    """
    ctx_three = _ctx(held_items={"microchip": 3})
    assert gate_open(graph, "three_microchips", ctx_three) is True


# ---------------------------------------------------------------------------
# C: ignition gates accept any ignition tool (torch OR burning_glass)
# ---------------------------------------------------------------------------


def test_burning_glass_opens_crate_tunnel_gate(graph: AreaGraph) -> None:
    """A Burning Glass alone satisfies the ignition_torches_crate gate.

    ignition_torches_crate lists both torch and burning_glass in item_ids (count=1).
    Previously it hardcoded item_id='torch', wrongly blocking Burning Glass holders.
    """
    ctx_bg = _ctx(held_items={"burning_glass": 1})
    assert gate_open(graph, "ignition_torches_crate", ctx_bg) is True


def test_torch_still_opens_crate_tunnel_gate(graph: AreaGraph) -> None:
    """A Torch alone also satisfies the ignition_torches_crate gate.

    Confirms the any-of semantics: torch remains valid after switching to item_ids list.
    """
    ctx_torch = _ctx(held_items={"torch": 1})
    assert gate_open(graph, "ignition_torches_crate", ctx_torch) is True


def test_burning_glass_opens_candlestick_stairway_gate(graph: AreaGraph) -> None:
    """A Burning Glass alone satisfies the candlestick_stairway gate (mine_south->precipice).

    candlestick_stairway lists both torch and burning_glass in item_ids (count=1).
    Previously it hardcoded item_id='torch', wrongly blocking Burning Glass holders.
    """
    ctx_bg = _ctx(held_items={"burning_glass": 1})
    assert gate_open(graph, "candlestick_stairway", ctx_bg) is True


def test_no_ignition_tool_blocks_crate_tunnel(graph: AreaGraph) -> None:
    """Without any ignition tool, the ignition_torches_crate gate is closed."""
    ctx_empty = _ctx(held_items={})
    assert gate_open(graph, "ignition_torches_crate", ctx_empty) is False


# ---------------------------------------------------------------------------
# E: mine_south_visited single flag unlocks both mine_north and underpass edges
# ---------------------------------------------------------------------------


def test_mine_south_visited_flag_unlocks_mine_north_edge(graph: AreaGraph) -> None:
    """The mine_south_visited flag makes reservoir_north->mine_north traversable.

    Both the mine-cart move and gear positioning are collapsed into this single flag
    (spec: 'the sim collapses that to a single South visited flag'). Confirms the
    reservoir_north->mine_north edge uses mine_south_visited, not a separate gate.
    """
    # Without the flag, mine_north is not reachable from reservoir_north
    ctx_no_flag = _ctx(held_items={"basement_key": 1})
    dist_no = reachable(graph, "reservoir_north", ctx_no_flag)
    assert "mine_north" not in dist_no

    # With the flag, mine_north becomes reachable in 1 step
    ctx_with_flag = _ctx(held_items={"basement_key": 1}, flags=frozenset({"mine_south_visited"}))
    dist_yes = reachable(graph, "reservoir_north", ctx_with_flag)
    assert "mine_north" in dist_yes
    assert dist_yes["mine_north"] == 1


def test_mine_south_visited_flag_unlocks_underpass_edge(graph: AreaGraph) -> None:
    """The mine_south_visited flag also makes rotating_gear->underpass traversable.

    The same single flag gates both mine_north access and the underpass, as per the
    spec consolidation. Confirms no separate gear_positioned gate exists.
    """
    # Without the flag, underpass is not reachable from rotating_gear
    ctx_no_flag = _ctx()
    dist_no = reachable(graph, "rotating_gear", ctx_no_flag)
    assert "underpass" not in dist_no

    # With the flag, underpass becomes reachable in 1 step
    ctx_with_flag = _ctx(flags=frozenset({"mine_south_visited"}))
    dist_yes = reachable(graph, "rotating_gear", ctx_with_flag)
    assert "underpass" in dist_yes
    assert dist_yes["underpass"] == 1


def test_single_flag_unlocks_both_mine_north_and_underpass(graph: AreaGraph) -> None:
    """One mine_south_visited flag simultaneously unlocks both downstream edges.

    This verifies the collapsed-flag design: setting mine_south_visited once opens
    both reservoir_north->mine_north AND rotating_gear->underpass, matching the spec.
    """
    ctx = _ctx(
        held_items={"basement_key": 1},
        flags=frozenset({"mine_south_visited", "west_gate_unlatched"}),
    )
    # From reservoir_north: mine_north reachable
    dist_rn = reachable(graph, "reservoir_north", ctx)
    assert "mine_north" in dist_rn

    # From rotating_gear: underpass reachable
    dist_rg = reachable(graph, "rotating_gear", ctx)
    assert "underpass" in dist_rg
