"""Classroom: category-targeted draws can now select it, plus its own
counts_as_drafting_room effect and the free redraws it unlocks.

See tests/rooms/test_the_kennel.py for the full write-up of the
category-bias technique (a hand-built single-card deck plus a forced-chance
category bias, so the proof is deterministic). Classroom already has a
rooms-list-keyed Schoolhouse bias (priority_draws.json's "Classrooms
(Schoolhouse)" entry); test_classroom_selectable_by_a_blueprint_category_targeted_draw
instead exercises the CATEGORY-keyed path (draft.py:302), which needed the
fix to reach it at all.

test_drawing_room.py's test_drawing_room_still_counts_as_a_drafting_room
already pins that Drawing Room's own counts_as_drafting_room effect adds to
the same counter Classroom reads -- that test is room-specific to Drawing
Room (it uses Classroom only to read the counter) and stays there. The tests
below are Classroom's own: that placing it raises the counter, and that
drafting FROM it actually grants the free redraws the counter promises.
"""

from __future__ import annotations

import copy

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S, W
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


def test_classroom_placement_raises_the_drafting_room_count():
    """Classroom's own effects list carries counts_as_drafting_room, so
    placing one raises state.drafting_room_count by 1 -- the flag Classroom
    itself later reads for its free redraws."""
    g = Game(GameConfig(), seed=0)
    classroom = g.registry.by_id["classroom"]
    assert [eff.tag for eff in classroom.effects] == ["counts_as_drafting_room"]
    count_before = g.state.drafting_room_count
    g._place_room(classroom, 7, N | S)
    assert g.state.drafting_room_count == count_before + 1


def test_drafting_from_inside_the_classroom_grants_free_redraws_equal_to_the_count():
    """Standing in a placed Classroom and opening a doorway seeds
    pending.redraws_left from state.drafting_room_count (Game._in_classroom_context,
    game.py:678) -- and a second Classroom placed anywhere raises the free
    redraws a fresh doorway draft gets, since the count is a running house
    total, not a per-room flag."""
    g = Game(GameConfig(), seed=0)
    classroom = g.registry.by_id["classroom"]
    g._place_room(classroom, 7, N | S | W)  # placed north of the Entrance Hall
    g.state.pos = 7  # stand inside it without walking (bypasses ON_ENTER)
    g.phase = Phase.NAVIGATE
    g.state.steps = 999

    pending = g.open_door(7, N)  # N from cell 7 goes deeper into the house (cell 12)
    assert pending.redraws_left == 1 == g.state.drafting_room_count

    # A second Classroom raises the house-wide count...
    g._place_room(classroom, 1, classroom.door_mask)
    assert g.state.drafting_room_count == 2
    # ...and a FRESH doorway draft (a new (cell, direction) key) picks it up.
    g.phase = Phase.NAVIGATE  # open_door left phase at DRAFTING; reset for a new doorway
    pending2 = g.open_door(7, W)
    assert pending2.redraws_left == 2
