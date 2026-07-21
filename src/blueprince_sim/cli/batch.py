"""Batch Monte-Carlo evaluation of scripted policies."""

from __future__ import annotations

import math
import random
from collections import Counter

from ..config import GameConfig
from ..engine.game import Game, Phase
from .policies import POLICIES


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def run_episode(cfg: GameConfig, policy, seed: int, max_decisions: int = 800) -> dict:
    game = Game(cfg, seed=seed)
    rnd = random.Random(seed)
    decisions = 0
    def snapshot() -> tuple:
        st = game.state
        return (game.phase, st.steps, game.rooms_placed, st.pos,
                len(st.pending.options) if st.pending else -1)

    while game.phase is not Phase.TERMINAL and decisions < max_decisions:
        decisions += 1
        before = snapshot()
        policy(game, rnd)
        if snapshot() == before:
            # Policy made no progress this decision. Force a resolution: take
            # the guaranteed free slot (no decline), or end a day that can no
            # longer advance.
            if game.phase is Phase.DRAFTING and game.state.pending is not None:
                game.choose(min(o.slot for o in game.state.pending.options))
            else:
                game._check_termination()
                if game.phase is not Phase.TERMINAL:
                    break
    if game.phase is not Phase.TERMINAL:
        game.termination_reason = game.termination_reason or "decision_limit"
    st = game.state
    return {
        "success": game.success(),
        "reason": game.termination_reason,
        "deepest_rank": game.deepest_rank,
        "rooms_placed": game.rooms_placed,
        "steps_left": st.steps,
        "gems": st.gems, "keys": st.keys, "coins": st.coins,
    }


def run_batch(cfg: GameConfig, policy_name: str, episodes: int, seed0: int = 0,
              quiet: bool = False) -> dict:
    policy = POLICIES[policy_name]
    results = [run_episode(cfg, policy, seed0 + i) for i in range(episodes)]
    wins = sum(r["success"] for r in results)
    lo, hi = wilson_ci(wins, episodes)
    reasons = Counter(r["reason"] for r in results)
    ranks = Counter(r["deepest_rank"] for r in results)
    summary = {
        "policy": policy_name,
        "episodes": episodes,
        "p_antechamber": wins / episodes,
        "ci95": (lo, hi),
        "mean_deepest_rank": sum(r["deepest_rank"] for r in results) / episodes,
        "mean_rooms_placed": sum(r["rooms_placed"] for r in results) / episodes,
        "termination_reasons": dict(reasons),
        "rank_histogram": dict(sorted(ranks.items())),
    }
    if not quiet:
        print(f"policy={policy_name}  episodes={episodes}")
        print(f"P(reach Antechamber) = {summary['p_antechamber']:.3%}  "
              f"(95% CI {lo:.3%} - {hi:.3%})")
        print(f"mean deepest rank = {summary['mean_deepest_rank']:.2f}   "
              f"mean rooms placed = {summary['mean_rooms_placed']:.1f}")
        print(f"terminations: {dict(reasons)}")
        print(f"rank histogram: {dict(sorted(ranks.items()))}")
    return summary
