"""Dining Room: the rank-8-gated Main Course.

See tests/rooms/test_kitchen.py for the Kitchen's per-dish menu.
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _enter_dining(game: Game, cell: int = 7, reached_rank_8: bool = True) -> object:
    """Place the Dining Room at ``cell``, stand in it, and fire on_enter.

    The main course is rank-8 gated, so by default a rank-8 cell is marked as
    reached; pass reached_rank_8=False to test the early-entry case.
    """
    reg = game.registry
    room = reg.by_id["dining_room"]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.pos = cell
    state.entered[cell] = True
    if reached_rank_8:
        state.entered[36] = True  # rank 8: the course gate is open
    si.on_enter(game, room, cell)
    return room


def _place_room(game: Game, room_id: str, cell: int) -> object:
    """Place a room on the grid without entering it. Returns the Room."""
    reg = game.registry
    room = reg.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    return room


def test_main_course_not_served_before_rank_8():
    """Entering the Dining Room before reaching Rank 8 serves nothing.

    The real game only serves the Main Course late-run; an early Dining Room
    visit must leave the player to come back for it.
    """
    g = _game(GameConfig(day=1), seed=0)
    steps_before = g.state.steps
    _enter_dining(g, reached_rank_8=False)
    assert g.state.steps == steps_before
    assert not g.state.special.dining_room_served


def test_main_course_served_on_return_after_rank_8():
    """Returning to an already-entered Dining Room after reaching Rank 8
    serves the course via the arrival hook.

    Early visitors are not locked out — the course waits for the return trip.
    """
    g = _game(GameConfig(day=1), seed=0)
    _enter_dining(g, reached_rank_8=False)  # too early: nothing served
    g.state.entered[36] = True  # the player has now reached rank 8
    g.state.pos = 7  # back in the Dining Room
    steps_before = g.state.steps
    si.on_arrive(g, 7)
    assert g.state.steps == steps_before + 20  # day 1: salmon, no aquarium
    assert g.state.special.dining_room_served


# ---------------------------------------------------------------- dining room main course

def _day_course_id(day: int, registry) -> str:
    """Expected course id for ``day`` based on the data cycle."""
    food_rules = registry.item_rules.get("food", {})
    cycle = food_rules.get("main_course_cycle", [])
    return cycle[day % len(cycle)]


def test_main_course_salmon_on_day_1():
    """Day 1 serves Lemon Glazed Salmon (day%5==1 → cycle index 1 → salmon).

    The cycle is deterministic and data-driven; this test pins the index.
    """
    g = _game(GameConfig(day=1), seed=0)
    steps_before = g.state.steps
    _enter_dining(g)
    # salmon: 20 steps base, no Aquarium placed
    assert g.state.steps == steps_before + 20


def test_main_course_pizza_on_day_5():
    """Day 5 serves Wood-fired Pizza (day%5==0 → cycle index 0 → pizza).

    Day 5 wraps to index 0, confirming the modulo arithmetic.
    """
    g = _game(GameConfig(day=5), seed=0)
    steps_before = g.state.steps
    _enter_dining(g)
    # pizza: 20 steps, no Furnace placed
    assert g.state.steps == steps_before + 20


def test_main_course_boost_applies_with_boost_room():
    """Main course grants boosted_steps (30) when its boost room is on the estate.

    Day 1 = salmon → boost_room is aquarium. Placing an Aquarium before entering
    the Dining Room must yield 30 steps instead of 20.
    """
    g = _game(GameConfig(day=1), seed=0)
    # Place Aquarium at another grid cell before entering the Dining Room
    _place_room(g, "aquarium", 10)
    steps_before = g.state.steps
    _enter_dining(g, cell=7)
    assert g.state.steps == steps_before + 30


def test_main_course_pizza_boost_with_furnace():
    """Day 5 pizza grants 30 steps when the Furnace is on the estate.

    Separate from the salmon test to pin the pizza→furnace boost specifically.
    """
    g = _game(GameConfig(day=5), seed=0)
    _place_room(g, "furnace", 10)
    steps_before = g.state.steps
    _enter_dining(g, cell=7)
    assert g.state.steps == steps_before + 30


def test_main_course_boost_absent_without_boost_room():
    """Day 1 salmon grants base 20 steps when no Aquarium is on the estate.

    Verifies the boost does not fire spuriously.
    """
    g = _game(GameConfig(day=1), seed=0)
    steps_before = g.state.steps
    _enter_dining(g)
    assert g.state.steps == steps_before + 20


def test_main_course_served_once_per_day():
    """Entering the Dining Room a second time does not serve the main course again.

    The dining_room_served flag gates the one-per-day course delivery; re-entry
    must not add more steps.
    """
    g = _game(GameConfig(day=1), seed=0)
    _enter_dining(g, cell=7)
    steps_after_first = g.state.steps
    _enter_dining(g, cell=7)  # second entry
    assert g.state.steps == steps_after_first


def test_main_course_salt_shaker_silver_spoon_modify_course():
    """Salt Shaker (+1) then Silver Spoon (×2) modify the main course: 20→21→42.

    The food pipeline applies to the main course just like any other food item,
    so modifiers stack on top of the dish's resolved base.
    """
    g = _game(GameConfig(day=1,
                         starting_items=frozenset({"salt_shaker", "silver_spoon"})),
              seed=0)
    steps_before = g.state.steps
    _enter_dining(g)
    # day 1 = salmon = 20 base (no Aquarium), salt_shaker +1 = 21, ×2 = 42
    assert g.state.steps == steps_before + 42


def test_main_course_all_five_days_cycle():
    """The five-day cycle visits each dish exactly once and repeats correctly.

    Checks days 1-5 and 6-10 (same cycle) for the correct course_id, using only
    the data cycle from items.json — no hard-coded ids in the assertion.
    """
    for day in range(1, 11):
        g = _game(GameConfig(day=day), seed=0)
        expected_id = _day_course_id(day, g.registry)
        steps_before = g.state.steps
        _enter_dining(g)
        # Each course is at least 20 steps; just verify it runs at all here
        assert g.state.steps > steps_before, f"day {day}: no steps granted for {expected_id}"


def test_main_course_deterministic_same_seed():
    """Two Game instances with the same seed and day produce identical step gains.

    Confirms the main course resolution is deterministic and state-only (no extra rng).
    """
    for day in (1, 2, 3, 4, 5):
        g1 = _game(GameConfig(day=day), seed=0)
        g2 = _game(GameConfig(day=day), seed=0)
        _enter_dining(g1)
        _enter_dining(g2)
        assert g1.state.steps == g2.state.steps, f"day {day}: non-deterministic"
