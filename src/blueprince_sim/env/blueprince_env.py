"""Gymnasium environment wrapping the Game engine."""

from __future__ import annotations

import dataclasses

import numpy as np
import gymnasium
from gymnasium import spaces

from ..config import GameConfig, config_digest
from ..engine.game import Game, Phase
from ..engine.upgrades import all_slot_ids
from . import actions as A
from . import obs as O
from .multiday import DayChain
from .rewards import REWARDS, RewardFn, snapshot


def _serialize_config_value(v):
    """Coerce a GameConfig field value to a JSON-serializable form, or return None if not serializable.

    Rules:
    - frozenset[str] -> sorted list[str]
    - dict -> new dict with keys in sorted order (order-independent canonical form)
    - bool, int, str -> pass through
    - anything else (e.g. Path) -> None (skip)
    """
    if isinstance(v, frozenset):
        return sorted(v)
    if isinstance(v, dict):
        return {k: v[k] for k in sorted(v)}
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
            len(self.game.registry.area_graph.nodes),
            n_carryover=len(DayChain._CARRYOVER_KEYS),
            n_slots=len(all_slot_ids(self.game.registry)),
            n_axe_targets=len(A._build_axe_target_ids(self.game.registry)),
            n_permanent_rarity_rooms=len(
                A._build_permanent_rarity_room_ids(self.game.registry)),
            n_planetarium_planets=len(self.game.registry.special.planetarium_planets),
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
        # Digest (config.config_digest) of this episode's exact GameConfig,
        # captured once at reset() -- covers both the day_chain and no-chain
        # branches, since a single-day record needs the same replay-under-the-
        # wrong-config check a multi-day one does. Exposed as
        # info["config_digest"] so recorders can stamp it and BC's
        # config_for_record can catch a mismatched reconstruction at step 0.
        self._episode_config_digest: str = ""

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
        recorders can store it for faithful replay.  A digest of the exact
        ``GameConfig`` this episode runs under (``config.config_digest``) is
        captured in ``_episode_config_digest`` and exposed as
        ``info["config_digest"]`` in both branches, single-day included.
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
        self._episode_config_digest = config_digest(self.game.cfg)
        self._env_steps = 0
        self._episode_seed = game_seed
        self._prev_action = None
        return O.encode(self.game, self.day_chain), self._info()

    def step(self, action: int):
        """Apply one flat action; returns the usual Gymnasium 5-tuple.

        Illegal actions are a -0.01 no-op (masked agents never hit this).
        A post-step NAVIGATE state with no legal action terminates the episode
        as a dead end, and episodes truncate after ``max_env_steps`` decisions.

        When a ``day_chain`` is active:

        - A day ending mid-attempt (not the final day) is reported as
          ``terminated=False, truncated=True``. SB3's DummyVecEnv converts
          that into ``info["TimeLimit.truncated"]=True``, which makes
          ``OnPolicyAlgorithm.collect_rollouts`` bootstrap ``V(terminal_obs)``
          so cross-day value flows back through the value function.
        - The final day of an attempt (``current_day >= n_days``) is the only
          true terminal: ``terminated=True, truncated=False``.
        - ``day_chain.advance()`` runs BEFORE ``O.encode()`` at the end of
          this method. The observation returned at day end therefore describes
          the state the agent *resumes from tomorrow* (post-advance day index,
          post-advance carried flags). That is exactly the state to bootstrap
          from — a future reader should NOT read this ordering as a bug.
          On an attempt wrap, ``advance()`` resets day to 1 and clears flags,
          but that step is a true terminal so the observation is never
          bootstrapped from.

        When ``day_chain`` is None (single-day mode), behaviour is unchanged:
        ``terminated=True`` at game end.

        Upgrade decisions: when action falls in the CHOOSE_UPGRADE range (276-278)
        and the action is legal, an ``"upgrade_decision"`` key is included in the
        returned info dict with the fields needed for bottleneck analysis.  The
        snapshot is taken before apply_action so pending_upgrade_slot/options are
        still populated.
        """
        assert self.game.phase is not Phase.TERMINAL, "episode is over; call reset()"
        # SB3 hands us a numpy integer. Coerce at the boundary so nothing downstream
        # inherits a type json.dumps rejects: the upgrade log's chosen_index is
        # derived straight from this value, and a numpy int64 there killed a run.
        action = int(action)
        prev = snapshot(self.game)
        mask = A.action_mask(self.game, self._prev_action)

        # Capture upgrade context BEFORE apply_action clears pending_upgrade_*.
        # Only fire for legal CHOOSE_UPGRADE actions (276-278).
        upgrade_record: dict | None = None
        if mask[action] and A.CHOOSE_UPGRADE_BASE <= action <= A.CHOOSE_UPGRADE_BASE + 2:
            upgrade_record = _capture_upgrade_decision(
                self.game, action, self._episode_seed,
                self.day_chain.current_day if self.day_chain is not None else None,
            )

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
            # reward_fn is called below, once `terminated` is settled by the
            # post-step dead-end check -- a reward function forced to zero its
            # potential on a terminal step (see rewards.shaped/phased) must
            # never be called with a stale `terminated=False` on the very
            # step that flips it, or the zeroing it relies on never fires.
            reward = None
        self._env_steps += 1
        truncated = self._env_steps >= self.max_env_steps
        # Post-step mask, computed once and shared with _info. A NAVIGATE
        # state with no legal action is terminal (dead end); the all-False
        # mask stays valid after _terminate (TERMINAL masks everything off).
        post_mask = A.action_mask(self.game, self._prev_action)
        if not terminated and not any(post_mask):
            self.game._terminate("dead_end")
            terminated = True
        if reward is None:
            reward = self.reward_fn(self.game, prev, terminated)
        # Day-chain horizon: mid-attempt day ends are truncations, not terminations.
        # Evaluate is_last_day BEFORE advance() because advance() increments current_day
        # (and wraps it to 1 on an attempt boundary). After this block, advance() runs
        # unconditionally when done, so the observation returned describes the
        # post-advance state — exactly what the agent wakes up to tomorrow.
        # An attempt wrap IS a true terminal (is_last_day=True) so it is never
        # bootstrapped from; advance() resets day to 1 and clears flags for it.
        if terminated and self.day_chain is not None:
            is_last_day = self.day_chain.current_day >= self.day_chain.n_days
            if not is_last_day:
                truncated = True
                terminated = False
        if (terminated or truncated) and self.day_chain is not None:
            self.day_chain.advance(self.game.carryover())
        info = self._info(post_mask)
        if upgrade_record is not None:
            info["upgrade_decision"] = upgrade_record
        return (O.encode(self.game, self.day_chain), reward, terminated, truncated, info)

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

        ``"room46_reached"`` and ``"antechamber_reached"`` mirror
        ``GameState`` directly (set the moment the player first steps onto
        the Antechamber cell / enters Room 46 this day) and are always
        present. Several consumers read them with ``.get()`` — rl/train.py's
        ``evaluate()`` win counter, the training dashboard's win rate, and
        ``EpisodeRecorder``'s per-replay "win" tag — so an absent key reads
        as ``None``/falsy rather than raising, which is exactly what made
        every win metric silently report 0 before these keys were added here.

        ``"config_digest"`` is also always present (single-day mode included):
        it is ``_episode_config_digest``, captured once at ``reset()`` rather
        than recomputed here, since this method runs every step.
        """
        if mask is None:
            mask = A.action_mask(self.game, self._prev_action)
        info: dict = {
            "deepest_rank": self.game.deepest_rank,
            "rooms_placed": self.game.rooms_placed,
            "termination_reason": self.game.termination_reason,
            "episode_seed": self._episode_seed,
            "drafted_rooms": list(self.game.drafted_rooms),
            "visited_areas": sorted(self.game.state.areas_visited),
            "action_mask": np.array(mask, dtype=bool),
            "room46_reached": self.game.state.room46_reached,
            "antechamber_reached": self.game.state.antechamber_reached,
            "config_digest": self._episode_config_digest,
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


def _capture_upgrade_decision(game: Game, action: int,
                               episode_seed: int, day: int | None) -> dict:
    """Snapshot an upgrade decision for the upgrade event log.

    Called immediately BEFORE apply_action so pending_upgrade_slot and
    pending_upgrade_options are still populated.  Returns a plain dict with
    JSON-serializable values; all fields needed for bottleneck analysis are
    included if available.

    Fields:
    - ``episode_seed``: int — the seed that uniquely identifies this episode.
    - ``day``: int | None — in-game day index (1-based); None in single-day mode.
    - ``slot``: str — the selected upgrade slot id (e.g. "cloister").
    - ``offered``: list[str] — the three offered variant room ids.
    - ``chosen_index``: int — 0, 1, or 2; which option the agent picked.
    - ``chosen_variant``: str — the variant room id that was chosen.
    - ``catacombs_unlocked``: bool — whether Catacombs were unlocked at insert time.
    - ``draft_counts``: dict[str, int] — cumulative draft counts for the slot's
      root base room id (the ``min_drafts`` bracket input).  Keyed by base room id.
    - ``slots_upgraded``: int — number of slots already upgraded before this decision.
    - ``disks_held``: int — upgrade disks REMAINING in inventory, i.e. the
      POST-consume count.  ``insert_disk`` removes the inserted disk (game.py,
      ``remove(..., consumed=True)``) before it sets ``pending_upgrade_*``, so the
      disk driving this decision is already gone when this snapshot is taken.
      0 is normal and means the agent just spent its last disk.
    """
    from ..engine.upgrades import root_base_id, upgraded_slots

    st = game.state
    chosen_index = action - A.CHOOSE_UPGRADE_BASE  # 0, 1, or 2
    slot = st.pending_upgrade_slot or ""
    offered = list(st.pending_upgrade_options)
    chosen_variant = offered[chosen_index] if 0 <= chosen_index < len(offered) else ""

    # draft_counts for the slot's root base room
    slot_draft_counts: dict[str, int] = {}
    if slot:
        # Find the base room for this slot (any variant maps to the same base)
        base_ids = {
            root_base_id(game.registry, game.registry.by_id[v])
            for v in offered
            if v in game.registry.by_id
        }
        for bid in base_ids:
            if bid in st.draft_counts:
                slot_draft_counts[bid] = st.draft_counts[bid]

    # Upgrade disks held right now (pre-consume; choose_upgrade hasn't fired yet,
    # but insert_disk already consumed the disk so this reflects the post-insert count)
    disks_held = len(game.held_disk_ids())

    slots_already_upgraded = len(upgraded_slots(frozenset(st.applied_upgrades), game.registry))

    return {
        "episode_seed": episode_seed,
        "day": day,
        "slot": slot,
        "offered": offered,
        "chosen_index": chosen_index,
        "chosen_variant": chosen_variant,
        "catacombs_unlocked": game.catacombs_unlocked(),
        "draft_counts": slot_draft_counts,
        "slots_upgraded": slots_already_upgraded,
        "disks_held": disks_held,
    }


def register() -> None:
    """Register ``BluePrince-v0`` with Gymnasium (runs once at module import)."""
    gymnasium.register(id="BluePrince-v0", entry_point="blueprince_sim.env.blueprince_env:BluePrinceEnv")


register()
