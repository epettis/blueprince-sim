"""Steam power propagation over the placed grid (engine/power.py, docs/power.md).

Owner ruling: "The house isn't powered. A room is powered. A room is powered if
it shares a doorway with another powered room." Everything here is built by
placing named rooms at named cells with explicit door masks -- never by a seed,
so each scenario is exactly the grid its name claims.

The grid geometry used throughout: cells 7, 12, 17 and 22 are the centre column
(col 2) of ranks 2, 3, 4 and 5, so each is directly north of the one before it.
Cells 11 and 13 flank cell 12 on the west and east.

What this file does NOT cover: the effects a powered Garage, Pump Room, Laundry
Room or Furnace have once lit. Those are per-room work; powering is the whole
of the mechanic here. The Blackbridge Grotto gate the Laboratory's power feeds
is pinned in tests/test_lab_permanence.py.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_SEALED, segment_key
from blueprince_sim.engine.placement import legal_orientations, satisfies_draft_conditions
from blueprince_sim.engine.power import power_source_ids

SOUTH_CELL = 7    # rank 2, centre column
MID_CELL = 12     # rank 3, centre column
NORTH_CELL = 17   # rank 4, centre column
FAR_CELL = 22     # rank 5, centre column
WEST_CELL = 11    # rank 3, west of MID_CELL
EAST_CELL = 13    # rank 3, east of MID_CELL


def _game(registry) -> Game:
    """A default Game with an empty grid apart from the day-start fixtures."""
    return Game(GameConfig(), seed=1, registry=registry)


def _place(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Put ``room_id`` on ``cell`` with an explicit door mask, bypassing drafting."""
    g._place_room(g.registry.by_id[room_id], cell, mask)


# --------------------------------------------------------------- the sources

def test_a_power_source_powers_itself_with_nothing_attached(registry):
    """A Boiler Room alone on the grid is powered: sources need no neighbour.

    This is the BFS seed. If it failed, every other case here would fail with
    it, so it is asserted separately rather than inferred from the chains.
    """
    g = _game(registry)
    _place(g, "boiler_room", MID_CELL, N | S)

    assert g.cell_powered(MID_CELL) is True


def test_the_electric_eel_aquarium_is_a_source_and_its_siblings_are_not(registry):
    """Only the Electric Eel upgrade of the Aquarium generates power.

    The four Aquarium floorplans are otherwise interchangeable, so a source set
    keyed on the family rather than the variant would light all of them -- and
    an Aquarium is a common draft, which would make the Grotto near-free.
    """
    g = _game(registry)
    _place(g, "electric_eel_aquarium__ix4", MID_CELL, N | S)
    _place(g, "aquarium", NORTH_CELL, N | S)
    _place(g, "goldfish_aquarium__ix2", SOUTH_CELL, N | S)

    assert g.cell_powered(MID_CELL) is True
    assert g.cell_powered(NORTH_CELL) is False
    assert g.cell_powered(SOUTH_CELL) is False


def test_every_registered_source_also_carries_power(registry):
    """Each room registering Capability.POWER_SOURCE also carries flags.powered.

    The BFS seeds at sources but only ever walks carriers, so a source without
    the flag would silently light nothing -- a failure mode with no symptom
    other than a gate that never opens.
    """
    sources = power_source_ids()
    assert sources, "at least one room must register the capability"
    for room_id in sources:
        assert registry.by_id[room_id].powered is True, f"{room_id} needs flags.powered"


# ------------------------------------------------------- sharing a doorway

def test_a_source_powers_a_carrier_through_a_shared_doorway(registry):
    """A Laboratory with a door pair to a Boiler Room is powered.

    The base case of the owner's rule, and the one the Grotto gate rides on.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)

    assert g.cell_powered(MID_CELL) is True
    assert g.room_powered(g.registry.by_id["laboratory"]) is True


def test_orthogonal_adjacency_without_a_door_pair_does_not_carry_power(registry):
    """Two rooms in touching cells whose walls face each other stay unpowered.

    "Shares a doorway" is the engine's door-pair test, not adjacency: the
    Laboratory here has no north door and the Boiler Room no south door, so the
    two are neighbours on the grid with a solid wall between them. Getting this
    wrong would power most of the house from any source.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, E | W)      # no N bit
    _place(g, "boiler_room", NORTH_CELL, E | W)   # no S bit

    assert g.cell_powered(NORTH_CELL) is True, "the source is still a source"
    assert g.cell_powered(MID_CELL) is False


def test_a_one_sided_doorway_does_not_carry_power(registry):
    """A door on one side only is not a shared doorway.

    The Laboratory faces north but the Boiler Room has no south door, so the
    pair is half-formed. Testing only the near cell's mask would wrongly pass.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | E)   # no S bit

    assert g.cell_powered(MID_CELL) is False


# ------------------------------------------------------------ transitivity

def test_power_passes_through_a_connector_room(registry):
    """Boiler Room -> Passageway -> Laboratory powers the Laboratory.

    The owner's rule is transitive ("another powered room", not "a source"), so
    a connector between the two must conduct rather than absorb.
    """
    g = _game(registry)
    _place(g, "laboratory", SOUTH_CELL, N | S)
    _place(g, "passageway", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)

    assert g.cell_powered(MID_CELL) is True
    assert g.cell_powered(SOUTH_CELL) is True


def test_power_passes_through_a_chain_of_several_carriers(registry):
    """Power reaches the far end of a four-room chain, not just one hop.

    A rule implemented as "adjacent to a source" rather than a graph search
    would light the first neighbour and stop; this is the leg that would catch
    that.
    """
    g = _game(registry)
    _place(g, "boiler_room", SOUTH_CELL, N | S)
    _place(g, "archives", MID_CELL, N | S)
    _place(g, "darkroom", NORTH_CELL, N | S)
    _place(g, "laboratory", FAR_CELL, N | S)

    assert g.cell_powered(FAR_CELL) is True


def test_power_branches_down_every_doorway_of_a_carrier(registry):
    """One source lights both arms hanging off a shared connector.

    Power is not routed along a single path: the wiki's Darkroom "can split
    steam power in two different directions", and the graph search must do the
    same rather than stopping at the first neighbour it finds.
    """
    g = _game(registry)
    _place(g, "boiler_room", MID_CELL, N | E | S | W)
    _place(g, "laboratory", WEST_CELL, E)
    _place(g, "garage", EAST_CELL, W)

    assert g.cell_powered(WEST_CELL) is True
    assert g.cell_powered(EAST_CELL) is True


def test_a_non_carrying_room_breaks_the_chain(registry):
    """A Corridor between a Boiler Room and a Laboratory leaves the lab dark.

    Only rooms in the power network conduct. Treating every placed room as a
    conductor would make the Laboratory powered from almost anywhere, which is
    the difference between a real gate and a decorative one.
    """
    g = _game(registry)
    _place(g, "laboratory", SOUTH_CELL, N | S)
    _place(g, "corridor", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)

    assert g.cell_powered(MID_CELL) is False
    assert g.cell_powered(SOUTH_CELL) is False


def test_an_empty_cell_does_not_carry_power(registry):
    """A gap in the chain leaves the far room unpowered.

    Empty cells are freely walkable in the optimistic distance map, so a power
    search written against that map instead of the placed grid would conduct
    through nothing at all.
    """
    g = _game(registry)
    _place(g, "laboratory", SOUTH_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)

    assert g.state.grid[MID_CELL] < 0, "the middle cell must really be empty"
    assert g.cell_powered(SOUTH_CELL) is False


def test_a_carrier_with_no_route_to_a_source_stays_unpowered(registry):
    """Two carriers joined to each other but not to any source stay dark.

    Carrying power and having power are different things; without this, a rule
    that lit every carrier on the grid would pass every test above.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    _place(g, "archives", NORTH_CELL, N | S)

    assert g.cell_powered(MID_CELL) is False
    assert g.cell_powered(NORTH_CELL) is False


# ------------------------------------------------------ the three Red Rooms

def test_the_red_rooms_the_sheet_never_covered_carry_power(registry):
    """Darkroom, Weight Room and Furnace conduct power like any other carrier.

    All three are Red Rooms, absent from the datamined sheet and supplied by
    tools/supplemental_rooms.json, where their power flag was simply missing.
    The wiki is explicit that all three are on the network, so each is placed
    between a source and a Laboratory here and must pass power along.
    """
    for room_id in ("darkroom", "weight_room", "furnace"):
        g = _game(registry)
        _place(g, "laboratory", SOUTH_CELL, N | S)
        _place(g, room_id, MID_CELL, N | S)
        _place(g, "boiler_room", NORTH_CELL, N | S)

        assert g.cell_powered(MID_CELL) is True, f"{room_id} must be powered"
        assert g.cell_powered(SOUTH_CELL) is True, f"{room_id} must conduct"


# ------------------------------------------------------------- door state

def test_a_locked_doorway_still_carries_power(registry):
    """Power crosses a locked segment: locks gate the player, not the ducts.

    A doorway that needs a key is still a doorway, and making power depend on
    the key budget would make a room's power state change as keys are spent
    elsewhere. Deliberate divergence from nothing -- the wiki is silent -- and
    recorded in docs/power.md.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)
    g.state.door_state[segment_key(MID_CELL, N)] = DOOR_LOCKED
    g.state.door_version += 1
    g.state.keys = 0

    assert g.doorway_passable(MID_CELL, N) is False, "the player really cannot walk it"
    assert g.cell_powered(MID_CELL) is True


def test_a_sealed_doorway_still_carries_power(registry):
    """Power crosses a sealed segment too, for the same reason as a locked one.

    Sealed is the strongest door state there is (no key or item opens it), so
    it is the case most likely to have been special-cased by accident.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    _place(g, "boiler_room", NORTH_CELL, N | S)
    g.state.door_state[segment_key(MID_CELL, N)] = DOOR_SEALED
    g.state.door_version += 1

    assert g.doorway_passable(MID_CELL, N) is False
    assert g.cell_powered(MID_CELL) is True


# -------------------------------------------------------------- recomputation

def test_power_arrives_when_the_source_is_placed_later(registry):
    """A Laboratory placed first goes from dark to powered when a Boiler Room
    joins it, with no re-entry or other action in between.

    Power is a property of the current grid, not of the moment a room was
    drafted, so it must be recomputed as rooms are placed. Drafting the
    Laboratory first is the ordinary case, not the exception.
    """
    g = _game(registry)
    _place(g, "laboratory", MID_CELL, N | S)
    assert g.room_powered(g.registry.by_id["laboratory"]) is False

    _place(g, "boiler_room", NORTH_CELL, N | S)

    assert g.room_powered(g.registry.by_id["laboratory"]) is True


def test_room_powered_reports_true_when_any_copy_is_powered(registry):
    """With two Archives placed, one lit and one dark, room_powered is True.

    A room drafted twice records only its lowest cell in room_cells, so a
    lookup through that index would answer for the wrong copy.
    """
    g = _game(registry)
    _place(g, "archives", SOUTH_CELL, N | S)          # dark: nothing adjacent
    _place(g, "archives", NORTH_CELL, N | S)
    _place(g, "boiler_room", FAR_CELL, N | S)         # lights the NORTH copy only

    assert g.cell_powered(SOUTH_CELL) is False
    assert g.cell_powered(NORTH_CELL) is True
    assert g.room_powered(g.registry.by_id["archives"]) is True


# ------------------------------------------------- the Garage's West Path door

GARAGE_CELL = 1       # rank 1, col 1: directly west of the Entrance Hall at cell 2
GARAGE_WEST = 0       # rank 1, col 0: directly west of GARAGE_CELL


def _garage_door_game(registry, *, source: bool, breaker: bool,
                      source_faces_garage: bool = True) -> Game:
    """A Garage beside the Entrance Hall, with each of the door's two power
    routes switched on or off independently.

    ``source`` puts a Boiler Room -- the only power anywhere on this grid -- west
    of the Garage; ``source_faces_garage`` controls whether it carries the east
    door that completes the pair, so "a source is on the grid" and "the Garage is
    connected to it" can be told apart. ``breaker`` places the Utility Closet far
    from both and marks its cell entered, which is the whole of Game._breaker_on.
    Building both switches explicitly is what lets each route be proved on its
    own; a scenario that happened to satisfy both would prove neither.
    """
    g = _game(registry)
    g.state.steps = 50  # keep the doorstep affordable, so only the gate can close it
    _place(g, "garage", GARAGE_CELL, E | W)  # E joins the Entrance Hall, W the source
    if source:
        _place(g, "boiler_room", GARAGE_WEST, E if source_faces_garage else W)
    if breaker:
        _place(g, "utility_closet", MID_CELL, N | S)
        g.state.entered[g._utility_closet_cell()] = True
    return g


def test_garage_door_opens_on_the_breaker_with_no_power_on_the_grid(registry):
    """Breaker on and not one powered cell anywhere: the garage door still opens.

    The first of the ruling's two routes, proved with the second one impossible
    rather than merely absent -- no power source is placed at all, so a change
    that quietly made power a requirement would fail here.
    """
    g = _garage_door_game(registry, source=False, breaker=True)

    assert g._breaker_on() is True
    assert g._garage_powered() is False
    assert any(g.powered_map()) is False, "setup: this grid must carry no power"
    assert "garage_door_powered" in g._gate_ctx().flags
    assert g.area_route_cost("west_path") is not None


def test_garage_door_opens_on_power_with_the_breaker_off(registry):
    """A Boiler Room next door opens the garage door with no Utility Closet placed.

    The second of the ruling's two routes -- "or by connecting it to any powered
    room" -- proved with the breaker route impossible rather than merely off: the
    Utility Closet is not on the grid, so nothing could enter it.
    """
    g = _garage_door_game(registry, source=True, breaker=False)

    assert g._breaker_on() is False
    assert g._utility_closet_cell() == -1, "setup: no breaker box on this grid"
    assert g._garage_powered() is True
    assert "garage_door_powered" in g._gate_ctx().flags
    assert g.area_route_cost("west_path") is not None


def test_garage_door_stays_shut_when_neither_route_supplies_power(registry):
    """With no breaker and no power the door is shut and west_path is unreachable.

    The gate has to still be able to say no, or the two tests above would pass on
    a flag that was simply always set.
    """
    g = _garage_door_game(registry, source=False, breaker=False)

    assert g._breaker_on() is False
    assert g._garage_powered() is False
    assert "garage_door_powered" not in g._gate_ctx().flags
    assert g.area_route_cost("west_path") is None


def test_garage_door_power_route_needs_a_real_door_pair(registry):
    """A Boiler Room beside the Garage with its door facing the other way leaves
    the door shut.

    The power route is the door-graph connectivity of engine/power.py, not "a
    source exists somewhere": the same two rooms in the same two cells decide the
    gate differently depending only on the door masks.
    """
    g = _garage_door_game(registry, source=True, breaker=False,
                          source_faces_garage=False)

    assert g.cell_powered(GARAGE_WEST) is True, "the source is still a source"
    assert g._garage_powered() is False
    assert "garage_door_powered" not in g._gate_ctx().flags
    assert g.area_route_cost("west_path") is None


GARAGE_LEGAL_CELL = 20   # rank 5, col 0: one of the Garage's five legal tiles
GARAGE_FEED_CELL = 15    # rank 4, col 0: directly south of it


def test_the_power_route_is_reachable_at_a_legally_drafted_garage(registry):
    """A Boiler Room and a Garage in cells and orientations placement.py itself
    calls legal light the garage door.

    The tests above place rooms wherever the geometry reads most clearly, which
    would not catch the power route being impossible to actually draft: the
    Garage is confined to five West Wing tiles on ranks 4-8, entered heading
    north or west, and its dead-end floorplan has exactly one door -- so the
    only room that can ever feed it power is the one it was drafted from. This
    builds the pair through the drafter's own predicates, so the grid it asserts
    on is one a player could really reach.
    """
    g = _game(registry)
    garage = g.registry.by_id["garage"]
    boiler = g.registry.by_id["boiler_room"]
    st, cfg, placed = g.state, g.cfg, set(g.room_cells)

    assert satisfies_draft_conditions(garage, GARAGE_LEGAL_CELL, N, st, cfg, placed, False)
    garage_masks = legal_orientations(garage, GARAGE_LEGAL_CELL, N, st, cfg)
    assert garage_masks == [S], "the Garage's one door must face back the way it was drafted"

    assert satisfies_draft_conditions(boiler, GARAGE_FEED_CELL, S, st, cfg, placed, False)
    boiler_mask = next(m for m in legal_orientations(boiler, GARAGE_FEED_CELL, S, st, cfg)
                       if m & N)

    _place(g, "boiler_room", GARAGE_FEED_CELL, boiler_mask)
    _place(g, "garage", GARAGE_LEGAL_CELL, garage_masks[0])

    assert g._breaker_on() is False
    assert g._garage_powered() is True
    assert "garage_door_powered" in g._gate_ctx().flags
