"""Mechanical room-type membership via extra_categories/Room.is_category.

The wiki publishes a definitive list of eight Mechanical rooms (Utility
Closet, Boiler Room, Pump Room, Security, Workshop, Laboratory, Electric Eel
Aquarium, Mechanarium). "mechanical" is carried as an ``extra_categories``
member rather than a primary ``category`` -- every one of the eight still
displays/observes as its usual primary category (blueprint) -- and it is a
room-type tag, not a colour, so this also pins that a non-colour member
cannot leak into a colour-membership check.
"""

from __future__ import annotations

import pytest

from blueprince_sim.engine.model import Registry

MECHANICAL_ROOM_IDS = {
    "utility_closet",
    "boiler_room",
    "pump_room",
    "security",
    "workshop",
    "laboratory",
    "electric_eel_aquarium__ix4",
    "mechanarium",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def test_all_eight_mechanical_rooms_answer_is_category_mechanical(registry):
    """Every room on the wiki's Mechanical list counts as "mechanical"."""
    for room_id in MECHANICAL_ROOM_IDS:
        room = registry.by_id[room_id]
        assert room.is_category("mechanical"), f"{room_id} does not count as mechanical"


def test_a_non_mechanical_room_does_not_answer_is_category_mechanical(registry):
    """A room absent from the wiki's Mechanical list (Closet) is not mechanical,
    proving membership is scoped to the eight rather than accidentally global.
    """
    assert not registry.by_id["closet"].is_category("mechanical")


def test_electric_eel_aquarium_is_mechanical_and_every_colour(registry):
    """The Aquarium gains "mechanical" on top of its existing every-colour
    membership rather than in place of it -- both sets of extras must hold
    simultaneously.
    """
    room = registry.by_id["electric_eel_aquarium__ix4"]
    assert room.is_category("mechanical")
    for colour in ("red", "green", "hallway", "bedroom", "shop", "blackprint"):
        assert room.is_category(colour), f"lost {colour} membership"


def test_mechanical_membership_does_not_grant_colour_membership(registry):
    """Adding "mechanical" to a room that never carried any colour extras
    (Boiler Room, primary category "blueprint") must not make it satisfy a
    colour query it did not satisfy before -- "mechanical" is a room-type tag,
    not a colour, and Room.is_category does plain string membership against
    ``categories``, so a non-colour member cannot accidentally match one.
    """
    room = registry.by_id["boiler_room"]
    assert room.is_category("mechanical")
    assert not room.is_category("green")
    assert not room.is_category("red")
