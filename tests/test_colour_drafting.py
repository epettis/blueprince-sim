"""Colour-selective drafting (Secret Passage / Spare Secret Passage).

Wiki (blueprince.wiki.gg/wiki/Secret_Passage, /wiki/Drafting_effects): pulling
a book restricts the whole hand dealt from the revealed door to one of five
colours (Bedroom, Hallway, Green Room, Shop, Red Room); a thin colour falls
back to the published default triple. See docs/open_tasks.md's 2026-08-10
ruling for the exact scope (filter + defaults, no reserve copies).
"""

from __future__ import annotations

import random

import pytest

from blueprince_sim.engine.draft import (COLOUR_CATEGORIES, DraftContext,
                                         room_draftable)
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S
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
    assert not any(mask_before[A.CHOOSE_COLOUR_BASE:A.N_ACTIONS])

    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING
    mask_pending = A.action_mask(g)
    colour_slice = mask_pending[A.CHOOSE_COLOUR_BASE:A.N_ACTIONS]
    assert colour_slice == [True] * len(COLOUR_CATEGORIES)
    # Nothing else is legal while a colour pick is outstanding.
    assert sum(mask_pending) == len(COLOUR_CATEGORIES)

    g.choose_colour("red")
    assert g.phase is Phase.DRAFTING
    mask_after = A.action_mask(g)
    assert not any(mask_after[A.CHOOSE_COLOUR_BASE:A.N_ACTIONS])


def test_colour_choice_action_unavailable_at_an_ordinary_doorway(cfg):
    """An ordinary (non-Secret-Passage) doorway never routes through
    COLOUR_PENDING, so the choose-colour ids stay masked off after opening it."""
    g = Game(cfg, seed=6)
    doors = g.open_doorways()
    assert doors, "Entrance Hall must have at least one open doorway at day start"
    g.open_door(*doors[0])
    assert g.phase is Phase.DRAFTING
    mask = A.action_mask(g)
    assert not any(mask[A.CHOOSE_COLOUR_BASE:A.N_ACTIONS])


def test_day_replays_clean_through_colour_pending(cfg):
    """A masked-random rollout that forces a Secret Passage onto the grid
    reaches a normal termination with no crash and no illegal action, even
    though it must pass through the new COLOUR_PENDING phase along the way."""
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
            action = rng.choice(legal)
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
