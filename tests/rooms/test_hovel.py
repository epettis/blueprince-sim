"""Hovel: paying gem costs in steps instead.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption


def test_hovel_pays_gem_costs_with_steps(registry, cfg):
    """With the Hovel placed, a gem-cost room becomes affordable with ZERO
    gems: its cost is paid entirely in steps, at 3 steps per gem."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["hovel"], 7, N | S)  # ON_PLACE sets the flag
    assert g.hovel_placed
    room = next(r for r in registry.rooms if r.gem_cost > 0 and r.rarity)
    opt = DraftOption(room_idx=room.idx, orientation=room.door_mask,
                      gem_cost=room.gem_cost, slot=1)
    cost = g._effective_cost(room, opt)
    assert cost > 0
    g.state.steps, g.state.gems = 40, 0     # no gems at all
    assert g.affordable(room, opt), "must be affordable via steps with 0 gems"
    g._pay(room, opt)
    assert g.state.steps == 40 - 3 * cost   # paid in steps, at the 3:1 ratio
    assert g.state.gems == 0                # gems untouched (still 0)


def test_hovel_grants_sleeping_mask_bonus_steps(registry):
    """The Sleeping Mask's bonus (special_items.py::on_enter, ON_ENTER hook)
    fires when the entered room's category is "bedroom". Hovel now qualifies,
    since its category is "bedroom" rather than the pool name "outer" --
    previously entering it while holding a Sleeping Mask granted nothing."""
    # Seed 4's outer-room hand deals Hovel into slot 0 (verified by construction).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=4)
    assert registry.by_id["hovel"].category == "bedroom"
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 0)
    assert g.registry.rooms[opt.room_idx].id == "hovel", "setup: seed must deal Hovel"
    g.choose(0)

    si.grant(g.state, g.registry, "sleeping_mask", source="test")
    steps_before = g.state.steps
    g.travel_to("hovel")

    assert g.state.outer_room_entered
    assert g.state.steps > steps_before, (
        "Sleeping Mask must grant bonus steps entering a bedroom-category room"
    )
