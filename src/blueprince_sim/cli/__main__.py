"""Command line entry point.

Usage:
  python -m blueprince_sim.cli play  [--seed N] [--config file.yaml] [--set key=value ...]
  python -m blueprince_sim.cli batch [--episodes N] [--seed N] [--policy name]
                                     [--config file.yaml] [--set key=value ...]
"""

from __future__ import annotations

import argparse
import sys

from ..config import GameConfig
from .batch import run_batch
from .play import play
from .policies import POLICIES


def _parse_set(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if value.lower() in ("true", "false"):
            out[key] = value.lower() == "true"
        elif value.isdigit():
            out[key] = int(value)
        elif "," in value or key in ("studio_additions", "upgrade_disks", "satisfied_conditions"):
            out[key] = [v for v in value.split(",") if v]
        else:
            out[key] = value
    return out


def build_config(args) -> GameConfig:
    if args.config:
        cfg = GameConfig.from_yaml(args.config)
    else:
        cfg = GameConfig()
    if args.set:
        base = {**cfg.__dict__}
        base["studio_additions"] = set(cfg.studio_additions)
        base["upgrade_disks"] = set(cfg.upgrade_disks)
        base["satisfied_conditions"] = set(cfg.satisfied_conditions)
        base.update(_parse_set(args.set))
        cfg = GameConfig.from_dict(base)
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blueprince-sim")
    sub = parser.add_subparsers(dest="command", required=True)

    p_play = sub.add_parser("play", help="interactive REPL")
    p_play.add_argument("--seed", type=int, default=0)
    p_play.add_argument("--config", default=None)
    p_play.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")

    p_batch = sub.add_parser("batch", help="Monte-Carlo policy evaluation")
    p_batch.add_argument("--episodes", type=int, default=1000)
    p_batch.add_argument("--seed", type=int, default=0)
    p_batch.add_argument("--policy", choices=sorted(POLICIES), default="greedy_rank")
    p_batch.add_argument("--config", default=None)
    p_batch.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")

    args = parser.parse_args(argv)
    cfg = build_config(args)
    if args.command == "play":
        play(cfg, args.seed)
    else:
        run_batch(cfg, args.policy, args.episodes, seed0=args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
