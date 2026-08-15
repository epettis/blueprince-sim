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

from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Phase
from blueprince_sim.env import actions as A
from blueprince_sim.web import replay
from blueprince_sim.web.play import (
    IllegalActionError,
    PlaySession,
    _payout_diff,
    action_group,
)


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


def test_state_reports_entered_per_cell():
    """frame['entered'] mirrors GameState.entered exactly: 45 entries, the
    player's own starting cell already True, a freshly placed-but-unstepped
    room False. Task 34 (distinguish visited from unvisited rooms) needs this
    surfaced -- drafting and entering are distinct in this engine, and the UI
    had no way to see 'entered' at all before this field existed."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    game = session.env.game
    parlor = game.registry.by_id["parlor"]
    game._place_room(parlor, 7, parlor.door_mask)  # placed, never stepped into

    frame = session.state()["frame"]
    assert len(frame["entered"]) == 45
    assert frame["entered"][game.state.pos] is True
    assert frame["entered"][7] is False


def test_pending_upgrade_is_none_outside_upgrade_pending():
    """pending_upgrade is None whenever the game is not in UPGRADE_PENDING,
    so the client's disk-choice panel only ever renders when there is a real
    choice open."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    assert session.state()["frame"]["pending_upgrade"] is None


def test_pending_upgrade_uses_effect_text_not_raw_variant_id():
    """pending_upgrade's options carry a readable name plus the sheet's
    effect_text -- the owner's own example (parlor__ix108 vs parlor__ix109,
    both named plain 'Parlor') is only distinguishable through effect_text,
    which Room itself does not carry. Task 30 says this affects every
    __ixNN variant, not just the Parlor pair -- this pins the general
    lookup, not a Parlor special case."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    game = session.env.game
    game.state.pending_upgrade_slot = "parlor"
    game.state.pending_upgrade_options = ("parlor__ix108", "parlor__ix109")
    game.phase = Phase.UPGRADE_PENDING

    pu = session.state()["frame"]["pending_upgrade"]
    assert pu["slot_name"] == "Parlor"
    by_id = {o["id"]: o for o in pu["options"]}
    assert by_id["parlor__ix108"]["name"] == "Parlor"
    assert by_id["parlor__ix109"]["name"] == "Parlor"
    # The names alone are identical -- effect_text is what must differ.
    assert by_id["parlor__ix108"]["effect_text"] != by_id["parlor__ix109"]["effect_text"]
    assert by_id["parlor__ix108"]["effect_text"]
    assert by_id["parlor__ix109"]["effect_text"]


def test_pending_upgrade_reached_through_real_insert_disk():
    """The same pending_upgrade shape comes out of a real insert_disk() call
    (not just a hand-set state), so the dict construction agrees with how the
    engine actually reaches UPGRADE_PENDING."""
    session = PlaySession(seed=0, n_days=1, reward="shaped", unlocks="all")
    game = session.env.game
    security = game.registry.by_id["security"]
    game._place_room(security, 7, 14)
    game.state.pos = 7
    game.state.entered[7] = True
    si.grant(game.state, game.registry, "upgrade_disk_vault_304", source="test")
    assert game.insert_disk()
    assert game.phase is Phase.UPGRADE_PENDING

    pu = session.state()["frame"]["pending_upgrade"]
    assert pu is not None
    assert len(pu["options"]) == 3
    ids = {o["id"] for o in pu["options"]}
    assert len(ids) == 3  # three distinct variants offered


def test_payout_diff_reports_signed_deltas_and_omits_unchanged():
    """_payout_diff is the single reporting point behind task 28: it reports
    every changed resource/item as a signed delta (gains AND costs, since a
    walk's step cost nets against a room's step grant) and omits anything
    that did not change -- regardless of which engine path (items, a grant
    effect, a room_hook, a container open) produced the change."""
    session = PlaySession(seed=2, n_days=1, reward="shaped", unlocks="all")
    registry = session.env.game.registry
    before = {"steps": 50, "gems": 0, "keys": 1, "coins": 0, "dice": 0, "luck": 0}
    after = {"steps": 45, "gems": 2, "keys": 1, "coins": 0, "dice": 0, "luck": 0,
             "upgrade_disk_vault_304": 1}
    diff = _payout_diff(before, after, registry)
    by_id = {d["id"]: d["delta"] for d in diff}
    assert by_id == {"steps": -5, "gems": 2, "upgrade_disk_vault_304": 1}
    assert "keys" not in by_id  # unchanged resource omitted


def test_act_attaches_payout_matching_independent_resource_diff():
    """act()'s recorded last_action['payout'] matches an independently
    computed before/after resource diff -- pins that a single diffing point
    inside act() (not per-room-type additions) is what populates the action
    log's payout, per task 28."""
    session = PlaySession(seed=11, n_days=1, reward="shaped", unlocks="all")
    before = dict(session.state()["frame"]["resources"])
    action_id = session.state()["legal_actions"][0]["id"]
    st = session.act(action_id)
    after = dict(st["frame"]["resources"])
    expected = {k: after[k] - before[k] for k in before if after[k] != before[k]}

    payout = st["frame"]["action"]["payout"]
    resource_deltas = {p["id"]: p["delta"] for p in payout if p["id"] in before}
    assert resource_deltas == expected
