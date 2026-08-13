"""The Kennel: category-targeted draws can now select it, and digging
anywhere unlocks the doors of the room being dug.

draft.py::_apply_category_bias is the mechanism behind the Royal Scepter,
the Banner of the King, and every other category-biased re-deal
(draft.py:302 is the line that excludes non-matching cards). It works
entirely off Room.category, so a room whose category was a pool name
(the fixed studio_addition/outer decks) rather than a colour could never be
selected by it -- The Kennel is used here as the worked example, with a
hand-built single-card deck so the proof is deterministic rather than
statistical.

The digging half uses a real Game (not the bare duck-typed fake in
tests/test_digging.py) so special_items.dig_all's call into
Game._open_segment has a real door_state/door_version to mutate. Dig rooms
are placed directly via grid/placed_doors mutation (as test_locks.py's
helpers do), with their doors force-set to DOOR_LOCKED/DOOR_SECURITY so the
unlock is observed deterministically instead of depending on a lock-chance
roll.
"""

from __future__ import annotations

import copy
import dataclasses

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY, segment_key
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
    # is_gem must match deck_idx above, or the round's Free/Gem Draw gate
    # would hide the only card in the deck.
    return _apply_category_bias(ctx, placeholder, slot=1, cell=TARGET_CELL,
                                entry_dir=DIRECTION, exclude=set(), is_gem=not room.is_free)


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
    """The identical mechanism, with The Kennel's category set to
    "studio_addition" instead of "blueprint": the bias finds no matching
    card anywhere in the deck, so the original (placeholder) draw passes
    through unchanged -- the negative control showing the bias requires a
    genuine category match."""
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


# ------------------------------------------------------------- dig unlock


def _game(registry) -> Game:
    return Game(GameConfig(), seed=1, registry=registry)


def _place_dig_room(g: Game, room_id: str, cell: int, orientation: int):
    """Place a dig-spot room at ``cell`` with ``orientation``, without rolling locks."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = orientation
    return room


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


def test_dig_unlocks_locked_and_security_doors_with_kennel_placed(registry):
    """With the Kennel on the estate, digging a room's spots unlocks both a
    locked and a security doorway of that same room -- "This can also unlock
    security doors"."""
    g = _game(registry)
    si.grant(g.state, g.registry, "shovel", source="test")
    cell = 10
    _place_dig_room(g, "tomb", cell, E | W)
    _force_state(g, cell, E, DOOR_LOCKED)
    _force_state(g, cell, W, DOOR_SECURITY)
    g.placed_ids.add("the_kennel")

    si.dig_all(g, cell)

    assert g.door_state_of(cell, E) == DOOR_OPEN
    assert g.door_state_of(cell, W) == DOOR_OPEN


def test_dig_without_kennel_leaves_doors_locked(registry):
    """The identical dig, with no Kennel on the estate, leaves the room's
    locked and security doors untouched -- the effect is gated on the Kennel
    being drafted, not a blanket dig-unlocks-everything rule."""
    g = _game(registry)
    si.grant(g.state, g.registry, "shovel", source="test")
    cell = 10
    _place_dig_room(g, "tomb", cell, E | W)
    _force_state(g, cell, E, DOOR_LOCKED)
    _force_state(g, cell, W, DOOR_SECURITY)

    si.dig_all(g, cell)

    assert g.door_state_of(cell, E) == DOOR_LOCKED
    assert g.door_state_of(cell, W) == DOOR_SECURITY


def test_kennel_effect_works_without_entering_the_kennel(registry):
    """The Kennel only needs to be drafted, not entered: placed via the real
    Game._place_room pathway (never Game._enter'd), digging elsewhere still
    unlocks that room's doors."""
    g = _game(registry)
    si.grant(g.state, g.registry, "shovel", source="test")
    kennel = g.registry.by_id["the_kennel"]
    g._place_room(kennel, 5, kennel.door_mask)
    assert not g.state.entered[5], "setup: the Kennel must never be entered"

    cell = 10
    _place_dig_room(g, "tomb", cell, E)
    _force_state(g, cell, E, DOOR_LOCKED)

    si.dig_all(g, cell)

    assert g.door_state_of(cell, E) == DOOR_OPEN


def test_kennel_effect_repeats_across_rooms(registry):
    """The effect is unlimited: digging a second, unrelated room after the
    first also unlocks its doors, in the same run."""
    g = _game(registry)
    si.grant(g.state, g.registry, "shovel", source="test")
    g.placed_ids.add("the_kennel")

    cell_a, cell_b = 10, 20
    _place_dig_room(g, "tomb", cell_a, E)
    _force_state(g, cell_a, E, DOOR_LOCKED)
    _place_dig_room(g, "tomb", cell_b, E)
    _force_state(g, cell_b, E, DOOR_LOCKED)

    si.dig_all(g, cell_a)
    si.dig_all(g, cell_b)

    assert g.door_state_of(cell_a, E) == DOOR_OPEN
    assert g.door_state_of(cell_b, E) == DOOR_OPEN
