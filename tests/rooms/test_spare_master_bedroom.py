"""Spare Master Bedroom, an upgrade variant of the Spare Bedroom.

Entering grants 1 step for every room currently placed in the house, via
``grant_per_category`` with category "any", which sums over every placed room
regardless of category.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game


def test_spare_master_bedroom_grants_one_step_per_placed_room(registry, cfg):
    """Entering with 5 rooms on the grid (Entrance Hall + Antechamber, both
    pre-placed at day start, + 2 fillers + itself) grants exactly 5 steps --
    1 per room in the house, matching the base Master Bedroom's shape."""
    g = Game(cfg, seed=0)
    # Entrance Hall and the Antechamber are already placed at day start (2
    # rooms - see Game.reset). Add two filler rooms plus the bedroom itself,
    # for 5 rooms in the house total.
    corridor = registry.by_id["corridor"]
    g._place_room(corridor, 6, 15)
    g._place_room(corridor, 8, 15)
    room = registry.by_id["spare_master_bedroom__ix136"]
    g._place_room(room, 7, 15)

    steps0 = g.state.steps
    g._enter(7)
    assert g.state.steps == steps0 + 5
