"""The 5x9 manor grid.

Cells are flat indices ``0..44``: ``cell = (rank - 1) * 5 + col`` with ranks
1..9 (rank 1 = entrance row, rank 9 = Antechamber row) and cols 0..4
(col 0 = west edge, col 4 = east edge).

Doors are 4-bit masks: N=1 (toward rank 9), E=2, S=4 (toward rank 1), W=8.
"""

from __future__ import annotations

WIDTH = 5
RANKS = 9
N_CELLS = WIDTH * RANKS

N, E, S, W = 1, 2, 4, 8
DIRS = (N, E, S, W)
DIR_NAMES = {N: "N", E: "E", S: "S", W: "W"}
OPPOSITE = {N: S, E: W, S: N, W: E}

ENTRANCE_CELL = 2  # rank 1, center column


def rank_of(cell: int) -> int:
    return cell // WIDTH + 1


def col_of(cell: int) -> int:
    return cell % WIDTH


def neighbor(cell: int, direction: int) -> int:
    """Neighboring cell in ``direction``, or -1 if off-grid."""
    r, c = cell // WIDTH, cell % WIDTH
    if direction == N:
        r += 1
    elif direction == S:
        r -= 1
    elif direction == E:
        c += 1
    else:
        c -= 1
    if 0 <= r < RANKS and 0 <= c < WIDTH:
        return r * WIDTH + c
    return -1


def is_west_wing(cell: int) -> bool:
    return cell % WIDTH <= 1


def is_east_wing(cell: int) -> bool:
    return cell % WIDTH >= 3


def is_corner(cell: int) -> bool:
    r, c = cell // WIDTH, cell % WIDTH
    return r in (0, RANKS - 1) and c in (0, WIDTH - 1)


def rotate_mask(mask: int, quarter_turns: int) -> int:
    """Rotate a door mask clockwise by ``quarter_turns`` * 90 degrees."""
    k = quarter_turns % 4
    return ((mask << k) | (mask >> (4 - k))) & 0xF
