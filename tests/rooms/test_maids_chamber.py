"""Maid's Chamber: the anti-luck red-room penalty.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, S


def test_maids_chamber_reduces_luck_on_place(registry, cfg):
    """Placing Maid's Chamber applies -3 luck immediately (ON_PLACE)."""
    g = Game(cfg, seed=1)
    luck_before = g.state.luck
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == luck_before - 3


def test_maids_chamber_luck_clamps_at_zero(registry, cfg):
    """anti_luck never drives luck below 0."""
    g = Game(cfg, seed=1)
    g.state.luck = 1
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == 0


def test_maids_chamber_luck_negated_by_shelter(registry, cfg):
    """Shelter negates the Maid's Chamber red-room penalty."""
    g = Game(cfg, seed=1)
    g.red_negations = 1
    luck_before = g.state.luck
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == luck_before  # penalty negated
    assert g.red_negations == 0  # one negation consumed
