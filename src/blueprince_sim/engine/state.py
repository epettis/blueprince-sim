"""Mutable per-episode state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Room


@dataclass(slots=True)
class DeckState:
    """One solitaire deck: a shuffled list of room indices dealt from a cursor.

    Cards before ``pos`` have been dealt this cycle. ``deal_next`` scans from
    ``pos`` for the first card passing a predicate, swaps it to ``pos`` and
    advances, so no card repeats until the deck depletes and is reshuffled.
    """

    order: list[int] = field(default_factory=list)  # shuffled cards; each is a Room.idx
    pos: int = 0  # deal cursor: cards before pos are already dealt this cycle

    def remaining(self) -> int:
        return len(self.order) - self.pos

    def size(self) -> int:
        return len(self.order)

    def deal_next(self, predicate) -> int | None:
        for i in range(self.pos, len(self.order)):
            card = self.order[i]
            if predicate(card):
                self.order[i] = self.order[self.pos]
                self.order[self.pos] = card
                self.pos += 1
                return card
        return None

    def reshuffle(self, shuffler, drop: set[int] | None = None) -> None:
        if drop:
            self.order = [c for c in self.order if c not in drop]
        shuffler(self.order)
        self.pos = 0

    def add_copies(self, room_idx: int, n: int, shuffler) -> None:
        self.order.extend([room_idx] * n)
        shuffler(self.order)
        self.pos = 0


@dataclass(slots=True)
class DraftOption:
    room_idx: int          # index into Registry.rooms
    orientation: int       # door mask as dealt
    gem_cost: int          # resolved cost (dynamic costs evaluated at deal time)
    slot: int              # 0..2
    forced: bool = False   # placed by a priority/forced draw
    hidden: bool = False   # Archives: face-down "mystery" room, still draftable


@dataclass(slots=True)
class PendingDraft:
    from_cell: int         # cell whose doorway was opened
    direction: int         # door direction opened (N/E/S/W bit)
    target_cell: int       # empty cell the drafted room will occupy
    options: list[DraftOption] = field(default_factory=list)  # dealt hand, one entry per slot
    study_redraws_used: int = 0  # Study redraws bought with gems on this hand (max 8)
    redraws_left: int = 0  # free redraws (Classroom etc.)
    rotations_used: int = 0  # free rotations spent on this hand (see Game.rotation_available)


@dataclass(slots=True)
class GameState:
    # grid: -1 empty, else room idx; placed_doors: effective door mask of placed room
    grid: list[int] = field(default_factory=lambda: [-1] * 45)
    placed_doors: list[int] = field(default_factory=lambda: [0] * 45)
    opened: list[int] = field(default_factory=lambda: [0] * 45)  # mask of used doorways per cell
    # True once the player stepped into the cell (ON_ENTER effects/items fire only then)
    entered: list[bool] = field(default_factory=lambda: [False] * 45)
    pos: int = 2  # player cell (entrance)

    steps: int = 50  # step budget left today (moving costs steps; day ends at 0)
    gems: int = 0  # spent to draft gem-cost rooms and on Study redraws
    keys: int = 0  # spendable keys; opening a locked door costs one
    coins: int = 0  # money from coin piles etc.; only feeds resource_value (shops not modeled)
    dice: int = 0  # redraw dice: spend one to redraw the current draft hand
    luck: int = 10  # scales bonus-item odds between items.json floor and max_effect_at

    day: int = 20  # in-game day, copied from GameConfig at reset
    stage: str = "late"  # rarity-table stage (week1|week2|late) resolved from day

    # decks: index = rarity_idx * 2 + (0 free | 1 gem)
    decks: list[DeckState] = field(default_factory=list)

    # cached house-effect flags (recomputed on placement)
    solarium_placed: bool = False  # Solarium: swaps in the special slot-2/3 rarity table
    greenhouse_placed: bool = False  # Greenhouse: green-room bias, boosts some priority draws
    furnace_placed: bool = False  # Furnace: red-room category bias on draws
    drafting_room_count: int = 0  # grants that many free redraws when drafting from the Classroom
    study_placed: bool = False  # Study: pay 1 gem to redraw (max 8 per hand)
    library_placed: bool = False  # Library in the house (obs flag; Library draws key off position)

    # --- door locks & security doors (see engine.locks) ---
    # segment (locks.segment_key) -> DOOR_LOCKED/DOOR_SECURITY; DOOR_OPEN
    # entries mark rolled-or-opened segments, missing means never rolled
    # (freely passable). Mutate via Game helpers so door_version is bumped.
    door_state: dict[tuple[int, int], int] = field(default_factory=dict)
    door_version: int = 0  # cache stamp for the navigation maps
    lock_bias: float = 1.0  # daily lock-chance multiplier (locks.json "bias")
    # security doors rolled so far today (capped by locks.json spawn_limit per security level)
    security_doors_spawned: int = 0
    security_level: str = "normal"    # low|normal|high (Security terminal)
    keycard_power_on: bool = True     # Utility Closet breaker, "Keycard Entry"
    offline_unlocked: bool = False    # Security terminal offline mode (set on visit)
    has_keycard: bool = False         # Keycard held: opens security doors while power is on

    pending: PendingDraft | None = None  # in-flight draft hand; None outside the drafting phase
    outer_room_drafted: bool = False  # today's single outer-room draft has been used
    outer_loc: int = 0           # 0=on grid, 1=at doorstep, 2=inside outer room
    outer_room_entered: bool = False  # True once ON_ENTER has fired for today's outer room
    # chronological (item id, count) pickups this run, for CLI/replay reporting
    items_found_log: list[tuple[str, int]] = field(default_factory=list)

    def deck(self, rarity_idx: int, is_gem: bool) -> DeckState:
        return self.decks[rarity_idx * 2 + (1 if is_gem else 0)]

    def resource_value(self, values: dict) -> float:
        return (
            self.keys * values.get("key", 3.0)
            + self.gems * values.get("gem", 3.0)
            + self.coins * values.get("coin", 1.0)
            + self.dice * values.get("die", 4.0)
            + self.steps * values.get("step", 0.5)
        )


def resolve_gem_cost(room: Room, state: GameState, registry_rooms) -> int:
    """Resolve a room's gem cost, evaluating dynamic modifiers."""
    cost = room.gem_cost
    if room.gem_cost_dynamic == "plus_one_per_bedroom":
        n_bedrooms = sum(
            1 for idx in state.grid if idx >= 0 and registry_rooms[idx].category == "bedroom"
        )
        cost += n_bedrooms
    return cost
