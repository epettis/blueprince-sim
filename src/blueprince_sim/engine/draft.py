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
from .grid import N, OPPOSITE, rank_of
from .model import Registry, Room
from .placement import legal_orientations, satisfies_draft_conditions
from .rng import Rng
from .rotation import orientation_weights
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost

CLOSET_ID = "closet"
TUNNEL_ID = "tunnel"


def _hidden_count(from_room: Room | None) -> int:
    """Archives/Darkroom: drafting FROM it hides some (or all) floorplans.

    The room is still dealt and still draftable — it is shown face-down as a
    "mystery" option the player can select blind — so this counts how many of
    the dealt options to mark hidden, not how many to drop.

    The effect tag carries an optional ``amount`` param (default 1).  Archives
    omits it (→ 1 hidden); Darkroom sets amount=3 to hide all three options.
    """
    if from_room is None:
        return 0
    return sum(int(e.param("amount", 1)) for e in from_room.effects
               if e.tag == "reduce_draft_options")


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
                   exclude: set[int],
                   tunnel_chain: bool = False) -> bool:
    if room.idx in exclude:
        return False
    if room.id in ctx.placed_ids and "chamber_of_mirrors" not in ctx.placed_ids:
        # Allow a second (or third) Tunnel when it is force-dealt from a Tunnel's
        # north exit (tunnel_chain=True).  The duplicate-id check would otherwise
        # block the chain once the first Tunnel is on the grid.
        if not (tunnel_chain and room.id == TUNNEL_ID):
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


def _active_conditions(state) -> set[str]:
    """Return the category-bias condition tags that are currently satisfied."""
    conds: set[str] = set()
    if state.furnace_placed:
        conds.add("furnace_or_king")
    if state.greenhouse_placed:
        conds.add("greenhouse_or_king")
    return conds


def _deal_biased(ctx: DraftContext, slot: int, cell: int,
                 entry_dir: int, exclude: set[int],
                 pred) -> Room | None:
    """Deal the first card passing ``pred``, respecting slot 0 free-only rule."""
    rooms = ctx.registry.rooms
    if slot == 0:
        # Slot 0 is free-only: search only the free decks across all rarities.
        for rarity_idx in range(4):
            card = ctx.state.deck(rarity_idx, False).deal_next(pred)
            if card is not None:
                return rooms[card]
    else:
        # Slots 1/2 draw from the union of free+gem decks.
        for rarity_idx in range(4):
            for is_gem in (False, True):
                card = ctx.state.deck(rarity_idx, is_gem).deal_next(pred)
                if card is not None:
                    return rooms[card]
    return None


def _apply_category_bias(ctx: DraftContext, room: Room, slot: int, cell: int,
                         entry_dir: int, exclude: set[int]) -> Room:
    """After a normal draw, apply any active category biases.

    For each bias whose condition holds, roll its chance (via a dedicated named
    RNG substream that is only consumed when the bias is active).  On a hit,
    attempt to deal a room matching the target category/layout/flag from the
    remaining undealt cards.  If a matching room is found it replaces the
    original draw (the original stays consumed from its deck).  If no match is
    available the original draw is kept unchanged.
    """
    active = _active_conditions(ctx.state)
    if not active:
        return room

    rooms = ctx.registry.rooms

    for entry in ctx.registry.priority.get("category_biases", []):
        if entry.get("condition") not in active:
            continue
        if not ctx.rng.chance(f"cat_bias_{entry['label']}", entry["chance"]):
            continue

        target_cat = entry.get("category")
        target_layout = entry.get("layout")
        target_flag = entry.get("flag")
        target_room_ids = set(entry.get("rooms", []))

        def _pred(card: int,
                  _tc=target_cat, _tl=target_layout, _tf=target_flag,
                  _tr=target_room_ids) -> bool:
            r = rooms[card]
            if _tr and r.id not in _tr:
                return False
            if _tc and r.category != _tc:
                return False
            if _tl and r.layout != _tl:
                return False
            if _tf == "powered" and not r.powered:
                return False
            if _tf == "duct" and not r.duct:
                return False
            return room_draftable(ctx, r, cell, entry_dir, exclude)

        biased = _deal_biased(ctx, slot, cell, entry_dir, exclude, _pred)
        if biased is not None:
            room = biased

    return room


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
                room = _apply_category_bias(ctx, room, slot, cell, entry_dir, exclude)
                return _make_option(ctx, room, slot, cell, entry_dir)

    # Attempt 3: reshuffle every deck and retry once.
    for i, deck in enumerate(state.decks):
        deck.reshuffle(lambda lst, i=i: rng.shuffle(f"reshuffle_{i}", lst))
    rarity = roll_rarity(state, registry, cfg, rng, slot, rank)
    if rarity is not None:
        room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude)
        if room is not None:
            room = _apply_category_bias(ctx, room, slot, cell, entry_dir, exclude)
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
    if len(orientations) == 1:
        orientation = orientations[0]
    else:
        # A drawn floorplan is rolled into a legal orientation with datamined,
        # south-biased weights (the Ornate Compass flips the bias northward).
        weights = orientation_weights(orientations, OPPOSITE[entry_dir],
                                      ctx.state.day, ctx.cfg.compass)
        orientation = orientations[ctx.rng.roll_weighted("orientation", weights)]
    cost = 0 if slot == 0 else resolve_gem_cost(room, ctx.state, ctx.registry.rooms)
    return DraftOption(room_idx=room.idx, orientation=orientation, gem_cost=cost,
                       slot=slot, forced=forced_draw)


def _tunnel_chain_option(ctx: DraftContext, cell: int, entry_dir: int) -> DraftOption | None:
    """Return a forced Tunnel option when drafting north from a Tunnel cell.

    The Tunnel's chain-draft effect: opening the north door of a placed Tunnel
    always deals exactly ONE forced Tunnel option, provided the Tunnel is still
    legal at the target cell (rank_gte_2 / rank_lte_8 conditions + valid
    orientation).  No RNG is consumed: the orientation is always N|S (the
    Tunnel's only valid mask — a straight room drafted through a N doorway must
    be oriented N-S).

    Returns None if the Tunnel is illegal at the target (chain ends naturally).
    """
    tunnel = ctx.registry.by_id.get(TUNNEL_ID)
    if tunnel is None:
        return None
    # Check legality with tunnel_chain=True to allow duplicate placement.
    if not room_draftable(ctx, tunnel, cell, entry_dir, set(), tunnel_chain=True):
        return None
    # Tunnel is a straight room; the only valid N-S orientation is N|S (=5).
    # legal_orientations will confirm this — we trust it to stay N|S.
    orientations = legal_orientations(tunnel, cell, entry_dir, ctx.state, ctx.cfg)
    if not orientations:
        return None
    # There is only one legal orientation for a straight drafted northward (N|S).
    orientation = orientations[0]
    return DraftOption(room_idx=tunnel.idx, orientation=orientation, gem_cost=0,
                       slot=0, forced=True)


def _fill_options(ctx: DraftContext, pending: PendingDraft, from_room: Room | None) -> None:
    """Deal the three option slots, then mark mystery option(s) as hidden.

    Archives hides one option (always keeps option 0 visible).  Darkroom hides
    all three — every option is shown face-down.  A hidden option is still
    fully draftable; only its identity and orientation are concealed from the
    player (and from the RL observation).

    Tunnel chain: drafting north from a Tunnel always deals a single forced
    Tunnel option (if the Tunnel is legal at the target).  The normal three-slot
    deal is skipped entirely for the chain.  The chain ends naturally when the
    forced Tunnel is illegal at the target (rank 9 blocked by rank_lte_8, or the
    target is already occupied) — then the deal falls back to the normal pipeline.
    """
    # Tunnel chain-draft: north exit of a Tunnel forces another Tunnel.
    if (from_room is not None and from_room.id == TUNNEL_ID
            and pending.direction == N):
        opt = _tunnel_chain_option(ctx, pending.target_cell, pending.direction)
        if opt is not None:
            pending.options.append(opt)
            return  # chain active: skip the normal three-slot deal

    exclude: set[int] = set()
    for slot in range(3):
        opt = draw_slot(ctx, slot, pending.target_cell, pending.direction, exclude)
        if opt is not None:
            pending.options.append(opt)
            exclude.add(opt.room_idx)
    hidden = _hidden_count(from_room)
    if hidden:
        n = len(pending.options)
        # hide_all: Darkroom hides every option (hidden >= n).
        # Otherwise keep at least option[0] visible so there's always an
        # identifiable, affordable choice (Archives semantics).
        start = 0 if hidden >= n else max(1, n - hidden)
        for opt in pending.options[start:]:
            opt.hidden = True


def deal_draft(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
               placed_ids: set[str], from_cell: int, direction: int,
               target_cell: int) -> PendingDraft:
    from_room = registry.rooms[state.grid[from_cell]] if state.grid[from_cell] >= 0 else None
    from_library = from_room is not None and from_room.id == "library"
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_library)
    pending = PendingDraft(from_cell=from_cell, direction=direction, target_cell=target_cell)
    _fill_options(ctx, pending, from_room)
    return pending


def redeal(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
           placed_ids: set[str], pending: PendingDraft) -> None:
    """Redraw all three options in place (Study / Classroom / dice redraw)."""
    from_room = registry.rooms[state.grid[pending.from_cell]] \
        if state.grid[pending.from_cell] >= 0 else None
    from_library = from_room is not None and from_room.id == "library"
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_library)
    pending.options.clear()
    pending.rotations_used = 0  # fresh hand, fresh rotation budget
    _fill_options(ctx, pending, from_room)
