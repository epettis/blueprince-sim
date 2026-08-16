"""The scripted policies and the once-per-day outer draft.

``Game._action_in_budget`` counts today's outer draft as a reason the day is
not over, so a policy that never takes it asks ``_check_termination`` for an
ending the engine will not give: the decision changes nothing,
``cli/batch.py``'s stall detector fires, and the episode is recorded as
``decision_limit`` with steps still on the clock.

Taking it is only half the fix. ``Game.open_outer_draft`` walks the player to
West Path, off the 5x9 grid, where every query ``_navigate_frontier`` makes is
meaningless -- ``state.pos`` still names the last grid cell. A policy that
drafts out there and cannot walk home strands itself and stops placing rooms
altogether, so the return leg is asserted here as its own property.

Grids are hand-built rather than seeded: three rooms whose door masks face
only the Entrance Hall leave zero frontier doorways with total certainty,
where a seed would only make it likely. The same construction as
``test_day_end.py``'s ``_spent_house``, minus its
``outer_room_drafted = True`` line -- that flag is what this file is about.
"""

from __future__ import annotations

import random

import pytest

from blueprince_sim.cli.policies import (
    _navigate_frontier,
    _offgrid_destinations,
    frontier_greedy,
)
from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, ENTRANCE_CELL, N, S, W

NORTH_CELL = ENTRANCE_CELL + 5
WEST_CELL = ENTRANCE_CELL - 1
EAST_CELL = ENTRANCE_CELL + 1

#: house -> grounds -> west_path with the west gate already unlatched.
DOORSTEP_COST = 2
#: west_path -> grounds -> house, the walk back onto the grid.
HOME_COST = 2


def _spent_house(steps: int, seal_north: bool, seed: int = 3) -> Game:
    """A fully entered house standing on ``steps``, at the Entrance Hall.

    Locks and special items are off so no key, no container and no Running
    Shoes roll can quietly add a second reason for the day to continue; the
    west gate is pre-unlatched so the doorstep is a flat 2-step walk from the
    Entrance Hall rather than a Garage-and-breaker route that depends on which
    rooms got placed.

    ``seal_north`` places the Sauna (door mask S alone) north of the player,
    consuming the Entrance Hall's last frontier doorway and creating none.
    Leaving it out is how a caller keeps exactly one grid action on offer to
    weigh the outer trip against.
    """
    cfg = GameConfig(door_locks=False, special_items=False, west_gate_unlatched=True)
    game = Game(cfg, seed=seed)
    game._place_room(game.registry.by_id["closet"], WEST_CELL, E)
    game._place_room(game.registry.by_id["coat_check"], EAST_CELL, W)
    cells = [ENTRANCE_CELL, WEST_CELL, EAST_CELL]
    if seal_north:
        game._place_room(game.registry.by_id["sauna"], NORTH_CELL, S, entry_dir=S)
        cells.append(NORTH_CELL)
    st = game.state
    for cell in cells:
        st.entered[cell] = True
    st.pos = ENTRANCE_CELL
    st.steps = steps
    return game


def _only_the_outer_draft_left(steps: int = 10, seed: int = 3) -> Game:
    """A spent house where the outer draft is the single purposeful action the
    engine can still name.

    The closing pair of assertions is the anti-vacuity guard:
    ``_action_in_budget`` flips to False the moment the outer draft is marked
    taken, which proves the outer draft -- and nothing else -- is holding this
    day open.
    """
    game = _spent_house(steps=steps, seal_north=True, seed=seed)
    st = game.state
    assert not game.frontier_doorways(), "scenario needs a house with no doors left"
    assert not game._in_place_action_available(), "scenario needs nothing free underfoot"
    assert game.outer_draft_available(), "scenario needs the outer draft on offer"
    assert game._action_in_budget(), "scenario needs the day held open"
    st.outer_room_drafted = True
    assert not game._action_in_budget(), (
        "scenario needs the outer draft to be the ONLY thing holding the day open")
    st.outer_room_drafted = False
    return game


def _stall_snapshot(game: Game) -> tuple:
    """The exact tuple ``cli/batch.py::run_episode`` compares to decide a
    decision made no progress.

    Mirrored rather than imported because it is a local closure over the
    episode's game; the point of these tests is that the policy moves one of
    *these* fields on every decision, so an approximation would not test the
    property that fails in batch.
    """
    st = game.state
    return (game.phase, st.steps, game.rooms_placed, st.pos,
            len(st.pending.options) if st.pending else -1,
            st.keycard_power_on, st.security_level, st.door_version)


def _play_out(game: Game, limit: int = 64) -> None:
    """Run ``frontier_greedy`` to termination, failing on the first decision
    that ``cli/batch.py``'s stall detector would not see.

    A stalled decision there is force-resolved and then breaks the episode
    loop, which is what records ``decision_limit``; here it is an outright
    failure, so a policy that declines the outer draft cannot pass quietly.
    """
    rnd = random.Random(0)
    for _ in range(limit):
        if game.phase is Phase.TERMINAL:
            return
        before = _stall_snapshot(game)
        frontier_greedy(game, rnd)
        assert _stall_snapshot(game) != before, (
            f"decision changed nothing cli/batch.py can see "
            f"(phase {game.phase}, area {game.state.area}, steps {game.state.steps})")
    raise AssertionError("the day never ended")


def test_the_scenario_stalls_a_policy_that_declines_the_outer_draft():
    """The bug itself, stated as the engine sees it: with the house spent, the
    day stays in NAVIGATE and ``_check_termination`` refuses to end it, so a
    decision that only asks the engine to end the day changes nothing at all.

    This is the mutation guard for every test below -- it pins that the
    scenario really is one where declining is fatal, not merely suboptimal."""
    game = _only_the_outer_draft_left()
    before = _stall_snapshot(game)

    game._check_termination()

    assert game.phase is Phase.NAVIGATE
    assert _stall_snapshot(game) == before


def test_frontier_greedy_takes_the_outer_draft_when_the_house_has_nothing_left():
    """The fix: rather than concede a day the engine is holding open for the
    outer draft, the policy walks to the doorstep and opens the hand."""
    game = _only_the_outer_draft_left(steps=10)

    _navigate_frontier(game)

    assert game.phase is Phase.DRAFTING
    assert game.off_grid and game.state.area == "west_path"
    assert game.state.pending.target_cell == -1  # off-grid hand, no cell to fill
    assert game.state.steps == 10 - DOORSTEP_COST


def test_the_outer_draft_is_the_last_resort_not_the_first_choice():
    """The outer trip costs the walk to the doorstep and lands the return leg
    at the Entrance Hall, so it must never pre-empt a doorway the policy could
    still draft. With the north doorway restored the policy drafts it and
    stays on the grid, even though the outer draft is equally available."""
    game = _spent_house(steps=10, seal_north=False)
    assert game.outer_draft_available(), "guard needs both actions genuinely on offer"
    assert (ENTRANCE_CELL, N) in game.frontier_doorways()

    _navigate_frontier(game)

    assert game.phase is Phase.DRAFTING
    assert not game.off_grid
    assert game.state.pending.target_cell == NORTH_CELL


def test_the_policy_enters_the_outer_room_then_walks_back_onto_the_grid():
    """The return leg, which is what makes the draft worth taking: outer rooms
    sit off the 5x9 grid, so every room still left to place is in the house.

    ``west_path -> grounds -> house`` is always open by the time a policy is
    out there -- arriving at the doorstep is itself the act that unlatches the
    west gate -- and the room's own ON_ENTER pickups are collected on the way
    past."""
    game = _only_the_outer_draft_left(steps=10)
    _navigate_frontier(game)                 # walk to the doorstep, deal the hand
    frontier_greedy(game, random.Random(0))  # take an option
    assert game.phase is Phase.NAVIGATE
    assert game.state.outer_room_drafted and game.off_grid

    for _ in range(8):
        if not game.off_grid or game.phase is Phase.TERMINAL:
            break
        _navigate_frontier(game)

    assert game.state.outer_room_entered, "the outer room's pickups were skipped"
    assert not game.off_grid, "the policy stranded itself off the grid"
    assert game.state.pos == ENTRANCE_CELL


def test_a_spent_house_ends_the_day_after_the_outer_trip_instead_of_stalling():
    """End to end: the day that used to run out of decisions now terminates
    with a real reason, having taken the outer draft on the way."""
    game = _only_the_outer_draft_left(steps=10)

    _play_out(game)

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason in ("dead_end", "out_of_steps")
    assert game.state.outer_room_drafted


def test_the_outer_trip_is_declined_when_the_doorstep_is_out_of_reach():
    """Anti-vacuity in the other direction: the policy is not simply calling
    ``open_outer_draft`` unconditionally. Two steps do not cover the walk with
    one to spare, ``outer_draft_available`` is False, and the day ends."""
    game = _only_the_outer_draft_left()
    game.state.steps = DOORSTEP_COST
    assert not game.outer_draft_available()

    _navigate_frontier(game)

    assert game.phase is Phase.TERMINAL
    assert not game.state.outer_room_drafted


@pytest.mark.parametrize("steps", [4, 6, 10, 30])
def test_off_grid_the_policy_never_concedes_a_day_the_engine_keeps_open(steps):
    """The invariant that stops the fix from moving the stall off the grid:
    off the grid the engine's ``_outer_action_in_budget`` decides whether the
    day continues, and the policy's own destination list is built from the
    same predicate, so the two can never disagree.

    Swept across step budgets that straddle the walk home (4 is too few to
    return from inside the room, 30 is plenty) because the two predicates only
    risk diverging at the affordability boundary."""
    game = _only_the_outer_draft_left(steps=steps)
    _navigate_frontier(game)
    if game.phase is Phase.TERMINAL:
        pytest.skip("this budget cannot reach the doorstep at all")
    frontier_greedy(game, random.Random(0))
    assert game.off_grid, "scenario needs the player off the grid"

    engine_says_live = game._outer_action_in_budget()
    policy_has_a_move = bool(_offgrid_destinations(game)) or game.outer_draft_available()

    assert policy_has_a_move == engine_says_live


def test_off_grid_travel_only_ever_offers_anchors_travel_to_can_resolve():
    """``Game.travel_to`` resolves a grid anchor through
    ``Game._grid_anchors``, which omits the Garage and The Foundation until
    those rooms are actually on the grid -- while the area graph carries their
    nodes regardless. Offering one the mapping does not hold would raise a
    KeyError mid-episode."""
    game = _only_the_outer_draft_left(steps=30)
    _navigate_frontier(game)
    frontier_greedy(game, random.Random(0))
    assert game.off_grid

    anchors = game._grid_anchors()
    offered = {node_id for _cost, node_id in _offgrid_destinations(game)}

    assert "house" in offered, "the walk home must be on offer"
    for node_id in offered & {"garage", "the_foundation", "antechamber"}:
        assert node_id in anchors, f"{node_id} is offered but travel_to cannot resolve it"
