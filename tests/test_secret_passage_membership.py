"""Secret Passage's conditional migration between the patio_rooms and
garage_classroom priority-draw entries (data/priority_draws.json's
membership_moves; draft.py::_apply_membership_moves, called from
_priority_draw where each entry's candidate room list is built).

blueprince.wiki.gg/wiki/Drafting/Advanced: "Secret Passage is included if
Greenhouse has not been drafted" (patio_rooms clause) and "Secret Passage
included after Greenhouse effect is active" (garage_classroom clause). Both
clauses are keyed off the single signal state.greenhouse_placed here, the
same one chance_with_greenhouse already reads on patio_rooms, so the two
memberships stay strictly complementary -- see membership_moves' own
meta.notes in priority_draws.json for the wiki-wording gap (a King's-green
activation could, read literally, satisfy "effect is active" with no
Greenhouse drafted) this model does not distinguish.

tools/validate_data.py's rejection checks are pinned separately in
tests/test_validate_data_membership_moves.py.
"""

from __future__ import annotations

import copy

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_membership_moves, _priority_draw
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

# Interior cell (rank 3, col 2) reached by moving south -- matches the target
# cell/direction convention used by test_priority_draws.py/
# test_priority_draw_fidelity.py, comfortably away from grid edges so
# door-geometry legality never rules out a candidate.
TARGET_CELL = 12
DIRECTION = S


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def _entry(registry: Registry, label: str) -> dict:
    """The real priority_draws.json entry carrying this label."""
    return next(e for e in registry.priority["priority_draws"] if e["label"] == label)


def _ctx(registry: Registry, greenhouse_placed: bool) -> DraftContext:
    """A bare DraftContext with 8 empty decks and the given greenhouse_placed."""
    state = GameState(decks=[DeckState() for _ in range(8)])
    state.greenhouse_placed = greenhouse_placed
    return DraftContext(state, registry, GameConfig(), Rng(0), set(), None)


def _resolved(registry: Registry, ctx: DraftContext, label: str) -> list[str]:
    """The entry's own rooms list after _apply_membership_moves."""
    return _apply_membership_moves(ctx, label, list(_entry(registry, label)["rooms"]))


def test_secret_passage_is_a_patio_rooms_candidate_without_a_greenhouse(registry):
    """Wiki: "Secret Passage is included if Greenhouse has not been drafted" --
    with state.greenhouse_placed False, patio_rooms' resolved candidate list
    still carries secret_passage and garage_classroom's does not."""
    ctx = _ctx(registry, greenhouse_placed=False)
    assert "secret_passage" in _resolved(registry, ctx, "patio_rooms")
    assert "secret_passage" not in _resolved(registry, ctx, "garage_classroom")


def test_secret_passage_moves_to_garage_classroom_with_a_greenhouse_placed(registry):
    """Wiki: "Secret Passage included after Greenhouse effect is active" --
    with state.greenhouse_placed True, patio_rooms' resolved candidate list no
    longer carries secret_passage, and garage_classroom's now does."""
    ctx = _ctx(registry, greenhouse_placed=True)
    assert "secret_passage" not in _resolved(registry, ctx, "patio_rooms")
    assert "secret_passage" in _resolved(registry, ctx, "garage_classroom")


@pytest.mark.parametrize("greenhouse_placed", [False, True])
def test_secret_passage_is_in_exactly_one_of_the_two_groups(registry, greenhouse_placed):
    """Complementarity: whichever way state.greenhouse_placed reads, the
    Secret Passage sits in exactly one of patio_rooms/garage_classroom's
    resolved candidate lists, never both and never neither -- the invariant
    keying both halves off one signal is meant to guarantee."""
    ctx = _ctx(registry, greenhouse_placed=greenhouse_placed)
    in_patio = "secret_passage" in _resolved(registry, ctx, "patio_rooms")
    in_garage = "secret_passage" in _resolved(registry, ctx, "garage_classroom")
    assert in_patio != in_garage


def test_membership_moves_is_a_no_op_when_its_condition_is_inactive(registry):
    """With greenhouse_placed False, _apply_membership_moves returns
    patio_rooms' own rooms list UNCHANGED -- the identical object, not a copy
    -- so _priority_draw's iteration order and RNG-roll count for that entry
    are untouched by the primitive's mere presence in the data."""
    ctx = _ctx(registry, greenhouse_placed=False)
    original = _entry(registry, "patio_rooms")["rooms"]
    result = _apply_membership_moves(ctx, "patio_rooms", original)
    assert result is original


def test_a_condition_naming_no_gamestate_attribute_is_inert_not_a_crash(registry):
    """A membership_moves record whose condition matches no GameState attribute
    leaves the candidate list alone instead of raising mid-draft.

    This is what licenses validate_data.py treating an unknown condition as a
    warning rather than an error. Without it the same record would pass
    validation and then crash the draft, so the two decisions have to be
    changed together.
    """
    isolated = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    priority["membership_moves"][0]["condition"] = "greenhouse_plased"
    object.__setattr__(isolated, "priority", priority)
    ctx = _ctx(isolated, greenhouse_placed=True)
    original = _entry(isolated, "patio_rooms")["rooms"]
    assert _apply_membership_moves(ctx, "patio_rooms", original) == original


def _isolated_registry_without_membership_moves(registry: Registry) -> Registry:
    """A copy of ``registry`` with the membership_moves key deleted entirely
    -- the shape the data had before this primitive existed -- so a
    no-Greenhouse draw can be compared against it for byte-identical output."""
    isolated = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    priority.pop("membership_moves", None)
    object.__setattr__(isolated, "priority", priority)
    return isolated


def _stocked_state(registry: Registry) -> GameState:
    """8 decks, each holding (at most) one room per rarity/free-gem slot,
    drawn from every priority_draws entry's own room list -- enough for every
    named priority-draw room to actually be draftable when its roll hits."""
    state = GameState(decks=[DeckState() for _ in range(8)])
    seen_slots: set[tuple[int, bool]] = set()
    for entry in registry.priority["priority_draws"]:
        for rid in entry.get("rooms", []):
            room = registry.by_id.get(rid)
            if room is None or room.rarity is None:
                continue
            slot = (room.rarity_idx, room.is_free)
            if slot in seen_slots:
                continue
            seen_slots.add(slot)
            deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
            state.decks[deck_idx] = DeckState(order=[room.idx])
    return state


def test_no_greenhouse_draw_sequence_is_unchanged_by_membership_moves(registry):
    """The unconditional (no-Greenhouse) path must behave exactly as it did
    before membership_moves existed. Deterministic: over 200 fixed seeds x
    both Free/Gem classes, with every priority-draw room stocked in its own
    deck slot and greenhouse_placed False, _priority_draw against the real
    (post-PR) registry and against a registry with membership_moves stripped
    out entirely return the identical room (or both None) and leave every
    deck at the identical cursor position -- proving the primitive changes
    nothing while its condition never fires."""
    stripped = _isolated_registry_without_membership_moves(registry)

    for seed in range(200):
        for is_gem in (False, True):
            state_a = _stocked_state(registry)
            state_a.greenhouse_placed = False
            ctx_a = DraftContext(state_a, registry, GameConfig(), Rng(seed), set(), None)
            result_a = _priority_draw(ctx_a, TARGET_CELL, DIRECTION, set(), is_gem=is_gem)

            state_b = _stocked_state(registry)
            state_b.greenhouse_placed = False
            ctx_b = DraftContext(state_b, stripped, GameConfig(), Rng(seed), set(), None)
            result_b = _priority_draw(ctx_b, TARGET_CELL, DIRECTION, set(), is_gem=is_gem)

            assert (result_a.id if result_a else None) == (
                result_b.id if result_b else None), (
                f"seed {seed}, is_gem={is_gem}: registry with membership_moves "
                f"diverged from the stripped registry with no Greenhouse placed"
            )
            for i in range(8):
                assert state_a.decks[i].pos == state_b.decks[i].pos, (
                    f"seed {seed}, is_gem={is_gem}: deck {i} cursor diverged"
                )
