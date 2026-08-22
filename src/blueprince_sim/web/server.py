"""blueprince-dash: local web server for training observability.

Pure stdlib. Serves a four-tab SPA (dashboard, learning-progress, run
inspector, and a "Play" tab for recording human demonstrations -- see
``play.py``) plus a JSON API over the artifacts a training run writes to its
checkpoint dir (``latest.json``, ``replays.jsonl``), and runs two background
workers:

- a metrics sampler that polls ``latest.json`` and appends timestamped rows to
  ``<checkpoint-dir>/metrics.jsonl``;
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
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from . import play as _play
from . import replay
from ..engine import areas as _areas_mod
# Pure-stdlib metric spec table (see its module docstring) -- importing it does
# NOT pull in sb3/torch, preserving the "server never loads torch" invariant
# the eval_worker subprocess split also relies on.
from ..rl import dashboard as _dashboard

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_CHART_POINTS = 2000
FRAMES_CACHE_SIZE = 8
# Caps the number of ordinary (non-top) replay records held in memory by an
# Observatory; best-of-window ("top") records are exempt from this cap.
DEFAULT_MAX_RUNS = 20000


# Upgrade-economy bucket width in IN-GAME DAYS.  Attempts are 200 days, so this
# gives ~20 points across an attempt; the 10k episode bucket would give one.
_ECONOMY_DAY_BUCKET = 10


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


class _RunMeta(NamedTuple):
    """Lightweight per-episode replay index entry (no actions/modes payload).

    Enough to answer the run-list API and to seek+parse the one JSONL line
    needed for a frame rebuild, without holding every episode's full record
    (actions list + modes string) in memory.
    """

    offset: int          # byte offset of this record's line start within replays.jsonl
    length: int           # length of that line in bytes, EXCLUDING the trailing newline
    win: bool             # from rec["win"]
    deepest_rank: int     # deepest grid rank (1-9) the episode reached
    rooms_placed: int     # count of rooms drafted+placed during the episode
    moves: int            # len(rec["actions"]) at ingest time; the list itself is dropped
    top: bool             # sticky best-of-window flag (see _refresh_replays docstring)
    reason: str | None    # termination reason string, interned when not None
    saved_at: str | None  # ISO timestamp string the recorder wrote, interned when not None


class Observatory:
    """All run-dir state behind the HTTP API.

    Replay records are held as a byte-offset index (``_RunMeta``) rather than
    the full parsed JSON, and ``_recent`` is capped at ``max_runs`` entries
    (oldest ingested evicted first) so memory stays bounded even for very
    long runs. ``_top`` (best-of-window records) is deliberately NOT capped:
    it grows at roughly one entry per ``--record-top-every`` episodes (the
    trainer default is 1000), so ~10k entries - a few MB - at 10M episodes.
    Setting ``--record-top-every 1`` would defeat the cap on ``_top``; that
    tradeoff is intentional but worth stating plainly rather than implying
    memory is bounded unconditionally.
    """

    def __init__(self, ckpt_dir: Path, reward: str, max_runs: int = DEFAULT_MAX_RUNS) -> None:
        self.ckpt_dir = ckpt_dir
        self.reward = reward
        self.replays_path = ckpt_dir / "replays.jsonl"
        self.metrics_path = ckpt_dir / "metrics.jsonl"
        self.eval_path = ckpt_dir / "eval.jsonl"
        self.draft_stats_path = ckpt_dir / "draft_stats.jsonl"
        self.area_stats_path = ckpt_dir / "area_stats.jsonl"
        self.copula_stats_path = ckpt_dir / "copula_stats.jsonl"
        self.upgrades_path = ckpt_dir / "upgrades.jsonl"
        self.latest_json = ckpt_dir / "latest.json"
        self.latest_zip = ckpt_dir / "latest.zip"
        self._lock = threading.Lock()
        self.max_runs = max_runs
        self._top: dict[int, _RunMeta] = {}  # best-of-window records; never evicted
        self._recent: OrderedDict[int, _RunMeta] = OrderedDict()  # ordinary; capped at max_runs
        self._replay_offset = 0
        self._frames_cache: OrderedDict[int, list] = OrderedDict()
        self._registry = None

    # ------------------------------------------------------------- replays

    def _refresh_replays(self) -> None:
        """Incrementally ingest new complete lines appended to replays.jsonl.

        Caller must hold ``self._lock``. Each ingested line is stored as a
        ``_RunMeta`` offset index (byte offset + length + summary fields)
        rather than the full parsed record, so ``run_frames`` seeks back into
        the file to re-read the JSON line it needs.

        A later line for the same episode replaces the earlier one (its
        offset/length win), but the ``top`` flag is sticky once set - an
        episode that was ever ``top_window`` stays top even if a later
        ``random`` line arrives for it. Top records go into ``self._top``
        (never evicted); ordinary records go into ``self._recent``, an
        ``OrderedDict`` capped at ``self.max_runs`` entries, evicting the
        entries ingested longest ago. Because several parallel envs can
        finish concurrently, ingestion order (file order) is not always the
        same as episode-number order - eviction follows ingestion order, the
        more honest notion of "most recent" here.

        If the file shrinks (truncated or replaced, e.g. a new run reusing
        the checkpoint dir), all stored offsets are meaningless against the
        new content, so the whole index is reset and re-ingested from
        scratch.
        """
        try:
            size = self.replays_path.stat().st_size
        except FileNotFoundError:
            return
        if size < self._replay_offset:
            # file truncated or replaced: stored offsets are meaningless, start over
            self._replay_offset = 0
            self._top.clear()
            self._recent.clear()
            self._frames_cache.clear()
        elif size == self._replay_offset:
            return
        with self.replays_path.open("rb") as f:
            f.seek(self._replay_offset)
            chunk = f.read()
        # Only consume complete lines; a partial tail is re-read next time.
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        base = self._replay_offset
        self._replay_offset += end + 1
        pos = 0
        for line in chunk[:end + 1].split(b"\n"):
            line_offset = base + pos
            pos += len(line) + 1
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ep = rec.get("episode")
            if ep is None:
                continue
            prev = self._top.get(ep) or self._recent.get(ep)
            was_top = prev.top if prev is not None else False
            top = rec.get("why") == "top_window" or was_top
            reason = rec.get("reason")
            saved_at = rec.get("saved_at")
            meta = _RunMeta(
                offset=line_offset, length=len(line),
                win=rec.get("win", False), deepest_rank=rec.get("deepest_rank", 0),
                rooms_placed=rec.get("rooms_placed", 0), moves=len(rec.get("actions", [])),
                top=top,
                reason=sys.intern(reason) if reason is not None else None,
                saved_at=sys.intern(saved_at) if saved_at is not None else None,
            )
            if top:
                self._top[ep] = meta
                self._recent.pop(ep, None)
            else:
                self._recent[ep] = meta
                self._recent.move_to_end(ep)
        while len(self._recent) > self.max_runs:
            self._recent.popitem(last=False)

    def runs_index(self, sort: str) -> list[dict]:
        """Lightweight metadata for every recorded episode, for the run list.

        ``sort="progress"`` orders by (win, deepest rank, episode) descending;
        anything else orders newest-episode first.
        """
        with self._lock:
            self._refresh_replays()
            metas = [
                {"episode": ep, "win": m.win, "deepest_rank": m.deepest_rank,
                 "rooms_placed": m.rooms_placed, "reason": m.reason, "top": m.top,
                 "moves": m.moves, "saved_at": m.saved_at}
                for store in (self._top, self._recent)
                for ep, m in store.items()
            ]
        if sort == "progress":
            metas.sort(key=lambda m: (m["win"], m["deepest_rank"], m["episode"]),
                       reverse=True)
        else:
            metas.sort(key=lambda m: m["episode"], reverse=True)
        return metas

    def run_frames(self, episode: int, debug: bool = False) -> dict | None:
        """Full frame-by-frame replay of one episode, or None if unknown.

        Frames are rebuilt by re-simulating the recorded actions, which is
        slow, so results live in a small LRU cache; the rebuild itself runs
        outside the lock. The single JSONL line is re-read via the stored
        byte offset/length; a stale offset (rotated file, corrupt read) is
        treated as "unknown episode" rather than raising a 500.

        ``debug`` attaches per-option counterfactual rewards to every frame
        with an open hand (``replay.option_rewards``). Cached separately from
        the plain build: the two differ in content, so one key would serve a
        debug viewer a frame set with no rewards in it, or the reverse.
        """
        with self._lock:
            self._refresh_replays()
            meta = self._top.get(episode)
            if meta is None:
                meta = self._recent.get(episode)
            if meta is None:
                return None
            cache_key = (episode, debug)
            cached = self._frames_cache.get(cache_key)
            if cached is not None:
                self._frames_cache.move_to_end(cache_key)
                return cached
        try:
            with self.replays_path.open("rb") as f:
                f.seek(meta.offset)
                raw = f.read(meta.length)
            rec = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return None
        if rec.get("episode") != episode:
            return None
        rec["top"] = meta.top
        frames, divergence = replay.build_frames(rec, debug=debug)
        result = {
            "episode": episode, "seed": rec["seed"], "win": rec.get("win", False),
            "deepest_rank": rec.get("deepest_rank", 0),
            "reason": rec.get("reason"), "top": rec.get("top", False),
            "frames": frames,
            "divergence": divergence,
        }
        with self._lock:
            self._frames_cache[cache_key] = result
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
            row = {
                "episodes": m.get("episodes"), "timesteps": m.get("timesteps"),
                "sampled_at": m.get("sampled_at"),
                "win_rate_recent": m.get("win_rate_recent"),
                "win_rate_exploit": m.get("win_rate_exploit"),
                "win_rate_explore": m.get("win_rate_explore"),
            }
            # The Progress tab mirrors the CLI dashboard's SPECS table, keyed by
            # the literal sb3 logger keys (e.g. "train/approx_kl") that
            # rl/train.py's checkpoint metadata now carries when present (see
            # _logger_snapshot). Rows from a metrics.jsonl written before that
            # change simply lack these keys, so every lookup here is None --
            # the Progress tab's job, not this endpoint's, to say so honestly.
            for spec in _dashboard.SPECS:
                row[spec.key] = m.get(spec.key)
            train.append(row)
        evals = sorted(_read_jsonl(self.eval_path),
                       key=lambda m: m.get("sampled_at", 0))
        return {"train": _downsample(train), "eval": _downsample(evals)}

    def summary(self) -> dict:
        """Header stats: latest checkpoint meta + mtime, replay count, last eval."""
        latest = {}
        if self.latest_json.exists():
            try:
                latest = json.loads(self.latest_json.read_text())
            except (json.JSONDecodeError, PermissionError, FileNotFoundError):
                pass  # mid-replace or just-deleted; the next request retries
        ckpt_mtime = None
        if self.latest_zip.exists():
            ckpt_mtime = self.latest_zip.stat().st_mtime
        evals = _read_jsonl(self.eval_path)
        with self._lock:
            self._refresh_replays()
            n_replays = len(self._top) + len(self._recent)
        return {
            "run": self.ckpt_dir.name, "latest": latest,
            "checkpoint_mtime": ckpt_mtime, "now": time.time(),
            "n_replays": n_replays,
            "last_eval": evals[-1] if evals else None,
        }

    def draft_stats(self) -> dict:
        """Draft-frequency series for the dashboard.

        ``train``: 10k-episode buckets from draft_stats.jsonl, rows merged by
        ``bucket_start`` (partial buckets from stops/resumes sum back
        together). ``eval``: per-checkpoint counts from the eval rows that
        carry them (older rows without drafts are skipped).
        """
        merged: dict[int, dict] = {}
        for row in _read_jsonl(self.draft_stats_path):
            start = row.get("bucket_start")
            if start is None:
                continue
            b = merged.setdefault(start, {
                "bucket_start": start, "bucket_end": row.get("bucket_end"),
                "seeds": 0, "drafts": {}, "seeds_with": {}})
            b["seeds"] += row.get("seeds", 0)
            for key in ("drafts", "seeds_with"):
                for name, n in (row.get(key) or {}).items():
                    b[key][name] = b[key].get(name, 0) + n
        evals = [
            {"episodes": r.get("episodes"), "eval_episodes": r.get("eval_episodes"),
             "drafts": r["drafts"], "seeds_with": r.get("seeds_with", {}),
             "sampled_at": r.get("sampled_at")}
            for r in _read_jsonl(self.eval_path) if r.get("drafts")
        ]
        return {"train": [merged[k] for k in sorted(merged)], "eval": evals}

    def rooms(self) -> list[dict]:
        """Static room metadata for the client, loading the engine Registry lazily."""
        if self._registry is None:
            from ..engine.model import Registry
            self._registry = Registry.load()
        return replay.rooms_meta(self._registry)

    def areas(self) -> dict:
        """Area graph plus a derived BFS layout for the front end.

        Returns nodes annotated with ``depth`` (undirected BFS hops from
        ``house``, ignoring all gates) and ``band`` (surface/underground/anchor),
        all edges annotated with ``stub`` (True when any required gate is a stub),
        and a ``stub_gates`` mapping.  Nodes unreachable from ``house`` even
        undirected get ``depth: null``.
        """
        if self._registry is None:
            from ..engine.model import Registry
            self._registry = Registry.load()
        graph = self._registry.area_graph

        # BFS from "house" over the UNDIRECTED graph with ALL gates ignored.
        # Walk graph.adjacency for the forward direction and also the reverse,
        # so every edge is traversable in both directions.
        reverse: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
        for edge in graph.edges:
            reverse[edge.to_id].append(edge.from_id)

        depth: dict[str, int | None] = {nid: None for nid in graph.nodes}
        if "house" in graph.nodes:
            depth["house"] = 0
            q = deque(["house"])
            while q:
                cur = q.popleft()
                next_cost = depth[cur] + 1  # type: ignore[operator]
                # forward neighbours (ignoring gate requirements)
                for nb, _ in graph.adjacency.get(cur, []):
                    if depth[nb] is None:
                        depth[nb] = next_cost
                        q.append(nb)
                # reverse neighbours
                for nb in reverse.get(cur, []):
                    if depth[nb] is None:
                        depth[nb] = next_cost
                        q.append(nb)

        def _band(area) -> str:
            if area.surface is None:
                return "anchor"
            return "surface" if area.surface else "underground"

        nodes_out = [
            {
                "id": area.id, "name": area.name, "kind": area.kind,
                "surface": area.surface, "modelled": area.modelled,
                "depth": depth[area.id], "band": _band(area),
            }
            for area in graph.nodes.values()
        ]

        stub_gate_ids = {gid for gid, g in graph.gates.items() if g.stub}
        edges_out = [
            {
                "from": e.from_id, "to": e.to_id,
                "requires": list(e.requires),
                "stub": any(gid in stub_gate_ids for gid in e.requires),
            }
            for e in graph.edges
        ]

        return {
            "nodes": nodes_out,
            "edges": edges_out,
            "stub_gates": _areas_mod.stub_gates(graph),
        }

    def area_stats(self) -> dict:
        """Area-visit series from area_stats.jsonl, merged by bucket_start.

        Same response shape and merge semantics as draft_stats().
        Returns empty structure (not a 500) when the file is absent.
        """
        merged: dict[int, dict] = {}
        for row in _read_jsonl(self.area_stats_path):
            start = row.get("bucket_start")
            if start is None:
                continue
            b = merged.setdefault(start, {
                "bucket_start": start, "bucket_end": row.get("bucket_end"),
                "seeds": 0, "visits": {}, "seeds_with": {}})
            b["seeds"] += row.get("seeds", 0)
            for key in ("visits", "seeds_with"):
                for area_id, n in (row.get(key) or {}).items():
                    b[key][area_id] = b[key].get(area_id, 0) + n
        return {"train": [merged[k] for k in sorted(merged)]}

    def copula_stats(self) -> dict:
        """Return/depth dependence series from copula_stats.jsonl.

        One entry per bucket in episode order, carrying Spearman's rho, the
        empirical-copula grid and the marginal summaries. Unlike draft_stats
        and area_stats these rows are NOT merged by bucket_start: each row is a
        finished statistic over its own sample, and two rows covering the same
        range (a resumed run re-emitting a partial bucket) cannot be added
        together the way counts can. Later rows win.

        Returns an empty structure (not a 500) when the file is absent, which
        is the normal state for a run trained before this stream existed.
        """
        merged: dict[int, dict] = {}
        for row in _read_jsonl(self.copula_stats_path):
            start = row.get("bucket_start")
            if start is None:
                continue
            merged[start] = row
        return {"train": [merged[k] for k in sorted(merged)]}

    def upgrade_stats(self) -> dict:
        """Aggregated upgrade-decision statistics from upgrades.jsonl.

        Returns three sections:
        - ``variants``: per-variant offer/chosen counts and selection rate.
        - ``economy``: decisions bucketed by day (or arrival order), with
          means of disks_held and slots_upgraded.
        - ``gates``: total decisions, catacombs_unlocked count, and
          slot_draft_count_zero (decisions where every draft count was 0).

        Absent file -> empty structure, not a 500.
        """
        rows = _read_jsonl(self.upgrades_path)
        if not rows:
            return {"variants": [], "economy": [], "gates": {}}

        # --- variants ---
        offered_counts: dict[str, int] = {}
        chosen_counts: dict[str, int] = {}
        for row in rows:
            for vid in (row.get("offered") or []):
                offered_counts[vid] = offered_counts.get(vid, 0) + 1
            cv = row.get("chosen_variant") or ""
            if cv:
                chosen_counts[cv] = chosen_counts.get(cv, 0) + 1
        variants = sorted(
            [
                {
                    "variant": vid,
                    "offered": offered_counts[vid],
                    "chosen": chosen_counts.get(vid, 0),
                    "selection_rate": (chosen_counts.get(vid, 0) / offered_counts[vid]
                                       if offered_counts[vid] else 0.0),
                }
                for vid in offered_counts
            ],
            key=lambda v: v["offered"],
            reverse=True,
        )

        # --- economy ---
        # Bucketed by IN-GAME DAY when multi-day, because the question this answers
        # is "how far into the 16-slot supply does an attempt get" — a within-attempt
        # progression.  Days run 1..n_days (200 by default), so the 10k bucket used
        # for episode counts would collapse every decision into one point.
        # Single-day runs have no day, so they fall back to arrival order at 10k.
        has_days = any(r.get("day") is not None for r in rows)
        bucket_size = _ECONOMY_DAY_BUCKET if has_days else 10_000
        econ_buckets: dict[int, dict] = {}
        for idx, row in enumerate(rows):
            day = row.get("day")
            bucket_key = (int(day) - 1) // bucket_size if day is not None else idx // bucket_size
            b = econ_buckets.setdefault(bucket_key, {
                "bucket_start": bucket_key * bucket_size,
                "decisions": 0,
                "_disks_sum": 0.0,
                "_slots_sum": 0.0,
            })
            b["decisions"] += 1
            b["_disks_sum"] += row.get("disks_held", 0) or 0
            b["_slots_sum"] += row.get("slots_upgraded", 0) or 0
        economy = []
        for bk in sorted(econ_buckets):
            b = econ_buckets[bk]
            n = b["decisions"]
            economy.append({
                "bucket_start": b["bucket_start"],
                "decisions": n,
                "mean_disks_held": round(b["_disks_sum"] / n, 4) if n else 0.0,
                "mean_slots_upgraded": round(b["_slots_sum"] / n, 4) if n else 0.0,
            })

        # --- gates ---
        total = len(rows)
        catacombs_count = sum(1 for r in rows if r.get("catacombs_unlocked"))
        slot_zero_count = 0
        for row in rows:
            dc = row.get("draft_counts") or {}
            if not dc or all(v == 0 for v in dc.values()):
                slot_zero_count += 1
        gates = {
            "decisions": total,
            "catacombs_unlocked": catacombs_count,
            "slot_draft_count_zero": slot_zero_count,
        }

        return {"variants": variants, "economy": economy, "gates": gates,
                "economy_axis": "day" if has_days else "decision"}


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
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            # PermissionError: Windows raises it while the trainer is
            # mid-os.replace on this very file. Transient -- the next poll
            # sees the new contents; crashing this thread would silently
            # stop the dashboard updating for the rest of the run.
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
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
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
    play_session: _play.PlaySession | None = None  # set/replaced by POST /api/play/new
    demos_path: Path  # set on the server class from --demos

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
                case "/api/draft_stats":
                    self._send_json(self.obs.draft_stats())
                case "/api/areas":
                    self._send_json(self.obs.areas())
                case "/api/area_stats":
                    self._send_json(self.obs.area_stats())
                case "/api/copula_stats":
                    self._send_json(self.obs.copula_stats())
                case "/api/upgrade_stats":
                    self._send_json(self.obs.upgrade_stats())
                case "/api/play/state":
                    if self.play_session is None:
                        self._send_json_error(404, "no active play session")
                    else:
                        self._send_json(self.play_session.state())
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

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        """Route the Play-session write endpoints; everything else is GET-only.

        The request body is read by Content-Length and parsed as JSON; a
        missing/malformed body is a 400, never an uncaught exception.
        """
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
        except ValueError as e:
            self._send_json_error(400, f"malformed request body: {e}")
            return
        try:
            match path:
                case "/api/play/new":
                    self._play_new(body)
                case "/api/play/act":
                    self._play_act(body)
                case "/api/play/end-day":
                    self._play_end_day()
                case "/api/play/undo":
                    self._play_undo()
                case "/api/play/save":
                    self._play_save()
                case _:
                    self.send_error(404)
        except BrokenPipeError:
            pass

    def _read_json_body(self) -> dict:
        """Parse the POST body as a JSON object; ``{}`` when there is none.

        Raises ``ValueError`` on anything that is not valid JSON or is valid
        JSON but not an object, so callers can turn it into a 400 uniformly.
        """
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        data = json.loads(raw)  # raises json.JSONDecodeError (a ValueError) on bad input
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def _play_new(self, body: dict) -> None:
        """POST /api/play/new: start a fresh session, replacing any existing one."""
        seed = body.get("seed")
        if seed is not None:
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                self._send_json_error(400, "seed must be an integer")
                return
        try:
            n_days = int(body.get("n_days", 1))
        except (TypeError, ValueError):
            self._send_json_error(400, "n_days must be an integer")
            return
        if n_days < 1:
            self._send_json_error(400, "n_days must be >= 1")
            return
        reward = body.get("reward", "shaped")
        if reward not in ("shaped", "sparse", "phased"):
            self._send_json_error(400, "reward must be one of shaped/sparse/phased")
            return
        unlocks = body.get("unlocks", "all")
        if unlocks not in ("all", "fresh"):
            self._send_json_error(400, "unlocks must be one of all/fresh")
            return
        Handler.play_session = _play.PlaySession(seed, n_days, reward, unlocks)
        self._send_json(Handler.play_session.state())

    def _play_act(self, body: dict) -> None:
        """POST /api/play/act: apply one action, 400 if the mask rejects it."""
        if self.play_session is None:
            self._send_json_error(400, "no active play session; POST /api/play/new first")
            return
        try:
            action = int(body.get("action"))
        except (TypeError, ValueError):
            self._send_json_error(400, "action must be an integer")
            return
        try:
            state = self.play_session.act(action)
        except _play.IllegalActionError as e:
            self._send_json_error(400, str(e))
            return
        self._send_json(state)

    def _play_end_day(self) -> None:
        """POST /api/play/end-day: the player's "call it a day".

        Takes no body: there is no action id to send, since ending the day by
        hand is not an action (see ``web/play.py::PlaySession.call_it_a_day``).
        400 when a pending choice makes the day un-endable right now.
        """
        if self.play_session is None:
            self._send_json_error(400, "no active play session")
            return
        try:
            state = self.play_session.call_it_a_day()
        except _play.DayNotEndableError as e:
            self._send_json_error(400, str(e))
            return
        self._send_json(state)

    def _play_undo(self) -> None:
        """POST /api/play/undo: step the current day back one action."""
        if self.play_session is None:
            self._send_json_error(400, "no active play session")
            return
        self._send_json(self.play_session.undo())

    def _play_save(self) -> None:
        """POST /api/play/save: append completed days to the demos file."""
        if self.play_session is None:
            self._send_json_error(400, "no active play session")
            return
        n = self.play_session.save(Handler.demos_path)
        self._send_json({"written": n, "path": str(Handler.demos_path)})

    def _send_json(self, data) -> None:
        """Write ``data`` as a 200 JSON response, marked no-store so polls stay fresh."""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json_error(self, code: int, message: str) -> None:
        """Write a JSON ``{"error": message}`` body with the given status code.

        Used instead of ``BaseHTTPRequestHandler.send_error`` (which renders
        an HTML page) for the Play-session API, so client-side ``fetch`` calls
        can always parse the response body regardless of status.
        """
        body = json.dumps({"error": message}).encode()
        self.send_response(code)
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
    parser.add_argument("--reward", choices=["shaped", "sparse", "phased"], default="shaped",
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
    parser.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS,
                        help="maximum ordinary replay records kept in memory "
                             "(oldest ingested evicted first); best-of-window "
                             "records are always kept")
    parser.add_argument("--demos", default="demos.jsonl",
                        help="filename (relative to checkpoint dir) that the Play "
                             "tab's 'save session' button appends to")
    args = parser.parse_args(argv)

    obs = Observatory(Path(args.checkpoint_dir), args.reward, max_runs=args.max_runs)
    stop = threading.Event()
    threading.Thread(target=metrics_sampler, args=(obs, args.metrics_poll, stop),
                     daemon=True, name="metrics-sampler").start()
    if not args.no_eval:
        threading.Thread(target=eval_worker,
                         args=(obs, args.eval_episodes, args.eval_poll, stop),
                         daemon=True, name="eval-worker").start()

    Handler.obs = obs
    Handler.play_session = None
    Handler.demos_path = Path(args.checkpoint_dir) / args.demos
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
