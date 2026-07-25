"""Observation encoding."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces

from ..engine.game import ANTECHAMBER_CELL, Game, Phase
from ..engine.grid import DIRS, OPPOSITE, neighbor
from ..engine.locks import DOOR_LOCKED, DOOR_SECURITY, SECURITY_LEVELS
from ..engine.model import LAYOUTS

CATEGORIES = ("blueprint", "bedroom", "hallway", "green", "shop", "red",
              "blackprint", "studio_addition", "outer", "objective")
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
STAGES = ("week1", "week2", "late")
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
# room_idx+1, rarity+1, gem_cost, step_cost, layout, category, door_N, door_E,
# door_S, door_W, affordable, forced. The four door bits expose the drafted
# orientation as separate directional features so the policy can prefer, e.g.,
# north doors. Cost is split by currency: with the Hovel placed, gem costs are
# paid entirely in steps at 3:1, which a single scalar cannot express.
OPTION_FEATURES = 12
HOUSE_FLAGS = 13  # solarium, greenhouse, study, library, hovel, bedroom_bonus,
                  # red_negations, free_categories count, has_keycard,
                  # keycard_power_on, offline_unlocked, security_level,
                  # security_openable


def observation_space(n_rooms: int) -> spaces.Dict:
    """Dict observation space over the 9x5 (rank-major) grid; see :func:`encode`.

    Room ids are shifted by +1 so 0 means "empty cell"; -1 is the sentinel for
    unreachable/walled-off in the distance planes and for absent option slots.
    """
    return spaces.Dict({
        "grid_room": spaces.Box(0, n_rooms, shape=(9, 5), dtype=np.int16),
        "grid_doors": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # Walking distance from the player per cell (-1 empty/unreachable).
        "grid_dist": spaces.Box(-1, 99, shape=(9, 5), dtype=np.int16),
        # Optimistic distance to the Antechamber per cell: empty cells count
        # as passable, placed rooms only via their doors (-1 = walled off).
        "grid_ante_dist": spaces.Box(-1, 99, shape=(9, 5), dtype=np.int16),
        # 4-bit mask of frontier doorways (draftable doors) per cell.
        "grid_frontier": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # 4-bit masks of locked / security doorway segments per cell (both
        # sides of a segment carry the bit; opened doors drop out).
        "grid_locked": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "grid_security": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "grid_entered": spaces.Box(0, 1, shape=(9, 5), dtype=np.uint8),
        "player_pos": spaces.Discrete(45),
        "resources": spaces.Box(-1, 999, shape=(7,), dtype=np.int16),
        "options": spaces.Box(-1, max(n_rooms, 999), shape=(3, OPTION_FEATURES), dtype=np.int16),
        "phase": spaces.Discrete(3),
        "stage": spaces.Discrete(3),
        "house_flags": spaces.Box(0, 999, shape=(HOUSE_FLAGS,), dtype=np.int16),
        # deepest_rank, optimistic player->Antechamber distance (-1 if walled
        # off), Antechamber connected+walkable right now (0/1), outer_loc (0/1/2).
        "progress": spaces.Box(-1, 999, shape=(4,), dtype=np.int16),
    })


def _cost_split(game: Game, room, opt) -> tuple[int, int]:
    """Effective cost as (gems, steps): the Hovel converts gems to steps 3:1."""
    cost = game._effective_cost(room, opt)
    if cost <= 0:
        return 0, 0
    if game.hovel_placed:
        return 0, 3 * cost
    return cost, 0


def encode(game: Game) -> dict:
    """Encode the live game into the Dict observation for the current phase.

    Grid planes are 9x5 rank-major. Locked/security bits are painted on BOTH
    cells of a doorway segment (and drop out once the door is opened). Option
    rows are -1 outside DRAFTING or for absent slots; a hidden (Archives
    mystery) option exposes only cost and affordability, not identity.
    """
    st = game.state
    grid_room = np.array(st.grid, dtype=np.int16).reshape(9, 5)
    grid_room += 1
    grid_doors = np.array(st.placed_doors, dtype=np.uint8).reshape(9, 5)
    grid_entered = np.array(st.entered, dtype=np.uint8).reshape(9, 5)

    grid_dist = np.array(game.distance_map(), dtype=np.int16).reshape(9, 5)
    grid_ante_dist = np.array(game.optimistic_distances(), dtype=np.int16).reshape(9, 5)
    grid_frontier = np.zeros((9, 5), dtype=np.uint8)
    if game.phase is not Phase.TERMINAL:
        for cell, d in game.frontier_doorways():
            grid_frontier[cell // 5, cell % 5] |= d

    grid_locked = np.zeros((9, 5), dtype=np.uint8)
    grid_security = np.zeros((9, 5), dtype=np.uint8)
    for (cell, d), seg in st.door_state.items():
        if seg == DOOR_LOCKED:
            plane = grid_locked
        elif seg == DOOR_SECURITY:
            plane = grid_security
        else:
            continue
        plane[cell // 5, cell % 5] |= d
        nb = neighbor(cell, d)
        plane[nb // 5, nb % 5] |= OPPOSITE[d]

    pending = st.pending
    redraws = pending.redraws_left if pending else 0
    resources = np.array(
        [st.steps, st.gems, st.keys, st.coins, st.dice, st.luck, redraws], dtype=np.int16)

    options = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    if game.phase is Phase.DRAFTING and pending is not None:
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            gem_cost, step_cost = _cost_split(game, room, opt)
            doors = tuple(int(bool(opt.orientation & d)) for d in DIRS)  # N,E,S,W
            if opt.hidden:
                # Archives mystery: identity and orientation concealed
                # (room_idx 0 = unknown, door bits 0), but the cost and
                # affordability stay visible and it is still selectable.
                options[opt.slot] = (0, 0, gem_cost, step_cost, -1, -1, 0, 0, 0, 0,
                                     int(game.affordable(room, opt)), 0)
                continue
            options[opt.slot] = (
                room.idx + 1,
                room.rarity_idx + 1,
                gem_cost,
                step_cost,
                LAYOUTS.index(room.layout),
                CAT_INDEX.get(room.category, 0),
                *doors,
                int(game.affordable(room, opt)),
                int(opt.forced),
            )

    house_flags = np.array([
        int(st.solarium_placed),
        int(st.greenhouse_placed),
        int(st.study_placed),
        int(st.library_placed),
        int(game.hovel_placed),
        game.bedroom_bonus,
        game.red_negations,
        len(game.free_categories),
        int(st.has_keycard),
        int(st.keycard_power_on),
        int(st.offline_unlocked),
        SECURITY_LEVELS.index(st.security_level),
        int(game.security_openable()),
    ], dtype=np.int16)

    ante_flat = grid_ante_dist.reshape(-1)
    progress = np.array([
        game.deepest_rank,
        int(ante_flat[st.pos]),
        int(grid_dist[ANTECHAMBER_CELL // 5, ANTECHAMBER_CELL % 5] > 0),
        st.outer_loc,
    ], dtype=np.int16)

    return {
        "grid_room": grid_room,
        "grid_doors": grid_doors,
        "grid_dist": grid_dist,
        "grid_ante_dist": grid_ante_dist,
        "grid_frontier": grid_frontier,
        "grid_locked": grid_locked,
        "grid_security": grid_security,
        "grid_entered": grid_entered,
        "player_pos": st.pos,
        "resources": resources,
        "options": options,
        "phase": game.phase.value,
        "stage": STAGE_INDEX.get(st.stage, 2),
        "house_flags": house_flags,
        "progress": progress,
    }
