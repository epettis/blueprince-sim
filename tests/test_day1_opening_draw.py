"""Day 1's opening draw: a Guaranteed Draw, not an ordinary rarity roll.

blueprince.wiki.gg/wiki/Drafting/Advanced, Special Draws > Guaranteed Draws:
"The very first draw on Day 1 is Bedroom, Closet, and Hallway in that order.
Ending Day 1 without drafting skips this forced draw." This is a DIFFERENT
mechanism from priority_draws/forced_draws/category_biases (see
tests/test_free_gem_draws.py and tests/test_draft_stats.py for those):
it fixes the whole three-slot hand at once, before the ordinary rank/rarity
ladder ever runs, and only for the very first draft of the very first day.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, ENTRANCE_CELL, N, S, W

# The wiki's own words, transcribed directly here rather than read from
# priority_draws.json or draft.py -- so a bug in the data OR the gate can
# never drag this expectation along with it (deterministic construction, not
# an expectation derived by calling the function under test).
WIKI_OPENING_TRIPLE = ("bedroom", "closet", "hallway")
DIRECTIONS = (N, E, S, W)

N_SEEDS = 150


def _open_first_available(game, cell, exclude_dirs=()):
    """Open the first of DIRECTIONS (skipping ``exclude_dirs``) that deals a hand.

    Returns ``(direction, pending)``, or ``(None, None)`` if every remaining
    direction is locked/unavailable for this seed -- some Entrance Hall doors
    roll locked, mirroring test_free_gem_draws.py's
    test_slot0_is_never_a_gem_room, which sees a dealt slot 0 at only ~75% of
    seeds through a single fixed direction.
    """
    for d in DIRECTIONS:
        if d in exclude_dirs:
            continue
        pending = game.open_door(cell, d)
        if pending is not None and pending.options:
            return d, pending
    return None, None


def test_day1_first_hand_is_the_published_triple_in_order(registry):
    """Across many seeds, the very first hand dealt on Day 1 -- whichever
    Entrance Hall doorway happens to be open first for that seed -- is
    exactly Bedroom (slot 0), Closet (slot 1), Hallway (slot 2): the wiki's
    Guaranteed Draw, not a rank/rarity roll. A single seed producing any
    other triple, a different order, or a short hand is a violation of this
    exact property (not a rate), and every dealt option must carry
    ``forced=True`` since a Guaranteed Draw bypasses the ordinary
    rarity-ladder attempts entirely."""
    hands_checked = 0
    for seed in range(N_SEEDS):
        game = Game(GameConfig(day=1), seed=seed, registry=registry)
        _direction, pending = _open_first_available(game, ENTRANCE_CELL)
        if pending is None:
            continue
        hands_checked += 1
        ids = tuple(registry.rooms[o.room_idx].id
                    for o in sorted(pending.options, key=lambda o: o.slot))
        assert ids == WIKI_OPENING_TRIPLE, (
            f"seed {seed}: Day 1's first hand was {ids}, not the published "
            f"opening triple {WIKI_OPENING_TRIPLE} in order"
        )
        assert all(o.forced for o in pending.options), (
            f"seed {seed}: Day 1's opening draw must mark every option "
            "forced -- it bypasses the ordinary rarity ladder entirely"
        )
    assert hands_checked > N_SEEDS // 2, (
        "setup: too few seeds produced a dealt Day 1 opening hand"
    )


def test_day1_second_draft_is_not_fixed(registry):
    """The Guaranteed Draw scopes to ONLY the very first draft of Day 1 -- a
    second draft, at a different Entrance Hall doorway of the same day, must
    return to ordinary drafting and produce more than one distinct hand
    across many seeds. This is the wiki's own scope ("the very first draw on
    Day 1"), not every draw of the day; a fixed second hand would mean the
    guarantee over-fired past its published bound."""
    second_hands: set[tuple[str, ...]] = set()
    seeds_checked = 0
    for seed in range(N_SEEDS):
        game = Game(GameConfig(day=1), seed=seed, registry=registry)
        d1, pending1 = _open_first_available(game, ENTRANCE_CELL)
        if pending1 is None:
            continue
        # Drafting has no decline: take slot 0 to return to NAVIGATE (the
        # player stays put -- choose() only places the room, see its
        # docstring) so a second, different Entrance Hall doorway can be
        # tried for a genuine second draft.
        game.choose(0)
        _d2, pending2 = _open_first_available(game, ENTRANCE_CELL, exclude_dirs=(d1,))
        if pending2 is None:
            continue
        seeds_checked += 1
        ids2 = tuple(registry.rooms[o.room_idx].id
                     for o in sorted(pending2.options, key=lambda o: o.slot))
        second_hands.add(ids2)
    assert seeds_checked > 20, (
        "setup: too few seeds produced a second open Day 1 doorway to draft from"
    )
    assert len(second_hands) > 1, (
        f"Day 1's SECOND draft came back as a single fixed hand across "
        f"{seeds_checked} seeds ({second_hands}) -- the opening-draw "
        "guarantee must bound to only the day's first draft"
    )
