"""Secret Garden: on entry, pulls the Antechamber's west lever -- no extra
cost beyond entering (design doc antechamber-lever-design.md).
"""

from __future__ import annotations

from ...grid import E
from ...locks import DOOR_SEALED, segment_key

WEST_SEGMENT_CELL = 41  # column 1: its east face is the Antechamber's west door


def pull_west_lever(game, cell: int) -> None:
    """Open the sealed west segment, if the lever is still there to pull."""
    if not game.cfg.antechamber_levers:
        return
    seg = segment_key(WEST_SEGMENT_CELL, E)
    if game.state.door_state.get(seg) != DOOR_SEALED:
        return
    game._open_segment(WEST_SEGMENT_CELL, E)
