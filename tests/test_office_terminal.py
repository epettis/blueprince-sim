"""The Office's two terminal processes (docs/open_tasks.md task 1).

Spread Gold in Estate IS a spread (GameState.spread_pending/Game._collect_spread,
Conference Room redirect); Run Payroll is explicitly NOT one (no Conference Room
interaction, paid out through a separate GameState.payroll_pending dict keyed by
room id instead of cell). Both are gated on standing at the Office's own cell
(Capability.OFFICE_TERMINAL, engine/effects/rooms/office.py) -- the disk_reader
flag on the same room is a third, unrelated terminal process, already shipped.

Grouped in its own file, the same shape as tests/test_pump_room.py, since the
mechanic touches several concerns at once: two new action ids, a per-day bool
gate, a non-bool carry-over channel (the weekly cooldown), and a payout path
that is deliberately NOT the spread machinery.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects.rooms import office
from blueprince_sim.engine.game import Game
from blueprince_sim.env.actions import (
    N_ACTIONS,
    RUN_PAYROLL_ACTION,
    SPREAD_GOLD_ACTION,
    action_mask,
    apply_action,
)
from blueprince_sim.env.multiday import DayChain

OFFICE_CELL = 6
CONFERENCE_CELL = 7
FILLER_CELL = 8       # a room with no effects, to prove "every drafted room"
MAIDS_CELL = 9
SERVANTS_CELL = 10


def _place(game: Game, room_id: str, cell: int) -> None:
    """Place ``room_id`` at ``cell`` directly, bypassing drafting/walking --
    the same shortcut tests/test_pump_room.py's own _stand_at_pump_room and
    tests/test_carryover.py's Clock Tower tests use."""
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, room.door_mask)


def _stand_at_office(game: Game, cell: int = OFFICE_CELL) -> None:
    if game.state.grid[cell] < 0:
        _place(game, "office", cell)
    game.state.pos = cell


# --------------------------------------------------------------------------
# 1. Spread Gold in Estate: reaches every drafted room, including the Office
#    itself, never a room drafted afterward.
# --------------------------------------------------------------------------


def test_spread_gold_reaches_every_currently_drafted_room_including_office(registry):
    """Every occupied cell at the moment Spread Gold runs -- including the
    Office's own cell -- gets a parked coins_exact pile in spread_pending."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_office(g)
    _place(g, "spare_room", FILLER_CELL)

    assert g.can_spread_gold() is True
    g.spread_gold()

    assert OFFICE_CELL in g.state.spread_pending
    assert FILLER_CELL in g.state.spread_pending
    assert g.state.spread_pending[OFFICE_CELL] == [
        ("coins_exact", g.state.spread_pending[OFFICE_CELL][0][1])]


def test_spread_gold_does_not_reach_a_room_drafted_afterward(registry):
    """A room drafted AFTER Spread Gold runs gets no pile -- "not any room
    drafted after the Office" (wiki, matching the Patio/Locker Room/Secret
    Garden's own "arrival, not first entry" wording)."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_office(g)
    g.spread_gold()

    _place(g, "spare_room", FILLER_CELL)
    assert FILLER_CELL not in g.state.spread_pending


def test_spread_gold_once_per_day(registry):
    """A second Spread Gold press the same day is illegal -- once per day."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_office(g)
    g.spread_gold()
    assert g.can_spread_gold() is False


def test_spread_gold_requires_standing_in_the_office(registry):
    """Not legal anywhere else on the grid."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _place(g, "office", OFFICE_CELL)
    g.state.pos = FILLER_CELL if g.state.grid[FILLER_CELL] >= 0 else 1
    assert g.can_spread_gold() is False


def test_spread_gold_pile_sizes_are_exactly_3_4_or_5_over_a_seed_sweep(registry):
    """Piles are a random 3, 4, or 5 (owner ruling: unpublished by the wiki,
    reusing the Office's own floor-item pile sizes). Asserted as the SET of
    observed values over a seed sweep, never a bar on one stochastic draw."""
    observed: set[int] = set()
    for seed in range(60):
        g = Game(GameConfig(), seed=seed, registry=registry)
        _stand_at_office(g)
        g.spread_gold()
        amount = g.state.spread_pending[OFFICE_CELL][0][1]
        assert g.state.spread_pending[OFFICE_CELL][0][0] == "coins_exact"
        observed.add(amount)
    assert observed == {3, 4, 5}, f"expected exactly {{3, 4, 5}}, got {observed}"


def test_spread_gold_pays_out_on_arrival(registry):
    """Walking into a room with a parked pile grants the coins (Game._enter ->
    _collect_spread), the same "arrival, not first entry" timing as the other
    spreaders."""
    g = Game(GameConfig(), seed=1, registry=registry)
    _stand_at_office(g)
    _place(g, "spare_room", FILLER_CELL)
    g.spread_gold()
    pile = g.state.spread_pending[FILLER_CELL][0][1]

    before = g.state.coins
    g._enter(FILLER_CELL)
    assert g.state.coins == before + pile
    assert FILLER_CELL not in g.state.spread_pending  # drained


# --------------------------------------------------------------------------
# 2. Conference Room: redirects Spread Gold (a spread), never Run Payroll.
# --------------------------------------------------------------------------


def test_conference_room_redirects_spread_gold(registry):
    """A placed Conference Room redirects every Spread Gold pile -- including
    the Office's own -- into its own cell, the same shape as the Patio/Locker
    Room/Secret Garden redirects."""
    g = Game(GameConfig(), seed=2, registry=registry)
    _stand_at_office(g)
    _place(g, "conference_room", CONFERENCE_CELL)
    _place(g, "spare_room", FILLER_CELL)

    occupied_count = sum(1 for idx in g.state.grid if idx >= 0)
    g.spread_gold()

    assert OFFICE_CELL not in g.state.spread_pending
    assert FILLER_CELL not in g.state.spread_pending
    assert CONFERENCE_CELL in g.state.spread_pending
    entries = g.state.spread_pending[CONFERENCE_CELL]
    # One pile per occupied cell (Entrance Hall, Antechamber, Office, Conference
    # Room, spare_room), all redirected here -- including the Office's own and
    # the Conference Room's own, the same "keeps none of its own" shape as the
    # Patio's redirect.
    assert len(entries) == occupied_count
    assert all(kind == "coins_exact" and 3 <= amount <= 5 for kind, amount in entries)


def test_conference_room_does_not_redirect_run_payroll(registry):
    """Run Payroll is explicitly not a spread: a placed Conference Room has
    no effect on it at all -- the wiki states no Conference Room
    interaction, and payroll_pending never even consults room_cells for it."""
    g = Game(GameConfig(), seed=3, registry=registry)
    _stand_at_office(g)
    _place(g, "conference_room", CONFERENCE_CELL)

    g.run_payroll()

    assert CONFERENCE_CELL not in g.state.spread_pending
    assert g.state.spread_pending == {}
    assert g.state.payroll_pending == {
        "maids_chamber": [("coins_exact", office.PAYROLL_PILE)],
        "servants_quarters": [("coins_exact", office.PAYROLL_PILE)],
    }


# --------------------------------------------------------------------------
# 3. Run Payroll: 10 coins total (two piles of 5), draft order does not matter.
# --------------------------------------------------------------------------


def test_run_payroll_pays_10_coins_total_as_two_piles_of_5(registry):
    """Both wiki-published figures: 5 coins for the Maid's Chamber, 5 for the
    Servant's Quarters, 10 total, collected on arrival at each."""
    g = Game(GameConfig(), seed=4, registry=registry)
    _stand_at_office(g)
    _place(g, "maids_chamber", MAIDS_CELL)
    _place(g, "servants_quarters", SERVANTS_CELL)

    g.run_payroll()
    coins_before = g.state.coins
    g._enter(MAIDS_CELL)
    g._enter(SERVANTS_CELL)
    assert g.state.coins == coins_before + 10


def test_run_payroll_pays_out_even_when_target_drafted_after_the_terminal_is_used(registry):
    """Draft order does not matter (wiki): a target drafted AFTER Run Payroll
    still receives its pile once entered, via GameState.payroll_pending
    (keyed by room id, not cell)."""
    g = Game(GameConfig(), seed=5, registry=registry)
    _stand_at_office(g)
    g.run_payroll()

    _place(g, "maids_chamber", MAIDS_CELL)
    coins_before = g.state.coins
    g._enter(MAIDS_CELL)
    assert g.state.coins == coins_before + office.PAYROLL_PILE


def test_run_payroll_does_not_touch_spread_pending(registry):
    """Run Payroll never writes to GameState.spread_pending -- the wiki's
    "not a spread effect" claim, checked at the state-shape level."""
    g = Game(GameConfig(), seed=6, registry=registry)
    _stand_at_office(g)
    g.run_payroll()
    assert g.state.spread_pending == {}


def test_run_payroll_requires_standing_in_the_office(registry):
    """Not legal anywhere else on the grid, same gate as Spread Gold."""
    g = Game(GameConfig(), seed=7, registry=registry)
    _place(g, "office", OFFICE_CELL)
    g.state.pos = 1
    assert g.can_run_payroll() is False


# --------------------------------------------------------------------------
# 4. Weekly cooldown: usable, then not, then usable again on the coming Saturday.
# --------------------------------------------------------------------------


def test_payroll_available_pure_function_cooldown_shape():
    """office.payroll_available in isolation: never used is always available;
    once used, blocked until the coming day % 7 == 0 strictly after use."""
    never_used: dict = {}
    assert office.payroll_available(never_used, today=1) is True

    used_day1 = {office.PAYROLL_COOLDOWN_KEY: 1}
    assert office.payroll_available(used_day1, today=1) is False
    for day in range(2, 7):
        assert office.payroll_available(used_day1, today=day) is False, day
    assert office.payroll_available(used_day1, today=7) is True

    used_day7 = {office.PAYROLL_COOLDOWN_KEY: 7}
    for day in range(7, 14):
        assert office.payroll_available(used_day7, today=day) is False, day
    assert office.payroll_available(used_day7, today=14) is True


def test_run_payroll_cooldown_end_to_end_across_daychain_days(registry):
    """Usable on day 1, not on days 2-6, usable again on day 7 -- driven end
    to end through DayChain the same way test_pump_room.py's
    test_levels_survive_a_day_boundary proves the non-bool carry channel."""
    chain = DayChain(GameConfig(), n_days=200)

    g1 = Game(chain.next_config(), seed=1, registry=registry)
    _stand_at_office(g1)
    assert g1.can_run_payroll() is True
    g1.run_payroll()
    assert g1.can_run_payroll() is False
    chain.advance(g1.carryover())

    for day in range(2, 7):
        cfg = chain.next_config()
        assert cfg.day == day
        g = Game(cfg, seed=day, registry=registry)
        _stand_at_office(g)
        assert g.can_run_payroll() is False, day
        chain.advance(g.carryover())

    cfg7 = chain.next_config()
    assert cfg7.day == 7
    g7 = Game(cfg7, seed=7, registry=registry)
    _stand_at_office(g7)
    assert g7.can_run_payroll() is True


def test_payroll_cooldown_not_save_scoped_across_daychain_attempt_wrap(registry):
    """The cooldown record resets at the attempt wrap, the same NOT
    SAVE-scoped shape as water_levels (nothing rules a payroll cooldown to
    survive past one save)."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"payroll_last_used": {office.PAYROLL_COOLDOWN_KEY: 1}})  # day 1 -> day 2
    assert chain.next_config().payroll_last_used == {office.PAYROLL_COOLDOWN_KEY: 1}
    chain.advance({})                                                       # day 2 -> wraps to day 1
    assert chain.next_config().payroll_last_used == {}


# --------------------------------------------------------------------------
# 5. Weekday derivation: Day One is Sunday, 7 November 1993 -- Saturdays are
#    exactly day % 7 == 0.
# --------------------------------------------------------------------------


def test_weekday_derivation_days_7_and_14_are_saturdays_day_1_is_not():
    """Pins the re-derivation this session made exact: Day One (day 1) is
    Sunday, 7 November 1993 (wiki Time page), so Saturdays are exactly
    day % 7 == 0 -- days 7 and 14 qualify, day 1 (and day 6, day 8, day 13)
    do not."""
    assert office.is_saturday(1) is False
    assert office.is_saturday(6) is False
    assert office.is_saturday(7) is True
    assert office.is_saturday(8) is False
    assert office.is_saturday(13) is False
    assert office.is_saturday(14) is True


# --------------------------------------------------------------------------
# 6. Action-space integration: both ids follow the existing terminal idiom.
# --------------------------------------------------------------------------


def test_spread_gold_and_run_payroll_action_ids_mask_and_dispatch(registry):
    """Both new action ids follow the existing terminal-action idiom
    (INSERT_DISK_ACTION's shape): legal only while standing in the Office,
    each masks itself off after its own gate is spent (once-per-day for
    Spread Gold, the weekly cooldown for Run Payroll), independently."""
    g = Game(GameConfig(), seed=8, registry=registry)
    _stand_at_office(g)

    mask = action_mask(g)
    assert len(mask) == N_ACTIONS
    assert mask[SPREAD_GOLD_ACTION] is True
    assert mask[RUN_PAYROLL_ACTION] is True

    apply_action(g, SPREAD_GOLD_ACTION)
    assert g.state.special.office_spread_gold_used is True
    mask_after = action_mask(g)
    assert mask_after[SPREAD_GOLD_ACTION] is False  # once per day, now spent
    assert mask_after[RUN_PAYROLL_ACTION] is True    # independent gate

    apply_action(g, RUN_PAYROLL_ACTION)
    assert g.state.payroll_last_used[office.PAYROLL_COOLDOWN_KEY] == g.cfg.day
    assert action_mask(g)[RUN_PAYROLL_ACTION] is False  # weekly cooldown now active


def test_spread_gold_and_run_payroll_masked_off_away_from_the_office(registry):
    """Both ids are False in the action mask when the Office is placed but
    the player is standing elsewhere on the grid."""
    g = Game(GameConfig(), seed=9, registry=registry)
    _place(g, "office", OFFICE_CELL)
    g.state.pos = 1
    mask = action_mask(g)
    assert mask[SPREAD_GOLD_ACTION] is False
    assert mask[RUN_PAYROLL_ACTION] is False
