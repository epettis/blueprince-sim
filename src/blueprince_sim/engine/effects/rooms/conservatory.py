"""Conservatory: drafting it re-rolls the rarity of 3 random undealt deck cards.

A one-time effect fired when the Conservatory itself is drafted: 3 random
undealt deck cards each roll a fresh rarity (uniform over the 4 rarities)
via the dedicated ``conservatory_reroll`` RNG substream, and changed cards
move to the new rarity's deck of the same free/gem class at a random
undealt position.
"""

from __future__ import annotations

from ...decks import reroll_random_rarities
from .. import Hook, room_hook

REROLL_COUNT = 3


@room_hook("conservatory", Hook.ON_PLACE)
def reroll_deck_rarities(game, room, ctx_room) -> None:
    reroll_random_rarities(game.state, game.rng, count=REROLL_COUNT)
