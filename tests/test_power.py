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
