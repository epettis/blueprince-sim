"""Rotunda: grants free rotation of the current drafting hand for as long as
it is PLACED on the grid.

Game.rotation_available's docstring calls out three sources by name --
Ornate Compass (held), Rotunda (placed), Dovecote (drawn) -- and
tests/rooms/test_dovecote.py already pins the DRAWN-only half of the
placed/drawn distinction from the Dovecote's side (a placed-but-not-drawn
Dovecote grants nothing). Nothing exercises the Rotunda's own half: no
existing test places a real Rotunda and checks rotation_available() at all
(tests/test_rotation.py's "all three sources" suite only covers Ornate
Compass and Dovecote). This is the missing case, built the same way
test_dovecote.py's does.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.state import DraftOption, PendingDraft

DIRECTION = S
TARGET_CELL = 12


def test_rotunda_placed_but_not_drawn_grants_free_rotation(registry, cfg):
    """A Rotunda sitting on the grid, with no Rotunda among the CURRENT
    hand's options, still grants free rotation -- unlike the Dovecote, whose
    grant rides being drawn rather than placed."""
    g = Game(cfg, seed=1, registry=registry)
    rotunda = g.registry.by_id["rotunda"]
    g._place_room(rotunda, 6, rotunda.door_mask)
    assert "rotunda" in g.placed_ids
    assert g.rotunda_placed

    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=DIRECTION, target_cell=TARGET_CELL)
    pd.options = [DraftOption(room_idx=troom.idx, orientation=troom.door_mask, gem_cost=0, slot=0)]
    g.state.pending = pd

    assert g.rotation_available(), "a placed Rotunda must grant free rotation"
