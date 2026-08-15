"""Tomb: each Dead End drafted in the house, including the Tomb itself,
spreads 5 coins into it.
"""

from __future__ import annotations

from ...grid import is_dead_end_mask
from .. import Hook, room_hook

COINS_PER_DEAD_END = 5


@room_hook("tomb", Hook.ON_DRAFT_ROOM)
def spread_coins_for_dead_ends(game, room, ctx_room) -> None:
    if (ctx_room is not None and ctx_room.is_dead_end_capable
            and is_dead_end_mask(game.state.draft_hook_orientation)):
        game.state.coins = max(0, game.state.coins + COINS_PER_DEAD_END)
