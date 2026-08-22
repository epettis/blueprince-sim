"""Gymnasium API compliance and action masking."""

import numpy as np
import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine.game import Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_LOCKED, segment_key
from blueprince_sim.env import actions as A
from blueprince_sim.env.rewards import PATHS_ONE_PENALTY, snapshot


def test_check_env():
    """The env passes Gymnasium's official check_env compliance suite
    (spaces, reset/step contracts, seeding)."""
    from gymnasium.utils.env_checker import check_env

    env = make_env()
    check_env(env, skip_render_check=True)


def test_masked_actions_never_raise():
    """Any action the mask marks legal can be stepped without raising, and
    every observation stays within the declared observation space."""
    env = make_env()
    rng = np.random.default_rng(0)
    for episode in range(5):
        obs, info = env.reset(seed=episode)
        for _ in range(300):
            mask = env.action_masks()
            legal = np.flatnonzero(mask)
            if len(legal) == 0:
                break
            action = int(rng.choice(legal))
            obs, reward, terminated, truncated, info = env.step(action)
            assert env.observation_space.contains(obs)
            if terminated or truncated:
                break


def test_invalid_action_penalized_not_crashing():
    """A masked-out action is a harmless no-op: small -0.01 penalty, no crash,
    no episode termination."""
    env = make_env()
    env.reset(seed=0)
    mask = env.action_masks()
    illegal = int(np.flatnonzero(~mask)[0])
    obs, reward, terminated, truncated, info = env.step(illegal)
    assert reward == pytest.approx(-0.01)
    assert not terminated


def test_outer_action_masked_by_unlock():
    """The outer-draft action is only legal when outer rooms are unlocked in
    the GameConfig."""
    env = make_env(GameConfig(west_gate_unlatched=False))
    env.reset(seed=0)
    assert not env.action_masks()[A.OUTER_DRAFT_ACTION]
    env2 = make_env(GameConfig(west_gate_unlatched=True))
    env2.reset(seed=0)
    assert env2.action_masks()[A.OUTER_DRAFT_ACTION]


def test_gym_registration():
    """The env is registered as "BluePrince-v0" and reset() exposes the action
    mask in the info dict for MaskablePPO-style consumers."""
    import gymnasium

    env = gymnasium.make("BluePrince-v0")
    obs, info = env.reset(seed=1)
    assert "action_mask" in info


def test_reward_modes():
    """The shaped reward mode is selectable via config and yields plain float
    rewards from step()."""
    env = make_env(GameConfig(reward="shaped"))
    obs, info = env.reset(seed=3)
    mask = env.action_masks()
    action = int(np.flatnonzero(mask)[0])
    _, reward, *_ = env.step(action)
    assert isinstance(reward, float)


def test_env_detected_dead_end_zeroes_phi_paths_before_scoring():
    """A step that ends the day through BluePrinceEnv.step's own post-mask
    check (Game.phase never leaves NAVIGATE on its own) still scores with
    `terminated=True`, so phi_paths is zeroed rather than left at its
    uncancelled sealed value.

    A locked frontier doorway whose menu has been abandoned
    ``locks.LOCK_ABANDON_LIMIT`` times stops being offered by the action mask
    (``Game.frontier_doorway_triable``), but ``Game._action_in_budget`` --
    what ``Game._check_termination`` actually consults -- only asks whether
    the door is affordable, not how many times its menu has been abandoned.
    So the doorway's final abandon can leave the engine satisfied the day
    goes on while the env's own mask has nothing left to offer: exactly the
    state ``BluePrinceEnv.step``'s post-mask dead-end check exists for, with
    `Game._check_termination` never once setting `Phase.TERMINAL` itself.
    """
    env = make_env(GameConfig(special_items=False, door_locks=True, reward="shaped"))
    env.reset(seed=0)
    g = env.game
    st = g.state
    st.grid[2] = -1                 # clear the day-start Entrance Hall
    st.placed_doors[2] = 0
    room = g.registry.by_id["entrance_hall"]  # stand-in; only its door mask matters
    st.grid[32] = room.idx
    st.placed_doors[32] = N         # one frontier doorway, optimistically reaching the Antechamber
    st.entered[32] = True
    st.pos = 32
    st.steps = 5
    st.keys = 1
    seg = segment_key(32, N)
    st.door_state[seg] = DOOR_LOCKED
    st.lock_abandons[seg] = (2, 1)  # two prior abandons at 1 key; the next hits the limit
    st.door_version += 1
    g.phase = Phase.LOCK_PENDING
    st.pending_lock_cell = 32
    st.pending_lock_direction = N

    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(PATHS_ONE_PENALTY)
    assert g.can_abandon_lock()

    _, reward, terminated, truncated, info = env.step(A.LOCK_ABANDON_ACTION)

    assert terminated and not truncated
    assert info["termination_reason"] == "dead_end"
    # Time pressure is the only other per-step term here (steps unspent,
    # floored to one decision's worth); the rest of the delta is phi_paths,
    # which must telescope its -0.15 starting potential to 0 on this step.
    assert reward == pytest.approx(-PATHS_ONE_PENALTY - 0.001)
