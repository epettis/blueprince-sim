"""The Kennel: digging anywhere unlocks the doors of the room being dug.

Wiki (blueprince.wiki.gg/wiki/The_Kennel): "After drafting the Kennel, using
a Shovel to dig in any room with locked doors will immediately unlock the
doors in that room ... This can also unlock security doors." "All dig spots
count for this effect, as does digging for treasure." The Jack Hammer and the
Detector Shovel also trigger it.

Implemented:
  - unlock_dug_room is called from special_items.dig_all (Task C's dig site)
    right after an actual dig resolves, both for the room's own dig spots and
    for a Treasure Map dig -- covering "all dig spots ... as does digging for
    treasure". dig_all already funnels every dig tool (Shovel, Jack Hammer,
    Detector Shovel) through one code path keyed on DIG_PRIORITY, so no
    per-tool casing is needed here: whichever tool triggered the dig,
    unlock_dug_room fires the same way.
  - The Kennel only needs to be drafted, never entered: unlock_dug_room reads
    game.placed_ids directly, which Game._place_room populates for every
    placed room regardless of whether it has been walked into.
  - Unlocks both DOOR_LOCKED and DOOR_SECURITY segments on the dug room's own
    placed doors.
  - Registered at Hook.ON_PLACE purely as a marker: the Kennel arms nothing
    at its own placement (game.placed_ids already reflects "drafted" with no
    extra state needed), but a room_hook at its own id is what the
    room-fidelity audit (tools/validate_data.py) recognizes as "modelled".

Not modelled:
  - The wiki's own unexplained note that the effect "often does not work in
    the Foundation" carries an open {{Question}} asking why, so it is
    unexplained behaviour rather than a rule -- ordinary Kennel behaviour
    applies to the Foundation the same as any other room.
"""

from __future__ import annotations

from ...grid import DIRS
from ...locks import DOOR_LOCKED, DOOR_SECURITY, segment_key
from .. import Hook, room_hook


def unlock_dug_room(game, cell: int) -> None:
    """Force every locked/security doorway of the room at ``cell`` open,
    provided the Kennel is on the estate. A no-op otherwise."""
    if "the_kennel" not in game.placed_ids:
        return
    st = game.state
    doors = st.placed_doors[cell]
    for d in DIRS:
        if not doors & d:
            continue
        if st.door_state.get(segment_key(cell, d)) in (DOOR_LOCKED, DOOR_SECURITY):
            game._open_segment(cell, d)


@room_hook("the_kennel", Hook.ON_PLACE)
def mark_kennel_placed(game, room, ctx_room) -> None:
    """No state to arm here -- see unlock_dug_room's docstring above."""
