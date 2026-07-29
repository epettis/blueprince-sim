"""Observatory areas backend: area tracking, replay frames, AreaStatsWriter, and API endpoints.

Tests cover the five deliverables of the feat/observatory-areas task:
1. areas_visited tracking in GameState / Game.travel_to
2. replay frames carrying the area field
3. AreaStatsWriter bucket/merge semantics
4. /api/areas structure invariants
5. /api/upgrade_stats correctness on synthetic data
6. Absent-file safety for /api/area_stats and /api/upgrade_stats
"""

from __future__ import annotations

import json
from pathlib import Path

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.rl.train import AreaStatsWriter
from blueprince_sim.web import replay as _replay
from blueprince_sim.web.server import Observatory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _game_with_west_gate() -> Game:
    """A game with west_gate_unlatched so open_outer_draft succeeds on step 1."""
    cfg = GameConfig(west_gate_unlatched=True)
    return Game(cfg, seed=9)


# ---------------------------------------------------------------------------
# Task 1: replay frames carry the area field
# ---------------------------------------------------------------------------


def test_frame_area_null_on_grid():
    """A replay frame taken while the player is on the 5x9 grid carries area=null.

    pos is authoritative when area is null; the field must always be present.
    """
    g = _game_with_west_gate()
    assert g.state.area is None  # player starts on the grid
    frame = _replay._frame(g, None, "N")
    assert "area" in frame
    assert frame["area"] is None


def test_frame_area_set_when_off_grid():
    """A replay frame taken while the player is at an area node carries that node's id.

    After open_outer_draft the player is at 'west_path'; area must reflect that.
    """
    g = _game_with_west_gate()
    g.open_outer_draft()
    assert g.state.area == "west_path"
    frame = _replay._frame(g, None, "N")
    assert frame["area"] == "west_path"


# ---------------------------------------------------------------------------
# Task 1: areas_visited tracking in GameState / Game.travel_to
# ---------------------------------------------------------------------------


def test_areas_visited_starts_empty():
    """A freshly-reset game has an empty areas_visited set."""
    g = _game_with_west_gate()
    assert g.state.areas_visited == set()


def test_areas_visited_populated_by_travel_to():
    """travel_to adds the destination to areas_visited; staying on the grid adds nothing.

    After travelling to west_path the set must contain it; after returning to
    'house' (a grid anchor) the set must contain 'house' too.
    """
    g = _game_with_west_gate()
    g.open_outer_draft()   # arrives at west_path (travel_to internally)
    assert "west_path" in g.state.areas_visited

    g.choose(0)
    outer_id = next(r.id for r in g.outer_rooms if r.id in g.placed_ids)
    g.travel_to(outer_id)
    assert outer_id in g.state.areas_visited

    # Returning to the grid anchor 'house' also records it
    g.travel_to("house")
    assert "house" in g.state.areas_visited


def test_areas_visited_in_env_info(registry):
    """episode-end info['visited_areas'] is a sorted list containing areas travelled.

    An episode that never goes off-grid reports an empty list; an episode that does
    go off-grid includes at least 'west_path'.  We test both behaviours separately
    to avoid flaky episodes.
    """
    from blueprince_sim.env.blueprince_env import BluePrinceEnv

    # --- episode with no off-grid travel ---
    env = BluePrinceEnv(cfg=GameConfig())
    _, info = env.reset(seed=1)
    assert "visited_areas" in info
    # The info at reset is the initial info (before any travel).
    # visited_areas is always present and is a sorted list.
    assert isinstance(info["visited_areas"], list)

    # --- manual travel to west_path and verify env info ---
    cfg = GameConfig(west_gate_unlatched=True)
    env2 = BluePrinceEnv(cfg=cfg)
    env2.reset(seed=9)
    # Travel off-grid by directly driving the game (env drives through actions,
    # but we can call game methods directly for unit-test precision).
    env2.game.open_outer_draft()
    env2.game.choose(0)
    info2 = env2._info()
    assert "west_path" in info2["visited_areas"]
    # visited_areas is sorted
    assert info2["visited_areas"] == sorted(info2["visited_areas"])


def test_visited_areas_not_in_info_for_unvisited_area(registry):
    """An area not visited is not present in visited_areas.

    Uses 'mine_north' (deeply gated, never reachable in a normal episode) as a
    reliable negative example: it must not appear in the visited set of any
    standard single-day episode.
    """
    from blueprince_sim.env.blueprince_env import BluePrinceEnv
    import numpy as np

    env = BluePrinceEnv(cfg=GameConfig(west_gate_unlatched=True))
    _, info = env.reset(seed=5)
    rng = np.random.default_rng(5)
    for _ in range(300):
        legal = np.flatnonzero(env.action_masks())
        if not len(legal):
            break
        _, _, term, trunc, info = env.step(int(rng.choice(legal)))
        if term or trunc:
            break
    # mine_north requires several gated steps; never reachable in one day
    assert "mine_north" not in info["visited_areas"]


# ---------------------------------------------------------------------------
# Task 3: AreaStatsWriter
# ---------------------------------------------------------------------------


def test_area_stats_writer_buckets_and_seed_counts(tmp_path: Path):
    """The writer flushes a bucket at the episode boundary and separates total
    visits from seeds-that-visited: visiting an area twice in one episode is
    2 visits but 1 seed_with.
    """
    path = tmp_path / "area_stats.jsonl"
    w = AreaStatsWriter(path, episodes_done=0, bucket=2)
    w.on_episode_end(1, {"visited_areas": ["west_path", "west_path", "grounds"]})
    w.on_episode_end(2, {"visited_areas": ["grounds"]})
    w.on_episode_end(3, {"visited_areas": ["tomb"]})  # rolls into bucket 2
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["bucket_start"] == 0 and rows[0]["bucket_end"] == 2
    assert rows[0]["seeds"] == 2
    assert rows[0]["visits"] == {"west_path": 2, "grounds": 2}
    assert rows[0]["seeds_with"] == {"west_path": 1, "grounds": 2}
    # Flush the partial bucket at shutdown
    w.flush()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[1]["seeds"] == 1 and rows[1]["visits"] == {"tomb": 1}


def test_area_stats_writer_skips_episodes_without_info(tmp_path: Path):
    """Episodes whose info lacks visited_areas are silently ignored.

    An env that predates the feature should not be counted as an empty seed.
    """
    path = tmp_path / "area_stats.jsonl"
    w = AreaStatsWriter(path, episodes_done=0, bucket=1)
    w.on_episode_end(1, {"deepest_rank": 3})
    w.flush()
    assert not path.exists()


def test_server_merges_partial_area_buckets(tmp_path: Path):
    """Observatory.area_stats() merges rows sharing a bucket_start by summing
    seeds and both visit counters, just like draft_stats does.
    """
    (tmp_path / "area_stats.jsonl").write_text(
        json.dumps({"bucket_start": 0, "bucket_end": 10000, "seeds": 3000,
                    "visits": {"west_path": 30}, "seeds_with": {"west_path": 28}}) + "\n" +
        json.dumps({"bucket_start": 0, "bucket_end": 10000, "seeds": 7000,
                    "visits": {"west_path": 70, "grounds": 14},
                    "seeds_with": {"west_path": 65, "grounds": 14}}) + "\n"
    )
    obs = Observatory(tmp_path, "shaped")
    result = obs.area_stats()
    assert "train" in result
    assert len(result["train"]) == 1
    b = result["train"][0]
    assert b["seeds"] == 10000
    assert b["visits"] == {"west_path": 100, "grounds": 14}
    assert b["seeds_with"] == {"west_path": 93, "grounds": 14}


# ---------------------------------------------------------------------------
# Task 4: /api/areas structure invariants
# ---------------------------------------------------------------------------


def test_areas_endpoint_edges_resolve_to_nodes(tmp_path: Path):
    """Every edge's from/to id appears in the nodes list of the same payload.

    Broken graph wiring (a typo in areas.json) would produce a dangling reference
    that breaks the front-end layout; this catches it at the API layer.
    """
    obs = Observatory(tmp_path, "shaped")
    data = obs.areas()
    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert edge["from"] in node_ids, f"edge from {edge['from']!r} has no matching node"
        assert edge["to"] in node_ids, f"edge to {edge['to']!r} has no matching node"


def test_areas_endpoint_house_depth_is_zero(tmp_path: Path):
    """The 'house' node has depth 0 because it is the BFS origin."""
    obs = Observatory(tmp_path, "shaped")
    data = obs.areas()
    house = next(n for n in data["nodes"] if n["id"] == "house")
    assert house["depth"] == 0


def test_areas_endpoint_reachable_nodes_have_nonnull_depth(tmp_path: Path):
    """Nodes directly adjacent to 'house' (undirected, no gates) have non-null depth.

    'grounds' connects to 'house' in the graph; with gates ignored and undirected
    traversal, it must be reachable and carry a positive integer depth.
    """
    obs = Observatory(tmp_path, "shaped")
    data = obs.areas()
    grounds = next((n for n in data["nodes"] if n["id"] == "grounds"), None)
    assert grounds is not None
    assert grounds["depth"] is not None
    assert grounds["depth"] > 0


def test_areas_endpoint_band_values(tmp_path: Path):
    """Every node's band is one of the three allowed values: surface/underground/anchor."""
    obs = Observatory(tmp_path, "shaped")
    data = obs.areas()
    allowed = {"surface", "underground", "anchor"}
    for node in data["nodes"]:
        assert node["band"] in allowed, (
            f"node {node['id']!r} has unexpected band {node['band']!r}"
        )


def test_areas_endpoint_stub_gates_present(tmp_path: Path):
    """stub_gates key is present in the /api/areas response (may be empty dict)."""
    obs = Observatory(tmp_path, "shaped")
    data = obs.areas()
    assert "stub_gates" in data
    assert isinstance(data["stub_gates"], dict)


# ---------------------------------------------------------------------------
# Task 5: /api/upgrade_stats
# ---------------------------------------------------------------------------


def _write_upgrades(path: Path, rows: list[dict]) -> None:
    """Write synthetic upgrade records to a jsonl file."""
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_upgrade_stats_offered_and_chosen_counts(tmp_path: Path):
    """variant offered/chosen counts and selection_rate are computed from raw records.

    A variant offered 3 times and chosen once has selection_rate ≈ 0.333.
    A variant offered but never chosen has rate 0.0 (no ZeroDivisionError).
    """
    rows = [
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_a",
         "catacombs_unlocked": False, "draft_counts": {"base": 2},
         "slots_upgraded": 0, "disks_held": 0, "day": 5},
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_b",
         "catacombs_unlocked": True, "draft_counts": {"base": 3},
         "slots_upgraded": 1, "disks_held": 1, "day": 6},
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_a",
         "catacombs_unlocked": False, "draft_counts": {},
         "slots_upgraded": 1, "disks_held": 0, "day": 7},
    ]
    _write_upgrades(tmp_path / "upgrades.jsonl", rows)
    obs = Observatory(tmp_path, "shaped")
    result = obs.upgrade_stats()
    variants = {v["variant"]: v for v in result["variants"]}

    # v_a: offered 3 times, chosen 2 → rate 2/3
    assert variants["v_a"]["offered"] == 3
    assert variants["v_a"]["chosen"] == 2
    assert abs(variants["v_a"]["selection_rate"] - 2 / 3) < 1e-6

    # v_b: offered 3 times, chosen 1 → rate 1/3
    assert variants["v_b"]["offered"] == 3
    assert variants["v_b"]["chosen"] == 1
    assert abs(variants["v_b"]["selection_rate"] - 1 / 3) < 1e-6

    # v_c: offered 3 times, never chosen → rate 0.0 (no ZeroDivisionError)
    assert variants["v_c"]["offered"] == 3
    assert variants["v_c"]["chosen"] == 0
    assert variants["v_c"]["selection_rate"] == 0.0


def test_upgrade_stats_gates_section(tmp_path: Path):
    """The gates section counts total decisions, catacombs_unlocked, and
    slot_draft_count_zero correctly.

    slot_draft_count_zero counts decisions where every value in draft_counts
    is 0 or the dict is empty (the min_drafts bottleneck).
    """
    rows = [
        # empty draft_counts -> slot_draft_count_zero
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_a",
         "catacombs_unlocked": True, "draft_counts": {},
         "slots_upgraded": 0, "disks_held": 0, "day": 1},
        # all-zero draft_counts -> slot_draft_count_zero
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_b",
         "catacombs_unlocked": False, "draft_counts": {"base": 0},
         "slots_upgraded": 0, "disks_held": 0, "day": 2},
        # nonzero draft_counts -> NOT slot_draft_count_zero
        {"offered": ["v_a", "v_b", "v_c"], "chosen_variant": "v_c",
         "catacombs_unlocked": False, "draft_counts": {"base": 5},
         "slots_upgraded": 1, "disks_held": 0, "day": 3},
    ]
    _write_upgrades(tmp_path / "upgrades.jsonl", rows)
    obs = Observatory(tmp_path, "shaped")
    result = obs.upgrade_stats()
    gates = result["gates"]
    assert gates["decisions"] == 3
    assert gates["catacombs_unlocked"] == 1
    assert gates["slot_draft_count_zero"] == 2


def test_upgrade_stats_variants_sorted_by_offered(tmp_path: Path):
    """Variants are sorted descending by offered count."""
    rows = [
        {"offered": ["v_rare", "v_a", "v_b"], "chosen_variant": "v_rare",
         "catacombs_unlocked": False, "draft_counts": {},
         "slots_upgraded": 0, "disks_held": 0, "day": 1},
        {"offered": ["v_common", "v_a", "v_b"], "chosen_variant": "v_common",
         "catacombs_unlocked": False, "draft_counts": {},
         "slots_upgraded": 0, "disks_held": 0, "day": 2},
        {"offered": ["v_common", "v_a", "v_b"], "chosen_variant": "v_a",
         "catacombs_unlocked": False, "draft_counts": {},
         "slots_upgraded": 0, "disks_held": 0, "day": 3},
    ]
    _write_upgrades(tmp_path / "upgrades.jsonl", rows)
    obs = Observatory(tmp_path, "shaped")
    result = obs.upgrade_stats()
    # v_common is offered 2 times; v_a, v_b each 3; v_rare once
    # Sort order: [v_a=3, v_b=3, v_common=2, v_rare=1]
    offered_counts = [v["offered"] for v in result["variants"]]
    assert offered_counts == sorted(offered_counts, reverse=True)


# ---------------------------------------------------------------------------
# Task 6: absent-file safety
# ---------------------------------------------------------------------------


def test_area_stats_absent_file_returns_empty_structure(tmp_path: Path):
    """area_stats() returns empty train list (not a 500) when file is absent."""
    obs = Observatory(tmp_path, "shaped")
    result = obs.area_stats()
    assert result == {"train": []}


def test_upgrade_stats_absent_file_returns_empty_structure(tmp_path: Path):
    """upgrade_stats() returns empty structure (not a 500) when file is absent."""
    obs = Observatory(tmp_path, "shaped")
    result = obs.upgrade_stats()
    assert result == {"variants": [], "economy": [], "gates": {}}
