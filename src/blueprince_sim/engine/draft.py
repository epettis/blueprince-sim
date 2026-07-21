"""The drafting algorithm.

Implements the datamined procedure: for each of the 3 option slots -
(1) roll a rarity from the weight table (rank x slot x stage x Solarium),
(2) deal a room of that rarity solitaire-style from the free deck (slot 1)
or the union of free+gem decks (slots 2 & 3), subject to the doorway's
filters. Four attempts per slot: full rules -> ignore priority filters ->
reshuffle decks -> forced Closet. Priority draws can force specific rooms
into slot 3.
"""

from __future__ import annotations

from ..config import GameConfig
from .decks import roll_rarity
from .grid import rank_of
from .model import Registry, Room
from .placement import legal_orientations, satisfies_draft_conditions
from .rng import Rng
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost

CLOSET_ID = "closet"


def _from_room_option_penalty(from_room: Room | None) -> int:
    """Archives: drafting FROM it hides one of the three floorplans."""
    if from_room is None:
        return 0
    return sum(1 for e in from_room.effects if e.tag == "reduce_draft_options")


class DraftContext:
    """Bundles the per-draft references so helpers stay signature-light."""

    __slots__ = ("state", "registry", "cfg", "rng", "placed_ids", "from_library")

    def __init__(self, state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
                 placed_ids: set[str], from_library: bool) -> None:
        self.state = state
        self.registry = registry
        self.cfg = cfg
        self.rng = rng
        self.placed_ids = placed_ids
        self.from_library = from_library


def room_draftable(ctx: DraftContext, room: Room, cell: int, entry_dir: int,
                   exclude: set[int]) -> bool:
    if room.idx in exclude:
        return False
    if room.id in ctx.placed_ids and "chamber_of_mirrors" not in ctx.placed_ids:
        return False  # one copy of a room on the grid at a time
    if not satisfies_draft_conditions(room, cell, entry_dir, ctx.state, ctx.cfg,
                                      ctx.placed_ids, ctx.from_library):
        return False
    if not legal_orientations(room, cell, entry_dir, ctx.state, ctx.cfg):
        return False
    return True


def _deal_from_rarity(ctx: DraftContext, rarity_idx: int, slot: int, cell: int,
                      entry_dir: int, exclude: set[int]) -> Room | None:
    """Deal the next eligible room of a rarity (solitaire semantics)."""
    rooms = ctx.registry.rooms

    def pred(card: int) -> bool:
        return room_draftable(ctx, rooms[card], cell, entry_dir, exclude)

    decks = [ctx.state.deck(rarity_idx, False)]
    if slot != 0:
        decks.append(ctx.state.deck(rarity_idx, True))
        # Deal from whichever deck has proportionally more undealt cards so the
        # union behaves like one combined deck.
        decks.sort(key=lambda d: -d.remaining())
    for deck in decks:
        card = deck.deal_next(pred)
        if card is not None:
            return rooms[card]
    return None


def _priority_draw(ctx: DraftContext, cell: int, entry_dir: int,
                   exclude: set[int]) -> Room | None:
    """Roll the slot-3 priority draws (Patio group, Commissary/Observatory, Classroom)."""
    pool_ids = {ctx.registry.rooms[c].id
                for d in ctx.state.decks for c in d.order}
    for entry in ctx.registry.priority["priority_draws"]:
        chance = entry["chance"]
        if ctx.state.greenhouse_placed and "chance_with_greenhouse" in entry:
            chance = entry["chance_with_greenhouse"]
        if not ctx.rng.chance(f"priority_{entry['label']}", chance):
            continue
        candidates = [rid for rid in entry["rooms"]
                      if rid in pool_ids or rid in ctx.registry.by_id and
                      ctx.registry.by_id[rid].pool == "base"]
        for rid in candidates:
            room = ctx.registry.by_id.get(rid)
            if room is not None and room.rarity is not None and \
                    room_draftable(ctx, room, cell, entry_dir, exclude):
                return room
    return None


def draw_slot(ctx: DraftContext, slot: int, cell: int, entry_dir: int,
              exclude: set[int]) -> DraftOption | None:
    """Fill one option slot via the four-attempt procedure."""
    state, registry, cfg, rng = ctx.state, ctx.registry, ctx.cfg, ctx.rng
    rank = rank_of(cell)

    # Priority draws force specific rooms into slot 3 (attempt-1 rules only).
    if slot == 2:
        forced = _priority_draw(ctx, cell, entry_dir, exclude)
        if forced is not None:
            return _make_option(ctx, forced, slot, cell, entry_dir, forced_draw=True)

    # Attempts 1 & 2 (identical here once the priority filter has run above).
    for _attempt in (1, 2):
        rarity = roll_rarity(state, registry, cfg, rng, slot, rank)
        if rarity is not None:
            room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude)
            if room is not None:
                return _make_option(ctx, room, slot, cell, entry_dir)

    # Attempt 3: reshuffle every deck and retry once.
    for i, deck in enumerate(state.decks):
        deck.reshuffle(lambda lst, i=i: rng.shuffle(f"reshuffle_{i}", lst))
    rarity = roll_rarity(state, registry, cfg, rng, slot, rank)
    if rarity is not None:
        room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude)
        if room is not None:
            return _make_option(ctx, room, slot, cell, entry_dir)

    # Attempt 4: forced Closet - cannot fail (Closet is a free commonplace
    # dead end, so it always has a legal orientation).
    closet = registry.by_id.get(CLOSET_ID)
    if closet is not None and closet.idx not in exclude:
        return _make_option(ctx, closet, slot, cell, entry_dir, forced_draw=True)
    return None


def _make_option(ctx: DraftContext, room: Room, slot: int, cell: int, entry_dir: int,
                 forced_draw: bool = False) -> DraftOption:
    orientations = legal_orientations(room, cell, entry_dir, ctx.state, ctx.cfg)
    if not orientations:  # forced Closet fallback path
        orientations = [room.door_mask]
    orientation = orientations[0] if len(orientations) == 1 else \
        ctx.rng.choice("orientation", orientations)
    cost = 0 if slot == 0 else resolve_gem_cost(room, ctx.state, ctx.registry.rooms)
    return DraftOption(room_idx=room.idx, orientation=orientation, gem_cost=cost,
                       slot=slot, forced=forced_draw)


def deal_draft(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
               placed_ids: set[str], from_cell: int, direction: int,
               target_cell: int) -> PendingDraft:
    from_room = registry.rooms[state.grid[from_cell]] if state.grid[from_cell] >= 0 else None
    from_library = from_room is not None and from_room.id == "library"
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_library)

    pending = PendingDraft(from_cell=from_cell, direction=direction, target_cell=target_cell)
    exclude: set[int] = set()
    n_slots = max(1, 3 - _from_room_option_penalty(from_room))
    for slot in range(n_slots):
        opt = draw_slot(ctx, slot, target_cell, direction, exclude)
        if opt is not None:
            pending.options.append(opt)
            exclude.add(opt.room_idx)
    return pending


def redeal(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
           placed_ids: set[str], pending: PendingDraft) -> None:
    """Redraw all three options in place (Study / Classroom / dice redraw)."""
    from_room = registry.rooms[state.grid[pending.from_cell]] \
        if state.grid[pending.from_cell] >= 0 else None
    from_library = from_room is not None and from_room.id == "library"
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_library)
    pending.options.clear()
    exclude: set[int] = set()
    n_slots = max(1, 3 - _from_room_option_penalty(from_room))
    for slot in range(n_slots):
        opt = draw_slot(ctx, slot, pending.target_cell, pending.direction, exclude)
        if opt is not None:
            pending.options.append(opt)
            exclude.add(opt.room_idx)
