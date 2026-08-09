"""Great Hall: on entry, pulls the Antechamber's east lever -- behind the
prize-room's own locked side door, so a key is spent (design doc
antechamber-lever-design.md). No key in hand means the lever is not pulled.
"""

from __future__ import annotations

from ...grid import W
from ...locks import DOOR_SEALED, segment_key

EAST_SEGMENT_CELL = 43  # column 3: its west face is the Antechamber's east door


def pull_east_lever(game, cell: int) -> None:
    """Open the sealed east segment, spending the prize-room key it costs."""
    if not game.cfg.antechamber_levers:
        return
    st = game.state
    seg = segment_key(EAST_SEGMENT_CELL, W)
    if st.door_state.get(seg) != DOOR_SEALED:
        return
    cost = game.lever_key_cost(cell)
    if st.keys < cost:
        return
    st.keys -= cost
    game._open_segment(EAST_SEGMENT_CELL, W)
