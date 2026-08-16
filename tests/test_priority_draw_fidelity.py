"""Priority Draws vs. the Slot-3-only Forced Draw: the four rulings that separate
them (blueprince.wiki.gg/wiki/Drafting/Advanced).

1. Priority Draws are an additional attempt-1-only filter applied to EVERY slot
   ("Filters > Priority Draws"), not a Slot-3-only mechanism -- only the Garage's
   own Forced Draw (draft.py's _forced_draw, "Special Draws > Forced Draws")
   is Slot-3-only. The two were previously conflated: draw_slot only ever called
   _priority_draw when slot == 2.
2. A dealt priority-draw card is actually removed from its deck ("the floorplan
   gets added to the discard filter for future draws"), via the same
   ``deck.deal_next`` call ``_deal_from_rarity`` uses -- the old code returned a
   Room without ever touching the deck, so the same card could be dealt again.
3. Each floorplan named by an entry gets its OWN independent acceptance roll
   ("each floorplan has a chance to get accepted"), not one roll for the whole
   named group followed by "first draftable room in list order wins" -- the old
   code made Observatory structurally unreachable behind Commissary in
   commissary_observatory's room list.
4. data/priority_draws.json's 3% group is {Garage, Classroom} per the wiki, not
   Classroom alone.

Each guard below is deterministic (RNG forced via literal chance=1.0 entries or
monkeypatched Rng.chance, never inferred by calling the function under test) so
a mutation of the fix under test fails for a diagnosable, property-named reason.
"""

from __future__ import annotations

import copy

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _priority_draw, draw_slot
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

# Interior cell (rank 3, col 2) reached by moving south -- away from grid edges
# so door-geometry legality never rules out a candidate (CLAUDE.md convention,
# matching test_category_biases.py/test_priority_draws.py's own target cell).
TARGET_CELL = 12
DIRECTION = S

# A free, base-pool, unconditional (no draft_conditions) room distinct from the
# forced-Closet fallback, so a hit is unambiguous evidence of the priority-draw
# path specifically (Closet would also be `forced=True` via the fallback attempt,
# making it useless for telling the two paths apart).
FREE_TARGET_ROOM_ID = "spare_room"


@pytest.fixture(scope="module")
def registry() -> Registry:
    """Load the packaged data once; every test below only reads it."""
    return Registry.load()


def _isolated_registry(registry: Registry, entries: list[dict]) -> Registry:
    """A copy of ``registry`` whose priority_draws list holds ONLY ``entries``,
    isolating a test's own entry from the other unconditional real ones."""
    isolated = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    priority["priority_draws"] = entries
    object.__setattr__(isolated, "priority", priority)
    return isolated


def _ctx_with_deck(registry: Registry, room_id: str) -> DraftContext:
    """A bare DraftContext whose only populated deck holds one copy of
    ``room_id`` in its real rarity/free-gem slot."""
    room = registry.by_id[room_id]
    state = GameState(decks=[DeckState() for _ in range(8)])
    deck_idx = room.rarity_idx * 2 + (0 if room.is_free else 1)
    state.decks[deck_idx] = DeckState(order=[room.idx])
    return DraftContext(state, registry, GameConfig(), Rng(0), set(), None)


# --------------------------------------------------------- Ruling 1: every slot


def test_priority_draw_reaches_slot_0_and_slot_1_not_just_slot_2(registry, monkeypatch):
    """draw_slot must call _priority_draw for slot 0 and slot 1 too, not only
    slot 2 -- the wiki puts Priority Draws under Filters with no slot
    restriction (only the Garage's Forced Draw is Slot-3-only). Deterministic:
    an isolated one-entry registry with chance=1.0 forces the roll to hit, and
    the target room is a distinguishable free room (not Closet, which the
    forced-Closet fallback would also produce with forced=True)."""
    entry = {"rooms": [FREE_TARGET_ROOM_ID], "label": "test_all_slots", "chance": 1.0}
    isolated = _isolated_registry(registry, [entry])
    target_idx = registry.by_id[FREE_TARGET_ROOM_ID].idx

    for slot in (0, 1, 2):
        ctx = _ctx_with_deck(isolated, FREE_TARGET_ROOM_ID)
        opt = draw_slot(ctx, slot, TARGET_CELL, DIRECTION, set(), is_gem=False)
        assert opt is not None and opt.room_idx == target_idx and opt.forced, (
            f"slot {slot}: priority draw did not fire (still gated to slot == 2?)"
        )


def test_forced_draw_stays_slot_3_only(registry):
    """The OTHER half of ruling 1: _forced_draw must stay gated to
    slot == 2 -- draw_slot only calls it when ``slot == 2`` -- unlike
    _priority_draw, which this PR deliberately un-gates from that same check."""
    import inspect

    from blueprince_sim.engine import draft as draft_mod

    source = inspect.getsource(draft_mod.draw_slot)
    forced_call = source.index("_forced_draw(")
    priority_call = source.index("_priority_draw(")
    guard = "if slot == 2:"
    # The nearest preceding "if slot == 2:" to the Forced Draw call must be
    # closer than to the priority-draw call, i.e. only the Forced Draw call is
    # still wrapped by the slot-2 gate.
    guard_pos = source.rindex(guard, 0, forced_call)
    assert guard_pos < forced_call < priority_call, (
        "_forced_draw is no longer gated to slot == 2 in draw_slot"
    )
    assert guard not in source[forced_call:priority_call], (
        "an 'if slot == 2:' gate reappeared between the two calls -- "
        "_priority_draw must not be slot-restricted"
    )


# ------------------------------------------------------- Ruling 2: card consumed


def test_priority_draw_consumes_the_card_from_its_deck(registry):
    """A dealt priority-draw card is actually removed from its deck (wiki:
    "the floorplan gets added to the discard filter for future draws"), via
    the same ``deck.deal_next`` call ``_deal_from_rarity`` uses. Deterministic:
    a one-card deck, chance=1.0. The first call must return the card; the
    second call (same ctx, same deck, same forced chance) must return None --
    if the card were still sitting undealt in the deck (the old bug: a Room
    was returned without ever touching the deck), the second call would deal
    it again."""
    entry = {"rooms": [FREE_TARGET_ROOM_ID], "label": "test_consume", "chance": 1.0}
    isolated = _isolated_registry(registry, [entry])
    ctx = _ctx_with_deck(isolated, FREE_TARGET_ROOM_ID)
    room = registry.by_id[FREE_TARGET_ROOM_ID]
    deck = ctx.state.deck(room.rarity_idx, not room.is_free)

    first = _priority_draw(ctx, TARGET_CELL, DIRECTION, set(), is_gem=False)
    assert first is not None and first.id == FREE_TARGET_ROOM_ID
    assert deck.pos == 1, "the dealt card was not advanced past the deck cursor"

    second = _priority_draw(ctx, TARGET_CELL, DIRECTION, set(), is_gem=False)
    assert second is None, (
        "the same priority-draw card was dealt twice -- it was never actually "
        "removed from its deck"
    )


# --------------------------------------------- Ruling 3: independent acceptance


def test_commissary_and_observatory_each_get_their_own_acceptance_roll(registry, monkeypatch):
    """Commissary and Observatory must each roll their OWN acceptance chance
    (wiki: "each floorplan has a chance to get accepted"), not one shared roll
    for the whole commissary_observatory entry followed by "first draftable
    room in list order wins" -- the bug that made Observatory structurally
    unreachable (2436 Commissary vs 0 Observatory over 20,000 first hands).
    Deterministic: Rng.chance is monkeypatched to hit ONLY Observatory's own
    labeled roll and miss Commissary's, so the old (entry-level, list-order)
    code -- which never even looks at a per-room label -- would return
    Commissary regardless, while the fixed code must return Observatory."""
    entry = {"rooms": ["commissary", "observatory"], "label": "commissary_observatory",
             "chance": 0.13}
    isolated = _isolated_registry(registry, [entry])
    state = GameState(decks=[DeckState() for _ in range(8)])
    commissary = registry.by_id["commissary"]
    observatory = registry.by_id["observatory"]
    state.decks[commissary.rarity_idx * 2 + 1] = DeckState(order=[commissary.idx])
    state.decks[observatory.rarity_idx * 2 + 1] = DeckState(order=[observatory.idx])
    ctx = DraftContext(state, isolated, GameConfig(), Rng(0), set(), None)

    def chance(self, label, p):
        return label == "priority_commissary_observatory_observatory"

    monkeypatch.setattr(Rng, "chance", chance)

    picked = _priority_draw(ctx, TARGET_CELL, DIRECTION, set(), is_gem=True)
    assert picked is not None and picked.id == "observatory", (
        f"expected Observatory (its own roll was forced to hit, Commissary's forced to "
        f"miss); got {picked.id if picked else None} -- rolls are not independent per room"
    )


def test_observatory_is_reachable_over_many_seeds(registry):
    """Statistical confirmation of the fix, not just the forced-roll pin above:
    over many real (unforced) seeds, Observatory is picked a nonzero number of
    times through the isolated commissary_observatory entry -- the old code
    picked it zero times in 20,000 trials (Commissary, listed first, always
    won whenever it was draftable)."""
    entry = {"rooms": ["commissary", "observatory"], "label": "commissary_observatory",
             "chance": 0.13}
    isolated = _isolated_registry(registry, [entry])
    commissary = registry.by_id["commissary"]
    observatory = registry.by_id["observatory"]
    counts = {"commissary": 0, "observatory": 0, None: 0}
    trials = 20_000
    for seed in range(trials):
        state = GameState(decks=[DeckState() for _ in range(8)])
        state.decks[commissary.rarity_idx * 2 + 1] = DeckState(order=[commissary.idx])
        state.decks[observatory.rarity_idx * 2 + 1] = DeckState(order=[observatory.idx])
        ctx = DraftContext(state, isolated, GameConfig(), Rng(seed), set(), None)
        picked = _priority_draw(ctx, TARGET_CELL, DIRECTION, set(), is_gem=True)
        counts[picked.id if picked else None] += 1

    assert counts["observatory"] > 0, (
        f"Observatory was never picked across {trials} seeds (counts={counts})"
    )
    assert counts["commissary"] > 0, (
        f"setup: Commissary was never picked across {trials} seeds (counts={counts})"
    )


# ------------------------------------------------------- Ruling 4a: data gap


def test_garage_classroom_entry_carries_both_rooms(registry):
    """priority_draws.json's 3% group is {Garage, Classroom} per the wiki
    ("Garage, Classroom: 3% chance"), not Classroom alone."""
    entry = next(e for e in registry.priority["priority_draws"]
                 if e["label"] == "garage_classroom")
    assert set(entry["rooms"]) == {"garage", "classroom"}
    assert entry["chance"] == pytest.approx(0.03)


def test_garage_is_reachable_via_the_garage_classroom_entry(registry):
    """Behavioral half of the data-gap fix: with the roll forced to hit and
    Garage's own draft conditions satisfied (unlike TARGET_CELL, which the
    Garage's wing/rank restriction blocks), _priority_draw actually returns
    Garage through the (now two-room) garage_classroom entry -- not merely
    listed in the data but reachable through the real candidate/deal path."""
    entry = {"rooms": ["garage", "classroom"], "label": "garage_classroom", "chance": 1.0}
    isolated = _isolated_registry(registry, [entry])
    garage = registry.by_id["garage"]
    # Garage's own draft_conditions require the West Wing, rank 4->5 (matches
    # tests/rooms/test_garage.py's SRC_A/TARGET_A doorway) -- TARGET_CELL/
    # DIRECTION used elsewhere in this module does not satisfy them.
    garage_target_cell = 20  # rank 5, West Wing
    garage_direction = N

    state = GameState(decks=[DeckState() for _ in range(8)])
    state.decks[garage.rarity_idx * 2 + 1] = DeckState(order=[garage.idx])
    ctx = DraftContext(state, isolated, GameConfig(), Rng(0), set(), None)

    picked = _priority_draw(ctx, garage_target_cell, garage_direction, set(), is_gem=True)
    assert picked is not None and picked.id == "garage", (
        f"Garage was not returned via garage_classroom (got "
        f"{picked.id if picked else None}) at its own legal doorway"
    )
