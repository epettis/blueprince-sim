"""Foyer / Spare Foyer: force every Hallway-category room's doors unlocked.

Wiki (blueprince.wiki.gg/wiki/Foyer): "Once drafted, every door in a Hallway
will have all its doors unlocked. This applies to all hallways, regardless of
if they were drafted before or after the Foyer, and includes the Foyer
itself." Also: "The Foyer's effect also applies to security doors ... can
even be opened if the Keycard System is offline and the offline mode set to
locked." And: "The Foyer's effect also works on the doors that are
guaranteed to be locked in the Great Hall, overriding its effect and
unlocking them all. The same is true of the Vestibule." "If a second Foyer is
somehow drafted, it is redundant and has no additional effect."

Implemented:
  - GameState.foyer_placed is a persistent per-day flag, set the moment
    either Foyer or the Spare Foyer is placed. Setting it immediately sweeps
    every Hallway-category room already on the grid (including the Foyer's
    own doors, since Game._place_room writes the grid/doors before firing
    ON_PLACE), covering "drafted before". Game._place_room also consults the
    flag after every later placement (unlock_hallway_segments), so a Hallway
    drafted after the Foyer comes out unlocked too, covering "drafted
    before or after" with one primitive. Both the Great Hall and the
    Vestibule are themselves category "hallway" (rooms.json), so their own
    guaranteed-lock overrides fall out of the same generic sweep with no
    room-specific casing.
  - unlock_hallway_segments only force-opens segments currently DOOR_LOCKED
    or DOOR_SECURITY, leaving DOOR_SEALED (the Antechamber lever gate)
    untouched -- the Foyer's own wording never claims to bypass that gate,
    and security doors are covered by the same DOOR_OPEN write Game
    doorway_passable/security_openable treat as unconditionally passable.
  - A second Foyer re-fires the same sweep, which is idempotent: nothing is
    left to unlock, matching "redundant ... no additional effect".

Not modelled:
  - The wiki's "doors close" framing has no separate open/closed state in
    this sim; forcing DOOR_OPEN is the entire observable effect.
"""

from __future__ import annotations

from ...grid import DIRS
from ...locks import DOOR_LOCKED, DOOR_SECURITY, segment_key
from .. import Hook, room_hook


def unlock_hallway_segments(game, cell: int) -> None:
    """Force every locked/security doorway of the Hallway-category room at
    ``cell`` open. A no-op for any other room's category."""
    st = game.state
    room = game.registry.rooms[st.grid[cell]]
    if room.category != "hallway":
        return
    doors = st.placed_doors[cell]
    for d in DIRS:
        if not doors & d:
            continue
        if st.door_state.get(segment_key(cell, d)) in (DOOR_LOCKED, DOOR_SECURITY):
            game._open_segment(cell, d)


def _activate(game) -> None:
    """Arm the persistent flag and sweep every Hallway already on the grid."""
    game.state.foyer_placed = True
    for cell, idx in enumerate(game.state.grid):
        if idx >= 0:
            unlock_hallway_segments(game, cell)


@room_hook("foyer", Hook.ON_PLACE)
def activate_foyer(game, room, ctx_room) -> None:
    """"Once drafted, every door in a Hallway will have all its doors
    unlocked ... includes the Foyer itself."""
    _activate(game)


@room_hook("spare_foyer__ix137", Hook.ON_PLACE)
def activate_spare_foyer(game, room, ctx_room) -> None:
    """"The effects of the Spare Foyer ... are identical to the originals
    in each case."""
    _activate(game)
