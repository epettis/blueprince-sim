"""Locker Room: on placement, spreads basic keys throughout the estate.

Implemented:
  - spread_keys -- "the Locker Room will spread basic keys throughout the
    estate. This can include the Locker Room itself, but not any rooms
    drafted after the Locker Room" (wiki). The wiki publishes no count and
    no rate for this spread, so the room-count bucket below reuses the
    Secret Garden's fruit bucket for consistency; see its comment for the
    caveat. That many keys are parked in distinct occupied cells, excluding
    the 18 rooms the wiki names as never receiving one (rooms.json's
    flags.no_locker_keys), via GameState.spread_pending, paid out on
    arrival (Game._collect_spread). A Conference Room already on the estate
    redirects every one of those keys, including any that would have landed
    on the Locker Room itself, into the Conference Room's own cell instead
    -- the exclusion list does not apply to the Conference Room in that case.

Not modelled:
  - The 17 locked lockers and their datamined loot table: opening one is a
    player action that needs its own action-space slot, which belongs with
    a retrain rather than a passive spread.
  - Per-room spread failure beyond the 18 excluded rooms: as with the
    Secret Garden, the computed count is simply the number of keys placed.
"""

from __future__ import annotations

from .. import Hook, room_hook

# Room-count bucket thresholds and their key counts. The wiki publishes no
# figure for the Locker Room's own spread, so this borrows the Secret
# Garden's fruit-count bucket (0-9 -> 3, 10-24 -> 4, 25+ -> 6) for
# consistency between the estate's two spreaders. The wiki separately notes
# that keys are rarer than other spread items, so this borrowed bucket
# likely OVERSTATES how many keys the Locker Room actually spreads.
SMALL_HOUSE_MAX = 9
MEDIUM_HOUSE_MAX = 24
SMALL_HOUSE_KEYS = 3
MEDIUM_HOUSE_KEYS = 4
LARGE_HOUSE_KEYS = 6

# The 18 rooms the wiki names as never receiving a spread key (Antechamber,
# Room 46, The Foundation, Spare Room, Gift Shop, Passageway, Dovecote,
# Armory, Rotunda, Darkroom, Pump Room, Vestibule, Mechanarium, Maid's
# Chamber, Lavatory, Furnace, Freezer, Bookshop) are sourced from rooms.json's
# flags.no_locker_keys per room rather than listed here as ids, per the
# repo's no-branch-on-room-id rule; Room.no_locker_keys carries the parsed flag.
def _keys_for_room_count(room_count: int) -> int:
    """Bucketed key count, per the module docstring."""
    if room_count <= SMALL_HOUSE_MAX:
        return SMALL_HOUSE_KEYS
    if room_count <= MEDIUM_HOUSE_MAX:
        return MEDIUM_HOUSE_KEYS
    return LARGE_HOUSE_KEYS


@room_hook("locker_room", Hook.ON_PLACE)
def spread_keys(game, room, ctx_room) -> None:
    """"Spread basic keys throughout the estate" -- see the module docstring."""
    state = game.state
    cell = game.room_cells.get(room.id)
    if cell is None:
        return  # no grid cell to spread from

    conference_cell = game.room_cells.get("conference_room")
    room_count = sum(1 for idx in state.grid if idx >= 0)
    if state.outer_room_drafted:
        room_count += 1
    count = _keys_for_room_count(room_count)

    if conference_cell is not None:
        state.spread_pending.setdefault(conference_cell, []).append(("key", count))
        return

    occupied = [i for i, idx in enumerate(state.grid)
                if idx >= 0 and not game.registry.rooms[idx].no_locker_keys]
    n = min(count, len(occupied))
    if n <= 0:
        return
    chosen_cells = game.rng.stream("locker_room_spread_cells").sample(occupied, n)
    for target_cell in chosen_cells:
        state.spread_pending.setdefault(target_cell, []).append(("key", 1))
