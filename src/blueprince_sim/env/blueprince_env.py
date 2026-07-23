"""Gymnasium environment wrapping the Game engine."""

from __future__ import annotations

import numpy as np
import gymnasium
from gymnasium import spaces

from ..config import GameConfig
from ..engine.game import Game, Phase
from . import actions as A
from . import obs as O
from .rewards import REWARDS, RewardFn, snapshot


class BluePrinceEnv(gymnasium.Env):
    """One episode = one in-game day: Entrance Hall -> Antechamber (or bust).

    Flat Discrete(196) action space with `action_masks()` for
    sb3-contrib's MaskablePPO (via its ActionMasker wrapper) or any
    masking-aware algorithm.
    """

    metadata = {"render_modes": ["ansi"]}

    def __init__(self, cfg: GameConfig | None = None, reward_fn: RewardFn | None = None,
                 render_mode: str | None = None) -> None:
        self.cfg = cfg or GameConfig()
        self.game = Game(self.cfg, seed=0)
        self.reward_fn = reward_fn or REWARDS[self.cfg.reward]
        self.render_mode = render_mode
        self.action_space = spaces.Discrete(A.N_ACTIONS)
        self.observation_space = O.observation_space(len(self.game.registry.rooms))
        self._env_steps = 0
        self.max_env_steps = 1000
        self._episode_seed = 0

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        game_seed = seed if seed is not None else int(self.np_random.integers(0, 2**31))
        self.game.reset(game_seed)
        self._env_steps = 0
        self._episode_seed = game_seed
        return O.encode(self.game), self._info()

    def step(self, action: int):
        assert self.game.phase is not Phase.TERMINAL, "episode is over; call reset()"
        prev = snapshot(self.game)
        mask = A.action_mask(self.game)
        if not mask[action]:
            # Invalid action: no state change, small penalty. Masked agents
            # never hit this; random agents learn from it.
            terminated = False
            reward = -0.01
        else:
            A.apply_action(self.game, action)
            terminated = self.game.phase is Phase.TERMINAL
            reward = self.reward_fn(self.game, prev, terminated)
        self._env_steps += 1
        truncated = self._env_steps >= self.max_env_steps
        # A NAVIGATE state with no legal action is terminal (dead end).
        if not terminated and not any(A.action_mask(self.game)):
            self.game._terminate("dead_end")
            terminated = True
        return O.encode(self.game), reward, terminated, truncated, self._info()

    def action_masks(self) -> np.ndarray:
        return np.array(A.action_mask(self.game), dtype=bool)

    def render(self):
        from ..cli.render import render_grid

        return render_grid(self.game, color=False)

    def _info(self) -> dict:
        return {
            "deepest_rank": self.game.deepest_rank,
            "rooms_placed": self.game.rooms_placed,
            "termination_reason": self.game.termination_reason,
            "episode_seed": self._episode_seed,
            "action_mask": np.array(A.action_mask(self.game), dtype=bool),
        }


def register() -> None:
    gymnasium.register(id="BluePrince-v0", entry_point="blueprince_sim.env.blueprince_env:BluePrinceEnv")


register()
