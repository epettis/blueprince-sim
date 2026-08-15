"""Observatory: a permanent star on every draft, and the night sky those stars buy.

Implemented:
  - grant_star -- +1 permanent star (game.state.stars) each time the
    Observatory is drafted, regardless of how many times it was drafted
    before. Fires on ON_PLACE (draft), not on entry. Uncapped: no published
    cap exists, so capping it would be an invention. This is a known
    self-amplifying loop (draft Observatory -> +1 star -> richer sky -> more
    resources -> more drafts), recorded in docs/rooms.md.
  - Capability.NIGHT_SKY -- registers that this room's telescope can view a
    night sky, which is what Game.can_view_night_sky asks. Registered as a
    capability rather than tested by room id so no engine module has to
    branch on "observatory", the same shape as Capability.COMMERCE.

Not modelled:
  - One constellation stays inert: the Spiral of Stars' word growth, which
    has no primitive to hang off (data/constellations.json's blocked_on).
    The other twelve activate -- five pay a resource, and the Southern
    Cross, Draxus, The Twins, Farmer's Apple, The Sail, Florealis and the
    Ink Well write through constellations.py::apply_effect.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

STARS_PER_DRAFT = 1  # observatory's own effect_text: "+1[star]"

provides("observatory", Capability.NIGHT_SKY)


@room_hook("observatory", Hook.ON_PLACE)
def grant_star(game, room, ctx_room) -> None:
    """"When the Observatory is drafted, one star is immediately added to the
    player's star count." (blueprince.wiki.gg/wiki/Observatory)
    """
    game.state.stars += STARS_PER_DRAFT
