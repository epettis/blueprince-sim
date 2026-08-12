"""Secret Garden: on entry, pulls the Antechamber's west lever (design doc
antechamber-lever-design.md); on placement, spreads fruit through the house.

Implemented:
  - pull_west_lever -- no extra cost beyond entering.
  - spread_fruit -- "Spread Fruit throughout the House." Room count (rooms on
    the estate when the Secret Garden is drafted, including the Entrance
    Hall/Antechamber and the Outer Room) plus a soil bonus gives the total
    fruit count, capped, then that many apples/oranges (equal proportion) are
    parked in distinct occupied cells via GameState.spread_pending and paid
    out on arrival (Game._collect_spread). A Conference Room already on the
    estate replaces the whole computation with a fixed payout into its own
    cell.

Not modelled:
  - Per-cell soil quality: the wiki text does not publish the soil map (only
    an image), so SOIL_BONUS below is a flat "Good" stand-in for every cell
    rather than a lookup keyed on the drafted cell.
  - Per-room spread failure: the wiki notes some targeted rooms do not
    actually receive their spread, with no published success rate. The
    computed count is simply the number of fruit actually placed.
  - Outer-room drafts: the Secret Garden has no grid cell when drafted from
    the outer-room pool, so nothing spreads (matches the only reported
    evidence -- an outer Secret Garden does not appear to spread fruit).
"""

from __future__ import annotations

from ...grid import E
from ...locks import DOOR_SEALED, segment_key
from .. import Hook, provides_lever, room_hook

WEST_SEGMENT_CELL = 41  # column 1: its east face is the Antechamber's west door

# Room-count bucket thresholds and their fruit counts (wiki: 0-9 -> 3, 10-24 -> 4, 25+ -> 6).
SMALL_HOUSE_MAX = 9
MEDIUM_HOUSE_MAX = 24
SMALL_HOUSE_FRUIT = 3
MEDIUM_HOUSE_FRUIT = 4
LARGE_HOUSE_FRUIT = 6

# Flat stand-in for the unpublished per-cell soil map; see the module docstring.
SOIL_BONUS = 4

SPREAD_CAP = 10  # total fruit is capped here regardless of bucket + soil

# The fruit a spread produces, one equal-weight roll per fruit placed.
SPREAD_FRUIT = ("apple", "orange")

# Conference Room branch: a fixed payout replaces the normal spread entirely.
CONFERENCE_ROOM_APPLES = 4
CONFERENCE_ROOM_ORANGES = 3


def pull_west_lever(game, cell: int) -> None:
    """Open the sealed west segment, if the lever is still there to pull."""
    if not game.cfg.antechamber_levers:
        return
    seg = segment_key(WEST_SEGMENT_CELL, E)
    if game.state.door_state.get(seg) != DOOR_SEALED:
        return
    game._open_segment(WEST_SEGMENT_CELL, E)


provides_lever("secret_garden", pull_west_lever)


def _fruit_for_room_count(room_count: int) -> int:
    """Bucketed base fruit count before the soil bonus, per the module docstring."""
    if room_count <= SMALL_HOUSE_MAX:
        return SMALL_HOUSE_FRUIT
    if room_count <= MEDIUM_HOUSE_MAX:
        return MEDIUM_HOUSE_FRUIT
    return LARGE_HOUSE_FRUIT


@room_hook("secret_garden", Hook.ON_PLACE)
def spread_fruit(game, room, ctx_room) -> None:
    """"Spread Fruit throughout the House" -- see the module docstring."""
    state = game.state
    cell = game.room_cells.get(room.id)
    if cell is None:
        return  # outer-room draft: no grid cell to spread from

    conference_cell = game.room_cells.get("conference_room")
    if conference_cell is not None:
        entries = state.spread_pending.setdefault(conference_cell, [])
        entries.append(("apple", CONFERENCE_ROOM_APPLES))
        entries.append(("orange", CONFERENCE_ROOM_ORANGES))
        return

    room_count = sum(1 for idx in state.grid if idx >= 0)
    if state.outer_room_drafted:
        room_count += 1
    count = min(_fruit_for_room_count(room_count) + SOIL_BONUS, SPREAD_CAP)

    occupied = [i for i, idx in enumerate(state.grid) if idx >= 0]
    n = min(count, len(occupied))
    if n <= 0:
        return
    chosen_cells = game.rng.stream("secret_garden_spread_cells").sample(occupied, n)
    for target_cell in chosen_cells:
        fruit = SPREAD_FRUIT[game.rng.roll_weighted("secret_garden_fruit_kind", (1.0, 1.0))]
        state.spread_pending.setdefault(target_cell, []).append((fruit, 1))
