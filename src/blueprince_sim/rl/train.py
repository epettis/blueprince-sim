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
import json
import os
import random
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

from ..config import GameConfig

ALL_STUDIO_ADDITIONS = frozenset({
    "solarium", "classroom", "dovecote", "the_kennel",
    "clock_tower", "dormitory", "vestibule", "casino",
})

STOP = threading.Event()


def all_unlocks_config(reward: str = "shaped") -> GameConfig:
    """All permanent unlocks enabled; no upgrade disks applied."""
    return GameConfig(
        day=20,                       # late-game weight tables
        orchard_unlocked=True,        # +20 starting steps
        mine_unlocked=True,           # +2 gems at day start
        outer_rooms_unlocked=True,    # 1/day West Path outer-room draft
        studio_additions=ALL_STUDIO_ADDITIONS,
        upgrade_disks=frozenset(),    # explicitly: no room upgrades
        reward=reward,
    )


def make_single_env(reward: str, seed: int):
    """Module-level factory (picklable for SubprocVecEnv spawn)."""
    from sb3_contrib.common.wrappers import ActionMasker
    from stable_baselines3.common.monitor import Monitor

    from ..env.blueprince_env import BluePrinceEnv

    def _thunk():
        env = BluePrinceEnv(cfg=all_unlocks_config(reward))
        env.reset(seed=seed)
        env = ActionMasker(env, lambda e: e.unwrapped.action_masks())
        return Monitor(env)

    return _thunk


class EpisodeRecorder:
    """Samples finished episodes to ``<ckpt_dir>/replays.jsonl`` for the web replay UI.

    An episode is stored as its seed plus the action sequence (determinism
    given a seed is a tested engine invariant, so this reconstructs the run
    exactly). Retention: a random ``sample_rate`` slice, plus the best episode
    of every ``top_every``-episode window, scored (win, deepest_rank,
    rooms_placed). ``modes`` is a 0/1 string per action ('0' = explore).
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
        }
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
                         recorder: EpisodeRecorder | None = None) -> None:
                super().__init__()
                self.ckpt_dir = ckpt_dir
                self.every = every_episodes
                self.episodes = episodes_done
                self.next_ckpt = episodes_done + every_episodes
                self.snapshot_every = snapshot_every
                self.recorder = recorder
                self.recent = deque(maxlen=1000)
                self.recent_exploit = deque(maxlen=1000)
                self.recent_explore = deque(maxlen=1000)
                self.t0 = time.time()

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
                    if mixed and not policy.per_decision:
                        # Attribute the win to the mode the episode ran under
                        # (read BEFORE resampling).
                        if policy.env_modes[i]:
                            self.recent_exploit.append(win)
                        else:
                            self.recent_explore.append(win)
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
                    print(f"[train] stop signal received at {self.episodes} episodes; "
                          "saving and shutting down...", flush=True)
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
                print(f"[train] checkpoint {final.name}: {self.episodes} episodes, "
                      f"{meta['timesteps']} steps, win_rate(1k)="
                      f"{wr:.3f}" if wr is not None else "n/a", flush=True)

        return _Impl(*args, **kwargs)


def _install_signal_handlers() -> None:
    """SIGINT/SIGTERM set STOP for a graceful stop; a second signal exits hard."""
    def handler(signum, frame):
        if STOP.is_set():  # second signal: exit hard
            print("[train] second signal - exiting immediately", flush=True)
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
        description="Continuously train a MaskablePPO drafting policy "
                    "(all unlocks, no room upgrades).")
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
    parser.add_argument("--reward", choices=["shaped", "sparse"], default="shaped")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", choices=["auto", "never"], default="auto",
                        help="auto: continue from latest.zip if present")
    parser.add_argument("--total-timesteps", type=int, default=None,
                        help="optional cap; default runs until signaled")
    parser.add_argument("--tensorboard", action="store_true",
                        help="also log to <checkpoint-dir>/tb")
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

    fns = [make_single_env(args.reward, args.seed + i) for i in range(args.n_envs)]
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
        print(f"[train] resumed from {latest} at {episodes_done} episodes, "
              f"{model.num_timesteps} timesteps", flush=True)
        reset_counters = False
    else:
        model = MaskablePPO(
            MixedExplorationPolicy, vec_env,
            n_steps=args.n_steps, batch_size=1024, learning_rate=3e-4,
            gamma=0.999, ent_coef=0.01, seed=args.seed, verbose=1,
            tensorboard_log=str(ckpt_dir / "tb") if args.tensorboard else None,
            device=args.device, policy_kwargs=policy_kwargs,
        )
        print(f"[train] fresh run: {args.n_envs} envs, reward={args.reward}, "
              f"checkpoint every {args.checkpoint_every} episodes -> {ckpt_dir}",
              flush=True)
        reset_counters = True

    model.policy.set_mode_config(
        exploit_prob=args.exploit_prob,
        per_decision=(args.mode_granularity == "decision"),
        n_envs=args.n_envs, seed=args.seed)
    print(f"[train] explore/exploit: {args.exploit_prob:.0%} exploit "
          f"(temp {args.exploit_temp}) / {1 - args.exploit_prob:.0%} explore "
          f"(temp {args.explore_temp}, eps {args.explore_eps}), "
          f"per-{args.mode_granularity}", flush=True)

    recorder = None
    if not args.no_record and (args.record_sample_rate > 0 or args.record_top_every > 0):
        recorder = EpisodeRecorder(
            ckpt_dir / "replays.jsonl", args.n_envs, args.reward,
            args.record_sample_rate, args.record_top_every, episodes_done,
            seed=args.seed)
        print(f"[train] recording episodes to {recorder.path} "
              f"(sample rate {args.record_sample_rate:.2%}, "
              f"top-of-{args.record_top_every} windows)", flush=True)

    callback = CheckpointAndStopCallback(
        ckpt_dir, args.checkpoint_every, episodes_done, args.snapshot_every,
        recorder=recorder)
    _install_signal_handlers()
    print(f"[train] pid {os.getpid()} - stop with: kill {os.getpid()} (or Ctrl-C)",
          flush=True)

    total = args.total_timesteps if args.total_timesteps else int(1e12)
    try:
        model.learn(total_timesteps=total, callback=callback,
                    reset_num_timesteps=reset_counters, progress_bar=False)
    finally:
        callback.save("latest")
        if recorder is not None:
            recorder.flush_top()
        vec_env.close()
        print(f"[train] done: {callback.episodes} episodes total; "
              f"checkpoint at {latest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
