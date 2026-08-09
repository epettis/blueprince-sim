"""Spare Terrace, an upgrade variant of the Spare Greenroom.

Placing it makes Green Rooms free to draft, through the same
``free_green_drafts`` tag the base Terrace carries. Effects are not inherited
through ``variant_of``, so the variant carries the tag itself.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.state import DraftOption


def test_spare_terrace_waives_green_room_gem_cost(registry, cfg):
    """A gem-cost Green Room (Patio, 1 gem) is unaffordable with 0 gems in
    hand before Spare Terrace is placed, and becomes affordable for free
    immediately after -- the same public ``affordable`` check the draft flow
    uses to gate a real choose() call."""
    g = Game(cfg, seed=0)
    g.state.gems = 0
    patio = registry.by_id["patio"]
    opt = DraftOption(room_idx=patio.idx, orientation=patio.door_mask, gem_cost=1, slot=1)

    assert not g.affordable(patio, opt), "Patio should cost a gem before Spare Terrace"

    terrace = registry.by_id["spare_terrace__ix141"]
    g._place_room(terrace, 7, 4)

    assert g.affordable(patio, opt), "Green Rooms must be free once Spare Terrace is placed"
