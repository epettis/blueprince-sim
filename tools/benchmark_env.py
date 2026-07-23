"""Benchmark the RL env hot path (the per-step work training pays for).

Replays a fixed set of episodes with a seeded random masked policy, exercising
exactly what MaskablePPO does per step: ``action_masks()`` -> ``step()`` (which
encodes the observation and rebuilds the info mask). Reports env steps/sec.

The action sequence is derived from the mask via a seeded RNG, so as long as an
optimization preserves engine behavior (a tested invariant), every run replays
the identical episodes and timings are directly comparable.

Usage:
    python tools/benchmark_env.py                 # timing only
    python tools/benchmark_env.py --profile       # cProfile top functions
    python tools/benchmark_env.py --episodes 300
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import random
import time

from blueprince_sim.rl.train import all_unlocks_config
from blueprince_sim.env.blueprince_env import BluePrinceEnv


def run(episodes: int, seed: int) -> tuple[int, float]:
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    rng = random.Random(seed)
    steps = 0
    t0 = time.perf_counter()
    for ep in range(episodes):
        env.reset(seed=seed + ep)
        done = False
        while not done:
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            _, _, term, trunc, _ = env.step(rng.choice(legal))
            steps += 1
            done = term or trunc
    return steps, time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--sort", default="cumulative", choices=["cumulative", "tottime"])
    args = ap.parse_args()

    if args.profile:
        prof = cProfile.Profile()
        prof.enable()
        steps, dt = run(args.episodes, args.seed)
        prof.disable()
        print(f"{steps} steps in {dt:.2f}s = {steps / dt:,.0f} steps/s")
        pstats.Stats(prof).sort_stats(args.sort).print_stats(30)
        return

    best = None
    for i in range(args.repeats):
        steps, dt = run(args.episodes, args.seed)
        rate = steps / dt
        best = max(best or 0, rate)
        print(f"run {i + 1}: {steps} steps in {dt:.2f}s = {rate:,.0f} steps/s")
    print(f"best: {best:,.0f} steps/s")


if __name__ == "__main__":
    main()
