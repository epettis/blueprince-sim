"""Drawing Room: fires the drawing_room_drawn experiment trigger when dealt.

Implemented:
  - on_hand_dealt -- delegates to experiments.on_drawing_room_dealt, which
    holds the trigger_id gate. The Drawing Room has no upgrade variants, so
    room_hook's "never fires for variants" caveat does not apply here.
"""

from __future__ import annotations

from ... import experiments
from .. import Hook, room_hook


@room_hook("drawing_room", Hook.ON_HAND_DEALT)
def on_hand_dealt(game, room, ctx_room) -> None:
    """Fire drawing_room_drawn if that trigger is today's configured experiment."""
    experiments.on_drawing_room_dealt(game)
