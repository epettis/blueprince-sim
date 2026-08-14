"""Telescope: gated out of the spawn pool unless the player holds at least 1
star at the START of the day.

Wiki (blueprince.wiki.gg/wiki/Telescope, "How to obtain"): "The Telescope is
only present in the item pool if the player has at least 1 star at start the
day, and cannot spawn otherwise." Reads ``cfg.stars`` (the carried-over
start-of-day total, seeded before anything today could grow it), never
``state.stars`` -- a star earned mid-day (Observatory/Starfish Aquarium) must
not un-gate the Telescope until TOMORROW's start-of-day count reflects it.

The item's other use -- unlocking Planetarium planets -- lives in
:mod:`engine.special_items` (``use_telescope_in_planetarium``) and
:mod:`engine.effects.rooms.planetarium`, since that mechanic touches the
Planetarium room and the planet table, not just the item's own gate.
"""

from __future__ import annotations

ITEM_ID = "telescope"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``telescope`` to ``gated`` unless ``cfg.stars >= 1``."""
    if getattr(cfg, "stars", 0) < 1:
        gated.append(ITEM_ID)


def held(state) -> bool:
    """True while a Telescope is currently in inventory.

    Referenced by Game.can_use_telescope_planetarium via ``ITEM_ID``/
    ``held`` rather than the bare string, the same avoid-the-literal shape
    as royal_scepter.held/keycard.held.
    """
    return state.inventory.get(ITEM_ID, 0) > 0
