"""The path-preservation potential is a function of the grid, not of the
player's position.

Covers the off-grid collapse bug: ``_ante_paths`` used to fall through to
``Game.frontier_doorways()``, which unconditionally returns ``[]`` while
``game.off_grid`` is True — a fact about where the player is standing, not
about the house's connectivity. That made every off-grid excursion (Outer
Room drafting, area-graph travel) read as "all routes sealed" and back,
which happened to cancel out under potential-based shaping (so it was
invisible in aggregate reward) while still corrupting the *signal* a step at
a time: a genuine 1-open-path danger state read as 0 while outside, and
empirically it made a trained policy loop off-grid travel actions for free.

Also covers the companion instrumentation bug: ``BluePrinceEnv._info()``
never set ``"room46_reached"``/``"antechamber_reached"``, so every consumer
reading them with ``.get()`` (the win-rate counter in rl/train.py, the
training dashboard, ``EpisodeRecorder``'s "win" tag) silently saw ``None``.
"""

from __future__ import annotations

import pytest

from blueprince_sim import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, S, ENTRANCE_CELL, neighbor
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.rewards import PATHS_ONE_PENALTY, _ante_paths, _phi_paths


def _place(g: Game, cell: int, mask: int, *, pos: bool = False) -> None:
    """Place a minimal room at ``cell`` with door ``mask``, bumping the cache
    stamp so BFS/frontier maps notice the change (mirrors tests/test_rewards.py).
    """
    room = g.registry.by_id["entrance_hall"]
    st = g.state
    st.grid[cell] = room.idx
    st.placed_doors[cell] = mask
    st.entered[cell] = True
    if pos:
        st.pos = cell
    st.door_version += 1


def _sealed_game(registry) -> Game:
    """Fresh game with the pre-placed Entrance Hall cleared, so a test can
    build a custom minimal grid without inheriting its default doors."""
    g = Game(GameConfig(), seed=1, registry=registry)
    st = g.state
    st.grid[2] = -1
    st.placed_doors[2] = 0
    st.door_version += 1
    return g


def test_ante_paths_identical_on_and_off_grid(registry):
    """With the grid completely unchanged, _ante_paths (and the phi_paths it
    feeds) must read identically whether the player is on the 5x9 grid or has
    stepped off it into an area node -- the potential is a property of the
    house, not of where the player happens to be standing.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)  # exactly ONE open frontier -> not the >=2 "already neutral" case

    on_grid_paths = _ante_paths(g)
    on_grid_phi = _phi_paths(on_grid_paths)
    assert on_grid_paths == 1
    assert on_grid_phi == pytest.approx(PATHS_ONE_PENALTY)

    g.state.area = "west_path"  # step off the grid; state.pos (32) is untouched
    assert g.off_grid

    off_grid_paths = _ante_paths(g)
    off_grid_phi = _phi_paths(off_grid_paths)

    assert off_grid_paths == on_grid_paths
    assert off_grid_phi == pytest.approx(on_grid_phi)


def test_offgrid_round_trip_is_reward_neutral_on_path_term():
    """An off-grid round trip through the real env (travel to west_path, then
    back to house) leaves the path-preservation potential exactly where it
    started at every leg, from a position with only ONE open route.

    A single open path (not >=2, which is already potential-0 and would hide
    a collapse-to-zero) is what makes a wrong "return 99 while off-grid" fix
    visibly fail here just as much as the original "return 0" bug would:
    both replace -0.15 with a different constant instead of leaving it alone.
    """
    env = BluePrinceEnv(cfg=GameConfig())
    env.reset(seed=1)
    g = env.game

    # West Path is the only "modelled" (travel-advertised) area node cheaply
    # reachable from a fresh save; the west gate's unlatch is otherwise earned
    # by physically walking there first, which this test isn't about, so it's
    # set directly -- the same GameState-poking pattern test_rewards.py uses.
    g.state.west_gate_unlatched = True

    # Seal two of the Entrance Hall's three frontier doors by occupying their
    # target cells, leaving exactly one open route (mirrors test_rewards.py's
    # sealing scenarios, but keeps the player's own cell -- and therefore the
    # "house" area anchor -- intact so travel is still legal).
    for d in (N, E):
        nb = neighbor(ENTRANCE_CELL, d)
        g.state.grid[nb] = g.registry.by_id["entrance_hall"].idx
        g.state.placed_doors[nb] = 0
        g.state.entered[nb] = True
    g.state.door_version += 1

    phi_home = _phi_paths(_ante_paths(g))
    assert phi_home == pytest.approx(PATHS_ONE_PENALTY)

    node_ids = A._build_area_node_ids(g.registry)
    west_action = A.TRAVEL_BASE + node_ids.index("west_path")
    house_action = A.TRAVEL_BASE + node_ids.index("house")

    assert env.action_masks()[west_action]
    obs, r, term, trunc, info = env.step(west_action)
    assert not term and not trunc
    assert g.off_grid
    phi_away = _phi_paths(_ante_paths(g))

    assert env.action_masks()[house_action]
    obs, r, term, trunc, info = env.step(house_action)
    assert not term and not trunc
    assert not g.off_grid
    phi_back = _phi_paths(_ante_paths(g))

    # The house never changed connectivity, so the potential must be pinned
    # at PATHS_ONE_PENALTY throughout, and the delta telescopes to exactly 0:
    # leaving costs nothing, returning pays nothing, no free reward either way.
    assert phi_away == pytest.approx(phi_home)
    assert phi_back == pytest.approx(phi_home)
    net_path_reward = (phi_away - phi_home) + (phi_back - phi_away)
    assert net_path_reward == pytest.approx(0.0)


def test_sealing_last_route_still_charges_full_penalty_off_grid(registry):
    """The off-grid fix must not disarm the real signal: drafting the room
    that truly seals the last route to the Antechamber still drops the
    potential from -0.15 to -1.0, whether read on-grid or off.

    Guards against an overzealous fix (e.g. one that always serves a frozen
    "last known" value) that would also hide genuine sealing events that
    happen to be observed while the player is off-grid.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)  # one frontier: (32, N) -> cell 37

    assert _ante_paths(g) == 1
    g.state.area = "west_path"
    assert _phi_paths(_ante_paths(g)) == pytest.approx(PATHS_ONE_PENALTY)

    _place(g, 37, S)  # S mask: connects to 32, no further frontier -> route sealed
    assert g.off_grid

    assert _ante_paths(g) == 0
    assert _phi_paths(_ante_paths(g)) == pytest.approx(-1.0)


def test_win_flags_present_and_track_underlying_state():
    """room46_reached and antechamber_reached must be present in info at every
    step (reset and step alike) and must flip to True exactly when the
    corresponding GameState flag does -- the fix for the silently-None info
    keys that made every consumer's win rate read as zero.
    """
    env = BluePrinceEnv(cfg=GameConfig())
    obs, info = env.reset(seed=1)
    assert info["room46_reached"] is False
    assert info["antechamber_reached"] is False

    mask = env.action_masks()
    action = int(next(i for i, ok in enumerate(mask) if ok))
    obs, r, term, trunc, info = env.step(action)
    assert "room46_reached" in info
    assert "antechamber_reached" in info
    assert info["room46_reached"] == env.game.state.room46_reached
    assert info["antechamber_reached"] == env.game.state.antechamber_reached

    env.game.state.antechamber_reached = True
    env.game.state.room46_reached = True
    info = env._info()
    assert info["antechamber_reached"] is True
    assert info["room46_reached"] is True
