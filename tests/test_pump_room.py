"""The Pump Room's water-level system (docs/areas.md's Pump Room section).

The macro action ("set source to level", assumed-solved doctrine) is a
factored two-step menu: pick a water source (PUMP_SOURCE_BASE, 6 ids), then
pick its target level (PUMP_LEVEL_BASE, 15 ids, Phase.PUMP_LEVEL_PENDING).
Grouped in its own file, the same shape as tests/test_gear_wrench.py/
tests/test_the_axe.py, since the mechanic touches several concerns at once: a
new engine phase/action range, a non-bool carry-over channel threaded through
DayChain (including the attempt wrap), an observation key, and the three area
gates the six levels drive (pump_water_lte8/rowboat_water_6/fountain_water_0,
live checks every traversal) plus the fourth (reservoir_water_13, latched
permanent once set).
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects.rooms import pump_room as pump_room_data
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import ENTRANCE_CELL
from blueprince_sim.env.actions import (
    N_ACTIONS,
    PUMP_LEVEL_BASE,
    PUMP_SOURCE_BASE,
    SPREAD_GOLD_ACTION,
    _build_pump_source_ids,
    action_mask,
    apply_action,
)
from blueprince_sim.env.multiday import DayChain

PUMP_ROOM_CELL = 7  # rank 2 centre; arbitrary -- these tests bypass drafting/walking


def _stand_at_pump_room(game: Game, registry, cell: int = PUMP_ROOM_CELL) -> None:
    """Place the Pump Room at ``cell`` (idempotent) and move the player there.

    Bypasses drafting/walking, the same shortcut test_locks.py's own
    Security/Utility Closet capability tests use (``g._place_room`` + a
    direct ``state.pos`` write). Does not connect the cell's doors to the
    rest of the grid -- callers that need a real ``area_route_cost`` reading
    afterward must move ``state.pos`` back to ``ENTRANCE_CELL`` themselves
    (see ``_set_pump_level``), since this cell is not door-connected to it.
    """
    if game.state.grid[cell] < 0:
        room = registry.by_id["pump_room"]
        game._place_room(room, cell, room.door_mask)
    game.state.pos = cell


def _set_pump_level(game: Game, registry, source_id: str, level: int,
                    cell: int = PUMP_ROOM_CELL) -> None:
    """Operate the panel to set ``source_id`` to ``level``, then return the
    player to ENTRANCE_CELL so a subsequent on-grid ``area_route_cost`` call
    measures a real, door-connected route rather than tripping over the
    isolated Pump Room cell placed by ``_stand_at_pump_room``."""
    _stand_at_pump_room(game, registry, cell)
    game.set_pump_source(source_id)
    game.set_pump_level(level)
    game.state.pos = ENTRANCE_CELL


def _sources(registry) -> dict[str, pump_room_data.PumpSource]:
    return {s.id: s for s in pump_room_data.load_sources(registry.data_dir)}


# ---------------------------------------------------------------------------
# 1. Each source clamps to its own min/max
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_id", [
    "aquarium", "fountain", "greenhouse", "kitchen", "pool", "reservoir",
])
def test_each_source_clamps_to_its_own_min_max(source_id, registry):
    """set_pump_level accepts exactly [min, max] for the chosen source and
    rejects one step outside either bound, per data/pump_room.json -- proving
    the six sources are genuinely independent ranges, not one shared 0..14."""
    src = _sources(registry)[source_id]
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_pump_room(g, registry)

    g.set_pump_source(source_id)
    assert g.phase is Phase.PUMP_LEVEL_PENDING
    assert g.can_set_pump_level(src.min) is True
    assert g.can_set_pump_level(src.max) is True
    if src.min > 0:
        assert g.can_set_pump_level(src.min - 1) is False
    if src.max < 14:
        assert g.can_set_pump_level(src.max + 1) is False

    g.set_pump_level(src.max)
    assert g.water_level(source_id) == src.max
    assert g.phase is Phase.NAVIGATE
    assert g.state.pending_pump_source is None


def test_reservoir_floors_at_2_not_0(registry):
    """The Reservoir is the one source whose min is 2, not 0 (the wiki: 'the
    Reservoir...cannot be drained below water level 2') -- 0 and 1 are both
    illegal picks, unlike every other source."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_pump_room(g, registry)
    g.set_pump_source("reservoir")
    assert g.can_set_pump_level(0) is False
    assert g.can_set_pump_level(1) is False
    assert g.can_set_pump_level(2) is True
    g.set_pump_level(2)
    assert g.water_level("reservoir") == 2


def test_fresh_save_levels_match_data_file_initial_values(registry):
    """A never-touched Game reports each source at data/pump_room.json's own
    "initial" value (Fountain 12, Reservoir 14, Aquarium 6, Kitchen 0,
    Greenhouse 1, Pool 8) -- water_level's fallback path, not state.water_levels
    (which starts empty)."""
    g = Game(GameConfig(), seed=0, registry=registry)
    assert g.state.water_levels == {}
    expected = {"aquarium": 6, "fountain": 12, "greenhouse": 1,
                "kitchen": 0, "pool": 8, "reservoir": 14}
    for source_id, level in expected.items():
        assert g.water_level(source_id) == level


# ---------------------------------------------------------------------------
# 2. Day-boundary carry-over: levels persist, the selected source does not
# ---------------------------------------------------------------------------


def test_levels_survive_a_day_boundary(registry):
    """A level set on day 1 is still in effect on day 2's fresh Game, via
    DayChain's non-bool water_levels channel (NOT _CARRYOVER_KEYS, which is
    bool-only) -- GameConfig.water_levels/DayChain.next_config/advance."""
    chain = DayChain(GameConfig(), n_days=200)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    _stand_at_pump_room(g1, registry)
    g1.set_pump_source("greenhouse")
    g1.set_pump_level(5)
    assert g1.water_level("greenhouse") == 5

    chain.advance(g1.carryover())
    cfg_day2 = chain.next_config()
    assert cfg_day2.water_levels.get("greenhouse") == 5

    g2 = Game(cfg_day2, seed=2, registry=registry)
    assert g2.water_level("greenhouse") == 5


def test_selected_source_does_not_survive_a_day_boundary(registry):
    """Picking a source (entering PUMP_LEVEL_PENDING) without completing the
    level pick leaves no trace in tomorrow's config -- only the six levels
    are carried, never which source was mid-selection or the phase itself
    (the wiki: 'the selected source...will reset each day')."""
    chain = DayChain(GameConfig(), n_days=200)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    _stand_at_pump_room(g1, registry)
    g1.set_pump_source("kitchen")
    assert g1.phase is Phase.PUMP_LEVEL_PENDING
    assert g1.state.pending_pump_source == "kitchen"

    chain.advance(g1.carryover())
    cfg_day2 = chain.next_config()
    assert cfg_day2.water_levels == {}  # no level was ever actually set

    g2 = Game(cfg_day2, seed=2, registry=registry)
    assert g2.phase is Phase.NAVIGATE
    assert g2.state.pending_pump_source is None
    assert g2.water_level("kitchen") == 0  # back to data/pump_room.json's initial


# ---------------------------------------------------------------------------
# 3. Each gate opens and closes at its real threshold
# ---------------------------------------------------------------------------


def test_pump_water_lte8_opens_and_closes_at_the_threshold(registry):
    """Grounds -> Well: legal exactly while Fountain <= 8, re-checked live
    (not latched) -- moving the Fountain back above 8 closes it again."""
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.steps = 50
    assert g.water_level("fountain") == 12  # fresh-save default
    assert g.area_route_cost("well") is None

    _set_pump_level(g, registry, "fountain", 8)
    assert g.area_route_cost("well") is not None

    _set_pump_level(g, registry, "fountain", 9)
    assert g.area_route_cost("well") is None


def test_rowboat_water_6_opens_only_at_exactly_6(registry):
    """Reservoir South <-> Safehouse: legal only at Reservoir == 6, not <= or
    >= -- both 5 and 7 must stay closed, unlike pump_water_lte8's <= rule."""
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.inventory["basement_key"] = 1
    g.state.steps = 50
    # Open well -> reservoir_south first (basement_key + Fountain at 0) so
    # reservoir_south itself is reachable and the rowboat gate is on trial
    # in isolation.
    _set_pump_level(g, registry, "fountain", 0)
    assert g.area_route_cost("reservoir_south") is not None  # sanity

    for level, expect_open in ((5, False), (6, True), (7, False)):
        _set_pump_level(g, registry, "reservoir", level)
        result = g.area_route_cost("safehouse")
        assert (result is not None) is expect_open, f"level={level}"


def test_well_to_reservoir_south_is_re_checked_every_traversal(registry):
    """well -> reservoir_south needs the Fountain at 0 on TOP of the permanent
    basement_key_well unlock, re-checked on every traversal rather than
    latched once passed -- holding the key is not enough once the Fountain is
    raised back above 0, and the route re-opens the moment it is lowered
    again."""
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.inventory["basement_key"] = 1
    g.state.steps = 50

    # Fountain at 8 clears the FIRST gate (grounds -> well) but not the
    # second -- isolates fountain_water_0 from pump_water_lte8.
    _set_pump_level(g, registry, "fountain", 8)
    assert g.area_route_cost("well") is not None
    assert g.area_route_cost("reservoir_south") is None, (
        "basement_key alone must not be enough while the Fountain sits above 0"
    )

    _set_pump_level(g, registry, "fountain", 0)
    assert g.area_route_cost("reservoir_south") is not None

    _set_pump_level(g, registry, "fountain", 3)
    assert g.area_route_cost("well") is not None  # first gate still open (<= 8)
    assert g.area_route_cost("reservoir_south") is None, (
        "raising the Fountain back above 0 must close the passage again -- not latched"
    )

    _set_pump_level(g, registry, "fountain", 0)
    assert g.area_route_cost("reservoir_south") is not None, (
        "lowering the Fountain back to 0 must re-open it"
    )


def test_reservoir_water_13_is_permanent_once_set(registry):
    """Reservoir North <-> Reservoir South opens the first time the Reservoir
    is set to exactly 13, and -- UNLIKE the three gates above -- stays open
    even after the level later moves away from 13 (docs/areas.md)."""
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.sealed_entrance_broken = True  # free house->...->basement->reservoir_north
    g.state.steps = 50
    assert g.area_route_cost("reservoir_north") is not None  # sanity
    assert g.area_route_cost("reservoir_south") is None

    _set_pump_level(g, registry, "reservoir", 13)
    assert g.state.reservoir_13_reached is True
    assert g.area_route_cost("reservoir_south") is not None

    # Move the level away from 13 -- the crossing must stay open.
    _set_pump_level(g, registry, "reservoir", 6)
    assert g.water_level("reservoir") == 6
    assert g.area_route_cost("reservoir_south") is not None, (
        "reservoir_water_13 must latch permanently, not re-check the live level"
    )


def test_reservoir_water_13_flag_carries_across_a_day_boundary(registry):
    """Once the Reservoir has been set to 13, the crossing stays open on a
    LATER day too (state.reservoir_13_reached -> cfg.reservoir_13_reached via
    DayChain._CARRYOVER_KEYS), even though the carried level moves away from
    13 in the meantime (a fresh Game only ever sees the CURRENT level, never
    the history) -- the permanence lives in the separate boolean flag, not in
    water_levels itself."""
    chain = DayChain(GameConfig(), n_days=200)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    _stand_at_pump_room(g1, registry)
    g1.set_pump_source("reservoir")
    g1.set_pump_level(13)
    chain.advance(g1.carryover())

    cfg_day2 = chain.next_config()
    assert cfg_day2.reservoir_13_reached is True
    assert cfg_day2.water_levels.get("reservoir") == 13
    g2 = Game(cfg_day2, seed=2, registry=registry)
    g2.state.sealed_entrance_broken = True
    g2.state.steps = 50
    assert g2.area_route_cost("reservoir_south") is not None


# ---------------------------------------------------------------------------
# 4. Reachability before/after choosing the Reservoir levels (the sequencing
#    trap docs/areas.md's Pump Room section and areas.json's old
#    reservoir_water_13 note both flag: an OPEN crossing walks around
#    basement_key_well)
# ---------------------------------------------------------------------------


def test_reservoir_loophole_reachability_before_and_after_choosing_the_levels(registry):
    """Reproduces the exact loophole areas.json's reservoir_water_13 note
    measured (house->reservoir_south=5, house->mine_south=6,
    house->safehouse=6 with an empty inventory) -- but proves it now requires
    the player to actually operate the Pump Room panel, twice, rather than
    being a free default state.

    BEFORE: empty inventory, only sealed_entrance_broken set (the free
    house->grounds->sealed_entrance->basement->reservoir_north route) --
    reservoir_south/mine_south/safehouse are all unreachable, because
    reservoir_water_13 defaults closed and rowboat_water_6 needs the live
    Reservoir at exactly 6 (fresh-save default is 14).

    AFTER: the SAME empty-inventory state, but the Reservoir has been set to
    13 (permanently opening reservoir_north<->reservoir_south) and then to 6
    (satisfying rowboat_water_6's live check too) -- both nodes and safehouse
    become reachable, at the SAME hop counts the old stub-open data measured.
    """
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.sealed_entrance_broken = True
    g.state.steps = 50

    before = g.area_route_costs()
    assert "reservoir_south" not in before
    assert "mine_south" not in before
    assert "safehouse" not in before

    _set_pump_level(g, registry, "reservoir", 13)
    _set_pump_level(g, registry, "reservoir", 6)

    after = g.area_route_costs()
    assert after["reservoir_south"][0] == 5
    assert after["mine_south"][0] == 6
    assert after["safehouse"][0] == 6


# ---------------------------------------------------------------------------
# 5. The action layer: mask/apply_action wiring end to end
# ---------------------------------------------------------------------------


def test_action_layer_selects_a_source_then_a_level(registry):
    """The full flat-action path (action_mask/apply_action) drives the same
    macro two-step menu as the direct Game API: PUMP_SOURCE_BASE picks a
    source, PUMP_LEVEL_BASE (masked to that source's own range) sets the
    level."""
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_pump_room(g, registry)

    mask = action_mask(g)
    source_ids = _build_pump_source_ids(g.registry)
    pool_idx = source_ids.index("pool")
    for i in range(len(source_ids)):
        assert mask[PUMP_SOURCE_BASE + i] is True

    apply_action(g, PUMP_SOURCE_BASE + pool_idx)
    assert g.phase is Phase.PUMP_LEVEL_PENDING
    assert g.state.pending_pump_source == "pool"

    mask = action_mask(g)
    assert mask[PUMP_LEVEL_BASE + 9] is True   # Pool's own max
    assert mask[PUMP_LEVEL_BASE + 10] is False  # one past Pool's max

    apply_action(g, PUMP_LEVEL_BASE + 9)
    assert g.phase is Phase.NAVIGATE
    assert g.water_level("pool") == 9


def test_pump_level_pending_never_dead_ends(registry):
    """Every id in the PUMP_LEVEL_BASE block agrees with the Office terminal
    block's own start (no reserved-but-unmasked tail -- SPREAD_GOLD_ACTION is
    N_ACTIONS's own end minus 2 now that the Office terminal block appended
    two more ids after the Pump Room panel), and at least one level is always
    legal in PUMP_LEVEL_PENDING -- the source's current level is always in
    its own range, so this phase can never mask every id False."""
    assert PUMP_LEVEL_BASE + 15 == SPREAD_GOLD_ACTION
    g = Game(GameConfig(), seed=0, registry=registry)
    _stand_at_pump_room(g, registry)
    g.set_pump_source("aquarium")
    mask = action_mask(g)
    assert any(mask[PUMP_LEVEL_BASE:N_ACTIONS])
