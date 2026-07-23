"""Immutable room/data registry loaded from the committed JSON data files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .grid import N, E, S, W, rotate_mask

RARITIES = ("commonplace", "standard", "unusual", "rare")
RARITY_INDEX = {r: i for i, r in enumerate(RARITIES)}

# Canonical door masks per layout. The canonical orientation is arbitrary;
# rotations are enumerated at load time.
LAYOUT_MASKS = {
    "dead_end": S,
    "straight": N | S,
    "corner": S | E,
    "t": E | S | W,
    "cross": N | E | S | W,
}
LAYOUTS = tuple(LAYOUT_MASKS)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True, slots=True)
class Effect:
    tag: str
    params: tuple[tuple[str, object], ...] = ()

    def param(self, key: str, default=None):
        for k, v in self.params:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class ItemSpec:
    guaranteed: tuple[tuple[str, int], ...] = ()  # (item, count)
    additional_max: int = 0
    dig_spots: int = 0


@dataclass(frozen=True, slots=True)
class Room:
    idx: int  # dense index into Registry.rooms
    id: str
    name: str
    category: str  # blueprint|bedroom|hallway|green|shop|red|blackprint|studio_addition|outer|objective|tomorrow|mechanical
    rarity: str | None  # None = never appears in decks (Entrance Hall, forced-only rooms)
    gem_cost: int
    gem_cost_dynamic: str | None
    layout: str
    door_mask: int  # canonical orientation
    rotations: tuple[int, ...]  # distinct legal door masks
    draft_conditions: tuple[str, ...]
    no_library_draft: bool
    powered: bool
    duct: bool
    deck_copies: int
    effects: tuple[Effect, ...]
    items: ItemSpec
    pool: str  # base|studio_addition|outer|pool_temp|upgrade_variant|conditional|none
    variant_of: str | None = None  # base room id this upgrade variant replaces
    confidence: str = "wiki"

    @property
    def is_free(self) -> bool:
        return self.gem_cost == 0

    @property
    def rarity_idx(self) -> int:
        return RARITY_INDEX[self.rarity] if self.rarity else -1


def _parse_effects(raw: list[dict]) -> tuple[Effect, ...]:
    out = []
    for e in raw:
        params = tuple(sorted((k, v) for k, v in e.items() if k != "tag"))
        out.append(Effect(tag=e["tag"], params=params))
    return tuple(out)


def _parse_room(idx: int, raw: dict) -> Room:
    layout = raw["layout"]
    mask = LAYOUT_MASKS[layout]
    all_layouts = [layout, *raw.get("alt_layouts", [])]
    if raw.get("rotatable", True):
        rotations = tuple(sorted(
            {rotate_mask(LAYOUT_MASKS[lay], k) for lay in all_layouts for k in range(4)}))
    else:
        rotations = (mask,)
    gem = raw.get("gem_cost", 0)
    if isinstance(gem, dict):
        gem_base, gem_dyn = gem.get("base", 0), gem.get("dynamic")
    else:
        gem_base, gem_dyn = gem, None
    items = raw.get("items", {})
    return Room(
        idx=idx,
        id=raw["id"],
        name=raw["name"],
        category=raw["category"],
        rarity=raw.get("rarity"),
        gem_cost=gem_base,
        gem_cost_dynamic=gem_dyn,
        layout=layout,
        door_mask=mask,
        rotations=rotations,
        draft_conditions=tuple(raw.get("draft_conditions", [])),
        no_library_draft=bool(raw.get("flags", {}).get("no_library_draft", False)),
        powered=bool(raw.get("flags", {}).get("powered", False)),
        duct=bool(raw.get("flags", {}).get("duct", False)),
        deck_copies=int(raw.get("deck_copies", 1)),
        effects=_parse_effects(raw.get("effects", [])),
        items=ItemSpec(
            guaranteed=tuple((g["item"], g["count"]) for g in items.get("guaranteed", [])),
            additional_max=int(items.get("additional_max", 0)),
            dig_spots=int(items.get("dig_spots", 0)),
        ),
        pool=raw.get("pool", "base"),
        variant_of=raw.get("variant_of"),
        confidence=raw.get("meta", {}).get("confidence", "wiki"),
    )


@dataclass(frozen=True)
class Registry:
    rooms: tuple[Room, ...]
    by_id: dict[str, Room]
    weights: dict  # parsed weights.json
    priority: dict  # parsed priority_draws.json
    item_rules: dict  # parsed items.json
    lock_rules: dict  # parsed locks.json
    data_dir: Path = field(default=DEFAULT_DATA_DIR)

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Registry":
        d = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        rooms_raw = json.loads((d / "rooms.json").read_text())["rooms"]
        rooms = tuple(_parse_room(i, r) for i, r in enumerate(rooms_raw))
        return cls(
            rooms=rooms,
            by_id={r.id: r for r in rooms},
            weights=json.loads((d / "weights.json").read_text()),
            priority=json.loads((d / "priority_draws.json").read_text()),
            item_rules=json.loads((d / "items.json").read_text()),
            lock_rules=json.loads((d / "locks.json").read_text()),
            data_dir=d,
        )

    def weight_row(self, stage: str, solarium: bool, slot_class: str, rank: int) -> tuple[float, ...]:
        """Rarity weights (C, S, U, R) for one option slot.

        slot_class is "slot1" or "slot23". The Solarium override applies to
        slot23 only, regardless of stage.
        """
        if solarium and slot_class == "slot23":
            return tuple(self.weights["solarium_slot23"][str(rank)])
        return tuple(self.weights["tables"][stage][slot_class][str(rank)])

    def stage_for_day(self, day: int) -> str:
        b = self.weights["stage_day_boundaries"]
        if day <= b["week1_days"][1]:
            return "week1"
        if day <= b["week2_days"][1]:
            return "week2"
        return "late"
