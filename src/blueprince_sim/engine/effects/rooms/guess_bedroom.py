"""Guess Bedroom (guess_bedroom__ix70): secretly mimics a Bedroom in the pool.

"When it is drafted, it secretly chooses and mimics a Bedroom which is
currently in your draft pool" -- rooms.json already drops the base Guest
Bedroom's own +10-steps grant for this variant (empty ``effects``), so this
module only needs to add the mimicry. Selection fires at ON_PLACE, the
drafted-not-entered site (Game._place_room writes the grid cell, then fires
ON_PLACE; move()/_enter() -- ON_ENTER/ON_ARRIVE -- come later, on a
subsequent action), matching "when it is drafted".

Selection (_mimic_candidates): decks.eligible_pool(registry, cfg) already
computes exactly "today's draft pool" -- upgrade variants substituted for
their base, Repellent bans applied -- with no notion of per-day draft counts,
so a room already on the estate (e.g. returned to the pool by the Chamber of
Mirrors) stays eligible for free. Filtered to Room.is_category("bedroom")
(never `category ==`, so Maid's Chamber -- red primary, bedroom extra --
still counts), minus the never-selected ids and the Aquarium family, plus the
Hovel unconditionally (rarity=None keeps it out of eligible_pool entirely; it
is drafted at its own outer location, not from a deck, so nothing else here
ever adds it).

The Aquarium family (aquarium + goldfish/starfish/electric eel variants) is
outside the selectable set: mimicking it means inheriting its extra colours,
and every is_category consumer (category biases, grant_per_category, the
Cloister/Terrace green boosts, scepter colours) treats category membership as
a fixed fact about a Room record rather than something true for one drafted
cell and false for another of the same id. See meta.blocked_on on
guess_bedroom__ix70's own record.

State: GameState.guess_bedroom_mimic_id holds the chosen id, rolled on the
first Guess Bedroom that finds a valid candidate and reused by any drafted
afterward the same day -- see the field's own comment in state.py. The draw
uses its own RNG substream (RNG_LABEL) so it cannot perturb other features.

Payload dispatch (mimic_on_place/_on_enter/_on_arrive/_on_draft_room below):
each hook re-fires the mimicked Room's own tag effects via
effects.fire(game, mimicked, hook, ctx_room) -- the same dispatch
Game._place_room/_enter/move use for a real room of that id -- with three
carve-outs:

  - Boudoir (base + boudoir__ix16/17/18): no effect. The Boudoir has no
    standard effect of its own, and all four ids carry
    her_ladyships_chamber.py's `pay_boudoir_bonus` room_hook at ON_ENTER,
    which pays Her Ladyship's Chamber's armed bonus to whoever enters an
    actual Boudoir. Delegating would pay a bonus the Chamber never armed for
    this cell.
  - Bedroom: the only mimic that retriggers on every entry ("does not become
    an Entry Room" -- it still pays out on re-entry, unlike a normal room's
    ON_ENTER grant, which Game._enter fires once per cell). Wired to
    ON_ARRIVE so it can call effects.fire(..., Hook.ON_ENTER, ...) on every
    arrival, past the entered-gate that lives in Game._enter rather than in
    fire() itself.
  - Bunk Room (base + bunk_room__ix20/21/22): ON_DRAFT_ROOM is skipped. The
    mimic counts as a flat 2 Bedrooms, which the shared counts_as_bedrooms
    tag on the ON_PLACE path below already produces. The upgraded variants
    additionally carry bunk_room.py's own room_hook at ON_DRAFT_ROOM, which
    doubles a resource on exactly 2 Hallways/Green Rooms/Shops in the house;
    that is not part of the mimic.

Servant's Quarters needs no carve-out: its grant_per_category tag carries the
published cap of 15, so delegation reproduces the mimic's cap for free.
"""

from __future__ import annotations

from .. import Hook, fire, room_hook
from ...decks import eligible_pool

GUESS_BEDROOM_ID = "guess_bedroom__ix70"
BEDROOM_ID = "bedroom"
BOUDOIR_ID = "boudoir"
BUNK_ROOM_ID = "bunk_room"
HOVEL_ID = "hovel"
AQUARIUM_ID = "aquarium"

# Never chosen, regardless of pool/ban state. Her Ladyship's Chamber and the
# Master Bedroom are excluded outright; the Spare Bedroom family root and branch.
NEVER_SELECTED_IDS = frozenset({
    GUESS_BEDROOM_ID,
    "her_ladyships_chamber",
    "master_bedroom",
    "spare_bedroom__ix131",
    "servants_spare_quarters__ix134",
    "her_ladyships_spare_room__ix135",
    "spare_master_bedroom__ix136",
})

RNG_LABEL = "guess_bedroom_mimic"  # this room's own RNG substream label


def _is_aquarium(room) -> bool:
    """True for the Aquarium base room or any of its upgrade variants."""
    return room.id == AQUARIUM_ID or room.variant_of == AQUARIUM_ID


def _is_boudoir(room) -> bool:
    """True for the Boudoir base room or any of its upgrade variants."""
    return room.id == BOUDOIR_ID or room.variant_of == BOUDOIR_ID


def _is_bunk_room(room) -> bool:
    """True for the Bunk Room base room or any of its upgrade variants."""
    return room.id == BUNK_ROOM_ID or room.variant_of == BUNK_ROOM_ID


def _mimic_candidates(game) -> list:
    """Bedroom-category rooms today's Guess Bedroom may mimic.

    See the module docstring for the eligible_pool/is_category/Aquarium/Hovel
    reasoning; this just assembles it.
    """
    candidates = [
        r for r in eligible_pool(game.registry, game.cfg)
        if r.is_category("bedroom") and r.id not in NEVER_SELECTED_IDS and not _is_aquarium(r)
    ]
    hovel = game.registry.by_id.get(HOVEL_ID)
    if hovel is not None and hovel.id not in NEVER_SELECTED_IDS:
        candidates.append(hovel)
    return candidates


@room_hook(GUESS_BEDROOM_ID, Hook.ON_PLACE)
def mimic_on_place(game, room, ctx_room) -> None:
    """Roll today's mimic if none is set yet, then fire whatever ON_PLACE tag
    the chosen room carries (e.g. Bunk Room's counts_as_bedrooms)."""
    st = game.state
    if st.guess_bedroom_mimic_id is None:
        candidates = _mimic_candidates(game)
        if candidates:
            st.guess_bedroom_mimic_id = game.rng.choice(RNG_LABEL, candidates).id
    mimic_id = st.guess_bedroom_mimic_id
    if mimic_id is None:
        return
    fire(game, game.registry.by_id[mimic_id], Hook.ON_PLACE)


@room_hook(GUESS_BEDROOM_ID, Hook.ON_ENTER)
def mimic_on_enter(game, room, ctx_room) -> None:
    """Fire the mimicked room's ON_ENTER tag, once, on this room's own first
    entry -- except Bedroom (handled at ON_ARRIVE, see module docstring) and
    Boudoir (forced to no effect)."""
    mimic_id = game.state.guess_bedroom_mimic_id
    if mimic_id is None or mimic_id == BEDROOM_ID:
        return
    mimicked = game.registry.by_id[mimic_id]
    if _is_boudoir(mimicked):
        return
    fire(game, mimicked, Hook.ON_ENTER, ctx_room)


@room_hook(GUESS_BEDROOM_ID, Hook.ON_ARRIVE)
def mimic_on_arrive(game, room, ctx_room) -> None:
    """Bedroom mimic only: +2 steps on every arrival, including re-entry."""
    if game.state.guess_bedroom_mimic_id != BEDROOM_ID:
        return
    fire(game, game.registry.by_id[BEDROOM_ID], Hook.ON_ENTER, ctx_room)


@room_hook(GUESS_BEDROOM_ID, Hook.ON_DRAFT_ROOM)
def mimic_on_draft_room(game, room, ctx_room) -> None:
    """Fire the mimicked room's ON_DRAFT_ROOM tag (Nursery's persistent
    per-Bedroom-drafted grant) -- except Bunk Room, whose own ON_DRAFT_ROOM
    room_hook is outside the mimic (see module docstring)."""
    mimic_id = game.state.guess_bedroom_mimic_id
    if mimic_id is None:
        return
    mimicked = game.registry.by_id[mimic_id]
    if _is_bunk_room(mimicked):
        return
    fire(game, mimicked, Hook.ON_DRAFT_ROOM, ctx_room)
