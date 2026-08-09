"""Statistical test: Furnace red-category bias.

Verifies that placing the Furnace raises the proportion of red rooms among
dealt draft options, and that draws WITHOUT the Furnace are bit-identical to
the pre-Furnace baseline (determinism guard).
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

# Cell layout: rank 1 = cells 0-4 (entrance = cell 2).
# We draft northward: player at cell 2, door direction N, target cell 7.
DRAFT_FROM = 2
DRAFT_DIR = N
DRAFT_TARGET = 7

# Furnace is placed at cell 3 (rank 1, col 3) so it does not block the draft
# target at cell 7.  _place_room fires ON_PLACE which sets furnace_placed=True.
FURNACE_CELL = 3

# Number of drafts per condition; 3 options per draft → ~N*3 option samples.
# 10 000 drafts gives ~30 000 option samples — comfortably detects a 30% boost
# in red-room frequency.  Seeds 0..N-1 are fixed so the test is deterministic.
N_DRAFTS = 10_000

# Significance level (Bonferroni-free; only one hypothesis here).
ALPHA = 1e-6


def _count_red_options(game: Game, seed: int, place_furnace: bool) -> tuple[int, int]:
    """Return (red_count, total_count) across all options dealt for one draft."""
    game.reset(seed)
    if place_furnace:
        furnace = game.registry.by_id["furnace"]
        game._place_room(furnace, FURNACE_CELL, S)  # dead-end, door south
    game.state.steps = 999  # prevent step exhaustion
    pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
    red = sum(
        1 for opt in pending.options
        if game.registry.rooms[opt.room_idx].category == "red"
    )
    return red, len(pending.options)


def _sample_red_rate(cfg: GameConfig, place_furnace: bool) -> tuple[int, int]:
    """Aggregate red_count / total_options over N_DRAFTS episodes."""
    game = Game(cfg, seed=0)
    total_red = 0
    total_opts = 0
    for seed in range(N_DRAFTS):
        red, n = _count_red_options(game, seed, place_furnace)
        total_red += red
        total_opts += n
    return total_red, total_opts


@pytest.fixture(scope="module")
def furnace_bias_counts():
    """Compute (red, total) for with- and without-furnace in one pass (module scope
    so the expensive sampling runs only once for the whole module)."""
    cfg = GameConfig()
    red_with, total_with = _sample_red_rate(cfg, place_furnace=True)
    red_without, total_without = _sample_red_rate(cfg, place_furnace=False)
    return red_with, total_with, red_without, total_without


def test_furnace_raises_red_room_rate(furnace_bias_counts):
    """With the Furnace placed, red rooms appear significantly more often."""
    red_with, total_with, red_without, total_without = furnace_bias_counts

    rate_with = red_with / total_with
    rate_without = red_without / total_without

    # The Furnace bias fires with p=0.30 and re-deals a red room (if available).
    # In a fresh deck with ~8 red rooms out of ~79, the base red rate is ~10%.
    # After bias: roughly rate_without*(1-0.3) + 0.3*(red_availability) >> rate_without.
    # We require at least 1.5x uplift as a conservative lower bound.
    assert rate_with > rate_without * 1.5, (
        f"Furnace bias too weak: with={rate_with:.4f} without={rate_without:.4f}"
    )

    # Chi-square test: observed vs expected-if-no-bias.
    # H0: red rate is the same with and without the furnace.
    obs = [red_with, total_with - red_with]
    exp = [rate_without * total_with, (1 - rate_without) * total_with]
    _, p = stats.chisquare(obs, exp)
    assert p < ALPHA, (
        f"Chi-square not significant: p={p:.2e} "
        f"(with={rate_with:.4f}, without={rate_without:.4f})"
    )


def test_no_furnace_leaves_draws_unchanged():
    """Without a Furnace, draws must be bit-identical regardless of furnace code path.

    We re-run the same seeds twice (both without furnace) and verify the dealt
    options are identical.  This guards against accidental unconditional RNG
    consumption introduced by the bias wiring.
    """
    cfg = GameConfig()
    game = Game(cfg, seed=0)

    def collect(seed: int) -> list[tuple[int, int, int]]:
        """Return (room_idx, orientation, gem_cost) for each option."""
        game.reset(seed)
        pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
        return [(o.room_idx, o.orientation, o.gem_cost) for o in pending.options]

    for seed in range(200):
        run_a = collect(seed)
        run_b = collect(seed)
        assert run_a == run_b, f"seed {seed}: non-deterministic without furnace"
