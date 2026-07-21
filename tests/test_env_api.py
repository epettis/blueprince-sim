"""Gymnasium API compliance and action masking."""

import numpy as np
import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.env import actions as A


def test_check_env():
    from gymnasium.utils.env_checker import check_env

    env = make_env()
    check_env(env, skip_render_check=True)


def test_masked_actions_never_raise():
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
    env = make_env()
    env.reset(seed=0)
    mask = env.action_masks()
    illegal = int(np.flatnonzero(~mask)[0])
    obs, reward, terminated, truncated, info = env.step(illegal)
    assert reward == pytest.approx(-0.01)
    assert not terminated


def test_outer_action_masked_by_unlock():
    env = make_env(GameConfig(outer_rooms_unlocked=False))
    env.reset(seed=0)
    assert not env.action_masks()[A.OUTER_DRAFT_ACTION]
    env2 = make_env(GameConfig(outer_rooms_unlocked=True))
    env2.reset(seed=0)
    assert env2.action_masks()[A.OUTER_DRAFT_ACTION]


def test_gym_registration():
    import gymnasium

    env = gymnasium.make("BluePrince-v0")
    obs, info = env.reset(seed=1)
    assert "action_mask" in info


def test_reward_modes():
    env = make_env(GameConfig(reward="shaped"))
    obs, info = env.reset(seed=3)
    mask = env.action_masks()
    action = int(np.flatnonzero(mask)[0])
    _, reward, *_ = env.step(action)
    assert isinstance(reward, float)
