"""Game configuration: unlock toggles, stage selection, rule flags."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
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
    # Apple Orchard reached at least once (any prior day): +20 starting steps
    # (Game.reset). Earned the first time the player travels to apple_orchard;
    # same carry shape as west_gate_unlatched (recorded on GameState, ORed in
    # via shops.carryover(), never written back here).
    orchard_unlocked: bool = False
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
    # The Foundation does not reset day-to-day: once drafted it stays at the same
    # cell/orientation forever.  -1 = not yet drafted this attempt.
    foundation_cell: int = -1           # grid cell the Foundation permanently occupies
    foundation_doors: int = 0           # its frozen 4-bit door mask; 0 = not yet drafted
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
        iterable of characters.  ``--set upgrade_disks=cloister_of_orinda__ix35``
        used to reach ``frozenset(str)``, which silently produced a set of single
        letters: the ids matched nothing, so the override did nothing and said
        nothing.  A measurement configured that way silently measures its own
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


# Config fields that hold a set of ids.  DERIVED from the annotations, not hand-listed:
# the previous hand-written tuple was one edit away from silently omitting a new
# frozenset field, and an omitted field would pass its raw value straight through.
# `from __future__ import annotations` makes f.type a string, hence the substring test.
_SET_VALUED_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(GameConfig) if "frozenset" in f.type
)
