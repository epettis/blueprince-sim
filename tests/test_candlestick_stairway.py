"""The Abandoned Mine (South) <-> Precipice stairway.

Regression coverage for the owner-confirmed bug: `precipice -> mine_south` was
ungated while `mine_south -> precipice` carried an item gate (torch/burning
glass held), making the Precipice a free front door into the mine. The real
mechanic is the reverse: the mine is reached from the house side (Catacombs
via the Tomb puzzle, the drained Fountain + Basement Key, or the lowered
Reservoir crossing from the north), and the stairway to the Precipice is
something the player *creates* by lighting all 8 candlesticks from *inside*
the mine. Both directions now share one `candlestick_stairway_lit` flag gate,
set from `state.special.lit_targets` via the existing ignition system
(`engine/special_items.py::can_light`/`light`) rather than a bespoke item gate.
See `docs/areas.md`'s "Corrections already applied" for the full writeup.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.rl.train import all_unlocks_config, fresh_save_config


def test_mine_unreachable_on_day_one_under_both_baseline_configs(registry):
    """With an empty inventory and nothing earned, mine_south is unreachable
    on day 1 under both training baseline configs -- the regression this fix
    closes. Previously the ungated precipice -> mine_south backdoor made it
    reachable in 3 steps regardless of config."""
    for cfg in (all_unlocks_config(), fresh_save_config()):
        g = Game(cfg, seed=1, registry=registry)
        g.state.steps = 200
        assert g.area_route_cost("mine_south") is None, (
            f"mine_south must be unreachable under {cfg.__class__.__name__} day={cfg.day}"
        )


def test_holding_torch_alone_does_not_open_stairway(registry):
    """Merely holding an ignition tool must not open the stairway -- the exact
    failure mode of the old item gate, where holding a torch alone satisfied
    the (wrongly one-sided) candlestick_stairway gate without ever lighting
    anything."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["torch"] = 1
    assert g.area_route_cost("mine_south") is None, (
        "holding a torch must not open a stairway that has not been lowered"
    )


def test_lighting_from_inside_opens_stairway_both_ways(registry):
    """Lighting the candlesticks from inside the mine opens the stairway in
    BOTH directions -- the honest model: the flag is earned by standing in
    mine_south and lighting it, not by merely holding a torch anywhere."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200

    # Simulate having reached the mine some other way (Catacombs, drained
    # Fountain, or the lowered Reservoir crossing) with a torch in hand.
    g.state.area = "mine_south"
    g.state.inventory["torch"] = 1
    assert g.can_light(), "setup: standing at an unlit target with a tool held"

    # NOT "is the Precipice reachable" -- a long surface route (out through the
    # Reservoir and back down the open cliffside stub) reaches it even unlit, so
    # mere reachability proves nothing here. The stairway is a DIRECT one-step
    # link, so pin the hop count: it must collapse to 1 only once lit.
    before = g.area_route_cost("precipice")
    assert before is not None and before[0] > 1, (
        "setup: unlit, the Precipice is only reachable the long way round"
    )

    g.light()
    assert "mine_south" in g.state.special.lit_targets

    after = g.area_route_cost("precipice")
    assert after is not None and after[0] == 1, (
        "lighting must open the direct mine_south -> precipice stairway"
    )
    assert after[0] < before[0], "the lit stairway must be strictly shorter than going round"

    # precipice -> mine_south now passable too (same physical stairway). This
    # direction has no alternate route at all -- tests 1 and 2 pin that it is
    # None while unlit -- so plain reachability is meaningful here.
    g.state.area = "precipice"
    assert g.area_route_cost("mine_south") is not None, "precipice -> mine_south must open"


def test_lit_stairway_persists_across_days_via_carryover(registry):
    """Lighting mine_south is permanent: it flows through the real
    shops.carryover()/Game.carryover() path into DayChain, so day 2's
    GameConfig already lists mine_south as lit and the stairway stays open
    on day 2 without re-lighting."""
    chain = DayChain(GameConfig(special_items=True), n_days=3)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    g1.state.steps = 200
    g1.state.area = "mine_south"
    g1.state.inventory["torch"] = 1
    assert g1.can_light()
    g1.light()
    assert "mine_south" in g1.state.special.lit_targets

    chain.advance(g1.carryover())
    cfg_day2 = chain.next_config()
    assert "mine_south" in cfg_day2.lit_targets, (
        "mine_south lit on day 1 must appear in day 2 cfg.lit_targets"
    )

    g2 = Game(cfg_day2, seed=2, registry=registry)
    g2.state.steps = 200
    # Emptied deliberately: with today's own lit_targets bare, cfg.lit_targets is
    # the only place the flag can come from, so this pins that _gate_ctx() reads
    # the carried config directly rather than leaning on seeded per-day state.
    g2.state.special.lit_targets.clear()
    assert "candlestick_stairway_lit" in g2._gate_ctx().flags, (
        "the flag must be live on day 2 from carried-over cfg.lit_targets alone"
    )
    assert g2.area_route_cost("mine_south") is not None, (
        "the stairway must stay open on day 2 without re-lighting"
    )


def test_light_action_offered_off_grid_at_mine_south(registry):
    """The LIGHT_ACTION must be offered off-grid, not just on-grid, or the
    mine's candlesticks could never be lit at all -- a soft-lock. can_light()
    is consulted outside the on-grid/off-grid split in env/actions.py, the
    same way INSERT_DISK_ACTION already is for Shelter."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.area = "mine_south"
    g.state.inventory["torch"] = 1
    assert g.off_grid
    mask = A.action_mask(g)
    assert mask[A.LIGHT_ACTION], "lighting must be offered while standing off-grid at mine_south"
