"""The Laboratory unlock is a SAVE-SCOPED one-time unlock of Blackbridge Grotto.

Owner ruling: "You only need to unlock the Blackbridge Grotto once for the
entire save. However, you need to power and enter the Laboratory for that to
happen." The `private_drive -> blackbridge_grotto` edge carries the two
conjuncts as two separate gates (docs/areas.md's "Blackbridge Grotto gate"),
and both are real `kind: "flag"` gates with `permanence: "permanent"`:

- `lab_steam_and_power`, the POWER half. `effects/rooms/laboratory.py`'s
  ON_DRAFT_ROOM hook sets `state.lab_powered` the moment a placed Laboratory is
  powered (docs/power.md), and `DayChain.lab_powered` carries it.
- `lab_visited`, the visit half. `effects/rooms/laboratory.py`'s ON_ENTER hook
  sets `state.lab_visited`, and the named `DayChain.lab_visited` attribute
  carries it.

Both take the same route: `shops.py::carryover` ORs state with config, and
neither is a `_CARRYOVER_KEYS` flag, because that set is cleared at the attempt
wrap and membership would make the unlock attempt-scoped. They are the two
bools among the save-scoped carve-outs (docs/scoping-and-carryover.md).

This file pins the scope: powering and entering the Laboratory once opens the
Grotto for every later day AND every later attempt, and doing neither leaves
the Grotto shut. Gate-evaluation truth-table coverage lives in
tests/test_areas.py; power propagation itself in tests/test_power.py; the
carve-out list as a whole is pinned in tests/test_carryover.py; the Grotto's
own contents are covered by tests/test_grotto_chip.py and
tests/test_orindian_ruins.py.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env.multiday import DayChain, _CARRYOVER_KEYS

LAB_CELL = 12  # rank 3, centre column: free in every scenario below
BOILER_CELL = 17  # rank 4, centre column: directly north of LAB_CELL


def _power_and_enter_laboratory(g: Game) -> None:
    """Place a Laboratory, join a Boiler Room to it by a doorway, and walk in.

    Satisfies both Grotto conjuncts in one deterministic setup. The
    Laboratory's N bit and the Boiler Room's S bit form a real door pair across
    LAB_CELL's north side, which is what powers the Laboratory
    (engine/power.py) -- orthogonal adjacency alone would not.

    ``_enter`` rather than ``_place_room(entered=True)``: the visit latch is
    the room's own ON_ENTER hook, and only ``_enter`` fires room hooks.
    """
    g._place_room(g.registry.by_id["laboratory"], LAB_CELL, N | S)
    g._place_room(g.registry.by_id["boiler_room"], BOILER_CELL, N | S)
    g._enter(LAB_CELL)


# --------------------------------------------------------------- the latch

def test_powering_and_entering_the_laboratory_sets_state_not_config(registry):
    """Both halves of the unlock are recorded on GameState only.

    Same shape as boiler_room_steam: one GameConfig object is shared by every
    episode of a trainer worker, so writing either discovery there would leak
    the unlock into later, unrelated episodes.
    """
    cfg = GameConfig()
    g = Game(cfg, seed=1, registry=registry)
    assert g.state.lab_visited is False
    assert g.state.lab_powered is False

    _power_and_enter_laboratory(g)

    assert g.state.lab_visited is True
    assert g.state.lab_powered is True
    assert cfg.lab_visited is False, "the shared config must not be mutated"
    assert cfg.lab_powered is False, "the shared config must not be mutated"


def test_grotto_shut_on_a_fresh_save_until_the_laboratory_is_powered_and_entered(registry):
    """A fresh save cannot reach Blackbridge Grotto, and powering plus entering
    the Laboratory is what opens it -- the owner's rule, measured on one Game so
    the before/after differ in exactly that one act.

    Anti-vacuity: the "before" leg is what proves neither conjunct already
    opens the edge on its own.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50

    assert g.area_route_cost("blackbridge_grotto") is None

    _power_and_enter_laboratory(g)

    assert g.area_route_cost("blackbridge_grotto") is not None


def test_an_unpowered_laboratory_visit_leaves_the_grotto_shut(registry):
    """Entering a Laboratory nothing powers does NOT open the Grotto.

    The POWER conjunct used to be a stub that passed unconditionally, so a bare
    visit was enough. This is the leg that proves it no longer is -- and it is
    the test above minus the Boiler Room, so the Boiler Room is provably what
    makes the difference.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50

    g._place_room(g.registry.by_id["laboratory"], LAB_CELL, N | S)
    g._enter(LAB_CELL)

    assert g.state.lab_visited is True
    assert g.state.lab_powered is False
    assert g.area_route_cost("blackbridge_grotto") is None


def test_carryover_reports_both_conjuncts_after_powering_and_entering(registry):
    """shops.carryover() reports lab_visited AND lab_powered once each has been
    earned, and neither on a day they were not -- the report is what DayChain
    merges, so a missing key here would silently make the unlock day-scoped."""
    g = Game(GameConfig(), seed=1, registry=registry)
    assert carryover(g)["lab_visited"] is False
    assert carryover(g)["lab_powered"] is False

    _power_and_enter_laboratory(g)

    assert carryover(g)["lab_visited"] is True
    assert carryover(g)["lab_powered"] is True


# --------------------------------------------------------------- permanence

def test_grotto_stays_open_the_next_day_without_re_powering_the_laboratory(registry):
    """THE property: powering and visiting the Laboratory on day 1 keeps the
    Grotto open on day 2 even though the Laboratory is never drafted again.

    Day 2's grid has no Laboratory and no Boiler Room on it at all, so the only
    things that can open the edge are the carried cfg.lab_visited and
    cfg.lab_powered. This is the day-scoping bug inverted into an assertion:
    with either conjunct re-derived daily, day 2 would re-lock every morning.
    """
    chain = DayChain(GameConfig(), n_days=5)

    day1 = Game(chain.next_config(), seed=1, registry=registry)
    day1.state.steps = 50
    _power_and_enter_laboratory(day1)
    assert day1.area_route_cost("blackbridge_grotto") is not None
    chain.advance(carryover(day1))

    day2_cfg = chain.next_config()
    assert day2_cfg.lab_visited is True
    assert day2_cfg.lab_powered is True

    day2 = Game(day2_cfg, seed=2, registry=registry)
    day2.state.steps = 50
    assert "laboratory" not in day2.placed_ids, "day 2 must not have its own Laboratory"
    assert day2.state.lab_visited is False, "the day's own state starts clean"
    assert day2.state.lab_powered is False, "the day's own state starts clean"
    assert day2.area_route_cost("blackbridge_grotto") is not None


def test_grotto_stays_shut_the_next_day_when_the_laboratory_was_never_entered(registry):
    """The counterpart: a day 1 that never entered the Laboratory carries
    nothing, and day 2's Grotto is still shut.

    Without this, the test above would pass just as well against a gate that
    had been deleted outright.
    """
    chain = DayChain(GameConfig(), n_days=5)

    day1 = Game(chain.next_config(), seed=1, registry=registry)
    day1.state.steps = 50
    assert carryover(day1)["lab_visited"] is False
    assert carryover(day1)["lab_powered"] is False
    chain.advance(carryover(day1))

    day2_cfg = chain.next_config()
    assert day2_cfg.lab_visited is False
    assert day2_cfg.lab_powered is False

    day2 = Game(day2_cfg, seed=2, registry=registry)
    day2.state.steps = 50
    assert day2.area_route_cost("blackbridge_grotto") is None


def test_the_unlock_survives_the_attempt_wrap(registry):
    """Both conjuncts are SAVE-scoped: the unlock carries through the attempt
    wrap into a fresh attempt, so the Grotto opens on day 1 of the new attempt
    with no Laboratory on the grid at all.

    Owner ruling: "You only need to unlock the Blackbridge Grotto once for the
    entire save." DayChain.advance()'s wrap block clears carried_flags
    wholesale, so this only holds because lab_visited and lab_powered are named
    DayChain attributes left out of that block, not _CARRYOVER_KEYS entries
    (docs/scoping-and-carryover.md).
    """
    chain = DayChain(GameConfig(starting_steps=50), n_days=2)

    day1 = Game(chain.next_config(), seed=1, registry=registry)
    _power_and_enter_laboratory(day1)
    chain.advance(carryover(day1))
    assert chain.next_config().lab_visited is True
    assert chain.next_config().lab_powered is True

    day2 = Game(chain.next_config(), seed=2, registry=registry)
    chain.advance(carryover(day2))

    wrapped = chain.next_config()
    assert wrapped.day == 1, "n_days=2 must have wrapped by now"
    assert wrapped.lab_visited is True
    assert wrapped.lab_powered is True

    fresh_attempt = Game(wrapped, seed=3, registry=registry)
    fresh_attempt.state.steps = 50
    assert "laboratory" not in fresh_attempt.placed_ids
    assert fresh_attempt.area_route_cost("blackbridge_grotto") is not None


def test_the_wrap_that_spares_the_unlock_still_clears_an_attempt_scoped_flag(registry):
    """Anti-vacuity companion: the same wrap that keeps lab_visited and
    lab_powered DOES clear boiler_room_steam, an ordinary _CARRYOVER_KEYS flag
    earned the same way.

    Without this, the test above would pass just as well against a DayChain
    whose wrap block had stopped running at all, or an n_days that never
    wrapped -- the contrast is what proves the carve-out is specific.
    """
    chain = DayChain(GameConfig(), n_days=1)

    chain.advance({"lab_visited": True, "lab_powered": True, "boiler_room_steam": True})

    wrapped = chain.next_config()
    assert wrapped.day == 1, "n_days=1 must wrap on the first advance"
    assert wrapped.lab_visited is True, "save-scoped: survives"
    assert wrapped.lab_powered is True, "save-scoped: survives"
    assert wrapped.boiler_room_steam is False, "attempt-scoped: cleared"


# --------------------------------------------------------------- RL plumbing

def test_neither_grotto_conjunct_is_a_carryover_key(registry):
    """lab_visited and lab_powered are deliberately NOT in _CARRYOVER_KEYS.

    That set is cleared wholesale at the wrap, so membership would make the
    unlock attempt-scoped -- the opposite of the owner's ruling. It also fixes
    the width of the 'carryover' observation vector, so staying out of it is
    what keeps the power system off the retrain-trigger list
    (docs/rl-environment.md).
    """
    assert "lab_visited" not in _CARRYOVER_KEYS
    assert "lab_powered" not in _CARRYOVER_KEYS
    assert len(_CARRYOVER_KEYS) == 19
    assert isinstance(GameConfig().lab_visited, bool)
    assert isinstance(GameConfig().lab_powered, bool)
    assert isinstance(DayChain(GameConfig()).lab_visited, bool)
    assert isinstance(DayChain(GameConfig()).lab_powered, bool)
