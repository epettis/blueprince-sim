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
    """reset() reports the episode seed in info - both explicit seeds and
    auto-generated ones - so recorded episodes can be replayed."""
    env = BluePrinceEnv()
    _, info = env.reset(seed=1234)
    assert info["episode_seed"] == 1234
    _, info = env.reset()
    assert isinstance(info["episode_seed"], int)


def test_replay_roundtrip_matches_live_episode():
    """Rebuilding frames from a recorded episode reproduces the live run: one
    frame per action plus the reset state, with matching outcome and explore
    flags decoded from the modes string."""
    record, info = _play_random_episode(seed=99)
    frames, divergence = replay.build_frames(record)
    assert divergence is None  # single-day record must replay cleanly
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
    """build_frames is a pure function of the record: rebuilding twice gives
    identical frames and divergence info."""
    record, _ = _play_random_episode(seed=7)
    a_frames, a_div = replay.build_frames(record)
    b_frames, b_div = replay.build_frames(record)
    assert a_frames == b_frames
    assert a_div == b_div


def test_describe_action_navigate_and_draft():
    """describe_action renders human-readable labels for draft, choose,
    redraw, and rotate actions in their respective phases."""
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    open_actions = [i for i, ok in enumerate(env.action_masks()) if ok and i < A.CHOOSE_BASE]
    assert open_actions
    desc = A.describe_action(game, open_actions[0])
    assert desc.startswith("draft ") and "door from " in desc and "(r" in desc
    env.step(open_actions[0])  # now drafting
    desc = A.describe_action(game, A.CHOOSE_BASE)
    assert desc.startswith("choose #1 ")
    assert A.describe_action(game, A.REDRAW_ACTION) == "redraw"
    assert A.describe_action(game, A.ROTATE_ACTION) == "rotate options"


def test_describe_action_draft_names_source_room():
    """A draft action's label names the room it is opened from (plus the grid
    coordinate), not a bare coordinate -- players draft standing inside a
    room, and translating r1c2 back into "which room am I in" was the
    reported confusion this label exists to resolve."""
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    open_actions = [i for i, ok in enumerate(env.action_masks()) if ok and i < A.CHOOSE_BASE]
    cell, _dir_idx = divmod(open_actions[0], 4)
    room = game.registry.rooms[game.state.grid[cell]]
    desc = A.describe_action(game, open_actions[0])
    # The room's name is present, and the coordinate is still there too --
    # room names can repeat across a house (allow_duplicates rooms), so the
    # coordinate remains the only unique reference to this exact cell.
    assert room.name in desc
    assert A._cell_name(cell) in desc


def test_describe_action_draft_empty_source_cell_degrades_gracefully():
    """A doorway action built for a source cell holding no room falls back to
    the bare coordinate instead of crashing or fabricating a room name --
    defensive, mirroring the guard describe_action's move_to branch already
    has for an empty grid[cell]."""
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    empty_cell = next(c for c in range(45) if game.state.grid[c] < 0)
    action_id = empty_cell * 4  # direction N; legality doesn't matter here
    desc = A.describe_action(game, action_id)
    assert desc == f"draft N door from {A._cell_name(empty_cell)}"


def test_pending_dict_outer_draft_has_no_source_room():
    """The outer-room draft is opened from the West Path doorstep, off-grid --
    its pending dict reports from_room=None rather than fabricating a room
    name, since from_cell=-1 has no grid room behind it."""
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    game = env.game
    for seed in range(1, 200):
        env.reset(seed=seed)
        if game.outer_draft_available():
            break
    else:
        raise AssertionError("no seed in range gave an available outer draft")
    game.open_outer_draft()
    pending = replay._pending_dict(game)
    assert pending["from_cell"] == -1
    assert pending["from_room"] is None


def test_recorder_sampling_and_top_window(tmp_path: Path):
    """The recorder keeps the best episode per window - a win beats any deeper
    losing run - and at sample_rate=1 it records every episode verbatim."""
    path = tmp_path / "replays.jsonl"
    rec = EpisodeRecorder(path, n_envs=1, reward="shaped", sample_rate=0.0,
                          top_every=10, episodes_done=0)

    def finish(episode: int, rank: int, win: bool = False):
        rec.on_step([episode % 7], [True])
        rec.on_episode_end(0, episode, {
            "episode_seed": episode, "deepest_rank": rank, "rooms_placed": rank,
            "termination_reason": "out_of_steps", "room46_reached": win})

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
    """The Observatory indexes replays by episode or by progress (wins and
    deeper runs first), flags top-window runs, and serves frames only for
    episodes it knows."""
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
    assert "divergence" in data  # key always present; None = clean replay
    assert obs.run_frames(999) is None


def test_frame_includes_scepter_color():
    """Every frame carries scepter_color: null when the scepter is inactive,
    the category string (e.g. 'green') once state.shops.scepter_color is set.

    The field must always be present in the serialized frame dict; its value
    is either None or one of the six SCEPTER_COLORS strings from shops.py.
    """
    from blueprince_sim.env.blueprince_env import BluePrinceEnv
    from blueprince_sim.engine.shops import SCEPTER_COLORS
    from blueprince_sim.rl.train import all_unlocks_config

    # Fresh reset with no Royal Scepter configured: field is present and null.
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=1)
    assert env.game.state.shops.scepter_color is None
    frame = replay._frame(env.game, None, "N")
    assert "scepter_color" in frame
    assert frame["scepter_color"] is None

    # Manually activate the scepter: frame reflects the live state.
    env.game.state.shops.scepter_color = "green"
    frame_active = replay._frame(env.game, None, "N")
    assert frame_active["scepter_color"] == "green"

    # Full episode round-trip: every frame has the key; its value is either
    # None or a valid scepter color (the episode may or may not activate it).
    record, _ = _play_random_episode(seed=7)
    frames, _div = replay.build_frames(record)
    valid = set(SCEPTER_COLORS) | {None}
    assert all("scepter_color" in f and f["scepter_color"] in valid for f in frames)


def test_option_orientation_is_always_a_legal_orientation():
    """Every drafted option's dealt orientation is a member of its own
    legal_orientations set, and (at this fixed, reproducible doorway) a
    corner-shaped option's set holds more than one entry -- the signal the
    Play tab uses to show "this room also legally fits another orientation
    here" even though nothing currently lets the player pick it directly for
    that option (see _option_legal_orientations's docstring: only
    ROTATE_ACTION, which advances the whole hand together, is wired up).
    """
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    open_actions = [i for i, ok in enumerate(env.action_masks()) if ok and i < A.CHOOSE_BASE]
    env.step(open_actions[0])
    pending = replay._pending_dict(game)
    assert pending is not None
    saw_multiple = False
    for opt in pending["options"]:
        if opt["hidden"]:
            assert opt["legal_orientations"] == []
            continue
        assert opt["orientation"] in opt["legal_orientations"]
        assert len(opt["legal_orientations"]) >= 1
        saw_multiple = saw_multiple or len(opt["legal_orientations"]) > 1
    assert saw_multiple, "expected a corner-shaped option with >1 legal orientation at this doorway"


def test_redraw_info_reports_cost_and_reason():
    """The pending dict's redraw field names the source REDRAW_ACTION would
    actually consume when available (mirroring env.actions._redraw_kind, the
    mask's own eligibility check) and states a concrete reason when no source
    is available -- the owner's literal complaint was seeing no explanation
    for why the redraw button was missing during a draft.
    """
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=42)
    game = env.game
    open_actions = [i for i, ok in enumerate(env.action_masks()) if ok and i < A.CHOOSE_BASE]
    env.step(open_actions[0])

    # No dice, no Study placed: unavailable, with a stated reason.
    game.state.dice = 0
    game.state.study_placed = False
    info = replay._pending_dict(game)["redraw"]
    assert info["available"] is False
    assert info["reason"]

    # Give the player a die: agrees with the mask, and names "die" as the cost.
    game.state.dice = 1
    info = replay._pending_dict(game)["redraw"]
    assert info == {"available": True, "kind": "die"}
    assert bool(env.action_masks()[A.REDRAW_ACTION]) is True


def test_frame_inventory_reports_held_items_by_name():
    """_frame's inventory field surfaces held special items by display name
    and count -- readable identifiers the old display omitted entirely -- and
    omits an item once its count drops to zero rather than listing it at 0.
    """
    env = BluePrinceEnv(cfg=all_unlocks_config("shaped"))
    env.reset(seed=1)
    game = env.game
    before = replay._frame(game, None, "N")["inventory"]
    assert all(it["id"] != "torch" for it in before)  # not held yet

    game.state.inventory["torch"] = 2
    frame = replay._frame(game, None, "N")
    torch_entries = [it for it in frame["inventory"] if it["id"] == "torch"]
    assert torch_entries == [{"id": "torch", "name": "Torch", "count": 2}]

    game.state.inventory["torch"] = 0
    frame = replay._frame(game, None, "N")
    assert all(it["id"] != "torch" for it in frame["inventory"])


def test_metrics_merge_and_downsample(tmp_path: Path):
    """Observatory metrics drop duplicate checkpoint samples and serve the
    eval series alongside the training series."""
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


# ---------------------------------------------- per-option counterfactual rewards


def test_option_rewards_scores_every_option_without_disturbing_the_game(registry):
    """Debug mode reports what each dealt option would pay, and changes nothing.

    Each option is scored on a copy, so the replay being rendered must come out
    of the call byte-identical -- otherwise inspecting a run would alter it.
    """
    from blueprince_sim.config import GameConfig
    from blueprince_sim.engine.game import Game, Phase
    from blueprince_sim.web import replay as RP

    g = Game(GameConfig(day=1, special_items=True), seed=7, registry=registry)
    g.reset()
    cell, d = g.open_doorways()[0]
    g.open_door(cell, d)
    assert g.phase is Phase.DRAFTING, "setup: a hand must be open"

    before = (list(g.state.grid), list(g.state.placed_doors), g.state.steps,
              g.state.gems, g.phase, len(g.state.pending.options))
    out = RP.option_rewards(g)
    after = (list(g.state.grid), list(g.state.placed_doors), g.state.steps,
             g.state.gems, g.phase, len(g.state.pending.options))
    assert before == after, "scoring the hand must not mutate the game"

    assert out is not None and len(out) == len(g.state.pending.options)
    for entry in out:
        assert entry["slot"] in {o.slot for o in g.state.pending.options}
        if not entry["error"]:
            assert isinstance(entry["reward"], float)
            assert entry["open_ways"] >= 0
            assert isinstance(entry["ante_reachable"], bool)


def test_option_rewards_is_none_with_no_hand_open(registry):
    """No draft, nothing to score -- None rather than an empty list.

    An empty list would read as "a hand with no options", which is a different
    state the UI would render as an empty draft panel.
    """
    from blueprince_sim.config import GameConfig
    from blueprince_sim.engine.game import Game
    from blueprince_sim.web import replay as RP

    g = Game(GameConfig(day=1), seed=1, registry=registry)
    g.reset()
    assert RP.option_rewards(g) is None


def test_frames_carry_option_rewards_only_when_debug_is_asked_for(registry):
    """The rewards cost a deep copy per option, so they are opt-in.

    A viewer who never opens the panel must not pay for them, and the plain
    build has to stay byte-compatible with what the UI already renders.
    """
    from blueprince_sim.web import replay as RP

    rec, _ = _play_random_episode(seed=5)
    plain, _ = RP.build_frames(rec)
    debug, _ = RP.build_frames(rec, debug=True)
    assert all(f["option_rewards"] is None for f in plain)
    assert any(f["option_rewards"] for f in debug if f.get("pending")), (
        "at least one frame with a hand must carry scores under debug"
    )


def test_option_rewards_scores_a_day_ending_choice_as_terminal(registry):
    """An option that ends the day on the spot is scored with the same
    `terminated=True` BluePrinceEnv.step would have used, not as if play
    continued.

    Choosing the dealt Dead End seals the house's only frontier doorway, so
    ``Game.choose`` itself flips the copy to ``Phase.TERMINAL`` before this
    function's own reward call runs. Scoring it as non-terminal would leave
    phi_paths' sealing penalty uncancelled -- a number the policy, scored
    through the real env, would never have been shown.
    """
    from blueprince_sim.config import GameConfig
    from blueprince_sim.engine.game import Game, Phase
    from blueprince_sim.engine.grid import N, S
    from blueprince_sim.engine.state import DraftOption, PendingDraft
    from blueprince_sim.env import rewards
    from blueprince_sim.web import replay as RP

    g = Game(GameConfig(), seed=1, registry=registry)
    st = g.state
    st.grid[2] = -1               # clear the day-start Entrance Hall
    st.placed_doors[2] = 0
    room = registry.by_id["entrance_hall"]  # stand-in; only its door mask matters
    st.grid[32] = room.idx
    st.placed_doors[32] = N       # the house's only frontier doorway
    st.entered[32] = True
    st.pos = 32
    st.steps = 5
    st.door_version += 1
    g.deepest_rank = 8            # matches the target cell's own rank: isolates
                                   # the assertion to phi_paths, no rank-delta term

    g.phase = Phase.DRAFTING
    pending = PendingDraft(
        from_cell=32, direction=N, target_cell=37,
        # orientation=S only: placed with no door but the one it was
        # entered by, so choosing it seals the house's last route.
        options=[DraftOption(room_idx=room.idx, orientation=S, gem_cost=0, slot=0)],
    )
    st.pending = pending
    g.doorway_drafts[(32, N)] = pending

    prev = rewards.snapshot(g)
    assert prev["phi_paths"] < 0, "setup: one open route, so sealing it costs something"

    out = RP.option_rewards(g)

    assert out is not None and len(out) == 1
    assert not out[0]["error"]
    assert out[0]["reward"] == pytest.approx(prev["phi_paths"] * -1 - 0.001)
