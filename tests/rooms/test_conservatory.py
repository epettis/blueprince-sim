"""Conservatory drawing board (the remodel): stocking, clicking, and its bounds.

Drafting the Conservatory stocks a three-row drawing board
(``conservatory.stock_drawing_board``, ``Hook.ON_PLACE``); standing in the
room, each row may be clicked ``CLICKS_PER_FLOORPLAN`` times to set that
floorplan's rarity permanently (``Game.can_remodel``/``Game.remodel``), writing
the same ``state.permanent_rarity`` slot the Gear Wrench writes.

Every scenario here is built deterministically -- the Conservatory is placed
directly at a chosen cell and the board's rows are read off the state -- rather
than by hunting a seed that happens to draft it.
"""

from __future__ import annotations

from collections import Counter

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import build_decks, eligible_pool
from blueprince_sim.engine.effects.rooms import conservatory as C
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import RARITIES
from blueprince_sim.rl.train import all_unlocks_config

# Draft setup: player at entrance (cell 2), open north door to cell 7 (rank 2).
DRAFT_FROM = 2
DRAFT_DIR = N

# Conservatory: corner room; place at cell 0 (rank 1, col 0 - a corner, not
# adjacent to the draft target cell) with a north-facing entry. Orientation 3
# is its north|east door pair, which leaves two open frontier doorways at the
# cell so a player standing there still has work to do and the day stays in
# NAVIGATE -- without it _check_termination ends the day on the first action
# and every phase-gated predicate below would pass for the wrong reason.
CONSERVATORY_CELL = 0
CONSERVATORY_ORIENTATION = 3


def _board_game(seed: int = 0, cfg: GameConfig | None = None) -> Game:
    """A game with the Conservatory placed at CONSERVATORY_CELL and the player
    standing in it, i.e. a stocked board the drawing-board actions are legal at."""
    game = Game(cfg if cfg is not None else all_unlocks_config(), seed=seed)
    game.reset(seed)
    game._place_room(game.registry.by_id[C.CONSERVATORY_ID], CONSERVATORY_CELL,
                     CONSERVATORY_ORIENTATION, entry_dir=N)
    game.state.pos = CONSERVATORY_CELL
    game.state.steps = 999
    return game


def test_drafting_the_conservatory_stocks_three_rows():
    """Placing the Conservatory fills the board with exactly BOARD_OFFERS
    floorplans, all drawn from the remodel pool, with every row unclicked --
    the state the twelve REMODEL_BASE action ids read."""
    game = _board_game()
    st = game.state
    assert len(st.remodel_offers) == C.BOARD_OFFERS == 3
    assert st.remodel_clicks == [0] * C.BOARD_OFFERS
    pool = set(C.remodel_pool(game))
    assert set(st.remodel_offers) <= pool


def test_an_unplaced_conservatory_leaves_the_board_unstocked():
    """No board exists until the Conservatory is drafted, so none of its
    actions are legal -- the day-scoped default, and the reason a fresh
    GameState needs no reset hook of its own."""
    game = Game(all_unlocks_config(), seed=0)
    game.reset(0)
    assert game.state.remodel_offers == ()
    assert game.state.remodel_clicks == []
    assert not any(game.can_remodel(slot, r)
                   for slot in range(C.BOARD_OFFERS) for r in range(len(RARITIES)))


def test_the_three_offers_are_uniform_with_replacement():
    """The owner's ruling is "uniform random WITH replacement", which has two
    observable consequences this pins across 2000 independent stockings:

    1. every pool room is drawn about equally often (chi-square against a
       uniform null over the pool, not rejected at p < 0.001), and
    2. repeats across the three rows happen at the rate independent draws
       predict, 1 - (1 - 1/n)(1 - 2/n) for pool size n -- WITHOUT replacement
       would make that rate exactly zero.

    A per-room uniformity test alone would pass for a without-replacement draw
    too, so the repeat rate is the half that actually separates the two models.
    """
    from scipy import stats

    game = _board_game()
    pool = C.remodel_pool(game)
    n = len(pool)
    trials = 2000
    counts: Counter[str] = Counter()
    repeats = 0
    for seed in range(trials):
        g = _board_game(seed=seed)
        offers = g.state.remodel_offers
        counts.update(offers)
        if len(set(offers)) < C.BOARD_OFFERS:
            repeats += 1

    observed = [counts.get(rid, 0) for rid in pool]
    assert sum(observed) == trials * C.BOARD_OFFERS
    chi = stats.chisquare(observed)
    assert chi.pvalue > 1e-3, (
        f"offer frequencies are not uniform over the {n}-room pool: "
        f"chi-square p={chi.pvalue:.2e}")

    p_repeat = 1 - (1 - 1 / n) * (1 - 2 / n)
    binom = stats.binomtest(repeats, trials, p=p_repeat)
    assert binom.pvalue > 1e-3, (
        f"repeat rate {repeats}/{trials} disagrees with independent draws "
        f"(expected p={p_repeat:.4f}, binomial p={binom.pvalue:.2e}) -- a draw "
        f"WITHOUT replacement would show zero repeats")


def test_a_click_writes_the_gear_wrench_permanent_slot():
    """A remodel writes ``state.permanent_rarity`` -- the Gear Wrench's own
    save-scoped record, which the wiki says the two mechanics share -- and
    moves the room's live cards into that bucket for the rest of today."""
    game = _board_game()
    room_id = game.state.remodel_offers[0]
    room = game.registry.by_id[room_id]
    target = (room.rarity_idx + 1) % len(RARITIES)

    game.remodel(0, target)

    assert game.state.permanent_rarity[room_id] == target
    assert game.state.dynamic_rarity[room_id] == target
    deck = game.state.deck(target, not room.is_free)
    assert deck.order.count(room.idx) == room.deck_copies


def test_a_remodelled_room_starts_tomorrow_in_its_new_bucket():
    """The permanent record is what ``build_decks`` reads at day start, so a
    remodel survives the night in the only way that matters: the room's cards
    are dealt from the chosen rarity's deck on a later day, not its natal one.
    """
    game = _board_game()
    room_id = game.state.remodel_offers[0]
    room = game.registry.by_id[room_id]
    target = (room.rarity_idx + 2) % len(RARITIES)
    game.remodel(0, target)

    cfg = all_unlocks_config()
    cfg.permanent_rarity = dict(game.state.permanent_rarity)
    tomorrow = Game(cfg, seed=1)
    assert tomorrow.state.deck(target, not room.is_free).order.count(room.idx) == 1
    assert tomorrow.state.deck(room.rarity_idx, not room.is_free).order.count(room.idx) == 0


def test_a_remodel_can_reset_a_wrench_set_rarity():
    """Both mechanics write one slot, so a remodel of a room the Gear Wrench
    already set replaces that entry rather than adding a second, competing
    record -- the wiki's "the Conservatory can reset a wrench-set rarity"."""
    game = _board_game()
    room_id = game.state.remodel_offers[0]
    room = game.registry.by_id[room_id]
    wrenched = (room.rarity_idx + 1) % len(RARITIES)
    game._write_permanent_rarity(room_id, wrenched, label="gear_wrench_set_rarity")
    assert game.state.permanent_rarity[room_id] == wrenched

    remodelled = (room.rarity_idx + 2) % len(RARITIES)
    game.remodel(0, remodelled)
    assert game.state.permanent_rarity[room_id] == remodelled


def test_a_no_op_click_consumes_the_row_and_records_no_override():
    """Owner ruling: "clicking a floorplan, even without actually changing the
    rarity, counts as changing the rarity". Picking the floorplan's own natal
    rarity spends the row exactly as any other pick does, while leaving
    ``permanent_rarity`` without an entry -- the same idempotent-pop convention
    ``Game.set_wrench_rarity`` uses, because the room's rarity genuinely is its
    natal one and a stale entry would misreport it as an override.
    """
    game = _board_game()
    room_id = game.state.remodel_offers[0]
    natal = game.registry.by_id[room_id].rarity_idx

    game.remodel(0, natal)

    assert room_id not in game.state.permanent_rarity
    assert game.state.remodel_clicks[0] == C.CLICKS_PER_FLOORPLAN
    assert not any(game.can_remodel(0, r) for r in range(len(RARITIES)))


def test_each_row_is_independently_clickable():
    """Owner ruling: the player may change the rarity of EACH of the three
    floorplans, not one of them -- so spending row 0 must leave rows 1 and 2
    answering."""
    game = _board_game()
    game.remodel(0, 0)
    assert not any(game.can_remodel(0, r) for r in range(len(RARITIES)))
    for slot in (1, 2):
        assert all(game.can_remodel(slot, r) for r in range(len(RARITIES)))


def test_the_board_runs_out_so_a_conservatory_day_terminates():
    """The board offers at most BOARD_OFFERS * CLICKS_PER_FLOORPLAN clicks
    between stockings and every click strictly increments a counter nothing
    decrements, so a player who only clicks the board runs out of board
    actions in bounded time.

    This is the property that makes the drawing board safe to expose at all --
    the Casino's slot rows once broke the same invariant by being unlimited and
    non-consuming. It is checked directly rather than via
    ``Game._in_place_actions``, which deliberately excludes the board (see that
    method's docstring), so no policy sweep can hold a day open for it either.
    """
    game = _board_game()
    clicks = 0
    while True:
        legal = [(s, r) for s in range(C.BOARD_OFFERS) for r in range(len(RARITIES))
                 if game.can_remodel(s, r)]
        if not legal:
            break
        slot, rarity = legal[0]
        game.remodel(slot, rarity)
        clicks += 1
        assert clicks <= C.BOARD_OFFERS * C.CLICKS_PER_FLOORPLAN, "board never ran out"
    assert clicks == C.BOARD_OFFERS * C.CLICKS_PER_FLOORPLAN

    assert not any(entry[0] == "remodel" for entry in game._in_place_actions())


def test_the_board_is_only_usable_from_inside_the_conservatory():
    """The drawing board is furniture: the actions gate on standing at the
    room's own cell (Capability.DRAWING_BOARD), not merely on having drafted
    it, the same shape the Office terminal and Pump Room panel use."""
    game = _board_game()
    assert game.can_remodel(0, 0)
    game.state.pos = DRAFT_FROM
    assert not game.can_remodel(0, 0)


def test_the_board_is_illegal_outside_navigate():
    """Every other phase owns its own menu, so a board click must not be legal
    mid-draft -- the guard ``Game.remodel``'s assertion enforces."""
    game = _board_game()
    game.open_door(CONSERVATORY_CELL, N)
    assert game.phase is Phase.DRAFTING
    assert not game.can_remodel(0, 0)
    with pytest.raises(AssertionError):
        game.remodel(0, 0)


def test_a_modified_room_stays_eligible_for_a_later_board():
    """Owner ruling, overriding the datamined filter chain: "the modified room
    can be modified in future days", so a room whose rarity has been set is NOT
    dropped from later offers and the pool never shrinks as rooms are used."""
    game = _board_game()
    room_id = game.state.remodel_offers[0]
    before = C.remodel_pool(game)
    game.remodel(0, (game.registry.by_id[room_id].rarity_idx + 1) % len(RARITIES))
    assert C.remodel_pool(game) == before
    assert room_id in C.remodel_pool(game)


def test_the_pool_drops_the_datamined_exclusions():
    """data/conservatory.json's ``always_excluded`` list is honoured (the
    DataMinedBox's unconditional drops plus the Conservatory itself), and the
    ``draft_gated`` list is honoured until that room has been drafted."""
    game = _board_game()
    rules = C.load_remodel_rules(game.registry.data_dir)
    pool = set(C.remodel_pool(game))
    assert rules.always_excluded
    assert not (pool & rules.always_excluded)
    for rid in rules.draft_gated:
        assert rid not in pool
        game.state.draft_counts[rid] = 1
    assert set(rules.draft_gated) <= set(C.remodel_pool(game))


def test_the_pool_is_the_days_draft_pool():
    """A room the day's decks do not contain has no rarity bucket to move
    between, so the board's pool is ``decks.eligible_pool`` minus the data
    file's exclusions -- never a wider registry sweep."""
    game = _board_game()
    assert set(C.remodel_pool(game)) <= {r.id for r in eligible_pool(game.registry, game.cfg)}


def test_no_board_stocking_consumes_rng_without_a_conservatory():
    """The board's substream is touched only when the Conservatory is drafted,
    so an ordinary day is bit-identical with the mechanic present -- the guard
    against an unconditional RNG consumption shifting every other roll."""
    game = Game(all_unlocks_config(), seed=0)
    game.reset(0)
    before = game.rng.stream(C.RNG_LABEL).getstate()
    game.state.steps = 999
    game.open_door(DRAFT_FROM, DRAFT_DIR)
    assert game.rng.stream(C.RNG_LABEL).getstate() == before


def test_deck_cards_are_conserved_by_a_click():
    """A remodel MOVES the room's cards between rarity decks of its own
    free/gem class; it never creates or destroys one, the solitaire invariant
    decks.py rests on."""
    game = _board_game()

    def by_class(gem_bit: int) -> list[int]:
        return sorted(c for i in range(gem_bit, 8, 2) for c in game.state.decks[i].order)

    before = [by_class(0), by_class(1)]
    game.remodel(0, (game.registry.by_id[game.state.remodel_offers[0]].rarity_idx + 1) % 4)
    assert [by_class(0), by_class(1)] == before


def test_conservatory_is_category_green():
    """The Conservatory's own ``category`` is "green" (a plain data fix: the
    wiki's infobox and the Green Rooms page both list it), so is_category
    matches it on "green" without needing any extra_categories."""
    game = Game(GameConfig(), seed=0)
    conservatory = game.registry.by_id[C.CONSERVATORY_ID]
    assert conservatory.category == "green"
    assert conservatory.is_category("green")
    assert conservatory.categories == frozenset({"green"})


def test_conservatory_counts_as_green_for_indoor_nursery_bonus():
    """Indoor Nursery's "+2 gems for each GREEN ROOM you draft" (not counting
    its own draft) fires when the Conservatory is drafted, now that green
    membership is honoured wherever it matters, not just where convenient.
    """
    cfg = GameConfig()
    game = Game(cfg, seed=0)
    indoor_nursery = game.registry.by_id["indoor_nursery__ix103"]
    conservatory = game.registry.by_id[C.CONSERVATORY_ID]
    game._place_room(indoor_nursery, 1, indoor_nursery.door_mask)
    before = game.state.gems
    game._place_room(conservatory, CONSERVATORY_CELL, S)
    assert game.state.gems == before + 2, (
        "drafting the Conservatory should grant Indoor Nursery's per-green-room bonus"
    )


def test_build_decks_is_the_only_reader_of_the_permanent_record():
    """A remodel's cross-day effect goes entirely through
    ``GameConfig.permanent_rarity`` and ``build_decks``: seeding a fresh
    config with the recorded dict reproduces the moved bucket exactly, with no
    second channel needed."""
    cfg = all_unlocks_config()
    registry = Game(cfg, seed=0).registry
    room = next(r for r in eligible_pool(registry, cfg) if r.rarity_idx != 3)
    cfg.permanent_rarity = {room.id: 3}
    decks = build_decks(registry, cfg, Game(cfg, seed=2).rng)
    assert decks[3 * 2 + (0 if room.is_free else 1)].order.count(room.idx) == room.deck_copies
