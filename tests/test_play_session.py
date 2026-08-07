"""Tests for the human-play recording session (`web/play.py`).

Drives `PlaySession` directly through `act()`/`undo()`/`save()` -- the same
`BluePrinceEnv.action_masks()`/`step()` entry points MaskablePPO uses -- so
these pin the property the whole feature exists for: a session recorded by a
human is a legitimate, replayable training demonstration.
"""

from __future__ import annotations

import json
import random

import pytest

from blueprince_sim.env import actions as A
from blueprince_sim.web import replay
from blueprince_sim.web.play import IllegalActionError, PlaySession, action_group


def _finish_day(session: PlaySession, rng: random.Random, max_steps: int = 600) -> None:
    """Drive `session` with random legal actions through exactly one more day.

    Stops the instant a day closes (a new `day_records` entry appears) or the
    attempt ends -- checking `day_over` alone would not stop in time, since a
    mid-attempt day boundary auto-advances to tomorrow inside `act()` before
    returning, leaving `day_over` False again for the new day. A day always
    ends within a bounded number of decisions (starting steps are finite and
    every dead end is detected), so hitting `max_steps` indicates a real bug.
    """
    days_before = len(session.day_records)
    for _ in range(max_steps):
        if len(session.day_records) > days_before or session.attempt_over:
            return
        s = session.state()
        action_id = rng.choice([a["id"] for a in s["legal_actions"]])
        session.act(action_id)
    raise AssertionError("day did not end within max_steps random actions")


def test_full_day_produces_one_record():
    """Playing a single-day session to completion through act() closes out
    exactly one EpisodeRecorder-shaped day record."""
    session = PlaySession(seed=1234, n_days=1, reward="shaped", unlocks="all")
    _finish_day(session, random.Random(0))
    assert len(session.day_records) == 1
    assert session.attempt_over


def test_recorded_demo_replays_identically():
    """A saved single-day record round-trips through replay.build_frames with
    no divergence -- the property that makes a demo trustworthy as training
    data, since a diverging replay means the recorded actions do not actually
    reproduce the session."""
    session = PlaySession(seed=99, n_days=1, reward="shaped", unlocks="all")
    _finish_day(session, random.Random(1))
    record = session.day_records[0]
    frames, divergence = replay.build_frames(record)
    assert divergence is None
    assert len(frames) == len(record["actions"]) + 1


def test_act_rejects_illegal_action():
    """act() raises for an id the live mask does not currently offer, and
    leaves the action buffer untouched -- the server-side re-validation the
    spec requires so a stale client can never record an action the engine
    would not have allowed."""
    session = PlaySession(seed=5, n_days=1, reward="shaped", unlocks="all")
    mask = session.env.action_masks()
    illegal_id = next(i for i, ok in enumerate(mask) if not ok)
    with pytest.raises(IllegalActionError):
        session.act(illegal_id)
    assert session.actions == []


def test_undo_restores_prior_state():
    """undo() puts the session back to exactly the state before the last
    action: same grid position, same resource totals, same action count."""
    session = PlaySession(seed=7, n_days=1, reward="shaped", unlocks="all")
    first_action = session.state()["legal_actions"][0]["id"]
    session.act(first_action)
    snapshot = session.state()
    pos_after_first = snapshot["frame"]["pos"]
    resources_after_first = dict(snapshot["frame"]["resources"])
    n_after_first = snapshot["n_actions_today"]

    second_action = session.state()["legal_actions"][0]["id"]
    session.act(second_action)
    assert session.state()["n_actions_today"] == n_after_first + 1

    result = session.undo()
    assert result["undone"] is True
    assert result["frame"]["pos"] == pos_after_first
    assert result["frame"]["resources"] == resources_after_first
    assert result["n_actions_today"] == n_after_first


def test_multiday_record_carries_day_config_and_replays():
    """Finishing day 1 of a multi-day attempt advances the chain, stamps
    day_config on the closed record, and that record still replays with
    divergence None. Dropping day_config would diverge instead (see
    replay.py's per-day starting-condition caveat), which is the whole point
    of carrying it."""
    session = PlaySession(seed=42, n_days=2, reward="shaped", unlocks="all")
    _finish_day(session, random.Random(2))
    assert len(session.day_records) == 1
    assert not session.attempt_over  # day 2 of 2 has not been played yet

    record = session.day_records[0]
    assert "day_config" in record
    frames, divergence = replay.build_frames(record)
    assert divergence is None


def test_save_appends_valid_jsonl_matching_runs_tab(tmp_path):
    """save() appends one JSON line per completed day whose keys match what
    the Runs tab's replay loader reads, is idempotent across repeated calls,
    and the reloaded record's episode id matches the in-memory one."""
    session = PlaySession(seed=3, n_days=2, reward="shaped", unlocks="all")
    _finish_day(session, random.Random(3))
    demos_path = tmp_path / "demos.jsonl"

    written = session.save(demos_path)
    assert written == 1
    lines = demos_path.read_text().splitlines()
    assert len(lines) == 1

    loaded = json.loads(lines[0])
    expected_keys = {"episode", "seed", "reward", "actions", "modes", "win",
                      "deepest_rank", "rooms_placed", "reason", "saved_at",
                      "n_actions", "why", "day_config"}
    assert expected_keys <= loaded.keys()
    assert loaded["episode"] == session.day_records[0]["episode"]

    # Nothing new completed since the last save: a second call writes zero
    # records and the file gains no lines.
    assert session.save(demos_path) == 0
    assert len(demos_path.read_text().splitlines()) == 1


def test_action_group_covers_full_action_space():
    """Every action id in 0..N_ACTIONS-1 is classified into a named group,
    never the 'other' fallback -- a newly added *_BASE range in actions.py
    that this file forgot to teach action_group about would show up here."""
    groups = {action_group(i) for i in range(A.N_ACTIONS)}
    assert "other" not in groups
