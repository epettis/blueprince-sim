"""On-grid travel to an anchor must obey MOVE_TO's "purposefulness" rule.

On grid, ``env/actions.py``'s MOVE_TO loop already refuses to walk into an
already-entered, non-re-enterable cell. The travel loop (TRAVEL_BASE + i)
applies the same rule -- via ``_cell_worth_entering`` -- to on-grid travel to
a grid anchor (house/garage/the_foundation), not just destinations whose
route cost is 0; otherwise the mask would offer a pointless round trip to a
cell the player has already fully drained. Off-grid anchor travel (the only
way back onto the grid) and every non-anchor destination stay unconditional.
"""

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.env import actions as A
from blueprince_sim.rl.train import all_unlocks_config


def _corridor(registry):
    return registry.by_id["corridor"]


def _garage(registry):
    return next(r for r in registry.rooms if r.id.startswith("garage"))


def test_travel_to_house_suppressed_when_eh_already_drained(registry):
    """On grid, two rooms from home, with the Entrance Hall already entered
    and holding no re-enterable feature, TRAVEL[house] must NOT be offered --
    and it must agree with MOVE_TO[entrance_hall], which was already refusing
    the same walk. Reproduces the run #25,195 pattern: a mask-advertised
    round trip to a cell with nothing left to gain.
    """
    g = Game(GameConfig(door_locks=False), seed=9, registry=registry)
    corridor = _corridor(registry)
    # Door convention (grid.py): N=toward rank 9, S=toward rank 1 (the Entrance
    # Hall). Cell 7 (rank 2) needs both: S to reach EH, N to reach cell 12.
    g._place_room(corridor, 7, N | S)   # rank2 c2: connects EH (S) to cell 12 (N)
    g._place_room(corridor, 12, S)      # rank3 c2: dead end, two rooms from home
    g.state.pos = 12
    assert g.distance_map()[2] == 2, "setup: player must be exactly two rooms from EH"

    mask = A.action_mask(g)
    node_ids = A._build_area_node_ids(g.registry)
    house_idx = node_ids.index("house")
    assert not mask[A.TRAVEL_BASE + house_idx], "travel to house should be suppressed"
    assert not mask[A.MOVE_TO_BASE + 2], "walking straight to EH should already be suppressed"


def test_travel_to_house_offered_off_grid():
    """Off grid, TRAVEL[house] must stay offered unconditionally.

    This is the anti-stranding guard: off grid, travelling to a grid anchor
    is the only way back onto the grid, so the purposefulness filter must
    not apply there even though the Entrance Hall itself is fully drained.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.off_grid
    mask = A.action_mask(g)
    node_ids = A._build_area_node_ids(g.registry)
    house_idx = node_ids.index("house")
    assert mask[A.TRAVEL_BASE + house_idx], "travel to house must stay legal off-grid"


def test_travel_to_garage_offered_while_unentered(registry):
    """A placed-but-unentered Garage is still worth walking to, so on-grid
    TRAVEL[garage] stays offered -- the filter must not block first entry.
    """
    g = Game(GameConfig(), seed=9, registry=registry)
    garage = _garage(registry)
    g._place_room(garage, 1, E | W)  # cell 1, east door connects to EH cell 2
    garage_cell = g._garage_cell()
    assert not g.state.entered[garage_cell]

    mask = A.action_mask(g)
    node_ids = A._build_area_node_ids(g.registry)
    garage_idx = node_ids.index("garage")
    assert mask[A.TRAVEL_BASE + garage_idx], "unentered garage must stay a legal travel target"


def test_travel_to_garage_suppressed_once_drained(registry):
    """Once the Garage is entered and nothing about it is re-enterable
    (no car trunk item, no special items), on-grid TRAVEL[garage] must be
    suppressed -- the same round-trip bug the Entrance Hall case pins.
    """
    g = Game(GameConfig(), seed=9, registry=registry)
    garage = _garage(registry)
    g._place_room(garage, 1, E | W)
    garage_cell = g._garage_cell()
    g.state.entered[garage_cell] = True

    mask = A.action_mask(g)
    node_ids = A._build_area_node_ids(g.registry)
    garage_idx = node_ids.index("garage")
    assert not mask[A.TRAVEL_BASE + garage_idx], "drained garage must not be a travel target"


def test_non_anchor_destination_unaffected(registry):
    """A non-anchor area destination (west_path) is never gated on
    _cell_worth_entering -- it has no grid cell of its own, so the filter
    must only ever touch the three modelled grid anchors. Also pins that
    west_path really is a non-anchor node, so a future change to
    _grid_anchors() can't make this assertion vacuous.
    """
    g = Game(GameConfig(west_gate_unlatched=True), seed=1, registry=registry)
    assert "west_path" not in g._grid_anchors(), "setup: west_path must be a non-anchor node"
    node_ids = A._build_area_node_ids(g.registry)
    i = node_ids.index("west_path")
    assert g.area_route_cost("west_path") is not None, "setup: must be reachable"
    mask = A.action_mask(g)
    assert mask[A.TRAVEL_BASE + i], "west_path travel must be unaffected by the anchor filter"


def test_anchor_travel_agrees_with_cell_worth_entering_under_random_play(registry):
    """Property: across many states reached by masked random play, whenever
    on-grid TRAVEL to a modelled grid anchor is offered, _cell_worth_entering
    independently agrees the anchor's cell is worth entering.

    Under the fix, nearly every naturally-occurring anchor-travel opportunity
    in random play is (correctly) suppressed -- the Entrance Hall is visited
    turn one and never re-enterable, so "house" is the dominant repro of the
    original bug. "opportunities" (a nonzero-cost route existed) is tracked
    separately from the implication check so the test proves it actually
    exercised many real states instead of passing vacuously; the implication
    itself is what a reverted fix breaks, since the pre-fix mask offered
    every one of those opportunities regardless of _cell_worth_entering.
    """
    cfg = all_unlocks_config()
    node_ids = A._build_area_node_ids(registry)
    opportunities = 0
    for seed in range(40):
        g = Game(cfg, seed=seed, registry=registry)
        rnd = random.Random(seed)
        steps_taken = 0
        while g.phase is not Phase.TERMINAL and steps_taken < 300:
            mask = A.action_mask(g)
            if g.phase is Phase.NAVIGATE and not g.off_grid:
                route_costs = g.area_route_costs()
                for node_id, cell in g._grid_anchors().items():
                    result = route_costs.get(node_id)
                    if result is None or result[0] == 0:
                        continue
                    opportunities += 1
                    i = node_ids.index(node_id)
                    if mask[A.TRAVEL_BASE + i]:
                        assert A._cell_worth_entering(g, cell), (
                            f"seed={seed} anchor={node_id} cell={cell} "
                            "offered by TRAVEL but not worth entering"
                        )
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            A.apply_action(g, rnd.choice(legal))
            steps_taken += 1
    assert opportunities > 0, "setup: no anchor-travel opportunity ever arose to check"
