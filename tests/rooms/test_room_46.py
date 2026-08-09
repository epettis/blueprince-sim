"""Tests for Room 46 — the north door, two-tier objective, and reward split.

These tests pin the observable behaviour introduced by the Room 46 objective:
the north door sealing, the two-tier win condition (Antechamber + Room 46),
and the arrival-based reward split.  All assertions go through the public
Game / carryover / reward API.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import rewards as R


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game(seed: int = 1, **cfg_kwargs) -> Game:
    """Return a fresh game with antechamber_levers=True and enough steps."""
    defaults = {"antechamber_levers": True, "starting_steps": 100}
    defaults.update(cfg_kwargs)
    return Game(GameConfig(**defaults), seed=seed)


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to *cell* and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


def _travel_to_inner_sanctum(g: Game) -> None:
    """Drive the real travel_to() into inner_sanctum from its off-grid neighbour.

    inner_sanctum is not routable from the house on a fresh day (the outer-area
    chain is gated), so the player is parked on the adjacent "underpass" node.
    From there travel_to() runs the genuine arrival path, lever included -- the
    test must never re-implement that logic itself or it would assert nothing.
    """
    g.state.area = "underpass"
    g.state.pos = -1
    g.travel_to("inner_sanctum")


def _travel_to_room46(g: Game) -> None:
    """Stand the player in the Antechamber and drive the real travel_to() to Room 46.

    Requires the north door to be open already; while it is sealed there is no
    route at all, which test_room46_unreachable_while_north_door_sealed pins.
    """
    g.state.area = None
    g.state.pos = ANTECHAMBER_CELL
    g.state.entered[ANTECHAMBER_CELL] = True
    g.travel_to("room_46")


# ---------------------------------------------------------------------------
# 1. North door starts sealed on every reset
# ---------------------------------------------------------------------------

def test_north_door_sealed_on_reset():
    """The Antechamber's north door (toward Room 46) starts DOOR_SEALED each day.

    This is the fundamental gate: the player cannot reach Room 46 without
    first pulling one of the two levers (Inner Sanctum or Throne Room).
    """
    g = _game()
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED


def test_north_door_reseals_on_next_day():
    """The north door resets to DOOR_SEALED at the start of each new day.

    The Antechamber resets nightly — even if the north door was opened on day 1,
    it must be sealed again at day 2 start.
    """
    g = _game()
    # Manually open the north door via lever helper
    g._open_segment(ANTECHAMBER_CELL, N)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN
    # Build next-day config from carryover and verify door is sealed again
    carry = carryover(g)
    g2 = Game(GameConfig(antechamber_levers=True, starting_steps=100,
                         room46_reached=carry["room46_reached"]), seed=2)
    assert g2.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED


# ---------------------------------------------------------------------------
# 2. Antechamber arrival no longer terminates the day
# ---------------------------------------------------------------------------

def test_antechamber_arrival_does_not_terminate():
    """Moving onto cell 42 does not end the day; the day continues.

    The old termination_reason=='antechamber' path is removed; the day ends
    only on out_of_steps or dead_end.  Walking into the Antechamber must
    leave the game running.
    """
    g = _game()
    _enter_at(g, ANTECHAMBER_CELL)
    done, reason = g.is_done()
    assert not done, f"Game ended unexpectedly after Antechamber entry: reason={reason!r}"


# ---------------------------------------------------------------------------
# 3. antechamber_reached fires on first entry to cell 42
# ---------------------------------------------------------------------------

def test_antechamber_reached_set_on_entry():
    """antechamber_reached becomes True the first time the player enters cell 42.

    It stays False until that moment and does not require Room 46 to be reached.
    """
    g = _game()
    assert not g.state.antechamber_reached
    _enter_at(g, ANTECHAMBER_CELL)
    assert g.state.antechamber_reached


def test_antechamber_reached_not_set_before_entry():
    """antechamber_reached is False at game start (before the Antechamber is entered)."""
    g = _game()
    assert not g.state.antechamber_reached


# ---------------------------------------------------------------------------
# 4. Inner Sanctum arrival opens the north door
# ---------------------------------------------------------------------------

def test_inner_sanctum_arrival_opens_north_door():
    """Arriving at inner_sanctum opens the Antechamber's north door (the main lever).

    The game wiki: "In the main area of the room, there is a lever to open the
    north door of the Antechamber."  Reaching the inner_sanctum node is sufficient.
    Driven through the real travel_to(), so the engine lever wiring is exercised.
    """
    g = _game()
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED
    _travel_to_inner_sanctum(g)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN


def test_inner_sanctum_arrival_idempotent():
    """Arriving at inner_sanctum twice does not error and leaves the north door open."""
    g = _game()
    _travel_to_inner_sanctum(g)
    _travel_to_inner_sanctum(g)  # second visit: already open, must be a no-op
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN


# ---------------------------------------------------------------------------
# 5. (Throne Room's own lever behaviour lives in tests/rooms/test_throne_room.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. room_46 arrival sets room46_reached and success() is True
# ---------------------------------------------------------------------------

def test_room46_reached_on_arrival():
    """Arriving at room_46 sets room46_reached and success() returns True.

    Room 46 is the win condition; it is reached via the off-grid area graph
    after the north door is opened.
    """
    g = _game()
    assert not g.state.room46_reached
    assert not g.success()
    _travel_to_inner_sanctum(g)  # pull the lever: unseals the north door
    _travel_to_room46(g)
    assert g.state.room46_reached
    assert g.success()


def test_room46_does_not_terminate_day():
    """Reaching Room 46 does not end the day; play continues.

    Per design: the win reward fires on arrival and the agent keeps collecting
    resources (disks, keys) for tomorrow until steps run out.
    """
    g = _game()
    _travel_to_inner_sanctum(g)
    _travel_to_room46(g)
    done, _ = g.is_done()
    assert not done, "Day should continue after Room 46 is reached"


def test_room46_unreachable_while_north_door_sealed():
    """While the north door is sealed there is no route to Room 46 at all.

    This is what makes the levers load-bearing: standing in the Antechamber is
    not sufficient, so area_route_cost must report no route until one is pulled.
    """
    g = _game()
    g.state.pos = ANTECHAMBER_CELL
    g.state.entered[ANTECHAMBER_CELL] = True
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED
    assert g.area_route_cost("room_46") is None, "sealed door must block all routing"
    g._open_segment(ANTECHAMBER_CELL, N)
    assert g.area_route_cost("room_46") is not None, "opened door must expose a route"


# ---------------------------------------------------------------------------
# 7. room46_reached carries across days
# ---------------------------------------------------------------------------

def test_room46_reached_carries_to_next_day():
    """room46_reached=True persists into the next day via carryover.

    This is the permanent gem-deck gate: once Room 46 is reached, it remains
    reached on all future days even before the player steps into it again.
    """
    g = _game()
    _travel_to_inner_sanctum(g)
    _travel_to_room46(g)
    assert g.state.room46_reached
    carry = carryover(g)
    assert carry["room46_reached"] is True


def test_room46_not_reached_does_not_carry():
    """room46_reached=False does not persist into the next day if never reached."""
    g = _game()
    carry = carryover(g)
    assert carry["room46_reached"] is False


# ---------------------------------------------------------------------------
# 8. Reward split: +0.25 on Antechamber, +1.0 on Room 46
# ---------------------------------------------------------------------------

def test_sparse_reward_antechamber_arrival():
    """sparse() yields ANTECHAMBER_REWARD (+0.25) on first entry to the Antechamber.

    The reward fires on the state transition, not on termination, so it must appear
    when antechamber_reached flips from False to True.
    """
    g = _game()
    prev = R.snapshot(g)
    assert not prev["antechamber_reached"]
    _enter_at(g, ANTECHAMBER_CELL)
    r = R.sparse(g, prev, terminated=False)
    assert r == pytest.approx(R.ANTECHAMBER_REWARD), (
        f"Expected +{R.ANTECHAMBER_REWARD} on Antechamber arrival, got {r}")


def test_sparse_reward_room46_arrival():
    """sparse() yields ROOM46_REWARD (+1.0) on first Room 46 arrival.

    The win reward fires on arrival, not on termination.  The Antechamber step
    must not be double-counted: prev snapshot is taken after Antechamber.
    """
    g = _game()
    _enter_at(g, ANTECHAMBER_CELL)
    _travel_to_inner_sanctum(g)   # open the north door before snapshotting
    prev = R.snapshot(g)          # snapshot after Antechamber but before Room 46
    assert prev["antechamber_reached"]
    assert not prev["room46_reached"]
    _travel_to_room46(g)
    r = R.sparse(g, prev, terminated=False)
    assert r == pytest.approx(R.ROOM46_REWARD), (
        f"Expected +{R.ROOM46_REWARD} on Room 46 arrival, got {r}")


def test_sparse_reward_zero_without_milestones():
    """sparse() yields 0 when neither Antechamber nor Room 46 is newly reached."""
    g = _game()
    prev = R.snapshot(g)
    r = R.sparse(g, prev, terminated=False)
    assert r == 0.0


def test_sparse_reward_combined_in_one_step():
    """sparse() yields +1.25 when both milestones fire in the same step (edge case).

    Can occur if prev snapshot predates both flags; the reward must add them.
    """
    g = _game()
    prev = R.snapshot(g)
    assert not prev["antechamber_reached"]
    assert not prev["room46_reached"]
    g.state.antechamber_reached = True
    g.state.room46_reached = True
    r = R.sparse(g, prev, terminated=False)
    expected = R.ANTECHAMBER_REWARD + R.ROOM46_REWARD
    assert r == pytest.approx(expected), (
        f"Expected +{expected} for both milestones, got {r}")


# ---------------------------------------------------------------------------
# 9. obs 'progress' array shape and room46 index

def test_observation_progress_includes_room46():
    """The 'progress' observation array has shape (5,) with antechamber_reached
    at index 3 and room46_reached at index 4, both reflecting current game state."""
    from blueprince_sim.env.obs import encode
    g = _game()

    obs = encode(g)
    assert obs["progress"].shape == (5,), (
        f"progress shape should be (5,), got {obs['progress'].shape}"
    )
    assert obs["progress"][3] == 0, "antechamber_reached (index 3) should be 0 at start"
    assert obs["progress"][4] == 0, "room46_reached (index 4) should be 0 at start"

    g.state.antechamber_reached = True
    g.state.room46_reached = True
    obs2 = encode(g)
    assert obs2["progress"][3] == 1, "antechamber_reached (index 3) should reflect state"
    assert obs2["progress"][4] == 1, "room46_reached (index 4) should reflect state"
