"""Category-bias activation: southern_cross_constellation, king_*, drafting_from_library.

Covers the four conditions the wave-1 category-bias task lit up or deliberately
left inert-but-shaped: the Southern Cross constellation stub (day-scoped flag,
no in-game setter), the five king_<color> tags (never emitted -- no Banner of
the King subsystem is modeled), and drafting_from_library (Bookshop half live,
rare-rarity half deliberately inert under a renamed, never-emitted condition).
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import build_decks
from blueprince_sim.engine.draft import DraftContext, _active_conditions, deal_draft
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

# A lone interior target cell (rank 3, col 2) reached by moving south from
# rank 2, col 2 -- comfortably away from grid edges so 4-way (cross) rooms are
# never ruled out by door-geometry legality (CLAUDE.md: 4-way rooms are edge-
# restricted, corners restrict to L-shapes/Dead Ends).
FROM_CELL = 7
DIRECTION = S
TARGET_CELL = 12

KING_TAGS = {"king_blueprint", "king_hallway", "king_bedroom", "king_shop", "king_blackprint"}


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def _bare_ctx(registry: Registry, cfg: GameConfig, state: GameState,
             from_room=None) -> DraftContext:
    """Build a DraftContext with no in-flight decks -- enough for _active_conditions."""
    return DraftContext(state, registry, cfg, Rng(0), set(), from_room)


def test_southern_cross_absent_by_default_present_when_flag_set(registry):
    """southern_cross_constellation is unreachable under the zero-value GameState
    default (no in-game setter exists yet) but appears the instant the day-scoped
    stub flag is set, proving the emission wiring itself works end to end."""
    cfg = GameConfig()
    state = GameState()
    ctx = _bare_ctx(registry, cfg, state)

    assert "southern_cross_constellation" not in _active_conditions(ctx)

    state.southern_cross_active = True
    assert "southern_cross_constellation" in _active_conditions(ctx)


def _sample_cross_rate(registry: Registry, cfg: GameConfig, n_seeds: int,
                       southern_cross: bool) -> tuple[int, int]:
    """Deal N independent single-hand drafts at TARGET_CELL; return (cross_count, total)."""
    cross = 0
    total = 0
    for seed in range(n_seeds):
        rng = Rng(seed)
        state = GameState()
        state.decks = build_decks(registry, cfg, rng)
        state.southern_cross_active = southern_cross
        pending = deal_draft(state, registry, cfg, rng, set(), FROM_CELL, DIRECTION, TARGET_CELL)
        for opt in pending.options:
            total += 1
            if registry.rooms[opt.room_idx].layout == "cross":
                cross += 1
    return cross, total


@pytest.fixture(scope="module")
def southern_cross_counts(registry):
    """(cross_with, total_with, cross_without, total_without) over 3000 seeds each,
    computed once and shared by the tests below (module-scoped: expensive sampling)."""
    cfg = GameConfig()
    cross_with, total_with = _sample_cross_rate(registry, cfg, 3000, southern_cross=True)
    cross_without, total_without = _sample_cross_rate(registry, cfg, 3000, southern_cross=False)
    return cross_with, total_with, cross_without, total_without


def test_southern_cross_biases_toward_cross_layout(southern_cross_counts):
    """With southern_cross_active set, layout:cross rooms are dealt at a
    statistically significant higher rate than with it unset (3000 seeds x 3
    option slots = 9000 samples per condition; the bias fires at 40% chance,
    so a strong shift is expected, not a marginal one)."""
    cross_with, total_with, cross_without, total_without = southern_cross_counts

    rate_with = cross_with / total_with
    rate_without = cross_without / total_without

    # Generous lower bound (cross rooms are rare, ~9% of the base pool) --
    # chosen to avoid flakiness while still requiring a real, large shift.
    assert rate_with > rate_without * 1.5, (
        f"southern_cross bias too weak: with={rate_with:.4f} without={rate_without:.4f}"
    )

    obs = [cross_with, total_with - cross_with]
    exp = [rate_without * total_with, (1 - rate_without) * total_with]
    _, p = stats.chisquare(obs, exp)
    assert p < 1e-6, (
        f"chi-square not significant: p={p:.2e} "
        f"(with={rate_with:.4f}, without={rate_without:.4f})"
    )


def test_king_tags_never_emitted_even_under_maximal_active_state(registry):
    """None of the five king_<color> tags (nor a bare 'king') are ever emitted,
    even when every other known condition is simultaneously active. No source
    models how the Banner of the King is obtained or its per-day color pick, so
    this must stay unreachable; it also guards against a future regression that
    emits a bare 'king' tag, which would wrongly fire all five biases at once
    (the player can only pick ONE color per day)."""
    cfg = GameConfig()
    state = GameState()
    state.furnace_placed = True
    state.greenhouse_placed = True
    state.schoolhouse_placed = True
    state.southern_cross_active = True
    state.draxus_active = True
    state.shops.scepter_color = "blueprint"
    library = registry.by_id["library"]
    ctx = _bare_ctx(registry, cfg, state, from_room=library)

    conds = _active_conditions(ctx)

    assert not (conds & KING_TAGS), f"king tag(s) leaked: {conds & KING_TAGS}"
    assert "king" not in conds


def test_drafting_from_library_is_positional(registry):
    """drafting_from_library is emitted only when the room being drafted FROM is
    the Library -- not for other rooms and not when there is no from_room at all
    (e.g. drafting from the pre-placed Entrance Hall isn't the Library)."""
    cfg = GameConfig()
    state = GameState()

    ctx_none = _bare_ctx(registry, cfg, state, from_room=None)
    assert "drafting_from_library" not in _active_conditions(ctx_none)

    other_room = registry.by_id["closet"]
    ctx_other = _bare_ctx(registry, cfg, state, from_room=other_room)
    assert "drafting_from_library" not in _active_conditions(ctx_other)

    library = registry.by_id["library"]
    ctx_library = _bare_ctx(registry, cfg, state, from_room=library)
    assert "drafting_from_library" in _active_conditions(ctx_library)


def _neuter_bookshop_bias(registry: Registry) -> Registry:
    """A copy of ``registry`` whose priority data drops the live Bookshop-bias
    entry, isolating that one entry's effect on the draft (control group)."""
    import copy

    neutered = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    priority["category_biases"] = [
        e for e in priority["category_biases"]
        if not (e.get("condition") == "drafting_from_library" and e.get("rooms") == ["bookshop"])
    ]
    object.__setattr__(neutered, "priority", priority)
    return neutered


def _sample_bookshop_rate(registry: Registry, cfg: GameConfig, n_seeds: int) -> tuple[int, int]:
    """Deal N independent single-hand drafts FROM the Library; return
    (hands_with_bookshop, total_hands)."""
    library = registry.by_id["library"]
    hits = 0
    for seed in range(n_seeds):
        rng = Rng(seed)
        state = GameState()
        state.decks = build_decks(registry, cfg, rng)
        state.grid[FROM_CELL] = library.idx
        pending = deal_draft(state, registry, cfg, rng, {"library"},
                             FROM_CELL, DIRECTION, TARGET_CELL)
        if any(registry.rooms[opt.room_idx].id == "bookshop" for opt in pending.options):
            hits += 1
    return hits, n_seeds


def test_drafting_from_library_bookshop_bias_applies(registry):
    """Drafting from the Library raises the rate Bookshop appears in the dealt
    hand versus an identical draft with only the Bookshop-bias entry removed
    (2000 seeds each) -- isolates the live entry's real effect on the draft
    path, not just its presence in _active_conditions."""
    cfg = GameConfig()
    neutered = _neuter_bookshop_bias(registry)

    hits_with, n = _sample_bookshop_rate(registry, cfg, 2000)
    hits_without, _ = _sample_bookshop_rate(neutered, cfg, 2000)

    rate_with = hits_with / n
    rate_without = hits_without / n
    assert rate_with > rate_without, (
        f"Bookshop bias had no measurable effect: with={rate_with:.4f} "
        f"without={rate_without:.4f}"
    )

    # Two-proportion chi-square (Bookshop is rare-rarity + 1 gem_cost + deck_copies=1,
    # so baseline is very low; the bias more than doubles it in practice).
    obs = [hits_with, n - hits_with]
    exp_rate = max(rate_without, 1e-6)
    exp = [exp_rate * n, (1 - exp_rate) * n]
    _, p = stats.chisquare(obs, exp)
    assert p < 1e-3, (
        f"chi-square not significant: p={p:.2e} (with={rate_with:.4f}, without={rate_without:.4f})"
    )


def test_drafting_from_library_rare_override_entry_stays_inert(registry):
    """The rarity-override entry (originally sharing the drafting_from_library
    condition) was renamed to a never-emitted condition so wiring up the
    Bookshop bias cannot accidentally also fire it -- its condition string
    must not appear in what _active_conditions can ever return for any state
    this module exercises."""
    entries = [e for e in registry.priority["category_biases"]
              if e.get("label") == "Rare Rooms (Library)"]
    assert len(entries) == 1
    inert_condition = entries[0]["condition"]
    assert inert_condition != "drafting_from_library"

    cfg = GameConfig()
    state = GameState()
    state.furnace_placed = True
    state.greenhouse_placed = True
    state.schoolhouse_placed = True
    state.southern_cross_active = True
    state.draxus_active = True
    state.shops.scepter_color = "blueprint"
    library = registry.by_id["library"]
    ctx = _bare_ctx(registry, cfg, state, from_room=library)

    assert inert_condition not in _active_conditions(ctx)
