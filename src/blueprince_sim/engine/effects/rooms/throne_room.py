"""Throne Room: a backup north-door lever (studio addition) -- on entry,
pulls the same north segment the Inner Sanctum's main lever opens, at no
extra cost beyond entering.
"""

from __future__ import annotations

from ...grid import N
from ...locks import DOOR_SEALED, segment_key
from .. import provides_lever

ANTECHAMBER_CELL = 42  # rank 9, center column


def pull_north_lever(game, cell: int) -> None:
    """Open the Antechamber's sealed north segment via Game._open_north_door.

    Routes through the single call site shared with the Inner Sanctum's own
    lever (Game.travel_to) so the two cannot record the per-day north-door
    reward event independently of each other.
    """
    if not game.cfg.antechamber_levers:
        return
    seg = segment_key(ANTECHAMBER_CELL, N)
    if game.state.door_state.get(seg) != DOOR_SEALED:
        return
    game._open_north_door()


provides_lever("throne_room", pull_north_lever)
