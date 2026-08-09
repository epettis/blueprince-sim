"""Solarium: sets the flag that keys the slot-2/3 rarity flattening.

Split out of the old test_game.py, which keeps the general game-loop tests.
See tests/rooms/test_library.py for the Library-vs-Solarium precedence
(the weights-table side of the Solarium's effect).
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def test_solarium_flag_set_on_place(registry):
    """Placing the Solarium sets the flag that keys the slot-2/3 rarity
    flattening for the rest of the day."""
    cfg = GameConfig(studio_additions=frozenset({"solarium"}))
    g = Game(cfg, seed=2)
    assert not g.state.solarium_placed
    g._place_room(registry.by_id["solarium"], 7, 4)
    assert g.state.solarium_placed
