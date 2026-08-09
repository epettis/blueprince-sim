"""Spare Veranda (spare_veranda__ix140), a second-level upgrade variant whose
display name differs from its variant_of parent (Spare Greenroom), so the
ingest pipeline's base-slug EFFECT_MAP entry never matched it and it
previously carried no effect at all, despite promising the same "Greater
chance of finding items in Green Rooms" text as the base Veranda.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game

CELL = 7  # rank 2, col 2


def test_spare_veranda_grants_three_luck_where_its_parent_grants_none(registry, cfg):
    """spare_veranda__ix140 mirrors the base Veranda's "grant 3 luck" modeling
    of "greater chance of finding items" (the same magnitude used everywhere
    else in this codebase for that effect text, e.g. Root Cellar) on first
    entry -- while its variant_of parent, spare_greenroom__ix132, which it
    previously modeled exactly, leaves luck untouched."""
    parent = registry.by_id["spare_greenroom__ix132"]
    variant = registry.by_id["spare_veranda__ix140"]

    g = Game(cfg, seed=0)
    g.state.luck = 0
    g.state.grid[CELL] = parent.idx
    g.state.placed_doors[CELL] = parent.door_mask
    g._enter(CELL)
    assert g.state.luck == 0, "spare_greenroom__ix132 does not affect luck"

    g2 = Game(cfg, seed=0)
    g2.state.luck = 0
    g2.state.grid[CELL] = variant.idx
    g2.state.placed_doors[CELL] = variant.door_mask
    g2._enter(CELL)
    assert g2.state.luck == 3, "spare_veranda__ix140 must grant exactly 3 luck"
