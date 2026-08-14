"""Draft-frequency tracking: engine list, bucket writer, server merge.

Covers the observable plumbing behind the dashboard's draft-frequency
charts: the engine records every drafted room's display name (and only
drafts - the pre-placed Entrance Hall and Antechamber are excluded), the
env surfaces the list in ``info``, ``DraftStatsWriter`` buckets episodes
and distinguishes total drafts from seeds-containing, and the server
merges partial bucket rows written across stops and resumes.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from dataclasses import replace

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine.items import EXTRA_ITEM_TABLE, expected_yields
from blueprince_sim.engine.model import Effect, ItemSpec
from blueprince_sim.rl.train import DraftStatsWriter
from blueprince_sim.web.replay import rooms_meta
from blueprince_sim.web.server import Observatory


def _rollout(seed: int):
    """Play one masked-random episode to the end; returns (env, final info)."""
    env = make_env(GameConfig())
    obs, info = env.reset(seed=seed)
    rng = np.random.default_rng(seed)
    for _ in range(500):
        legal = np.flatnonzero(env.action_masks())
        if len(legal) == 0:
            break
        obs, r, term, trunc, info = env.step(int(rng.choice(legal)))
        if term or trunc:
            break
    return env, info


def test_drafted_rooms_match_placements():
    """Every placement after day start is recorded by display name: the list
    grows to rooms_placed minus the pre-placed Entrance Hall, and each name
    is a real room name from the registry."""
    env, info = _rollout(seed=7)
    drafted = info["drafted_rooms"]
    assert len(drafted) == info["rooms_placed"] - 1
    names = {room.name for room in env.unwrapped.game.registry.rooms}
    assert set(drafted) <= names
    assert "Entrance Hall" not in drafted


def test_reset_clears_drafted_rooms():
    """A new day starts with an empty drafted list even after a played episode.

    Forces one draft via the greedy policy to guarantee a non-empty list before
    the reset, rather than relying on the random rollout's action choice.
    """
    from blueprince_sim.cli.policies import POLICIES
    from blueprince_sim.engine.game import Phase
    import random
    policy = POLICIES["frontier_greedy"]
    env = make_env(GameConfig())
    env.reset(seed=5)
    rng = random.Random(5)
    for _ in range(200):
        if env.game.phase is Phase.TERMINAL:
            break
        policy(env.game, rng)
    info = env.unwrapped._info()
    assert info["drafted_rooms"], "greedy policy should draft at least one room"
    _, info = env.reset(seed=9)
    assert info["drafted_rooms"] == []


def test_writer_buckets_and_seed_counts(tmp_path):
    """The writer flushes a bucket when an episode crosses the boundary, and
    counts drafts and seeds-with separately: a room drafted twice in one seed
    is 2 drafts but 1 seed."""
    path = tmp_path / "draft_stats.jsonl"
    w = DraftStatsWriter(path, episodes_done=0, bucket=2)
    w.on_episode_end(1, {"drafted_rooms": ["Garage", "Garage", "Den"]})
    w.on_episode_end(2, {"drafted_rooms": ["Den"]})
    w.on_episode_end(3, {"drafted_rooms": ["Parlor"]})  # rolls into bucket 2
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["bucket_start"] == 0 and rows[0]["bucket_end"] == 2
    assert rows[0]["seeds"] == 2
    assert rows[0]["drafts"] == {"Garage": 2, "Den": 2}
    assert rows[0]["seeds_with"] == {"Garage": 1, "Den": 2}
    w.flush()  # partial bucket at shutdown
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[1]["seeds"] == 1 and rows[1]["drafts"] == {"Parlor": 1}


def test_writer_skips_episodes_without_draft_info(tmp_path):
    """Episodes whose info lacks drafted_rooms (e.g. from an env predating the
    feature) are ignored rather than counted as empty seeds."""
    path = tmp_path / "draft_stats.jsonl"
    w = DraftStatsWriter(path, episodes_done=0, bucket=1)
    w.on_episode_end(1, {"deepest_rank": 3})
    w.flush()
    assert not path.exists()


def test_expected_yields_formula(registry):
    """Guaranteed items count in full; "random" items and luck-rolled extras
    contribute their table-weighted expectation; grant/anti_luck effects add
    (or subtract) flat amounts. Verified on synthetic rooms so the test pins
    the formula, not the data.

    p_extra is hard-coded from the wiki rather than derived from
    engine/items.py or data/items.json's item_ladder (the same dict
    expected_yields itself reads) -- deriving it from either would make this
    test pass for any value, the anti-pattern docs/open_tasks.md's 2026-08-13
    decisions log found here. items.json's luck.day_start is 10, which the
    item_ladder bands to 5-10 luck; the wiki (Luck page, "Luck effects") says:
    "5-10 Luck: The chance to get 1 item is the first line of the above that
    applies: ... If Veteran Mode is enabled, 15%." expected_yields assumes day
    1 (so the Day>=6/Day>=3 rows don't match), Room 46 not reached, and
    Veteran Mode on (GameConfig.veteran_mode's own default) -- under those
    assumptions "Veteran Mode is enabled" is the first row that matches.
    """
    base = registry.rooms[0]
    weights = dict(EXTRA_ITEM_TABLE)
    p_key = weights["key"] / sum(weights.values())
    p_coins = weights["coins"] / sum(weights.values())
    assert registry.item_rules["luck"]["day_start"] == 10, "test assumes the 5-10 luck band"
    p_extra = 0.15
    pile = registry.item_rules["coins"]
    pile_avg = (pile["pile_min"] + pile["pile_max"]) / 2

    plain = replace(base, items=ItemSpec(guaranteed=(("key", 2), ("gem", 1), ("coins", 2))),
                    effects=())
    y = expected_yields(plain, registry)
    assert y == {"steps": 0.0, "keys": 2.0, "gems": 1.0,
                 "coins": 2 * pile_avg, "luck": 0.0}

    # additional_max=2 does not multiply p_extra: a ladder roll gives a TOTAL
    # item count for the whole room (already p_extra), clamped to
    # additional_max -- not additional_max independent p_extra-chance slots.
    lucky = replace(base, items=ItemSpec(guaranteed=(("random", 4),), additional_max=2),
                    effects=())
    y = expected_yields(lucky, registry)
    assert y["keys"] == pytest.approx((4 + p_extra) * p_key)
    assert y["coins"] == pytest.approx((4 + p_extra) * p_coins * pile_avg)

    effectful = replace(base, items=ItemSpec(), effects=(
        Effect(tag="grant", params=(("amount", 2), ("resource", "steps"))),
        Effect(tag="grant", params=(("amount", -1), ("resource", "steps"))),
        Effect(tag="anti_luck", params=()),
    ))
    y = expected_yields(effectful, registry)
    assert y["steps"] == 1.0
    assert y["luck"] == -7.0  # anti_luck's default amount


def test_rooms_meta_carries_yields(registry):
    """Every room's client metadata includes a finite yields dict with the
    four indicator resources."""
    metas = rooms_meta(registry)
    assert len(metas) == len(registry.rooms)
    for m in metas:
        assert set(m["yields"]) == {"steps", "keys", "gems", "coins", "luck"}
        assert all(isinstance(v, float) for v in m["yields"].values())


def test_server_merges_partial_buckets(tmp_path):
    """Rows sharing a bucket_start (a stop + resume inside one bucket) merge by
    summing seeds and both counters, and eval rows carrying drafts surface in
    the eval series."""
    (tmp_path / "draft_stats.jsonl").write_text(
        json.dumps({"bucket_start": 0, "bucket_end": 10000, "seeds": 4000,
                    "drafts": {"Garage": 40}, "seeds_with": {"Garage": 38}}) + "\n" +
        json.dumps({"bucket_start": 0, "bucket_end": 10000, "seeds": 6000,
                    "drafts": {"Garage": 60, "Den": 10},
                    "seeds_with": {"Garage": 55, "Den": 10}}) + "\n")
    (tmp_path / "eval.jsonl").write_text(
        json.dumps({"episodes": 100, "eval_episodes": 500, "p_antechamber": 0.0,
                    "sampled_at": 1.0}) + "\n" +  # pre-feature row: no drafts
        json.dumps({"episodes": 200, "eval_episodes": 500, "p_antechamber": 0.0,
                    "drafts": {"Den": 7}, "seeds_with": {"Den": 6},
                    "sampled_at": 2.0}) + "\n")
    ds = Observatory(tmp_path, "shaped").draft_stats()
    assert len(ds["train"]) == 1
    bucket = ds["train"][0]
    assert bucket["seeds"] == 10000
    assert bucket["drafts"] == {"Garage": 100, "Den": 10}
    assert bucket["seeds_with"] == {"Garage": 93, "Den": 10}
    assert len(ds["eval"]) == 1
    assert ds["eval"][0]["drafts"] == {"Den": 7}
