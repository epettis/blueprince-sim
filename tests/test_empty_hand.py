"""A redeal that empties a colour-selective hand must not crash the engine.

Reproduces the SubprocVecEnv death from an overnight training run: a redraw
of a Secret Passage's colour-locked hand can legitimately come back with zero
options (the on-colour pool exhausted in both deck classes, and the published
default triple also exhausted), and ``Game._redeal_pending`` had no guard for
that -- it left ``phase`` at DRAFTING with an empty hand, so the next
``action_mask`` call crashed inside ``rotation_available``'s ``max()`` over
zero legal-orientation counts. See ``Game._redeal_pending``/``rotation_available``.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import PendingDraft
from blueprince_sim.env import actions as A

SECRET_PASSAGE_CELL = 7  # rank 2, col 2: interior, doorway north targets cell 12 (empty)

# priority_draws.json::colour_defaults' published "red" triple -- placing all
# three on the grid (via placed_ids) closes the colour fallback ladder's last
# rung, matching tests/test_colour_drafting.py's own exhaustion rig.
RED_DEFAULTS = ("gymnasium", "darkroom", "chapel")


def _place_secret_passage(g: Game, cell: int = SECRET_PASSAGE_CELL) -> None:
    """Place a Secret Passage at ``cell`` oriented N|S and stand there, so its
    north doorway drafts (colour-selective) into the empty cell beyond."""
    room = g.registry.by_id["secret_passage"]
    g._place_room(room, cell, N | S)
    g.state.pos = cell


def _empty_every_deck(g: Game) -> None:
    """Drain every one of the 8 solitaire decks, so no ordinary pool draw can
    fill a slot -- the same rig tests/test_colour_drafting.py uses to reach
    the published default-triple fallback."""
    for deck in g.state.decks:
        deck.order = []
        deck.pos = 0


def _open_red_hand(g: Game) -> PendingDraft:
    """Open the Secret Passage doorway and lock the hand to "red", via the
    real engine path (open_door -> COLOUR_PENDING -> choose_colour)."""
    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING
    pending = g.choose_colour("red")
    assert pending is not None and g.phase is Phase.DRAFTING
    return pending


def test_an_emptied_redraw_does_not_crash_action_mask(cfg):
    """The crash itself, reproduced through the real engine: a colour-locked
    redraw that empties the hand must leave the game in a state
    ``env.actions.action_mask`` can read without raising.

    Reached via genuine engine state, not monkeypatching: the initial hand is
    dealt through the real ``open_door``/``choose_colour`` path with full
    decks (so it is non-empty), then the pool is drained and every published
    "red" default parked on the grid before redrawing -- exactly the
    fallback-ladder exhaustion ``test_colour_drafting.py``'s own
    ``test_exhausted_colour_defaults_leave_the_slot_unfilled_not_off_colour``
    pins for an initial deal, applied here to a redraw instead.

    The Rotunda is placed first so ``rotation_available`` is actually called
    with a rotation source active and an empty hand, matching the training
    run's SubprocVecEnv worker at the moment it died.
    """
    g = Game(cfg, seed=8)
    g.rotunda_placed = True  # a free-rotation source, so action_mask reaches rotation_available
    _place_secret_passage(g)
    _open_red_hand(g)  # full decks: a real, non-empty initial hand

    _empty_every_deck(g)
    g.placed_ids |= set(RED_DEFAULTS)  # exhausts the colour fallback ladder too
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)  # must not raise, and must not leave a dead DRAFTING hand

    mask = A.action_mask(g)  # this is exactly where the training run crashed
    assert sum(mask) > 0, "an emptied redraw must not leave a deadlocked (all-False) mask"


def test_an_emptied_redraw_falls_back_to_navigate(cfg):
    """After a redeal empties the hand, the game must drop back to NAVIGATE
    with no pending draft -- the same escape ``open_door``/``choose_colour``
    already use for an empty initial deal -- rather than parking in DRAFTING
    with nothing to choose.
    """
    g = Game(cfg, seed=8)
    _place_secret_passage(g)
    _open_red_hand(g)

    _empty_every_deck(g)
    g.placed_ids |= set(RED_DEFAULTS)
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)

    assert g.phase is Phase.NAVIGATE
    assert g.state.pending is None


def test_an_emptied_redraw_evicts_the_doorway_cache(cfg):
    """A doorway whose redraw emptied the hand must forget that dead hand, so
    a later reopen re-deals instead of replaying it forever.

    After the emptied redraw, one of the three exhausted "red" defaults
    (Gymnasium) is freed back up while the drained decks are left empty.
    Reopening the same doorway then deals a hand containing exactly that
    default -- only possible if the doorway cache was evicted and a genuine
    re-deal ran; a stale cached (permanently empty) hand would still show
    zero options here.
    """
    g = Game(cfg, seed=8)
    _place_secret_passage(g)
    _open_red_hand(g)

    _empty_every_deck(g)
    g.placed_ids |= set(RED_DEFAULTS)
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)
    assert g.phase is Phase.NAVIGATE

    key = (SECRET_PASSAGE_CELL, N)
    assert key not in g.doorway_drafts, "the emptied hand must not stay cached"

    g.placed_ids.discard("gymnasium")  # reopen the fallback ladder's first rung
    g.open_door(SECRET_PASSAGE_CELL, N)
    assert g.phase is Phase.COLOUR_PENDING, "the doorway must ask for a colour again, not replay"
    pending = g.choose_colour("red")
    assert pending is not None and pending.options, "the doorway must genuinely re-deal"
    dealt_ids = {g.registry.rooms[o.room_idx].id for o in pending.options}
    assert dealt_ids == {"gymnasium"}, "only the just-freed default should be dealable here"


def test_rotation_available_on_an_empty_hand_returns_false(cfg):
    """Defense in depth: ``rotation_available`` must not raise on an empty
    hand no matter how the engine arrives there, pinned independently of the
    ``_redeal_pending`` guard by hand-building a DRAFTING state with a
    rotation source active and zero dealt options.

    Reverting the ``rotation_available`` early return (fix 3) alone still
    crashes this test with the original ``max()`` ``ValueError``, even though
    fix 1 keeps the real redraw path from ever reaching it.
    """
    g = Game(cfg, seed=1)
    g.rotunda_placed = True  # a free-rotation source, so the empty check is actually exercised
    g.phase = Phase.DRAFTING
    g.state.pending = PendingDraft(from_cell=g.state.pos, direction=N, target_cell=12, options=[])

    assert g.rotation_available() is False


def test_a_redraw_that_still_deals_options_stays_in_drafting(cfg):
    """No regression: an ordinary redraw that DOES produce options (full
    decks, no colour restriction) must leave the game exactly as before --
    still DRAFTING, with a pending hand the player can choose from.
    """
    g = Game(cfg, seed=12)
    doors = g.open_doorways()
    g.open_door(*doors[0])
    assert g.phase is Phase.DRAFTING
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)

    assert g.phase is Phase.DRAFTING
    assert g.state.pending is not None
    assert g.state.pending.options, "a full-deck redraw must still deal a usable hand"
    mask = A.action_mask(g)
    assert sum(mask) > 0
