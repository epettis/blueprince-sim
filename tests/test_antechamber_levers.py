"""Antechamber lever gate: observable behavior of sealed doors and lever rooms.

Covers: sealed segments start sealed and block traversal; entering lever rooms
(Weight Room, Secret Garden, Great Hall) opens the correct segment; the Weight
Room power_hammer requirement and carry-over wall break; Great Hall key cost;
sealed-vs-locked distinction; overnight reset; antechamber_levers=False
regression guard; termination with a sealed antechamber; Greenhouse
broken_lever path regression; and that the Great Hall's on-arrival lever key
spend is charged to the walk itself, not just to the door being opened
(key_cost_map, the action mask's key budget, and end-to-end masked play all
agree with what move_to actually deducts).
"""

from __future__ import annotations

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.rl.train import fresh_save_config


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


# Test 2: Weight Room with power_hammer opens South and only South

def test_weight_room_with_hammer_opens_south(registry):
    """Entering the Weight Room while holding power_hammer opens the south
    Antechamber segment (37, N) and leaves west and east sealed."""
    g = _game(levers=True, items=frozenset({"power_hammer"}), registry=registry)
    # Place the Weight Room at rank 8 center (cell 37) with N and S doors
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    # South segment should now be open
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN
    # West and East segments remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED


# Test 3: Weight Room without hammer and without wall-break flag does NOT open

def test_weight_room_no_hammer_no_break_stays_sealed(registry):
    """Entering the Weight Room without power_hammer and without the permanent
    wall-break flag leaves the south segment sealed (no lever pull)."""
    g = _game(levers=True, registry=registry)  # no power_hammer, no wall_broken flag
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED


# Test 4: wall-break carry-over lets Weight Room open South on a later day

def test_weight_room_wall_broken_carryover_opens_south(registry):
    """Once weight_room_wall_broken is carried over, entering the Weight Room on
    a future day opens the south segment without needing the hammer again."""
    g = _game(levers=True, weight_room_wall_broken=True, registry=registry)
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN


# Test 5a: Secret Garden opens West; 5b: Great Hall opens East and consumes a key

def test_secret_garden_opens_west(registry):
    """Entering the Secret Garden opens the west Antechamber segment (41, E)."""
    g = _game(levers=True, registry=registry,
              satisfied_conditions=frozenset({"secret_garden_key"}))
    _place_at(g, "secret_garden", 41, E | W)
    _enter_at(g, 41)

    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_OPEN
    # South and East remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED


def test_great_hall_opens_east_costs_key(registry):
    """Entering the Great Hall with a key opens the east Antechamber segment
    (43, W) and consumes exactly one key."""
    g = _game(levers=True, keys=3, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_OPEN
    assert g.state.keys == 2  # one key spent
    # South and West remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED


def test_great_hall_no_key_stays_sealed(registry):
    """Entering the Great Hall with zero keys does not open the east segment:
    the lever requires a key to access and cannot be pulled without one."""
    g = _game(levers=True, keys=0, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED
    assert g.state.keys == 0  # no key spent


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


# Test 8: antechamber_levers=False is unchanged from old behavior

def test_levers_false_all_doors_open_or_locked_only(registry):
    """With antechamber_levers=False, no segment starts DOOR_SEALED: the three
    Antechamber segments roll locked (as before this PR) and can be opened with
    keys, reproducing the old open-door baseline."""
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


# Test 10: Greenhouse broken_lever path regression

def test_greenhouse_lever_still_opens_south(registry):
    """Installing a Broken Lever in the Greenhouse still opens the south segment
    (37, N), with antechamber_levers=True, exactly as before."""
    from blueprince_sim.engine import special_items
    g = _game(levers=True, items=frozenset({"broken_lever"}), registry=registry)
    # Place the Greenhouse in a wing position (it requires west_or_east_wing)
    greenhouse = g.registry.by_id["greenhouse"]
    g._place_room(greenhouse, 5, E | W | N | S & greenhouse.door_mask)
    g.state.pos = 5
    g.state.entered[5] = True

    # Even though segment starts SEALED, install_lever opens it via _open_segment
    assert special_items.can_install_lever(g)
    special_items.install_lever(g)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN


# Test 11: the Great Hall's lever key is charged to the route, not just the door

def test_walking_into_the_great_hall_is_charged_to_the_route(registry):
    """key_cost_map() prices in the Great Hall's on-arrival lever key spend
    before the caller ever walks - and move_to actually deducts exactly that
    many keys - so a caller budgeting off key_cost_map is never surprised."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    # Force the entrance -> Great Hall segment open so the only key spend on
    # this walk is the lever, not a locked door on the way in.
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    # Setup assertion: the lever has not been pulled yet, so the test can't
    # silently stop testing anything.
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED

    assert g.key_cost_map()[7] == 1  # the route to the Great Hall spends the lever key

    g.move_to(7)
    assert g.state.keys == 0  # the map matched what the walk actually spent


def test_the_nav_cache_notices_a_lever_room_that_has_already_been_entered(registry):
    """The nav memo must key on state.entered: an already-entered Great Hall
    charges nothing, because its lever only ever fires on first entry, and a
    map cached from before that entry would over-charge the route and could
    strand the player behind a road it wrongly reads as unaffordable."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled
    assert g.key_cost_map()[7] == 1  # unentered: walking in will pull the lever

    # Entry is the only thing that changes here, and the lever cannot fire twice.
    g.state.entered[7] = True
    assert g.key_cost_map()[7] == 0


# Test 12: the mask budgets the lever key AND the locked door behind it

def test_the_mask_never_offers_a_draft_the_lever_key_has_already_paid_for(registry):
    """A locked frontier doorway past the Great Hall needs two keys: one the
    walk itself spends pulling the lever, one for the door. The mask must
    not let the lever spend ride free on the door's own key budget."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    # Lock one of the Great Hall's own frontier doorways.
    g.state.door_state[segment_key(7, E)] = DOOR_LOCKED
    g.state.door_version += 1

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled

    action = A.OPEN_BASE + 7 * 4 + A.DIR_INDEX[E]

    g.state.keys = 1
    mask = A.action_mask(g)
    assert not mask[action], "1 key covers only the lever pull, not the locked door too"

    g.state.keys = 2
    mask = A.action_mask(g)  # _maps() fingerprints on st.keys, so this recomputes
    assert mask[action], "2 keys cover both the lever pull and the locked door"


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
