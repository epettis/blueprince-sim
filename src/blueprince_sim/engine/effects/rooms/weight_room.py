"""Weight Room: a red room that halves the player's remaining steps on draft.

The halving is a red-room penalty, so Shelter's negation (and Knight's
Shield) can cancel it, same as the Chapel's coin loss or the Maid's
Chamber's anti-luck.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _red_negated


@room_hook("weight_room", Hook.ON_PLACE)
def halve_remaining_steps(game, room, ctx_room) -> None:
    if _red_negated(game, room):
        return
    game.state.steps -= game.state.steps // 2
