"""Test-only luck suppression: the wiki's published item-count ladder has no
zero point -- even at floor luck (<=4) there is still a 7% chance of 1 item
("4- Luck: 7% for 1 item, 93% for 0 items", Luck page). Flooring
``state.luck`` alone does not stop a room's luck-rolled additional items from
firing; ``suppress_luck`` is what gives that guarantee, and every site needing
it calls this helper (see docs/luck.md's item-count ladder table, the
floor-luck row).

Its own correctness has a dedicated test (test_luck_ladder.py): if this
silently stopped suppressing, the 27 test files that call it would go flaky
at a 7% failure rate per assertion -- the same vacuous-by-luck failure shape
this repo has recorded four times.

Also forces the two data/items.json ``count_transforms`` labels that can
turn a genuine "0 items" ladder roll back into 1 item or a bonus gem (Guest
Bedroom's ``zero_becomes_one_or_gem``, engine/items.py's
``_apply_count_transform``) to their own "0 items" branch -- otherwise a
Guest Bedroom / Guess Bedroom draft would still leak an item 65% of the time
even with the ladder itself fully suppressed.
"""

from __future__ import annotations

from blueprince_sim.engine.rng import Rng

# The RNG stream labels engine/items.py's roll_ladder_count and
# _apply_count_transform use for their own draws (see that module). Kept
# here as the single source of truth for what this helper intercepts, so the
# helper and the ladder/transforms can't drift apart silently -- if items.py
# ever renames a label, this stops suppressing and test_luck_ladder.py's own
# suppression test catches it immediately.
LUCK_LADDER_OUTCOME_LABEL = "luck_ladder_outcome"
LUCK_LADDER_VARIABLE_LABEL = "luck_ladder_variable"
COUNT_TRANSFORM_ZERO_ONE_LABEL = "count_transform_zero_one"
COUNT_TRANSFORM_ZERO_GEM_LABEL = "count_transform_zero_gem"


class _NoLuckRng(Rng):
    """``Rng`` subclass forcing the item_ladder's own draw labels (plus the
    two zero-item count_transforms labels above) to whichever branch yields
    the FEWEST items; every other label passes through unchanged (same
    "subclass, not an attribute patch" idiom as test_digging.py's
    ``_AlwaysFirstRng`` -- ``Rng`` is a slotted class, so a bare
    instance-attribute patch of ``chance``/``roll_weighted`` is not an
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
        if label in (LUCK_LADDER_OUTCOME_LABEL, LUCK_LADDER_VARIABLE_LABEL,
                     COUNT_TRANSFORM_ZERO_ONE_LABEL, COUNT_TRANSFORM_ZERO_GEM_LABEL):
            return False  # "0 items" (flat/chain bands), "2 items" (variable roll),
            # or "stay at 0" (Guest Bedroom's zero_becomes_one_or_gem transform)
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

    Only meaningful with luck at/near the floor, which is every call site in
    this repo: bands 23-28/29+ are unconditional (no roll at all, just a
    fixed item count) and cannot be suppressed this way, but they are
    also unreachable from floored luck plus this codebase's only per-draft
    modifier (Rabbit's Foot/Lucky Purse, capped at +3) -- effective luck
    tops out at 3, still inside the flat <=4 band.
    """
    game.state.luck = 0
    game.rng = _NoLuckRng(game.rng)
