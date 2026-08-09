"""Treasure Trove: each draft pays coins for every pile accumulated so far.

The room permanently gains a 5-coin pile per draft, and every draft collects
the whole surface -- so draft 1 pays 5, draft 2 pays 10, draft N pays 5*N,
capped at a payout of 5*32=160 once 32 piles have accumulated (wiki: "to a
maximum of 32 piles (160 Gold Coin total)"). The cap bounds what a single
draft is worth, NOT what the room earns over the attempt: the first 32
drafts alone total 5 * (1+2+...+32) = 2640 coins.

``state.draft_counts`` tracks cumulative attempt-wide draft counts keyed by
root base room id, carried across days by DayChain and incremented in
``Game._place_room`` immediately BEFORE the ON_PLACE hook fires -- so the
count read here already includes this draft. Reusing it means the payout is
a pure function of that count, so it cannot double-count however many times
the room is later entered or re-entered.
"""

from __future__ import annotations

from ...upgrades import root_base_id
from .. import Hook, room_hook

COINS_PER_PILE = 5
MAX_PILES = 32


@room_hook("treasure_trove", Hook.ON_PLACE)
def pay_for_accumulated_piles(game, room, ctx_room) -> None:
    root_id = root_base_id(game.registry, room)
    count = game.state.draft_counts.get(root_id, 0)
    piles = min(count, MAX_PILES)
    game.state.coins = max(0, game.state.coins + COINS_PER_PILE * piles)
