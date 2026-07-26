"""Observation encoding."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces

from ..engine.game import ANTECHAMBER_CELL, Game, Phase
from ..engine.grid import DIRS, OPPOSITE, neighbor
from ..engine.locks import DOOR_LOCKED, DOOR_SECURITY, SECURITY_LEVELS
from ..engine.model import LAYOUTS
from ..engine.shops import SCEPTER_COLORS, current_shop_id

CATEGORIES = ("blueprint", "bedroom", "hallway", "green", "shop", "red",
              "blackprint", "studio_addition", "outer", "objective")
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
STAGES = ("week1", "week2", "late")
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
# room_idx+1, rarity+1, gem_cost, step_cost, layout, category, door_N, door_E,
# door_S, door_W, affordable, forced. The four door bits expose the drafted
# orientation as separate directional features so the policy can prefer, e.g.,
# north doors. Cost is split by currency: with the Hovel placed, gem costs are
# paid entirely in steps at 3:1, which a single scalar cannot express.
OPTION_FEATURES = 12
HOUSE_FLAGS = 13  # solarium, greenhouse, study, library, hovel, bedroom_bonus,
                  # red_negations, free_categories count, has_keycard,
                  # keycard_power_on, offline_unlocked, security_level,
                  # security_openable

# shop_stock resource code: 0 none, 1 coins, 2 keys, 3 gems, 4 dice, 5 food.
# Mapped from the stored entry's "grant" dict key (first key wins).
_GRANT_KEY_CODE = {"coins": 1, "keys": 2, "gems": 3, "dice": 4, "food": 5}

# Maximum row counts for the padded observation arrays (caps match the
# maximum real display length — asserted in tests).
SHOP_STOCK_ROWS = 6    # showroom with trophy = 5; cap at 6 for one free slot
TRADE_OFFER_ROWS = 8   # generous; 24 tradeables, real sessions hold far fewer

SCEPTER_COLOR_INDEX = {c: i for i, c in enumerate(SCEPTER_COLORS)}


def observation_space(n_rooms: int, n_items: int, n_recipes: int) -> spaces.Dict:
    """Dict observation space over the 9x5 (rank-major) grid; see :func:`encode`.

    Room ids are shifted by +1 so 0 means "empty cell"; -1 is the sentinel for
    unreachable/walled-off in the distance planes and for absent option slots.

    ``n_items`` is the number of special items in registry order (inventory
    vector length); ``n_recipes`` is the number of fabrication recipes.
    """
    return spaces.Dict({
        "grid_room": spaces.Box(0, n_rooms, shape=(9, 5), dtype=np.int16),
        "grid_doors": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # Walking distance from the player per cell (-1 empty/unreachable).
        "grid_dist": spaces.Box(-1, 99, shape=(9, 5), dtype=np.int16),
        # Optimistic distance to the Antechamber per cell: empty cells count
        # as passable, placed rooms only via their doors (-1 = walled off).
        "grid_ante_dist": spaces.Box(-1, 99, shape=(9, 5), dtype=np.int16),
        # 4-bit mask of frontier doorways (draftable doors) per cell.
        "grid_frontier": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # 4-bit masks of locked / security doorway segments per cell (both
        # sides of a segment carry the bit; opened doors drop out).
        "grid_locked": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "grid_security": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "grid_entered": spaces.Box(0, 1, shape=(9, 5), dtype=np.uint8),
        "player_pos": spaces.Discrete(45),
        "resources": spaces.Box(-1, 999, shape=(7,), dtype=np.int16),
        "options": spaces.Box(-1, max(n_rooms, 999), shape=(3, OPTION_FEATURES), dtype=np.int16),
        "phase": spaces.Discrete(3),
        "stage": spaces.Discrete(3),
        "house_flags": spaces.Box(0, 999, shape=(HOUSE_FLAGS,), dtype=np.int16),
        # deepest_rank, optimistic player->Antechamber distance (-1 if walled
        # off), Antechamber connected+walkable right now (0/1), outer_loc (0/1/2).
        "progress": spaces.Box(-1, 999, shape=(4,), dtype=np.int16),
        # Special-item observation keys (PR3 additions).
        # count per special item (registry order, 0 = not held)
        "inventory": spaces.Box(0, 99, shape=(n_items,), dtype=np.int16),
        # per-day item counters in documented order:
        # stopwatch_left, water, lockpick_attempts, lockpick_fails, shield_used,
        # trades_left, scepter_color_idx+1 (0=none), treasure_cell+1 (0=none),
        # treasure_dug, dining_room_served,
        # can_open_vault_box (0/1), can_open_parlor_box (0/1)
        "item_state": spaces.Box(-1, 999, shape=(12,), dtype=np.int16),
        # dig spots REMAINING per cell (placed rooms; 0 = empty or fully dug)
        "grid_dig": spaces.Box(0, 9, shape=(9, 5), dtype=np.uint8),
        # current shop's display entries, -1 rows when absent / not in a shop.
        # row: [item_idx+1 or 0, resource_code, price, sold_out, affordable]
        "shop_stock": spaces.Box(-1, 999, shape=(SHOP_STOCK_ROWS, 5), dtype=np.int16),
        # Trading Post trade offers (inside the post); -1 rows otherwise.
        # row: [give item idx+1, receive item idx+1 (0 = dice/sentinel)]
        "trade_offers": spaces.Box(-1, 999, shape=(TRADE_OFFER_ROWS, 2), dtype=np.int16),
        # buildable-now mask over fabrication recipes (registry order)
        "fabricate": spaces.Box(0, 1, shape=(n_recipes,), dtype=np.uint8),
        # unopened containers per cell (placed rooms only; 0 = empty or fully opened)
        "grid_containers": spaces.Box(0, 9, shape=(9, 5), dtype=np.uint8),
    })


def _cost_split(game: Game, room, opt) -> tuple[int, int]:
    """Effective cost as (gems, steps): the Hovel converts gems to steps 3:1."""
    cost = game._effective_cost(room, opt)
    if cost <= 0:
        return 0, 0
    if game.hovel_placed:
        return 0, 3 * cost
    return cost, 0


def _encode_shop_stock(game: Game) -> np.ndarray:
    """Encode the current shop's display into a (SHOP_STOCK_ROWS, 5) int16 array.

    Rows are -1 when absent (not in a shop or row index >= display length).
    Row layout: [item_idx+1 or 0, resource_code, price, sold_out, affordable].
    resource_code: 0=none, 1=coins, 2=keys, 3=gems, 4=dice, 5=food.
    item_idx is the registry index (0-based); 0 in column 0 means resource entry.
    """
    arr = np.full((SHOP_STOCK_ROWS, 5), -1, dtype=np.int16)
    display = game.shop_stock()
    if display is None:
        return arr
    # Build item id -> index map for registry lookup (cheap per-call dict comp)
    item_idx_map = {item.id: i for i, item in enumerate(game.registry.special.items)}
    # Corresponding stored entries for grant-key lookup (display index == stored index
    # for all real shops; showroom trophy is appended last with no stored entry).
    shop_id = current_shop_id(game)
    stored = game.state.shops.stock.get(shop_id, []) if shop_id else []

    for row_i, d in enumerate(display[:SHOP_STOCK_ROWS]):
        item_id = d.get("id")
        if d.get("kind") == "item":
            item_col = item_idx_map.get(item_id, -1) + 1  # +1: 0 = resource entry
            if item_col <= 0:
                item_col = 0
            resource_code = 0
        else:
            # Resource entry: look up grant key from the underlying stored entry
            item_col = 0
            resource_code = 0
            if row_i < len(stored):
                grant = stored[row_i].get("grant", {})
                for gkey, code in _GRANT_KEY_CODE.items():
                    if gkey in grant:
                        resource_code = code
                        break
        # Column 4 mirrors the BUY action mask: affordable AND not blocked
        # by an unmet container requirement (Cursed Coffers without a hammer).
        arr[row_i] = [item_col, resource_code, d["price"],
                      int(d["sold_out"]),
                      int(d["affordable"] and not d.get("blocked", False))]
    return arr


def _encode_trade_offers(game: Game) -> np.ndarray:
    """Encode Trading Post trade offers into a (TRADE_OFFER_ROWS, 2) int16 array.

    Rows are -1 when absent (outside the post). Row: [give_idx+1, receive_idx+1];
    receive is 0 only for dice — allowance_token and upgrade_disk are real
    registry items and encode as their index, so a tier-5 special offer is
    distinguishable from a dice offer.
    """
    arr = np.full((TRADE_OFFER_ROWS, 2), -1, dtype=np.int16)
    offers = game.trade_offers()
    if not offers:
        return arr
    item_idx_map = {item.id: i for i, item in enumerate(game.registry.special.items)}
    for row_i, offer in enumerate(offers[:TRADE_OFFER_ROWS]):
        give_col = item_idx_map.get(offer["give"], -1) + 1  # 1-based; 0 = unknown
        # "dice" is the only non-item terminal; the other graph sentinels
        # (allowance_token, upgrade_disk) resolve through the item map.
        receive_col = item_idx_map.get(offer["receive"], -1) + 1
        arr[row_i] = [give_col, receive_col]
    return arr


def encode(game: Game) -> dict:
    """Encode the live game into the Dict observation for the current phase.

    Grid planes are 9x5 rank-major. Locked/security bits are painted on BOTH
    cells of a doorway segment (and drop out once the door is opened). Option
    rows are -1 outside DRAFTING or for absent slots; a hidden (Archives
    mystery) option exposes only cost and affordability, not identity.
    """
    st = game.state
    grid_room = np.array(st.grid, dtype=np.int16).reshape(9, 5)
    grid_room += 1
    grid_doors = np.array(st.placed_doors, dtype=np.uint8).reshape(9, 5)
    grid_entered = np.array(st.entered, dtype=np.uint8).reshape(9, 5)

    grid_dist = np.array(game.distance_map(), dtype=np.int16).reshape(9, 5)
    grid_ante_dist = np.array(game.optimistic_distances(), dtype=np.int16).reshape(9, 5)
    grid_frontier = np.zeros((9, 5), dtype=np.uint8)
    if game.phase is not Phase.TERMINAL:
        for cell, d in game.frontier_doorways():
            grid_frontier[cell // 5, cell % 5] |= d

    grid_locked = np.zeros((9, 5), dtype=np.uint8)
    grid_security = np.zeros((9, 5), dtype=np.uint8)
    for (cell, d), seg in st.door_state.items():
        if seg == DOOR_LOCKED:
            plane = grid_locked
        elif seg == DOOR_SECURITY:
            plane = grid_security
        else:
            continue
        plane[cell // 5, cell % 5] |= d
        nb = neighbor(cell, d)
        plane[nb // 5, nb % 5] |= OPPOSITE[d]

    pending = st.pending
    redraws = pending.redraws_left if pending else 0
    resources = np.array(
        [st.steps, st.gems, st.keys, st.coins, st.dice, st.luck, redraws], dtype=np.int16)

    options = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    if game.phase is Phase.DRAFTING and pending is not None:
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            gem_cost, step_cost = _cost_split(game, room, opt)
            doors = tuple(int(bool(opt.orientation & d)) for d in DIRS)  # N,E,S,W
            if opt.hidden:
                # Archives mystery: identity and orientation concealed
                # (room_idx 0 = unknown, door bits 0), but the cost and
                # affordability stay visible and it is still selectable.
                options[opt.slot] = (0, 0, gem_cost, step_cost, -1, -1, 0, 0, 0, 0,
                                     int(game.affordable(room, opt)), 0)
                continue
            options[opt.slot] = (
                room.idx + 1,
                room.rarity_idx + 1,
                gem_cost,
                step_cost,
                LAYOUTS.index(room.layout),
                CAT_INDEX.get(room.category, 0),
                *doors,
                int(game.affordable(room, opt)),
                int(opt.forced),
            )

    house_flags = np.array([
        int(st.solarium_placed),
        int(st.greenhouse_placed),
        int(st.study_placed),
        int(st.library_placed),
        int(game.hovel_placed),
        game.bedroom_bonus,
        game.red_negations,
        len(game.free_categories),
        int(st.has_keycard),
        int(st.keycard_power_on),
        int(st.offline_unlocked),
        SECURITY_LEVELS.index(st.security_level),
        int(game.security_openable()),
    ], dtype=np.int16)

    ante_flat = grid_ante_dist.reshape(-1)
    progress = np.array([
        game.deepest_rank,
        int(ante_flat[st.pos]),
        int(grid_dist[ANTECHAMBER_CELL // 5, ANTECHAMBER_CELL % 5] > 0),
        st.outer_loc,
    ], dtype=np.int16)

    # --- Special-item observation keys (PR3) ---
    registry = game.registry
    n_items = len(registry.special.items)

    # inventory: count per item, registry order
    inventory = np.zeros(n_items, dtype=np.int16)
    for i, item in enumerate(registry.special.items):
        inventory[i] = st.inventory.get(item.id, 0)

    # item_state: 10 per-day counters in documented order
    special = st.special
    shops_state = st.shops
    trading = registry.shop_rules.trading
    trades_per_day = trading.get("trades_per_day", 20)
    trades_left = max(0, trades_per_day - shops_state.trades_done)
    scepter_col = (SCEPTER_COLOR_INDEX.get(shops_state.scepter_color, -1) + 1
                   if shops_state.scepter_color is not None else 0)
    treasure_col = special.treasure_cell + 1  # -1 -> 0 (sentinel = no map read)
    item_state = np.array([
        special.stopwatch_left,           # 0
        special.water,                    # 1
        special.lockpick_attempts,        # 2
        special.lockpick_fails,           # 3
        int(special.shield_used),         # 4
        trades_left,                      # 5
        scepter_col,                      # 6  scepter_color index+1; 0 = not activated
        treasure_col,                     # 7  treasure_cell+1; 0 = no map read today
        int(special.treasure_dug),        # 8
        int(special.dining_room_served),  # 9
        int(game.can_open_vault_box()),   # 10 vault deposit box openable right now (0/1)
        int(game.can_open_parlor_box()),  # 11 Parlor box openable right now (0/1)
    ], dtype=np.int16)

    # grid_dig: remaining dig spots per cell (placed rooms only)
    grid_dig = np.zeros((9, 5), dtype=np.uint8)
    for cell, room_idx in enumerate(st.grid):
        if room_idx >= 0:
            room = registry.rooms[room_idx]
            total = room.items.dig_spots
            already = special.dug.get(cell, 0)
            remaining = max(0, total - already)
            if remaining > 0:
                grid_dig[cell // 5, cell % 5] = remaining

    # grid_containers: unopened container count per cell
    grid_containers = np.zeros((9, 5), dtype=np.uint8)
    containers_data = registry.special.containers
    if containers_data:
        rooms_map = containers_data.get("rooms", {})
        for cell, room_idx in enumerate(st.grid):
            if room_idx >= 0:
                room = registry.rooms[room_idx]
                all_kinds = rooms_map.get(room.id, {})
                total = sum(all_kinds.values())
                already = special.opened_containers.get(cell, 0)
                remaining = max(0, total - already)
                if remaining > 0:
                    grid_containers[cell // 5, cell % 5] = remaining

    # shop_stock: current shop's display (SHOP_STOCK_ROWS x 5), -1 sentinel rows
    shop_stock_arr = _encode_shop_stock(game)

    # trade_offers: Trading Post offers (TRADE_OFFER_ROWS x 2), -1 sentinel rows
    trade_offers_arr = _encode_trade_offers(game)

    # fabricate: mask over recipes (registry.special.fabrication order)
    buildable = set(game.fabricate_options())
    fabricate = np.array(
        [1 if output in buildable else 0
         for _inputs, output in registry.special.fabrication],
        dtype=np.uint8,
    )

    return {
        "grid_room": grid_room,
        "grid_doors": grid_doors,
        "grid_dist": grid_dist,
        "grid_ante_dist": grid_ante_dist,
        "grid_frontier": grid_frontier,
        "grid_locked": grid_locked,
        "grid_security": grid_security,
        "grid_entered": grid_entered,
        "player_pos": st.pos,
        "resources": resources,
        "options": options,
        "phase": game.phase.value,
        "stage": STAGE_INDEX.get(st.stage, 2),
        "house_flags": house_flags,
        "progress": progress,
        "inventory": inventory,
        "item_state": item_state,
        "grid_dig": grid_dig,
        "grid_containers": grid_containers,
        "shop_stock": shop_stock_arr,
        "trade_offers": trade_offers_arr,
        "fabricate": fabricate,
    }
