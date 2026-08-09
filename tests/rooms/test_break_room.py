"""Break Room (a Billiard Room upgrade variant): ending the day there grants
a starting keycard the next day.

Effect text: "If you call it a day in BREAK ROOM, tomorrow you will begin
the day with a staff keycard." The sim has no separate "call it a day"
player action -- every day ends through Game._check_termination (out of
steps or dead end) -- so that termination path is where the room check
lives. Per the wiki this is a one-day pulse, not a permanent unlock: ending
a later day elsewhere does not keep granting the keycard.
"""

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_ending_the_day_in_break_room_grants_a_keycard_the_next_day(registry, cfg):
    """Draining the player's steps to 0 while standing in Break Room leaves
    the next day's game starting with has_keycard True."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["break_room__ix11"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    g1.state.steps = 0
    g1._check_termination()
    assert g1.state.break_room_keycard

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.has_keycard


def test_ending_the_day_elsewhere_does_not_grant_a_keycard(registry, cfg):
    """Draining the player's steps to 0 while NOT standing in Break Room
    leaves the next day's has_keycard False -- entry alone is not enough."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    g1.state.steps = 0
    g1._check_termination()
    assert not g1.state.break_room_keycard

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert not g2.state.has_keycard


def test_the_keycard_lapses_the_day_after_it_is_granted(registry, cfg):
    """The keycard applies only to the immediate next day: a later day that
    does not end in Break Room again does not keep inheriting it forever."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["break_room__ix11"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    g1.state.steps = 0
    g1._check_termination()

    chain.advance(g1.carryover())          # day 2 gets the keycard
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.has_keycard

    chain.advance(g2.carryover())          # day 2 did not end in Break Room
    g3 = Game(chain.next_config(), seed=3)
    assert not g3.state.has_keycard
