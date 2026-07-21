"""Observation encoding."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces

from ..engine.game import Game, Phase
from ..engine.grid import DIRS
from ..engine.model import LAYOUTS

CATEGORIES = ("blueprint", "bedroom", "hallway", "green", "shop", "red",
              "blackprint", "studio_addition", "outer", "objective")
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
# room_idx+1, rarity+1, cost, layout, category, door_N, door_E, door_S, door_W,
# affordable, forced. The four door bits expose the drafted orientation as
# separate directional features so the policy can prefer, e.g., north doors.
OPTION_FEATURES = 11


def observation_space(n_rooms: int) -> spaces.Dict:
    return spaces.Dict({
        "grid_room": spaces.Box(0, n_rooms, shape=(9, 5), dtype=np.int16),
        "grid_doors": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "player_pos": spaces.Discrete(45),
        "resources": spaces.Box(-1, 999, shape=(7,), dtype=np.int16),
        "options": spaces.Box(-1, max(n_rooms, 999), shape=(3, OPTION_FEATURES), dtype=np.int16),
        "phase": spaces.Discrete(3),
    })


def encode(game: Game) -> dict:
    st = game.state
    grid_room = np.zeros((9, 5), dtype=np.int16)
    grid_doors = np.zeros((9, 5), dtype=np.uint8)
    for cell in range(45):
        r, c = divmod(cell, 5)
        grid_room[r, c] = st.grid[cell] + 1
        grid_doors[r, c] = st.placed_doors[cell]

    pending = st.pending
    redraws = pending.redraws_left if pending else 0
    resources = np.array(
        [st.steps, st.gems, st.keys, st.coins, st.dice, st.luck, redraws], dtype=np.int16)

    options = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    if game.phase is Phase.DRAFTING and pending is not None:
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            cost = game._effective_cost(room, opt)
            doors = tuple(int(bool(opt.orientation & d)) for d in DIRS)  # N,E,S,W
            if opt.hidden:
                # Archives mystery: identity and orientation concealed
                # (room_idx 0 = unknown, door bits 0), but the gem cost and
                # affordability stay visible and it is still selectable.
                options[opt.slot] = (0, 0, cost, -1, -1, 0, 0, 0, 0,
                                     int(game.affordable(room, opt)), 0)
                continue
            options[opt.slot] = (
                room.idx + 1,
                room.rarity_idx + 1,
                cost,
                LAYOUTS.index(room.layout),
                CAT_INDEX.get(room.category, 0),
                *doors,
                int(game.affordable(room, opt)),
                int(opt.forced),
            )
    return {
        "grid_room": grid_room,
        "grid_doors": grid_doors,
        "player_pos": st.pos,
        "resources": resources,
        "options": options,
        "phase": game.phase.value,
    }
