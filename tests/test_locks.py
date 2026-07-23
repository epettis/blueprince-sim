"""Locked doors and security doors.

Covers the datamined lock-chance table, the daily bias multiplier, key
spending at locked doorways (drafting and moving), key-aware path planning,
security-door spawning (whitelist, distance gate, per-level caps), the
keycard/power/offline-mode truth table, the Security and Utility Closet
switch actions, and the env mask/obs plumbing.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import locks
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import (DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY,
                                         base_lock_chance, segment_key)
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env import actions as A


# ------------------------------------------------------------- lock table


def test_base_lock_chance_matches_datamined_table(registry):
    rules = registry.lock_rules
    # E-W doors within a rank (any col): keyed by the rank itself.
    assert base_lock_chance(rules, 2, E) == 0        # rank 1
    assert base_lock_chance(rules, 16, E) == 25      # rank 4
    assert base_lock_chance(rules, 36, W) == 110     # rank 8
    assert base_lock_chance(rules, 41, E) == 130     # rank 9
    # N-S boundaries: keyed by the lower rank; edge cols differ from center.
    assert base_lock_chance(rules, 12, N) == 0       # 3<->4 boundary
    assert base_lock_chance(rules, 17, N) == 45      # 4<->5 boundary
    assert base_lock_chance(rules, 27, N) == 60      # 6<->7 center
    assert base_lock_chance(rules, 25, N) == 70      # 6<->7 edge (col 0)
    assert base_lock_chance(rules, 37, N) == 130     # 8<->9 boundary
    # Both sides of one segment agree.
    assert base_lock_chance(rules, 42, S) == base_lock_chance(rules, 37, N)


def test_segment_key_is_shared_by_both_sides():
    assert segment_key(7, N) == segment_key(12, S)
    assert segment_key(7, E) == segment_key(8, W)
    assert segment_key(7, N) != segment_key(7, S)


def test_low_ranks_never_locked_by_chance(registry):
    for seed in range(20):
        g = Game(GameConfig(), seed=seed, registry=registry)
        for (cell, d), state in g.state.door_state.items():
            low_cell, _ = segment_key(cell, d)
            if low_cell < 15 and d in (E, W):        # E-W within ranks 1-3
                assert state == DOOR_OPEN
            if low_cell < 10:                        # N-S boundaries below 3<->4
                assert state == DOOR_OPEN


def test_antechamber_doorways_start_locked(registry):
    # Rank 8<->9 sits at 130% base chance: at day-start bias 1 every
    # Antechamber doorway rolls locked, so walking in costs a key.
    g = Game(GameConfig(), seed=3, registry=registry)
    for d in (S, E, W):
        assert g.door_state_of(ANTECHAMBER_CELL, d) == DOOR_LOCKED
    # Guaranteed-by-chance locks skip the bias update (second-roll rule).
    assert g.state.lock_bias == 1.0


def test_door_locks_flag_disables_everything(registry):
    g = Game(GameConfig(door_locks=False), seed=3, registry=registry)
    assert g.state.door_state == {}
    assert g.doorway_passable(ANTECHAMBER_CELL, S)
    assert not g.can_toggle_keycard_power()


# ------------------------------------------------------------- bias system


def _bias_state() -> GameState:
    st = GameState()
    st.lock_bias = 1.0
    return st


def test_bias_drops_after_locked_and_recovers_after_unlocked(registry):
    rules = registry.lock_rules
    st = _bias_state()
    # Find a seed whose first roll at 45% locks the 4<->5 boundary door.
    for seed in range(50):
        st = _bias_state()
        if locks._roll_lock(st, rules, 17, N, Rng(seed)) == DOOR_LOCKED:
            break
    assert st.lock_bias == pytest.approx(1 - 0.385)
    # 45 * 0.615 = 27.7% effective chance for the next same-band door.
    # An unlocked outcome at >= 31% chance restores the bias toward 1.
    st.lock_bias = 0.7
    for seed in range(50):
        probe = _bias_state()
        probe.lock_bias = 0.7
        if locks._roll_lock(probe, rules, 17, N, Rng(seed)) == DOOR_OPEN:
            st = probe
            break
    # max(0.7 + 0.35, 1) = 1.05: unlocked doors can push the bias past 1,
    # making the next doors slightly MORE lock-prone (datamined rule).
    assert st.lock_bias == pytest.approx(1.05)


# ------------------------------------------------- keys at locked doorways


def _game(registry, **cfg) -> Game:
    return Game(GameConfig(**cfg), seed=1, registry=registry)


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


def test_locked_doorway_needs_and_spends_a_key(registry):
    g = _game(registry)
    doors = g.open_doorways()
    assert doors
    cell, d = doors[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    with pytest.raises(AssertionError):
        g.open_door(cell, d)
    g.state.keys = 2
    g.open_door(cell, d)
    assert g.phase is Phase.DRAFTING
    assert g.state.keys == 1
    assert g.door_state_of(cell, d) == DOOR_OPEN  # unlocked for good


def test_move_through_locked_door_spends_a_key(registry):
    g = _game(registry)
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    g._place_room(straight, 7, N | S)  # above the entrance (rank 2 center)
    _force_state(g, 2, N, DOOR_LOCKED)
    g.state.keys = 0
    assert N not in g.adjacent_moves()
    assert g.distance_map()[7] == -1  # not walkable without a key
    g.state.keys = 1
    assert N in g.adjacent_moves()
    assert g.distance_map()[7] == 1
    assert g.key_cost_map()[7] == 1
    g.move(N)
    assert g.state.pos == 7
    assert g.state.keys == 0
    assert g.door_state_of(2, N) == DOOR_OPEN


def test_security_door_blocks_until_openable(registry):
    g = _game(registry)
    doors = g.open_doorways()
    cell, d = doors[0]
    _force_state(g, cell, d, DOOR_SECURITY)
    assert not g.doorway_passable(cell, d)
    with pytest.raises(AssertionError):
        g.open_door(cell, d)
    g.state.has_keycard = True  # powered readers accept the card
    assert g.doorway_passable(cell, d)
    g.open_door(cell, d)
    assert g.state.keys == 0  # no key spent
    assert g.door_state_of(cell, d) == DOOR_OPEN


# ------------------------------------------------------- keycard system


def test_security_openable_truth_table():
    st = GameState()
    for power, card, offline, expect in [
        (True, True, False, True),    # powered + card
        (True, False, True, False),   # powered, no card: offline mode moot
        (False, True, False, False),  # unpowered + default Locked: nobody passes
        (False, False, True, True),   # unpowered + offline Unlocked: free
        (False, True, True, True),
        (True, False, False, False),
    ]:
        st.keycard_power_on = power
        st.has_keycard = card
        st.offline_unlocked = offline
        assert locks.security_openable(st) is expect, (power, card, offline)


def test_entering_security_assumes_offline_unlocked(registry):
    g = _game(registry)
    sec = registry.by_id["security"]
    g._place_room(sec, 7, sec.door_mask)
    _force_state(g, 2, N, DOOR_OPEN)
    assert not g.state.offline_unlocked
    g.move(N)
    assert g.state.offline_unlocked


def test_switch_actions_require_standing_in_the_room(registry):
    g = _game(registry)
    uc = registry.by_id["utility_closet"]
    sec = registry.by_id["security"]
    with pytest.raises(AssertionError):
        g.set_keycard_power(False)
    with pytest.raises(AssertionError):
        g.set_security_level("high")
    g._place_room(uc, 7, S)
    g._place_room(sec, 3, sec.door_mask)
    _force_state(g, 2, N, DOOR_OPEN)
    _force_state(g, 2, E, DOOR_OPEN)
    g.move(N)  # into the Utility Closet
    assert g.can_toggle_keycard_power() and not g.can_set_security_level()
    g.set_keycard_power(False)
    assert not g.state.keycard_power_on
    g.move(S)
    g.move(E)  # into Security
    assert g.can_set_security_level() and not g.can_toggle_keycard_power()
    g.set_security_level("high")
    assert g.state.security_level == "high"


# ------------------------------------------------------- security spawning


def test_security_spawn_needs_whitelist_and_distance(registry):
    rules = registry.lock_rules
    st = GameState()
    plain = registry.by_id["closet"]  # not on the whitelist
    sec_room = registry.by_id["security"]
    hits = 0
    for seed in range(200):
        assert not locks._roll_security(st, rules, plain, 41, E, Rng(seed))
        # Rank-1 doors sit ~80 units from the Antechamber: over the cutoff.
        assert not locks._roll_security(st, rules, sec_room, 2, E, Rng(seed))
        # Rank-9 doors of a whitelisted room are close and frequently spawn.
        if locks._roll_security(st, rules, sec_room, 41, E, Rng(seed)):
            hits += 1
        st.security_doors_spawned = 0
    assert hits > 30


def test_security_spawn_respects_daily_cap_and_level(registry):
    rules = registry.lock_rules
    sec_room = registry.by_id["security"]
    st = GameState()
    st.security_level = "low"
    st.security_doors_spawned = rules["security"]["spawn_limit"]["low"]
    for seed in range(100):
        assert not locks._roll_security(st, rules, sec_room, 41, E, Rng(seed))
    # Raising the level mid-day re-opens headroom (cap checked at roll time).
    st.security_level = "high"
    assert any(locks._roll_security(st, rules, sec_room, 41, E, Rng(seed))
               for seed in range(100))


def test_high_security_forces_the_door_probability(registry):
    # Passageway's 30% chance is forced to 100% on high: the only remaining
    # gate is the distance roll, so spawn rates jump sharply.
    rules = registry.lock_rules
    room = registry.by_id["passageway"]

    def rate(level: str) -> int:
        n = 0
        for seed in range(300):
            st = GameState()
            st.security_level = level
            n += locks._roll_security(st, rules, room, 41, E, Rng(seed))
        return n

    low, high = rate("normal"), rate("high")
    assert high > low * 2


def test_keycard_can_be_found_in_source_rooms(registry):
    found = 0
    for seed in range(40):
        g = Game(GameConfig(), seed=seed, registry=registry)
        office = registry.by_id["office"]
        g._place_room(office, 7, office.door_mask)
        _force_state(g, 2, N, DOOR_OPEN)
        g.move(N)
        found += g.state.has_keycard
    assert 0 < found < 40  # 25% chance: some days find it, most don't


# ------------------------------------------------------------- env plumbing


def test_mask_seals_and_reopens_security_doorways(registry):
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_SECURITY)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    assert not A.action_mask(g)[idx]
    g.state.has_keycard = True
    g.state.door_version += 1
    assert A.action_mask(g)[idx]


def test_mask_locked_doorway_accounts_for_path_keys(registry):
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    g.state.keys = 0
    assert not A.action_mask(g)[idx]
    g.state.keys = 1
    assert A.action_mask(g)[idx]


def test_mask_allows_revisiting_control_rooms(registry):
    g = _game(registry)
    uc = registry.by_id["utility_closet"]
    g._place_room(uc, 7, S)
    _force_state(g, 2, N, DOOR_OPEN)
    g.move(N)
    g.move(S)  # back in the entrance; the closet is entered
    g.state.offline_unlocked = True  # a power cut would now open doors
    mask = A.action_mask(g)
    assert mask[A.MOVE_TO_BASE + 7]
    # Standing inside, the breaker toggle itself is exposed.
    g.move(N)
    mask = A.action_mask(g)
    assert mask[A.TOGGLE_POWER_ACTION]
    lvl = [mask[A.SET_LEVEL_BASE + i] for i in range(3)]
    assert lvl == [False, False, False]  # not standing in Security


def test_obs_planes_mark_both_sides_of_a_segment(registry):
    from blueprince_sim.env import obs as O

    g = _game(registry)
    _force_state(g, 2, N, DOOR_LOCKED)
    enc = O.encode(g)
    flat_locked = enc["grid_locked"].reshape(-1)
    assert flat_locked[2] & N
    assert flat_locked[7] & S
    assert enc["house_flags"][9] == 1  # keycard power starts on


def test_determinism_with_locks(registry):
    def transcript(seed: int) -> tuple:
        g = Game(GameConfig(), seed=seed, registry=registry)
        return (tuple(sorted(g.state.door_state.items())), g.state.lock_bias,
                g.state.security_doors_spawned)

    for seed in range(10):
        assert transcript(seed) == transcript(seed)


def test_all_placed_rooms_stay_reachable_without_keys(registry):
    """Drafting opens the doorway it goes through, so the whole placed house
    (minus the pre-sealed Antechamber) is walkable with zero keys."""
    from blueprince_sim.cli.policies import POLICIES

    import random
    for seed in range(5):
        g = Game(GameConfig(), seed=seed, registry=registry)
        rnd = random.Random(seed)
        for _ in range(120):
            if g.phase is Phase.TERMINAL:
                break
            POLICIES["frontier_greedy"](g, rnd)
        if g.phase is Phase.TERMINAL:
            continue
        g.state.keys = 0
        dist = g.distance_map()
        for cell, idx in enumerate(g.state.grid):
            if idx >= 0 and cell != ANTECHAMBER_CELL:
                assert dist[cell] >= 0, f"seed {seed}: cell {cell} unreachable"
