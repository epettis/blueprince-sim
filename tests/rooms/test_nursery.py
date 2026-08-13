"""Nursery: grants steps whenever a bedroom is drafted.
"""

from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck


def test_nursery_grants_on_bedroom_draft(registry, cfg):
    """A placed Nursery grants 5 steps whenever a bedroom is drafted."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["nursery"], 7, 4)
    steps0 = g.state.steps
    g._place_room(registry.by_id["guest_bedroom"], 8, 4)
    assert g.state.steps == steps0 + 5


def test_indoor_nursery_grants_gems_on_green_room_draft(registry, cfg):
    """Indoor Nursery, an upgrade variant of the Nursery, grants 2 gems whenever
    another Green Room is drafted. It uses the same grant_on_draft_category
    shape as the base Nursery, keyed to the green category and paying gems."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["indoor_nursery__ix103"], 7, 4)
    gems0 = g.state.gems
    g._place_room(registry.by_id["patio"], 8, 4)  # a plain Green Room
    assert g.state.gems == gems0 + 2


def test_nursery_grants_on_its_own_draft(registry, cfg):
    """The Nursery's own category is Bedroom, so placing it grants 5 steps
    immediately for itself, not only for bedrooms drafted afterward."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    steps0 = g.state.steps
    g._place_room(registry.by_id["nursery"], 7, 4)
    assert g.state.steps == steps0 + 5


def test_indoor_nursery_does_not_grant_on_its_own_draft(registry, cfg):
    """Indoor Nursery's effect text says "another Green Room", so unlike the
    base Nursery it must not pay itself gems on its own draft even though its
    own category is Green -- the regression guard for the include_self opt-in."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    gems0 = g.state.gems
    g._place_room(registry.by_id["indoor_nursery__ix103"], 7, 4)
    assert g.state.gems == gems0


def test_upgraded_nursery_grants_more_than_the_base_room(registry, cfg):
    """nursery__ix101 pays 8 steps per bedroom where the base Nursery pays 5.

    Asserted against the base room in the same test so the two cannot silently
    converge: effects are not inherited through variant_of, so an upgrade that
    matches its parent is indistinguishable from one that was never authored."""
    base_steps, upgraded_steps = [], []
    for room_id, sink in (("nursery", base_steps), ("nursery__ix101", upgraded_steps)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        before = g.state.steps
        g._place_room(registry.by_id[room_id], 7, 4)
        sink.append(g.state.steps - before)
    assert base_steps == [5]
    assert upgraded_steps == [8]
