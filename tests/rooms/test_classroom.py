"""Classroom: category-targeted draws can now select it.

See tests/rooms/test_the_kennel.py for the full write-up of this technique
(a hand-built single-card deck plus a forced-chance category bias, so the
proof is deterministic). Classroom already has a rooms-list-keyed Schoolhouse
bias (priority_draws.json's "Classrooms (Schoolhouse)" entry); this test
instead exercises the CATEGORY-keyed path (draft.py:302), which needed the
fix to reach it at all.
"""

from __future__ import annotations

import copy

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

DIRECTION = S
TARGET_CELL = 12


def _registry_with_forced_bias(registry: Registry, condition: str) -> Registry:
    """A copy of ``registry`` whose ``condition`` category-bias entry always fires."""
    neutered = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    for entry in priority["category_biases"]:
        if entry.get("condition") == condition:
            entry["chance"] = 1.0
    object.__setattr__(neutered, "priority", priority)
    return neutered


def test_classroom_selectable_by_a_blueprint_category_targeted_draw():
    """With Royal Scepter's scepter_blueprint bias forced to fire and a deck
    holding ONLY Classroom's card, the bias deals Classroom in place of the
    original draw -- unreachable unless its category really is "blueprint"."""
    registry = _registry_with_forced_bias(Registry.load(), "scepter_blueprint")
    classroom = registry.by_id["classroom"]
    assert classroom.category == "blueprint"

    state = GameState()
    state.decks = [DeckState() for _ in range(8)]
    deck_idx = classroom.rarity_idx * 2 + (0 if classroom.is_free else 1)
    state.decks[deck_idx] = DeckState(order=[classroom.idx])
    state.shops.scepter_color = "blueprint"
    ctx = DraftContext(state, registry, GameConfig(), Rng(0), set(), None)
    placeholder = registry.by_id["closet"]

    result = _apply_category_bias(ctx, placeholder, slot=1, cell=TARGET_CELL,
                                  entry_dir=DIRECTION, exclude=set())

    assert result.id == "classroom"
