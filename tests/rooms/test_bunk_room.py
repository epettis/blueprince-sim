"""Bunk Room upgrade variants: each doubles a different resource when drafted
with exactly 2 rooms of a category already in the house.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck

HALLWAY_IDS = ("hallway", "corridor", "secret_passage")  # base-pool hallway rooms
GREEN_IDS = ("patio", "courtyard", "cloister")  # base-pool green rooms
SHOP_IDS = ("commissary", "kitchen", "locksmith")  # base-pool shop rooms


def _place_category_rooms(g, registry, room_ids, count):
    """Place ``count`` rooms from ``room_ids`` at arbitrary distinct cells."""
    for i, room_id in enumerate(room_ids[:count]):
        room = registry.by_id[room_id]
        g._place_room(room, 20 + i, room.door_mask)


def test_bunk_room_base_never_doubles_anything(registry, cfg):
    """The base Bunk Room only counts as 2 bedrooms; it carries none of the
    exact-2-category doubling the three upgrade variants add."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    g.state.keys = g.state.gems = g.state.coins = 5
    _place_category_rooms(g, registry, HALLWAY_IDS, 2)
    _place_category_rooms(g, registry, GREEN_IDS, 2)
    _place_category_rooms(g, registry, SHOP_IDS, 2)
    bunk_room = registry.by_id["bunk_room"]
    g._place_room(bunk_room, 10, bunk_room.door_mask)
    assert (g.state.keys, g.state.gems, g.state.coins) == (5, 5, 5)


def test_bunk_room_ix20_doubles_keys_at_exactly_two_hallways(registry, cfg):
    """bunk_room__ix20 doubles KEYS (per meta.glyph_resolution) when drafted
    with exactly 2 Hallways already placed, unlike the base Bunk Room."""
    for room_id, expected_keys in (("bunk_room", 5), ("bunk_room__ix20", 10)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.keys = 5
        _place_category_rooms(g, registry, HALLWAY_IDS, 2)
        room = registry.by_id[room_id]
        g._place_room(room, 10, room.door_mask)
        assert g.state.keys == expected_keys


def test_bunk_room_ix20_boundary_one_and_three_hallways_do_not_double(registry, cfg):
    """The doubling is gated on exactly 2 Hallways: 1 and 3 both leave keys unchanged."""
    for hallway_count in (1, 3):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.keys = 5
        _place_category_rooms(g, registry, HALLWAY_IDS, hallway_count)
        room = registry.by_id["bunk_room__ix20"]
        g._place_room(room, 10, room.door_mask)
        assert g.state.keys == 5, f"{hallway_count} hallways must not trigger the doubling"


def test_bunk_room_ix20_doubling_zero_keys_stays_zero(registry, cfg):
    """Doubling a zero KEYS total is a no-op, not a flat grant."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    g.state.keys = 0
    _place_category_rooms(g, registry, HALLWAY_IDS, 2)
    room = registry.by_id["bunk_room__ix20"]
    g._place_room(room, 10, room.door_mask)
    assert g.state.keys == 0


def test_bunk_room_ix21_doubles_gems_at_exactly_two_green_rooms(registry, cfg):
    """bunk_room__ix21 doubles GEMS (per meta.glyph_resolution) when drafted
    with exactly 2 Green Rooms already placed, unlike the base Bunk Room."""
    for room_id, expected_gems in (("bunk_room", 4), ("bunk_room__ix21", 8)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.gems = 4
        _place_category_rooms(g, registry, GREEN_IDS, 2)
        room = registry.by_id[room_id]
        g._place_room(room, 10, room.door_mask)
        assert g.state.gems == expected_gems


def test_bunk_room_ix21_boundary_one_and_three_green_rooms_do_not_double(registry, cfg):
    """The doubling is gated on exactly 2 Green Rooms: 1 and 3 both leave gems unchanged."""
    for green_count in (1, 3):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.gems = 4
        _place_category_rooms(g, registry, GREEN_IDS, green_count)
        room = registry.by_id["bunk_room__ix21"]
        g._place_room(room, 10, room.door_mask)
        assert g.state.gems == 4, f"{green_count} green rooms must not trigger the doubling"


def test_bunk_room_ix22_doubles_coins_at_exactly_two_shops(registry, cfg):
    """bunk_room__ix22 doubles COINS (per meta.glyph_resolution) when drafted
    with exactly 2 Shops already placed, unlike the base Bunk Room."""
    for room_id, expected_coins in (("bunk_room", 3), ("bunk_room__ix22", 6)):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.coins = 3
        _place_category_rooms(g, registry, SHOP_IDS, 2)
        room = registry.by_id[room_id]
        g._place_room(room, 10, room.door_mask)
        assert g.state.coins == expected_coins


def test_bunk_room_ix22_boundary_one_and_three_shops_do_not_double(registry, cfg):
    """The doubling is gated on exactly 2 Shops: 1 and 3 both leave coins unchanged."""
    for shop_count in (1, 3):
        g = Game(cfg, seed=1)
        suppress_luck(g)
        g.state.coins = 3
        _place_category_rooms(g, registry, SHOP_IDS, shop_count)
        room = registry.by_id["bunk_room__ix22"]
        g._place_room(room, 10, room.door_mask)
        assert g.state.coins == 3, f"{shop_count} shops must not trigger the doubling"


def test_bunk_room_variants_do_not_cross_react_to_other_variants_category(registry, cfg):
    """bunk_room__ix20 (Hallways) does not double keys off 2 Green Rooms or 2 Shops,
    and each variant only reacts to its own category, so the three cannot converge."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    g.state.keys = 5
    _place_category_rooms(g, registry, GREEN_IDS, 2)
    _place_category_rooms(g, registry, SHOP_IDS, 2)
    room = registry.by_id["bunk_room__ix20"]
    g._place_room(room, 30, room.door_mask)
    assert g.state.keys == 5


def test_bunk_room_variant_still_counts_as_two_bedrooms(registry, cfg):
    """bunk_room__ix20 keeps the base's counts-as-2-Bedrooms behaviour, read
    through bedroom_bonus since effects are not inherited via variant_of."""
    g = Game(cfg, seed=1)
    suppress_luck(g)
    bonus_before = g.bedroom_bonus
    room = registry.by_id["bunk_room__ix20"]
    g._place_room(room, 10, room.door_mask)
    assert g.bedroom_bonus == bonus_before + 1  # counts_as_bedrooms(amount=2) adds (2 - 1)
