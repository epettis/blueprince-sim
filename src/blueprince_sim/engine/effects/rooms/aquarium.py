"""Starfish Aquarium: a permanent star on every draft.

Implemented:
  - grant_star -- +1 permanent star (game.state.stars) each time the
    Starfish Aquarium is drafted, regardless of how many times it was
    drafted before. Fires on ON_PLACE (draft); entering the room is not
    required.

Not modelled:
  - The telescope/constellation system that stars gate: no activation
    source exists in the sim for southern_cross_active / draxus_active, so
    the accumulated star count has nothing downstream to spend it on here.
  - "AQUARIUM is every color of room": a separate ruled `counts_as_all_colors`
    flag, out of scope for this room's star grant.
"""

from __future__ import annotations

from .. import Hook, room_hook

STARS_PER_DRAFT = 1  # starfish_aquarium__ix3's own effect_text: "...+1[star]"


@room_hook("starfish_aquarium__ix3", Hook.ON_PLACE)
def grant_star(game, room, ctx_room) -> None:
    """"The Starfish Aquarium immedately gives the player 1 star whenever it
    is drafted. Entering the Starfish Aquarium is not necessary to gain the
    star." (blueprince.wiki.gg/wiki/Aquarium/Upgrades)
    """
    game.state.stars += STARS_PER_DRAFT
