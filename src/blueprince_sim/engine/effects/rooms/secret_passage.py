"""Secret Passage / Spare Secret Passage: colour-selective drafting.

Wiki (blueprince.wiki.gg/wiki/Secret_Passage): "If a book is pulled from the
bookshelf, it will open the passage to a hidden door of the chosen color.
Drafting from this door will only draw floorplans of the same color."

The mechanism lives outside this module, split across the two sites that
already own drafting and door-opening: Game.open_door detects a doorway
whose from-room is one of these two ids and, on its first opening, enters
Phase.COLOUR_PENDING instead of dealing (state.pending_colour_cell/
_direction park the doorway); Game.choose_colour resolves the pick and
finishes the deal through draft.deal_draft(colour=...), which threads the
restriction into every slot via draft.room_draftable (see that module's
docstring). This module registers the ON_DRAFT_FROM handler both ids need to
count as "modelled" for the divergence audit (tools/validate_data.py), and
uses that hook site for a real regression check: by the time ON_DRAFT_FROM
fires, the doorway's hand already exists, so this is the first point able to
confirm the deal actually honoured the chosen colour.
"""

from __future__ import annotations

from .. import Hook, room_hook


def _validate_hand(game, room) -> None:
    """Every option dealt from a colour-locked doorway matches its colour.

    Defensive self-check for draft.py's colour threading (DraftContext.colour
    -> room_draftable) -- a regression there would otherwise only surface as
    a silent rules divergence rather than a loud failure. A no-op for a hand
    with no colour restriction (e.g. this doorway was already dealt and is
    being reopened, or -- defensively -- pending is somehow absent).
    """
    pending = game.state.pending
    if pending is None or pending.colour is None:
        return
    for opt in pending.options:
        dealt = game.registry.rooms[opt.room_idx]
        assert dealt.is_category(pending.colour), (
            f"{room.id} dealt {dealt.id!r}, not a {pending.colour!r} room"
        )


@room_hook("secret_passage", Hook.ON_DRAFT_FROM)
def validate_secret_passage_hand(game, room, ctx_room) -> None:
    """Every option dealt from the Secret Passage's chosen colour door matches that colour."""
    _validate_hand(game, room)


@room_hook("spare_secret_passage__ix138", Hook.ON_DRAFT_FROM)
def validate_spare_secret_passage_hand(game, room, ctx_room) -> None:
    """"The effects of the Spare Secret Passage ... are identical to the originals in each case."""
    _validate_hand(game, room)
