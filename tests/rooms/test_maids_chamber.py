"""Maid's Chamber: the anti-luck red-room penalty, and its dual red+bedroom membership.
"""

import dataclasses

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, S
from blueprince_sim.engine.state import resolve_gem_cost
from blueprince_sim.env import obs as O


def test_maids_chamber_reduces_luck_on_place(registry, cfg):
    """Placing Maid's Chamber applies -7 luck immediately (ON_PLACE).

    Wiki (Luck page DataMinedBox): "Maid's Chamber: -7 when drafted."
    """
    g = Game(cfg, seed=1)
    luck_before = g.state.luck
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == luck_before - 7


def test_maids_chamber_luck_goes_negative_unclamped(registry, cfg):
    """Four Maid's Chambers reach -18 with no floor clamp.

    Derivation (also see the Dowsing Rod's datamined box, verified against
    the live wiki): day-start luck is 10 (data/items.json). The Dowsing
    Rod's low-luck branch (effective <=18) is reachable "only ... having 4
    Maid's Chambers drafted." At -7 per chamber: 4 x -7 = -28, so
    10 - 28 = -18 stored luck; +32 (the Dowsing Rod's own bonus) = 14, which
    IS <=18. Three chambers give 10 - 21 = -11, +32 = 21, which is NOT
    <=18 -- so four really is the only way, confirming -7 (not the old -3,
    which never reaches the branch even at four: 10 - 12 = -2, +32 = 30).
    A floor clamp at 0 would make -18 unreachable, contradicting that fact.
    """
    g = Game(cfg, seed=1)
    g.state.luck = 10  # wiki: "Luck starts each day at 10" -- pinned here, not
    # read from data/items.json, so this test is independent of that file.
    for cell in (7, 17, 27, 37):  # four separate, unconnected cells
        g._place_room(registry.by_id["maids_chamber"], cell, S | E)
    assert g.state.luck == 10 - 4 * 7 == -18


def test_maids_chamber_negative_luck_stays_inside_declared_obs_box(registry, cfg):
    """-18 luck (four Maid's Chambers, unclamped) must still encode inside
    the declared "resources" observation Box -- the bound this PR widened
    specifically to accommodate this floor (env/obs.py).
    """
    g = Game(cfg, seed=1)
    g.state.luck = 10
    for cell in (7, 17, 27, 37):
        g._place_room(registry.by_id["maids_chamber"], cell, S | E)
    assert g.state.luck == -18

    space = O.observation_space(
        len(registry.rooms), len(registry.special.items), len(registry.special.fabrication))
    obs = O.encode(g)
    assert space["resources"].contains(obs["resources"])


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
    Chamber as a Bedroom, not just red. This needs genuine dual-category
    support: Aquarium's counts_as_all_colors is a single escape hatch, but
    Maid's Chamber is a genuine second colour on an otherwise ordinary room.
    """
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    priced_room = dataclasses.replace(
        registry.by_id["boudoir"], gem_cost=0, gem_cost_dynamic="plus_one_per_bedroom")
    assert resolve_gem_cost(priced_room, g.state, registry.rooms) == 1
