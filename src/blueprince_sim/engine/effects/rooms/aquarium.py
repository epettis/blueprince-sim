"""Aquarium upgrades: the Starfish's permanent star, the Electric Eel's power.

Implemented:
  - grant_star -- +1 permanent star (game.state.stars) each time the
    Starfish Aquarium is drafted, regardless of how many times it was
    drafted before. Fires on ON_PLACE (draft); entering the room is not
    required.
  - ``Capability.POWER_SOURCE`` on the Electric Eel Aquarium, which seeds
    ``engine/power.py``'s propagation from wherever it is placed
    (docs/power.md). Registered on the one variant, not the family: the base
    Aquarium and the Goldfish/Starfish upgrades generate no power.

The star this grants is spent on the night sky like any other: stars are the
count an Observatory's sky resolves against (engine/constellations.py), so a
Starfish Aquarium drafted before the sky is viewed enriches it.

"AQUARIUM is every color of room" is not handled here: it lives on
``Room.categories`` / ``Room.is_category()`` (engine/model.py), out of scope
for this room's star grant specifically.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

STARS_PER_DRAFT = 1  # starfish_aquarium__ix3's own effect_text: "...+1[star]"

provides("electric_eel_aquarium__ix4", Capability.POWER_SOURCE)


@room_hook("starfish_aquarium__ix3", Hook.ON_PLACE)
def grant_star(game, room, ctx_room) -> None:
    """"The Starfish Aquarium immedately gives the player 1 star whenever it
    is drafted. Entering the Starfish Aquarium is not necessary to gain the
    star." (blueprince.wiki.gg/wiki/Aquarium/Upgrades)
    """
    game.state.stars += STARS_PER_DRAFT
