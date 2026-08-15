"""Colour-selective drafting (Secret Passage / Spare Secret Passage).

Wiki (blueprince.wiki.gg/wiki/Secret_Passage, /wiki/Drafting_effects): pulling
a book restricts the whole hand dealt from the revealed door to one of five
colours (Bedroom, Hallway, Green Room, Shop, Red Room); a thin colour falls
back to the published default triple. See docs/drafting.md for the exact
scope (filter + defaults, no reserve copies).
"""

from __future__ import annotations

import random

import pytest

from blueprince_sim.engine.draft import (COLOUR_CATEGORIES, DraftContext,
                                         room_draftable)
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import DIRS, N, S
from blueprince_sim.engine.locks import DOOR_LOCKED
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv

SECRET_PASSAGE_CELL = 7  # rank 2, col 2: interior, doorway north targets cell 12 (empty)


def _place_secret_passage(g: Game, room_id: str = "secret_passage",
                          cell: int = SECRET_PASSAGE_CELL) -> None:
    """Place ``room_id`` (straight layout) at ``cell`` oriented N|S and stand there."""
    room = g.registry.by_id[room_id]
    g._place_room(room, cell, N | S)
    g.state.pos = cell


@pytest.mark.parametrize("colour", COLOUR_CATEGORIES)
def test_choosing_a_colour_restricts_every_option_to_that_colour(cfg, colour):
    """Every option in the dealt hand carries the chosen colour, for all five colours."""
    g = Game(cfg, seed=1)
    _place_secret_passage(g)
    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING
    pending = g.choose_colour(colour)
    assert g.phase is Phase.DRAFTING
    assert pending.options, "a colour-selective hand must still deal something"
    for opt in pending.options:
        room = g.registry.rooms[opt.room_idx]
        assert room.is_category(colour), f"{room.id!r} is not a {colour!r} room"


def test_thin_colour_falls_back_to_published_defaults_not_off_colour(cfg):
    """With every deck drained, the hand falls back to the published default
    triple (never an off-colour room, and never nothing) -- reserve copies
    are out of scope, so the defaults are the whole thin-pool answer."""
    g = Game(cfg, seed=2)
    _place_secret_passage(g)
    for deck in g.state.decks:
        deck.order = []
    g.open_door(SECRET_PASSAGE_CELL, N)
    pending = g.choose_colour("shop")
    dealt_ids = [g.registry.rooms[o.room_idx].id for o in pending.options]
    assert dealt_ids, "the forced-Closet safety net must not be needed here"
    for rid in dealt_ids:
        shop_defaults = g.registry.priority["colour_defaults"]["triples"]["shop"]
        assert rid in shop_defaults, f"{rid!r} is not one of the shop defaults"
    # Slot 0's default is placed with its cost waived, matching the wiki's
    # "placing a special floorplan in that slot and waiving its cost".
    slot0 = next(o for o in pending.options if o.slot == 0)
    assert slot0.gem_cost == 0


def test_exhausted_colour_defaults_leave_the_slot_unfilled_not_off_colour(cfg):
    """When every deck is drained AND all three of a colour's published
    defaults are already on the grid, the colour-selective fallback ladder
    (pool -> defaults) is fully exhausted -- the hand must come up empty,
    never fall through to the universal forced-Closet: Closet's category is
    "blueprint", never one of the five selectable colours, and the wiki
    states the colour invariant ("only floorplans of that color can be
    drawn") with no exhaustion exception
    (blueprince.wiki.gg/wiki/Drafting_effects#Color-selective_drafting).

    An empty hand must also be *escapable*: Game.choose_colour falls back to
    NAVIGATE (see its docstring) rather than parking in DRAFTING with nothing
    to choose, which would leave every action illegal -- unsurvivable for a
    masked policy. Asserting only emptiness would pass even if the game
    deadlocked there, since it never checks that any action remains; this
    checks the escape itself."""
    g = Game(cfg, seed=9)
    _place_secret_passage(g)
    for deck in g.state.decks:
        deck.order = []
    # "red"'s three published defaults (gymnasium, darkroom, chapel) are all
    # already on the grid, so room_draftable's one-copy rule blocks every one
    # of them for every slot -- the fallback ladder has nothing left to try.
    g.placed_ids |= {"gymnasium", "darkroom", "chapel"}
    g.open_door(SECRET_PASSAGE_CELL, N)
    pending = g.choose_colour("red")  # must not raise
    assert pending is None, "every red default was exhausted; the deal must not happen at all"
    assert g.phase is Phase.NAVIGATE, (
        "an exhausted deal must fall back to NAVIGATE, not park in DRAFTING")
    mask = A.action_mask(g)
    assert sum(mask) > 0, "the exhausted-deal state must still have a legal action (no deadlock)"


@pytest.mark.parametrize("colour", COLOUR_CATEGORIES)
def test_aquarium_counts_for_every_colour_in_colour_selective_draft(registry, cfg, colour):
    """The Aquarium ("every color of room") passes room_draftable's colour gate
    for all five colours, the same gate every colour-selective slot deals through."""
    aquarium = registry.by_id["aquarium"]
    ctx = DraftContext(GameState(), registry, cfg, Rng(0), set(), None, colour=colour)
    assert room_draftable(ctx, aquarium, 12, N, set())


def test_spare_secret_passage_behaves_identically(cfg):
    """"The effects of the Spare Secret Passage ... are identical to the
    originals in each case": the Spare variant restricts its hand to the
    chosen colour exactly like the base Secret Passage."""
    g = Game(cfg, seed=3)
    _place_secret_passage(g, room_id="spare_secret_passage__ix138")
    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING
    pending = g.choose_colour("green")
    assert g.phase is Phase.DRAFTING
    assert pending.options
    for opt in pending.options:
        assert g.registry.rooms[opt.room_idx].is_category("green")


def test_secret_passage_never_dealt_during_its_own_colour_selective_draft(cfg):
    """"The Secret Passage cannot itself be drawn during a color-selective
    draft" -- true even for the hallway-colour pick, which is the Secret
    Passage's own category."""
    g = Game(cfg, seed=4)
    _place_secret_passage(g)
    for deck in g.state.decks:
        deck.order = []
    g.open_door(SECRET_PASSAGE_CELL, N)
    pending = g.choose_colour("hallway")
    dealt_ids = {g.registry.rooms[o.room_idx].id for o in pending.options}
    assert "secret_passage" not in dealt_ids
    assert "spare_secret_passage__ix138" not in dealt_ids


def test_colour_choice_is_masked_only_in_colour_pending(cfg):
    """The five choose-colour ids are legal only in COLOUR_PENDING; the
    action is unavailable both before the Secret Passage door is opened and
    after a colour has already been picked (back in DRAFTING)."""
    g = Game(cfg, seed=5)
    _place_secret_passage(g)

    mask_before = A.action_mask(g)
    assert not any(mask_before[A.CHOOSE_COLOUR_BASE:A.DONATE_BASE])

    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING
    mask_pending = A.action_mask(g)
    colour_slice = mask_pending[A.CHOOSE_COLOUR_BASE:A.DONATE_BASE]
    assert colour_slice == [True] * len(COLOUR_CATEGORIES)
    # Nothing else is legal while a colour pick is outstanding.
    assert sum(mask_pending) == len(COLOUR_CATEGORIES)

    g.choose_colour("red")
    assert g.phase is Phase.DRAFTING
    mask_after = A.action_mask(g)
    assert not any(mask_after[A.CHOOSE_COLOUR_BASE:A.DONATE_BASE])


def test_colour_choice_action_unavailable_at_an_ordinary_doorway(cfg):
    """An ordinary (non-Secret-Passage) doorway never routes through
    COLOUR_PENDING, so the choose-colour ids stay masked off after opening it."""
    g = Game(cfg, seed=6)
    doors = g.open_doorways()
    assert doors, "Entrance Hall must have at least one open doorway at day start"
    g.open_door(*doors[0])
    assert g.phase is Phase.DRAFTING
    mask = A.action_mask(g)
    assert not any(mask[A.CHOOSE_COLOUR_BASE:A.DONATE_BASE])


def _targets_a_locked_door(env: BluePrinceEnv, action: int) -> bool:
    """True for a draft (open-doorway) action id whose segment is DOOR_LOCKED.

    A locked doorway is now always legal to TRY (Phase.LOCK_PENDING; trying
    costs nothing) even at 0 keys, so unlike before this PR "legal to open"
    no longer implies "opening it makes progress" -- see the rollout below.
    """
    cell, dir_idx = divmod(action, 4)
    return env.game.door_state_of(cell, DIRS[dir_idx]) == DOOR_LOCKED


def test_day_replays_clean_through_colour_pending(cfg):
    """A masked-random rollout that forces a Secret Passage onto the grid
    reaches a normal termination with no crash and no illegal action, even
    though it must pass through the new COLOUR_PENDING phase along the way.

    Excludes locked doorways from the "prefer opening a door" bias (see
    _targets_a_locked_door): trying one is always legal now, at any key
    count, so blindly preferring it here would deterministically loop
    open(locked, free) -> LOCK_PENDING -> abandon (free) -> NAVIGATE ->
    open(the SAME locked door) forever whenever it is the only doorway
    action offered, burning the whole rollout budget without ever spending
    a step. That loop is a real, intended consequence of the owner's
    walk-away ruling, not a bug -- this test is about COLOUR_PENDING
    pass-through, not lock choice-making (see test_locks.py for that), so
    it steers around locked doors here instead of learning to resolve them.
    """
    rng = random.Random(11)
    for seed in range(5):
        env = BluePrinceEnv(cfg)
        env.reset(seed=seed)
        _place_secret_passage(env.game)
        reached_colour_pending = False
        for _ in range(400):
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            assert legal, f"seed {seed}: all-zero mask in phase {env.game.phase.name}"
            if env.game.phase is Phase.COLOUR_PENDING:
                reached_colour_pending = True
            # Prefer opening an UNLOCKED doorway while navigating: the point
            # of this rollout is to pass THROUGH colour selection, and a
            # purely random walk only reaches the forced Secret Passage by
            # luck once the action space is wide enough to wander instead.
            open_doors = [i for i in legal
                          if i < A.CHOOSE_BASE and not _targets_a_locked_door(env, i)]
            action = rng.choice(open_doors or legal)
            _, _, term, trunc, _ = env.step(action)
            if term or trunc:
                break
        assert env.game.phase is Phase.TERMINAL
        assert reached_colour_pending, f"seed {seed}: never opened the forced Secret Passage door"


def test_same_seed_same_hand(cfg):
    """Two independently-built games with the same seed, doorway, and chosen
    colour deal an identical hand -- the colour filter consumes RNG the same
    deterministic way every time."""
    def _deal(seed: int):
        g = Game(cfg, seed=seed)
        _place_secret_passage(g)
        g.open_door(SECRET_PASSAGE_CELL, N)
        return g.choose_colour("bedroom")

    a = _deal(42)
    b = _deal(42)
    a_shape = [(o.slot, o.room_idx, o.orientation, o.gem_cost, o.forced) for o in a.options]
    b_shape = [(o.slot, o.room_idx, o.orientation, o.gem_cost, o.forced) for o in b.options]
    assert a_shape == b_shape


def test_redraw_keeps_the_hand_on_colour(cfg):
    """Redrawing a colour-selective hand (die/study/free) stays locked to the
    original colour rather than reverting to an ordinary unrestricted draw."""
    from blueprince_sim.engine.game import RedrawKind

    g = Game(cfg, seed=8)
    _place_secret_passage(g)
    g.open_door(SECRET_PASSAGE_CELL, N)
    g.choose_colour("red")
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)
    assert g.state.pending.colour == "red"
    for opt in g.state.pending.options:
        assert g.registry.rooms[opt.room_idx].is_category("red")


# ------------------------------------------------------- the free first option

#: The green defaults (priority_draws.json::colour_defaults), parked on the grid
#: by _only_a_gem_green_is_dealable so the fallback ladder's last rung is closed.
GREEN_DEFAULTS = ("courtyard", "aquarium", "cloister")


def _only_a_gem_green_is_dealable(g: Game, monkeypatch) -> None:
    """Rig the decks so a green hand can only fill its Gem-Draw slot.

    Empties every free deck, so a Free Draw slot has nothing to deal and slot
    0 -- whose deck-size gate looks at the free deck alone (decks.py::
    rarity_deck_ok) -- cannot even roll a rarity; parks the three green
    defaults on the grid, so ``_deal_colour_default`` is closed too. The
    Solarium's gem deck is the only one left passing its size gate, padded to
    that gate with off-colour rooms the colour filter drops, so the rarity
    roll can only land there. Pins the round's Free/Gem decision to "slot 2 is
    a Gem Draw" (a published outcome of weights.json::free_gem_draws -- every
    round of 3+, and most rank rolls -- but a rolled one, so it is fixed here
    rather than hunted for in a seed).
    """
    solarium = g.registry.by_id["solarium"]
    padding = [g.registry.by_id[rid].idx for rid in ("kitchen", "locksmith", "chapel")]
    gate = g.registry.weights["deck_size_gates"]["gem"][solarium.rarity_idx]
    for rarity_idx in range(4):
        for is_gem in (False, True):
            deck = g.state.deck(rarity_idx, is_gem)
            deck.order = []
            deck.pos = 0
    gem_deck = g.state.deck(solarium.rarity_idx, True)
    gem_deck.order = [solarium.idx] + (padding * gate)[:gate - 1]
    g.placed_ids |= set(GREEN_DEFAULTS)
    g.state.gems = 0
    monkeypatch.setattr("blueprince_sim.engine.draft._resolve_free_gem",
                        lambda ctx, rank, round_num: (False, True))


def test_the_secret_passage_grants_its_first_option_free_from_a_later_slot(cfg, monkeypatch):
    """"The Secret Passage will grant the first option with zero cost, even if
    it would ordinarily cost gems" (owner ruling): the waiver follows the first
    option the hand actually presents, not the literal slot index 0. A
    colour-selective hand's slots fail independently, so slots 0 and 1 can come
    up unfilled while the Gem-Draw slot 2 deals a gem room -- and that room is
    then granted free even with no gems in hand. Pins the deal's shape too, so
    the test cannot pass without the later-slot case actually arising."""
    g = Game(cfg, seed=1)
    _place_secret_passage(g)
    _only_a_gem_green_is_dealable(g, monkeypatch)
    g.open_door(SECRET_PASSAGE_CELL, N)
    pending = g.choose_colour("green")
    assert pending is not None and g.phase is Phase.DRAFTING

    assert [o.slot for o in pending.options] == [2], (
        "the branch under test needs slots 0 and 1 unfilled and slot 2 dealt")
    first = pending.options[0]
    room = g.registry.rooms[first.room_idx]
    assert not room.is_free, "a free room would price at 0 anyway and test nothing"
    assert first.cost_waived and first.gem_cost == 0
    assert g._effective_cost(room, first) == 0
    assert g.state.gems == 0 and g.affordable(room, first)


def test_a_drafting_hand_always_offers_an_affordable_option(cfg, monkeypatch):
    """"Always allow a free option" (owner ruling). There is no decline, and
    every other DRAFTING action needs resources the player may not hold, so a
    hand with nothing affordable would leave the phase with an empty action
    mask -- unsurvivable for a masked policy. Checks the mask itself on the
    hand that used to have none, not just the option's price."""
    g = Game(cfg, seed=1)
    _place_secret_passage(g)
    _only_a_gem_green_is_dealable(g, monkeypatch)
    g.open_door(SECRET_PASSAGE_CELL, N)
    g.choose_colour("green")
    assert g.phase is Phase.DRAFTING
    assert any(g.affordable(g.registry.rooms[o.room_idx], o) for o in g.state.pending.options)
    mask = A.action_mask(g)
    assert mask[A.CHOOSE_BASE + 2], "the hand's only option must be choosable"
    g.choose(2)  # must not raise: the waiver is what makes this payable
    assert g.state.gems == 0, "a waived cost must not be charged"


def test_a_redraw_re_waives_the_new_hands_first_option(cfg, monkeypatch):
    """The waiver is applied per hand, not once per doorway: a redraw replaces
    every option, so the freshly dealt first option carries it and the discarded
    one keeps its own copy on the rewind stack. Guarding only the initial deal
    would let a redraw land on an unaffordable hand."""
    from blueprince_sim.engine.game import RedrawKind

    g = Game(cfg, seed=5)
    _place_secret_passage(g)
    for deck in g.state.decks:
        deck.order = []
    g.open_door(SECRET_PASSAGE_CELL, N)
    g.choose_colour("green")
    assert g.phase is Phase.DRAFTING, "the drained-pool hand must fall back to the defaults"
    assert g.state.pending.options[0].cost_waived

    g.state.pending.redraws_left = 1
    _only_a_gem_green_is_dealable(g, monkeypatch)
    g.redraw(RedrawKind.FREE)
    assert [o.slot for o in g.state.pending.options] == [2], (
        "the redealt hand must be the later-slot-only one, or nothing is being tested")
    assert g.state.pending.options[0].cost_waived
    assert sum(A.action_mask(g)) > 0
    assert g.state.pending.rewind_stack[-1][0].cost_waived, (
        "the discarded hand keeps its own waiver, so a rewind restores a takeable hand")


def test_an_ordinary_hand_waives_slot_0_and_prices_the_rest(cfg):
    """The free-first-option rule is a no-op on an ordinary hand: options are
    built in slot order, so the waiver lands on slot 0, whose cost the deal
    already zeroes. Slots 1 and 2 are left unwaived, which is what stops the
    rule from quietly making a whole hand free."""
    g = Game(cfg, seed=11)
    g.open_door(g.state.pos, next(d for c, d in g.open_doorways() if c == g.state.pos))
    options = g.state.pending.options
    assert [o.slot for o in options] == [0, 1, 2], "an ordinary hand deals all three slots"
    assert options[0].cost_waived and options[0].gem_cost == 0
    assert not any(o.cost_waived for o in options[1:])
