"""Shrine: category correctness without a live in-game consumer.

Shrine is an outer room drafted through the fixed 8-room outer shuffle,
which does not filter by category, and its own effect (multi-day donation
blessings) is out of single-day scope and does not key off category. Its
"blueprint" category (corrected from the pool name "outer") currently has no
OTHER live consumer in the engine. This test pins the one thing that IS
observable today -- that it does not spuriously activate the outer-shop dead
branch -- see tests/rooms/test_toolshed.py for the same reasoning.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry


def test_shrine_category_does_not_activate_the_outer_shop_dead_branch():
    """Shrine's category is "blueprint", not "shop": entering it off-grid
    must not resolve a current_shop_id."""
    reg = Registry.load()
    shrine = reg.by_id["shrine"]
    assert shrine.category == "blueprint"

    # Seed 3's outer-room hand deals Shrine into slot 1 (verified by construction).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=3, registry=reg)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 1)
    assert g.registry.rooms[opt.room_idx].id == "shrine", (
        "setup: seed must deal Shrine into slot 1"
    )
    g.choose(1)
    g.travel_to("shrine")

    assert g.state.outer_room_entered
    assert shops.current_shop_id(g) is None
