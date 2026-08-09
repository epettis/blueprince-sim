"""Root Cellar: green-category item effects now reach it.

Root Cellar is an outer room drafted through the fixed 8-room outer shuffle
(game.py::_deal_outer_options), which does not filter by category, so its
category never affected its own drafting odds. What it DOES gate is whether
category-keyed ON_ENTER item effects recognize the room once entered -- the
Watering Can only converts water to a gem in a "green"-category room
(special_items.py:534), which Root Cellar could never satisfy while
mislabeled with the pool name "outer".
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game


def test_root_cellar_lets_watering_can_convert_water_to_a_gem():
    """The Watering Can's on_enter hook only fires in a "green"-category room.
    Root Cellar now qualifies, since its category is "green" rather than the
    pool name "outer" -- previously entering it with the can equipped
    converted nothing."""
    # Seed 1's outer-room hand deals Root Cellar into slot 2 (verified by
    # construction; shared with tests/rooms/test_trading_post.py's seed).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=1)
    assert g.registry.by_id["root_cellar"].category == "green"
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 2)
    assert g.registry.rooms[opt.room_idx].id == "root_cellar", (
        "setup: seed must deal Root Cellar into slot 2"
    )
    g.choose(2)

    si.grant(g.state, g.registry, "watering_can", source="test")
    assert g.state.special.water > 0, "setup: the can starts with charges"
    water_before = g.state.special.water
    gems_before = g.state.gems

    g.travel_to("root_cellar")

    assert g.state.outer_room_entered
    assert g.state.special.water == water_before - 1
    assert g.state.gems == gems_before + 1
