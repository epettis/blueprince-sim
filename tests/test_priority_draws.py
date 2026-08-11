"""Southern Cross category-bias exclusions: Mechanarium, Chamber of Mirrors, upgrade variants.

The wiki's own selection query for the Southern Cross constellation is
``Room_Shape="4-way" AND NOT Type HOLDS "Upgrade" AND NOT Name="Mechanarium"
AND NOT Name="Chamber of Mirrors"`` (the Mechanarium page repeats the exclusion
verbatim: "It is also unaffected by the Southern Cross"). The raw
``"layout": "cross"`` selector in data/priority_draws.json matches all 19
cross-layout rooms, so this pins the ``exclude_rooms``/``exclude_upgrade_variants``
mechanism added to that entry and to the ``_apply_category_bias`` predicate in
engine/draft.py that reads it. The bias is otherwise inert (nothing sets
``state.southern_cross_active`` yet), so nothing else in the suite would catch
a mistake here.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

# Interior cell (rank 3, col 2) reached by moving south -- comfortably away
# from grid edges so cross-layout rooms are never ruled out by door-geometry
# legality (CLAUDE.md: 4-way rooms are edge-restricted).
TARGET_CELL = 12
DIRECTION = S


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def test_southern_cross_entry_carries_the_exclusions(registry):
    """The southern_cross_constellation entry in priority_draws.json excludes
    the Mechanarium and Chamber of Mirrors by id and flags every upgrade
    variant for exclusion, matching the wiki's query rather than the raw
    "layout": "cross" selector that would otherwise match all 19 cross rooms.
    """
    entry = next(e for e in registry.priority["category_biases"]
                 if e.get("condition") == "southern_cross_constellation")
    assert set(entry["exclude_rooms"]) == {"mechanarium", "chamber_of_mirrors"}
    assert entry["exclude_upgrade_variants"] is True


def test_southern_cross_bias_skips_excluded_rooms_and_selects_an_ordinary_cross_room(
    registry, monkeypatch
):
    """With southern_cross_active set and the bias roll forced to hit, a deck
    holding the Mechanarium, the Chamber of Mirrors and a cross-layout upgrade
    variant ahead of an ordinary cross room (Great Hall) is dealt past all
    three exclusions straight to the ordinary room -- pinning the actual
    selection set the exclusion mechanism produces, not just the entry's
    config.
    """
    monkeypatch.setattr(Rng, "chance", lambda self, label, p: True)

    cfg = GameConfig()
    state = GameState()
    state.decks = [DeckState() for _ in range(8)]
    mechanarium = registry.by_id["mechanarium"]
    chamber_of_mirrors = registry.by_id["chamber_of_mirrors"]
    upgrade_variant = registry.by_id["spare_great_hall__ix139"]
    great_hall = registry.by_id["great_hall"]
    assert upgrade_variant.layout == "cross" and upgrade_variant.variant_of is not None
    state.decks[0].order = [
        mechanarium.idx, chamber_of_mirrors.idx, upgrade_variant.idx, great_hall.idx,
    ]
    state.southern_cross_active = True

    ctx = DraftContext(state, registry, cfg, Rng(0), set(), None)
    original = registry.by_id["closet"]  # a non-cross room the bias should replace

    biased = _apply_category_bias(ctx, original, 1, TARGET_CELL, DIRECTION, set())

    assert biased.id == "great_hall"
