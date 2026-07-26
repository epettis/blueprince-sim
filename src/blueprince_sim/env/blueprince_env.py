"""Gymnasium environment wrapping the Game engine."""

from __future__ import annotations

import dataclasses

import numpy as np
import gymnasium
from gymnasium import spaces

from ..config import GameConfig
from ..engine.game import Game, Phase
from . import actions as A
from . import obs as O
from .multiday import DayChain
from .rewards import REWARDS, RewardFn, snapshot


def _serialize_config_value(v):
    """Coerce a GameConfig field value to a JSON-serializable form, or return None if not serializable.

    Rules:
    - frozenset[str] -> sorted list[str]
    - bool, int, str -> pass through
    - anything else (e.g. Path) -> None (skip)
    """
    if isinstance(v, frozenset):
        return sorted(v)
    if isinstance(v, (bool, int, str)):
        return v
    # Path, None, and anything else: not serializable for our purposes
    return None


def _day_config_diff(day_cfg: GameConfig, base_cfg: GameConfig) -> dict:
    """Return a JSON-serializable dict of fields where day_cfg differs from base_cfg.

    Iterates dataclasses.fields(GameConfig) generically so new per-day fields
    are captured automatically.  Fields whose values are not JSON-serializable
    (e.g. data_dir: Path | None) are silently skipped.
    Only fields that differ are included.
    """
    diff = {}
    for f in dataclasses.fields(GameConfig):
        day_val = getattr(day_cfg, f.name)
        base_val = getattr(base_cfg, f.name)
        if day_val == base_val:
            continue
        serialized = _serialize_config_value(day_val)
        if serialized is None and not isinstance(day_val, (bool, int, str)):
            # Not serializable (Path, etc.) — skip
            continue
        diff[f.name] = serialized
    return diff


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
        # Last *applied* action id (legal actions only); None at reset and after
        # any illegal (masked-out) action.  Threaded into action_mask() so the
        # security-setpoint repeat guard can fire without touching engine state.
        self._prev_action: int | None = None
        # Snapshot of the carry-over flags active at the START of this episode;
        # captured at reset() so it remains stable even after advance() mutates
        # day_chain.carried_flags at episode end.
        self._episode_carryover: dict[str, bool] = {}
        # JSON-serializable diff of this episode's GameConfig vs. the chain's
        # base_cfg; only present (non-empty) when a day_chain is active.
        # Captured at reset() for use in info["day_config"].
        self._episode_day_config: dict = {}

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        """Start a new day, returning ``(obs, info)``.

        An explicit ``seed`` reproduces the episode exactly (engine
        determinism is a tested invariant); otherwise a fresh seed is drawn
        from Gymnasium's ``np_random``. The seed actually used is exposed as
        ``info["episode_seed"]`` so recorded episodes can be replayed.

        When a ``day_chain`` is active, the day's ``GameConfig`` comes from
        ``day_chain.next_config()`` so the correct day index and carry-over
        flags are applied.  The registry is reused from the previous episode to
        avoid re-parsing data files on every reset.  A JSON-serializable diff
        of the day's config vs. the chain's base config is captured in
        ``_episode_day_config`` and exposed as ``info["day_config"]`` so
        recorders can store it for faithful replay.
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
            # Capture the config diff for replay: snapshot AFTER next_config()
            # so we have the full per-day GameConfig to compare.
            self._episode_day_config = _day_config_diff(day_cfg, self.day_chain.base_cfg)
        else:
            self._episode_carryover = {}
            self._episode_day_config = {}
            self.game.reset(game_seed)
        self._env_steps = 0
        self._episode_seed = game_seed
        self._prev_action = None
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
        mask = A.action_mask(self.game, self._prev_action)
        if not mask[action]:
            # Invalid action: no state change, small penalty. Masked agents
            # never hit this; random agents learn from it.  Illegal actions do
            # NOT update _prev_action so the setpoint guard stays active.
            terminated = False
            reward = -0.01
        else:
            A.apply_action(self.game, action)
            self._prev_action = action  # record only legal applied actions
            terminated = self.game.phase is Phase.TERMINAL
            reward = self.reward_fn(self.game, prev, terminated)
        self._env_steps += 1
        truncated = self._env_steps >= self.max_env_steps
        # Post-step mask, computed once and shared with _info. A NAVIGATE
        # state with no legal action is terminal (dead end); the all-False
        # mask stays valid after _terminate (TERMINAL masks everything off).
        post_mask = A.action_mask(self.game, self._prev_action)
        if not terminated and not any(post_mask):
            self.game._terminate("dead_end")
            terminated = True
        if (terminated or truncated) and self.day_chain is not None:
            self.day_chain.advance(self.game.carryover())
        return (O.encode(self.game), reward, terminated, truncated,
                self._info(post_mask))

    def action_masks(self) -> np.ndarray:
        """Boolean legality mask; the hook MaskablePPO reads via ActionMasker."""
        return np.array(A.action_mask(self.game, self._prev_action), dtype=bool)

    def render(self):
        from ..cli.render import render_grid

        return render_grid(self.game, color=False)

    def _info(self, mask: list[bool] | None = None) -> dict:
        """Per-step info dict; pass ``mask`` to reuse an already-computed action mask.

        When a ``day_chain`` is active, three extra keys are included:
        ``"day"`` (1-based in-game day for the *current* episode),
        ``"carryover"`` (the dict of carry-over flags that were active at
        the *start* of this day, i.e. what ``day_chain.next_config()`` used),
        and ``"day_config"`` (a JSON-serializable dict of GameConfig fields
        that differ from the chain's base_cfg — used by EpisodeRecorder so
        replay.build_frames can reconstruct the day's exact conditions).
        These are present at every step so callers can read day progress
        without waiting for episode end.
        """
        if mask is None:
            mask = A.action_mask(self.game, self._prev_action)
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
            # _episode_day_config is the JSON-serializable diff of this day's
            # GameConfig vs. the chain's base_cfg, captured at reset() time.
            # Recorders store this so replay can reconstruct the exact conditions.
            info["day_config"] = self._episode_day_config
        return info


def register() -> None:
    """Register ``BluePrince-v0`` with Gymnasium (runs once at module import)."""
    gymnasium.register(id="BluePrince-v0", entry_point="blueprince_sim.env.blueprince_env:BluePrinceEnv")


register()
