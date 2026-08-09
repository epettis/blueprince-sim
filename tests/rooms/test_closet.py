"""Closet guaranteed items, for the base room and its three upgrade variants.

The base Closet and both the Hallway and Bedroom variants grant 2 random items
on first entry; Empty Closet grants none. Nothing is inherited through
``variant_of``, so each record carries its own count.

The variants' "+N extra items if drafted adjoined to a Hallway/Bedroom/Red
Room" is an adjacency mechanic the sim does not model, so only the flat
baseline is asserted here.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` luck-rolled extra item
    never procs, keeping the guaranteed-item-count assertions below
    deterministic."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_hallway_closet_grants_two_items():
    """hallway_closet__ix39 grants exactly 2 items on first entry, matching
    the base Closet's baseline (its Hallway-adjacency bonus is out of scope)."""
    cell = 5
    g = _make_game_with_room("hallway_closet__ix39", cell)
    found0 = len(g.state.items_found_log)

    g._enter(cell)
    assert len(g.state.items_found_log) == found0 + 2


def test_bedroom_closet_grants_two_items():
    """bedroom_closet__ix40 grants exactly 2 items on first entry, matching
    the base Closet's baseline (its Bedroom-adjacency bonus is out of scope)."""
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
