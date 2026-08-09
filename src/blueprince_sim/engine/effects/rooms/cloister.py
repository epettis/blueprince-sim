"""Cloister variants: "...for each X you draft FROM THIS CLOISTER" tracking.

Shared primitive: ``_drafted_from(game, room)`` answers "was the room now
being placed dealt from ``room``'s own doorway", using only state already on
hand while ON_DRAFT_ROOM fires (``game.state.pending.from_cell`` plus
``game.room_cells``) -- no new state is needed for the primitive itself. See
its docstring for why the timing works out.

Implemented:
  - cloister_of_rynna__ix29 -- luck for each green room.
  - cloister_of_mila__ix33 -- an extra item for each Bedroom. The item is
    granted later, at that Bedroom's own first entry (see
    GameState.cloister_mila_bonus_cells), since drafting only places a room
    and grants nothing until it is entered.
  - cloister_of_orinda__ix35 -- opens a random Antechamber doorway segment
    for each Blackprint.
  - cloister_of_draxus__ix36 -- dice for each Dead End actually drafted from
    this Cloister. The room's own "you WILL draft" wording promises this as a
    certainty, which in the real game comes from restricting this Cloister's
    draft pool to Dead Ends only; that pool restriction belongs in draft.py
    and is out of this module's scope, so only the reward half is modeled
    here -- it pays out for whatever Dead End is actually drafted rather than
    guaranteeing every draft is one.
  - cloister_of_lydia__ix34 -- 2 permanent allowance for each Shop drafted
    from this Cloister.

Not modeled, and why:
  - cloister_of_joya__ix30: the Dining Room's "main course" bonus has no
    representation anywhere in the engine (dining_room's effects list is
    empty; nothing tracks or ever reads a meal value), so there is nowhere to
    write a permanent bonus that anything would consume.
  - cloister_of_dauja__ix31: stars are not a tracked resource
    (effects/tier1.py::_grant no-ops "stars" explicitly).
  - cloister_of_veia__ix32: "room with a fireplace" is not a category or flag
    anywhere in rooms.json.
"""

from __future__ import annotations

from ...grid import E, N, W
from ...locks import DOOR_SEALED, segment_key
from .. import Hook, room_hook
from ..tier1 import _grant

ANTECHAMBER_CELL = 42  # rank 9, center column

# blueprince.wiki.gg/wiki/Cloister: "Specifically, 6 luck is added per
# activation." The record's own effect_text carries no number.
LUCK_PER_GREEN_ROOM = 6
DICE_PER_DEAD_END = 4  # cloister_of_draxus__ix36, per meta.glyph_resolution icon "dice"
ALLOWANCE_PER_SHOP = 2  # cloister_of_lydia__ix34, from its own effect_text

# The Antechamber's four doorway segments, as (cell, direction) pairs -- matches
# the SEALED assignment Game.reset makes when antechamber_levers is True.
_ANTECHAMBER_SEGMENTS = (
    (ANTECHAMBER_CELL, N),  # North: off-grid door to Room 46
    (41, E),                 # West: Antechamber's W door, via col 1
    (37, N),                 # South: Antechamber's S door, via rank 8 center
    (43, W),                 # East: Antechamber's E door, via col 3
)


def _drafted_from(game, room) -> bool:
    """True when the room now being placed was dealt from ``room``'s own doorway.

    ``game.state.pending`` still holds the in-flight draft's ``from_cell``
    while ON_DRAFT_ROOM fires: Game._place_room fires the hook and only
    Game.choose clears ``pending`` afterward. ``game.room_cells`` already has
    ``room``'s own cell recorded, since Game._place_room updates it before
    firing ON_PLACE/ON_DRAFT_ROOM. Comparing the two needs no new state, and
    works for both the broadcast to other placed rooms and a room's own
    self-fire (which never matches -- nothing can be drafted from a doorway
    that is itself only being placed this instant).
    """
    pending = game.state.pending
    if pending is None or pending.from_cell < 0:
        return False
    return pending.from_cell == game.room_cells.get(room.id)


@room_hook("cloister_of_rynna__ix29", Hook.ON_DRAFT_ROOM)
def raise_luck_for_green_rooms(game, room, ctx_room) -> None:
    """"Raise your LUCK with each GREEN ROOM you draft from this CLOISTER"."""
    if ctx_room is not None and ctx_room.category == "green" and _drafted_from(game, room):
        _grant(game, "luck", LUCK_PER_GREEN_ROOM)


@room_hook("cloister_of_mila__ix33", Hook.ON_DRAFT_ROOM)
def mark_bedroom_bonus_item(game, room, ctx_room) -> None:
    """"Find an extra item in each BEDROOM you draft from this CLOISTER".

    Marks the drafted Bedroom's cell so Game._enter grants the extra item
    once the player actually walks in.
    """
    if ctx_room is not None and ctx_room.category == "bedroom" and _drafted_from(game, room):
        game.state.cloister_mila_bonus_cells.add(game.state.pending.target_cell)


def _open_random_antechamber_door(game) -> None:
    """Open one of the Antechamber's sealed doorway segments, chosen uniformly.

    Only segments still sealed are candidates, so the room always delivers the
    door it promises; when none is sealed there is nothing to open and the
    trigger passes. Mirrors the lever rooms (Game._open_segment /
    Game._open_north_door): gated on antechamber_levers, since without it the
    Antechamber's doors are never sealed to begin with, so there is nothing for
    this to open that a normal doorway doesn't already offer. The North segment
    routes through Game._open_north_door so it records the same per-day reward
    event a lever pull would.
    """
    if not game.cfg.antechamber_levers:
        return
    sealed = [(cell, direction) for cell, direction in _ANTECHAMBER_SEGMENTS
              if game.state.door_state.get(segment_key(cell, direction)) == DOOR_SEALED]
    if not sealed:
        return
    cell, direction = game.rng.choice("cloister_of_orinda_door", sealed)
    if cell == ANTECHAMBER_CELL and direction == N:
        game._open_north_door()
    else:
        game._open_segment(cell, direction)


@room_hook("cloister_of_orinda__ix35", Hook.ON_DRAFT_ROOM)
def open_door_per_blackprint(game, room, ctx_room) -> None:
    """"Open a random door of the ANTECHAMBER for each BLACKPRINT you draft
    from this CLOISTER"."""
    if ctx_room is not None and ctx_room.category == "blackprint" and _drafted_from(game, room):
        _open_random_antechamber_door(game)


@room_hook("cloister_of_draxus__ix36", Hook.ON_DRAFT_ROOM)
def grant_dice_for_dead_ends(game, room, ctx_room) -> None:
    """"Gain 4[dice] for each DEAD-END room ... you draft from this CLOISTER"
    (see the module docstring for the "WILL draft" gap)."""
    if ctx_room is not None and ctx_room.layout == "dead_end" and _drafted_from(game, room):
        _grant(game, "dice", DICE_PER_DEAD_END)


@room_hook("cloister_of_lydia__ix34", Hook.ON_DRAFT_ROOM)
def raise_allowance_for_shops(game, room, ctx_room) -> None:
    """"Add 2[coin] to your allowance for each SHOP you draft from this CLOISTER"."""
    if ctx_room is not None and ctx_room.category == "shop" and _drafted_from(game, room):
        _grant(game, "allowance", ALLOWANCE_PER_SHOP)
