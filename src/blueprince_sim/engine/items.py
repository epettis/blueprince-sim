"""Item spawns and the luck system.

Each room has guaranteed items plus up to ``additional_max`` extra items.
Each extra item spawns with probability given by the luck curve (1.0 at
luck >= max_effect_at). Finding 2+ items in one room lowers luck. Fixed-
content rooms (additional_max == 0) are unaffected by luck.
"""

from __future__ import annotations

from .model import Registry, Room
from .rng import Rng
from .state import GameState

EXTRA_ITEM_TABLE = (
    # (item, weight) - what an "additional item" resolves to. The exact
    # distribution is not datamined; weights are community-informed estimates
    # (confidence: inferred), editable via items.json overrides later.
    ("coins", 40.0),
    ("key", 25.0),
    ("gem", 25.0),
    ("die", 10.0),
)


def luck_probability(state: GameState, registry: Registry) -> float:
    luck = registry.item_rules["luck"]
    lo, hi = luck["floor"], luck["max_effect_at"]
    if state.luck >= hi:
        return 1.0
    if state.luck <= lo:
        return 0.0
    return (state.luck - lo) / (hi - lo)


def grant_item(state: GameState, item: str, count: int, rng: Rng, registry: Registry) -> None:
    if item == "coins":
        pile = registry.item_rules["coins"]
        for _ in range(count):
            state.coins += rng.randint("coin_pile", pile["pile_min"], pile["pile_max"])
    elif item == "key":
        state.keys += count
    elif item == "gem":
        state.gems += count
    elif item == "die":
        state.dice += count
    elif item == "steps":
        state.steps += count
    state.items_found_log.append((item, count))


def roll_room_items(state: GameState, registry: Registry, room: Room, rng: Rng) -> int:
    """Spawn a room's items into the player's resources; returns items found."""
    found = 0
    for item, count in room.items.guaranteed:
        if item == "random":
            # Fixed COUNT of random items (Closet/Walk-In/Attic): luck-immune.
            for _ in range(count):
                weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
                idx = rng.roll_weighted("extra_item_kind", weights)
                grant_item(state, EXTRA_ITEM_TABLE[idx][0], 1, rng, registry)
                found += 1
        else:
            grant_item(state, item, count, rng, registry)
            found += 1
    p = luck_probability(state, registry)
    for _ in range(room.items.additional_max):
        if rng.chance("extra_item", p):
            weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
            idx = rng.roll_weighted("extra_item_kind", weights)
            grant_item(state, EXTRA_ITEM_TABLE[idx][0], 1, rng, registry)
            found += 1
    if found >= 2:
        state.luck += registry.item_rules["luck"]["penalty_two_plus_items"]
    return found
