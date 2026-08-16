"""cli/play.py: the interactive REPL's NAVIGATE-phase menu.

PR #374 added ``Game._in_place_action_available()`` to ``_check_termination``,
so the engine correctly keeps a day alive while a zero-step action (an
openable container, a shop buy, an Office/Workshop/Sanctum terminal, a night
sky, ...) is still legal where the player stands -- but the REPL had no verb
for any of them. With no doors and no moves at the player's cell, the old
``if not doors and not moves: game._check_termination(); continue`` branch
spun forever: the engine (correctly) refused to end the day, and the REPL
never reached ``input()`` to let the player act or even quit.

``_in_place_label`` is tested directly (pure function, no I/O). The REPL menu
itself is driven end-to-end through the real ``play()`` loop with
``blueprince_sim.cli.play.Game`` monkeypatched to hand back a deterministically
constructed scenario (never a lucky seed) and ``input()`` monkeypatched to a
scripted transcript. Every such test runs on a background daemon thread with a
wall-clock join timeout: unlike a bounded iteration count, this is the only
safe way to cap a call into ``play()`` that might -- if the fix regresses --
spin without ever touching ``input()`` at all, so a per-call iteration counter
would never even run.
"""

from __future__ import annotations

import threading

from blueprince_sim.cli import play as play_module
from blueprince_sim.cli.play import _in_place_label, play
from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, CALLED_IT_A_DAY, Game, Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_OPEN, segment_key

#: Wall-clock bound for one play() call in these tests. A day this small
#: (one in-place action, one or two menu round-trips) finishes in well under
#: a second when the fix is in place; a regression that reintroduces the
#: silent spin never returns at all, so this is a hang/no-hang bound, not a
#: performance budget.
_JOIN_TIMEOUT = 5.0


def _run_play_bounded(cfg: GameConfig, seed: int) -> None:
    """Call ``play(cfg, seed)`` on a daemon thread; raise if it outlives
    ``_JOIN_TIMEOUT`` instead of letting a hang stall the whole test run."""
    outcome: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            play(cfg, seed)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(_JOIN_TIMEOUT)
    assert not thread.is_alive(), (
        "play() did not return within the bound -- the NAVIGATE loop is "
        "spinning without reaching input(), the exact pre-fix hang"
    )
    if "error" in outcome:
        raise outcome["error"]


def _locker_room_scenario(seed: int = 1) -> Game:
    """A NAVIGATE state with no doorways, no adjacent moves, and one legal
    in-place action (a free locker) -- built by direct engine manipulation,
    not a searched-for seed, per the deterministic-scenario convention.

    The Locker Room carries several free lockers (data/special_items.json's
    containers table), so the in-place action stays legal after one is taken
    -- exercising the menu twice in the tests that pick it more than once
    without needing a second scenario.
    """
    game = Game(GameConfig(), seed=seed)
    room = game.registry.by_id["locker_room"]
    game.state.grid[game.state.pos] = room.idx
    game.state.placed_doors[game.state.pos] = 0
    assert game.open_doorways() == []
    assert game.adjacent_moves() == []
    assert game.can_open_container()
    return game


def _laboratory_scenario(seed: int = 0) -> Game:
    """A NAVIGATE state standing at a doorless, moveless Laboratory terminal,
    the only in-place action being ``start_setup`` -- the one in-place action
    that leaves NAVIGATE (for EXPERIMENT_PENDING), per
    ``Game._in_place_actions``'s own docstring."""
    game = Game(GameConfig(), seed=seed)
    lab = game.registry.by_id["laboratory"]
    game._place_room(lab, 7, lab.rotations[0])
    game.state.pos = 7
    game.state.entered[7] = True
    game.state.placed_doors[7] = 0
    assert game.open_doorways() == []
    assert game.adjacent_moves() == []
    assert game.can_start_setup()
    return game


def _room46_scenario(seed: int = 1) -> Game:
    """Standing in the Antechamber with its north door open (not
    DOOR_SEALED), no other doors, no adjacent moves, and no in-place action
    -- task 41's exact reproduction: ``Game._action_in_budget`` is True
    purely because the off-grid ``room_46`` hop is reachable and affordable,
    with 1 step left (the boundary case, since the room_46 check is
    non-strict: ``steps >= cost``, unlike the off-grid menu's own strict
    ``steps > cost``). Built by direct engine manipulation, not a
    searched-for seed, per the deterministic-scenario convention. The
    assertions establish the state is genuinely reachable rather than
    hypothetical, settling task 41's open question.
    """
    game = Game(GameConfig(), seed=seed)
    st = game.state
    st.pos = ANTECHAMBER_CELL
    st.entered[ANTECHAMBER_CELL] = True
    st.placed_doors[ANTECHAMBER_CELL] = 0
    st.door_state[segment_key(ANTECHAMBER_CELL, N)] = DOOR_OPEN
    st.door_version += 1
    st.steps = 1
    assert game.open_doorways() == []
    assert game.adjacent_moves() == []
    assert list(game._in_place_actions()) == []
    assert not game.outer_draft_available()
    route = game.area_route_cost("room_46")
    assert route is not None and st.steps >= route[0]
    assert game._action_in_budget(), (
        "room_46 travel should be the one action keeping the day alive"
    )
    return game


def _truly_dead_scenario(seed: int = 1) -> Game:
    """A NAVIGATE state with no doors, no moves, no in-place action, no outer
    draft, and no steps left -- the one state where the day really is over
    and ``_check_termination`` must say so without any player input."""
    game = Game(GameConfig(), seed=seed)
    game.state.placed_doors[game.state.pos] = 0
    game.state.steps = 0
    assert game.open_doorways() == []
    assert game.adjacent_moves() == []
    assert list(game._in_place_actions()) == []
    assert not game.outer_draft_available()
    return game


def _scripted_input(monkeypatch, responses: list[str]) -> None:
    """Patch ``input`` to replay ``responses`` in order, then fall back to
    ``'q'`` forever -- a finite script that always terminates the REPL even
    if a test's expectations about the exact prompt count are slightly off,
    rather than ever blocking on real stdin."""
    it = iter(responses)

    def _fake_input(prompt: str = "") -> str:
        return next(it, "q")

    monkeypatch.setattr("builtins.input", _fake_input)


# --------------------------------------------------------------- _in_place_label

def test_in_place_label_names_the_disambiguating_argument():
    """A partial-wrapped in-place action (activate_constellation) names the
    specific constellation, not just the generic action id -- the label must
    read the entry's own argument rather than a fixed string, or two
    different constellations would show the same menu line."""
    import functools
    game = Game(GameConfig(), seed=0)
    record = game.registry.constellations.records[0]
    do = functools.partial(lambda i: None, 0)
    label = _in_place_label(game, "activate_constellation", do)
    assert record.name in label
    assert str(record.stars) in label


def test_in_place_label_falls_back_to_the_id_for_an_unrecognized_action():
    """An id the label function does not special-case (none of
    ``Game._in_place_actions``'s current ids reach this) still returns
    something rather than raising, so a future new action id degrades to a
    plain-but-working menu line instead of crashing the REPL."""
    game = Game(GameConfig(), seed=0)
    label = _in_place_label(game, "some_future_action", lambda: None)
    assert label == "some_future_action"


def test_in_place_label_covers_every_action_id():
    """Every id ``Game._in_place_actions`` can yield gets a label that is not
    just the raw id echoed back (except the deliberate id-as-label fallback
    for an unrecognized id) -- catches a label branch silently missing for a
    real action id."""
    known_ids = {
        "open_container", "open_car_trunk", "open_vault_box", "install_lever",
        "smash_vase", "spread_gold", "run_payroll", "view_night_sky",
        "use_telescope_planetarium", "take_grotto_chip", "light",
        "start_setup",
    }
    game = Game(GameConfig(), seed=0)
    for action_id in known_ids:
        label = _in_place_label(game, action_id, lambda: None)
        assert label != action_id, f"{action_id} has no readable label"


# ------------------------------------------------------------- the hang itself

def test_old_branch_shape_spins_without_progress_bounded():
    """Pins the defect: the pre-fix branch (``if not doors and not moves:
    game._check_termination(); continue``) reproduced verbatim against a
    state with a pending in-place action never breaks out, never taking the
    action, across a large bounded iteration cap -- the same silent spin PR
    #374 made reachable. Kept as a permanent pin of the bug shape (not just a
    manual pre-fix check) so a future edit that reintroduces the old
    early-continue is caught here, independent of whether the rest of the
    REPL still happens to work around it."""
    game = _locker_room_scenario()
    cap = 2000
    made_progress = False
    for _ in range(cap):
        doors = game.open_doorways()
        moves = game.adjacent_moves()
        if not doors and not moves:
            game._check_termination()
            continue
        made_progress = True
        break
    assert not made_progress, "the old branch shape should never escape here"
    assert game.phase is Phase.NAVIGATE
    assert game.can_open_container(), "the in-place action was never taken"


def test_x_menu_takes_the_pending_in_place_action_and_does_not_hang(monkeypatch):
    """The exact scenario above, driven through the real, fixed ``play()``:
    picking 'x1' opens the locker (state visibly changes) and the REPL keeps
    going instead of spinning -- the regression test for the PR #374 hang."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["x1", "q"])

    before = dict(game.state.special.opened_containers)
    _run_play_bounded(GameConfig(), seed=1)

    after = game.state.special.opened_containers
    assert after.get(game.state.pos, 0) > before.get(game.state.pos, 0), (
        "the in-place action offered at 'x1' was never actually taken"
    )


def test_dead_state_terminates_without_needing_input(monkeypatch):
    """No doors, no moves, no in-place action, no outer draft, and no steps
    left: the day must end on its own -- the 'report or terminate' half of
    the brief's dead-branch requirement, proven by never even needing a
    scripted response beyond the safety-net 'q'."""
    game = _truly_dead_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, [])  # every input() call falls back to 'q'

    _run_play_bounded(GameConfig(), seed=1)
    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == "out_of_steps"


def test_experiment_pending_trigger_and_effect_menu_resolves(monkeypatch):
    """start_setup is the one in-place action that leaves NAVIGATE (for
    EXPERIMENT_PENDING); picking it from the 'x' menu and then a trigger and
    an effect must configure the experiment and return to NAVIGATE rather
    than crashing on the DRAFTING-shaped fallback branch (game.state.pending
    is None in EXPERIMENT_PENDING, so treating it as DRAFTING would raise)."""
    game = _laboratory_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["x1", "1", "1", "q"])

    _run_play_bounded(GameConfig(), seed=0)
    assert game.state.experiment.configured


# --------------------------------------------------------- task 41: room 46

def test_room46_menu_entry_travels_and_wins(monkeypatch):
    """Picking '46' from the on-grid NAVIGATE menu at ``_room46_scenario``'s
    state reaches Room 46 -- the regression test for task 41's missing CLI
    verb. Before the fix, ``cli/play.py`` only ever called
    ``game.travel_to`` inside the ``game.off_grid`` branch, so this
    on-grid-only route to the objective had no command that could take it
    and the day could only be abandoned with 'q'."""
    game = _room46_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["46", "q"])

    _run_play_bounded(GameConfig(), seed=1)
    assert game.state.room46_reached
    assert game.success()


def test_room46_menu_entry_absent_when_not_affordable(monkeypatch, capsys):
    """A fresh day's start (Entrance Hall, no path yet to the Antechamber's
    open north door) must not print '[46]': the entry is gated on
    ``area_route_cost('room_46')`` being reachable and affordable -- the
    same predicate ``_action_in_budget`` uses -- not shown unconditionally,
    which would let the player "travel" from a state where the engine does
    not consider the destination reachable."""
    game = Game(GameConfig(), seed=0)
    assert game.area_route_cost("room_46") is None
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["q"])

    _run_play_bounded(GameConfig(), seed=0)
    out = capsys.readouterr().out
    assert "[46]" not in out


# ---------------------------------------------------- task 44: call it a day

def _off_grid_scenario(seed: int = 1) -> Game:
    """A NAVIGATE state standing off the grid at the west path, where the REPL
    shows its ``outer>`` travel menu instead of the on-grid one.

    The two NAVIGATE prompts are separate code paths with separate command
    parsers, so a verb added to one is not automatically on the other; this
    scenario is what lets the off-grid prompt be driven on its own.
    """
    game = Game(GameConfig(), seed=seed)
    game.state.area = "west_path"
    assert game.off_grid, "scenario needs the player off the grid"
    assert game.can_call_it_a_day()
    return game


def test_the_on_grid_menu_offers_calling_it_a_day(monkeypatch, capsys):
    """The verb has to be discoverable, not just implemented: a player who
    never sees '[c]' printed cannot use it, and the REPL's only other exit is
    'q', which walks away from the day rather than ending it."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["q"])

    _run_play_bounded(GameConfig(), seed=1)

    assert "[c] call it a day" in capsys.readouterr().out


def test_the_off_grid_menu_offers_calling_it_a_day_too(monkeypatch, capsys):
    """The off-grid ``outer>`` prompt parses its own commands, so the verb
    could easily exist on one prompt and not the other. A player who walked
    out to the west path must be able to stop the day from there."""
    game = _off_grid_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["q"])

    _run_play_bounded(GameConfig(), seed=1)

    assert "[c] call it a day" in capsys.readouterr().out


def test_confirming_at_the_on_grid_prompt_ends_the_day(monkeypatch):
    """The mutation proof in the REPL: this is a state the engine keeps alive
    (a free locker underfoot), and 'c' then 'y' ends it anyway -- with the
    hand-ended reason, so the summary line does not misreport it as running
    out of steps."""
    game = _locker_room_scenario()
    assert game.can_open_container(), "setup: purposeful work must remain"
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["c", "y"])

    _run_play_bounded(GameConfig(), seed=1)

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == CALLED_IT_A_DAY


def test_confirming_at_the_off_grid_prompt_ends_the_day(monkeypatch):
    """The same, driven through the ``outer>`` prompt, so the off-grid branch
    is proven to reach ``Game.call_it_a_day`` rather than merely printing the
    menu line for it."""
    game = _off_grid_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["c", "y"])

    _run_play_bounded(GameConfig(), seed=1)

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == CALLED_IT_A_DAY


def test_declining_the_confirmation_leaves_the_day_running(monkeypatch):
    """The confirmation is the request's other half. Answering 'n' must leave
    the day exactly where it was -- still NAVIGATE, still holding the locker
    it had -- or the prompt is theatre and a misclick still ends the day."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["c", "n", "q"])

    _run_play_bounded(GameConfig(), seed=1)

    assert game.phase is Phase.NAVIGATE
    assert game.termination_reason == ""
    assert game.can_open_container(), "declining must not have consumed anything"


def test_an_empty_answer_does_not_end_the_day(monkeypatch):
    """The prompt reads '[y/N]', so the default on a bare Enter is no. An
    irreversible action that fires on an accidental keypress is exactly what
    the confirmation exists to prevent."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["c", "", "q"])

    _run_play_bounded(GameConfig(), seed=1)

    assert game.phase is Phase.NAVIGATE
    assert game.termination_reason == ""


def test_calling_it_a_day_prints_the_end_of_day_summary(monkeypatch, capsys):
    """Ending the day and abandoning it are different outcomes and must read
    differently: 'q' returns silently, while 'c' + 'y' falls out of the loop
    into the summary that reports the reason and the rooms placed."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["c", "y"])

    _run_play_bounded(GameConfig(), seed=1)

    assert f"Day over: {CALLED_IT_A_DAY}" in capsys.readouterr().out


def test_quitting_still_leaves_the_day_unfinished(monkeypatch, capsys):
    """The contrast that keeps the test above honest: 'q' must NOT have
    quietly become "end the day". It walks away from the REPL with the day
    still running and prints no summary at all."""
    game = _locker_room_scenario()
    monkeypatch.setattr(play_module, "Game", lambda cfg, seed: game)
    _scripted_input(monkeypatch, ["q"])

    _run_play_bounded(GameConfig(), seed=1)

    assert game.phase is Phase.NAVIGATE
    assert "Day over:" not in capsys.readouterr().out
