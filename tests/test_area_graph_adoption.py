"""Tests for the area-graph action/observation adoption (Task 2-5, PR2).

These tests pin the observable behavior introduced by the TRAVEL_BASE action
family and the player_area observation key. They operate through the public
Game / action_mask / encode API; never against raw data/*.json values.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import ENTRANCE_CELL
from blueprince_sim.env import actions as A
from blueprince_sim.env import obs as O
from blueprince_sim.env.actions import _build_area_node_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_with_outer_room_unlocked(seed: int = 9) -> Game:
    """Return a fresh game with west_gate_unlatched and enough steps."""
    cfg = GameConfig(west_gate_unlatched=True, starting_steps=50)
    return Game(cfg, seed=seed)


def _travel_idx(game: Game, node_id: str) -> int:
    """Return the flat action index for travel to node_id."""
    node_ids = _build_area_node_ids(game.registry)
    return A.TRAVEL_BASE + node_ids.index(node_id)


# ---------------------------------------------------------------------------
# 1. Reachability masking
# ---------------------------------------------------------------------------

def test_unreachable_area_masked_out():
    """An area node unreachable from the current position is masked out.

    "west_path" via Grounds requires the west_gate_unlatched config flag.
    With west_gate_unlatched=False and no Garage placed, "west_path" is
    unreachable, and its travel action must be masked False.
    """
    cfg_locked = GameConfig(west_gate_unlatched=False)
    g = Game(cfg_locked, seed=0)
    mask = A.action_mask(g)
    node_ids = _build_area_node_ids(g.registry)
    west_path_action = A.TRAVEL_BASE + node_ids.index("west_path")
    # Confirm unreachable
    assert g.area_route_cost("west_path") is None, "west_path must be unreachable without gate"
    assert not mask[west_path_action], "west_path must be masked when unreachable"


def test_reachable_area_not_masked():
    """An affordable reachable area destination is not masked out.

    With west_gate_unlatched=True and enough steps, west_path is reachable
    from the grid and must appear as a legal travel action.
    """
    g = _make_game_with_outer_room_unlocked()
    mask = A.action_mask(g)
    west_path_action = _travel_idx(g, "west_path")
    assert mask[west_path_action], "west_path must be legal when gate open and steps > cost"


# ---------------------------------------------------------------------------
# 2. Travel to house returns player to the grid
# ---------------------------------------------------------------------------

def test_travel_house_from_outer_room_returns_to_grid():
    """Travelling to 'house' from inside the outer room sets area=None and pos=ENTRANCE_CELL.

    This pins the full lifecycle: on-grid -> west_path -> outer_room -> house.
    After arriving at house, player_pos is ENTRANCE_CELL and area is cleared.
    """
    g = _make_game_with_outer_room_unlocked()
    g.open_outer_draft()
    g.choose(0)
    outer_room = next(r for r in g.outer_rooms if r.id in g.placed_ids)
    g.travel_to(outer_room.id)
    assert g.state.area == outer_room.id

    g.travel_to("house")
    assert g.state.area is None          # back on the grid
    assert g.state.pos == ENTRANCE_CELL  # returned to Entrance Hall


# ---------------------------------------------------------------------------
# 3. Self-travel masked out
# ---------------------------------------------------------------------------

def test_self_travel_masked_out_on_grid():
    """Travelling to a grid anchor that has zero route cost is masked out as self-travel.

    'house' maps to ENTRANCE_CELL; starting there its route cost is 0. A zero-
    cost route means the player is already at the destination, so it must be
    masked False regardless of the step budget.
    """
    g = _make_game_with_outer_room_unlocked()
    assert g.state.area is None  # starts on the grid
    result = g.area_route_cost("house")
    assert result is not None and result[0] == 0, "house must have zero cost from Entrance Hall"
    mask = A.action_mask(g)
    house_action = _travel_idx(g, "house")
    assert not mask[house_action], "zero-cost travel to 'house' is self-travel; must be masked"


def test_self_travel_masked_out_off_grid():
    """Travelling to the current off-grid node is masked out.

    After open_outer_draft the player is at 'west_path'. Travelling to
    'west_path' again must be masked off as self-travel.
    """
    g = _make_game_with_outer_room_unlocked()
    g.open_outer_draft()
    assert g.state.area == "west_path"
    mask = A.action_mask(g)
    wp_action = _travel_idx(g, "west_path")
    assert not mask[wp_action], "self-travel to current area node must be masked"


# ---------------------------------------------------------------------------
# 4. Travel is legal both on-grid and off-grid
# ---------------------------------------------------------------------------

def test_travel_legal_on_grid():
    """Travel to a reachable area is legal while the player is on the grid.

    With west_gate_unlatched=True, west_path is reachable from the grid. The
    mask must permit travel to it even before going off-grid.
    """
    g = _make_game_with_outer_room_unlocked()
    assert not g.off_grid
    mask = A.action_mask(g)
    wp_action = _travel_idx(g, "west_path")
    assert mask[wp_action], "travel to west_path must be legal from the grid"


def test_travel_legal_off_grid():
    """Travel to 'house' is legal while off-grid after choosing an outer room.

    open_outer_draft enters DRAFTING; choosing resolves back to NAVIGATE with
    area=='west_path'. From there, 'house' is affordable and must be legal.
    """
    g = _make_game_with_outer_room_unlocked()
    g.open_outer_draft()
    g.choose(0)  # resolve draft -> NAVIGATE, still at west_path
    assert g.off_grid
    assert g.phase.name == "NAVIGATE"
    mask = A.action_mask(g)
    house_action = _travel_idx(g, "house")
    assert mask[house_action], "travel to house must be legal from off-grid (west_path)"


# ---------------------------------------------------------------------------
# 5. Observation round-trip
# ---------------------------------------------------------------------------

def test_observation_player_area_on_grid():
    """player_area is 0 when the player is on the grid (state.area is None)."""
    g = _make_game_with_outer_room_unlocked()
    assert g.state.area is None
    enc = O.encode(g)
    assert enc["player_area"] == 0, "player_area must be 0 when on-grid"


def test_observation_player_area_off_grid():
    """player_area is 1 + area_index when off-grid; index matches TRAVEL_BASE ordering.

    After open_outer_draft, area is 'west_path'. The encoded player_area must
    be 1 + the sorted position of 'west_path' in the node list.
    """
    g = _make_game_with_outer_room_unlocked()
    g.open_outer_draft()
    assert g.state.area == "west_path"
    node_ids = _build_area_node_ids(g.registry)
    expected_idx = node_ids.index("west_path")
    enc = O.encode(g)
    assert enc["player_area"] == 1 + expected_idx, (
        f"player_area should be 1+{expected_idx} for west_path, got {enc['player_area']}")


def test_observation_progress_shape():
    """progress has shape (3,) with deepest_rank, ante_dist, and ante_connected."""
    g = _make_game_with_outer_room_unlocked()
    enc = O.encode(g)
    shape = enc["progress"].shape
    assert shape == (3,), f"progress should have shape (3,), got {shape}"


def test_observation_player_area_encoding_consistent_with_travel():
    """The player_area encoding index matches the TRAVEL_BASE ordering.

    Travel to node X uses TRAVEL_BASE + node_ids.index(X). If the player is at
    node X, player_area == 1 + node_ids.index(X). Both use the same sorted list.
    """
    g = _make_game_with_outer_room_unlocked()
    # travel to grounds (if reachable) and verify player_area reflects it
    node_ids = _build_area_node_ids(g.registry)
    # Use west_path as the observable off-grid node
    g.open_outer_draft()
    assert g.state.area == "west_path"
    wp_idx = node_ids.index("west_path")
    travel_action = A.TRAVEL_BASE + wp_idx
    enc = O.encode(g)
    assert enc["player_area"] == 1 + wp_idx
    # Verify the action index it would use to leave matches
    assert travel_action == _travel_idx(g, "west_path")


# ---------------------------------------------------------------------------
# 6. Affordability gate
# ---------------------------------------------------------------------------

def test_unaffordable_travel_masked_out():
    """With a step budget below the route cost, the travel action is masked out.

    west_path costs 3 steps from the grid (house->grounds->west_path).
    With exactly 3 steps the player cannot arrive with a step to spare, so
    the travel action must be masked False.
    """
    cfg = GameConfig(west_gate_unlatched=True, starting_steps=3)
    g = Game(cfg, seed=0)
    # Route cost to west_path from EH should be >= 3; with steps == 3 the
    # strict inequality (steps > cost) should fail for west_path.
    result = g.area_route_cost("west_path")
    if result is None:
        pytest.skip("west_path not reachable in this config")
    cost, _ = result
    # Force steps to exactly equal the cost so the strict check fails.
    g.state.steps = cost
    mask = A.action_mask(g)
    wp_action = _travel_idx(g, "west_path")
    assert not mask[wp_action], (
        f"travel to west_path must be masked when steps({cost}) == cost({cost})")


def test_affordable_travel_enabled():
    """With one more step than the route cost, the travel action is legal.

    With steps == cost + 1, the strict affordability check (steps > cost) passes
    and the action must be unmasked.
    """
    cfg = GameConfig(west_gate_unlatched=True, starting_steps=50)
    g = Game(cfg, seed=0)
    result = g.area_route_cost("west_path")
    if result is None:
        pytest.skip("west_path not reachable in this config")
    cost, _ = result
    g.state.steps = cost + 1
    mask = A.action_mask(g)
    wp_action = _travel_idx(g, "west_path")
    assert mask[wp_action], (
        f"travel to west_path must be legal when steps({cost+1}) > cost({cost})")


# ---------------------------------------------------------------------------
# 7. Unmodelled areas are routed through, never offered
# ---------------------------------------------------------------------------

def test_unmodelled_areas_are_never_offered_as_travel_destinations() -> None:
    """No travel action is ever legal for an area whose contents are not modelled.

    Those areas hold nothing to collect, so offering them is a pure step sink:
    measured against an unmasked build, a random policy spent 80% of its steps
    wandering them. They stay in the graph and the pathfinder still routes
    THROUGH them; they are simply not advertised as destinations.
    """
    game = _make_game_with_outer_room_unlocked()
    nodes = game.registry.area_graph.nodes
    unmodelled = [nid for nid, area in nodes.items() if not area.modelled]
    assert unmodelled, "fixture is meaningless if every area is modelled"

    mask = A.action_mask(game)
    for node_id in unmodelled:
        assert not mask[_travel_idx(game, node_id)], (
            f"travel to unmodelled area {node_id!r} must never be offered"
        )


def test_a_modelled_area_is_still_offered() -> None:
    """At least one modelled area is offered, so the mask is not vacuously empty.

    Guards the test above: masking every travel action would satisfy it while
    breaking the feature outright.
    """
    game = _make_game_with_outer_room_unlocked()
    mask = A.action_mask(game)
    offered = [
        nid for nid in game.registry.area_graph.nodes
        if mask[_travel_idx(game, nid)]
    ]
    assert offered, "no travel destination offered at all — the mask is broken"
    assert all(game.registry.area_graph.nodes[nid].modelled for nid in offered)
