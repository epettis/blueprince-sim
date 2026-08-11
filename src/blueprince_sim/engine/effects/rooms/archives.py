"""Archives: house-wide, non-stacking archiving of one dealt floorplan per
draft (see engine/draft.py's _fill_options, which reads the day flag this
module sets and is the only consumer of it).
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _red_negated


@room_hook("archives", Hook.ON_PLACE)
def activate_archiving(game, room, ctx_room) -> None:
    """Turn on house-wide archiving for the rest of the day.

    Shelter or Knight's Shield can negate this -- consulted once, here, at
    placement, so it spends exactly one Shelter charge rather than one per
    doorway drafted afterward. A second Archives placed later finds the flag
    already set and _red_negated is never consulted again, which is what
    makes non-stacking free: the flag is a plain boolean.
    """
    if _red_negated(game, room):
        return
    game.state.archives_active = True
