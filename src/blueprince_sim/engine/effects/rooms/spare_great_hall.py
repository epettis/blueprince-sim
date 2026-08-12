"""Spare Great Hall: one of three published prize bundles, rolled on entry.

The room's own effect text reads "7 Locked Doors", but the wiki gives it no
side doorways, no Antechamber lever and no Upgrade Disk, and says its far
door is not necessarily locked -- so none of that effect has a
grid-granularity representation here. What it does have is a prize alcove
whose contents are published, and that is what this grants.

Wiki (Spare Room/Upgrades/Spare Hall Upgrades): "Exactly one alcove on each
side contains a prize... Prizes include: Four cyan gems / A basic key, a
cyan gem and a pile of 5 coins / Four piles of 5 coins, for a total of 20
coins."

Gem colour is not modelled anywhere in this engine -- gems are one plain
resource -- so a cyan gem is granted as a gem.
"""

from __future__ import annotations

from .. import Hook, room_hook

ROOM_ID = "spare_great_hall__ix139"

# The three published bundles, as (gems, keys, coins). One is drawn per entry.
PRIZE_BUNDLES = (
    (4, 0, 0),   # four cyan gems
    (1, 1, 5),   # a basic key, a cyan gem and a pile of 5 coins
    (0, 0, 20),  # four piles of 5 coins
)

RNG_LABEL = "spare_great_hall_prize"  # this room's own RNG substream label


@room_hook(ROOM_ID, Hook.ON_ENTER)
def grant_prize(game, room, ctx_room) -> None:
    """Grant one uniformly drawn prize bundle from the room's alcove."""
    gems, keys, coins = game.rng.choice(RNG_LABEL, list(PRIZE_BUNDLES))
    st = game.state
    st.gems += gems
    st.keys += keys
    st.coins += coins
