"""Gymnasium environment wrapping the Game engine."""

from __future__ import annotations

import numpy as np
import gymnasium
from gymnasium import spaces

from ..config import GameConfig
from ..engine.game import Game, Phase
from . import actions as A
from . import obs as O
from .multiday import DayChain
from .rewards import REWARDS, RewardFn, snapshot


class BluePrinceEnv(gymnasium.Env):
    """One episode = one in-game day: Entrance Hall -> Antechamber (or bust).

    Flat Discrete(270) action space with `action_masks()` for
    sb3-contrib's MaskablePPO (via its ActionMasker wrapper) or any
    masking-aware algorithm.

    When ``day_chain`` is supplied each episode's terminal step calls
    ``day_chain.advance(game.carryover())`` so the chain tracks cross-day
    discoveries, and ``reset()`` rebuilds the ``Game`` from
    ``day_chain.next_config()`` (reusing the already-loaded registry to avoid
    re-parsing data files on every episode).  Without a chain, behaviour is
    identical to the original single-day env.
    """

    metadata = {"render_modes": ["ansi"]}

    def __init__(self, cfg: GameConfig | None = None, reward_fn: RewardFn | None = None,
                 render_mode: str | None = None,
                 day_chain: DayChain | None = None) -> None:
        self.cfg = cfg or GameConfig()
        self.day_chain: DayChain | None = day_chain   # None = legacy single-day mode
        self.game = Game(self.cfg, seed=0)
        self.reward_fn = reward_fn or REWARDS[self.cfg.reward]
        self.render_mode = render_mode
        self.action_space = spaces.Discrete(A.N_ACTIONS)
        self.observation_space = O.observation_space(
            len(self.game.registry.rooms),
            len(self.game.registry.special.items),
            len(self.game.registry.special.fabrication),
        )
        self._env_steps = 0
        self.max_env_steps = 1000
        self._episode_seed = 0
        # Snapshot of the carry-over flags active at the START of this episode;
        # captured at reset() so it remains stable even after advance() mutates
        # day_chain.carried_flags at episode end.
        self._episode_carryover: dict[str, bool] = {}

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        """Start a new day, returning ``(obs, info)``.

        An explicit ``seed`` reproduces the episode exactly (engine
        determinism is a tested invariant); otherwise a fresh seed is drawn
        from Gymnasium's ``np_random``. The seed actually used is exposed as
        ``info["episode_seed"]`` so recorded episodes can be replayed.

        When a ``day_chain`` is active, the day's ``GameConfig`` comes from
        ``day_chain.next_config()`` so the correct day index and carry-over
        flags are applied.  The registry is reused from the previous episode to
        avoid re-parsing data files on every reset.
        """
        super().reset(seed=seed)
        game_seed = seed if seed is not None else int(self.np_random.integers(0, 2**31))
        if self.day_chain is not None:
            # Snapshot carried_flags before building the game; advance() will
            # mutate them at episode end, so we need the pre-advance copy.
            self._episode_carryover = dict(self.day_chain.carried_flags)
            # Build a fresh Game for this day's config, reusing the loaded registry.
            day_cfg = self.day_chain.next_config()
            self.game = Game(day_cfg, seed=game_seed, registry=self.game.registry)
        else:
            self._episode_carryover = {}
            self.game.reset(game_seed)
        self._env_steps = 0
        self._episode_seed = game_seed
        return O.encode(self.game), self._info()

    def step(self, action: int):
        """Apply one flat action; returns the usual Gymnasium 5-tuple.

        Illegal actions are a -0.01 no-op (masked agents never hit this).
        A post-step NAVIGATE state with no legal action terminates the episode
        as a dead end, and episodes truncate after ``max_env_steps`` decisions.

        When a ``day_chain`` is active, terminal or truncated episodes call
        ``day_chain.advance(game.carryover())`` so cross-day discoveries are
        carried forward before the next ``reset()``.
        """
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
        # Post-step mask, computed once and shared with _info. A NAVIGATE
        # state with no legal action is terminal (dead end); the all-False
        # mask stays valid after _terminate (TERMINAL masks everything off).
        post_mask = A.action_mask(self.game)
        if not terminated and not any(post_mask):
            self.game._terminate("dead_end")
            terminated = True
        if (terminated or truncated) and self.day_chain is not None:
            self.day_chain.advance(self.game.carryover())
        return (O.encode(self.game), reward, terminated, truncated,
                self._info(post_mask))

    def action_masks(self) -> np.ndarray:
        """Boolean legality mask; the hook MaskablePPO reads via ActionMasker."""
        return np.array(A.action_mask(self.game), dtype=bool)

    def render(self):
        from ..cli.render import render_grid

        return render_grid(self.game, color=False)

    def _info(self, mask: list[bool] | None = None) -> dict:
        """Per-step info dict; pass ``mask`` to reuse an already-computed action mask.

        When a ``day_chain`` is active, two extra keys are included:
        ``"day"`` (1-based in-game day for the *current* episode) and
        ``"carryover"`` (the dict of carry-over flags that were active at
        the *start* of this day, i.e. what ``day_chain.next_config()`` used).
        These are present at every step so callers can read day progress
        without waiting for episode end.
        """
        if mask is None:
            mask = A.action_mask(self.game)
        info: dict = {
            "deepest_rank": self.game.deepest_rank,
            "rooms_placed": self.game.rooms_placed,
            "termination_reason": self.game.termination_reason,
            "episode_seed": self._episode_seed,
            "drafted_rooms": list(self.game.drafted_rooms),
            "action_mask": np.array(mask, dtype=bool),
        }
        if self.day_chain is not None:
            # state.day is the in-game day index that was injected via next_config().
            info["day"] = self.game.state.day
            # _episode_carryover is the snapshot taken at reset() time — the
            # flags that were active at the START of this day.  This is stable
            # even after advance() mutates day_chain.carried_flags at episode end.
            info["carryover"] = self._episode_carryover
        return info


def register() -> None:
    """Register ``BluePrince-v0`` with Gymnasium (runs once at module import)."""
    gymnasium.register(id="BluePrince-v0", entry_point="blueprince_sim.env.blueprince_env:BluePrinceEnv")


register()
