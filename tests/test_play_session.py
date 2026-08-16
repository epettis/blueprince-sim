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

from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import CALLED_IT_A_DAY, Phase
from blueprince_sim.env import actions as A
from blueprince_sim.rl import behavioral_cloning as bc
from blueprince_sim.web import replay
from blueprince_sim.web.play import (
    DayNotEndableError,
    IllegalActionError,
    PlaySession,
    _payout_diff,
    action_group,
)


def _enter_shop(game, room_id: str, cell: int = 7):
    """Place ``room_id`` at ``cell``, stand in it, and roll its stock.

    Mirrors test_shops.py's helper of the same purpose: mimics the room-state
    prerequisites Game._enter sets up, without driving a full move through
    the engine.
    """
    room = game.registry.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    shops.on_enter_shop(game, room)
    return room


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
    room False. The Play tab shades unvisited rooms off this field, which
    drafting alone cannot supply: drafting and entering are distinct in this
    engine, so a placed room is not an entered one."""
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
    which Room itself does not carry. The bare ids are unreadable for every
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
    """_payout_diff is the action log's single payout reporting point: it reports
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
    log's payout."""
    session = PlaySession(seed=11, n_days=1, reward="shaped", unlocks="all")
    before = dict(session.state()["frame"]["resources"])
    action_id = session.state()["legal_actions"][0]["id"]
    st = session.act(action_id)
    after = dict(st["frame"]["resources"])
    expected = {k: after[k] - before[k] for k in before if after[k] != before[k]}

    payout = st["frame"]["action"]["payout"]
    resource_deltas = {p["id"]: p["delta"] for p in payout if p["id"] in before}
    assert resource_deltas == expected


def test_shop_stock_is_none_outside_a_shop():
    """frame['shop_stock'] is None whenever the player is not standing in a
    shop -- e.g. at a fresh day's start -- so the client only ever renders
    unaffordable-stock rows where a shop is actually open (task 47)."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    assert session.state()["frame"]["shop_stock"] is None


def test_shop_stock_view_includes_unaffordable_rows_with_no_action_id():
    """Every rolled stock entry appears in frame['shop_stock'], including ones
    the player cannot afford -- the display change task 47 asks for, since
    the action mask alone (legal_actions) only ever shows buyable rows and a
    shop menu filtered to those hides the reason to come back. An entry gets
    a real action_id exactly when the BUY_BASE mask would legalize it (not
    sold out, affordable, not blocked), and None otherwise, so the client can
    tell a real buy button from a row it must grey out."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    game = session.env.game
    _enter_shop(game, "commissary")
    game.state.coins = 0  # affords nothing

    stock = session.state()["frame"]["shop_stock"]
    assert stock  # the Commissary always rolls at least one entry
    assert all(not entry["affordable"] for entry in stock)
    assert all(entry["action_id"] is None for entry in stock)
    # The mask agrees: no BUY_BASE action is legal with zero coins.
    legal_ids = {a["id"] for a in session.state()["legal_actions"]}
    assert not legal_ids & set(range(A.BUY_BASE, A.TRADE_BASE))


def test_shop_stock_view_action_id_matches_the_legal_buy_action():
    """Once affordable, a shop_stock entry's action_id is exactly the
    BUY_BASE-offset id the mask legalized for that slot -- so clicking the
    row the client renders as a button performs the same purchase the
    RL-facing mask would offer at that index, never a different one."""
    session = PlaySession(seed=1, n_days=1, reward="shaped", unlocks="all")
    game = session.env.game
    _enter_shop(game, "commissary")
    game.state.coins = 10_000  # affords everything rolled

    stock = session.state()["frame"]["shop_stock"]
    legal_ids = {a["id"] for a in session.state()["legal_actions"]}
    for entry in stock:
        assert entry["action_id"] == A.BUY_BASE + entry["index"]
        assert entry["action_id"] in legal_ids


# ---------------------------------------------------- task 44: call it a day

def _draft_one_room(session: PlaySession) -> None:
    """Draft and place one room, leaving the session back in NAVIGATE.

    A day mid-draft cannot be ended (that is its own test below), so a
    scenario that wants a started-but-unfinished day has to close the hand it
    opens rather than stop at the draft action.
    """
    draft = next(a for a in session.state()["legal_actions"] if a["group"] == "draft")
    session.act(draft["id"])
    choose = next(a for a in session.state()["legal_actions"] if a["group"] == "choose")
    session.act(choose["id"])
    assert session.env.game.phase is Phase.NAVIGATE


def test_calling_it_a_day_ends_a_day_the_mask_still_has_work_in():
    """The mutation proof at the session level: a session one room into a
    fresh day still has legal actions and is not over, and call_it_a_day()
    ends it anyway -- through PlaySession, which otherwise only ever mutates
    via env.step()."""
    session = PlaySession(seed=1234, n_days=1, reward="shaped", unlocks="all")
    _draft_one_room(session)
    before = session.state()
    assert before["legal_actions"], "setup: the mask must still offer work"
    assert not before["day_over"]

    after = session.call_it_a_day()

    assert after["day_over"]
    assert after["attempt_over"]
    assert session.day_records[0]["reason"] == CALLED_IT_A_DAY


def test_a_hand_ended_day_is_still_a_usable_demonstration():
    """The recorded actions were every one of them chosen off a live mask, so
    the day trains like any other; it just stops before the engine would have.
    replay_demo only refuses a replay that ends EARLY, so a record ending late
    must yield one (obs, action, mask) triple per recorded action."""
    session = PlaySession(seed=4321, n_days=1, reward="shaped", unlocks="all")
    rng = random.Random(11)
    for _ in range(5):
        session.act(rng.choice([a["id"] for a in session.state()["legal_actions"]]))
    session.call_it_a_day()

    record = session.day_records[0]
    assert len(record["actions"]) == 5
    assert len(bc.replay_demo(record)) == 5


def test_a_hand_ended_day_still_advances_the_chain():
    """Ending the day outside env.step() means the day-chain advance env.step
    would have run has to be done by hand. If it were skipped, tomorrow would
    replay today's day index and lose today's carry-over."""
    session = PlaySession(seed=77, n_days=3, reward="shaped", unlocks="all")
    assert session.state()["day"] == 1

    after = session.call_it_a_day()

    assert not after["attempt_over"], "day 1 of 3 is not the attempt's last"
    assert after["day"] == 2
    assert session.chain.current_day == 2


def test_the_last_day_called_by_hand_ends_the_attempt():
    """The attempt-final verdict has to be read BEFORE advance() wraps
    current_day back to 1, exactly as env.step reads it. Reading it after
    would report the final day as mid-attempt and reopen a finished attempt."""
    session = PlaySession(seed=78, n_days=1, reward="shaped", unlocks="all")

    after = session.call_it_a_day()

    assert after["attempt_over"]
    assert session.attempt_over


def test_undo_after_a_hand_ended_day_rebuilds_the_same_chain():
    """undo() rebuilds the whole session by replaying records, and a hand-ended
    day's actions do NOT end it on replay -- so the rebuild must re-run the
    hand end itself. Without that the rebuilt chain sits a day behind and every
    later day is generated under the wrong config."""
    session = PlaySession(seed=90, n_days=3, reward="shaped", unlocks="all")
    session.call_it_a_day()
    session.act(session.state()["legal_actions"][0]["id"])
    day_before = session.state()["day"]

    result = session.undo()

    assert result["undone"] is True
    assert result["day"] == day_before == 2
    assert session.chain.current_day == 2
    assert len(session.day_records) == 1


def test_calling_it_a_day_is_refused_mid_draft():
    """A dealt draft hand is a decision already in flight ("you must choose one
    -- no backing out"), so the request is refused rather than left to strand
    the pending record. Refusing is also what keeps the button's disabled state
    honest instead of decorative."""
    session = PlaySession(seed=1234, n_days=1, reward="shaped", unlocks="all")
    draft = next(a for a in session.state()["legal_actions"] if a["group"] == "draft")
    session.act(draft["id"])
    assert session.env.game.phase is Phase.DRAFTING, "setup: a hand must be dealt"

    assert session.state()["can_end_day"] is False
    with pytest.raises(DayNotEndableError):
        session.call_it_a_day()

    assert session.env.game.phase is Phase.DRAFTING


def test_calling_it_a_day_is_refused_once_the_attempt_is_over():
    """A finished attempt has no live Game to end. Without this guard the call
    would append a second record for a day that was already closed."""
    session = PlaySession(seed=1234, n_days=1, reward="shaped", unlocks="all")
    session.call_it_a_day()
    assert session.attempt_over

    with pytest.raises(DayNotEndableError):
        session.call_it_a_day()

    assert len(session.day_records) == 1


def test_can_end_day_tracks_what_the_call_would_actually_do():
    """The flag drives whether the Play tab's button is clickable, so it has to
    agree with the method rather than approximate it: true exactly when
    call_it_a_day() would be accepted."""
    session = PlaySession(seed=555, n_days=1, reward="shaped", unlocks="all")
    assert session.state()["can_end_day"] is True

    session.call_it_a_day()

    assert session.state()["can_end_day"] is False
