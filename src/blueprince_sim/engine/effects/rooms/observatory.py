"""Observatory: a permanent star on every draft.

Implemented:
  - grant_star -- +1 permanent star (game.state.stars) each time the
    Observatory is drafted, regardless of how many times it was drafted
    before. Fires on ON_PLACE (draft), not on entry.

Not modelled:
  - The telescope/constellation system that stars gate: no activation
    source exists in the sim for southern_cross_active / draxus_active, so
    the accumulated star count has nothing downstream to spend it on here.
"""

from __future__ import annotations

from .. import Hook, room_hook

STARS_PER_DRAFT = 1  # observatory's own effect_text: "+1[star]"


@room_hook("observatory", Hook.ON_PLACE)
def grant_star(game, room, ctx_room) -> None:
    """"When the Observatory is drafted, one star is immediately added to the
    player's star count." (blueprince.wiki.gg/wiki/Observatory)
    """
    game.state.stars += STARS_PER_DRAFT
