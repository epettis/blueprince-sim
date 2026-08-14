"""Observation encoding."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces

from ..engine.draft import COLOUR_CATEGORIES
from ..engine.effects.rooms import shrine
from ..engine.game import ANTECHAMBER_CELL, Game, Phase
from ..engine.grid import DIRS, OPPOSITE, neighbor
from ..engine.locks import DOOR_LOCKED, DOOR_SEALED, DOOR_SECURITY, SECURITY_LEVELS
from ..engine.model import LAYOUTS
from ..engine.shops import SCEPTER_COLORS, current_shop_id
from ..engine.special_items import SIGIL_REALMS, _container_kinds_at
from ..engine.upgrades import all_slot_ids, upgraded_slots
from .actions import _build_area_node_ids, _build_axe_target_ids, _build_mechanical_room_ids
from .multiday import DayChain

CATEGORIES = ("blueprint", "bedroom", "hallway", "green", "shop", "red",
              "blackprint", "studio_addition", "outer", "objective")
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
STAGES = ("week1", "week2", "late")
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
# room_idx+1, rarity+1, gem_cost, step_cost, layout, category, door_N, door_E,
# door_S, door_W, affordable, forced, archived. The four door bits expose the
# drafted orientation as separate directional features so the policy can
# prefer, e.g., north doors. Cost is split by currency: with the Hovel placed,
# gem costs are paid entirely in steps at 3:1, which a single scalar cannot
# express. archived is distinct from a hidden option's concealment: it marks
# the one floorplan an active Archives archived this hand (archived implies
# hidden, never the converse).
OPTION_FEATURES = 13
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

# Cap on the encoded disks_held count. Disks are unique items, so the true
# maximum is the number of "upgrade_disk_*" records in the registry (16: the 7
# original + the 8 in-grid disks (The Foundation added last) + mine_south's
# bespoke arrival grant). Declared as Discrete(MAX_DISKS_HELD + 1) and used as
# the encode clamp, so the space bound and the clamp cannot drift apart.
# tests/test_in_grid_disks.py pins this against the registry's actual disk count.
MAX_DISKS_HELD = 16

SCEPTER_COLOR_INDEX = {c: i for i, c in enumerate(SCEPTER_COLORS)}


def observation_space(n_rooms: int, n_items: int, n_recipes: int,
                      n_area_nodes: int = 38,
                      n_carryover: int = len(DayChain._CARRYOVER_KEYS),
                      n_slots: int = 16,
                      n_axe_targets: int = 48,
                      n_mechanical_rooms: int = 8,
                      n_planetarium_planets: int = 5) -> spaces.Dict:
    """Dict observation space over the 9x5 (rank-major) grid; see :func:`encode`.

    Room ids are shifted by +1 so 0 means "empty cell"; -1 is the sentinel for
    unreachable/walled-off in the distance planes and for absent option slots.

    ``n_items`` is the number of special items in registry order (inventory
    vector length); ``n_recipes`` is the number of fabrication recipes.
    ``n_area_nodes`` is the number of area-graph nodes (default 36); the actual
    count is passed in from the registry so the space cannot drift from areas.json.
    ``n_carryover`` is the number of carry-over bool flags (``len(DayChain._CARRYOVER_KEYS)``),
    always passed from ``BluePrinceEnv`` so the space and encoder stay in sync.
    ``n_axe_targets`` is the number of Axe-axeable floorplan families
    (``len(actions._build_axe_target_ids(registry))``, 48 today), the same
    registry-derived-but-defaulted convention as ``n_slots``.
    ``n_mechanical_rooms`` is the number of Mechanical Room ids
    (``len(actions._build_mechanical_room_ids(registry))``, 8 today), the
    same convention.
    ``n_planetarium_planets`` is the number of Telescope-in-Planetarium
    planets (``len(registry.special.planetarium_planets)``, 5 today,
    validated exactly 5 by tools/validate_data.py), the same convention.
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
        # 4-bit masks of locked / security / sealed doorway segments per cell
        # (both sides carry the bit; opened/unsealed doors drop out).
        "grid_locked": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # Extra keys (beyond the base 1) a currently-locked segment costs to
        # open, from Game.door_search_cost (locks.json's side_search_cost --
        # today only the Great Hall's two side doorways). Painted on both
        # cells of the segment, like grid_locked; a cell touching more than
        # one such segment reports the max (a scalar per-cell magnitude, not
        # a per-direction bitmask like the boolean grid_* planes above/below).
        # 0 everywhere a locked door costs only the base key, or a segment
        # carrying a search cost has already been opened. An additive Dict
        # key (never a shape change to grid_locked, which would silently
        # reinterpret trained weights) -- without it, a 3-key Great Hall side
        # door is indistinguishable from an ordinary 1-key door, so "spend
        # keys versus walk further" is unlearnable at exactly the doors
        # where it matters most.
        "grid_search_cost": spaces.Box(0, 99, shape=(9, 5), dtype=np.uint8),
        "grid_security": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        # Sealed Antechamber doorway segments: impassable until a lever is pulled.
        # Non-zero only on the three sealed cells and the Antechamber when the
        # antechamber_levers flag is on; zero on every cell otherwise.
        "grid_sealed": spaces.Box(0, 15, shape=(9, 5), dtype=np.uint8),
        "grid_entered": spaces.Box(0, 1, shape=(9, 5), dtype=np.uint8),
        # player_pos: flat cell index on the 5x9 grid. Only meaningful when
        # player_area == 0 (the player is on the grid). When player_area > 0
        # the player is off-grid; player_pos holds the last grid cell visited.
        "player_pos": spaces.Discrete(45),
        # Low bound widened from -1: luck can now go genuinely negative (four
        # Maid's Chambers at -7 each from a luck_penalty day-start of 10
        # reaches -18, unclamped -- see engine/effects/tier1.py::anti_luck).
        # -99 is a round margin above that floor, not a tight bound: steps
        # (also carried in this array) is 1-per-move through the masked env
        # action space (Game.move: cost is 0/1, asserts steps>=1 first) and
        # every bulk step spend the action mask can reach is affordability-
        # gated to leave steps >= 1 (Game.affordable's Hovel branch, and the
        # TRAVEL_BASE mask's "steps > cost" check in env/actions.py) -- so
        # steps cannot go below 0 through env.step(), only through direct
        # internal calls (tests) that bypass the mask, same as any other
        # internal-API state this array does not otherwise guard against.
        "resources": spaces.Box(-99, 999, shape=(7,), dtype=np.int16),
        "options": spaces.Box(-1, max(n_rooms, 999), shape=(3, OPTION_FEATURES), dtype=np.int16),
        # prev_options: the top of the Chronograph's REWIND stack (the hand
        # the current one's most recent redraw replaced), encoded identically
        # to "options" (same _encode_option_rows helper, same row layout) so
        # the agent can evaluate the REWIND action -- the Chronograph is
        # blind, and undraftable, without seeing what it would restore.
        # Additive: never a shape change to "options" (widening that would
        # silently reinterpret trained weights). All -1 outside DRAFTING and
        # whenever the current hand has not yet been redrawn (stack empty).
        "prev_options": spaces.Box(-1, max(n_rooms, 999), shape=(3, OPTION_FEATURES),
                                   dtype=np.int16),
        # upgrade_options: Room.idx+1 for each of the three offered upgrade variants
        # while in UPGRADE_PENDING, or -1 in every slot otherwise.
        "upgrade_options": spaces.Box(-1, max(n_rooms, 999), shape=(3,), dtype=np.int16),
        # experiment: Laboratory/Experiments state, 0 = none/absent throughout
        # (matching item_state's +1/0 sentinel convention, not options' -1):
        #   [0:3] offered trigger idx+1 (registry.experiments.triggers order),
        #         while in EXPERIMENT_PENDING with that slot still unchosen
        #   [3:6] offered effect idx+1 (registry.experiments.effects order),
        #         while in EXPERIMENT_PENDING with that slot still unchosen
        #   [6]   today's chosen trigger idx+1, or 0 if not configured
        #   [7]   today's chosen effect idx+1, or 0 if not configured
        #   [8]   paused (0/1)
        #   [9]   success_count today, clamped to 999
        "experiment": spaces.Box(0, 999, shape=(10,), dtype=np.int16),
        "phase": spaces.Discrete(len(Phase)),
        # secret_passage_colour: 1 + COLOUR_CATEGORIES index of the dealt hand's
        # colour-selective restriction (state.pending.colour) while DRAFTING;
        # 0 in COLOUR_PENDING (no colour chosen yet -- that IS the pending
        # choice) and whenever the current hand, if any, carries no restriction.
        "secret_passage_colour": spaces.Discrete(len(COLOUR_CATEGORIES) + 1),
        # disks_held: count of upgrade disks in inventory, clamped to
        # MAX_DISKS_HELD. Lets the agent know whether inserting is possible
        # without inspecting the full inventory.
        "disks_held": spaces.Discrete(MAX_DISKS_HELD + 1),
        "stage": spaces.Discrete(3),
        "house_flags": spaces.Box(0, 999, shape=(HOUSE_FLAGS,), dtype=np.int16),
        # deepest_rank, optimistic player->Antechamber distance (-1 if walled off),
        # Antechamber connected+walkable right now (0/1),
        # antechamber_reached this day (0/1), room46_reached this day (0/1).
        "progress": spaces.Box(-1, 999, shape=(5,), dtype=np.int16),
        # player_area: 0 = on the 5x9 grid; 1 + area_index = off-grid at that
        # node. The area_index uses the same sorted-by-id ordering as TRAVEL_BASE.
        # When player_area == 0, player_pos is authoritative for location.
        "player_area": spaces.Discrete(n_area_nodes + 1),
        # Special-item observation keys (PR3 additions).
        # count per special item (registry order, 0 = not held)
        "inventory": spaces.Box(0, 99, shape=(n_items,), dtype=np.int16),
        # per-day item counters in documented order:
        # stopwatch_left, water, lockpick_attempts, lockpick_fails, shield_used,
        # trades_left, scepter_color_idx+1 (0=none), treasure_cell+1 (0=none),
        # treasure_dug, dining_room_served,
        # can_open_vault_box (0/1), crown_blocked_room_count
        # lockpick_fails (the pity counter) is two-sided and can sit at -2
        # between attempts (two consecutive successful picks), hence low=-2.
        "item_state": spaces.Box(-2, 999, shape=(12,), dtype=np.int16),
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
        # day: [current_day, days_remaining]. Single-day mode: [1, 0] (day 1 of 1, no tomorrow).
        # With a chain: current_day from DayChain.current_day;
        # days_remaining = max(0, n_days - current_day).
        "day": spaces.Box(0, 9999, shape=(2,), dtype=np.int16),
        # carryover: one int16 per DayChain._CARRYOVER_KEYS entry (sorted order), 0 or 1.
        # Length is always len(_CARRYOVER_KEYS); single-day mode encodes all zeros.
        "carryover": spaces.Box(0, 999, shape=(n_carryover,), dtype=np.int16),
        # upgrade_slots: 1 per upgrade slot in upgrades.all_slot_ids() order, 1 = upgraded.
        # Read from state.applied_upgrades, so carried-over and same-day upgrades both show.
        # This is the permanent cross-day investment the day-boundary bootstrap has to value.
        "upgrade_slots": spaces.Box(0, 1, shape=(n_slots,), dtype=np.uint8),
        # disks_spent: how many one-time disk sources are permanently used up
        # (len(cfg.collected_disks)) — i.e. how much of the finite supply is gone.
        "disks_spent": spaces.Box(0, 99, shape=(1,), dtype=np.int16),
        # treasure_trove_piles: cumulative attempt-wide Treasure Trove draft count,
        # clamped to the 32-pile cap (state.draft_counts["treasure_trove"], carried
        # across days by DayChain the same way as draft_counts generally). Same
        # rationale as disks_spent: a "spend today, pays out capped forever" quantity
        # is unpriceable to the agent unless V(s) can see how much of the lifetime
        # 160-coin budget is already earned.
        "treasure_trove_piles": spaces.Box(0, 32, shape=(1,), dtype=np.int16),
        # allowance: the permanent allowance total (state.allowance), separate
        # from today's already-spent "resources" coins figure -- the size of
        # the permanent income stream the attempt has banked so far, same
        # rationale as disks_spent/treasure_trove_piles/upgrade_slots: V(s)
        # cannot price a cross-day investment it cannot see.
        "allowance": spaces.Box(0, 9999, shape=(1,), dtype=np.int16),
        # stars: the permanent star total (state.stars), the same permanent
        # cross-day accumulation as allowance -- V(s) cannot price the
        # Observatory/Starfish Aquarium's investment without seeing it.
        "stars": spaces.Box(0, 9999, shape=(1,), dtype=np.int16),
        # mail: [mail cycle state code, transit days remaining, No Contact ordered].
        # [0]: 0 = empty (no order outstanding), 1 = awaiting (next Mail Room
        # draft delivers), 2 = transit (Freight Shipping's order placed but not
        # yet ready; drafting has no effect). [1]: Freight Shipping's transit
        # days remaining (0 outside of a transit order). [2]: 1 = a No Contact
        # Delivery (mail_room__ix90) was drafted today, so its package lands at
        # the start of TOMORROW -- the cross-day investment V(s) has to be able
        # to price.
        "mail": spaces.Box(0, 99, shape=(3,), dtype=np.int16),
        # shrine: [active blessing idx+1 (0 = none), blessing days remaining,
        # curse days remaining, coins parked in the bowl]. Blessing idx uses
        # data/shrine.json's own order (engine.effects.rooms.shrine.ShrineRules
        # .blessing_index), the same order DONATE_BASE indexes by.
        "shrine": spaces.Box(0, 999, shape=(4,), dtype=np.int16),
        # sigil_doors_open: 1 bit per Inner Sanctum realm door, in SIGIL_REALMS
        # (sorted) order, 1 = permanently unlocked (state.special.sigil_doors_opened
        # union cfg.sigil_doors_open). A door never re-seals, so this is another
        # cross-day investment V(s) needs to see, same rationale as upgrade_slots.
        "sigil_doors_open": spaces.Box(0, 1, shape=(len(SIGIL_REALMS),), dtype=np.uint8),
        # axed_rooms: 1 bit per axeable floorplan family, in
        # actions._build_axe_target_ids (sorted root-id) order, 1 = The Axe has
        # permanently zeroed that family's gem cost. Same additive-key shape as
        # sigil_doors_open: a permanent cross-day investment V(s) needs to see,
        # never a shape change to an existing key (options[].gem_cost already
        # reads 0 for an axed room via _effective_cost/resolve_gem_cost).
        "axed_rooms": spaces.Box(0, 1, shape=(n_axe_targets,), dtype=np.uint8),
        # wrench_rarity: per Mechanical Room (actions._build_mechanical_room_ids
        # order), the Gear Wrench's permanently-set rarity index+1, or 0 when
        # untouched (still its own natal rarity). An additive Dict key, never
        # a shape change to an existing one -- same rationale as axed_rooms:
        # a permanent, cross-day, per-room investment V(s) needs to see.
        "wrench_rarity": spaces.Box(0, 4, shape=(n_mechanical_rooms,), dtype=np.uint8),
        # dowsing: [dowsed_slot+1 (0 = no Dowsing Rod pick live right now --
        # not held, special items off, or no dealt hand), dowsing_penalty
        # (state.dowsing_penalty, clamped to the space bound)]. Additive: an
        # agent holding the Dowsing Rod cannot evaluate WHICH of the three
        # "options" rows is boosted, or how far up its own penalty ladder
        # today's draws have pushed it, from any existing key.
        "dowsing": spaces.Box(0, 999, shape=(2,), dtype=np.int16),
        # planetarium_planets: 1 bit per Telescope-in-Planetarium planet, in
        # data/special_items.json's planetarium_planets table order
        # (dauja/fennmora/mamora/veia/mora), 1 = permanently unlocked
        # (state.planetarium_planets). Same additive-key shape as axed_rooms:
        # a permanent, cross-day investment V(s) needs to see, never a shape
        # change to an existing key.
        "planetarium_planets": spaces.Box(0, 1, shape=(n_planetarium_planets,), dtype=np.uint8),
    })


def _cost_split(game: Game, room, opt) -> tuple[int, int]:
    """Effective cost as (gems, steps): the Hovel converts gems to steps 3:1."""
    cost = game._effective_cost(room, opt)
    if cost <= 0:
        return 0, 0
    if game.hovel_placed:
        return 0, 3 * cost
    return cost, 0


def _encode_option_rows(game: Game, pending, opts) -> np.ndarray:
    """Encode ``opts`` (a list of DraftOption, indexed by their own ``.slot``)
    into a (3, OPTION_FEATURES) int16 array; a slot absent from ``opts``
    stays -1. ``pending`` supplies the doorway (``from_cell``/``direction``)
    the security-door rarity leak checks against -- it is the live
    ``PendingDraft`` in every caller, even when ``opts`` is a past hand
    pulled off its ``rewind_stack``, since the doorway a hand was dealt at
    never changes across a redraw/rewind of the same draft.

    Shared by the "options" (live pending hand) and "prev_options" (top of
    the Chronograph's REWIND stack) observation keys so the two encode
    identically by construction rather than by two hand-kept-in-sync copies.
    """
    rows = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    for opt in opts:
        room = game.registry.rooms[opt.room_idx]
        gem_cost, step_cost = _cost_split(game, room, opt)
        doors = tuple(int(bool(opt.orientation & d)) for d in DIRS)  # N,E,S,W
        if opt.hidden:
            # Identity and orientation concealed (room_idx 0 = unknown,
            # door bits 0), but the cost and affordability stay visible
            # and it is still selectable. Rarity leaks through a security
            # door (wiki: "If the door being drafted from is a security
            # door, the rarity of the floorplan is shown"), otherwise -1.
            # forced is also zeroed: forced options are drawn from a small
            # named-room pool (Garage, Tunnel chain, Reading Nook Library,
            # priority draws), so exposing it on an otherwise-concealed
            # card would narrow its identity far more than any in-game
            # tell does -- same suppress-unless-canon-leak treatment as
            # rarity above.
            # from_cell == -1 (outer-room draft) has no doorway segment to
            # check; never hidden today anyway, but guarded explicitly.
            security = (
                pending is not None and pending.from_cell != -1
                and game.door_state_of(pending.from_cell, pending.direction) == DOOR_SECURITY
            )
            rarity = room.rarity_idx + 1 if security else -1
            rows[opt.slot] = (0, rarity, gem_cost, step_cost, -1, -1, 0, 0, 0, 0,
                              int(game.affordable(room, opt)), 0, int(opt.archived))
            continue
        rows[opt.slot] = (
            room.idx + 1,
            room.rarity_idx + 1,
            gem_cost,
            step_cost,
            LAYOUTS.index(room.layout),
            CAT_INDEX.get(room.category, 0),
            *doors,
            int(game.affordable(room, opt)),
            int(opt.forced),
            int(opt.archived),
        )
    return rows


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
    receive is 0 only for dice — allowance_token is a real registry item and
    encodes as its index, so a tier-5 special offer is distinguishable from a
    dice offer.
    """
    arr = np.full((TRADE_OFFER_ROWS, 2), -1, dtype=np.int16)
    offers = game.trade_offers()
    if not offers:
        return arr
    item_idx_map = {item.id: i for i, item in enumerate(game.registry.special.items)}
    for row_i, offer in enumerate(offers[:TRADE_OFFER_ROWS]):
        give_col = item_idx_map.get(offer["give"], -1) + 1  # 1-based; 0 = unknown
        # "dice" is the only non-item sentinel; allowance_token resolves through
        # the item map like any other item id.
        receive_col = item_idx_map.get(offer["receive"], -1) + 1
        arr[row_i] = [give_col, receive_col]
    return arr


def encode(game: Game, day_chain: DayChain | None = None) -> dict:
    """Encode the live game into the Dict observation for the current phase.

    Grid planes are 9x5 rank-major. Locked/security bits are painted on BOTH
    cells of a doorway segment (and drop out once the door is opened). Option
    rows are -1 outside DRAFTING or for absent slots; a hidden (Archives
    mystery) option exposes only cost and affordability, not identity.

    ``day_chain`` is threaded in from ``BluePrinceEnv`` when running in
    multi-day mode; it is ``None`` in single-day mode.  The ``day`` and
    ``carryover`` observation keys are populated from the chain when present,
    or set to sentinel values ([1, 0] and all-zeros) in single-day mode.
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
    grid_sealed = np.zeros((9, 5), dtype=np.uint8)
    grid_search_cost = np.zeros((9, 5), dtype=np.uint8)
    for (cell, d), seg in st.door_state.items():
        if seg == DOOR_LOCKED:
            plane = grid_locked
        elif seg == DOOR_SECURITY:
            plane = grid_security
        elif seg == DOOR_SEALED:
            plane = grid_sealed
        else:
            continue
        plane[cell // 5, cell % 5] |= d
        nb = neighbor(cell, d)
        plane[nb // 5, nb % 5] |= OPPOSITE[d]
        if seg == DOOR_LOCKED:
            extra = game.door_search_cost.get((cell, d), 0)
            if extra:
                grid_search_cost[cell // 5, cell % 5] = max(
                    grid_search_cost[cell // 5, cell % 5], extra)
                grid_search_cost[nb // 5, nb % 5] = max(
                    grid_search_cost[nb // 5, nb % 5], extra)

    pending = st.pending
    redraws = pending.redraws_left if pending else 0
    resources = np.array(
        [st.steps, st.gems, st.keys, st.coins, st.dice, st.luck, redraws], dtype=np.int16)

    secret_passage_colour = 0
    if pending is not None and pending.colour is not None:
        secret_passage_colour = COLOUR_CATEGORIES.index(pending.colour) + 1

    options = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    # prev_options: the top of the Chronograph's REWIND stack (the hand the
    # most recent redraw replaced), encoded with the same _encode_option_rows
    # helper as "options" -- an ADDITIVE key, never a shape change to
    # "options" itself. All -1 whenever the stack is empty (including outside
    # DRAFTING, or DRAFTING with no prior redraw this hand): without this key
    # a rewind is a menu item the agent cannot evaluate, since it can never
    # see what hand it would restore.
    prev_options = np.full((3, OPTION_FEATURES), -1, dtype=np.int16)
    if game.phase is Phase.DRAFTING and pending is not None:
        options = _encode_option_rows(game, pending, pending.options)
        if pending.rewind_stack:
            prev_options = _encode_option_rows(game, pending, pending.rewind_stack[-1])

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
        int(st.antechamber_reached),
        int(st.room46_reached),
    ], dtype=np.int16)

    # player_area: 0 = on the grid; 1 + area_index = off-grid at that node.
    # Uses the same sorted ordering as TRAVEL_BASE so the agent can correlate
    # the observation with the action family without a separate lookup.
    node_ids = _build_area_node_ids(game.registry)
    if st.area is None:
        player_area = 0
    else:
        idx = node_ids.index(st.area) if st.area in node_ids else -1
        player_area = (1 + idx) if idx >= 0 else 0

    # --- Special-item observation keys (PR3) ---
    registry = game.registry
    n_items = len(registry.special.items)

    # inventory: count per item, registry order
    inventory = np.zeros(n_items, dtype=np.int16)
    for i, item in enumerate(registry.special.items):
        inventory[i] = st.inventory.get(item.id, 0)

    # item_state: 12 per-day counters in documented order
    special = st.special
    shops_state = st.shops
    trading = registry.shop_rules.trading
    trades_per_day = trading.get("trades_per_day", 20)
    trades_left = max(0, trades_per_day - shops_state.trades_done)
    scepter_col = (SCEPTER_COLOR_INDEX.get(shops_state.scepter_color, -1) + 1
                   if shops_state.scepter_color is not None else 0)
    treasure_col = special.treasure_cell + 1  # -1 -> 0 (sentinel = no map read)
    item_state = np.array([
        special.stopwatch_left,               # 0
        special.water,                        # 1
        special.lockpick_attempts,            # 2
        special.lockpick_fails,               # 3
        int(special.shield_used),             # 4
        trades_left,                          # 5
        scepter_col,                          # 6  scepter_color index+1; 0 = not activated
        treasure_col,                         # 7  treasure_cell+1; 0 = no map read today
        int(special.treasure_dug),            # 8
        int(special.dining_room_served),      # 9
        int(game.can_open_vault_box()),       # 10 vault deposit box openable right now (0/1)
        len(special.crown_blocked_rooms),     # 11 rooms filtered today by the Crown
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

    # grid_containers: unopened container count per cell. Routed through
    # _container_kinds_at rather than reading registry.special.containers["rooms"]
    # directly, so per-cell overlays (Mechanarium compartments, Entrance Hall
    # trunks added by the entrance_hall_trunk experiment effect, the
    # Planetarium's Telescope-unlocked Dauja's Trunk) are visible here too,
    # not just the static per-room table.
    grid_containers = np.zeros((9, 5), dtype=np.uint8)
    for cell, room_idx in enumerate(st.grid):
        if room_idx >= 0:
            remaining = sum(n for _, n in _container_kinds_at(st, registry, cell))
            if remaining > 0:
                grid_containers[cell // 5, cell % 5] = remaining

    # upgrade_options: offered variant room indices (+1) in UPGRADE_PENDING, else -1
    upgrade_options = np.full(3, -1, dtype=np.int16)
    if game.phase is Phase.UPGRADE_PENDING:
        for i, variant_id in enumerate(st.pending_upgrade_options[:3]):
            room = game.registry.by_id.get(variant_id)
            upgrade_options[i] = room.idx + 1 if room is not None else -1

    # disks_held: count of upgrade disk items currently in inventory, clamped to
    # the same MAX_DISKS_HELD that bounds the declared space above.
    disks_held = min(len(game.held_disk_ids()), MAX_DISKS_HELD)

    # experiment: Laboratory/Experiments state (see the space's field-layout comment).
    ex_state = st.experiment
    ex_registry = registry.experiments
    trigger_idx = {t.id: i for i, t in enumerate(ex_registry.triggers)}
    effect_idx = {e.id: i for i, e in enumerate(ex_registry.effects)}
    experiment_arr = np.zeros(10, dtype=np.int16)
    if game.phase is Phase.EXPERIMENT_PENDING:
        if ex_state.trigger_id is None:
            for i, tid in enumerate(ex_state.offered_triggers[:3]):
                experiment_arr[i] = trigger_idx.get(tid, -1) + 1
        if ex_state.effect_id is None:
            for i, eid in enumerate(ex_state.offered_effects[:3]):
                experiment_arr[3 + i] = effect_idx.get(eid, -1) + 1
    if ex_state.trigger_id is not None:
        experiment_arr[6] = trigger_idx.get(ex_state.trigger_id, -1) + 1
    if ex_state.effect_id is not None:
        experiment_arr[7] = effect_idx.get(ex_state.effect_id, -1) + 1
    experiment_arr[8] = int(ex_state.paused)
    experiment_arr[9] = min(ex_state.success_count, 999)

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

    # day: [current_day, days_remaining]
    # With a chain: read directly from the chain (after advance() if day just ended).
    # Single-day mode: [1, 0] — day 1 of 1, no tomorrow.
    if day_chain is not None:
        _cur_day = day_chain.current_day
        _days_rem = max(0, day_chain.n_days - _cur_day)
    else:
        _cur_day = 1
        _days_rem = 0
    day_obs = np.array([_cur_day, _days_rem], dtype=np.int16)

    # carryover: one int16 per _CARRYOVER_KEYS entry (sorted for stable ordering).
    # All values are bools; encode as 0/1. Single-day mode: all zeros.
    _carryover_keys = sorted(DayChain._CARRYOVER_KEYS)
    if day_chain is not None:
        carryover_obs = np.array(
            [int(day_chain.carried_flags.get(k, False)) for k in _carryover_keys],
            dtype=np.int16,
        )
    else:
        carryover_obs = np.zeros(len(_carryover_keys), dtype=np.int16)

    # upgrade_slots: which permanent upgrade slots are filled, in all_slot_ids() order.
    # Read from state.applied_upgrades (not the chain) because it is seeded from
    # cfg.upgrade_disks at day start AND updated when an upgrade is applied mid-day,
    # so carried-over and same-day upgrades are covered by the same read.
    _slot_ids = all_slot_ids(game.registry)
    _filled = upgraded_slots(frozenset(st.applied_upgrades), game.registry)
    upgrade_slots_obs = np.array(
        [1 if s in _filled else 0 for s in _slot_ids], dtype=np.uint8
    )

    # disks_spent: one-time disk sources permanently used up across the attempt.
    disks_spent_obs = np.array([len(game.cfg.collected_disks)], dtype=np.int16)

    # treasure_trove_piles: cumulative draft count for the Treasure Trove this
    # attempt, clamped to the 32-pile cap.
    treasure_trove_piles_obs = np.array(
        [min(st.draft_counts.get("treasure_trove", 0), 32)], dtype=np.int16
    )

    # allowance: the permanent total banked so far this attempt, clamped to the space bound.
    allowance_obs = np.array([min(st.allowance, 9999)], dtype=np.int16)

    # stars: the permanent star total banked so far this attempt, clamped to the space bound.
    stars_obs = np.array([min(st.stars, 9999)], dtype=np.int16)

    # mail: [cycle state code, transit days remaining, No Contact ordered].
    _mail_cycle_code = {"empty": 0, "awaiting": 1, "transit": 2}.get(st.mail_cycle, 0)
    mail_obs = np.array(
        [_mail_cycle_code, st.mail_transit_days, 1 if st.no_contact_drafted else 0],
        dtype=np.int16,
    )

    # shrine: active blessing (0 = none while shrine_blessing_days == 0), its
    # remaining days, curse days remaining, and coins parked in the bowl.
    _shrine_rules = shrine.rules(game)
    _blessing_col = 0
    if st.shrine_blessing_days > 0:
        _blessing_col = _shrine_rules.blessing_index.get(st.shrine_blessing_id, -1) + 1
    shrine_obs = np.array(
        [_blessing_col, st.shrine_blessing_days, st.shrine_curse_days, st.shrine_offered_coins],
        dtype=np.int16,
    )

    # sigil_doors_open: which Inner Sanctum realm doors are permanently unlocked.
    # Union of cfg (carried from earlier days) and today's own openings, same
    # read shape as upgrade_slots (state.applied_upgrades).
    _opened_realms = set(game.cfg.sigil_doors_open) | set(st.special.sigil_doors_opened)
    sigil_doors_open_obs = np.array(
        [1 if r in _opened_realms else 0 for r in SIGIL_REALMS], dtype=np.uint8
    )

    # axed_rooms: which floorplan families The Axe has permanently zeroed,
    # in _build_axe_target_ids order. state.axed_rooms is already the full
    # history (seeded from cfg at reset, only ever grown), the same read
    # shape as upgrade_slots/sigil_doors_open above.
    _axe_target_ids = _build_axe_target_ids(registry)
    _axed = set(st.axed_rooms)
    axed_rooms_obs = np.array(
        [1 if t in _axed else 0 for t in _axe_target_ids], dtype=np.uint8
    )

    # wrench_rarity: Gear Wrench's permanent per-room override, in
    # _build_mechanical_room_ids order. state.permanent_rarity is already
    # the full current record (seeded from cfg at reset, only ever changed
    # by Game.set_wrench_rarity), the same read shape as axed_rooms above.
    _mech_room_ids = _build_mechanical_room_ids(registry)
    wrench_rarity_obs = np.array(
        [st.permanent_rarity.get(rid, -1) + 1 for rid in _mech_room_ids], dtype=np.uint8
    )

    # dowsing: [dowsed_slot+1, dowsing_penalty]. dowsed_slot is only
    # meaningful while DRAFTING with a live pending hand carrying a pick --
    # 0 otherwise (no Dowsing Rod boost to show right now), the same
    # DRAFTING gate "options" itself uses.
    _dowsed_slot_col = 0
    if game.phase is Phase.DRAFTING and pending is not None and pending.dowsed_slot is not None:
        _dowsed_slot_col = pending.dowsed_slot + 1
    dowsing_obs = np.array([_dowsed_slot_col, min(st.dowsing_penalty, 999)], dtype=np.int16)

    # planetarium_planets: which planets are permanently unlocked, in the
    # data table's own order. state.planetarium_planets is already the full
    # history (seeded from cfg at reset, only ever grown), the same read
    # shape as axed_rooms/sigil_doors_open above.
    _unlocked_planets = set(st.planetarium_planets)
    planetarium_planets_obs = np.array(
        [1 if p["id"] in _unlocked_planets else 0
         for p in registry.special.planetarium_planets],
        dtype=np.uint8,
    )

    return {
        "grid_room": grid_room,
        "grid_doors": grid_doors,
        "grid_dist": grid_dist,
        "grid_ante_dist": grid_ante_dist,
        "grid_frontier": grid_frontier,
        "grid_locked": grid_locked,
        "grid_search_cost": grid_search_cost,
        "grid_security": grid_security,
        "grid_sealed": grid_sealed,
        "grid_entered": grid_entered,
        "player_pos": st.pos,
        "resources": resources,
        "options": options,
        "prev_options": prev_options,
        "upgrade_options": upgrade_options,
        "experiment": experiment_arr,
        "phase": game.phase.value,
        "secret_passage_colour": secret_passage_colour,
        "disks_held": disks_held,
        "stage": STAGE_INDEX.get(st.stage, 2),
        "house_flags": house_flags,
        "progress": progress,
        "player_area": player_area,
        "inventory": inventory,
        "item_state": item_state,
        "grid_dig": grid_dig,
        "grid_containers": grid_containers,
        "shop_stock": shop_stock_arr,
        "trade_offers": trade_offers_arr,
        "fabricate": fabricate,
        "day": day_obs,
        "carryover": carryover_obs,
        "upgrade_slots": upgrade_slots_obs,
        "disks_spent": disks_spent_obs,
        "treasure_trove_piles": treasure_trove_piles_obs,
        "allowance": allowance_obs,
        "stars": stars_obs,
        "sigil_doors_open": sigil_doors_open_obs,
        "mail": mail_obs,
        "shrine": shrine_obs,
        "axed_rooms": axed_rooms_obs,
        "wrench_rarity": wrench_rarity_obs,
        "dowsing": dowsing_obs,
        "planetarium_planets": planetarium_planets_obs,
    }
