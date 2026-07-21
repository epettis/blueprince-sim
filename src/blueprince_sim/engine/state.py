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

    order: list[int] = field(default_factory=list)
    pos: int = 0

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
    room_idx: int
    orientation: int       # door mask as dealt
    gem_cost: int          # resolved cost (dynamic costs evaluated at deal time)
    slot: int              # 0..2
    forced: bool = False   # placed by a priority/forced draw


@dataclass(slots=True)
class PendingDraft:
    from_cell: int
    direction: int         # door direction opened (N/E/S/W bit)
    target_cell: int
    options: list[DraftOption] = field(default_factory=list)
    study_redraws_used: int = 0
    redraws_left: int = 0  # free redraws (Classroom etc.)


@dataclass(slots=True)
class GameState:
    # grid: -1 empty, else room idx; placed_doors: effective door mask of placed room
    grid: list[int] = field(default_factory=lambda: [-1] * 45)
    placed_doors: list[int] = field(default_factory=lambda: [0] * 45)
    opened: list[int] = field(default_factory=lambda: [0] * 45)  # mask of used doorways per cell
    entered: list[bool] = field(default_factory=lambda: [False] * 45)
    pos: int = 2  # player cell (entrance)

    steps: int = 50
    gems: int = 0
    keys: int = 0
    coins: int = 0
    dice: int = 0
    luck: int = 10

    day: int = 20
    stage: str = "late"

    # decks: index = rarity_idx * 2 + (0 free | 1 gem)
    decks: list[DeckState] = field(default_factory=list)

    # cached house-effect flags (recomputed on placement)
    solarium_placed: bool = False
    greenhouse_placed: bool = False
    drafting_room_count: int = 0
    study_placed: bool = False
    library_placed: bool = False

    pending: PendingDraft | None = None
    outer_room_drafted: bool = False
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
