"""Greenhouse: the Broken Lever machine (south Antechamber segment).

The Antechamber-lever regression test is split out of the old
test_antechamber_levers.py (coverage for the pre-existing broken_lever path);
see tests/test_antechamber_levers.py for the cross-cutting lever-gate
invariants that stayed there. The remaining install_lever tests are split out
of the old test_ignition.py, which keeps the broken_lever item's generic
consumption rules for any machine room (see tests/test_ignition.py).
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
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
