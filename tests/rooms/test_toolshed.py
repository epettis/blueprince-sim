"""Toolshed: category correctness without a live in-game consumer.

Toolshed is an outer room drafted through the fixed 8-room outer shuffle,
which does not filter by category, and its own effect (2 guaranteed items)
does not key off category either. Its "blueprint" category (corrected from
the pool name "outer") currently has no OTHER live consumer in the engine:
unlike Trading Post it is not a Shop, and unlike Hovel/Root Cellar no
category-gated item effect targets "blueprint" rooms specifically. This test
pins the one thing that IS observable today -- that it does not spuriously
activate the outer-shop dead branch -- so a future regression that flips it
to "shop" (or that adds a blueprint-gated outer effect) is caught either way.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry


def test_toolshed_category_does_not_activate_the_outer_shop_dead_branch():
    """Toolshed's category is "blueprint", not "shop": entering it off-grid
    must not resolve a current_shop_id."""
    reg = Registry.load()
    toolshed = reg.by_id["toolshed"]
    assert toolshed.category == "blueprint"

    # Seed 4's outer-room hand deals Toolshed into slot 2 (verified by construction).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=4, registry=reg)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 2)
    assert g.registry.rooms[opt.room_idx].id == "toolshed", (
        "setup: seed must deal Toolshed into slot 2"
    )
    g.choose(2)
    g.travel_to("toolshed")

    assert g.state.outer_room_entered
    assert shops.current_shop_id(g) is None
