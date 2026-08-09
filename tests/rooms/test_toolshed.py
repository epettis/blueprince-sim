"""Toolshed: always contains 2 items, and its "blueprint" category does not
key any other live consumer.

Toolshed is an outer room drafted through the fixed 8-room outer shuffle,
which does not filter by category. Its "blueprint" category (corrected from
the pool name "outer") has no OTHER live consumer in the engine: unlike
Trading Post it is not a Shop, and unlike Hovel/Root Cellar no category-gated
item effect targets "blueprint" rooms specifically. The dead-branch test
below pins that -- a future regression that flips it to "shop" (or that adds
a blueprint-gated outer effect) is caught either way.
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


def test_toolshed_always_grants_exactly_two_items_on_first_entry():
    """Toolshed's items.guaranteed is [{"random", 2}]: roll_room_items grants
    a FIXED count of 2 table-rolled items regardless of luck (the "random"
    guaranteed branch is luck-immune, unlike the additional_max luck roll),
    so entering it always logs exactly 2 pickups."""
    reg = Registry.load()
    toolshed = reg.by_id["toolshed"]
    assert toolshed.items.guaranteed == (("random", 2),), (
        "setup: Toolshed must guarantee exactly 2 random items"
    )

    tried = 0
    for seed in range(60):
        g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=seed, registry=reg)
        pending = g.open_outer_draft()
        opt = next((o for o in pending.options
                    if g.registry.rooms[o.room_idx].id == "toolshed"), None)
        if opt is None:  # the fixed 8-room shuffle only offers 3; skip hands without it
            continue
        tried += 1
        g.choose(opt.slot)
        log_before = len(g.state.items_found_log)
        g.travel_to("toolshed")
        assert g.state.outer_room_entered
        assert len(g.state.items_found_log) == log_before + 2, (
            f"seed={seed}: Toolshed must always grant exactly 2 items"
        )
    assert tried >= 5, "setup: expected several seeds in 0..59 to deal Toolshed"
