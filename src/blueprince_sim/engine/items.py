"""Item spawns and the luck system.

Each room has guaranteed items plus up to ``additional_max`` extra items.
Each extra item spawns with probability given by the luck curve (1.0 at
luck >= max_effect_at). Finding 2+ items in one room lowers luck. Fixed-
content rooms (additional_max == 0) are unaffected by luck.
"""

from __future__ import annotations

from . import special_items
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


def expected_yields(room: Room, registry: Registry) -> dict[str, float]:
    """Static expected steps/keys/gems/coins/luck from drafting and entering
    ``room`` once.

    Computed from data alone (no simulation): guaranteed items, "random"
    guaranteed items via the EXTRA_ITEM_TABLE weights, luck-rolled additional
    items at the day-start luck probability, plus flat ``grant`` and
    ``anti_luck`` effects. A "coins" item is a PILE; it contributes the
    pile-size midpoint. Conditional effects (per-category grants,
    set-to-value, shop pricing) are excluded - they depend on game state.
    """
    total_w = sum(w for _, w in EXTRA_ITEM_TABLE)
    p_item = {item: w / total_w for item, w in EXTRA_ITEM_TABLE}
    luck = registry.item_rules["luck"]
    p_extra = min(1.0, max(0.0, (luck["day_start"] - luck["floor"])
                           / (luck["max_effect_at"] - luck["floor"])))
    pile = registry.item_rules["coins"]
    pile_avg = (pile["pile_min"] + pile["pile_max"]) / 2
    y = {"steps": 0.0, "keys": 0.0, "gems": 0.0, "coins": 0.0, "luck": 0.0}

    def add(item: str, count: float) -> None:
        match item:
            case "key":
                y["keys"] += count
            case "gem":
                y["gems"] += count
            case "steps":
                y["steps"] += count
            case "coins":  # coin piles, each rolling pile_min..pile_max
                y["coins"] += count * pile_avg
            case "coins_exact":  # a literal coin amount, no pile roll (see grant_item)
                y["coins"] += count
            case "random":  # table-rolled items; count may be a fractional expectation
                y["keys"] += count * p_item["key"]
                y["gems"] += count * p_item["gem"]
                y["coins"] += count * p_item["coins"] * pile_avg

    for item, count in room.items.guaranteed:
        add(item, count)
    add("random", room.items.additional_max * p_extra)
    for eff in room.effects:
        if eff.tag == "grant":
            res = eff.param("resource")
            if res in y:
                y[res] += eff.param("amount", 0)
        elif eff.tag == "anti_luck":
            y["luck"] -= eff.param("amount", 3)
    return y


def luck_probability(state: GameState, registry: Registry) -> float:
    """Spawn chance of each additional (luck-rolled) item at the current luck.

    Linear ramp from 0.0 at the items.json luck floor to 1.0 at max_effect_at.
    """
    luck = registry.item_rules["luck"]
    lo, hi = luck["floor"], luck["max_effect_at"]
    # Held lucky charms add to EFFECTIVE luck only, so losing the charm
    # (Lost & Found) takes its bonus with it.
    effective = state.luck + special_items.luck_bonus(state, registry)
    if effective >= hi:
        return 1.0
    if effective <= lo:
        return 0.0
    return (effective - lo) / (hi - lo)


def grant_item(state: GameState, item: str, count: int, rng: Rng, registry: Registry) -> None:
    """Add ``count`` of one item kind to the player's resources and log the pickup.

    "coins" means coin PILES: each of the ``count`` piles rolls its own size
    from the items.json pile_min..pile_max range. "coins_exact" means a
    literal coin amount (``count`` IS the payout, no pile roll) for rooms
    whose effect text states an exact figure (see rooms.json's
    ``items.guaranteed`` entries for e.g. the Vault) - it still routes through
    the same Coin Purse / Lucky Purse interest hook as "coins". Unknown item
    ids grant nothing but are still logged.
    """
    match item:
        case "coins" | "coins_exact":
            if item == "coins_exact":
                got = count
            else:
                pile = registry.item_rules["coins"]
                got = 0
                for _ in range(count):
                    got += rng.randint("coin_pile", pile["pile_min"], pile["pile_max"])
            # Coin Purse / Lucky Purse interest rides every coin pickup.
            state.coins += got + special_items.on_coins_granted(state, registry, got)
        case "key":
            state.keys += count
        case "gem":
            state.gems += count
        case "die":
            state.dice += count
        case "steps":
            state.steps += count
        case "food":
            # Food restores steps; per-dish values and Salt Shaker / Silver
            # Spoon modifiers are eat_food's concern (it logs each item).
            special_items.eat_food(state, registry, "banana", count)
            return
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
            # A luck proc may resolve to one of the room's special items
            # (docs/special-items-design.md spawn model) instead of a
            # resource from the table.
            if special_items.roll_special_spawn(state, registry, room, rng) is not None:
                found += 1
                continue
            weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
            idx = rng.roll_weighted("extra_item_kind", weights)
            grant_item(state, EXTRA_ITEM_TABLE[idx][0], 1, rng, registry)
            found += 1
    if found >= 2:
        state.luck += registry.item_rules["luck"]["penalty_two_plus_items"]
    return found
