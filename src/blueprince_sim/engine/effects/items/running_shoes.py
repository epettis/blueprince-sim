"""Running Shoes: on-grid moves waive their step cost once the player is far
enough (euclidean, in room-lengths) from the position where a step was last
lost while holding the shoes -- the first loss of the day only records that
position. Area-graph travel (game.py::travel_to) separately rolls one
independent activation chance per area node entered.
"""

from __future__ import annotations

import math

from .. import ItemHook, item_hook
from ...grid import col_of, neighbor, rank_of

_EFFECT_TAG = "free_move_interval"


def _effect(state, registry):
    """The item's ``_EFFECT_TAG`` effect record, or None if not held, or held
    but not carrying that effect."""
    if state.inventory.get("running_shoes", 0) <= 0:
        return None
    item = registry.special.by_id.get("running_shoes")
    return item.effect(_EFFECT_TAG) if item is not None else None


def _room_distance(cell_a: int, cell_b: int) -> float:
    """Euclidean distance between two grid cells, in room-lengths (1.0 = adjacent)."""
    dr = rank_of(cell_a) - rank_of(cell_b)
    dc = col_of(cell_a) - col_of(cell_b)
    return math.hypot(dr, dc)


@item_hook("running_shoes", ItemHook.MOVE_STEP_COST)
def _distance_move(state, registry, from_cell, direction, to_room):
    """Waives the step cost once the destination is far enough from the
    position where a step was last lost while holding the shoes -- unlike
    the other MOVE_STEP_COST items, this one always decides the outcome once
    held, never declining with None.

    ``state.special.moves_since_free`` doubles as the encoded reference
    position: 0 means no step has been lost yet today (the sentinel, since
    cell 0 is itself a legitimate anchor), otherwise the anchor cell is
    ``value - 1``.
    """
    e = _effect(state, registry)
    if e is None:
        return None
    threshold = e.param("distance_threshold", 2.2)
    to_cell = neighbor(from_cell, direction)
    anchor_code = state.special.moves_since_free
    if anchor_code == 0:
        state.special.moves_since_free = to_cell + 1
        return 1
    if _room_distance(anchor_code - 1, to_cell) >= threshold:
        state.special.moves_since_free = to_cell + 1
        return 0
    return 1


def area_arrival_steps_saved(game, route: tuple[str, ...], anchors) -> int:
    """Steps waived across one area-graph hop (``game.py::travel_to``), from
    ``route[0]`` to ``route[-1]``.

    Rolls once per node entered (``route[1:]``), independently, at that
    node's own activation chance -- entering a grid anchor (the house, the
    garage) never rolls, matching the wiki's scope of "anywhere outside the
    house". Returns 0 without rolling anything when the shoes are not held
    or carry no declared effect.
    """
    e = _effect(game.state, game.registry)
    if e is None:
        return 0
    default_chance = e.param("area_chance_default", 0.6)
    overrides = e.param("area_chance_overrides", {})
    saved = 0
    for node_id in route[1:]:
        if node_id in anchors:
            continue
        chance = overrides.get(node_id, default_chance)
        if game.rng.chance(f"running_shoes_area_{node_id}", chance):
            saved += 1
    return saved
