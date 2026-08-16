"""Conservatory drawing board (the remodel) and its 15% Forced Draw.

Drafting the Conservatory stocks a three-row drawing board
(``conservatory.stock_drawing_board``, ``Hook.ON_PLACE``); standing in the
room, each row may be clicked ``CLICKS_PER_FLOORPLAN`` times to set that
floorplan's rarity permanently (``Game.can_remodel``/``Game.remodel``), writing
the same ``state.permanent_rarity`` slot the Gear Wrench writes.

The Forced Draw section at the bottom covers data/priority_draws.json's
``forced_draws`` conservatory entry (blueprince.wiki.gg/wiki/Conservatory; see
draft.py's ``_forced_draw``). Reachability -- the Found Floorplan gate that
puts the room in the pool at all -- lives in
tests/test_conservatory_reachability.py.

Every scenario here is built deterministically -- the Conservatory is placed
directly at a chosen cell, or a corridor is hand-placed to make the doorway
under test exist -- rather than by hunting a seed that happens to draft it.
"""

from __future__ import annotations

from collections import Counter

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import build_decks, eligible_pool
from blueprince_sim.engine.draft import deal_draft, redeal
from blueprince_sim.engine.effects.rooms import conservatory as C
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.model import RARITIES
from blueprince_sim.engine.rng import Rng
from blueprince_sim.rl.train import all_unlocks_config

GARAGE_ID = "garage"

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


# ---------------------------------------------------------------------------
# Forced Draw
# ---------------------------------------------------------------------------

# The Conservatory is corner-only (rooms.json draft_conditions "corner_only"),
# so cells 0/4/40/44 are the only ones it can ever be dealt at. Cell 0 is
# reached from cell 1 heading west and cell 4 from cell 3 heading east; the
# corner layout's rotations supply the door facing back at either doorway, so
# geometry never rules the room out and only the mechanic is under test.
CORNER_SRC_A, CORNER_DIR_A, CORNER_CELL_A = 1, W, 0
CORNER_SRC_B, CORNER_DIR_B, CORNER_CELL_B = 3, E, 4
# Rank-2 centre column heading north: never a corner, so the mechanic must not
# fire -- and must not even roll -- there.
OFF_CORNER_SRC = 7
# The doorway the Garage's own Forced Draw always covers (West Wing, rank 4->5,
# entered north), borrowed from tests/rooms/test_garage.py.
GARAGE_SRC = 15
FORCED_DRAW_STREAM = "forced_draw_conservatory"
FORCED_CHANCE = 0.15
FORCED_N = 2000  # ~0.8pp standard error on a 15% rate
# Arms whose own assertion is an exact equality need no statistical power of
# their own, so they run a cheaper sample.
FORCED_N_SMALL = 600
FORCED_ALPHA = 0.001  # two-sided binomial; deliberately loose, the arms are huge


def _forced_cfg(**kw) -> GameConfig:
    """Config for the Forced Draw doorways below: locks off so every open_door
    actually deals, steps to spare, and (unless a test says otherwise) the
    Conservatory's Found Floorplan already in hand so the room is in the pool."""
    kw.setdefault("conservatory_floorplan_found", True)
    kw.setdefault("day", 20)
    return GameConfig(door_locks=False, starting_steps=50, **kw)


def _deal_at(cfg: GameConfig, seed: int, src: int, direction: int):
    """Deal one real hand at ``(src, direction)`` through Game.open_door.

    The source cell gets a hand-placed corridor carrying the doorway's own
    axis, mirroring tests/rooms/test_garage.py -- the doorway exists because
    the test put it there, never because a seed happened to draft it.
    """
    game = Game(cfg, seed=seed)
    corridor = game.registry.by_id["corridor"]
    game._place_room(corridor, src, (N | S) if direction in (N, S) else (E | W))
    game.state.pos = src
    return game, game.open_door(src, direction)


def _forced_hits(cfg: GameConfig, src: int, direction: int, n: int = FORCED_N,
                 room_id: str = C.CONSERVATORY_ID, seed0: int = 0) -> int:
    """Hands out of ``n`` whose slot 2 holds ``room_id`` as a forced option.

    Filtering on ``forced and slot == 2`` measures the Forced Draw itself
    rather than the ordinary deal, which can also surface the room once it is
    in the pool.
    """
    idx = Game(cfg, seed=0).registry.by_id[room_id].idx
    hits = 0
    for seed in range(seed0, seed0 + n):
        _game, pending = _deal_at(cfg, seed, src, direction)
        hits += any(o.room_idx == idx and o.forced and o.slot == 2 for o in pending.options)
    return hits


def _assert_published_rate(hits: int, n: int = FORCED_N) -> None:
    """Fail unless ``hits``/``n`` is consistent with the published 15%."""
    p = stats.binomtest(hits, n, FORCED_CHANCE).pvalue
    assert p > FORCED_ALPHA, (
        f"offer rate {hits}/{n} = {hits / n:.4f} is inconsistent with the "
        f"published {FORCED_CHANCE:.0%} (two-sided binomial p={p:.2g})")


def test_forced_draw_offer_rate_matches_the_published_15_percent():
    """A corner doorway offers the Conservatory in slot 3 at the wiki's rate:
    "This is a Forced Draw, with a 15% chance of occurring; there are no
    additional conditions." Pinned by a two-sided binomial test rather than a
    hand-picked band, so substituting any other published forced-draw constant
    (the Garage's 90% / 92.5%) or dropping the roll fails outright."""
    _assert_published_rate(_forced_hits(_forced_cfg(), CORNER_SRC_A, CORNER_DIR_A))


def test_forced_draw_fires_at_every_corner_not_just_one():
    """The second corner doorway rolls at the same published rate as the first:
    the mechanic keys off the room's own ``corner_only`` draft condition, so it
    must not end up pinned to whichever cell the first test happened to use."""
    _assert_published_rate(
        _forced_hits(_forced_cfg(), CORNER_SRC_B, CORNER_DIR_B, seed0=10_000_000))


def test_forced_draw_never_fires_off_a_corner():
    """Off a doorway where the Conservatory's own draft conditions fail, the
    Forced Draw must not fire -- and must consume no randomness, so a doorway
    where the room was never a candidate cannot perturb any other draw's RNG
    stream (the contract the Garage's Forced Draw and the Foundation's rank-3
    roll already hold to)."""
    cfg = _forced_cfg()
    assert _forced_hits(cfg, OFF_CORNER_SRC, N, n=200) == 0
    for seed in range(50):
        game, _pending = _deal_at(cfg, seed, OFF_CORNER_SRC, N)
        assert FORCED_DRAW_STREAM not in game.rng._streams, (
            "a non-corner doorway must not consume the forced-draw RNG stream")


def test_forced_draw_needs_the_found_floorplan():
    """Forced Draws "still require the room to be present in the draft pool":
    without ``conservatory_floorplan_found`` the room is in no deck
    (decks.py::eligible_pool), so the mechanic must neither fire nor roll.
    Otherwise the Forced Draw would smuggle an unearned room onto the grid,
    routing around the entire Found Floorplan gate."""
    cfg = GameConfig(door_locks=False, starting_steps=50, day=20)
    assert cfg.conservatory_floorplan_found is False, "setup: floorplan must be unfound"
    assert _forced_hits(cfg, CORNER_SRC_A, CORNER_DIR_A, n=500) == 0
    for seed in range(50):
        game, _pending = _deal_at(cfg, seed, CORNER_SRC_A, CORNER_DIR_A)
        assert FORCED_DRAW_STREAM not in game.rng._streams, (
            "a room outside today's pool must not consume the forced-draw RNG stream")


def test_forced_draw_has_no_day_or_veteran_gate():
    """"There are no additional conditions": unlike the Garage's Forced Draw,
    which needs Veteran Mode or day 3, the Conservatory's day-2 rate with
    Veteran Mode off equals its late-game rate. Both arms run the same seeds
    through the same labelled substream, so a day gate shows up as a collapse
    to zero rather than as noise."""
    early = _forced_hits(_forced_cfg(day=2, veteran_mode=False), CORNER_SRC_A,
                         CORNER_DIR_A, n=FORCED_N_SMALL)
    late = _forced_hits(_forced_cfg(day=20), CORNER_SRC_A, CORNER_DIR_A, n=FORCED_N_SMALL)
    assert early == late, f"day 2 ({early}) and day 20 ({late}) must roll identically"
    _assert_published_rate(early, FORCED_N_SMALL)


def test_forced_draw_is_not_once_per_day():
    """Drafting/Advanced names only the Garage and the Utility Closet in "only
    appear as a Forced Draw once per day", so a Conservatory success must never
    retire the entry: its id stays out of ``forced_draws_succeeded_today`` even
    on the hands where the draw actually fired."""
    cfg = _forced_cfg()
    idx = Game(cfg, seed=0).registry.by_id[C.CONSERVATORY_ID].idx
    fired = 0
    for seed in range(200):
        game, pending = _deal_at(cfg, seed, CORNER_SRC_A, CORNER_DIR_A)
        fired += any(o.room_idx == idx and o.forced and o.slot == 2 for o in pending.options)
        assert C.CONSERVATORY_ID not in game.state.forced_draws_succeeded_today
    assert fired > 0, "setup: the sampled seeds must contain at least one success"


def test_a_second_corner_the_same_day_rolls_again(monkeypatch):
    """"[It] can try again if drafting again in a new location": with the roll
    pinned to succeed, one game deals BOTH corner doorways on the same day and
    both hands carry the forced Conservatory -- the mechanic is spent per
    doorway, not per day."""
    real_chance = Rng.chance
    monkeypatch.setattr(Rng, "chance", lambda self, label, p: (
        True if label == FORCED_DRAW_STREAM else real_chance(self, label, p)))
    cfg = _forced_cfg()
    game = Game(cfg, seed=0)
    idx = game.registry.by_id[C.CONSERVATORY_ID].idx

    def forced_slot2(pending) -> bool:
        return any(o.room_idx == idx and o.forced and o.slot == 2 for o in pending.options)

    first = deal_draft(game.state, game.registry, cfg, game.rng, game.placed_ids,
                       CORNER_SRC_A, CORNER_DIR_A, CORNER_CELL_A)
    second = deal_draft(game.state, game.registry, cfg, game.rng, game.placed_ids,
                        CORNER_SRC_B, CORNER_DIR_B, CORNER_CELL_B)
    assert forced_slot2(first) and forced_slot2(second), (
        "both corners of the same day must force-draw the Conservatory")


def test_forced_draw_does_not_re_roll_on_a_redraw():
    """"If the chance to appear fails, it does not try again on redraws": the
    doorway, not the hand, is what a roll is spent against, so redealing the
    same hand leaves the forced-draw substream exactly where it was. Without
    this the published 15% would compound with every Study/Classroom redraw
    taken at a corner."""
    cfg = _forced_cfg()
    game = Game(cfg, seed=0)
    pending = deal_draft(game.state, game.registry, cfg, game.rng, game.placed_ids,
                         CORNER_SRC_A, CORNER_DIR_A, CORNER_CELL_A)
    assert (C.CONSERVATORY_ID, CORNER_CELL_A, CORNER_DIR_A) \
        in game.state.forced_draws_rolled_today, (
        "setup: the initial deal must have spent this doorway's roll")
    before = game.rng.stream(FORCED_DRAW_STREAM).getstate()
    redeal(game.state, game.registry, cfg, game.rng, game.placed_ids, pending)
    assert game.rng.stream(FORCED_DRAW_STREAM).getstate() == before, (
        "a redraw of the same doorway must not spend a second forced-draw roll")


def test_a_retired_garage_forced_draw_does_not_suppress_the_conservatory():
    """The once-per-day record is keyed per room id rather than held in one
    shared flag, so a day on which the Garage's Forced Draw already succeeded
    leaves the Conservatory's corner rate untouched. A shared flag would zero
    this arm outright."""
    cfg = _forced_cfg()
    idx = Game(cfg, seed=0).registry.by_id[C.CONSERVATORY_ID].idx
    hits = 0
    for seed in range(FORCED_N):
        game = Game(cfg, seed=seed)
        game.state.forced_draws_succeeded_today.add(GARAGE_ID)
        game._place_room(game.registry.by_id["corridor"], CORNER_SRC_A, E | W)
        game.state.pos = CORNER_SRC_A
        pending = game.open_door(CORNER_SRC_A, CORNER_DIR_A)
        hits += any(o.room_idx == idx and o.forced and o.slot == 2 for o in pending.options)
    _assert_published_rate(hits)


def test_the_conservatory_does_not_suppress_the_garage():
    """The Conservatory outranks the Garage in ``forced_draw_precedence``, but
    blocking is positional -- an entry blocks only where it is itself available
    at the doorway being drawn. Its corners {0, 4, 40, 44} never meet the
    Garage's West Wing ranks 4-8 {15, 20, 25, 30, 35}, so putting the
    Conservatory in the pool must leave the Garage's own forced-draw rate
    byte-identical, not merely close."""
    with_conservatory = _forced_hits(_forced_cfg(day=5, veteran_mode=False),
                                     GARAGE_SRC, N, n=FORCED_N_SMALL, room_id=GARAGE_ID)
    without = _forced_hits(
        GameConfig(door_locks=False, starting_steps=50, day=5, veteran_mode=False),
        GARAGE_SRC, N, n=FORCED_N_SMALL, room_id=GARAGE_ID)
    assert with_conservatory == without > 0, (
        "the Conservatory changed the Garage's forced-draw rate: "
        f"{with_conservatory} vs {without}")


def test_forced_draw_is_deterministic_for_a_given_seed():
    """Same seed, same corner doorway -> an identical dealt hand: the engine's
    seeded-replay invariant, which the new labelled substream must not break."""
    cfg = _forced_cfg()

    def snapshot(seed: int):
        _game, pending = _deal_at(cfg, seed, CORNER_SRC_A, CORNER_DIR_A)
        return [(o.room_idx, o.orientation, o.gem_cost, o.slot, o.forced, o.hidden)
                for o in pending.options]

    for seed in (1, 2, 3, 42):
        assert snapshot(seed) == snapshot(seed), f"seed {seed} was not deterministic"
