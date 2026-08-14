"""Pure area-graph library: nodes, edges, gates, BFS traversal.

Every edge costs exactly 1 step (owner-confirmed).  See docs/areas.md for the
full specification and docs/areas.dot for the co-authoritative edge set.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Mapping

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Area:
    id: str           # snake_case node identifier matching areas.json
    name: str         # human-readable display name
    kind: str         # "area" (graph node) or "anchor" (on-grid/drafted room)
    surface: bool | None  # True = surface area; False = underground; None for anchors
    # True once this area's contents are modelled and travelling there can pay off.
    # Only modelled areas are offered as travel actions; the rest are still routed
    # THROUGH by the pathfinder.  Flipping this to True is how a later PR switches an
    # area on, and it is mask-only — the action space does not change, so no retrain.
    modelled: bool


@dataclass(frozen=True, slots=True)
class Gate:
    id: str              # snake_case gate identifier, referenced in AreaEdge.requires
    kind: str            # "item" | "flag" | "room" | "puzzle" | "unmodelled"
    permanence: str      # "permanent" | "daily" | "none"
    stub: bool           # True when the mechanism is deferred; passes unconditionally
    detail: str          # human-readable explanation of the real gate condition
    item_ids: tuple[str, ...]  # item ids (ANY of these count); non-empty only for kind="item"
    count: int           # how many items (summed across item_ids) the player must hold; default 1
    # Flag whose presence contributes 1 to the item total: an in-place copy of
    # the item the player does not have to carry. None on every other gate.
    counts_flag: str | None
    room_id: str | None  # room that must have been entered today; non-None only for kind="room"
    # PR that replaces this placeholder with the real gate. Non-None on every
    # kind="unmodelled" gate, whether it defaults open (stub=True, passes) or closed
    # (default_closed=True in the data, never passes) -- both are deferred work.
    retire_in: str | None


@dataclass(frozen=True, slots=True)
class AreaEdge:
    from_id: str              # source node id
    to_id: str                # destination node id
    requires: tuple[str, ...]  # gate tag ids (ALL must hold — AND semantics)


@dataclass(frozen=True)
class AreaGraph:
    nodes: dict[str, Area]           # node id -> Area
    gates: dict[str, Gate]           # gate id -> Gate
    edges: tuple[AreaEdge, ...]      # all directed edges
    # adjacency: node id -> list of (neighbour id, gate ids tuple)
    adjacency: dict[str, list[tuple[str, tuple[str, ...]]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GateContext:
    """Everything gate_open needs to evaluate a gate.

    PR2 widens this with outer_room_id; flags and held items were added in PR1.
    """
    held_items: Mapping[str, int]    # special-item id -> count held by the player right now
    flags: frozenset[str]            # persistent boolean flags set during this run
    rooms_entered: frozenset[str]    # room ids entered today (e.g. "tomb" for catacombs gate)
    # room id drawn as today's outer room; None until an outer-room draft happens
    outer_room_id: str | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def stub_gates(graph: AreaGraph) -> dict[str, str]:
    """Return {gate id: retiring PR} for every gate still standing in for a real mechanism.

    Derived from the graph rather than hand-maintained, so it cannot drift from
    areas.json.  A stub gate passes unconditionally, so anything measured while
    one is open is an UPPER BOUND on what a real player could reach.
    """
    return {g.id: (g.retire_in or "unassigned") for g in graph.gates.values() if g.stub}


def load_areas(raw: dict) -> AreaGraph:
    """Parse a raw areas.json dict into an immutable AreaGraph.

    Called by Registry.load(); ``raw`` is the result of json.loads on areas.json.
    """
    nodes: dict[str, Area] = {}
    for n in raw["nodes"]:
        nodes[n["id"]] = Area(
            id=n["id"],
            name=n["name"],
            kind=n["kind"],
            surface=n.get("surface", None),
            modelled=n["modelled"],
        )

    gates: dict[str, Gate] = {}
    for g in raw["gates"]:
        gates[g["id"]] = Gate(
            id=g["id"],
            kind=g["kind"],
            permanence=g["permanence"],
            stub=g["stub"],
            detail=g["detail"],
            item_ids=tuple(g.get("item_ids", [])),
            count=g.get("count", 1),
            counts_flag=g.get("counts_flag", None),
            room_id=g.get("room_id", None),
            retire_in=g.get("retire_in", None),
        )

    edges_list: list[AreaEdge] = []
    adjacency: dict[str, list[tuple[str, tuple[str, ...]]]] = {nid: [] for nid in nodes}
    for e in raw["edges"]:
        edge = AreaEdge(
            from_id=e["from"],
            to_id=e["to"],
            requires=tuple(e.get("requires", [])),
        )
        edges_list.append(edge)
        adjacency[e["from"]].append((e["to"], edge.requires))

    return AreaGraph(
        nodes=nodes,
        gates=gates,
        edges=tuple(edges_list),
        adjacency=adjacency,
    )


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def gate_open(
    graph: AreaGraph, gate_id: str, ctx: GateContext, *, dest: str | None = None
) -> bool:
    """Return True if the named gate is passable in the given context.

    Dispatches on Gate.kind using match/case (repo convention for 4+ arm dispatch).
    Stub gates always pass — they represent deferred mechanisms; see stub_gates().

    dest -- the destination node id of the edge being tested; required only for
            kind="outer_room" gates (passed by _edge_passable from the adjacency entry).
    """
    gate = graph.gates[gate_id]

    if gate.stub:
        return True

    match gate.kind:
        case "item":
            # item gate: player must hold at least gate.count items in total across
            # gate.item_ids (ANY of the listed ids contribute to the count), plus 1
            # more if counts_flag is set and present -- an in-place copy of the item
            # that satisfies the gate without being carried in inventory.
            total = sum(ctx.held_items.get(iid, 0) for iid in gate.item_ids)
            if gate.counts_flag is not None and gate.counts_flag in ctx.flags:
                total += 1
            return total >= gate.count

        case "flag":
            # flag gate: a persistent engine boolean must be set
            return gate_id in ctx.flags

        case "room":
            # room gate: a specific room was drafted/entered today
            if gate.room_id is None:
                return False
            return gate.room_id in ctx.rooms_entered

        case "puzzle":
            # puzzle gate: sim doctrine — player solves every puzzle they enter
            return True

        case "outer_room":
            # outer_room gate: the edge's destination must be the room drawn as today's
            # outer room.  dest is the to_id of the edge; outer_room_id is from context.
            return dest is not None and ctx.outer_room_id is not None and dest == ctx.outer_room_id

        case "unmodelled":
            # unmodelled gate: mechanism deferred; stub=False shouldn't occur
            # (stub=True already returns True above), but be explicit.
            return False

        case _:
            return False


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


def _edge_passable(
    graph: AreaGraph, requires: tuple[str, ...], ctx: GateContext, dest: str
) -> bool:
    """Return True if all gates on this edge are open.

    dest -- the destination node id; forwarded to gate_open for outer_room gates.
    """
    return all(gate_open(graph, gid, ctx, dest=dest) for gid in requires)


def reachable(graph: AreaGraph, origin: str, ctx: GateContext) -> dict[str, int]:
    """BFS from origin; return {node_id: step_distance} for every reachable node.

    Every edge costs exactly 1 step (owner-confirmed).  Only nodes reachable
    with all required gates open are included.  The origin itself is at distance 0.
    """
    dist: dict[str, int] = {origin: 0}
    queue: deque[str] = deque([origin])
    while queue:
        current = queue.popleft()
        for neighbour, requires in graph.adjacency.get(current, []):
            if neighbour not in dist and _edge_passable(graph, requires, ctx, neighbour):
                dist[neighbour] = dist[current] + 1
                queue.append(neighbour)
    return dist


def path(graph: AreaGraph, origin: str, dest: str, ctx: GateContext) -> tuple[str, ...] | None:
    """Return the shortest path from origin to dest, or None if unreachable.

    The returned tuple includes both origin and dest as the first and last elements.
    Every edge costs 1 step.
    """
    if origin == dest:
        return (origin,)
    parent: dict[str, str | None] = {origin: None}
    queue: deque[str] = deque([origin])
    while queue:
        current = queue.popleft()
        for neighbour, requires in graph.adjacency.get(current, []):
            if neighbour not in parent and _edge_passable(graph, requires, ctx, neighbour):
                parent[neighbour] = current
                if neighbour == dest:
                    # Reconstruct path from dest back to origin.
                    steps: list[str] = []
                    node: str | None = dest
                    while node is not None:
                        steps.append(node)
                        node = parent[node]
                    return tuple(reversed(steps))
                queue.append(neighbour)
    return None
