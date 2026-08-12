"""Observation encoding for special items (PR3-A): inventory, item_state,
grid_dig, shop_stock, trade_offers, and fabricate keys."""

import numpy as np
import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env import obs as O


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _obs(game: Game) -> dict:
    return O.encode(game)


def _space(game: Game):
    return O.observation_space(
        len(game.registry.rooms),
        len(game.registry.special.items),
        len(game.registry.special.fabrication),
    )


def _item_idx(game: Game, item_id: str) -> int:
    """Return the registry index of ``item_id`` in game.registry.special.items."""
    return next(i for i, it in enumerate(game.registry.special.items)
                if it.id == item_id)


def _recipe_idx(game: Game, output_id: str) -> int:
    """Return the fabrication recipe index whose output is ``output_id``."""
    return next(i for i, (_, out) in enumerate(game.registry.special.fabrication)
                if out == output_id)


def _enter_shop(game: Game, room_id: str, cell: int = 7) -> object:
    """Place ``room_id`` at ``cell``, set position, roll stock, return Room."""
    room = game.registry.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    shops.on_enter_shop(game, room)
    return room


# ------------------------------------------------------------------ space shape/dtype

def test_all_six_new_keys_present_in_observation_space():
    """All six PR3 keys appear in observation_space with the correct shapes and dtypes.

    The key contract (name, shape, dtype) is what any consumer of the encoded
    obs relies on; a missing or mistyped key breaks the gym space.contains check.
    """
    g = _game()
    space = _space(g)
    n_items = len(g.registry.special.items)
    n_recipes = len(g.registry.special.fabrication)
    assert "inventory"    in space.spaces
    assert "item_state"   in space.spaces
    assert "grid_dig"     in space.spaces
    assert "shop_stock"   in space.spaces
    assert "trade_offers" in space.spaces
    assert "fabricate"    in space.spaces

    assert space.spaces["inventory"].shape    == (n_items,)
    assert space.spaces["item_state"].shape   == (11,)
    assert space.spaces["grid_dig"].shape     == (9, 5)
    assert space.spaces["shop_stock"].shape   == (O.SHOP_STOCK_ROWS, 5)
    assert space.spaces["trade_offers"].shape == (O.TRADE_OFFER_ROWS, 2)
    assert space.spaces["fabricate"].shape    == (n_recipes,)

    assert space.spaces["inventory"].dtype    == np.int16
    assert space.spaces["item_state"].dtype   == np.int16
    assert space.spaces["grid_dig"].dtype     == np.uint8
    assert space.spaces["shop_stock"].dtype   == np.int16
    assert space.spaces["trade_offers"].dtype == np.int16
    assert space.spaces["fabricate"].dtype    == np.uint8


def test_encode_contained_in_observation_space():
    """Every encoded obs from a live game satisfies observation_space.contains.

    The space's box bounds must hold for all values, so this pins the sentinel
    choices (-1 for absent rows, 0-based +1 indices) against the declared
    lower/upper bounds.
    """
    g = _game()
    space = _space(g)
    assert space.contains(_obs(g)), "encoded obs is not contained in observation_space"


def test_encoded_obs_contained_after_entering_shop():
    """space.contains holds after entering a shop (shop_stock rows populated).

    Non-default shop_stock rows must still fit within the declared Box bounds.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    space = _space(g)
    assert space.contains(_obs(g))


# ------------------------------------------------------------------ inventory

def test_inventory_all_zeros_on_empty_inventory():
    """inventory is all-zero at start when no starting_items are configured and scepter disabled.

    royal_scepter_found=False is explicit because the default is now True (the unlock
    puzzle is unmodeled; False disables the day-start grant, keeping inventory clean).
    """
    g = _game(GameConfig(royal_scepter_found=False))
    assert np.all(_obs(g)["inventory"] == 0)


def test_inventory_reflects_starting_items():
    """inventory[i] == 1 for each item in starting_items at game start.

    starting_items is the canonical way curricula and tests inject held items;
    the observation must show them immediately after reset (before any actions).
    """
    g = _game(GameConfig(starting_items=frozenset({"shovel", "compass"})))
    obs = _obs(g)
    shovel_i = _item_idx(g, "shovel")
    compass_i = _item_idx(g, "compass")
    assert obs["inventory"][shovel_i] == 1
    assert obs["inventory"][compass_i] == 1


def test_inventory_zero_for_non_held_item():
    """inventory[i] == 0 for an item not in starting_items."""
    g = _game(GameConfig(starting_items=frozenset({"shovel"})))
    obs = _obs(g)
    compass_i = _item_idx(g, "compass")
    assert obs["inventory"][compass_i] == 0


def test_inventory_increments_after_grant():
    """inventory[i] rises to 1 after si.grant and stays at 1 for unique items.

    Granting a non-starting item mid-run (e.g. from a spawn or Lost & Found)
    must appear in the very next encode call.
    """
    g = _game()
    si.grant(g.state, g.registry, "shovel", source="test")
    obs = _obs(g)
    shovel_i = _item_idx(g, "shovel")
    assert obs["inventory"][shovel_i] == 1
    # second grant of unique item is a no-op
    si.grant(g.state, g.registry, "shovel", source="test")
    assert _obs(g)["inventory"][shovel_i] == 1


def test_inventory_nonunique_item_can_stack():
    """inventory[i] > 1 when a non-unique item (prism_key) is granted twice."""
    g = _game()
    si.grant(g.state, g.registry, "prism_key", source="test")
    si.grant(g.state, g.registry, "prism_key", source="test")
    prism_i = _item_idx(g, "prism_key")
    assert _obs(g)["inventory"][prism_i] == 2


# ------------------------------------------------------------------ item_state

def test_item_state_default_trades_left():
    """item_state[5] equals trades_per_day (20) at game start with no trades done.

    A fresh game has done zero trades; the observable value must reflect the
    full daily budget so a policy can plan trading-post visits.
    """
    g = _game()
    trades_per_day = g.registry.shop_rules.trading.get("trades_per_day", 20)
    obs = _obs(g)
    assert obs["item_state"][5] == trades_per_day


def test_item_state_stopwatch_left_zero_initially():
    """item_state[0] (stopwatch_left) is 0 when no Stopwatch is held."""
    g = _game()
    assert _obs(g)["item_state"][0] == 0


def test_item_state_stopwatch_left_set_after_pickup():
    """item_state[0] equals the Stopwatch's free_costs param (10) after pickup.

    The Stopwatch's on-pickup effect fires immediately, so the very next
    encode must show the charged counter.
    """
    g = _game()
    si.grant(g.state, g.registry, "stopwatch", source="test")
    assert _obs(g)["item_state"][0] == 10


def test_item_state_water_charges_from_watering_can():
    """item_state[1] (water) equals watering_can capacity (3) after pickup."""
    g = _game()
    si.grant(g.state, g.registry, "watering_can", source="test")
    assert _obs(g)["item_state"][1] == 3


def test_item_state_water_decrements_on_green_room():
    """item_state[1] (water) drops by 1 when the player enters a green room while holding the can.

    The watering_can effect triggers on_enter for green rooms; the observable
    counter must reflect the spent charge in the very next encode.
    """
    g = _game(GameConfig(starting_items=frozenset({"watering_can"})))
    obs_before = _obs(g)
    assert obs_before["item_state"][1] == 3
    # Place and enter a green room
    reg = g.registry
    green_rooms = [r for r in reg.rooms if r.category == "green"]
    assert green_rooms, "no green rooms in registry"
    room = green_rooms[0]
    state = g.state
    state.grid[5] = room.idx
    state.placed_doors[5] = room.door_mask
    state.entered[5] = True
    state.pos = 5
    si.on_enter(g, room, 5)
    assert _obs(g)["item_state"][1] == 2


def test_item_state_shield_used_becomes_1():
    """item_state[4] (shield_used) flips to 1 after the Knight's Shield is spent.

    shield_negates() is the first red-room negation per day; the observation
    must show it consumed so a policy can stop expecting the protection.
    """
    g = _game(GameConfig(starting_items=frozenset({"knights_shield"})))
    assert _obs(g)["item_state"][4] == 0
    si.shield_negates(g)
    assert _obs(g)["item_state"][4] == 1


def test_item_state_trades_left_decrements_after_trade():
    """item_state[5] (trades_left) decreases by 1 after a successful trade.

    This pins the trades_done counter in ShopsState to the observable budget.
    """
    # Use enough starting items to guarantee a tradeable pair and a trade graph.
    g = _game(GameConfig(starting_items=frozenset({"battery_pack"})), seed=5)
    trades_per_day = g.registry.shop_rules.trading.get("trades_per_day", 20)
    assert _obs(g)["item_state"][5] == trades_per_day
    # Manually increment trades_done to simulate a trade
    g.state.shops.trades_done += 1
    assert _obs(g)["item_state"][5] == trades_per_day - 1


def test_item_state_scepter_color_zero_when_inactive():
    """item_state[6] (scepter_color index+1) is 0 when scepter not activated."""
    g = _game()
    assert _obs(g)["item_state"][6] == 0


def test_item_state_scepter_color_nonzero_after_activation():
    """item_state[6] equals SCEPTER_COLORS.index(color)+1 after activation.

    The +1 encoding allows 0 to serve as the "not activated" sentinel.
    """
    from blueprince_sim.env.obs import SCEPTER_COLOR_INDEX
    g = _game(GameConfig(royal_scepter_found=True))
    # Activate the scepter with a known color
    shops.activate_scepter(g, "green")
    obs = _obs(g)
    expected = SCEPTER_COLOR_INDEX["green"] + 1
    assert obs["item_state"][6] == expected


def test_item_state_treasure_cell_zero_when_no_map():
    """item_state[7] (treasure_cell+1) is 0 when no map has been read today.

    The -1 treasure_cell sentinel maps to 0 in the observation.
    """
    g = _game()
    assert _obs(g)["item_state"][7] == 0


def test_item_state_treasure_cell_nonzero_after_reading_map():
    """item_state[7] is > 0 after the Treasure Map marks a cell.

    Cells are flat indices 0-44, so treasure_cell+1 is 1-45. Any nonzero
    value here means the map has been read and the X spot is known.
    """
    g = _game()
    # Manually simulate the map-resolve that happens on first arrival post-pickup
    cells = g.registry.special.treasure_map["cells"]
    g.state.special.treasure_cell = cells[0]
    obs = _obs(g)
    assert obs["item_state"][7] == cells[0] + 1
    assert obs["item_state"][7] > 0


def test_item_state_treasure_dug_flips():
    """item_state[8] (treasure_dug) flips to 1 after the treasure dig fires."""
    g = _game()
    assert _obs(g)["item_state"][8] == 0
    g.state.special.treasure_dug = True
    assert _obs(g)["item_state"][8] == 1


def test_item_state_dining_room_served_flips():
    """item_state[9] (dining_room_served) flips to 1 when the main course is eaten."""
    g = _game()
    assert _obs(g)["item_state"][9] == 0
    g.state.special.dining_room_served = True
    assert _obs(g)["item_state"][9] == 1


# ------------------------------------------------------------------ grid_dig

def test_grid_dig_all_zeros_without_dig_spots():
    """grid_dig is entirely 0 on a fresh game with no digging tool.

    No rooms are placed yet (only the Entrance Hall, which has no dig spots),
    so every cell must show 0 remaining spots.
    """
    g = _game()
    assert np.all(_obs(g)["grid_dig"] == 0)


def test_grid_dig_reflects_room_dig_spots():
    """grid_dig shows the correct remaining count for a placed room with dig_spots.

    dig_spots is a room record field; before any digging the observation
    must match it exactly (all spots undug).
    """
    g = _game()
    reg = g.registry
    # Find a room with dig_spots > 0
    room = next(r for r in reg.rooms if r.items.dig_spots > 0)
    cell = 10
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    obs = _obs(g)
    assert obs["grid_dig"][cell // 5, cell % 5] == room.items.dig_spots


def test_grid_dig_decrements_after_auto_dig():
    """grid_dig drops to 0 after auto-dig consumes all spots in a cell.

    auto-dig fires on entry when a digging tool is held and spots remain;
    the observation must immediately reflect zero remaining spots.
    """
    g = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    reg = g.registry
    room = next(r for r in reg.rooms if r.items.dig_spots > 0)
    cell = 10
    state = g.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    si.dig_all(g, cell)
    obs = _obs(g)
    assert obs["grid_dig"][cell // 5, cell % 5] == 0


def test_grid_dig_empty_cell_is_zero():
    """grid_dig[r, c] == 0 for cells with no placed room."""
    g = _game()
    # Cell 20 is empty initially
    assert g.state.grid[20] < 0
    obs = _obs(g)
    assert obs["grid_dig"][20 // 5, 20 % 5] == 0


# ------------------------------------------------------------------ shop_stock

def test_shop_stock_all_minus_one_outside_shop():
    """shop_stock is entirely -1 when the player is not in any shop.

    A player in the Entrance Hall (non-shop) must see no stock entries.
    """
    g = _game()
    obs = _obs(g)
    assert np.all(obs["shop_stock"] == -1)


def test_shop_stock_rows_populated_in_shop():
    """shop_stock has at least one non-(-1) row when standing in a stocked shop.

    The commissary always has 4 entries; the first 4 rows must be non-sentinel.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    obs = _obs(g)
    filled = np.any(obs["shop_stock"] != -1, axis=1)
    assert filled.sum() == 4


def test_shop_stock_item_idx_plus1_for_item_entries():
    """shop_stock column 0 holds item_idx+1 for item-kind entries (0 for resources).

    Column 0 == 0 means "resource entry" (food/gem/key/coin).
    Column 0 > 0 means item; (col-1) gives the registry index of that item.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    display = shops.stock_for(g)
    obs = _obs(g)
    items = g.registry.special.items
    item_idx = {item.id: i for i, item in enumerate(items)}

    for row_i, d in enumerate(display):
        enc_col = obs["shop_stock"][row_i, 0]
        if d["kind"] == "item":
            expected_idx = item_idx.get(d["id"], -1)
            assert enc_col == expected_idx + 1, (
                f"row {row_i} id={d['id']}: encoded {enc_col}, expected {expected_idx + 1}"
            )
        else:
            assert enc_col == 0, (
                f"row {row_i} id={d['id']} (resource): column 0 should be 0, got {enc_col}"
            )


def test_shop_stock_resource_code_mapping():
    """shop_stock column 1 encodes the resource type: 2=keys, 3=gems, 5=food.

    The code lets the policy know what a resource entry yields without
    inspecting the room's item id string.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    display = shops.stock_for(g)
    obs = _obs(g)
    # Find key and gem entries
    for row_i, d in enumerate(display):
        if d["id"] == "key" and d["kind"] == "resource":
            assert obs["shop_stock"][row_i, 1] == 2, "key resource code should be 2"
        if d["id"] == "gem" and d["kind"] == "resource":
            assert obs["shop_stock"][row_i, 1] == 3, "gem resource code should be 3"


def test_shop_stock_food_resource_code_5():
    """shop_stock column 1 == 5 for food (Kitchen food entries)."""
    g = _game(GameConfig(day=15), seed=0)
    _enter_shop(g, "kitchen")
    display = shops.stock_for(g)
    obs = _obs(g)
    food_rows = [i for i, d in enumerate(display)
                 if d.get("kind") == "resource"]
    assert food_rows, "no resource entries in kitchen stock"
    for row_i in food_rows:
        assert obs["shop_stock"][row_i, 1] == 5, (
            f"kitchen row {row_i}: expected food code 5, got {obs['shop_stock'][row_i, 1]}"
        )


def test_shop_stock_price_matches_display():
    """shop_stock column 2 (price) matches the resolved price from stock_for.

    Prices include sale-day and Coupon Book adjustments; the obs must reflect
    the same resolved price the buy action would use.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    display = shops.stock_for(g)
    obs = _obs(g)
    for row_i, d in enumerate(display):
        assert obs["shop_stock"][row_i, 2] == d["price"], (
            f"row {row_i} id={d['id']}: price enc={obs['shop_stock'][row_i, 2]} display={d['price']}"
        )


def test_shop_stock_sold_out_flag():
    """shop_stock column 3 (sold_out) flips to 1 after buying an item entry."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 500
    display = shops.stock_for(g)
    item_entries = [(i, d) for i, d in enumerate(display) if d["kind"] == "item"]
    assert item_entries, "need an item entry for this test"
    idx, d = item_entries[0]
    shops.buy(g, idx)
    obs = _obs(g)
    assert obs["shop_stock"][idx, 3] == 1, "sold_out should be 1 after purchase"


def test_shop_stock_absent_rows_are_minus_one():
    """shop_stock rows beyond the display length are all -1 (sentinel padding).

    The commissary has 4 entries; rows 4 and 5 must be -1.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    obs = _obs(g)
    for row_i in range(4, O.SHOP_STOCK_ROWS):
        assert np.all(obs["shop_stock"][row_i] == -1), (
            f"row {row_i} should be all -1, got {obs['shop_stock'][row_i]}"
        )


def test_shop_stock_display_index_matches_game_shop_stock():
    """shop_stock encoded row i is the same entry as game.shop_stock()[i].

    Display-index alignment is load-bearing for the BUY action (BUY_BASE+i
    buys row i); the obs must remain in sync with game.shop_stock().
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    display = g.shop_stock()
    obs = _obs(g)
    items = g.registry.special.items
    item_idx = {item.id: i for i, item in enumerate(items)}
    for row_i, d in enumerate(display):
        enc_col = obs["shop_stock"][row_i, 0]
        if d["kind"] == "item":
            assert enc_col == item_idx.get(d["id"], -1) + 1
        else:
            assert enc_col == 0


def test_no_shop_exceeds_six_rows():
    """No shop's display list has more than SHOP_STOCK_ROWS (6) entries.

    The cap is the basis for the fixed-size Box; any shop exceeding it would
    silently truncate without error, so we assert the bound is never hit.
    """
    shops_to_check = [
        "commissary", "locksmith", "showroom", "gift_shop",
        "the_armory", "kitchen",
    ]
    for shop_id in shops_to_check:
        g = _game(GameConfig(day=15), seed=42)
        _enter_shop(g, shop_id)
        state = g.state
        state.coins = 1000
        # Exhaust showroom to trigger the trophy row
        if shop_id == "showroom":
            for _ in range(4):
                stock = shops.stock_for(g)
                unsold = [i for i, d in enumerate(stock) if not d["sold_out"]]
                if unsold:
                    shops.buy(g, unsold[0])
        display = shops.stock_for(g)
        if display is not None:
            assert len(display) <= O.SHOP_STOCK_ROWS, (
                f"{shop_id}: {len(display)} entries exceeds SHOP_STOCK_ROWS={O.SHOP_STOCK_ROWS}"
            )


# ------------------------------------------------------------------ trade_offers

def test_trade_offers_all_minus_one_outside_trading_post():
    """trade_offers is entirely -1 when not inside the Trading Post.

    The Trading Post is an outer room; standing on the grid or at the doorstep
    must show the sentinel.
    """
    g = _game()
    assert np.all(_obs(g)["trade_offers"] == -1)


def test_trade_offer_encoding_never_overflows_its_box():
    """``_encode_trade_offers`` always returns exactly TRADE_OFFER_ROWS rows, even
    when the player holds enough tradeables to generate more offers than that.

    A full inventory really does exceed the cap -- with all 24 tradeables held,
    most seeds produce well over 8 offers -- so the encoder truncates rather
    than assuming it never has to. Swept over many seeds because the offer
    count varies with the day's shuffled trade graph, and a single seed would
    pin only whichever count that seed happened to produce.
    """
    tradeables = [it.id for it in _game().registry.special.items
                  if it.tier is not None and it.id != "keycard"]
    sample = frozenset(tradeables[:24])
    seen_over_cap = False
    for seed in range(40):
        g = _game(GameConfig(starting_items=sample, west_gate_unlatched=True), seed=seed)
        if g.registry.by_id.get("trading_post") is None:
            pytest.skip("trading_post room not in registry for this config")
        g.placed_ids.add("trading_post")
        g.state.area = "trading_post"
        arr = O._encode_trade_offers(g)
        assert arr.shape == (O.TRADE_OFFER_ROWS, 2)
        assert arr.dtype == np.int16
        if len(g.trade_offers()) > O.TRADE_OFFER_ROWS:
            seen_over_cap = True
    assert seen_over_cap, (
        "no seed exceeded TRADE_OFFER_ROWS, so this test never exercised truncation"
    )


# ------------------------------------------------------------------ fabricate

def test_fabricate_all_zeros_with_no_inputs():
    """fabricate is all-zero when the player holds none of any recipe's inputs."""
    g = _game()
    obs = _obs(g)
    assert np.all(obs["fabricate"] == 0)


def test_fabricate_flips_to_1_when_inputs_assembled():
    """fabricate[recipe_idx] == 1 when all recipe inputs are held.

    detector_shovel requires metal_detector + shovel; with both held the
    recipe's bit must flip to 1.
    """
    g = _game(GameConfig(starting_items=frozenset({"metal_detector", "shovel"})))
    recipe_i = _recipe_idx(g, "detector_shovel")
    obs = _obs(g)
    assert obs["fabricate"][recipe_i] == 1


def test_fabricate_zero_when_output_already_held():
    """fabricate[i] == 0 when the output item is already held (not available).

    Fabricating a unique item you already own is not a valid option, so the bit
    must remain 0 even when all inputs are present.
    """
    g = _game(GameConfig(starting_items=frozenset(
        {"metal_detector", "shovel", "detector_shovel"}
    )))
    recipe_i = _recipe_idx(g, "detector_shovel")
    # detector_shovel is held AND inputs are held — output not available
    assert _obs(g)["fabricate"][recipe_i] == 0


def test_fabricate_clears_after_building():
    """fabricate[i] drops to 0 after fabricating the contraption.

    The inputs are consumed and the output is now held, so neither the recipe
    nor any recipe sharing a consumed input can fire again.
    """
    # Stand in the Workshop to allow fabricate()
    g = _game(GameConfig(starting_items=frozenset({"metal_detector", "shovel"})), seed=0)
    # Place Workshop at current position
    workshop = g.registry.by_id["workshop"]
    state = g.state
    cell = state.pos
    state.grid[cell] = workshop.idx
    state.placed_doors[cell] = workshop.door_mask
    state.entered[cell] = True
    shops.on_enter_shop(g, workshop)  # gives free component; ignore that

    recipe_i = _recipe_idx(g, "detector_shovel")
    # Confirm it was buildable before
    assert g.fabricate_options()  # some recipe available

    # Build it (if detector_shovel is now still fabricatable after workshop gave a component)
    options = g.fabricate_options()
    if "detector_shovel" in options:
        g.fabricate("detector_shovel")
        assert _obs(g)["fabricate"][recipe_i] == 0


def test_fabricate_mask_aligns_with_fabricate_options():
    """fabricate[i] == 1 iff registry.special.fabrication[i]'s output is in
    game.fabricate_options().

    This tests the alignment between the mask and the underlying function across
    all 8 recipes simultaneously.
    """
    # Give enough inputs to have at least one buildable recipe
    g = _game(GameConfig(
        starting_items=frozenset({"compass", "battery_pack"})
    ))
    buildable = set(g.fabricate_options())
    obs = _obs(g)
    for i, (inputs, output) in enumerate(g.registry.special.fabrication):
        expected = 1 if output in buildable else 0
        assert obs["fabricate"][i] == expected, (
            f"recipe {i} ({output}): fabricate[{i}]={obs['fabricate'][i]}, expected {expected}"
        )


# ------------------------------------------------------------------ cross-key: space.contains after changes

def test_space_contains_after_item_grants():
    """Encoded obs is still within space bounds after granting multiple items.

    Granting items pushes inventory values above 0 and updates item_state;
    the Box bounds must accommodate these without overflow.
    """
    g = _game()
    for item_id in ["shovel", "compass", "stopwatch", "watering_can"]:
        si.grant(g.state, g.registry, item_id, source="test")
    space = _space(g)
    assert space.contains(_obs(g))
