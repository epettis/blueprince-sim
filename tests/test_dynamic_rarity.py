"""set_dynamic_rarity: moving a room's live-deck cards between rarity buckets.

Groundwork for the add_aquariums experiment effect (unwired as of this PR --
no production call site exists yet). A card's effective rarity IS the deck it
sits in, so "override a room's rarity for the day" is a card move between the
eight solitaire decks, not a lookup; these tests pin the move's three
required properties: it relocates every copy, it preserves dealt-ness, and it
is idempotent.
"""

from __future__ import annotations

from blueprince_sim.engine.decks import build_decks, set_dynamic_rarity
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState


def _deck_index(rarity_idx: int, is_gem: bool) -> int:
    return rarity_idx * 2 + (1 if is_gem else 0)


def test_set_dynamic_rarity_moves_every_copy_and_conserves_multiset(registry, cfg):
    """Every copy of the room's cards leaves the source deck for the target
    rarity's deck of the same free/gem class, and the combined card multiset
    within that free/gem class is conserved -- nothing is lost or duplicated."""
    rng = Rng(0)
    state = GameState(decks=build_decks(registry, cfg, rng))
    room = registry.by_id["closet"]  # commonplace, free
    target_rarity_idx = 2  # unusual

    before = [list(d.order) for d in state.decks]
    set_dynamic_rarity(state, registry, room.id, target_rarity_idx, rng)
    after = [list(d.order) for d in state.decks]

    src_idx = _deck_index(room.rarity_idx, not room.is_free)
    dst_idx = _deck_index(target_rarity_idx, not room.is_free)
    assert room.idx not in after[src_idx]
    assert after[dst_idx].count(room.idx) == before[src_idx].count(room.idx)

    # Conservation: the free-class multiset (all four rarities combined) is
    # unchanged -- the same room count check the Conservatory's own test uses.
    combined_before = sorted(c for i in range(0, 8, 2) for c in before[i])
    combined_after = sorted(c for i in range(0, 8, 2) for c in after[i])
    assert combined_before == combined_after


def test_set_dynamic_rarity_preserves_dealt_ness(registry, cfg):
    """A copy already dealt in the source bucket lands before the
    destination deck's cursor and stays dealt -- it must not become
    re-dealable after the move, or the solitaire invariant breaks."""
    rng = Rng(0)
    state = GameState(decks=build_decks(registry, cfg, rng))
    room = registry.by_id["closet"]
    src_deck = state.deck(room.rarity_idx, not room.is_free)

    dealt = src_deck.deal_next(lambda c: c == room.idx)
    assert dealt == room.idx
    assert src_deck.order.index(room.idx) < src_deck.pos

    target_rarity_idx = 2
    dst_deck = state.deck(target_rarity_idx, not room.is_free)
    dst_pos_before = dst_deck.pos

    set_dynamic_rarity(state, registry, room.id, target_rarity_idx, rng)

    assert room.idx not in src_deck.order
    idx_in_dst = dst_deck.order.index(room.idx)
    assert idx_in_dst < dst_deck.pos
    assert dst_deck.pos == dst_pos_before + 1

    # Not re-dealable: deal_next only scans from pos onward.
    assert dst_deck.deal_next(lambda c: c == room.idx) is None


def test_set_dynamic_rarity_is_idempotent(registry, cfg):
    """A second call moving the same room to the bucket it already occupies
    is a no-op that consumes no RNG -- required because the effect that will
    call this fires many times a day and must not stack with itself."""
    rng = Rng(0)
    state = GameState(decks=build_decks(registry, cfg, rng))
    room = registry.by_id["closet"]
    target_rarity_idx = 2

    set_dynamic_rarity(state, registry, room.id, target_rarity_idx, rng)
    stream_state = rng.stream("dynamic_rarity").getstate()
    order_before = [list(d.order) for d in state.decks]
    pos_before = [d.pos for d in state.decks]

    set_dynamic_rarity(state, registry, room.id, target_rarity_idx, rng)

    assert rng.stream("dynamic_rarity").getstate() == stream_state
    assert [list(d.order) for d in state.decks] == order_before
    assert [d.pos for d in state.decks] == pos_before
