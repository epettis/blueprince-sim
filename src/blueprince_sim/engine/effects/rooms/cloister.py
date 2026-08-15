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
  - cloister_of_dauja__ix31 -- 2 stars for each of six specific "room with an
    animal" ids drafted from this Cloister. The membership list is an ad-hoc
    wiki enumeration (a mounted fish and stuffed plushies qualify, taxidermy
    elsewhere does not), so it is carried as the has_animal flag on those six
    records rather than derived from any semantic rule.
  - cloister_of_veia__ix32 -- +8 dig spots (additive) in a room with a
    fireplace drafted from this Cloister. The fireplace rooms carry a static
    has_fireplace flag; the Dining Room's fireplace instead depends on the
    cell it lands on (see grant_dig_bonus_for_fireplace_rooms).
  - cloister_of_joya__ix30 -- +5 steps, permanently and cumulatively, to every
    one of the five Main Course dishes for each Kitchen/Pantry/Furnace
    drafted from this Cloister (special_items.py::_dish_base_steps reads
    the running total off GameState.main_course_bonus). "Permanently" is read
    as per-attempt (carried by DayChain, cleared on attempt wrap), the same
    shape as allowance/stars -- an owner-flagged assumption, since the wiki
    never says "across the save".

Not modeled: nothing left in this file; see each handler's own docstring for
what it does and does not cover.
"""

from __future__ import annotations

from ...grid import E, N, W, is_center_column, is_dead_end_mask, rank_of
from ...locks import DOOR_SEALED, segment_key
from .. import Hook, room_hook
from ..tier1 import _grant

ANTECHAMBER_CELL = 42  # rank 9, center column

# blueprince.wiki.gg/wiki/Cloister: "Specifically, 6 luck is added per
# activation." The record's own effect_text carries no number.
LUCK_PER_GREEN_ROOM = 6
DICE_PER_DEAD_END = 4  # cloister_of_draxus__ix36, per meta.glyph_resolution icon "dice"
ALLOWANCE_PER_SHOP = 2  # cloister_of_lydia__ix34, from its own effect_text
STARS_PER_ANIMAL_ROOM = 2  # cloister_of_dauja__ix31, from its own effect_text
DIG_BONUS_PER_FIREPLACE_ROOM = 8  # cloister_of_veia__ix32, from its own effect_text
MAIN_COURSE_BONUS_PER_ROOM = 5  # cloister_of_joya__ix30, from its own effect_text
# Kitchen/Pantry/Furnace, per Joya's own effect_text; matched on id or
# variant_of the same way the Chapel's Keeper of Tithes matches "chapel".
_JOYA_TRIGGER_IDS = frozenset({"kitchen", "pantry", "furnace"})

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


def _dining_room_has_fireplace(cell: int) -> bool:
    """Cloister of Veia's Dining Room case: fireplace in the centre columns or
    on Rank 9; windows (no fireplace) on the wings or Rank 1.

    Both conditions are literal ORs over the cell the room lands on: a centre-
    column cell qualifies unless it is also Rank 1, and Rank 9 qualifies even
    on a wing, since it is named as its own alternative alongside the centre
    columns rather than as a subset of them.
    """
    return (is_center_column(cell) and rank_of(cell) != 1) or rank_of(cell) == 9


@room_hook("cloister_of_rynna__ix29", Hook.ON_DRAFT_ROOM)
def raise_luck_for_green_rooms(game, room, ctx_room) -> None:
    """"Raise your LUCK with each GREEN ROOM you draft from this CLOISTER"."""
    if ctx_room is not None and ctx_room.is_category("green") and _drafted_from(game, room):
        _grant(game, "luck", LUCK_PER_GREEN_ROOM)


@room_hook("cloister_of_mila__ix33", Hook.ON_DRAFT_ROOM)
def mark_bedroom_bonus_item(game, room, ctx_room) -> None:
    """"Find an extra item in each BEDROOM you draft from this CLOISTER".

    Marks the drafted Bedroom's cell so Game._enter grants the extra item
    once the player actually walks in.
    """
    if ctx_room is not None and ctx_room.is_category("bedroom") and _drafted_from(game, room):
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
    if ctx_room is not None and ctx_room.is_category("blackprint") and _drafted_from(game, room):
        _open_random_antechamber_door(game)


@room_hook("cloister_of_draxus__ix36", Hook.ON_DRAFT_ROOM)
def grant_dice_for_dead_ends(game, room, ctx_room) -> None:
    """"Gain 4[dice] for each DEAD-END room ... you draft from this CLOISTER"
    (see the module docstring for the "WILL draft" gap).

    "Dead End" is the room's actual drafted orientation (exactly one door)
    on a room whose card is even capable of a Dead End shape, not its frozen
    Room.layout -- a room whose alt_layouts include a multi-door shape (the
    Greenhouse's corner rotations) does not pay this when drafted in that
    orientation, and the Mechanarium's per-placement derived mask never
    counts even when it happens to land on one door (Room.is_dead_end_capable).
    """
    if (ctx_room is not None and ctx_room.is_dead_end_capable
            and is_dead_end_mask(game.state.draft_hook_orientation)
            and _drafted_from(game, room)):
        _grant(game, "dice", DICE_PER_DEAD_END)


@room_hook("cloister_of_lydia__ix34", Hook.ON_DRAFT_ROOM)
def raise_allowance_for_shops(game, room, ctx_room) -> None:
    """"Add 2[coin] to your allowance for each SHOP you draft from this CLOISTER"."""
    if ctx_room is not None and ctx_room.is_category("shop") and _drafted_from(game, room):
        _grant(game, "allowance", ALLOWANCE_PER_SHOP)


@room_hook("cloister_of_dauja__ix31", Hook.ON_DRAFT_ROOM)
def grant_stars_for_animal_rooms(game, room, ctx_room) -> None:
    """"Gain 2[stars] for each room with an animal you draft from this CLOISTER".

    Fires once per draft event regardless of what else a room "counts as"
    elsewhere (the Bunk Room counts as two Bedrooms for house-counting effects,
    but that is a separate mechanism -- this handler grants exactly once per
    room actually drafted, so the Bunk Room pays 2 stars here, never 4).
    """
    if (ctx_room is not None and ctx_room.has_animal
            and _drafted_from(game, room)):
        _grant(game, "stars", STARS_PER_ANIMAL_ROOM)


@room_hook("cloister_of_veia__ix32", Hook.ON_DRAFT_ROOM)
def grant_dig_bonus_for_fireplace_rooms(game, room, ctx_room) -> None:
    """"Find 8 dirt piles in each room with a fireplace you draft from this
    CLOISTER".

    Additive on top of the room's own items.dig_spots (the Furnace's baseline
    1 reaches 9, not a flat 8). The fireplace rooms carry a static
    has_fireplace flag; the Dining Room instead only has a fireplace
    in the centre columns or on Rank 9 (windows elsewhere), so its case is
    decided against the cell it actually lands on rather than the flag.
    """
    if ctx_room is None or not _drafted_from(game, room):
        return
    is_dining_room = ctx_room.id == "dining_room" or ctx_room.variant_of == "dining_room"
    cell = game.state.pending.target_cell
    qualifies = (_dining_room_has_fireplace(cell) if is_dining_room
                 else ctx_room.has_fireplace)
    if qualifies:
        bonus = game.state.special.veia_dig_bonus
        bonus[cell] = bonus.get(cell, 0) + DIG_BONUS_PER_FIREPLACE_ROOM


@room_hook("cloister_of_joya__ix30", Hook.ON_DRAFT_ROOM)
def raise_main_course_for_kitchen_pantry_furnace(game, room, ctx_room) -> None:
    """"Permanently add an extra 5[steps] to the MAIN COURSE for each KITCHEN,
    PANTRY, or FURNACE you draft from this CLOISTER".

    Raises every one of the five main-course dishes by 5, cumulatively, each
    time this fires (special_items.py::_dish_base_steps reads the running
    total); never touches the Lunch Box. "Permanently" is read as per-attempt,
    the same carry-over shape as allowance/stars (GameState.main_course_bonus).
    """
    if (ctx_room is not None and _drafted_from(game, room)
            and (ctx_room.id in _JOYA_TRIGGER_IDS or ctx_room.variant_of in _JOYA_TRIGGER_IDS)):
        game.state.main_course_bonus += MAIN_COURSE_BONUS_PER_ROOM
