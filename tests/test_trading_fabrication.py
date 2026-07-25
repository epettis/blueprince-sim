"""Trading Post trades and Workshop fabrication (shops.py PR2-C)."""

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_LOCKED, segment_key


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _place_workshop(game: Game, cell: int = 7) -> object:
    """Place the Workshop at ``cell``, set pos, and return the Room object.

    Does NOT enter (no on_enter_shop call), mirroring test_shops._place_shop.
    """
    room = game.registry.by_id["workshop"]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    return room


def _enter_workshop(game: Game, cell: int = 7) -> object:
    """Place and enter the Workshop, rolling its first-entry free component."""
    room = _place_workshop(game, cell)
    shops.on_enter_shop(game, room)
    return room


def _set_trading_post_inner(game: Game) -> None:
    """Fake the player being inside the Trading Post outer room.

    Sets outer_loc=2 and adds trading_post to placed_ids, replicating what
    open_outer_draft + enter_outer_room would do without driving the full
    outer-area machinery.
    """
    game.state.outer_loc = 2
    game.placed_ids.add("trading_post")


def _give_items(game: Game, *item_ids: str) -> None:
    """Grant items directly to inventory (bypassing special_items.grant effects)."""
    state = game.state
    for iid in item_ids:
        state.inventory[iid] = state.inventory.get(iid, 0) + 1


# ================================================================= TRADING POST

# ---------------------------------------------------------- offers gating

def test_trade_offers_empty_outside_trading_post():
    """trade_offers returns [] when the player is not inside the Trading Post.

    The offers list is only active at outer_loc==2 with trading_post placed;
    querying from any other position must return empty.
    """
    game = _game(seed=0)
    _give_items(game, "shovel")
    assert shops.trade_offers(game) == []


def test_trade_offers_empty_after_trades_per_day_used():
    """trade_offers returns [] once all three daily trade slots are consumed.

    The Trading Post enforces a hard cap of trades_per_day (3 per shops.json).
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel", "compass", "sleeping_mask",
                                                       "salt_shaker"})), seed=0)
    _set_trading_post_inner(game)
    # Use all 3 slots
    for _ in range(3):
        offers = shops.trade_offers(game)
        if not offers:
            break
        shops.trade(game, offers[0]["give"])
    assert shops.trade_offers(game) == []


def test_trade_offers_lists_only_tradeable_items():
    """trade_offers includes only items whose SpecialItem.tier is not None.

    royal_scepter (tier=None) and broken_lever (tier=None) must not appear;
    shovel (tier=2) must appear.
    """
    game = _game(seed=0)
    # royal_scepter is gated out by configure(); use broken_lever which is tier=None
    # and shovel which is tier=2
    state = game.state
    state.inventory["broken_lever"] = 1
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)

    offers = shops.trade_offers(game)
    give_ids = {o["give"] for o in offers}
    assert "shovel" in give_ids, "shovel (tier=2) should be tradeable"
    assert "broken_lever" not in give_ids, "broken_lever (tier=None) must not appear"


def test_trade_offers_excludes_keycard():
    """trade_offers never includes the keycard even if it were in the inventory.

    The keycard lives on state.has_keycard; it is excluded by the id guard.
    """
    game = _game(seed=0)
    game.state.inventory["keycard"] = 1  # hypothetically; bypassing pipeline guard
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    assert all(o["give"] != "keycard" for o in offers)


def test_trade_offers_sorted_by_id():
    """trade_offers is sorted by item id for deterministic ordering.

    Sorted order is required so the env's action-space index is stable across runs.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel", "compass",
                                                       "sleeping_mask", "salt_shaker"})), seed=0)
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    ids = [o["give"] for o in offers]
    assert ids == sorted(ids), f"offers not sorted: {ids}"


def test_trade_offers_tier_matches_item_data():
    """Each offer's tier matches the SpecialItem.tier from the registry."""
    game = _game(GameConfig(starting_items=frozenset({"shovel", "lock_pick_kit"})), seed=0)
    _set_trading_post_inner(game)
    reg = game.registry
    for offer in shops.trade_offers(game):
        item = reg.special.by_id[offer["give"]]
        assert offer["tier"] == item.tier, (
            f"{offer['give']}: offer tier {offer['tier']} != item tier {item.tier}"
        )


# ---------------------------------------------------------- trade mechanics

def test_trade_removes_given_item_from_inventory():
    """Calling trade removes exactly one copy of give_id from the inventory.

    The item is returned to the spawn pool (consumed=False), not burned.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    _set_trading_post_inner(game)
    assert si.has(game.state, "shovel")
    shops.trade(game, "shovel")
    assert not si.has(game.state, "shovel"), "shovel should be removed after trade"


def test_trade_does_not_add_given_item_to_removed():
    """A traded item is NOT added to state.special.removed (pool return, not consumed).

    Traded items can respawn; consumed items cannot. This is the key semantic
    difference between trade(consumed=False) and consuming items like lock picks.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    _set_trading_post_inner(game)
    shops.trade(game, "shovel")
    assert "shovel" not in game.state.special.removed, (
        "traded item must not enter removed list (would prevent respawn)"
    )


def test_trade_grants_exactly_one_thing():
    """Each trade grants exactly one item or resource to the player.

    The items_found_log grows by exactly one entry per trade call.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    _set_trading_post_inner(game)
    log_len_before = len(game.state.items_found_log)
    shops.trade(game, "shovel")
    assert len(game.state.items_found_log) == log_len_before + 1, (
        "exactly one item/resource must be logged per trade"
    )


def test_trade_increments_trades_done():
    """Each successful trade increments state.shops.trades_done by 1."""
    game = _game(GameConfig(starting_items=frozenset({"shovel", "compass"})), seed=0)
    _set_trading_post_inner(game)
    assert game.state.shops.trades_done == 0
    shops.trade(game, "shovel")
    assert game.state.shops.trades_done == 1


def test_trade_requires_active_offer():
    """trade() raises AssertionError when no offer exists for give_id.

    Prevents acting on stale or fabricated give_ids.
    """
    game = _game(seed=0)
    _set_trading_post_inner(game)
    with pytest.raises(AssertionError):
        shops.trade(game, "shovel")  # not held -> no offer


def test_trade_same_tier_return():
    """A non-dice non-t5 trade returns an item of the same tier as give_id.

    Across many seeds, the returned item's tier always equals the input tier.
    We seed-hunt for returns that are not dice (die has no tier) and check tier.
    """
    tier_returns_correct = True
    checked = 0
    for seed in range(200):
        game = _game(seed=seed)
        state = game.state
        # Give a tier-2 item and clear the registry so no items of other tiers
        # are in the way — just check whatever comes back
        state.inventory["compass"] = 1  # tier 2
        _set_trading_post_inner(game)
        log_before = list(state.items_found_log)
        shops.trade(game, "compass")
        new_entries = state.items_found_log[len(log_before):]
        if not new_entries:
            continue
        kind, _ = new_entries[0]
        if kind == "die":
            continue  # dice outcome: tier doesn't apply
        # The return should be a tier-2 item
        reg = game.registry
        item = reg.special.by_id.get(kind)
        if item is None:
            continue  # resource entry
        if item.tier != 2:
            tier_returns_correct = False
            break
        checked += 1
        if checked >= 10:
            break
    assert tier_returns_correct, "non-dice trade return had wrong tier"


def test_trade_t5_sometimes_yields_allowance_or_upgrade():
    """A tier-5 trade sometimes returns allowance_token or upgrade_disk.

    With t5_special_chance=50%, across many seeds we should see at least one
    allowance_token or upgrade_disk among the returns.
    """
    specials_seen = set()
    for seed in range(200):
        game = _game(seed=seed)
        state = game.state
        state.inventory["master_key"] = 1  # tier 5
        _set_trading_post_inner(game)
        log_before = len(state.items_found_log)
        shops.trade(game, "master_key")
        new_entries = state.items_found_log[log_before:]
        for kind, _ in new_entries:
            if kind in ("allowance_token", "upgrade_disk"):
                specials_seen.add(kind)
    assert specials_seen, (
        f"expected some t5 trades to yield allowance_token/upgrade_disk; got {specials_seen}"
    )


def test_trade_dice_sentinel_in_graph_yields_die():
    """An item whose trade_graph successor is "dice" yields a die when traded.

    The graph model replaces the old per-roll outcome with a fixed mapping.
    Directly crafting a trade_graph with a "dice" sentinel confirms the die path.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1  # tier 2
    _set_trading_post_inner(game)
    # Directly set the graph so shovel → "dice"
    state.shops.trade_graph = {"shovel": "dice"}
    state.shops.trade_graph_rolled = True
    log_before = len(state.items_found_log)
    shops.trade(game, "shovel")
    new_entries = state.items_found_log[log_before:]
    assert any(kind == "die" for kind, _ in new_entries), (
        "expected a die when the trade graph maps shovel to 'dice'"
    )


def test_trade_graph_rolled_lazily_on_first_offer():
    """The trade graph is rolled lazily on the first trade_offers call inside the post.

    Before any call, trade_graph_rolled is False.  After, it is True.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    assert not state.shops.trade_graph_rolled, "graph must not be rolled before first query"
    shops.trade_offers(game)
    assert state.shops.trade_graph_rolled, "graph must be rolled after first query inside post"


def test_trade_graph_deterministic_per_seed():
    """Two games with the same seed produce identical trade graphs.

    Graph determinism is the prerequisite for offer determinism.
    """
    for seed in range(5):
        g1 = _game(seed=seed)
        g2 = _game(seed=seed)
        for g in (g1, g2):
            g.state.inventory["shovel"] = 1
            _set_trading_post_inner(g)
            shops.trade_offers(g)  # trigger lazy roll
        assert g1.state.shops.trade_graph == g2.state.shops.trade_graph, (
            f"seed={seed}: trade graphs differ"
        )


def test_trade_graph_fixed_for_day():
    """Calling trade_offers a second time does not re-roll the graph.

    The graph rolled on first entry is reused for every subsequent offer
    query within the same day.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)
    graph_first = dict(state.shops.trade_graph)
    shops.trade_offers(game)
    assert state.shops.trade_graph == graph_first, "trade graph must not change after first roll"


def test_trade_graph_covers_all_tradeable_items():
    """Every tradeable item (tier not None, id not keycard) appears as a key in the graph."""
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)  # trigger roll
    reg = game.registry
    tradeable_ids = {
        it.id for it in reg.special.items
        if it.tier is not None and it.id != "keycard"
    }
    assert tradeable_ids == set(state.shops.trade_graph.keys()), (
        "trade graph must contain exactly the tradeable item ids"
    )


def test_trade_graph_successors_same_tier_or_sentinel():
    """Every item in the graph points to a same-tier item or an allowed sentinel.

    Items must only cycle within their own tier.  Dice/allowance_token/upgrade_disk
    are permitted cross-tier sentinels.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)
    reg = game.registry
    sentinels = {"dice", "allowance_token", "upgrade_disk"}
    for give_id, successor in state.shops.trade_graph.items():
        if successor in sentinels:
            continue
        give_item = reg.special.by_id[give_id]
        succ_item = reg.special.by_id.get(successor)
        assert succ_item is not None, f"{give_id!r} points to unknown id {successor!r}"
        assert give_item.tier == succ_item.tier, (
            f"{give_id!r} (tier {give_item.tier}) points to {successor!r} (tier {succ_item.tier})"
        )


def test_trade_offer_receive_never_already_held():
    """An offer's receive is never an item the player already holds.

    The skip-held walk must step past held items when resolving the terminal.
    """
    game = _game(seed=0)
    state = game.state
    # Give two tier-2 items: whichever one points to the other as successor,
    # the offer for the first must not show the second as receive while it is held.
    state.inventory["shovel"] = 1
    state.inventory["compass"] = 1
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    held = {iid for iid, cnt in state.inventory.items() if cnt > 0}
    for offer in offers:
        receive = offer.get("receive")
        if receive is not None and receive not in {"dice", "allowance_token", "upgrade_disk"}:
            assert receive not in held, (
                f"offer for {offer['give']!r} shows receive={receive!r} which is already held"
            )


def test_trade_self_cycle_item_untradeable():
    """An item in a 1-item tier cycle (pointing to itself) has no trade offer.

    In the graph model a self-edge means the item cannot be traded.
    Directly overriding the graph confirms the untradeable path.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1  # tier 2
    _set_trading_post_inner(game)
    # Overwrite graph so shovel is a self-cycle
    state.shops.trade_graph = {"shovel": "shovel"}
    state.shops.trade_graph_rolled = True
    offers = shops.trade_offers(game)
    assert all(o["give"] != "shovel" for o in offers), (
        "shovel self-cycle must not produce a trade offer"
    )


def test_trade_milking_loop_runs_until_trades_per_day():
    """An A→B→A two-cycle can be milked, and ONLY trades_per_day stops it.

    The real game lets a 2-cycle hand items back and forth indefinitely, so
    the daily trade cap is the loop bound — the spawn pipeline's
    once-per-day uniqueness must not block a trade return.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1  # hold only one side of the 2-cycle (tier 2)
    _set_trading_post_inner(game)
    # Force a 2-cycle: shovel → compass → shovel
    state.shops.trade_graph = {"shovel": "compass", "compass": "shovel"}
    state.shops.trade_graph_rolled = True
    trading = game.registry.shop_rules.trading
    trades_per_day = trading.get("trades_per_day", 3)
    trades_done = 0
    while True:
        offers = shops.trade_offers(game)
        if not offers:
            break
        shops.trade(game, offers[0]["give"])
        trades_done += 1
        assert trades_done <= trades_per_day, "milking loop exceeded trades_per_day"
    assert trades_done == trades_per_day, "the cap, not availability, must stop the loop"
    assert state.shops.trades_done == trades_per_day


def test_trade_offer_receive_exposed_before_trading():
    """Each offer includes a 'receive' key showing the terminal before the player commits.

    The real game exposes what you'll get before the trade is accepted.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    for offer in offers:
        assert "receive" in offer, f"offer for {offer['give']!r} is missing 'receive' key"
        assert offer["receive"] is not None, "receive must not be None for a live offer"


def test_trade_deterministic_per_seed():
    """Two games with the same seed produce the same trade outcome.

    Determinism is the foundational invariant for seeded runs.
    """
    for seed in range(5):
        g1 = _game(seed=seed)
        g2 = _game(seed=seed)
        for g in (g1, g2):
            g.state.inventory["shovel"] = 1
            _set_trading_post_inner(g)
        shops.trade(g1, "shovel")
        shops.trade(g2, "shovel")
        assert g1.state.items_found_log == g2.state.items_found_log, (
            f"seed={seed}: trade outcomes differ"
        )


# ================================================================= WORKSHOP

# ---------------------------------------------------------- free component on first entry

def test_workshop_grants_component_on_first_entry():
    """Entering the Workshop for the first time grants a component from the recipe inputs.

    The free component is documented behavior: the Workshop gives one component
    on first entry, drawn from the union of all fabrication input ids.
    """
    game = _game(seed=0)
    reg = game.registry
    component_ids = set()
    for inputs, _ in reg.special.fabrication:
        component_ids.update(inputs)

    log_before = len(game.state.items_found_log)
    _enter_workshop(game)
    new_entries = game.state.items_found_log[log_before:]
    assert new_entries, "Workshop first entry should grant something"
    granted_ids = {kind for kind, _ in new_entries if kind != "coins"}
    assert granted_ids <= component_ids or any(kind == "coins" for kind, _ in new_entries), (
        f"Workshop granted {granted_ids} which are not all component ids; "
        f"expected a component from {component_ids}"
    )


def test_workshop_component_from_component_set():
    """The Workshop free component is always a fabrication input id (when available).

    Over many seeds without any held items, the granted id must be in the
    union of all recipe input ids.
    """
    game_reg = _game(seed=0).registry
    component_ids = set()
    for inputs, _ in game_reg.special.fabrication:
        component_ids.update(inputs)

    for seed in range(20):
        game = _game(seed=seed)
        log_before = len(game.state.items_found_log)
        _enter_workshop(game)
        new_entries = game.state.items_found_log[log_before:]
        for kind, _ in new_entries:
            if kind == "coins":
                continue
            assert kind in component_ids, (
                f"seed={seed}: Workshop granted {kind!r} which is not a component"
            )


def test_workshop_free_component_only_on_first_entry():
    """The Workshop free component fires only once per day (once-per-day guard).

    A second on_enter_shop call must not grant another component.
    """
    game = _game(seed=0)
    room = _enter_workshop(game)
    log_after_first = list(game.state.items_found_log)
    # Second entry: guard should prevent any new grant
    shops.on_enter_shop(game, room)
    assert game.state.items_found_log == log_after_first, (
        "Workshop second entry must not grant another component"
    )


def test_workshop_fallback_5_coins_when_all_components_unavailable():
    """When all component ids are already held (unavailable), the Workshop grants 5 coins.

    This is the documented fallback: a player who already owns every component
    gets coins instead of a duplicate.
    """
    game = _game(seed=0)
    # Pre-fill all component ids so _is_available returns False for each
    reg = game.registry
    component_ids = set()
    for inputs, _ in reg.special.fabrication:
        component_ids.update(inputs)
    for cid in component_ids:
        game.state.inventory[cid] = 1

    coins_before = game.state.coins
    _enter_workshop(game)
    assert game.state.coins >= coins_before + 5, (
        f"expected at least 5 coins fallback; coins went from {coins_before} to {game.state.coins}"
    )
    assert ("coins", 5) in game.state.items_found_log, "fallback coins must be logged"


def test_workshop_stock_set_to_empty_list_after_entry():
    """After first entry the Workshop stock key is set (to []), enabling the guard.

    The once-per-day gate checks 'workshop' in state.shops.stock.
    """
    game = _game(seed=0)
    assert "workshop" not in game.state.shops.stock
    _enter_workshop(game)
    assert "workshop" in game.state.shops.stock
    assert game.state.shops.stock["workshop"] == []


# ---------------------------------------------------------- fabricate_options

def test_fabricate_options_visible_outside_workshop_but_action_gated():
    """fabricate_options is a pure inventory query usable anywhere, while
    fabricate() itself still requires standing in the Workshop.

    A policy can see from afar that its items could become a contraption
    (e.g. a lockpick upgrade when short on keys) and plan the walk there.
    """
    game = _game(GameConfig(starting_items=frozenset({"metal_detector", "shovel"})), seed=0)
    # Player is in the Entrance Hall (not the Workshop): the option shows...
    assert shops.fabricate_options(game) == ["detector_shovel"]
    # ...but building it here is refused.
    try:
        shops.fabricate(game, "detector_shovel")
        raise AssertionError("fabricate outside the Workshop should be refused")
    except AssertionError as e:
        assert "Workshop" in str(e)


def test_fabricate_options_empty_without_full_inputs():
    """fabricate_options omits recipes where at least one input is missing.

    Only recipes with ALL inputs held are shown; partial-input recipes are hidden.
    """
    game = _game(seed=0)
    _place_workshop(game)
    # Give only one of the two needed for detector_shovel
    game.state.inventory["metal_detector"] = 1
    # shovel not given: detector_shovel recipe incomplete
    options = shops.fabricate_options(game)
    assert "detector_shovel" not in options


def test_fabricate_options_shows_completable_recipes():
    """fabricate_options lists outputs whose full input set is held.

    When metal_detector + shovel are both held, detector_shovel must appear.
    """
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    options = shops.fabricate_options(game)
    assert "detector_shovel" in options


def test_fabricate_options_sorted():
    """fabricate_options returns output ids in sorted order for determinism."""
    game = _game(seed=0)
    _place_workshop(game)
    # Give inputs for multiple recipes
    for iid in ["metal_detector", "shovel", "magnifying_glass"]:
        game.state.inventory[iid] = 1
    options = shops.fabricate_options(game)
    assert options == sorted(options), f"fabricate_options not sorted: {options}"


def test_fabricate_options_excludes_already_held_output():
    """fabricate_options omits a recipe whose output is already in inventory.

    A held unique output fails _is_available, so the recipe disappears.
    """
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    game.state.inventory["detector_shovel"] = 1  # output already held
    options = shops.fabricate_options(game)
    assert "detector_shovel" not in options


# ---------------------------------------------------------- fabricate

def test_fabricate_consumes_inputs():
    """fabricate removes each input from inventory (consumed=True).

    After fabrication the input items must not be in inventory.
    """
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    shops.fabricate(game, "detector_shovel")
    assert not si.has(game.state, "metal_detector"), "metal_detector should be consumed"
    assert not si.has(game.state, "shovel"), "shovel should be consumed"


def test_fabricate_marks_inputs_consumed():
    """fabricate marks inputs consumed=True so they cannot respawn during the day.

    Consumed inputs enter state.special.removed and are excluded from spawn pools
    and trade offers for the rest of the day — the wiki says they are removed
    from inventory permanently.
    """
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    shops.fabricate(game, "detector_shovel")
    assert "metal_detector" in game.state.special.removed, (
        "metal_detector must be in removed after fabrication"
    )
    assert "shovel" in game.state.special.removed, (
        "shovel must be in removed after fabrication"
    )


def test_fabricate_grants_output():
    """fabricate grants the output contraption to inventory."""
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    shops.fabricate(game, "detector_shovel")
    assert si.has(game.state, "detector_shovel"), "detector_shovel must be in inventory"


def test_fabricate_requires_workshop_presence():
    """fabricate raises AssertionError when the player is not in the Workshop.

    Fabrication requires standing at the Workshop bench.
    """
    game = _game(GameConfig(starting_items=frozenset({"metal_detector", "shovel"})), seed=0)
    # Player is in Entrance Hall
    with pytest.raises(AssertionError):
        shops.fabricate(game, "detector_shovel")


def test_fabricate_requires_full_inputs():
    """fabricate raises AssertionError when required inputs are not all held."""
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    # shovel missing
    with pytest.raises(AssertionError):
        shops.fabricate(game, "detector_shovel")


# ---------------------------------------------------------- pick_sound_amplifier integration

def test_fabricated_pick_sound_amplifier_opens_locked_door():
    """Fabricating pick_sound_amplifier and using it can open a locked door.

    This exercises the full pipeline: fabricate inputs lock_pick_kit +
    metal_detector → grant pick_sound_amplifier → open_locked_free attempt.
    The Pick Sound Amplifier has better lockpick rates than the Lock Pick Kit
    (pity=0 per data), so across many tries it will succeed.
    """
    successes = 0
    for seed in range(50):
        game = _game(seed=seed)
        state = game.state

        # Fabricate the amplifier
        _place_workshop(game)
        state.inventory["lock_pick_kit"] = 1
        state.inventory["metal_detector"] = 1
        shops.fabricate(game, "pick_sound_amplifier")

        assert si.has(state, "pick_sound_amplifier"), (
            f"seed={seed}: pick_sound_amplifier not in inventory after fabrication"
        )
        assert not si.has(state, "lock_pick_kit"), "input consumed"
        assert not si.has(state, "metal_detector"), "input consumed"

        # Set up a locked door and attempt to open it
        seg = segment_key(state.pos, N)
        state.door_state[seg] = DOOR_LOCKED
        state.door_version += 1

        result = si.open_locked_free(game)
        if result:
            successes += 1
        if successes >= 5:
            break

    assert successes >= 5, (
        "expected pick_sound_amplifier to open at least 5 locked doors across 50 seeds"
    )
