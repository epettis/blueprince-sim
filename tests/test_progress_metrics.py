"""Persisting sb3 logger metrics through latest.json -> metrics.jsonl -> /api/metrics.

Covers the three links in the Observatory Progress tab's data path:

1. ``rl.train._logger_snapshot`` -- reads dashboard.SPECS keys out of the sb3
   Logger, including only what has actually been ``record()``-ed.
2. ``web.server.metrics_sampler`` -- carries whatever is in latest.json into
   metrics.jsonl verbatim (a characterization test: the whole persistence
   design leans on this already being true with no server change).
3. ``web.server.Observatory.metrics()`` -- surfaces the SPECS keys to the API,
   and reports them as ``None`` (not a fabricated 0.0) when a row predates
   this feature.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from stable_baselines3.common.logger import Logger

from blueprince_sim.rl.train import _logger_snapshot
from blueprince_sim.web.server import Observatory, metrics_sampler


def _sb3_logger(values: dict) -> Logger:
    """A real (but writer-less) sb3 Logger with ``values`` recorded into it."""
    logger = Logger(folder=None, output_formats=[])
    for key, value in values.items():
        logger.record(key, value)
    return logger


# ---------------------------------------------------------------------------
# _logger_snapshot
# ---------------------------------------------------------------------------


def test_logger_snapshot_includes_present_specs_keys():
    """A SPECS key that has been record()-ed is coerced to a plain float.

    Includes a numpy scalar (as sb3 itself records, e.g. np.mean() results)
    to pin the coercion that keeps json.dumps from raising on it.
    """
    logger = _sb3_logger({"train/approx_kl": np.float32(0.015), "time/fps": 1234})
    snap = _logger_snapshot(logger)
    assert snap["train/approx_kl"] == pytest.approx(0.015, rel=1e-5)
    assert snap["time/fps"] == 1234.0


def test_logger_snapshot_ignores_keys_outside_specs():
    """A logger key that isn't one of dashboard.SPECS' 20 is not carried through.

    sb3/callbacks can record arbitrary keys (eval/*, custom instrumentation);
    only the CLI-dashboard-parity set belongs in the persisted snapshot.
    """
    logger = _sb3_logger({"eval/mean_reward": 3.2, "train/loss": 0.1})
    snap = _logger_snapshot(logger)
    assert "eval/mean_reward" not in snap
    assert snap["train/loss"] == 0.1


def test_logger_snapshot_omits_absent_keys_never_zero():
    """Before the first record() call, dashboard.SPECS keys are omitted entirely.

    This is the property the whole design leans on: absent must stay absent,
    not become a 0.0 that a chart would mistake for a real measured zero.
    """
    logger = _sb3_logger({})
    snap = _logger_snapshot(logger)
    assert snap == {}
    assert "train/approx_kl" not in snap


def test_logger_snapshot_reflects_dump_clearing_the_logger():
    """After Logger.dump() clears name_to_value, a snapshot taken before the
    next record() call reports nothing for that key.

    Pins the sb3 semantics the whole design relies on: at trainer-checkpoint
    time, the snapshot is exactly "whatever the CLI dashboard would currently
    be showing," including the CLI's own "absent until re-recorded" gaps.
    """
    logger = _sb3_logger({"train/loss": 0.5})
    assert _logger_snapshot(logger)["train/loss"] == 0.5
    logger.dump()
    assert _logger_snapshot(logger) == {}


def test_logger_snapshot_drops_non_finite_values():
    """NaN/inf logger values are dropped rather than serialized.

    json.dumps would otherwise emit non-standard NaN/Infinity tokens that
    the browser's strict JSON.parse cannot read.
    """
    logger = _sb3_logger({"train/loss": float("nan"), "train/value_loss": float("inf")})
    assert _logger_snapshot(logger) == {}


# ---------------------------------------------------------------------------
# metrics_sampler: whole-dict-verbatim characterization
# ---------------------------------------------------------------------------


def test_metrics_sampler_carries_arbitrary_extra_keys_verbatim(tmp_path: Path):
    """metrics_sampler appends whatever latest.json contains, unmodified, plus sampled_at.

    This is the property the persistence design leans on: as long as
    rl/train.py adds new keys to the checkpoint metadata dict, the sampler
    needs no changes to carry them into metrics.jsonl.
    """
    obs = Observatory(tmp_path, "shaped")
    obs.latest_json.write_text(json.dumps({
        "episodes": 10, "timesteps": 100,
        "train/approx_kl": 0.01, "time/fps": 900.5,
    }))
    stop = threading.Event()
    t = threading.Thread(target=metrics_sampler, args=(obs, 0.01, stop))
    t.start()
    time.sleep(0.1)
    stop.set()
    t.join(timeout=2)

    rows = [json.loads(line) for line in obs.metrics_path.read_text().splitlines()]
    assert len(rows) == 1, "the (episodes, timesteps) key never changed, so only one row is written"
    assert rows[0]["train/approx_kl"] == 0.01
    assert rows[0]["time/fps"] == 900.5
    assert "sampled_at" in rows[0]


# ---------------------------------------------------------------------------
# Observatory.metrics(): API surfacing
# ---------------------------------------------------------------------------


def test_observatory_metrics_surfaces_logger_keys(tmp_path: Path):
    """/api/metrics rows carry dashboard.SPECS keys present in metrics.jsonl.

    Observatory.metrics() must not hand-pick a fixed subset of fields when
    building each row: every SPECS key that metrics_sampler already wrote
    verbatim must survive that step too.
    """
    row = {"episodes": 5, "timesteps": 50, "sampled_at": 1000.0,
           "win_rate_recent": 0.1, "train/approx_kl": 0.02, "time/fps": 1200}
    (tmp_path / "metrics.jsonl").write_text(json.dumps(row) + "\n")
    obs = Observatory(tmp_path, "shaped")
    out = obs.metrics()["train"]
    assert len(out) == 1
    assert out[0]["train/approx_kl"] == 0.02
    assert out[0]["time/fps"] == 1200
    # pre-existing fields are unaffected (additive-only change)
    assert out[0]["win_rate_recent"] == 0.1


def test_observatory_metrics_missing_keys_are_none_not_zero(tmp_path: Path):
    """A metrics.jsonl row predating this feature reports None, not 0.0, for the new keys.

    Simulates an old run's file: 0.0 would be indistinguishable from "a real
    zero was recorded," which is exactly the lie the design set out to avoid.
    """
    row = {"episodes": 5, "timesteps": 50, "sampled_at": 1000.0, "win_rate_recent": 0.1}
    (tmp_path / "metrics.jsonl").write_text(json.dumps(row) + "\n")
    obs = Observatory(tmp_path, "shaped")
    out = obs.metrics()["train"][0]
    assert out["train/approx_kl"] is None
    assert out["time/fps"] is None
