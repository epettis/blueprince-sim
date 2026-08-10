"""Observatory: a permanent star on every draft.

The room's own effect_text was corrected from the pre-Patch-1.7 wording
("+1 star for each time you've drafted OBSERVATORY", which reads as if the
payout scales with the room's own draft count) to the current flat "+1 star
per draft" wording (blueprince.wiki.gg/wiki/Observatory). The tests below pin
the flat reading: two drafts grant 1 + 1, never 1 + 2.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env.multiday import DayChain


def test_observatory_grants_one_star_on_draft(registry, cfg):
    """Placing the Observatory (ON_PLACE) grants exactly 1 star immediately."""
    g = Game(cfg, seed=1, registry=registry)
    room = registry.by_id["observatory"]
    assert g.state.stars == 0
    g._place_room(room, 7, N | S)  # placed north of the Entrance Hall
    assert g.state.stars == 1


def test_observatory_second_draft_grants_one_more_star_not_two(registry, cfg):
    """Drafting a second Observatory grants 1 + 1 = 2 stars total.

    This is the regression guard for the stale pre-1.7 wording: reading
    "+1 star for each time you've drafted OBSERVATORY" literally would pay
    an increasing amount per draft (1, then 2, ...); the actual effect is a
    flat +1 every time.
    """
    g = Game(cfg, seed=1, registry=registry)
    room = registry.by_id["observatory"]
    g._place_room(room, 7, N | S)
    assert g.state.stars == 1
    g._place_room(room, 8, N | S)  # a second Observatory drafted the same day
    assert g.state.stars == 2


def test_observatory_entry_grants_no_further_star(registry, cfg):
    """Walking into the Observatory grants no additional star -- the grant
    fires once, on draft (ON_PLACE), not on entry (ON_ENTER)."""
    g = Game(cfg, seed=1, registry=registry)
    room = registry.by_id["observatory"]
    g._place_room(room, 7, N | S)
    assert g.state.stars == 1
    g.move(N)
    assert g.state.pos == 7
    assert g.state.stars == 1


def test_stars_survive_day_boundary_via_daychain(registry):
    """A star earned drafting the Observatory on day 1 shows up in
    state.stars on day 2, and AGAIN on day 3 with no further action -- stars
    are a permanent per-attempt total, not a one-day pulse."""
    chain = DayChain(GameConfig(), n_days=200)

    # Day 1: draft the Observatory, earning +1 star.
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    room = g1.registry.by_id["observatory"]
    g1._place_room(room, 7, N | S)
    chain.advance(carryover(g1))

    # Day 2: the total carries over, with no new gain today.
    day2_cfg = chain.next_config()
    assert day2_cfg.stars == 1
    g2 = Game(day2_cfg, seed=2, registry=registry)
    assert g2.state.stars == 1
    chain.advance(carryover(g2))

    # Day 3: still carrying the same total -- permanent, not a one-day pulse.
    day3_cfg = chain.next_config()
    assert day3_cfg.stars == 1
    g3 = Game(day3_cfg, seed=3, registry=registry)
    assert g3.state.stars == 1


def test_stars_reset_on_attempt_wrap():
    """A fresh attempt (DayChain wrap past n_days) drops the star total back
    to the base preset, the same as every other carry-over discovery."""
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"stars": 3})  # day 1 -> wraps immediately

    assert chain.current_day == 1
    assert chain.next_config().stars == 0
