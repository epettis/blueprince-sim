"""Closet guaranteed items, for the base room and its three upgrade variants,
plus each variant's "adjoined" adjacency bonus (effects/rooms/closet.py).

The base Closet and both the Hallway and Bedroom variants grant 2 random items
on first entry; Empty Closet grants none. Nothing is inherited through
``variant_of``, so each record carries its own count.

The variants' "+N extra items if drafted adjoined to a Hallway/Bedroom/Red
Room" bonus is evaluated once, at ON_PLACE, against the grid as it stood at
that instant, and paid out later on the Closet's own first ON_ENTER.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck

CLOSET_CELL = 12  # rank 3, center column -- has all four orthogonal neighbors
NEIGHBOR_CELL = 11  # rank 3, west of CLOSET_CELL


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` luck-rolled extra item
    never procs, keeping the guaranteed-item-count assertions below
    deterministic."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=seed)
    suppress_luck(g)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def _place(g: Game, room_id: str, cell: int) -> None:
    """Place ``room_id`` at ``cell`` through Game._place_room, firing ON_PLACE."""
    room = g.registry.by_id[room_id]
    g._place_room(room, cell, room.door_mask)


def test_hallway_closet_grants_two_items():
    """hallway_closet__ix39 grants exactly 2 items on first entry when no
    Hallway neighbor is present at placement (its own flat baseline)."""
    cell = 5
    g = _make_game_with_room("hallway_closet__ix39", cell)
    found0 = len(g.state.items_found_log)

    g._enter(cell)
    assert len(g.state.items_found_log) == found0 + 2


def test_bedroom_closet_grants_two_items():
    """bedroom_closet__ix40 grants exactly 2 items on first entry when no
    Bedroom neighbor is present at placement (its own flat baseline)."""
    cell = 5
    g = _make_game_with_room("bedroom_closet__ix40", cell)
    found0 = len(g.state.items_found_log)

    g._enter(cell)
    assert len(g.state.items_found_log) == found0 + 2


def test_empty_closet_grants_no_items():
    """empty_closet__ix41 correctly grants 0 items on first entry -- its
    "0 items" baseline needed no fix; this guards against a future regression."""
    cell = 5
    g = _make_game_with_room("empty_closet__ix41", cell)
    found0 = len(g.state.items_found_log)

    g._enter(cell)
    assert len(g.state.items_found_log) == found0


def test_hallway_closet_bonus_fires_when_adjoined_to_a_hallway_at_placement():
    """The +1 item Hallway-adjacency bonus pays out when a Hallway-category
    room is already an orthogonal neighbor at the moment of placement."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "hallway", NEIGHBOR_CELL)
    _place(g, "hallway_closet__ix39", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2 + 1


def test_hallway_closet_bonus_absent_without_a_hallway_neighbor():
    """No Hallway neighbor at placement means the Hallway Closet grants only
    its flat 2 items -- no bonus is paid."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "hallway_closet__ix39", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2


def test_bedroom_closet_bonus_fires_when_adjoined_to_a_bedroom_at_placement():
    """The +2 item Bedroom-adjacency bonus pays out when a Bedroom-category
    room is already an orthogonal neighbor at the moment of placement."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "bedroom", NEIGHBOR_CELL)
    _place(g, "bedroom_closet__ix40", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2 + 2


def test_hallway_closet_ignores_a_bedroom_neighbor():
    """A Hallway Closet next to a Bedroom gets nothing extra -- each variant
    only reacts to its own category, not any neighbor."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "bedroom", NEIGHBOR_CELL)
    _place(g, "hallway_closet__ix39", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2


def test_bedroom_closet_ignores_a_hallway_neighbor():
    """A Bedroom Closet next to a Hallway gets nothing extra -- each variant
    only reacts to its own category, not any neighbor."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "hallway", NEIGHBOR_CELL)
    _place(g, "bedroom_closet__ix40", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2


def test_empty_closet_bonus_fires_when_adjoined_to_a_red_room_at_placement():
    """The +4 item Red-Room-adjacency bonus pays out when a Red-category room
    is already an orthogonal neighbor at the moment of placement -- the one
    variant whose flat baseline is 0, so the bonus is its entire yield."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "lavatory", NEIGHBOR_CELL)  # category "red"
    _place(g, "empty_closet__ix41", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 4


def test_empty_closet_bonus_absent_without_a_red_room_neighbor():
    """No Red Room neighbor at placement means the Empty Closet still grants
    its flat 0 items -- no bonus is paid."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "empty_closet__ix41", CLOSET_CELL)

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0


def test_bonus_neighbor_placed_after_the_closet_does_not_retroactively_grant_it():
    """A qualifying neighbor placed after the Closet must not grant the bonus
    -- the condition is fixed at ON_PLACE, not re-checked at entry."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1)
    suppress_luck(g)
    _place(g, "bedroom_closet__ix40", CLOSET_CELL)  # no neighbor yet
    _place(g, "bedroom", NEIGHBOR_CELL)  # qualifying neighbor arrives afterward

    found0 = len(g.state.items_found_log)
    g._enter(CLOSET_CELL)
    assert len(g.state.items_found_log) == found0 + 2  # flat baseline only, no +2 bonus
