"""Locked doors and security doors: observable behavior.

Covers key spending at locked doorways, in-drafting (a drafted room's door
opens a locked/security door on its far side for free), the daily bias
multiplier, security-door spawning (whitelist, distance gate, per-level
caps), the keycard/power/offline-mode truth table, the Security and Utility
Closet switch actions, and the env mask/obs plumbing.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import locks
from blueprince_sim.engine import special_items
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import DIRS, E, N, S, W, neighbor
from blueprince_sim.engine.locks import (DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY,
                                         segment_key)
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env import actions as A


def _game(registry, **cfg) -> Game:
    return Game(GameConfig(**cfg), seed=1, registry=registry)


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    """Overwrite a doorway segment's state, bumping door_version so caches
    (distance maps, action masks) notice the change."""
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


# ------------------------------------------------------------- lock rolls


def test_low_ranks_never_locked_by_chance(registry):
    """Rank 1-3 doors are never locked: E-W segments within ranks 1-3 and N-S
    boundaries below the 3<->4 line always roll open."""
    for seed in range(20):
        g = Game(GameConfig(), seed=seed, registry=registry)
        for (cell, d), state in g.state.door_state.items():
            low_cell, _ = segment_key(cell, d)
            if low_cell < 15 and d in (E, W):        # E-W within ranks 1-3
                assert state == DOOR_OPEN
            if low_cell < 10:                        # N-S boundaries below 3<->4
                assert state == DOOR_OPEN


def test_antechamber_doorways_start_locked(registry):
    """With antechamber_levers=False, the three doorways start DOOR_LOCKED
    (rank 8<->9 has 100% base chance), and a guaranteed lock leaves the
    daily bias untouched.

    antechamber_levers=False is used here to test the lock system in isolation;
    with levers=True the segments start DOOR_SEALED (see test_antechamber_levers.py).
    """
    # Rank 8<->9 sits over 100% base chance: at day-start bias 1 every
    # Antechamber doorway rolls locked (until a connecting room in-drafts).
    g = Game(GameConfig(antechamber_levers=False), seed=3, registry=registry)
    for d in (S, E, W):
        assert g.door_state_of(ANTECHAMBER_CELL, d) == DOOR_LOCKED
    # Guaranteed-by-chance locks skip the bias update (second-roll rule).
    assert g.state.lock_bias == 1.0


def test_corridor_and_corriyard_doors_are_never_locked(registry):
    """Corridor and Corriyard doors are guaranteed unlocked even at ranks
    where locks are near-certain, and never spawn as security doors."""
    # Guaranteed-unlocked rooms: even at ranks where locks are near-certain,
    # their doors roll open and never spawn as security doors.
    for room_id in ("corridor", "corriyard__ix50"):
        room = registry.by_id[room_id]
        for seed in range(30):
            g = Game(GameConfig(), seed=seed, registry=registry)
            g._place_room(room, 31, room.door_mask)  # rank 7 center
            for d in DIRS:
                if room.door_mask & d and neighbor(31, d) != -1:
                    assert g.door_state_of(31, d) == DOOR_OPEN, (room_id, seed, d)


def test_door_locks_flag_disables_everything(registry):
    """door_locks=False turns the whole system off: no door state is rolled,
    the Antechamber is passable, and the keycard machinery is inert.

    antechamber_levers=False is set alongside door_locks=False so that the
    sealed-lever state does not appear in door_state (sealed is a separate system).
    """
    g = Game(GameConfig(door_locks=False, antechamber_levers=False), seed=3,
             registry=registry)
    assert g.state.door_state == {}
    assert g.doorway_passable(ANTECHAMBER_CELL, S)
    assert not g.can_toggle_keycard_power()


# ------------------------------------------------------- in-drafting opens


def test_drafting_a_room_on_the_far_side_unlocks_a_locked_door(registry):
    """In-drafting: placing a room whose door faces back through a locked
    doorway opens that door for free - no key needed to walk through."""
    g = _game(registry)
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    _force_state(g, 2, N, DOOR_LOCKED)  # the entrance's north doorway
    g.state.keys = 0
    g._place_room(straight, 7, N | S)  # drafted on the far side, facing back
    assert g.door_state_of(2, N) == DOOR_OPEN
    assert N in g.adjacent_moves()      # walkable without a key
    assert g.distance_map()[7] == 1


def test_drafting_a_room_on_the_far_side_opens_a_security_door(registry):
    """In-drafting opens even a security door the keycard system would keep
    sealed - the placement bypasses the reader entirely."""
    g = _game(registry)
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    _force_state(g, 2, N, DOOR_SECURITY)
    assert not g.security_openable()    # system sealed: card-less, powered
    g._place_room(straight, 7, N | S)
    assert g.door_state_of(2, N) == DOOR_OPEN  # in-drafting ignores the seal


def test_connecting_room_opens_the_antechamber_doorway(registry):
    """Drafting a room facing the Antechamber opens its locked doorway
    (in-drafting mechanic), so reaching the Antechamber never requires a key.

    antechamber_levers=False is used to isolate the in-drafting / lock mechanic;
    with levers=True the segment starts DOOR_SEALED and in-drafting does NOT open
    it (only the lever room does).
    """
    g = Game(GameConfig(antechamber_levers=False), seed=1, registry=registry)
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_LOCKED
    g._place_room(straight, 37, N | S)  # rank 8 center, north door faces it
    g.state.keys = 0
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN
    assert g.doorway_passable(37, N)


# ------------------------------------------------------------- bias system


def _bias_state() -> GameState:
    st = GameState()
    st.lock_bias = 1.0
    return st


def test_bias_drops_after_locked_and_recovers_after_unlocked(registry):
    """The daily lock-bias multiplier drops after a locked roll and climbs
    after an unlocked one - even past 1.0, per the datamined rule."""
    rules = registry.lock_rules
    st = _bias_state()
    # Find a seed whose first roll locks a mid-band (4<->5 boundary) door.
    for seed in range(50):
        st = _bias_state()
        if locks._roll_lock(st, rules, 17, N, Rng(seed)) == DOOR_LOCKED:
            break
    assert st.lock_bias == pytest.approx(1 - 0.385)
    # An unlocked outcome above the low-chance gate raises the bias again.
    st.lock_bias = 0.7
    for seed in range(50):
        probe = _bias_state()
        probe.lock_bias = 0.7
        if locks._roll_lock(probe, rules, 17, N, Rng(seed)) == DOOR_OPEN:
            st = probe
            break
    # max(0.7 + 0.35, 1) = 1.05: unlocked doors can push the bias past 1,
    # making the next doors slightly MORE lock-prone (datamined rule).
    assert st.lock_bias == pytest.approx(1.05)


# ------------------------------------------------- keys at locked doorways


def test_locked_doorway_needs_and_spends_a_key(registry):
    """Trying a locked frontier doorway is free and always legal at any key
    count, including zero: Game.open_door parks Phase.LOCK_PENDING and
    spends nothing. Spending a key there is a separate step: use_key_at_lock
    requires one, spends exactly one, and leaves the door permanently open,
    exercised below via that menu row.
    """
    g = _game(registry)
    doors = g.open_doorways()
    assert doors
    cell, d = doors[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)  # trying is free: no raise, no key spent
    assert g.phase is Phase.LOCK_PENDING
    assert g.state.keys == 0
    assert not g.can_use_key_at_lock(), "0 keys: the use-a-key row must not be legal"
    g.abandon_lock()
    assert g.phase is Phase.NAVIGATE
    assert g.door_state_of(cell, d) == DOOR_LOCKED  # abandon leaves it locked

    g.state.keys = 2
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    g.use_key_at_lock()
    assert g.phase is Phase.DRAFTING
    assert g.state.keys == 1
    assert g.door_state_of(cell, d) == DOOR_OPEN  # unlocked for good


def test_locked_interior_door_costs_a_key_or_a_detour(registry):
    """A locked interior door reroutes the keyless pathfinder around it; with
    a key the direct path is used and the walk spends the key. Equidistant
    routes must be costed via the key-free path."""
    # A locked door between placed rooms (hand-built today; the Vestibule
    # will re-lock doors like this later) changes traversal distances: with
    # no key the pathfinder walks around it, with a key it goes through -
    # and both are reflected in the distance the step budget is checked
    # against.
    g = _game(registry)
    cross = next(r for r in registry.rooms
                 if r.layout == "cross" and r.rarity is not None)
    for cell in (3, 8, 7):  # ring: entrance(2) -> E(3) -> N(8) -> W(7)
        g._place_room(cross, cell, 0xF)
    _force_state(g, 2, N, DOOR_LOCKED)
    g.state.keys = 0
    assert g.distance_map()[7] == 3   # around: 2 -> 3 -> 8 -> 7
    g.state.keys = 1
    assert g.distance_map()[7] == 1   # straight through the lock
    assert g.key_cost_map()[7] == 1
    # Equidistant by either route, cell 8 must be costed via the free path.
    assert g.distance_map()[8] == 2 and g.key_cost_map()[8] == 0
    g.move_to(7)
    assert g.state.pos == 7 and g.state.keys == 0  # the walk spent the key
    assert g.door_state_of(2, N) == DOOR_OPEN


def test_locked_interior_door_can_wall_off_the_house_without_keys(registry):
    """With no detour and no key, the cell beyond a locked interior door is
    simply unreachable; gaining a key restores the route."""
    # No way around and no key: the cell beyond is unreachable, so e.g. the
    # Antechamber can sit out of reach even while steps remain.
    g = _game(registry)
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    g._place_room(straight, 7, N | S)
    _force_state(g, 2, N, DOOR_LOCKED)
    g.state.keys = 0
    assert g.distance_map()[7] == -1
    assert N not in g.adjacent_moves()
    g.state.keys = 1
    assert g.distance_map()[7] == 1
    assert N in g.adjacent_moves()


def test_security_door_blocks_until_openable(registry):
    """A security doorway is impassable until the system opens (keycard on a
    powered reader); passing through then costs no key."""
    g = _game(registry)
    doors = g.open_doorways()
    cell, d = doors[0]
    _force_state(g, cell, d, DOOR_SECURITY)
    assert not g.doorway_passable(cell, d)
    with pytest.raises(AssertionError):
        g.open_door(cell, d)
    g.state.has_keycard = True  # powered readers accept the card
    assert g.doorway_passable(cell, d)
    g.open_door(cell, d)
    assert g.state.keys == 0  # no key spent
    assert g.door_state_of(cell, d) == DOOR_OPEN


# --------------------------------------------------- LOCK_PENDING: the menu


class _FixedChance:
    """Deterministic engine.rng.Rng stand-in: .chance always returns a fixed
    outcome, so a lockpick attempt's success/failure branch can be built
    without hunting for a seed (never build a scenario by random rollout)."""

    def __init__(self, outcome: bool) -> None:
        self._outcome = outcome

    def chance(self, label: str, p: float) -> bool:
        return self._outcome


def test_lock_pending_entered_only_on_a_locked_doorway(registry):
    """Phase.LOCK_PENDING is entered on a DOOR_LOCKED doorway and only
    then -- an open doorway deals a hand directly, same as before this
    feature."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    assert g.door_state_of(cell, d) == DOOR_OPEN  # setup: unlocked by default
    g.open_door(cell, d)
    assert g.phase is Phase.DRAFTING

    g2 = _game(registry)
    cell2, d2 = g2.open_doorways()[0]
    _force_state(g2, cell2, d2, DOOR_LOCKED)
    g2.open_door(cell2, d2)
    assert g2.phase is Phase.LOCK_PENDING


def test_use_key_row_legality_and_effect(registry):
    """use_key: illegal at 0 keys, legal and spends exactly 1 once held,
    and continues straight to a dealt hand."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    assert not g.can_use_key_at_lock()

    g.abandon_lock()
    g.state.keys = 3
    g.open_door(cell, d)
    assert g.can_use_key_at_lock()
    pending = g.use_key_at_lock()
    assert g.phase is Phase.DRAFTING
    assert pending is not None and pending.options
    assert g.state.keys == 2
    assert g.door_state_of(cell, d) == DOOR_OPEN


def test_lockpick_row_success_opens_for_free_and_continues_the_draft(registry):
    """lockpick: legal at 0 keys (holding the tool is all it needs); a
    success opens the door for free (no key spent) and continues the draft.
    Forced deterministically via the pity rule (3 consecutive fails
    auto-succeeds, special_items.json's lock_pick_kit pity=3) rather than a
    seed hunt."""
    g = _game(registry, starting_items=frozenset({"lock_pick_kit"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    assert g.can_lockpick_at_lock(), "holding the kit is enough, no keys needed"
    g.state.special.lockpick_fails = 3  # pity: the next attempt auto-succeeds
    pending = g.lockpick_at_lock()
    assert g.phase is Phase.DRAFTING
    assert pending is not None and pending.options
    assert g.state.keys == 0, "lockpicking never spends a key"
    assert g.door_state_of(cell, d) == DOOR_OPEN
    assert special_items.has(g.state, "lock_pick_kit"), "the kit is reusable, not consumed"
    assert g.state.special.lockpick_fails == -1, "pity auto-success resets the counter to -1"


def test_lockpick_row_failure_stays_parked_and_spends_nothing(registry):
    """A failed lockpick attempt spends nothing, does not consume the tool,
    and does NOT exit the menu -- abandon (and a retry) stay available.
    Forced deterministically via a stub Rng, not a seed hunt."""
    g = _game(registry, starting_items=frozenset({"lock_pick_kit"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    g.rng = _FixedChance(False)
    result = g.lockpick_at_lock()
    assert result is None
    assert g.phase is Phase.LOCK_PENDING, "a failed pick stays in the menu, not a dead end"
    assert g.door_state_of(cell, d) == DOOR_LOCKED
    assert g.state.keys == 0
    assert special_items.has(g.state, "lock_pick_kit")
    assert g.can_abandon_lock()


def test_abandon_row_restores_navigate_with_the_door_still_locked(registry):
    """abandon: always legal, returns to NAVIGATE, the door stays locked,
    nothing is spent -- the wiki's "option to exit the menu"."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 5
    g.open_door(cell, d)
    assert g.can_abandon_lock()
    g.abandon_lock()
    assert g.phase is Phase.NAVIGATE
    assert g.door_state_of(cell, d) == DOOR_LOCKED
    assert g.state.keys == 5


def test_lock_pending_never_a_dead_end(registry):
    """LOCK_PENDING always offers at least one legal action (abandon, if
    nothing else) across a spread of held items and zero keys -- a
    dead-end phase is worse than the bug it replaces."""
    for items in (frozenset(), frozenset({"master_key"}), frozenset({"silver_key"}),
                  frozenset({"lock_pick_kit"}), frozenset({"basement_key"})):
        g = _game(registry, starting_items=items)
        cell, d = g.open_doorways()[0]
        _force_state(g, cell, d, DOOR_LOCKED)
        g.state.keys = 0
        g.open_door(cell, d)
        assert g.phase is Phase.LOCK_PENDING
        mask = A.action_mask(g)
        assert any(mask), f"items={sorted(items)}: LOCK_PENDING mask is all-False"
        assert mask[A.LOCK_ABANDON_ACTION], f"items={sorted(items)}: abandon must stay legal"


def test_master_key_opens_for_free_at_zero_keys_never_consumed(registry):
    """Master Key: legal at 0 keys, never consumed, opens the door for free."""
    g = _game(registry, starting_items=frozenset({"master_key"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    assert g.can_use_special_key_at_lock("master_key")
    pending = g.use_special_key_at_lock("master_key")
    assert g.phase is Phase.DRAFTING
    assert pending is not None and pending.options
    assert g.state.keys == 0
    assert special_items.has(g.state, "master_key"), "Master Key is never consumed"
    assert g.door_state_of(cell, d) == DOOR_OPEN


def test_silver_key_no_longer_auto_spent_on_open(registry):
    """Opening a locked doorway does not spend a held Silver Key -- it stays
    in inventory until the special-keys-menu row is explicitly chosen."""
    g = _game(registry, starting_items=frozenset({"silver_key"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert special_items.has(g.state, "silver_key"), "must not be auto-spent by merely opening"
    assert g.state.keys == 0


def test_reserved_special_keys_always_masked_off(registry):
    """secret_garden_key and key_8 are permanently reserved special-keys-menu
    ids: masked off even when force-held, since their menu behaviour is
    unimplemented -- both are modelled in this sim as draft_conditions tags,
    not door keys. (See the prism_key tests below for its real, non-reserved
    behaviour.)"""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    for key_id in ("secret_garden_key", "key_8"):
        g.state.inventory[key_id] = 1  # force-held, bypassing normal spawn gating
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    order = list(g.registry.lock_rules["special_key_menu"]["order"])
    mask = A.action_mask(g)
    for key_id in ("secret_garden_key", "key_8"):
        idx = A.LOCK_SPECIAL_KEY_BASE + order.index(key_id)
        assert not mask[idx], f"{key_id} must stay masked off even when held"
        assert not g.can_use_special_key_at_lock(key_id)


def test_basement_key_never_fits_an_on_grid_door(registry):
    """Basement Key is held but never legal at an on-grid locked doorway:
    this sim models the Basement purely as an off-grid area-graph
    destination (no on-grid room is ever a "Basement door"), so fits() is
    correctly always False here -- see effects/items/basement_key.py."""
    g = _game(registry, starting_items=frozenset({"basement_key"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert special_items.has(g.state, "basement_key")
    assert not g.can_use_special_key_at_lock("basement_key")
    order = list(g.registry.lock_rules["special_key_menu"]["order"])
    idx = A.LOCK_SPECIAL_KEY_BASE + order.index("basement_key")
    assert not A.action_mask(g)[idx]


# ------------------------------------------------------------- Prism Key
#
# Wiki (blueprince.wiki.gg/wiki/Prism_Key): "the Prism Key can only be used
# to unlock a door in Bedrooms, Hallways, Green Rooms, Shops and Red Rooms,
# and will not fit locks in rooms that are purely blue or black"; using it
# colour-restricts the resulting draft; "the color is chosen at random from
# all valid choices" in a multi-colour room; "consumes it and readds it to
# the item pool, allowing it to be obtained again in the same day."

PRISM_TEST_CELL = 7  # rank 2, col 2: interior, doorway north targets cell 12
                      # (empty) -- the same safe placement geometry
                      # test_colour_drafting.py uses for the Secret Passage.


def _place_and_stand(g: Game, room_id: str, cell: int = PRISM_TEST_CELL,
                     orientation: int = N) -> None:
    """Place ``room_id`` at ``cell`` with a door in ``orientation`` and stand
    there, bypassing normal drafting/movement -- the same shape
    test_colour_drafting.py's own ``_place_secret_passage`` helper uses.

    Leaves ``state.keys`` at 0: this teleports the player onto an island
    disconnected from the day-start Entrance Hall, so it is the ONLY
    frontier doorway Game._action_in_budget can see. Game._frontier_lock_affordable
    recognizes a fitting held special key (Prism Key here) as its own route
    past a locked doorway, independent of regular keys, so the still-locked
    doorway does not end the day (_terminate("out_of_steps")) before the
    special-keys-menu row is ever reached -- every prism_key test here
    resolves the lock via that menu row, never a regular key."""
    room = g.registry.by_id[room_id]
    g._place_room(room, cell, orientation)
    g.state.pos = cell
    g.state.keys = 0


class _FixedChoiceRng:
    """Wraps a real engine.rng.Rng, overriding ``.choice`` for exactly one
    label to a fixed index -- every other draw (rarity rolls, mechanarium
    orientation, etc.) still comes from the real substream underneath, so
    the deal itself stays realistic. Used to force the Prism Key's
    multi-colour draw deterministically instead of hunting for a seed."""

    def __init__(self, real: Rng, label: str, index: int) -> None:
        self._real = real
        self._label = label
        self._index = index

    def __getattr__(self, name):
        return getattr(self._real, name)

    def choice(self, label, items):
        if label == self._label:
            return items[self._index]
        return self._real.choice(label, items)


def test_prism_key_masked_off_in_a_purely_blue_room(registry):
    """The Prism Key does not fit the Entrance Hall: category "blueprint"
    (this sim's blue category) with no extra colour categories -- wiki:
    "will not fit locks in rooms that are purely blue or black"."""
    entrance = registry.by_id["entrance_hall"]
    assert entrance.category == "blueprint" and not entrance.extra_categories, (
        "setup check: the Entrance Hall must be purely blue for this test to mean anything")
    g = _game(registry, starting_items=frozenset({"prism_key"}))
    cell, d = g.open_doorways()[0]  # day-start position is the Entrance Hall
    _force_state(g, cell, d, DOOR_LOCKED)
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert special_items.has(g.state, "prism_key")
    assert not g.can_use_special_key_at_lock("prism_key")
    order = list(g.registry.lock_rules["special_key_menu"]["order"])
    idx = A.LOCK_SPECIAL_KEY_BASE + order.index("prism_key")
    assert not A.action_mask(g)[idx]


@pytest.mark.parametrize("room_id,colour", [
    ("bedroom", "bedroom"),
    ("corridor", "hallway"),
    ("cloister", "green"),
    ("kitchen", "shop"),
    ("lavatory", "red"),
])
def test_prism_key_fits_and_deals_that_single_colour(registry, room_id, colour):
    """Prism Key is offered (fits) in a room of each of the five colours,
    and using it deals a hand restricted entirely to that colour -- checked
    against the room's own registry category (rooms.json data), independent
    of prism_key.fitting_colours/fits, the functions under test."""
    room = registry.by_id[room_id]
    assert room.category == colour and not room.extra_categories, (
        f"setup check: {room_id!r} must be a single-colour {colour!r} room")
    g = _game(registry, starting_items=frozenset({"prism_key"}))
    _place_and_stand(g, room_id)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_use_special_key_at_lock("prism_key")
    order = list(g.registry.lock_rules["special_key_menu"]["order"])
    idx = A.LOCK_SPECIAL_KEY_BASE + order.index("prism_key")
    assert A.action_mask(g)[idx]
    pending = g.use_special_key_at_lock("prism_key")
    assert g.phase is Phase.DRAFTING
    assert pending is not None and pending.options, (
        "a colour-restricted hand must still deal something")
    for opt in pending.options:
        dealt = g.registry.rooms[opt.room_idx]
        assert dealt.is_category(colour), f"{dealt.id!r} is not a {colour!r} room"


def test_prism_key_consumed_and_readded_to_the_pool(registry):
    """Using the Prism Key spends the held one but does NOT gate it from
    spawning again today -- remove(..., consumed=False) never appends to
    state.special.removed, the only list _is_available consults (wiki:
    "consumes it and readds it to the item pool, allowing it to be obtained
    again in the same day")."""
    g = _game(registry, starting_items=frozenset({"prism_key"}))
    _place_and_stand(g, "cloister")  # green, single colour
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.open_door(PRISM_TEST_CELL, N)
    assert special_items.has(g.state, "prism_key")
    g.use_special_key_at_lock("prism_key")
    assert not special_items.has(g.state, "prism_key"), "the held key is spent"
    assert "prism_key" not in g.state.special.removed, "must not be gone for the day"
    assert special_items._is_available(g.state, "prism_key", g.registry), (
        "must be spawn-eligible again the same day")


@pytest.mark.parametrize("index", [0, 2, 4])
def test_prism_key_multi_colour_room_draws_via_its_own_rng_label(registry, index):
    """The Aquarium carries all five colours (rooms.json's extra_categories),
    so using the Prism Key there draws one via a single rng.choice on the
    "prism_key_colour" label -- forcing three different indices and checking
    the resulting hand matches each proves the draw is actually consumed
    (not hardcoded to one entry)."""
    from blueprince_sim.engine.draft import COLOUR_CATEGORIES

    aquarium = registry.by_id["aquarium"]
    assert set(COLOUR_CATEGORIES) <= aquarium.categories, (
        "setup check: the Aquarium must carry every colour category")
    g = _game(registry, starting_items=frozenset({"prism_key"}))
    _place_and_stand(g, "aquarium")
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.open_door(PRISM_TEST_CELL, N)
    g.rng = _FixedChoiceRng(g.rng, "prism_key_colour", index)
    expected = COLOUR_CATEGORIES[index]
    pending = g.use_special_key_at_lock("prism_key")
    assert g.phase is Phase.DRAFTING
    assert pending is not None and pending.options
    for opt in pending.options:
        assert g.registry.rooms[opt.room_idx].is_category(expected), (
            f"index={index}: expected the {expected!r}-restricted draw")


# --------------------------------------- day-end affordability (_action_in_budget)
#
# Game._action_in_budget's locked-door line decides whether an openable
# locked doorway keeps the day alive. It must count everything the
# LOCK_PENDING menu itself would accept (regular keys via lock_open_cost,
# Master Key, a fitting Silver/Prism Key) -- not just raw keys against a
# hardcoded cost of 1 -- while still correctly ending the day when nothing
# can open the door at all (no open/abandon infinite loop; trying a locked
# frontier doorway is always free, see frontier_doorway_triable).


def _enter_lock_pending(g: Game, cell: int, d: int) -> None:
    """Test-only: park Phase.LOCK_PENDING on cell->d directly, bypassing
    open_door's own _check_termination call -- so a doorway's own
    openability can be probed via the LOCK_PENDING menu (can_use_key_at_lock
    etc.) independent of whether the day as a whole would end first."""
    g.state.pending_lock_cell = cell
    g.state.pending_lock_direction = d
    g.phase = Phase.LOCK_PENDING


def test_master_key_holder_at_zero_keys_keeps_the_day_alive(registry):
    """A Master Key holder with 0 regular keys does not have the day end
    early merely because a locked frontier doorway is the only thing left:
    _action_in_budget recognizes that the Master Key opens it for free by
    checking held items, not just ``st.keys``."""
    g = _game(registry, starting_items=frozenset({"master_key"}))
    _place_and_stand(g, "bedroom")
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    assert g.state.keys == 0
    assert g._action_in_budget(), "a Master Key holder can always open a locked door"
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.LOCK_PENDING, "the day must not have terminated early"


def test_search_surcharge_door_not_affordable_with_too_few_keys(registry):
    """A locked frontier door carrying a 2-key search surcharge
    (lock_open_cost == 3) is NOT counted as affordable with only 2 regular
    keys: _action_in_budget calls lock_open_cost rather than assuming a
    door's base cost of 1, so a search-surcharged door is priced at its
    true, higher cost."""
    g = _game(registry)
    _place_and_stand(g, "bedroom")
    g.state.keys = 2
    seg = segment_key(PRISM_TEST_CELL, N)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.door_search_cost[seg] = 2  # lock_open_cost == 1 (base) + 2 == 3
    assert g.lock_open_cost(PRISM_TEST_CELL, N) == 3
    assert not g._action_in_budget(), "2 keys must not be counted as enough for a 3-key door"
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.TERMINAL, "no other purposeful action exists: the day must end"
    assert g.termination_reason == "out_of_steps"


def test_stopwatch_refund_keeps_the_day_alive_with_one_key_at_a_surcharged_door(registry):
    """An active Stopwatch refunds a locked frontier door's spend down to a
    single key, even under a search surcharge that would otherwise need
    more (can_use_key_at_lock's own refund rule, mirrored here): 1 key plus
    an active Stopwatch is enough for a 3-key door, so the day does not end
    early."""
    g = _game(registry)
    _place_and_stand(g, "bedroom")
    g.state.keys = 1
    g.state.special.stopwatch_left = 1
    seg = segment_key(PRISM_TEST_CELL, N)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.door_search_cost[seg] = 2  # lock_open_cost == 3 without the refund
    assert g.lock_open_cost(PRISM_TEST_CELL, N) == 3
    assert g._action_in_budget(), "1 key + an active Stopwatch must be enough"
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.LOCK_PENDING, "the day must not have terminated early"


def test_stopwatch_refund_still_needs_at_least_one_key(registry):
    """The Stopwatch refunds the SPEND, not the requirement to hold a key at
    all: 0 keys still ends the day even with an active Stopwatch (wiki:
    "At least one key is still required for the option to use a key to
    appear, even though it isn't spent")."""
    g = _game(registry)
    _place_and_stand(g, "bedroom")
    g.state.keys = 0
    g.state.special.stopwatch_left = 1
    seg = segment_key(PRISM_TEST_CELL, N)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.door_search_cost[seg] = 2
    assert not g._action_in_budget(), "0 keys must not be affordable even with a Stopwatch"
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.TERMINAL, "0 keys, no other action: the day must end"
    assert g.termination_reason == "out_of_steps"


def test_unopenable_locked_door_still_ends_the_day(registry):
    """A locked frontier door that genuinely cannot be opened -- no keys, no
    items -- still ends the day. This is the guard that matters: if
    _frontier_lock_affordable became unconditionally True, the day would
    never end (open the door -> abandon -> it's still the only option ->
    open again, forever), since trying a locked frontier doorway costs
    nothing and abandon_lock always returns to NAVIGATE."""
    g = _game(registry)
    _place_and_stand(g, "bedroom")
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    assert g.state.keys == 0
    assert not g._action_in_budget()
    g.open_door(PRISM_TEST_CELL, N)
    assert g.phase is Phase.TERMINAL, "nothing can open this door: the day must end"
    assert g.termination_reason == "out_of_steps"
    assert not g.can_abandon_lock(), "the day is over: no menu to loop through"


@pytest.mark.parametrize("items,keys,search_extra,stopwatch", [
    (frozenset(), 1, 0, 0),                     # exactly enough: base cost 1
    (frozenset(), 0, 0, 0),                     # not enough: 0 keys, cost 1
    (frozenset(), 3, 2, 0),                     # exactly enough: cost 1+2 surcharge
    (frozenset(), 2, 2, 0),                     # not enough: 2 keys, cost 3
    (frozenset({"master_key"}), 0, 0, 0),       # free regardless of keys
    (frozenset({"silver_key"}), 0, 0, 0),       # fits any standard locked door
    (frozenset({"prism_key"}), 0, 0, 0),        # fits: bedroom is a colour room
    (frozenset({"basement_key"}), 0, 0, 0),     # never fits an on-grid door
    (frozenset(), 1, 2, 1),                     # Stopwatch refund: 1 key enough for a 3-key door
    (frozenset(), 0, 2, 1),                     # Stopwatch refund still needs >=1 key
])
def test_frontier_lock_affordability_agrees_with_the_lock_pending_menu(
        registry, items, keys, search_extra, stopwatch):
    """Regression guard: Game._frontier_lock_affordable must agree with what
    the LOCK_PENDING menu itself would actually accept (can_use_key_at_lock
    -- including its Stopwatch refund -- can_open_locked_free,
    can_use_special_key_at_lock for master/silver/prism), across
    regular-key, surcharge, Stopwatch, and special-item scenarios -- so a
    fourth copy of this door-legality rule drifting from the other three
    (the action mask, draft_from, and this one) is caught by a test instead
    of discovered later, per #246's own unification of the first two. The
    Lock Pick Kit is deliberately excluded from both sides: it is a
    probabilistic menu row (can_lockpick_at_lock), not a deterministic
    affordability guarantee, and _frontier_lock_affordable is conservative
    about it on purpose (see its own docstring)."""
    g = _game(registry, starting_items=items)
    _place_and_stand(g, "bedroom")
    g.state.keys = keys
    g.state.special.stopwatch_left = stopwatch
    seg = segment_key(PRISM_TEST_CELL, N)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    if search_extra:
        g.door_search_cost[seg] = search_extra
    path_key_cost = g.key_cost_map()[PRISM_TEST_CELL]
    predicted = g._frontier_lock_affordable(PRISM_TEST_CELL, N, path_key_cost)

    _enter_lock_pending(g, PRISM_TEST_CELL, N)
    actual = (g.can_use_key_at_lock()
              or special_items.can_open_locked_free(g)
              or any(g.can_use_special_key_at_lock(k)
                     for k in ("master_key", "silver_key", "prism_key")))
    assert predicted == actual, (items, keys, search_extra, stopwatch)


# ------------------------------------------------------- keycard system


def test_security_openable_truth_table():
    """The security-door truth table: powered readers need the keycard, and
    unpowered doors follow the offline mode (Unlocked passes, Locked seals)."""
    st = GameState()
    for power, card, offline, expect in [
        (True, True, False, True),    # powered + card
        (True, False, True, False),   # powered, no card: offline mode moot
        (False, True, False, False),  # unpowered + default Locked: nobody passes
        (False, False, True, True),   # unpowered + offline Unlocked: free
        (False, True, True, True),
        (True, False, False, False),
    ]:
        st.keycard_power_on = power
        st.has_keycard = card
        st.offline_unlocked = offline
        assert locks.security_openable(st) is expect, (power, card, offline)


def test_entering_security_assumes_offline_unlocked(registry):
    """Entering the Security room flips the offline mode to Unlocked, so a
    later power cut opens the security doors instead of sealing them."""
    g = _game(registry)
    sec = registry.by_id["security"]
    g._place_room(sec, 7, sec.door_mask)
    _force_state(g, 2, N, DOOR_OPEN)
    assert not g.state.offline_unlocked
    g.move(N)
    assert g.state.offline_unlocked


def test_switch_actions_require_standing_in_the_room(registry):
    """The breaker toggle works only inside the Utility Closet and the
    security-level dial only inside Security - never from elsewhere."""
    g = _game(registry)
    uc = registry.by_id["utility_closet"]
    sec = registry.by_id["security"]
    with pytest.raises(AssertionError):
        g.set_keycard_power(False)
    with pytest.raises(AssertionError):
        g.set_security_level("high")
    g._place_room(uc, 7, S)
    g._place_room(sec, 3, sec.door_mask)
    _force_state(g, 2, N, DOOR_OPEN)
    _force_state(g, 2, E, DOOR_OPEN)
    g.move(N)  # into the Utility Closet
    assert g.can_toggle_keycard_power() and not g.can_set_security_level()
    g.set_keycard_power(False)
    assert not g.state.keycard_power_on
    g.move(S)
    g.move(E)  # into Security
    assert g.can_set_security_level() and not g.can_toggle_keycard_power()
    g.set_security_level("high")
    assert g.state.security_level == "high"


# ------------------------------------------------------- security spawning


def test_security_spawn_needs_whitelist_and_distance(registry):
    """Security doors spawn only on whitelisted rooms and only within the
    Antechamber distance cutoff (rank-1 doors are too far)."""
    rules = registry.lock_rules
    st = GameState()
    plain = registry.by_id["closet"]  # not on the whitelist
    sec_room = registry.by_id["security"]
    hits = 0
    for seed in range(200):
        assert not locks._roll_security(st, rules, plain, 41, E, Rng(seed))
        # Rank-1 doors sit far from the Antechamber: over the distance cutoff.
        assert not locks._roll_security(st, rules, sec_room, 2, E, Rng(seed))
        # Rank-9 doors of a whitelisted room are close and frequently spawn.
        if locks._roll_security(st, rules, sec_room, 41, E, Rng(seed)):
            hits += 1
        st.security_doors_spawned = 0
    assert hits > 30


def test_security_spawn_respects_daily_cap_and_level(registry):
    """Security-door spawns stop at the per-level daily cap; raising the
    security level mid-day restores headroom (the cap is checked per roll)."""
    rules = registry.lock_rules
    sec_room = registry.by_id["security"]
    st = GameState()
    st.security_level = "low"
    st.security_doors_spawned = rules["security"]["spawn_limit"]["low"]
    for seed in range(100):
        assert not locks._roll_security(st, rules, sec_room, 41, E, Rng(seed))
    # Raising the level mid-day re-opens headroom (cap checked at roll time).
    st.security_level = "high"
    assert any(locks._roll_security(st, rules, sec_room, 41, E, Rng(seed))
               for seed in range(100))


def test_high_security_forces_the_door_probability(registry):
    """High security forces a whitelisted room's door chance to 100%, so its
    spawn rate jumps sharply versus normal."""
    # Passageway's low chance is forced to 100% on high: the only remaining
    # gate is the distance roll, so spawn rates jump sharply.
    rules = registry.lock_rules
    room = registry.by_id["passageway"]

    def rate(level: str) -> int:
        n = 0
        for seed in range(300):
            st = GameState()
            st.security_level = level
            n += locks._roll_security(st, rules, room, 41, E, Rng(seed))
        return n

    low, high = rate("normal"), rate("high")
    assert high > low * 2


def test_keycard_can_be_found_in_source_rooms(registry):
    """Entering a keycard-source room (the Office) yields the keycard by
    chance: some days it is found, most days not."""
    found = 0
    for seed in range(40):
        g = Game(GameConfig(), seed=seed, registry=registry)
        office = registry.by_id["office"]
        g._place_room(office, 7, office.door_mask)
        _force_state(g, 2, N, DOOR_OPEN)
        g.move(N)
        found += g.state.has_keycard
    assert 0 < found < 40  # found by chance: some days yes, most no


# ------------------------------------------------------------- env plumbing


def test_mask_seals_and_reopens_security_doorways(registry):
    """The action mask hides drafting through a sealed security doorway and
    re-legalizes it once the keycard is in hand."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_SECURITY)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    assert not A.action_mask(g)[idx]
    g.state.has_keycard = True
    g.state.door_version += 1
    assert A.action_mask(g)[idx]


def test_mask_locked_doorway_needs_a_real_menu_choice(registry):
    """A locked doorway is only offered in the action mask's OPEN range when
    its menu would offer something besides abandon: masked out at 0 keys
    (no key, no lockpick, no fitting special key), reinstated once a key is
    held. Once triable, trying still costs nothing (Phase.LOCK_PENDING);
    only the use-a-key row inside that menu is additionally gated on
    holding a key, via Game.can_use_key_at_lock.
    """
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    g.state.keys = 0
    assert not A.action_mask(g)[idx], "no key, no lockpick, no special key: nothing but abandon"

    g.state.keys = 1
    assert A.action_mask(g)[idx], "a key makes the menu offer a real choice"
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_use_key_at_lock(), "1 key: use-a-key must be legal"
    g.abandon_lock()

    g.state.keys = 0
    assert not A.action_mask(g)[idx], "back to zero keys: masked off again"


# --------------------------------------------------- lock-menu real-choice gate
#
# Game.lock_menu_has_real_choice/frontier_doorway_triable: a DOOR_LOCKED
# frontier doorway is only triable when its menu would offer something
# besides abandon (a regular key, a lockpick tool, or a fitting special
# key) -- grid_locked is already on the observation, so opening a menu
# whose sole option is to back out cannot accomplish anything.


def test_locked_doorway_with_no_way_to_open_it_is_not_triable(registry):
    """A locked doorway with no key, no lockpick, and no fitting special key
    held is not triable, and its OPEN id is absent from the action mask."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    assert not g.frontier_doorway_triable(cell, d)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    assert not A.action_mask(g)[idx]


def test_one_key_makes_the_doorway_triable_again(registry):
    """Holding enough keys for the door's own lock_open_cost makes a
    previously untriable locked doorway triable again, and reinstates its
    OPEN id in the action mask."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    g.state.keys = 0
    assert not A.action_mask(g)[idx]

    g.state.keys = 1
    assert g.frontier_doorway_triable(cell, d)
    assert A.action_mask(g)[idx]


def test_stopwatch_refund_makes_a_surcharged_door_triable_with_one_key(registry):
    """An active Stopwatch refunds a search-surcharged door's spend to just
    1 key (the same rule can_use_key_at_lock applies): 1 key alone does not
    cover a 3-key lock_open_cost, but 1 key plus the Stopwatch does."""
    g = _game(registry)
    _place_and_stand(g, "bedroom")
    seg = segment_key(PRISM_TEST_CELL, N)
    _force_state(g, PRISM_TEST_CELL, N, DOOR_LOCKED)
    g.door_search_cost[seg] = 2  # lock_open_cost == 1 (base) + 2 == 3
    g.state.keys = 1
    assert g.lock_open_cost(PRISM_TEST_CELL, N) == 3
    assert not g.frontier_doorway_triable(PRISM_TEST_CELL, N), "1 key alone can't cover cost 3"

    g.state.special.stopwatch_left = 1
    assert g.frontier_doorway_triable(PRISM_TEST_CELL, N), "Stopwatch refund: 1 key is enough"


def test_lockpick_alone_makes_the_doorway_triable_with_zero_keys(registry):
    """Holding a Lock Pick Kit, with zero keys and no fitting special key, is
    by itself enough to make a locked doorway triable -- the lockpick term of
    lock_menu_has_real_choice; without the kit the same doorway is not
    triable, isolating the kit as what makes the difference."""
    for items, expect in ((frozenset(), False), (frozenset({"lock_pick_kit"}), True)):
        g = _game(registry, starting_items=items)
        cell, d = g.open_doorways()[0]
        _force_state(g, cell, d, DOOR_LOCKED)
        g.state.keys = 0
        assert g.frontier_doorway_triable(cell, d) == expect, items
        idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
        assert A.action_mask(g)[idx] == expect, items


def test_special_key_alone_makes_the_doorway_triable(registry):
    """Holding a fitting special key (Master Key), with zero keys and no
    lockpick, is by itself enough to make a locked doorway triable -- the
    special-key term of lock_menu_has_real_choice; without it the same
    doorway is not triable, isolating the key as what makes the difference."""
    for items, expect in ((frozenset(), False), (frozenset({"master_key"}), True)):
        g = _game(registry, starting_items=items)
        cell, d = g.open_doorways()[0]
        _force_state(g, cell, d, DOOR_LOCKED)
        g.state.keys = 0
        assert g.frontier_doorway_triable(cell, d) == expect, items
        idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
        assert A.action_mask(g)[idx] == expect, items


def test_reserved_special_key_alone_does_not_make_it_triable(registry):
    """A reserved special-keys-menu id (secret_garden_key) held with nothing
    else does not make the doorway triable -- it never counts as a real
    choice, matching its permanently-masked-off menu row."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.inventory["secret_garden_key"] = 1  # force-held, bypassing spawn gating
    g.state.keys = 0
    assert not g.frontier_doorway_triable(cell, d)


def test_key_wrapper_agrees_with_lock_menu_has_real_choice(registry):
    """With no lockpick and no fitting special key held, lock_menu_has_real_choice
    reduces to the key term alone, so it must exactly track
    can_use_key_at_lock() at the pending doorway -- proof the refactor kept
    the LOCK_PENDING wrapper and the pure mask-time query in lockstep."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    for keys in (0, 1):
        g.state.keys = keys
        g.open_door(cell, d)
        assert g.can_use_key_at_lock() == g.lock_menu_has_real_choice(cell, d)
        g.abandon_lock()


def test_lockpick_wrapper_agrees_with_lock_menu_has_real_choice(registry):
    """With 0 keys and no fitting special key, lock_menu_has_real_choice
    reduces to the lockpick term alone, so it must exactly track
    can_lockpick_at_lock() at the pending doorway."""
    g = _game(registry, starting_items=frozenset({"lock_pick_kit"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_lockpick_at_lock() == g.lock_menu_has_real_choice(cell, d)


def test_open_doorway_triability_unaffected_by_the_new_gate(registry):
    """An ordinary DOOR_OPEN frontier doorway stays triable regardless of
    keys or items held -- the real-choice gate only applies to DOOR_LOCKED
    segments."""
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    assert g.door_state_of(cell, d) == DOOR_OPEN
    g.state.keys = 0
    assert g.frontier_doorway_triable(cell, d)
    idx = A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]
    assert A.action_mask(g)[idx]


def test_mask_accounts_for_the_walks_keys_but_the_door_itself_is_free_to_try(registry):
    """The mask still budgets keys for the WALK (crossing a locked interior
    door to reach the doorway) via key_cost_map; trying the frontier
    doorway itself, once there, is free regardless of whether a key is
    spent on it. But if the walk would spend the player's only key getting
    there, leaving nothing and no other way to open the door, draft_from now
    declines the trip rather than walking into a menu with nothing but
    abandon (Game.lock_menu_has_real_choice).
    """
    straight = next(r for r in registry.rooms
                    if r.layout == "straight" and r.rarity is not None)
    idx = A.OPEN_BASE + 7 * 4 + A.DIR_INDEX[N]

    g0 = _game(registry)
    g0._place_room(straight, 7, N | S)
    _force_state(g0, 2, N, DOOR_LOCKED)
    _force_state(g0, 7, N, DOOR_LOCKED)
    g0.state.keys = 0
    assert not A.action_mask(g0)[idx], "0 keys: can't even afford the walk there"

    g1 = _game(registry)
    g1._place_room(straight, 7, N | S)
    _force_state(g1, 2, N, DOOR_LOCKED)
    _force_state(g1, 7, N, DOOR_LOCKED)
    g1.state.keys = 1
    assert A.action_mask(g1)[idx], "the menu looks live before the walk spends the only key"
    g1.draft_from(7, N)
    assert g1.state.keys == 0, "the walk still spent the interior door's key"
    assert g1.phase is Phase.NAVIGATE, "nothing left for the door: draft_from declines the trip"
    assert g1.door_state_of(7, N) == DOOR_LOCKED, "the frontier door itself was never tried"

    g2 = _game(registry)
    g2._place_room(straight, 7, N | S)
    _force_state(g2, 2, N, DOOR_LOCKED)
    _force_state(g2, 7, N, DOOR_LOCKED)
    g2.state.keys = 2
    g2.draft_from(7, N)
    assert g2.state.keys == 1, "the walk spent one key, one left for the door"
    assert g2.phase is Phase.LOCK_PENDING
    assert g2.can_use_key_at_lock()


def test_mask_allows_revisiting_control_rooms(registry):
    """Control rooms (Utility Closet / Security) stay revisitable after entry
    so their switches can be worked mid-day, and the switch actions are
    exposed only while standing inside the right room."""
    g = _game(registry)
    uc = registry.by_id["utility_closet"]
    g._place_room(uc, 7, S)
    _force_state(g, 2, N, DOOR_OPEN)
    g.move(N)
    g.move(S)  # back in the entrance; the closet is entered
    g.state.offline_unlocked = True  # a power cut would now open doors
    mask = A.action_mask(g)
    assert mask[A.MOVE_TO_BASE + 7]
    # Standing inside, the breaker toggle itself is exposed.
    g.move(N)
    mask = A.action_mask(g)
    assert mask[A.TOGGLE_POWER_ACTION]
    lvl = [mask[A.SET_LEVEL_BASE + i] for i in range(3)]
    assert lvl == [False, False, False]  # not standing in Security


def test_obs_planes_mark_both_sides_of_a_segment(registry):
    """The locked-door obs plane marks both cells of a locked segment (each
    side sees the shared door), and house_flags reports keycard power on."""
    from blueprince_sim.env import obs as O

    g = _game(registry)
    _force_state(g, 2, N, DOOR_LOCKED)
    enc = O.encode(g)
    flat_locked = enc["grid_locked"].reshape(-1)
    assert flat_locked[2] & N
    assert flat_locked[7] & S
    assert enc["house_flags"][9] == 1  # keycard power starts on


def test_grid_search_cost_plane_reports_extra_keys_on_both_sides(registry):
    """grid_search_cost encodes the extra keys (beyond the base 1) a
    currently-locked segment costs, painted on both cells like grid_locked;
    0 for a plain lock with no surcharge, and 0 again once the segment
    opens (an opened segment's own extra-key cost stops mattering, even
    though Game.door_search_cost's entry is never cleared)."""
    from blueprince_sim.env import obs as O

    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    nb = neighbor(cell, d)

    flat = O.encode(g)["grid_search_cost"].reshape(-1)
    assert flat[cell] == 0 and flat[nb] == 0, "a plain lock carries no search surcharge"

    g.door_search_cost[segment_key(cell, d)] = 2
    flat2 = O.encode(g)["grid_search_cost"].reshape(-1)
    assert flat2[cell] == 2 and flat2[nb] == 2, "both sides of the segment report the surcharge"

    g._open_segment(cell, d)
    flat3 = O.encode(g)["grid_search_cost"].reshape(-1)
    assert flat3[cell] == 0 and flat3[nb] == 0, "an opened segment's surcharge no longer applies"


def test_determinism_with_locks(registry):
    """Day-start lock rolls (door states, bias, security spawn count) are
    deterministic given a seed."""
    def transcript(seed: int) -> tuple:
        g = Game(GameConfig(), seed=seed, registry=registry)
        return (tuple(sorted(g.state.door_state.items())), g.state.lock_bias,
                g.state.security_doors_spawned)

    for seed in range(10):
        assert transcript(seed) == transcript(seed)


def test_all_placed_rooms_stay_reachable_without_keys(registry):
    """Drafting opens the doorway it goes through and in-drafting opens
    facing pairs, so the whole placed house (minus a still-unconnected
    Antechamber) is walkable with zero keys."""
    import random

    from blueprince_sim.cli.policies import POLICIES

    for seed in range(5):
        g = Game(GameConfig(), seed=seed, registry=registry)
        rnd = random.Random(seed)
        for _ in range(120):
            if g.phase is Phase.TERMINAL:
                break
            POLICIES["frontier_greedy"](g, rnd)
        if g.phase is Phase.TERMINAL:
            continue
        g.state.keys = 0
        dist = g.distance_map()
        for cell, idx in enumerate(g.state.grid):
            if idx >= 0 and cell != ANTECHAMBER_CELL:
                assert dist[cell] >= 0, f"seed {seed}: cell {cell} unreachable"


def test_special_key_menu_count_matches_the_pinned_action_space_width(registry):
    """_build_lock_special_key_order's own length agrees with the pinned
    _N_LOCK_SPECIAL_KEYS (the action space's own LOCK_SPECIAL_KEY_BASE..
    REWIND_ACTION width).

    A row added to or removed from data/locks.json's special_key_menu.order
    without a matching bump to _N_LOCK_SPECIAL_KEYS would desync the two; the
    mask-building loop that walks this tuple has no bounds check, so an extra
    row would silently write past the reserved block into REWIND_ACTION's
    mask bit -- the same corruption class discovered in the Axe block (PR
    #329, _N_AXE_TARGETS pinned at 48 while a 49th axe-eligible room silently
    overflowed into LOCK_MENU_BASE). _build_lock_special_key_order's own
    assertion is the primary guard; this test pins it as an explicit,
    discoverable invariant the way test_constellations.py does for
    _N_CONSTELLATIONS."""
    assert len(A._build_lock_special_key_order(registry)) == A._N_LOCK_SPECIAL_KEYS == 6


# ------------------------------------------- the per-doorway abandon limit


def test_a_doorway_stops_being_offered_after_three_abandons(registry):
    """A locked doorway may be declined LOCK_ABANDON_LIMIT times in a day;
    after that it is no longer triable, so the mask stops offering it.

    Trying a locked door and abandoning both cost zero game steps, so the pair
    is a loop the step budget cannot terminate -- measured at up to 493 probes
    of a single doorway in one episode before this bound existed. Declining and
    returning after checking other doors stays expressible; only the unbounded
    case is refused.

    Holds a Lock Pick Kit throughout so the doorway's menu always offers a
    real choice regardless of the (zero) key count: the abandon tally, not
    Game.lock_menu_has_real_choice, is what this test isolates.
    """
    g = _game(registry, starting_items=frozenset({"lock_pick_kit"}))
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    seg = segment_key(cell, d)

    for i in range(locks.LOCK_ABANDON_LIMIT):
        assert g.frontier_doorway_triable(cell, d), (
            f"doorway must still be triable on abandon {i} of "
            f"{locks.LOCK_ABANDON_LIMIT}"
        )
        g.open_door(cell, d)
        assert g.phase is Phase.LOCK_PENDING
        g.abandon_lock()
        assert g.state.lock_abandons[seg] == (i + 1, 0)

    assert not g.frontier_doorway_triable(cell, d), (
        "the doorway must stop being triable once the limit is reached"
    )
    assert not A.action_mask(g)[A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]], (
        "the mask must stop offering a doorway that is no longer triable"
    )


def test_the_abandon_limit_is_counted_per_doorway_not_per_day(registry):
    """Exhausting one doorway's abandons leaves every other doorway offered.

    The tally is keyed by segment, so a player who declines one locked door
    three times has spent nothing at any other door -- which is what makes
    "check the other doors first" still work after the bound applies.

    Holds a Lock Pick Kit throughout so both doorways' menus always offer a
    real choice regardless of the (zero) key count: the per-segment tally,
    not Game.lock_menu_has_real_choice, is what this test isolates.
    """
    g = _game(registry, starting_items=frozenset({"lock_pick_kit"}))
    doors = g.open_doorways()
    assert len(doors) >= 2, "setup: need two doorways to tell per-door from per-day"
    (cell_a, d_a), (cell_b, d_b) = doors[0], doors[1]
    _force_state(g, cell_a, d_a, DOOR_LOCKED)
    _force_state(g, cell_b, d_b, DOOR_LOCKED)
    g.state.keys = 0

    for _ in range(locks.LOCK_ABANDON_LIMIT):
        g.open_door(cell_a, d_a)
        g.abandon_lock()

    assert not g.frontier_doorway_triable(cell_a, d_a)
    assert g.frontier_doorway_triable(cell_b, d_b), (
        "a different doorway must be unaffected by the first one's tally"
    )
    assert segment_key(cell_b, d_b) not in g.state.lock_abandons


def test_abandon_stays_legal_inside_the_menu_at_the_limit(registry):
    """The bound refuses re-ENTRY to the menu, never the exit from it.

    LOCK_PENDING must always offer at least one legal action or the phase is a
    dead end, so a player already at the menu on their limit-reaching abandon
    can still leave it.
    """
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    seg = segment_key(cell, d)
    g.state.lock_abandons[seg] = (locks.LOCK_ABANDON_LIMIT - 1, 0)

    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_abandon_lock(), "abandon must remain legal at the limit"
    assert any(A.action_mask(g)), "LOCK_PENDING must never be a dead end"
    g.abandon_lock()
    assert g.state.lock_abandons[seg] == (locks.LOCK_ABANDON_LIMIT, 0)


def test_spending_a_key_is_unaffected_by_the_abandon_tally(registry):
    """The tally bounds free retries, not opening the door.

    A doorway at its abandon limit is no longer offered, but nothing about the
    limit touches key spending: reaching the menu by any route still opens the
    door for one key, so the bound can never strand a door a player can pay for
    while they are standing at it.
    """
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    seg = segment_key(cell, d)
    g.state.keys = 1
    g.state.lock_abandons[seg] = (locks.LOCK_ABANDON_LIMIT - 1, 1)

    g.open_door(cell, d)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_use_key_at_lock()
    g.use_key_at_lock()
    assert g.door_state_of(cell, d) == DOOR_OPEN
    assert g.state.keys == 0
    assert g.state.lock_abandons[seg] == (locks.LOCK_ABANDON_LIMIT - 1, 1), (
        "opening the door must not consume an abandon"
    )


def test_finding_a_key_makes_an_exhausted_doorway_triable_again(registry):
    """Holding more keys than at the last abandon lifts the bound outright.

    The earlier refusals answered "open this for a key I do not have"; a key
    found since then makes that a different question, so the doorway is offered
    again with a fresh tally. Without this the bound would strand a door the
    player can now afford, for the rest of the day.
    """
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    seg = segment_key(cell, d)

    for _ in range(locks.LOCK_ABANDON_LIMIT):
        g.open_door(cell, d)
        g.abandon_lock()
    assert not g.frontier_doorway_triable(cell, d), "setup: the bound must have applied"

    g.state.keys = 1  # a key turns up elsewhere in the house
    assert g.frontier_doorway_triable(cell, d), (
        "a key found since the last abandon must re-offer the doorway"
    )
    assert A.action_mask(g)[A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]], (
        "the mask must offer it again too -- a reset the mask cannot see is no reset"
    )

    # And the fresh tally is a full one, not a single grudging retry.
    g.open_door(cell, d)
    g.abandon_lock()
    assert g.state.lock_abandons[seg] == (1, 1)
    assert g.frontier_doorway_triable(cell, d)


def test_the_key_reset_does_not_repeat_without_another_key(registry):
    """One key buys one fresh tally, not unlimited retries at that key count.

    Otherwise the bound would be trivially defeated by picking up a single key:
    the comparison is against the keys held at the LAST abandon, which the
    abandon itself updates, so standing still re-exhausts the tally.
    """
    g = _game(registry)
    cell, d = g.open_doorways()[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    g.state.keys = 0
    for _ in range(locks.LOCK_ABANDON_LIMIT):
        g.open_door(cell, d)
        g.abandon_lock()

    g.state.keys = 1
    for _ in range(locks.LOCK_ABANDON_LIMIT):
        assert g.frontier_doorway_triable(cell, d)
        g.open_door(cell, d)
        g.abandon_lock()

    assert not g.frontier_doorway_triable(cell, d), (
        "the tally must re-exhaust at the same key count"
    )
