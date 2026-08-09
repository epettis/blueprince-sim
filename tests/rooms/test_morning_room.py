"""Morning Room: a same-day gem grant plus a one-day-pulse cross-day bonus.

Effect text: "+2 gems. Tomorrow, you will start with 2 gems." The same-day
half is already granted by the room's items.guaranteed table (a gem
count of 2), so these tests only cover the cross-day half, which -- per
the wiki's "Tomorrow Rooms" category -- is scoped to the single following
day, not a permanent unlock.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_entering_morning_room_grants_2_gems_the_same_day(registry, cfg):
    """The room's items.guaranteed table already grants +2 gems on first
    entry, independent of the cross-day bonus this suite otherwise covers."""
    g = Game(cfg, seed=1)
    room = registry.by_id["morning_room"]
    g._place_room(room, 7, N | S)
    gems_before = g.state.gems
    g.move(N)
    assert g.state.gems == gems_before + 2


def test_entering_morning_room_grants_2_extra_starting_gems_the_next_day(registry, cfg):
    """Entering the Morning Room on day N leaves the player with 2 more
    starting gems on day N+1, on top of the normal day-start gem total."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["morning_room"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    assert g1.state.morning_room_visited

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.gems == 2


def test_a_day_without_a_morning_room_visit_does_not_carry_the_bonus(registry, cfg):
    """A day that never enters a Morning Room leaves the next day's starting
    gems unchanged -- the bonus must not apply unconditionally."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    assert not g1.state.morning_room_visited

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.gems == 0


def test_the_bonus_lapses_the_day_after_it_is_granted(registry, cfg):
    """The +2 gems applies only to the immediate next day: a later day that
    does not re-enter a Morning Room does not keep inheriting it forever."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["morning_room"]
    g1._place_room(room, 7, N | S)
    g1.move(N)

    chain.advance(g1.carryover())          # day 2 gets the bonus
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.gems == 2

    chain.advance(g2.carryover())          # day 2 did not revisit a Morning Room
    g3 = Game(chain.next_config(), seed=3)
    assert g3.state.gems == 0
