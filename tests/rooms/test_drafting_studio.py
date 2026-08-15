"""Drafting Studio: its only modelled effect is counts_as_drafting_room.

docs/rooms.md records that the Drafting Studio's published safe
deliberately grants no gem (unlike every other safe room), so there is no
gem effect to pin here at all -- placing it and reading the counter the
Classroom's free-redraw grant reads is the room's whole observable
footprint. Mirrors tests/rooms/test_drawing_room.py's own thin pin of the
same effect for Drawing Room.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S


def test_drafting_studio_counts_as_a_drafting_room(registry, cfg):
    """Placing the Drafting Studio raises state.drafting_room_count by 1 --
    the flag the Classroom later reads for its free redraws."""
    g = Game(cfg, seed=0, registry=registry)
    studio = g.registry.by_id["drafting_studio"]
    assert [eff.tag for eff in studio.effects] == ["counts_as_drafting_room"]
    count_before = g.state.drafting_room_count
    g._place_room(studio, 7, N | S)
    assert g.state.drafting_room_count == count_before + 1
