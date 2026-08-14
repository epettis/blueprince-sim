"""Planetarium: 2 Stars for ENDING the day there, not for merely walking in.

Effect text (blueprince.wiki.gg/wiki/Planetarium, infobox): "If you call it a
day in PLANETARIUM, gain {{icon|star|2}}" -- and the body text: "Ending the
day in the Planetarium will increase star count by 2." Both gate the grant on
day-end, not on entry.

The room's own "grant" effect fires on ON_ENTER by default (see
engine/effects/tier1.py); the Planetarium overrides that default with a
"when": "on_day_end" param so the same handler fires at Game._terminate's
single ON_DAY_END call site (engine/game.py) instead. state.stars is a
carried-forward permanent counter (see GameState.stars), the same shape as
allowance -- these tests also cover that a Planetarium star survives the day
boundary.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_entering_the_planetarium_without_ending_the_day_there_grants_no_stars(registry, cfg):
    """Walking into the Planetarium and then leaving (or simply not ending
    the day there) must not grant the 2 Stars -- the historical bug had the
    "grant" effect firing on ON_ENTER, before the day-end gate the wiki
    describes."""
    g = Game(cfg, seed=1, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)  # enters the Planetarium; stops short of ending the day here
    assert g.state.pos == 7
    assert g.state.stars == 0


def test_ending_the_day_in_the_planetarium_grants_two_stars(registry, cfg):
    """Draining the player's steps to 0 while standing in the Planetarium
    grants exactly 2 Stars, matching the wiki's flat amount."""
    g = Game(cfg, seed=2, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)
    g.state.steps = 0
    g._check_termination()
    assert g.is_done()[0]
    assert g.state.stars == 2


def test_ending_the_day_elsewhere_grants_no_stars(registry, cfg):
    """A Planetarium sitting on the grid, unvisited (or visited but not the
    room the day ends in), never pays out -- the grant is keyed to the
    ON_DAY_END room, not to the Planetarium's mere presence or a past visit."""
    g = Game(cfg, seed=3, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)  # visit it...
    g.move(S)  # ...then leave, back to the Entrance Hall
    g.state.steps = 0
    g._check_termination()
    assert g.is_done()[0]
    assert g.state.stars == 0


def test_a_planetarium_star_carries_over_to_the_next_day(registry):
    """Stars earned ending a day in the Planetarium show up in the next
    day's starting state.stars via DayChain -- the same permanent,
    replace-wholesale carryover shape as allowance (GameState.stars)."""
    chain = DayChain(GameConfig(), n_days=5)

    g1 = Game(chain.next_config(), seed=4, registry=registry)
    room = registry.by_id["planetarium"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    g1.state.steps = 0
    g1._check_termination()
    assert g1.state.stars == 2

    chain.advance(g1.carryover())
    day2_cfg = chain.next_config()
    assert day2_cfg.stars == 2
    g2 = Game(day2_cfg, seed=5, registry=registry)
    assert g2.state.stars == 2
