"""Gymnasium API compliance and action masking."""

import numpy as np
import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.env import actions as A


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
    env = make_env(GameConfig(outer_rooms_unlocked=False))
    env.reset(seed=0)
    assert not env.action_masks()[A.OUTER_DRAFT_ACTION]
    env2 = make_env(GameConfig(outer_rooms_unlocked=True))
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
