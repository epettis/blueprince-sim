"""Locker Room: "spread basic keys throughout the estate" on placement.

Mirrors tests/rooms/test_secret_garden.py's setup style: rooms are placed
directly on the grid (no drafting), then the ON_PLACE hook is fired by hand.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects import Hook, fire
from blueprince_sim.engine.game import ANTECHAMBER_CELL, ENTRANCE_CELL, Game

# The 18 rooms the wiki names as never receiving a spread key (rooms.json's
# flags.no_locker_keys), verbatim from the module under test's docstring.
EXCLUDED_ROOM_IDS = (
    "antechamber", "room_46", "the_foundation", "spare_room", "gift_shop",
    "passageway", "dovecote", "the_armory", "rotunda", "darkroom",
    "pump_room", "vestibule", "mechanarium", "maids_chamber", "lavatory",
    "furnace", "freezer", "bookshop",
)

# Small-house bucket (0-9 rooms -> 3 keys); used to size fillers deterministically.
SMALL_HOUSE_KEYS = 3


def _game(*, registry=None, **extra) -> Game:
    """Fresh game with luck floored so filler rooms' luck-rolled bonus items
    never proc, keeping resource-count assertions deterministic.
    """
    cfg = GameConfig(**extra)
    g = Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))
    g.state.luck = 0
    return g


def _place_at(g: Game, room_id: str, cell: int, mask: int = 0) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to cell and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


def test_locker_room_places_keys_in_occupied_cells(registry):
    """Spread keys land only in cells already occupied at the draft moment."""
    g = _game(registry=registry)
    locker_cell, filler_cell = 10, 15
    _place_at(g, "corridor", filler_cell)
    _place_at(g, "locker_room", locker_cell)
    locker_room = g.registry.by_id["locker_room"]

    fire(g, locker_room, Hook.ON_PLACE)

    assert g.state.spread_pending  # at least one key was placed somewhere
    for cell in g.state.spread_pending:
        assert g.state.grid[cell] >= 0


def test_locker_room_can_seed_itself(registry):
    """The Locker Room's own cell is a legal spread target -- "This can
    include the Locker Room itself" (wiki) -- swept across seeds since the
    spread is a sample, not a guarantee, for any single cell.
    """
    seeded_self = False
    for seed in range(30):
        cfg = GameConfig()
        g = Game(cfg, seed=seed, registry=registry)
        g.state.luck = 0
        locker_cell = 10
        _place_at(g, "locker_room", locker_cell)
        locker_room = g.registry.by_id["locker_room"]

        fire(g, locker_room, Hook.ON_PLACE)

        if locker_cell in g.state.spread_pending:
            seeded_self = True
            break

    assert seeded_self


def test_none_of_the_eighteen_excluded_rooms_ever_receives_a_key(registry):
    """None of the 18 wiki-named rooms ever receives a spread key, swept
    across several seeds and with every excluded room placed at once so a
    single stray key would be caught. Also covers the Antechamber, which is
    pre-placed at ANTECHAMBER_CELL by every fresh Game and is itself one of
    the 18.
    """
    locker_cell = 44  # distinct from ENTRANCE_CELL (2), ANTECHAMBER_CELL (42)
    excluded_cells = list(range(5, 5 + len(EXCLUDED_ROOM_IDS)))  # 5..22, clear of both
    assert ENTRANCE_CELL not in excluded_cells and ANTECHAMBER_CELL not in excluded_cells

    for seed in range(20):
        cfg = GameConfig()
        g = Game(cfg, seed=seed, registry=registry)
        g.state.luck = 0
        _place_at(g, "locker_room", locker_cell)
        for room_id, cell in zip(EXCLUDED_ROOM_IDS, excluded_cells):
            _place_at(g, room_id, cell)
        locker_room = g.registry.by_id["locker_room"]

        fire(g, locker_room, Hook.ON_PLACE)

        for cell in g.state.spread_pending:
            landed_id = g.registry.rooms[g.state.grid[cell]].id
            assert landed_id not in EXCLUDED_ROOM_IDS, (
                f"seed {seed}: a key landed on excluded room {landed_id!r}"
            )


def test_room_drafted_after_locker_room_gets_nothing(registry):
    """A room drafted AFTER the Locker Room receives no key: the spread is a
    one-shot event over the cells occupied at the draft moment.
    """
    g = _game(registry=registry)
    locker_cell = 10
    _place_at(g, "locker_room", locker_cell)
    locker_room = g.registry.by_id["locker_room"]
    fire(g, locker_room, Hook.ON_PLACE)

    late_cell = 20
    _place_at(g, "corridor", late_cell)

    assert late_cell not in g.state.spread_pending


def test_conference_room_redirects_all_keys_including_the_locker_rooms_own(registry):
    """With a Conference Room on the estate, every key the Locker Room would
    have spread -- including onto itself -- lands in the Conference Room's
    cell instead, and nothing lands anywhere else. The exclusion list does
    not apply to the Conference Room in this branch.
    """
    g = _game(registry=registry)
    conference_cell, locker_cell = 5, 10
    _place_at(g, "conference_room", conference_cell)
    _place_at(g, "locker_room", locker_cell)
    locker_room = g.registry.by_id["locker_room"]

    fire(g, locker_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {conference_cell}
    assert g.state.spread_pending[conference_cell] == [("key", SMALL_HOUSE_KEYS)]


def test_spread_keys_are_actually_collected_on_arrival(registry):
    """Parked keys are granted on the player's arrival at the cell, and a
    further arrival grants nothing more -- the entry is drained, not read.
    """
    g = _game(registry=registry)
    locker_cell = 10
    g.state.spread_pending[locker_cell] = [("key", 2)]
    _place_at(g, "corridor", locker_cell)
    keys_before = g.state.keys

    _enter_at(g, locker_cell)
    assert g.state.keys == keys_before + 2

    _enter_at(g, locker_cell)
    assert g.state.keys == keys_before + 2  # no further gain on re-entry
