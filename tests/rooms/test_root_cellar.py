"""Root Cellar: green-category item effects now reach it, plus its own
unconditional +3 luck grant on first entry.

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
from blueprince_sim.engine.model import Registry


def test_root_cellar_lets_watering_can_convert_water_to_a_gem():
    """The Watering Can's on_enter hook keys off the room's category, not its
    pool name, so the Root Cellar (category "green", pool "outer") converts
    water to a gem too."""
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


def test_root_cellar_does_not_touch_luck():
    """Entering the Root Cellar leaves luck untouched, and the room declares no
    effects at all.

    Its real effect is spreading dig spots to OTHER rooms, which this sim does
    not model; the room keeps only its own dig_spots. It has no luck effect in
    the game: the wiki's datamined luck-modifier list enumerates every modifier
    (Spiral of Stars, Cloister of Rynna, Maid's Chamber, Veranda, Spare
    Veranda, Lucky Rabbit's Foot) and does not include the Root Cellar, and the
    room's own page never uses the word "luck". Pinned rather than simply
    deleted because luck band boundaries make a stray +3 worth roughly +66%
    expected items, so re-introducing the approximation would be materially
    wrong rather than cosmetic."""
    root_cellar = Registry.load().by_id["root_cellar"]
    assert not root_cellar.effects

    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=1)
    g.state.luck = 0
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options
              if g.registry.rooms[o.room_idx].id == "root_cellar")
    g.choose(opt.slot)

    g.travel_to("root_cellar")

    assert g.state.outer_room_entered
    assert g.state.luck == 0
