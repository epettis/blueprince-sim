"""Drawing Room: fires the drawing_room_drawn experiment trigger when dealt,
and grants one free redraw to every hand dealt from its own doorway.

Implemented:
  - on_hand_dealt -- delegates to experiments.on_drawing_room_dealt, which
    holds the trigger_id gate. The Drawing Room has no upgrade variants, so
    room_hook's "never fires for variants" caveat does not apply here.
  - on_draft_from -- +1 redraws_left, mirroring the Classroom's own grant
    (effects/rooms/classroom.py). ON_DRAFT_FROM fires once per doorway, on
    the initial deal only, so the free redraw is per **door**: every fresh
    doorway drafted from the Drawing Room gets its own charge, redraws of
    the same doorway do not add another, and the charge is not a once-a-day
    flag -- a second Drawing Room doorway drafted later the same day grants
    another.
"""

from __future__ import annotations

from ... import experiments
from .. import Hook, room_hook


@room_hook("drawing_room", Hook.ON_HAND_DEALT)
def on_hand_dealt(game, room, ctx_room) -> None:
    """Fire drawing_room_drawn if that trigger is today's configured experiment."""
    experiments.on_drawing_room_dealt(game)


@room_hook("drawing_room", Hook.ON_DRAFT_FROM)
def grant_free_redraw(game, room, ctx_room) -> None:
    """One free redraw for the hand just dealt from this doorway."""
    game.state.pending.redraws_left += 1
