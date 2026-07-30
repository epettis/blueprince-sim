"""Continuous MaskablePPO training with episode-based checkpointing.

Designed to run indefinitely on a desktop:

  blueprince-train --checkpoint-dir runs/all-unlocks

- Checkpoints every N completed episodes (default 10,000) - atomic writes,
  a rolling `latest.zip`, plus periodic numbered snapshots.
- SIGINT (Ctrl-C) or SIGTERM (`kill <pid>`) stops gracefully: the current
  rollout finishes, a final checkpoint is saved, and the process exits 0.
  Maximum progress at risk = one rollout (n_envs * n_steps env steps).
- `--resume` (default: auto) picks up from `latest.zip` and continues the
  episode/timestep counters.

The policy sees the full manor layout (grid room ids + door masks), player
position, resources (steps/gems/keys/coins/dice/luck/redraws), the current
draft options, and the game phase - with invalid actions masked.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import random
import signal
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path

from ..config import GameConfig
from ..engine.model import Registry
from . import dashboard
from .dashboard import emit

# Studio-addition rooms whose special behaviour is NOT yet modelled in the engine;
# excluded from training so the agent never sees rooms that do nothing meaningful.
# Promote a room from this set once its behaviour is implemented.
# Each entry carries the open-task reference that blocked it.
_STUDIO_ADDITION_EXCLUSIONS: frozenset[str] = frozenset({
    # Mechanarium: gated arms mechanic unmodelled (open task: Mechanarium gated arms).
    "mechanarium",
    # Planetarium: Telescope planet mechanic unmodelled (open task: Planetarium planets).
    "planetarium",
    # Treasure Trove: black-box reward mechanic unmodelled (open task: Treasure Trove black box).
    "treasure_trove",
    # Closed Exhibit: security puzzle (Paper Crown pickup simplified to guaranteed) — excluded
    # because the intended locked-puzzle behaviour is unmodelled (open task: Closed Exhibit puzzle).
    "closed_exhibit",
    # Throne Room: no special behaviour implemented; open task: Throne Room.
    "throne_room",
    # NOTE: casino IS included below even though its slot-machine games are unmodelled.
    # Removing it would change training behaviour beyond this fix's intent; the inconsistency
    # is acknowledged here.  Promote this note once Casino games are implemented.
})

@functools.cache
def all_studio_additions() -> frozenset[str]:
    """Studio-addition room ids whose behaviour is modelled, derived from the registry.

    Derived rather than hand-listed so a newly-added ``studio_addition`` room is
    either picked up automatically or flagged by
    ``test_studio_additions_all_accounted_for``. It can then never be silently
    dropped from training, which is exactly how ``lost_and_found`` ended up
    implemented but disabled.

    Two inclusions worth naming: ``lost_and_found`` (steal/gift behaviour in
    ``special_items.py``) and ``tunnel`` (chain-draft mechanic in ``draft.py``)
    are both implemented despite having been absent from the old hand-written set.

    Lazy and cached deliberately: deriving this at import time would make merely
    importing this module read the data files, and ``web/replay.py`` imports it.
    """
    return frozenset(
        r.id for r in Registry.load().rooms
        if r.pool == "studio_addition"
    ) - _STUDIO_ADDITION_EXCLUSIONS

STOP = threading.Event()


def all_unlocks_config(reward: str = "shaped") -> GameConfig:
    """All permanent unlocks enabled; no upgrade disks applied.

    day=20: late-game weight tables (week2 stage, gem gates active at day>=16).
    This is the training baseline; results are NOT comparable to fresh_save_config
    because the day index changes the rarity tables and step/gem bonuses.
    """
    return GameConfig(
        day=20,                        # late-game weight tables
        orchard_unlocked=True,         # +20 starting steps
        mine_unlocked=True,            # +2 gems at day start
        west_gate_unlatched=True,      # Grounds<->West Path shortcut open
        studio_additions=all_studio_additions(),
        upgrade_disks=frozenset(),     # explicitly: no room upgrades
        reward=reward,
    )


def fresh_save_config(reward: str = "shaped") -> GameConfig:
    """Brand-new save with nothing earned — the counterpart to all_unlocks_config.

    day=1: stage="auto" resolves to "week1" rarity tables (<=7 days), and
    gem_gate_active() is off (triggers at day>=16). Results are NOT comparable
    to the day=20 baseline; use this only to study fresh-save behaviour.

    All fields are set explicitly so this reads as a complete statement of a
    fresh save and a future default change cannot silently alter it.

    ONE deliberate exception: royal_scepter_found=True. The Key of Aries ->
    Treasure Trove unlock chain is unmodelled, so leaving it False means the
    scepter is never exercised at all. The owner wants it on because the scepter's
    colour prioritisation (green) is what makes Cloisters appear. Everything else
    is exactly what a player sees on day 1 of a new file.
    """
    return GameConfig(
        day=1,                         # week1 rarity tables; gem gates off
        stage="auto",                  # resolves to "week1" at day 1
        starting_steps=50,             # base budget; no orchard bonus
        studio_additions=frozenset(),  # no studio rooms unlocked
        west_gate_unlatched=False,     # Grounds shortcut not yet open
        orchard_unlocked=False,        # no +20 steps
        mine_unlocked=False,           # no +2 gems
        upgrade_disks=frozenset(),     # no room upgrades
        veteran_mode=False,            # no gem deck-size gates
        room46_reached=False,          # no gem gate from reaching Room 46
        satisfied_conditions=frozenset(),  # no item/unlock-dependent conditions
        door_locks=True,               # locked/security doors active (default)
        strict_door_matching=False,    # permissive placement (default)
        orientation_choice=False,      # random orientation (default)
        compass=False,                 # no compass held
        ornate_compass=False,          # no ornate compass held
        special_items=True,            # item system active (default)
        starting_items=frozenset(),    # no items at day start
        lunch_box_unlocked=False,      # Gift Shop lunch box not bought
        cursed_effigy_unlocked=False,  # Shrine effigy not unlocked
        # Deliberate exception: the Key of Aries -> Treasure Trove unlock chain
        # is unmodelled. Leaving False means the scepter is never exercised and
        # its green-colour bias (which makes Cloisters appear) is absent from
        # all measurements. Set True to keep scepter mechanics live.
        royal_scepter_found=True,
        used_vault_keys=frozenset(),   # no vault deposit boxes opened
        draft_counts={},               # no cumulative draft history
        entrance_vase_broken=False,    # west vase intact
        outer_chip_dug=False,          # West Path chip not yet dug
        banned_rooms=frozenset(),      # no Repellent bans active
        lit_targets=frozenset(),       # no ignition targets lit
        collected_disks=frozenset(),   # no upgrade disks spent
        chapel_tithes=0,               # no Keeper of Tithes coins banked
        reward=reward,
        data_dir=None,
    )


def make_single_env(reward: str, seed: int, multi_day: int = 0, unlocks: str = "all"):
    """Module-level factory (picklable for SubprocVecEnv spawn).

    When ``multi_day`` > 0, each worker builds its own ``DayChain`` of that
    many days and passes it to BluePrinceEnv; chains are per-worker so episodes
    in different envs advance independently.

    ``unlocks`` selects the config preset: "all" uses all_unlocks_config (the
    day=20 training baseline), "none" uses fresh_save_config (day=1, nothing earned).
    """
    from sb3_contrib.common.wrappers import ActionMasker
    from stable_baselines3.common.monitor import Monitor

    from ..env.blueprince_env import BluePrinceEnv
    from ..env.multiday import DayChain

    def _thunk():
        cfg = fresh_save_config(reward) if unlocks == "none" else all_unlocks_config(reward)
        chain = DayChain(cfg, n_days=multi_day) if multi_day > 0 else None
        env = BluePrinceEnv(cfg=cfg, day_chain=chain)
        env.reset(seed=seed)
        env = ActionMasker(env, lambda e: e.unwrapped.action_masks())
        return Monitor(env)

    return _thunk


def _n_actions() -> int:
    """Current flat action-space size, imported lazily to keep startup light."""
    from ..env import actions as A
    return A.N_ACTIONS


class EpisodeRecorder:
    """Samples finished episodes to ``<ckpt_dir>/replays.jsonl`` for the web replay UI.

    An episode is stored as its seed plus the action sequence.  In single-day
    mode (no DayChain) the seed+actions pair reconstructs the run exactly, since
    engine determinism is a tested invariant.  In multi-day mode the starting
    conditions vary per day (day index, carry-over items/flags/bans), so the
    record also carries ``"day_config"`` — a JSON-serializable diff of the
    episode's ``GameConfig`` vs. the chain's base config.  ``replay.build_frames``
    uses ``day_config`` to reconstruct the exact conditions; without it, the
    replayed draft hands will diverge from the recorded run.  Records without
    ``"day_config"`` (written before this field was added) are legacy and may
    diverge; the replay UI will flag the divergence rather than silently
    rendering an incomplete house.

    Retention: a random ``sample_rate`` slice, plus the best episode of every
    ``top_every``-episode window, scored (win, deepest_rank, rooms_placed).
    ``modes`` is a 0/1 string per action ('0' = explore).
    """

    def __init__(self, path: Path, n_envs: int, reward: str, sample_rate: float,
                 top_every: int, episodes_done: int, seed: int = 0) -> None:
        self.path = path
        self.reward = reward
        self.sample_rate = sample_rate
        self.top_every = top_every
        self.buffers: list[list[tuple[int, bool]]] = [[] for _ in range(n_envs)]
        self._rng = random.Random(seed ^ 0x5EED)
        self._window = episodes_done // top_every if top_every else 0
        self._best: tuple[tuple, dict] | None = None

    def on_step(self, actions, modes) -> None:
        """Buffer this vec-step's (action, exploit-mode) pair for every env."""
        if actions is None:
            return
        for i, a in enumerate(actions):
            m = True if modes is None or i >= len(modes) else bool(modes[i])
            self.buffers[i].append((int(a), m))

    def on_episode_end(self, env_idx: int, episode: int, info: dict) -> None:
        """Close env ``env_idx``'s action buffer and apply the retention policy.

        Tracks the best-scored record of the current window (written when the
        window rolls over) and, independently, writes a random sample.
        """
        buf, self.buffers[env_idx] = self.buffers[env_idx], []
        seed = info.get("episode_seed")
        if not buf or seed is None:
            return
        win = info.get("termination_reason") == "antechamber"
        record = {
            "episode": episode,
            "seed": int(seed),
            "reward": self.reward,
            "actions": [a for a, _ in buf],
            "modes": "".join("1" if m else "0" for _, m in buf),
            "win": win,
            "deepest_rank": int(info.get("deepest_rank", 0)),
            "rooms_placed": int(info.get("rooms_placed", 0)),
            "reason": info.get("termination_reason"),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Action ids are positional, so a record is only replayable against
            # the action space it was written for.  Stamped so the replay UI can
            # say "recorded against a different action space" instead of calling
            # a renumbering an unexplained bug.
            "n_actions": _n_actions(),
        }
        # Only include day_config when present (multi-day mode); omit the key
        # entirely for single-day records so their format stays byte-identical.
        day_config = info.get("day_config")
        if day_config is not None:
            record["day_config"] = day_config
        if self.top_every:
            window = episode // self.top_every
            if window != self._window:
                self.flush_top()
                self._window = window
            score = (win, record["deepest_rank"], record["rooms_placed"])
            if self._best is None or score > self._best[0]:
                self._best = (score, record)
        if self.sample_rate and self._rng.random() < self.sample_rate:
            self._write(record, "random")

    def flush_top(self) -> None:
        """Write the current window's best episode, if any (also called at shutdown)."""
        if self._best is not None:
            self._write(self._best[1], "top_window")
            self._best = None

    def _write(self, record: dict, why: str) -> None:
        """Append the record to replays.jsonl, tagged with ``why`` it was kept."""
        rec = dict(record)
        rec["why"] = why
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")


class UpgradeLogger:
    """Writes one JSON record per upgrade decision to ``<ckpt_dir>/upgrades.jsonl``.

    Not sampled: every upgrade decision is recorded.  At ~0.35 decisions/day
    this is far cheaper than global episode sampling while capturing rare events
    (e.g. Cloister-of-Orinda offers that appear ~once per 730 days) reliably.

    File conventions mirror EpisodeRecorder: parent dir is created on first
    write, lines are appended directly (no buffering needed at this rate).
    Neither writer rotates; the file grows for the life of the run.

    Disable with ``--no-upgrade-log``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path  # upgrades.jsonl path under the checkpoint dir

    def on_step(self, infos: list[dict]) -> None:
        """Check each env's info for an ``"upgrade_decision"`` record and write it."""
        for info in infos:
            rec = info.get("upgrade_decision")
            if rec is None:
                continue
            self._write(rec)

    def _write(self, record: dict) -> None:
        """Append one upgrade-decision record as a JSON line."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")


class BucketStatsWriter:
    """Aggregates per-episode counters into fixed episode buckets and writes JSONL.

    Each bucket writes one JSON line with these keys (in order):
    ``bucket_start``, ``bucket_end``, ``seeds``, ``<count_key>``, ``seeds_with``,
    ``saved_at``.  A partial bucket (graceful stop or resume remainder) is written
    with its true ``seeds`` count; readers merge rows by ``bucket_start``.

    Parameters
    ----------
    path:
        Output ``.jsonl`` file path.
    info_key:
        Key in the episode ``info`` dict that carries the per-episode list of names
        (e.g. ``"drafted_rooms"`` or ``"visited_areas"``).
    count_key:
        Key used for the aggregated Counter in the JSONL record
        (e.g. ``"drafts"`` or ``"visits"``).
    episodes_done:
        Completed-episode count at construction (for resume support).
    bucket:
        Episodes per bucket (default 10 000).
    """

    def __init__(self, path: Path, info_key: str, count_key: str,
                 episodes_done: int, bucket: int = 10_000) -> None:
        self.path = path
        self._info_key = info_key
        self._count_key = count_key
        self.bucket = bucket
        self._idx = episodes_done // bucket
        self._seeds = 0
        self._counts: Counter[str] = Counter()
        self._seeds_with: Counter[str] = Counter()

    def on_episode_end(self, episode: int, info: dict) -> None:
        """Fold one finished episode's names into the current bucket."""
        names = info.get(self._info_key)
        if names is None:
            return
        idx = (episode - 1) // self.bucket
        if idx != self._idx:
            self.flush()
            self._idx = idx
        self._seeds += 1
        self._counts.update(names)
        self._seeds_with.update(set(names))

    def flush(self) -> None:
        """Write the current bucket's counts, if any (also called at shutdown)."""
        if self._seeds:
            rec = {
                "bucket_start": self._idx * self.bucket,
                "bucket_end": (self._idx + 1) * self.bucket,
                "seeds": self._seeds,
                self._count_key: dict(self._counts),
                "seeds_with": dict(self._seeds_with),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        self._seeds = 0
        self._counts.clear()
        self._seeds_with.clear()


def DraftStatsWriter(path: Path, episodes_done: int, bucket: int = 10_000) -> BucketStatsWriter:
    """Construct a BucketStatsWriter for drafted-room stats (draft_stats.jsonl)."""
    return BucketStatsWriter(path, info_key="drafted_rooms", count_key="drafts",
                             episodes_done=episodes_done, bucket=bucket)


def AreaStatsWriter(path: Path, episodes_done: int, bucket: int = 10_000) -> BucketStatsWriter:
    """Construct a BucketStatsWriter for visited-area stats (area_stats.jsonl)."""
    return BucketStatsWriter(path, info_key="visited_areas", count_key="visits",
                             episodes_done=episodes_done, bucket=bucket)


class CheckpointAndStopCallback:
    """Counts finished episodes, checkpoints every N, stops on signal.

    Implemented as an sb3 BaseCallback subclass created lazily so this module
    imports without torch installed.
    """

    def __new__(cls, *args, **kwargs):
        from stable_baselines3.common.callbacks import BaseCallback

        class _Impl(BaseCallback):
            def __init__(self, ckpt_dir: Path, every_episodes: int,
                         episodes_done: int, snapshot_every: int,
                         recorder: EpisodeRecorder | None = None,
                         draft_stats: DraftStatsWriter | None = None,
                         area_stats: AreaStatsWriter | None = None,
                         upgrade_logger: UpgradeLogger | None = None,
                         multi_day: int = 0,
                         note_fraction: float = 0.05) -> None:
                super().__init__()
                self.ckpt_dir = ckpt_dir
                self.every = every_episodes
                self.episodes = episodes_done
                self.next_ckpt = episodes_done + every_episodes
                self.snapshot_every = snapshot_every
                self.recorder = recorder
                self.draft_stats = draft_stats
                self.area_stats = area_stats
                self.upgrade_logger = upgrade_logger  # None = disabled via --no-upgrade-log
                self.recent = deque(maxlen=1000)
                self.recent_exploit = deque(maxlen=1000)
                self.recent_explore = deque(maxlen=1000)
                self.t0 = time.time()
                self.multi_day = multi_day  # 0 = single-day mode; >0 = chain length
                # Per-episode chain notes are the only high-frequency terminal
                # output; every line re-renders the whole dashboard frame, which
                # costs real throughput on long runs. Emit one every Nth episode
                # instead (0.05 -> every 20th). Lifecycle lines (checkpoints,
                # stop signals, the final summary) are never throttled.
                self.note_every = max(1, round(1.0 / note_fraction)) if note_fraction > 0 else 0

            def _on_step(self) -> bool:
                """Count episode ends, checkpoint on schedule, honor STOP.

                Wins are attributed to the mode each episode ran under BEFORE
                per-episode modes are resampled. Returning False (after a
                stop signal) ends ``model.learn()`` at this rollout step.
                """
                infos = self.locals.get("infos", ())
                policy = getattr(self.model, "policy", None)
                mixed = hasattr(policy, "resample_modes")
                if self.recorder is not None:
                    self.recorder.on_step(self.locals.get("actions"),
                                          getattr(policy, "last_modes", None))
                if self.upgrade_logger is not None:
                    self.upgrade_logger.on_step(list(infos))
                done_indices = []
                for i, (done, info) in enumerate(
                        zip(self.locals.get("dones", ()), infos)):
                    if not done:
                        continue
                    self.episodes += 1
                    win = 1.0 if info.get("termination_reason") == "antechamber" else 0.0
                    self.recent.append(win)
                    if self.recorder is not None:
                        self.recorder.on_episode_end(i, self.episodes, info)
                    if self.draft_stats is not None:
                        self.draft_stats.on_episode_end(self.episodes, info)
                    if self.area_stats is not None:
                        self.area_stats.on_episode_end(self.episodes, info)
                    if mixed and not policy.per_decision:
                        # Attribute the win to the mode the episode ran under
                        # (read BEFORE resampling).
                        if policy.env_modes[i]:
                            self.recent_exploit.append(win)
                        else:
                            self.recent_explore.append(win)
                    if (self.multi_day > 0 and "day" in info and self.note_every
                            and self.episodes % self.note_every == 0):
                        # Compact one-line chain-state note after each episode.
                        # Short key aliases keep the line width manageable.
                        _KEY_ABBREV = {
                            "royal_scepter_found": "scepter",
                            "entrance_vase_broken": "vase",
                            "outer_chip_dug": "chip",
                            "lunch_box_unlocked": "lunchbox",
                            "cursed_effigy_unlocked": "effigy",
                        }
                        carry = info.get("carryover", {})
                        carry_str = (",".join(
                            _KEY_ABBREV.get(k, k)
                            for k, v in carry.items() if v
                        ) or "none")
                        emit(f"[chain] env{i} day {info['day']}/{self.multi_day}"
                             f" | carry: {carry_str}")
                    done_indices.append(i)
                if mixed and done_indices and not policy.per_decision:
                    policy.resample_modes(done_indices)
                if self.episodes >= self.next_ckpt:
                    self.next_ckpt = ((self.episodes // self.every) + 1) * self.every
                    self.save("latest")
                    if self.snapshot_every and self.episodes % (
                            self.every * self.snapshot_every) < self.every:
                        self.save(f"ep{self.episodes}")
                if STOP.is_set():
                    emit(f"[train] stop signal received at {self.episodes} episodes; "
                         "saving and shutting down...")
                    return False  # ends model.learn() after this step
                return True

            def _on_rollout_end(self) -> None:
                """Emit rolling 1k-episode win-rate metrics to the sb3 logger."""
                if self.recent:
                    self.logger.record("blueprince/episodes", self.episodes)
                    self.logger.record("blueprince/win_rate_1k",
                                       sum(self.recent) / len(self.recent))
                if self.recent_exploit:
                    self.logger.record("blueprince/win_rate_exploit_1k",
                                       sum(self.recent_exploit) / len(self.recent_exploit))
                if self.recent_explore:
                    self.logger.record("blueprince/win_rate_explore_1k",
                                       sum(self.recent_explore) / len(self.recent_explore))

            def save(self, name: str) -> None:
                """Atomically write ``<name>.zip`` plus its ``<name>.json`` sidecar.

                The sidecar carries the episode/timestep counters and rolling
                win rates that ``--resume`` and the web dashboard read.
                """
                self.ckpt_dir.mkdir(parents=True, exist_ok=True)
                tmp = self.ckpt_dir / f".tmp_{name}.zip"
                final = self.ckpt_dir / f"{name}.zip"
                self.model.save(tmp)
                os.replace(tmp, final)  # atomic: never a half-written checkpoint
                meta = {
                    "episodes": self.episodes,
                    "timesteps": int(self.model.num_timesteps),
                    "win_rate_recent": (sum(self.recent) / len(self.recent)
                                        if self.recent else None),
                    "win_rate_exploit": (sum(self.recent_exploit) / len(self.recent_exploit)
                                         if self.recent_exploit else None),
                    "win_rate_explore": (sum(self.recent_explore) / len(self.recent_explore)
                                         if self.recent_explore else None),
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "wall_seconds_this_run": round(time.time() - self.t0, 1),
                }
                tmp_meta = self.ckpt_dir / f".tmp_{name}.json"
                tmp_meta.write_text(json.dumps(meta, indent=2))
                os.replace(tmp_meta, self.ckpt_dir / f"{name}.json")
                wr = meta["win_rate_recent"]
                emit(f"[train] checkpoint {final.name}: {self.episodes} episodes, "
                     f"{meta['timesteps']} steps, win_rate(1k)="
                     + (f"{wr:.3f}" if wr is not None else "n/a"))

        return _Impl(*args, **kwargs)


def _install_signal_handlers() -> None:
    """SIGINT/SIGTERM set STOP for a graceful stop; a second signal exits hard."""
    def handler(signum, frame):
        if STOP.is_set():  # second signal: exit hard
            emit("[train] second signal - exiting immediately")
            sys.exit(1)
        STOP.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def resolve_eval_checkpoint(ckpt_dir: Path, model_path: Path | None) -> Path:
    """Pick the model file to evaluate: an explicit ``--model`` path wins,
    otherwise ``<ckpt_dir>/latest.zip``. Pure (no torch import) so it is
    cheaply unit-testable."""
    return model_path if model_path is not None else ckpt_dir / "latest.zip"


def evaluate(ckpt_dir: Path, episodes: int, reward: str, seed: int,
             device: str, model_path: Path | None = None,
             eval_json: Path | None = None) -> int:
    """Deterministic rollout of a checkpointed policy; prints win rate.

    Evaluates ``model_path`` when given (e.g. a model.zip fetched from a
    GitHub Release), else ``<ckpt_dir>/latest.zip``. With ``eval_json``, also
    appends the stats as one JSON line (consumed by the web dashboard as the
    exploration-disabled baseline series).
    """
    from sb3_contrib import MaskablePPO

    from ..cli.batch import wilson_ci

    ckpt = resolve_eval_checkpoint(ckpt_dir, model_path)
    if not ckpt.exists():
        print(f"no checkpoint at {ckpt}", file=sys.stderr)
        return 1
    model = MaskablePPO.load(ckpt, device=device)
    env = make_single_env(reward, seed)()
    wins, ranks = 0, []
    drafts: Counter[str] = Counter()
    seeds_with: Counter[str] = Counter()
    for ep in range(episodes):
        obs, info = env.reset(seed=seed + 1_000_000 + ep)
        done = False
        while not done:
            mask = env.get_wrapper_attr("action_masks")()
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, r, term, trunc, info = env.step(int(action))
            done = term or trunc
        wins += info.get("termination_reason") == "antechamber"
        ranks.append(info.get("deepest_rank", 0))
        names = info.get("drafted_rooms") or []
        drafts.update(names)
        seeds_with.update(set(names))
    lo, hi = wilson_ci(wins, episodes)
    print(f"evaluated {ckpt}: P(Antechamber) = {wins / episodes:.3%} "
          f"(95% CI {lo:.3%} - {hi:.3%}), mean deepest rank "
          f"{sum(ranks) / len(ranks):.2f} over {episodes} episodes")
    if eval_json is not None:
        meta_path = ckpt.with_suffix(".json")
        trained_episodes = None
        if meta_path.exists():
            try:
                trained_episodes = json.loads(meta_path.read_text()).get("episodes")
            except (json.JSONDecodeError, OSError):
                pass
        rec = {
            "episodes": trained_episodes,
            "p_antechamber": wins / episodes,
            "ci95": [lo, hi],
            "mean_deepest_rank": sum(ranks) / len(ranks),
            "eval_episodes": episodes,
            "drafts": dict(drafts),
            "seeds_with": dict(seeds_with),
            "model": str(ckpt),
            "sampled_at": time.time(),
        }
        eval_json.parent.mkdir(parents=True, exist_ok=True)
        with eval_json.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """blueprince-train entry point: parse flags, then evaluate or train.

    Training builds the vec env, creates a MaskablePPO with the mixed
    exploration policy (or resumes it from ``latest.zip``), and runs
    ``model.learn`` until a stop signal or the optional timestep cap; a
    final checkpoint is always saved on the way out.
    """
    parser = argparse.ArgumentParser(
        prog="blueprince-train",
        description="Continuously train a MaskablePPO drafting policy. "
                    "No room upgrades are applied; --unlocks picks the config preset.")
    parser.add_argument("--checkpoint-dir", default="runs/blueprince-ppo",
                        help="where checkpoints + logs live")
    parser.add_argument("--checkpoint-every", type=int, default=10_000,
                        metavar="EPISODES", help="checkpoint interval in episodes")
    parser.add_argument("--snapshot-every", type=int, default=5, metavar="K",
                        help="also keep a numbered snapshot every K checkpoints "
                             "(0 = only latest.zip)")
    parser.add_argument("--n-envs", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    parser.add_argument("--n-steps", type=int, default=512,
                        help="PPO rollout length per env (progress at risk on stop)")
    parser.add_argument("--reward", choices=["shaped", "sparse", "phased"], default="shaped")
    parser.add_argument("--unlocks", choices=["all", "none"], default="all",
                        help="config preset: 'all' = all_unlocks_config (day=20 baseline, "
                             "default); 'none' = fresh_save_config (day=1, nothing earned). "
                             "Results from 'none' are NOT comparable to 'all' — the rarity "
                             "tables and step/gem bonuses differ.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", choices=["auto", "never"], default="auto",
                        help="auto: continue from latest.zip if present")
    parser.add_argument("--total-timesteps", type=int, default=None,
                        help="optional cap; default runs until signaled")
    parser.add_argument("--tensorboard", action="store_true",
                        help="also log to <checkpoint-dir>/tb")
    parser.add_argument("--dashboard-every", type=float, default=0.05,
                        metavar="FRACTION",
                        help="fraction of finished episodes that emit a chain-state "
                             "line to the dashboard (default 0.05 = one in 20). Each "
                             "line re-renders the frame, so lowering this speeds up "
                             "long runs; 0 disables the per-episode lines entirely. "
                             "Checkpoint, stop and summary lines are never throttled.")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="print sb3's scrolling metric table instead of "
                             "the in-place dashboard (the dashboard is also "
                             "skipped automatically when stdout is not a TTY, "
                             "e.g. under nohup or when piped to a log)")
    parser.add_argument("--device", default="cpu",
                        help="torch device (default cpu: the policy nets are tiny "
                             "MLPs and CPU avoids CUDA probing on GPU-less hosts)")
    parser.add_argument("--evaluate", type=int, default=0, metavar="EPISODES",
                        help="don't train: evaluate a checkpoint for N episodes "
                             "and report the win rate")
    parser.add_argument("--model", default=None, metavar="PATH",
                        help="model.zip to evaluate (e.g. one fetched from a "
                             "GitHub Release); defaults to <checkpoint-dir>/"
                             "latest.zip")
    parser.add_argument("--eval-json", default=None, metavar="PATH",
                        help="with --evaluate: also append the stats as one "
                             "JSON line to this file (dashboard baseline)")
    # --- episode recording (web replay UI) ---
    parser.add_argument("--record-sample-rate", type=float, default=0.005,
                        help="fraction of episodes recorded at random to "
                             "<checkpoint-dir>/replays.jsonl for replay")
    parser.add_argument("--record-top-every", type=int, default=1000,
                        metavar="EPISODES",
                        help="also record the best episode (win, deepest rank, "
                             "rooms placed) of every such window (0 = off)")
    parser.add_argument("--no-record", action="store_true",
                        help="disable episode recording entirely")
    # --- upgrade decision log ---
    parser.add_argument("--no-upgrade-log", action="store_true",
                        help="disable upgrade-decision logging to "
                             "<checkpoint-dir>/upgrades.jsonl "
                             "(default: enabled; writes one record per upgrade "
                             "decision, ~0.35/day, regardless of sample rate)")
    # --- multi-day loop ---
    parser.add_argument("--multi-day", type=int, default=0, metavar="N",
                        help="enable the multi-day loop: each env worker runs a "
                             "DayChain of N days before wrapping back to day 1 "
                             "(carry-over flags accumulate across the chain). "
                             "0 = off (default, each episode is independent).")
    parser.add_argument("--gamma", type=float, default=0.999,
                        help="discount factor for MaskablePPO (default: 0.999; "
                             "at ~31 steps/day this is ~32 days of lookahead). "
                             "Only takes effect for fresh runs; resumed "
                             "checkpoints load gamma from the saved model.")
    # --- explore/exploit mixing ---
    parser.add_argument("--exploit-prob", type=float, default=0.9,
                        help="probability EACH DECISION is taken in EXPLOIT mode "
                             "(best-known-policy, low temperature); the rest "
                             "explore. High by default: an episode is 50-70 "
                             "decisions, so a lower value makes whole episodes "
                             "effectively random")
    parser.add_argument("--exploit-temp", type=float, default=0.5,
                        help="sampling temperature in exploit mode (<1 sharpens "
                             "toward the argmax; 1.0 = vanilla PPO sampling)")
    parser.add_argument("--explore-temp", type=float, default=1.5,
                        help="sampling temperature in explore mode (>1 boosts "
                             "low-confidence, plausibly-high-value actions)")
    parser.add_argument("--explore-eps", type=float, default=0.05,
                        help="uniform floor over legal actions in explore mode")
    parser.add_argument("--mode-granularity", choices=["episode", "decision"],
                        default="decision",
                        help="re-roll exploit/explore per decision (default; "
                             "epsilon-greedy feel, keeps long episodes mostly "
                             "on-policy) or per episode (coherent deep "
                             "exploration, but a whole episode can be random)")
    args = parser.parse_args(argv)

    if args.evaluate:
        return evaluate(Path(args.checkpoint_dir), args.evaluate, args.reward,
                        args.seed, args.device,
                        model_path=Path(args.model) if args.model else None,
                        eval_json=Path(args.eval_json) if args.eval_json else None)

    import torch

    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))

    from sb3_contrib import MaskablePPO
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    ckpt_dir = Path(args.checkpoint_dir)
    latest = ckpt_dir / "latest.zip"
    meta_path = ckpt_dir / "latest.json"

    # Activated before anything is logged so the startup banner lands in the
    # dashboard's event tail rather than tearing the frame.
    dash = None
    if not args.no_dashboard and dashboard.supported():
        dash = dashboard.activate(
            "blueprince-train",
            f"{ckpt_dir} · reward={args.reward} · pid {os.getpid()}")

    fns = [make_single_env(args.reward, args.seed + i, args.multi_day, args.unlocks)
           for i in range(args.n_envs)]
    vec_env = SubprocVecEnv(fns) if args.n_envs > 1 else DummyVecEnv(fns)

    from .mixed_policy import MixedExplorationPolicy

    policy_kwargs = {
        "exploit_temp": args.exploit_temp,
        "explore_temp": args.explore_temp,
        "explore_eps": args.explore_eps,
    }

    episodes_done = 0
    if args.resume == "auto" and latest.exists():
        # custom_objects overrides the stored policy class/kwargs so older
        # checkpoints (plain policy) load into the mixed policy - the network
        # architecture is identical, only rollout-time sampling differs.
        # Current-run flags always win over flags stored in the checkpoint.
        model = MaskablePPO.load(
            latest, env=vec_env, device=args.device,
            custom_objects={"policy_class": MixedExplorationPolicy,
                            "policy_kwargs": policy_kwargs})
        if meta_path.exists():
            episodes_done = json.loads(meta_path.read_text()).get("episodes", 0)
        emit(f"[train] resumed from {latest} at {episodes_done} episodes, "
             f"{model.num_timesteps} timesteps")
        reset_counters = False
    else:
        model = MaskablePPO(
            MixedExplorationPolicy, vec_env,
            n_steps=args.n_steps, batch_size=1024, learning_rate=3e-4,
            gamma=args.gamma, ent_coef=0.01, seed=args.seed, verbose=1,
            tensorboard_log=str(ckpt_dir / "tb") if args.tensorboard else None,
            device=args.device, policy_kwargs=policy_kwargs,
        )
        emit(f"[train] fresh run: {args.n_envs} envs, reward={args.reward}, "
             f"checkpoint every {args.checkpoint_every} episodes -> {ckpt_dir}")
        reset_counters = True

    if dash is not None:
        # set_logger flips sb3's _custom_logger flag, so learn() keeps ours
        # instead of installing the scrolling HumanOutputFormat table.
        model.set_logger(dashboard.make_sb3_logger(
            dash, str(ckpt_dir / "tb") if args.tensorboard else None))
        model.verbose = 0

    model.policy.set_mode_config(
        exploit_prob=args.exploit_prob,
        per_decision=(args.mode_granularity == "decision"),
        n_envs=args.n_envs, seed=args.seed)
    emit(f"[train] explore/exploit: {args.exploit_prob:.0%} exploit "
         f"(temp {args.exploit_temp}) / {1 - args.exploit_prob:.0%} explore "
         f"(temp {args.explore_temp}, eps {args.explore_eps}), "
         f"per-{args.mode_granularity}")

    recorder = None
    if not args.no_record and (args.record_sample_rate > 0 or args.record_top_every > 0):
        recorder = EpisodeRecorder(
            ckpt_dir / "replays.jsonl", args.n_envs, args.reward,
            args.record_sample_rate, args.record_top_every, episodes_done,
            seed=args.seed)
        emit(f"[train] recording episodes to {recorder.path} "
             f"(sample rate {args.record_sample_rate:.2%}, "
             f"top-of-{args.record_top_every} windows)")

    upgrade_logger = None
    if not args.no_upgrade_log:
        upgrade_logger = UpgradeLogger(ckpt_dir / "upgrades.jsonl")
        emit(f"[train] upgrade decisions -> {upgrade_logger.path} "
             "(every decision, not sampled; disable with --no-upgrade-log)")

    draft_stats = DraftStatsWriter(ckpt_dir / "draft_stats.jsonl", episodes_done)
    area_stats = AreaStatsWriter(ckpt_dir / "area_stats.jsonl", episodes_done)
    callback = CheckpointAndStopCallback(
        ckpt_dir, args.checkpoint_every, episodes_done, args.snapshot_every,
        recorder=recorder, draft_stats=draft_stats, area_stats=area_stats,
        upgrade_logger=upgrade_logger,
        multi_day=args.multi_day, note_fraction=args.dashboard_every)
    _install_signal_handlers()
    emit(f"[train] pid {os.getpid()} - stop with: kill {os.getpid()} (or Ctrl-C)")

    total = args.total_timesteps if args.total_timesteps else int(1e12)
    try:
        model.learn(total_timesteps=total, callback=callback,
                    reset_num_timesteps=reset_counters, progress_bar=False)
    finally:
        callback.save("latest")
        if recorder is not None:
            recorder.flush_top()
        draft_stats.flush()
        area_stats.flush()
        vec_env.close()
        emit(f"[train] done: {callback.episodes} episodes total; "
             f"checkpoint at {latest}")
        dashboard.deactivate()   # final frame, then restore the cursor
    return 0


if __name__ == "__main__":
    sys.exit(main())
