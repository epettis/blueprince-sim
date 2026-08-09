"""Classroom: drafting from inside it grants free redraws equal to the
house's running drafting-room count (state.drafting_room_count).
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("classroom", Hook.ON_DRAFT_FROM)
def grant_free_redraws(game, room, ctx_room) -> None:
    game.state.pending.redraws_left += game.state.drafting_room_count
