"""Mechanarium: seeds its diagonal-compartment count, and provides its
container-kinds overlay.

Wiki (blueprince.wiki.gg/wiki/Mechanarium): once the four cardinal doors are
accounted for (draft.py's ``_mechanarium_orientation``), further Mechanical
rooms open up to four diagonal compartments instead of doors. Each
compartment is a closed container with its own deterministic, priority-
ordered loot -- not a room -- so it is modelled as a container at the
Mechanarium's cell (engine/special_items.py's ``containers.kinds``
``mechanarium_lever``/``mechanarium_key``/``mechanarium_upgrade``/
``mechanarium_sanctum``), opened one at a time through the ordinary
OPEN_CONTAINER_ACTION rather than as a fifth grid doorway.

This module fixes the per-placement compartment COUNT via the Mechanarium's
own ON_PLACE hook, and answers which compartment kinds are currently
openable via its ``provides_containers`` overlay -- registry.special.
containers["rooms"] carries no static Mechanarium entry, since the count is
per-placement, not a fixed per-room number. The loot chains themselves live
in special_items.py alongside the rest of the container system.

Not modelled: which physical corner each compartment door occupies -- the
sim tracks only the deterministic open ORDER (1st/2nd/3rd/4th), which is
enough to reproduce the wiki's fixed loot-per-position table.
"""

from __future__ import annotations

from .. import Hook, provides_containers, room_hook
from ... import special_items

# The Mechanarium's diagonal-compartment kinds, in the wiki's fixed open
# order (1st/2nd/3rd/4th corner). Each is a containers.kinds entry in
# data/special_items.json with its own deterministic, priority-chain loot.
_COMPARTMENT_KINDS: tuple[str, ...] = (
    "mechanarium_lever", "mechanarium_key", "mechanarium_upgrade", "mechanarium_sanctum",
)


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


@provides_containers("mechanarium")
def compartment_kinds(state, registry, cell: int) -> dict[str, int]:
    """This Mechanarium's openable compartment kinds at ``cell``, one each, in order.

    Sliced from ``_COMPARTMENT_KINDS`` by the count
    ``seed_mechanarium_compartments`` fixed for this cell at draft time.
    """
    n = state.special.mechanarium_compartments.get(cell, 0)
    return {kind: 1 for kind in _COMPARTMENT_KINDS[:n]}
