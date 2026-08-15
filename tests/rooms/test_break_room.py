"""Break Room (a Billiard Room upgrade variant): ending the day there grants
a starting keycard the next day.

Effect text: "If you call it a day in BREAK ROOM, tomorrow you will begin
the day with a staff keycard." The sim has no separate "call it a day"
player action -- every day ends through Game._check_termination (out of
steps or dead end) -- so that termination path is where the room check
lives. Per the wiki this is a one-day pulse, not a permanent unlock: ending
a later day elsewhere does not keep granting the keycard.

The pulse is implemented by a ``room_hook`` registered at Hook.ON_DAY_END
(engine/effects/rooms/break_room.py), fired through the same
``effects.fire(self, room, Hook.ON_DAY_END)`` call Game._terminate already
makes for every room's day-end effects -- no id-hardcoded branch remains in
game.py. This is the room's own dedicated test file, so the room_hook's
tests live here rather than in tests/test_effect_hooks.py, which covers the
Hook enum's firing mechanics generically (probe tags), not any one room's
handler.

Game._terminate also broadcasts Hook.ON_DAY_END_ALL to every room placed on
the grid (see effects/rooms/clock_tower.py); Break Room's own handler is
registered only at ON_DAY_END, not ON_DAY_END_ALL, so that broadcast must
not change this room's "only where the day ends" behaviour -- pinned below.
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


def test_merely_entering_break_room_does_not_grant_a_keycard(registry, cfg):
    """Walking through Break Room and ending the day in a LATER room leaves
    the flag unset: the pulse is gated on where the day terminates, not on
    having stepped inside at some earlier point (ON_ENTER carries no handler
    for this room -- only ON_DAY_END does)."""
    chain = DayChain(cfg, n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    room = registry.by_id["break_room__ix11"]
    corridor = registry.by_id["corridor"]
    g1._place_room(room, 7, N | S)
    g1._place_room(corridor, 12, N | S)
    g1.move(N)  # entrance -> Break Room (first entry)
    g1.move(N)  # Break Room -> corridor
    g1.state.steps = 0
    g1._check_termination()
    assert not g1.state.break_room_keycard

    chain.advance(g1.carryover())
    g2 = Game(chain.next_config(), seed=2)
    assert not g2.state.has_keycard


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


def test_the_day_end_broadcast_hook_does_not_grant_a_keycard_from_elsewhere(registry, cfg):
    """With Break Room merely present on the grid (never entered) and the day
    ending in a different room, Hook.ON_DAY_END_ALL -- the broadcast every
    placed room now receives at day end (see effects/rooms/clock_tower.py) --
    fires for Break Room too, but its handler is registered only at
    Hook.ON_DAY_END, so the flag still stays unset. Proves the new broadcast
    hook did not leak into this room's "only where the day ends" pulse."""
    g = Game(cfg, seed=1)
    break_room = registry.by_id["break_room__ix11"]
    corridor = registry.by_id["corridor"]
    g._place_room(break_room, 7, N | S)
    g._place_room(corridor, 12, N | S)
    g.state.pos = 12
    g.state.steps = 0

    g._check_termination()

    assert g.is_done()[0]
    assert not g.state.break_room_keycard
