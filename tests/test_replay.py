"""Replay reconstruction, action descriptions, and recorder retention logic."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.rl.train import EpisodeRecorder, all_unlocks_config
from blueprince_sim.web import replay
from blueprince_sim.web.server import Observatory


def _play_random_episode(seed: int) -> tuple[dict, dict]:
    """Play one masked-random episode; return (record, final_info)."""
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    _, info = env.reset(seed=seed)
    rng = random.Random(seed)
    actions = []
    done = False
    while not done:
        legal = [i for i, ok in enumerate(env.action_masks()) if ok]
        action = rng.choice(legal)
        actions.append(action)
        _, _, term, trunc, info = env.step(action)
        done = term or trunc
    record = {
        "episode": 1, "seed": seed, "reward": "shaped", "actions": actions,
        "modes": "10" * (len(actions) // 2 + 1),
        "win": info["termination_reason"] == "antechamber",
        "deepest_rank": info["deepest_rank"], "rooms_placed": info["rooms_placed"],
        "reason": info["termination_reason"],
    }
    return record, info


def test_episode_seed_in_info():
    env = BluePrinceEnv()
    _, info = env.reset(seed=1234)
    assert info["episode_seed"] == 1234
    _, info = env.reset()
    assert isinstance(info["episode_seed"], int)


def test_replay_roundtrip_matches_live_episode():
    record, info = _play_random_episode(seed=99)
    frames = replay.build_frames(record)
    assert len(frames) == len(record["actions"]) + 1
    last = frames[-1]
    assert last["reason"] == info["termination_reason"]
    assert last["deepest_rank"] == info["deepest_rank"]
    # Frame 0 is the freshly-reset state: entrance hall only, full steps.
    assert frames[0]["pos"] == 2
    assert frames[0]["grid"][2] >= 0
    # Explore flags follow the recorded modes string ('0' = explore).
    for frame in frames[1:]:
        act = frame["action"]
        assert act["explore"] == (record["modes"][act["index"]] == "0")


def test_replay_is_deterministic():
    record, _ = _play_random_episode(seed=7)
    a = replay.build_frames(record)
    b = replay.build_frames(record)
    assert a == b


def test_describe_action_navigate_and_draft():
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    open_actions = [i for i, ok in enumerate(env.action_masks()) if ok and i < A.CHOOSE_BASE]
    assert open_actions
    desc = A.describe_action(game, open_actions[0])
    assert desc.startswith("open door ") and "@ r" in desc
    env.step(open_actions[0])  # now drafting
    desc = A.describe_action(game, A.CHOOSE_BASE)
    assert desc.startswith("choose #1 ")
    assert A.describe_action(game, A.REDRAW_ACTION) == "redraw"
    assert A.describe_action(game, A.ROTATE_ACTION) == "rotate options"


def test_recorder_sampling_and_top_window(tmp_path: Path):
    path = tmp_path / "replays.jsonl"
    rec = EpisodeRecorder(path, n_envs=1, reward="shaped", sample_rate=0.0,
                          top_every=10, episodes_done=0)

    def finish(episode: int, rank: int, win: bool = False):
        rec.on_step([episode % 7], [True])
        rec.on_episode_end(0, episode, {
            "episode_seed": episode, "deepest_rank": rank, "rooms_placed": rank,
            "termination_reason": "antechamber" if win else "out_of_steps"})

    for ep in range(1, 10):
        finish(ep, rank=ep % 5 + 1, win=(ep == 4))
    finish(10, rank=9)  # window 0 closes when episode 10 (window 1) arrives
    finish(11, rank=2)
    rec.flush_top()

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["why"] for r in rows] == ["top_window", "top_window"]
    assert rows[0]["episode"] == 4  # the win beats any deeper losing run
    assert rows[0]["win"] is True
    assert rows[1]["episode"] == 10  # best of the partial second window

    # sample_rate=1 records every episode
    path2 = tmp_path / "all.jsonl"
    rec2 = EpisodeRecorder(path2, n_envs=1, reward="shaped", sample_rate=1.0,
                           top_every=0, episodes_done=0)
    rec2.on_step([3], [False])
    rec2.on_episode_end(0, 1, {"episode_seed": 5, "deepest_rank": 1,
                               "termination_reason": "out_of_steps"})
    row = json.loads(path2.read_text())
    assert row["why"] == "random" and row["actions"] == [3] and row["modes"] == "0"


def test_observatory_runs_index_and_frames(tmp_path: Path):
    record, _ = _play_random_episode(seed=17)
    losing = dict(record, episode=5, win=False, deepest_rank=1, why="random")
    winning = dict(record, episode=3, why="top_window")
    replays = tmp_path / "replays.jsonl"
    replays.write_text(json.dumps(losing) + "\n" + json.dumps(winning) + "\n")

    obs = Observatory(tmp_path, "shaped")
    by_episode = obs.runs_index("episode")
    assert [m["episode"] for m in by_episode] == [5, 3]
    by_progress = obs.runs_index("progress")
    keys = [(m["win"], m["deepest_rank"], m["episode"]) for m in by_progress]
    assert keys == sorted(keys, reverse=True)
    assert next(m for m in by_progress if m["episode"] == 3)["top"] is True

    data = obs.run_frames(3)
    assert data is not None and len(data["frames"]) == len(record["actions"]) + 1
    assert obs.run_frames(999) is None


def test_metrics_merge_and_downsample(tmp_path: Path):
    metrics = tmp_path / "metrics.jsonl"
    with metrics.open("w") as f:
        for i in range(5):
            f.write(json.dumps({"episodes": i * 100, "timesteps": i * 1000,
                                "win_rate_recent": i / 100, "sampled_at": 1000.0 + i}) + "\n")
        # duplicate checkpoint sample must be dropped
        f.write(json.dumps({"episodes": 400, "timesteps": 4000,
                            "win_rate_recent": 0.04, "sampled_at": 1010.0}) + "\n")
    (tmp_path / "eval.jsonl").write_text(json.dumps(
        {"episodes": 400, "p_antechamber": 0.02, "ci95": [0.01, 0.03],
         "eval_episodes": 10, "sampled_at": 1004.5}) + "\n")
    obs = Observatory(tmp_path, "shaped")
    m = obs.metrics()
    assert len(m["train"]) == 5
    assert m["train"][-1]["episodes"] == 400
    assert m["eval"][0]["p_antechamber"] == pytest.approx(0.02)
