"""Game configuration: unlock toggles, stage selection, rule flags."""

from __future__ import annotations

from dataclasses import dataclass, fields
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
    outer_rooms_unlocked: bool = False               # West Gate open: outer-room draft available
    outer_path_entrance_cost: int = 2             # steps, user-verified: Entrance Hall <-> doorstep
    # steps, user-verified: garage door <-> doorstep (breaker-gated)
    outer_path_garage_cost: int = 1
    outer_enter_cost: int = 1                 # steps, user-verified: doorstep <-> inside Outer Room
    orchard_unlocked: bool = False                   # Apple Orchard: +20 starting steps (wiki)
    mine_unlocked: bool = False                      # Gemstone Cavern: +2 gems at day start (wiki)
    upgrade_disks: frozenset[str] = frozenset()      # applied upgrade ids (e.g. "pool_hall")
    veteran_mode: bool = False                       # triggers gem deck-size gates (with day>=16/room46)
    room46_reached: bool = False                     # Room 46 reached before: gem deck-size gate
    # Draft-condition gates satisfied for this run (item/unlock-dependent
    # conditions: "breakfast", "secret_garden_key", "knight_chess_piece",
    # "room8_key"). Rooms carrying an unsatisfied gate never deal.
    satisfied_conditions: frozenset[str] = frozenset()
    # Locked doors and security doors (data/locks.json): doorway segments can
    # roll locked (opening costs a key) or spawn as security doors (opened by
    # the keycard system: Security terminal + Utility Closet breaker).
    door_locks: bool = True
    # --- rule flags for documented-but-ambiguous behavior ---
    strict_door_matching: bool = False  # True: forbid doors facing occupied blank walls
    orientation_choice: bool = False    # True: player picks orientation; False: dealt orientation
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
    entrance_vase_broken: bool = False  # west vase smashed before: its microchip granted at day start
    outer_chip_dug: bool = False        # West Path chip dug up before: granted on reaching the doorstep
    # Room ids banned from the draft pool by the Repellent item.  Each
    # repellent use records a ban for 7 days; DayChain decrements the counters
    # on advance() and passes the survivors here.  Rooms in this set are excluded
    # from eligible_pool() in engine/decks.py.  The dict lives in DayChain and is
    # converted to a frozenset of active (days_left > 0) room ids for the config.
    banned_rooms: frozenset[str] = frozenset()
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

        Unknown keys raise KeyError; list-valued unlock fields are coerced to
        frozensets and data_dir to a Path.
        """
        kwargs = {}
        valid = {f.name for f in fields(cls)}
        for k, v in raw.items():
            if k not in valid:
                raise KeyError(f"Unknown config key: {k}")
            if k in ("studio_additions", "upgrade_disks", "satisfied_conditions",
                     "starting_items", "banned_rooms"):
                v = frozenset(v)
            elif k == "data_dir" and v is not None:
                v = Path(v)
            kwargs[k] = v
        return cls(**kwargs)
