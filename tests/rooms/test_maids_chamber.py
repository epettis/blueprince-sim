"""Maid's Chamber: the anti-luck red-room penalty, and its dual red+bedroom membership.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

import dataclasses

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, S
from blueprince_sim.engine.state import resolve_gem_cost


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


def test_maids_chamber_is_category_red_and_bedroom(registry):
    """Maid's Chamber's own effect text has always read "Counts as red room
    AND bedroom": Room.is_category must return True for both, and False for
    every other colour -- the second membership a single-``category`` field
    cannot express at all.
    """
    maids_chamber = registry.by_id["maids_chamber"]
    assert maids_chamber.category == "red"
    assert maids_chamber.is_category("red")
    assert maids_chamber.is_category("bedroom")
    for category in ("blueprint", "hallway", "green", "shop", "blackprint", "objective"):
        assert not maids_chamber.is_category(category), (
            f"Maid's Chamber should not count as {category!r}")


def test_maids_chamber_counts_as_bedroom_for_dynamic_gem_cost(registry, cfg):
    """resolve_gem_cost's ``plus_one_per_bedroom`` modifier must count the Maid's
    Chamber as a Bedroom, not just red -- the case the old counts_as_all_colors-only
    model (a single Aquarium-only escape hatch) had no way to express, since Maid's
    Chamber is a genuine second colour on an otherwise ordinary room.
    """
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    priced_room = dataclasses.replace(
        registry.by_id["boudoir"], gem_cost=0, gem_cost_dynamic="plus_one_per_bedroom")
    assert resolve_gem_cost(priced_room, g.state, registry.rooms) == 1
