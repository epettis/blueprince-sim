"""Placement legality: orientations, draft conditions, connectivity."""

from __future__ import annotations

from ..config import GameConfig
from .grid import (DIRS, RANKS, E, N, OPPOSITE, S, W, is_center_column, is_corner,
                   is_east_wing, is_interior, is_west_wing, neighbor, rank_of)
from .model import Room
from .state import GameState


def legal_orientations(room: Room, cell: int, entry_dir: int, state: GameState,
                       cfg: GameConfig) -> list[int]:
    """Door masks (rotations of the room) legal at ``cell`` entered via ``entry_dir``.

    ``entry_dir`` is the direction the player moved to reach the cell, so the
    room needs a door on the OPPOSITE side, facing back to the room drafted
    from. A doorway can never point into the outer wall, so any rotation with
    a door facing off-grid is illegal: this is what stops 4-way rooms being
    drawn on edges, restricts corners to L-shapes and Dead Ends, and fixes a
    T-shape's orientation against an edge. Blank-wall-facing doors are allowed
    by default (they become permanently blocked doors) unless
    ``cfg.strict_door_matching`` is set.
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
                ok = False  # door would point into the outer wall
                break
            if state.grid[nb] >= 0 and not state.placed_doors[nb] & OPPOSITE[d]:
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
            # Outdoor green rooms (Terrace, Patio, Veranda, Greenhouse, Secret
            # Garden) sit against the west or east outer wall (a wing is one
            # edge column).
            return False
        elif cond == "not_on_wing" and not is_center_column(cell):
            # Hallway: only the three interior columns, mutually exclusive with
            # the West/East Wing Halls that take the edge columns.
            return False
        elif cond == "no_corner" and is_corner(cell):
            return False
        elif cond == "corner_only" and not is_corner(cell):
            return False
        elif cond == "interior_only" and not is_interior(cell):
            # Courtyard: inside the mansion, never with its (T-shape) missing
            # door against an outer wall.
            return False
        elif cond == "west_wing_from_south_door":
            # Her Ladyship's Chamber: drafted southward into the West Wing (its
            # back door faces north); never on Rank 1.
            if not (is_west_wing(cell) and entry_dir == S and rank_of(cell) >= 2):
                return False
        elif cond == "garage":
            # West Wing, Ranks 4-8, only drafted heading north or west (never
            # south or east) — five legal tiles.
            if not (is_west_wing(cell) and 4 <= rank_of(cell) <= 8
                    and entry_dir in (N, W)):
                return False
        elif cond == "boiler_room":
            # Never on Rank 1 or 9. On the West Wing it must be drafted
            # southward, on the East Wing northward; center columns are free.
            if rank_of(cell) in (1, RANKS):
                return False
            if is_west_wing(cell) and entry_dir != S:
                return False
            if is_east_wing(cell) and entry_dir != N:
                return False
        elif cond == "morning_room":
            # Fixed door sides per wing: on the West Wing it cannot be drafted
            # northward, on the East Wing it cannot be drafted southward.
            if is_west_wing(cell) and entry_dir == N:
                return False
            if is_east_wing(cell) and entry_dir == S:
                return False
        elif cond == "room8_placement":
            # Key 8 drafts Room 8 onto Rank 8 only: northward from Rank 7 in the
            # East Wing, or southward from Rank 9 in the West Wing.
            north_east = is_east_wing(cell) and entry_dir == N
            south_west = is_west_wing(cell) and entry_dir == S
            if not (rank_of(cell) == 8 and (north_east or south_west)):
                return False
        elif cond == "gift_shop":
            # Never on Rank 9; and never drafted southward onto Rank 1.
            if rank_of(cell) == RANKS:
                return False
            if rank_of(cell) == 1 and entry_dir == S:
                return False
        elif cond == "no_north_on_wing":
            # Clock Tower / Solarium: on a wing (edge column) they cannot be
            # drafted heading north, except onto the corner tiles.
            if ((is_west_wing(cell) or is_east_wing(cell)) and not is_corner(cell)
                    and entry_dir == N):
                return False
        elif cond == "no_horizontal_end_rank":
            # Solarium: on Rank 1 or Rank 9 it cannot be drafted horizontally
            # (heading east or west), except into the corners.
            if rank_of(cell) in (1, RANKS) and not is_corner(cell) and entry_dir in (E, W):
                return False
        elif cond == "pool_drafted" and "the_pool" not in placed_ids:
            return False
        elif cond == "library_only" and not from_library:
            return False
        elif cond.startswith("rank_gte_") and rank_of(cell) < int(cond.rsplit("_", 1)[1]):
            return False
        elif cond.startswith("rank_lte_") and rank_of(cell) > int(cond.rsplit("_", 1)[1]):
            return False
        elif cond in ("secret_garden_key", "knight_chess_piece", "breakfast", "room8_key"):
            if cond not in cfg.satisfied_conditions:
                return False
        elif cond == "antechamber_north_door":
            return False  # Room 46; beyond the day-run objective
    return True
