"""Tests for the Apple Orchard: reachability as a travel destination, and
earning the permanent +20 starting-steps bonus.

Two bugs stacked (owner report, 2026-08-08): (1) apple_orchard/campsite were
never offered as travel destinations because both carried ``modelled:
false``, even though the graph path (house -> ... -> campsite ->
apple_orchard) was always routable; (2) GameConfig.orchard_unlocked was never
set anywhere in-run, so even arriving granted nothing. This file pins the fix
for both, following the exact carry-over shape used by west_gate_unlatched /
sealed_entrance_broken: the discovery is recorded on GameState, never written
back to GameConfig (one config object is shared by every episode of a
trainer worker -- see test_orchard_unlocked_does_not_leak_into_a_fresh_game).
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import reachable
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain


# ---------------------------------------------------------------------------
# 1. Apple Orchard (and its only approach, Campsite) are offered destinations
# ---------------------------------------------------------------------------

def test_apple_orchard_is_offered_as_a_travel_destination(registry):
    """With enough steps, TRAVEL_BASE + index(apple_orchard) is legal from day 1.

    Before the fix, apple_orchard/campsite carried modelled: false, so this
    action stayed masked False even though the route (house -> grounds ->
    private_drive -> campsite -> apple_orchard, 4 steps) was always reachable
    -- the padlock_code gate passes unconditionally under the sim's
    assumed-solved-puzzle doctrine.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50

    assert g.area_route_cost("apple_orchard") == (4, "house")

    node_ids = A._build_area_node_ids(g.registry)
    mask = A.action_mask(g)
    for dest in ("campsite", "apple_orchard"):
        i = node_ids.index(dest)
        assert mask[A.TRAVEL_BASE + i], f"{dest} must be offered as a travel destination"


def test_reachable_from_house_is_unchanged_by_the_modelled_flip(registry):
    """Flipping `modelled` only changes which nodes are OFFERED as travel
    actions, not which nodes the pathfinder can reach -- campsite and
    apple_orchard were already routable through, so reachable() from "house"
    must report the identical node set (and hop counts) as before the flip.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    dist = reachable(g.registry.area_graph, "house", g._gate_ctx())
    assert dist.get("campsite") == 3
    assert dist.get("apple_orchard") == 4


# ---------------------------------------------------------------------------
# 2. Arriving sets the flag on STATE, never on the shared config
# ---------------------------------------------------------------------------

def test_arriving_at_apple_orchard_sets_state_not_config(registry):
    """travel_to("apple_orchard") records orchard_unlocked on GameState only.

    Same shape as west_gate_unlatched: the config object is shared across
    every episode of a trainer worker, so writing the discovery there would
    leak the bonus into later, unrelated episodes.
    """
    cfg = GameConfig()
    g = Game(cfg, seed=1, registry=registry)
    g.state.steps = 50

    g.travel_to("apple_orchard")

    assert g.state.area == "apple_orchard"
    assert g.state.orchard_unlocked is True
    assert cfg.orchard_unlocked is False, "the shared config must not be mutated"


def test_arriving_does_not_retroactively_grant_steps_this_day(registry):
    """Visiting the Orchard mid-day does not top up the CURRENT day's step
    budget -- st.steps is set once, at reset(), from cfg.orchard_unlocked.
    The owner brief calls out this ordering explicitly: the bonus is earned
    for the FOLLOWING day via carry-over, not applied retroactively today.
    """
    g = Game(GameConfig(starting_steps=50), seed=1, registry=registry)
    steps_before = g.state.steps
    g.travel_to("apple_orchard")
    # Only the area-hop cost should have been deducted; no +20 appears today.
    assert g.state.steps == steps_before - 4


# ---------------------------------------------------------------------------
# 3. carryover() reports it; DayChain carries it into next_config()
# ---------------------------------------------------------------------------

def test_carryover_reports_orchard_unlocked_after_arrival(registry):
    """shops.carryover()["orchard_unlocked"] is True once the Orchard has been reached."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.travel_to("apple_orchard")

    report = carryover(g)
    assert report["orchard_unlocked"] is True


def test_orchard_bonus_applies_from_the_following_day_via_daychain(registry):
    """The full lifecycle: arrive -> carryover -> DayChain.advance() ->
    next_config().orchard_unlocked is True -> a Game built from that config
    starts with +20 steps (Game.reset reads cfg.orchard_unlocked).
    """
    cfg = GameConfig(starting_steps=50)
    chain = DayChain(cfg)

    g = Game(chain.next_config(), seed=1, registry=registry)
    g.state.steps = 50
    g.travel_to("apple_orchard")
    chain.advance(carryover(g))

    next_cfg = chain.next_config()
    assert next_cfg.orchard_unlocked is True

    g2 = Game(next_cfg, seed=2, registry=registry)
    assert g2.state.steps == 50 + 20


# ---------------------------------------------------------------------------
# 4. Clears on attempt wrap
# ---------------------------------------------------------------------------

def test_orchard_unlocked_clears_on_attempt_wrap(registry):
    """A fresh attempt (DayChain wrap past n_days) drops orchard_unlocked, the
    same as every other carry-over discovery -- Blue Prince attempts restart
    from a fresh save, so an earlier attempt's Orchard visit must not persist.
    """
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"orchard_unlocked": True})  # day 1 -> wraps immediately

    assert chain.current_day == 1
    assert chain.carried_flags == {}
    assert chain.next_config().orchard_unlocked is False


# ---------------------------------------------------------------------------
# 5. Regression: must not leak into a fresh Game built from the same config
# ---------------------------------------------------------------------------

def test_orchard_unlocked_does_not_leak_into_a_fresh_game(registry):
    """The 2026-07-28 config-mutation regression, applied to the Orchard: a
    second episode built straight from the SAME GameConfig object (bypassing
    DayChain, as the trainer does per worker) must NOT inherit the bonus just
    because an earlier episode on that config reached the Orchard.
    """
    cfg = GameConfig(day=1, orchard_unlocked=False, starting_steps=50)

    first = Game(cfg, seed=9, registry=registry)
    first.state.steps = 50
    first.travel_to("apple_orchard")
    assert first.state.orchard_unlocked is True
    assert not cfg.orchard_unlocked, "the shared config must not have been mutated"

    # A brand-new episode on the SAME config object.
    second = Game(cfg, seed=123, registry=registry)
    assert second.state.orchard_unlocked is False
    assert second.state.steps == 50, "no +20 bonus without ever having earned it on this config"
