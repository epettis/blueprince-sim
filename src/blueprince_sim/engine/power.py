"""Steam power over the placed grid: which rooms are carrying power right now.

Owner ruling, which this module implements verbatim:

    "The house isn't powered. A room is powered. A room is powered if it
    shares a doorway with another powered room."

So power is plain connectivity over the door graph, seeded at the power
sources and conducted only by rooms that carry power. It is transitive and
branching, and it is derived from the grid rather than latched, because
placing one room can light up a whole chain at once.

**Which rooms carry power** is ``Room.powered`` (``flags.powered`` in
rooms.json): the datamined sheet's power-room column, extended in
``tools/supplemental_rooms.json`` to the three Red Rooms the sheet never
covered (Darkroom, Weight Room, Furnace). Sources, connectors and powerable
rooms all carry it -- the wiki's three-way split matters only to what a room
*does* once powered, which is per-room work this module deliberately does not
do. ``docs/power.md`` owns the room lists and the wiki citations.

**Which rooms are sources** is ``Capability.POWER_SOURCE``, registered by each
source's own module under ``effects/rooms/`` the same way every other
capability is, so no engine module names a source's room id.
``tools/validate_data.py`` checks each registered source also carries
``flags.powered``, since the BFS seeds at sources but only ever walks carriers.

**"Shares a doorway" is a door pair, not adjacency.** Both cells must be
placed and each must have a door bit facing the other -- the same test
``Game._connected`` and the navigation BFS use. Door *state* is deliberately
ignored: a locked, security or sealed segment is still a doorway with ducts
running through it, and coupling power to the key budget would make it depend
on how many keys the player happens to be holding.
"""

from __future__ import annotations

from collections import deque
from typing import Sequence

from .effects import Capability, rooms_with_capability
from .grid import ADJACENT, N_CELLS
from .model import Room


def power_source_ids() -> frozenset[str]:
    """Room ids that generate power of their own, from the capability registry.

    A function rather than a module constant because ``provides`` runs at the
    import time of each room module: reading the registry once here would
    freeze whichever subset had registered so far.
    """
    return rooms_with_capability(Capability.POWER_SOURCE)


def powered_cells(grid: Sequence[int], placed_doors: Sequence[int],
                  rooms: Sequence[Room]) -> list[bool]:
    """Per-cell power state for the whole grid, in one BFS.

    ``grid`` is ``GameState.grid`` (room index per cell, -1 empty),
    ``placed_doors`` is ``GameState.placed_doors`` (4-bit door mask per cell),
    and ``rooms`` is the registry's room table, indexed by ``Room.idx``.

    Returns a list of ``N_CELLS`` bools. A cell is True when its room is a
    source, or when a chain of door pairs joins it to one through rooms that
    all carry power. Empty cells and non-carrying rooms are always False, and
    a non-carrying room breaks the chain: power stops at it rather than
    passing through.
    """
    sources = power_source_ids()
    carriers: dict[int, bool] = {}  # powered-carrying cell -> is it a source
    for cell, idx in enumerate(grid):
        if idx < 0:
            continue
        room = rooms[idx]
        if room.powered:
            carriers[cell] = room.id in sources

    powered = [False] * N_CELLS
    queue: deque[int] = deque()
    for cell, is_source in carriers.items():
        if is_source:
            powered[cell] = True
            queue.append(cell)

    while queue:
        cell = queue.popleft()
        mask = placed_doors[cell]
        for direction, opposite, neighbour in ADJACENT[cell]:
            if powered[neighbour] or neighbour not in carriers:
                continue
            if mask & direction and placed_doors[neighbour] & opposite:
                powered[neighbour] = True
                queue.append(neighbour)
    return powered
