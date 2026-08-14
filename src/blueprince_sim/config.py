"""Game configuration: unlock toggles, stage selection, rule flags."""

from __future__ import annotations

import hashlib
import json
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path

STAGES = ("week1", "week2", "late", "auto")


@dataclass
class GameConfig:
    # --- episode framing ---
    day: int = 20                      # in-game day; drives stage when stage="auto"
    stage: str = "auto"                # week1|week2|late|auto (auto = derive from day)
    # step budget at day start; OPEN QUESTION: community consensus 50, confidence=wiki
    starting_steps: int = 50
    # --- permanent unlocks (the "enable various unlocks" toggles) ---
    studio_additions: frozenset[str] = frozenset()   # subset of the 8 studio-addition room ids
    # True when the West Gate has been permanently unlatched (Grounds <-> West Path shortcut
    # is open). Maps to the "west_gate_unlatched" flag in GateContext. Earned the first time
    # the player reaches west_path via the Garage route; afterwards, the 2-step Grounds route
    # is open for all future days. Does NOT gate outer-room drafting — on a fresh save the
    # Garage route works from day 1 (no flag needed), so the draft is available whenever the
    # route cost is affordable and no outer room has been drafted today.
    west_gate_unlatched: bool = False
    # The mine cart has been shifted from the south side, permanently opening
    # reservoir_north -> mine_north and rotating_gear -> underpass.
    mine_south_visited: bool = False
    # The Sealed Entrance barrier has been broken by the Power Hammer, permanently
    # opening grounds<->sealed_entrance<->basement for the rest of the attempt.
    sealed_entrance_broken: bool = False
    # The Boiler Room has been entered at least once (any prior day), permanently
    # opening the "boiler_room_steam" gate: Underpass -> Upper Rotating Gear.
    boiler_room_steam: bool = False
    # The Treasure Trove blackprint has been picked up at Upper Rotating Gear
    # (any prior day), permanently adding the Treasure Trove to the draft pool
    # (decks.py::eligible_pool) from the following day onward.
    treasure_trove_blackprint: bool = False
    # The Throne Room blueprint has been picked up at Orindian Ruins (any prior
    # day), permanently adding the Throne Room to the draft pool
    # (decks.py::eligible_pool) from the following day onward.
    throne_room_blueprint: bool = False
    # Room 8 solved on a prior day this attempt: later solves pay the reduced
    # repeat-solve reward instead of the first-solve one (effects/rooms/room_8.py).
    # Same carry shape as west_gate_unlatched (recorded on GameState, ORed in
    # via shops.carryover(), never written back here).
    room8_solved: bool = False
    # Apple Orchard reached at least once (any prior day): +20 starting steps
    # (Game.reset). Earned the first time the player travels to apple_orchard;
    # same carry shape as west_gate_unlatched (recorded on GameState, ORed in
    # via shops.carryover(), never written back here).
    orchard_unlocked: bool = False
    # The Apple Orchard sundial has been lit (three held microchips + an ignition
    # tool), permanently unlocking the Satellite Dish. Same carry shape as
    # west_gate_unlatched (recorded on GameState, ORed in via shops.carryover(),
    # never written back here). Consumed by engine/experiments.py::draw_offers /
    # _effect_offerable to open the packet trigger/effect pools (implemented
    # records only) alongside base -- from the FOLLOWING day onward, same as
    # orchard_unlocked's own steps bonus, since this is read from cfg, not state.
    satellite_dish_unlocked: bool = False
    # Sauna entered on the previous day: +20 starting steps today only (Game.reset).
    # A ONE-DAY pulse, not a permanent unlock like orchard_unlocked: DayChain replaces
    # this each advance() from that day's own carryover rather than OR-ing it in
    # forever, so a day that does not (re-)enter a Sauna does not inherit yesterday's
    # bonus (wiki: "Sauna" is a "Tomorrow Room", scoped to the single following day).
    sauna_bonus: bool = False
    # Morning Room entered on the previous day: +2 starting gems today only
    # (Game.reset). Same one-day pulse shape as sauna_bonus.
    morning_room_bonus: bool = False
    # A previous day ended with the player standing in Break Room: start today with
    # a keycard (Game.reset -> state.has_keycard). Same one-day pulse shape as
    # sauna_bonus.
    break_room_keycard: bool = False
    # Freezer carry: coins/gems to start today with instead of the normal reset
    # (0 coins; gems from mine_unlocked/morning_room_bonus only). 0 = no freeze
    # pending. A one-day pulse, replaced each DayChain.advance() from that day's
    # own carryover -- entering the Freezer again is required to keep carrying.
    frozen_coins: int = 0
    frozen_gems: int = 0
    # No Contact Delivery (mail_room__ix90) drafted on the previous day: its
    # package grants outright at the start of today (Game.reset via
    # shops.on_day_start). Same one-day pulse shape as sauna_bonus -- a day
    # that does not draft it again does not inherit yesterday's order.
    no_contact_due: bool = False
    mine_unlocked: bool = False                      # Gemstone Cavern: +2 gems at day start (wiki)
    upgrade_disks: frozenset[str] = frozenset()      # applied variant room ids (e.g. "pool_hall__ix12")
    # Veteran Mode (New Game+). Default TRUE: this project models expert play.
    # Gates three things -- the stricter gem deck-size gates (with day>=16/room46),
    # the Garage forced draw before day 3, and the veteran Upgrade-Disk slot table.
    veteran_mode: bool = True
    room46_reached: bool = False                     # Room 46 reached before: gem deck-size gate
    # Draft-condition gates satisfied for this run (item/unlock-dependent
    # conditions: "breakfast", "secret_garden_key", "knight_chess_piece",
    # "room8_key"). Rooms carrying an unsatisfied gate never deal.
    satisfied_conditions: frozenset[str] = frozenset()
    # Locked doors and security doors (data/locks.json): doorway segments can
    # roll locked (opening costs a key) or spawn as security doors (opened by
    # the keycard system: Security terminal + Utility Closet breaker).
    door_locks: bool = True
    # True (default): the three non-north Antechamber doorways start each day SEALED
    # and require a lever room to be entered before the Antechamber can be reached.
    # False: all four Antechamber doors open unconditionally, reproducing the old
    # open-door model so existing baselines remain reproducible.
    antechamber_levers: bool = True
    # --- rule flags for documented-but-ambiguous behavior ---
    strict_door_matching: bool = False  # True: forbid doors facing occupied blank walls
    # Compass held this run: shifts the random rotation roll toward north-facing
    # doors (datamined "Compass" column). See engine/rotation.py.
    compass: bool = False
    # Ornate Compass held this run: a rotate-at-will option is available on every
    # draft (choose any legal orientation), the way the Dovecote is only while
    # it is one of the drawn options.
    ornate_compass: bool = False
    # --- special items (engine/special_items.py; docs/special-items-design.md) ---
    special_items: bool = True          # master toggle for special-item spawning/behavior
    # Special items held at day start. RL curricula, tests, and the (future)
    # multi-day carry-over wrapper all inject items through this.
    starting_items: frozenset[str] = frozenset()
    # Cross-day discovery unlocks (each changes what spawns today):
    lunch_box_unlocked: bool = False    # bought once at the Gift Shop: Dining Rooms spawn it daily
    cursed_effigy_unlocked: bool = False  # Cursed Coffers bought: the Shrine spawns the Effigy
    # Treasure Trove opened before: scepter granted at day start.
    # Default True: the unlock puzzle (Key of Aries -> Treasure Trove) is unmodeled, so
    # defaulting on is the only way the scepter is ever exercised.  Set False to disable.
    royal_scepter_found: bool = True
    # Vault Key ids whose deposit box has been opened (ever, across all days).
    # These keys are never grantable again — permanently removed from spawn pool.
    used_vault_keys: frozenset[str] = frozenset()
    # Cumulative per-attempt draft counts keyed by root base room id, carried
    # from previous days.  Plain dict — NOT in the frozenset-coercion list.
    draft_counts: dict[str, int] = field(default_factory=dict)
    entrance_vase_broken: bool = False  # west vase smashed before: its microchip granted at day start
    # Weight Room wall broken before with the Power Hammer: the wall stays broken on
    # future days, so entering the Weight Room opens the south Antechamber door
    # without needing to hold the Power Hammer again. Carried by DayChain.
    weight_room_wall_broken: bool = False
    outer_chip_dug: bool = False        # West Path chip dug up before: granted on reaching the doorstep
    # Room ids banned from the draft pool by the Repellent item.  Each
    # repellent use records a ban for 7 days; DayChain decrements the counters
    # on advance() and passes the survivors here.  Rooms in this set are excluded
    # from eligible_pool() in engine/decks.py.  The dict lives in DayChain and is
    # converted to a frozenset of active (days_left > 0) room ids for the config.
    banned_rooms: frozenset[str] = frozenset()
    # Ignition targets permanently lit across days (set of room ids, e.g. "chapel",
    # "tomb", "trading_post").  Once a target is lit it cannot be lit again in any
    # later day within the same attempt.  Carried by DayChain as a frozenset and
    # merged as a union — a lit target never un-lights.
    lit_targets: frozenset[str] = frozenset()
    # Upgrade Disk ids already spent (inserted at a terminal).  Covers all
    # persistence="day" disks: the seven in-grid guaranteed_in room disks (Office,
    # Morning Room, Her Ladyship's Chamber, Great Hall, Freezer, Archives,
    # Mechanarium) plus the four bespoke-source disks (garage, vault_304, tomb,
    # trading_post).  An unspent disk drops at end of day and returns to its
    # source on re-entry/re-open; only spending it (remove(..., consumed=True))
    # makes removal permanent.  upgrade_disk_trade is excluded (repeatable).
    # Carried by DayChain as a frozenset and merged as a union; seeded into
    # gated_out at day start so _is_available refuses them.
    collected_disks: frozenset[str] = frozenset()
    # Accumulated Keeper of Tithes coins: every time the Chapel's entry -1 coin
    # penalty actually fires (player has at least 1 coin when entering the Chapel),
    # this counter increments.  Lighting the Chapel altar pays out the running total
    # immediately.  Carried by DayChain as a running sum so the total grows across
    # all days until the altar is lit (which is a one-time-ever event by construction,
    # since lit_targets makes the Chapel un-lightable on future days).
    chapel_tithes: int = 0
    # Permanent allowance total: the daily gold packet's size.  Grown by
    # Allowance Tokens (+2 each) and Cloister of Lydia (+2 per Shop drafted
    # from it) and added to coins at the start of every future day
    # (Game.reset).  Never spent itself.  Carried by DayChain as a running
    # total, replaced wholesale each advance() the same way as chapel_tithes.
    allowance: int = 0
    # Permanent star total: grown by the Observatory and Starfish Aquarium
    # (both +1 per draft, never per entry) and carried into every future day
    # (Game.reset).  Never spent itself.  Carried by DayChain as a running
    # total, replaced wholesale each advance() the same way as allowance.
    stars: int = 0
    # Cloister of Joya's permanent Main Course bonus: +5 per Kitchen/Pantry/
    # Furnace drafted from it, added to every one of the five main-course
    # dishes and added to future days (Game.reset). Never spent itself.
    # Carried by DayChain as a running total, replaced wholesale each
    # advance() the same way as allowance/stars.
    main_course_bonus: int = 0
    # Experiment letters delivered to the Mail Room (permanent additions, in a
    # fixed published order, capped at 16).  Their contents are deliberately
    # unmodelled -- see experiments.json -- so this exists only to retire the
    # mail_room_letter effect from the setup draw once all 16 have arrived.
    # Carried by DayChain as a running total, replaced wholesale each advance()
    # the same way as stars; SAVE-scoped, so it survives an attempt wrap.
    letters_delivered: int = 0
    # Fixed-source Allowance Token ids collected (ever, across all days): each
    # one-time find spot (a Mora Jai box or the Cloister's token) has its own
    # item id, so this set gates exactly the sources already collected without
    # blocking the others.  Same shape as collected_disks: seeded into
    # gated_out at day start, accumulated as a union by DayChain, never
    # shrinks within an attempt.
    collected_allowance_tokens: frozenset[str] = frozenset()
    # Mail Room order/delivery cycle carried into the next day: "empty" (no
    # order outstanding) or "awaiting" (an order is placed; the next Mail
    # Room draft delivers it). Replaced wholesale each advance() the same
    # way as chapel_tithes/allowance, since state.mail_cycle already IS the
    # day's ending value.
    mail_cycle: str = "empty"
    # Freight Shipping (mail_room__ix91) transit countdown carried into the next
    # day: days remaining in the "transit" cycle state, 0 outside of one. Replaced
    # wholesale each advance() (mechanical decay lives in DayChain.advance()), the
    # same shape as mail_cycle.
    mail_transit_days: int = 0
    # Tomorrow Hallway (hallway__ix76) carry: extra Hallway copies to inject into
    # TODAY's draft pool at day start, from Tomorrow Hallways drafted YESTERDAY.
    # A one-day pulse, not a running total -- replaced wholesale each advance()
    # from that day's own count (state.hallway_tomorrow_count), the same shape
    # as mail_cycle/mail_transit_days, so a day that drafts none clears the
    # bonus rather than compounding it forever.
    hallway_tomorrow_extra: int = 0
    # Clock Tower carry: starting keys to grant TODAY (Game.reset -> state.keys),
    # from yesterday's day-end Tomorrow-room tally (state.clock_tower_tomorrow_keys)
    # if the Clock Tower was present in the mansion. A one-day pulse, not a running
    # total -- replaced wholesale each advance(), the same shape as
    # hallway_tomorrow_extra, so a day that ends without the Clock Tower standing
    # clears the bonus rather than compounding it forever.
    clock_tower_tomorrow_keys: int = 0
    # Sanctum Key source ids permanently spent (ever, across all days): opening a
    # Sigil Chamber door consumes one key and its own source id (e.g.
    # "sanctum_key_vault") is recorded here, so that source never spawns another
    # key -- "no longer spawns in the location it was obtained" (wiki). Same
    # shape as collected_disks: seeded into gated_out at day start, accumulated
    # as a union by DayChain, never shrinks within an attempt.
    collected_sanctum_keys: frozenset[str] = frozenset()
    # Realm ids (arch_aries, corarica, eraja, fenn_aries, mora_jai, nuance,
    # orinda_aries, verra) whose Inner Sanctum door has been permanently
    # unlocked with a Sanctum Key.  Union-accumulated across days by DayChain;
    # an opened door never re-seals.
    sigil_doors_open: frozenset[str] = frozenset()
    # The Foundation does not reset day-to-day: once drafted it stays at the same
    # cell/orientation forever.  -1 = not yet drafted this attempt.
    foundation_cell: int = -1           # grid cell the Foundation permanently occupies
    foundation_doors: int = 0           # its frozen 4-bit door mask; 0 = not yet drafted
    # --- Shrine blessings/curse (data/shrine.json; engine/effects/rooms/shrine.py) ---
    # SAVE-scoped (survives an attempt wrap, like stars/main_course_bonus), but decayed
    # day-to-day the way mail_transit_days is: DayChain replaces these from each day's
    # own carryover value, then mechanically decrements the two day-counts by 1 (floored
    # at 0) every advance().
    shrine_blessing_id: str = ""    # active blessing id; meaningful only while blessing_days > 0
    shrine_blessing_days: int = 0   # days left on the blessing, counting the day it was granted
    shrine_curse_days: int = 0      # days left on the Shrine curse (2 when freshly cursed)
    # Coins parked in the stone bowl for the active blessing; returned in full if the
    # offering is taken back. Meaningful only while shrine_blessing_days > 0.
    shrine_offered_coins: int = 0
    # Reserved for Blessing of the Monk (not implemented -- blocked on grounds
    # drafting, see data/shrine.json): would hold the cell the day ended in, to
    # offer that room from the grounds the next day. Always -1 today.
    shrine_monk_room: int = -1
    # --- The Axe (engine/effects/items/the_axe.py; data/special_items.json) ---
    # Ordered tuple of floorplan-family root ids (upgrades.root_base_id)
    # permanently axed this SAVE: each one's gem cost is zeroed forever
    # (engine/state.py::resolve_gem_cost), capped at 3 simultaneously active
    # (the_axe's own data-driven max_active). SAVE-scoped like stars/
    # main_course_bonus/the shrine_* fields -- env/multiday.py::DayChain does
    # NOT clear this at the attempt wrap, unlike draft_counts/upgrade_disks.
    # An ORDERED TUPLE, not a frozenset: the wiki's unmodelled "a 4th axe
    # overwrites the 3rd" rule (unreachable today once the Armory gate stops
    # selling at the cap) would need insertion order to ever be implemented,
    # and a frozenset would have already thrown that away. Deliberately NOT a
    # "frozenset" annotation, so _SET_VALUED_FIELDS (which matches on that
    # substring) does not try to coerce it -- coercing a tuple field the way
    # a comma-separated string is split for set-valued fields would silently
    # turn a real override into something else, the exact failure mode
    # from_dict's own docstring warns about for string inputs generally.
    axed_rooms: tuple[str, ...] = ()
    # --- Gear Wrench (engine/effects/items/gear_wrench.py; data/special_items.json) ---
    # Mechanical Room id -> permanently-set rarity index (engine/model.py RARITIES),
    # set by Game.set_wrench_rarity whenever the chosen level differs from the
    # room's own natal rarity_idx (a choice matching the natal rarity is popped
    # back out, mirroring decks.set_dynamic_rarity's own idempotent-pop
    # convention). SAVE-scoped like axed_rooms immediately above -- env/
    # multiday.py::DayChain does NOT clear this at the attempt wrap. A plain
    # dict, not in the frozenset-coercion list, same shape as draft_counts.
    permanent_rarity: dict[str, int] = field(default_factory=dict)
    # --- reward selection for the env ---
    reward: str = "sparse"              # sparse|shaped|phased
    data_dir: Path | None = None        # alternate data/*.json directory (None = packaged data)

    def resolved_stage(self) -> str:
        """Rarity-table stage; "auto" derives it from ``day`` (<=7 week1, <=14 week2)."""
        if self.stage != "auto":
            return self.stage
        if self.day <= 7:
            return "week1"
        if self.day <= 14:
            return "week2"
        return "late"

    def gem_gate_active(self) -> bool:
        """Whether the stricter gem deck-size gates apply to the rarity roll
        (veteran mode, Room 46 reached before, or day 16+)."""
        return self.veteran_mode or self.room46_reached or self.day >= 16

    @classmethod
    def from_yaml(cls, path: str | Path) -> "GameConfig":
        """Load a config from a YAML mapping file (see from_dict for coercions)."""
        import yaml

        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "GameConfig":
        """Build a config from plain values (YAML / --set overrides).

        Unknown keys raise KeyError; set-valued unlock fields are coerced to
        frozensets and data_dir to a Path.

        A set-valued field given as a STRING is a comma-separated id list, NOT an
        iterable of characters: coercing it via plain ``frozenset(str)`` would
        silently produce a set of single letters, so e.g.
        ``--set upgrade_disks=cloister_of_orinda__ix35`` would match no real id --
        the override would do nothing and say nothing, silently measuring its own
        control arm.
        """
        kwargs = {}
        valid = {f.name for f in fields(cls)}
        for k, v in raw.items():
            if k not in valid:
                raise KeyError(f"Unknown config key: {k}")
            if k in _SET_VALUED_FIELDS:
                if isinstance(v, str):
                    v = frozenset(part.strip() for part in v.split(",") if part.strip())
                else:
                    v = frozenset(v)
            elif k == "data_dir" and v is not None:
                v = Path(v)
            kwargs[k] = v
        return cls(**kwargs)


# Config fields that hold a set of ids.  DERIVED from the annotations, not hand-listed,
# so a new frozenset field can't be silently omitted -- an omitted field would pass
# its raw value straight through.
# `from __future__ import annotations` makes f.type a string, hence the substring test.
_SET_VALUED_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(GameConfig) if "frozenset" in f.type
)


def _field_default(f):
    """The declared default of dataclass field ``f``, factories called."""
    if f.default is not MISSING:
        return f.default
    return f.default_factory()


def _canonical_config_value(v):
    """JSON-ready, order-independent form of one ``GameConfig`` field value.

    frozenset -> sorted list; dict -> key-sorted dict; Path -> str;
    bool/int/str/None -> unchanged. Never touches ``hash()``.
    """
    if isinstance(v, frozenset):
        return sorted(v)
    if isinstance(v, dict):
        return {k: v[k] for k in sorted(v)}
    if isinstance(v, Path):
        return str(v)
    return v


def config_digest(cfg: GameConfig) -> str:
    """16-hex-char blake2b digest of every non-default field of ``cfg``.

    Only fields whose value differs from the field's declared default are
    hashed, so appending a new ``GameConfig`` field never changes the digest
    of an existing config that leaves it at default -- a demo record stamped
    before the field existed still matches after one is added.  The accepted
    cost of that design: changing a field's *default* (rather than adding a
    field) is invisible to the digest, since a config left at the new default
    hashes identically to one left at the old default.

    Never uses ``hash()``: ``PYTHONHASHSEED`` randomises ``str.__hash__``
    per-process, so a hash-based digest would not be stable across processes
    (``GameConfig`` is not frozen and has ``__hash__ is None`` in any case).
    """
    payload = {}
    for f in fields(cfg):
        value = getattr(cfg, f.name)
        if value != _field_default(f):
            payload[f.name] = _canonical_config_value(value)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(blob.encode(), digest_size=8).hexdigest()
