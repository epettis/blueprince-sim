"""Special items: movement cost, lock, and gem-cost behaviors (task C)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_SECURITY, segment_key
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.state import GameState
from blueprince_sim.env import actions as A


# ----------------------------------------------------------------- helpers

def _game(items: frozenset[str] = frozenset(), seed: int = 0) -> Game:
    cfg = GameConfig(starting_items=items)
    return Game(cfg, seed=seed)


def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


# ------------------------------------------------ Hall Pass move costs

def test_hall_pass_hallway_to_hallway_free():
    """Hall Pass makes moving from a hallway room into another hallway room cost 0.

    This is the Hall Pass's core mechanic: hallway-to-hallway traversal is free.
    """
    game = _game(frozenset({"hall_pass"}))
    reg = game.registry
    hallway = reg.by_id["hallway"]
    # Place a hallway room at cell 7 as the "from" cell
    game.state.grid[7] = hallway.idx
    cost = si.move_step_cost(game, 7, N, hallway)
    assert cost == 0


def test_hall_pass_non_hallway_costs_1():
    """Hall Pass does not waive the cost when the destination is not a hallway.

    The waiver requires both source AND destination to be hallways.
    """
    game = _game(frozenset({"hall_pass"}))
    reg = game.registry
    hallway = reg.by_id["hallway"]
    bedroom = reg.by_id["bedroom"]
    game.state.grid[7] = hallway.idx
    cost = si.move_step_cost(game, 7, N, bedroom)
    assert cost == 1


def test_hall_pass_from_non_hallway_costs_1():
    """Hall Pass does not waive the cost when the source room is not a hallway.

    The waiver requires both sides of the move to be hallway rooms.
    """
    game = _game(frozenset({"hall_pass"}))
    reg = game.registry
    hallway = reg.by_id["hallway"]
    bedroom = reg.by_id["bedroom"]
    game.state.grid[7] = bedroom.idx
    cost = si.move_step_cost(game, 7, N, hallway)
    assert cost == 1


# ------------------------------------------------ Running Shoes cadence

def test_running_shoes_cadence_6_moves():
    """Running Shoes make every 3rd move free: moves 1,2 cost 1; move 3 costs 0; pattern repeats.

    The cadence must be exactly every-3rd regardless of room category.
    """
    game = _game(frozenset({"running_shoes"}))
    reg = game.registry
    # Use entrance hall as a stable from-cell (already placed at cell 2)
    entrance = reg.by_id["entrance_hall"]
    # We call move_step_cost directly — the from_cell room category doesn't affect shoes
    costs = []
    for _ in range(6):
        cost = si.move_step_cost(game, game.state.pos, N, entrance)
        costs.append(cost)
    assert costs == [1, 1, 0, 1, 1, 0], f"expected [1,1,0,1,1,0] got {costs}"


# ------------------------------------------------ Stopwatch move costs

def test_stopwatch_waives_move_and_expires():
    """Stopwatch provides free_costs free move events, then expires (stopwatch_left == 0).

    After the budget runs out, moves cost 1 again.
    """
    game = _game(frozenset({"stopwatch"}))
    reg = game.registry
    free_costs = game.state.special.stopwatch_left
    assert free_costs > 0, "stopwatch must be active after pickup"
    entrance = reg.by_id["entrance_hall"]
    # Exhaust the stopwatch
    for _ in range(free_costs):
        cost = si.move_step_cost(game, game.state.pos, N, entrance)
        assert cost == 0, "expected free move while stopwatch active"
    assert game.state.special.stopwatch_left == 0
    # Next move costs 1
    cost = si.move_step_cost(game, game.state.pos, N, entrance)
    assert cost == 1


# ------------------------------------------------ Master Key

def test_master_key_doorway_passable_with_no_keys():
    """Master Key makes a locked doorway passable even with 0 keys in hand.

    can_open_locked_free returns True, so doorway_passable bypasses the key check.
    """
    game = _game(frozenset({"master_key"}))
    assert game.state.keys == 0
    # Force a locked segment on the north door of entrance cell
    seg = segment_key(game.state.pos, N)
    game.state.door_state[seg] = DOOR_LOCKED
    game.state.door_version += 1
    assert game.doorway_passable(game.state.pos, N)


def test_master_key_cannot_open_security_door():
    """The Master Key opens regular key locks only — never security doors.

    A security segment stays gated on the keycard/power system: with the
    security system unopenable, a Master Key holder is still blocked.
    """
    game = _game(frozenset({"master_key"}))
    game.state.has_keycard = False
    game.state.keycard_power_on = True  # powered readers, no card: unopenable
    seg = segment_key(game.state.pos, N)
    game.state.door_state[seg] = DOOR_SECURITY
    game.state.door_version += 1
    assert si.can_open_locked_free(game)  # the key itself is held and active
    assert not game.security_openable()
    assert not game.doorway_passable(game.state.pos, N)


def test_master_key_keys_unchanged_on_passage():
    """Passing a locked door with the Master Key does not decrement keys.

    The Master Key is a permanent free opener; keys are never spent.
    """
    game = _game(frozenset({"master_key"}))
    game.state.keys = 0
    seg = segment_key(game.state.pos, N)
    game.state.door_state[seg] = DOOR_LOCKED
    game.state.door_version += 1
    game._unlock_for_passage(game.state.pos, N)
    assert game.state.keys == 0


def test_can_open_locked_free_false_without_master_key():
    """can_open_locked_free returns False when no Master Key is held.

    This gates the nav BFS key-cost exemption to only when the key is actually held.
    """
    game = _game()
    assert not si.can_open_locked_free(game)


# ------------------------------------------------ Lockpick rates

def test_lockpick_attempt1_success_rate():
    """First lockpick attempt succeeds at approximately 54/101 (~53.5%) over 300 trials.

    The datamined rate must be reproduced within ±10 percentage points.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "lock_pick_kit", source="test")

    from blueprince_sim.engine.rng import Rng
    successes = 0
    trials = 300
    for seed in range(trials):
        # Fresh state per trial so attempt index and pity reset
        st2 = GameState()
        st2.special.enabled = True
        si.grant(st2, reg, "lock_pick_kit", source="test")

        class _FakeGame:
            state = st2
            registry = reg
            rng = Rng(seed)

        result = si.open_locked_free(_FakeGame())
        if result:
            successes += 1

    rate = successes / trials
    expected = 54 / 101
    assert abs(rate - expected) < 0.10, (
        f"lockpick attempt-1 success rate {rate:.3f} deviates >10pp from {expected:.3f}")


def test_lockpick_pity_auto_succeeds_after_3_fails():
    """Lock Pick Kit pity rule: after 3 consecutive fails, the next attempt auto-succeeds.

    This prevents indefinite lockout regardless of RNG seed.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "lock_pick_kit", source="test")
    st.special.lockpick_fails = 3  # pity threshold reached

    from blueprince_sim.engine.rng import Rng

    class _FakeGame:
        state = st
        registry = reg
        rng = Rng(0)

    result = si.open_locked_free(_FakeGame())
    assert result is True, "pity should auto-succeed after 3 consecutive fails"
    assert st.special.lockpick_fails == 0, "pity success must reset fail counter"


# ------------------------------------------------ OPEN action mask: locked doorways

def _force_lock(game: Game, cell: int, d: int) -> None:
    """Force a doorway segment to DOOR_LOCKED, bumping door_version so cached
    distance/mask state notices the change."""
    game.state.door_state[segment_key(cell, d)] = DOOR_LOCKED
    game.state.door_version += 1


def _open_action_legal(game: Game, cell: int, d: int) -> bool:
    """Whether action_mask() marks the draft-open of (cell, d) legal."""
    mask = A.action_mask(game)
    return mask[A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]]


def test_open_action_master_key_legal_at_zero_keys():
    """Drafting through a locked frontier doorway is legal at 0 keys when a
    Master Key is held.

    This is the bug this PR fixes: action_mask()'s OPEN branch gated on
    st.keys alone and never consulted special_items.can_open_locked_free
    (unlike game.doorway_passable), so a Master Key holder with 0 regular
    keys could never use the highest-tier unlock item at all.
    """
    game = _game(frozenset({"master_key"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert _open_action_legal(game, cell, d)


def test_open_action_stopwatch_does_not_open_at_zero_keys():
    """The Stopwatch must NOT make a 0-key locked-door draft legal.

    open_locked_free() only waives a locked door via the Stopwatch when
    state.keys >= 1 (the wiki: a key must be in hand, though it is not
    spent), so at 0 keys the Stopwatch grants no bypass and the OPEN action
    must stay illegal, same as before this fix.
    """
    game = _game(frozenset({"stopwatch"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert not _open_action_legal(game, cell, d)


def test_open_action_silver_key_legal_at_zero_keys():
    """A held Silver Key makes a locked frontier doorway's draft-open legal
    at 0 keys: it is consumed instead of a regular key on a draft-open
    (open_door passes for_draft=True to _unlock_for_passage), unlike a
    plain move through an already-open segment.

    doorway_passable() does not know about this bypass -- its
    can_open_locked_free check only recognizes the Master Key -- so the
    mask cannot rely on doorway_passable alone here; it asks about a held
    Silver Key directly, mirroring _unlock_for_passage's own for_draft
    branch. Also confirms the engine actually honours it end-to-end: the
    draft succeeds and the Silver Key (not a nonexistent regular key) is
    what gets spent.
    """
    game = _game(frozenset({"silver_key"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert _open_action_legal(game, cell, d)
    game.open_door(cell, d)
    assert game.state.keys == 0
    assert not si.has(game.state, "silver_key")


def test_open_action_lockpick_does_not_open_at_zero_keys():
    """A held Lock Pick Kit does NOT make a 0-key locked-door draft legal.

    A pick attempt is probabilistic (special_items.open_locked_free); on
    failure _unlock_for_passage falls back to spending a real key and
    asserts st.keys >= cost. At 0 keys that assert would fail, so unlike
    the Master/Silver Key the lockpick cannot make this action a *safe*
    legal move -- the mask must stay conservative (illegal), same as
    before this fix.
    """
    game = _game(frozenset({"lock_pick_kit"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert not _open_action_legal(game, cell, d)


def test_open_action_mask_agrees_with_engine_predicate():
    """The OPEN mask bit for the current room's own locked doorway must
    exactly match what the engine will actually accept, across several
    items and key counts.

    Scoped to the player's own room (key_cost_map()[cell] == 0 there, since
    no path is walked to reach it) so the mask's affordability arithmetic
    and doorway_passable's segment-local check are directly comparable.
    The ground truth used here is doorway_passable() OR a held Silver Key
    with special_items enabled -- doorway_passable alone does not model
    the Silver Key's draft-only bypass (see
    test_open_action_silver_key_legal_at_zero_keys above). This is exactly
    the class of drift -- a second, silently-diverging copy of a passability
    rule -- that produced the bug this PR fixes.
    """
    for items in (
        frozenset(),
        frozenset({"master_key"}),
        frozenset({"silver_key"}),
        frozenset({"lock_pick_kit"}),
        frozenset({"stopwatch"}),
    ):
        for keys in (0, 1, 2):
            game = _game(items)
            cell, d = game.open_doorways()[0]
            _force_lock(game, cell, d)
            game.state.keys = keys
            expected = game.doorway_passable(cell, d) or (
                game.cfg.special_items and si.has(game.state, "silver_key"))
            actual = _open_action_legal(game, cell, d)
            assert actual == expected, (
                f"items={sorted(items)} keys={keys}: mask={actual} expected={expected}")


# ------------------------------------------------ Emerald Bracelet gem cost

def test_emerald_bracelet_waives_gem_cost():
    """Emerald Bracelet reduces any gem cost to 0.

    The bracelet waiver takes priority over other modifiers and applies unconditionally.
    """
    game = _game(frozenset({"emerald_bracelet"}))
    reg = game.registry
    # Find any gem-cost room
    gem_room = next(r for r in reg.rooms if r.gem_cost > 0)
    result = si.gem_cost_modifier(game, gem_room, gem_room.gem_cost)
    assert result == 0


# ------------------------------------------------ Sleeping Mask

def test_sleeping_mask_steps_on_bedroom_entry():
    """Sleeping Mask grants 5 steps when first entering a standard bedroom.

    This is the mask's core mechanic: restoring steps by resting in a bedroom.
    """
    game = _game(frozenset({"sleeping_mask"}))
    reg = game.registry
    bedroom = reg.by_id["bedroom"]
    steps_before = game.state.steps
    cell = 7
    game.state.grid[cell] = bedroom.idx
    game.state.placed_doors[cell] = bedroom.door_mask
    si.on_enter(game, bedroom, cell)
    assert game.state.steps == steps_before + 5


def test_sleeping_mask_bunk_room_gives_10_steps():
    """Sleeping Mask grants 10 steps in the Bunk Room (counts as 2 bedrooms).

    The Bunk Room's counts_as_bedrooms=2 effect doubles the mask's per-bedroom grant.
    """
    game = _game(frozenset({"sleeping_mask"}))
    reg = game.registry
    bunk = reg.by_id["bunk_room"]
    steps_before = game.state.steps
    cell = 7
    game.state.grid[cell] = bunk.idx
    game.state.placed_doors[cell] = bunk.door_mask
    si.on_enter(game, bunk, cell)
    assert game.state.steps == steps_before + 10


# ------------------------------------------------ Watering Can

def test_watering_can_green_room_converts_water():
    """Watering Can converts one water charge to one gem on first green room entry.

    Each green room entry that finds water > 0 produces one gem.
    """
    game = _game(frozenset({"watering_can"}))
    reg = game.registry
    greenhouse = reg.by_id["greenhouse"]
    assert game.state.special.water == 3
    gems_before = game.state.gems
    cell = 7
    game.state.grid[cell] = greenhouse.idx
    game.state.placed_doors[cell] = greenhouse.door_mask
    si.on_enter(game, greenhouse, cell)
    assert game.state.special.water == 2
    assert game.state.gems == gems_before + 1


def test_watering_can_stops_at_zero_water():
    """Watering Can does not grant gems once water charges are exhausted.

    Water = 0 means the can is empty; entering more green rooms yields nothing.
    """
    game = _game(frozenset({"watering_can"}))
    reg = game.registry
    greenhouse = reg.by_id["greenhouse"]
    game.state.special.water = 0
    gems_before = game.state.gems
    cell = 7
    game.state.grid[cell] = greenhouse.idx
    game.state.placed_doors[cell] = greenhouse.door_mask
    si.on_enter(game, greenhouse, cell)
    assert game.state.gems == gems_before


# ------------------------------------------------ Stopwatch gem cost

def test_stopwatch_waives_gem_cost_at_pay_time_only():
    """Active Stopwatch keeps the gems on an actual payment, but affordability
    queries never burn a charge.

    The wiki requires the gems to be held; the charge is spent when paying,
    so policies may probe gem_cost_modifier freely without draining the timer.
    """
    game = _game(frozenset({"stopwatch"}))
    reg = game.registry
    gem_room = next(r for r in reg.rooms if r.gem_cost > 0)
    cost = gem_room.gem_cost
    game.state.gems = cost  # exactly enough
    left_before = game.state.special.stopwatch_left
    # Query path stays pure: full cost reported, no charge spent.
    assert si.gem_cost_modifier(game, gem_room, cost) == cost
    assert game.state.special.stopwatch_left == left_before
    # Pay path waives: gems kept, one charge spent.
    assert si.stopwatch_waives_gems(game, cost)
    assert game.state.gems == cost
    assert game.state.special.stopwatch_left == left_before - 1


def test_stopwatch_ignores_free_rooms():
    """A zero gem cost never burns a Stopwatch charge.

    Free rooms reach the modifier with cost 0; waiving nothing must not
    consume one of the stopwatch's limited free-cost events.
    """
    game = _game(frozenset({"stopwatch"}))
    reg = game.registry
    free_room = next(r for r in reg.rooms if r.gem_cost == 0 and r.rarity)
    left_before = game.state.special.stopwatch_left
    assert si.gem_cost_modifier(game, free_room, 0) == 0
    assert game.state.special.stopwatch_left == left_before


def test_stopwatch_waives_locked_door():
    """Stopwatch can open a locked door without spending a key (key is kept in hand).

    Per the wiki, the stopwatch requires a key in hand but does not consume it.
    """
    game = _game(frozenset({"stopwatch"}))
    game.state.keys = 1
    left_before = game.state.special.stopwatch_left
    result = si.open_locked_free(game)
    assert result is True
    assert game.state.keys == 1, "stopwatch must not spend the key"
    assert game.state.special.stopwatch_left == left_before - 1
