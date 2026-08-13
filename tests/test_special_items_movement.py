"""Special items: movement cost, lock, and gem-cost behaviors (task C)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
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


def test_open_action_legal_regardless_of_items_or_keys_for_a_locked_doorway():
    """Trying a locked frontier doorway is legal at 0 keys and with no
    unlock item held at all -- trying costs nothing (Phase.LOCK_PENDING is
    how the player finds out it's locked and chooses how to open it, the
    owner's ruling). This is the property that replaces the four
    item-specific "does the OPEN action become legal" tests below: with the
    OLD auto-resolving open_door, whether an item made the draft legal
    depended on which item and how many keys were held; now the try itself
    never depends on either.
    """
    for items in (frozenset(), frozenset({"master_key"}), frozenset({"silver_key"}),
                  frozenset({"lock_pick_kit"}), frozenset({"stopwatch"})):
        game = _game(items)
        cell, d = game.open_doorways()[0]
        _force_lock(game, cell, d)
        game.state.keys = 0
        assert _open_action_legal(game, cell, d), f"items={sorted(items)}"


def test_open_action_master_key_legal_at_zero_keys():
    """Drafting through a locked frontier doorway is legal at 0 keys when a
    Master Key is held, AND the special-keys-menu's master_key row is itself
    legal once there.

    Setup rebuilt, not the property (a held Master Key still makes the door
    openable at 0 keys) -- but the mechanism moved: it used to be
    action_mask()'s OPEN branch consulting special_items.can_open_locked_free
    directly; now trying is unconditional (see the test above) and the
    Master Key's own legality lives on Game.can_use_special_key_at_lock,
    reached through Phase.LOCK_PENDING instead of resolved inline.
    """
    game = _game(frozenset({"master_key"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert _open_action_legal(game, cell, d)
    game.open_door(cell, d)
    assert game.phase is Phase.LOCK_PENDING
    idx = A.LOCK_SPECIAL_KEY_BASE + list(
        game.registry.lock_rules["special_key_menu"]["order"]).index("master_key")
    assert A.action_mask(game)[idx]
    assert game.can_use_special_key_at_lock("master_key")


def test_open_action_stopwatch_does_not_waive_the_key_requirement_at_zero_keys():
    """An active Stopwatch must NOT make the use-a-key menu row legal at 0
    keys: the wiki's "at least one key is still required for the option to
    use a key to appear, even though it isn't spent."

    Setup rebuilt (was: the OPEN action itself must stay illegal at 0 keys).
    Trying is unconditional now (see the first test above), so the
    Stopwatch's key-requirement check moved to Game.can_use_key_at_lock,
    which this exercises directly through Phase.LOCK_PENDING instead of via
    the old auto-resolving open_door/_unlock_for_passage.
    """
    game = _game(frozenset({"stopwatch"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    game.state.special.stopwatch_left = 5
    game.open_door(cell, d)
    assert game.phase is Phase.LOCK_PENDING
    assert not game.can_use_key_at_lock(), "0 keys: an active Stopwatch grants no bypass"
    assert not A.action_mask(game)[A.LOCK_USE_KEY_ACTION]


def test_open_action_silver_key_legal_at_zero_keys():
    """The special-keys-menu's silver_key row is legal at 0 keys, consumes
    the Silver Key (not a nonexistent regular key), and biases the dealt
    hand -- exercised here through the action mask and apply_action, the
    same entry points the trainer uses, complementing
    test_draft_items.py's direct Game-API coverage of the same mechanism.

    Setup rebuilt, not the property: opening a locked doorway no longer
    resolves the Silver Key automatically (open_door used to pass
    for_draft=True straight into _unlock_for_passage's silver-key branch);
    it now only parks Phase.LOCK_PENDING, and the special-keys-menu row must
    be selected as its own action.
    """
    game = _game(frozenset({"silver_key"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    assert _open_action_legal(game, cell, d)
    game.open_door(cell, d)
    assert game.phase is Phase.LOCK_PENDING
    idx = A.LOCK_SPECIAL_KEY_BASE + list(
        game.registry.lock_rules["special_key_menu"]["order"]).index("silver_key")
    assert A.action_mask(game)[idx]
    A.apply_action(game, idx)
    assert game.state.keys == 0
    assert not si.has(game.state, "silver_key")
    assert game.phase is Phase.DRAFTING


def test_open_action_lockpick_legal_at_zero_keys():
    """A held Lock Pick Kit makes the lockpick menu row legal even at 0
    keys -- the wiki: it unlocks "without using any keys or special keys".

    Setup rebuilt AND the property flips: the OLD open_door resolved a
    locked door in one call, so a probabilistic pick attempt had to be
    conservatively excluded from the mask altogether (a failure fell back
    to _unlock_for_passage spending a real key it might not have, an
    unsafe "legal but may crash" action). Now a failed lockpick_at_lock
    attempt spends nothing and leaves Phase.LOCK_PENDING (see
    Game.lockpick_at_lock), so it is safe to offer regardless of keys held.
    """
    game = _game(frozenset({"lock_pick_kit"}))
    cell, d = game.open_doorways()[0]
    _force_lock(game, cell, d)
    game.state.keys = 0
    game.open_door(cell, d)
    assert game.phase is Phase.LOCK_PENDING
    assert game.can_lockpick_at_lock()
    assert A.action_mask(game)[A.LOCK_LOCKPICK_ACTION]


def test_lock_pending_mask_agrees_with_engine_predicates(registry):
    """Every LOCK_PENDING mask bit must exactly match its Game can_* predicate,
    across several items and key counts -- the drift risk the OLD OPEN-action
    version of this test guarded against (a second, silently-diverging copy
    of a legality rule) moved here along with the legality logic itself: the
    OPEN action's own legality is now unconditional for a locked doorway
    (see test_open_action_legal_regardless_of_items_or_keys_for_a_locked_doorway),
    so there is nothing left to drift on that side; the menu is the new
    surface with two independent implementations (env/actions.py's mask and
    engine/game.py's can_* methods) that could silently disagree.
    """
    order = list(registry.lock_rules["special_key_menu"]["order"])
    for items in (
        frozenset(),
        frozenset({"master_key"}),
        frozenset({"silver_key"}),
        frozenset({"lock_pick_kit"}),
        frozenset({"stopwatch"}),
        frozenset({"master_key", "silver_key", "lock_pick_kit"}),
    ):
        for keys in (0, 1, 2):
            game = _game(items)
            cell, d = game.open_doorways()[0]
            _force_lock(game, cell, d)
            game.state.keys = keys
            game.open_door(cell, d)
            assert game.phase is Phase.LOCK_PENDING
            mask = A.action_mask(game)
            assert mask[A.LOCK_USE_KEY_ACTION] == game.can_use_key_at_lock(), (
                f"items={sorted(items)} keys={keys}: use_key")
            assert mask[A.LOCK_LOCKPICK_ACTION] == game.can_lockpick_at_lock(), (
                f"items={sorted(items)} keys={keys}: lockpick")
            assert mask[A.LOCK_ABANDON_ACTION] == game.can_abandon_lock(), (
                f"items={sorted(items)} keys={keys}: abandon")
            for i, key_id in enumerate(order):
                assert (mask[A.LOCK_SPECIAL_KEY_BASE + i]
                        == game.can_use_special_key_at_lock(key_id)), (
                    f"items={sorted(items)} keys={keys}: {key_id}")


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
