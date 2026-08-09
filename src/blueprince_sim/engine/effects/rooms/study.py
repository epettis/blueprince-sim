"""Study: while placed, lets the player pay a gem to redraw the current hand.

The gem cost and the 8-per-hand cap are enforced where the redraw is
requested (``Game.redraw``); this only flips the flag that unlocks it.
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("study", Hook.ON_PLACE)
def mark_study_placed(game, room, ctx_room) -> None:
    game.state.study_placed = True
