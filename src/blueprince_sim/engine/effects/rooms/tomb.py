"""Tomb: each Dead End drafted in the house, the Tomb itself included,
spreads 5 coins into the Tomb, collected when the player walks in.

This is a spread in the sense docs/rooms.md defines: the coins are parked in
``GameState.spread_pending`` and paid out by ``Game._collect_spread`` on
arrival, not granted at the moment of the draft. The Tomb is an outer-pool
room with no grid cell, so they key on ``OFF_GRID_CELL`` -- the ``-1``
sentinel the rest of the outer-room pipeline
already uses (``Game._choose_outer``'s ``target_cell``, ``roll_room_items``'s
``cell``). ``Game.travel_to`` drains that key on every arrival at the drafted
outer room, so coins parked by Dead Ends drafted after a first visit are
collected on the next one.

The trigger is each Dead End's *draft*, which makes the effect draft-ordered:
a Dead End drafted before the Tomb pays nothing, there being no Tomb on the
estate to spread into.

**No Conference Room redirect applies.** These coins are the Tomb's own
contents accumulating in it rather than a spread reaching out to other cells --
the same distinction ``Game._park_florealis_gems`` draws -- and nothing
published puts the Tomb among the spreaders a Conference Room absorbs.
"""

from __future__ import annotations

from ...grid import is_dead_end_mask
from .. import Hook, room_hook

COINS_PER_DEAD_END = 5

#: ``GameState.spread_pending`` key for payouts parked in the drafted outer
#: room, which occupies no grid cell. Read by ``Game.travel_to``.
OFF_GRID_CELL = -1


@room_hook("tomb", Hook.ON_DRAFT_ROOM)
def spread_coins_for_dead_ends(game, room, ctx_room) -> None:
    """Park 5 coins in the Tomb for the Dead End just drafted.

    ``ctx_room`` is that just-drafted room, and it may be the Tomb itself: the
    Tomb counts among the Dead Ends it collects for, so its own draft parks the
    first 5 coins and a Tomb entered with nothing else drafted still pays out.

    "Dead End" is the drafted orientation having exactly one door on a room
    whose card can print that shape (``Room.is_dead_end_capable`` plus
    ``GameState.draft_hook_orientation``), not ``Room.layout`` alone -- a
    Greenhouse drafted in a two-door corner rotation is not one.
    """
    if (ctx_room is not None and ctx_room.is_dead_end_capable
            and is_dead_end_mask(game.state.draft_hook_orientation)):
        game.state.spread_pending.setdefault(OFF_GRID_CELL, []).append(
            ("coins_exact", COINS_PER_DEAD_END))
