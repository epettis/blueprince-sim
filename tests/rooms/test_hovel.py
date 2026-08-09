"""Hovel: paying gem costs in steps instead.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption


def test_hovel_pays_gem_costs_with_steps(registry, cfg):
    """With the Hovel placed, gem costs are paid in steps at 3 steps per gem
    and the gem balance is left untouched."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["hovel"], 7, N | S)  # ON_PLACE sets the flag
    assert g.hovel_placed
    room = next(r for r in registry.rooms if r.gem_cost > 0 and r.rarity)
    opt = DraftOption(room_idx=room.idx, orientation=room.door_mask,
                      gem_cost=room.gem_cost, slot=1)
    cost = g._effective_cost(room, opt)
    assert cost > 0
    g.state.steps, g.state.gems = 40, 5
    assert g.affordable(room, opt)          # 40 > 3*cost
    g._pay(room, opt)
    assert g.state.steps == 40 - 3 * cost   # paid in steps
    assert g.state.gems == 5                # gems untouched
