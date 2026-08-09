"""Nursery: grants steps whenever a bedroom is drafted.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.engine.game import Game


def test_nursery_grants_on_bedroom_draft(registry, cfg):
    """A placed Nursery grants 5 steps whenever a bedroom is drafted."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["nursery"], 7, 4)
    steps0 = g.state.steps
    g._place_room(registry.by_id["guest_bedroom"], 8, 4)
    assert g.state.steps == steps0 + 5
