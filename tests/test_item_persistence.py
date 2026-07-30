"""Multi-day item persistence: carry channels (Coat Check, Moon Pendant, self-persisting
items) and Repellent room bans.

Tests pin observable behavior: which item ids survive into next-day starting_items,
which rooms are absent from the deck, whether bans expire on schedule.  Data lookups
are avoided — we grant/remove items directly and drive end_of_day_carry / use_repellent
through the same Game/shops API the env uses.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.decks import eligible_pool
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.env.multiday import DayChain


# ---------------------------------------------------------- helpers / fixtures

def _reg() -> Registry:
    return Registry.load()


def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(royal_scepter_found=False), seed=seed)


def _game_with(*item_ids: str, seed: int = 0) -> Game:
    """Game whose inventory starts with the given item ids (no scepter noise)."""
    return _game(GameConfig(
        starting_items=frozenset(item_ids),
        royal_scepter_found=False,
    ), seed=seed)


# ============================================================= persistence rules

def test_day_persistence_item_not_carried():
    """A 'day'-persistence item (shovel) does not appear in end_of_day_carry output.

    The base rule: all items are lost at end of day unless they fall into one of
    the carry channels.  Shovel is tier-2 tradeable and persistence='day'.
    """
    g = _game_with("shovel")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "shovel" not in carried


def test_permanent_item_always_carried():
    """A permanent-persistence item always appears in end_of_day_carry.

    The permanent flag is the self-persistence channel for Key 8 (unlocks rank 8
    room drafts) — losing it between days would make the unlock meaningless.
    """
    g = _game_with("sanctum_key")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "sanctum_key" in carried


def test_until_used_item_carried():
    """A vault key (persistence='until_used') appears in end_of_day_carry.

    Vault keys must persist until actually used on a Vault box; losing them
    overnight would make the Vault permanently inaccessible.
    """
    g = _game_with("vault_key_149")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "vault_key_149" in carried


def test_multiple_persistence_channels_combined():
    """Permanent + until_used items all carry; day-only items do not.

    When the inventory contains items from different persistence tiers,
    each channel fires independently.
    """
    g = _game_with("vault_key_149", "sanctum_key", "shovel", "magnifying_glass")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "sanctum_key" in carried
    assert "sanctum_key" in carried
    assert "shovel" not in carried
    assert "magnifying_glass" not in carried


def test_no_items_yields_empty_carry():
    """end_of_day_carry returns [] when nothing is held.

    An empty inventory has no persist channels to fire, so the output must be
    an empty list (not None, not a list with sentinels).
    """
    g = _game()
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert carried == []


# ============================================================= Coat Check

def test_coat_check_stores_best_item():
    """Entering the Coat Check stores the highest-tier held item.

    Coat Check auto-selects the best item by Trading Post tier (highest tier
    wins; ties broken alphabetically by id).  Telescope (tier 4) beats
    shovel (tier 2), so telescope is stored.
    """
    g = _game_with("shovel", "telescope")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "telescope"


def test_coat_check_stored_item_appears_in_carry():
    """The Coat Check stored item appears in end_of_day_carry even if it is day-persistence.

    Telescope persistence is 'day', so it would normally be lost.  Entering
    the Coat Check overrides this — the item is conceptually held at the
    check room and returned tomorrow.
    """
    g = _game_with("telescope")
    si.coat_check_on_enter(g)
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "telescope" in carried


def test_coat_check_day_item_not_carried_without_coat_check():
    """Without the Coat Check room, a day-persistence item is not carried.

    Contrast with the test above: the Coat Check is what causes the carry,
    not the item's own persistence.
    """
    g = _game_with("telescope")
    # Do NOT call coat_check_on_enter
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "telescope" not in carried


def test_coat_check_tie_broken_alphabetically():
    """When two items share the same tier, coat_check_on_enter picks the alphabetically
    first id (deterministic tie-break).

    magnifying_glass (tier 1) and sleeping_mask (tier 1): 'm' < 's', so
    magnifying_glass is stored.
    """
    g = _game_with("magnifying_glass", "sleeping_mask")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "magnifying_glass"


def test_coat_check_only_once_per_day():
    """The second call to coat_check_on_enter in one day is a no-op.

    The game stores at most one item per day; a second entry to the Coat Check
    (or a second direct call) must not overwrite the first.
    """
    g = _game_with("telescope", "shovel")
    si.coat_check_on_enter(g)
    first = g.state.special.coat_check_item
    # Grant a higher-tier item and call again
    si.grant(g.state, g.registry, "watering_can", source="test")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == first  # unchanged


def test_coat_check_empty_inventory_no_op():
    """coat_check_on_enter with no held items leaves coat_check_item as None."""
    g = _game()
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item is None


def test_coat_check_carryover_in_daychain():
    """DayChain carries the Coat Check item into the next day's starting_items via carryover.

    This is the full observable path: coat_check_on_enter → end_of_day_carry →
    carryover() → DayChain.advance() → next_config().starting_items.
    """
    # Start with a shovel (day persistence) and trigger coat check
    g = _game_with("shovel")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "shovel"

    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=10)
    co = shops.carryover(g)
    assert "shovel" in co["starting_items"]

    chain.advance(co)
    cfg2 = chain.next_config()
    # shovel should be in next day's starting_items
    assert "shovel" in cfg2.starting_items


# ============================================================= Moon Pendant

def test_moon_pendant_carries_exactly_two_items():
    """Moon Pendant causes exactly 2 distinct held item ids to carry overnight.

    When 3+ items are held, the pendant draw picks exactly 2 (not all, not 1).
    """
    g = _game_with("moon_pendant", "shovel", "telescope", "magnifying_glass")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    # shovel/telescope/magnifying_glass are day-persistence; pendant draw should add 2
    assert len(carried) == 2
    # All carried items must be from the inventory
    inventory_ids = set(g.state.inventory)
    assert all(iid in inventory_ids for iid in carried)


def test_moon_pendant_itself_is_eligible():
    """The Moon Pendant itself is eligible for its own 2-item draw.

    The wiki says '2 random inventory items carry'; the pendant is in inventory
    and is included in the pool.
    """
    g = _game_with("moon_pendant", "shovel")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    # Only 2 items total; both must carry (pendant draw when <= 2 items held)
    assert set(carried) == {"moon_pendant", "shovel"}


def test_moon_pendant_all_carry_when_two_or_fewer_held():
    """When only 1 or 2 items are held, all carry (trivial pendant draw).

    The pendant draws 2 distinct items; if there are fewer than 2 items, all
    are included without a random draw.
    """
    g = _game_with("moon_pendant")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "moon_pendant" in carried


def test_moon_pendant_carry_is_deterministic_per_seed():
    """The Moon Pendant draw produces the same result given the same seed.

    Determinism is a tested invariant: same config + seed must yield identical
    observable outcomes across repeated resets.
    """
    cfg = GameConfig(
        starting_items=frozenset({"moon_pendant", "shovel", "telescope",
                                   "magnifying_glass", "running_shoes"}),
        royal_scepter_found=False,
    )
    g1 = Game(cfg, seed=99)
    g2 = Game(cfg, seed=99)
    c1 = si.end_of_day_carry(g1.state, g1.registry, g1.rng)
    c2 = si.end_of_day_carry(g2.state, g2.registry, g2.rng)
    assert c1 == c2


def test_moon_pendant_different_seeds_can_differ():
    """Different seeds can produce different Moon Pendant draw results.

    This verifies that the draw is genuinely random (not always the same fixed
    two items), which would mask a determinism bug.
    """
    cfg = GameConfig(
        starting_items=frozenset({"moon_pendant", "shovel", "telescope",
                                   "magnifying_glass", "running_shoes",
                                   "sleeping_mask", "salt_shaker"}),
        royal_scepter_found=False,
    )
    results = set()
    for seed in range(30):
        g = Game(cfg, seed=seed)
        carried = si.end_of_day_carry(g.state, g.registry, g.rng)
        results.add(tuple(carried))
    # Multiple distinct outcomes across 30 seeds proves non-degenerate randomness
    assert len(results) > 1


def test_without_moon_pendant_only_persistent_items_carry():
    """Without the Moon Pendant, only permanent/until_used items carry; day items do not.

    This pins the baseline: the pendant is the only source of extra carry for
    day-persistence items (besides Coat Check).
    """
    g = _game_with("sanctum_key", "shovel", "telescope")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "sanctum_key" in carried
    assert "shovel" not in carried
    assert "telescope" not in carried


# ============================================================= Repellent

def test_repellent_use_consumes_item():
    """use_repellent() removes one Repellent from inventory (consumed, not pool-returned).

    The repellent is consumed on use, not returned to the spawn pool.  The
    inventory count must drop to 0 after one use.
    """
    g = _game_with("repellent")
    shops.use_repellent(g, "coat_check")
    assert g.state.inventory.get("repellent", 0) == 0


def test_repellent_records_ban():
    """use_repellent() records a 7-day ban in state.shops.repellent_bans.

    The ban is stored with days=7 and is passed through carryover() to DayChain.
    """
    g = _game_with("repellent")
    shops.use_repellent(g, "coat_check")
    assert g.state.shops.repellent_bans.get("coat_check") == 7


def test_repellent_carryover_includes_ban():
    """carryover()['banned_rooms'] contains the newly-banned room with days=7.

    The shops.carryover() function must expose new repellent bans so DayChain
    can merge them into its running ban dict.
    """
    g = _game_with("repellent")
    shops.use_repellent(g, "coat_check")
    co = shops.carryover(g)
    assert co["banned_rooms"].get("coat_check") == 7


def test_repellent_banned_room_absent_from_deck():
    """A room in cfg.banned_rooms is excluded from the eligible draft pool.

    This is the core observable effect: the banned room cannot appear in any
    draft offer that day.
    """
    reg = _reg()
    cfg_normal = GameConfig(royal_scepter_found=False)
    cfg_banned = GameConfig(banned_rooms=frozenset({"coat_check"}), royal_scepter_found=False)
    normal_ids = {r.id for r in eligible_pool(reg, cfg_normal)}
    banned_ids = {r.id for r in eligible_pool(reg, cfg_banned)}
    assert "coat_check" in normal_ids
    assert "coat_check" not in banned_ids


def test_repellent_ban_propagates_into_next_day_config():
    """After a Repellent use, the next day's config has the banned room in banned_rooms.

    The full path: use_repellent → carryover → DayChain.advance →
    next_config().banned_rooms contains the room id.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=10)
    g = Game(chain.next_config(), seed=0)
    # Grant repellent and ban coat_check
    si.grant(g.state, g.registry, "repellent", source="test")
    shops.use_repellent(g, "coat_check")
    chain.advance(shops.carryover(g))
    cfg2 = chain.next_config()
    assert "coat_check" in cfg2.banned_rooms


def test_repellent_ban_expires_after_seven_days():
    """A Repellent ban lasts exactly 7 days and is gone before day 9's config.

    Day 1: ban applied.  Days 2–8: room is in banned_rooms (7 days active).
    Day 9: room is no longer in banned_rooms.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=20)
    g1 = Game(chain.next_config(), seed=0)
    si.grant(g1.state, g1.registry, "repellent", source="test")
    shops.use_repellent(g1, "coat_check")
    chain.advance(shops.carryover(g1))

    # Days 2–8 must all have coat_check banned
    for day_idx in range(7):
        cfg = chain.next_config()
        assert "coat_check" in cfg.banned_rooms, f"expected ban on day {day_idx + 2}"
        chain.advance(shops.carryover(Game(cfg, seed=0)))

    # Day 9: ban must be gone
    cfg9 = chain.next_config()
    assert "coat_check" not in cfg9.banned_rooms


def test_repellent_three_ban_cap():
    """The 3-ban cap prevents a 4th active ban; oldest is evicted when cap is exceeded.

    Adding four bans serially: after the 4th, the total active count stays at 3
    and the first-added room is dropped (oldest-evict policy).
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=30)

    # Each iteration: apply a repellent ban on a different room
    ban_rooms = ["coat_check", "workshop", "library", "attic"]
    for room_id in ban_rooms:
        g = Game(chain.next_config(), seed=0)
        si.grant(g.state, g.registry, "repellent", source="test")
        shops.use_repellent(g, room_id)
        chain.advance(shops.carryover(g))

    # After 4 advances, at most 3 bans should be active
    cfg = chain.next_config()
    assert len(cfg.banned_rooms) <= 3
    # The oldest ban (coat_check) should have been evicted
    assert "coat_check" not in cfg.banned_rooms
    # The three newest should still be active (or nearly — depends on days left)
    # workshop was banned 3 advances ago (days remaining = 7 - 3 = 4 > 0)
    assert "workshop" in cfg.banned_rooms
    assert "library" in cfg.banned_rooms
    assert "attic" in cfg.banned_rooms


def test_repellent_illegal_target_entrance_hall():
    """use_repellent raises AssertionError when the target is entrance_hall.

    The Entrance Hall is always present in the house; banning it would break
    the day entirely.
    """
    g = _game_with("repellent")
    with pytest.raises(AssertionError):
        shops.use_repellent(g, "entrance_hall")


def test_repellent_illegal_target_antechamber():
    """use_repellent raises AssertionError when the target is antechamber.

    The Antechamber is the win condition; it must always be draftable.
    """
    g = _game_with("repellent")
    with pytest.raises(AssertionError):
        shops.use_repellent(g, "antechamber")


def test_repellent_illegal_target_room_46():
    """use_repellent raises AssertionError when the target is room_46.

    Room 46 is a unique story room; banning it is excluded by the wiki rules.
    """
    g = _game_with("repellent")
    with pytest.raises(AssertionError):
        shops.use_repellent(g, "room_46")


def test_repellent_without_item_raises():
    """use_repellent raises AssertionError if no Repellent is held.

    Consuming the item requires holding it; the assertion guards against
    accidental misuse.
    """
    g = _game()
    with pytest.raises(AssertionError):
        shops.use_repellent(g, "coat_check")


# ============================================================= DayChain wrap resets

def test_daychain_wrap_clears_starting_items():
    """After a full-cycle wrap, carried_items resets so no items bleed into attempt 2.

    The 200-day attempt is a self-contained run; items must not carry beyond it.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=2)
    # Advance twice with a permanent item
    g1 = _game_with("key_8")
    co1 = shops.carryover(g1)
    chain.advance(co1)
    g2 = Game(chain.next_config(), seed=0)
    co2 = shops.carryover(g2)
    chain.advance(co2)  # wraps after n_days=2
    # Fresh attempt: starting_items back to the base config's value
    cfg_fresh = chain.next_config()
    # base_cfg has no starting_items; carried_items was reset
    assert chain.carried_items == frozenset()
    assert "key_8" not in cfg_fresh.starting_items


def test_daychain_wrap_clears_repellent_bans():
    """After a full-cycle wrap, all Repellent bans are cleared.

    Bans from attempt 1 must not carry into attempt 2.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=2)
    g1 = _game_with("repellent")
    shops.use_repellent(g1, "coat_check")
    chain.advance(shops.carryover(g1))
    chain.advance(shops.carryover(_game()))   # second advance wraps
    assert chain.repellent_bans == {}
    assert "coat_check" not in chain.next_config().banned_rooms


# ============================================================= starting_items inject

def test_starting_items_from_carryover_are_granted_at_day_start():
    """Items in next_config().starting_items are in the inventory at day start.

    DayChain feeds carried_items into GameConfig.starting_items; Game.reset
    grants them at construction time.
    """
    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=10)
    g1 = _game_with("sanctum_key")
    chain.advance(shops.carryover(g1))
    cfg2 = chain.next_config()
    g2 = Game(cfg2, seed=0)
    assert si.has(g2.state, "sanctum_key")


def test_carryover_starting_items_is_sorted_and_deduped():
    """end_of_day_carry returns a sorted, deduplicated list.

    The caller (DayChain) converts this to a frozenset; a sorted list
    is the stable canonical form for comparison in tests.
    """
    g = _game_with("key_8", "vault_key_149", "sanctum_key")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert carried == sorted(set(carried))


def test_repellent_ban_covers_upgrade_variant():
    """Banning a floorplan also removes its upgrade variant from the pool.

    A ban targets the floorplan itself, so an Upgrade Disk must not smuggle
    the banned room back in through its upgraded form.
    """
    from blueprince_sim.engine.decks import eligible_pool
    from blueprince_sim.engine.model import Registry
    registry = Registry.load()
    variant = next((r for r in registry.rooms
                    if r.pool == "upgrade_variant" and r.variant_of and r.rarity), None)
    assert variant is not None, "no upgrade variant with a rarity in the data"
    cfg_on = GameConfig(upgrade_disks=frozenset({variant.id}))
    assert any(r.id == variant.id for r in eligible_pool(registry, cfg_on))
    cfg_banned = GameConfig(upgrade_disks=frozenset({variant.id}),
                            banned_rooms=frozenset({variant.variant_of}))
    assert not any(r.id == variant.id for r in eligible_pool(registry, cfg_banned))


def test_key_8_is_a_daily_gallery_find_not_a_carried_item():
    """Key 8 does not survive the night; it is guaranteed in the Gallery instead.

    Unlocking it makes it appear in the Gallery every day, and the sim assumes
    any entered room's puzzle is solved — so the find, not the inventory, is
    what persists.
    """
    from blueprince_sim.engine.model import Registry
    registry = Registry.load()
    assert "key_8" in registry.special.guaranteed_by_room["gallery"]
    g = _game_with("key_8")
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "key_8" not in carried
