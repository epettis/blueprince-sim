"""Locked doors and security doors.

Lock state lives on *doorway segments* - the shared edge between two adjacent
cells - keyed canonically by :func:`segment_key`. ``GameState.door_state`` maps
a segment to ``DOOR_LOCKED`` or ``DOOR_SECURITY``; ``DOOR_OPEN`` entries mark
segments that rolled unlocked or have been opened, and a missing entry means
the segment was never rolled and is freely passable (so tests that build
states by hand see no locks).

All numbers come from ``data/locks.json`` (TFMurphy datamine; see its meta).
A segment is rolled when the first door on it is placed - the real game rolls
lazily on first click, so the daily bias multiplier here follows placement
order rather than click order (see README "Known simplifications").
"""

from __future__ import annotations

import math

from .grid import E, OPPOSITE, W, WIDTH, col_of, neighbor, rank_of
from .rng import Rng
from .state import GameState

DOOR_OPEN = 0      # rolled unlocked, or unlocked/opened by the player
DOOR_LOCKED = 1    # opening consumes one key
DOOR_SECURITY = 2  # opening needs the keycard system (see security_openable)

SECURITY_LEVELS = ("low", "normal", "high")

# The Antechamber sits at rank 9, center column; security-door spawning is
# gated on Euclidean distance to its center (cell centers 10 units apart).
_ANTE_RANK, _ANTE_COL = 9.0, 2.0


def segment_key(cell: int, direction: int) -> tuple[int, int]:
    """Canonical (cell, direction) for a doorway segment: lower cell first."""
    nb = neighbor(cell, direction)
    if 0 <= nb < cell:
        return nb, OPPOSITE[direction]
    return cell, direction


def base_lock_chance(rules: dict, cell: int, direction: int) -> float:
    """Datamined base lock chance (percent) for one doorway segment."""
    table = rules["lock_chance"]
    if direction in (E, W):
        return float(table["ew_by_rank"].get(str(rank_of(cell)), 0.0))
    low_cell, _ = segment_key(cell, direction)  # N/S: keyed by the lower rank
    band = table["ns_boundary"].get(str(rank_of(low_cell)))
    if band is None:
        return 0.0
    edge = col_of(cell) in (0, WIDTH - 1)
    return float(band["edge" if edge else "center"])


def security_openable(st: GameState) -> bool:
    """Can the player open security doors right now?

    Powered readers need the Keycard. Unpowered readers open freely only if
    the Security terminal's offline mode was switched to Unlocked (the sim
    assumes the player does this on every Security visit); otherwise an
    unpowered door lets nobody through, Keycard or not.
    """
    if st.keycard_power_on:
        return st.has_keycard
    return st.offline_unlocked


def roll_segment(st: GameState, rules: dict, room, cell: int, direction: int,
                 rng: Rng) -> int:
    """Roll a freshly created doorway segment of ``room``'s door at ``cell``.

    Security replaces the normal lock roll; guaranteed-state doors (security
    doors, always-unlocked rooms) bypass the bias system entirely.
    """
    if _roll_security(st, rules, room, cell, direction, rng):
        st.security_doors_spawned += 1
        return DOOR_SECURITY
    if room.id in rules["always_unlocked_rooms"]["rooms"]:
        return DOOR_OPEN
    return _roll_lock(st, rules, cell, direction, rng)


def _roll_lock(st: GameState, rules: dict, cell: int, direction: int, rng: Rng) -> int:
    base = base_lock_chance(rules, cell, direction)
    if base <= 0:
        return DOOR_OPEN
    b = rules["bias"]
    chance = base * st.lock_bias
    if rng.chance("door_lock", chance / 100.0):
        # Guaranteed-by-chance locks mostly leave the bias alone: a second
        # roll against the base chance (ignoring bias) skips the update.
        if not (chance > b["high_second_roll_above"]
                and rng.chance("door_lock_bias", base / 100.0)):
            st.lock_bias = min(st.lock_bias + b["locked_delta"], 1.0)
        return DOOR_LOCKED
    # Low-chance unlocks mostly leave the bias alone (mirrored second roll).
    if not (chance < b["low_second_roll_below"]
            and not rng.chance("door_lock_bias", base / 100.0)):
        st.lock_bias = max(st.lock_bias + b["unlocked_delta"], 1.0)
    return DOOR_OPEN


def _door_distance(cell: int, direction: int, cell_size: float) -> float:
    """Euclidean distance from the doorway midpoint to the Antechamber center."""
    nb = neighbor(cell, direction)
    mid_rank = (rank_of(cell) + rank_of(nb)) / 2.0
    mid_col = (col_of(cell) + col_of(nb)) / 2.0
    return math.hypot((mid_col - _ANTE_COL) * cell_size,
                      (mid_rank - _ANTE_RANK) * cell_size)


def _roll_security(st: GameState, rules: dict, room, cell: int, direction: int,
                   rng: Rng) -> bool:
    sec = rules["security"]
    chance = sec["room_door_chance"].get(room.id)
    if chance is None:
        return False
    if st.security_doors_spawned >= sec["spawn_limit"][st.security_level]:
        return False
    dist = _door_distance(cell, direction, sec["cell_size"])
    if dist > sec["distance_cutoff"]:
        return False
    if rng.uniform("security_door", 0.0, sec["distance_roll_max"]) <= dist:
        return False
    p = 100.0 if st.security_level == "high" else float(chance)
    return rng.chance("security_door_prob", p / 100.0)
