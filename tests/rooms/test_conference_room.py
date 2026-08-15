"""Conference Room: the Capability.DIG_SPOTS registration.

See tests/test_experiments.py's spread_dig_spots section
(test_spread_dig_spots_adds_a_batch_to_the_conference_room_when_present and
test_spread_dig_spots_without_a_conference_room_adds_nothing_and_does_not_crash)
for the full dispatch-through-Game._capability_cell coverage; this file
covers the registration itself.
"""

from __future__ import annotations

from blueprince_sim.engine.effects import Capability, provides_capability


def test_conference_room_provides_dig_spots_capability():
    """The Conference Room registers Capability.DIG_SPOTS (effects/rooms/
    conference_room.py) -- the fact experiments._apply_spread_dig_spots
    resolves via Game._capability_cell instead of a direct
    game.room_cells["conference_room"] lookup. A room silently losing this
    registration would make the Spread Dig Spots effect silently treat the
    Conference Room as unbuilt rather than raising, so this pins the
    registration itself."""
    assert provides_capability("conference_room", Capability.DIG_SPOTS)


def test_ordinary_room_does_not_provide_dig_spots_capability():
    """A room with no Conference Room role (the Corridor) does not provide
    Capability.DIG_SPOTS -- the registry is opt-in, not a default."""
    assert not provides_capability("corridor", Capability.DIG_SPOTS)
