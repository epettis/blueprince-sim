"""Placement legality: orientations, draft conditions, connectivity."""

from __future__ import annotations

from ..config import GameConfig
from .grid import DIRS, OPPOSITE, N, is_corner, is_east_wing, is_west_wing, neighbor, rank_of
from .model import Room
from .state import GameState


def legal_orientations(room: Room, cell: int, entry_dir: int, state: GameState,
                       cfg: GameConfig) -> list[int]:
    """Door masks (rotations of the room) legal at ``cell`` entered via ``entry_dir``.

    ``entry_dir`` is the direction the player moved to reach the cell, so the
    room needs a door on the OPPOSITE side, facing back to the room drafted
    from. Off-grid-facing and blank-wall-facing doors are allowed by default
    (they become permanently blocked doors, as in the real game) unless the
    corresponding strict config flags are set.
    """
    back = OPPOSITE[entry_dir]
    out = []
    for mask in room.rotations:
        if not mask & back:
            continue
        ok = True
        for d in DIRS:
            if not mask & d:
                continue
            nb = neighbor(cell, d)
            if nb == -1:
                if cfg.forbid_offgrid_doors:
                    ok = False
                    break
            elif state.grid[nb] >= 0 and not state.placed_doors[nb] & OPPOSITE[d]:
                if cfg.strict_door_matching:
                    ok = False
                    break
        if ok:
            out.append(mask)
    return out


def satisfies_draft_conditions(room: Room, cell: int, entry_dir: int, state: GameState,
                               cfg: GameConfig, placed_ids: set[str],
                               from_library: bool) -> bool:
    """Check a room's datamined Draft Conditions against the target doorway.

    ``placed_ids`` is the set of room ids currently on the grid (maintained by
    Game). Item/unlock gates pass when listed in cfg.satisfied_conditions.
    Unknown condition tags are permissive; the data validator reports them so
    gaps are visible rather than silently restrictive.
    """
    if from_library and room.no_library_draft:
        return False
    for cond in room.draft_conditions:
        if cond == "west_wing" and not is_west_wing(cell):
            return False
        elif cond == "east_wing" and not is_east_wing(cell):
            return False
        elif cond == "west_or_east_wing" and not (is_west_wing(cell) or is_east_wing(cell)):
            return False
        elif cond == "west_wing_from_south_door":
            # Target must be west wing, entered heading north (i.e. through the
            # target's south-facing door).
            if not (is_west_wing(cell) and entry_dir == N):
                return False
        elif cond == "corner_only" and not is_corner(cell):
            return False
        elif cond == "pool_drafted" and "the_pool" not in placed_ids:
            return False
        elif cond == "library_only" and not from_library:
            return False
        elif cond.startswith("rank_gte_") and rank_of(cell) < int(cond.rsplit("_", 1)[1]):
            return False
        elif cond in ("secret_garden_key", "knight_chess_piece", "breakfast", "room8_key"):
            if cond not in cfg.satisfied_conditions:
                return False
        elif cond == "antechamber_north_door":
            return False  # Room 46; beyond the day-run objective
    return True
