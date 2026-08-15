"""Shelter: negates the effects of the next 3 red rooms drafted.

Forward-looking and counted in drafts: a red room already on the board when
the Shelter is drafted keeps its own penalty, no matter when that penalty
actually resolves.
"""

from __future__ import annotations

from .. import Hook, room_hook

NEGATIONS = 3


@room_hook("shelter", Hook.ON_PLACE)
def negate_next_red_rooms(game, room, ctx_room) -> None:
    """Grant 3 negation charges and freeze out every room already drafted.

    ``game.placed_ids`` already holds every room drafted so far, the Shelter
    itself included (``Game._choose_outer`` adds it before firing ON_PLACE),
    so snapshotting it here can never exclude the Shelter's own future
    charges. ``tier1._red_negated`` reads ``game.shelter_excluded_ids`` back
    to keep an already-drafted red room's penalty live even while charges
    remain.
    """
    game.red_negations += NEGATIONS
    game.shelter_excluded_ids = frozenset(game.placed_ids)
