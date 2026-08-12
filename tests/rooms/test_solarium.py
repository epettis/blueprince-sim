"""Solarium: sets the flag that keys the slot-2/3 rarity flattening.

See tests/rooms/test_library.py for the Library-vs-Solarium precedence
(the weights-table side of the Solarium's effect).
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.state import DraftOption


def test_solarium_flag_set_on_place(registry):
    """Placing the Solarium sets the flag that keys the slot-2/3 rarity
    flattening for the rest of the day."""
    cfg = GameConfig(studio_additions=frozenset({"solarium"}))
    g = Game(cfg, seed=2)
    assert not g.state.solarium_placed
    g._place_room(registry.by_id["solarium"], 7, 4)
    assert g.state.solarium_placed


def test_terrace_frees_solarium_gem_cost(registry, cfg):
    """The Terrace's free_green_drafts effect (Hook.ON_PLACE) zeroes gem cost
    for any room whose category is "green" (Game._effective_cost,
    game.py:1134). This keys off category, not pool name, so the Solarium
    (category "green", pool "studio_addition") qualifies too."""
    g = Game(cfg, seed=2)
    solarium = registry.by_id["solarium"]
    assert solarium.category == "green"
    opt = DraftOption(room_idx=solarium.idx, orientation=solarium.door_mask,
                      gem_cost=solarium.gem_cost, slot=1)

    cost_before = g._effective_cost(solarium, opt)
    assert cost_before > 0, "setup: Solarium normally costs gems"

    g.free_categories.add("green")  # what the Terrace's ON_PLACE hook does
    cost_after = g._effective_cost(solarium, opt)
    assert cost_after == 0
