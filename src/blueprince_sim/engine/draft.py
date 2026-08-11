"""The drafting algorithm.

Implements the datamined procedure: for each of the 3 option slots -
(1) roll a rarity from the weight table (rank x slot x stage x Solarium),
(2) deal a room of that rarity solitaire-style from the free deck (slot 1)
or the union of free+gem decks (slots 2 & 3), subject to the doorway's
filters. Four attempts per slot: full rules -> ignore priority filters ->
reshuffle decks -> forced Closet. Priority draws can force specific rooms
into slot 3.

The Mechanarium is a special case handled entirely in this module (see
_mechanarium_orientation): its door mask is derived from the number of
placed Mechanical rooms rather than rolled, so it never consumes an
"orientation" RNG draw.

Not modelled: Mechanical rooms beyond the four cardinal doors are meant to
open diagonal compartments with key/item caches (wiki); that mechanic is out
of scope here.
"""

from __future__ import annotations

from ..config import GameConfig
from .decks import roll_rarity
from .grid import N, OPPOSITE, neighbor, rank_of, rotate_mask
from .model import Registry, Room
from .placement import legal_orientations, satisfies_draft_conditions
from .rng import Rng
from .rotation import orientation_weights
from .special_items import compass_active_from_state
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost

CLOSET_ID = "closet"
TUNNEL_ID = "tunnel"
READING_NOOK_ID = "reading_nook__ix99"
LIBRARY_ID = "library"
MECHANARIUM_ID = "mechanarium"


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

    __slots__ = ("state", "registry", "cfg", "rng", "placed_ids", "from_room", "from_library")

    def __init__(self, state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
                 placed_ids: set[str], from_room: Room | None) -> None:
        self.state = state
        self.registry = registry
        self.cfg = cfg
        self.rng = rng
        self.placed_ids = placed_ids
        self.from_room = from_room  # room being drafted FROM, or None (positional condition source)
        self.from_library = from_room is not None and from_room.id == "library"


def room_draftable(ctx: DraftContext, room: Room, cell: int, entry_dir: int,
                   exclude: set[int],
                   tunnel_chain: bool = False) -> bool:
    """Full eligibility check for dealing ``room`` at the target doorway.

    Combines the one-copy-on-the-grid rule (waived entirely while the Chamber
    of Mirrors is placed, and for Tunnels dealt via the chain), the room's
    draft conditions, and door-geometry legality. ``exclude`` holds room
    indices already dealt into earlier slots of this hand.
    """
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


def _garage_dead_end_gate(ctx: DraftContext, earlier_options: list[DraftOption]) -> bool:
    """Wiki gate: "the first two slots are not both a Dead End, or Slot 2 was not
    drawn by a normal draw" (1-indexed wiki Slot 2 = this engine's slot index 1).

    Reading: the Forced Draw attempt is blocked only when BOTH (a) slots 0 and 1
    are both Dead End rooms AND (b) slot index 1 was placed by a normal roll-based
    draw. "Normal draw" is read here as ``DraftOption.forced is False`` -- forced
    marks priority draws, the Tunnel chain guarantee, and the forced-Closet
    fallback, all of which bypassed the rarity lottery; a category-bias
    substitution is still treated as normal since it re-deals the same
    rarity-rolled slot rather than forcing a placement. If either slot hasn't
    been dealt yet (a rare failure path), "both Dead End" is trivially false and
    the gate passes.
    """
    if len(earlier_options) < 2:
        return True
    rooms = ctx.registry.rooms
    slot0_room = rooms[earlier_options[0].room_idx]
    slot1_room = rooms[earlier_options[1].room_idx]
    both_dead_end = slot0_room.layout == "dead_end" and slot1_room.layout == "dead_end"
    slot1_normal = not earlier_options[1].forced
    return not (both_dead_end and slot1_normal)


def _forced_draw_garage(ctx: DraftContext, cell: int, entry_dir: int, exclude: set[int],
                        earlier_options: list[DraftOption]) -> Room | None:
    """Roll the Garage's once-per-day Forced Draw into slot 3 (data/priority_draws.json
    "forced_draws"; blueprince.wiki.gg/wiki/Garage).

    Distinct from :func:`_priority_draw`: this targets one specific room's own
    draft conditions (not a named group), is gated on Veteran Mode/Day 3 and the
    slot-0/1 Dead-End clause, and can succeed (permanently disabling itself for
    today) even when the resulting placement then fails because the Garage
    already occupies an earlier slot of this same hand.
    """
    state, cfg = ctx.state, ctx.cfg
    if state.garage_forced_draw_succeeded:
        return None
    if not (cfg.veteran_mode or state.day >= 3):
        return None
    entry = next((e for e in ctx.registry.priority.get("forced_draws", [])
                  if e["room"] == "garage"), None)
    garage = ctx.registry.by_id.get("garage")
    if entry is None or garage is None:
        return None
    if not _garage_dead_end_gate(ctx, earlier_options):
        return None
    # "Spawning requirements met": the Garage's own draft conditions/geometry at
    # this doorway, ignoring same-hand dedup (exclude=set()) -- the wiki says the
    # roll still tries even if the Garage already occupies an earlier slot of
    # this hand; only the eventual placement fails in that case (checked below,
    # after the roll, against the caller's real `exclude`).
    if not room_draftable(ctx, garage, cell, entry_dir, set()):
        return None
    west_gate = cfg.west_gate_unlatched or state.west_gate_unlatched
    chance = entry["chance_with_west_gate"] if west_gate else entry["chance"]
    if not ctx.rng.chance(f"forced_draw_{entry['label']}", chance):
        return None
    # The roll has succeeded: no more Forced Draw attempts for the Garage today,
    # regardless of whether the placement below actually goes through.
    state.garage_forced_draw_succeeded = True
    if garage.idx in exclude:
        return None  # already dealt into an earlier slot this hand: draw fails regardless
    return garage


def _active_conditions(ctx: DraftContext) -> set[str]:
    """Return the category-bias condition tags that are currently satisfied.

    Most conditions are global (read off ``GameState``); a few are positional,
    keyed on the room being drafted FROM (``ctx.from_room``), which is why this
    takes the whole context rather than just ``state``.
    """
    state = ctx.state
    conds: set[str] = set()
    if state.furnace_placed:
        conds.add("furnace_or_king")
    if state.greenhouse_placed:
        conds.add("greenhouse_or_king")
    # Royal Scepter: once a color is activated, inject the scepter_<color> condition
    # so _apply_category_bias picks up the corresponding priority_draws.json entry.
    if state.shops.scepter_color is not None:
        conds.add(f"scepter_{state.shops.scepter_color}")
    if state.schoolhouse_placed:
        conds.add("schoolhouse")
    if state.southern_cross_active:
        conds.add("southern_cross_constellation")
    if state.draxus_active:
        conds.add("draxus_constellation")
    # King's Chess Piece (Banner of the King) is deliberately NOT emitted here: no
    # source models how the Banner is obtained or a per-day color pick, and the five
    # king_* tags must fire one at a time (mirroring scepter_<color>), never all at
    # once. See priority_draws.json's king_* entries for the shaped-but-inert tags.
    if ctx.from_library:
        conds.add("drafting_from_library")
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


def _deal_cross_t_biased(ctx: DraftContext, slot: int, cell: int,
                         entry_dir: int, exclude: set[int]) -> DraftOption | None:
    """Try to deal a cross/t-layout room for the Silver Key draft bias.

    Returns a DraftOption or None if no cross/t card qualifies; the caller
    then falls back to the normal draw. Silver Key wiki: biases toward cross/t
    layouts; straight/L is the fallback (modeled assumption).
    """
    rooms = ctx.registry.rooms

    def pred_cross_t(card: int) -> bool:
        r = rooms[card]
        return r.layout in ("cross", "t") and room_draftable(ctx, r, cell, entry_dir, exclude)

    room = _deal_biased(ctx, slot, cell, entry_dir, exclude, pred_cross_t)
    if room is None:
        return None
    return _make_option(ctx, room, slot, cell, entry_dir)


def _apply_category_bias(ctx: DraftContext, room: Room, slot: int, cell: int,
                         entry_dir: int, exclude: set[int]) -> Room:
    """After a normal draw, apply any active category biases.

    For each bias whose condition holds, roll its chance (via a dedicated named
    RNG substream that is only consumed when the bias is active).  On a hit,
    attempt to deal a room matching the target category/layout/flag from the
    remaining undealt cards.  If a matching room is found it replaces the
    original draw (the original stays consumed from its deck).  If no match is
    available the original draw is kept unchanged.

    A target category is a colour identity check (Furnace/Greenhouse/King's
    Chess Piece/Royal Scepter all bias toward drafting a room of that colour),
    so it goes through ``Room.is_category`` and can match a multi-category
    room such as the Aquarium or Maid's Chamber on any colour it counts as.

    An entry can also carry ``exclude_rooms`` (specific ids to leave out) and
    ``exclude_upgrade_variants`` (drop every room with a ``variant_of``, the
    direct link an upgrade variant carries to the base room it replaces) —
    the Southern Cross's 4-way bias needs both to match the wiki's own query.
    """
    active = _active_conditions(ctx)
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
        exclude_room_ids = set(entry.get("exclude_rooms", []))
        exclude_upgrade_variants = entry.get("exclude_upgrade_variants", False)

        def _pred(card: int,
                  _tc=target_cat, _tl=target_layout, _tf=target_flag,
                  _tr=target_room_ids, _xr=exclude_room_ids,
                  _xu=exclude_upgrade_variants) -> bool:
            r = rooms[card]
            if _tr and r.id not in _tr:
                return False
            if _xr and r.id in _xr:
                return False
            if _xu and r.variant_of is not None:
                return False
            if _tc and not r.is_category(_tc):
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
              exclude: set[int], earlier_options: list[DraftOption] = ()) -> DraftOption | None:
    """Fill one option slot via the four-attempt procedure.

    ``earlier_options`` holds the already-dealt slot-0/1 options of this hand
    (only meaningful, and only passed, at ``slot == 2``); it feeds the Garage
    Forced Draw's Dead-End gate.
    """
    state, registry, cfg, rng = ctx.state, ctx.registry, ctx.cfg, ctx.rng
    rank = rank_of(cell)

    # Forced draws push one specific room into slot 3 with a very high chance,
    # ahead of the named-group priority draws below (see _forced_draw_garage).
    if slot == 2:
        forced = _forced_draw_garage(ctx, cell, entry_dir, exclude, list(earlier_options))
        if forced is not None:
            return _make_option(ctx, forced, slot, cell, entry_dir, forced_draw=True)

    # Priority draws force specific rooms into slot 3 (attempt-1 rules only).
    if slot == 2:
        forced = _priority_draw(ctx, cell, entry_dir, exclude)
        if forced is not None:
            return _make_option(ctx, forced, slot, cell, entry_dir, forced_draw=True)

    # Attempts 1 & 2 (identical here once the priority filter has run above).
    for _attempt in (1, 2):
        rarity = roll_rarity(state, registry, cfg, rng, slot, rank, ctx.from_library)
        if rarity is not None:
            room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude)
            if room is not None:
                room = _apply_category_bias(ctx, room, slot, cell, entry_dir, exclude)
                return _make_option(ctx, room, slot, cell, entry_dir)

    # Attempt 3: reshuffle every deck and retry once.
    for i, deck in enumerate(state.decks):
        deck.reshuffle(lambda lst, i=i: rng.shuffle(f"reshuffle_{i}", lst))
    rarity = roll_rarity(state, registry, cfg, rng, slot, rank, ctx.from_library)
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


def _mechanarium_orientation(ctx: DraftContext, cell: int, entry_dir: int) -> int:
    """Derive the Mechanarium's door mask at draft time -- never rolled.

    Wiki (blueprince.wiki.gg/wiki/Mechanarium): "it contains one doorway per
    Mechanical room in the estate, including the Mechanarium itself. The
    first door is always the one that the Mechanarium is drafted from... The
    next doors that spawn are forward, left and right drafting doors that
    lead into open space. If a Mechanarium doorway would lead in an existing
    room... If that room has no door at that position... the Mechanarium
    skips that doorway and tries again at the next position." The count and
    orientation are "set in stone the moment it is drafted" -- later
    Mechanical-room drafts never add doors to an already-placed Mechanarium.

    ``entry_dir`` is the direction the player moved to reach ``cell`` (see
    grid.py), so "forward" continues that same direction; "left"/"right" are
    its counterclockwise/clockwise quarter turns under this grid's N/E/S/W
    bit convention (rotate_mask's quarter-turn direction).

    A skipped candidate (an occupied neighbour with no facing door) does not
    consume its slot -- the next candidate direction gets the door instead
    (owner ruling). An empty neighbour, or one with a facing door, is fine.
    Capped at the four cardinal directions; surplus Mechanical rooms are
    meant to open diagonal compartments, not modelled here (see module
    docstring).
    """
    rooms = ctx.registry.rooms
    mechanical_rooms = sum(
        1 for idx in ctx.state.grid if idx >= 0 and rooms[idx].is_category("mechanical"))
    # n = mechanical_rooms + 1 (this Mechanarium, not yet placed); the back door
    # already accounts for one of the n doors, so n - 1 remain to be tried below,
    # capped at 3 (forward/left/right -- the fourth and last cardinal direction).
    doors_left = min(mechanical_rooms, 3)
    back = OPPOSITE[entry_dir]
    mask = back
    forward = entry_dir
    right = rotate_mask(entry_dir, 1)
    left = rotate_mask(entry_dir, 3)
    for d in (forward, left, right):
        if doors_left <= 0:
            break
        nb = neighbor(cell, d)
        if nb == -1:
            continue  # never a door; unreachable under interior_only, kept defensively
        if ctx.state.grid[nb] != -1 and not ctx.state.placed_doors[nb] & OPPOSITE[d]:
            continue  # occupied neighbour has no facing door: skip without consuming the slot
        mask |= d
        doors_left -= 1
    return mask


def _make_option(ctx: DraftContext, room: Room, slot: int, cell: int, entry_dir: int,
                 forced_draw: bool = False) -> DraftOption:
    """Build the DraftOption for a dealt room, rolling its floorplan orientation.

    A single legal orientation is taken as-is; otherwise the datamined
    south-biased roll picks one. Slot 0 is always free; other slots carry the
    room's resolved gem cost. ``forced_draw`` marks priority-draw, forced-
    Closet, and Tunnel-chain deals. The Mechanarium's mask is derived instead
    (see _mechanarium_orientation) and consumes no "orientation" RNG draw.
    """
    if room.id == MECHANARIUM_ID:
        orientation = _mechanarium_orientation(ctx, cell, entry_dir)
    else:
        orientations = legal_orientations(room, cell, entry_dir, ctx.state, ctx.cfg)
        if not orientations:  # forced Closet fallback path
            orientations = [room.door_mask]
        if len(orientations) == 1:
            orientation = orientations[0]
        else:
            # A drawn floorplan is rolled into a legal orientation with datamined,
            # south-biased weights (the Ornate Compass flips the bias northward).
            weights = orientation_weights(orientations, OPPOSITE[entry_dir],
                                          ctx.state.day,
                                          compass_active_from_state(
                                              ctx.state, ctx.registry, ctx.cfg))
            orientation = orientations[ctx.rng.roll_weighted("orientation", weights)]
    cost = 0 if slot == 0 else resolve_gem_cost(room, ctx.state, ctx.registry.rooms)
    return DraftOption(room_idx=room.idx, orientation=orientation, gem_cost=cost,
                       slot=slot, forced=forced_draw)


def _tunnel_chain_option(ctx: DraftContext, cell: int, entry_dir: int) -> DraftOption | None:
    """Return the guaranteed slot-0 Tunnel option for drafting north from a Tunnel cell.

    The Tunnel's chain-draft effect: opening the north door of a placed Tunnel
    guarantees a Tunnel in slot 0 of the normal three-slot hand (see
    ``_fill_options``), provided the Tunnel is still legal at the target cell
    (rank_gte_2 / rank_lte_8 conditions + valid orientation).  This helper
    itself consumes no RNG: the orientation is always N|S (the Tunnel's only
    valid mask — a straight room drafted through a N doorway must be oriented
    N-S).

    Returns None if the Tunnel is illegal at the target (chain ends naturally,
    and the caller deals slot 0 normally instead).
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


def _reading_nook_library_option(ctx: DraftContext, cell: int, entry_dir: int) -> DraftOption:
    """Force LIBRARY into slot 2 for a hand dealt from the Reading Nook's own doorway.

    "the floorplan in the third slot will always be the Library. This happens
    even if floorplans are redrawn; even if the Library is no longer in the
    draft pool due to being drafted elsewhere; even when using Silver Key or
    Prism Key; and even if it has been removed entirely via Repellent."
    (blueprince.wiki.gg/wiki/Nook/Upgrades)

    A Library card is still pulled from its own rarity's decks when one
    remains -- "drafting the Library this way will still pull it from the
    draft pool" -- but the option itself is built unconditionally through
    _make_option's forced-orientation fallback, so an empty deck (or a
    Repellent ban, which only ever affects deck membership) never breaks the
    guarantee.
    """
    library = ctx.registry.by_id[LIBRARY_ID]
    for is_gem in (False, True):
        deck = ctx.state.deck(library.rarity_idx, is_gem)
        if deck.deal_next(lambda c: c == library.idx) is not None:
            break
    return _make_option(ctx, library, 2, cell, entry_dir, forced_draw=True)


def _fill_options(ctx: DraftContext, pending: PendingDraft, from_room: Room | None) -> None:
    """Deal the three option slots, then mark mystery option(s) as hidden.

    Archives hides one option (always keeps option 0 visible).  Darkroom hides
    all three — every option is shown face-down.  A hidden option is still
    fully draftable; only its identity and orientation are concealed from the
    player (and from the RL observation).

    Tunnel chain: drafting north from a placed Tunnel deals a normal
    three-slot hand with slot 0 guaranteed to be a Tunnel — the wiki
    (blueprince.wiki.gg/wiki/Drafting/Advanced) states "When drafting from a
    Tunnel, a Tunnel is drawn into Slot 1", and its 1-indexed Slot 1 is this
    engine's slot 0 (confirmed by the same page's "Slot 1 always makes a Free
    Draw", matching slot 0's existing free-only convention here). Slots 1 and
    2 are dealt through the ordinary pipeline and cannot re-deal a second
    Tunnel (its index is pre-excluded). The guaranteed Tunnel is marked
    ``forced`` — like a priority draw, it bypassed the rarity lottery even
    though (like a priority draw) it sits alongside two ordinarily-dealt
    options; it is a real, choosable slot, not a sole non-choice. The chain
    ends naturally when the Tunnel is illegal at the target (rank 9 blocked by
    rank_lte_8, or the target already occupied) — slot 0 then falls back to an
    ordinary draw, so the hand is three ordinary options with no Tunnel.

    Reading Nook: slot 2 is always LIBRARY when ``from_room`` is
    reading_nook__ix99 (see _reading_nook_library_option), on both the
    initial deal and every redraw (redeal() calls this same function). If an
    earlier slot in the same hand fails to deal at all — the pre-existing,
    exceedingly rare forced-Closet-already-excluded failure in draw_slot —
    the guarantee still targets list index 2 specifically, which then lands
    on a visually earlier option than "third"; that already-rare edge case is
    not special-cased further here.
    """
    # Tunnel chain-draft: north exit of a placed Tunnel guarantees a Tunnel in
    # slot 0 of an otherwise-normal three-slot hand (see docstring above).
    exclude: set[int] = set()
    tunnel_forced_option: DraftOption | None = None
    if (from_room is not None and from_room.id == TUNNEL_ID
            and pending.direction == N):
        tunnel_forced_option = _tunnel_chain_option(ctx, pending.target_cell, pending.direction)
        if tunnel_forced_option is not None:
            exclude.add(tunnel_forced_option.room_idx)

    # The Foundation: wiki says drafting on Rank 3 has a 90% chance to remove
    # it from the draft pool "for that draft" - rolled ONCE per hand (not once
    # per card, which would make the RNG draw count depend on deck order and
    # break determinism), and only when the Foundation could otherwise be dealt
    # at all (not already on the grid), to avoid disturbing the RNG stream on
    # doorways where it was never a candidate. See docs/foundation-design.md.
    foundation = ctx.registry.by_id.get("the_foundation")
    if (foundation is not None and foundation.id not in ctx.placed_ids
            and rank_of(pending.target_cell) == 3
            and ctx.rng.chance("foundation_rank3", 0.90)):
        exclude.add(foundation.idx)

    # Silver Key: on the initial deal, try cross/t layouts first for each slot,
    # falling back to the normal draw when no cross/t card qualifies.
    # Redraws clear the flag before calling _fill_options via redeal (flag already False).
    silver_key_bias = ctx.state.special.silver_key_draft
    for slot in range(3):
        if slot == 0 and tunnel_forced_option is not None:
            pending.options.append(tunnel_forced_option)
            continue
        if slot == 2 and from_room is not None and from_room.id == READING_NOOK_ID:
            # Reading Nook: slot 2 is always LIBRARY, ahead of (and instead
            # of) the Silver Key bias, the Garage Forced Draw, and the
            # priority draws -- see _reading_nook_library_option.
            opt = _reading_nook_library_option(ctx, pending.target_cell, pending.direction)
        else:
            opt = None
            if silver_key_bias:
                opt = _deal_cross_t_biased(ctx, slot, pending.target_cell,
                                           pending.direction, exclude)
            if opt is None:
                opt = draw_slot(ctx, slot, pending.target_cell, pending.direction, exclude,
                                pending.options)
        if opt is not None:
            pending.options.append(opt)
            exclude.add(opt.room_idx)
    # Clear after the initial deal; redraws of this hand use normal odds.
    ctx.state.special.silver_key_draft = False
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
    """Deal a fresh three-option hand for the doorway ``from_cell`` -> ``target_cell``.

    Entry point used by ``Game.open_door`` the first time a doorway is opened
    (the result is cached per doorway, so reopening shows the same hand).
    Library no-draft filtering, Archives/Darkroom hiding, and the Tunnel
    chain all key off the room being drafted FROM.
    """
    from_room = registry.rooms[state.grid[from_cell]] if state.grid[from_cell] >= 0 else None
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_room)
    pending = PendingDraft(from_cell=from_cell, direction=direction, target_cell=target_cell)
    _fill_options(ctx, pending, from_room)
    return pending


def redeal(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
           placed_ids: set[str], pending: PendingDraft) -> None:
    """Redraw all three options in place (Study / Classroom / dice redraw)."""
    from_room = registry.rooms[state.grid[pending.from_cell]] \
        if state.grid[pending.from_cell] >= 0 else None
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_room)
    pending.options.clear()
    pending.rotations_used = 0  # fresh hand, fresh rotation budget
    _fill_options(ctx, pending, from_room)
