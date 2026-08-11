"""Closet variants: the "adjoined" bonus on top of each variant's flat item
baseline (the flat 2/2/0 counts already come from rooms.json's own
``items.guaranteed``/``additional_max``, unaffected by this module).

Each variant's effect_text promises extra items when the Closet itself is
DRAFTED next to a room of one category:
  - hallway_closet__ix39: "+1 extra item if drafted adjoined to a Hallway"
  - bedroom_closet__ix40: "+2 extra items if drafted adjoined to a Bedroom"
  - empty_closet__ix41:   "+4 extra items if drafted adjoined to a Red Room"

Design:
  - "Adjoined" reads as grid adjacency (engine.grid.ADJACENT), not a shared
    doorway -- CLAUDE.md's grid conventions call out that "a room can be
    adjacent without a doorway joining them", and the effect text never
    mentions a door, only a neighboring room.
  - "Adjoined to a Bedroom/Hallway/Red Room" is one flat yes/no bonus, not
    counted per neighbor -- unlike the Cloister of Mila's explicit
    "for each Bedroom" wording (cloister.py), this text names a single
    threshold condition.
  - The condition is evaluated once, at ON_PLACE, against whatever is
    already on the grid at that instant. A matching room placed beside the
    Closet afterward must not retroactively grant the bonus (rooms are
    placed, never un-placed, so "adjoined at draft time" is a strictly
    smaller set than "adjoined right now"). Since items are only granted on
    first ENTRY (Game._enter -> roll_room_items), the ON_PLACE result has to
    be parked somewhere until the Closet's own ON_ENTER fires and pays out.
  - That parking spot is GameState.closet_bonus_cells, which a fresh
    GameState per day clears on its own, alongside the Cloister of Mila's
    equivalent marker.
  - The bonus items are drawn through items.roll_extra_items, the same
    luck-immune EXTRA_ITEM_TABLE roll a Closet's own guaranteed "random"
    items use -- no separate distribution.
"""

from __future__ import annotations

from ...grid import ADJACENT
from ...items import roll_extra_items
from .. import Hook, room_hook

HALLWAY_CLOSET_BONUS = 1  # hallway_closet__ix39, adjoined to a Hallway
BEDROOM_CLOSET_BONUS = 2  # bedroom_closet__ix40, adjoined to a Bedroom
EMPTY_CLOSET_BONUS = 4    # empty_closet__ix41, adjoined to a Red Room


def _bonus_cells(game) -> set[int]:
    """Cells whose Closet-family bonus condition held at placement."""
    return game.state.closet_bonus_cells


def _has_adjacent_category(game, cell: int, category: str) -> bool:
    """True if an orthogonally adjacent grid cell already holds a placed
    room of ``category`` (grid geometry only -- see module docstring)."""
    grid = game.state.grid
    rooms = game.registry.rooms
    return any(grid[nb] >= 0 and rooms[grid[nb]].is_category(category)
               for _d, _od, nb in ADJACENT[cell])


def _mark_if_adjoined(game, room, category: str) -> None:
    """Record ON_PLACE-time eligibility for ``room``'s own adjacency bonus."""
    cell = game.room_cells.get(room.id)
    if cell is not None and _has_adjacent_category(game, cell, category):
        _bonus_cells(game).add(cell)


def _pay_bonus(game, room, count: int) -> None:
    """Grant the bonus marked at ON_PLACE, if any, and clear the marker."""
    cell = game.room_cells.get(room.id)
    if cell is not None and cell in _bonus_cells(game):
        _bonus_cells(game).discard(cell)
        roll_extra_items(game, count)


@room_hook("hallway_closet__ix39", Hook.ON_PLACE)
def hallway_closet_check_adjacency(game, room, ctx_room) -> None:
    """"+1 extra item if drafted adjoined to a Hallway": marks the cell when
    a Hallway-category room is already an orthogonal neighbor at placement."""
    _mark_if_adjoined(game, room, "hallway")


@room_hook("hallway_closet__ix39", Hook.ON_ENTER)
def hallway_closet_pay_bonus(game, room, ctx_room) -> None:
    """Pays the Hallway-adjacency bonus (1 item) marked at ON_PLACE, if any."""
    _pay_bonus(game, room, HALLWAY_CLOSET_BONUS)


@room_hook("bedroom_closet__ix40", Hook.ON_PLACE)
def bedroom_closet_check_adjacency(game, room, ctx_room) -> None:
    """"+2 extra items if drafted adjoined to a Bedroom": marks the cell when
    a Bedroom-category room is already an orthogonal neighbor at placement."""
    _mark_if_adjoined(game, room, "bedroom")


@room_hook("bedroom_closet__ix40", Hook.ON_ENTER)
def bedroom_closet_pay_bonus(game, room, ctx_room) -> None:
    """Pays the Bedroom-adjacency bonus (2 items) marked at ON_PLACE, if any."""
    _pay_bonus(game, room, BEDROOM_CLOSET_BONUS)


@room_hook("empty_closet__ix41", Hook.ON_PLACE)
def empty_closet_check_adjacency(game, room, ctx_room) -> None:
    """"+4 extra items if drafted adjoined to a Red Room": marks the cell
    when a Red-category room is already an orthogonal neighbor at placement."""
    _mark_if_adjoined(game, room, "red")


@room_hook("empty_closet__ix41", Hook.ON_ENTER)
def empty_closet_pay_bonus(game, room, ctx_room) -> None:
    """Pays the Red-Room-adjacency bonus (4 items) marked at ON_PLACE, if any."""
    _pay_bonus(game, room, EMPTY_CLOSET_BONUS)
