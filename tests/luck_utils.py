"""Test-only luck suppression: the wiki's published item-count ladder has no
zero point -- even at floor luck (<=4) there is still a 7% chance of 1 item
("4- Luck: 7% for 1 item, 93% for 0 items", Luck page). Flooring
``state.luck`` alone, the pre-ladder idiom, no longer guarantees a room's
luck-rolled additional items never fire. ``suppress_luck`` replaces that
idiom at all 76 sites that used it (see docs/open_tasks.md's 2026-08-13
decisions log entry).

Its own correctness has a dedicated test (test_luck_ladder.py): if this
silently stopped suppressing, the 27 test files that call it would go flaky
at a 7% failure rate per assertion -- the same vacuous-by-luck failure shape
this repo has recorded four times.
"""

from __future__ import annotations

from blueprince_sim.engine.rng import Rng

# The two RNG stream labels engine/items.py's roll_ladder_count uses for its
# own draws (see that module). Kept here as the single source of truth for
# what this helper intercepts, so the helper and the ladder can't drift apart
# silently -- if items.py ever renames a label, this stops suppressing and
# test_luck_ladder.py's own suppression test catches it immediately.
LUCK_LADDER_OUTCOME_LABEL = "luck_ladder_outcome"
LUCK_LADDER_VARIABLE_LABEL = "luck_ladder_variable"


class _NoLuckRng(Rng):
    """``Rng`` subclass forcing the item_ladder's own two draw labels to
    whichever branch yields the FEWEST items; every other label passes
    through unchanged (same "subclass, not an attribute patch" idiom as
    test_digging.py's ``_AlwaysFirstRng`` -- ``Rng`` is a slotted class, so a
    bare instance-attribute patch of ``chance``/``roll_weighted`` is not an
    option).

    Adopts the wrapped ``Rng``'s already-mutated ``_streams`` dict by
    reference (not a fresh reseed from the same seed) so every OTHER label's
    randomness continues exactly where it left off, whether or not anything
    had already been rolled before ``suppress_luck`` was called.
    """

    def __init__(self, inner: Rng) -> None:
        super().__init__(inner.seed)
        self._streams = inner._streams

    def chance(self, label: str, p: float) -> bool:
        if label in (LUCK_LADDER_OUTCOME_LABEL, LUCK_LADDER_VARIABLE_LABEL):
            return False  # "0 items" (flat/chain bands) or "2 items" (variable roll)
        return super().chance(label, p)

    def roll_weighted(self, label: str, weights) -> int:
        if label == LUCK_LADDER_OUTCOME_LABEL:
            return len(weights) - 1  # variable_mix bands: index 2 is always "0 items"
        return super().roll_weighted(label, weights)


def suppress_luck(game) -> None:
    """Floor ``game``'s luck AND force the item_ladder's own RNG draws to
    their lowest-item branch, so a room's luck-rolled additional items
    genuinely never fire -- unlike setting ``state.luck = 0`` alone (see
    module docstring for why that stopped being sufficient).

    Only meaningful with luck at/near the floor, which is every one of this
    repo's 76 call sites: bands 23-28/29+ are unconditional (no roll at all,
    just a fixed item count) and cannot be suppressed this way, but they are
    also unreachable from floored luck plus this codebase's only per-draft
    modifier (Rabbit's Foot/Lucky Purse, capped at +3) -- effective luck
    tops out at 3, still inside the flat <=4 band.
    """
    game.state.luck = 0
    game.rng = _NoLuckRng(game.rng)
