"""Item spawns and the luck system.

Each room has guaranteed items plus up to ``additional_max`` extra items. The
extra-item COUNT for a room's draft is rolled once from the published
item-count ladder (data/items.json's ``item_ladder``; wiki: Luck page,
"Luck effects" DataMinedBox), then clamped to ``additional_max``. Finding
items no longer lowers luck by itself -- high-luck ladder outcomes grow
``state.luck_penalty`` instead (see ``roll_ladder_count``). Fixed-content
rooms (additional_max == 0) are unaffected by luck.
"""

from __future__ import annotations

from . import special_items
from .model import Registry, Room
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


def _find_band(value: float, bands: list[dict]) -> dict:
    """First (only) ``item_ladder`` band whose ``[min, max]`` (either end may
    be absent, meaning unbounded) covers ``value``. Bands are contiguous and
    sorted by construction (validated by tools/validate_data.py)."""
    for band in bands:
        lo = band.get("min", float("-inf"))
        hi = band.get("max", float("inf"))
        if lo <= value <= hi:
            return band
    raise AssertionError(f"item_ladder: no band covers effective luck {value}")


def _chain_p_one(*, room46_reached: bool, day: int, veteran_mode: bool, chain: list[dict]) -> float:
    """Resolve the 5-10 luck band's first-match chain (wiki, verbatim order):

    "The chance to get 1 item is the first line of the above that applies:
    Room 46 reached -> 15%; Day 6+ -> 25%; Day 1 + Veteran Mode enabled by
    fast early drafts -> 23%; Veteran Mode enabled -> 15%; Day 3+ -> 20%;
    otherwise -> 18%."

    The "Day 1, Veteran Mode enabled by fast early drafts" row can never
    match here: ``GameConfig.veteran_mode`` (config.py) is a plain bool set
    at config time, with no notion of Veteran Mode having turned on MID-RUN
    from fast early drafts -- that sub-state is not representable in this
    sim, so the row is skipped and falls through to the next one (documented
    in items.json's item_ladder.meta.notes and the PR-A report).
    """
    for row in chain:
        cond = row["if"]
        if cond == "room46_reached":
            if room46_reached:
                return row["p_one_pct"] / 100.0
        elif cond == "day_gte":
            if day >= row["day"]:
                return row["p_one_pct"] / 100.0
        elif cond == "day1_veteran_by_fast_early_drafts":
            continue  # not representable -- see docstring above
        elif cond == "veteran_mode":
            if veteran_mode:
                return row["p_one_pct"] / 100.0
        elif cond == "otherwise":
            return row["p_one_pct"] / 100.0
    raise AssertionError("item_ladder: 5-10 chain fell through without an 'otherwise' row")


def _variable_mean(effective: float, variable_bands: list[dict]) -> float:
    """Analytic E[items] of the variable sub-table at ``effective`` luck."""
    band = _find_band(effective, variable_bands)
    if band["kind"] == "fixed":
        return float(band["items"])
    p3 = band["p_three_pct"] / 100.0
    return p3 * 3.0 + (1.0 - p3) * 2.0


def _resolve_variable(effective: float, variable_bands: list[dict], state: GameState, rng) -> int:
    """Roll the variable sub-table (wiki): <=10 -> 1 item; 11-16 -> 2 items,
    +1 Luck Penalty; 17+ -> 5% for 3 items (+3 penalty), 95% for 2 (+1
    penalty). Re-keyed on the SAME effective luck as the parent band. Adds
    the outcome's penalty delta to ``state.luck_penalty``.
    """
    band = _find_band(effective, variable_bands)
    if band["kind"] == "fixed":
        state.luck_penalty += band["penalty"]
        return band["items"]
    if rng.chance("luck_ladder_variable", band["p_three_pct"] / 100.0):
        state.luck_penalty += band["three_penalty"]
        return 3
    state.luck_penalty += band["two_penalty"]
    return 2


def roll_ladder_count(game) -> int:
    """Roll the published item-count ladder once for this draft's additional
    items; returns the raw count (BEFORE the ``additional_max`` clamp --
    ``roll_room_items`` clamps it). Adds any Luck Penalty the resolved
    band/outcome carries to ``state.luck_penalty``.

    Effective luck = ``state.luck`` + per-draft modifiers
    (``special_items.luck_bonus``: Rabbit's Foot / Lucky Purse) -
    ``state.luck_penalty``.
    """
    state, cfg, registry, rng = game.state, game.cfg, game.registry, game.rng
    ladder = registry.item_rules["item_ladder"]
    effective = state.luck + special_items.luck_bonus(state, registry) - state.luck_penalty
    band = _find_band(effective, ladder["bands"])
    kind = band["kind"]

    if kind == "flat":
        p_one = band["p_one_pct"] / 100.0
        return 1 if rng.chance("luck_ladder_outcome", p_one) else 0
    if kind == "chain":
        p_one = _chain_p_one(room46_reached=state.room46_reached, day=state.day,
                              veteran_mode=cfg.veteran_mode, chain=band["chain"])
        return 1 if rng.chance("luck_ladder_outcome", p_one) else 0
    if kind == "variable_mix":
        # 3-way split: [variable, 1 item, 0 items], in that order.
        weights = (band["p_variable_pct"], band["p_one_pct"],
                   100.0 - band["p_variable_pct"] - band["p_one_pct"])
        outcome = rng.roll_weighted("luck_ladder_outcome", weights)
        if outcome == 1:
            return 1
        if outcome == 2:
            return 0
        return _resolve_variable(effective, ladder["variable"], state, rng)
    if kind == "always_variable":
        return _resolve_variable(effective, ladder["variable"], state, rng)
    # kind == "fixed": 23-28 (3 items, +2 penalty) or 29+ (4 items, +3 penalty)
    state.luck_penalty += band["penalty"]
    return band["items"]


def expected_yields(room: Room, registry: Registry) -> dict[str, float]:
    """Static expected steps/keys/gems/coins/luck from drafting and entering
    ``room`` once.

    Computed from data alone (no simulation): guaranteed items, "random"
    guaranteed items via the EXTRA_ITEM_TABLE weights, an analytic mean of
    one item_ladder roll at the items.json day-start luck, plus flat
    ``grant`` and ``anti_luck`` effects. A "coins" item is a PILE; it
    contributes the pile-size midpoint. Conditional effects (per-category
    grants, set-to-value, shop pricing) are excluded - they depend on game
    state. The item_ladder's 5-10 luck chain also depends on game state
    (day, Room 46, Veteran Mode) that this function has no access to; it
    assumes day 1, Room 46 not yet reached, and Veteran Mode on (matching
    GameConfig.veteran_mode's own default) -- a fixed, documented baseline
    rather than a live read, same spirit as excluding conditional effects.
    """
    total_w = sum(w for _, w in EXTRA_ITEM_TABLE)
    p_item = {item: w / total_w for item, w in EXTRA_ITEM_TABLE}
    ladder = registry.item_rules["item_ladder"]
    day_start_luck = registry.item_rules["luck"]["day_start"]
    band = _find_band(day_start_luck, ladder["bands"])
    if band["kind"] == "flat":
        p_extra = band["p_one_pct"] / 100.0
    elif band["kind"] == "chain":
        p_extra = _chain_p_one(room46_reached=False, day=1, veteran_mode=True, chain=band["chain"])
    elif band["kind"] == "variable_mix":
        var_mean = _variable_mean(day_start_luck, ladder["variable"])
        p_extra = band["p_one_pct"] / 100.0 + (band["p_variable_pct"] / 100.0) * var_mean
    elif band["kind"] == "always_variable":
        p_extra = _variable_mean(day_start_luck, ladder["variable"])
    else:  # "fixed"
        p_extra = float(band["items"])
    pile = registry.item_rules["coins"]
    pile_avg = (pile["pile_min"] + pile["pile_max"]) / 2
    food_rules = registry.item_rules["food"]
    default_steps = food_rules["default_steps"]
    fruit_weights = food_rules["fruit_weights"]
    fruit_total_w = sum(fruit_weights.values())
    fruit_mean_steps = sum(
        w * food_rules["dishes"].get(dish_id, {}).get("steps", default_steps)
        for dish_id, w in fruit_weights.items()
    ) / fruit_total_w
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
            case "fruit":  # weighted mean of food.fruit_weights dish steps
                y["steps"] += count * fruit_mean_steps
            case "random":  # table-rolled items; count may be a fractional expectation
                y["keys"] += count * p_item["key"]
                y["gems"] += count * p_item["gem"]
                y["coins"] += count * p_item["coins"] * pile_avg

    for item, count in room.items.guaranteed:
        add(item, count)
    # p_extra is already the mean item count for the WHOLE room (one ladder
    # roll), not a per-slot probability -- clamp it to additional_max the
    # same way roll_room_items clamps the actual rolled count.
    add("random", min(p_extra, room.items.additional_max))
    for eff in room.effects:
        if eff.tag == "grant":
            res = eff.param("resource")
            if res in y:
                y[res] += eff.param("amount", 0)
        elif eff.tag == "anti_luck":
            y["luck"] -= eff.param("amount", 3)
    return y


def grant_item(game, item: str, count: int) -> None:
    """Add ``count`` of one item kind to the player's resources and log the pickup.

    "coins" means coin PILES: each of the ``count`` piles rolls its own size
    from the items.json pile_min..pile_max range. "coins_exact" means a
    literal coin amount (``count`` IS the payout, no pile roll) for rooms
    whose effect text states an exact figure (see rooms.json's
    ``items.guaranteed`` entries for e.g. the Vault) - it still routes through
    the same Coin Purse / Lucky Purse interest hook as "coins". "fruit" rolls
    ``count`` dishes from items.json's food.fruit_weights and eats each one
    immediately via ``special_items.eat_food``. Unknown item ids grant
    nothing but are still logged.
    """
    state = game.state
    registry = game.registry
    rng = game.rng
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
            special_items.eat_food(game, "banana", count)
            return
        case "fruit":
            # Each of count is its own weighted dish roll, eaten immediately;
            # eat_food logs each pickup, so no items_found_log append below.
            fruit_weights = registry.item_rules["food"]["fruit_weights"]
            dish_ids = sorted(fruit_weights)
            weights = tuple(fruit_weights[d] for d in dish_ids)
            for _ in range(count):
                idx = rng.roll_weighted("fruit_kind", weights)
                special_items.eat_food(game, dish_ids[idx], 1)
            return
    state.items_found_log.append((item, count))


def roll_extra_items(game, count: int) -> int:
    """Grant ``count`` items resolved through EXTRA_ITEM_TABLE, luck-immune.

    The same fixed-count random-item roll a room's own guaranteed "random"
    entries use below (Closet/Walk-In/Attic). Callers that owe a flat bonus
    on top of a room's own items -- the Closet-family adjacency bonuses,
    effects/rooms/closet.py -- reuse this rather than re-rolling their own
    table. Returns ``count``, matching roll_room_items's "items found"
    convention.
    """
    for _ in range(count):
        weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
        idx = game.rng.roll_weighted("extra_item_kind", weights)
        grant_item(game, EXTRA_ITEM_TABLE[idx][0], 1)
    return count


def roll_room_items(game, room: Room) -> int:
    """Spawn a room's items into the player's resources; returns items found."""
    state = game.state
    registry = game.registry
    rng = game.rng
    found = 0
    for item, count in room.items.guaranteed:
        if item == "random":
            # Fixed COUNT of random items (Closet/Walk-In/Attic): luck-immune.
            found += roll_extra_items(game, count)
        else:
            grant_item(game, item, count)
            found += 1
    extra = min(roll_ladder_count(game), room.items.additional_max)
    for _ in range(extra):
        # A luck proc may resolve to one of the room's special items
        # (docs/special-items-design.md spawn model) instead of a resource
        # from the table.
        if special_items.roll_special_spawn(state, registry, room, rng) is not None:
            found += 1
            continue
        weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
        idx = rng.roll_weighted("extra_item_kind", weights)
        grant_item(game, EXTRA_ITEM_TABLE[idx][0], 1)
        found += 1
    return found
