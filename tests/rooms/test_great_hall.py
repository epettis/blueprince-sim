"""Great Hall: the east Antechamber segment lever and its key cost, plus its
own "7 Locked Doors" guaranteed locks on the room's non-entry doorways.

See tests/test_antechamber_levers.py for the cross-cutting lever-gate
invariants.

The Great Hall is the only lever room whose pull costs a key, so its cost is
charged to the walk itself (key_cost_map, the action mask's key budget, and
end-to-end masked play all agree with what move_to actually deducts) rather
than just to the door being opened.

The two feature areas are independent: the lever tests below place the room
with plain :meth:`Game._place_room` (no ``entry_dir``), which -- per
locks.roll_segment -- skips the search-cost roll entirely, so those tests are
unaffected by the guaranteed-lock feature. The guaranteed-lock tests instead
use :func:`_draft_place`, which pre-opens the entry segment the way
:meth:`Game.choose` does before drafting, so ``entry_dir`` is meaningful and
the far-vs-side split actually applies.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.engine.placement import legal_orientations
from blueprince_sim.engine.state import GameState
from blueprince_sim.env import actions as A


def _game(*, levers: bool = True, keys: int = 0, seed: int = 1, registry=None, **extra) -> Game:
    """Fresh game with antechamber_levers set to ``levers``."""
    cfg = GameConfig(antechamber_levers=levers, **extra)
    g = Game(cfg, seed=seed, **({"registry": registry} if registry is not None else {}))
    g.state.keys = keys
    return g


def _draft_place(g: Game, room_id: str, cell: int, mask: int, entry_dir: int) -> None:
    """Place a room as though freshly drafted through ``entry_dir``.

    Pre-opens the entry segment first, mirroring what Game.choose does before
    _place_room ever runs (open_door's _unlock_for_passage sets it DOOR_OPEN
    at draft time) -- so locks.roll_segment sees the same precondition it
    would in a real draft: the entry segment already resolved, only the other
    (up to 3) fresh segments left to roll.
    """
    room = g.registry.by_id[room_id]
    g.state.door_state[segment_key(cell, entry_dir)] = DOOR_OPEN
    g.state.door_version += 1
    g._place_room(room, cell, mask, entry_dir=entry_dir)


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


# ------------------------------------------------------- Spare Great Hall layout


def test_spare_great_hall_drafts_on_a_wing_cell(registry, cfg):
    """Unlike the base Great Hall (a 4-way, barred from every edge by the
    outer-wall invariant), the Spare Great Hall is a straight room per the
    wiki -- it does not inherit the Great Hall's shape -- so it can be
    drafted on a wing cell when entered vertically."""
    st = GameState()
    spare = registry.by_id["spare_great_hall__ix139"]
    # Cell 20: rank 5, west wing (col 0). Entering north, the back door (S)
    # and the straight room's other end (N) both stay off the outer wall.
    assert legal_orientations(spare, 20, N, st, cfg) == [N | S]
    hall = registry.by_id["great_hall"]
    assert legal_orientations(hall, 20, N, st, cfg) == []  # 4-way: still barred


def test_great_hall_opens_east_costs_key(registry):
    """Entering the Great Hall with a key opens the east Antechamber segment
    (43, W) and consumes exactly one key."""
    g = _game(levers=True, keys=3, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_OPEN
    assert g.state.keys == 2  # one key spent
    # South and West remain sealed
    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, W) == DOOR_SEALED


def test_great_hall_no_key_stays_sealed(registry):
    """Entering the Great Hall with zero keys does not open the east segment:
    the lever requires a key to access and cannot be pulled without one."""
    g = _game(levers=True, keys=0, registry=registry)
    _place_at(g, "great_hall", 43, E | W)
    _enter_at(g, 43)

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED
    assert g.state.keys == 0  # no key spent


def test_walking_into_the_great_hall_is_charged_to_the_route(registry):
    """key_cost_map() prices in the Great Hall's on-arrival lever key spend
    before the caller ever walks - and move_to actually deducts exactly that
    many keys - so a caller budgeting off key_cost_map is never surprised."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    # Force the entrance -> Great Hall segment open so the only key spend on
    # this walk is the lever, not a locked door on the way in.
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    # Setup assertion: the lever has not been pulled yet, so the test can't
    # silently stop testing anything.
    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED

    assert g.key_cost_map()[7] == 1  # the route to the Great Hall spends the lever key

    g.move_to(7)
    assert g.state.keys == 0  # the map matched what the walk actually spent


def test_the_nav_cache_notices_a_lever_room_that_has_already_been_entered(registry):
    """The nav memo must key on state.entered: an already-entered Great Hall
    charges nothing, because its lever only ever fires on first entry, and a
    map cached from before that entry would over-charge the route and could
    strand the player behind a road it wrongly reads as unaffordable."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    g.state.door_version += 1
    g.state.keys = 1

    assert g.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled
    assert g.key_cost_map()[7] == 1  # unentered: walking in will pull the lever

    # Entry is the only thing that changes here, and the lever cannot fire twice.
    g.state.entered[7] = True
    assert g.key_cost_map()[7] == 0


def _hall_with_locked_east(keys: int, registry) -> Game:
    """Fresh game with the Great Hall placed at cell 7 (antechamber_levers
    on), its east doorway force-locked, and ``keys`` in hand."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=True), seed=1, registry=registry)
    hall = registry.by_id["great_hall"]
    g._place_room(hall, 7, hall.door_mask)
    g.state.door_state[segment_key(2, N)] = DOOR_OPEN
    # Lock one of the Great Hall's own frontier doorways.
    g.state.door_state[segment_key(7, E)] = DOOR_LOCKED
    g.state.door_version += 1
    g.state.keys = keys
    return g


def test_lock_pending_never_lets_the_lever_key_pay_for_the_door_too(registry):
    """A locked frontier doorway past the Great Hall needs two keys: one the
    walk itself spends pulling the lever, one for the door. Trying the door
    is legal as soon as the WALK there is affordable (trying itself is
    free), but the use-a-key row inside the menu must not let the lever's
    own spend double as the door's key too.

    Two separate games (rather than one game re-used across both key counts)
    because the walk must actually happen and spend the lever key before the
    use-a-key row is checked -- see
    test_unaffordable_search_cost_blocks_use_key_not_the_try for the matching
    setup on the side-doorway case.
    """
    action = A.OPEN_BASE + 7 * 4 + A.DIR_INDEX[E]

    g1 = _hall_with_locked_east(1, registry)
    assert g1.door_state_of(ANTECHAMBER_CELL, E) == DOOR_SEALED  # setup: lever unpulled
    assert g1.key_cost_map()[7] == 1, "setup: walking into the Hall drains 1 key (the lever)"
    assert A.action_mask(g1)[action], "trying is free once the walk (lever pull) is affordable"
    g1.draft_from(7, E)
    assert g1.state.keys == 0, "the walk spent the lever's 1 key"
    assert g1.phase is Phase.LOCK_PENDING
    assert not g1.can_use_key_at_lock(), "1 key covers only the lever pull, not the locked door too"

    g2 = _hall_with_locked_east(2, registry)
    g2.draft_from(7, E)
    assert g2.state.keys == 1, "the walk spent the lever's 1 key, 1 left for the door"
    assert g2.phase is Phase.LOCK_PENDING
    assert g2.can_use_key_at_lock(), "2 keys cover both the lever pull and the locked door"


# --------------------------------------------------------- guaranteed locks

HALL_CELL = 7  # rank 2, center column: all four neighbors (2, 6, 8, 12) are on-grid


def _placed_hall(seed: int = 1, registry=None) -> Game:
    """A Game with the Great Hall drafted at HALL_CELL, entered from the south
    (matching the Entrance Hall at cell 2), antechamber_levers off so the
    lever mechanic never interferes with the lock assertions below."""
    g = Game(GameConfig(door_locks=True, antechamber_levers=False), seed=seed, registry=registry)
    hall = g.registry.by_id["great_hall"]
    _draft_place(g, "great_hall", HALL_CELL, hall.door_mask, S)
    return g


def test_all_three_non_entry_doorways_lock(registry):
    """The far doorway (N, opposite the S entry) and both side doorways
    (E, W) all come out DOOR_LOCKED -- the wiki's "all seven ... guaranteed
    to be locked" claim, expressed on our single-chamber cross layout."""
    g = _placed_hall(registry=registry)
    assert g.door_state_of(HALL_CELL, N) == DOOR_LOCKED
    assert g.door_state_of(HALL_CELL, E) == DOOR_LOCKED
    assert g.door_state_of(HALL_CELL, W) == DOOR_LOCKED


def test_entry_doorway_is_not_locked(registry):
    """The doorway the player actually drafted the Great Hall through stays
    open -- the guaranteed lock only ever applies to the room's other doors,
    exactly like the wiki's own drafting-door exception."""
    g = _placed_hall(registry=registry)
    assert g.door_state_of(HALL_CELL, S) == DOOR_OPEN


def test_foyer_overrides_the_great_halls_guaranteed_locks(registry):
    """A Foyer placed after the Great Hall force-opens all three of its
    guaranteed locks, matching the wiki: 'The Foyer's effect also works on
    the doors that are guaranteed to be locked in the Great Hall.'"""
    g = _placed_hall(registry=registry)
    assert g.door_state_of(HALL_CELL, N) == DOOR_LOCKED  # setup: locked before the Foyer

    foyer_room = g.registry.by_id["foyer"]
    g._place_room(foyer_room, 30, foyer_room.door_mask)

    assert g.door_state_of(HALL_CELL, N) == DOOR_OPEN
    assert g.door_state_of(HALL_CELL, E) == DOOR_OPEN
    assert g.door_state_of(HALL_CELL, W) == DOOR_OPEN
    assert g.door_state_of(HALL_CELL, S) == DOOR_OPEN  # already open; still open


def test_search_cost_only_ever_hits_the_side_doorways(registry):
    """The far doorway always costs exactly the base 1 key, never a search
    surcharge; the two side doorways' surcharge is a live roll -- across
    enough seeds it takes every value the datamined table allows (0, 1 or 2
    extra), not just one, proving the mechanism is wired up and not a
    constant in disguise."""
    side_extra_values: set[int] = set()
    for seed in range(20):
        g = _placed_hall(seed=seed, registry=registry)
        assert g.lock_open_cost(HALL_CELL, N) == 1  # far: never a surcharge
        side_extra_values.add(g.lock_open_cost(HALL_CELL, E) - 1)
        side_extra_values.add(g.lock_open_cost(HALL_CELL, W) - 1)
    assert side_extra_values == {0, 1, 2}


def _seed_with_side_cost_at_least(min_cost: int, registry=None) -> tuple[int, int]:
    """First seed whose Great Hall east doorway needs >= min_cost keys.

    Search rather than a hardcoded seed, so this stays correct if the RNG
    derivation ever changes shape without needing a new magic number.
    """
    for seed in range(50):
        g = _placed_hall(seed=seed, registry=registry)
        cost = g.lock_open_cost(HALL_CELL, E)
        if cost >= min_cost:
            return seed, cost
    raise AssertionError(f"no seed in range(50) rolled a side cost >= {min_cost}")


def test_unaffordable_search_cost_blocks_use_key_not_the_try(registry):
    """A side doorway whose rolled search cost exceeds the player's keys still
    lets the player TRY the door for free -- trying a locked door costs
    nothing regardless of the rolled cost, per the owner's ruling that the
    player only finds out a door is locked, and chooses how to open it,
    after clicking it (Phase.LOCK_PENDING). The acceptance bar moves to the
    use-a-key menu row: it must not let a player short of the rolled cost
    spend keys they don't have.

    Trying the door is always free and is checked before the use-a-key row,
    which isolates the acceptance bar tested here to the rolled cost itself
    -- see Game.can_use_key_at_lock.
    """
    seed, cost = _seed_with_side_cost_at_least(2, registry=registry)
    g = _placed_hall(seed=seed, registry=registry)
    action = A.OPEN_BASE + HALL_CELL * 4 + A.DIR_INDEX[E]

    g.state.keys = cost - 1
    assert A.action_mask(g)[action], "trying the door is free, regardless of the rolled cost"
    g.state.pos = HALL_CELL
    g.open_door(HALL_CELL, E)
    assert g.phase is Phase.LOCK_PENDING
    assert not g.can_use_key_at_lock(), "one key short of the rolled cost must not be spendable"
    g.abandon_lock()
    assert g.door_state_of(HALL_CELL, E) == DOOR_LOCKED  # abandon leaves it locked

    g.state.keys = cost
    g.open_door(HALL_CELL, E)
    assert g.phase is Phase.LOCK_PENDING
    assert g.can_use_key_at_lock(), "exactly the rolled cost must be affordable"
    g.use_key_at_lock()
    assert g.phase is Phase.DRAFTING
    assert g.state.keys == 0, "use_key_at_lock must spend the FULL rolled cost, not just 1"


def test_same_seed_rolls_the_same_search_cost(registry):
    """Two games built from the same seed roll an identical search cost for
    the Great Hall's side doorways -- the search-cost draw is deterministic
    given the seed, not just correctly distributed."""
    seed, _ = _seed_with_side_cost_at_least(1, registry=registry)
    first = _placed_hall(seed=seed, registry=registry)
    second = _placed_hall(seed=seed, registry=registry)
    assert first.lock_open_cost(HALL_CELL, E) == second.lock_open_cost(HALL_CELL, E)
    assert first.lock_open_cost(HALL_CELL, W) == second.lock_open_cost(HALL_CELL, W)


def test_corridor_doors_remain_always_open(registry):
    """The pre-existing always_unlocked_rooms path (Corridor) is untouched by
    adding always_locked_rooms alongside it in locks.json."""
    g = Game(GameConfig(door_locks=True), seed=1, registry=registry)
    corridor = g.registry.by_id["corridor"]
    g._place_room(corridor, HALL_CELL, corridor.door_mask)
    for d in (N, E, S, W):
        if corridor.door_mask & d:
            assert g.door_state_of(HALL_CELL, d) == DOOR_OPEN


def test_spare_great_hall_grants_one_published_prize_bundle(registry):
    """Entering it pays exactly one of the three published alcove bundles.

    The room's "7 Locked Doors" text has no grid-granularity representation --
    no side doorways, no lever, no disk -- so the prize is the only part of it
    a player can observe, and paying a blend of the bundles or none at all
    would both be wrong.
    """
    from blueprince_sim.engine import effects
    from blueprince_sim.engine.effects import Hook
    from blueprince_sim.engine.effects.rooms.spare_great_hall import PRIZE_BUNDLES

    spare = registry.by_id["spare_great_hall__ix139"]
    seen = set()
    for seed in range(60):
        g = Game(GameConfig(), seed=seed, registry=registry)
        before = (g.state.gems, g.state.keys, g.state.coins)
        # Fire the entry hooks directly: the room also carries a luck-gated
        # extra-item roll, which would otherwise land in the same delta.
        effects.fire(g, spare, Hook.ON_ENTER, None)
        granted = (g.state.gems - before[0], g.state.keys - before[1],
                   g.state.coins - before[2])
        assert granted in PRIZE_BUNDLES, f"seed {seed} granted {granted}, not a published bundle"
        seen.add(granted)

    assert seen == set(PRIZE_BUNDLES), f"only {sorted(seen)} appeared over 60 seeds"
