"""Secret Garden: the west Antechamber segment lever, and the fruit spread
("Spread Fruit throughout the House.") effect.

Split out of the old test_antechamber_levers.py; see
tests/test_antechamber_levers.py for the cross-cutting lever-gate invariants
that stayed there.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects import Hook, fire
from blueprince_sim.engine.game import ANTECHAMBER_CELL, ENTRANCE_CELL, Game
from blueprince_sim.engine.grid import E, S, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED

APPLE_STEPS = 2
ORANGE_STEPS = 5


def _game(*, levers: bool = True, registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``.

    Luck is floored so filler Corridors' luck-rolled ``additional_max`` extra
    item never procs, keeping step-total assertions below deterministic (same
    rationale as tests/rooms/test_closet.py).
    """
    cfg = GameConfig(antechamber_levers=levers, **extra)
    g = Game(cfg, seed=1, **({"registry": registry} if registry is not None else {}))
    g.state.luck = 0
    return g


def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
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


def _fill_cells(g: Game, n: int, *, exclude: set[int]) -> list[int]:
    """Place ``n`` filler Corridors on distinct, otherwise-empty cells.

    Used to pad the estate's room count for the bucket-arithmetic tests, and
    to give the spread enough distinct occupied cells to land in.
    """
    cells = []
    for cell in range(45):
        if cell in exclude or g.state.grid[cell] >= 0:
            continue
        cells.append(cell)
        if len(cells) == n:
            break
    for cell in cells:
        _place_at(g, "corridor", cell, 0)
    return cells


def test_secret_garden_opens_west(registry):
    """Entering the Secret Garden opens the west Antechamber segment (41, E)."""
    g = _game(levers=True, registry=registry,
              satisfied_conditions=frozenset({"secret_garden_key"}))
    _place_at(g, "secret_garden", 41, E | W)
    _enter_at(g, 41)

    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_OPEN
    # South and East remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED


def test_outer_secret_garden_spreads_nothing(registry):
    """A Secret Garden drafted from the outer-room pool has no grid cell
    (Game.room_cells is only populated on the grid-placement path), so the
    spread must place nothing -- the only reported evidence is that fruit
    does not spread from an outer Secret Garden.
    """
    g = _game(levers=False, registry=registry)
    secret_garden_room = g.registry.by_id["secret_garden"]
    assert "secret_garden" not in g.room_cells

    fire(g, secret_garden_room, Hook.ON_PLACE)

    assert g.state.spread_pending == {}


def test_spread_collected_regardless_of_prior_first_entry(registry):
    """The load-bearing case: a room walked through BEFORE the Secret Garden
    spreads into it must still pay out on the player's next arrival -- the
    drain in Game._collect_spread is not gated on first entry, unlike the
    ON_ENTER effects it sits beside.
    """
    g = _game(levers=False, registry=registry)
    _place_at(g, "corridor", 5, 0)
    _enter_at(g, 5)  # first entry, well before any fruit is parked here
    steps_before = g.state.steps

    g.state.spread_pending[5] = [("apple", 3)]  # spread arrives only now
    _enter_at(g, 5)  # a later arrival at an already-entered cell

    assert g.state.steps == steps_before + 3 * APPLE_STEPS


def test_spread_pays_out_on_arrival_and_only_once(registry):
    """Fruit parked in a cell is collected on arrival with the correct step
    total, and a further arrival at the same cell grants nothing more -- the
    entry is drained, not merely read.
    """
    g = _game(levers=False, registry=registry)
    _place_at(g, "corridor", 5, 0)
    g.state.spread_pending[5] = [("apple", 2), ("orange", 1)]
    steps_before = g.state.steps

    _enter_at(g, 5)
    assert g.state.steps == steps_before + 2 * APPLE_STEPS + ORANGE_STEPS

    steps_after_first = g.state.steps
    _enter_at(g, 5)
    _enter_at(g, 5)
    assert g.state.steps == steps_after_first


def test_conference_room_branch_pays_fixed_amount_independent_of_house_size(registry):
    """A Conference Room on the estate replaces the normal spread with a fixed
    4 apples + 3 oranges (23 steps) into its own cell, with nothing spread
    anywhere else, and the payout does not depend on how many rooms are on
    the estate.
    """
    for filler_count in (0, 30):  # a small house and a very large one
        g = _game(levers=False, registry=registry)
        conference_cell = 20
        garden_cell = 21
        _fill_cells(g, filler_count, exclude={ENTRANCE_CELL, ANTECHAMBER_CELL,
                                               conference_cell, garden_cell})
        _place_at(g, "conference_room", conference_cell, 0)
        _place_at(g, "secret_garden", garden_cell, 0)
        secret_garden_room = g.registry.by_id["secret_garden"]

        fire(g, secret_garden_room, Hook.ON_PLACE)

        assert set(g.state.spread_pending) == {conference_cell}
        assert g.state.spread_pending[conference_cell] == [
            ("apple", 4), ("orange", 3)]

        steps_before = g.state.steps
        _enter_at(g, conference_cell)
        assert g.state.steps == steps_before + 4 * APPLE_STEPS + 3 * ORANGE_STEPS


def test_normal_spread_total_follows_bucket_and_soil_arithmetic(registry):
    """The normal (no Conference Room) spread's total fruit count is the
    room-count bucket (0-9->3, 10-24->4, 25+->6) plus the flat +4 soil bonus,
    capped at 10 -- checked at all three buckets, with enough distinct
    occupied cells available that the count is never reduced by scarcity.
    """
    garden_cell = 21
    # (extra filler rooms, expected total fruit); entrance+antechamber+garden = 3
    # rooms already on the grid before any filler is added.
    cases = [
        (6, 7),    # 3 + 6 fillers = 9 rooms (0-9 bucket): 3 + 4 = 7
        (7, 8),    # 3 + 7 fillers = 10 rooms (10-24 bucket): 4 + 4 = 8
        (30, 10),  # 3 + 30 fillers = 33 rooms (25+ bucket): 6 + 4 = 10 (at the cap)
    ]
    for filler_count, expected_total in cases:
        g = _game(levers=False, registry=registry)
        _fill_cells(g, filler_count, exclude={ENTRANCE_CELL, ANTECHAMBER_CELL, garden_cell})
        _place_at(g, "secret_garden", garden_cell, 0)
        secret_garden_room = g.registry.by_id["secret_garden"]

        fire(g, secret_garden_room, Hook.ON_PLACE)

        total = sum(count for entries in g.state.spread_pending.values()
                    for _what, count in entries)
        assert total == expected_total
        assert total <= 10


def test_spread_reaches_only_cells_occupied_at_the_draft_moment(registry):
    """A room drafted AFTER the Secret Garden receives no fruit: the spread
    is a one-shot event over the cells occupied the instant it fires, not a
    standing effect that later rooms can benefit from.
    """
    garden_cell = 21
    g = _game(levers=False, registry=registry)
    _fill_cells(g, 6, exclude={ENTRANCE_CELL, ANTECHAMBER_CELL, garden_cell})
    _place_at(g, "secret_garden", garden_cell, 0)
    secret_garden_room = g.registry.by_id["secret_garden"]
    fire(g, secret_garden_room, Hook.ON_PLACE)

    late_cell = 30
    assert late_cell not in g.state.spread_pending  # empty before the late room lands
    _place_at(g, "corridor", late_cell, 0)  # drafted after the spread already fired

    assert late_cell not in g.state.spread_pending


def test_only_apples_and_oranges_are_ever_spread(registry):
    """Every fruit a spread places is an apple or an orange, never a banana.

    Swept across enough seeds and a large enough house that a stray banana
    would surface: it restores 3 steps, distinct from apple's 2 and orange's
    5, so the step value alone identifies which fruit was placed.
    """
    garden_cell = 21
    seen_steps = set()
    for seed in range(20):
        cfg = GameConfig(antechamber_levers=False)
        g = Game(cfg, seed=seed, registry=registry)
        g.state.luck = 0  # no luck-rolled extra items from filler Corridors muddying step deltas
        _fill_cells(g, 30, exclude={ENTRANCE_CELL, ANTECHAMBER_CELL, garden_cell})
        _place_at(g, "secret_garden", garden_cell, 0)
        secret_garden_room = g.registry.by_id["secret_garden"]
        fire(g, secret_garden_room, Hook.ON_PLACE)

        for cell, entries in list(g.state.spread_pending.items()):
            steps_before = g.state.steps
            _enter_at(g, cell)
            gained = g.state.steps - steps_before
            per_fruit_count = sum(count for _what, count in entries)
            seen_steps.add(gained / per_fruit_count if per_fruit_count else gained)

    assert seen_steps
    assert seen_steps <= {float(APPLE_STEPS), float(ORANGE_STEPS)}
