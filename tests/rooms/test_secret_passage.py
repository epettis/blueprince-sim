"""Secret Passage / Spare Secret Passage: colour-selective drafting.

tests/test_colour_drafting.py already drives both ids end to end through
Game.open_door / choose_colour and pins the colour restriction, the
default-triple fallback, the exhaustion escape, and the Spare's identical
behaviour -- there is nothing about the mechanism itself left to add under
tests/rooms/ without duplicating that file. What it never exercises is the
failure path of this module's own ON_DRAFT_FROM self-check
(validate_secret_passage_hand / validate_spare_secret_passage_hand): every
hand those tests deal already honours the chosen colour, so the assertion
inside the hook silently passes on every run and nothing proves it would
actually catch a regression in draft.py's colour threading. This file adds
just that one case, for both ids.
"""

from __future__ import annotations

import pytest

from blueprince_sim.engine.effects.rooms.secret_passage import (
    validate_secret_passage_hand, validate_spare_secret_passage_hand)
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption, PendingDraft

SECRET_PASSAGE_CELL = 7  # rank 2, col 2: interior, doorway north targets cell 12 (empty)


@pytest.mark.parametrize("room_id, validate", [
    ("secret_passage", validate_secret_passage_hand),
    ("spare_secret_passage__ix138", validate_spare_secret_passage_hand),
])
def test_hook_raises_when_a_dealt_option_does_not_match_the_chosen_colour(
        registry, cfg, room_id, validate):
    """A hand whose colour restriction and dealt option disagree trips the
    hook's own assertion, proving it is reachable and would actually catch a
    real drafting regression rather than only ever observing agreement."""
    g = Game(cfg, seed=1, registry=registry)
    room = g.registry.by_id[room_id]
    g._place_room(room, SECRET_PASSAGE_CELL, N | S)
    off_colour = next(r for r in g.registry.rooms if not r.is_category("red"))
    pending = PendingDraft(from_cell=SECRET_PASSAGE_CELL, direction=N,
                           target_cell=12, colour="red")
    pending.options = [DraftOption(room_idx=off_colour.idx,
                                   orientation=off_colour.door_mask,
                                   gem_cost=0, slot=0)]
    g.state.pending = pending

    with pytest.raises(AssertionError, match="not a"):
        validate(g, room, None)
