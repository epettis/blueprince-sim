"""Placement legality: orientations, wings, corners, connectivity."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.grid import (E, N, S, W, is_corner, is_east_wing,
                                        is_west_wing, neighbor, rank_of, rotate_mask)
from blueprince_sim.engine.placement import legal_orientations, satisfies_draft_conditions
from blueprince_sim.engine.state import GameState


def test_rotate_mask():
    assert rotate_mask(N, 1) == E
    assert rotate_mask(N, 2) == S
    assert rotate_mask(N | S, 1) == E | W
    assert rotate_mask(N | E | S | W, 3) == N | E | S | W


def test_grid_helpers():
    assert rank_of(0) == 1 and rank_of(44) == 9
    assert neighbor(2, N) == 7 and neighbor(2, S) == -1
    assert neighbor(0, W) == -1 and neighbor(4, E) == -1
    assert is_west_wing(0) and is_west_wing(1) and not is_west_wing(2)
    assert is_east_wing(3) and is_east_wing(4)
    assert is_corner(0) and is_corner(4) and is_corner(40) and is_corner(44)
    assert not is_corner(2) and not is_corner(22)


def test_orientation_requires_back_door(registry, cfg):
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
    st = GameState()
    garage = registry.by_id["garage"]  # West Wing only
    assert satisfies_draft_conditions(garage, 0, N, st, cfg, set(), False)
    assert not satisfies_draft_conditions(garage, 4, N, st, cfg, set(), False)
    master = registry.by_id["master_bedroom"]  # East Wing only
    assert satisfies_draft_conditions(master, 4, N, st, cfg, set(), False)
    assert not satisfies_draft_conditions(master, 0, N, st, cfg, set(), False)
    ladyship = registry.by_id["her_ladyships_chamber"]  # west wing, south-facing door
    assert satisfies_draft_conditions(ladyship, 5, N, st, cfg, set(), False)
    assert not satisfies_draft_conditions(ladyship, 5, E, st, cfg, set(), False)


def test_pool_and_library_conditions(registry, cfg):
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


def test_gated_conditions_via_config(registry):
    st = GameState()
    garden = registry.by_id["secret_garden"]
    assert not satisfies_draft_conditions(garden, 0, N, st, GameConfig(), set(), False)
    cfg2 = GameConfig(satisfied_conditions=frozenset({"secret_garden_key"}))
    assert satisfies_draft_conditions(garden, 0, N, st, cfg2, set(), False)
