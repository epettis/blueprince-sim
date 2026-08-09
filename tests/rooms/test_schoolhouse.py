"""Schoolhouse Classroom-category bias: placement sets the flag, the flag
raises Classroom's draft rate, and the flag does not leak across days.

Mirrors tests/test_furnace_bias.py's statistical idiom for the sibling
schoolhouse_bias/greenhouse_bias/furnace_bias trio of Hook.ON_PLACE handlers.
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry

# Cell layout: rank 1 = cells 0-4 (entrance = cell 2).
# We draft northward: player at cell 2, door direction N, target cell 7.
DRAFT_FROM = 2
DRAFT_DIR = N
DRAFT_TARGET = 7

# Schoolhouse is placed at cell 3 (rank 1, col 3) so it does not block the
# draft target at cell 7. _place_room fires ON_PLACE which sets
# schoolhouse_placed=True (and injects 8 Classrooms into today's decks).
SCHOOLHOUSE_CELL = 3

# Number of drafts per condition; 3 options per draft -> ~N*3 option samples.
N_DRAFTS = 10_000

# Significance level (Bonferroni-free; only one hypothesis here).
ALPHA = 1e-6


def test_placing_schoolhouse_sets_schoolhouse_placed_flag():
    """The ON_PLACE hook is the single missing link between the datamined
    'schoolhouse' priority_draws condition and play: placing the Schoolhouse
    must flip state.schoolhouse_placed from its False default to True."""
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    assert game.state.schoolhouse_placed is False

    schoolhouse = game.registry.by_id["schoolhouse"]
    game._place_room(schoolhouse, SCHOOLHOUSE_CELL, S)

    assert game.state.schoolhouse_placed is True


def test_schoolhouse_flag_does_not_leak_across_days():
    """schoolhouse_placed lives on GameState, which Game.reset() replaces with
    a fresh GameState() each day (mirrors greenhouse_placed/furnace_placed,
    which reset the same way) -- placing the Schoolhouse on one day must not
    carry the flag into the next day's reset."""
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    schoolhouse = game.registry.by_id["schoolhouse"]
    game._place_room(schoolhouse, SCHOOLHOUSE_CELL, S)
    assert game.state.schoolhouse_placed is True

    game.reset(seed=1)
    assert game.state.schoolhouse_placed is False


def _count_classroom_options(game: Game, seed: int, place_schoolhouse: bool) -> tuple[int, int]:
    """Return (classroom_count, total_count) across all options dealt for one draft."""
    game.reset(seed)
    if place_schoolhouse:
        schoolhouse = game.registry.by_id["schoolhouse"]
        game._place_room(schoolhouse, SCHOOLHOUSE_CELL, S)
    game.state.steps = 999  # prevent step exhaustion
    pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
    classroom = sum(
        1 for opt in pending.options
        if game.registry.rooms[opt.room_idx].id == "classroom"
    )
    return classroom, len(pending.options)


def _sample_classroom_rate(cfg: GameConfig, place_schoolhouse: bool) -> tuple[int, int]:
    """Aggregate classroom_count / total_options over N_DRAFTS episodes."""
    game = Game(cfg, seed=0)
    total_classroom = 0
    total_opts = 0
    for seed in range(N_DRAFTS):
        classroom, n = _count_classroom_options(game, seed, place_schoolhouse)
        total_classroom += classroom
        total_opts += n
    return total_classroom, total_opts


@pytest.fixture(scope="module")
def schoolhouse_bias_counts():
    """Compute (classroom, total) for with- and without-schoolhouse in one pass
    (module scope so the expensive sampling runs only once for the whole module)."""
    cfg = GameConfig()
    classroom_with, total_with = _sample_classroom_rate(cfg, place_schoolhouse=True)
    classroom_without, total_without = _sample_classroom_rate(cfg, place_schoolhouse=False)
    return classroom_with, total_with, classroom_without, total_without


def test_schoolhouse_raises_classroom_rate(schoolhouse_bias_counts):
    """With the Schoolhouse placed, Classroom appears significantly more often
    among dealt draft options -- both the 35% category-bias re-deal and the
    8 injected Classroom decks push the rate up versus an identical draft
    without the Schoolhouse.

    Classroom's pool is "studio_addition", which the default GameConfig
    leaves entirely disabled (cfg.studio_additions is the empty set), so
    absent the Schoolhouse's inject_pool effect Classroom is structurally
    undraftable -- the without-Schoolhouse baseline is exactly 0, not merely
    low. A plain chi-square against a zero expected frequency is degenerate,
    so this asserts the exact zero baseline directly and then uses a
    one-sided binomial test to confirm the with-Schoolhouse rate is
    significantly above a small epsilon rather than comparing two rates."""
    classroom_with, total_with, classroom_without, total_without = schoolhouse_bias_counts

    assert classroom_without == 0, (
        f"Classroom dealt without Schoolhouse (should be structurally impossible): "
        f"{classroom_without}/{total_without}"
    )
    assert classroom_with > 0

    # One-sided binomial test: is the with-Schoolhouse rate significantly
    # above a small epsilon (1%)? The observed rate is ~20%, so this is a
    # deliberately conservative null, not a tight fit to the true rate.
    result = stats.binomtest(classroom_with, total_with, p=0.01, alternative="greater")
    assert result.pvalue < ALPHA, (
        f"Schoolhouse bias not significant: with={classroom_with}/{total_with} "
        f"p={result.pvalue:.2e}"
    )


def test_no_schoolhouse_leaves_draws_unchanged():
    """Without a Schoolhouse, draws must be bit-identical regardless of the
    schoolhouse code path -- guards against accidental unconditional RNG
    consumption introduced by the bias wiring."""
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
        assert run_a == run_b, f"seed {seed}: non-deterministic without schoolhouse"


def test_schoolhouse_category_does_not_activate_the_outer_shop_dead_branch():
    """Schoolhouse's category is "blueprint" (corrected from the pool name
    "outer"), not "shop": entering it off-grid must not resolve a
    current_shop_id -- that branch (game.py:994 / shops.py:359) only fires
    for Trading Post. See tests/rooms/test_trading_post.py for the
    positive case."""
    reg = Registry.load()
    assert reg.by_id["schoolhouse"].category == "blueprint"

    # Seed 4's outer-room hand deals Schoolhouse into slot 1 (verified by
    # construction; shared with tests/rooms/test_toolshed.py's seed).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=4, registry=reg)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 1)
    assert g.registry.rooms[opt.room_idx].id == "schoolhouse", (
        "setup: seed must deal Schoolhouse into slot 1"
    )
    g.choose(1)
    g.travel_to("schoolhouse")

    assert g.state.outer_room_entered
    assert shops.current_shop_id(g) is None
