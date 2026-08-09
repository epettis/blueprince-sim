"""Dovecote: grants free floorplan rotation while it sits among the current
draft hand's options -- unlike the Rotunda (see rotunda.py), the grant rides
being DRAWN, not being placed.
"""

from __future__ import annotations


def in_current_hand(game) -> bool:
    """Is the Dovecote one of the pending draft hand's options right now?

    A live query against ``state.pending.options`` rather than an
    ``ON_HAND_DEALT``-fired flag: several rotation tests (tests/test_rotation.py)
    build a ``PendingDraft`` directly and assign it to ``state.pending``,
    bypassing ``Game.open_door``/``Game.redraw`` -- and so ``ON_HAND_DEALT`` --
    entirely. A flag set only at those two fire sites would read stale for
    every one of those hands.
    """
    pending = game.state.pending
    return pending is not None and any(
        game.registry.rooms[o.room_idx].id == "dovecote" for o in pending.options)
