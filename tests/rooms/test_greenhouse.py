"""Greenhouse: the Broken Lever machine (south Antechamber segment) and the
Power Hammer wall break gating its corner-layout rotations
(docs/scoping-and-carryover.md).

See tests/test_antechamber_levers.py for the cross-cutting lever-gate
invariants (coverage for the pre-existing broken_lever path), and
tests/test_ignition.py for the broken_lever item's generic consumption rules,
shared by any machine room.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, segment_key


def test_greenhouse_lever_still_opens_south(registry):
    """Installing a Broken Lever in the Greenhouse still opens the south segment
    (37, N), with antechamber_levers=True, exactly as before."""
    g = Game(GameConfig(antechamber_levers=True,
                        starting_items=frozenset({"broken_lever"})), seed=1, registry=registry)
    # Place the Greenhouse in a wing position (it requires west_or_east_wing)
    greenhouse = g.registry.by_id["greenhouse"]
    g._place_room(greenhouse, 5, E | W | N | S & greenhouse.door_mask)
    g.state.pos = 5
    g.state.entered[5] = True

    # Even though segment starts SEALED, install_lever opens it via _open_segment
    assert si.can_install_lever(g)
    si.install_lever(g)

    assert g.door_state_of(ANTECHAMBER_CELL, S) == DOOR_OPEN


def test_greenhouse_lever_opens_antechamber_south_segment():
    """Installing the lever in the Greenhouse sets the Antechamber's south doorway to DOOR_OPEN.

    That doorway is the rank-8-centre (cell 37) to Antechamber (cell 42) segment:
    the Antechamber's own south door, since segment_key(42, S) == segment_key(37, N).
    """
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)

    # The Antechamber's south door and cell 37's north door are one segment.
    seg = segment_key(37, N)
    assert seg == segment_key(ANTECHAMBER_CELL, S), "lever must target the Antechamber's south door"
    # Force it locked so the unlock is observable rather than incidental.
    g.state.door_state[seg] = DOOR_LOCKED

    # Place the greenhouse at a reachable cell and stand there
    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    assert si.can_install_lever(g)
    si.install_lever(g)
    assert g.state.door_state.get(seg, DOOR_OPEN) == DOOR_OPEN, (
        "Antechamber south segment must be DOOR_OPEN after lever install"
    )


def test_greenhouse_lever_makes_antechamber_passable_without_a_key():
    """After the lever, the Antechamber's south doorway is passable holding zero keys.

    This is the point of the lever: a locked Antechamber normally costs a key to
    enter, so the unlock has to change passability, not just the stored flag.
    """
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    g.state.door_state[segment_key(37, N)] = DOOR_LOCKED
    g.state.keys = 0

    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    assert not g.doorway_passable(37, N), "locked Antechamber must be impassable with no keys"
    si.install_lever(g)
    assert g.doorway_passable(37, N), "lever must open the Antechamber without spending a key"
    assert g.state.keys == 0, "the lever must not consume a key"


def test_greenhouse_lever_door_version_bumped():
    """Installing the Greenhouse lever bumps door_version, invalidating nav caches."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    before = g.state.door_version
    si.install_lever(g)
    assert g.state.door_version > before, "door_version must increase after lever install"


# --------------------------------------------------------- Power Hammer wall break

def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False


def test_greenhouse_wall_breaks_on_enter_with_power_hammer(registry):
    """Entering the Greenhouse while holding a Power Hammer permanently sets
    state.shops.greenhouse_wall_broken -- the fact
    engine/placement.py::legal_orientations reads (via Room.alt_layouts_gate)
    to admit the corner rotations."""
    g = Game(GameConfig(special_items=True, starting_items=frozenset({"power_hammer"})),
             seed=1, registry=registry)
    greenhouse = g.registry.by_id["greenhouse"]
    _place_at(g, "greenhouse", 5, greenhouse.door_mask)
    g.state.pos = 5
    g._enter(5)
    assert g.state.shops.greenhouse_wall_broken is True


def test_greenhouse_wall_stays_intact_without_power_hammer(registry):
    """Entering the Greenhouse without a Power Hammer leaves
    greenhouse_wall_broken False -- no player action beyond arriving in the
    room is modelled, but the item itself is required."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)  # no power_hammer
    greenhouse = g.registry.by_id["greenhouse"]
    _place_at(g, "greenhouse", 5, greenhouse.door_mask)
    g.state.pos = 5
    g._enter(5)
    assert g.state.shops.greenhouse_wall_broken is False


def test_greenhouse_wall_broken_reported_in_carryover(registry):
    """shops.carryover()['greenhouse_wall_broken'] is True once the wall has
    broken in-run, and True when already carried in via cfg -- the same
    OR-from-cfg-or-state shape as weight_room_wall_broken."""
    g = Game(GameConfig(special_items=True, starting_items=frozenset({"power_hammer"})),
             seed=1, registry=registry)
    greenhouse = g.registry.by_id["greenhouse"]
    _place_at(g, "greenhouse", 5, greenhouse.door_mask)
    g.state.pos = 5
    g._enter(5)
    assert shops.carryover(g)["greenhouse_wall_broken"] is True

    g_carried = Game(GameConfig(greenhouse_wall_broken=True), seed=1, registry=registry)
    assert shops.carryover(g_carried)["greenhouse_wall_broken"] is True

    g_fresh = Game(GameConfig(), seed=1, registry=registry)
    assert shops.carryover(g_fresh)["greenhouse_wall_broken"] is False


def test_greenhouse_wall_broken_survives_day_boundary_and_reaches_carryover_obs():
    """A flag discovered on day 1 shows up at index
    sorted(_CARRYOVER_KEYS).index('greenhouse_wall_broken') in day 2's
    'carryover' obs vector -- the real Box(shape=(len(_CARRYOVER_KEYS),))
    encoding, mirroring tests/test_conservatory_reachability.py's own
    carryover-obs test for conservatory_floorplan_found."""
    import numpy as np

    from blueprince_sim.env.blueprince_env import BluePrinceEnv
    from blueprince_sim.env.multiday import DayChain, _CARRYOVER_KEYS

    base = GameConfig(starting_steps=3)
    chain = DayChain(base, n_days=3)
    env = BluePrinceEnv(cfg=base, day_chain=chain)
    env.reset(seed=0)

    env.day_chain.carried_flags["greenhouse_wall_broken"] = True
    rng = np.random.default_rng(0)
    terminated = truncated = False
    while not (terminated or truncated):
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        action = int(rng.choice(legal))
        _, _, terminated, truncated, _ = env.step(action)

    obs2, _ = env.reset(seed=1)
    carryover_vec = obs2["carryover"]
    idx = sorted(_CARRYOVER_KEYS).index("greenhouse_wall_broken")
    assert carryover_vec[idx] == 1
