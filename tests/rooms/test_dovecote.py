"""Dovecote: category-targeted draws can now select it, plus its free-
rotation source only counts while it is a DRAWN option, not once placed.

See tests/rooms/test_the_kennel.py for the full write-up of the category-bias
technique (a hand-built single-card deck plus a forced-chance category bias,
so the proof is deterministic rather than statistical).

The rotation-while-drawn mechanism itself (spinning options, the per-hand
budget, the Ornate Compass / Rotunda / Dovecote precedence) is a system suite
in tests/test_rotation.py covering all three sources together -- that file
is left alone; test_dovecote_placed_but_not_drawn_grants_no_free_rotation
below adds the one Dovecote-specific case it doesn't cover: the distinction
between "placed" and "drawn" that Game.rotation_available's docstring calls
out (Rotunda grants rotation while PLACED; Dovecote only while DRAWN).
"""

from __future__ import annotations

import copy

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, DraftOption, GameState, PendingDraft

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


def test_dovecote_selectable_by_a_blueprint_category_targeted_draw():
    """With Royal Scepter's scepter_blueprint bias forced to fire and a deck
    holding ONLY Dovecote's card, the bias deals Dovecote in place of the
    original draw -- unreachable unless its category really is "blueprint"
    rather than the pool name "studio_addition"."""
    registry = _registry_with_forced_bias(Registry.load(), "scepter_blueprint")
    dovecote = registry.by_id["dovecote"]
    assert dovecote.category == "blueprint"

    state = GameState()
    state.decks = [DeckState() for _ in range(8)]
    deck_idx = dovecote.rarity_idx * 2 + (0 if dovecote.is_free else 1)
    state.decks[deck_idx] = DeckState(order=[dovecote.idx])
    state.shops.scepter_color = "blueprint"
    ctx = DraftContext(state, registry, GameConfig(), Rng(0), set(), None)
    placeholder = registry.by_id["closet"]

    result = _apply_category_bias(ctx, placeholder, slot=1, cell=TARGET_CELL,
                                  entry_dir=DIRECTION, exclude=set())

    assert result.id == "dovecote"


def test_dovecote_placed_but_not_drawn_grants_no_free_rotation():
    """A Dovecote sitting on the grid, with no Dovecote among the CURRENT
    hand's options, grants no rotation -- unlike the Rotunda, whose grant
    rides being placed rather than being drawn (Game.rotation_available's
    docstring states this distinction explicitly)."""
    g = Game(GameConfig(), seed=1)
    dovecote = g.registry.by_id["dovecote"]
    g._place_room(dovecote, 6, dovecote.door_mask)  # placed, off to one side
    assert "dovecote" in g.placed_ids

    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=DIRECTION, target_cell=TARGET_CELL)
    pd.options = [DraftOption(room_idx=troom.idx, orientation=troom.door_mask, gem_cost=0, slot=0)]
    g.state.pending = pd

    assert not g.rotation_available(), (
        "a placed (not drawn) Dovecote must not grant free rotation"
    )
