"""Deck construction and the rarity roll.

Eight decks: rarity (4) x free/gem (2). Rooms enter decks at day start based
on which pools the config enables. The rarity roll picks a rarity from the
datamined weight row, restricted to rarities whose decks satisfy the
deck-size gates, then the room is dealt uniformly (solitaire-style) from that
rarity's deck(s).
"""

from __future__ import annotations

from ..config import GameConfig
from .model import RARITIES, Registry, Room
from .rng import Rng
from .state import DeckState, GameState


def eligible_pool(registry: Registry, cfg: GameConfig) -> list[Room]:
    """Rooms that participate in today's normal draft decks.

    Upgrade variants (from Upgrade Disks) REPLACE their base room: when a
    variant id appears in cfg.upgrade_disks, the variant joins the pool and
    its base room is removed.

    The Treasure Trove (``pool == "studio_addition"``) has a second, narrower
    door into the pool besides ``cfg.studio_additions``: ``cfg.treasure_trove_
    blackprint``, set once the player has picked up its blackprint at Upper
    Rotating Gear (game.py::travel_to / special_items.py::on_area_arrival).
    This mirrors the general "GameConfig flag gates pool membership" pattern
    rather than mutating cfg.studio_additions, because the Treasure Trove's
    black-box/Key-of-Aries reward mechanics remain unmodelled (see
    rl/train.py::_STUDIO_ADDITION_EXCLUSIONS) -- only its basic draftability is.
    """
    replaced: set[str] = set()
    chosen_variants: list[Room] = []
    for room in registry.rooms:
        if room.pool == "upgrade_variant" and room.id in cfg.upgrade_disks:
            chosen_variants.append(room)
            if room.variant_of:
                replaced.add(room.variant_of)

    out = []
    for room in registry.rooms:
        if room.rarity is None or room.id in replaced:
            continue
        # Repellent bans: rooms temporarily removed from the pool for 7 days.
        if room.id in cfg.banned_rooms:
            continue
        if room.pool == "base":
            out.append(room)
        elif room.pool == "studio_addition" and room.id in cfg.studio_additions:
            out.append(room)
        elif room.id == "treasure_trove" and cfg.treasure_trove_blackprint:
            out.append(room)
        # "outer": drafted at the dedicated outer location, not in decks
        # "pool_temp": injected by The Pool's effect during the day
        # "conditional"/"none": forced-only or gated rooms, never dealt normally
    # A ban targets the FLOORPLAN, so it covers the room's upgrade variant too
    # (banning "courtyard" must not leave an upgraded Courtyard dealable).
    out.extend(v for v in chosen_variants
               if v.rarity is not None
               and v.id not in cfg.banned_rooms
               and v.variant_of not in cfg.banned_rooms)
    return out


def build_decks(registry: Registry, cfg: GameConfig, rng: Rng) -> list[DeckState]:
    """Build and shuffle the eight day-start decks (index = rarity_idx * 2 + free/gem).

    Each eligible room contributes ``deck_copies`` cards to the deck matching
    its rarity and free/gem class; each deck shuffles on its own rng substream.
    """
    decks = [DeckState() for _ in range(8)]
    for room in eligible_pool(registry, cfg):
        d = decks[room.rarity_idx * 2 + (0 if room.is_free else 1)]
        d.order.extend([room.idx] * room.deck_copies)
    for i, d in enumerate(decks):
        rng.shuffle(f"deck_shuffle_{i}", d.order)
    return decks


def inject_rooms(state: GameState, registry: Registry, room_ids: list[str], rng: Rng) -> None:
    """Add rooms to the live decks mid-day (The Pool, Gardener mode, etc.).

    Reshuffles the whole target deck and rewinds its cursor to 0, so cards
    already dealt this cycle become dealable again -- correct for this
    function's once-per-day callers. :func:`inject_rooms_undealt` is the
    sibling for an effect that fires many times a day: it inserts into the
    undealt region only, leaving already-dealt cards dealt.
    """
    for rid in room_ids:
        room = registry.by_id.get(rid)
        if room is None or room.rarity is None:
            continue
        deck = state.deck(room.rarity_idx, not room.is_free)
        deck.add_copies(room.idx, room.deck_copies,
                        lambda lst, i=room.rarity_idx: rng.shuffle(f"deck_inject_{i}", lst))


def inject_rooms_undealt(state: GameState, registry: Registry, room_ids: list[str], rng: Rng,
                         label: str = "deck_inject_undealt") -> None:
    """Add rooms to the live decks mid-day without reshuffling or rewinding the cursor.

    Sibling to :func:`inject_rooms`: that helper's whole-deck reshuffle is
    correct for its once-per-day callers but would be wrong for an effect
    that fires many times a day, since it would silently un-deal every card
    already drawn this cycle. Each copy is inserted at a uniformly random
    undealt position instead, so ``order[:pos]`` and ``pos`` are untouched
    and the relative order of the existing undealt residue is preserved.
    ``len(order)`` is recomputed before each insert (as :func:`apply_upgrade`
    does for its cross-bucket path), so later inserts can land after earlier
    ones. All positions are drawn from the single ``label`` substream.

    Copies land in whichever bucket the room's cards currently occupy --
    ``state.dynamic_rarity`` when :func:`set_dynamic_rarity` has moved them,
    otherwise the room's own rarity. A room that has not been moved is
    absent from that dict, so this is its static bucket as usual.
    """
    for rid in room_ids:
        room = registry.by_id.get(rid)
        if room is None or room.rarity is None:
            continue
        rarity_idx = state.dynamic_rarity.get(room.id, room.rarity_idx)
        deck = state.deck(rarity_idx, not room.is_free)
        for _ in range(room.deck_copies):
            at = rng.randint(label, deck.pos, len(deck.order))
            deck.insert_undealt(room.idx, at)


def rarity_deck_ok(state: GameState, registry: Registry, cfg: GameConfig,
                   rarity_idx: int, free_only: bool) -> bool:
    """Deck-size gate: can this rarity be selected for a draw?

    Free decks need >=3 cards. Gem decks need 5/5/4/4 once the gem gate is
    active (veteran / Room 46 / day >= 16); before that, gem decks only need
    to be non-empty. Slot 1 (free_only) checks the free deck alone; slots 2&3
    draw from the union of free+gem decks of the rarity.
    """
    gates = registry.weights["deck_size_gates"]
    free_deck = state.deck(rarity_idx, False)
    if free_only:
        return free_deck.size() >= gates["free"][rarity_idx]
    gem_deck = state.deck(rarity_idx, True)
    if cfg.gem_gate_active():
        gem_ok = gem_deck.size() >= gates["gem"][rarity_idx]
    else:
        gem_ok = gem_deck.size() > 0
    return free_deck.size() >= gates["free"][rarity_idx] or gem_ok


def roll_rarity(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
                slot: int, rank: int, from_library: bool = False) -> int | None:
    """Pick a rarity index for one option slot, or None if no rarity is legal.

    ``from_library`` selects the Library's fixed rarity table instead of the
    normal stage/slot/rank row -- a datamined full override, not a re-deal bias
    (see priority_draws.json's former "Rare Rooms (Library)" entry). The table
    itself lives in weights.json alongside every other rarity table; the
    substitution happens inside ``weight_row`` and therefore lands BEFORE the
    deck-size-gate zeroing below, so a rarity whose deck is exhausted or
    unaffordable is still zeroed exactly as it would be for any other draft.
    """
    slot_class = "slot1" if slot == 0 else "slot23"
    row = registry.weight_row(state.stage, state.solarium_placed, slot_class, rank,
                              library=from_library)
    weights = [
        w if rarity_deck_ok(state, registry, cfg, i, free_only=(slot == 0)) else 0.0
        for i, w in enumerate(row)
    ]
    if not any(w > 0 for w in weights):
        return None
    return rng.roll_weighted("rarity", tuple(weights))


def reroll_random_rarities(state: GameState, rng: Rng, count: int = 3,
                           label: str = "conservatory_reroll") -> None:
    """Conservatory: one-time re-roll of the rarity of ``count`` undealt cards.

    Fired once when the Conservatory is drafted. Picks ``count`` distinct
    undealt cards across the eight decks, rolls each a fresh rarity uniformly
    over the four rarities (the real re-roll distribution is unpublished;
    uniform is inferred), and moves changed cards into the new rarity's deck of
    the same free/gem class at a random undealt position. A card whose re-roll
    matches its current rarity stays put. All randomness comes from the
    dedicated ``label`` substream, consumed only when this fires.
    """
    undealt = [(r, g, i)
               for r in range(4) for g in (False, True)
               for i in range(state.deck(r, g).pos, state.deck(r, g).size())]
    if not undealt:
        return
    order = list(range(len(undealt)))
    rng.shuffle(label, order)

    moves = []
    for j in order[:count]:
        r, g, i = undealt[j]
        new_r = rng.randint(label, 0, len(RARITIES) - 1)
        if new_r != r:
            moves.append((r, g, i, new_r))

    # Remove every moved card first (descending index within each deck keeps
    # the remaining removal indices valid), then insert, so an insertion can
    # never shift a pending removal.
    moves.sort(key=lambda m: (m[0], m[1], -m[2]))
    removed = [(state.deck(r, g).order.pop(i), g, new_r) for r, g, i, new_r in moves]
    for card, g, new_r in removed:
        dst = state.deck(new_r, g)
        dst.order.insert(rng.randint(label, dst.pos, dst.size()), card)


RARITY_NAMES = RARITIES


def apply_upgrade(state: GameState, registry: Registry, variant_id: str, rng: Rng) -> None:
    """Apply an upgrade to the live decks by substituting base cards for variant cards.

    For same-bucket upgrades (same rarity and free/gem class): rewrites every
    base card as the variant card in-place. No RNG consumed, no card changes
    position.

    For cross-bucket upgrades (the 8 Cloister variants, all unusual/gem ->
    standard/gem or standard/free): removes base cards from the source deck and
    inserts variant cards at random undealt positions in the destination deck.
    Uses the 'upgrade_deck_insert' substream.

    Rooms already placed on the grid are never touched, and neither is a draft
    hand already dealt — but the deck itself retires the base floorplan
    completely, including cards dealt earlier this cycle, because draft.py's
    attempt-3 reshuffle would otherwise make the un-upgraded room dealable again.
    """
    variant = registry.by_id[variant_id]
    base = registry.by_id[variant.variant_of]

    src_deck = state.deck(base.rarity_idx, not base.is_free)
    dst_deck = state.deck(variant.rarity_idx, not variant.is_free)

    if src_deck is dst_deck:
        # Same bucket: in-place substitution, no RNG consumed
        src_deck.replace_card(base.idx, variant.idx)
    else:
        # Cross-bucket (Cloister variants): remove from source, insert into destination
        removed = src_deck.remove_card(base.idx)
        for _ in range(removed):
            at = rng.randint("upgrade_deck_insert", dst_deck.pos, len(dst_deck.order))
            dst_deck.insert_undealt(variant.idx, at)


def set_dynamic_rarity(state: GameState, registry: Registry, room_id: str,
                       target_rarity_idx: int, rng: Rng,
                       label: str = "dynamic_rarity") -> None:
    """Move a room's live-deck cards into another rarity bucket for the day.

    The room's free/gem class never changes -- only which rarity's deck(s) its
    cards sit in, since a card's effective rarity IS the deck it occupies
    (``_deal_from_rarity`` is handed a rarity index and never reads a card's own
    rarity). Idempotent: if the room's cards already sit in ``target_rarity_idx``
    (per ``state.dynamic_rarity``, defaulting to ``Room.rarity_idx``), this is a
    no-op that consumes no RNG -- required because the effect that will call
    this fires many times a day and does not stack with itself.

    Copies already dealt this cycle stay dealt: they move to just before the
    destination deck's cursor (``DeckState.insert_dealt``), which the solitaire
    invariant requires -- leaving a dealt copy behind in the source deck would
    let it be re-dealt after draw_slot's attempt-3 full reshuffle. Undealt
    copies move to a uniformly random undealt position in the destination deck,
    the same shape as :func:`apply_upgrade`'s cross-bucket path. All positions
    are drawn from the single ``label`` substream.
    """
    room = registry.by_id[room_id]
    current_rarity_idx = state.dynamic_rarity.get(room_id, room.rarity_idx)
    if current_rarity_idx == target_rarity_idx:
        return  # already in the target bucket: no-op, no RNG consumed

    is_gem = not room.is_free
    src_deck = state.deck(current_rarity_idx, is_gem)
    dst_deck = state.deck(target_rarity_idx, is_gem)

    n_dealt = src_deck.order[:src_deck.pos].count(room.idx)
    n_total = src_deck.remove_card(room.idx)
    n_undealt = n_total - n_dealt

    for _ in range(n_dealt):
        dst_deck.insert_dealt(room.idx)
    for _ in range(n_undealt):
        at = rng.randint(label, dst_deck.pos, len(dst_deck.order))
        dst_deck.insert_undealt(room.idx, at)

    if target_rarity_idx == room.rarity_idx:
        state.dynamic_rarity.pop(room_id, None)
    else:
        state.dynamic_rarity[room_id] = target_rarity_idx
