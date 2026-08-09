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


def test_indoor_nursery_grants_gems_on_green_room_draft(registry, cfg):
    """Indoor Nursery (an upgrade variant of the Nursery, restored per the room
    fidelity audit) grants 2 gems whenever another Green Room is drafted -
    mirroring the base Nursery's grant_on_draft_category shape but keyed to
    the green category and paying gems instead of steps."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["indoor_nursery__ix103"], 7, 4)
    gems0 = g.state.gems
    g._place_room(registry.by_id["patio"], 8, 4)  # a plain Green Room
    assert g.state.gems == gems0 + 2
