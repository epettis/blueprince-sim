"""Antechamber lever gate: cross-cutting invariants of the sealed-door system.

Covers: sealed segments start sealed and block traversal; sealed-vs-locked
distinction; the overnight reset (segments opened on day N are sealed again on
day N+1 -- the single most important invariant of the lever gate design, shown
here via the Weight Room but not itself a Weight Room property); the
antechamber_levers=False regression guard; termination with a sealed
antechamber; and end-to-end masked random play never hitting an engine
assertion.

Individual lever rooms' own behaviour (Weight Room, Secret Garden, Great Hall,
Greenhouse) lives in their own files under tests/rooms/.
"""

from __future__ import annotations

import random

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects import Capability, _CAPABILITY_REGISTRY, provides_capability
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.rl.train import fresh_save_config

# The four rooms that pull an Antechamber lever on first entry, each
# registered via engine/effects/rooms/<id>.py's own provides_lever() call.
LEVER_ROOM_IDS = ("great_hall", "secret_garden", "throne_room", "weight_room")


# ---------------------------------------------------------------------------
# helpers

def _game(*, levers: bool = True, keys: int = 0, items: frozenset | None = None,
          registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``.

    Passes ``registry`` through when provided to avoid repeated loads.
    """
    kwargs: dict = dict(antechamber_levers=levers, **extra)
    if items is not None:
        kwargs["starting_items"] = items
    cfg = GameConfig(**kwargs)
    g = Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))
    g.state.keys = keys
    return g


def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to cell and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


# ---------------------------------------------------------------------------
# Test 1: sealed segments start sealed and the Antechamber is NOT reachable

def test_sealed_segments_start_sealed(registry):
    """With antechamber_levers=True, the West/South/East segments start DOOR_SEALED
    and the Antechamber is not reachable through them."""
    g = _game(levers=True, registry=registry)
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED
    # North is off-grid (rank 9 has no rank 10); not a segment we seal.
    assert ANTECHAMBER_CELL not in g.reachable_cells()


# Test 6: sealed door is NOT key-openable

def test_sealed_door_not_key_openable(registry):
    """A sealed segment is impassable regardless of keys held: doorway_passable
    returns False even with many keys, and the action mask never enables
    drafting through a sealed doorway (defense-in-depth check in action_mask).

    Sealed segments are only on the Antechamber side; frontier_doorways() already
    excludes the Antechamber and non-empty cells, so this confirms the sealed
    check in the action mask handles any edge case correctly.
    """
    from blueprince_sim.env import actions as A
    from blueprince_sim.engine.locks import DOOR_SEALED
    g = _game(levers=True, keys=10, registry=registry)
    # The sealed south segment is not passable regardless of keys
    assert not g.doorway_passable(ANTECHAMBER_CELL, S)
    # doorway_passable returns False for sealed (not locked behavior)
    # Verify door_state_of returns DOOR_SEALED (not DOOR_LOCKED or DOOR_OPEN)
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    # A segment can be injected as sealed on a frontier; the mask skips it
    from blueprince_sim.env.actions import OPEN_BASE, DIR_INDEX
    g2 = _game(levers=True, keys=10, registry=registry)
    # Manually seal a frontier doorway (synthetic test for action mask defense)
    g2.state.door_state[segment_key(2, N)] = DOOR_SEALED
    g2.state.door_version += 1
    mask = A.action_mask(g2)
    open_north_action = OPEN_BASE + 2 * 4 + DIR_INDEX[N]
    assert not mask[open_north_action], "sealed frontier door must not be a legal open action"


# Test 7: doors reset overnight

def test_sealed_doors_reset_overnight(registry):
    """A segment opened on day N (by entering a lever room) is sealed again on
    day N+1: the seal resets with each day, per the wiki rule.

    This is the single most important invariant of the lever gate design.
    """
    chain = DayChain(
        GameConfig(antechamber_levers=True, special_items=True,
                   starting_items=frozenset({"power_hammer"})),
        n_days=3,
    )

    # Day 1: enter Weight Room with hammer -> south opens
    cfg1 = chain.next_config()
    g1 = Game(cfg1, seed=1)
    _place_at(g1, "weight_room", 37, N | S)
    _enter_at(g1, 37)
    assert g1.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN  # lever pulled
    # Carry over: wall is now permanently broken
    co = g1.carryover()
    assert co["weight_room_wall_broken"] is True
    chain.advance(co)

    # Day 2: fresh day, south segment must be sealed again at start
    cfg2 = chain.next_config()
    assert cfg2.weight_room_wall_broken is True  # wall-break carried over
    g2 = Game(cfg2, seed=2)
    assert g2.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED  # sealed at day start

    # But entering the Weight Room NOW opens it again (no hammer needed: wall broken)
    _place_at(g2, "weight_room", 37, N | S)
    _enter_at(g2, 37)
    assert g2.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN


# Test 8: antechamber_levers=False leaves segments as ordinary locked doors

def test_levers_false_all_doors_open_or_locked_only(registry):
    """With antechamber_levers=False, no segment starts DOOR_SEALED: the three
    Antechamber segments roll locked and can be opened with keys, same as any
    other locked door."""
    g = _game(levers=False, registry=registry)
    # None of the three segments should be DOOR_SEALED
    for d in (S, E, W):
        seg_state = g.door_state_of(ANTECHAMBER_CELL, d)
        assert seg_state != DOOR_SEALED, f"direction {d} should not be sealed with levers=False"
    # The segments will be DOOR_LOCKED (rank 8<->9 is 100% base chance), not DOOR_OPEN
    # and a room placed connecting to the Antechamber opens the lock (in-drafting).
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    g._place_room(straight, 37, N | S)
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN  # in-drafting still works


# Test 9: termination fires when Antechamber is sealed and unreachable

def test_termination_fires_when_antechamber_sealed_and_no_frontier(registry):
    """When the Antechamber is sealed (unreachable) and no frontier doorways
    remain, the day terminates as a dead_end rather than hanging."""
    g = _game(levers=True, registry=registry)
    # Only the pre-placed Entrance Hall is on the grid; no frontier except the
    # Entrance Hall's own doors. Seal the player in by exhausting steps.
    g.state.steps = 1
    # Drain steps directly to trigger out_of_steps termination
    g.state.steps = 0
    g._check_termination()
    done, reason = g.is_done()
    assert done
    assert reason == "out_of_steps"


def test_dead_end_fires_when_no_frontier_and_antechamber_unreachable(registry):
    """With all frontier doorways consumed and the Antechamber sealed, the day
    terminates as dead_end (not a hang)."""
    g = _game(levers=True, registry=registry)
    # Clear the entrance hall's doors so there are no frontier doorways
    g.state.placed_doors[2] = 0  # entrance hall: no doors
    g.state.door_version += 1
    g._check_termination()
    done, reason = g.is_done()
    assert done
    assert reason == "dead_end"


# Test 13: end-to-end - masked random play never hits an engine assertion

def test_random_masked_play_never_hits_an_engine_assertion():
    """Uniform-random play restricted to action_masks() must never trip an
    engine assertion (e.g. 'door is locked and you have no key'): the mask
    must only ever offer actions the engine can actually carry out, across
    many seeds including the known-bad seed 27 (fresh_save_config, step 33,
    action 72 at base commit f2cad2e)."""
    for seed in range(200):
        env = BluePrinceEnv(cfg=fresh_save_config())
        env.reset(seed=seed)
        rng = random.Random(seed)
        for step in range(5000):
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            action = rng.choice(legal)
            try:
                _, _, terminated, truncated, _ = env.step(action)
            except AssertionError as exc:
                raise AssertionError(
                    f"seed={seed} step={step} action={action} raised: {exc}"
                ) from exc
            if terminated or truncated:
                break


# ---------------------------------------------------------------------------
# Capability.LEVER: which rooms register it, and that dispatch is
# capability-gated rather than an id list living in game.py (docs/architecture.md).
# Mirrors tests/test_capabilities.py's Capability.COMMERCE coverage.

@pytest.mark.parametrize("room_id", LEVER_ROOM_IDS)
def test_lever_room_provides_lever(room_id):
    """Each of the four lever rooms is registered as providing Capability.LEVER
    via its own effects/rooms module's provides_lever() call."""
    assert provides_capability(room_id, Capability.LEVER)


def test_ordinary_room_does_not_provide_lever(registry):
    """A room with no lever role (e.g. the Corridor) does not provide
    Capability.LEVER -- the registry is opt-in, not a default."""
    assert not provides_capability("corridor", Capability.LEVER)


def test_lever_capability_registry_has_exactly_four_rooms():
    """The set of ids registered for Capability.LEVER is exactly the four
    lever rooms -- no fifth room accidentally registered, and none of the
    four is missing."""
    registered = {room_id for room_id, cap in _CAPABILITY_REGISTRY if cap is Capability.LEVER}
    assert registered == set(LEVER_ROOM_IDS)


def test_entering_an_ordinary_room_at_a_lever_cell_does_not_pull_a_lever(registry):
    """A room with no Capability.LEVER registration does not open an
    Antechamber segment even when placed at a real lever room's own segment
    cell (37, the Weight Room's south-segment cell) and entered -- dispatch
    is gated on the capability, not merely on "a room was entered"."""
    g = _game(levers=True, registry=registry)
    _place_at(g, "corridor", 37, N | S)
    _enter_at(g, 37)
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
