"""Special items: movement cost, lock, and gem-cost behaviors (task C)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, N
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


# ------------------------------------------------ Running Shoes distance rule

def test_running_shoes_first_loss_of_day_only_records_position():
    """The first step lost while holding the shoes always costs 1 -- it has no
    reference position yet to measure distance against, so it can only record
    one (the wiki: "the first time the player loses a step ... the player's
    position is recorded").
    """
    game = _game(frozenset({"running_shoes"}))
    reg = game.registry
    entrance = reg.by_id["entrance_hall"]
    assert game.state.special.moves_since_free == 0, "setup check: no anchor recorded yet"

    cost = si.move_step_cost(game, game.state.pos, N, entrance)

    assert cost == 1, "the very first loss of the day establishes the baseline, never free"


def test_running_shoes_waives_when_destination_far_from_anchor():
    """A move landing 2.2+ room-lengths (euclidean) from the recorded anchor
    is free, and the landing cell becomes the new anchor.

    Cell 7 (rank 2, col 2) is the anchor. Moving North from cell 37 (rank 8,
    col 2) lands on cell 42 (rank 9, col 2) -- 7.0 room-lengths from the
    anchor on the same column -- past the 2.2 default threshold, computed by
    hand (not by calling move_step_cost).
    """
    game = _game(frozenset({"running_shoes"}))
    reg = game.registry
    entrance = reg.by_id["entrance_hall"]
    game.state.special.moves_since_free = 7 + 1  # anchor cell 7, pre-set (no prior call)

    cost = si.move_step_cost(game, 37, N, entrance)  # neighbor(37, N) == 42

    assert cost == 0, "42 is 7.0 room-lengths from the anchor (7), past the 2.2 threshold"
    assert game.state.special.moves_since_free == 42 + 1, "the landing cell becomes the anchor"


def test_running_shoes_stays_close_costs_normally_and_anchor_unchanged():
    """A move landing within 2.2 room-lengths of the anchor costs 1, and the
    anchor is left exactly where it was -- distance keeps accumulating
    against the SAME reference point rather than resetting every move.

    Cell 6 (rank 2, col 1) is the anchor. Cell 8 (rank 2, col 3) is 2.0 room-
    lengths away (same rank, two columns over) -- under the 2.2 threshold --
    computed by hand, not by calling move_step_cost.
    """
    game = _game(frozenset({"running_shoes"}))
    reg = game.registry
    entrance = reg.by_id["entrance_hall"]
    game.state.special.moves_since_free = 6 + 1  # anchor cell 6, pre-set (no prior call)

    cost = si.move_step_cost(game, 7, E, entrance)  # neighbor(7, E) == 8

    assert cost == 1, "8 is only 2.0 room-lengths from the anchor (6), under the 2.2 threshold"
    assert game.state.special.moves_since_free == 6 + 1, "anchor must not move on a normal loss"


def test_running_shoes_not_held_declines():
    """Without the shoes in inventory, the handler declines (None) regardless
    of anchor state, leaving the priority chain's default cost of 1 in place.
    """
    game = _game(frozenset())
    reg = game.registry
    entrance = reg.by_id["entrance_hall"]

    cost = si.move_step_cost(game, game.state.pos, N, entrance)

    assert cost == 1, "move_step_cost's own default applies when no item answers"


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
    assert st.special.lockpick_fails == -1, "pity auto-success resets the counter to -1"


class _ScriptedChance:
    """Deterministic engine.rng.Rng stand-in: pops a scripted outcome per
    call (never a seed hunt) and records the (label, probability) pairs it
    was asked to resolve, so the rate rung a roll used can be inspected
    without depending on RNG internals."""

    def __init__(self, outcomes: list[bool]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, float]] = []

    def chance(self, label: str, p: float) -> bool:
        self.calls.append((label, p))
        return self._outcomes.pop(0)


def _fake_game(state, registry, rng):
    """A duck-typed game object exposing just what special_items.py's
    lockpick path reads (state/registry/rng), for driving it without a
    full Game."""
    class _FakeGame:
        pass
    g = _FakeGame()
    g.state = state
    g.registry = registry
    g.rng = rng
    return g


def test_lockpick_ladder_indexes_by_successes_not_attempts():
    """The rate ladder steps down only after a SUCCESSFUL pick, per the wiki
    ("the chance goes down after a successful lockpick") -- three
    consecutive failures must leave it on the first rung, and a single
    success must advance it to the second. Uses the Pick Sound Amplifier
    (pity=0) so the two-sided pity system cannot intervene and change which
    rolls get made."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "pick_sound_amplifier", source="test")
    rng = _ScriptedChance([False, False, False, True, False])
    game = _fake_game(st, reg, rng)

    for _ in range(3):
        assert si.open_locked_free(game) is False
    # three fails, zero successes so far: every roll used rung 0 (90/101)
    assert [p for _, p in rng.calls] == [90 / 101, 90 / 101, 90 / 101]

    assert si.open_locked_free(game) is True  # 4th roll succeeds -> 1 success now
    assert si.open_locked_free(game) is False  # 5th roll must use rung 1 (85/101)
    assert rng.calls[-1] == ("lockpick", 85 / 101)


def test_lockpick_pity_counter_is_two_sided():
    """The pity counter adds 1 on a fail and subtracts 1 on a success --
    it does not just clear to 0 on either outcome, per the wiki's "failing
    ... adds 1, succeeding subtracts 1"."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "lock_pick_kit", source="test")
    rng = _ScriptedChance([False, False, True, False])
    game = _fake_game(st, reg, rng)

    si.open_locked_free(game)  # fail: 0 -> 1
    assert st.special.lockpick_fails == 1
    si.open_locked_free(game)  # fail: 1 -> 2
    assert st.special.lockpick_fails == 2
    si.open_locked_free(game)  # success: 2 -> 1
    assert st.special.lockpick_fails == 1
    si.open_locked_free(game)  # fail: 1 -> 2
    assert st.special.lockpick_fails == 2


def test_lockpick_pity_auto_succeeds_at_3_and_resets_to_negative_one():
    """Once the counter reaches the pity threshold (3), the NEXT attempt
    auto-succeeds without consulting the RNG at all, and resets to -1 (not
    0) per the wiki's "the counter is set to -1"."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "lock_pick_kit", source="test")
    st.special.lockpick_fails = 3
    rng = _ScriptedChance([])  # must not be consulted: this is a bypass, not a roll

    assert si.open_locked_free(_fake_game(st, reg, rng)) is True
    assert st.special.lockpick_fails == -1
    assert rng.calls == [], "pity auto-success must bypass the RNG entirely"


def test_lockpick_pity_auto_fails_at_negative_2_and_resets_to_1():
    """Two consecutive successes drive the counter to -2; the wiki says
    that (while lockpicking skill is <= 20, which this sim always is since
    no skill stat exists -- see special_items.json's lock_pick_kit
    meta.notes) the NEXT attempt auto-fails and the counter resets to 1."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "lock_pick_kit", source="test")
    st.special.lockpick_fails = -2
    rng = _ScriptedChance([])  # must not be consulted: this is a bypass, not a roll

    assert si.open_locked_free(_fake_game(st, reg, rng)) is False
    assert st.special.lockpick_fails == 1
    assert rng.calls == [], "pity auto-fail must bypass the RNG entirely"


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
    owner's ruling). Whether an item or key count changes what's legal
    inside that menu is exercised by the four item-specific tests below;
    trying itself never depends on either.
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

    Trying itself is unconditional (see the test above); the Master Key's
    own legality lives on Game.can_use_special_key_at_lock, reached through
    Phase.LOCK_PENDING.
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

    The Stopwatch's key-requirement check lives on Game.can_use_key_at_lock,
    exercised here directly through Phase.LOCK_PENDING.
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

    open_door only parks Phase.LOCK_PENDING; the special-keys-menu row must
    be selected as its own action to resolve the Silver Key.
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

    A failed lockpick_at_lock attempt spends nothing and leaves
    Phase.LOCK_PENDING (see Game.lockpick_at_lock), so it is safe to offer
    regardless of keys held.
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
    across several items and key counts: the menu is the surface with two
    independent implementations (env/actions.py's mask and engine/game.py's
    can_* methods) that could silently disagree. The OPEN action's own
    legality is unconditional for a locked doorway (see
    test_open_action_legal_regardless_of_items_or_keys_for_a_locked_doorway),
    so there is nothing to drift on that side.
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


# ------------------------------------------------ Running Shoes area travel

class _FixedChanceRng:
    """Wraps a real engine.rng.Rng, overriding ``.chance`` for an exact set of
    labels to fixed booleans -- every other draw still comes from the real
    substream underneath. Used to force Running Shoes' area-roll outcomes
    deterministically instead of hunting for a seed."""

    def __init__(self, real, outcomes: dict) -> None:
        self._real = real
        self._outcomes = outcomes

    def __getattr__(self, name):
        return getattr(self._real, name)

    def chance(self, label, p):
        if label in self._outcomes:
            return self._outcomes[label]
        return self._real.chance(label, p)


def test_travel_to_area_hop_waives_both_steps_when_both_rolls_forced_true():
    """travel_to's area-hop deduction now rolls Running Shoes once per node
    entered along the route, instead of bypassing it entirely: house ->
    grounds -> private_drive is a 2-step area_hop through two non-anchor
    nodes, and forcing both of their rolls to hit waives both steps.
    """
    game = _game(frozenset({"running_shoes"}))
    game.rng = _FixedChanceRng(game.rng, {
        "running_shoes_area_grounds": True,
        "running_shoes_area_private_drive": True,
    })
    steps_before = game.state.steps

    game.travel_to("private_drive")

    assert game.state.steps == steps_before, (
        "both of the 2 area_hop steps must be waived when both rolls are forced to hit")


def test_travel_to_area_hop_waives_exactly_one_step_on_a_mixed_roll():
    """One forced hit and one forced miss across the same two-hop route waives
    exactly one of the two area_hop steps -- proving the per-node rolls are
    independent, not an all-or-nothing waiver for the whole hop.
    """
    game = _game(frozenset({"running_shoes"}))
    game.rng = _FixedChanceRng(game.rng, {
        "running_shoes_area_grounds": True,
        "running_shoes_area_private_drive": False,
    })
    steps_before = game.state.steps

    game.travel_to("private_drive")

    assert game.state.steps == steps_before - 1, (
        "exactly one of the two area_hop steps must be waived on a mixed roll")


def test_travel_to_area_hop_not_held_pays_full_cost():
    """Without Running Shoes held, travel_to's area-hop deduction is
    untouched: the full 2-step house -> grounds -> private_drive cost is
    paid, matching pre-fix behavior for a non-holder.
    """
    game = _game(frozenset())
    steps_before = game.state.steps

    game.travel_to("private_drive")

    assert game.state.steps == steps_before - 2, "area_hop must be paid in full when not held"


def test_travel_to_grid_anchor_landing_never_rolls_running_shoes():
    """Landing back on a grid anchor (the house) never rolls Running Shoes,
    even forced to always hit -- the wiki scopes the area-entry roll to
    "anywhere outside the house", which a house landing is not.
    """
    game = _game(frozenset({"running_shoes"}))
    game.rng = _FixedChanceRng(game.rng, {"running_shoes_area_grounds": False})
    game.travel_to("grounds")  # off-grid now; "grounds" roll forced to miss
    game.rng = _FixedChanceRng(game.rng, {"running_shoes_area_house": True})
    steps_before = game.state.steps

    game.travel_to("house")

    assert game.state.steps == steps_before - 1, (
        "the house landing must pay its 1 area_hop step even with a forced-hit roll")
