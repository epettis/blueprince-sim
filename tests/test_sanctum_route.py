"""Tests for Part 2 of The Foundation: the Basement/Sanctum route it opens, and
the three-tier reward that pays for opening the Antechamber's north door.

Part 1 (the room itself: placement rules, persistence, its own Upgrade Disk) is
covered by test_foundation.py and is out of scope here. This file covers the
route-unblocking changes: mine_south_visited actually being set by the engine,
the Foundation becoming a grid anchor so its elevator reaches the Basement, the
Abandoned Mine's bespoke disk grant, and the north-door reward paid once by
either lever (Inner Sanctum or Throne Room) -- keyed off a per-day event flag,
never derived from the door segment's own state (see docs/foundation-design.md).
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import reachable
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import actions as A
from blueprince_sim.env import rewards as R
from blueprince_sim.env.multiday import DayChain

CORRIDOR_CHAIN = (7, 12, 17)  # rank2..rank4, col 2 -- climbs north from the Entrance Hall
FOUNDATION_CELL = 22          # rank 5, col 2


# ---------------------------------------------------------------------------
# Helpers (test setup only; no assertions live here)
# ---------------------------------------------------------------------------

def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Plant a room in the grid at ``cell`` with ``mask`` doors, without drafting."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to ``cell`` and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


def _place_foundation_connected(g: Game) -> None:
    """Chain inert Corridor fillers north from the pre-placed Entrance Hall up
    to rank 5 col 2, then place the Foundation there directly (bypassing the
    draft) -- gives the Foundation a grid anchor genuinely walkable from the
    house, the same connectivity shape test_foundation.py's ``_chain_to`` builds."""
    corridor = g.registry.by_id["corridor"]
    for cell in CORRIDOR_CHAIN:
        g._place_room(corridor, cell, N | S)
    foundation = g.registry.by_id["the_foundation"]
    g._place_room(foundation, FOUNDATION_CELL, N | S)


# ---------------------------------------------------------------------------
# 1. mine_south_visited: set on arrival, carried across days
# ---------------------------------------------------------------------------

def test_mine_south_visit_persists_across_days(registry):
    """Arriving at mine_south sets state.mine_south_visited, and DayChain carries
    it into day 2's GameConfig -- the same persistence shape as west_gate_unlatched,
    so the underpass route stays open for the rest of the attempt."""
    chain = DayChain(GameConfig(special_items=True), n_days=5)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    g1.state.steps = 50
    assert g1.state.mine_south_visited is False
    # mine_south is gated behind the (unlit) candlestick_stairway_lit flag, so a
    # bare Game cannot travel straight there from the house; place the player at
    # Catacombs first (one of the mine's real entrances, draxus_scythe always
    # passes) so the arrival below is a genuine travel_to() call.
    g1.state.area = "catacombs"
    g1.travel_to("mine_south")
    assert g1.state.mine_south_visited is True

    chain.advance(carryover(g1))
    cfg2 = chain.next_config()
    assert cfg2.mine_south_visited is True, (
        "mine_south_visited must carry into day 2's GameConfig"
    )


# ---------------------------------------------------------------------------
# 2. The flag is what gates rotating_gear -> underpass -> inner_sanctum
# ---------------------------------------------------------------------------

def test_mine_south_visited_flag_gates_the_underpass_route(registry):
    """_gate_ctx() must contribute "mine_south_visited" once state or config
    record the visit, since that flag is what makes rotating_gear -> underpass
    -> inner_sanctum traversable (docs/foundation-design.md)."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)

    ctx_before = g._gate_ctx()
    assert "mine_south_visited" not in ctx_before.flags
    dist_before = reachable(g.registry.area_graph, "rotating_gear", ctx_before)
    assert dist_before.get("underpass") is None
    assert dist_before.get("inner_sanctum") is None

    g.state.mine_south_visited = True
    ctx_after = g._gate_ctx()
    assert "mine_south_visited" in ctx_after.flags
    dist_after = reachable(g.registry.area_graph, "rotating_gear", ctx_after)
    assert dist_after.get("underpass") == 1
    assert dist_after.get("inner_sanctum") == 2


# ---------------------------------------------------------------------------
# 3. The full chain, end to end, through the real Game API
# ---------------------------------------------------------------------------

def test_full_sanctum_route_reachable_end_to_end(registry):
    """Holding the Basement Key, with the Foundation drafted and grid-connected:
    the whole Sanctum route resolves through the real Game API. Visiting
    mine_south sets mine_south_visited; only afterward does area_route_cost
    report a finite route to inner_sanctum, through the Foundation's elevator,
    the Basement, and the Underpass."""
    g = Game(GameConfig(special_items=True, antechamber_levers=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    _place_foundation_connected(g)

    assert g.area_route_cost("mine_south") is not None, "setup: mine_south must be reachable at all"
    g.travel_to("mine_south")
    assert g.state.mine_south_visited is True

    g.travel_to("house")
    result = g.area_route_cost("inner_sanctum")
    assert result is not None, (
        "inner_sanctum must be reachable once mine_south has been visited and "
        "the Foundation gives access to the Basement"
    )

    g.travel_to("inner_sanctum")
    assert g.state.area == "inner_sanctum"


# ---------------------------------------------------------------------------
# 3b. The Foundation's own Basement door is a separate Basement-Key gate
# ---------------------------------------------------------------------------

def test_foundation_basement_door_blocked_without_basement_key(registry):
    """The wiki treats the three Basement doors as independent instances, each
    unlocked only by a Basement Key. Without one held, the_foundation -> basement
    must not traverse, and basement must be unreachable even though the
    Foundation is drafted and grid-connected: the basement_key_foundation gate
    applies independently of the open elevator stub."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    assert g.state.inventory.get("basement_key", 0) == 0
    _place_foundation_connected(g)

    assert g.area_route_cost("the_foundation") is not None, (
        "setup: the Foundation must be reachable"
    )
    assert g.area_route_cost("basement") is None, (
        "basement must stay unreachable through the Foundation without a Basement Key"
    )

    with pytest.raises(AssertionError):
        g.travel_to("basement")


def test_foundation_basement_door_opens_with_basement_key(registry):
    """The same Foundation setup as the no-key test, but holding a Basement Key:
    the_foundation -> basement must now traverse. This is the positive half of
    the gate pin -- together the two tests fail if the gate is reverted in
    either direction (removed entirely, or added but never satisfiable)."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    _place_foundation_connected(g)

    assert g.area_route_cost("basement") is not None, (
        "basement must be reachable through the Foundation once a Basement Key is held"
    )
    g.travel_to("basement")
    assert g.state.area == "basement"


def test_foundation_basement_door_gates_the_inside_direction_too(registry):
    """The wiki unlocks this door "from either side using a Basement Key", so
    arriving in the Basement by another route must not let a keyless player walk
    out through it into the Foundation. A Power Hammer opens the Sealed Entrance
    wall, which reaches the Basement without ever touching the key."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["power_hammer"] = 1
    g.state.west_gate_unlatched = True
    assert g.state.inventory.get("basement_key", 0) == 0

    assert g.area_route_cost("basement") is not None, (
        "setup: the Power Hammer must open the Sealed Entrance route into the Basement"
    )
    assert g.area_route_cost("the_foundation") is None, (
        "a keyless player in the Basement must not walk out through the Basement door"
    )

    g.state.inventory["basement_key"] = 1
    assert g.area_route_cost("the_foundation") is not None, (
        "with the key held the same door opens from the inside"
    )


# ---------------------------------------------------------------------------
# 3c. This change must not close the pre-existing empty-inventory mine route
# ---------------------------------------------------------------------------

def test_precipice_still_reachable_with_empty_inventory(registry):
    """precipice is reachable with a completely empty inventory via the open
    cliffside_elevator_down stub (house -> grounds -> precipice, 2 hops) and
    does not run through the Foundation's Basement door at all -- gating
    the_foundation -> basement on the Basement Key must not accidentally
    close this unrelated route (docs/foundation-design.md).

    mine_south is deliberately NOT reached through precipice here: reaching
    mine_south requires candlestick_stairway_lit (docs/areas.md correction)
    -- see test_candlestick_stairway.py for that property.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    assert g.state.inventory.get("basement_key", 0) == 0
    assert g.state.inventory.get("power_hammer", 0) == 0

    result = g.area_route_cost("precipice")
    assert result is not None, "precipice must still be reachable with an empty inventory"
    steps, _anchor = result
    assert steps == 2, "the elevator route is exactly 2 hops from the house"

    assert g.area_route_cost("mine_south") is None, (
        "mine_south must not be reachable through the (now closed) precipice backdoor"
    )


# ---------------------------------------------------------------------------
# 4. Both levers open the north door, set the event flag, and pay the reward once
# ---------------------------------------------------------------------------

def test_inner_sanctum_lever_opens_door_sets_flag_and_pays_reward_once(registry):
    """Arriving at inner_sanctum opens the Antechamber's north segment, sets
    north_door_opened, and the sparse reward pays NORTH_DOOR_REWARD exactly on
    that step -- a second arrival (already open) pays nothing further."""
    g = Game(GameConfig(special_items=True, antechamber_levers=True), seed=1, registry=registry)
    g.state.steps = 50
    g.state.area = "underpass"  # off-grid neighbour; the real edge gate always passes
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED
    assert g.state.north_door_opened is False

    prev = R.snapshot(g)
    g.travel_to("inner_sanctum")
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN
    assert g.state.north_door_opened is True
    r = R.sparse(g, prev, terminated=False)
    assert r == pytest.approx(R.NORTH_DOOR_REWARD)

    # Second arrival: leave and come back; the door is already open, so the
    # guard (state.door_state.get(seg) == DOOR_SEALED) must skip the lever.
    g.travel_to("underpass")
    prev2 = R.snapshot(g)
    g.travel_to("inner_sanctum")
    r2 = R.sparse(g, prev2, terminated=False)
    assert r2 == 0.0, "the reward must not pay a second time once the door is already open"


def test_throne_room_lever_opens_door_sets_flag_and_pays_reward(registry):
    """Entering the Throne Room pulls the backup north lever exactly like the
    Inner Sanctum: it opens the Antechamber's north segment, sets
    north_door_opened, and the sparse reward pays NORTH_DOOR_REWARD once."""
    g = Game(GameConfig(special_items=True, antechamber_levers=True), seed=1, registry=registry)
    _place_at(g, "throne_room", 7, N | S)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED
    assert g.state.north_door_opened is False

    prev = R.snapshot(g)
    _enter_at(g, 7)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN
    assert g.state.north_door_opened is True
    r = R.sparse(g, prev, terminated=False)
    assert r == pytest.approx(R.NORTH_DOOR_REWARD)


def test_north_door_reward_pays_once_regardless_of_which_lever_pulls_it(registry):
    """The two levers open the SAME segment: once the Inner Sanctum lever has
    opened it, later entering the Throne Room must not pay NORTH_DOOR_REWARD a
    second time -- the reward is for the door, not for either room specifically."""
    g = Game(GameConfig(special_items=True, antechamber_levers=True), seed=1, registry=registry)
    g.state.steps = 50
    g.state.area = "underpass"
    g.travel_to("inner_sanctum")
    assert g.state.north_door_opened is True
    g.state.area = None
    g.state.pos = 2

    _place_at(g, "throne_room", 7, N | S)
    prev = R.snapshot(g)
    _enter_at(g, 7)
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_OPEN  # already open from the Sanctum
    r = R.sparse(g, prev, terminated=False)
    assert r == 0.0, "the Throne Room must not re-pay a reward the Sanctum lever already earned"


# ---------------------------------------------------------------------------
# 5. antechamber_levers=False: no free reward from the old open-door baseline
# ---------------------------------------------------------------------------

def test_no_north_door_reward_under_levers_false_without_touching_a_lever(registry):
    """Under antechamber_levers=False the north segment is never sealed to begin
    with, so a day that never enters a lever room must never pay
    NORTH_DOOR_REWARD. A reward derived from the door's OWN state (rather than
    the north_door_opened event flag set only at the lever sites) would pay it
    for free on every such day and corrupt the pre-lever baseline this config
    exists to reproduce."""
    g = Game(GameConfig(special_items=True, antechamber_levers=False), seed=1, registry=registry)
    assert g.door_state_of(ANTECHAMBER_CELL, N) != DOOR_SEALED, (
        "setup: the north segment must never be sealed under levers=False"
    )

    total = 0.0
    prev = R.snapshot(g)
    for _ in range(10):
        g.state.steps -= 1  # stand in for a day's worth of ordinary decisions
        total += R.sparse(g, prev, terminated=False)
        prev = R.snapshot(g)

    assert g.state.north_door_opened is False, (
        "no lever was ever pulled, so the event flag must stay False"
    )
    assert total == 0.0, (
        f"expected zero north-door reward on a lever-free levers=False day, got {total}"
    )


# ---------------------------------------------------------------------------
# 6. The Abandoned Mine's disk: granted once per day
# ---------------------------------------------------------------------------

def test_mine_south_disk_granted_on_first_arrival_not_on_second(registry):
    """The Abandoned Mine's Upgrade Disk is granted the first time the player
    reaches mine_south each day, and a second arrival the same day does not
    re-grant it -- disks are unique items, so _is_available blocks the
    duplicate the same way the in-grid guaranteed_in disks do."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 50
    assert g.state.inventory.get("upgrade_disk_mine_south", 0) == 0

    # mine_south is gated behind the (unlit) candlestick_stairway_lit flag, so
    # stage the player at Catacombs first (a real entrance, draxus_scythe
    # always passes) for a genuine first travel_to() arrival.
    g.state.area = "catacombs"
    g.travel_to("mine_south")
    assert g.state.inventory.get("upgrade_disk_mine_south", 0) == 1

    g.travel_to("reservoir_south")
    g.travel_to("mine_south")
    assert g.state.inventory.get("upgrade_disk_mine_south", 0) == 1, (
        "re-arriving at mine_south the same day must not grant a second disk"
    )


# ---------------------------------------------------------------------------
# 7. The Basement Key: spawns on Antechamber entry, gates the well, not consumed
# ---------------------------------------------------------------------------

def test_basement_key_spawns_on_antechamber_entry_and_is_not_consumed(registry):
    """The Basement Key is granted from the pillar that emerges the first time
    the Antechamber is entered each day, and opening the well -> reservoir_south
    gate with it does not remove it from inventory -- the wiki's 'Using the
    Basement Key does not consume the key'."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    assert g.state.inventory.get("basement_key", 0) == 0
    _enter_at(g, ANTECHAMBER_CELL)
    assert g.state.inventory.get("basement_key", 0) == 1

    # Back on the Entrance Hall (grid-connected to the rest of the house) to
    # walk the well -> reservoir_south route the key gates.
    g.state.pos = 2
    g.state.steps = 50
    g.travel_to("well")
    g.travel_to("reservoir_south")
    assert g.state.area == "reservoir_south", (
        "the basement_key_well gate must open while the key is held"
    )
    assert g.state.inventory.get("basement_key", 0) == 1, (
        "opening the gate must not consume the Basement Key"
    )


# ---------------------------------------------------------------------------
# 8. modelled: the four new nodes are offered as travel destinations
# ---------------------------------------------------------------------------

def test_mine_south_travel_action_offered_once_reachable(registry):
    """mine_south is gated shut behind the candlestick_stairway_lit flag on a
    bare day 1 (the mine is not a front door reachable from the Precipice) --
    but once the stairway is lit from inside the mine, "modelled" is what then
    makes the action mask offer travel to it (env/actions.py); a
    reachable-but-unmodelled node would leave the mask False even though
    area_route_cost reports a route."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 200
    assert g.area_route_cost("mine_south") is None, "setup: gated shut before lighting"

    # Simulate having reached the mine some other way (Catacombs, drained
    # Fountain, or the lowered Reservoir crossing) and lighting the eight
    # candlesticks from inside.
    g.state.area = "mine_south"
    g.state.inventory["torch"] = 1
    assert g.can_light()
    g.light()
    assert "mine_south" in g.state.special.lit_targets

    # Step to another node and confirm the mine is now a legal, offered
    # travel destination.
    g.state.area = "precipice"
    node_ids = A._build_area_node_ids(g.registry)
    i = node_ids.index("mine_south")
    assert g.area_route_cost("mine_south") is not None, "stairway should now be open"
    mask = A.action_mask(g)
    assert mask[A.TRAVEL_BASE + i], "mine_south must be offered as a travel destination"


def test_foundation_and_basement_travel_actions_offered_once_placed_and_visited(registry):
    """Once the Foundation is drafted and grid-connected, its own "modelled"
    flag (and basement's) make the action mask offer travel to both -- the
    same wiring test_mine_south_travel_action_offered_once_reachable pins for
    mine_south, covering the other three nodes flipped modelled by this PR."""
    g = Game(GameConfig(special_items=True, antechamber_levers=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1  # the Foundation's own Basement door needs it too
    _place_foundation_connected(g)

    node_ids = A._build_area_node_ids(g.registry)
    mask = A.action_mask(g)
    for dest in ("the_foundation", "basement"):
        i = node_ids.index(dest)
        assert g.area_route_cost(dest) is not None, f"setup: {dest} must be reachable"
        assert mask[A.TRAVEL_BASE + i], f"{dest} must be offered as a travel destination"


# ---------------------------------------------------------------------------
# 9. The Sealed Entrance breaks once and stays broken
# ---------------------------------------------------------------------------

def test_sealed_entrance_unreachable_without_hammer_or_flag(registry):
    """With no Power Hammer held and the break not yet earned, the Sealed
    Entrance and the route it gives into the Basement are both shut -- the
    negative half of the sealed_entrance_broken gate."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    assert g.state.inventory.get("power_hammer", 0) == 0
    assert "sealed_entrance_broken" not in g._gate_ctx().flags

    assert g.area_route_cost("sealed_entrance") is None
    assert g.area_route_cost("basement") is None


def test_power_hammer_opens_sealed_entrance_route(registry):
    """Holding a Power Hammer satisfies the gate, which is what lets the FIRST
    break happen; the Basement then opens through the Sealed Entrance without
    any Basement Key."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["power_hammer"] = 1
    assert g.state.inventory.get("basement_key", 0) == 0

    assert g.area_route_cost("sealed_entrance") is not None
    assert g.area_route_cost("basement") is not None


def test_sealed_entrance_stays_open_with_hammer_removed(registry):
    """The whole point of the owner's correction: once broken it does not grow
    back. After one trip through, the route survives the Power Hammer leaving
    the inventory -- in both directions, since the return trip crosses the same
    barrier."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["power_hammer"] = 1
    g.travel_to("sealed_entrance")
    assert g.state.sealed_entrance_broken is True

    del g.state.inventory["power_hammer"]
    assert g.area_route_cost("basement") is not None, "the break must outlast the hammer"

    g.travel_to("basement")
    g.travel_to("sealed_entrance")  # the return trip crosses the same broken barrier
    assert g.state.area == "sealed_entrance"


def test_sealed_entrance_break_is_state_only_and_carries_across_days(registry):
    """The break is recorded on GameState, never written back to GameConfig --
    one config object is shared by every episode of a training worker, so a cfg
    write would leak the unlock into later fresh-save episodes. carryover() and
    DayChain are what make it permanent, and a chain wrap clears it."""
    chain = DayChain(GameConfig(special_items=True), n_days=3)
    g = Game(chain.next_config(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["power_hammer"] = 1
    g.travel_to("sealed_entrance")

    assert g.state.sealed_entrance_broken is True
    assert g.cfg.sealed_entrance_broken is False, "the config must never be mutated in-run"

    chain.advance(carryover(g))
    assert chain.next_config().sealed_entrance_broken is True

    chain.advance({})
    chain.advance({})  # day 3 -> wrap: a fresh attempt starts unbroken again
    assert chain.next_config().sealed_entrance_broken is False
