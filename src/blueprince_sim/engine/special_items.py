"""Special items: inventory, spawning, and per-item behavior.

Everything the wiki calls a "special item" (inventory-slot items, as opposed to
the resource counters) lives here: the frozen registry parsed from
data/special_items.json, the mutable per-day state, and the hook functions
game.py/items.py call at fixed integration points. Items whose target system is
not modeled yet carry ``implemented: false`` records — they exist, spawn, and
can be stolen by the Lost & Found, but their use is inert.

Design doc: docs/special-items-design.md. Data provenance:
docs/research/special-items-wiki.md.

Like the effects/ handlers, hook functions take the ``game`` orchestrator
duck-typed (no import of Game) to keep this module free of import cycles:
state.py imports SpecialItemsState from here, model.py lazily imports the
loader, and this module imports only model/rng types.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .model import Effect

KINDS = ("standard", "special_key", "contraption", "showroom", "armory", "unique")
PERSISTENCE = ("day", "until_used", "permanent")

# Items the generic SPAWN pipeline must never touch: the Keycard is owned by
# engine/locks.py (state.has_keycard), kept there so the security door system
# stays self-contained. The Lost & Found can still steal it (it special-cases
# has_keycard directly).
PIPELINE_EXCLUDED = frozenset({"keycard"})


@dataclass(frozen=True, slots=True)
class SpecialItem:
    id: str  # stable snake_case identifier, unique across special_items.json
    name: str  # human-readable display name
    kind: str  # standard|special_key|contraption|showroom|armory|unique
    tier: int | None  # Trading Post tier 1-5; None = untradeable
    unique: bool  # at most one may be held
    persistence: str  # day|until_used|permanent (consumed by the PR2 carry-over layer)
    spawn_rooms: tuple[str, ...]  # room ids where it can spawn on first entry
    spawn_rooms_high_luck: tuple[str, ...]  # extra pool entries at luck >= spawn.high_luck_at
    guaranteed_in: tuple[str, ...]  # room ids that always contain it on first entry
    effects: tuple[Effect, ...]  # behavior tags dispatched by the functions below
    implemented: bool  # False = inert record (meta.blocked_on says what's missing)
    confidence: str = "wiki"  # data provenance: datamined > wiki > inferred > placeholder

    def effect(self, tag: str) -> Effect | None:
        """The item's effect record for ``tag``, or None if it doesn't carry it."""
        for e in self.effects:
            if e.tag == tag:
                return e
        return None


@dataclass(frozen=True)
class SpecialItemsRegistry:
    items: tuple[SpecialItem, ...]  # every item, in special_items.json order
    by_id: dict[str, SpecialItem]  # item id -> SpecialItem lookup
    spawn_rules: dict  # "spawn" section: special_share, high_luck_at
    dig_rules: dict  # "dig" section: tables, coin_pile_split, turnip_steps
    treasure_map: dict  # "treasure_map" section: cells, rewards
    lost_and_found: dict  # "lost_and_found" section: gives, pool
    fabrication: tuple[tuple[tuple[str, ...], str], ...]  # ((inputs...), output)
    trading: dict  # "trading" section (consumed by PR2)
    containers: dict = field(default_factory=dict)  # "containers" section: kinds/rooms/garage_car
    # room id -> item ids that can spawn there (derived; excludes guaranteed_in)
    spawn_pool_by_room: dict[str, tuple[str, ...]] = field(default_factory=dict)
    spawn_pool_high_luck: dict[str, tuple[str, ...]] = field(default_factory=dict)
    guaranteed_by_room: dict[str, tuple[str, ...]] = field(default_factory=dict)


def load_special_items(data_dir: Path) -> SpecialItemsRegistry:
    """Parse data/special_items.json into the frozen registry.

    Effect records reuse model.Effect (every key besides "tag" becomes a
    param). Per-room spawn indexes are derived here so entry-time rolls are a
    dict lookup, not a scan over every item.
    """
    raw = json.loads((Path(data_dir) / "special_items.json").read_text())
    items = []
    for r in raw["items"]:
        effects = tuple(
            Effect(tag=e["tag"], params=tuple(sorted((k, v) for k, v in e.items() if k != "tag")))
            for e in r.get("effects", []))
        items.append(SpecialItem(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            tier=r.get("tier"),
            unique=bool(r.get("unique", True)),
            persistence=r.get("persistence", "day"),
            spawn_rooms=tuple(r.get("spawn_rooms", [])),
            spawn_rooms_high_luck=tuple(r.get("spawn_rooms_high_luck", [])),
            guaranteed_in=tuple(r.get("guaranteed_in", [])),
            effects=effects,
            implemented=bool(r.get("implemented", False)),
            confidence=r.get("meta", {}).get("confidence", "wiki"),
        ))
    pool: dict[str, list[str]] = {}
    pool_hl: dict[str, list[str]] = {}
    guaranteed: dict[str, list[str]] = {}
    for it in items:
        if it.id in PIPELINE_EXCLUDED:
            continue
        for room in it.spawn_rooms:
            pool.setdefault(room, []).append(it.id)
        for room in it.spawn_rooms_high_luck:
            pool_hl.setdefault(room, []).append(it.id)
        for room in it.guaranteed_in:
            guaranteed.setdefault(room, []).append(it.id)
    return SpecialItemsRegistry(
        items=tuple(items),
        by_id={i.id: i for i in items},
        spawn_rules=raw["spawn"],
        dig_rules=raw["dig"],
        treasure_map=raw["treasure_map"],
        lost_and_found=raw["lost_and_found"],
        fabrication=tuple((tuple(f["inputs"]), f["output"]) for f in raw.get("fabrication", [])),
        trading=raw.get("trading", {}),
        containers=raw.get("containers", {}),
        spawn_pool_by_room={k: tuple(v) for k, v in pool.items()},
        spawn_pool_high_luck={k: tuple(v) for k, v in pool_hl.items()},
        guaranteed_by_room={k: tuple(v) for k, v in guaranteed.items()},
    )


@dataclass(slots=True)
class SpecialItemsState:
    """Mutable per-day special-item bookkeeping, reset with GameState."""

    enabled: bool = True  # GameConfig.special_items, copied at reset (gates spawning)
    lockpick_attempts: int = 0  # picks tried today (indexes the per-day rate table)
    lockpick_fails: int = 0  # consecutive fails, for the Lock Pick Kit pity rule
    coin_interest: int = 0  # coins collected since the last Coin Purse interest payout
    water: int = 0  # Watering Can charges left (set to capacity on pickup)
    stopwatch_left: int = 0  # free cost events remaining (0 = stopwatch inactive)
    stopwatch_used: bool = False  # a Stopwatch already ran today (unobtainable again)
    moves_since_free: int = 0  # Running Shoes cadence counter
    dug: dict[int, int] = field(default_factory=dict)  # cell -> dig spots already dug
    treasure_cell: int = -1  # Treasure Map X cell; -1 = no map read today
    treasure_dug: bool = False  # the map's one-per-day treasure dig happened
    silver_key_draft: bool = False  # next draw biased toward cross/t layouts
    shield_used: bool = False  # Knight's Shield daily red-room negation spent
    # ids gone for the day (Lost & Found steals, consumed-for-good keys):
    # excluded from spawn pools and (PR2) trade offers
    removed: list[str] = field(default_factory=list)
    spawned_today: list[str] = field(default_factory=list)  # unique ids already spawned
    # config gates: item ids excluded by unlock flags (populated by configure())
    gated_out: list[str] = field(default_factory=list)
    configured: bool = False  # True once configure() has been called this episode
    # room.idx of the room where a special item already spawned today; -1 = none
    spawn_room_done: int = -1
    dining_room_served: bool = False  # main course eaten today (rank-8 gated Dining Room visit)
    # Draft conditions satisfied by in-run events (e.g. "breakfast" from Bacon & Eggs).
    # Checked by satisfied_condition_items alongside item-gated conditions.
    extra_conditions: set[str] = field(default_factory=set)
    # Coat Check: one item stored for pickup at the start of the NEXT day.
    # Set in on_enter when the player enters the Coat Check room; the stored id
    # is returned via end_of_day_carry() and injected as a starting_item.
    # None = no item stored today.
    coat_check_item: str | None = None
    opened_containers: dict[int, int] = field(default_factory=dict)  # cell -> count of containers already opened there
    garage_car_opened: bool = False  # Car Keys garage car trunk used today (once per day)


# --------------------------------------------------------------- inventory ops

def has(state, item_id: str) -> bool:
    """Is at least one of ``item_id`` in the inventory?"""
    return state.inventory.get(item_id, 0) > 0


def count(state, item_id: str) -> int:
    return state.inventory.get(item_id, 0)


def _is_available(state, item_id: str, registry) -> bool:
    """True when ``item_id`` can be granted or spawned right now."""
    if item_id in PIPELINE_EXCLUDED:
        return False
    if item_id in state.special.removed:
        return False
    item = registry.special.by_id.get(item_id)
    if item is not None and item.unique:
        if state.inventory.get(item_id, 0) > 0:
            return False
        if item_id in state.special.spawned_today:
            return False
    # A Stopwatch that already ran today is unobtainable again.
    if (item is not None and item.effect("stopwatch") is not None
            and state.special.stopwatch_used):
        return False
    if item_id in state.special.gated_out:
        return False
    return True


def grant(state, registry, item_id: str, source: str = "spawn") -> None:
    """Add one ``item_id`` to the inventory, log it, and fire pickup effects.

    Auto-pickup is a documented simplification: spawned items are always
    taken. Unique items never stack (granting a held unique is a no-op).
    The Stopwatch is unobtainable again today once it has already run.
    """
    item = registry.special.by_id.get(item_id)
    # Stopwatch: unobtainable again today once it has been used
    if item is not None and item.effect("stopwatch") is not None and state.special.stopwatch_used:
        return
    if item is not None and item.unique and has(state, item_id):
        return
    state.inventory[item_id] = state.inventory.get(item_id, 0) + 1
    state.items_found_log.append((item_id, 1))
    if item is not None:
        state.special.spawned_today.append(item_id)
        _on_pickup(state, registry, item)


def remove(state, item_id: str, *, consumed: bool = False) -> None:
    """Take one ``item_id`` out of the inventory.

    ``consumed=True`` marks it gone for the day (spawn pools and PR2 trades
    skip it) — Lost & Found steals and one-shot keys use this.
    """
    n = state.inventory.get(item_id, 0)
    if n <= 0:
        return
    if n == 1:
        del state.inventory[item_id]
    else:
        state.inventory[item_id] = n - 1
    if consumed:
        state.special.removed.append(item_id)


def check_lunch_box(state, registry, item=None) -> None:
    """Consume the Lunch Box and grant food-modified steps if held at rank >= its threshold.

    The Lunch Box's step count (10, from data) is the *base* fed into the food
    pipeline, so Salt Shaker / Silver Spoon modify it: 10 → 11 → 22.

    Called from _on_pickup (pickup at high rank) and task C's on_arrive
    (rank-crossing check on each arrival).
    """
    if item is None:
        item = registry.special.by_id.get("lunch_box")
        if item is None or not has(state, "lunch_box"):
            return
    e = item.effect("steps_at_rank")
    if e is None:
        return
    from .grid import rank_of
    if rank_of(state.pos) < e.param("rank", 5):
        return
    remove(state, "lunch_box", consumed=True)
    # Use the item's own steps param as the food-pipeline base (10), so
    # Salt Shaker (+1) and Silver Spoon (×2) modify it correctly.
    base = e.param("steps", 3)
    steps_gained = food_steps(state, registry, base)
    state.steps += steps_gained
    state.items_found_log.append(("food", 1))


def _on_pickup(state, registry, item: SpecialItem) -> None:
    """Immediate effects of picking an item up.

    The Treasure Map's marked cell is resolved lazily in on_arrive/dig_all
    where game.rng is available; no action is taken here at pickup time.
    """
    # set_steps_on_pickup (Cursed Effigy): clamp steps to value only if above it
    e = item.effect("set_steps_on_pickup")
    if e is not None:
        value = e.param("value", 13)
        only_if_above = e.param("only_if_above", False)
        if not only_if_above or state.steps > value:
            state.steps = value

    # watering_can: fill charges to capacity on pickup
    e = item.effect("watering_can")
    if e is not None:
        state.special.water = e.param("capacity", 3)

    # stopwatch: activate (grant already blocked a re-grant, so this always fires first time)
    e = item.effect("stopwatch")
    if e is not None:
        if not state.special.stopwatch_used:
            state.special.stopwatch_left = e.param("free_costs", 10)
            state.special.stopwatch_used = True

    # steps_at_rank (Lunch Box): consume immediately if already at/above rank threshold
    e = item.effect("steps_at_rank")
    if e is not None:
        check_lunch_box(state, registry, item)

    # treasure_map: the marked cell is resolved lazily in on_arrive/dig_all
    # when game.rng is available. No action needed at pickup time.


# ------------------------------------------------------------------ config gates

def configure(state, cfg) -> None:
    """Populate config-gated item exclusions; idempotent (safe to call every on_enter)."""
    if state.special.configured:
        return
    state.special.configured = True
    gated = []
    if not cfg.lunch_box_unlocked:
        gated.append("lunch_box")
    if not cfg.cursed_effigy_unlocked:
        gated.append("cursed_effigy")
    # Royal Scepter: gate out of spawn pool unless the carry-over flag is set.
    # (Finding the scepter in-run requires the unmodeled Treasure Trove / Key of
    # Aries puzzle; with royal_scepter_found it is granted at reset time instead.)
    if not cfg.royal_scepter_found:
        gated.append("royal_scepter")
    state.special.gated_out = gated


# ------------------------------------------------------------- spawn pipeline

def roll_special_spawn(state, registry, room, rng) -> str | None:
    """Resolve one additional-item proc to a special item, or None to fall
    through to the regular EXTRA_ITEM_TABLE kinds.

    Modeling assumption (inferred): with probability spawn.special_share, a
    luck-proc in a room with a non-empty spawn pool yields a uniformly random
    still-available pool item (high-luck entries join at luck >=
    spawn.high_luck_at); at most one special item spawns per room per day.
    Grants the item itself and returns its id, or returns None.
    """
    if not state.special.enabled:
        return None
    # At most one special item per room per day
    if state.special.spawn_room_done == room.idx:
        return None
    if not registry.special.by_id:
        return None

    # Build pool: base entries + high-luck entries when effective luck qualifies
    effective_luck = state.luck + luck_bonus(state, registry)
    high_luck_at = registry.special.spawn_rules.get("high_luck_at", 16)

    pool = list(registry.special.spawn_pool_by_room.get(room.id, ()))
    if effective_luck >= high_luck_at:
        pool = pool + list(registry.special.spawn_pool_high_luck.get(room.id, ()))

    # Filter to currently available items
    pool = [iid for iid in pool if _is_available(state, iid, registry)]
    if not pool:
        return None

    # Roll the special-share chance
    special_share = registry.special.spawn_rules.get("special_share", 25) / 100.0
    if not rng.chance("special_spawn", special_share):
        return None

    # Pick uniformly from the available pool
    idx = rng.randint("special_kind", 0, len(pool) - 1)
    item_id = pool[idx]
    grant(state, registry, item_id, source="spawn")
    state.special.spawn_room_done = room.idx
    return item_id


def on_enter(game, room, cell: int) -> None:
    """First-entry hooks: guaranteed spawns, Lost & Found, Sleeping Mask,
    Watering Can, Dining Room main course. Called from Game._enter after
    roll_room_items. Tasks B (spawns, Lost & Found) and C (mask, can).
    """
    state = game.state
    registry = game.registry
    configure(state, game.cfg)

    # Grant items guaranteed in this room (filtered by standard availability rules)
    for item_id in registry.special.guaranteed_by_room.get(room.id, ()):
        if _is_available(state, item_id, registry):
            grant(state, registry, item_id, source="guaranteed")

    # Dining Room main course (rank-8 gated; also checked on every arrival so
    # a return visit after reaching Rank 8 serves it).
    _maybe_serve_main_course(state, registry)

    # Lunch Box: guaranteed in the Dining Room (and upgrade variants) when unlocked
    if game.cfg.lunch_box_unlocked:
        if room.id == "dining_room" or room.variant_of == "dining_room":
            if _is_available(state, "lunch_box", registry):
                grant(state, registry, "lunch_box", source="guaranteed")

    # Lost & Found: steal one held item and grant two draws from the pool
    if room.id == "lost_and_found":
        lost_and_found_on_enter(game)

    # Coat Check: store the most valuable held item overnight.
    # The real game lets the player choose which item to store and retrieve it on
    # any later day; we auto-store the highest-tier item (ties broken by id for
    # determinism) and auto-return it at the start of the NEXT day.  Only fires
    # if the player holds at least one non-excluded item and no item is already
    # stored this day.  (Simplification documented in docs/special-items-design.md.)
    if room.id == "coat_check" and state.special.coat_check_item is None:
        coat_check_on_enter(game)

    # Sleeping Mask: grant steps when entering a bedroom (including Bunk Room x2)
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("sleeping_mask")
        if e is not None and room.category == "bedroom":
            steps_per = e.param("steps", 5)
            bed_count_effect = next(
                (ef for ef in room.effects if ef.tag == "counts_as_bedrooms"), None)
            amount = bed_count_effect.param("amount", 1) if bed_count_effect is not None else 1
            state.steps += steps_per * amount
            break  # only one sleeping mask can be held (unique)

    # Watering Can: convert one water charge to one gem on entering a green room
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        if item.effect("watering_can") is not None and room.category == "green":
            if state.special.water > 0:
                state.special.water -= 1
                state.gems += 1
            break


def _maybe_serve_main_course(state, registry) -> None:
    """Serve the day's Dining Room Main Course if it is due.

    The course is only served once the player has REACHED Rank 8 (some
    entered cell at rank >= 8): entering the Dining Room earlier means
    returning to eat it later, while a Dining Room drafted at rank 8/9 serves
    immediately on entry. Once per day; the day's dish is cycle[day % 5];
    the boost-room check happens inside eat_food.
    """
    from .grid import rank_of
    if not state.special.enabled or state.special.dining_room_served:
        return
    if state.outer_loc != 0:
        return
    room_idx = state.grid[state.pos]
    if room_idx < 0:
        return
    room = registry.rooms[room_idx]
    if room.id != "dining_room" and room.variant_of != "dining_room":
        return
    if not any(entered and rank_of(c) >= 8 for c, entered in enumerate(state.entered)):
        return
    state.special.dining_room_served = True
    cycle = registry.item_rules.get("food", {}).get("main_course_cycle", [])
    if cycle:
        eat_food(state, registry, cycle[state.day % len(cycle)])


def on_arrive(game, cell: int) -> None:
    """Every-arrival hooks (including re-entry): auto-dig, Treasure Map,
    Lunch Box rank check, Dining Room main course (rank-8 gated return
    visits). Called from Game.move after entering. Task C.
    """
    check_lunch_box(game.state, game.registry)
    _maybe_serve_main_course(game.state, game.registry)

    # Treasure Map: resolve the marked cell lazily on first arrival after pickup
    state = game.state
    if has(state, "treasure_map") and state.special.treasure_cell == -1:
        cells = game.registry.special.treasure_map["cells"]
        state.special.treasure_cell = game.rng.choice("treasure_map", cells)

    dig_all(game, cell)


def on_place(game, room, cell: int) -> None:
    """Metal Detector / Powered Electromagnet extra key/coin spawns in the
    room just drafted. Called from Game._place_room. Task C.
    """
    state = game.state
    registry = game.registry

    # Find metal_detector_spawns effect from any held item (detector or detector_shovel)
    spawns_effect = None
    has_auto_collect = False
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        if spawns_effect is None:
            e = item.effect("metal_detector_spawns")
            if e is not None:
                spawns_effect = e
        if not has_auto_collect and item.effect("auto_collect") is not None:
            has_auto_collect = True

    if spawns_effect is not None or has_auto_collect:
        coins_chance = spawns_effect.param("coins_chance", 60) if spawns_effect else 60
        key_chance = spawns_effect.param("key_chance", 25) if spawns_effect else 25

        if game.rng.chance("detector_coin", coins_chance / 100.0):
            bonus = on_coins_granted(state, registry, 1)
            state.coins += 1 + bonus
            state.items_found_log.append(("coins", 1))

        if game.rng.chance("detector_key", key_chance / 100.0):
            state.keys += 1
            state.items_found_log.append(("key", 1))

    # Secret Garden Key: consumed when the Secret Garden is placed (max one per day;
    # the key does not return to the spawn pool, consumed=True).
    if room.id == "secret_garden" and has(state, "secret_garden_key"):
        remove(state, "secret_garden_key", consumed=True)


def lost_and_found_on_enter(game) -> None:
    """Steal one uniformly random held special item (nothing if none held),
    then grant lost_and_found.gives draws from the data pool.
    """
    state = game.state
    registry = game.registry
    rng = game.rng

    # Steal one random held item. The Keycard is stealable like anything else,
    # but lives on state.has_keycard (engine/locks.py), not the inventory.
    held = [iid for iid, cnt in state.inventory.items()
            if cnt > 0 and iid not in PIPELINE_EXCLUDED]
    if state.has_keycard:
        held.append("keycard")
    if held:
        stolen_id = rng.choice("lost_and_found", held)
        if stolen_id == "keycard":
            # Re-findable later via the locks.py source-room rolls, matching
            # the pool-return behavior of other stolen items well enough.
            state.has_keycard = False
        else:
            remove(state, stolen_id, consumed=True)

    # Grant lost_and_found.gives draws from the pool
    lf = registry.special.lost_and_found
    gives = lf.get("gives", 2)
    pool = lf.get("pool", [])

    from . import items as items_mod  # deferred: items.py imports this module

    for _ in range(gives):
        # "die" is always available; items filtered by standard availability
        available = [e for e in pool
                     if e == "die" or _is_available(state, e, registry)]
        if not available:
            continue
        chosen = rng.choice("lost_and_found", available)
        if chosen == "die":
            items_mod.grant_item(state, "die", 1, rng, registry)
        else:
            grant(state, registry, chosen, source="lost_and_found")


def coat_check_on_enter(game) -> None:
    """Auto-store the most valuable held item in the Coat Check for overnight.

    Picks the highest-tier item from inventory (untradeable/no tier counts as 0;
    ties broken alphabetically by id for determinism).  The stored item is NOT
    removed from today's inventory — the player keeps it for the rest of the day.
    It is returned by end_of_day_carry() as a starting_item for tomorrow.

    Simplification: the real game lets the player choose which item to store
    and retrieve it on any later day.  We auto-store the best item and
    auto-return it exactly the next day.  (Documented in docs/special-items-design.md.)
    """
    state = game.state
    registry = game.registry

    # Collect all held items that are not excluded from the pipeline
    held = [
        iid for iid, cnt in state.inventory.items()
        if cnt > 0 and iid not in PIPELINE_EXCLUDED
    ]
    if not held:
        return

    def _item_sort_key(iid: str):
        item = registry.special.by_id.get(iid)
        tier = item.tier if (item is not None and item.tier is not None) else 0
        return (-tier, iid)  # highest tier first; ties broken by id ascending

    best = sorted(held, key=_item_sort_key)[0]
    state.special.coat_check_item = best


def end_of_day_carry(state, registry, rng) -> list[str]:
    """Compute the item ids that persist into tomorrow's starting_items.

    Carry channels (in priority order — results are de-duplicated):
    1. Self-persisting items: any held item whose record has persistence
       "permanent" or "until_used".
    2. Coat Check: the item stored when the player entered the Coat Check room
       this day (state.special.coat_check_item), if any.
    3. Moon Pendant: if held at end of day, TWO uniformly random distinct items
       from the full held inventory (moon_pendant itself is eligible) carry over.
       The selection is deterministic given ``rng`` (substream "moon_pendant_carry").

    Returns a sorted, de-duplicated list of item ids.  Does NOT include items
    that are currently absent from the inventory (the coat_check_item may have
    been stolen by the Lost & Found after storage, for example; we check held
    status only for the Moon Pendant draw, but the Coat Check item is returned
    regardless since it is conceptually "at the Coat Check", not in inventory).

    Caller (shops.carryover / DayChain) is responsible for injecting these into
    the next day's GameConfig.starting_items.
    """
    result: set[str] = set()

    # 1. Self-persisting items (permanent or until_used)
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is not None and item.persistence in ("permanent", "until_used"):
            result.add(item_id)

    # 2. Coat Check stored item (returns to player next day regardless of
    # what happened to the inventory copy this day)
    if state.special.coat_check_item is not None:
        result.add(state.special.coat_check_item)

    # 3. Moon Pendant: 2 random distinct held items (pendant itself eligible)
    if has(state, "moon_pendant"):
        held_ids = sorted(
            iid for iid, cnt in state.inventory.items() if cnt > 0
        )
        if len(held_ids) <= 2:
            # Fewer than 2 held: all carry anyway
            result.update(held_ids)
        else:
            # Draw 2 distinct ids uniformly at random from the held set
            indices = list(range(len(held_ids)))
            rng.shuffle("moon_pendant_carry", indices)
            result.add(held_ids[indices[0]])
            result.add(held_ids[indices[1]])

    return sorted(result)


# ------------------------------------------------------- movement & door costs

def move_step_cost(game, from_cell: int, direction: int, to_room) -> int:
    """Step cost of one move: 1, or 0 via Hall Pass (hallway to hallway),
    Running Shoes cadence, or an active Stopwatch. Task C.

    Priority: Hall Pass first (doesn't consume stopwatch/shoes charges),
    then Stopwatch, then Running Shoes.
    """
    state = game.state
    registry = game.registry

    # Hall Pass: hallway-to-hallway moves are free (no counter consumed)
    from_idx = state.grid[from_cell]
    if from_idx >= 0:
        from_room = registry.rooms[from_idx]
        if (from_room.category == "hallway" and to_room.category == "hallway"
                and _has_item_effect(state, registry, "free_hallway_moves")):
            return 0

    # Stopwatch: active free cost event
    if state.special.stopwatch_left > 0:
        state.special.stopwatch_left -= 1
        return 0

    # Running Shoes: every n-th move is free
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("free_move_interval")
        if e is not None:
            n = e.param("n", 3)
            if (state.special.moves_since_free + 1) % n == 0:
                state.special.moves_since_free = 0
                return 0
            else:
                state.special.moves_since_free += 1
                return 1

    return 1


def can_open_locked_free(game) -> bool:
    """Deterministic free open of a locked door (Master Key), used by
    passability/nav so paths don't budget keys the player won't spend."""
    return _has_item_effect(game.state, game.registry, "master_key")


def open_locked_free(game) -> bool:
    """Try to open a locked door without spending a key: Master Key,
    active Stopwatch (needs a key in hand, per the wiki), else a Lock Pick
    Kit / Pick Sound Amplifier attempt with the datamined rates and pity
    rule. Called once per locked-door opening. Task C."""
    state = game.state
    registry = game.registry

    # Master Key: always free, deterministic
    if can_open_locked_free(game):
        return True

    # Stopwatch: free if active and a key is in hand (key is kept, per wiki)
    if state.special.stopwatch_left > 0 and state.keys >= 1:
        state.special.stopwatch_left -= 1
        return True

    # Lock Pick Kit / Pick Sound Amplifier: probabilistic with pity
    # Prefer the Amplifier when both are held (better rates, no pity drain)
    lockpick_effect = None
    for preferred in ("pick_sound_amplifier", "lock_pick_kit"):
        if has(state, preferred):
            item = registry.special.by_id.get(preferred)
            if item is not None:
                e = item.effect("lockpick")
                if e is not None:
                    lockpick_effect = e
                    break

    if lockpick_effect is None:
        return False

    rates = lockpick_effect.param("rates", [54, 35, 30, 19])
    denominator = lockpick_effect.param("denominator", 101)
    pity = lockpick_effect.param("pity", 0)

    attempt = state.special.lockpick_attempts
    rate_idx = min(attempt, len(rates) - 1)
    state.special.lockpick_attempts += 1

    # Pity rule: if pity > 0 and consecutive fails >= pity threshold, auto-succeed
    if pity > 0 and state.special.lockpick_fails >= pity:
        state.special.lockpick_fails = 0
        return True

    if game.rng.chance("lockpick", rates[rate_idx] / denominator):
        state.special.lockpick_fails = 0
        return True
    else:
        state.special.lockpick_fails += 1
        return False


# ------------------------------------------------------------- draft-side hooks

def gem_cost_modifier(game, room, cost: int) -> int:
    """Emerald Bracelet waiver, Hall Pass hallway-from-hallway drafts,
    Stopwatch waiver. Task C.

    Priority: Emerald Bracelet first, then Hall Pass, then Stopwatch.
    Only one waiver applies — no double-decrement.
    """
    state = game.state
    registry = game.registry
    if cost <= 0:
        # Nothing to waive: never burn a Stopwatch charge on a free room.
        return cost

    # Emerald Bracelet: always waive gem cost
    if _has_item_effect(state, registry, "emerald_bracelet"):
        return 0

    # Hall Pass: waive if drafting a hallway room from a hallway room
    if room.category == "hallway" and state.pending is not None:
        from_cell = state.pending.from_cell
        if from_cell >= 0 and state.grid[from_cell] >= 0:
            from_room = registry.rooms[state.grid[from_cell]]
            if (from_room.category == "hallway"
                    and _has_item_effect(state, registry, "free_hallway_moves")):
                return 0

    # Stopwatch gem waiver happens at PAY time (stopwatch_waives_gems), never
    # here: this runs on every affordability query and must stay pure.
    return cost


def stopwatch_waives_gems(game, cost: int) -> bool:
    """Waive a gem payment via an active Stopwatch (gems must be in hand, per
    the wiki). Called once per actual payment (Game._pay), spending a charge."""
    state = game.state
    if cost > 0 and state.special.stopwatch_left > 0 and state.gems >= cost:
        state.special.stopwatch_left -= 1
        return True
    return False


def inventory_value(state, registry) -> float:
    """Reward-shaping worth of the held special items.

    Each item counts its Trading Post tier's value from items.json
    special_item_values (untradeable items use the flat value). Purely a
    shaping/reporting number — no game rule reads it. Keeping it here (not in
    rewards.py) keeps the tier lookup beside the item registry it indexes.
    """
    if not state.inventory:
        return 0.0
    values = registry.item_rules.get("special_item_values", {})
    by_tier = values.get("by_tier", {})
    flat = values.get("untradeable", 0.0)
    total = 0.0
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        worth = by_tier.get(str(item.tier), flat) if item.tier is not None else flat
        total += worth * cnt
    return total


def luck_bonus(state, registry) -> int:
    """Flat luck added while lucky charms are held (Rabbit's Foot / Lucky
    Purse +3). Applied to effective luck, never stored.
    """
    if not state.inventory:
        return 0
    total = 0
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("luck_bonus")
        if e is not None:
            total += e.param("amount", 0) * cnt
    return total


def on_coins_granted(state, registry, amount: int) -> int:
    """Coin Purse / Lucky Purse interest owed on ``amount`` collected coins;
    returns bonus coins (caller adds them).

    Lucky Purse (coin_multiplier) doubles coins and supersedes Coin Purse.
    Coin Purse (coin_interest) pays 1 bonus per 3 coins across pickups.
    """
    # Lucky Purse: doubles the incoming amount (supersedes Coin Purse)
    if _has_item_effect(state, registry, "coin_multiplier"):
        return amount
    # Coin Purse: accumulate interest; pay 1 per 3 coins collected
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("coin_interest")
        if e is not None:
            per = e.param("per", 3)
            bonus_per = e.param("bonus", 1)
            state.special.coin_interest += amount
            earned = state.special.coin_interest // per
            state.special.coin_interest %= per
            return earned * bonus_per
    return 0


def _resolve_food_base(state, registry, food_id: str) -> int:
    """Resolve the base step count for one serving of ``food_id``.

    Looks up the dish record in items.json food.dishes:
    - ``steps``: flat step value (banana, club_sandwich, main courses).
    - ``steps_per_category``: steps × count of grid rooms of that category
      (chef_salad/tomato_soup; count taken at eat time, as the wiki states).
    - ``boost_room`` + ``boosted_steps``: boosted_steps when that room is
      anywhere on the estate (any cell in state.grid), else base steps
      (main courses: salmon, steak, stew_pie, quail, pizza).
    Falls back to ``food.default_steps`` (3) for unknown dish ids.
    """
    food_rules = registry.item_rules.get("food", {})
    default_steps = food_rules.get("default_steps", 3)
    dish = food_rules.get("dishes", {}).get(food_id)
    if dish is None:
        return default_steps

    if "steps_per_category" in dish:
        # Chef Salad / Tomato Soup: count grid rooms of each named category
        total = 0
        for cat, per_room in dish["steps_per_category"].items():
            n = sum(
                1 for idx in state.grid if idx >= 0
                and registry.rooms[idx].category == cat
            )
            total += n * per_room
        return total

    if "boost_room" in dish:
        # Main courses: check if the boost room is anywhere on the estate
        boost_id = dish["boost_room"]
        on_estate = any(
            idx >= 0 and registry.rooms[idx].id == boost_id
            for idx in state.grid
        )
        return dish["boosted_steps"] if on_estate else dish["steps"]

    return dish.get("steps", default_steps)


def eat_food(state, registry, food_id: str = "banana", count: int = 1) -> None:
    """Eat ``count`` food items of kind ``food_id``, granting steps.

    Per-dish resolution via ``_resolve_food_base``: flat steps (banana,
    club_sandwich), category-count steps (chef_salad/tomato_soup), or
    boost-room-conditional steps (main courses). Unknown dishes fall back
    to food.default_steps (3). Salt Shaker / Silver Spoon apply per item
    via :func:`food_steps`. ``inject_rooms`` dishes are NOT handled here —
    callers that have access to ``game`` must check the dish record and call
    ``game.inject_rooms`` after eat_food for those dishes.
    """
    base = _resolve_food_base(state, registry, food_id)
    for _ in range(count):
        state.steps += food_steps(state, registry, base)
        state.items_found_log.append(("food", 1))


def food_steps(state, registry, base: int) -> int:
    """Steps granted by one food item: base, +1 with the Salt Shaker, then
    doubled by the Silver Spoon (in that order, per the wiki).
    """
    total = base
    # Salt Shaker: add food_bonus amount first
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("food_bonus")
        if e is not None:
            total += e.param("amount", 0)
    # Silver Spoon: then double
    if _has_item_effect(state, registry, "food_multiplier"):
        total *= 2
    return total


def _has_item_effect(state, registry, tag: str) -> bool:
    """True when any held item carries ``tag`` as one of its effects."""
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is not None and item.effect(tag) is not None:
            return True
    return False


def compass_active(game) -> bool:
    """North-bias rotation rolls: config flag, held Compass, or a Powered
    Electromagnet (its compass effect persists while held)."""
    return game.cfg.compass or _has_item_effect(game.state, game.registry, "compass")


def ornate_compass_active(game) -> bool:
    """Rotate-at-will on every draft: config flag or held Ornate Compass."""
    return game.cfg.ornate_compass or _has_item_effect(
        game.state, game.registry, "ornate_compass")


def compass_active_from_state(state, registry, cfg) -> bool:
    """Compass-active check from state/registry/cfg (no game object).

    Used by draft.py where game is not available. Checks the config flag
    and any held item carrying the ``compass`` effect tag.
    """
    return cfg.compass or _has_item_effect(state, registry, "compass")


def satisfied_condition_items(state) -> set[str]:
    """Draft-condition gates granted by held items or in-run events.

    key_8 -> room8_key (Key 8 is not consumed on use).
    secret_garden_key -> secret_garden_key (consumed on placement by on_place).
    state.special.extra_conditions: conditions added mid-run (e.g. "breakfast"
    when Bacon & Eggs is eaten from the Kitchen).
    """
    conds: set[str] = set()
    if state.inventory.get("key_8", 0) > 0:
        conds.add("room8_key")
    if state.inventory.get("secret_garden_key", 0) > 0:
        conds.add("secret_garden_key")
    conds.update(state.special.extra_conditions)
    return conds


def shield_negates(game) -> bool:
    """Knight's Shield: negate the first red-room negative effect today.

    Returns True and sets shield_used=True when a held item carries
    ``mask_red_room`` or ``negate_red_once_per_day`` and the daily charge
    has not yet been spent. Auto-applies to the first negative red-room
    effect (simplification #6 in docs/special-items-design.md).
    """
    state = game.state
    registry = game.registry
    if state.special.shield_used:
        return False
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        if (item.effect("mask_red_room") is not None
                or item.effect("negate_red_once_per_day") is not None):
            state.special.shield_used = True
            return True
    return False


# ------------------------------------------------------------------- digging

def dig_all(game, cell: int) -> None:
    """Dig every remaining spot at ``cell`` with the best held digging tool
    (auto-dig simplification: digging is free, so skipping it is dominated).
    Also handles the Treasure Map dig at the marked cell. Task C.

    Tool priority (best table first): jack_hammer > detector_shovel > shovel.
    Detector shovel table entries carry explicit coin amounts; other tables
    sub-roll coin_pile_split for the 1-4 coin spread.
    """
    state = game.state
    registry = game.registry

    # Find the best dig tool held (hardcoded priority: better tables win)
    _DIG_PRIORITY = ("jack_hammer", "detector_shovel", "shovel")
    tool_item = None
    table_name = None
    for tool_id in _DIG_PRIORITY:
        if has(state, tool_id):
            item = registry.special.by_id.get(tool_id)
            if item is not None:
                e = item.effect("dig_tool")
                if e is not None:
                    tool_item = item
                    table_name = e.param("table")
                    break

    # Dig remaining spots in the room at this cell
    if state.grid[cell] >= 0:
        room = registry.rooms[state.grid[cell]]
        total_spots = room.items.dig_spots
        already_dug = state.special.dug.get(cell, 0)
        remaining = total_spots - already_dug

        if remaining > 0 and tool_item is not None:
            table = registry.special.dig_rules["tables"][table_name]
            weights = tuple(entry["weight"] for entry in table)
            coin_split = registry.special.dig_rules["coin_pile_split"]
            turnip_steps_val = registry.special.dig_rules["turnip_steps"]

            for _ in range(remaining):
                idx = game.rng.roll_weighted("dig", weights)
                entry = table[idx]
                kind = entry["kind"]

                if kind in ("junk", "nothing"):
                    pass
                elif kind == "coins":
                    if "amount" in entry:
                        n_coins = entry["amount"]
                    else:
                        split_weights = tuple(float(w) for w in coin_split)
                        split_idx = game.rng.roll_weighted("dig_kind", split_weights)
                        n_coins = split_idx + 1
                    bonus = on_coins_granted(state, registry, n_coins)
                    state.coins += n_coins + bonus
                    state.items_found_log.append(("coins", n_coins))
                elif kind == "gold_coin":
                    bonus = on_coins_granted(state, registry, 1)
                    state.coins += 1 + bonus
                    state.items_found_log.append(("coins", 1))
                elif kind == "gems":
                    count = entry.get("count", 2)
                    state.gems += count
                    state.items_found_log.append(("gem", count))
                elif kind == "turnip":
                    steps_gained = food_steps(state, registry, turnip_steps_val)
                    state.steps += steps_gained
                    state.items_found_log.append(("food", 1))
                elif kind == "key":
                    state.keys += 1
                    state.items_found_log.append(("key", 1))
                elif kind == "item":
                    item_id = entry["id"]
                    if _is_available(state, item_id, registry):
                        grant(state, registry, item_id, source="dig")
                    else:
                        bonus = on_coins_granted(state, registry, 1)
                        state.coins += 1 + bonus
                        state.items_found_log.append(("coins", 1))

            state.special.dug[cell] = total_spots

    # Treasure Map: one-per-day dig at the marked cell
    if (state.special.treasure_cell == cell
            and not state.special.treasure_dug
            and tool_item is not None):
        rewards = registry.special.treasure_map["rewards"]
        reward = game.rng.choice("treasure_map", rewards)
        coins = reward.get("coins", 0)
        gems = reward.get("gems", 0)
        if coins > 0:
            bonus = on_coins_granted(state, registry, coins)
            state.coins += coins + bonus
            state.items_found_log.append(("coins", coins))
        if gems > 0:
            state.gems += gems
            state.items_found_log.append(("gem", gems))
        state.special.treasure_dug = True


# ----------------------------------------------------------------- containers

def containers_in(registry, room_id: str) -> dict[str, int]:
    """Container kinds and counts for ``room_id``, or {} if none.

    Reads from registry.special.containers["rooms"]; returns e.g. {"trunk": 1}.
    """
    return dict(registry.special.containers.get("rooms", {}).get(room_id, {}))


def _container_kinds_at(state, registry, cell: int) -> list[tuple[str, int]]:
    """Remaining openable (kind, remaining_count) pairs at ``cell``.

    Subtracts already-opened count from the room's total per kind.
    Returns an empty list when there are no containers or all are opened.
    """
    if state.grid[cell] < 0:
        return []
    room = registry.rooms[state.grid[cell]]
    all_kinds = containers_in(registry, room.id)
    if not all_kinds:
        return []
    already = state.special.opened_containers.get(cell, 0)
    total = sum(all_kinds.values())
    remaining = total - already
    if remaining <= 0:
        return []
    # Deterministic open order: trunk first, then chest, then locker_open, then
    # locker_locked, then any other kinds in stable insertion order.
    _PRIORITY = ("trunk", "chest", "locker_open", "locker_locked", "locker")
    ordered_kinds = list(_PRIORITY)
    for k in all_kinds:
        if k not in _PRIORITY:
            ordered_kinds.append(k)

    result = []
    used = already
    for kind in ordered_kinds:
        n = all_kinds.get(kind, 0)
        if n <= 0:
            continue
        taken = min(used, n)
        left = n - taken
        used -= taken
        if left > 0:
            result.append((kind, left))
    return result


def _next_container_kind(state, registry, cell: int) -> str | None:
    """The kind of the NEXT container to open at ``cell``, or None if exhausted.

    Opens in a deterministic order: trunk first, then chest, then locker.
    """
    pairs = _container_kinds_at(state, registry, cell)
    return pairs[0][0] if pairs else None


def can_open_container(game, cell: int) -> bool:
    """True when the player at ``cell`` can open at least one container there.

    A trunk needs either a smash-tagged item (Sledge Hammer / Morning Star /
    Power Hammer) OR at least 1 key in hand. A chest needs a key. A locker_open
    is always free. A locker_locked needs exactly 1 key — no smash/lockpick/
    master-key substitutes (wiki: lockers are not doors). At least one container
    must remain unopened.
    """
    state = game.state
    registry = game.registry
    kind = _next_container_kind(state, registry, cell)
    if kind is None:
        return False
    kinds_cfg = registry.special.containers.get("kinds", {})
    kind_cfg = kinds_cfg.get(kind, {})
    openers = kind_cfg.get("opener", [])
    if not openers:
        return True  # locker_open or legacy locker: free
    if openers == ["key_only"]:
        # locker_locked: requires exactly one basic key — no special openers
        return state.keys >= 1
    if "smash" in openers and _has_item_effect(state, registry, "smash"):
        return True
    if "key" in openers and state.keys >= 1:
        return True
    return False


def _apply_grant(state, registry, game, grant_entry: dict) -> str:
    """Apply one grant entry from a loot ``grants`` list; return a log tag.

    Supported kinds: coins, keys, gems, dice, item, keycard.
    Unknown kinds are silently skipped and return "".
    """
    from . import items as items_mod  # deferred import to avoid cycles
    gkind = grant_entry.get("kind", "")
    match gkind:
        case "coins":
            amount = grant_entry.get("amount", 1)
            bonus = on_coins_granted(state, registry, amount)
            state.coins += amount + bonus
            state.items_found_log.append(("coins", amount))
            return f"coins:{amount}"
        case "keys":
            amount = grant_entry.get("amount", 1)
            state.keys += amount
            state.items_found_log.append(("key", amount))
            return f"keys:{amount}"
        case "gems":
            amount = grant_entry.get("amount", 1)
            state.gems += amount
            state.items_found_log.append(("gem", amount))
            return f"gems:{amount}"
        case "dice":
            amount = grant_entry.get("amount", 1)
            items_mod.grant_item(state, "die", amount, game.rng, registry)
            state.items_found_log.append(("die", amount))
            return f"dice:{amount}"
        case "keycard":
            state.has_keycard = True
            state.items_found_log.append(("keycard", 1))
            return "keycard"
        case "item":
            item_id = grant_entry.get("id", "")
            if _is_available(state, item_id, registry):
                grant(state, registry, item_id, source="container")
            else:
                # Fallback: 1 coin when the item is unavailable
                bonus = on_coins_granted(state, registry, 1)
                state.coins += 1 + bonus
                state.items_found_log.append(("coins", 1))
                return "coins:1"
            return item_id
        case _:
            return ""


def open_container(game, cell: int) -> str | None:
    """Open ONE unopened container at ``cell``; return what was granted or None.

    Trunk: smash-tagged item is free (no key); else spend 1 key.
    Chest: always spend 1 key (never smashable).
    Locker_open: free.
    Locker_locked: spend exactly 1 key — no smash/lockpick/master-key
    substitutes (wiki: lockers are not doors).

    Loot entries use a ``grants`` list for multi-outcome entries; legacy
    single-grant entries (``kind``/``id``/``amount`` at top level) are not
    used in the shipped data but would need ``grants`` wrapping if added.

    Returns a log string like "coins:5", "gems:3", an item id, or a
    slash-joined multi-grant string like "car_keys/gems:1".
    """
    state = game.state
    registry = game.registry
    kind = _next_container_kind(state, registry, cell)
    if kind is None:
        return None

    kinds_cfg = registry.special.containers.get("kinds", {})
    kind_cfg = kinds_cfg.get(kind, {})
    openers = kind_cfg.get("opener", [])

    # Pay the cost (if any)
    if openers == ["key_only"]:
        # locker_locked: exactly one basic key, no special openers
        if state.keys < 1:
            return None
        state.keys -= 1
    elif openers:
        if "smash" in openers and _has_item_effect(state, registry, "smash"):
            pass  # smash-tagged item opens trunks for free
        elif "key" in openers and state.keys >= 1:
            state.keys -= 1
        else:
            return None  # cannot open

    # Mark one container opened at this cell
    state.special.opened_containers[cell] = state.special.opened_containers.get(cell, 0) + 1

    # Roll loot
    loot_table = kind_cfg.get("loot", [])
    if not loot_table:
        return None
    weights = tuple(float(entry["weight"]) for entry in loot_table)
    idx = game.rng.roll_weighted("container", weights)
    entry = loot_table[idx]

    # New schema: list of grants per outcome
    grants_list = entry.get("grants")
    if grants_list is not None:
        tags = []
        for g in grants_list:
            tag = _apply_grant(state, registry, game, g)
            if tag:
                tags.append(tag)
        return "/".join(tags) if tags else None

    # Legacy single-grant entries (backward compat)
    return _apply_grant(state, registry, game, entry)


def can_open_car_trunk(game) -> bool:
    """True when: special items enabled, Car Keys held, standing in the Garage,
    and the car trunk has not yet been opened today.

    The garage car trunk is a one-per-day mechanic separate from regular containers.
    """
    state = game.state
    registry = game.registry
    if not state.special.enabled:
        return False
    if state.special.garage_car_opened:
        return False
    if not has(state, "car_keys"):
        return False
    if state.grid[state.pos] < 0:
        return False
    room = registry.rooms[state.grid[state.pos]]
    # Accept garage or any garage variant (id starts with "garage")
    garage_ids = getattr(game, "_garage_ids", ())
    if room.id != "garage" and not any(room.id == gid for gid in garage_ids):
        return False
    return True


def open_car_trunk(game) -> list[str]:
    """Use the Car Keys on the Garage car trunk; return list of granted item ids.

    First use ever (cfg.garage_car_used_before is False):
      grants the Upgrade Disk (from garage_car.first_loot).
    Later uses (cfg.garage_car_used_before is True):
      draws later_draws (2) items at random from later_pool + grants later_gold coins.

    One use per day; sets state.special.garage_car_opened=True.
    """
    state = game.state
    registry = game.registry
    cfg = game.cfg
    car_cfg = registry.special.containers.get("garage_car", {})

    state.special.garage_car_opened = True
    granted: list[str] = []

    # First-ever use: grant items from first_loot
    first_loot = car_cfg.get("first_loot", [])
    if not getattr(cfg, "garage_car_used_before", False) and first_loot:
        for entry in first_loot:
            if entry.get("kind") == "item":
                iid = entry["id"]
                if _is_available(state, iid, registry):
                    grant(state, registry, iid, source="garage_car")
                    granted.append(iid)
        return granted

    # Later uses: draw from later_pool + grant later_gold coins
    later_pool = list(car_cfg.get("later_pool", []))
    later_draws = car_cfg.get("later_draws", 2)
    later_gold = car_cfg.get("later_gold", 5)

    available = [iid for iid in later_pool
                 if iid == "keycard" or _is_available(state, iid, registry)]
    for _ in range(later_draws):
        if not available:
            break
        pick_idx = game.rng.randint("garage_car", 0, len(available) - 1)
        picked = available.pop(pick_idx)
        if picked == "keycard":
            state.has_keycard = True
            state.items_found_log.append(("keycard", 1))
            granted.append("keycard")
        elif _is_available(state, picked, registry):
            grant(state, registry, picked, source="garage_car")
            granted.append(picked)

    if later_gold > 0:
        bonus = on_coins_granted(state, registry, later_gold)
        state.coins += later_gold + bonus
        state.items_found_log.append(("coins", later_gold))

    return granted
