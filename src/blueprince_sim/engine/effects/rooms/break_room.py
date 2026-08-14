"""Break Room: calling it a day here grants a starting keycard tomorrow.

Wiki (effect text): "If you call it a day in BREAK ROOM, tomorrow you will
begin the day with a staff keycard." This is a one-day pulse, not a
resource grant -- ``GameState.break_room_keycard`` is read back out by
``Game.carryover()`` at day end and turned into next day's ``has_keycard``
starting state by DayChain (see the flag's docstring on GameState for the
full shape, shared with sauna_visited/morning_room_visited/freezer_frozen).
Bespoke to this one room (CLAUDE.md: no reusable parametric tag covers "set
a one-day carry flag gated on day-end presence" -- ``mark_visited`` is
shaped for ON_ENTER, and ``grant`` is a flat resource delta, neither of
which fits a boolean pulse keyed on where the day itself ends), hence a
``room_hook`` rather than a new tag.
"""

from __future__ import annotations

from .. import Hook, room_hook

ROOM_ID = "break_room__ix11"


@room_hook(ROOM_ID, Hook.ON_DAY_END)
def grant_keycard_pulse(game, room, ctx_room) -> None:
    """Set the one-day pulse flag; DayChain turns it into tomorrow's keycard."""
    game.state.break_room_keycard = True
