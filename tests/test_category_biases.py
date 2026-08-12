"""Category-bias activation: southern_cross_constellation, king_*, drafting_from_library,
electromagnet.

Covers the four conditions the wave-1 category-bias task lit up or deliberately
left inert-but-shaped: the Southern Cross constellation stub (day-scoped flag,
no in-game setter), the five king_<color> tags (never emitted -- no Banner of
the King subsystem is modeled), and drafting_from_library's Bookshop re-deal
bias. The Library's rarity-table override is implemented directly in
decks.py::roll_rarity rather than through the category_biases table -- see
test_draft_stats.py for its statistical coverage.

Also covers the Powered Electromagnet's "mechanical_or_rotunda" bias: the
condition is emitted while the item is held (inventory-based, like Compass),
and the category resolves as a union of Room.is_category("mechanical") plus
the Rotunda by id (see draft.py's _category_matches, which reads the
bias record's own category_base/category_extra_rooms).
"""

from __future__ import annotations

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import build_decks
from blueprince_sim.engine.draft import (
    DraftContext,
    _active_conditions,
    _category_matches,
    deal_draft,
)
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

MECHANICAL_ROOM_IDS = {
    "utility_closet",
    "boiler_room",
    "pump_room",
    "security",
    "workshop",
    "laboratory",
    "electric_eel_aquarium__ix4",
    "mechanarium",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def _bare_ctx(registry: Registry, cfg: GameConfig, state: GameState,
             from_room=None) -> DraftContext:
    """Build a DraftContext with no in-flight decks -- enough for _active_conditions."""
    return DraftContext(state, registry, cfg, Rng(0), set(), from_room)


ROTUNDA_ID = "rotunda"  # named here, not imported: the engine no longer knows it


def _electromagnet_entry(registry):
    """The Electro Magnet bias record, which carries its own union definition."""
    return next(e for e in registry.priority["category_biases"]
                if e.get("category") == "mechanical_or_rotunda")


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


def test_drafting_from_library_rare_override_no_longer_a_category_bias(registry):
    """The former "Rare Rooms (Library)" category_biases entry was deleted once
    its mechanism (a full rarity-table override, not a re-deal bias) was
    implemented directly in decks.py::roll_rarity -- it must not reappear here
    under any label, so a future edit can't accidentally revive the wrong
    mechanism alongside the correct one."""
    labels = {e.get("label") for e in registry.priority["category_biases"]}
    assert "Rare Rooms (Library)" not in labels


def test_electromagnet_absent_by_default_present_when_held(registry):
    """electromagnet is unreachable while the item isn't in inventory, and
    appears the instant a Powered Electromagnet is held (inventory-based, the
    same idiom as the Compass effect it shares a component with)."""
    cfg = GameConfig()
    state = GameState()
    ctx = _bare_ctx(registry, cfg, state)

    assert "electromagnet" not in _active_conditions(ctx)

    state.inventory["powered_electromagnet"] = 1
    assert "electromagnet" in _active_conditions(ctx)


def test_mechanical_or_rotunda_union_is_exactly_mechanical_rooms_plus_rotunda(registry):
    """category_matches("mechanical_or_rotunda") holds for exactly the eight
    wiki-pinned Mechanical rooms plus the Rotunda -- no more, no less -- mirroring
    how test_categories.py pins the eight rooms' is_category("mechanical")
    membership. The Rotunda itself must NOT carry "mechanical" (it is category
    "blueprint"; the union lives in the bias resolution, not the room data)."""
    expected = MECHANICAL_ROOM_IDS | {ROTUNDA_ID}
    entry = _electromagnet_entry(registry)
    matched = {r.id for r in registry.rooms if _category_matches(r, entry)}
    assert matched == expected

    rotunda = registry.by_id[ROTUNDA_ID]
    assert not rotunda.is_category("mechanical")
    assert _category_matches(rotunda, entry)


def test_category_matches_never_true_for_non_mechanical_non_rotunda_room(registry):
    """A room that is neither mechanical-category nor the Rotunda (the Closet)
    never matches "mechanical_or_rotunda", proving the union predicate is
    scoped rather than accidentally permissive."""
    entry = _electromagnet_entry(registry)
    assert not _category_matches(registry.by_id["closet"], entry)


def _sample_electromagnet_rate(registry: Registry, cfg: GameConfig, n_seeds: int,
                               electromagnet: bool) -> tuple[int, int]:
    """Deal N independent single-hand drafts at TARGET_CELL; return the count of
    dealt options that are a mechanical room or the Rotunda, and the total dealt."""
    hits = 0
    total = 0
    for seed in range(n_seeds):
        rng = Rng(seed)
        state = GameState()
        state.decks = build_decks(registry, cfg, rng)
        if electromagnet:
            state.inventory["powered_electromagnet"] = 1
        pending = deal_draft(state, registry, cfg, rng, set(), FROM_CELL, DIRECTION, TARGET_CELL)
        for opt in pending.options:
            total += 1
            room = registry.rooms[opt.room_idx]
            if room.is_category("mechanical") or room.id == ROTUNDA_ID:
                hits += 1
    return hits, total


@pytest.fixture(scope="module")
def electromagnet_counts(registry):
    """(hits_with, total_with, hits_without, total_without) over 3000 seeds each,
    computed once and shared by the tests below (module-scoped: expensive sampling)."""
    cfg = GameConfig()
    hits_with, total_with = _sample_electromagnet_rate(registry, cfg, 3000, electromagnet=True)
    hits_without, total_without = _sample_electromagnet_rate(
        registry, cfg, 3000, electromagnet=False)
    return hits_with, total_with, hits_without, total_without


def test_electromagnet_biases_toward_mechanical_rooms_and_rotunda(electromagnet_counts):
    """Holding a Powered Electromagnet raises the rate at which dealt options are
    a mechanical room or the Rotunda, versus an identical draft without it (3000
    seeds x 3 option slots = 9000 samples per condition; the bias fires at 40%
    chance, so a strong shift is expected, not a marginal one)."""
    hits_with, total_with, hits_without, total_without = electromagnet_counts

    rate_with = hits_with / total_with
    rate_without = hits_without / total_without

    assert rate_with > rate_without * 1.5, (
        f"electromagnet bias too weak: with={rate_with:.4f} without={rate_without:.4f}"
    )

    obs = [hits_with, total_with - hits_with]
    exp = [rate_without * total_with, (1 - rate_without) * total_with]
    _, p = stats.chisquare(obs, exp)
    assert p < 1e-6, (
        f"chi-square not significant: p={p:.2e} "
        f"(with={rate_with:.4f}, without={rate_without:.4f})"
    )


def test_electromagnet_absent_leaves_ordinary_draft_untouched(registry):
    """Without a held Powered Electromagnet, dealing at TARGET_CELL is
    byte-for-byte identical to the same seed run through a registry whose
    "mechanical_or_rotunda" category_biases entry has been deleted -- pinning
    that the bias entry's mere presence in the data has zero effect on ordinary
    draws, only its condition being active does."""
    import copy

    cfg = GameConfig()
    neutered = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    priority["category_biases"] = [
        e for e in priority["category_biases"] if e.get("condition") != "electromagnet"
    ]
    object.__setattr__(neutered, "priority", priority)

    for seed in range(200):
        rng_a = Rng(seed)
        state_a = GameState()
        state_a.decks = build_decks(registry, cfg, rng_a)
        pending_a = deal_draft(state_a, registry, cfg, rng_a, set(),
                               FROM_CELL, DIRECTION, TARGET_CELL)

        rng_b = Rng(seed)
        state_b = GameState()
        state_b.decks = build_decks(neutered, cfg, rng_b)
        pending_b = deal_draft(state_b, neutered, cfg, rng_b, set(),
                               FROM_CELL, DIRECTION, TARGET_CELL)

        rooms_a = [opt.room_idx for opt in pending_a.options]
        rooms_b = [opt.room_idx for opt in pending_b.options]
        assert rooms_a == rooms_b, f"seed {seed}: draw diverged with the bias entry removed"
