"""Deck (solitaire) semantics and pool construction."""

from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import (build_decks, eligible_pool, inject_rooms,
                                         inject_rooms_undealt)
from blueprince_sim.engine.draft import DraftContext, _priority_draw
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState


def test_deal_no_repeat_until_depletion():
    """Solitaire semantics: each card is dealt at most once until the deck is
    depleted (then None), and a reshuffle makes the cards dealable again."""
    deck = DeckState(order=[1, 2, 3, 4, 5])
    dealt = [deck.deal_next(lambda c: True) for _ in range(5)]
    assert sorted(dealt) == [1, 2, 3, 4, 5]
    assert deck.deal_next(lambda c: True) is None  # depleted
    deck.reshuffle(lambda lst: None)
    assert deck.deal_next(lambda c: True) in (1, 2, 3, 4, 5)


def test_deal_respects_predicate_and_preserves_skipped():
    """Dealing with a predicate returns the first eligible card; skipped cards
    are not lost and remain dealable later."""
    deck = DeckState(order=[1, 2, 3])
    assert deck.deal_next(lambda c: c == 3) == 3
    # 3 was swapped behind the cursor; 1 and 2 still dealable
    remaining = {deck.deal_next(lambda c: True) for _ in range(2)}
    assert remaining == {1, 2}


def test_reshuffle_drops_filtered():
    """Reshuffling with a drop set removes those cards for good and rewinds
    the deal cursor to the top."""
    deck = DeckState(order=[1, 2, 3, 4])
    deck.reshuffle(lambda lst: None, drop={2, 4})
    assert sorted(deck.order) == [1, 3]
    assert deck.pos == 0


def test_pool_respects_unlock_config(registry):
    """The draftable pool tracks the config: outer rooms, Pool-only temps, the
    fixed start/end rooms, and locked Studio additions stay out of the decks,
    while library-gated rooms stay in (they are gated at deal time)."""
    base = {r.id for r in eligible_pool(registry, GameConfig())}
    assert "solarium" not in base
    assert "locker_room" not in base       # pool_temp: only via The Pool
    assert "tomb" not in base              # outer rooms never in normal decks
    assert "entrance_hall" not in base
    assert "antechamber" not in base
    assert "closet" in base
    assert "bookshop" in base              # library-gated at deal time, not pool time

    with_solarium = {r.id for r in eligible_pool(
        registry, GameConfig(studio_additions=frozenset({"solarium"})))}
    assert "solarium" in with_solarium


def test_upgrade_variant_replaces_base(registry):
    """An unlocked upgrade disk swaps the variant into the pool and removes
    the base room - the two never coexist."""
    # Boudoir dice variant (internal index 17) replaces the base Boudoir.
    variant_id = "boudoir__ix17"
    assert variant_id in registry.by_id
    pool = {r.id for r in eligible_pool(
        registry, GameConfig(upgrade_disks=frozenset({variant_id})))}
    assert variant_id in pool
    assert "boudoir" not in pool


def test_deck_copies_and_build(registry):
    """build_decks produces the 8 solitaire decks (4 rarities x free/gem) that
    exactly partition the eligible pool, with every card in the deck matching
    its free/gem class."""
    cfg = GameConfig()
    decks = build_decks(registry, cfg, Rng(0))
    assert len(decks) == 8
    total = sum(d.size() for d in decks)
    assert total == len(eligible_pool(registry, cfg))  # all copies=1 in base data
    # free/gem split is consistent
    for rarity_idx in range(4):
        free = decks[rarity_idx * 2]
        gem = decks[rarity_idx * 2 + 1]
        for card in free.order:
            assert registry.rooms[card].is_free
        for card in gem.order:
            assert not registry.rooms[card].is_free


def test_inject_rooms_undealt_preserves_dealt_prefix_and_grows_by_copies(registry):
    """inject_rooms_undealt must not perturb the dealt prefix or cursor, and
    grows the deck by exactly the number of copies injected."""
    rng = Rng(0)
    room = registry.by_id["closet"]
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
    decks = [DeckState() for _ in range(8)]
    decks[deck_idx] = DeckState(order=[100, 101, 200, 201, 202], pos=2)
    state = GameState(decks=decks)
    deck = decks[deck_idx]
    before_prefix = list(deck.order[:deck.pos])
    before_pos = deck.pos
    before_len = len(deck.order)

    inject_rooms_undealt(state, registry, ["closet", "closet"], rng)

    assert deck.order[:before_pos] == before_prefix
    assert deck.pos == before_pos
    assert len(deck.order) == before_len + 2 * room.deck_copies


def test_inject_rooms_undealt_lands_only_in_undealt_range(registry):
    """Every injected card lands at an index >= pos -- none can leak into the
    already-dealt prefix."""
    rng = Rng(0)
    room = registry.by_id["closet"]
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
    decks = [DeckState() for _ in range(8)]
    decks[deck_idx] = DeckState(order=[900, 901, 902], pos=3)  # fully dealt, no closet cards
    state = GameState(decks=decks)

    inject_rooms_undealt(state, registry, ["closet"] * 20, rng)

    deck = decks[deck_idx]
    positions = [i for i, c in enumerate(deck.order) if c == room.idx]
    assert len(positions) == 20 * room.deck_copies
    assert all(i >= 3 for i in positions)


def test_inject_rooms_undealt_positions_are_roughly_uniform(registry):
    """Over many trials, injected positions spread evenly across the undealt
    range instead of clustering at either end (chi-square against uniform)."""
    rng = Rng(0)
    room = registry.by_id["closet"]
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
    undealt_width = 50
    n_bins = 5
    n_trials = 4000
    counts = [0] * n_bins
    for _ in range(n_trials):
        decks = [DeckState() for _ in range(8)]
        decks[deck_idx] = DeckState(order=list(range(1000, 1000 + undealt_width)), pos=0)
        state = GameState(decks=decks)
        inject_rooms_undealt(state, registry, ["closet"], rng)
        at = decks[deck_idx].order.index(room.idx)
        counts[min(at * n_bins // (undealt_width + 1), n_bins - 1)] += 1
    expected = [n_trials / n_bins] * n_bins
    _, p = stats.chisquare(counts, expected)
    assert p > 0.001, f"injected positions not uniform: counts={counts}"


def test_add_copies_rewinds_but_inject_rooms_undealt_does_not(registry):
    """Pins the distinction the new primitive exists for: add_copies (the
    existing once-a-day helper) reshuffles and rewinds pos to 0, while
    inject_rooms_undealt leaves the cursor and dealt prefix untouched."""
    room = registry.by_id["closet"]
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)

    rewound = DeckState(order=[100, 101, 102, 103], pos=2)
    rewound.add_copies(room.idx, 1, lambda lst: None)
    assert rewound.pos == 0

    decks = [DeckState() for _ in range(8)]
    decks[deck_idx] = DeckState(order=[100, 101, 102, 103], pos=2)
    inject_rooms_undealt(GameState(decks=decks), registry, ["closet"], Rng(0))
    assert decks[deck_idx].pos == 2


def test_priority_draw_skips_entry_with_inactive_condition(registry, cfg):
    """A priority_draws entry carrying a condition absent from the active set
    is skipped before its own chance is ever rolled -- splicing one in ahead
    of the real entries must leave both the final pick and every other
    entry's own RNG substream exactly as if it were absent."""
    original = registry.priority["priority_draws"]
    gated_entry = {"rooms": ["closet"], "label": "never_active_gate", "chance": 1.0,
                   "condition": "definitely_not_a_real_condition"}
    try:
        for seed in range(10):
            registry.priority["priority_draws"] = original
            rng_base = Rng(seed)
            state_base = GameState(decks=[DeckState() for _ in range(8)])
            ctx_base = DraftContext(state_base, registry, cfg, rng_base, set(), None)
            base_pick = _priority_draw(ctx_base, 7, N, set(), is_gem=True)

            registry.priority["priority_draws"] = [gated_entry, *original]
            rng_gated = Rng(seed)
            state_gated = GameState(decks=[DeckState() for _ in range(8)])
            ctx_gated = DraftContext(state_gated, registry, cfg, rng_gated, set(), None)
            gated_pick = _priority_draw(ctx_gated, 7, N, set(), is_gem=True)

            assert (gated_pick.id if gated_pick else None) == \
                   (base_pick.id if base_pick else None), \
                f"seed {seed}: an inactive gated entry changed the priority-draw pick"
            fresh_gate_state = Rng(seed).stream("priority_never_active_gate").getstate()
            assert (rng_gated.stream("priority_never_active_gate").getstate()
                    == fresh_gate_state), f"seed {seed}: gated entry's substream was consumed"
    finally:
        registry.priority["priority_draws"] = original


def test_deck_groundwork_ships_inert(cfg):
    """Behaviour-neutrality guard for the deck-level groundwork (inject_rooms_undealt,
    set_dynamic_rarity, the priority_draws condition key): with no call site added for
    any of them, dealt hands stay bit-identical across two runs of the same seed, and
    the two new named substreams go untouched by a full three-slot deal."""
    game = Game(cfg, seed=0)

    def collect(seed: int):
        game.reset(seed)
        game.state.steps = 999
        pending = game.open_door(2, N)
        return [(o.room_idx, o.orientation, o.gem_cost) for o in pending.options]

    for seed in range(200):
        run_a = collect(seed)
        run_b = collect(seed)
        assert run_a == run_b, f"seed {seed}: non-deterministic hand"

    game.reset(0)
    before = (game.rng.stream("deck_inject_undealt").getstate(),
             game.rng.stream("dynamic_rarity").getstate())
    game.state.steps = 999
    game.open_door(2, N)
    after = (game.rng.stream("deck_inject_undealt").getstate(),
            game.rng.stream("dynamic_rarity").getstate())
    assert before == after, "a full hand deal consumed the new deck-groundwork substreams"


def test_axing_a_room_never_moves_its_cards_between_decks(registry):
    """The Axe zeroes a room's CHARGED gem cost at payment time; it must never
    move the family's cards into the free deck or otherwise change any of the
    8 deck sizes. A card's effective rarity IS the deck it sits in, and deck
    SIZES feed decks.py::rarity_deck_ok's legality gate -- so an
    implementation that "makes the room free" by moving its cards to the free
    deck would silently change which rarities are legal to roll for the rest
    of the day, on top of letting the axed room be dealt into slot 0 (which
    must always be a statically-free room). kitchen is deck-resident
    (pool == "base"), so a wrongly-implemented bucket move is actually
    exercised by this test, not a no-op -- an upgrade_variant room is never
    deck-resident, so a guard built on one would be theatre (see
    docs/special-items-behaviour.md's Axe section)."""
    room = registry.by_id["kitchen"]
    assert room.pool == "base", "must be deck-resident for this guard to mean anything"
    assert room.gem_cost > 0
    gem_idx = room.rarity_idx * 2 + 1
    free_idx = room.rarity_idx * 2

    cfg = GameConfig(special_items=True, starting_items=frozenset({"the_axe"}))
    game = Game(cfg, seed=3, registry=registry)
    sizes_before = [d.size() for d in game.state.decks]
    assert game.state.decks[gem_idx].order.count(room.idx) == room.deck_copies
    assert game.state.decks[free_idx].order.count(room.idx) == 0

    assert game.can_axe_room("kitchen")
    game.axe_room("kitchen")

    sizes_after = [d.size() for d in game.state.decks]
    assert sizes_after == sizes_before, (
        f"axing changed deck sizes: before={sizes_before} after={sizes_after}"
    )
    assert game.state.decks[gem_idx].order.count(room.idx) == room.deck_copies, (
        "the axed room's cards left the gem deck"
    )
    assert game.state.decks[free_idx].order.count(room.idx) == 0, (
        "the axed room's cards were moved into the free deck"
    )


# --------------------------------------------------------- Gear Wrench guard


def test_gear_wrench_pump_room_injection_lands_in_wrenched_bucket_not_natal(registry):
    """The reachable corruption decks.py::inject_rooms's own docstring warns
    about: Pump Room is BOTH Mechanical (wrenchable) and pool_temp (never in
    build_decks's eligible pool -- it only ever reaches a live deck through
    The Pool's decks.inject_rooms call). A permanently-wrenched Pump Room's
    injected cards must land in the wrenched bucket, not the room's own
    natal one -- landing in both would be a reachable split-bucket
    corruption (two decks both claiming to hold the same physical card),
    landing only in the natal bucket would silently discard the wrench.

    Mutation-tested: reverting inject_rooms to index by ``room.rarity_idx``
    directly makes this fail -- the injected copy then lands in the natal
    (standard) bucket instead of the wrenched (rare) one, and the
    natal-bucket assertion below flips true.
    """
    pump_room = registry.by_id["pump_room"]
    assert pump_room.pool == "pool_temp", "must be pool_temp for this guard to mean anything"
    natal_idx = pump_room.rarity_idx
    target_idx = 3  # rare; natal is standard (1), so this is a genuine move
    assert target_idx != natal_idx

    cfg = GameConfig(permanent_rarity={pump_room.id: target_idx})
    rng = Rng(0)
    state = GameState(decks=build_decks(registry, cfg, rng))
    # Game.reset's own seeding step, right after build_decks (see its own comment).
    state.dynamic_rarity = dict(cfg.permanent_rarity)

    inject_rooms(state, registry, [pump_room.id], rng)

    natal_deck = state.deck(natal_idx, not pump_room.is_free)
    wrenched_deck = state.deck(target_idx, not pump_room.is_free)
    assert pump_room.idx not in natal_deck.order, (
        "a wrenched Pump Room's injected cards leaked into its natal bucket"
    )
    assert wrenched_deck.order.count(pump_room.idx) == pump_room.deck_copies, (
        "the injected copies did not land in the wrenched bucket"
    )
    # Conservation: exactly one bucket holds the injected copies, total
    # matches deck_copies -- never split across two buckets.
    total = sum(d.order.count(pump_room.idx) for d in state.decks)
    assert total == pump_room.deck_copies


def test_gear_wrench_build_decks_seeds_wrenched_room_in_target_bucket(registry):
    """cfg.permanent_rarity relocates a deck-resident room's cards to the
    wrenched bucket at day-start build time (no same-day set_dynamic_rarity
    sweep needed): zero cards in the natal bucket, the full count in the
    target bucket, and the total card count conserved against an
    unwrenched build of the same config."""
    room = registry.by_id["boiler_room"]  # unusual (gem deck), deck-resident (pool == "base")
    assert room.pool == "base"
    natal_idx = room.rarity_idx
    target_idx = 0  # commonplace
    assert target_idx != natal_idx

    plain = build_decks(registry, GameConfig(), Rng(0))
    wrenched = build_decks(registry, GameConfig(permanent_rarity={room.id: target_idx}), Rng(0))

    natal_deck = wrenched[natal_idx * 2 + (0 if room.is_free else 1)]
    target_deck = wrenched[target_idx * 2 + (0 if room.is_free else 1)]
    assert room.idx not in natal_deck.order
    assert target_deck.order.count(room.idx) == room.deck_copies

    assert sum(d.size() for d in wrenched) == sum(d.size() for d in plain)


def test_no_upgrade_variant_chains_off_a_mechanical_room_or_its_variant(registry):
    """apply_upgrade's own docstring claims its dynamic_rarity fallback is
    unreachable with today's data: no room is ``variant_of`` a Mechanical
    Room, and no room is ``variant_of`` a Mechanical Room's OWN upgrade
    variant. Pins the empirical fact so a future rooms.json change that
    makes it reachable is caught here rather than leaving a silently-stale
    docstring claim."""
    mechanical_ids = {r.id for r in registry.rooms if r.is_category("mechanical")}
    for room in registry.rooms:
        if room.variant_of is None:
            continue
        assert room.variant_of not in mechanical_ids, (
            f"{room.id} is a variant of Mechanical Room {room.variant_of!r}: "
            "apply_upgrade's dynamic_rarity fallback is no longer unreachable"
        )
