"""Shops: stock generation, purchases, and commerce rules."""

import math

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _place_shop(game: Game, room_id: str, cell: int = 7) -> object:
    """Place ``room_id`` at ``cell``, set position, and return the Room object.

    Mimics what Game._enter does for the room-state prerequisites so that
    on_enter_shop can run without driving a full move through the engine.
    """
    reg = game.registry
    room = reg.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    return room


def _enter_shop(game: Game, room_id: str, cell: int = 7) -> object:
    """Place and enter a shop, rolling its stock. Returns the Room."""
    room = _place_shop(game, room_id, cell)
    shops.on_enter_shop(game, room)
    return room


# ---------------------------------------------------------- stock determinism

def test_commissary_stock_is_deterministic_per_seed():
    """The same seed always produces the same commissary stock IDs in the same order.

    Determinism is the foundational invariant: seeded runs must replay identically.
    """
    g1 = _game(seed=77)
    g2 = _game(seed=77)
    _enter_shop(g1, "commissary")
    _enter_shop(g2, "commissary")
    ids1 = [e["id"] for e in g1.state.shops.stock["commissary"]]
    ids2 = [e["id"] for e in g2.state.shops.stock["commissary"]]
    assert ids1 == ids2
    assert len(ids1) == 4


def test_commissary_stock_varies_across_seeds():
    """Different seeds produce different commissary stock at least sometimes.

    Verifies the random selection is actually drawing from the pool, not
    always returning the same fixed subset.
    """
    stocks = set()
    for seed in range(20):
        g = _game(seed=seed)
        _enter_shop(g, "commissary")
        stocks.add(tuple(e["id"] for e in g.state.shops.stock["commissary"]))
    assert len(stocks) > 1


# ---------------------------------------------------------- commissary rules

def test_commissary_offers_exactly_4_distinct_entries():
    """The Commissary always offers exactly 4 distinct stock entries per day.

    The shop spec is 4 slots drawn uniformly without replacement; no duplicates.
    """
    g = _game(seed=42)
    _enter_shop(g, "commissary")
    entries = g.state.shops.stock["commissary"]
    assert len(entries) == 4
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == 4, f"Duplicate entries: {ids}"


def test_commissary_excludes_already_owned_unique_item():
    """The Commissary omits items already in the player's inventory (unique items).

    An owned unique is not available to grant again, so it should never appear
    in the 4-slot offer.
    """
    for seed in range(30):
        g = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=seed)
        _enter_shop(g, "commissary")
        ids = [e["id"] for e in g.state.shops.stock["commissary"]]
        assert "shovel" not in ids, f"seed={seed}: shovel appeared in stock despite being held"


def test_commissary_reserve_not_in_primary_draw():
    """The upgrade_disk_commissary (reserve=true) is excluded from the 4-slot primary draw.

    Reserve entries only fill remaining slots when fewer than 4 primary entries
    are available; with all primary entries available it must never appear.
    """
    for seed in range(50):
        g = _game(seed=seed)
        _enter_shop(g, "commissary")
        ids = [e["id"] for e in g.state.shops.stock["commissary"]]
        assert "upgrade_disk_commissary" not in ids, (
            f"seed={seed}: reserve entry upgrade_disk_commissary appeared"
        )


def test_commissary_stock_not_rerolled_on_second_entry():
    """Entering the same commissary room a second time does not change the stock.

    Stock is rolled once on first entry (room id already in state.shops.stock).
    """
    g = _game(seed=42)
    room = _enter_shop(g, "commissary")
    first = [e["id"] for e in g.state.shops.stock["commissary"]]
    shops.on_enter_shop(g, room)  # second call
    second = [e["id"] for e in g.state.shops.stock["commissary"]]
    assert first == second


# ---------------------------------------------------------- resource purchase

def test_buy_gem_grants_gem_and_spends_coins():
    """Buying the gem entry from the Commissary adds a gem and deducts the price.

    Verifies the resource grant path and exact coin spend.
    """
    g = _game(GameConfig(day=15), seed=42)  # non-sale day: gem costs 3g
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 20
    gems_before = state.gems
    coins_before = state.coins

    stock = shops.stock_for(g)
    gem_entry = next((i, d) for i, d in enumerate(stock) if d["id"] == "gem")
    shops.buy(g, gem_entry[0])

    assert state.gems == gems_before + 1
    assert state.coins == coins_before - gem_entry[1]["price"]


def test_buy_key_grants_key_and_spends_coins():
    """Buying a key entry grants exactly one key and deducts the price in coins."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 50

    stock = shops.stock_for(g)
    key_entry = next((i, d) for i, d in enumerate(stock) if d["id"] == "key")
    keys_before = state.keys
    shops.buy(g, key_entry[0])

    assert state.keys == keys_before + 1


def test_buy_banana_grants_food_steps():
    """Buying a banana (food resource) from the Kitchen restores steps.

    Food items go through the food pipeline (food_steps), so the base 3 steps
    is what the player receives with no modifiers.
    """
    g = _game(GameConfig(day=15), seed=0)
    _enter_shop(g, "kitchen")
    state = g.state
    state.coins = 50
    steps_before = state.steps

    stock = shops.stock_for(g)
    banana = next((i, d) for i, d in enumerate(stock) if d["id"] == "banana")
    shops.buy(g, banana[0])

    assert state.steps > steps_before  # food pipeline applied steps


def test_buy_with_insufficient_coins_raises():
    """Attempting to buy when coins < price raises AssertionError.

    The budget check is a hard invariant: the engine must not grant items to
    a player who cannot pay.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    g.state.coins = 0

    stock = shops.stock_for(g)
    assert stock is not None
    idx = next(i for i, d in enumerate(stock) if not d["sold_out"])
    with pytest.raises(AssertionError):
        shops.buy(g, idx)


# ---------------------------------------------------------- item purchase

def test_buy_item_grants_it_and_marks_sold():
    """Buying an item entry grants it to inventory and marks it sold_out.

    Items never restock; a second query must show sold_out=True.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    item_entries = [(i, d) for i, d in enumerate(stock) if d["kind"] == "item"]
    assert item_entries, "no item entries in commissary stock"
    idx, d = item_entries[0]
    item_id = d["id"]

    shops.buy(g, idx)
    assert si.has(state, item_id)

    stock2 = shops.stock_for(g)
    assert stock2[idx]["sold_out"] is True


def test_buy_item_does_not_restock():
    """A bought item remains sold_out across multiple stock_for queries.

    Restocking would be a bug — item shop slots are one-per-day.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    item_idx = next(i for i, d in enumerate(stock) if d["kind"] == "item")
    shops.buy(g, item_idx)

    for _ in range(3):
        assert shops.stock_for(g)[item_idx]["sold_out"] is True


# ---------------------------------------------------------- price modifiers

def test_sale_day_halves_price_rounded_up():
    """On sale days (20, 21) prices are ceil(price/2), not floor.

    A 3-coin gem becomes 2 (ceil(3/2)), not 1 (floor). A 5-coin item becomes 3.
    """
    # Day 20 is a sale day per shops.json
    g = _game(GameConfig(day=20), seed=42)
    _enter_shop(g, "commissary")
    stock = shops.stock_for(g)

    g2 = _game(GameConfig(day=15), seed=42)
    _enter_shop(g2, "commissary")
    stock2 = shops.stock_for(g2)

    # Price on sale day should equal ceil(non-sale price / 2) for every entry
    for d, d2 in zip(stock, stock2, strict=True):
        assert d["id"] == d2["id"]
        expected = math.ceil(d2["price"] / 2)
        assert d["price"] == expected, (
            f"{d['id']}: sale={d['price']} expected {expected} (base {d2['price']})"
        )


def test_non_sale_day_prices_not_halved():
    """Outside sale days (e.g. day 15) prices are the full listed values."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    stock = shops.stock_for(g)
    # shovel is 6g; if halved it would be 3g — must be 6g on day 15
    shovel_d = next((d for d in stock if d["id"] == "shovel"), None)
    if shovel_d is not None:
        assert shovel_d["price"] == 6


def test_coupon_book_reduces_price_by_1():
    """A held Coupon Book reduces each displayed price by 1 (floor 0).

    The coupon applies at display time, not as a post-buy refund.
    """
    g_plain = _game(GameConfig(day=15), seed=42)
    _enter_shop(g_plain, "commissary")
    plain_stock = shops.stock_for(g_plain)

    g_coupon = _game(GameConfig(day=15, starting_items=frozenset({"coupon_book"})), seed=42)
    _enter_shop(g_coupon, "commissary")
    coupon_stock = shops.stock_for(g_coupon)

    for d, dc in zip(plain_stock, coupon_stock, strict=True):
        assert d["id"] == dc["id"]
        expected = max(0, d["price"] - 1)
        assert dc["price"] == expected, (
            f"{d['id']}: plain={d['price']} coupon={dc['price']} expected={expected}"
        )


def test_coupon_book_floors_at_0():
    """The Coupon Book can bring a 1-coin price to 0, never to a negative value."""
    g = _game(GameConfig(day=20, starting_items=frozenset({"coupon_book"})), seed=42)
    _enter_shop(g, "commissary")
    stock = shops.stock_for(g)
    for d in stock:
        assert d["price"] >= 0, f"{d['id']} price went negative: {d['price']}"


# ---------------------------------------------------------- locksmith

def test_locksmith_special_key_is_one_of_four_valid_ids():
    """The Locksmith's special key offer is always one of the four valid key ids.

    Valid: silver_key, secret_garden_key, prism_key, car_keys.
    """
    valid = {"silver_key", "secret_garden_key", "prism_key", "car_keys"}
    for seed in range(30):
        g = _game(seed=seed)
        _enter_shop(g, "locksmith")
        offer = g.state.shops.special_key_offer
        assert offer in valid, f"seed={seed}: unexpected special key {offer!r}"


def test_locksmith_special_key_silver_majority():
    """Over many seeds, silver_key and secret_garden_key together are the majority offer.

    With the 30/40/30 roll distribution and availability filtering, common keys
    (silver_key, secret_garden_key, prism_key) dominate; car_keys is fallback only.
    """
    counts: dict[str, int] = {}
    for seed in range(100):
        g = _game(seed=seed)
        _enter_shop(g, "locksmith")
        kid = g.state.shops.special_key_offer
        counts[kid] = counts.get(kid, 0) + 1
    # silver+secret_garden+prism should account for the vast majority
    common = counts.get("silver_key", 0) + counts.get("secret_garden_key", 0) + counts.get("prism_key", 0)
    assert common >= 90, f"expected >= 90 common keys out of 100; got {common}, counts={counts}"


def test_locksmith_special_key_one_per_day():
    """After the Locksmith's special key is bought, it shows as sold_out."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "locksmith")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    special_idx = next(i for i, d in enumerate(stock) if d.get("id") == state.shops.special_key_offer)
    shops.buy(g, special_idx)

    stock2 = shops.stock_for(g)
    special_entry = next(d for d in stock2 if d["id"] == state.shops.special_key_offer)
    assert special_entry["sold_out"] is True


def test_locksmith_robbery_grants_24_keys():
    """Entering the Locksmith with a Powered Electromagnet grants exactly 24 keys.

    The Electromagnet auto-collects the four wall racks (modeled as a flat 24).
    """
    g = _game(GameConfig(starting_items=frozenset({"powered_electromagnet"})), seed=42)
    state = g.state
    keys_before = state.keys
    _enter_shop(g, "locksmith")
    assert state.keys - keys_before == 24


def test_locksmith_robbery_sets_robbed_flag():
    """After robbery, state.shops.locksmith_robbed is True."""
    g = _game(GameConfig(starting_items=frozenset({"powered_electromagnet"})), seed=42)
    _enter_shop(g, "locksmith")
    assert g.state.shops.locksmith_robbed is True


def test_locksmith_robbery_disables_key_entries():
    """After robbery, the key and set_of_3_keys entries are sold_out."""
    g = _game(GameConfig(starting_items=frozenset({"powered_electromagnet"})), seed=42)
    _enter_shop(g, "locksmith")
    stock = shops.stock_for(g)
    key_entry = next((d for d in stock if d["id"] == "key" and not d.get("special_key")), None)
    set3_entry = next((d for d in stock if d["id"] == "set_of_3_keys"), None)
    assert key_entry is not None and key_entry["sold_out"] is True
    assert set3_entry is not None and set3_entry["sold_out"] is True


def test_locksmith_robbery_does_not_disable_special_key():
    """After robbery, the special key offer remains available for purchase.

    The wiki confirms the Electromagnet does not take the special-key slot.
    """
    g = _game(GameConfig(starting_items=frozenset({"powered_electromagnet"})), seed=42)
    _enter_shop(g, "locksmith")
    state = g.state
    stock = shops.stock_for(g)
    special_entry = next((d for d in stock if d.get("id") == state.shops.special_key_offer), None)
    assert special_entry is not None
    assert special_entry["sold_out"] is False


def test_locksmith_no_robbery_without_electromagnet():
    """Without the Electromagnet the Locksmith robbery never fires."""
    for seed in range(10):
        g = _game(seed=seed)
        _enter_shop(g, "locksmith")
        assert g.state.shops.locksmith_robbed is False
        assert g.state.keys == 0


# ---------------------------------------------------------- showroom

def test_showroom_picks_2_from_tier_a_and_2_from_tier_b():
    """The Showroom always offers 2 tier_a items and 2 tier_b items.

    tier_a ids: moon_pendant, chronograph, silver_spoon.
    tier_b ids: ornate_compass, emerald_bracelet, master_key.
    Exactly 2 from each tier must appear.
    """
    tier_a = {"moon_pendant", "chronograph", "silver_spoon"}
    tier_b = {"ornate_compass", "emerald_bracelet", "master_key"}

    for seed in range(20):
        g = _game(seed=seed)
        _enter_shop(g, "showroom")
        entries = g.state.shops.stock["showroom"]
        ids = [e["id"] for e in entries]
        a_count = sum(1 for i in ids if i in tier_a)
        b_count = sum(1 for i in ids if i in tier_b)
        assert a_count == 2, f"seed={seed}: expected 2 tier_a, got {a_count} ({ids})"
        assert b_count == 2, f"seed={seed}: expected 2 tier_b, got {b_count} ({ids})"


def test_showroom_avoids_already_owned_items():
    """The Showroom excludes items already in inventory from both tiers.

    An owned unique item passes _is_available=False and must be absent.
    """
    for seed in range(20):
        g = _game(GameConfig(starting_items=frozenset({"chronograph", "master_key"})), seed=seed)
        _enter_shop(g, "showroom")
        ids = [e["id"] for e in g.state.shops.stock["showroom"]]
        assert "chronograph" not in ids, f"seed={seed}: owned chronograph appeared"
        assert "master_key" not in ids, f"seed={seed}: owned master_key appeared"


def test_showroom_trophy_absent_before_buying_all():
    """The Trophy is not shown until all 4 displayed showroom items are sold.

    The trophy is appended dynamically; with unsold entries it must not appear.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "showroom")
    stock = shops.stock_for(g)
    assert all(d["id"] != "trophy_of_wealth" for d in stock)
    assert len(stock) == 4


def test_showroom_trophy_appears_after_buying_all():
    """The Trophy of Wealth appears in stock_for once all 4 displayed items are bought.

    After the last purchase the length grows to 5 with the trophy at the end.
    """
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "showroom")
    state = g.state
    state.coins = 500

    # Buy all 4 items
    for _ in range(4):
        stock = shops.stock_for(g)
        idx = next(i for i, d in enumerate(stock) if not d["sold_out"])
        shops.buy(g, idx)

    stock = shops.stock_for(g)
    assert len(stock) == 5
    assert stock[-1]["id"] == "trophy_of_wealth"
    assert stock[-1]["sold_out"] is False


def test_showroom_trophy_absent_if_already_owned():
    """If the player already owns the Trophy of Wealth it is never shown.

    Buying it twice would be a bug; owned unique items must be gated out.
    """
    g = _game(GameConfig(day=15, starting_items=frozenset({"trophy_of_wealth"})), seed=42)
    _enter_shop(g, "showroom")
    state = g.state
    state.coins = 500
    for _ in range(4):
        stock = shops.stock_for(g)
        idx = next((i for i, d in enumerate(stock) if not d["sold_out"]), None)
        if idx is None:
            break
        shops.buy(g, idx)

    stock = shops.stock_for(g)
    assert all(d["id"] != "trophy_of_wealth" for d in stock)


# ---------------------------------------------------------- gift shop

def test_gift_shop_excludes_lunch_box_when_unlocked():
    """The Gift Shop does not list the lunch_box when lunch_box_unlocked is True.

    The lunch_box is a one-time unlock; once purchased it spawns in Dining Rooms
    instead, so the shop must not offer it again.
    """
    g = _game(GameConfig(lunch_box_unlocked=True), seed=0)
    _enter_shop(g, "gift_shop")
    stock = shops.stock_for(g)
    assert stock is not None
    assert all(d["id"] != "lunch_box" for d in stock)


def test_gift_shop_shows_lunch_box_when_not_unlocked():
    """The Gift Shop lists the lunch_box when lunch_box_unlocked is False (default)."""
    g = _game(GameConfig(lunch_box_unlocked=False), seed=0)
    _enter_shop(g, "gift_shop")
    stock = shops.stock_for(g)
    assert any(d["id"] == "lunch_box" for d in stock)


def test_gift_shop_cursed_coffers_without_sledge_hammer_raises():
    """Buying cursed_coffers without a Sledge Hammer raises AssertionError.

    The container requires the sledge_hammer in inventory; an attempt without
    it must be rejected hard so the action space cannot accidentally allow it.
    """
    g = _game(GameConfig(), seed=0)
    _enter_shop(g, "gift_shop")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    coffers_idx = next(
        (i for i, d in enumerate(stock) if d["id"] == "cursed_coffers"), None
    )
    if coffers_idx is None:
        pytest.skip("cursed_coffers not in gift_shop stock (already unlocked config)")
    # The display marks the unmet requirement as blocked, and buy refuses it
    # (the same "blocked" bit keeps the env BUY action masked off).
    assert shops.stock_for(g)[coffers_idx]["blocked"]
    with pytest.raises(AssertionError, match="requires an item not held"):
        shops.buy(g, coffers_idx)


def test_gift_shop_cursed_coffers_with_sledge_hammer_grants_effigy():
    """Buying cursed_coffers with a Sledge Hammer grants the Cursed Effigy.

    The effigy's set_steps_on_pickup effect fires immediately (steps clamped to
    13 from above), confirming the grant pipeline runs correctly.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=0)
    _enter_shop(g, "gift_shop")
    state = g.state
    state.coins = 100
    state.steps = 50  # above 13 so the clamp fires

    stock = shops.stock_for(g)
    coffers_idx = next(
        (i for i, d in enumerate(stock) if d["id"] == "cursed_coffers"), None
    )
    if coffers_idx is None:
        pytest.skip("cursed_coffers not in gift_shop stock (already unlocked config)")

    shops.buy(g, coffers_idx)

    assert si.has(state, "cursed_effigy")
    assert state.steps == 13  # set_steps_on_pickup clamped from 50


def test_gift_shop_cursed_coffers_clamps_steps_to_13_from_above():
    """Cursed Effigy pickup via cursed_coffers always clamps steps to exactly 13 from above.

    Steps at or below 13 are not increased — only the over-budget case is penalised.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=0)
    _enter_shop(g, "gift_shop")
    state = g.state
    state.coins = 100
    state.steps = 10  # below 13: must stay 10

    stock = shops.stock_for(g)
    coffers_idx = next(
        (i for i, d in enumerate(stock) if d["id"] == "cursed_coffers"), None
    )
    if coffers_idx is None:
        pytest.skip("cursed_coffers not in gift_shop stock")

    shops.buy(g, coffers_idx)
    assert state.steps == 10  # unchanged (below threshold)


def test_gift_shop_cursed_coffers_records_unlock_in_gift_unlocks():
    """Buying the Cursed Coffers records 'cursed_effigy_unlocked' in state.shops.gift_unlocks.

    The gift_unlocks list feeds the carryover() report for multi-day sessions.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=0)
    _enter_shop(g, "gift_shop")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    coffers_idx = next(
        (i for i, d in enumerate(stock) if d["id"] == "cursed_coffers"), None
    )
    if coffers_idx is None:
        pytest.skip("cursed_coffers not in gift_shop stock")

    shops.buy(g, coffers_idx)
    assert "cursed_effigy_unlocked" in state.shops.gift_unlocks


def test_gift_shop_lunch_box_purchase_records_unlock():
    """Buying the lunch_box records 'lunch_box_unlocked' in state.shops.gift_unlocks."""
    g = _game(GameConfig(lunch_box_unlocked=False, day=15), seed=0)
    _enter_shop(g, "gift_shop")
    state = g.state
    state.coins = 100

    stock = shops.stock_for(g)
    lb_idx = next((i for i, d in enumerate(stock) if d["id"] == "lunch_box"), None)
    if lb_idx is None:
        pytest.skip("lunch_box not in gift_shop stock")

    shops.buy(g, lb_idx)
    assert "lunch_box_unlocked" in state.shops.gift_unlocks


# ---------------------------------------------------------- current_shop_id

def test_current_shop_id_returns_none_outside_shop():
    """current_shop_id returns None when the player is not in a shop room."""
    g = _game(seed=0)
    # Player starts in the Entrance Hall (not a shop)
    assert shops.current_shop_id(g) is None


def test_current_shop_id_returns_room_id_in_shop():
    """current_shop_id returns the correct room id when standing in a shop cell."""
    g = _game(seed=0)
    _place_shop(g, "commissary", cell=7)
    assert shops.current_shop_id(g) == "commissary"


# ---------------------------------------------------------- stock_for edge cases

def test_stock_for_returns_none_outside_shop():
    """stock_for returns None when the player is not in any shop."""
    g = _game(seed=0)
    assert shops.stock_for(g) is None


def test_stock_for_returns_none_before_stock_rolled():
    """stock_for returns None when placed in a shop cell but on_enter_shop never ran."""
    g = _game(seed=0)
    _place_shop(g, "commissary", cell=7)
    # stock not rolled yet
    assert shops.stock_for(g) is None


def test_stock_for_affordable_flag():
    """The affordable flag reflects whether current coins cover the displayed price."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 0  # can't afford anything

    stock = shops.stock_for(g)
    assert all(not d["affordable"] for d in stock)

    state.coins = 1000  # can afford everything
    stock2 = shops.stock_for(g)
    assert all(d["affordable"] for d in stock2)


# ---------------------------------------------------------- resource limit

def test_commissary_gem_limit_tracks_purchases():
    """The gem entry becomes sold_out after its limit (5) purchases."""
    g = _game(GameConfig(day=15), seed=42)
    _enter_shop(g, "commissary")
    state = g.state
    state.coins = 500

    # Find gem entry
    stock = shops.stock_for(g)
    gem_idx = next((i for i, d in enumerate(stock) if d["id"] == "gem"), None)
    if gem_idx is None:
        pytest.skip("gem not in commissary stock for this seed")

    # Buy up to the limit (5)
    for _ in range(5):
        s = shops.stock_for(g)
        if s[gem_idx]["sold_out"]:
            break
        shops.buy(g, gem_idx)

    final = shops.stock_for(g)
    assert final[gem_idx]["sold_out"] is True


# ---------------------------------------------------------- armory (simple shop)

def test_armory_all_4_entries_available():
    """The Armory lists all 4 entries (no availability filtering needed for non-unique items).

    knights_shield, morning_star, torch, the_axe are all unique items that start
    unowned, so all 4 should be available on a fresh game.
    """
    g = _game(GameConfig(day=15), seed=0)
    _enter_shop(g, "the_armory")
    entries = g.state.shops.stock["the_armory"]
    ids = [e["id"] for e in entries]
    assert "knights_shield" in ids
    assert "morning_star" in ids
    assert "torch" in ids
    assert "the_axe" in ids
    assert len(entries) == 4
