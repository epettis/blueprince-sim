"""Patio and Spare Patio: "spread 1 gem to each Green Room" on placement.

Mirrors tests/rooms/test_secret_garden.py's setup style: rooms are placed
directly on the grid (no drafting), then the ON_PLACE hook is fired by hand.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects import Hook, fire
from blueprince_sim.engine.game import ANTECHAMBER_CELL, ENTRANCE_CELL, Game
from luck_utils import suppress_luck

# Plain green rooms with no room_hook of their own, used as filler so the
# gem-count arithmetic isn't muddied by another room's ON_PLACE side effect.
FILLER_GREEN_IDS = ("terrace", "veranda", "courtyard")


def _game(*, registry=None, **extra) -> Game:
    """Fresh game with luck floored so filler rooms' luck-rolled bonus items
    never proc, keeping resource-count assertions deterministic.
    """
    cfg = GameConfig(**extra)
    g = Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))
    suppress_luck(g)
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


def _fill_green_cells(g: Game, n: int, *, exclude: set[int]) -> list[int]:
    """Place ``n`` filler green rooms on distinct, otherwise-empty cells."""
    cells: list[int] = []
    if n <= 0:
        return cells
    for cell in range(45):
        if cell in exclude or g.state.grid[cell] >= 0:
            continue
        cells.append(cell)
        if len(cells) == n:
            break
    for i, cell in enumerate(cells):
        _place_at(g, FILLER_GREEN_IDS[i % len(FILLER_GREEN_IDS)], cell)
    return cells


def test_patio_gives_itself_and_each_green_room_exactly_one_gem(registry):
    """Every Green Room on the estate gets exactly one gem, the Patio
    included; a non-Green room gets none.
    """
    g = _game(registry=registry)
    patio_cell, green_cell, hallway_cell = 10, 15, 20
    _place_at(g, "terrace", green_cell)
    _place_at(g, "corridor", hallway_cell)
    _place_at(g, "patio", patio_cell)
    patio_room = g.registry.by_id["patio"]

    fire(g, patio_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {patio_cell, green_cell}
    assert g.state.spread_pending[patio_cell] == [("gem", 1)]
    assert g.state.spread_pending[green_cell] == [("gem", 1)]
    assert hallway_cell not in g.state.spread_pending


def test_aquarium_and_conservatory_count_as_green(registry):
    """The Aquarium (every colour via extra_categories) and the Conservatory
    (primary category green) both receive a gem -- a ``category ==`` check
    would miss the Aquarium, which is why the handler uses ``is_category``.
    """
    g = _game(registry=registry)
    patio_cell, aquarium_cell, conservatory_cell = 10, 15, 20
    _place_at(g, "aquarium", aquarium_cell)
    _place_at(g, "conservatory", conservatory_cell)
    _place_at(g, "patio", patio_cell)
    patio_room = g.registry.by_id["patio"]

    fire(g, patio_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {patio_cell, aquarium_cell, conservatory_cell}


def test_green_room_drafted_after_patio_gets_nothing(registry):
    """A Green Room drafted AFTER the Patio receives no gem: the spread is a
    one-shot event over the cells occupied at the draft moment.
    """
    g = _game(registry=registry)
    patio_cell = 10
    _place_at(g, "patio", patio_cell)
    patio_room = g.registry.by_id["patio"]
    fire(g, patio_room, Hook.ON_PLACE)

    late_cell = 20
    _place_at(g, "terrace", late_cell)

    assert late_cell not in g.state.spread_pending


def test_gem_count_tracks_number_of_green_rooms(registry):
    """The total gem count in spread_pending equals the number of Green
    Rooms on the estate (the Patio included), across several house sizes.
    """
    for filler_count in (0, 3, 7):
        g = _game(registry=registry)
        patio_cell = 10
        _fill_green_cells(g, filler_count, exclude={ENTRANCE_CELL, ANTECHAMBER_CELL, patio_cell})
        _place_at(g, "patio", patio_cell)
        patio_room = g.registry.by_id["patio"]

        fire(g, patio_room, Hook.ON_PLACE)

        total = sum(count for entries in g.state.spread_pending.values()
                    for _what, count in entries)
        assert total == filler_count + 1  # +1 for the Patio itself


def test_spare_patio_spreads_the_same_way(registry):
    """The Spare Patio's own handler gives the same one-gem-per-Green-Room
    behaviour as the base Patio.
    """
    g = _game(registry=registry)
    spare_patio_cell, green_cell, hallway_cell = 10, 15, 20
    _place_at(g, "terrace", green_cell)
    _place_at(g, "corridor", hallway_cell)
    _place_at(g, "spare_patio__ix142", spare_patio_cell)
    spare_patio_room = g.registry.by_id["spare_patio__ix142"]

    fire(g, spare_patio_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {spare_patio_cell, green_cell}
    assert g.state.spread_pending[spare_patio_cell] == [("gem", 1)]
    assert g.state.spread_pending[green_cell] == [("gem", 1)]
    assert hallway_cell not in g.state.spread_pending


def test_conference_room_redirects_all_gems_including_the_patios_own(registry):
    """With a Conference Room on the estate, every gem the Patio would have
    spread -- including the one it would have kept for itself -- lands in
    the Conference Room's cell instead, and nothing lands anywhere else.
    """
    g = _game(registry=registry)
    conference_cell, patio_cell, green_cell = 5, 10, 15
    _place_at(g, "conference_room", conference_cell)
    _place_at(g, "terrace", green_cell)
    _place_at(g, "patio", patio_cell)
    patio_room = g.registry.by_id["patio"]

    fire(g, patio_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {conference_cell}
    assert g.state.spread_pending[conference_cell] == [("gem", 2)]  # Patio + terrace


def test_conference_room_redirects_spare_patios_gems_too(registry):
    """The Conference Room redirect applies to the Spare Patio's handler as
    well, not only the base Patio's.
    """
    g = _game(registry=registry)
    conference_cell, spare_patio_cell = 5, 10
    _place_at(g, "conference_room", conference_cell)
    _place_at(g, "spare_patio__ix142", spare_patio_cell)
    spare_patio_room = g.registry.by_id["spare_patio__ix142"]

    fire(g, spare_patio_room, Hook.ON_PLACE)

    assert set(g.state.spread_pending) == {conference_cell}
    assert g.state.spread_pending[conference_cell] == [("gem", 1)]  # the Spare Patio itself


def test_spread_gems_are_actually_collected_on_arrival(registry):
    """Parked gems are granted on the player's arrival at the cell, and a
    further arrival grants nothing more -- the entry is drained, not read.
    """
    g = _game(registry=registry)
    patio_cell, green_cell = 10, 15
    _place_at(g, "terrace", green_cell)
    _place_at(g, "patio", patio_cell)
    patio_room = g.registry.by_id["patio"]
    fire(g, patio_room, Hook.ON_PLACE)
    gems_before = g.state.gems

    _enter_at(g, green_cell)
    assert g.state.gems == gems_before + 1

    _enter_at(g, green_cell)
    assert g.state.gems == gems_before + 1  # no further gain on re-entry
