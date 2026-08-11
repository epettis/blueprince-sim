"""Darkroom: the first entry each day blows a fuse and kills its lights.

Wiki (Utility Closet page): "The first time a player enters the Darkroom in
a given day, the fuse will blow and make the lights go out... Although this
switch is initially on, it will switch off when the fuse blows." The dead
lights are what make drafting FROM the Darkroom obscure every floorplan
(engine/draft.py's _fill_options reads state.darkroom_lights_on live on
every doorway draft from this room, not just once here).
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _red_negated


@room_hook("darkroom", Hook.ON_ENTER)
def maybe_blow_fuse(game, room, ctx_room) -> None:
    """Blow the fuse on first entry while the switch is on.

    "If the switch is off when the Darkroom is drafted, then fuse never
    breaks" -- if the player pre-emptively flipped it off at the Utility
    Closet before ever entering, there is nothing to blow. Shelter or
    Knight's Shield can also keep the lights on, consulted only when the
    switch is actually on (matching _grant's "only negate an effect that
    would actually happen" pattern), so an already-dark switch never spends
    a charge.
    """
    if not game.state.darkroom_lights_on:
        return
    if _red_negated(game, room):
        return
    game.state.darkroom_lights_on = False
