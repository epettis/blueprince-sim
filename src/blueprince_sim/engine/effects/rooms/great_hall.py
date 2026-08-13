"""Great Hall: on entry, pulls the Antechamber's east lever -- behind the
prize-room's own locked side door, so a key is spent (design doc
antechamber-lever-design.md). No key in hand means the lever is not pulled.
"""

from __future__ import annotations

from ... import experiments
from ...grid import W
from ...locks import DOOR_SEALED, segment_key
from .. import provides_lever

EAST_SEGMENT_CELL = 43  # column 3: its west face is the Antechamber's east door
LEVER_KEY_COST = 1  # keys spent pulling the lever while the east segment is sealed


def lever_cost(game, cell: int) -> int:
    """Keys pulling the east lever would cost right now: 0 once already open."""
    if game.state.door_state.get(segment_key(EAST_SEGMENT_CELL, W)) != DOOR_SEALED:
        return 0
    return LEVER_KEY_COST


def pull_east_lever(game, cell: int) -> None:
    """Open the sealed east segment, spending the prize-room key it costs."""
    if not game.cfg.antechamber_levers:
        return
    st = game.state
    seg = segment_key(EAST_SEGMENT_CELL, W)
    if st.door_state.get(seg) != DOOR_SEALED:
        return
    cost = lever_cost(game, cell)
    if st.keys < cost:
        return
    st.keys -= cost
    game._open_segment(EAST_SEGMENT_CELL, W)
    experiments.on_lever_pulled(game, EAST_SEGMENT_CELL, W)


provides_lever("great_hall", pull_east_lever, lever_cost)
