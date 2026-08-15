"""Pump Room: the water-level control panel.

``Capability.PUMP_PANEL`` is read by ``Game.can_set_pump_source`` (via
``Game._capability_cell``) to gate the panel menu to this room's cell,
without ``game.py`` naming this room's id directly -- the same shape as
``security.py``'s ``Capability.SECURITY_LEVEL``.

Data: data/pump_room.json (six water sources, each with its own initial/min/
max level). The real Pump Room is a water-pouring puzzle -- two tanks and
four pumps move water one stroke at a time between a tank and a fixed pair of
sources per pump. This sim assumes the puzzle solved (docs/doctrine.md): the
player picks a source and a target level directly (Game.set_pump_source /
Game.set_pump_level), reaching in one decision every level the wiki says the
real panel can reach. See data/rooms.json's pump_room.meta.simplification for
what this leaves unmodelled (the tanks, the pumps, the disconnected Reserve
Tank) and docs/areas.md for the gates the six levels drive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import Capability, provides

DATA_FILENAME = "pump_room.json"
PUMP_ROOM_ID = "pump_room"

provides(PUMP_ROOM_ID, Capability.PUMP_PANEL)


@dataclass(frozen=True, slots=True)
class PumpSource:
    id: str        # data/pump_room.json source id (aquarium, fountain, greenhouse,
                    # kitchen, pool, reservoir)
    initial: int    # fresh-save level (also GameState.water_levels' fallback)
    min: int        # lowest level Game.set_pump_level accepts (2 for the Reservoir, 0 elsewhere)
    max: int        # highest level Game.set_pump_level accepts


_SOURCES_CACHE: dict[Path, tuple[PumpSource, ...]] = {}


def load_sources(data_dir: Path) -> tuple[PumpSource, ...]:
    """Parse data/pump_room.json's source table, cached per data_dir.

    File order (alphabetical by id) is the action-index order for
    env/actions.py's PUMP_SOURCE_BASE block.
    """
    data_dir = Path(data_dir)
    cached = _SOURCES_CACHE.get(data_dir)
    if cached is not None:
        return cached
    raw = json.loads((data_dir / DATA_FILENAME).read_text())
    sources = tuple(
        PumpSource(id=s["id"], initial=s["initial"], min=s["min"], max=s["max"])
        for s in raw["sources"]
    )
    _SOURCES_CACHE[data_dir] = sources
    return sources
