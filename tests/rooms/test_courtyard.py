"""Courtyard upgrade variants: ix48's gem prize and ix49's widened dig-spot count.

Both variants previously modeled exactly the base Courtyard (no ON_ENTER
effect, 1 dig spot) even though their own effect text promises "+2 gems" and
"5 dig spots" respectively.
"""

from __future__ import annotations

from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game

CELL = 7  # rank 2, col 2 -- any on-grid cell works since _enter bypasses door legality


def test_courtyard_ix48_grants_two_gems_the_base_does_not(registry, cfg):
    """courtyard__ix48's "+2 gem" prize (glyph resolves to gem per its
    meta.glyph_resolution) fires on first entry, while the base Courtyard --
    whose empty effects list ix48 used to share -- grants nothing at all."""
    base = registry.by_id["courtyard"]
    ix48 = registry.by_id["courtyard__ix48"]

    g = Game(cfg, seed=0)
    g.state.luck = 0
    g.state.grid[CELL] = base.idx
    g.state.placed_doors[CELL] = base.door_mask
    gems_before = g.state.gems
    g._enter(CELL)
    assert g.state.gems == gems_before, "base Courtyard grants no gems"

    g2 = Game(cfg, seed=0)
    g2.state.luck = 0
    g2.state.grid[CELL] = ix48.idx
    g2.state.placed_doors[CELL] = ix48.door_mask
    gems_before2 = g2.state.gems
    g2._enter(CELL)
    assert g2.state.gems == gems_before2 + 2, "courtyard__ix48 must grant exactly 2 gems"


def test_courtyard_ix49_has_five_dig_spots_where_the_base_has_one(registry, cfg):
    """courtyard__ix49's "5 dig spots" text widens its own dig-spot count to 5,
    against the base Courtyard's 1 -- proven by actually digging every spot
    with a held shovel rather than reading the data field back."""
    base = registry.by_id["courtyard"]
    ix49 = registry.by_id["courtyard__ix49"]

    g = Game(cfg, seed=0)
    si.grant(g.state, g.registry, "shovel", source="test")
    g.state.grid[CELL] = base.idx
    si.dig_all(g, CELL)
    assert g.state.special.dug[CELL] == 1, "base Courtyard has exactly 1 dig spot"

    g2 = Game(cfg, seed=0)
    si.grant(g2.state, g2.registry, "shovel", source="test")
    g2.state.grid[CELL] = ix49.idx
    si.dig_all(g2, CELL)
    assert g2.state.special.dug[CELL] == 5, "courtyard__ix49 must widen the dig-spot count to 5"
