"""Trading Post trades and Workshop fabrication."""

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.locks import DOOR_LOCKED, segment_key
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.env.obs import TRADE_OFFER_ROWS


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

    Sets area='trading_post' and adds trading_post to placed_ids, replicating
    what open_outer_draft + enter_outer_room would do without driving the full
    outer-area machinery.
    """
    game.state.area = "trading_post"
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

    The offers list is only active inside a placed trading_post;
    querying from any other position must return empty.
    """
    game = _game(seed=0)
    _give_items(game, "shovel")
    assert shops.trade_offers(game) == []


def test_trade_offers_empty_after_trades_per_day_used():
    """trade_offers returns [] once the daily trade cap is exhausted.

    trades_per_day (20 per shops.json — generous, because the trade graph is
    only discoverable by experimenting) is the hard stop on trading.
    """
    game = _game(GameConfig(starting_items=frozenset({"shovel", "compass", "sleeping_mask",
                                                       "salt_shaker"})), seed=0)
    _set_trading_post_inner(game)
    cap = game.registry.shop_rules.trading["trades_per_day"]
    for _ in range(cap):
        offers = shops.trade_offers(game)
        if not offers:
            break
        shops.trade(game, offers[0]["give"])
    game.state.shops.trades_done = cap  # exhaust any slots the graph left unusable
    assert shops.trade_offers(game) == []


def test_trade_offers_lists_only_tradeable_items():
    """trade_offers includes only items whose SpecialItem.tier is not None.

    royal_scepter (tier=None) and file_cabinet_key (tier=None, untradeable per
    the wiki's Trading Post tier lists) must not appear; shovel (tier=2) must
    appear. broken_lever is tier=1/receive: false now (give-only, wiki-verified),
    so it is a valid "give" and is exercised separately in the give-only tests.
    """
    game = _game(seed=0)
    # royal_scepter is gated out by configure(); use file_cabinet_key which is
    # tier=None and shovel which is tier=2
    state = game.state
    state.inventory["file_cabinet_key"] = 1
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)

    offers = shops.trade_offers(game)
    give_ids = {o["give"] for o in offers}
    assert "shovel" in give_ids, "shovel (tier=2) should be tradeable"
    assert "file_cabinet_key" not in give_ids, "file_cabinet_key (tier=None) must not appear"


# ------------------------------------------------- trade-offer identity collapse

def test_trade_identity_groups_agree_on_tier_and_receivability():
    """Sim ids that collapse into one trade offer must agree on tier, and on
    `receive` except for the one item the owner ruled receivable, or the
    surviving offer would misreport the terms of the ids it speaks for.

    The identity key strips a display name's trailing source qualifier, so
    this is also the guard that a future item whose name happens to carry a
    parenthetical does not silently join a family it does not belong to: the
    families are pinned by name here, and only these three exist.

    The Upgrade Disk family is the deliberate exception: `upgrade_disk_trade`
    is the single receivable disk (the 16th, granted only by the tier-5 trade
    special), while the 15 fixed-source disks stay give-only. Receivability is
    read per id by `_trade_target_ok`, never through the collapsed identity,
    so the split cannot misreport a give offer.
    """
    game = _game(seed=0)
    groups: dict[str, list] = {}
    for item in game.registry.special.items:
        groups.setdefault(shops._trade_identity(item), []).append(item)
    multi = {name: members for name, members in groups.items() if len(members) > 1}
    assert set(multi) == {"Sanctum Key", "Upgrade Disk", "Allowance Token"}, (
        f"unexpected trade-identity families: {sorted(multi)}"
    )
    for name, members in multi.items():
        tiers = {m.tier for m in members}
        assert len(tiers) == 1, f"{name!r} members disagree on tier: {tiers}"
        receivable = {m.receive for m in members if m.id != "upgrade_disk_trade"}
        assert len(receivable) == 1, (
            f"{name!r} members disagree on receive: {receivable}"
        )
    assert game.registry.special.by_id["upgrade_disk_trade"].receive, (
        "upgrade_disk_trade is the Upgrade Disk family's one receivable member; "
        "if it is no longer receivable the carve-out above must go"
    )


def test_all_held_sanctum_keys_produce_a_single_offer():
    """Holding every Sanctum Key yields exactly one offer, keyed on the first
    id in sorted order.

    The wiki states each Sanctum Key is considered the same item, so having
    multiple only produces one trade offer. The sim splits them into one id
    per source purely so each source's respawn gates independently; that split
    must not leak into the Trading Post menu. The representative is the first
    held id in sorted order, the same rule open_sigil_door uses to pick which
    key a Sigil door spends.
    """
    game = _game(seed=0)
    for key_id in si.SANCTUM_KEY_IDS:
        game.state.inventory[key_id] = 1
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    assert [o["give"] for o in offers] == [sorted(si.SANCTUM_KEY_IDS)[0]], (
        f"eight Sanctum Keys must be one offer, got {[o['give'] for o in offers]}"
    )


def test_all_held_upgrade_disks_produce_a_single_offer():
    """Holding every Upgrade Disk yields exactly one offer, keyed on the first
    id in sorted order.

    Same wiki rule as the Sanctum Keys, and the larger of the two families:
    sixteen ids exhaust the game's whole supply of disks, so sixteen offers
    would on their own overflow the eight-row offer cap twice over.
    """
    game = _game(seed=0)
    disk_ids = sorted(
        it.id for it in game.registry.special.items
        if it.id.startswith("upgrade_disk_")
    )
    assert len(disk_ids) == 16, f"expected the game's 16 disks, got {len(disk_ids)}"
    for disk_id in disk_ids:
        game.state.inventory[disk_id] = 1
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    assert [o["give"] for o in offers] == [disk_ids[0]], (
        f"sixteen Upgrade Disks must be one offer, got {[o['give'] for o in offers]}"
    )


def test_full_tier5_inventory_fits_the_offer_row_cap():
    """Holding all twelve tier-5 items cannot produce more offers than the
    action space and the observation array can carry.

    Twelve ids are five game items — the eight Sanctum Keys plus
    cursed_effigy, emerald_bracelet, master_key and ornate_compass — which
    fits inside TRADE_OFFER_ROWS. Beyond that cap an offer is never encoded
    and never masked legal, silently, so the worst held inventory staying
    under it is the property that makes the menu reachable at all.
    """
    game = _game(seed=0)
    tier5_ids = [it.id for it in game.registry.special.items if it.tier == 5]
    assert len(tier5_ids) == 12, f"tier 5 is the worst case at 12 ids, got {len(tier5_ids)}"
    for item_id in tier5_ids:
        game.state.inventory[item_id] = 1
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    keys_offered = [o["give"] for o in offers if o["give"] in si.SANCTUM_KEY_IDS]
    assert len(keys_offered) <= 1, f"Sanctum Keys must share one offer, got {keys_offered}"
    assert len(offers) <= 5, (
        f"12 tier-5 ids are 5 game items, got {len(offers)}: {[o['give'] for o in offers]}"
    )
    assert len(offers) <= TRADE_OFFER_ROWS, (
        f"{len(offers)} offers exceed the {TRADE_OFFER_ROWS}-row cap and truncate silently"
    )


def test_distinct_items_are_never_collapsed_together():
    """Two items of the same tier that are different game items keep separate
    offers.

    The collapse is per game item, not per tier — otherwise a tier would
    become a single menu entry and every item in it but one unreachable.
    """
    game = _game(seed=0)
    game.state.inventory["shovel"] = 1
    game.state.inventory["sleeping_mask"] = 1
    _set_trading_post_inner(game)
    gives = {o["give"] for o in shops.trade_offers(game)}
    assert {"shovel", "sleeping_mask"} <= gives, (
        f"two distinct tier-2 items must keep two offers, got {gives}"
    )


# ------------------------------------------------------- the Keycard round trip

def test_a_held_keycard_is_offered_without_an_inventory_entry():
    """A Keycard held on state.has_keycard is offered at the Trading Post.

    It is tier 3 and the wiki lists it as receivable; only its storage sets it
    apart, so the offer walk has to read keycard.held rather than scanning the
    inventory dict, which never contains it.
    """
    game = _game(seed=0)
    game.state.has_keycard = True
    _set_trading_post_inner(game)
    offers = shops.trade_offers(game)
    assert "keycard" not in game.state.inventory, (
        "the Keycard must never gain a phantom inventory entry"
    )
    assert [o["give"] for o in offers] == ["keycard"]


def test_giving_the_keycard_away_takes_door_access_with_it():
    """Trading the Keycard away clears state.has_keycard and leaves no
    inventory entry behind.

    This is the trap in the naive fix: deleting the exclusion checks and
    letting si.remove run would take nothing out of state.has_keycard, so the
    player would keep security-door access for an item they had given away.
    """
    game = _game(seed=0)
    game.state.has_keycard = True
    _set_trading_post_inner(game)
    shops.trade(game, "keycard")
    assert game.state.has_keycard is False, (
        "giving the Keycard away must clear the flag every security door reads"
    )
    assert game.state.inventory.get("keycard", 0) == 0


def test_receiving_the_keycard_sets_the_flag_not_an_inventory_entry():
    """A Keycard received in trade lands on state.has_keycard.

    The other half of the trap: si.grant would write state.inventory["keycard"],
    which no door code reads, so the player would pay an item for a card that
    opens nothing. The graph is pinned rather than rolled so the receive is the
    Keycard by construction.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    state.shops.trade_graph = {"shovel": "keycard"}
    state.shops.trade_graph_rolled = True
    _set_trading_post_inner(game)
    assert state.has_keycard is False
    shops.trade(game, "shovel")
    assert state.has_keycard is True, "a received Keycard must set has_keycard"
    assert "keycard" not in state.inventory, (
        "the Keycard must never gain a phantom inventory entry"
    )


def test_a_keycard_already_held_is_skipped_as_a_trade_return():
    """A held Keycard is skipped as a trade RETURN, like any held unique.

    The skip-held test has to read keycard.held; reading the inventory dict
    would find nothing and hand a second Keycard to a player who already has
    one. The graph is pinned so the walk's next hop is known by construction.
    """
    game = _game(seed=0)
    state = game.state
    state.has_keycard = True
    state.inventory["shovel"] = 1
    state.shops.trade_graph = {"shovel": "keycard", "keycard": "dice"}
    state.shops.trade_graph_rolled = True
    _set_trading_post_inner(game)
    offer = next(o for o in shops.trade_offers(game) if o["give"] == "shovel")
    assert offer["receive"] == "dice", (
        "a held Keycard must be walked past, not offered again"
    )


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


def test_trade_t5_sometimes_yields_allowance_or_the_traded_disk():
    """A tier-5 trade sometimes returns allowance_token (upgrade_disk no longer from trade path).

    All five tier-5 item groups are wiki give-only (no plain item is ever
    received from a tier-5 trade -- confirmed by the raw wiki page's Trading
    Post spoiler box: none of the tier-5 entries are bolded, and the
    datamined section states the Upgrade Disk trade list "contains no other
    items"). shops.json ships t5_special_chance=100, so every tier-5 trade
    graph roll replaces the would-be self-edge with allowance_token or
    upgrade_disk_trade before it can surface: master_key always has an
    active offer, never a self-edge. Across many seeds we should still see
    at least one allowance_token among the offered trades.
    """
    specials_seen = set()
    for seed in range(200):
        game = _game(seed=seed)
        state = game.state
        state.inventory["master_key"] = 1  # tier 5
        _set_trading_post_inner(game)
        offers = shops.trade_offers(game)
        assert any(o["give"] == "master_key" for o in offers), (
            "master_key should always have an active offer: t5_special_chance=100 "
            "overrides the self-edge on every roll"
        )
        log_before = len(state.items_found_log)
        shops.trade(game, "master_key")
        new_entries = state.items_found_log[log_before:]
        for kind, _ in new_entries:
            if kind == "allowance_token":
                specials_seen.add(kind)
    assert specials_seen, (
        f"expected some t5 trades to yield allowance_token; got {specials_seen}"
    )


def test_trade_dice_sentinel_in_graph_yields_die():
    """An item whose trade_graph successor is "dice" yields a die when traded.

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


def test_t5_special_chance_missing_key_raises():
    """trading['t5_special_chance'] has no fallback default: a data source
    that omits the key must raise KeyError rather than silently rolling at
    some made-up rate.

    load_shops() is the ONLY ShopsRegistry constructor in the codebase
    (verified by AST: a single Call node named ShopsRegistry, in
    engine/shops.py itself) and data/shops.json always supplies the key, so
    this can only be reached by a future data bug -- which must fail loudly.
    """
    game = _game(seed=0)
    game.registry.shop_rules.trading.pop("t5_special_chance")
    with pytest.raises(KeyError):
        shops._roll_trade_graph(game)


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
    """Every tradeable item (tier not None) appears as a key in the graph.

    Tier membership is the whole rule: an item carrying a Trading Post tier is
    in its tier's cycle, with no id carved out. The keycard is included like
    any other tier-3 item -- where it is stored is a concern of the offer and
    grant paths, not of the graph.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)  # trigger roll
    reg = game.registry
    tradeable_ids = {it.id for it in reg.special.items if it.tier is not None}
    assert tradeable_ids == set(state.shops.trade_graph.keys()), (
        "trade graph must contain exactly the tradeable item ids"
    )


def test_trade_graph_successors_same_tier_or_sentinel():
    """Every item in the graph points to a same-tier item or an allowed sentinel.

    Items must only cycle within their own tier.  Dice and allowance_token are
    permitted cross-tier sentinels; upgrade_disk_trade is a tier-5-only special
    outcome (shops.py::_roll_trade_graph) assigned directly as a successor
    string bypassing the normal same-tier cycle, so it also crosses tiers here
    even though it carries its own real tier (4, for the give-away path).
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)
    reg = game.registry
    sentinels = {"dice", "allowance_token", "upgrade_disk_trade"}
    for give_id, successor in state.shops.trade_graph.items():
        if successor in sentinels:
            continue
        give_item = reg.special.by_id[give_id]
        succ_item = reg.special.by_id.get(successor)
        assert succ_item is not None, f"{give_id!r} points to unknown id {successor!r}"
        assert give_item.tier == succ_item.tier, (
            f"{give_id!r} (tier {give_item.tier}) points to {successor!r} (tier {succ_item.tier})"
        )


def test_trade_graph_give_only_ids_never_a_successor():
    """A give-only (receive: false) item is never anyone's successor in the graph.

    Every wiki-verified give-only item (microchip, treasure_map, watering_can,
    plus the broader tier sweep: give-only keys, contraptions, Upgrade Disks,
    and the entirely-give-only tier-5 group) can be handed over at the Trading
    Post but the real game never hands any of them back. Checked across
    several seeds since the graph's shuffle is seed-dependent. The set itself
    is read from the registry rather than pinned here, since it is exactly
    the data this PR is sweeping -- pinning it would make this a change
    detector on data/special_items.json instead of a test of the graph
    invariant.

    Self-edges (an id mapped to itself) are excluded from "successors": tier 5
    is entirely give-only, so every tier-5 id's un-overridden successor is
    itself (_next_receivable's no-receivable-in-tier fallback) -- that is
    _resolve_trade's untradeable-today case, not another give reaching it, so
    it must not trip this check. upgrade_disk_trade needs no exclusion: it is
    receivable, so it is not in the give-only set this test sweeps.
    """
    reg_ids = None
    for seed in range(5):
        game = _game(seed=seed)
        state = game.state
        state.inventory["shovel"] = 1
        _set_trading_post_inner(game)
        shops.trade_offers(game)  # trigger roll
        reg = game.registry
        if reg_ids is None:
            reg_ids = {it.id for it in reg.special.items if not it.receive}
            assert reg_ids, "expected at least one give-only item in the registry"
        successors = {v for k, v in state.shops.trade_graph.items() if v != k}
        assert not (reg_ids & successors), (
            f"seed={seed}: give-only id(s) {reg_ids & successors} appear as a successor"
        )


def test_trade_graph_give_only_id_is_still_a_giveable_source():
    """A give-only item is still a key in the graph — it can be given away,
    just never received.  Its successor is a real (different, receivable)
    item or a sentinel, never itself.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)
    graph = state.shops.trade_graph
    for give_only_id in ("microchip", "treasure_map", "watering_can"):
        assert give_only_id in graph, f"{give_only_id!r} must still be a graph source"
        assert graph[give_only_id] != give_only_id, (
            f"{give_only_id!r} must not resolve to itself"
        )


def test_trade_give_only_item_skipped_as_a_trade_return():
    """A give-only item is skipped by the resolution walk even if it sits
    directly in a (hand-built) chain, falling through to the next node —
    the same carve-out as an already-held or already-used-Stopwatch node.

    Pins shops._trade_target_ok's `receive` check directly, independent of
    whether the real graph builder could ever produce this shape.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1  # tier 2, held: the trade root
    _set_trading_post_inner(game)
    # shovel -> microchip (give-only, must be skipped) -> compass (valid return)
    state.shops.trade_graph = {"shovel": "microchip", "microchip": "compass", "compass": "shovel"}
    state.shops.trade_graph_rolled = True
    offers = shops.trade_offers(game)
    shovel_offer = next(o for o in offers if o["give"] == "shovel")
    assert shovel_offer["receive"] == "compass", (
        "a give-only node must be skipped as a trade return, falling through "
        "to the next node in the graph"
    )


def test_tier5_trade_actually_yields_the_traded_upgrade_disk():
    """The tier-5 special really hands back upgrade_disk_trade.

    _roll_trade_graph assigns "upgrade_disk_trade" as the successor of tier-5
    gives on roughly half of all tier-5 edges. Those edges must resolve to a
    real offer: the disk is receivable, so _trade_target_ok accepts it and the
    walk terminates there instead of falling through to a tier-4 item.

    Swept over seeds rather than pinned to one, since which tier-5 ids draw the
    disk is seed-dependent; the property is that SOME tier-5 edge assigned the
    disk resolves to it, and that no edge assigned the disk resolves elsewhere
    while the player holds none.
    """
    seen_edges = 0
    for seed in range(20):
        game = _game(seed=seed)
        state = game.state
        state.inventory["shovel"] = 1
        _set_trading_post_inner(game)
        shops.trade_offers(game)  # trigger roll
        graph = state.shops.trade_graph
        for give_id, successor in graph.items():
            if successor != "upgrade_disk_trade":
                continue
            seen_edges += 1
            resolved = shops._resolve_trade(state, game.registry, give_id)
            assert resolved == "upgrade_disk_trade", (
                f"seed={seed}: {give_id!r} is assigned the traded Upgrade Disk "
                f"but resolves to {resolved!r} — the disk must be receivable"
            )
    assert seen_edges, "expected at least one edge assigned upgrade_disk_trade"


def test_traded_upgrade_disk_is_never_reachable_from_a_tier4_give():
    """An ordinary tier-4 trade never hands back the traded Upgrade Disk — only
    the tier-5 special grants it.

    The wiki's Trading Post tier lists bold every id receivable within its own
    tier. "Upgrade Disk" sits unbold in the tier-4 list, and the tier-5 section
    says the disk "is in the list of items given as Tier 5 trades (which
    contains no other items)".

    The disk stays `receive: true` so the tier-5 branch's direct assignment
    still resolves; the exclusion lives in cycle membership instead. That means
    a `receive`-flag check cannot catch a regression here, and this sweep is
    what pins it. Both the graph edge and the resolved outcome are asserted, as
    a tier-4 give could otherwise reach the disk by walking past a skipped node.
    """
    tier4_gives = 0
    for seed in range(20):
        game = _game(seed=seed)
        state = game.state
        state.inventory["shovel"] = 1
        _set_trading_post_inner(game)
        shops.trade_offers(game)  # trigger roll
        for give_id, successor in state.shops.trade_graph.items():
            if game.registry.special.by_id[give_id].tier != 4:
                continue
            tier4_gives += 1
            assert successor != "upgrade_disk_trade", (
                f"seed={seed}: tier-4 give {give_id!r} is assigned the traded "
                f"Upgrade Disk, which only the tier-5 special may grant"
            )
            resolved = shops._resolve_trade(state, game.registry, give_id)
            assert resolved != "upgrade_disk_trade", (
                f"seed={seed}: tier-4 give {give_id!r} resolves to the traded "
                f"Upgrade Disk, which only the tier-5 special may grant"
            )
    assert tier4_gives, "expected the sweep to exercise at least one tier-4 give"


def test_held_traded_upgrade_disk_stops_being_offered():
    """The traded disk is unique: once held, the tier-5 trade decays past it.

    This is the flip side of the test above and the reason the item can be
    receivable without becoming an infinite disk faucet — _trade_target_ok
    refuses a held unique, so the walk falls through to the graph's other
    outcomes exactly as the docstring claims.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1
    _set_trading_post_inner(game)
    shops.trade_offers(game)
    graph = state.shops.trade_graph
    give_id = next(g for g, s in graph.items() if s == "upgrade_disk_trade")
    assert shops._resolve_trade(state, game.registry, give_id) == "upgrade_disk_trade"
    state.inventory["upgrade_disk_trade"] = 1
    assert shops._resolve_trade(state, game.registry, give_id) != "upgrade_disk_trade", (
        "a held traded Upgrade Disk must stop resolving (unique)"
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
        if receive is not None and receive not in {"dice", "allowance_token"}:
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


def test_trade_already_used_stopwatch_is_skipped_as_a_trade_return():
    """A second Stopwatch cannot come back as a trade return once one has
    already run today (state.special.stopwatch_used); the walk must fall
    through to the next node in the graph instead, the same way it falls
    through a held item.

    Pins the carve-out in shops._trade_target_ok, which delegates to
    stopwatch.blocks_as_trade_return in effects/items/stopwatch.py.
    """
    game = _game(seed=0)
    state = game.state
    state.inventory["shovel"] = 1  # tier 2, held: the trade root
    _set_trading_post_inner(game)
    # shovel -> stopwatch (blocked once used today) -> compass (a valid, unheld return)
    state.shops.trade_graph = {"shovel": "stopwatch", "stopwatch": "compass", "compass": "shovel"}
    state.shops.trade_graph_rolled = True
    state.special.stopwatch_used = True
    offers = shops.trade_offers(game)
    shovel_offer = next(o for o in offers if o["give"] == "shovel")
    assert shovel_offer["receive"] == "compass", (
        "an already-used Stopwatch must be skipped as a trade return, "
        "falling through to the next node in the graph"
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
    with pytest.raises(AssertionError, match="Workshop"):
        shops.fabricate(game, "detector_shovel")


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


# ------------------------------------------ contraption carry-over lockout
#
# wiki/Coat_Check, Effect -> Interactions: "If a contraption is checked at
# the start of a day, it will remove some of its component items from the
# item pool ... The items removed differ from contraption to contraption,"
# followed by a per-contraption list that includes BOTH the Dowsing Rod
# ("prevents the Compass from being obtained") and the Pick Sound Amplifier
# ("prevents the Lock Pick Kit from being obtained") -- there is no
# per-contraption exemption, and the block set is a curated SUBSET of each
# recipe's inputs, not the whole recipe ("Components not listed above can
# still be obtained ... the Broken Lever and Battery Pack can still be found
# while either the Power Hammer or Jack Hammer is checked").

def test_contraption_carried_via_coat_check_gates_its_listed_component_only():
    """A Power Hammer carried into day 2 via Coat Check gates the Sledge
    Hammer (its wiki-listed component) but leaves the Battery Pack and
    Broken Lever -- its other two recipe inputs -- obtainable.

    Exercises the full observable path: fabricate -> coat_check_on_enter ->
    carryover() -> DayChain.advance() -> next day's Game.reset() ->
    gated_out. Nothing here derives its expectation by calling the function
    under test (special_items.configure); the blocked/unblocked ids are
    asserted as literal wiki facts.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=5)

    cfg1 = chain.next_config()
    g1 = Game(cfg1, seed=3)
    g1.state.inventory["sledge_hammer"] = 1
    g1.state.inventory["battery_pack"] = 1
    g1.state.inventory["broken_lever"] = 1
    _place_workshop(g1)
    shops.fabricate(g1, "power_hammer")
    assert si.has(g1.state, "power_hammer"), "setup: fabrication must succeed"

    si.coat_check_on_enter(g1)
    assert g1.state.special.coat_check_item == "power_hammer", "setup: must be checked"

    co = g1.carryover()
    assert "power_hammer" in co["starting_items"], "setup: must carry to tomorrow"
    chain.advance(co)

    cfg2 = chain.next_config()
    assert "power_hammer" in cfg2.starting_items, "setup: day 2 must start with it"
    g2 = Game(cfg2, seed=4)

    assert "sledge_hammer" in g2.state.special.gated_out, (
        "carried power_hammer must gate its wiki-listed component sledge_hammer"
    )
    assert "battery_pack" not in g2.state.special.gated_out, (
        "battery_pack is not in power_hammer's wiki-listed block set"
    )
    assert "broken_lever" not in g2.state.special.gated_out, (
        "broken_lever is not in power_hammer's wiki-listed block set"
    )


def test_dowsing_rod_carry_over_gates_compass_not_shovel():
    """A carried Dowsing Rod gates Compass -- same as every other contraption,
    with NO exemption (wiki: "The Dowsing Rod prevents the Compass from
    being obtained while checked"). Shovel, its other recipe input, is not
    in the wiki's list for this contraption and stays obtainable.
    """
    g = Game(GameConfig(starting_items=frozenset({"dowsing_rod"})), seed=1)
    assert "compass" in g.state.special.gated_out, (
        "carried dowsing_rod must gate compass (wiki-listed component)"
    )
    assert "shovel" not in g.state.special.gated_out, (
        "shovel is not in dowsing_rod's wiki-listed block set"
    )


def test_pick_sound_amplifier_carry_over_gates_lock_pick_kit_not_metal_detector():
    """A carried Pick Sound Amplifier gates Lock Pick Kit -- again with no
    exemption (wiki: "The Pick Sound Amplifier prevents the Lock Pick Kit
    from being obtained while checked"). Metal Detector, its other recipe
    input, stays obtainable.
    """
    g = Game(GameConfig(starting_items=frozenset({"pick_sound_amplifier"})), seed=1)
    assert "lock_pick_kit" in g.state.special.gated_out, (
        "carried pick_sound_amplifier must gate lock_pick_kit (wiki-listed component)"
    )
    assert "metal_detector" not in g.state.special.gated_out, (
        "metal_detector is not in pick_sound_amplifier's wiki-listed block set"
    )


def test_fabricating_today_does_not_gate_its_own_components_today():
    """Assembling a contraption THIS day (fresh, not carried from a previous
    day) must not lock out its own components today: the lockout is a
    start-of-day effect keyed off cfg.starting_items, computed once before
    the day's first fabrication is even possible, and fabricate() never
    touches gated_out.
    """
    game = _game(seed=0)
    _place_workshop(game)
    game.state.inventory["metal_detector"] = 1
    game.state.inventory["shovel"] = 1
    shops.fabricate(game, "detector_shovel")
    assert "metal_detector" not in game.state.special.gated_out, (
        "fabricating detector_shovel today must not gate metal_detector today"
    )
    assert "shovel" not in game.state.special.gated_out, (
        "fabricating detector_shovel today must not gate shovel today"
    )


#: Ground truth from the wiki's own per-contraption list (wiki/Coat_Check),
#: hardcoded independently of registry.special.contraption_lockout so this
#: test cannot pass vacuously if the data table were ever silently emptied or
#: shrunk -- the expectation must not come from the code path under test.
_WIKI_CONTRAPTION_LOCKOUT: dict[str, frozenset[str]] = {
    "burning_glass": frozenset({"metal_detector"}),
    "detector_shovel": frozenset({"metal_detector", "shovel"}),
    "dowsing_rod": frozenset({"compass"}),
    "jack_hammer": frozenset({"shovel"}),
    "lucky_purse": frozenset({"lucky_rabbits_foot", "coin_purse"}),
    "pick_sound_amplifier": frozenset({"lock_pick_kit"}),
    "power_hammer": frozenset({"sledge_hammer"}),
    "powered_electromagnet": frozenset({"compass"}),
}


def test_contraption_lockout_sweeps_every_data_driven_entry():
    """Every contraption named on the wiki's Coat Check page gates its own
    listed components when carried via starting_items -- read from
    data/special_items.json's "contraption_lockout" section (not a Python
    constant), and checked against a literal, hardcoded expectation so a
    data-move regression that silently dropped or emptied a table entry is
    still caught (comparing against the loaded data itself would not).

    Covers all eight contraptions in one sweep, including the five
    (burning_glass, detector_shovel, jack_hammer, lucky_purse,
    powered_electromagnet) the three dedicated tests above do not exercise.
    """
    registry = Game(GameConfig(), seed=0).registry
    assert registry.special.contraption_lockout == _WIKI_CONTRAPTION_LOCKOUT, (
        "registry.special.contraption_lockout must match the wiki's published table exactly"
    )
    for contraption_id, blocked_ids in _WIKI_CONTRAPTION_LOCKOUT.items():
        g = Game(GameConfig(starting_items=frozenset({contraption_id})), seed=1)
        for comp_id in blocked_ids:
            assert comp_id in g.state.special.gated_out, (
                f"{contraption_id} must gate its wiki-listed component {comp_id}"
            )


def test_traded_upgrade_disk_is_one_and_only_one():
    """The tradeable Upgrade Disk is unique, so a second tier-5 trade can never
    hand over another one.

    Fifteen fixed locations plus this single traded disk are the game's whole
    supply of sixteen; once it is held the offer must decay to something else.
    """
    from blueprince_sim.engine.model import Registry
    registry = Registry.load()
    disks = [i.id for i in registry.special.items if i.id.startswith("upgrade_disk")]
    assert "upgrade_disk_trade" in disks
    assert registry.special.by_id["upgrade_disk_trade"].unique
    game = _game(GameConfig(starting_items=frozenset({"upgrade_disk_trade"})), seed=0)
    state = game.state
    _set_trading_post_inner(game)
    # Holding it already: every resolved trade offer must point elsewhere.
    state.inventory["master_key"] = 1
    for offer in shops.trade_offers(game):
        assert offer["receive"] != "upgrade_disk_trade"
