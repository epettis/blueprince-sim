"""Vestibule: hallway-category movement rules now reach it.

special_items.py::move_step_cost waives the step cost of a move between two
"hallway"-category rooms while a Hall Pass is held. Vestibule could never
satisfy either side of that check while its category was the pool name
"studio_addition" instead of "hallway".
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import S


def test_vestibule_qualifies_for_hall_pass_free_move(registry):
    """move_step_cost's Hall Pass shortcut only fires hallway-to-hallway
    (special_items.py:773). Vestibule now qualifies as "hallway" rather than
    the pool name "studio_addition", so a Hall Pass move from another
    hallway room into it costs 0 steps instead of the normal 1."""
    g = Game(GameConfig(special_items=True), seed=0)
    si.grant(g.state, g.registry, "hall_pass", source="test")

    corridor = registry.by_id["corridor"]  # a pre-existing, correctly-tagged hallway room
    vestibule = registry.by_id["vestibule"]
    assert vestibule.category == "hallway"
    g.state.grid[7] = corridor.idx

    cost = si.move_step_cost(g, 7, S, vestibule)
    assert cost == 0


def test_vestibule_move_costs_a_step_without_hall_pass(registry):
    """Without a Hall Pass, the same hallway-to-hallway move costs the normal
    1 step -- the free move is the item's doing, not an unconditional
    category shortcut."""
    g = Game(GameConfig(special_items=True), seed=0)

    corridor = registry.by_id["corridor"]
    vestibule = registry.by_id["vestibule"]
    g.state.grid[7] = corridor.idx

    cost = si.move_step_cost(g, 7, S, vestibule)
    assert cost == 1
