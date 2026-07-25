"""blueprince-dash: local web server for training observability.

Pure stdlib. Serves a two-tab SPA (learning-progress dashboard + run
inspector) plus a JSON API over the artifacts a training run writes to its
checkpoint dir (``latest.json``, ``replays.jsonl``), and runs two background
workers:

- a metrics sampler that polls ``latest.json`` and appends timestamped rows to
  ``<checkpoint-dir>/metrics.jsonl`` (subsumes the old out-of-tree sampler);
- an eval worker that, whenever ``latest.zip`` changes, spawns a subprocess
  ``blueprince-train --evaluate N --eval-json <checkpoint-dir>/eval.jsonl`` -
  the deterministic (exploration disabled) baseline series.

Binds 0.0.0.0 so the dashboard is reachable on the local network. Read-only
API, no auth: intended for home-LAN use only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import replay

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_CHART_POINTS = 2000
FRAMES_CACHE_SIZE = 8


def _read_jsonl(path: Path) -> list[dict]:
    """Parse a .jsonl file, skipping malformed lines; [] when the file is missing."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a mid-write partial last line
    return out


def _downsample(rows: list, limit: int = MAX_CHART_POINTS) -> list:
    """Thin rows to at most ``limit`` by even striding, always keeping the last row."""
    if len(rows) <= limit:
        return rows
    stride = len(rows) / limit
    picked = [rows[int(i * stride)] for i in range(limit)]
    if picked[-1] is not rows[-1]:
        picked[-1] = rows[-1]
    return picked


class Observatory:
    """All run-dir state behind the HTTP API."""

    def __init__(self, ckpt_dir: Path, reward: str) -> None:
        self.ckpt_dir = ckpt_dir
        self.reward = reward
        self.replays_path = ckpt_dir / "replays.jsonl"
        self.metrics_path = ckpt_dir / "metrics.jsonl"
        self.eval_path = ckpt_dir / "eval.jsonl"
        self.latest_json = ckpt_dir / "latest.json"
        self.latest_zip = ckpt_dir / "latest.zip"
        self._lock = threading.Lock()
        self._records: dict[int, dict] = {}   # episode -> full replay record
        self._replay_offset = 0
        self._frames_cache: OrderedDict[int, list] = OrderedDict()
        self._registry = None

    # ------------------------------------------------------------- replays

    def _refresh_replays(self) -> None:
        """Incrementally ingest new complete lines appended to replays.jsonl.

        Caller must hold ``self._lock``. A later line for the same episode
        replaces the earlier one, but the ``top`` flag is sticky once set.
        """
        try:
            size = self.replays_path.stat().st_size
        except FileNotFoundError:
            return
        if size <= self._replay_offset:
            return
        with self.replays_path.open("rb") as f:
            f.seek(self._replay_offset)
            chunk = f.read()
        # Only consume complete lines; a partial tail is re-read next time.
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        self._replay_offset += end + 1
        for line in chunk[:end].splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ep = rec.get("episode")
            if ep is None:
                continue
            prev = self._records.get(ep)
            top = rec.get("why") == "top_window" or (prev or {}).get("top", False)
            rec["top"] = top
            self._records[ep] = rec

    def runs_index(self, sort: str) -> list[dict]:
        """Lightweight metadata for every recorded episode, for the run list.

        ``sort="progress"`` orders by (win, deepest rank, episode) descending;
        anything else orders newest-episode first.
        """
        with self._lock:
            self._refresh_replays()
            metas = [
                {"episode": r["episode"], "win": r.get("win", False),
                 "deepest_rank": r.get("deepest_rank", 0),
                 "rooms_placed": r.get("rooms_placed", 0),
                 "reason": r.get("reason"), "top": r.get("top", False),
                 "moves": len(r.get("actions", [])),
                 "saved_at": r.get("saved_at")}
                for r in self._records.values()
            ]
        if sort == "progress":
            metas.sort(key=lambda m: (m["win"], m["deepest_rank"], m["episode"]),
                       reverse=True)
        else:
            metas.sort(key=lambda m: m["episode"], reverse=True)
        return metas

    def run_frames(self, episode: int) -> dict | None:
        """Full frame-by-frame replay of one episode, or None if unknown.

        Frames are rebuilt by re-simulating the recorded actions, which is
        slow, so results live in a small LRU cache; the rebuild itself runs
        outside the lock.
        """
        with self._lock:
            self._refresh_replays()
            rec = self._records.get(episode)
            if rec is None:
                return None
            cached = self._frames_cache.get(episode)
            if cached is not None:
                self._frames_cache.move_to_end(episode)
                return cached
        frames = replay.build_frames(rec)
        result = {
            "episode": episode, "seed": rec["seed"], "win": rec.get("win", False),
            "deepest_rank": rec.get("deepest_rank", 0),
            "reason": rec.get("reason"), "top": rec.get("top", False),
            "frames": frames,
        }
        with self._lock:
            self._frames_cache[episode] = result
            while len(self._frames_cache) > FRAMES_CACHE_SIZE:
                self._frames_cache.popitem(last=False)
        return result

    # ------------------------------------------------------------- metrics

    def metrics(self) -> dict:
        """Chart series for the dashboard: ``{"train": [...], "eval": [...]}``.

        Merges the per-run metrics.jsonl with any legacy shared sampler file,
        de-duplicates by (episodes, timesteps), sorts by sample time, and
        downsamples both series.
        """
        rows = _read_jsonl(self.metrics_path)
        # Merge history from the legacy shared sampler file (runs/metrics.jsonl)
        # so an existing run's curve is not lost when switching to the server.
        legacy = self.ckpt_dir.parent / "metrics.jsonl"
        if legacy.exists() and legacy != self.metrics_path:
            rows += _read_jsonl(legacy)
        seen, train = set(), []
        for m in sorted(rows, key=lambda m: m.get("sampled_at", 0)):
            key = (m.get("episodes"), m.get("timesteps"))
            if key in seen or m.get("sampled_at") is None:
                continue
            seen.add(key)
            train.append({
                "episodes": m.get("episodes"), "timesteps": m.get("timesteps"),
                "sampled_at": m.get("sampled_at"),
                "win_rate_recent": m.get("win_rate_recent"),
                "win_rate_exploit": m.get("win_rate_exploit"),
                "win_rate_explore": m.get("win_rate_explore"),
            })
        evals = sorted(_read_jsonl(self.eval_path),
                       key=lambda m: m.get("sampled_at", 0))
        return {"train": _downsample(train), "eval": _downsample(evals)}

    def summary(self) -> dict:
        """Header stats: latest checkpoint meta + mtime, replay count, last eval."""
        latest = {}
        if self.latest_json.exists():
            try:
                latest = json.loads(self.latest_json.read_text())
            except json.JSONDecodeError:
                pass
        ckpt_mtime = None
        if self.latest_zip.exists():
            ckpt_mtime = self.latest_zip.stat().st_mtime
        evals = _read_jsonl(self.eval_path)
        with self._lock:
            self._refresh_replays()
            n_replays = len(self._records)
        return {
            "run": self.ckpt_dir.name, "latest": latest,
            "checkpoint_mtime": ckpt_mtime, "now": time.time(),
            "n_replays": n_replays,
            "last_eval": evals[-1] if evals else None,
        }

    def rooms(self) -> list[dict]:
        """Static room metadata for the client, loading the engine Registry lazily."""
        if self._registry is None:
            from ..engine.model import Registry
            self._registry = Registry.load()
        return replay.rooms_meta(self._registry)


# ----------------------------------------------------------- background work

def metrics_sampler(obs: Observatory, poll_s: float, stop: threading.Event) -> None:
    """Background worker: poll latest.json, append new samples to metrics.jsonl.

    A row is written only when the (episodes, timesteps) pair changes, with a
    ``sampled_at`` wall-clock timestamp added for the charts.
    """
    last_key = None
    while not stop.wait(poll_s):
        try:
            latest = json.loads(obs.latest_json.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        key = (latest.get("episodes"), latest.get("timesteps"))
        if key == last_key or key[0] is None:
            continue
        last_key = key
        latest["sampled_at"] = time.time()
        with obs.metrics_path.open("a") as f:
            f.write(json.dumps(latest) + "\n")


def eval_worker(obs: Observatory, episodes: int, poll_s: float,
                stop: threading.Event) -> None:
    """Background worker: run a deterministic eval whenever latest.zip changes.

    Spawns ``blueprince-train --evaluate`` as a subprocess so torch never
    loads into the server; results land in eval.jsonl. Checkpoints whose
    trained-episode count was already evaluated are skipped, so a server
    restart does not re-evaluate old checkpoints.
    """
    last_mtime = None
    # Skip checkpoints already evaluated (survives server restarts).
    evals = _read_jsonl(obs.eval_path)
    done_episodes = {e.get("episodes") for e in evals}
    while not stop.wait(poll_s):
        if not obs.latest_zip.exists():
            continue
        mtime = obs.latest_zip.stat().st_mtime
        if mtime == last_mtime:
            continue
        try:
            trained = json.loads(obs.latest_json.read_text()).get("episodes")
        except (FileNotFoundError, json.JSONDecodeError):
            trained = None
        if trained is not None and trained in done_episodes:
            last_mtime = mtime
            continue
        last_mtime = mtime
        cmd = [sys.executable, "-m", "blueprince_sim.rl.train",
               "--checkpoint-dir", str(obs.ckpt_dir),
               "--evaluate", str(episodes),
               "--eval-json", str(obs.eval_path),
               "--reward", obs.reward, "--device", "cpu"]
        print(f"[dash] evaluating checkpoint ({episodes} episodes)...", flush=True)
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            done_episodes.add(trained)
            print(f"[dash] eval done in {time.time() - t0:.0f}s: "
                  f"{proc.stdout.strip().splitlines()[-1] if proc.stdout else ''}",
                  flush=True)
        else:
            print(f"[dash] eval failed (rc {proc.returncode}): "
                  f"{proc.stderr.strip()[-500:]}", flush=True)


# ------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    obs: Observatory  # set on the server class

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        """Route the SPA, the flat /static files, and the read-only JSON API."""
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            match path:
                case "/" | "/index.html":
                    self._send_file(STATIC_DIR / "index.html", "text/html")
                case _ if path.startswith("/static/"):
                    name = Path(path).name  # flat static dir; no traversal
                    ctype = {"js": "application/javascript", "css": "text/css",
                             "html": "text/html"}.get(name.rsplit(".", 1)[-1],
                                                      "application/octet-stream")
                    self._send_file(STATIC_DIR / name, ctype)
                case "/api/summary":
                    self._send_json(self.obs.summary())
                case "/api/metrics":
                    self._send_json(self.obs.metrics())
                case "/api/rooms":
                    self._send_json(self.obs.rooms())
                case "/api/runs":
                    sort = parse_qs(parsed.query).get("sort", ["episode"])[0]
                    self._send_json(self.obs.runs_index(sort))
                case _ if path.startswith("/api/run/"):
                    try:
                        episode = int(path.rsplit("/", 1)[-1])
                    except ValueError:
                        self.send_error(400, "bad episode")
                        return
                    data = self.obs.run_frames(episode)
                    if data is None:
                        self.send_error(404, "unknown episode")
                    else:
                        self._send_json(data)
                case _:
                    self.send_error(404)
        except BrokenPipeError:
            pass

    def _send_json(self, data) -> None:
        """Write ``data`` as a 200 JSON response, marked no-store so polls stay fresh."""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype: str) -> None:
        """Write a static file as a 200 response, or 404 if it does not exist."""
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args) -> None:
        pass  # quiet; the workers print the interesting events


def main(argv: list[str] | None = None) -> int:
    """blueprince-dash entry point: start the daemon workers, serve until Ctrl-C."""
    parser = argparse.ArgumentParser(
        prog="blueprince-dash",
        description="Local web dashboard + run replay for blueprince-train.")
    parser.add_argument("--checkpoint-dir", default="runs/all-unlocks",
                        help="training run dir (latest.json / replays.jsonl)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default 0.0.0.0: reachable on LAN)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--reward", choices=["shaped", "sparse"], default="shaped",
                        help="reward config used for eval + replay reconstruction")
    parser.add_argument("--eval-episodes", type=int, default=500,
                        help="deterministic eval episodes per new checkpoint "
                             "(the exploration-disabled baseline)")
    parser.add_argument("--no-eval", action="store_true",
                        help="disable the background eval worker")
    parser.add_argument("--metrics-poll", type=float, default=60.0,
                        help="seconds between latest.json samples")
    parser.add_argument("--eval-poll", type=float, default=30.0,
                        help="seconds between latest.zip mtime checks")
    args = parser.parse_args(argv)

    obs = Observatory(Path(args.checkpoint_dir), args.reward)
    stop = threading.Event()
    threading.Thread(target=metrics_sampler, args=(obs, args.metrics_poll, stop),
                     daemon=True, name="metrics-sampler").start()
    if not args.no_eval:
        threading.Thread(target=eval_worker,
                         args=(obs, args.eval_episodes, args.eval_poll, stop),
                         daemon=True, name="eval-worker").start()

    Handler.obs = obs
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[dash] serving {obs.ckpt_dir} on http://{args.host}:{args.port} "
          f"(LAN: http://<this-mac's-ip>:{args.port})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
