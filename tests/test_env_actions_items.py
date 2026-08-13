"""PR3-B action-space wiring: buy/trade/fabricate/scepter/smash + move-to re-entry."""

from __future__ import annotations

import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, rank_of
from blueprince_sim.engine.state import DraftOption
from blueprince_sim.env import actions as A


# ------------------------------------------------------------------ helpers


def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _place_shop(game: Game, room_id: str, cell: int = 7) -> object:
    """Place ``room_id`` at ``cell``, set pos, mark entered; mirrors test_shops helper."""
    room = game.registry.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    return room


def _enter_shop(game: Game, room_id: str, cell: int = 7) -> object:
    """Place and enter a shop so its stock is rolled. Returns the Room."""
    room = _place_shop(game, room_id, cell)
    shops.on_enter_shop(game, room)
    return room


def _place_workshop(game: Game, cell: int = 7) -> object:
    """Place the Workshop at ``cell``, set pos; does NOT roll stock (no entry)."""
    return _place_shop(game, "workshop", cell)


def _enter_workshop(game: Game, cell: int = 7) -> object:
    """Place and enter the Workshop, firing the first-entry free-component grant."""
    room = _place_workshop(game, cell)
    shops.on_enter_shop(game, room)
    return room


def _give_items(game: Game, *item_ids: str) -> None:
    """Grant items directly to inventory (bypass grant effects)."""
    for iid in item_ids:
        game.state.inventory[iid] = game.state.inventory.get(iid, 0) + 1


def _set_trading_post_inner(game: Game) -> None:
    """Fake the player being inside the Trading Post outer room (area='trading_post')."""
    game.state.area = "trading_post"
    game.placed_ids.add("trading_post")


def _place_dining_room(game: Game, cell: int = 7, rank8_entered: bool = False) -> object:
    """Place the Dining Room at ``cell`` and optionally mark a rank-8 cell as entered."""
    room = game.registry.by_id["dining_room"]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    if rank8_entered:
        # Mark a cell at rank 8 as entered so the gate is open
        # rank_of(cell) = cell // 5 + 1, so rank 8 means cell // 5 == 7 (cells 35..39)
        r8_cell = 35  # col 0, rank 8
        state.entered[r8_cell] = True
    return room


def _mask(game: Game) -> list[bool]:
    return A.action_mask(game)


# ================================================================= mask length & defaults

def test_new_action_slots_all_false_at_reset():
    """All 29 new action slots (241..269) are False at reset when no items, no scepter.

    royal_scepter_found=False is explicit because the default is now True (the unlock
    puzzle is unmodeled; False disables the day-start grant).  With no items and no shop
    standing, none of the new actions should be legal immediately after reset.
    """
    env = make_env(GameConfig(royal_scepter_found=False))
    env.reset(seed=0)
    mask = env.action_masks()
    for action_id in range(241, 270):
        assert not mask[action_id], f"action {action_id} should be False at reset"


# ================================================================= BUY (241..246)

def test_buy_mask_reflects_affordability():
    """Buy slots are True only when the entry is not sold_out and the player can afford it.

    An unaffordable entry (coins < price) must be masked False; an affordable one True.
    """
    game = _game(seed=0)
    game.state.coins = 0
    _enter_shop(game, "commissary")
    mask = _mask(game)

    display = game.shop_stock()
    assert display is not None
    for i, entry in enumerate(display[:6]):
        if entry["sold_out"]:
            assert not mask[A.BUY_BASE + i], f"slot {i}: sold_out must be masked False"
        else:
            expected = entry["affordable"]  # coins=0 -> all False
            assert mask[A.BUY_BASE + i] == expected, f"slot {i}: affordable={expected}"


def test_buy_mask_true_when_entry_affordable():
    """A buy slot becomes True once the player has enough coins.

    Coins are set to cover the cheapest entry; at least one slot should become legal.
    """
    game = _game(seed=0)
    _enter_shop(game, "commissary")
    display = game.shop_stock()
    assert display
    min_price = min(e["price"] for e in display if not e["sold_out"])
    game.state.coins = min_price
    mask = _mask(game)
    assert any(mask[A.BUY_BASE + i] for i in range(6)), (
        "at least one buy slot should be True when coins == min affordable price"
    )


def test_buy_apply_action_spends_coins_and_grants():
    """Applying a buy action deducts coins and grants the item or resource.

    After a successful purchase the player's coins decrease by the entry price
    and the item appears in inventory (or the resource increases).
    """
    game = _game(seed=0)
    game.state.coins = 100
    _enter_shop(game, "commissary")
    display = game.shop_stock()
    assert display

    # Find the first non-sold-out entry
    idx = next(i for i, e in enumerate(display[:6]) if not e["sold_out"])
    entry = display[idx]
    coins_before = game.state.coins
    log_before = len(game.state.items_found_log)

    A.apply_action(game, A.BUY_BASE + idx)

    # Coins must have decreased by the price
    assert game.state.coins == coins_before - entry["price"], (
        f"coins should drop by {entry['price']}"
    )
    # items_found_log must have a new entry
    assert len(game.state.items_found_log) > log_before, (
        "items_found_log should grow after a purchase"
    )


def test_buy_mask_false_when_not_in_shop():
    """Buy slots are all False outside a shop room (on a fresh entrance game).

    The mask only legalizes buy actions when the player stands in a shop.
    """
    game = _game(seed=0)
    game.state.coins = 999
    mask = _mask(game)
    assert not any(mask[A.BUY_BASE + i] for i in range(6)), (
        "no buy slots should be legal when not in a shop"
    )


def test_buy_sold_out_entry_masked_false():
    """A sold-out entry is masked False even if coins are sufficient.

    sold_out is independent of affordability; both must pass for the slot to be legal.
    """
    game = _game(seed=0)
    game.state.coins = 999
    _enter_shop(game, "commissary")
    # Mark the first entry sold
    stored = game.state.shops.stock["commissary"]
    if stored:
        stored[0]["sold"] = stored[0].get("limit", 1) or 1
    mask = _mask(game)
    display = game.shop_stock()
    for i, entry in enumerate(display[:6]):
        if entry["sold_out"]:
            assert not mask[A.BUY_BASE + i], f"slot {i}: sold_out entry must be masked False"


# ================================================================= TRADE (247..254)

def test_trade_mask_empty_outside_trading_post():
    """Trade slots are all False when the player is not inside the Trading Post.

    Trades are only offered while standing inside a placed trading_post.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    mask = _mask(game)
    assert not any(mask[A.TRADE_BASE + i] for i in range(8)), (
        "trade slots should be False when not inside the Trading Post"
    )


def test_trade_mask_reflects_offers():
    """Trade slots 0..len(offers)-1 are True when inside the Trading Post with tradeable items.

    Each offer index corresponds to one item in trade_offers() sorted order.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel", "compass"})), seed=0)
    _set_trading_post_inner(game)
    offers = game.trade_offers()
    mask = _mask(game)
    for i in range(8):
        expected = i < len(offers)
        assert mask[A.TRADE_BASE + i] == expected, (
            f"trade slot {i}: expected={expected}, offers count={len(offers)}"
        )


def test_trade_apply_action_consumes_give_item():
    """Applying a trade action removes the given item and grants the received one.

    After the trade, give_id is no longer held and items_found_log grows.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    _set_trading_post_inner(game)
    offers = game.trade_offers()
    assert offers, "need at least one offer to test trade apply"
    give_id = offers[0]["give"]
    log_before = len(game.state.items_found_log)

    A.apply_action(game, A.TRADE_BASE + 0)

    assert not si.has(game.state, give_id), f"{give_id} should be gone after trade"
    assert len(game.state.items_found_log) > log_before, (
        "items_found_log should grow after a trade"
    )


# ================================================================= FABRICATE (255..262)

def test_fabricate_mask_all_false_when_not_in_workshop():
    """Fabricate slots are all False when the player holds inputs but is not at the Workshop.

    fabricate_options() is a pure query visible anywhere, but the action requires
    the Workshop; without it, all fabricate slots are masked out.
    """
    game = _game(
        GameConfig(starting_items=frozenset({"metal_detector", "shovel"})), seed=0
    )
    # Not in the Workshop (Entrance Hall position)
    assert game.fabricate_options()  # options exist...
    mask = _mask(game)
    assert not any(mask[A.FABRICATE_BASE + i] for i in range(8)), (
        "fabricate slots must be False when not standing in the Workshop"
    )


def test_fabricate_mask_true_in_workshop_with_inputs():
    """The fabricate slot for a recipe is True when standing in the Workshop with all inputs.

    Recipe index 1 (metal_detector + shovel → detector_shovel) should be legal
    when those inputs are held and the player is in the Workshop.
    """
    game = _game(seed=0)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    _enter_workshop(game)

    fab = game.registry.special.fabrication
    recipe_idx = next(
        i for i, (inputs, output) in enumerate(fab) if output == "detector_shovel"
    )
    mask = _mask(game)
    assert mask[A.FABRICATE_BASE + recipe_idx], (
        "fabricate slot for detector_shovel should be True with inputs held in Workshop"
    )


def test_fabricate_apply_action_consumes_inputs_and_grants_output():
    """Applying a fabricate action consumes recipe inputs and grants the output contraption.

    Inputs must be absent from inventory afterwards; the output must be present.
    """
    game = _game(seed=0)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    _enter_workshop(game)

    fab = game.registry.special.fabrication
    recipe_idx = next(
        i for i, (inputs, output) in enumerate(fab) if output == "detector_shovel"
    )
    A.apply_action(game, A.FABRICATE_BASE + recipe_idx)

    assert not si.has(game.state, "metal_detector"), "metal_detector should be consumed"
    assert not si.has(game.state, "shovel"), "shovel should be consumed"
    assert si.has(game.state, "detector_shovel"), "detector_shovel should be granted"


def test_fabricate_mask_false_without_inputs():
    """Fabricate slots are False when the recipe's inputs are not all held.

    A partial-input state must not legalize the action, even in the Workshop.
    """
    game = _game(seed=0)
    game.state.inventory["metal_detector"] = 1
    # shovel not given — detector_shovel recipe incomplete
    _enter_workshop(game)

    fab = game.registry.special.fabrication
    recipe_idx = next(
        i for i, (inputs, output) in enumerate(fab) if output == "detector_shovel"
    )
    mask = _mask(game)
    assert not mask[A.FABRICATE_BASE + recipe_idx], (
        "fabricate slot must be False when recipe inputs are incomplete"
    )


# ================================================================= SCEPTER (263..268)

def test_scepter_mask_all_false_without_royal_scepter():
    """All 6 scepter slots are False when the Royal Scepter is not held.

    The scepter action is gated on can_activate_scepter(), which requires holding
    it.  royal_scepter_found=False is explicit because the default is now True
    (the unlock puzzle is unmodeled; False disables the day-start grant).
    """
    game = _game(GameConfig(royal_scepter_found=False), seed=0)
    assert not si.has(game.state, "royal_scepter")
    mask = _mask(game)
    assert not any(mask[A.SCEPTER_BASE + i] for i in range(6)), (
        "scepter slots must be False without the Royal Scepter"
    )


def test_scepter_mask_all_true_when_held_and_not_activated():
    """All 6 scepter slots are True when the Royal Scepter is held and not yet activated.

    One activation per day; before it fires all 6 color options are legal.
    """
    game = _game(seed=0)
    _give_items(game, "royal_scepter")
    mask = _mask(game)
    for i in range(6):
        assert mask[A.SCEPTER_BASE + i], (
            f"scepter slot {i} should be True with royal_scepter held"
        )


def test_scepter_apply_action_locks_the_color():
    """Applying a scepter action sets scepter_color and masks all scepter slots False.

    The activation is irrevocable for the day; all 6 slots become False after it fires.
    """
    game = _game(seed=0)
    _give_items(game, "royal_scepter")
    assert game.state.shops.scepter_color is None

    A.apply_action(game, A.SCEPTER_BASE + 0)  # blueprint

    assert game.state.shops.scepter_color == shops.SCEPTER_COLORS[0], (
        "scepter_color should be set after activation"
    )
    mask = _mask(game)
    assert not any(mask[A.SCEPTER_BASE + i] for i in range(6)), (
        "all scepter slots should be False after activation"
    )


def test_scepter_colors_order_matches_constant():
    """The scepter apply action uses shops.SCEPTER_COLORS index order.

    SCEPTER_COLORS = (blueprint, green, red, bedroom, hallway, shop).
    Action id SCEPTER_BASE+i activates color SCEPTER_COLORS[i].
    """
    game = _game(seed=0)
    _give_items(game, "royal_scepter")

    for i, color in enumerate(shops.SCEPTER_COLORS):
        g = _game(seed=0)
        _give_items(g, "royal_scepter")
        A.apply_action(g, A.SCEPTER_BASE + i)
        assert g.state.shops.scepter_color == color, (
            f"SCEPTER_BASE+{i} should activate {color!r}, got {g.state.shops.scepter_color!r}"
        )


# ================================================================= SMASH VASE (269)

def test_smash_vase_mask_false_without_smash_item():
    """SMASH_VASE_ACTION is False when the player holds no smash-capable item.

    can_smash_vase() checks for the 'smash' effect tag (sledge_hammer etc.).
    """
    game = _game(seed=0)
    # Player starts in the Entrance Hall; can_smash_vase checks the pos room id.
    mask = _mask(game)
    assert not mask[A.SMASH_VASE_ACTION], (
        "smash vase should be False without a smash-capable item"
    )


def test_smash_vase_mask_true_in_entrance_hall_with_sledge():
    """SMASH_VASE_ACTION is True when in the Entrance Hall holding a sledge_hammer.

    Entrance Hall is where the player starts; giving a smash item unlocks the action.
    """
    game = _game(seed=0)
    _give_items(game, "sledge_hammer")
    # Player starts in the Entrance Hall
    assert game.can_smash_vase()
    mask = _mask(game)
    assert mask[A.SMASH_VASE_ACTION], (
        "smash vase should be True in Entrance Hall with sledge_hammer"
    )


def test_smash_vase_apply_grants_microchip():
    """Applying smash_vase grants a microchip and records the discovery.

    After smashing: vase_smashed=True, microchip in inventory.
    """
    game = _game(seed=0)
    _give_items(game, "sledge_hammer")
    assert not game.state.shops.vase_smashed

    A.apply_action(game, A.SMASH_VASE_ACTION)

    assert game.state.shops.vase_smashed, "vase_smashed should be True after smash"
    assert si.has(game.state, "microchip"), "microchip should be granted after smash"


def test_smash_vase_mask_false_after_smashing():
    """SMASH_VASE_ACTION is False after the vase has already been smashed today.

    can_smash_vase() checks vase_smashed (and cfg.entrance_vase_broken); once set
    the action is no longer legal.
    """
    game = _game(seed=0)
    _give_items(game, "sledge_hammer")
    A.apply_action(game, A.SMASH_VASE_ACTION)
    mask = _mask(game)
    assert not mask[A.SMASH_VASE_ACTION], (
        "smash vase should be False after it has already been smashed"
    )


# ================================================================= MOVE-TO RE-ENTRY

def test_move_to_reenters_shop_cell_with_buyable_stock():
    """A walk-to target for an entered shop cell is legal when it has a buyable entry.

    The re-entry extension lets the agent return to buy from a previously entered shop.
    The cell must be reachable and not already bought out.
    """
    game = _game(seed=0)
    # Give lots of steps and place the Commissary at a reachable distance
    game.state.steps = 50

    # Place the commissary at cell 23 (entrance is at cell 22 in a 5x9 grid: r1c2)
    eh_cell = game.state.pos  # Entrance Hall
    target_cell = eh_cell + 1  # adjacent cell (same rank, one column east)

    room = game.registry.by_id["commissary"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8  # West door to connect back
    state.entered[target_cell] = True  # already visited
    shops.on_enter_shop(game, room)  # roll stock

    # Make sure player can afford at least one item
    state.coins = 999

    # distance_map: target_cell must be reachable; fake by placing a connecting door
    state.placed_doors[eh_cell] |= 2  # East door from EH
    # Recompute mask
    mask = _mask(game)

    # target_cell is entered but has buyable stock → should be in move_to targets
    if any(not e["sold_out"] and e["affordable"] for e in shops.stock_display(game, room.id)):
        # The cell should be walkable again
        dist = game.distance_map()
        if 0 < dist[target_cell] <= state.steps:
            assert mask[A.MOVE_TO_BASE + target_cell], (
                "entered shop cell with buyable stock should be walkable"
            )


def test_move_to_does_not_reenter_exhausted_shop():
    """An entered shop cell with all entries sold out is NOT in the walk-to targets.

    Once a shop is fully exhausted, there's nothing to buy, so re-entry is unnecessary.
    """
    game = _game(seed=0)
    game.state.steps = 50
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["commissary"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    shops.on_enter_shop(game, room)
    state.placed_doors[eh_cell] |= 2

    # Mark all entries as sold out
    for entry in state.shops.stock["commissary"]:
        entry["sold"] = entry.get("limit", 1) or 1

    state.coins = 999
    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert not mask[A.MOVE_TO_BASE + target_cell], (
            "entered shop with all sold-out entries should NOT be walkable"
        )


def test_move_to_reenters_workshop_with_fabricate_options():
    """An entered Workshop cell is walkable again when fabricate_options() is non-empty.

    The Workshop is revisitable when the player could build something there.
    """
    game = _game(seed=0)
    game.state.steps = 50
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["workshop"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    shops.on_enter_shop(game, room)   # first entry: grants free component, sets stock=[]
    state.placed_doors[eh_cell] |= 2

    # Give inputs for a recipe
    state.inventory["metal_detector"] = 1
    state.inventory["shovel"] = 1
    assert game.fabricate_options()

    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert mask[A.MOVE_TO_BASE + target_cell], (
            "entered Workshop with fabricate options should be walkable"
        )


def test_move_to_does_not_reenter_workshop_without_options():
    """An entered Workshop with no fabricate options is NOT walkable.

    If the player has no inputs for any recipe, the Workshop re-entry is blocked.
    """
    game = _game(seed=0)
    game.state.steps = 50
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["workshop"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    shops.on_enter_shop(game, room)
    state.placed_doors[eh_cell] |= 2

    # No recipe inputs held
    assert not game.fabricate_options()

    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert not mask[A.MOVE_TO_BASE + target_cell], (
            "entered Workshop without fabricate options should NOT be walkable"
        )


def test_move_to_reenters_dining_room_with_rank8_gate_open():
    """An entered Dining Room is walkable when rank-8 reached but course unserved.

    The main course is only served once rank 8 is reached; a prior visit left
    empty-handed. The agent should be able to return after reaching rank 8.
    """
    game = _game(seed=0)
    game.state.steps = 50
    game.state.special.enabled = True
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["dining_room"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    state.placed_doors[eh_cell] |= 2

    # Rank-8 gate: mark a rank-8 cell as entered
    rank8_cell = 35  # (8-1)*5 + 0 = 35, rank 8, col 0
    state.entered[rank8_cell] = True
    assert any(entered and rank_of(c) >= 8 for c, entered in enumerate(state.entered))

    # Course not yet served
    assert not state.special.dining_room_served

    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert mask[A.MOVE_TO_BASE + target_cell], (
            "entered Dining Room with rank-8 open and unserved course should be walkable"
        )


def test_move_to_does_not_reenter_dining_room_after_serving():
    """An entered Dining Room is NOT walkable once the main course has been served.

    After serving, dining_room_served=True; there's nothing more to do there.
    """
    game = _game(seed=0)
    game.state.steps = 50
    game.state.special.enabled = True
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["dining_room"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    state.placed_doors[eh_cell] |= 2

    rank8_cell = 35
    state.entered[rank8_cell] = True
    state.special.dining_room_served = True  # already served

    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert not mask[A.MOVE_TO_BASE + target_cell], (
            "entered Dining Room after serving should NOT be walkable"
        )


def test_move_to_does_not_reenter_dining_room_before_rank8():
    """An entered Dining Room is NOT walkable when rank 8 has not been reached.

    The rank-8 gate is closed: even though the course is unserved, returning
    would be fruitless (the course won't serve until rank 8 is reached).
    """
    game = _game(seed=0)
    game.state.steps = 50
    game.state.special.enabled = True
    eh_cell = game.state.pos
    target_cell = eh_cell + 1

    room = game.registry.by_id["dining_room"]
    state = game.state
    state.grid[target_cell] = room.idx
    state.placed_doors[target_cell] = room.door_mask | 8
    state.entered[target_cell] = True
    state.placed_doors[eh_cell] |= 2

    # No rank-8 cell entered
    assert not any(state.entered[c] and rank_of(c) >= 8 for c in range(len(state.entered)))
    assert not state.special.dining_room_served

    mask = _mask(game)
    dist = game.distance_map()
    if 0 < dist[target_cell] <= state.steps:
        assert not mask[A.MOVE_TO_BASE + target_cell], (
            "entered Dining Room before rank-8 should NOT be walkable"
        )


# ================================================================= DESCRIBE_ACTION

def test_describe_action_returns_nonempty_for_all_new_ids():
    """describe_action returns a non-empty string for every new action id 241..269.

    Human-readable descriptions must never be empty so logs and dashboards work.
    """
    game = _game(seed=0)
    game.state.coins = 999
    _give_items(game, "royal_scepter", "sledge_hammer")
    _enter_shop(game, "commissary")
    # Craft a Trading Post context
    _set_trading_post_inner(game)
    _give_items(game, "shovel")
    # Enter the workshop too (but can only be in one place; just test describe with index)
    for action_id in range(241, 270):
        desc = A.describe_action(game, action_id)
        assert desc and len(desc) > 0, (
            f"describe_action({action_id}) returned empty or None: {desc!r}"
        )


def test_describe_buy_includes_price():
    """describe_action for a buy slot includes the item id and price in parentheses.

    The format is 'buy <id> (<price>g)' — useful for human log reading.
    """
    game = _game(seed=0)
    game.state.coins = 999
    _enter_shop(game, "commissary")
    display = game.shop_stock()
    assert display
    desc = A.describe_action(game, A.BUY_BASE + 0)
    assert "buy" in desc.lower(), f"describe for buy should contain 'buy': {desc!r}"
    assert "g" in desc, f"describe for buy should mention price in gold: {desc!r}"


def test_describe_trade_includes_give_and_receive():
    """describe_action for a trade slot includes both give and receive ids.

    The format 'trade <give> -> <receive>' lets the player read what they're exchanging.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    _set_trading_post_inner(game)
    offers = game.trade_offers()
    if not offers:
        pytest.skip("no trade offers available for this seed")
    desc = A.describe_action(game, A.TRADE_BASE + 0)
    assert "->" in desc, f"describe for trade should contain '->': {desc!r}"


def test_describe_scepter_includes_color():
    """describe_action for a scepter slot includes the color name.

    The format 'scepter: <color>' maps the color to its SCEPTER_COLORS index.
    """
    game = _game(seed=0)
    for i, color in enumerate(shops.SCEPTER_COLORS):
        desc = A.describe_action(game, A.SCEPTER_BASE + i)
        assert color in desc, (
            f"describe for scepter slot {i} should mention color {color!r}: {desc!r}"
        )


def test_describe_smash_vase_mentions_vase():
    """describe_action for SMASH_VASE_ACTION mentions the vase.

    The description must contain 'vase' to be meaningful in human-readable logs.
    """
    game = _game(seed=0)
    desc = A.describe_action(game, A.SMASH_VASE_ACTION)
    assert "vase" in desc.lower(), (
        f"describe for smash vase should mention 'vase': {desc!r}"
    )


# ============================================================ CROWN_BLOCK (376..378)

def _drafting_with_forced_red_slot0(item_held: bool = True, seed: int = 0):
    """Build a Game in DRAFTING at a real doorway (cell 2, north -- the
    Entrance Hall's own door, already proven open at day 1 by the silver-key
    tests in test_draft_items.py), then overwrite slot 0 with a known Red
    Room directly. Deterministic: no seed-hunting for a hand that happens to
    contain a Red Room.
    """
    items = frozenset(("crown_of_the_blueprints",)) if item_held else frozenset()
    game = _game(GameConfig(starting_items=items), seed=seed)
    game.state.steps = 100
    pending = game.open_door(2, N)
    red = next(r for r in game.registry.rooms if r.is_category("red") and r.rarity is not None)
    pending.options[0] = DraftOption(room_idx=red.idx, orientation=red.door_mask,
                                     gem_cost=0, slot=0)
    return game, pending, red


def test_crown_block_mask_true_for_red_slot_with_item_held():
    """CROWN_BLOCK_BASE + 0 is legal in the mask when slot 0 is a Red Room
    and the Crown is held; slots 1/2 stay masked off since they are not."""
    game, pending, red = _drafting_with_forced_red_slot0()
    mask = A.action_mask(game)
    assert mask[A.CROWN_BLOCK_BASE + 0]
    assert not mask[A.CROWN_BLOCK_BASE + 1]
    assert not mask[A.CROWN_BLOCK_BASE + 2]


def test_crown_block_mask_false_without_item_even_for_red_slot():
    """Without the Crown held, CROWN_BLOCK_BASE + 0 stays masked off even
    though slot 0 is a Red Room -- the item, not just the room, gates it."""
    game, pending, red = _drafting_with_forced_red_slot0(item_held=False)
    mask = A.action_mask(game)
    assert not mask[A.CROWN_BLOCK_BASE + 0]


def test_apply_action_crown_block_grants_gem_and_redeals():
    """Dispatching CROWN_BLOCK_BASE + 0 through apply_action (not calling
    Game.crown_block directly) grants 1 gem, records the block, and the
    redealt hand never includes the just-blocked room."""
    game, pending, red = _drafting_with_forced_red_slot0(seed=1)
    gems_before = game.state.gems
    A.apply_action(game, A.CROWN_BLOCK_BASE + 0)
    assert game.state.gems == gems_before + 1
    assert red.id in game.state.special.crown_blocked_rooms
    assert all(game.registry.rooms[o.room_idx].id != red.id for o in game.state.pending.options)


def test_describe_action_crown_block_mentions_room_name():
    """describe_action for a CROWN_BLOCK id includes the dealt room's name,
    matching the 'choose #n <name>' convention used for CHOOSE_BASE."""
    game, pending, red = _drafting_with_forced_red_slot0(seed=2)
    desc = A.describe_action(game, A.CROWN_BLOCK_BASE + 0)
    assert red.name in desc
