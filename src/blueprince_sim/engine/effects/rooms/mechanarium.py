"""Mechanarium: seeds its diagonal-compartment count at draft time.

Wiki (blueprince.wiki.gg/wiki/Mechanarium): once the four cardinal doors are
accounted for (draft.py's ``_mechanarium_orientation``), further Mechanical
rooms open up to four diagonal compartments instead of doors. Each
compartment is a closed container with its own deterministic, priority-
ordered loot -- not a room -- so it is modelled as a container at the
Mechanarium's cell (engine/special_items.py's ``containers.kinds``
``mechanarium_lever``/``mechanarium_key``/``mechanarium_upgrade``/
``mechanarium_sanctum``), opened one at a time through the ordinary
OPEN_CONTAINER_ACTION rather than as a fifth grid doorway.

This module only fixes the per-placement compartment COUNT, via the
Mechanarium's own ON_PLACE hook; the loot chains themselves live in
special_items.py alongside the rest of the container system.

Not modelled: which physical corner each compartment door occupies -- the
sim tracks only the deterministic open ORDER (1st/2nd/3rd/4th), which is
enough to reproduce the wiki's fixed loot-per-position table.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ... import special_items


@room_hook("mechanarium", Hook.ON_PLACE)
def seed_compartments(game, room, ctx_room) -> None:
    """Fix this Mechanarium's diagonal-compartment count, once, at draft time.

    Fires after Game._place_room has already written the grid and the
    cardinal door mask for this cell, so
    special_items.seed_mechanarium_compartments reads both as their final,
    frozen values.
    """
    cell = game.room_cells.get(room.id)
    if cell is not None:
        special_items.seed_mechanarium_compartments(game, cell)
