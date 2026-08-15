"""Special items: inventory, spawning, and per-item behavior.

Everything the wiki calls a "special item" (inventory-slot items, as opposed to
the resource counters) lives here: the frozen registry parsed from
data/special_items.json, the mutable per-day state, and the hook functions
game.py/items.py call at fixed integration points. Items whose target system is
not modeled yet carry ``implemented: false`` records — they exist, spawn, and
can be stolen by the Lost & Found, but their use is inert.

Design docs: docs/special-items-schema.md (the data contract) and
docs/special-items-behaviour.md (what each item and subsystem does).
Data provenance:
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

from . import constellations, experiments
from .effects import (
    ItemCapability,
    ItemHook,
    container_kinds_for,
    fire_item_chain,
    fold_item_chain,
    item_capability_any,
)
from .effects.items import (
    battery_pack,
    broken_lever,
    car_keys,
    crown_of_the_blueprints,
    cursed_effigy,
    key_8,
    keycard,
    lunch_box,
    moon_pendant,
    morning_star,
    royal_scepter,
    secret_garden_key,
    silver_key,
    sledge_hammer,
    sleeping_mask,
    telescope,
    the_axe,
    treasure_map,
    watering_can,
)
from .model import Effect

KINDS = ("standard", "special_key", "contraption", "showroom", "armory", "unique")
PERSISTENCE = ("day", "until_used", "permanent")

# Dig-tool priority: better tables win; shared with shops.py (imported from there).
DIG_PRIORITY: tuple[str, ...] = ("jack_hammer", "detector_shovel", "shovel")

# Contraption carry-over lockout table (registry.special.contraption_lockout,
# consumed in configure() below) lives in data/special_items.json's
# "contraption_lockout" section, not here -- it is a published wiki table, per
# this repo's own doctrine that published tables belong in data, not Python
# constants. See that section's "meta"."note" for the wiki sourcing.

# --------------------------------------------------- item priority chains
#
# One named, ordered, engine-owned tuple per ItemHook this module fires --
# never a priority= number on the item_hook registration itself, which would
# scatter the total order across the very modules it is supposed to rank.
# Five of these are first-match-wins chains (fire_item_chain: the first
# applicable item in the tuple wins, and items after it are never even
# queried); FOOD_STEPS_PIPELINE is the one genuine ordered fold
# (fold_item_chain: every applicable item transforms the running total).

# ItemHook.GEM_COST: first applicable item wins; only one waiver, ever.
GEM_COST_PRIORITY: tuple[str, ...] = (
    "emerald_bracelet",  # unconditional: waives every gem cost while held
    "hall_pass",  # conditional: only a hallway room drafted from a hallway doorway
)

# ItemHook.MOVE_STEP_COST: first applicable item wins. Hall Pass sits first
# so a free hallway-to-hallway move never touches the Stopwatch or Running
# Shoes counters; Stopwatch outranks Running Shoes so an active timer is
# spent down before distance-based Running Shoes gets a turn.
MOVE_STEP_COST_PRIORITY: tuple[str, ...] = (
    "hall_pass",  # free hallway-to-hallway moves; consumes nothing
    "stopwatch",  # active timer: spends one of its charges
    "running_shoes",  # waives a step once the move ends far enough from the anchor
)

# ItemHook.COINS_GRANTED: first applicable item wins. Lucky Purse's flat
# doubling supersedes Coin Purse outright -- Coin Purse's interest
# accumulator must not advance while Lucky Purse is held, so Lucky Purse
# must be checked, and satisfied, before Coin Purse is even queried.
COINS_GRANTED_PRIORITY: tuple[str, ...] = (
    "lucky_purse",  # doubles every coin pickup; always applies once held
    "coin_purse",  # pays 1 bonus per 3 coins collected; superseded by Lucky Purse
)

# ItemHook.GEM_PAYMENT_WAIVER: a single item today. Kept as a chain (rather
# than an inline check) so a second free-gem-payment item would slot in
# without reshaping stopwatch_waives_gems.
GEM_PAYMENT_WAIVER_PRIORITY: tuple[str, ...] = (
    "stopwatch",  # spends one charge to waive a gem payment (gems stay in hand)
)

# ItemHook.RED_ROOM_NEGATE: a single item today, same rationale as
# GEM_PAYMENT_WAIVER_PRIORITY above.
RED_ROOM_NEGATE_PRIORITY: tuple[str, ...] = (
    "knights_shield",  # spends the once-per-day charge and negates the effect
)

# ItemHook.FOOD_STEP_BONUS: NOT a priority chain -- a genuine ordered fold
# (fold_item_chain). Every held item in this tuple applies its own
# transform to the running total, in this order: Salt Shaker's flat +1 must
# land before Silver Spoon's doubling, per the wiki ((base+1)*2, not
# base+(1*2)).
FOOD_STEPS_PIPELINE: tuple[str, ...] = (
    "salt_shaker",  # add a flat bonus first
    "silver_spoon",  # then double the running total
)

# Items the generic SPAWN pipeline must never touch: the Keycard is owned by
# engine/locks.py (state.has_keycard), kept there so the security door system
# stays self-contained. The Lost & Found can still steal it (it special-cases
# has_keycard directly).
PIPELINE_EXCLUDED = frozenset({keycard.ITEM_ID})

# The eight Sanctum Key source ids (one per spawn site: six on-grid rooms,
# two off-grid areas -- see each record's meta in special_items.json).
# Sorted for deterministic iteration (which held key gets spent first).
SANCTUM_KEY_IDS: tuple[str, ...] = (
    "sanctum_key_clock_tower",
    "sanctum_key_mechanarium",
    "sanctum_key_music_room",
    "sanctum_key_reservoir_north",
    "sanctum_key_room_46",
    "sanctum_key_safehouse",
    "sanctum_key_throne_room",
    "sanctum_key_vault",
)

# The eight Inner Sanctum realm ids, sorted for deterministic iteration and
# stable observation/action ordering (env/actions.py, env/obs.py).
SIGIL_REALMS: tuple[str, ...] = (
    "arch_aries",
    "corarica",
    "eraja",
    "fenn_aries",
    "mora_jai",
    "nuance",
    "orinda_aries",
    "verra",
)


@dataclass(frozen=True, slots=True)
class SpecialItem:
    id: str  # stable snake_case identifier, unique across special_items.json
    name: str  # human-readable display name
    kind: str  # standard|special_key|contraption|showroom|armory|unique
    tier: int | None  # Trading Post tier 1-5; None = untradeable
    receive: bool  # may be offered as a trade RECEIVE; False = give-only (wiki), absent = True
    unique: bool  # at most one may be held
    persistence: str  # day|until_used|permanent (consumed by the PR2 carry-over layer)
    spawn_rooms: tuple[str, ...]  # room ids where it can spawn on first entry
    spawn_rooms_high_luck: tuple[str, ...]  # extra pool entries at luck >= spawn.high_luck_at
    guaranteed_in: tuple[str, ...]  # room ids that always contain it on first entry
    effects: tuple[Effect, ...]  # behavior tags dispatched by the functions below
    implemented: bool  # False = inert record (meta.blocked_on says what's missing)
    confidence: str = "wiki"  # data provenance: datamined > wiki > inferred > placeholder
    # Item id that must already be held (count > 0) for THIS item to be
    # grantable by any path (_is_available) -- same naming/shape as the
    # ignition targets' requires_item (ignition_requires_met), applied here to
    # a special item's own record instead of an ignition target. None = no
    # gate. Data-driven: nothing that reads this checks a room id.
    requires_item: str | None = None

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
    ignition: dict = field(default_factory=dict)   # "ignition" section from special_items.json
    machines: dict = field(default_factory=dict)   # "machines" section from special_items.json
    mail_packages: dict = field(default_factory=dict)  # "mail_packages" section: slot1/slot2/slot3
    freight_packages: dict = field(default_factory=dict)  # "freight_packages" section (ix91)
    battery_pack: dict = field(default_factory=dict)  # "battery_pack" section: room, rarity options
    # "contraption_lockout" section's "table": contraption id -> frozenset of its
    # own fabrication-input ids blocked while it is held at day start (carried
    # overnight via Coat Check/Moon Pendant). See configure() below for how this
    # is applied and data/special_items.json's own "meta"."note" for the wiki
    # sourcing/methodology.
    contraption_lockout: dict[str, frozenset[str]] = field(default_factory=dict)
    # "planetarium_planets" section's "planets" list: five {id, name, payload}
    # records (Mora's carries forced_last: true), the wiki's own gallery
    # order. See engine.special_items.use_telescope_in_planetarium and
    # effects/rooms/planetarium.py for how this table is read generically.
    planetarium_planets: tuple[dict, ...] = ()
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
            receive=bool(r.get("receive", True)),
            unique=bool(r.get("unique", True)),
            persistence=r.get("persistence", "day"),
            spawn_rooms=tuple(r.get("spawn_rooms", [])),
            spawn_rooms_high_luck=tuple(r.get("spawn_rooms_high_luck", [])),
            guaranteed_in=tuple(r.get("guaranteed_in", [])),
            effects=effects,
            implemented=bool(r.get("implemented", False)),
            confidence=r.get("meta", {}).get("confidence", "wiki"),
            requires_item=r.get("requires_item"),
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
        ignition=raw.get("ignition", {}),
        machines=raw.get("machines", {}),
        mail_packages=raw.get("mail_packages", {}),
        freight_packages=raw.get("freight_packages", {}),
        battery_pack=raw.get("battery_pack", {}),
        contraption_lockout={
            k: frozenset(v)
            for k, v in raw.get("contraption_lockout", {}).get("table", {}).items()
        },
        planetarium_planets=tuple(raw.get("planetarium_planets", {}).get("planets", [])),
        spawn_pool_by_room={k: tuple(v) for k, v in pool.items()},
        spawn_pool_high_luck={k: tuple(v) for k, v in pool_hl.items()},
        guaranteed_by_room={k: tuple(v) for k, v in guaranteed.items()},
    )


@dataclass(slots=True)
class SpecialItemsState:
    """Mutable per-day special-item bookkeeping, reset with GameState."""

    enabled: bool = True  # GameConfig.special_items, copied at reset (gates spawning)
    lockpick_attempts: int = 0  # picks tried today (Lock Pick Kit / Amplifier)
    lockpick_successes: int = 0  # successful picks today, indexes the per-day rate table
    lockpick_fails: int = 0  # pity counter: +1/fail, -1/success (meaningful only when
    # the held tool's lockpick effect has pity > 0; see _attempt_lockpick)
    coin_interest: int = 0  # coins collected since the last Coin Purse interest payout
    water: int = 0  # Watering Can charges left (set to capacity on pickup)
    stopwatch_left: int = 0  # free cost events remaining (0 = stopwatch inactive)
    stopwatch_used: bool = False  # a Stopwatch already ran today (unobtainable again)
    shoes_anchor_code: int = 0  # Running Shoes reference position, sentinel-encoded:
    # 0 = no anchor recorded yet today; otherwise the anchor cell is (value - 1)
    # (0 must be free for "unset" since cell 0 is itself a legitimate anchor;
    # see effects/items/running_shoes.py)
    dug: dict[int, int] = field(default_factory=dict)  # cell -> dig spots already dug
    # Cloister of Veia: cell -> extra dig spots (+8, additive on top of the
    # room's own items.dig_spots) for a room with a fireplace drafted from its
    # own doorway (effects/rooms/cloister.py). Room is frozen, so a per-
    # instance bonus needs this per-cell store rather than a Room field.
    veia_dig_bonus: dict[int, int] = field(default_factory=dict)
    treasure_cell: int = -1  # Treasure Map X cell; -1 = no map read today
    treasure_dug: bool = False  # the map's one-per-day treasure dig happened
    silver_key_draft: bool = False  # next draw biased toward cross/t layouts
    shield_used: bool = False  # Knight's Shield daily red-room negation spent
    # ids gone for the day (Lost & Found steals, consumed-for-good keys):
    # excluded from spawn pools and (PR2) trade offers
    removed: list[str] = field(default_factory=list)
    spawned_today: list[str] = field(default_factory=list)  # unique ids already spawned
    # Battery Pack: pickups today whose Dynamic Rarity flip/toggle has not
    # resolved yet (drained by battery_pack.resolve_pending, deferred until
    # rng is in scope -- see _on_pickup and effects/items/battery_pack.py).
    battery_pack_pending: int = 0
    # Battery Pack: index into battery_pack.options of the last rarity chosen
    # today; -1 = none chosen yet this day (sentinel), so the next resolution
    # knows whether to roll fresh or toggle to the other option.
    battery_pack_last_rarity: int = -1
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
    # Mechanarium: cell -> its diagonal-compartment count (0-4), fixed once at
    # draft time by seed_mechanarium_compartments. Per-placement, not a static
    # per-room count, because it depends on how many Mechanical rooms are
    # standing the moment this particular Mechanarium is placed.
    mechanarium_compartments: dict[int, int] = field(default_factory=dict)
    # Per-day use count of each bearer room's ``draft_luck`` ladder effect
    # (Veranda's "first one in a day gives +12, all later ones give +6"),
    # keyed by the bearer's own room id -- see engine/items.py::draft_luck_bonus.
    # Reset with GameState like everything else in this dataclass, so it is a
    # per-DAY count, matching "in a day".
    draft_luck_uses: dict[str, int] = field(default_factory=dict)
    garage_car_opened: bool = False  # Car Keys garage car trunk used today (once per day)
    # Vault Key ids whose deposit box was opened today (at most once per key per day).
    vault_boxes_opened: list[str] = field(default_factory=list)
    # ids lit this day (ignition mechanic): room ids for on-grid targets (chapel,
    # tomb, trading_post), plus area-graph node ids for off-grid ones (mine_south).
    lit_targets: list[str] = field(default_factory=list)
    machines_used: list[str] = field(default_factory=list)  # machine room ids used today (lever install)
    # Keeper of Tithes: coins actually banked (incremented each time the Chapel's -1
    # coin entry penalty fires and the player had at least 1 coin to lose).  Paid out
    # in full when the Chapel altar is lit.  Resets across days via carryover() — the
    # running total lives in GameConfig.chapel_tithes and is re-injected at configure().
    chapel_tithes: int = 0
    # Inner Sanctum: realm ids whose Sigil Chamber door was opened TODAY (a
    # Sanctum Key spent via open_sigil_door).  Checked alongside
    # cfg.sigil_doors_open (permanently opened on an earlier day), the same
    # "today's list + cfg's permanent set" shape as vault_boxes_opened /
    # used_vault_keys.
    sigil_doors_opened: list[str] = field(default_factory=list)
    # Extra 'trunk' containers added to the Entrance Hall today. Named for the
    # room, not for either source that bumps it: the entrance_hall_trunk
    # experiment effect (experiments.py::apply_effect) and The Twins
    # constellation (constellations.py::apply_effect) both spawn here, under
    # the one cap the wiki gives them ("identical to triggering this effect
    # twice"). Never assigned directly -- add_entrance_hall_trunks below is the
    # only writer, so the cap cannot be bypassed by a third source. Per-day
    # only: neither the trunks nor the count carry over (owner ruling: the cap
    # is a daily maximum), which falls out for free from SpecialItemsState
    # being rebuilt fresh with GameState.
    entrance_hall_trunks: int = 0
    # Dig spots the spread_dig_spots experiment effect has added to the
    # Conference Room today (experiments.py::apply_effect), capped at 50.
    # Tracked separately from veia_dig_bonus -- which this counter also feeds
    # -- so the 50-spot cap is exact even if something else ever adds to
    # veia_dig_bonus at the same cell. Per-day only, same reset shape as
    # entrance_hall_trunks.
    conference_room_dig_spots: int = 0
    # Crown of the Blueprints: room ids filtered from every draw for the rest
    # of today (owner ruling 2026-08-12 -- no exemption for colour-selective
    # drafts, the Silver Key, the Prism Key, or ducts). A filter, not a deck
    # mutation: draft.py::room_draftable excludes these ids at draw time, so
    # deck sizes (and therefore rarity legality) never change.
    crown_blocked_rooms: list[str] = field(default_factory=list)
    # Crown of the Blueprints: its once-per-hand filter option already spent
    # on the CURRENT hand. Reset to False every time a hand is dealt or
    # redealt (engine/draft.py::_fill_options) -- unlimited hands per day.
    crown_block_used: bool = False
    # Raw item_ladder counts stashed by engine/items.py::_apply_count_transform's
    # "deferred_ladder" kind, room id -> raw count, for rooms whose transform is
    # applied later by a room-specific item hook instead of inline (currently only
    # Lost & Found -- lost_and_found_on_enter below). Keyed by room id so the
    # dispatch in _apply_count_transform stays generic (no room id literal there).
    # Popped (consumed) by the hook that reads it; reset with GameState like
    # everything else in this dataclass, so a stale entry can never survive
    # into a later day.
    count_transform_raw: dict[str, int] = field(default_factory=dict)
    # Telescope-in-Planetarium: whether today's one-upgrade-per-day cap has
    # already been spent (wiki: "only one upgrade can be done per day").
    # Day-scoped only, same reset shape as garage_car_opened -- the PERMANENT
    # record of which planets are unlocked lives on GameState.planetarium_planets
    # (SAVE-scoped, carried by DayChain), not here.
    planetarium_telescope_used: bool = False

    def add_entrance_hall_trunks(self, cap: int | None, count: int) -> int:
        """Add up to ``count`` trunks to the Entrance Hall, and return how many landed.

        The one place the shared trunk cap is compared. Two unrelated sources
        spawn here -- the entrance_hall_trunk experiment effect and The Twins
        constellation, "identical to triggering this effect twice" -- and both
        pass the same ``cap``, published on the experiment's own record and
        read back through experiments.py::entrance_hall_trunk_cap. A method
        rather than a free function so the field and its invariant stay
        together and neither caller has to import the other's module.

        Fills partially rather than refusing: The Twins' pair added with one
        slot left puts one trunk in the hall, not zero. ``cap`` of None means
        uncapped. Going silent at the cap is the wiki's own wording for the
        experiment ("will no longer have any effect"), so the caller is not
        told to stop -- only this effect does.
        """
        room = count if cap is None else max(0, cap - self.entrance_hall_trunks)
        added = min(count, room)
        self.entrance_hall_trunks += added
        return added


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
    # Data-driven item-holds-item gate (e.g. upgrade_disk_archives requires
    # file_cabinet_key): blocks every grant path uniformly (guaranteed_in,
    # dig, spawn, lost_and_found), never just the room it happens to sit in.
    if item is not None and item.requires_item is not None and not has(state, item.requires_item):
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

    # Watering Can: fill charges to capacity on pickup
    watering_can.on_pickup(state, item)

    # Battery Pack: record a pending Dynamic Rarity flip/toggle, resolved
    # lazily at the next deal (resolve_battery_pack below) where rng is in scope.
    battery_pack.on_pickup(state, item)

    # stopwatch: activate (grant already blocked a re-grant, so this always fires first time)
    e = item.effect("stopwatch")
    if e is not None:
        if not state.special.stopwatch_used:
            state.special.stopwatch_left = e.param("free_costs", 10)
            state.special.stopwatch_used = True

    # Lunch Box: consume immediately if already at/above its rank threshold
    lunch_box.check_rank_threshold(state, registry, item)

    # treasure_map: the marked cell is resolved lazily in on_arrive/dig_all
    # when game.rng is available. No action needed at pickup time.

    # allowance (Allowance Token): +2 permanent allowance, credited once at
    # pickup, then the token itself is cleared from the inventory slot -- it
    # converts straight to allowance rather than sitting as a held item.
    # Fixed one-time-source tokens (every id besides the shared "allowance_token"
    # -- one per Mora Jai box / the Cloister's own token) are removed with
    # consumed=True so fixed_allowance_tokens_collected_today can see they were
    # taken today, feeding the permanent collected_allowance_tokens gate that
    # stops that specific spot from ever granting again. The shared
    # "allowance_token" id (Trading Post trades, Jack Hammer digging, and the
    # Vault 149/233 boxes -- whose own key-tracked one-shot open already keeps
    # them one-time) removes with consumed=False since it never needs that gate
    # and must stay repeatable.
    e = item.effect("allowance")
    if e is not None:
        state.allowance += e.param("amount", 2)
        remove(state, item.id, consumed=(item.id != "allowance_token"))


def resolve_battery_pack(game) -> None:
    """Drains any pending Battery Pack Dynamic Rarity triggers recorded at
    pickup, the same lazy-resolution shape as treasure_map.resolve_cell but
    fired from Game._deal_and_cache (just before the deal) rather than
    on_arrive -- see effects/items/battery_pack.py::resolve_pending."""
    battery_pack.resolve_pending(game)


# ------------------------------------------------------------------ config gates

def configure(state, cfg, registry=None) -> None:
    """Populate config-gated item exclusions; idempotent (safe to call every on_enter).

    ``registry`` is only consulted by the Axe's cap gate below (it needs the
    item's own data-driven max_active); every other gate here reads cfg
    alone. Optional (default None, skipping just that one gate) because this
    function's four effects/rooms/mail_room.py call sites are pure no-ops
    after the first real call from Game.reset() -- the ``configured`` guard
    above returns before registry would ever be read on those calls -- so
    they need not be forced to thread it through just to satisfy a branch
    they can never reach.
    """
    if state.special.configured:
        return
    state.special.configured = True
    gated = []
    lunch_box.gate(cfg, gated)
    cursed_effigy.gate(cfg, gated)
    # Royal Scepter: gate out of spawn pool unless the carry-over flag is set.
    # (Finding the scepter in-run requires the unmodeled Treasure Trove / Key of
    # Aries puzzle; with royal_scepter_found it is granted at reset time instead.)
    royal_scepter.gate(cfg, gated)
    # Vault keys permanently used (across all days): never spawn again.
    for vk_id in getattr(cfg, "used_vault_keys", frozenset()):
        if vk_id not in gated:
            gated.append(vk_id)
    # Fixed-location Upgrade Disks already collected on an earlier day: gate them
    # so the room's guaranteed_in grant cannot re-mint one on a later day. Needed
    # because state.special.removed only survives the day, while these disks are
    # gone from the house for the whole attempt once taken.
    for disk_id in getattr(cfg, "collected_disks", frozenset()):
        if disk_id not in gated:
            gated.append(disk_id)
    # Fixed-source Allowance Token ids already collected on an earlier day (a
    # Mora Jai box or the Cloister's own token): same shape as collected_disks,
    # so a later visit to that same spot cannot mint a second one.
    for token_id in getattr(cfg, "collected_allowance_tokens", frozenset()):
        if token_id not in gated:
            gated.append(token_id)
    # Sanctum Key sources already spent (ever, across all days): permanently
    # blocked, same shape as collected_disks/collected_allowance_tokens.
    for key_id in getattr(cfg, "collected_sanctum_keys", frozenset()):
        if key_id not in gated:
            gated.append(key_id)
    # Owner ruling (see docs/rooms.md): none of the eight Sanctum Keys
    # spawn anywhere until Room 46 has been reached at least
    # once (cfg.room46_reached, a permanent carry-over flag set the FOLLOWING
    # day -- same convention as gem_gate_active(), which also reads cfg only).
    if not cfg.room46_reached:
        for key_id in SANCTUM_KEY_IDS:
            if key_id not in gated:
                gated.append(key_id)
    # Crown of the Blueprints: reads the same cfg.room46_reached flag, for its
    # own wiki reason ("cannot be obtained the first time the room is reached").
    crown_of_the_blueprints.gate(cfg, gated)
    # The Axe: the Armory stops selling once the permanent, save-scoped cap of
    # simultaneously-axed families (cfg.axed_rooms, capped at the_axe's own
    # data-driven max_active) has been spent. Same gated_out channel as
    # collected_disks/collected_sanctum_keys above.
    if registry is not None:
        axed = getattr(cfg, "axed_rooms", ())
        if len(axed) >= the_axe.max_active(registry) and the_axe.ITEM_ID not in gated:
            gated.append(the_axe.ITEM_ID)
    # Telescope: gated out below 1 start-of-day star (state.stars_at_day_start,
    # not the live-growing state.stars -- see effects/items/telescope.py::gate).
    telescope.gate(state, gated)
    # Contraption carry-over lockout: cfg.starting_items is what a contraption
    # carried overnight (Coat Check / Moon Pendant) arrives through -- it is
    # granted into inventory AFTER this function runs (see Game.reset), so
    # checking it here rather than state.inventory catches a carried
    # contraption before it is even held, and never fires for one assembled
    # fresh today (fabricate() never touches cfg.starting_items). Day-scoped
    # like every other entry in ``gated``: a fresh SpecialItemsState next day
    # drops it unless the contraption carries over again. Table is
    # registry.special.contraption_lockout (data/special_items.json), same
    # ``registry is not None`` guard as the Axe gate above -- both are no-ops
    # on the four mail_room.py/shops.carryover call sites that omit registry,
    # which only ever run after Game.reset()'s own registry-bearing call has
    # already set ``configured`` True (see this function's own docstring).
    if registry is not None:
        for contraption_id in cfg.starting_items:
            for comp_id in registry.special.contraption_lockout.get(contraption_id, ()):
                if comp_id not in gated:
                    gated.append(comp_id)
    state.special.gated_out = gated
    # Ignition targets permanently lit across days: pre-populate lit_targets so
    # can_light() blocks them on day N+1 just as it would mid-day.
    for target_id in getattr(cfg, "lit_targets", frozenset()):
        if target_id not in state.special.lit_targets:
            state.special.lit_targets.append(target_id)
    # Keeper of Tithes: seed the running tithe counter from config so the total
    # accumulates correctly across days.
    state.special.chapel_tithes = getattr(cfg, "chapel_tithes", 0)
    # Mail Room order/delivery cycle: seed from the carried config value so a
    # pending order survives the day boundary.
    state.mail_cycle = getattr(cfg, "mail_cycle", "empty")
    # Freight Shipping (mail_room__ix91) transit countdown: seed from the
    # carried config value alongside mail_cycle.
    state.mail_transit_days = getattr(cfg, "mail_transit_days", 0)
    # Cloister of Joya's permanent Main Course bonus: seed from the carried
    # config value, the same "replace wholesale" shape as allowance/stars
    # (those are seeded directly in Game.reset(); this one is seeded here
    # since configure() is this module's own reset-time entry point).
    state.main_course_bonus = getattr(cfg, "main_course_bonus", 0)


# ------------------------------------------------------------- spawn pipeline

def roll_special_spawn(state, registry, room, rng, draft_bonus: int = 0) -> str | None:
    """Resolve one additional-item proc to a special item, or None to fall
    through to the regular EXTRA_ITEM_TABLE kinds.

    Modeling assumption (inferred): with probability spawn.special_share, a
    luck-proc in a room with a non-empty spawn pool yields a uniformly random
    still-available pool item (high-luck entries join at luck >=
    spawn.high_luck_at); at most one special item spawns per room per day.
    Grants the item itself and returns its id, or returns None.

    ``draft_bonus`` is engine/items.py::draft_luck_bonus's ALREADY-COMPUTED
    result for this room's roll (Veranda / Spare Veranda) -- callers must
    pass the same value used for this room's ``roll_ladder_count`` call, not
    recompute it here, since computing it advances a per-day counter.
    """
    if not state.special.enabled:
        return None
    # At most one special item per room per day
    if state.special.spawn_room_done == room.idx:
        return None
    if not registry.special.by_id:
        return None

    # Build pool: base entries + high-luck entries when effective luck qualifies.
    # Same effective-luck formula as engine/items.py::roll_ladder_count, so a
    # high-luck spawn only becomes eligible exactly when the ladder itself
    # would treat the draft as high luck.
    effective_luck = state.luck + luck_bonus(state, registry) + draft_bonus - state.luck_penalty
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


def on_area_arrival(game, area_id: str) -> None:
    """Arrival hooks for off-grid area nodes reached via Game.travel_to.

    Called on every arrival; ``_is_available``'s uniqueness check makes repeat
    calls within the same day a no-op, the same way re-entering a
    ``guaranteed_in`` room does.

    Two mechanisms, in this order:

    First, ``guaranteed_by_room[area_id]`` is granted generically, exactly as
    ``on_enter`` does for grid rooms. This is the path for an area node that
    also has a rooms.json record and so can carry ``guaranteed_in`` in its
    items' data (Room 46 and its Crown of the Blueprints / Sanctum Key): the
    node is never placed on the grid, so ``on_enter`` never runs for it and
    this is the only site that reads its guaranteed list.

    The other nodes that reach this function -- mine_south, upper_rotating_gear,
    orindian_ruins, reservoir_north, safehouse, underpass -- are off-grid with
    no rooms.json record, so the lookup cannot key on them and the block is a
    no-op on their arrivals. **That is a property of which nodes call this
    function, not of area nodes in general**: ``antechamber``, ``tomb``,
    ``trading_post`` and ``the_foundation`` are each both a room record and an
    area node, and each carries guaranteed items that the grid ``on_enter``
    path already grants. Adding a travel_to call here for any of them would
    start granting those items on arrival too -- check that against the grid
    path before doing it.

    Second, the bespoke grants for those record-less nodes:

    - The Abandoned Mine (South)'s Upgrade Disk, sitting openly on a table
      (docs/areas.md) — obtainable without an ignition tool, unlike the
      candlesticks that separately open the Precipice stairway.
    - Upper Rotating Gear's gem and Treasure Trove blackprint (owner spec,
      see docs/areas.md). Neither is an inventory item, so neither uses
      ``grant``/``_is_available``: the gem is a plain
      ``state.gems`` bump guarded by a per-day flag (once per day, not once
      ever — a fresh ``GameState`` resets the guard every day), and the
      blackprint is a permanent ``state.treasure_trove_blackprint`` flag
      carried across days the same way ``west_gate_unlatched`` is, which
      ``decks.py::eligible_pool`` reads (via the carried ``GameConfig`` field)
      to add the Treasure Trove to the draft pool.
    - Orindian Ruins' Throne Room blueprint, same shape as the Treasure
      Trove blackprint above: not an inventory item, so it uses neither
      ``grant`` nor ``_is_available``. Setting the permanent
      ``state.throne_room_blueprint`` flag is unconditional on every arrival
      (idempotent), and ``decks.py::eligible_pool`` reads it (via the
      carried ``GameConfig`` field) to add the Throne Room to the draft pool.
    - Two of the eight Sanctum Key sources (``reservoir_north``, ``safehouse``)
      sit off-grid with no rooms.json record, same shape as the Abandoned
      Mine's disk above -- configure()'s room46_reached/collected_sanctum_keys
      gating already runs through ``_is_available``, so no extra gate is
      needed here.
    - The Underpass's Mora Jai box (+2 allowance), off-grid with no
      rooms.json record, same shape as the Abandoned Mine's disk above --
      ``configure()``'s ``collected_allowance_tokens`` gating already runs
      through ``_is_available``, so no extra gate is needed here either.

    Calls ``configure()`` itself, the same as ``on_enter()`` does: an off-grid
    area can be the day's very first special-items touch (nothing on the grid
    has to be entered before travelling straight to an area node), and
    ``configure()`` is what seeds ``state.special.gated_out`` from the
    permanent carry-over sets. ``configure()`` is idempotent, so this is a
    no-op on every call after the first for the day.
    """
    configure(game.state, game.cfg)
    for item_id in game.registry.special.guaranteed_by_room.get(area_id, ()):
        if _is_available(game.state, item_id, game.registry):
            grant(game.state, game.registry, item_id, source="guaranteed")
    if area_id == "mine_south":
        state = game.state
        registry = game.registry
        if _is_available(state, "upgrade_disk_mine_south", registry):
            grant(state, registry, "upgrade_disk_mine_south", source="mine_south")
    elif area_id == "upper_rotating_gear":
        state = game.state
        if not state.upper_rotating_gear_gem_granted:
            state.gems += 1
            state.upper_rotating_gear_gem_granted = True
            state.items_found_log.append(("gem", 1))
        state.treasure_trove_blackprint = True
    elif area_id == "orindian_ruins":
        game.state.throne_room_blueprint = True
    elif area_id == "reservoir_north":
        state = game.state
        registry = game.registry
        if _is_available(state, "sanctum_key_reservoir_north", registry):
            grant(state, registry, "sanctum_key_reservoir_north", source="reservoir_north")
    elif area_id == "safehouse":
        state = game.state
        registry = game.registry
        if _is_available(state, "sanctum_key_safehouse", registry):
            grant(state, registry, "sanctum_key_safehouse", source="safehouse")
    elif area_id == "underpass":
        state = game.state
        registry = game.registry
        if _is_available(state, "allowance_token_underpass", registry):
            grant(state, registry, "allowance_token_underpass", source="underpass")


def on_enter(game, room, cell: int) -> None:
    """First-entry hooks: guaranteed spawns, Dining Room main course and Lunch
    Box, Lost & Found, Sleeping Mask, Watering Can. Called from Game._enter
    after roll_room_items runs for ``room``, and after this room's own
    guaranteed items (if any) have already been granted above. Both the Lunch
    Box grant and the Lost & Found steal depend on that ordering rather than
    on a ``room_hook`` at ``Hook.ON_ENTER`` (which fires earlier, before
    roll_room_items and before this function even starts): Lunch Box is in
    the Dining Room's own luck-spawn pool, so granting it any earlier would
    remove it from that pool before the room's own luck roll sees it; the
    Lost & Found's own guaranteed Allowance Token needs to already be in
    inventory so the steal below can draw it like any other held item. Coat
    Check carries no such dependency and is dispatched from its own
    room_hook instead (``effects/rooms/coat_check.py``).
    """
    state = game.state
    registry = game.registry
    configure(state, game.cfg)

    # Grant items guaranteed in this room (filtered by standard availability rules)
    for item_id in registry.special.guaranteed_by_room.get(room.id, ()):
        if _is_available(state, item_id, registry):
            grant(state, registry, item_id, source="guaranteed")

    # Re-grant day-persistence disk from a previously-lit ignition target.
    # Candles/fuse stay lit permanently (room.id in cfg.lit_targets) so the
    # player never re-lights the room — but the disk returns to the chamber
    # until spent (inserted at a terminal, which puts it in collected_disks).
    # Only targets whose disk has persistence="day" qualify; the grant check
    # in _is_available blocks it if it is already in collected_disks (spent).
    #
    # This path is ONLY for disks that are themselves an ignition reward — the
    # Tomb and Trading Post disks sit behind the flame. A disk that merely shares
    # a room with candles does NOT belong here: the Abandoned Mine (South) disk
    # sits openly on a table and is obtainable without ever lighting anything,
    # while its eight candlesticks independently open the stairway to the
    # Precipice (the "candlestick_stairway_lit" flag game.py::_gate_ctx derives
    # from state.special.lit_targets, areas.json). mine_south has no rooms.json
    # record and is off-grid, so this on-grid re-grant path never runs for it
    # anyway; its disk is granted instead by on_area_arrival, called from
    # Game.travel_to on arrival at the mine_south area node. Coupling the disk
    # to the candles would make it unreachable without an ignition tool, which
    # is wrong.
    targets = registry.special.ignition.get("targets", {})
    if room.id in targets and room.id in state.special.lit_targets:
        for reward in targets[room.id].get("grants", []):
            if reward.get("kind") == "item":
                item_id = reward["id"]
                item = registry.special.by_id.get(item_id)
                if (item is not None and item.persistence == "day"
                        and item_id.startswith("upgrade_disk_")):
                    if _is_available(state, item_id, registry):
                        grant(state, registry, item_id, source="ignition_reentry")

    # Dining Room main course (rank-8 gated; also checked on every arrival so
    # a return visit after reaching Rank 8 serves it).
    _maybe_serve_main_course(game)

    # Lunch Box: guaranteed in the Dining Room (and upgrade variants) when unlocked
    lunch_box.grant_guaranteed(game, room)

    # Lost & Found: steal one held item and grant draws from the pool (count
    # per its own ladder-based rule -- see lost_and_found_on_enter). Fires
    # after the guaranteed-items loop above, so this room's own guaranteed
    # Allowance Token is already in inventory and can itself be the steal target.
    if room.id == "lost_and_found":
        lost_and_found_on_enter(game)

    # Sleeping Mask: grant steps when entering a bedroom (including Bunk Room x2)
    sleeping_mask.apply_on_enter(state, registry, room)

    # Watering Can: convert one water charge to one gem on entering a green room
    watering_can.apply_on_enter(state, registry, room)


def _maybe_serve_main_course(game) -> None:
    """Serve the day's Dining Room Main Course if it is due.

    The course is only served once the player has REACHED Rank 8 (some
    entered cell at rank >= 8): entering the Dining Room earlier means
    returning to eat it later, while a Dining Room drafted at rank 8/9 serves
    immediately on entry. Once per day; the day's dish is cycle[day % 5];
    the boost-room check happens inside eat_food.
    """
    from .grid import rank_of
    state = game.state
    registry = game.registry
    if not state.special.enabled or state.special.dining_room_served:
        return
    if state.area is not None:
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
        eat_food(game, cycle[state.day % len(cycle)])


def on_arrive(game, cell: int) -> None:
    """Every-arrival hooks (including re-entry): auto-dig, Treasure Map,
    Lunch Box rank check, Dining Room main course (rank-8 gated return
    visits). Called from Game.move after entering. Task C.
    """
    lunch_box.check_rank_threshold(game.state, game.registry)
    _maybe_serve_main_course(game)

    # Treasure Map: resolve the marked cell lazily on first arrival after pickup
    treasure_map.resolve_cell(game)

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

    secret_garden_key.consume_on_place(state, room.id)


def lost_and_found_on_enter(game) -> None:
    """Steal one uniformly random held special item (nothing if none held),
    then grant items drawn from the data pool per the room's own published
    count rule (data/items.json count_transforms.rooms.lost_and_found,
    "deferred_ladder" -- owner ruling: replaces the room's prior fixed
    gives=2, luck-independent draw).

    Wiki (Lost & Found's own DataMinedBox): "If any Guaranteed Item spawns,
    one additional item appears, and this room does not check Luck.
    Otherwise, Luck is used. One item is added to the result, and the item
    count then clamped to be in 2-4."

    Two branches, evaluated in that order:

    1. Guaranteed-item carve-out: this room's own guaranteed_by_room grant
       (allowance_token_lost_and_found) already ran earlier in on_enter,
       before this hook fires -- whether it actually spawned this entry is
       read from state.special.spawned_today, not re-derived. Pool draws =
       lf["gives"] + spec["guaranteed_add"], no luck consulted. JUDGMENT
       CALL: "Guaranteed Item" is mapped onto this sim's existing
       guaranteed_by_room/guaranteed_in concept (the Mora Jai Box Allowance
       Token) -- see items.json's count_transforms.meta for the wiki's
       fuller, unmodeled per-item guaranteed-selection mechanic (Vault Key
       370 / Key 8 / Upgrade Disk) this does NOT attempt to reproduce.

    2. Otherwise: pool draws = clamp(raw + spec["add"], spec["min"],
       spec["max"]), where ``raw`` is the SAME item_ladder roll
       roll_room_items already performed for this room this entry, stashed
       by engine/items.py's _apply_count_transform (a second independent
       roll here would double-count both the rng draw and
       state.luck_penalty). Missing -- e.g. this function called directly,
       as several tests do, bypassing roll_room_items -- defaults raw to 0.

    The steal fires first either way, unaffected by which branch the grant
    takes.
    """
    state = game.state
    registry = game.registry
    rng = game.rng

    # Steal one random held item. The Keycard is stealable like anything else,
    # but lives on state.has_keycard (engine/locks.py), not the inventory.
    held = [iid for iid, cnt in state.inventory.items()
            if cnt > 0 and iid not in PIPELINE_EXCLUDED]
    if keycard.held(state):
        held.append(keycard.ITEM_ID)
    if held:
        stolen_id = rng.choice("lost_and_found", held)
        if stolen_id == keycard.ITEM_ID:
            keycard.release(state)
        else:
            remove(state, stolen_id, consumed=True)

    # Grant draws from the pool: item count per the ladder-based transform above.
    lf = registry.special.lost_and_found
    base_gives = lf.get("gives", 2)
    pool = lf.get("pool", [])
    spec = registry.item_rules["count_transforms"]["rooms"].get("lost_and_found", {})

    guaranteed_ids = registry.special.guaranteed_by_room.get("lost_and_found", ())
    guaranteed_spawned = any(gid in state.special.spawned_today for gid in guaranteed_ids)

    if guaranteed_spawned:
        gives = base_gives + spec.get("guaranteed_add", 1)
    else:
        raw = state.special.count_transform_raw.pop("lost_and_found", 0)
        gives = min(max(raw + spec.get("add", 1), spec.get("min", 2)), spec.get("max", 4))

    from . import items as items_mod  # deferred: items.py imports this module

    for _ in range(gives):
        # "die" is always available; items filtered by standard availability
        available = [e for e in pool
                     if e == "die" or _is_available(state, e, registry)]
        if not available:
            continue
        chosen = rng.choice("lost_and_found", available)
        if chosen == "die":
            items_mod.grant_item(game, "die", 1)
        else:
            grant(state, registry, chosen, source="lost_and_found")


def coat_check_on_enter(game) -> None:
    """Auto-store the most valuable held item in the Coat Check for overnight.

    Picks the highest-tier item from inventory (untradeable/no tier counts as 0;
    ties broken alphabetically by id for determinism).  The stored item is NOT
    removed from today's inventory — the player keeps it for the rest of the day.
    It is returned by end_of_day_carry() as a starting_item for tomorrow.  A
    no-op if an item is already stored this day (one Coat Check use per day).

    Simplification: the real game lets the player choose which item to store
    and retrieve it on any later day.  We auto-store the best item and
    auto-return it exactly the next day.  (Documented in
    docs/special-items-behaviour.md.)
    """
    state = game.state
    registry = game.registry
    if state.special.coat_check_item is not None:
        return

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

    Also fires the Morning Star's end-of-day star grant (state.stars, a
    separate permanent counter, not an item carry channel -- see
    effects/items/morning_star.py) at this same day-end call site, so an item
    stolen or traded away earlier in the day is correctly not held here.

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
    moon_pendant.carry_over(state, rng, result)

    # 4. Morning Star: +1 permanent star iff still held right now (not an
    # item carry channel -- mutates state.stars directly).
    morning_star.grant_star_if_held(state)

    return sorted(result)


# ------------------------------------------------------- movement & door costs

def move_step_cost(game, from_cell: int, direction: int, to_room) -> int:
    """Step cost of one move: 1, or 0 via Hall Pass (hallway to hallway), an
    active Stopwatch, or Running Shoes cadence.

    Priority: MOVE_STEP_COST_PRIORITY. Hall Pass first, so its free hallway
    moves never consume a Stopwatch charge or advance the Running Shoes
    cadence counter.
    """
    state = game.state
    registry = game.registry
    return fire_item_chain(
        state, registry, ItemHook.MOVE_STEP_COST, MOVE_STEP_COST_PRIORITY,
        from_cell, direction, to_room, default=1)


def can_open_locked_free(game) -> bool:
    """Deterministic free open of a locked door (Master Key), used by
    passability/nav so paths don't budget keys the player won't spend."""
    return item_capability_any(game.state, game.registry, ItemCapability.MASTER_KEY)


def can_attempt_lockpick(state, registry) -> bool:
    """A Lock Pick Kit or Pick Sound Amplifier is held (either qualifies)."""
    return has(state, "lock_pick_kit") or has(state, "pick_sound_amplifier")


def _attempt_lockpick(game) -> bool:
    """One Lock Pick Kit / Pick Sound Amplifier attempt: probabilistic with
    the datamined rates and pity rule, prefering the Amplifier when both are
    held (better rates, no pity drain). Tracked by GLOBAL per-day counters
    (``state.special.lockpick_attempts``/``lockpick_successes``/
    ``lockpick_fails``), not per doorway -- the wiki documents retrying the
    SAME door as pointless once it has failed once ("attempting to use the
    Lock Pick Kit on that door again still does not open the door"), which
    this sim does not model; a retry here draws a fresh roll off the same
    global counters instead of an automatic re-fail. False, with no counters
    touched, when neither tool is held. Shared by :func:`open_locked_free`
    (movement, auto-cascade) and Game.lockpick_at_lock (LOCK_PENDING, the
    player's own explicit choice).

    The rate ladder (``rates``) is indexed by SUCCESSFUL picks so far today,
    not attempts -- consecutive failures hold the player at the current rung
    instead of pushing them down it. The pity counter is two-sided: a fail
    adds 1, a success subtracts 1. At >= ``pity`` the attempt auto-succeeds
    and the counter resets to -1; at <= ``pity_fail`` it auto-fails and the
    counter resets to 1 (the wiki gates this second case on lockpicking
    skill <= 20; no skill stat exists here, so it always applies). Both
    checks are skipped when ``pity`` is 0 (the Amplifier has no pity drain).
    """
    state = game.state
    registry = game.registry
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
    pity_fail = lockpick_effect.param("pity_fail", -2)

    state.special.lockpick_attempts += 1
    counter = state.special.lockpick_fails

    if pity > 0 and counter >= pity:
        state.special.lockpick_fails = -1
        state.special.lockpick_successes += 1
        return True

    if pity > 0 and counter <= pity_fail:
        state.special.lockpick_fails = 1
        return False

    rate_idx = min(state.special.lockpick_successes, len(rates) - 1)
    if game.rng.chance("lockpick", rates[rate_idx] / denominator):
        state.special.lockpick_fails -= 1
        state.special.lockpick_successes += 1
        return True
    else:
        state.special.lockpick_fails += 1
        return False


def open_locked_free(game) -> bool:
    """Try to open a locked door without spending a key: Master Key,
    active Stopwatch (needs a key in hand, per the wiki), else a Lock Pick
    Kit / Pick Sound Amplifier attempt (:func:`_attempt_lockpick`). Called
    once per locked-door opening while walking (Game._unlock_for_passage,
    ``for_draft=False``) -- the auto-cascade movement path across an
    already-open-or-drafted segment. Drafting through a fresh DOOR_LOCKED
    segment instead parks in Phase.LOCK_PENDING (Game.open_door) and offers
    Master Key / use-a-key-with-Stopwatch-refund / lockpick / a special key
    as the player's own explicit choice -- see Game.can_use_key_at_lock,
    Game.can_lockpick_at_lock, Game.can_use_special_key_at_lock."""
    state = game.state

    # Master Key: always free, deterministic
    if can_open_locked_free(game):
        return True

    # Stopwatch: free if active and a key is in hand (key is kept, per wiki)
    if state.special.stopwatch_left > 0 and state.keys >= 1:
        state.special.stopwatch_left -= 1
        return True

    return _attempt_lockpick(game)


# ------------------------------------------------------------- draft-side hooks

def gem_cost_modifier(game, room, cost: int) -> int:
    """Emerald Bracelet waiver, Hall Pass hallway-from-hallway drafts.

    Priority: GEM_COST_PRIORITY. Only one waiver applies -- no
    double-decrement. The Stopwatch's gem waiver happens at PAY time
    (stopwatch_waives_gems), never here: this runs on every affordability
    query and must stay pure (no charge spent just from being asked).
    """
    if cost <= 0:
        # Nothing to waive.
        return cost
    state = game.state
    registry = game.registry
    return fire_item_chain(
        state, registry, ItemHook.GEM_COST, GEM_COST_PRIORITY, room, cost, default=cost)


def stopwatch_waives_gems(game, cost: int) -> bool:
    """Waive a gem payment via an active Stopwatch (gems must be in hand, per
    the wiki). Called once per actual payment (Game._pay), spending a charge.

    Priority: GEM_PAYMENT_WAIVER_PRIORITY.
    """
    if cost <= 0:
        # Nothing to waive: never burn a Stopwatch charge on a free payment.
        return False
    state = game.state
    registry = game.registry
    return fire_item_chain(
        state, registry, ItemHook.GEM_PAYMENT_WAIVER, GEM_PAYMENT_WAIVER_PRIORITY, cost,
        default=False)


def inventory_value(state, registry) -> float:
    """Reward-shaping worth of the held special items.

    Each item counts its Trading Post tier's value from tuning.json
    special_item_values (untradeable items use the flat value). Purely a
    shaping/reporting number — no game rule reads it. Keeping it here (not in
    rewards.py) keeps the tier lookup beside the item registry it indexes.
    """
    if not state.inventory:
        return 0.0
    values = registry.tuning.get("special_item_values", {})
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


def fixed_disks_spent_today(state, registry) -> set[str]:
    """Upgrade Disk ids spent today (inserted at a terminal), for the collected_disks carryover.

    Qualifies any ``upgrade_disk_*`` item whose ``persistence`` is ``"day"``:
    these disks drop overnight when unspent and return to their source on
    re-entry/re-open, so only consuming one (``remove(..., consumed=True)``,
    which appends to ``state.special.removed``) makes the removal permanent.

    ``persistence: "day"`` covers every Upgrade Disk except one:
    - the seven in-grid guaranteed_in room disks (office, morning_room, etc.)
    - the four bespoke-source disks: garage, vault_304, tomb, trading_post
    - commissary (restocked daily, re-charging 15 gold each time) and
      lost_and_found (stays in the draw pool while unspent)

    Excluded by design (``persistence: "permanent"``):
    - ``upgrade_disk_trade`` — the repeatable tier-5 trade outcome; must stay
      repeatable even after an earlier instance was spent. It is now the only
      exception, so the regression guard on it carries all the weight.
    """
    respawning = {
        item.id
        for item in registry.special.items
        if item.id.startswith("upgrade_disk_") and item.persistence == "day"
    }
    return respawning & set(state.special.removed)


def fixed_allowance_tokens_collected_today(state, registry) -> set[str]:
    """Fixed-source Allowance Token ids collected today, for the
    collected_allowance_tokens carryover.

    Mirrors fixed_disks_spent_today: each one-time source (a Mora Jai box or
    the Cloister's own token) has its own item id and is consumed
    (remove(..., consumed=True)) the instant its "allowance" effect fires in
    _on_pickup, so state.special.removed already records it here. The shared
    "allowance_token" id -- the Trading Post trades, Jack Hammer digging, and
    the Vault 149/233 boxes (whose own key-tracked one-shot open already keeps
    them one-time) -- is excluded by name so it never gets permanently gated.
    """
    fixed = {
        item.id
        for item in registry.special.items
        if item.id != "allowance_token" and item.effect("allowance") is not None
    }
    return fixed & set(state.special.removed)


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

    Priority: COINS_GRANTED_PRIORITY. Lucky Purse's flat doubling supersedes
    Coin Purse: its interest accumulator is not touched while Lucky Purse is
    held.
    """
    return fire_item_chain(
        state, registry, ItemHook.COINS_GRANTED, COINS_GRANTED_PRIORITY, amount, default=0)


def _resolve_food_base(state, registry, food_id: str) -> int:
    """Resolve the base step count for one serving of ``food_id``.

    The dish's own value from :func:`_dish_base_steps`, plus whatever today's
    constellation activations add to THIS dish -- Farmer's Apple is the one
    that does, once per activation and stacking. The bonus lands on the base,
    so it sits inside everything :func:`food_steps` then multiplies; see that
    record in data/constellations.json for the published worked example
    pinning the order.
    """
    return (_dish_base_steps(state, registry, food_id)
            + constellations.food_step_bonus(registry.constellations, state, food_id))


def _dish_base_steps(state, registry, food_id: str) -> int:
    """The step count one serving of ``food_id`` is worth by its own record.

    Looks up the dish record in items.json food.dishes:
    - ``steps``: flat step value (banana, club_sandwich, main courses).
    - ``steps_per_category``: steps × count of grid rooms of that category
      (chef_salad/tomato_soup; count taken at eat time, as the wiki states).
    - ``boost_room`` + ``boosted_steps``: boosted_steps when that room is
      anywhere on the estate (any cell in state.grid), else base steps
      (main courses: salmon, steak, stew_pie, quail, pizza) -- PLUS
      ``state.main_course_bonus`` (Cloister of Joya, effects/rooms/cloister.py),
      the one thing that raises a main course's own step value; the Lunch Box
      calls ``food_steps`` directly rather than through here, so it never sees
      this bonus.
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
                and registry.rooms[idx].is_category(cat)
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
        base = dish["boosted_steps"] if on_estate else dish["steps"]
        return base + state.main_course_bonus

    return dish.get("steps", default_steps)


def eat_food(game, food_id: str = "banana", count: int = 1) -> None:
    """Eat ``count`` food items of kind ``food_id``, granting steps.

    Per-dish resolution via ``_resolve_food_base``: flat steps (banana,
    club_sandwich), category-count steps (chef_salad/tomato_soup), or
    boost-room-conditional steps (main courses). Unknown dishes fall back
    to food.default_steps (3). Salt Shaker / Silver Spoon apply per item
    via :func:`food_steps`. ``inject_rooms`` dishes are NOT handled here —
    callers must check the dish record and call
    ``game.inject_rooms`` after eat_food for those dishes.

    Each apple eaten (``food_id == "apple"``, covering all three visual
    varieties — green, red, and with leaves, which share the one dish id)
    fires the ``apples`` experiment trigger once its steps have already been
    granted, so a same-day ``set_steps`` effect lands last, per the wiki. A
    ``count`` > 1 call fires once per apple, not once per call, matching
    apples being eaten one at a time.
    """
    state = game.state
    registry = game.registry
    base = _resolve_food_base(state, registry, food_id)
    for _ in range(count):
        state.steps += food_steps(state, registry, base)
        state.items_found_log.append(("food", 1))
        if food_id == "apple" and state.experiment.trigger_id == "apples":
            experiments.trigger_success(game)


def food_steps(state, registry, base: int) -> int:
    """Steps granted by one food item: base, +1 with the Salt Shaker, then
    doubled by the Silver Spoon (in that order, per the wiki).

    FOOD_STEPS_PIPELINE: the one genuine ordered fold among this module's
    item chains (fold_item_chain) -- every held item in the tuple applies
    its own transform to the running total, in order.
    """
    return fold_item_chain(state, registry, ItemHook.FOOD_STEP_BONUS, FOOD_STEPS_PIPELINE, base)


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
    return game.cfg.compass or item_capability_any(
        game.state, game.registry, ItemCapability.COMPASS_BIAS)


def ornate_compass_active(game) -> bool:
    """Rotate-at-will on every draft: config flag or held Ornate Compass."""
    return game.cfg.ornate_compass or item_capability_any(
        game.state, game.registry, ItemCapability.ORNATE_COMPASS)


def compass_active_from_state(state, registry, cfg) -> bool:
    """Compass-active check from state/registry/cfg (no game object).

    Used by draft.py where game is not available. Checks the config flag
    and any held item registering ``ItemCapability.COMPASS_BIAS``.
    """
    return cfg.compass or item_capability_any(state, registry, ItemCapability.COMPASS_BIAS)


def dowsing_rod_active_from_state(state, registry) -> bool:
    """True while holding a Dowsing Rod: its per-draft slot-pointing effect
    persists while held (same 'held' semantics as compass_active_from_state).

    Used by draft.py where game is not available.
    """
    return item_capability_any(state, registry, ItemCapability.DOWSING_ROD)


def electromagnet_active_from_state(state, registry) -> bool:
    """Powered Electromagnet drafting-bias check from state/registry (no game object).

    Used by draft.py where game is not available. True while holding a Powered
    Electromagnet: its Mechanical-Rooms-plus-Rotunda draft bias persists while
    held, the same way its component Compass effect does.
    """
    return item_capability_any(state, registry, ItemCapability.ELECTROMAGNET)


def chronograph_active_from_state(state, registry) -> bool:
    """Chronograph drafting-bias check from state/registry (no game object).

    Used by draft.py where game is not available. True while holding a
    Chronograph: its 40% Tomorrow-Rooms priority draw persists while held, the
    same shape as the Powered Electromagnet's bias above. The Chronograph's
    other effect, rewinding a redraw, is separate and unmodelled.
    """
    return item_capability_any(state, registry, ItemCapability.CHRONOGRAPH)


def crown_room_blocked_from_state(state, room_id: str) -> bool:
    """Crown of the Blueprints block check from state (no registry needed).

    Used by draft.py's room_draftable gate. Delegates to
    effects.items.crown_of_the_blueprints, which owns the item id literal,
    so this stays a thin, id-free wrapper -- the same shape as the
    ``*_from_state`` helpers above.
    """
    return crown_of_the_blueprints.is_blocked(state, room_id)


def satisfied_condition_items(state) -> set[str]:
    """Draft-condition gates granted by held items or in-run events.

    key_8 -> room8_key (Key 8 is not consumed on use).
    secret_garden_key -> secret_garden_key (consumed on placement by on_place).
    state.special.extra_conditions: conditions added mid-run (e.g. "breakfast"
    when Bacon & Eggs is eaten from the Kitchen).
    """
    conds: set[str] = set()
    if key_8.held(state):
        conds.add("room8_key")
    if secret_garden_key.held(state):
        conds.add(secret_garden_key.ITEM_ID)
    conds.update(state.special.extra_conditions)
    return conds


def shield_negates(game) -> bool:
    """Knight's Shield: negate the first red-room negative effect today.

    Priority: RED_ROOM_NEGATE_PRIORITY. Auto-applies to the first negative
    red-room effect, with no player choice (docs/special-items-behaviour.md).
    """
    state = game.state
    registry = game.registry
    return fire_item_chain(
        state, registry, ItemHook.RED_ROOM_NEGATE, RED_ROOM_NEGATE_PRIORITY, default=False)


# ------------------------------------------------------------------- digging

def dig_all(game, cell: int) -> None:
    """Dig every remaining spot at ``cell`` with the best held digging tool
    (auto-dig simplification: digging is free, so skipping it is dominated).
    Also handles the Treasure Map dig at the marked cell. Task C.

    Tool priority (best table first): jack_hammer > detector_shovel > shovel.
    Detector shovel table entries carry explicit coin amounts; other tables
    sub-roll coin_pile_split for the 1-4 coin spread.

    A room whose ``items.dig_guaranteed`` names an item (data-driven; only the
    Patio today, for file_cabinet_key) yields that item deterministically from
    its first-ever dig spot at a cell instead of a table roll, still gated on
    a tool being held like every other spot.

    Digs every remaining spot in one loop, so trash_while_digging can fire
    once per junk spot in a single call -- a burst, not a single event per
    player action, on rooms/bonuses that stack many spots at one cell.
    """
    from .effects.rooms import the_kennel  # deferred: effects/rooms imports special_items

    state = game.state
    registry = game.registry

    # Find the best dig tool held (hardcoded priority: better tables win)
    tool_item = None
    table_name = None
    for tool_id in DIG_PRIORITY:
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
        total_spots = room.items.dig_spots + state.special.veia_dig_bonus.get(cell, 0)
        already_dug = state.special.dug.get(cell, 0)
        remaining = total_spots - already_dug

        if remaining > 0 and tool_item is not None:
            # remaining is fixed before the loop starts, so nothing inside it can
            # grow this dig. spread_dig_spots is the only effect that could (it
            # adds to veia_dig_bonus), but this loop's junk branch below can only
            # ever fire trigger_success for the trash_while_digging trigger, and
            # spread_dig_spots can never be today's configured effect alongside
            # that trigger -- the wiki forbids offering the two together
            # (experiments.json's spread_dig_spots.availability.cross_column_exclude,
            # enforced in experiments._effect_offerable), so the junk branch below
            # can never turn around and invoke apply_effect(spread_dig_spots) on
            # this same cell mid-loop.
            table = registry.special.dig_rules["tables"][table_name]
            weights = tuple(entry["weight"] for entry in table)
            coin_split = registry.special.dig_rules["coin_pile_split"]
            turnip_steps_val = registry.special.dig_rules["turnip_steps"]

            # room.items.dig_guaranteed (data-driven, e.g. the Patio's single
            # dig spot -> file_cabinet_key): the room's very first dig spot
            # ever dug at this cell (already_dug == 0, so this only fires once
            # per cell -- re-arriving at an already-fully-dug cell never
            # re-enters this block at all) yields that item deterministically
            # instead of a table roll, if it is still available; otherwise it
            # falls back to the same "unavailable" substitute the ordinary
            # "item" table outcome below uses (1 coin), rather than consuming
            # a table roll for a guarantee that can no longer pay out. Every
            # spot after the first (and every spot at every other room) still
            # rolls the table normally.
            guaranteed_item = room.items.dig_guaranteed if already_dug == 0 else None

            for spot_i in range(remaining):
                if spot_i == 0 and guaranteed_item is not None:
                    if _is_available(state, guaranteed_item, registry):
                        grant(state, registry, guaranteed_item, source="dig_guaranteed")
                    else:
                        bonus = on_coins_granted(state, registry, 1)
                        state.coins += 1 + bonus
                        state.items_found_log.append(("coins", 1))
                    continue

                idx = game.rng.roll_weighted("dig", weights)
                entry = table[idx]
                kind = entry["kind"]

                if kind == "junk":
                    # trash_while_digging: "digging up nothing does not count"
                    # (wiki), so only junk fires here -- nothing falls through
                    # below. Scraps of Paper (Patch 1.6) is folded into the
                    # tables' junk rows rather than a separate row, so this
                    # covers it too.
                    if state.experiment.trigger_id == "trash_while_digging":
                        experiments.trigger_success(game)
                elif kind == "nothing":
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
            the_kennel.unlock_dug_room(game, cell)

    # Treasure Map: one-per-day dig at the marked cell
    if treasure_map.dig_reward(game, cell, tool_item):
        the_kennel.unlock_dug_room(game, cell)


# ----------------------------------------------------------------- containers

def containers_in(registry, room_id: str) -> dict[str, int]:
    """Container kinds and counts for ``room_id``, or {} if none.

    Reads from registry.special.containers["rooms"]; returns e.g. {"trunk": 1}.
    A room whose containers are not a fixed per-room count -- per-placement,
    added per-day, or save-scoped -- has no entry here at all; it instead
    registers a ``provides_containers`` overlay (engine/effects/rooms/), which
    ``_container_kinds_at`` below consults first.
    """
    return dict(registry.special.containers.get("rooms", {}).get(room_id, {}))


def _container_kinds_at(state, registry, cell: int) -> list[tuple[str, int]]:
    """Remaining openable (kind, remaining_count) pairs at ``cell``.

    Subtracts already-opened count from the room's total per kind. A room
    with a registered ``provides_containers`` overlay uses that; every other
    room falls back to the static ``containers_in`` table. Returns an empty
    list when there are no containers or all are opened.
    """
    if state.grid[cell] < 0:
        return []
    room = registry.rooms[state.grid[cell]]
    overlay = container_kinds_for(state, registry, room.id, cell)
    all_kinds = overlay if overlay is not None else containers_in(registry, room.id)
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

    Opens in a deterministic order: trunk, chest, locker_open, locker_locked,
    then any other kinds in stable insertion order (see ``_PRIORITY`` in
    ``_container_kinds_at``).
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

    Supported kinds: coins, keys, gems, dice, item, keycard, food, plus the
    four Mechanarium compartment kinds (mechanarium_lever/_key_chain/
    _upgrade_chain/_sanctum_chain -- see the "Mechanarium diagonal
    compartments" section below). Unknown kinds are silently skipped and
    return "".
    """
    from . import items as items_mod  # deferred import to avoid cycles
    gkind = grant_entry.get("kind", "")
    match gkind:
        case "food":
            food_id = grant_entry.get("id", "banana")
            amount = grant_entry.get("amount", 1)
            eat_food(game, food_id, amount)
            return f"food:{food_id}:{amount}"
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
            # grant_item logs the pickup itself; a second append would
            # double-count dice in items_found_log.
            items_mod.grant_item(game, "die", amount)
            return f"dice:{amount}"
        case keycard.ITEM_ID:
            return keycard.grant(state)
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
        case "mechanarium_lever":
            return _mechanarium_west_lever(game)
        case "mechanarium_key_chain":
            return _mechanarium_key_chain(game)
        case "mechanarium_upgrade_chain":
            return _mechanarium_upgrade_chain(game)
        case "mechanarium_sanctum_chain":
            return _mechanarium_sanctum_chain(game)
        case _:
            return ""


def apply_grant_list(state, registry, game, grants: list[dict]) -> None:
    """Apply every entry of a resolved grants list, in order, via ``_apply_grant``.

    Used by the Mail Room's package delivery (``roll_mail_package``); mirrors
    how ``open_container`` walks a loot entry's own ``grants`` list.
    """
    for g in grants:
        _apply_grant(state, registry, game, g)


def _resolve_mail_chain(state, registry, chain: list[dict]) -> dict:
    """Walk one mail_packages chain, returning its first available entry.

    A non-item entry (dice/gems/food) is always available. Every shipped
    chain ends on one of those, so this always returns before running out.
    """
    for entry in chain:
        if entry.get("kind") != "item" or (
            state.special.enabled and _is_available(state, entry["id"], registry)
        ):
            return entry
    raise AssertionError("mail_packages chain has no available fallback entry")


def roll_mail_package(state, registry, rng) -> list[dict]:
    """Roll one Mail Room package: three slots from data/special_items.json's
    ``mail_packages`` table, resolved against current item availability.

    Slot 1: one of three ordered chains, chosen uniformly, resolved to its
    first available entry. Slot 2: a flat chance of 2 gems, else one of five
    chains chosen uniformly and resolved the same way. Slot 3: a weighted
    table keyed by what slot 2 actually resolved to (its item id, or "gems"
    for the flat-chance/fallback case), falling back to the table's
    "default" entry for outcomes with no entry of their own; its "none"
    result yields no third grant.

    Item availability is state.special.enabled-gated on top of the usual
    ``_is_available`` check, so every item entry is treated as unavailable
    (falling through to its chain's guaranteed non-item fallback) while
    special items are disabled.

    Returns the resolved grants in ``mail_packages``'s grant vocabulary
    (``_apply_grant``'s), one per slot that produced something -- slot 3 can
    be absent.
    """
    tables = registry.special.mail_packages
    grants: list[dict] = []

    slot1_chains = tables["slot1"]["chains"]
    chain1 = rng.choice("mail_room_slot1_chain", slot1_chains)
    grants.append(_resolve_mail_chain(state, registry, chain1))

    slot2 = tables["slot2"]
    shortcut_chance = slot2["gems_shortcut_chance_pct"] / 100.0
    if rng.chance("mail_room_slot2_shortcut", shortcut_chance):
        slot2_grant = slot2["gems_shortcut_grant"]
    else:
        chain2 = rng.choice("mail_room_slot2_chain", slot2["chains"])
        slot2_grant = _resolve_mail_chain(state, registry, chain2)
    grants.append(slot2_grant)

    outcome_key = slot2_grant["id"] if slot2_grant.get("kind") == "item" else slot2_grant.get("kind")
    outcomes = tables["slot3"]["outcomes"]
    table = outcomes.get(outcome_key, outcomes["default"])["table"]
    weights = tuple(row["weight"] for row in table)
    row = table[rng.roll_weighted("mail_room_slot3", weights)]
    match row["result"]:
        case "gems":
            grants.append({"kind": "gems", "amount": row["amount"]})
        case "keys":
            grants.append({"kind": "keys", "amount": row["amount"]})
        case _:
            pass  # "none": no third grant

    return grants


def roll_freight_package(state, registry, rng) -> list[dict]:
    """Roll one Freight Shipping package (mail_room__ix91), using
    ``data/special_items.json``'s ``freight_packages`` table.

    Special items: ``special_item_pool`` filtered by current availability. If
    all of the pool is available, one of ``drop_one_pair`` is dropped at
    random, leaving ``specials_target`` items; otherwise every available item
    is included as-is.

    Resources: one of ``resource_configs`` is rolled, then topped up with
    keys (up to ``keys_top_up_cap``) and then gems until the special items
    plus resources reach ``specials_target`` resource items -- i.e. the
    package always totals ``package_size`` items.

    Returns the resolved grants in ``_apply_grant``'s vocabulary: one entry
    per included special item, plus at most one keys entry and one gems entry.
    """
    tables = registry.special.freight_packages
    grants: list[dict] = []

    pool = tables["special_item_pool"]
    available = [
        item_id for item_id in pool
        if state.special.enabled and _is_available(state, item_id, registry)
    ]
    if len(available) == len(pool):
        dropped = rng.choice("freight_package_drop", list(tables["drop_one_pair"]))
        included = [item_id for item_id in available if item_id != dropped]
    else:
        included = available
    grants.extend({"kind": "item", "id": item_id} for item_id in included)

    configs = tables["resource_configs"]
    weights = tuple(c["weight"] for c in configs)
    chosen = configs[rng.roll_weighted("freight_package_resource_config", weights)]
    keys, gems = chosen["keys"], chosen["gems"]

    shortfall = max(0, tables["specials_target"] - len(included))
    add_keys = min(shortfall, max(0, tables["keys_top_up_cap"] - keys))
    keys += add_keys
    gems += shortfall - add_keys

    if keys:
        grants.append({"kind": "keys", "amount": keys})
    if gems:
        grants.append({"kind": "gems", "amount": gems})

    return grants


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

    # trunks_opened: trunk and the dead 'chest' kind both count (wiki: "chest" is
    # trunk terminology); lockers, the Garage car trunk, and Vault boxes are
    # separate mechanics and never reach this point. Only fires past the payment
    # gates above, so a failed open (insufficient keys) never counts, and a
    # smash-open (which skips payment but still reaches here) does count.
    if kind in ("trunk", "chest") and state.experiment.trigger_id == "trunks_opened":
        experiments.trigger_success(game)

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


# ------------------------------------------------------------ Planetarium planets

def use_telescope_in_planetarium(game, cell: int) -> str:
    """Reveal one not-yet-unlocked Planetarium planet and apply its payload.

    Wiki (Telescope, "another use"): "The Telescope can be used in the
    Planetarium to permanently upgrade the room, unlocking a planet that
    confers permanent benefits to the room. Doing this does not consume the
    Telescope, but only one upgrade can be done per day." Planets appear in
    random order except Mora, always last (the ``forced_last`` planet record,
    data/special_items.json's ``planetarium_planets`` table).

    Applies TODAY's immediate effect: a "food"/"dice"/"item" payload is
    granted right now via ``apply_grant_list`` (the room's own ON_ENTER
    already fired earlier today, before this unlock, so it will not re-grant
    it); a "dig_bonus" payload (Veia) is added directly to
    ``state.special.veia_dig_bonus`` at ``cell`` (the same per-cell overlay
    the Cloister of Veia and spread_dig_spots already share), since that dict
    is only read once at ON_PLACE time and this room was already placed
    today. A "container" payload (Dauja) needs no immediate action:
    effects/rooms/planetarium.py's ``container_kinds`` overlay reads
    ``state.planetarium_planets`` live, so the Trunk is openable the moment
    this returns.

    Returns the revealed planet's id. Caller (Game.use_telescope_planetarium)
    is responsible for the can_use_telescope_planetarium() legality check.
    """
    state, registry, rng = game.state, game.registry, game.rng
    unlocked = set(state.planetarium_planets)
    remaining = [p for p in registry.special.planetarium_planets if p["id"] not in unlocked]
    non_forced = [p for p in remaining if not p.get("forced_last")]
    chosen = rng.choice("planetarium_planet", non_forced) if non_forced else remaining[0]

    state.planetarium_planets = (*state.planetarium_planets, chosen["id"])
    state.special.planetarium_telescope_used = True

    payload = chosen.get("payload", {})
    pkind = payload.get("kind")
    if pkind == "dig_bonus":
        bonus = state.special.veia_dig_bonus
        bonus[cell] = bonus.get(cell, 0) + payload.get("amount", 1)
    elif pkind in ("food", "dice", "item"):
        apply_grant_list(state, registry, game, [payload])
    # "container": no immediate action -- see docstring above.
    return chosen["id"]


# ------------------------------------------------- Mechanarium diagonal compartments

def seed_mechanarium_compartments(game, cell: int) -> None:
    """Fix the Mechanarium at ``cell``'s diagonal-compartment count, once, at draft time.

    Wiki (blueprince.wiki.gg/wiki/Mechanarium): once the four cardinal doors
    are accounted for, further Mechanical rooms open diagonal compartments
    instead, up to four -- min(4, mechanical_rooms - cardinal_doors_spawned).
    ``mechanical_rooms`` counts every Mechanical-category room on the grid
    INCLUDING this Mechanarium itself; ``cardinal_doors_spawned`` is the
    popcount of its own placed door mask.

    Called from the Mechanarium's own ON_PLACE hook
    (effects/rooms/mechanarium.py), which fires after Game._place_room has
    already written both the grid and ``placed_doors[cell]`` for this
    placement, so both counts here reflect their final, frozen values -- the
    same "set in stone the moment it is drafted" timing as the cardinal mask
    itself (draft.py's _mechanarium_orientation).
    """
    state = game.state
    rooms = game.registry.rooms
    mechanical_rooms = sum(
        1 for idx in state.grid if idx >= 0 and rooms[idx].is_category("mechanical"))
    cardinal_doors_spawned = bin(state.placed_doors[cell]).count("1")
    compartments = max(0, min(4, mechanical_rooms - cardinal_doors_spawned))
    state.special.mechanarium_compartments[cell] = compartments


def _mechanarium_west_lever(game) -> str:
    """First diagonal compartment: "contains a West Antechamber Lever."

    Routes through secret_garden.pull_west_lever -- the same Antechamber west
    segment Secret Garden's own on-entry lever opens (effects/rooms/
    secret_garden.py; game.py's _enter_lever_room dispatches to it there) --
    rather than a second, independent lever mechanism. No extra cost beyond
    opening the compartment itself. ``pull_west_lever`` ignores its ``cell``
    argument (kept only to match the shared ``LeverPullFn`` signature every
    lever provider registers under), so there is no cell to look up here.
    """
    from .effects.rooms import secret_garden
    secret_garden.pull_west_lever(game, -1)
    return "lever:west_antechamber"


def _mechanarium_key_chain(game) -> str:
    """Second diagonal compartment: first available of Silver Key, Keycard,
    Secret Garden Key, Vault Key 233, else a basic key.

    Silver Key is not a ``unique`` item (the general spawn system allows more
    than one to exist in the house at once), so ``_is_available`` alone would
    never treat an already-held Silver Key as unavailable; this compartment
    adds its own explicit "not already held" check on top, so it does not
    hand over a second one. Keycard is excluded from ``_is_available``
    (PIPELINE_EXCLUDED -- owned by locks.py's ``state.has_keycard`` instead),
    so its availability here is ``not state.has_keycard`` directly. Secret
    Garden Key and Vault Key 233 are both ``unique``, so ``_is_available``
    already resolves "already held" correctly for them.
    """
    state, registry = game.state, game.registry
    result = silver_key.mechanarium_grant(state, registry, game)
    if result is not None:
        return result
    if not keycard.held(state):
        return _apply_grant(state, registry, game, {"kind": keycard.ITEM_ID})
    if _is_available(state, secret_garden_key.ITEM_ID, registry):
        return _apply_grant(
            state, registry, game, {"kind": "item", "id": secret_garden_key.ITEM_ID})
    if _is_available(state, "vault_key_233", registry):
        return _apply_grant(state, registry, game, {"kind": "item", "id": "vault_key_233"})
    return _apply_grant(state, registry, game, {"kind": "keys", "amount": 1})


def _mechanarium_upgrade_chain(game) -> str:
    """Third diagonal compartment: first available of the Upgrade Disk,
    Battery Pack, Broken Lever, Sledge Hammer, else a Trunk roll.

    All four items are ``unique``, so ``_is_available`` alone (already-held +
    gated_out) resolves each step; the Upgrade Disk in particular becomes
    unavailable once ``GameConfig.collected_disks`` gates it out via
    ``configure()`` -- "The Upgrade Disk becomes unavailable if the disk from
    this location was previously used" (wiki). The Trunk fallback rolls the
    ordinary ``containers.kinds.trunk`` loot table exactly as a real Trunk
    container would: the wiki names "Trunk" as the last resort rather than a
    specific item.
    """
    state, registry = game.state, game.registry
    for item_id in ("upgrade_disk_mechanarium", battery_pack.ITEM_ID, broken_lever.ITEM_ID,
                     sledge_hammer.ITEM_ID):
        if _is_available(state, item_id, registry):
            return _apply_grant(state, registry, game, {"kind": "item", "id": item_id})
    loot = registry.special.containers.get("kinds", {}).get("trunk", {}).get("loot", [])
    if not loot:
        return ""
    weights = tuple(float(e["weight"]) for e in loot)
    idx = game.rng.roll_weighted("mechanarium_compartment_trunk", weights)
    tags = [t for g in loot[idx].get("grants", []) if (t := _apply_grant(state, registry, game, g))]
    return "/".join(tags) if tags else ""


def _mechanarium_sanctum_chain(game) -> str:
    """Fourth diagonal compartment: "a Sanctum Key, or 8 dice if the Sanctum
    Key has already been used or is otherwise unavailable" (wiki).

    ``_is_available`` already resolves the Sanctum Key's own cross-day gates
    (``GameConfig.collected_sanctum_keys`` once spent, and ``room46_reached``
    before any Sanctum Key may spawn at all -- both seeded into
    ``state.special.gated_out`` by ``configure()``).
    """
    state, registry = game.state, game.registry
    if _is_available(state, "sanctum_key_mechanarium", registry):
        return _apply_grant(
            state, registry, game, {"kind": "item", "id": "sanctum_key_mechanarium"})
    return _apply_grant(state, registry, game, {"kind": "dice", "amount": 8})


def can_open_car_trunk(game) -> bool:
    """True when: special items enabled, Car Keys held, standing in the Garage,
    and the car trunk has not yet been opened today.

    The trunk re-locks every night, unlike the Vault deposit boxes: Car Keys are
    required on every open, not just the first. The disk inside still returns
    until spent — see ``open_car_trunk`` — so a later day costs fresh Car Keys
    but yields the same unspent disk.

    The garage car trunk is a one-per-day mechanic separate from regular containers.
    """
    state = game.state
    registry = game.registry
    if not state.special.enabled:
        return False
    if state.special.garage_car_opened:
        return False
    if not has(state, car_keys.ITEM_ID):
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

    The trunk re-locks every night, so reaching this function always costs Car
    Keys (see ``can_open_car_trunk``). What varies is only what is inside, which
    turns on whether the disk has been spent:

    - Disk NOT yet spent (not in ``cfg.collected_disks``):
        grant the Upgrade Disk from ``garage_car.first_loot``. It returns to the
        trunk overnight, so this path fires on every open until the player
        actually inserts the disk at a terminal.

    - Disk already spent (in ``cfg.collected_disks``):
        the disk is gone for good; draw ``later_draws`` items from ``later_pool``
        and grant ``later_gold`` coins instead.

    One use per day (``state.special.garage_car_opened`` is the within-day guard).
    """
    state = game.state
    registry = game.registry
    cfg = game.cfg
    car_cfg = registry.special.containers.get("garage_car", {})

    state.special.garage_car_opened = True
    granted: list[str] = []

    first_loot = car_cfg.get("first_loot", [])

    # Disk not yet spent: grant it (first time ever, or re-grant from open trunk)
    disk_spent = "upgrade_disk_garage" in getattr(cfg, "collected_disks", frozenset())
    if not disk_spent and first_loot:
        for entry in first_loot:
            if entry.get("kind") == "item":
                iid = entry["id"]
                if _is_available(state, iid, registry):
                    grant(state, registry, iid, source="garage_car")
                    granted.append(iid)
        return granted

    # Disk already spent: draw from later_pool + grant later_gold coins
    later_pool = list(car_cfg.get("later_pool", []))
    later_draws = car_cfg.get("later_draws", 2)
    later_gold = car_cfg.get("later_gold", 5)

    available = [iid for iid in later_pool
                 if iid == keycard.ITEM_ID or _is_available(state, iid, registry)]
    for _ in range(later_draws):
        if not available:
            break
        pick_idx = game.rng.randint("garage_car", 0, len(available) - 1)
        picked = available.pop(pick_idx)
        if picked == keycard.ITEM_ID:
            granted.append(keycard.grant(state))
        elif _is_available(state, picked, registry):
            grant(state, registry, picked, source="garage_car")
            granted.append(picked)

    if later_gold > 0:
        bonus = on_coins_granted(state, registry, later_gold)
        state.coins += later_gold + bonus
        state.items_found_log.append(("coins", later_gold))

    return granted


# --------------------------------------------------------- vault deposit boxes

def can_open_vault_box(game) -> str | None:
    """Return the vault key id whose box is actionable right now, or None.

    Two access paths per key / box pair:

    - **Key held, box never opened**: the player holds the key, the box has not
      been opened today, and it was never opened before (key not in
      ``cfg.used_vault_keys``).  Normal first-time access; key stays in inventory
      but is recorded in ``used_vault_keys`` permanently (the box is now open).

    - **Box previously opened (key in used_vault_keys), disk not yet spent**:
      the box stays open permanently; no key is needed to re-enter it.  This path
      fires every day for ``vault_key_304`` until ``upgrade_disk_vault_304``
      is spent (inserted at a terminal), at which point ``collected_disks``
      blocks the disk and there is nothing left to grant — the box becomes inert.

    Boxes for keys 149, 233, and 370 grant non-disk items (an Allowance Token,
    sanctum_key); the ``has_respawning_disk`` check below is False for all
    three, so once opened they never satisfy the re-entry condition again --
    the box itself becomes permanently inert, independent of whatever
    persistence the granted item carries.

    Requires: standing in the Vault, special items enabled.
    Priority order: 149, 233, 304, 370.
    """
    state = game.state
    registry = game.registry
    if not state.special.enabled:
        return None
    if state.grid[state.pos] < 0:
        return None
    room = registry.rooms[state.grid[state.pos]]
    if room.id != "vault":
        return None
    vault_boxes = registry.special.containers.get("vault_boxes", {})
    boxes = vault_boxes.get("boxes", {})
    used_keys = getattr(game.cfg, "used_vault_keys", frozenset())
    for key_id in ("vault_key_149", "vault_key_233", "vault_key_304", "vault_key_370"):
        if key_id not in boxes:
            continue
        if key_id in state.special.vault_boxes_opened:
            continue  # already opened this day
        if key_id in used_keys:
            # Box was previously opened; the only thing worth re-entering for is a
            # day-persistence disk (which returns to the open box until spent).
            # Boxes 149/233/370 grant an Allowance Token / sanctum_key, neither of
            # which is a respawning disk, so those boxes never satisfy this check
            # again once opened -- they stay permanently inert.
            box_grants = boxes[key_id].get("grants", [])
            has_respawning_disk = any(
                (item := registry.special.by_id.get(item_id)) is not None
                and item.id.startswith("upgrade_disk_")
                and item.persistence == "day"
                and _is_available(state, item_id, registry)
                for item_id in box_grants
            )
            if has_respawning_disk:
                return key_id
            continue  # nothing left to grant; skip
        if state.inventory.get(key_id, 0) > 0:
            return key_id
    return None


def open_vault_box(game) -> list[str]:
    """Open (or re-enter) the vault deposit box for the matching key; return granted ids.

    First opening (key not yet in ``cfg.used_vault_keys``):
        The key stays in inventory but is added to ``state.special.removed``
        (so it cannot re-spawn this day) and to ``used_vault_keys`` carry-over
        (box is permanently open; key never needed again).

    Re-entry on a later day (key already in ``cfg.used_vault_keys``):
        Box is already open — no key interaction.  Only the disk grant is
        attempted; ``_is_available`` blocks it if it is in ``collected_disks``
        (i.e. already spent), so this is a no-op once the disk is gone.

    Grants: allowance_token (149/233), upgrade_disk_vault_304 (304),
    sanctum_key_vault (370).  Returns the list of granted item ids.
    """
    state = game.state
    registry = game.registry
    key_id = can_open_vault_box(game)
    if key_id is None:
        return []
    vault_boxes = registry.special.containers.get("vault_boxes", {})
    boxes = vault_boxes.get("boxes", {})
    box_data = boxes.get(key_id, {})

    state.special.vault_boxes_opened.append(key_id)

    used_keys = getattr(game.cfg, "used_vault_keys", frozenset())
    if key_id not in used_keys:
        # First opening: bar the key from spawning again (it stays in inventory).
        if key_id not in state.special.removed:
            state.special.removed.append(key_id)
    # Re-entry (key in used_vault_keys): box already open, no key action needed.

    granted = []
    for item_id in box_data.get("grants", []):
        if _is_available(state, item_id, registry):
            grant(state, registry, item_id, source="vault_box")
            granted.append(item_id)
    return granted


# --------------------------------------------------------- inner sanctum


def can_open_sigil_door(game, realm: str) -> bool:
    """Holding an unspent Sanctum Key, standing at the Inner Sanctum, door sealed.

    ``realm`` must be one of :data:`SIGIL_REALMS`. Requires special items
    enabled, the player off-grid at the ``inner_sanctum`` area node, at least
    one held ``sanctum_key_*`` item, and the realm's door not already open
    (checked against BOTH ``cfg.sigil_doors_open``, permanent from an earlier
    day, and ``state.special.sigil_doors_opened``, opened earlier today).
    """
    state = game.state
    if realm not in SIGIL_REALMS:
        return False
    if not state.special.enabled:
        return False
    if state.area != "inner_sanctum":
        return False
    if (realm in getattr(game.cfg, "sigil_doors_open", frozenset())
            or realm in state.special.sigil_doors_opened):
        return False
    return any(state.inventory.get(kid, 0) > 0 for kid in SANCTUM_KEY_IDS)


def open_sigil_door(game, realm: str) -> bool:
    """Spend one held Sanctum Key to permanently unlock the Sigil Chamber door for ``realm``.

    Picks the first held key id in :data:`SANCTUM_KEY_IDS` order (a specific
    physical key is not tracked; any held key opens any door -- the wiki does
    not distinguish). Consuming it (``remove(..., consumed=True)``) records
    its *source* in ``state.special.removed``, which ``fixed_sanctum_keys_spent_today``
    turns into the permanent ``collected_sanctum_keys`` carry-over so that
    source never spawns another key. Grants the realm's own dedicated
    Allowance Token immediately (the assumed-solved Mora Jai box fires the
    moment the door opens, not on a later chamber visit -- see the
    ``sigil_chambers`` node's notes in areas.json). Returns True on success.
    """
    if not can_open_sigil_door(game, realm):
        return False
    state = game.state
    registry = game.registry
    key_id = next(kid for kid in SANCTUM_KEY_IDS if state.inventory.get(kid, 0) > 0)
    remove(state, key_id, consumed=True)
    state.special.sigil_doors_opened.append(realm)
    token_id = f"allowance_token_sigil_{realm}"
    if _is_available(state, token_id, registry):
        grant(state, registry, token_id, source="sigil_chamber")
    return True


def fixed_sanctum_keys_spent_today(state, registry) -> set[str]:
    """Sanctum Key source ids consumed today, for the collected_sanctum_keys carryover.

    Mirrors fixed_disks_spent_today: each of the eight sources has its own
    item id, consumed (remove(..., consumed=True)) the instant open_sigil_door
    spends it, so state.special.removed already records it here.
    """
    keys = {item.id for item in registry.special.items if item.id in SANCTUM_KEY_IDS}
    return keys & set(state.special.removed)


# ----------------------------------------------------------------- ignition

def _ignition_tools(registry) -> frozenset:
    """Set of item ids that can light ignition targets (torch and burning_glass)."""
    return frozenset(registry.special.ignition.get("tools", []))


def ignition_requires_met(inventory: dict, target_cfg: dict) -> bool:
    """True when a target's item requirement(s) are satisfied by ``inventory``.

    Supports both shapes a target's data record may declare: the legacy
    ``requires_item`` (a single item id, held count >= 1 -- unused by any
    target today but kept working) and ``requires_items`` (a dict of item id
    -> minimum held count, e.g. the sundial's ``{"microchip": 3}``). A target
    with neither key has no requirement and always passes. Shared by
    special_items.py::can_light and env/actions.py::_cell_has_ignition_target
    so the two callers never drift apart.
    """
    req = target_cfg.get("requires_item")
    if req is not None:
        return inventory.get(req, 0) > 0
    reqs = target_cfg.get("requires_items")
    if reqs:
        return all(inventory.get(item_id, 0) >= count for item_id, count in reqs.items())
    return True


def _current_ignition_target_id(game) -> str | None:
    """Id of the ignition target the player currently stands at, or None.

    On-grid, this is the room id under state.pos, matched against a target
    entry that is NOT flagged "area". Off-grid (state.area is not None), it is
    the area-graph node id in state.area, matched against a target entry that
    IS flagged "area" (e.g. mine_south — an off-grid node with no rooms.json
    record). Either way, a location that isn't itself a listed target (or is
    listed under the wrong shape) returns None, same as an ordinary room.
    """
    state = game.state
    registry = game.registry
    targets = registry.special.ignition.get("targets", {})
    if state.area is not None:
        target_id = state.area
        if target_id in targets and targets[target_id].get("area", False):
            return target_id
        return None
    if state.grid[state.pos] < 0:
        return None
    room = registry.rooms[state.grid[state.pos]]
    if room.id in targets and not targets[room.id].get("area", False):
        return room.id
    return None


def can_light(game) -> bool:
    """True when: special items enabled, standing at an ignition target (a
    room on the grid, or an off-grid area node flagged "area" in
    ignition.targets), holding a torch or burning_glass, target not yet lit
    today, and any requires_item/requires_items satisfied.

    Only targets listed in ignition.targets are actionable; targets absent
    from both rooms.json and areas.json (crate_tunnel) are listed in
    ignition.meta.absent_targets and never appear here.
    """
    state = game.state
    registry = game.registry
    if not state.special.enabled:
        return False
    target_id = _current_ignition_target_id(game)
    if target_id is None:
        return False
    if target_id in state.special.lit_targets:
        return False
    # Check tool held
    tools = _ignition_tools(registry)
    if not any(state.inventory.get(t, 0) > 0 for t in tools):
        return False
    # Check requires_item / requires_items
    target_cfg = registry.special.ignition["targets"][target_id]
    if not ignition_requires_met(state.inventory, target_cfg):
        return False
    return True


def light(game) -> None:
    """Light the ignition target at the current room/area; grant its rewards.

    Marks the target as lit (one-shot per target; persists across days via
    carryover/configure). Grants all entries from the target's 'grants' list:
    - coins/gems/dice: granted directly.
    - item: granted via grant() (no-op if unavailable).
    - chapel_tithe_payout: pays out state.special.chapel_tithes coins (the
      Keeper of Tithes accumulated total) as a one-time reward.
    mine_south's grants list is empty — its Upgrade Disk is a separate,
    ungated pickup granted by on_area_arrival, not an ignition reward.
    apple_orchard's grants list is also empty: lighting the sundial sets the
    permanent state.satellite_dish_unlocked flag directly below instead of
    through the grants list, since the reward is a config unlock rather than
    an inventory item or a resource.
    Does not consume the tool (torch/burning_glass are reusable).
    """
    from . import items as items_mod  # deferred to avoid cycles
    state = game.state
    registry = game.registry
    if not can_light(game):
        return
    target_id = _current_ignition_target_id(game)
    target_cfg = registry.special.ignition["targets"][target_id]
    state.special.lit_targets.append(target_id)
    if target_id == "apple_orchard":
        # Satellite Dish unlock: recorded on STATE, never written back to
        # GameConfig (one config object is shared by every episode of a
        # trainer worker). shops.py::carryover() ORs this with
        # cfg.satellite_dish_unlocked; DayChain carries the result permanently.
        state.satellite_dish_unlocked = True
    for reward in target_cfg.get("grants", []):
        kind = reward.get("kind")
        match kind:
            case "coins":
                amount = reward.get("amount", 0)
                bonus = on_coins_granted(state, registry, amount)
                state.coins += amount + bonus
                state.items_found_log.append(("coins", amount))
            case "gems":
                amount = reward.get("amount", 0)
                state.gems += amount
                state.items_found_log.append(("gem", amount))
            case "dice":
                amount = reward.get("amount", 1)
                # grant_item already logs the pickup (see above).
                items_mod.grant_item(game, "die", amount)
            case "chapel_tithe_payout":
                # Pay out the Keeper of Tithes accumulated total: every coin the
                # Chapel's -1 entry penalty ever took.  The counter is cleared
                # after payout (the piggy bank is broken and emptied).
                payout = state.special.chapel_tithes
                if payout > 0:
                    bonus = on_coins_granted(state, registry, payout)
                    state.coins += payout + bonus
                    state.items_found_log.append(("coins", payout))
                    state.special.chapel_tithes = 0
            case "item":
                item_id = reward.get("id", "")
                if _is_available(state, item_id, registry):
                    grant(state, registry, item_id, source="ignition")
            case _:
                pass


# --------------------------------------------------------------- lever install

def can_install_lever(game) -> bool:
    """True when: special items enabled, standing in a machine room listed in
    machines, holding a broken_lever, and the machine has not been used today.

    Machine rooms: greenhouse (antechamber_lever), casino (slot_bonus).
    """
    state = game.state
    registry = game.registry
    if not state.special.enabled:
        return False
    if not has(state, broken_lever.ITEM_ID):
        return False
    if state.grid[state.pos] < 0:
        return False
    room = registry.rooms[state.grid[state.pos]]
    machines = registry.special.machines
    machine_ids = {k for k in machines if k != "meta"}
    if room.id not in machine_ids:
        return False
    if room.id in state.special.machines_used:
        return False
    return True


def install_lever(game) -> None:
    """Install the broken_lever in the current machine room; apply its effect.

    Consumes the broken_lever (consumed=True so it doesn't re-spawn today).
    Records the room id in machines_used to prevent a second install.
    Dispatches effects:
    - antechamber_lever: unlock the Antechamber south doorway (cell 37's north side,
      segment (37, N)); the wiki calls this the "south Antechamber door" because it
      connects rank-8 center (cell 37) to the Antechamber (cell 42) from below.
      Also fires the antechamber_lever_pull experiment trigger (dedup'd against
      the Weight Room's own south lever by experiments.on_lever_pulled, since
      both target the same segment).
    - slot_bonus: grant the casino loot from machines.casino.grants
    """
    state = game.state
    registry = game.registry
    if not can_install_lever(game):
        return
    room = registry.rooms[state.grid[state.pos]]
    machines = registry.special.machines
    machine_cfg = machines.get(room.id, {})
    effect = machine_cfg.get("effect")

    # Consume the lever first
    remove(state, broken_lever.ITEM_ID, consumed=True)
    state.special.machines_used.append(room.id)

    from .grid import N
    match effect:
        case "antechamber_lever":
            # Unlock the Antechamber's SOUTH doorway segment (the wiki calls it
            # the "south door").  The segment is shared between rank-8 center
            # (cell 37) and the Antechamber (cell 42): segment_key(42, S) ==
            # segment_key(37, N) == (37, 1).  We call _open_segment(37, N) because
            # that is how segment_key canonicalizes it (lower cell, north direction).
            # The Antechamber's north door opens only from the Throne Room and the
            # Sanctum lever — neither is modeled.
            ante_cell = 37  # rank-8 center; neighbor(37, N) == ANTECHAMBER_CELL(42)
            game._open_segment(ante_cell, N)
            experiments.on_lever_pulled(game, ante_cell, N)
        case "slot_bonus":
            for reward in machine_cfg.get("grants", []):
                kind = reward.get("kind")
                match kind:
                    case "coins":
                        amount = reward.get("amount", 0)
                        bonus = on_coins_granted(state, registry, amount)
                        state.coins += amount + bonus
                        state.items_found_log.append(("coins", amount))
                    case "gems":
                        amount = reward.get("amount", 0)
                        state.gems += amount
                        state.items_found_log.append(("gem", amount))
                    case "item":
                        item_id = reward.get("id", "")
                        if _is_available(state, item_id, registry):
                            grant(state, registry, item_id, source="machine")
                    case _:
                        pass
        case _:
            pass
