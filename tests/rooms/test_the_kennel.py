"""The Kennel: category-targeted draws can now select it.

draft.py::_apply_category_bias is the mechanism behind the Royal Scepter,
the Banner of the King, and every other category-biased re-deal
(draft.py:302 is the line that excludes non-matching cards). It works
entirely off Room.category, so a room whose category was a pool name
(the fixed studio_addition/outer decks) rather than a colour could never be
selected by it -- The Kennel is used here as the worked example, with a
hand-built single-card deck so the proof is deterministic rather than
statistical.
"""

from __future__ import annotations

import copy
import dataclasses

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

# A lone interior target cell (rank 3, col 2), reached moving south from rank
# 2 col 2 -- mirrors tests/test_category_biases.py's FROM_CELL/TARGET_CELL so
# door-geometry legality is never the reason a room is rejected here.
FROM_CELL = 7
DIRECTION = S
TARGET_CELL = 12


def _registry_with_forced_bias(registry: Registry, condition: str) -> Registry:
    """A copy of ``registry`` whose ``condition`` category-bias entry always
    fires (chance forced to 1.0), isolating the mechanism from the RNG roll
    that normally gates it (scepter_blueprint is 40% on a real Royal Scepter)."""
    neutered = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    for entry in priority["category_biases"]:
        if entry.get("condition") == condition:
            entry["chance"] = 1.0
    object.__setattr__(neutered, "priority", priority)
    return neutered


def _deal_only_card(registry: Registry, cfg: GameConfig, room, scepter_color: str):
    """Call the real _apply_category_bias with a deck holding ONLY ``room``'s
    card, so whichever room comes out is unambiguous -- no sampling needed."""
    state = GameState()
    state.decks = [DeckState() for _ in range(8)]
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
    state.decks[deck_idx] = DeckState(order=[room.idx])
    state.shops.scepter_color = scepter_color
    ctx = DraftContext(state, registry, cfg, Rng(0), set(), None)
    placeholder = registry.by_id["closet"]  # already-dealt filler; replaced if the bias hits
    return _apply_category_bias(ctx, placeholder, slot=1, cell=TARGET_CELL,
                                entry_dir=DIRECTION, exclude=set())


def test_kennel_selectable_by_a_blueprint_category_targeted_draw():
    """With Royal Scepter's scepter_blueprint bias forced to fire, The Kennel
    -- the only card in the deck -- is dealt in place of the original draw.
    This is unreachable unless its category really is "blueprint"."""
    registry = _registry_with_forced_bias(Registry.load(), "scepter_blueprint")
    kennel = registry.by_id["the_kennel"]
    assert kennel.category == "blueprint"

    result = _deal_only_card(registry, GameConfig(), kennel, "blueprint")

    assert result.id == "the_kennel"


def test_kennel_was_unreachable_under_its_old_pool_name_category():
    """The identical mechanism, with The Kennel's category reverted to
    "studio_addition" (its value before the fix): the bias finds no matching
    card anywhere in the deck and the original (placeholder) draw passes
    through unchanged -- this is the exact exclusion the fix removes."""
    registry = _registry_with_forced_bias(Registry.load(), "scepter_blueprint")
    kennel_idx = registry.by_id["the_kennel"].idx
    stale_kennel = dataclasses.replace(registry.rooms[kennel_idx], category="studio_addition")
    rooms = list(registry.rooms)
    rooms[kennel_idx] = stale_kennel
    object.__setattr__(registry, "rooms", tuple(rooms))
    object.__setattr__(registry, "by_id", {r.id: r for r in rooms})

    result = _deal_only_card(registry, GameConfig(), stale_kennel, "blueprint")

    assert result.id == "closet", (
        "no card in the deck matches category 'blueprint', so the bias must "
        "leave the placeholder draw untouched"
    )
