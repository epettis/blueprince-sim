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


class CheckpointAndStopCallback:
    """Counts finished episodes, checkpoints every N, stops on signal.

    Implemented as an sb3 BaseCallback subclass created lazily so this module
    imports without torch installed.
    """

    def __new__(cls, *args, **kwargs):
        from stable_baselines3.common.callbacks import BaseCallback

        class _Impl(BaseCallback):
            def __init__(self, ckpt_dir: Path, every_episodes: int,
                         episodes_done: int, snapshot_every: int) -> None:
                super().__init__()
                self.ckpt_dir = ckpt_dir
                self.every = every_episodes
                self.episodes = episodes_done
                self.next_ckpt = episodes_done + every_episodes
                self.snapshot_every = snapshot_every
                self.recent = deque(maxlen=1000)
                self.recent_exploit = deque(maxlen=1000)
                self.recent_explore = deque(maxlen=1000)
                self.t0 = time.time()

            def _on_step(self) -> bool:
                infos = self.locals.get("infos", ())
                policy = getattr(self.model, "policy", None)
                mixed = hasattr(policy, "resample_modes")
                done_indices = []
                for i, (done, info) in enumerate(
                        zip(self.locals.get("dones", ()), infos)):
                    if not done:
                        continue
                    self.episodes += 1
                    win = 1.0 if info.get("termination_reason") == "antechamber" else 0.0
                    self.recent.append(win)
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
    def handler(signum, frame):
        if STOP.is_set():  # second signal: exit hard
            print("[train] second signal - exiting immediately", flush=True)
            sys.exit(1)
        STOP.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def evaluate(ckpt_dir: Path, episodes: int, reward: str, seed: int,
             device: str) -> int:
    """Deterministic rollout of the checkpointed policy; prints win rate."""
    from sb3_contrib import MaskablePPO

    from ..cli.batch import wilson_ci

    latest = ckpt_dir / "latest.zip"
    if not latest.exists():
        print(f"no checkpoint at {latest}", file=sys.stderr)
        return 1
    model = MaskablePPO.load(latest, device=device)
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
    print(f"evaluated {latest}: P(Antechamber) = {wins / episodes:.3%} "
          f"(95% CI {lo:.3%} - {hi:.3%}), mean deepest rank "
          f"{sum(ranks) / len(ranks):.2f} over {episodes} episodes")
    return 0


def main(argv: list[str] | None = None) -> int:
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
                        help="don't train: evaluate latest.zip for N episodes "
                             "and report the win rate")
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
                        args.seed, args.device)

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

    callback = CheckpointAndStopCallback(
        ckpt_dir, args.checkpoint_every, episodes_done, args.snapshot_every)
    _install_signal_handlers()
    print(f"[train] pid {os.getpid()} - stop with: kill {os.getpid()} (or Ctrl-C)",
          flush=True)

    total = args.total_timesteps if args.total_timesteps else int(1e12)
    try:
        model.learn(total_timesteps=total, callback=callback,
                    reset_num_timesteps=reset_counters, progress_bar=False)
    finally:
        callback.save("latest")
        vec_env.close()
        print(f"[train] done: {callback.episodes} episodes total; "
              f"checkpoint at {latest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
