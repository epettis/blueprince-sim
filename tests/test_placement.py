"""Placement legality: orientations, wings, corners, connectivity."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.grid import (E, N, S, W, is_center_column, is_corner,
                                        is_east_wing, is_west_wing, neighbor, rank_of,
                                        rotate_mask)
from blueprince_sim.engine.placement import legal_orientations, satisfies_draft_conditions
from blueprince_sim.engine.state import GameState


def test_rotate_mask():
    """rotate_mask spins door bits 90 degrees clockwise per step; a 4-way is
    rotation-invariant."""
    assert rotate_mask(N, 1) == E
    assert rotate_mask(N, 2) == S
    assert rotate_mask(N | S, 1) == E | W
    assert rotate_mask(N | E | S | W, 3) == N | E | S | W


def test_grid_helpers():
    """Grid geometry invariants: rank/neighbor lookups, off-grid edges
    returning -1, wing = single outer column, center columns, and corners."""
    assert rank_of(0) == 1 and rank_of(44) == 9
    assert neighbor(2, N) == 7 and neighbor(2, S) == -1
    assert neighbor(0, W) == -1 and neighbor(4, E) == -1
    # A wing is a single outer column: col 0 (west) / col 4 (east).
    assert is_west_wing(0) and not is_west_wing(1) and not is_west_wing(2)
    assert is_east_wing(4) and not is_east_wing(3)
    assert is_center_column(1) and is_center_column(2) and is_center_column(3)
    assert not is_center_column(0) and not is_center_column(4)
    assert is_corner(0) and is_corner(4) and is_corner(40) and is_corner(44)
    assert not is_corner(2) and not is_corner(22)


def test_orientation_requires_back_door(registry, cfg):
    """A drafted room must have a door facing back through the doorway it was
    drafted from, which pins each layout's legal orientations."""
    st = GameState()
    dead_end = registry.by_id["closet"]  # dead end
    # entering northward (entry_dir=N): needs a south-facing door
    masks = legal_orientations(dead_end, 22, N, st, cfg)
    assert masks == [S]
    straight = registry.by_id["corridor"]
    masks = legal_orientations(straight, 22, N, st, cfg)
    assert masks == [N | S]
    # entering eastward: straight must run E-W
    masks = legal_orientations(straight, 22, E, st, cfg)
    assert masks == [E | W]


def test_doors_cannot_face_outer_wall(registry, cfg):
    """No door may point into the outer wall: 4-way rooms are barred from
    edges and corner tiles admit only L-shapes / Dead Ends."""
    st = GameState()
    straight = registry.by_id["corridor"]
    # cell 4 = rank 1 SE corner, entered heading east (from cell 3): a straight
    # needs E|W, but the E door faces off-grid, so no orientation is legal.
    assert legal_orientations(straight, 4, E, st, cfg) == []
    # A 4-way room can never be drawn on an edge (a door always faces out).
    cross = registry.by_id["rotunda"]  # 4-Door
    assert legal_orientations(cross, 9, E, st, cfg) == []          # east edge
    assert legal_orientations(cross, 22, N, st, cfg) == [N | E | S | W]  # interior OK
    # A corner tile admits only L-shapes / Dead Ends. Cell 0 = SW corner,
    # entered heading south (from cell 5): back door is N (interior).
    dead_end = registry.by_id["closet"]
    assert legal_orientations(dead_end, 0, S, st, cfg) == [N]
    assert legal_orientations(straight, 0, S, st, cfg) == []       # straight can't fit


def test_wing_conditions(registry, cfg):
    """Wing-gated rooms: the Master Bedroom drafts only onto the East Wing,
    and Her Ladyship's Chamber only onto the West Wing heading south, never
    rank 1."""
    st = GameState()
    # A wing is a single edge column: col 0 (west) / col 4 (east).
    master = registry.by_id["master_bedroom"]  # East Wing only, any direction
    assert satisfies_draft_conditions(master, 24, N, st, cfg, set(), False)      # col 4
    assert not satisfies_draft_conditions(master, 23, N, st, cfg, set(), False)  # col 3 (not wing)
    assert not satisfies_draft_conditions(master, 20, N, st, cfg, set(), False)  # col 0
    ladyship = registry.by_id["her_ladyships_chamber"]  # west wing, drafted southward
    # Cell 5 = rank 2, col 0: drafting south (back door faces north) is legal.
    assert satisfies_draft_conditions(ladyship, 5, S, st, cfg, set(), False)
    assert not satisfies_draft_conditions(ladyship, 5, N, st, cfg, set(), False)  # wrong direction
    assert not satisfies_draft_conditions(ladyship, 9, S, st, cfg, set(), False)  # col 4, not west
    assert not satisfies_draft_conditions(ladyship, 0, S, st, cfg, set(), False)  # never Rank 1


def test_garage_placement(registry, cfg):
    """The Garage drafts only onto the West Wing at ranks 4-8, and only when
    heading north or west."""
    st = GameState()
    garage = registry.by_id["garage"]  # West Wing, Ranks 4-8, heading N or W only
    assert satisfies_draft_conditions(garage, 15, N, st, cfg, set(), False)      # col 0, rank 4
    assert satisfies_draft_conditions(garage, 35, W, st, cfg, set(), False)      # col 0, rank 8, westward
    assert not satisfies_draft_conditions(garage, 15, S, st, cfg, set(), False)  # southward barred
    assert not satisfies_draft_conditions(garage, 15, E, st, cfg, set(), False)  # eastward barred
    assert not satisfies_draft_conditions(garage, 10, N, st, cfg, set(), False)  # rank 3 too low
    assert not satisfies_draft_conditions(garage, 40, N, st, cfg, set(), False)  # rank 9 too high
    assert not satisfies_draft_conditions(garage, 19, N, st, cfg, set(), False)  # col 4, not west wing


def test_room8_placement(registry):
    """Room 8 requires Key 8 and drafts only onto rank 8, via east-wing
    northward or west-wing southward entries."""
    st = GameState()
    room8 = registry.by_id["room_8"]  # Key 8, onto Rank 8 via E-wing north / W-wing south
    keyed = GameConfig(satisfied_conditions=frozenset({"room8_key"}))
    assert satisfies_draft_conditions(room8, 35, S, st, keyed, set(), False)      # col 0 rank 8 south
    assert satisfies_draft_conditions(room8, 39, N, st, keyed, set(), False)      # col 4 rank 8 north
    assert not satisfies_draft_conditions(room8, 35, N, st, keyed, set(), False)  # west but northward
    assert not satisfies_draft_conditions(room8, 30, S, st, keyed, set(), False)  # rank 7, not 8
    assert not satisfies_draft_conditions(room8, 35, S, st, GameConfig(), set(), False)  # no Key 8


def test_wing_hall_and_hallway(registry, cfg):
    """West/East Wing Halls stick to their own wing and avoid the corners;
    the Hallway is confined to the center columns."""
    st = GameState()
    wwh = registry.by_id["west_wing_hall"]  # West Wing, no corners
    assert satisfies_draft_conditions(wwh, 20, N, st, cfg, set(), False)      # col 0, rank 5
    assert not satisfies_draft_conditions(wwh, 0, N, st, cfg, set(), False)   # SW corner
    assert not satisfies_draft_conditions(wwh, 24, N, st, cfg, set(), False)  # east wing
    ewh = registry.by_id["east_wing_hall"]  # East Wing, no corners
    assert satisfies_draft_conditions(ewh, 24, N, st, cfg, set(), False)      # col 4, rank 5
    assert not satisfies_draft_conditions(ewh, 4, N, st, cfg, set(), False)   # SE corner
    assert not satisfies_draft_conditions(ewh, 20, N, st, cfg, set(), False)  # west wing
    hall = registry.by_id["hallway"]  # center columns only (never on a wing)
    assert satisfies_draft_conditions(hall, 22, N, st, cfg, set(), False)     # col 2
    assert not satisfies_draft_conditions(hall, 20, N, st, cfg, set(), False)  # col 0 wing
    assert not satisfies_draft_conditions(hall, 24, N, st, cfg, set(), False)  # col 4 wing


def test_boiler_and_gift_shop(registry, cfg):
    """Boiler Room: never rank 1/9, west wing only southward, east wing only
    northward. Gift Shop: never rank 9 and never southward onto rank 1."""
    st = GameState()
    boiler = registry.by_id["boiler_room"]  # no rank 1/9; W-wing south, E-wing north
    assert satisfies_draft_conditions(boiler, 22, N, st, cfg, set(), False)      # center, any dir
    assert satisfies_draft_conditions(boiler, 20, S, st, cfg, set(), False)      # west wing southward
    assert not satisfies_draft_conditions(boiler, 20, N, st, cfg, set(), False)  # west wing northward
    assert satisfies_draft_conditions(boiler, 24, N, st, cfg, set(), False)      # east wing northward
    assert not satisfies_draft_conditions(boiler, 24, S, st, cfg, set(), False)  # east wing southward
    assert not satisfies_draft_conditions(boiler, 2, N, st, cfg, set(), False)   # rank 1
    assert not satisfies_draft_conditions(boiler, 42, S, st, cfg, set(), False)  # rank 9
    gift = registry.by_id["gift_shop"]  # never rank 9; not southward onto rank 1
    assert satisfies_draft_conditions(gift, 7, N, st, cfg, set(), False)         # rank 2
    assert not satisfies_draft_conditions(gift, 42, S, st, cfg, set(), False)    # rank 9
    assert not satisfies_draft_conditions(gift, 2, S, st, cfg, set(), False)     # rank 1 southward


def test_morning_room_direction(registry):
    """The Morning Room is breakfast-gated, and its fixed door sides bar
    northward drafts on the west wing and southward drafts on the east."""
    st = GameState()
    morning = registry.by_id["morning_room"]  # breakfast-gated + fixed door sides
    cfg = GameConfig(satisfied_conditions=frozenset({"breakfast"}))
    assert satisfies_draft_conditions(morning, 22, N, st, cfg, set(), False)      # center, any dir
    assert not satisfies_draft_conditions(morning, 20, N, st, cfg, set(), False)  # west wing northward
    assert satisfies_draft_conditions(morning, 20, S, st, cfg, set(), False)      # west wing southward
    assert not satisfies_draft_conditions(morning, 24, S, st, cfg, set(), False)  # east wing southward
    assert not satisfies_draft_conditions(morning, 22, N, st, GameConfig(), set(), False)  # no breakfast


def test_no_north_on_wing_studio_rooms(registry, cfg):
    """no_north_on_wing rooms: the Clock Tower bars northward wing drafts
    (corners exempt); the Solarium additionally bars horizontal drafts on
    ranks 1 and 9."""
    st = GameState()
    clock = registry.by_id["clock_tower"]  # no northward draft on a wing (corners OK)
    assert not satisfies_draft_conditions(clock, 20, N, st, cfg, set(), False)  # col 0, northward
    assert satisfies_draft_conditions(clock, 20, S, st, cfg, set(), False)      # col 0, southward OK
    assert satisfies_draft_conditions(clock, 0, N, st, cfg, set(), False)       # SW corner exempt
    assert satisfies_draft_conditions(clock, 22, N, st, cfg, set(), False)      # center, northward OK
    assert not satisfies_draft_conditions(clock, 24, N, st, cfg, set(), False)  # col 4, northward

    sol = registry.by_id["solarium"]  # also no horizontal draft on Rank 1/9 (corners OK)
    assert not satisfies_draft_conditions(sol, 20, N, st, cfg, set(), False)    # wing northward
    assert not satisfies_draft_conditions(sol, 2, E, st, cfg, set(), False)     # rank 1, eastward
    assert not satisfies_draft_conditions(sol, 42, W, st, cfg, set(), False)    # rank 9, westward
    assert satisfies_draft_conditions(sol, 0, E, st, cfg, set(), False)         # SW corner exempt
    assert satisfies_draft_conditions(sol, 2, N, st, cfg, set(), False)         # rank 1, vertical OK
    assert satisfies_draft_conditions(sol, 7, E, st, cfg, set(), False)         # rank 2 interior, any dir


def test_outer_wall_green_rooms(registry, cfg):
    """Terrace, Patio, Veranda and Greenhouse must sit against the west/east
    outer wall; the Greenhouse additionally avoids the corners."""
    st = GameState()
    # Terrace, Patio, Veranda and Greenhouse must sit against the west or east
    # outer wall (a wing is one edge column: col 0 or col 4).
    for rid in ("terrace", "patio", "veranda", "greenhouse"):
        room = registry.by_id[rid]
        assert satisfies_draft_conditions(room, 20, N, st, cfg, set(), False), rid   # col 0, rank 5
        assert satisfies_draft_conditions(room, 24, N, st, cfg, set(), False), rid   # col 4, rank 5
        # Interior columns 1, 2, 3 are inside the house, not on the outer wall.
        assert not satisfies_draft_conditions(room, 21, N, st, cfg, set(), False), rid
        assert not satisfies_draft_conditions(room, 22, N, st, cfg, set(), False), rid
        assert not satisfies_draft_conditions(room, 23, N, st, cfg, set(), False), rid
    # The Greenhouse additionally cannot appear on the corners.
    green = registry.by_id["greenhouse"]
    assert not satisfies_draft_conditions(green, 0, N, st, cfg, set(), False)    # SW corner
    assert not satisfies_draft_conditions(green, 40, S, st, cfg, set(), False)   # NW corner


def test_courtyard_interior_only(registry, cfg):
    """The Courtyard is interior-only: the whole perimeter (both wings and
    ranks 1/9) is rejected, since its T-shape could otherwise rotate a door
    into any outer wall."""
    st = GameState()
    court = registry.by_id["courtyard"]  # T-shape, must be drafted inside the mansion
    assert satisfies_draft_conditions(court, 22, N, st, cfg, set(), False)  # rank 5, col 2: interior
    assert satisfies_draft_conditions(court, 6, N, st, cfg, set(), False)   # rank 2, col 1: interior
    # A T-shape can rotate its missing door against any outer wall, so the
    # whole perimeter must be rejected: west/east edges and ranks 1 & 9.
    assert not satisfies_draft_conditions(court, 20, N, st, cfg, set(), False)  # col 0 (west wall)
    assert not satisfies_draft_conditions(court, 24, N, st, cfg, set(), False)  # col 4 (east wall)
    assert not satisfies_draft_conditions(court, 2, N, st, cfg, set(), False)   # rank 1 (south wall)
    assert not satisfies_draft_conditions(court, 42, N, st, cfg, set(), False)  # rank 9 (north wall)


def test_pool_and_library_conditions(registry, cfg):
    """Draft prerequisites: the Pump Room needs The Pool placed, the Bookshop
    deals only when drafting from the Library, and the Closet can never be
    drafted from the Library."""
    st = GameState()
    pump = registry.by_id["pump_room"]  # Pool Drafted
    assert not satisfies_draft_conditions(pump, 22, N, st, cfg, set(), False)
    assert satisfies_draft_conditions(pump, 22, N, st, cfg, {"the_pool"}, False)
    bookshop = registry.by_id["bookshop"]  # only from Library
    assert not satisfies_draft_conditions(bookshop, 22, N, st, cfg, set(), False)
    assert satisfies_draft_conditions(bookshop, 22, N, st, cfg, set(), True)
    closet = registry.by_id["closet"]  # cannot draft FROM library
    assert not satisfies_draft_conditions(closet, 22, N, st, cfg, set(), True)
    assert satisfies_draft_conditions(closet, 22, N, st, cfg, set(), False)


def test_tunnel_north_south_only(registry, cfg):
    """The Tunnel drafts only through north/south doorways and only onto
    ranks 2-8."""
    st = GameState()
    tunnel = registry.by_id["tunnel"]  # straight, north_south_only + rank_gte_2 + rank_lte_8
    # Interior cell, rank 5, col 2: N or S entry is legal.
    assert satisfies_draft_conditions(tunnel, 22, N, st, cfg, set(), False)
    assert satisfies_draft_conditions(tunnel, 22, S, st, cfg, set(), False)
    # E or W entry is rejected by north_south_only.
    assert not satisfies_draft_conditions(tunnel, 22, E, st, cfg, set(), False)
    assert not satisfies_draft_conditions(tunnel, 22, W, st, cfg, set(), False)
    # Rank gates: rank 1 and rank 9 are excluded.
    assert not satisfies_draft_conditions(tunnel, 2, N, st, cfg, set(), False)   # rank 1
    assert not satisfies_draft_conditions(tunnel, 42, S, st, cfg, set(), False)  # rank 9


def test_gated_conditions_via_config(registry):
    """Item-gated conditions come from the config: the Secret Garden needs its
    key in satisfied_conditions and is confined to a wing within ranks 3-8."""
    st = GameState()
    garden = registry.by_id["secret_garden"]
    # Cell 20 = rank 5, col 0: a west-wing tile within the rank 3-8 band.
    assert not satisfies_draft_conditions(garden, 20, N, st, GameConfig(), set(), False)
    cfg2 = GameConfig(satisfied_conditions=frozenset({"secret_garden_key"}))
    assert satisfies_draft_conditions(garden, 20, N, st, cfg2, set(), False)
    # Key-gated to the west/east wing between ranks 3 and 8.
    assert not satisfies_draft_conditions(garden, 0, N, st, cfg2, set(), False)   # rank 1 too low
    assert not satisfies_draft_conditions(garden, 40, N, st, cfg2, set(), False)  # rank 9 too high
    assert not satisfies_draft_conditions(garden, 22, N, st, cfg2, set(), False)  # col 2, not a wing
