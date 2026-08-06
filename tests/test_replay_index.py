"""Observatory's replay index: byte-offset seeking, the top/recent split,
the max_runs eviction cap, and its resilience to partial writes and file
truncation.
"""

from __future__ import annotations

import json
from pathlib import Path

from blueprince_sim.web.server import Observatory


def _record(episode: int, seed: int | None = None, why: str | None = None,
            win: bool = False, deepest_rank: int = 1, rooms_placed: int = 1,
            reason: str = "out_of_steps", saved_at: str | None = None) -> dict:
    """A minimal but shape-correct replay record.

    ``actions`` is deliberately empty: ``replay.build_frames`` only needs the
    post-reset frame to succeed when there is nothing to step through, so
    this stays cheap while still exercising the real Observatory ->
    build_frames path (no re-implemented ingestion or offset logic).
    """
    rec = {
        "episode": episode, "seed": seed if seed is not None else episode,
        "reward": "shaped", "actions": [], "modes": "",
        "win": win, "deepest_rank": deepest_rank, "rooms_placed": rooms_placed,
        "reason": reason,
    }
    if why is not None:
        rec["why"] = why
    if saved_at is not None:
        rec["saved_at"] = saved_at
    return rec


def _append_lines(path: Path, records: list[dict]) -> None:
    """Append one JSON line per record, each newline-terminated."""
    with path.open("a") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_run_frames_round_trips_through_offset_seek(tmp_path: Path):
    """The byte offset/length stored at ingest reads back the exact JSONL
    line: run_frames on a freshly ingested episode reports that episode's
    own episode number and seed, not some neighboring line's."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(1, seed=101), _record(2, seed=202),
                            _record(3, seed=303)])
    obs = Observatory(tmp_path, "shaped")
    data = obs.run_frames(2)
    assert data is not None
    assert data["episode"] == 2
    assert data["seed"] == 202


def test_ordinary_records_evicted_oldest_ingested_first(tmp_path: Path):
    """With max_runs=3, only the 3 most-recently-ingested ordinary records
    survive; older ones drop out of both runs_index and run_frames."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(ep, why="random") for ep in range(1, 11)])
    obs = Observatory(tmp_path, "shaped", max_runs=3)
    episodes = {m["episode"] for m in obs.runs_index("episode")}
    assert episodes == {8, 9, 10}
    assert obs.run_frames(1) is None  # evicted
    data = obs.run_frames(10)
    assert data is not None and data["episode"] == 10


def test_top_records_survive_eviction_of_far_more_than_max_runs(tmp_path: Path):
    """Best-of-window ('top') records are never evicted, even after many
    times max_runs worth of ordinary records have since been ingested."""
    replays = tmp_path / "replays.jsonl"
    records = [_record(0, why="top_window")]
    records += [_record(ep, why="random") for ep in range(1, 41)]
    records.append(_record(41, why="top_window"))
    _append_lines(replays, records)
    obs = Observatory(tmp_path, "shaped", max_runs=5)
    episodes = {m["episode"] for m in obs.runs_index("episode")}
    assert {0, 41}.issubset(episodes)
    assert obs.run_frames(0) is not None
    assert obs.run_frames(41) is not None


def test_top_stickiness_holds_in_both_write_orders(tmp_path: Path):
    """An episode rewritten random->top or top->random both end up flagged
    top:True and exempt from eviction, regardless of which line is newest."""
    replays = tmp_path / "replays.jsonl"
    records = [
        _record(1, why="random"),
        _record(1, why="top_window"),   # random then top: top wins
        _record(2, why="top_window"),
        _record(2, why="random"),       # top then random: stays top (sticky)
    ]
    records += [_record(ep, why="random") for ep in range(100, 120)]
    _append_lines(replays, records)
    obs = Observatory(tmp_path, "shaped", max_runs=3)
    by_episode = {m["episode"]: m for m in obs.runs_index("episode")}
    assert by_episode[1]["top"] is True
    assert by_episode[2]["top"] is True
    assert obs.run_frames(1) is not None
    assert obs.run_frames(2) is not None


def test_second_batch_offsets_resolve_after_incremental_append(tmp_path: Path):
    """Offsets computed for a second, later-appended batch of lines must
    still point at the right bytes - this is what an off-by-one in the
    running byte position would break."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(1, seed=11), _record(2, seed=22)])
    obs = Observatory(tmp_path, "shaped")
    first_index = obs.runs_index("episode")
    assert {m["episode"] for m in first_index} == {1, 2}

    _append_lines(replays, [_record(3, seed=33), _record(4, seed=44)])
    second_index = obs.runs_index("episode")
    assert {m["episode"] for m in second_index} == {1, 2, 3, 4}

    data = obs.run_frames(4)
    assert data is not None
    assert data["episode"] == 4
    assert data["seed"] == 44


def test_partial_trailing_line_is_ingested_only_once_completed(tmp_path: Path):
    """A line with no trailing newline yet is not ingested; once completed
    (rest of the bytes + newline appended) it becomes visible, and offsets
    for everything after it stay correct."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(1, seed=1)])

    full_line = json.dumps(_record(2, seed=222))
    # Write a partial line: no trailing newline.
    with replays.open("a") as f:
        f.write(full_line[: len(full_line) // 2])
    obs = Observatory(tmp_path, "shaped")
    episodes = {m["episode"] for m in obs.runs_index("episode")}
    assert episodes == {1}
    assert obs.run_frames(2) is None

    # Complete the line, then append one more record after it.
    with replays.open("a") as f:
        f.write(full_line[len(full_line) // 2:] + "\n")
    _append_lines(replays, [_record(3, seed=333)])

    episodes = {m["episode"] for m in obs.runs_index("episode")}
    assert episodes == {1, 2, 3}
    data2 = obs.run_frames(2)
    assert data2 is not None and data2["episode"] == 2 and data2["seed"] == 222
    data3 = obs.run_frames(3)
    assert data3 is not None and data3["episode"] == 3 and data3["seed"] == 333


def test_truncated_or_replaced_file_resets_the_index(tmp_path: Path):
    """When replays.jsonl shrinks (truncated or replaced by a new run
    reusing the checkpoint dir), stale offsets from the old file are
    dropped: the index is rebuilt from the new content only."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(ep, seed=ep) for ep in range(1, 6)])
    obs = Observatory(tmp_path, "shaped")
    assert {m["episode"] for m in obs.runs_index("episode")} == {1, 2, 3, 4, 5}
    assert obs.run_frames(3) is not None

    # Replace with a shorter file containing entirely different episodes.
    replays.write_text("")
    _append_lines(replays, [_record(900, seed=900), _record(901, seed=901)])

    episodes = {m["episode"] for m in obs.runs_index("episode")}
    assert episodes == {900, 901}
    assert obs.run_frames(3) is None  # old episode: gone, not a wrong record
    data = obs.run_frames(901)
    assert data is not None and data["episode"] == 901 and data["seed"] == 901


def test_runs_index_key_set_is_unchanged(tmp_path: Path):
    """runs_index entries still carry exactly the API-contracted key set,
    regardless of how the underlying storage represents a record."""
    replays = tmp_path / "replays.jsonl"
    _append_lines(replays, [_record(1, saved_at="2026-01-01T00:00:00")])
    obs = Observatory(tmp_path, "shaped")
    [meta] = obs.runs_index("episode")
    assert set(meta.keys()) == {
        "episode", "win", "deepest_rank", "rooms_placed", "reason", "top",
        "moves", "saved_at",
    }
