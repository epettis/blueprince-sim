"""The Basement Key opens one door at a time, and each stays open for the save.

Owner ruling: *"The Basement Key will open locked basement doors. You need to
enter the room with the door holding the Basement Key to unlock the door. Once
unlocked, the door will remain unlocked for the rest of the seed."*

Three claims follow, and this file pins each of them:

- **Per door.** Standing at one Basement door with the key unlocks that door
  and no other, so holding the key never opens a door the player has not
  walked up to.
- **Both directions of the retired shortcut.** The sim used to read the gates
  as "a Basement Key is currently held"; under the ruling an unlocked door
  opens with the key long gone, and a held key opens nothing on its own.
- **Save-scoped.** The unlocked set survives the ``DayChain`` attempt wrap,
  which is what makes it seed-scoped rather than attempt-scoped, and it is a
  SET, so it cannot live in the bool-only ``_CARRYOVER_KEYS``.

Scenarios are built explicitly (rooms planted, water levels and flags set by
hand); no test here relies on a seed to produce a situation.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.areas import gate_open, unlocked_by_visiting
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env.multiday import DayChain

#: rank2..rank4 of column 2, climbing north from the pre-placed Entrance Hall.
CORRIDOR_CHAIN = (7, 12, 17)
FOUNDATION_CELL = 22  # rank 5, col 2

#: The two modelled Basement doors, by gate id (areas.json). The Crate Tunnel's
#: third instance is not modelled -- crate_tunnel is truncated to its entrance.
WELL_DOOR = "basement_key_well"
FOUNDATION_DOOR = "basement_key_foundation"


def _well_route_config(**overrides) -> GameConfig:
    """A config whose only way underground is through the Well's Basement door.

    Fountain drained to 0 opens both grounds -> well (<= 8) and the well door's
    second, non-latching condition (== 0); the Reservoir crossing is opened via
    reservoir_13_reached. sealed_entrance_broken is deliberately left False, so
    the Sealed Entrance shortcut that otherwise bypasses the Well is shut and
    every underground route has to pass the door under test.
    """
    return GameConfig(
        special_items=True,
        water_levels={"fountain": 0},
        reservoir_13_reached=True,
        **overrides,
    )


def _place_foundation_connected(g: Game) -> None:
    """Plant Corridor fillers north from the Entrance Hall and the Foundation at
    their end, so the Foundation is a grid anchor genuinely walkable from the
    house without going through a draft."""
    corridor = g.registry.by_id["corridor"]
    for cell in CORRIDOR_CHAIN:
        g._place_room(corridor, cell, N | S)
    g._place_room(g.registry.by_id["the_foundation"], FOUNDATION_CELL, N | S)


# ---------------------------------------------------------------------------
# 1. Which nodes unlock which door
# ---------------------------------------------------------------------------

def test_a_door_unlocks_only_from_the_nodes_that_touch_it(registry):
    """unlocked_by_visiting reports a door only for the nodes the door is
    actually at, and only while the key is held.

    This is the whole "enter the room with the door" rule in one function, so
    it is worth pinning node by node: the Well door is at both sides of its own
    doorway, the Foundation's door is at the FOOT of the elevator (so the
    on-grid Foundation at the top is not a place you can reach it), and no node
    unlocks anything without a Basement Key.
    """
    graph = registry.area_graph
    key = {"basement_key": 1}

    assert unlocked_by_visiting(graph, {"well"}, key) == {WELL_DOOR}
    assert unlocked_by_visiting(graph, {"reservoir_south"}, key) == {WELL_DOOR}
    assert unlocked_by_visiting(graph, {"basement"}, key) == {FOUNDATION_DOOR}
    assert unlocked_by_visiting(graph, {"the_foundation"}, key) == set(), (
        "the Foundation is the TOP of the elevator; its Basement door is at the foot"
    )
    assert unlocked_by_visiting(graph, {"grounds", "house", "mine_south"}, key) == set()

    assert unlocked_by_visiting(graph, {"well", "basement"}, {}) == set(), (
        "no Basement Key held, so standing at either door unlocks nothing"
    )


def test_an_unlocked_door_does_not_unlock_the_other_one(registry):
    """Passing the Well door does not report the Foundation's door as unlocked.

    The two are independent locks on independent edges (the wiki treats
    Basement_door as a type with separate instances), and conflating them is
    exactly the "opens every basement door" reading the owner's ruling rejects.
    """
    graph = registry.area_graph
    unlocked = unlocked_by_visiting(graph, {"well", "reservoir_south"}, {"basement_key": 1})
    assert unlocked == {WELL_DOOR}
    assert FOUNDATION_DOOR not in unlocked


# ---------------------------------------------------------------------------
# 2. Walking to the door is what unlocks it
# ---------------------------------------------------------------------------

def test_travelling_past_the_well_door_with_the_key_records_it(registry):
    """A route THROUGH the Well records the Well door as unlocked.

    Both of that door's sides are unmodelled nodes that are never offered as a
    travel destination, so passing through is the only way a player ever stands
    at it -- if the latch only looked at the destination, this door could never
    be unlocked at all.
    """
    g = Game(_well_route_config(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    assert g.state.basement_doors_open == set()

    g.travel_to("mine_south")

    assert g.state.area == "mine_south"
    assert g.state.basement_doors_open == {WELL_DOOR}, (
        "the route house->grounds->well->reservoir_south->mine_south passes the door"
    )


def test_holding_the_key_at_home_unlocks_nothing(registry):
    """A key that never leaves the house unlocks no door.

    The direction the retired "key currently held" shortcut got wrong: under it
    a held key was indistinguishable from every door being open. Travelling to
    the Grounds (which touches no Basement door) must leave the set empty, and
    both gates must still read shut once the key is gone.
    """
    g = Game(_well_route_config(), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1

    g.travel_to("grounds")
    assert g.state.basement_doors_open == set()

    del g.state.inventory["basement_key"]
    ctx = g._gate_ctx()
    assert gate_open(g.registry.area_graph, WELL_DOOR, ctx) is False
    assert gate_open(g.registry.area_graph, FOUNDATION_DOOR, ctx) is False


def test_the_foundation_door_unlocks_by_riding_down_not_by_standing_on_top(registry):
    """Entering the on-grid Foundation with the key does not unlock its door;
    riding the elevator down to the Basement does.

    areas.json puts that door "at the foot of the Foundation's elevator", so the
    room the player has to enter to reach it is the Basement, not the Foundation
    -- which is why the gate's unlock_nodes is ``basement`` alone.
    """
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    _place_foundation_connected(g)

    g.travel_to("the_foundation")
    assert g.state.basement_doors_open == set(), (
        "standing at the top of the elevator is not standing at the door"
    )

    g.travel_to("basement")
    assert g.state.basement_doors_open == {FOUNDATION_DOOR}
    assert WELL_DOOR not in g.state.basement_doors_open


# ---------------------------------------------------------------------------
# 3. Once unlocked, the door opens without the key
# ---------------------------------------------------------------------------

def test_an_unlocked_door_stays_open_after_the_key_is_gone(registry):
    """A door unlocked on an earlier day opens with no Basement Key in hand.

    The other direction the retired shortcut got wrong. Asserted on a genuinely
    fresh Game whose only difference from the control below is the carried
    unlock, so nothing but the recorded door can explain the route.
    """
    unlocked = Game(
        _well_route_config(basement_doors_open=frozenset({WELL_DOOR})),
        seed=1, registry=registry,
    )
    control = Game(_well_route_config(), seed=1, registry=registry)
    for g in (unlocked, control):
        g.state.steps = 200
        assert g.state.inventory.get("basement_key", 0) == 0

    assert gate_open(unlocked.registry.area_graph, WELL_DOOR, unlocked._gate_ctx()) is True
    assert gate_open(control.registry.area_graph, WELL_DOOR, control._gate_ctx()) is False

    assert unlocked.area_route_cost("mine_south") is not None, (
        "the recorded unlock must reopen the route through the Well without the key"
    )
    assert control.area_route_cost("mine_south") is None, (
        "control: with the same config minus the unlock, that route must be shut"
    )
    unlocked.travel_to("mine_south")
    assert unlocked.state.area == "mine_south"


def test_the_unlock_reaches_gate_open_through_the_gates_counts_flag(registry):
    """The recorded unlock is read back through the gate's own counts_flag.

    Not an implementation detail worth hiding: counts_flag is what lets an item
    gate pass without the item (the Grotto pedestal's chip uses the same
    mechanism), and it is the only channel by which an unlocked door reports
    itself -- a gate that grew unlock_nodes without one would record unlocks
    that nothing ever reads.
    """
    g = Game(
        _well_route_config(basement_doors_open=frozenset({WELL_DOOR})),
        seed=1, registry=registry,
    )
    gate = g.registry.area_graph.gates[WELL_DOOR]
    assert gate.counts_flag == "basement_door_well_unlocked"
    assert gate.counts_flag in g._gate_ctx().flags
    assert "basement_door_foundation_unlocked" not in g._gate_ctx().flags


# ---------------------------------------------------------------------------
# 4. Scope: carried day to day, and across the attempt wrap
# ---------------------------------------------------------------------------

def test_carryover_ors_the_config_with_todays_unlocks(registry):
    """The carry reports yesterday's doors unioned with today's.

    Same OR-from-cfg-or-state shape as lab_visited: state alone would drop every
    door unlocked on an earlier day the moment a day passed without one.
    """
    g = Game(
        _well_route_config(basement_doors_open=frozenset({FOUNDATION_DOOR})),
        seed=1, registry=registry,
    )
    g.state.steps = 200
    g.state.inventory["basement_key"] = 1
    g.travel_to("mine_south")

    assert g.state.basement_doors_open == {WELL_DOOR}, "today unlocked only the Well door"
    assert sorted(g.carryover()["basement_doors_open"]) == [FOUNDATION_DOOR, WELL_DOOR]
    assert "basement_doors_open" not in carryover(g), (
        "the key is assembled by Game._basement_carryover, not shops.carryover"
    )


def test_unlocked_doors_survive_the_attempt_wrap(registry):
    """The unlocked set carries through the wrap; an attempt-scoped set does not.

    "For the rest of the seed" is a SAVE-scoped claim, and the wrap is exactly
    where attempt-scoped and save-scoped part company. sigil_doors_open is the
    control: same union-merged set shape, but cleared at the wrap, so a wrap
    block that stopped running could not make this test pass.
    """
    chain = DayChain(GameConfig(), n_days=1)  # day 1 of 1 -> advance() wraps
    chain.advance({
        "basement_doors_open": [WELL_DOOR],
        "sigil_doors_open": ["eraja"],
    })

    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    cfg = chain.next_config()
    assert cfg.basement_doors_open == frozenset({WELL_DOOR})
    assert cfg.sigil_doors_open == frozenset(), "control: sigil doors are attempt-scoped"


def test_the_unlocked_set_is_not_a_carryover_key(registry):
    """basement_doors_open is a named DayChain attribute, not a _CARRYOVER_KEYS
    member, and that set has not grown.

    _CARRYOVER_KEYS is bool-only and cleared wholesale at the wrap, so it can
    hold neither a set nor anything save-scoped. Its length is also the width of
    an observation field, so growing it would silently invalidate a checkpoint's
    learned field positions (docs/scoping-and-carryover.md).
    """
    assert "basement_doors_open" not in DayChain._CARRYOVER_KEYS
    assert len(DayChain._CARRYOVER_KEYS) == 19
    assert hasattr(DayChain(GameConfig()), "basement_doors_open")


def test_a_door_unlocked_today_is_open_again_tomorrow(registry):
    """End to end across a day boundary: unlock the Well door on day 1 holding
    the key, and day 2 walks the same route with no key granted at all.

    The single scenario that shows the whole mechanism doing its job, rather
    than each half of it separately.
    """
    chain = DayChain(_well_route_config(), n_days=5)
    day1 = Game(chain.next_config(), seed=1, registry=registry)
    day1.state.steps = 200
    day1.state.inventory["basement_key"] = 1
    day1.travel_to("mine_south")
    assert day1.state.basement_doors_open == {WELL_DOOR}

    chain.advance(day1.carryover())
    cfg2 = chain.next_config()
    assert cfg2.basement_doors_open == frozenset({WELL_DOOR})

    day2 = Game(cfg2, seed=2, registry=registry)
    day2.state.steps = 200
    day2.state.inventory.pop("basement_key", None)
    assert day2.area_route_cost("mine_south") is not None
    day2.travel_to("mine_south")
    assert day2.state.area == "mine_south"


# ---------------------------------------------------------------------------
# 5. Data invariants
# ---------------------------------------------------------------------------

def test_exactly_the_two_modelled_basement_doors_declare_unlock_nodes(registry):
    """unlock_nodes appears on the two Basement door gates and nowhere else.

    Every other gate is re-evaluated from scratch on each traversal; a third
    gate quietly acquiring a permanent unlock would change what a measured route
    means, so the set is pinned rather than merely counted.
    """
    graph = registry.area_graph
    declared = {g.id for g in graph.gates.values() if g.unlock_nodes}
    assert declared == {WELL_DOOR, FOUNDATION_DOOR}
    for gid in declared:
        gate = graph.gates[gid]
        assert gate.kind == "item"
        assert gate.item_ids == ("basement_key",)
        assert gate.counts_flag, "an unlock nobody can read back is not an unlock"


@pytest.mark.parametrize("gate_id,expected", [
    (WELL_DOOR, ("well", "reservoir_south")),
    (FOUNDATION_DOOR, ("basement",)),
])
def test_unlock_nodes_are_the_doors_own_sides(registry, gate_id, expected):
    """Each door's unlock_nodes are the nodes the door physically stands at.

    Pinned because the Foundation case is a judgment call, not a mechanical
    reading of the edge: its edge runs the_foundation <-> basement, but the door
    is at the foot of the elevator, so the_foundation is excluded on purpose.
    """
    assert registry.area_graph.gates[gate_id].unlock_nodes == expected
