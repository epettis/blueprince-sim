"""Sauna: a one-day-pulse cross-day bonus.

Effect text: "Tomorrow, you will start the day with 20 extra steps." The
wiki's "Tomorrow Rooms" category frames this as scoped to the single
following day, not a permanent unlock like the Apple Orchard -- so these
tests drive a real DayChain across three days to pin both the grant and its
lapse.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_entering_sauna_grants_20_extra_steps_the_following_day(registry, cfg):
    """Entering the Sauna on day N leaves the player with 20 more starting
    steps on day N+1, on top of the normal starting_steps baseline."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["sauna"]
    g1._place_room(room, 7, S)
    g1.move(N)
    assert g1.state.sauna_visited

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.steps == cfg.starting_steps + 20


def test_a_day_without_a_sauna_visit_does_not_carry_the_bonus(registry, cfg):
    """A day that never enters a Sauna leaves the next day's starting steps
    unchanged -- the bonus must not apply unconditionally."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    assert not g1.state.sauna_visited

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.steps == cfg.starting_steps


def test_the_bonus_lapses_the_day_after_it_is_granted(registry, cfg):
    """The +20 steps applies only to the immediate next day: a later day that
    does not re-enter a Sauna does not keep inheriting it forever."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["sauna"]
    g1._place_room(room, 7, S)
    g1.move(N)

    chain.advance(g1.carryover())          # day 2 gets the bonus
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.steps == cfg.starting_steps + 20

    chain.advance(g2.carryover())          # day 2 did not revisit a Sauna
    g3 = Game(chain.next_config(), seed=3)
    assert g3.state.steps == cfg.starting_steps
