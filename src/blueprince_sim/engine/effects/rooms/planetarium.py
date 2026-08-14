"""Planetarium: the Telescope's second use permanently upgrades this room.

Wiki (Telescope, "another use"): unlocking a planet "confers permanent
benefits to the room." Once a planet is unlocked (GameState.planetarium_planets,
SAVE-scoped, carried by DayChain), the room carries that planet's payload
every day going forward -- the SAME wiki text ("permanent benefits") that
justifies re-applying it, not just applying it once.

The unlock action itself (engine/special_items.py::use_telescope_in_planetarium)
applies THAT day's immediate effect, since it fires after this room's own
ON_ENTER already ran. This module re-applies the same payloads on every
LATER day's placement/first entry, reading data/special_items.json's
planetarium_planets table generically -- neither hook here hardcodes which
planet is which, only the payload "kind" vocabulary (also shared with
special_items.py's container/mail-package grant resolution).
"""

from __future__ import annotations

from .. import Hook, room_hook
from ... import special_items


def _unlocked_payloads(game) -> list[dict]:
    """Payload dicts for every planet this save has already unlocked."""
    unlocked = set(game.state.planetarium_planets)
    return [
        planet["payload"]
        for planet in game.registry.special.planetarium_planets
        if planet["id"] in unlocked
    ]


@room_hook("planetarium", Hook.ON_PLACE)
def seed_dig_bonus(game, room, ctx_room) -> None:
    """Veia's payload (a permanent dig spot) applies from this placement on.

    Additive into state.special.veia_dig_bonus at this Planetarium's own
    cell -- the same generic per-cell overlay the Cloister of Veia and the
    spread_dig_spots experiment effect already share (engine/special_items.py
    reads ``room.items.dig_spots + veia_dig_bonus.get(cell, 0)`` at dig time).
    """
    cell = game.room_cells.get(room.id)
    if cell is None:
        return
    for payload in _unlocked_payloads(game):
        if payload.get("kind") == "dig_bonus":
            bonus = game.state.special.veia_dig_bonus
            bonus[cell] = bonus.get(cell, 0) + payload.get("amount", 1)


@room_hook("planetarium", Hook.ON_ENTER)
def grant_unlocked_payloads(game, room, ctx_room) -> None:
    """Fennmora/Mamora/Mora's payloads (Apple/Ivory Die/Prism Key) re-grant
    on every day's first entry, once their planet is unlocked.

    "container" (Dauja) and "dig_bonus" (Veia) payloads are excluded here:
    the Trunk is a live read (special_items._planetarium_container_kinds),
    and the dig spot is seeded once per placement by seed_dig_bonus above --
    neither is a repeat-grant.
    """
    state, registry = game.state, game.registry
    grants = [p for p in _unlocked_payloads(game) if p.get("kind") in ("food", "dice", "item")]
    if grants:
        special_items.apply_grant_list(state, registry, game, grants)
