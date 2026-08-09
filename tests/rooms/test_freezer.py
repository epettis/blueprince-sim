"""Freezer: today's ending coins/gems carry into tomorrow's starting balance.

Effect text: "Freezes your accounts. (Coins and gems amounts will not reset
at the end of the day and they cannot be adjusted or used until tomorrow.)"
Modelled as a one-day pulse (like Sauna/Morning Room/Break Room): entering
the Freezer carries today's ENDING coins/gems total into tomorrow's starting
balance instead of the normal reset, but a day that does not (re-)enter a
Freezer resets to 0 as usual. The "cannot be adjusted or used" same-day
spend-lock is NOT modelled -- see the accompanying report for why.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_entering_freezer_carries_ending_coins_and_gems_to_the_next_day(registry, cfg):
    """Whatever coins/gems the player is holding when the day ends becomes
    the next day's starting coins/gems, instead of the normal reset to 0."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["freezer"]
    g1._place_room(room, 7, S)
    g1.move(N)
    assert g1.state.freezer_frozen
    g1.state.coins = 12
    g1.state.gems = 3

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.coins == 12
    assert g2.state.gems == 3


def test_a_day_without_a_freezer_visit_resets_coins_and_gems_as_normal(registry, cfg):
    """A day that never enters the Freezer leaves the next day's coins/gems
    at the ordinary day-start reset (0), even if resources were on hand."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    g1.state.coins = 12
    g1.state.gems = 3
    assert not g1.state.freezer_frozen

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.coins == 0
    assert g2.state.gems == 0


def test_the_freeze_lapses_the_day_after_it_is_granted(registry, cfg):
    """The carryover applies only to the immediate next day: a later day
    that does not re-enter the Freezer resets normally, not to a stale total."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["freezer"]
    g1._place_room(room, 7, S)
    g1.move(N)
    g1.state.coins = 12
    g1.state.gems = 3

    chain.advance(g1.carryover())          # day 2 inherits the frozen totals
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.coins == 12
    assert g2.state.gems == 3

    chain.advance(g2.carryover())          # day 2 did not revisit a Freezer
    g3 = Game(chain.next_config(), seed=3)
    assert g3.state.coins == 0
    assert g3.state.gems == 0
