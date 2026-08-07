"""Tests for the areas graph library (engine/areas.py + data/areas.json).

All tests operate on observable traversal behaviour, not on data-file contents.
No test asserts a literal distance or asserts that a JSON record has a specific
value — those are schema/range checks and belong in tools/validate_data.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blueprince_sim.engine.areas import (
    AreaGraph,
    GateContext,
    gate_open,
    load_areas,
    path,
    reachable,
)
from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.model import Registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "blueprince_sim" / "data"


@pytest.fixture(scope="module")
def graph() -> AreaGraph:
    """Load the committed areas.json once for all tests in this module."""
    raw = json.loads((DATA_DIR / "areas.json").read_text())
    return load_areas(raw)


@pytest.fixture(scope="module")
def outer_room_ids() -> list[str]:
    """Derive the list of outer-pool room ids from the live rooms registry.

    Using the registry (not a hardcoded list) ensures this fixture automatically
    picks up any new outer rooms added to rooms.json without changing test code.
    """
    registry = Registry.load()
    return [rm.id for rm in registry.rooms if rm.pool == "outer"]


def _ctx(
    held_items: dict[str, int] | None = None,
    flags: frozenset[str] = frozenset(),
    rooms_entered: frozenset[str] = frozenset(),
    outer_room_id: str | None = None,
) -> GateContext:
    """Convenience constructor for GateContext."""
    return GateContext(
        held_items=held_items if held_items is not None else {},
        flags=flags,
        rooms_entered=rooms_entered,
        outer_room_id=outer_room_id,
    )


def _all_open_ctx(outer_room_id: str | None = "tomb") -> GateContext:
    """A context with every item, flag, and room that any gate in the graph checks.

    outer_room_id controls which outer-room anchor is reachable from west_path;
    defaults to "tomb" so the existing 1-step distance tests remain valid.
    garage_door_breaker is now a real flag gate (not a stub) so it must be included.
    sealed_entrance_broken is a real flag gate — include it too.
    antechamber_north_door_open is a flag gate set when the north door lever is pulled.
    """
    return GateContext(
        held_items={
            "microchip": 3,
            "power_hammer": 1,
            "torch": 1,
            "basement_key": 1,
            "sanctum_key": 1,
        },
        flags=frozenset({
            "west_gate_unlatched",
            "mine_south_visited",
            "garage_door_breaker",
            "sealed_entrance_broken",
            "antechamber_north_door_open",
        }),
        rooms_entered=frozenset({"tomb"}),
        outer_room_id=outer_room_id,
    )


# ---------------------------------------------------------------------------
# 1-step rule — observable step deduction (the main evidence the graph is right)
# ---------------------------------------------------------------------------


def test_1step_rule_entrance_hall_to_doorstep() -> None:
    """Opening the outer draft from the Entrance Hall deducts exactly 2 steps.

    house->grounds->west_path is 2 edges in the graph; with the player already
    at the Entrance Hall (0 walk), the observable step budget must drop by 2.
    This was independently play-verified and is the primary evidence the
    1-step-per-edge rule and node choices are correct.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    g.open_outer_draft()
    assert g.state.steps == 8  # 10 - 2


def _game_standing_in_garage(breaker_on: bool) -> Game:
    """A game with the player standing in a placed Garage, breaker optionally on.

    The Utility Closet is placed away from the Garage so that ``breaker_on``
    is the only thing that differs between the two arms of the test below.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g._place_room(g.registry.by_id["garage"], 1, E | W)
    g._place_room(g.registry.by_id["utility_closet"], 7, N | S)
    if breaker_on:
        g.state.entered[g._utility_closet_cell()] = True
    g.state.pos = g._garage_cell()
    g.state.entered[g._garage_cell()] = True
    g.state.steps = 10
    return g


def test_1step_rule_garage_to_doorstep() -> None:
    """Reaching the doorstep from inside the Garage costs exactly 1 step.

    garage->west_path is a single edge, so with no grid walk to pay the budget
    must drop by exactly 1 -- one of the three play-verified constants the graph
    has to reproduce rather than contradict.
    """
    g = _game_standing_in_garage(breaker_on=True)
    g.open_outer_draft()
    assert g.state.steps == 9  # 10 - 1, and no walk


def test_garage_route_not_taken_when_breaker_off() -> None:
    """With the breaker off the Garage route is closed, so the pricier house route is used.

    The garage_door_breaker gate is real, so the only way out is back through the
    Entrance Hall: 1 step to walk there plus 2 area hops, versus 1 step via the
    Garage. Pins that the gate actually costs the player something.
    """
    g = _game_standing_in_garage(breaker_on=False)
    g.open_outer_draft()
    assert g.state.steps == 7  # 10 - (1 walk to the Entrance Hall + 2 area hops)


def test_1step_rule_doorstep_to_outer_room() -> None:
    """Travelling to the outer room from the doorstep deducts exactly 1 step.

    west_path->outer_room is 1 edge in the graph; after arriving at west_path
    and choosing an outer room, travelling to it must cost exactly 1 step.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    steps_before = g.state.steps
    outer_room = next(r for r in g.outer_rooms if r.id in g.placed_ids)
    g.travel_to(outer_room.id)
    assert g.state.steps == steps_before - 1


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


def test_no_dead_nodes_all_items_and_flags(
    graph: AreaGraph, outer_room_ids: list[str]
) -> None:
    """Every node is reachable from a grid anchor across all valid outer-room contexts.

    Outer-room anchor nodes are only reachable one at a time (the outer_room gate is
    destination-specific), so we cannot reach all 8 in a single BFS. Instead: each
    outer-room anchor must be reachable when it is the drawn room; every non-outer
    node must be reachable with tomb as the drawn room (tomb is also required for the
    catacombs gate). A node unreachable in any of these contexts is a design error.

    The BFS is seeded from BOTH grid anchors the player can stand on, 'house' and
    'antechamber'. The antechamber deliberately has no area edge to the house:
    reaching rank 9 center is a GRID walk through a lever-opened door, and giving it
    one would let travel_to() hop there for ~0 steps straight past the seal. So it is
    a BFS root here rather than a reachable destination.
    """
    outer_ids = set(outer_room_ids)

    # Compute reachable set with tomb drawn (covers all non-outer-room nodes and tomb itself)
    ctx_tomb = _all_open_ctx(outer_room_id="tomb")
    dist_tomb = dict(reachable(graph, "house", ctx_tomb))
    dist_tomb.update(reachable(graph, "antechamber", ctx_tomb))

    # Every non-outer-room node must be reachable via the tomb context
    non_outer_nodes = {nid for nid in graph.nodes if nid not in outer_ids}
    unreachable_non_outer = non_outer_nodes - set(dist_tomb)
    assert unreachable_non_outer == set(), (
        f"Non-outer nodes unreachable with all gates open: {sorted(unreachable_non_outer)}"
    )

    # Each outer-room anchor must be reachable when it is the drawn outer room
    for oid in outer_ids:
        ctx_oid = _all_open_ctx(outer_room_id=oid)
        dist_oid = reachable(graph, "house", ctx_oid)
        assert oid in dist_oid, (
            f"Outer room {oid!r} not reachable from 'house' when it is the drawn outer room"
        )


# ---------------------------------------------------------------------------
# Gate semantics
# ---------------------------------------------------------------------------


def test_item_gate_blocks_without_item(graph: AreaGraph) -> None:
    """An 'item' gate returns False from gate_open when the required item is not held.

    Uses basement_key_well (kind=item, stub=False): requires 'basement_key' in
    GateContext.held_items. Tests the gate function directly rather than
    reachability, so it pins the gate itself regardless of what else routes to
    reservoir_south.
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

    Uses foundation_elevator_down (kind=unmodelled, stub=True) as the canonical example.
    This is the mechanism that keeps deferred-mechanism nodes reachable.
    (garage_door_breaker was retired as a stub in PR2 — it is now a real flag gate.)
    """
    ctx_empty = _ctx()
    g = graph.gates["foundation_elevator_down"]
    assert g.kind == "unmodelled"
    assert g.stub is True
    assert gate_open(graph, "foundation_elevator_down", ctx_empty) is True


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
    the Grounds -> West Path edge is blocked. The Garage -> West Path route requires
    the garage_door_breaker flag (real gate since PR2), so both routes are blocked
    when neither flag is set.
    """
    ctx_no_flag = _ctx()  # no flags, no items
    # From grounds: west_path unreachable (west_gate_unlatched blocks)
    dist = reachable(graph, "grounds", ctx_no_flag)
    assert "west_path" not in dist

    # From garage: west_path also unreachable without garage_door_breaker flag
    dist_garage = reachable(graph, "garage", ctx_no_flag)
    assert "west_path" not in dist_garage

    # With garage_door_breaker flag set, garage -> west_path becomes traversable
    ctx_breaker = _ctx(flags=frozenset({"garage_door_breaker"}))
    dist_breaker = reachable(graph, "garage", ctx_breaker)
    assert "west_path" in dist_breaker


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


# ---------------------------------------------------------------------------
# F: outer_room gate — destination-specific daily access (Task 2)
# ---------------------------------------------------------------------------


def test_each_outer_room_reachable_when_drawn(
    graph: AreaGraph, outer_room_ids: list[str]
) -> None:
    """Every outer room is reachable from west_path when it is the drawn outer room.

    The outer_room gate is destination-specific: gate_open returns True only when
    the edge's to_id equals GateContext.outer_room_id. This parametrises over the
    full outer pool from the rooms registry, so new outer rooms are automatically covered.
    """
    for oid in outer_room_ids:
        ctx = _ctx(outer_room_id=oid)
        dist = reachable(graph, "west_path", ctx)
        assert oid in dist, (
            f"Outer room {oid!r} not reachable from west_path when it is the drawn room"
        )


def test_outer_room_not_reachable_when_different_room_drawn(
    graph: AreaGraph, outer_room_ids: list[str]
) -> None:
    """An outer room is NOT reachable from west_path when a different room is drawn.

    This is the behaviour that would have been broken by leaving outer_room_drawn as a stub.
    The gate is destination-specific, so drawing room A must not open the door to room B.
    """
    for oid in outer_room_ids:
        # Pick a different outer room id to draw
        other = next(other for other in outer_room_ids if other != oid)
        ctx = _ctx(outer_room_id=other)
        dist = reachable(graph, "west_path", ctx)
        assert oid not in dist, (
            f"Outer room {oid!r} was reachable from west_path when {other!r} was drawn"
        )


def test_no_outer_room_reachable_without_outer_room_id(
    graph: AreaGraph, outer_room_ids: list[str]
) -> None:
    """With outer_room_id=None, no outer-room anchor is reachable from west_path.

    When no outer room has been drafted today (outer_room_id is None), the
    outer_room gate must block every west_path -> outer_room edge.
    """
    ctx = _ctx(outer_room_id=None)
    dist = reachable(graph, "west_path", ctx)
    for oid in outer_room_ids:
        assert oid not in dist, (
            f"Outer room {oid!r} was reachable from west_path with outer_room_id=None"
        )


def test_outer_room_return_always_passable(
    graph: AreaGraph, outer_room_ids: list[str]
) -> None:
    """The return edge outer_room -> west_path is passable regardless of outer_room_id.

    Leaving an outer room back to the doorstep has no gate; you can always walk out.
    This holds even when outer_room_id is None (the player is already inside the room).
    """
    ctx_none = _ctx(outer_room_id=None)
    for oid in outer_room_ids:
        dist = reachable(graph, oid, ctx_none)
        assert "west_path" in dist, (
            f"west_path not reachable from {oid!r} (return edge should be ungated)"
        )


# ---------------------------------------------------------------------------
# G: garage_door_breaker — now a real flag gate (Task 3)
# ---------------------------------------------------------------------------


def test_garage_to_west_path_blocked_without_breaker_flag(graph: AreaGraph) -> None:
    """garage->west_path is blocked when the garage_door_breaker flag is not set.

    garage_door_breaker is now a real flag gate (not a stub), so the Utility Closet
    must have been placed and entered for the garage route to be open.
    """
    ctx = _ctx()  # no flags
    dist = reachable(graph, "garage", ctx)
    assert "west_path" not in dist


def test_garage_to_west_path_open_with_breaker_flag(graph: AreaGraph) -> None:
    """garage->west_path is open in 1 step when the garage_door_breaker flag is set.

    Once the breaker is on (Utility Closet placed and entered), the garage door
    opens and the Garage becomes a 1-step route to the West Path doorstep.
    """
    ctx = _ctx(flags=frozenset({"garage_door_breaker"}))
    dist = reachable(graph, "garage", ctx)
    assert "west_path" in dist
    assert dist["west_path"] == 1


# ---------------------------------------------------------------------------
# H: state.area round-trip — game-level integration
# ---------------------------------------------------------------------------


def test_area_round_trip_full_outer_room_lifecycle() -> None:
    """state.area tracks the full outer-room lifecycle: None -> west_path -> room id -> None.

    After open_outer_draft, area is "west_path".
    After travel_to(outer_room.id), area is the drafted room's id.
    After travel_to("house"), area is None and pos is the Entrance Hall cell.
    """
    from blueprince_sim.engine.grid import ENTRANCE_CELL
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    assert g.state.area is None  # starts on the grid

    g.open_outer_draft()
    assert g.state.area == "west_path"

    g.choose(0)
    assert g.state.area == "west_path"  # still at doorstep after choosing
    outer_room_id = next(r.id for r in g.outer_rooms if r.id in g.placed_ids)

    g.travel_to(outer_room_id)
    assert g.state.area == outer_room_id  # now inside the outer room

    g.travel_to("house")
    assert g.state.area is None  # back on the grid
    assert g.state.pos == ENTRANCE_CELL


