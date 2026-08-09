"""Dormitory: bedroom-category counting now reaches it.

Servant's Quarters grants keys per "bedroom"-category room on the grid
(effects/tier1.py::grant_per_category, state.py-style category scan over
state.grid). Dormitory is drafted on-grid (studio_addition pool), so it was
always counted by these scans -- but only once its category read "bedroom"
instead of the pool name "studio_addition".
"""

from __future__ import annotations

from blueprince_sim.engine.effects import tier1
from blueprince_sim.engine.game import Game


def test_dormitory_counts_toward_servants_quarters_bedroom_grant(registry, cfg):
    """grant_per_category("bedroom") (Servant's Quarters' effect) counts every
    on-grid room whose category is "bedroom". Dormitory now adds exactly 1 to
    that count, since its category is "bedroom" rather than the pool name
    "studio_addition" -- isolated by diffing against a baseline with only
    Servant's Quarters itself on the grid (it counts itself too)."""
    dormitory = registry.by_id["dormitory"]
    servants_quarters = registry.by_id["servants_quarters"]
    assert dormitory.category == "bedroom"
    eff = servants_quarters.effects[0]
    assert eff.tag == "grant_per_category" and eff.param("category") == "bedroom"

    def _keys_granted(place_dormitory: bool) -> int:
        g = Game(cfg, seed=0)
        g.state.grid[12] = servants_quarters.idx
        if place_dormitory:
            g.state.grid[7] = dormitory.idx
        keys_before = g.state.keys
        tier1.grant_per_category(g, servants_quarters, eff, None)
        return g.state.keys - keys_before

    baseline = _keys_granted(place_dormitory=False)
    with_dormitory = _keys_granted(place_dormitory=True)
    assert with_dormitory == baseline + 1
