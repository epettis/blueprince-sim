"""Room 8's allowance reward on entry: first solve vs. later solves, and carry-over."""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from luck_utils import suppress_luck


def _make_game_with_room(room_id: str, cell: int, cfg: GameConfig | None = None,
                         seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` extra-item roll never
    fires, isolating the guaranteed grant from the ordinary luck pipeline.
    """
    g = Game(cfg if cfg is not None else GameConfig(special_items=True), seed=seed)
    suppress_luck(g)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_first_solve_grants_four_allowance():
    """Entering Room 8 for the first time in an attempt raises allowance by 4
    (two Allowance Tokens at +2 each)."""
    cell = 5
    g = _make_game_with_room("room_8", cell)
    before = g.state.allowance
    g._enter(cell)
    assert g.state.allowance == before + 4
    assert g.state.room8_solved is True


def test_second_room_8_same_day_grants_two_allowance():
    """A second Room 8 entered later the same day raises allowance by only 2:
    Room 8 resets each time it is drafted, so a day can hold more than one, but
    only the first solved that day pays the full first-solve reward."""
    cell_a, cell_b = 5, 7
    g = _make_game_with_room("room_8", cell_a)
    room = g.registry.by_id["room_8"]
    g.state.grid[cell_b] = room.idx
    g.state.placed_doors[cell_b] = room.door_mask

    g._enter(cell_a)
    after_first = g.state.allowance
    g._enter(cell_b)
    assert g.state.allowance == after_first + 2


def test_carried_room8_solved_pays_repeat_reward_on_first_solve_today():
    """A day whose config carries room8_solved=True pays 2 on its first solve
    today, not 4 -- the first-solve/later-solve split is per attempt, not per day."""
    cell = 5
    cfg = GameConfig(special_items=True, room8_solved=True)
    g = _make_game_with_room("room_8", cell, cfg=cfg)
    before = g.state.allowance
    g._enter(cell)
    assert g.state.allowance == before + 2


def test_carryover_reports_room8_solved():
    """carryover() reports room8_solved true after a solve and false without one."""
    cell = 5
    g = _make_game_with_room("room_8", cell)
    assert g.carryover()["room8_solved"] is False
    g._enter(cell)
    assert g.carryover()["room8_solved"] is True
