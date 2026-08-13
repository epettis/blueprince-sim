"""Servant's Spare Quarters (servants_spare_quarters__ix134), a second-level
upgrade variant whose display name differs from its variant_of parent
(Spare Bedroom). Because the ingest pipeline's EFFECT_MAP keys off the base
slug, a display-name mismatch like this one needs its own explicit entry to
carry an effect at all.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck

TARGET_CELL = 7   # rank 2, col 2
FILLER_A = 8      # rank 2, col 3
FILLER_B = 9      # rank 2, col 4


def _place_bedroom_fillers(g: Game) -> None:
    """Put two ordinary Bedroom-category rooms on the grid alongside the target."""
    bedroom = g.registry.by_id["bedroom"]
    for cell in (FILLER_A, FILLER_B):
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask


def test_servants_spare_quarters_grants_a_key_per_bedroom_where_its_parent_grants_none(
    registry, cfg
):
    """servants_spare_quarters__ix134's "+1 key for each Bedroom in your house"
    (glyph resolves to key per its meta.glyph_resolution, mirroring the base
    Servant's Quarters) grants 1 key per Bedroom-category room on the grid,
    including itself; its variant_of parent, spare_bedroom__ix131, has no
    effect of its own and grants nothing regardless of how many Bedrooms are
    present."""
    parent = registry.by_id["spare_bedroom__ix131"]
    variant = registry.by_id["servants_spare_quarters__ix134"]

    g = Game(cfg, seed=0)
    suppress_luck(g)
    _place_bedroom_fillers(g)
    g.state.grid[TARGET_CELL] = parent.idx
    g.state.placed_doors[TARGET_CELL] = parent.door_mask
    keys_before = g.state.keys
    g._enter(TARGET_CELL)
    assert g.state.keys == keys_before, "spare_bedroom__ix131 grants no keys"

    g2 = Game(cfg, seed=0)
    suppress_luck(g2)
    _place_bedroom_fillers(g2)
    g2.state.grid[TARGET_CELL] = variant.idx
    g2.state.placed_doors[TARGET_CELL] = variant.door_mask
    keys_before2 = g2.state.keys
    g2._enter(TARGET_CELL)
    assert g2.state.keys == keys_before2 + 3, (
        "servants_spare_quarters__ix134 must grant 1 key per Bedroom on the grid "
        "(2 fillers + itself)"
    )
