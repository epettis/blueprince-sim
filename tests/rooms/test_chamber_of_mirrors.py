"""Chamber of Mirrors: waives the one-copy-per-room rule for every room, once placed.

draft.py::room_draftable checks the literal room id "chamber_of_mirrors"
against placed_ids -- the duplicate-allowing rule is already keyed by room
id there, independently of any effect tag, so this exercises it directly.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, room_draftable
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

# A lone interior target cell (rank 3, col 2), reached moving south -- mirrors
# tests/rooms/test_the_kennel.py's cell so door-geometry legality is never the
# reason a room is rejected here.
TARGET_CELL = 12
DIRECTION = S


def test_duplicate_room_blocked_without_chamber_of_mirrors(registry):
    """A room already on the grid cannot be dealt a second time when the
    Chamber of Mirrors is not among the placed rooms."""
    closet = registry.by_id["closet"]
    ctx = DraftContext(GameState(), registry, GameConfig(), Rng(0), {"closet"}, None)
    assert not room_draftable(ctx, closet, TARGET_CELL, DIRECTION, set())


def test_duplicate_room_allowed_once_chamber_of_mirrors_is_placed(registry):
    """The same duplicate becomes draftable once the Chamber of Mirrors is
    also among the placed rooms -- the rule is house-wide, not specific to
    the Chamber of Mirrors drafting a second copy of itself."""
    closet = registry.by_id["closet"]
    ctx = DraftContext(GameState(), registry, GameConfig(), Rng(0),
                       {"closet", "chamber_of_mirrors"}, None)
    assert room_draftable(ctx, closet, TARGET_CELL, DIRECTION, set())


def test_chamber_of_mirrors_carries_no_data_effects(registry):
    """The Chamber of Mirrors' own record carries no effect tags -- its
    behaviour lives entirely in draft.py's room-id check above."""
    assert registry.by_id["chamber_of_mirrors"].effects == ()
