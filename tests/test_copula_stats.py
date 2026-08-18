"""The return/depth dependence stream behind the Observatory's copula panel.

Win rate is 0 for long stretches of a run, so it carries no gradient to watch.
What still moves is whether the return a policy collects tracks the depth it
reached. These tests pin the statistic itself against hand-computable cases,
never against the implementation's own output.
"""

from __future__ import annotations

import json

import pytest

from blueprince_sim.rl.train import CopulaStatsWriter, _average_ranks, _spearman


def _info(ret: float, depth: int) -> dict:
    """One finished episode as the callback sees it (Monitor's key included)."""
    return {"episode": {"r": ret, "l": 10}, "deepest_rank": depth}


# ------------------------------------------------------------ rank machinery


def test_tied_values_share_their_average_rank():
    """Ties take the mean of the ranks they span, not an arbitrary order.

    Both margins tie heavily -- deepest_rank has nine values at most -- so
    ordinal ranks would impose an order inside a tie group and manufacture
    dependence the data does not contain.
    """
    # values 10, 20, 20, 30 -> ranks 1, 2.5, 2.5, 4
    assert _average_ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]
    # all tied -> everyone takes the midpoint of 1..4
    assert _average_ranks([7.0] * 4) == [2.5] * 4


def test_spearman_is_exactly_one_for_a_monotone_pairing():
    """A strictly increasing relation scores +1 whatever the raw scale.

    Spearman reads ranks only, so an arbitrary monotone transform of either
    margin must not move it -- which is the property that makes it the right
    summary for a reward whose units are not comparable to a rank.
    """
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _spearman(xs, [10.0, 20.0, 30.0, 40.0, 50.0]) == pytest.approx(1.0)
    assert _spearman(xs, [0.1, 9.0, 91.0, 400.0, 5000.0]) == pytest.approx(1.0)
    assert _spearman(xs, [-1.0, -2.0, -3.0, -4.0, -5.0]) == pytest.approx(-1.0)


def test_spearman_matches_the_textbook_value_on_a_known_sample():
    """A hand-checkable sample with no ties: rho = 1 - 6*sum(d^2)/(n(n^2-1)).

    Hard-coded from that published formula rather than recomputed by the
    function under test: x ranks 1..5 against y ranks 1,3,2,5,4 gives
    sum(d^2) = 0+1+1+1+1 = 4, so rho = 1 - 24/120 = 0.8.
    """
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 30.0, 20.0, 50.0, 40.0]
    assert _spearman(xs, ys) == pytest.approx(0.8)


def test_a_constant_margin_reports_no_answer_rather_than_zero():
    """rho is undefined when either margin never varies, and None says so.

    Early buckets really do end every episode at rank 1. Reporting 0.0 there
    would draw a line claiming "return tells you nothing about depth", when
    the truthful statement is that the question cannot be asked yet.
    """
    assert _spearman([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]) is None
    assert _spearman([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None
    assert _spearman([1.0], [1.0]) is None


# --------------------------------------------------------------- the writer


def test_a_bucket_is_emitted_once_its_episode_range_is_crossed(tmp_path):
    """One record per bucket, carrying the sample it actually covered.

    The record is what the dashboard plots a point from, so it has to name its
    own episode range and sample size rather than leaving the reader to infer
    them from position in the file.
    """
    path = tmp_path / "copula_stats.jsonl"
    w = CopulaStatsWriter(path, episodes_done=0, bucket=4)
    for ep in range(1, 5):
        w.on_episode_end(ep, _info(float(ep), ep))
    assert not path.exists(), "a bucket must not be written before it is full"
    w.on_episode_end(5, _info(9.0, 9))   # first episode of the next bucket
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert (rows[0]["bucket_start"], rows[0]["bucket_end"], rows[0]["n"]) == (0, 4, 4)
    assert rows[0]["spearman"] == pytest.approx(1.0)


def test_an_episode_without_a_monitor_return_is_skipped_not_zeroed(tmp_path):
    """A missing return is dropped, never folded in as 0.0.

    The return arrives via the Monitor wrapper; an env without it would
    otherwise contribute a fake worst-case return to every bucket and drag the
    dependence toward a value nothing in the run produced.
    """
    path = tmp_path / "copula_stats.jsonl"
    w = CopulaStatsWriter(path, episodes_done=0, bucket=100)
    w.on_episode_end(1, {"deepest_rank": 4})            # no "episode" key
    w.on_episode_end(2, {"episode": {"l": 5}, "deepest_rank": 4})  # no "r"
    w.on_episode_end(3, _info(1.0, 1))
    w.flush()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["n"] == 1, "only the episode carrying a return may count"


def test_the_grid_puts_a_monotone_sample_on_its_diagonal(tmp_path):
    """Perfect dependence fills the copula grid's diagonal and nothing else.

    This is the panel's whole visual claim -- mass on the diagonal means depth
    and return move together -- so it is pinned directly rather than trusted.
    """
    path = tmp_path / "copula_stats.jsonl"
    G = CopulaStatsWriter.GRID
    n = G * 4
    w = CopulaStatsWriter(path, episodes_done=0, bucket=n)
    for ep in range(1, n + 1):
        w.on_episode_end(ep, _info(float(ep), ep))
    w.flush()
    grid = json.loads(path.read_text().splitlines()[0])["grid"]
    for j, row in enumerate(grid):
        for i, count in enumerate(row):
            if i == j:
                assert count > 0, f"diagonal cell ({i},{j}) must hold mass"
            else:
                assert count == 0, f"off-diagonal cell ({i},{j}) must be empty"


def test_the_grid_totals_the_bucket_and_spreads_when_independent(tmp_path):
    """Every episode lands in exactly one cell, and independence spreads them.

    The total guards against a binning bug silently dropping observations at an
    edge; the spread is the contrast that makes the diagonal case meaningful.
    """
    path = tmp_path / "copula_stats.jsonl"
    G = CopulaStatsWriter.GRID
    n = G * G
    w = CopulaStatsWriter(path, episodes_done=0, bucket=n)
    # Return ascends while depth cycles, so the two carry no monotone relation.
    for ep in range(1, n + 1):
        w.on_episode_end(ep, _info(float(ep), (ep % G) + 1))
    w.flush()
    rec = json.loads(path.read_text().splitlines()[0])
    assert sum(sum(row) for row in rec["grid"]) == n
    occupied = sum(1 for row in rec["grid"] for c in row if c)
    assert occupied > G, "an independent sample must not concentrate on one line"


def test_resuming_mid_bucket_keeps_the_bucket_index(tmp_path):
    """A resumed run continues numbering from the episodes already done.

    Without this the dashboard's x-axis would restart at 0 on every resume and
    the series would fold back over itself.
    """
    path = tmp_path / "copula_stats.jsonl"
    w = CopulaStatsWriter(path, episodes_done=20_000, bucket=5_000)
    w.on_episode_end(20_001, _info(1.0, 1))
    w.on_episode_end(20_002, _info(2.0, 3))
    w.flush()
    rec = json.loads(path.read_text().splitlines()[0])
    assert (rec["bucket_start"], rec["bucket_end"]) == (20_000, 25_000)
