#!/usr/bin/env python3
"""Package a trained model as a release: in-tree provenance + GitHub asset.

The model *bytes* ship as a GitHub Release asset (kept out of git history);
the *provenance* (`models/<name>/MANIFEST.json`, plus the training curve) is
committed so a checkout tells you the release exists, its stats, its exact
`sha256`, and the tag to fetch it from.

This tool is the single source of truth that keeps the three artifacts in
lockstep: it computes the sha256 of the file it publishes, writes that same
sha into the committed manifest, and (on --publish) verifies the uploaded
asset round-trips to the identical bytes.

Pure stdlib; shells out to `git` and `gh`.

Typical use (run on the default branch, after the manifest PR has merged, so
the tag points at the commit carrying this manifest):

    python tools/make_release.py \\
        --checkpoint-dir runs/all-unlocks --name baseline-ep8275991 \\
        --tag baseline-ep8275991 --trained-with-sha <sha> \\
        --metrics runs/metrics.jsonl \\
        --eval-episodes 2000 --eval-p 0.131 --eval-ci 0.11692 0.14650 \\
        --eval-rank 6.48 \\
        --publish --repo epettis/blueprince-sim

Omit --publish to only (re)write the in-tree manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def lib_versions() -> dict:
    """Best-effort: record the training env's key package versions."""
    import importlib.metadata as md
    out = {"python": sys.version.split()[0]}
    for pkg in ("sb3-contrib", "stable-baselines3", "torch", "gymnasium", "numpy"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    return out


def build_manifest(args, model_path: Path, digest: str) -> dict:
    """Assemble the MANIFEST.json dict: asset sha256/fetch command, training
    stats read from ``<checkpoint-dir>/latest.json``, config summary, and
    provenance; a deterministic_eval block is included only when
    ``--eval-episodes`` was given."""
    meta = json.loads((Path(args.checkpoint_dir) / "latest.json").read_text())
    manifest = {
        "release_name": args.name,
        "release_tag": args.tag,
        "created_at": args.created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "description": args.description,
        "asset": {
            "name": "model.zip",
            "sha256": digest,
            "bytes": model_path.stat().st_size,
            "fetch": f"gh release download {args.tag} -p model.zip",
        },
        "training": {
            "episodes": meta.get("episodes"),
            "timesteps": meta.get("timesteps"),
            "final_saved_at": meta.get("saved_at"),
            "win_rate_rolling_final": meta.get("win_rate_recent"),
        },
        "config": {
            "preset": "all_unlocks_config (day=20, orchard+mine+outer_rooms, "
                      "all 8 studio additions, no upgrade disks)",
            "reward": args.reward,
            "algo": "MaskablePPO",
            "policy": "MixedExplorationPolicy",
        },
        "provenance": {
            "trained_with_git_sha": args.trained_with_sha,
            "libs": lib_versions(),
        },
    }
    if args.eval_episodes:
        manifest["deterministic_eval"] = {
            "p_antechamber": args.eval_p,
            "ci95": args.eval_ci,
            "mean_deepest_rank": args.eval_rank,
            "episodes": args.eval_episodes,
            "note": "greedy/argmax play; reproduce with "
                    f"blueprince-train --evaluate {args.eval_episodes} "
                    "--model models/" + args.name + "/model.zip",
        }
    return manifest


def write_intree(args, manifest: dict) -> Path:
    """Write the committed provenance: models/<name>/MANIFEST.json plus a copy
    of the training curve (``--metrics`` -> metrics.jsonl); returns the dir."""
    out_dir = ROOT / "models" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.metrics:
        shutil.copy2(args.metrics, out_dir / "metrics.jsonl")
    return out_dir


def publish(args, model_path: Path, digest: str) -> None:
    """Tag HEAD, create the GitHub Release, and upload the model as model.zip.

    Force-moves and force-pushes the tag, so rerunning repoints an existing
    release tag. Afterwards the asset is downloaded back and re-hashed; on a
    sha256 mismatch with the manifest the process exits with code 2.
    """
    tag = args.tag
    # Tag the current HEAD (run this on the merged default branch).
    subprocess.run(["git", "tag", "-f", tag], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-f", "origin", tag], cwd=ROOT, check=True)
    repo = ["--repo", args.repo] if args.repo else []
    notes = (f"Baseline drafting policy. {manifest_stats(args)}\n\n"
             f"model.zip sha256: `{digest}`")
    with tempfile.TemporaryDirectory() as td:
        # gh names the asset after the file's basename, so stage a copy called
        # model.zip (the source is <ckpt-dir>/latest.zip) to match the manifest.
        staged = Path(td) / "model.zip"
        shutil.copy2(model_path, staged)
        subprocess.run(
            ["gh", "release", "create", tag, str(staged),
             "--title", args.name, "--notes", notes, *repo],
            cwd=ROOT, check=True)
        # Round-trip verify: the published asset must hash to the same bytes.
        dl = Path(td) / "dl"
        dl.mkdir()
        subprocess.run(
            ["gh", "release", "download", tag, "-p", "model.zip",
             "--dir", str(dl), *repo],
            cwd=ROOT, check=True)
        got = sha256(dl / "model.zip")
    if got != digest:
        print(f"FATAL: published asset sha {got} != manifest sha {digest}",
              file=sys.stderr)
        sys.exit(2)
    print(f"verified: published asset matches manifest sha256 ({digest[:16]}...)")


def manifest_stats(args) -> str:
    """One-line eval summary for the release notes; "" when no eval was supplied."""
    if args.eval_episodes:
        return (f"Deterministic P(Antechamber) = {args.eval_p:.1%} over "
                f"{args.eval_episodes} episodes.")
    return ""


def main(argv: list[str] | None = None) -> int:
    """Write the in-tree manifest, then publish if requested.

    Returns 1 if the model file is missing, else 0 (publish itself exits 2 on
    a failed round-trip verification). Without ``--publish`` this is a dry run
    that only rewrites models/<name>/.
    """
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--checkpoint-dir", required=True,
                   help="dir holding latest.zip + latest.json")
    p.add_argument("--name", required=True, help="release name / models/<name>/ dir")
    p.add_argument("--tag", required=True, help="git tag / GitHub Release tag")
    p.add_argument("--model", default=None,
                   help="model.zip to publish (default <checkpoint-dir>/latest.zip)")
    p.add_argument("--trained-with-sha", required=True,
                   help="git SHA of the code that trained this model")
    p.add_argument("--reward", default="shaped")
    p.add_argument("--description", default="Frozen baseline model.")
    p.add_argument("--metrics", default=None, help="metrics.jsonl to copy in-tree")
    p.add_argument("--created-at", default=None, help="ISO timestamp override")
    p.add_argument("--eval-episodes", type=int, default=0)
    p.add_argument("--eval-p", type=float, default=None)
    p.add_argument("--eval-ci", type=float, nargs=2, default=None)
    p.add_argument("--eval-rank", type=float, default=None)
    p.add_argument("--publish", action="store_true",
                   help="create the tag + GitHub Release and upload model.zip")
    p.add_argument("--repo", default=None, help="owner/repo for gh (else inferred)")
    args = p.parse_args(argv)

    model_path = Path(args.model) if args.model \
        else Path(args.checkpoint_dir) / "latest.zip"
    if not model_path.exists():
        print(f"no model at {model_path}", file=sys.stderr)
        return 1

    digest = sha256(model_path)
    manifest = build_manifest(args, model_path, digest)
    out_dir = write_intree(args, manifest)
    rel = out_dir.relative_to(ROOT)
    print(f"wrote {rel}/MANIFEST.json (model.zip sha256 {digest[:16]}...)")

    if args.publish:
        publish(args, model_path, digest)
    else:
        print("dry run (no --publish); to publish the asset later, rerun on the "
              "merged default branch with --publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
