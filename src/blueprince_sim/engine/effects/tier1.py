"""Tier-1 effect handlers: resource grants and draft modifiers.

Handler signature: (game, room, effect, context_room). ``game`` is the Game
orchestrator; ``room`` is the room carrying the effect; ``context_room`` is
the other room involved for relational hooks (e.g. the bedroom just drafted,
for the Nursery's ON_DRAFT_ROOM effect).
"""

from __future__ import annotations

from . import Hook, effect

RESOURCES = ("steps", "gems", "keys", "coins", "dice", "stars")


def _grant(game, resource: str, amount: int) -> None:
    st = game.state
    if resource == "steps":
        st.steps += amount
    elif resource == "gems":
        st.gems = max(0, st.gems + amount)
    elif resource == "keys":
        st.keys = max(0, st.keys + amount)
    elif resource == "coins":
        st.coins = max(0, st.coins + amount)
    elif resource == "dice":
        st.dice = max(0, st.dice + amount)
    elif resource == "luck":
        st.luck += amount
    # "stars" and other out-of-scope currencies are tracked nowhere; no-op.


def _red_negated(game, room) -> bool:
    """Hovel: negate the effects of the next N red rooms."""
    if room.category == "red" and game.red_negations > 0:
        game.red_negations -= 1
        return True
    return False


# --- plain grants (fire when the player first enters the room) ---

@effect("grant", Hook.ON_ENTER)
def grant(game, room, eff, ctx_room) -> None:
    amount = eff.param("amount", 0)
    if amount < 0 and _red_negated(game, room):
        return
    _grant(game, eff.param("resource"), amount)


@effect("grant_per_category", Hook.ON_ENTER)
def grant_per_category(game, room, eff, ctx_room) -> None:
    """E.g. Servant's Quarters: +1 per Bedroom in the house."""
    category = eff.param("category")
    if category == "any":
        n = sum(1 for idx in game.state.grid if idx >= 0)
    else:
        n = sum(1 for idx in game.state.grid
                if idx >= 0 and game.registry.rooms[idx].category == category)
        n += game.bedroom_bonus if category == "bedroom" else 0
    _grant(game, eff.param("resource"), eff.param("amount", 1) * n)


@effect("set_resource_on_enter", Hook.ON_ENTER)
def set_resource_on_enter(game, room, eff, ctx_room) -> None:
    """Ballroom / Nurse's Station: set a resource to a fixed value on entry."""
    st = game.state
    resource, value = eff.param("resource"), eff.param("value", 0)
    threshold = eff.param("if_below")
    current = getattr(st, resource)
    if threshold is not None and current >= threshold:
        return
    setattr(st, resource, value)


# --- drafting-time relational grants ---

@effect("grant_on_draft_category", Hook.ON_DRAFT_ROOM)
def grant_on_draft_category(game, room, eff, ctx_room) -> None:
    """Nursery: whenever you draft a Bedroom, gain N steps."""
    if ctx_room is not None and ctx_room.category == eff.param("category"):
        _grant(game, eff.param("resource"), eff.param("amount", 0))


# --- house-state flags recomputed on placement (draft modifiers) ---

@effect("solarium_weights", Hook.ON_PLACE)
def solarium_weights(game, room, eff, ctx_room) -> None:
    game.state.solarium_placed = True


@effect("greenhouse_bias", Hook.ON_PLACE)
def greenhouse_bias(game, room, eff, ctx_room) -> None:
    game.state.greenhouse_placed = True


@effect("study_redraws", Hook.ON_PLACE)
def study_redraws(game, room, eff, ctx_room) -> None:
    game.state.study_placed = True


@effect("counts_as_drafting_room", Hook.ON_PLACE)
def counts_as_drafting_room(game, room, eff, ctx_room) -> None:
    game.state.drafting_room_count += 1


@effect("counts_as_bedrooms", Hook.ON_PLACE)
def counts_as_bedrooms(game, room, eff, ctx_room) -> None:
    """Bunk Room counts as 2 bedrooms for house-counting effects."""
    game.bedroom_bonus += eff.param("amount", 2) - 1


@effect("inject_pool", Hook.ON_PLACE)
def inject_pool(game, room, eff, ctx_room) -> None:
    """The Pool / Pool Hall: add rooms to today's draft decks."""
    game.inject_rooms(list(eff.param("rooms", ())))


@effect("allow_duplicates", Hook.ON_PLACE)
def allow_duplicates(game, room, eff, ctx_room) -> None:
    # Chamber of Mirrors: handled via placed_ids check in draft.room_draftable
    pass


@effect("free_green_drafts", Hook.ON_PLACE)
def free_green_drafts(game, room, eff, ctx_room) -> None:
    """Terrace: green rooms cost no gems."""
    game.free_categories.add("green")


@effect("halve_steps", Hook.ON_PLACE)
def halve_steps(game, room, eff, ctx_room) -> None:
    """Weight Room: lose half your steps (rounded down) on draft."""
    if _red_negated(game, room):
        return
    game.state.steps -= game.state.steps // 2


@effect("coins_per_deadend", Hook.ON_DRAFT_ROOM)
def coins_per_deadend(game, room, eff, ctx_room) -> None:
    """Tomb: each Dead End drafted in the house spreads gold into the Tomb."""
    if ctx_room is not None and ctx_room.layout == "dead_end":
        _grant(game, "coins", eff.param("amount", 5))


@effect("negate_red_rooms", Hook.ON_PLACE)
def negate_red_rooms(game, room, eff, ctx_room) -> None:
    """Hovel: negate the effects of the next N red rooms."""
    game.red_negations += eff.param("amount", 3)


# reduce_draft_options (Archives) is consumed directly by draft.deal_draft
# based on the room being drafted FROM; register it so it isn't warned about.
@effect("reduce_draft_options", Hook.ON_PLACE)
def reduce_draft_options(game, room, eff, ctx_room) -> None:
    pass
