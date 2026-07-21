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
        if room.pool == "base":
            out.append(room)
        elif room.pool == "studio_addition" and room.id in cfg.studio_additions:
            out.append(room)
        # "outer": drafted at the dedicated outer location, not in decks
        # "pool_temp": injected by The Pool's effect during the day
        # "conditional"/"none": forced-only or gated rooms, never dealt normally
    out.extend(v for v in chosen_variants if v.rarity is not None)
    return out


def build_decks(registry: Registry, cfg: GameConfig, rng: Rng) -> list[DeckState]:
    decks = [DeckState() for _ in range(8)]
    for room in eligible_pool(registry, cfg):
        d = decks[room.rarity_idx * 2 + (0 if room.is_free else 1)]
        d.order.extend([room.idx] * room.deck_copies)
    for i, d in enumerate(decks):
        rng.shuffle(f"deck_shuffle_{i}", d.order)
    return decks


def inject_rooms(state: GameState, registry: Registry, room_ids: list[str], rng: Rng) -> None:
    """Add rooms to the live decks mid-day (The Pool, Gardener mode, etc.)."""
    for rid in room_ids:
        room = registry.by_id.get(rid)
        if room is None or room.rarity is None:
            continue
        deck = state.deck(room.rarity_idx, not room.is_free)
        deck.add_copies(room.idx, room.deck_copies,
                        lambda lst, i=room.rarity_idx: rng.shuffle(f"deck_inject_{i}", lst))


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
                slot: int, rank: int) -> int | None:
    """Pick a rarity index for one option slot, or None if no rarity is legal."""
    slot_class = "slot1" if slot == 0 else "slot23"
    row = registry.weight_row(state.stage, state.solarium_placed, slot_class, rank)
    weights = [
        w if rarity_deck_ok(state, registry, cfg, i, free_only=(slot == 0)) else 0.0
        for i, w in enumerate(row)
    ]
    if not any(w > 0 for w in weights):
        return None
    return rng.roll_weighted("rarity", tuple(weights))


RARITY_NAMES = RARITIES
