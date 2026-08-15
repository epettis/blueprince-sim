"""Clock Tower: day-end Tomorrow-room tally, broadcast across the whole grid.

Wiki (effect text): "The Clock Tower increases the next day starting key for
every Tomorrow room present in the mansion. This includes the Clock Tower
itself." (the infobox's "for each Tomorrow room you draft today" is the
losing reading, per the owner ruling.) That is a day-end grid tally, not a
per-room reaction to the day ending where the player happens to stand -- the
room's own ``Hook.ON_DAY_END`` fires only for the room the player is
standing in at day end (see ``effects/rooms/break_room.py``), which would be
wrong here regardless of where the player ends the day. ``Hook.ON_DAY_END_ALL``
is broadcast from ``Game._terminate`` to every room placed on the grid, the
day-end counterpart to ``Hook.ON_DRAFT_ROOM``'s broadcast in
``Game._place_room`` -- so this handler runs once, at the Clock Tower's own
placement, regardless of where the player is when the day ends.

See tests/test_carryover.py for the DayChain-driven next-day key grant this
tally feeds.
"""

from __future__ import annotations

from .. import Hook, room_hook

ROOM_ID = "clock_tower"


@room_hook(ROOM_ID, Hook.ON_DAY_END_ALL)
def tally_tomorrow_rooms(game, room, ctx_room) -> None:
    """Count every Tomorrow-category room on the grid, including this one,
    into ``state.clock_tower_tomorrow_keys``."""
    st = game.state
    st.clock_tower_tomorrow_keys = sum(
        1 for idx in st.grid
        if idx >= 0 and game.registry.rooms[idx].is_category("tomorrow")
    )
