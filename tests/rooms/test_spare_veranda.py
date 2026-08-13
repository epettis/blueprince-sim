"""Spare Veranda (spare_veranda__ix140), a second-level upgrade variant whose
display name differs from its variant_of parent (Spare Greenroom). Because
the ingest pipeline's EFFECT_MAP keys off the base slug, a display-name
mismatch like this one needs its own explicit entry to carry an effect,
despite promising the same "Greater chance of finding items in Green Rooms"
text as the base Veranda.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck

CELL = 7  # rank 2, col 2


def test_spare_veranda_grants_three_luck_where_its_parent_grants_none(registry, cfg):
    """spare_veranda__ix140 mirrors the base Veranda's "grant 3 luck" modeling
    of "greater chance of finding items" on first entry; its variant_of parent,
    spare_greenroom__ix132, has no effect of its own and leaves luck untouched.

    The magnitude is an inferred placeholder, not a datamined figure: the
    datamined value is +6 per Spare Veranda, applied per draft and only when
    the drafted room is green. Correcting it is queued with the luck-model
    rebuild."""
    parent = registry.by_id["spare_greenroom__ix132"]
    variant = registry.by_id["spare_veranda__ix140"]

    g = Game(cfg, seed=0)
    suppress_luck(g)
    g.state.grid[CELL] = parent.idx
    g.state.placed_doors[CELL] = parent.door_mask
    g._enter(CELL)
    assert g.state.luck == 0, "spare_greenroom__ix132 does not affect luck"

    g2 = Game(cfg, seed=0)
    suppress_luck(g2)
    g2.state.grid[CELL] = variant.idx
    g2.state.placed_doors[CELL] = variant.door_mask
    g2._enter(CELL)
    assert g2.state.luck == 3, "spare_veranda__ix140 must grant exactly 3 luck"
