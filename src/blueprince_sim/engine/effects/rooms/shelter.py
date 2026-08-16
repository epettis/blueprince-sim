"""Shelter: negates the effects of the next 3 red rooms drafted.

Protection is decided at draft time and never revisited: the first three red
rooms drafted after the Shelter each claim one of its charges the moment they
are drafted, and only those three rooms are ever protected. A red room already
on the board when the Shelter is drafted is never offered a charge, so it keeps
its own penalty however much later that penalty resolves.
"""

from __future__ import annotations

from .. import Hook, room_hook

NEGATIONS = 3


@room_hook("shelter", Hook.ON_PLACE)
def negate_next_red_rooms(game, room, ctx_room) -> None:
    """Grant 3 unclaimed negation charges.

    Only rooms drafted after this fire can claim them: :func:`on_room_drafted`
    is the sole claimant and reads ``game.red_negations``, which is 0 until
    here. The Shelter itself is a blueprint room, not a red one, so its own
    draft claims nothing.
    """
    game.red_negations += NEGATIONS


def on_room_drafted(game, room) -> None:
    """Claim one charge for ``room`` if it is red and a charge is unclaimed.

    Called from ``Game._place_room`` on every grid draft, before the drafted
    room's own ON_PLACE fires, so a placement-time red penalty (Maid's
    Chamber's anti-luck, the Weight Room's step halving) already finds its own
    claim in place. No outer room is red, so the off-grid draft path needs no
    matching call.

    The claim is keyed on ``room.id`` rather than
    ``upgrades.root_base_id``: the room claiming here and the room whose
    penalty ``tier1._red_negated`` later resolves are the same ``Room``, and a
    red upgrade variant (``cloister_of_draxus__ix36``, ``empty_closet__ix41``)
    carries its penalty on its own record, so both sides already agree on the
    variant's own id. Folding a variant onto its base would instead let one
    claim cover two distinct rooms.

    A charge is claimed whether or not the claimed room's penalty ever
    resolves -- an unblown Darkroom fuse keeps its claim rather than returning
    it. Returning it would make the fourth red room's protection depend on
    which penalties happened to resolve first, which is the resolution-order
    dependence draft-time claiming exists to remove.
    """
    if game.red_negations > 0 and room.is_category("red"):
        game.red_negations -= 1
        game.shelter_protected_ids.add(room.id)
