"""Shops, trades, fabrication, and cross-day discovery actions.

Commerce layer over the special-item system (docs/special-items-design.md,
"PR2"): per-shop stock rolled from data/shops.json on first entry, purchases
paid in coins, Trading Post tier trades, Workshop fabrication, plus the
discovery actions that feed the cross-day carry-over report (Royal Scepter
activation, vase smash, West Path chip).

Mirrors special_items.py's structure: a frozen rules object parsed at load, a
mutable ShopsState on GameState, and hook/action functions taking the ``game``
orchestrator duck-typed. state.py imports ShopsState from here; model.py
lazily imports the loader; this module imports nothing from state/game.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# NOTE: engine.items must stay a deferred import (items -> state -> shops
# would cycle at module load); special_items imports only model, so it's safe.
from . import special_items as si


# Scepter colors are floorplan categories; the bias entries in
# priority_draws.json are keyed "scepter_<color>".
SCEPTER_COLORS = ("blueprint", "green", "red", "bedroom", "hallway", "shop")


@dataclass(frozen=True)
class ShopsRegistry:
    sale: dict  # "sale" section: days on which prices halve (round up)
    trading: dict  # "trading" section: trades_per_day, dice_chance, t5_special_chance
    shops: dict  # room id -> shop table (stock entries, special_key roll, tiers)


def load_shops(data_dir: Path) -> ShopsRegistry:
    """Parse data/shops.json into the frozen rules object."""
    raw = json.loads((Path(data_dir) / "shops.json").read_text())
    return ShopsRegistry(
        sale=raw.get("sale", {}),
        trading=raw.get("trading", {}),
        shops=raw.get("shops", {}),
    )


@dataclass(slots=True)
class ShopsState:
    """Mutable per-day commerce/discovery bookkeeping, reset with GameState."""

    # shop room id -> rolled stock entries (list of dicts with mutable sold/limit state)
    stock: dict[str, list] = field(default_factory=dict)
    special_key_offer: str | None = None  # today's Locksmith special-key id
    special_key_sold: bool = False  # the once-per-day Locksmith special key was bought
    locksmith_robbed: bool = False  # Electromagnet robbery fired (key purchases disabled)
    trades_done: int = 0  # Trading Post trades used today
    # Fixed trade mapping for the day: item_id -> successor id (item or sentinel
    # "dice"/"allowance_token"/"upgrade_disk").  Rolled lazily on first use inside
    # the Trading Post.  Within each tier items form a shuffled cycle; a 1-item
    # cycle points to itself (self-trade = untradeable).  dice_chance% of
    # successors are replaced with "dice"; tier-5 may also yield allowance_token
    # or upgrade_disk.
    trade_graph: dict[str, str] = field(default_factory=dict)
    # True once _roll_trade_graph has been called for this episode.
    trade_graph_rolled: bool = False
    scepter_color: str | None = None  # activated color (category); None = not yet activated
    vase_smashed: bool = False  # Entrance Hall vase smashed today (discovery)
    chip_dug: bool = False  # West Path chip dug today (discovery)
    gift_unlocks: list[str] = field(default_factory=list)  # one-time Gift Shop buys today
    # Repellent bans added this day: room_id -> days remaining (always 7 when first added).
    # Merged into DayChain.repellent_bans on advance(); DayChain enforces the 3-ban cap
    # (oldest evicted when a 4th is added) and decrements all counters each day.
    # The dict here grows only within the current episode (multiple repellent uses allowed
    # up to the cap).
    repellent_bans: dict[str, int] = field(default_factory=dict)


# ------------------------------------------------------------------ stock & buy

def on_enter_shop(game, room) -> None:
    """First entry to a placed shop room: roll today's stock (seeded substream
    "shop_stock"), the Locksmith special-key offer, and fire the Electromagnet
    Locksmith robbery. Task B."""
    state = game.state
    shop_rules = game.registry.shop_rules
    # Once-per-room-per-day guard
    if room.id in state.shops.stock:
        return

    table = shop_rules.shops.get(room.id, {})

    match room.id:
        case "commissary":
            _roll_commissary(game, table)
        case "locksmith":
            _roll_locksmith(game, table)
        case "showroom":
            _roll_showroom(game, table)
        case "gift_shop":
            _roll_gift_shop(game, table)
        case "workshop":
            _roll_workshop(game)
        case "kitchen":
            _roll_kitchen(game, table)
        case _:
            # Simple shops (armory, bookshop, laundry_room, etc.):
            # availability rules for item entries; resources are always available.
            entries = []
            for raw in table.get("stock", []):
                entry = dict(raw)
                entry.setdefault("sold", 0)
                if entry.get("kind") == "item":
                    if not si._is_available(state, entry["id"], game.registry):
                        continue
                entries.append(entry)
            state.shops.stock[room.id] = entries

    # Electromagnet Locksmith robbery
    if room.id == "locksmith":
        for item_id, cnt in state.inventory.items():
            if cnt <= 0:
                continue
            item = game.registry.special.by_id.get(item_id)
            if item is None:
                continue
            e = item.effect("locksmith_rob")
            if e is not None:
                # Rob the locksmith: grant 24 keys
                n_keys = e.param("keys", 24)
                state.keys += n_keys
                state.items_found_log.append(("key", n_keys))
                state.shops.locksmith_robbed = True
                break


def _roll_commissary(game, table: dict) -> None:
    """Build the Commissary's daily stock: slots distinct available entries."""
    state = game.state
    registry = game.registry
    slots = table.get("slots", 4)
    raw_stock = table.get("stock", [])

    # Partition entries into primary and reserve
    primary = []
    reserve = []
    for raw in raw_stock:
        entry = dict(raw)
        entry.setdefault("sold", 0)
        if raw.get("reserve"):
            reserve.append(entry)
            continue
        # Check availability for item entries
        if raw.get("kind") == "item":
            if not si._is_available(state, raw["id"], registry):
                continue
        primary.append(entry)

    # Shuffle primary indices for deterministic random selection
    indices = list(range(len(primary)))
    game.rng.shuffle("shop_stock", indices)
    chosen = [primary[i] for i in indices[:slots]]

    # Fill remaining slots with reserve entries (in data order) if needed
    if len(chosen) < slots:
        for r_entry in reserve:
            if len(chosen) >= slots:
                break
            chosen.append(r_entry)

    state.shops.stock["commissary"] = chosen


def _roll_locksmith(game, table: dict) -> None:
    """Build the Locksmith's daily stock including the special-key offer."""
    state = game.state
    registry = game.registry

    entries = []
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        if raw.get("not_if_owned") and raw.get("kind") == "item":
            if si.has(state, raw["id"]):
                continue
        entries.append(entry)

    # Roll the special key (30/40/30 priority lists)
    special_key_data = table.get("special_key", {})
    rolls = special_key_data.get("rolls", [])
    price = special_key_data.get("price", 8)
    fallback = special_key_data.get("fallback", ["car_keys", "silver_key"])

    # Roll which priority list to use (cumulative chance)
    chosen_order = None
    total = 0
    roll_val = game.rng.uniform("shop_stock", 0.0, 100.0)
    for roll_entry in rolls:
        total += roll_entry["chance"]
        if roll_val < total:
            chosen_order = roll_entry["order"]
            break
    if chosen_order is None and rolls:
        chosen_order = rolls[-1]["order"]

    special_key_id = None
    if chosen_order:
        for kid in chosen_order:
            if si._is_available(state, kid, registry):
                special_key_id = kid
                break

    if special_key_id is None:
        # Walk fallback list
        for kid in fallback:
            # car_keys: must be available; silver_key: always ok (non-unique)
            if si._is_available(state, kid, registry):
                special_key_id = kid
                break
            # silver_key at end of fallback is non-unique so _is_available passes
        # If we still have nothing, force silver_key (non-unique; _is_available passes)
        if special_key_id is None:
            special_key_id = fallback[-1] if fallback else "silver_key"

    state.shops.special_key_offer = special_key_id
    # Append the synthetic special-key entry
    synthetic = {
        "id": special_key_id,
        "kind": "item",
        "price": price,
        "special_key": True,
        "sold": 0,
    }
    entries.append(synthetic)
    state.shops.stock["locksmith"] = entries


def _roll_showroom(game, table: dict) -> None:
    """Pick 2 from tier_a + 2 from tier_b avoiding already-owned items."""
    state = game.state
    registry = game.registry

    entries = []
    for tier_key in ("tier_a", "tier_b"):
        tier = table.get(tier_key, [])
        available = [
            dict(raw, sold=0, kind="item")
            for raw in tier
            if si._is_available(state, raw["id"], registry)
        ]
        # Shuffle for uniform selection
        game.rng.shuffle("shop_stock", available)
        entries.extend(available[:2])

    state.shops.stock["showroom"] = entries


def _roll_gift_shop(game, table: dict) -> None:
    """Build the Gift Shop's stock, filtering one-time purchases by config."""
    state = game.state
    cfg = game.cfg

    entries = []
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        # lunch_box: only when not already unlocked
        if raw.get("id") == "lunch_box" and cfg.lunch_box_unlocked:
            continue
        # cursed_coffers: only when not already unlocked
        if raw.get("id") == "cursed_coffers" and cfg.cursed_effigy_unlocked:
            continue
        entries.append(entry)

    state.shops.stock["gift_shop"] = entries


def _roll_workshop(game) -> None:
    """First-entry Workshop effect: grant one free component (or 5 coins fallback).

    Components are the union of all fabrication recipe input ids. One is
    selected uniformly from those still available (substream "shop_stock").
    Fallback: 5 coins when no component is available. The once-per-day guard
    is satisfied by storing an empty list under state.shops.stock["workshop"].
    """
    state = game.state
    registry = game.registry

    comp_ids = sorted(_component_ids(registry))  # sorted for determinism
    available = [c for c in comp_ids if si._is_available(state, c, registry)]

    if available:
        idx = game.rng.randint("shop_stock", 0, len(available) - 1)
        chosen = available[idx]
        si.grant(state, registry, chosen, source="workshop")
    else:
        # Fallback: grant 5 coins
        bonus = si.on_coins_granted(state, registry, 5)
        state.coins += 5 + bonus
        state.items_found_log.append(("coins", 5))

    state.shops.stock["workshop"] = []


def _roll_kitchen(game, table: dict) -> None:
    """Build the Kitchen's daily stock: static entries + one rolled special dish.

    Static stock (banana × limit 5, club_sandwich × limit 1) is always present.
    Exactly ONE special is selected from the ``special_roll`` list using a
    cumulative-chance roll (substream ``shop_stock``, same pattern as the
    Locksmith's priority roll). Each special carries ``kind``, ``grant``,
    ``price``, and ``limit`` in the data record.
    """
    state = game.state
    entries = []

    # Static entries (always offered)
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        entries.append(entry)

    # Roll the daily special (40% Bacon & Eggs / 30% Chef Salad / 30% Tomato Soup)
    specials = table.get("special_roll", [])
    if specials:
        roll_val = game.rng.uniform("shop_stock", 0.0, 100.0)
        total = 0.0
        chosen_special = specials[-1]  # fallback: last entry
        for s in specials:
            total += s["chance"]
            if roll_val < total:
                chosen_special = s
                break
        entry = {k: v for k, v in chosen_special.items() if k != "chance"}
        entry.setdefault("sold", 0)
        entries.append(entry)

    state.shops.stock["kitchen"] = entries


def current_shop_id(game) -> str | None:
    """The shop room the player can currently buy from, or None.

    Standing in a grid shop room (NAVIGATE phase), or inside the drafted
    outer shop (Trading Post/Toolshed etc., ``outer_loc == 2``). Task B."""
    from .game import Phase
    state = game.state
    if game.phase is not Phase.NAVIGATE:
        return None
    if state.outer_loc == 0:
        # On-grid: check current cell
        cell = state.pos
        if state.grid[cell] < 0:
            return None
        room = game.registry.rooms[state.grid[cell]]
        if room.category == "shop":
            return room.id
        return None
    elif state.outer_loc == 2:
        # Inside outer room
        outer_room = next(
            (r for r in game.outer_rooms if r.id in game.placed_ids), None
        )
        if outer_room is not None and outer_room.category == "shop":
            return outer_room.id
        return None
    return None


def stock_display(game, shop_id: str) -> list:
    """Resolved display entries for a given shop_id using the current game state.

    Position-independent: caller supplies ``shop_id`` rather than deriving it
    from ``state.pos``.  Returns [] when stock has not been rolled for this shop
    yet (first-entry rolling happens on_enter_shop; before that the shop's stock
    dict entry is absent).

    This is the shared pricing/sold-out logic consumed by both ``stock_for``
    (current-shop path, checks position first) and the action-mask walk-to
    re-entry check (needs to peek at arbitrary cell shops without moving there).
    """
    state = game.state
    if shop_id not in state.shops.stock:
        return []

    sale_days = game.registry.shop_rules.sale.get("days", [])
    is_sale = state.day in sale_days
    has_coupon = si._has_item_effect(state, game.registry, "shop_discount")

    stored = state.shops.stock[shop_id]
    display = []

    # For the showroom: check if trophy should be appended
    # Trophy appended dynamically once all stored showroom entries are sold
    showroom_trophy = None
    if shop_id == "showroom":
        shop_table = game.registry.shop_rules.shops.get("showroom", {})
        trophy_data = shop_table.get("trophy")
        if trophy_data and not si._is_available(state, trophy_data["id"], game.registry):
            # trophy already owned — never show it
            pass
        elif trophy_data:
            showroom_trophy = trophy_data

    for entry in stored:
        raw_price = entry["price"]
        # Sale day: ceil(price / 2)
        if is_sale:
            raw_price = math.ceil(raw_price / 2)
        # Coupon Book: max(0, price - 1)
        if has_coupon:
            raw_price = max(0, raw_price - 1)

        # Determine sold_out
        sold_out = False
        if entry.get("kind") == "item" and not entry.get("special_key"):
            # Item entries: sold when entry["sold"] > 0
            if entry.get("sold", 0) > 0:
                sold_out = True
        elif entry.get("special_key"):
            # Synthetic special key entry
            if state.shops.special_key_sold:
                sold_out = True
        else:
            # Resource entries with a limit
            limit = entry.get("limit")
            if limit is not None and entry.get("sold", 0) >= limit:
                sold_out = True

        # Locksmith robbery disables key and set_of_3_keys (not the special key)
        if shop_id == "locksmith" and state.shops.locksmith_robbed:
            if entry.get("id") in ("key", "set_of_3_keys") and not entry.get("special_key"):
                sold_out = True

        # Containers (Cursed Coffers) need their opener in hand to be buyable.
        requires = entry.get("requires_item")
        blocked = bool(requires) and not si.has(state, requires)

        display.append({
            "id": entry.get("id"),
            "kind": entry.get("kind"),
            "price": raw_price,
            "sold_out": sold_out,
            "affordable": state.coins >= raw_price,
            "blocked": blocked,
        })

    # Showroom: append trophy once all stored entries sold
    if shop_id == "showroom" and showroom_trophy:
        all_sold = all(d["sold_out"] for d in display)
        if all_sold:
            raw_price = showroom_trophy["price"]
            if is_sale:
                raw_price = math.ceil(raw_price / 2)
            if has_coupon:
                raw_price = max(0, raw_price - 1)
            display.append({
                "id": showroom_trophy["id"],
                "kind": "item",
                "price": raw_price,
                "sold_out": False,
                "affordable": state.coins >= raw_price,
                "blocked": False,
            })

    return display


def stock_for(game) -> list | None:
    """Today's purchasable entries for the shop the player stands in, with
    resolved prices (sale + Coupon Book applied) and sold/limit state.
    None when not in a shop or stock not yet rolled. Task B."""
    shop_id = current_shop_id(game)
    if shop_id is None:
        return None
    if shop_id not in game.state.shops.stock:
        return None
    return stock_display(game, shop_id)


def buy(game, index: int) -> None:
    """Buy stock entry ``index`` from the current shop: spend coins, grant the
    resource/item/container contents, update limits and one-time flags. Task B."""
    shop_id = current_shop_id(game)
    assert shop_id is not None, "not in a shop"
    state = game.state
    assert shop_id in state.shops.stock, "shop stock not rolled"

    display = stock_for(game)
    assert display is not None
    assert 0 <= index < len(display), f"index {index} out of range"
    d = display[index]
    assert not d["sold_out"], "entry is sold out"
    assert d["affordable"], "cannot afford this entry"
    assert not d.get("blocked"), "entry requires an item not held"

    price = d["price"]
    state.coins -= price

    # Determine which stored entry this is (trophy is appended last and has no stored entry)
    stored = state.shops.stock[shop_id]
    is_trophy = (shop_id == "showroom" and index == len(display) - 1
                 and index >= len(stored))

    if is_trophy:
        # Trophy purchase
        si.grant(state, game.registry, d["id"], source="shop")
        return

    entry = stored[index]

    match entry.get("kind"):
        case "resource":
            for resource, amount in entry.get("grant", {}).items():
                match resource:
                    case "food":
                        # The entry id names the dish (banana, club_sandwich...)
                        # so per-food step values and dynamic rules apply.
                        si.eat_food(state, game.registry, entry["id"], amount)
                        # inject_rooms dishes (Bacon & Eggs): add rooms to
                        # today's draft decks after eating.
                        dish = (game.registry.item_rules
                                .get("food", {})
                                .get("dishes", {})
                                .get(entry["id"], {}))
                        inject_ids = dish.get("inject_rooms", [])
                        if inject_ids:
                            game.inject_rooms(inject_ids)
                            # Also satisfy the gate-type draft conditions on those
                            # rooms so they can actually be placed (e.g. "breakfast"
                            # on morning_room — inject_rooms adds deck copies but
                            # the condition gate still blocks placement otherwise).
                            _GATE_CONDITIONS = frozenset({
                                "breakfast", "secret_garden_key",
                                "knight_chess_piece", "room8_key",
                            })
                            for rid in inject_ids:
                                room_obj = game.registry.by_id.get(rid)
                                if room_obj is not None:
                                    for cond in room_obj.draft_conditions:
                                        if cond in _GATE_CONDITIONS:
                                            state.special.extra_conditions.add(cond)
                    case "coins":
                        bonus = si.on_coins_granted(state, game.registry, amount)
                        state.coins += amount + bonus
                        state.items_found_log.append(("coins", amount))
                    case "keys":
                        state.keys += amount
                        state.items_found_log.append(("key", amount))
                    case "gems":
                        state.gems += amount
                        state.items_found_log.append(("gem", amount))
                    case "dice":
                        state.dice += amount
                        state.items_found_log.append(("die", amount))
            entry["sold"] = entry.get("sold", 0) + 1

        case "item" if entry.get("special_key"):
            si.grant(state, game.registry, entry["id"], source="shop")
            state.shops.special_key_sold = True

        case "item":
            si.grant(state, game.registry, entry["id"], source="shop")
            entry["sold"] = entry.get("sold", 0) + 1
            if entry["id"] == "lunch_box":  # one-time Gift Shop unlock
                state.shops.gift_unlocks.append("lunch_box_unlocked")

        case "container":
            # cursed_coffers: requires sledge_hammer, grants cursed_effigy
            requires = entry.get("requires_item")
            assert requires is None or si.has(state, requires), (
                f"container requires {requires} but it is not held"
            )
            grants = entry.get("grants_item")
            if grants:
                si.grant(state, game.registry, grants, source="shop")
            entry["sold"] = entry.get("sold", 0) + 1
            state.shops.gift_unlocks.append("cursed_effigy_unlocked")


# ------------------------------------------------------------------- trading

def _inside_trading_post(game) -> bool:
    """True when the player is currently inside the Trading Post outer room."""
    from .game import Phase
    state = game.state
    if game.phase is not Phase.NAVIGATE:
        return False
    if state.outer_loc != 2:
        return False
    outer_room = next((r for r in game.outer_rooms if r.id in game.placed_ids), None)
    return outer_room is not None and outer_room.id == "trading_post"


def _roll_trade_graph(game) -> None:
    """Build the day's fixed trade mapping and store it on state.shops.trade_graph.

    Called lazily on first use inside the Trading Post (substream "trade_graph").
    For each tier 1–5 the tradeable items (SpecialItem.tier == tier, id != "keycard")
    are shuffled into one cycle: ids[i] → ids[(i+1) % n].  A 1-item tier cycle
    produces a self-edge — that item cannot be traded (real game's self-trade rule).

    Then, per item independently:
      - dice_chance% → replace successor with "dice".
      - tier-5 only: t5_special_chance% (checked before dice) → replace with
        "allowance_token" or "upgrade_disk" (50/50).

    The graph is FIXED for the day; it is never re-rolled.  trades_per_day bounds
    any A→B→A milking loop at the trade() call site.
    """
    state = game.state
    registry = game.registry
    trading = registry.shop_rules.trading
    dice_chance = trading.get("dice_chance", 10) / 100.0
    t5_special_chance = trading.get("t5_special_chance", 50) / 100.0

    graph: dict[str, str] = {}

    for tier in range(1, 6):
        ids = sorted(
            it.id for it in registry.special.items
            if it.tier == tier and it.id != "keycard"
        )
        if not ids:
            continue
        game.rng.shuffle("trade_graph", ids)
        n = len(ids)
        for i, item_id in enumerate(ids):
            successor = ids[(i + 1) % n]
            match tier:
                case 5:
                    if game.rng.chance("trade_graph", t5_special_chance):
                        # Tier-5 special: allowance_token or upgrade_disk (50/50)
                        if game.rng.chance("trade_graph", 0.5):
                            successor = "allowance_token"
                        else:
                            successor = "upgrade_disk"
                    elif game.rng.chance("trade_graph", dice_chance):
                        successor = "dice"
                case _:
                    if game.rng.chance("trade_graph", dice_chance):
                        successor = "dice"
            graph[item_id] = successor

    state.shops.trade_graph = graph
    state.shops.trade_graph_rolled = True


_SENTINELS = frozenset({"dice", "allowance_token", "upgrade_disk"})


def _trade_target_ok(state, registry, item_id: str) -> bool:
    """Can ``item_id`` be handed over as a trade return right now?

    Deliberately looser than the spawn pipeline's availability: an item that
    already spawned today (``spawned_today``) is still a valid trade return,
    so an A→B→A cycle really can hand A back — the real-game milking loop —
    bounded only by trades_per_day. Blocked: held uniques, consumed-for-good
    ids, the keycard, and a second Stopwatch after one already ran today.
    """
    if item_id in si.PIPELINE_EXCLUDED or item_id in state.special.removed:
        return False
    item = registry.special.by_id.get(item_id)
    if item is None:
        return False
    if item.unique and state.inventory.get(item_id, 0) > 0:
        return False
    if item.effect("stopwatch") is not None and state.special.stopwatch_used:
        return False
    return True


def _resolve_trade(state, registry, give_id: str) -> str | None:
    """Walk the trade graph from trade_graph[give_id] to a grantable terminal.

    Returns the terminal string (item id or sentinel) if a trade can be made,
    or None if the item is untradeable (1-item cycle or full loop of held/
    unavailable nodes).

    Skips nodes that are currently held or not valid trade returns
    (:func:`_trade_target_ok`), following each skipped node's own successor.
    Sentinels always terminate. A visited set guards against infinite loops.
    """
    graph = state.shops.trade_graph
    start = graph.get(give_id)
    if start is None:
        return None
    if start == give_id:
        # Self-edge: untradeable
        return None

    visited: set[str] = {give_id}
    current = start
    while True:
        if current in _SENTINELS:
            return current
        if current in visited:
            # Full cycle with nothing grantable
            return None
        visited.add(current)
        # Skip if held (player already has it) or not a valid trade return
        if (state.inventory.get(current, 0) > 0
                or not _trade_target_ok(state, registry, current)):
            # Follow to next in chain
            nxt = graph.get(current)
            if nxt is None or nxt == current:
                return None
            current = nxt
        else:
            return current


def trade_offers(game) -> list:
    """Currently offered trades at the Trading Post (inside it, trades left).

    Returns [] when not inside the Trading Post or the daily trade limit is reached.
    One offer per distinct held tradeable item (SpecialItem.tier not None,
    id not "keycard") whose trade graph resolves to a grantable terminal.
    The ``receive`` field is exposed — the player can see what they will get
    before committing (matching real-game UI).

    The trade graph is rolled lazily on first call inside the post and is FIXED
    for the day.  trades_per_day bounds milking loops (e.g. an A→B→A 2-cycle can
    be exploited at most trades_per_day times total).

    Sorted by "give" for a stable action-space index.
    """
    if not _inside_trading_post(game):
        return []
    state = game.state
    trading = game.registry.shop_rules.trading
    trades_per_day = trading.get("trades_per_day", 3)
    if state.shops.trades_done >= trades_per_day:
        return []

    if not state.shops.trade_graph_rolled:
        _roll_trade_graph(game)

    offers = []
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        if item_id == "keycard":
            continue
        item = game.registry.special.by_id.get(item_id)
        if item is None:
            continue
        if item.tier is None:
            continue
        receive = _resolve_trade(state, game.registry, item_id)
        if receive is None:
            continue  # untradeable (self-cycle or full loop)
        offers.append({"give": item_id, "tier": item.tier, "receive": receive})

    offers.sort(key=lambda o: o["give"])
    return offers


def trade(game, give_id: str) -> None:
    """Trade one held ``give_id`` for what its graph node resolves to.

    The given item returns to the spawn pool (consumed=False so it is NOT added
    to state.special.removed).  Resolution is re-run at trade time (the
    just-removed give_id no longer counts as held, which may change skip-held
    resolution for other items, but give_id's own edge is fixed in the graph).
    Updates state.shops.trades_done.
    """
    offers = trade_offers(game)
    offer = next((o for o in offers if o["give"] == give_id), None)
    assert offer is not None, f"no active trade offer for {give_id!r}"

    state = game.state
    registry = game.registry

    from . import items as items_mod

    # Return the given item to the spawn pool (pool return: consumed=False)
    si.remove(state, give_id, consumed=False)

    # Re-resolve at trade time: give_id no longer held, may affect skip-held walks
    receive = _resolve_trade(state, registry, give_id)
    if receive is None:
        # Became untradeable between offer and trade (edge case); grant a die as fallback
        items_mod.grant_item(state, "die", 1, game.rng, registry)
    else:
        match receive:
            case "dice":
                items_mod.grant_item(state, "die", 1, game.rng, registry)
            case "allowance_token" | "upgrade_disk":
                si.grant(state, registry, receive, source="trade")
            case _:
                # Item id
                si.grant(state, registry, receive, source="trade")

    state.shops.trades_done += 1


# ---------------------------------------------------------------- fabrication

def _inside_workshop(game) -> bool:
    """True when the player stands in the Workshop during NAVIGATE phase."""
    from .game import Phase
    state = game.state
    if game.phase is not Phase.NAVIGATE:
        return False
    if state.outer_loc != 0:
        return False
    cell = state.pos
    if state.grid[cell] < 0:
        return False
    room = game.registry.rooms[state.grid[cell]]
    return room.id == "workshop"


def _component_ids(registry) -> frozenset[str]:
    """All item ids that appear as inputs in any fabrication recipe."""
    ids: set[str] = set()
    for inputs, _output in registry.special.fabrication:
        ids.update(inputs)
    return frozenset(ids)


def fabricate_options(game) -> list[str]:
    """Contraption ids buildable from the CURRENT inventory: all recipe
    inputs held and the output still available. Sorted for determinism.

    A pure query, valid anywhere — so a policy can see that walking to the
    Workshop would, say, turn a Lock Pick Kit + Metal Detector into a Pick
    Sound Amplifier. Actually building (:func:`fabricate`) requires standing
    in the Workshop. Recomputed live from the inventory, so building one
    contraption immediately drops any other recipe that shared a consumed
    component (Power Hammer eats the Battery Pack a Jack Hammer needed).
    """
    state = game.state
    registry = game.registry

    results = []
    for inputs, output in registry.special.fabrication:
        if all(si.has(state, inp) for inp in inputs):
            if si._is_available(state, output, registry):
                results.append(output)

    results.sort()
    return results


def fabricate(game, output_id: str) -> None:
    """Consume the recipe inputs and grant the contraption.

    Inputs are consumed for good (consumed=True: they enter state.special.removed
    and never respawn). Asserts the player is in the Workshop and the output is
    in fabricate_options.
    """
    assert _inside_workshop(game), "must stand in the Workshop to fabricate"
    options = fabricate_options(game)
    assert output_id in options, f"{output_id!r} is not a current fabrication option"

    state = game.state
    registry = game.registry

    # Find the recipe
    recipe_inputs = None
    for inputs, output in registry.special.fabrication:
        if output == output_id:
            recipe_inputs = inputs
            break
    assert recipe_inputs is not None

    # Consume each input permanently
    for inp in recipe_inputs:
        si.remove(state, inp, consumed=True)

    # Grant the contraption
    si.grant(state, registry, output_id, source="fabricate")


# ------------------------------------------------- discoveries & carry-over

def on_day_start(game) -> None:
    """Reset-time carry-over grants: Royal Scepter (royal_scepter_found),
    Entrance Hall microchip (entrance_vase_broken). Task D."""
    cfg = game.cfg
    state = game.state
    registry = game.registry

    # Royal Scepter: granted at day start when discovered via carry-over.
    # The Entrance Hall is pre-entered at reset, so this is the daily spawn moment.
    if cfg.royal_scepter_found:
        si.grant(state, registry, "royal_scepter", source="day_start")

    # Entrance Hall vase chip: granted at day start when the vase was previously broken.
    if cfg.entrance_vase_broken:
        si.grant(state, registry, "microchip", source="day_start")


def on_doorstep(game) -> None:
    """Reaching the outer-area doorstep: grant the West Path chip when
    ``outer_chip_dug``, or auto-dig it the first time while holding a digging
    tool (records the discovery). Task D."""
    cfg = game.cfg
    state = game.state
    registry = game.registry

    if cfg.outer_chip_dug:
        # Already discovered carry-over: grant the chip at the doorstep.
        si.grant(state, registry, "microchip", source="doorstep")
        return

    # First-time discovery: auto-dig if holding any digging tool.
    # Reuse dig_all's tool detection logic (same _DIG_PRIORITY as dig_all).
    _DIG_PRIORITY = ("jack_hammer", "detector_shovel", "shovel")
    has_dig_tool = any(si.has(state, tool_id) for tool_id in _DIG_PRIORITY)
    if has_dig_tool and not state.shops.chip_dug:
        si.grant(state, registry, "microchip", source="doorstep_dig")
        state.shops.chip_dug = True


def can_activate_scepter(game) -> bool:
    """Royal Scepter held, not yet activated today, NAVIGATE phase. Task D."""
    from .game import Phase

    if game.phase is not Phase.NAVIGATE:
        return False
    if not si.has(game.state, "royal_scepter"):
        return False
    if game.state.shops.scepter_color is not None:
        return False
    return True


def activate_scepter(game, color: str) -> None:
    """Pick the scepter color for the day (irrevocable): floorplans of that
    category become more common via the scepter_<color> category bias. Task D."""
    assert can_activate_scepter(game), "scepter cannot be activated right now"
    assert color in SCEPTER_COLORS, f"invalid scepter color {color!r}; must be one of {SCEPTER_COLORS}"
    game.state.shops.scepter_color = color


def can_smash_vase(game) -> bool:
    """Standing in the Entrance Hall with a smash-capable item, vase intact. Task D."""
    from .game import Phase

    if game.phase is not Phase.NAVIGATE:
        return False
    if game.cfg.entrance_vase_broken:
        return False
    if game.state.shops.vase_smashed:
        return False
    if game.state.outer_loc != 0:
        return False
    # Must be standing in the Entrance Hall
    cell = game.state.pos
    if game.state.grid[cell] < 0:
        return False
    room = game.registry.rooms[game.state.grid[cell]]
    if room.id != "entrance_hall":
        return False
    # Must hold a smash-capable item (any item with the "smash" effect tag)
    return si._has_item_effect(game.state, game.registry, "smash")


def smash_vase(game) -> None:
    """Smash the west-side vase: grant a microchip, record the discovery. Task D."""
    assert can_smash_vase(game), "cannot smash vase right now"

    si.grant(game.state, game.registry, "microchip", source="vase_smash")
    game.state.shops.vase_smashed = True


# Rooms that can never be banned by the Repellent (wiki-documented exclusions):
# the Entrance Hall (the day always starts here), the Antechamber (the win
# condition), and Room 46 (the special secret room).  Room ids are stable
# snake_case identifiers matching rooms.json.
_REPELLENT_ILLEGAL_TARGETS = frozenset({"entrance_hall", "antechamber", "room_46"})

# Maximum number of simultaneously active Repellent bans (wiki: max 3).
_REPELLENT_MAX_BANS = 3

# Days a Repellent ban lasts (wiki: 7 days).
_REPELLENT_BAN_DAYS = 7


def can_use_repellent(game) -> bool:
    """Repellent usable: held at least one, NAVIGATE phase, on the grid.

    The target room is the room the player currently stands in; validity
    (not an illegal target) is checked in use_repellent().
    """
    from .game import Phase
    return (
        game.phase is Phase.NAVIGATE
        and game.state.outer_loc == 0
        and si.has(game.state, "repellent")
    )


def use_repellent(game, room_id: str) -> None:
    """Consume one Repellent and ban ``room_id`` from the draft pool for 7 days.

    Rules enforced:
    - The player must hold at least one Repellent (consumed, not pool-returned).
    - ``room_id`` must not be entrance_hall, antechamber, or room_46 (wiki
      exclusions — these rooms always appear in the house).
    - The global cap of 3 active bans is enforced by DayChain on advance(); a
      4th ban added here is recorded on ShopsState and DayChain will evict the
      oldest on the next advance().

    The ban takes effect on the NEXT day's draft pool (GameConfig.banned_rooms
    fed by DayChain.next_config()).  Today's already-built decks are unaffected.
    """
    assert can_use_repellent(game), "no Repellent held or not in navigate phase"
    assert room_id not in _REPELLENT_ILLEGAL_TARGETS, (
        f"{room_id!r} cannot be banned (entrance_hall/antechamber/room_46 are excluded)"
    )
    # The room must exist in the registry
    assert game.registry.by_id.get(room_id) is not None, (
        f"unknown room id {room_id!r}"
    )

    si.remove(game.state, "repellent", consumed=True)
    # Record or refresh the ban for this room (7 days from now)
    game.state.shops.repellent_bans[room_id] = _REPELLENT_BAN_DAYS


def carryover(game) -> dict:
    """Today's cross-day discoveries for a multi-day wrapper.

    Returns a dict with:
    - bool keys (GameConfig flag names): True when discovered today or already
      configured.  False values signal "still not discovered" — DayChain ignores
      them for bool flags (accumulative: once True, always True within an attempt).
    - ``"starting_items"``: sorted list of item ids that persist into tomorrow
      (permanent/until_used self-persisters + Coat Check + Moon Pendant carry).
    - ``"banned_rooms"``: dict room_id -> days_remaining for NEW Repellent bans
      added THIS day only.  DayChain already owns the old bans from previous days
      and decrements them itself; this key carries only new bans to merge in.

    DayChain.advance() handles the non-bool keys explicitly (merging/decrementing
    bans, storing starting_items).  Task D.
    """
    from . import special_items as si_mod
    cfg = game.cfg
    state = game.state

    # Item persistence carry
    carried_items = si_mod.end_of_day_carry(state, game.registry, game.rng)

    return {
        "lunch_box_unlocked": (
            cfg.lunch_box_unlocked or "lunch_box_unlocked" in state.shops.gift_unlocks
        ),
        "cursed_effigy_unlocked": (
            cfg.cursed_effigy_unlocked or "cursed_effigy_unlocked" in state.shops.gift_unlocks
        ),
        "entrance_vase_broken": cfg.entrance_vase_broken or state.shops.vase_smashed,
        "outer_chip_dug": cfg.outer_chip_dug or state.shops.chip_dug,
        "royal_scepter_found": cfg.royal_scepter_found,
        # The Garage car's Upgrade Disk is a one-time find for the whole save.
        "garage_car_used_before": cfg.garage_car_used_before or state.special.garage_car_opened,
        "starting_items": carried_items,              # list[str]: item ids for next starting_items
        "banned_rooms": dict(state.shops.repellent_bans),  # dict[str, int]: new bans from today
    }
