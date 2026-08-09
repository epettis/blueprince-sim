"""Hallway upgrade variant: guaranteed key count restored per the room
fidelity audit (docs/open_tasks.md task 15).

hallway__ix74's "+1 key" had regressed to an empty ``items.guaranteed`` list
because upgrade variants do not inherit items through ``variant_of``.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def test_hallway_ix74_grants_one_key():
    """hallway__ix74 ("+1 key") grants exactly 1 key on first entry.

    Luck is floored so its additional_max luck-rolled extra item never
    procs, keeping the guaranteed-key assertion deterministic."""
    cell = 5
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=0)
    g.state.luck = 0
    room = g.registry.by_id["hallway__ix74"]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1
