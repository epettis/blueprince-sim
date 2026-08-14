"""Prism Key: a special key that unlocks a locked door in a Bedroom,
Hallway, Green Room, Shop, or Red Room, colour-restricting the resulting
draft to that room's colour (wiki: "will not fit locks in rooms that are
purely blue or black"). The fit is about the room the key is used IN --
Phase.LOCK_PENDING always parks on the room the player is standing in
(``cell``, see game.py::_lock_pending_target) -- never a free player pick.

Reuses the colour-restricted deal the Secret Passage already built
(Game._deal_and_cache(colour=...), draft.py::room_draftable's colour gate)
via Game.use_special_key_at_lock -> Game._resolve_lock_open(colour=...) ->
Game._continue_draft(colour=...), which skips straight to the restricted
deal instead of detouring through Phase.COLOUR_PENDING's five-way player
pick: the colour here is never a choice, so that phase would be the wrong
tool -- it exists to let the player pick, and there is nothing to pick.

In the six rooms that carry more than one of the five colours (the five
Aquarium variants and the Maid's Chamber -- see ``fitting_colours``), the
wiki states "the color is chosen at random from all valid choices" (owner
ruling: taken literally over the same sentence's "may be rechosen by
unhovering and rehovering" clause, which has no equivalent in this
turn-based sim). Resolved with a single ``rng.choice`` draw on its own
"prism_key_colour" label -- a fresh label, so this draw cannot perturb any
other feature's substream.

Consumed on use and re-added to today's spawn pool the same day
(``remove(state, ITEM_ID, consumed=False)`` -- see special_items.remove:
consumed=False means the id is never appended to state.special.removed,
the only thing ``_is_available`` consults, so it is spawn-eligible again
immediately), matching the wiki: "consumes it and readds it to the item
pool, allowing it to be obtained again in the same day."

NOT MODELLED (named gaps, not oversights):
- Special key warping: this sim's Game._continue_draft always deals
  immediately once a door opens, so a Prism Key used on a door with no
  following draft (e.g. a Great Hall side door) has nowhere to park its
  still-pending colour restriction for a later, unrelated draft elsewhere
  in the house -- the wiki's "the effect ... will apply to the next draft
  initiated anywhere in the house" has no home in this model.
- The Silver Key's cross/t-layout bias on a door opened with the Prism Key:
  both are use_special_key_at_lock rows, and only one row can be chosen per
  lock in this sim, so the two can never combine here regardless of any
  wiki interaction between them.
"""

from __future__ import annotations

ITEM_ID = "prism_key"


def held(state) -> bool:
    """True while at least one Prism Key is in inventory."""
    from ...special_items import has
    return has(state, ITEM_ID)


def fitting_colours(game, cell: int) -> tuple[str, ...]:
    """The colour category ids (engine.draft.COLOUR_CATEGORIES order) the
    room at ``cell`` carries -- empty for a room that is purely blue/black
    (or any other non-colour category), which is exactly the wiki's "will
    not fit" case. More than one entry only for the six rooms carrying
    multiple colours (the five Aquarium variants and the Maid's Chamber).

    Imports draft.COLOUR_CATEGORIES lazily: engine.draft imports
    engine.special_items at module load time, and engine.special_items'
    own effects.items import chain would otherwise import this module
    before engine.draft finishes loading -- the same cycle every other
    lazy ``from ...special_items import`` in this items/ package dodges.
    """
    from ...draft import COLOUR_CATEGORIES
    room = game.registry.rooms[game.state.grid[cell]]
    return tuple(c for c in COLOUR_CATEGORIES if room.is_category(c))


def fits(game, cell: int, direction: int) -> bool:
    """The Prism Key fits a locked door only when the room the key is used
    IN (``cell``) carries at least one of the five colour categories.
    ``direction`` is unused -- the fit is a property of the FROM room, not
    the door's far side, unlike master_key/silver_key.fits (any standard
    locked door, direction-independent for a different reason)."""
    return bool(fitting_colours(game, cell))


def consume_and_resolve_colour(game, cell: int) -> str:
    """Spend one held Prism Key (re-added to today's pool, not gone for the
    day -- see module docstring) and resolve which colour this use
    restricts the draft to: the room's one fitting colour, or -- in a
    multi-colour room -- a single uniform draw on the "prism_key_colour"
    rng label (owner ruling, see module docstring).

    Caller (Game.use_special_key_at_lock) must have already confirmed
    ``can_use_special_key_at_lock("prism_key")``, so ``fitting_colours``
    is guaranteed non-empty here.
    """
    from ...special_items import remove
    colours = fitting_colours(game, cell)
    assert colours, "prism_key used on a non-fitting room"
    remove(game.state, ITEM_ID, consumed=False)
    if len(colours) == 1:
        return colours[0]
    return game.rng.choice("prism_key_colour", list(colours))
