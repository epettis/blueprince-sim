"""Tier-1 effect handlers: resource grants and draft modifiers.

Handler signature: (game, room, effect, context_room). ``game`` is the Game
orchestrator; ``room`` is the room carrying the effect; ``context_room`` is
the other room involved for relational hooks (e.g. the bedroom just drafted,
for the Nursery's ON_DRAFT_ROOM effect).
"""

from __future__ import annotations

from .. import special_items
from . import Hook, effect

RESOURCES = ("steps", "gems", "keys", "coins", "dice", "stars")


def _grant(game, resource: str, amount: int) -> None:
    """Apply a (possibly negative) resource delta to game state.

    Gems/keys/coins/dice clamp at zero; steps and luck may go negative
    (running out of steps is how the day ends). Unmodeled currencies no-op.
    """
    st = game.state
    match resource:
        case "steps":
            st.steps += amount
        case "gems":
            st.gems = max(0, st.gems + amount)
        case "keys":
            st.keys = max(0, st.keys + amount)
        case "coins":
            st.coins = max(0, st.coins + amount)
        case "dice":
            st.dice = max(0, st.dice + amount)
        case "luck":
            st.luck += amount
        case "allowance":
            st.allowance = max(0, st.allowance + amount)
        case "stars":
            st.stars = max(0, st.stars + amount)
        # other out-of-scope currencies are tracked nowhere; no-op.


def _red_negated(game, room) -> bool:
    """Shelter or Knight's Shield: negate negative effects of a red room.

    Shelter decrements its counter on each negate. Knight's Shield fires once
    per day (simplification #6: auto-applied, no player choice).
    """
    if not room.is_category("red"):
        return False
    if game.red_negations > 0:
        game.red_negations -= 1
        return True
    if game.cfg.special_items and special_items.shield_negates(game):
        return True
    return False


# --- plain grants (fire when the player first enters the room) ---

@effect("grant", Hook.ON_ENTER)
def grant(game, room, eff, ctx_room) -> None:
    """Flat resource grant on first entry; negative amounts are red-room
    penalties, which Shelter's negation can cancel.

    Chapel -1 coin: the Keeper of Tithes secretly banks each coin actually
    taken (player had >=1 coin).  Tracked in special.chapel_tithes and paid
    out when the Chapel altar is lit.
    """
    amount = eff.param("amount", 0)
    if amount < 0 and _red_negated(game, room):
        return
    resource = eff.param("resource")
    # Keeper of Tithes: bank the coin before it is taken, but only when the
    # player has at least one coin to lose (no coins -> no penalty -> no tithe).
    if (resource == "coins" and amount < 0
            and (room.id == "chapel" or room.variant_of == "chapel")):
        coins_taken = min(-amount, game.state.coins)
        if coins_taken > 0:
            game.state.special.chapel_tithes += coins_taken
    _grant(game, resource, amount)


@effect("grant_per_category", Hook.ON_ENTER)
def grant_per_category(game, room, eff, ctx_room) -> None:
    """E.g. Servant's Quarters: +1 per Bedroom in the house, up to its cap of 15.

    An optional ``cap`` param bounds the total granted, not the count.
    """
    category = eff.param("category")
    if category == "any":
        n = sum(1 for idx in game.state.grid if idx >= 0)
    else:
        n = sum(1 for idx in game.state.grid
                if idx >= 0 and game.registry.rooms[idx].is_category(category))
        n += game.bedroom_bonus if category == "bedroom" else 0
    total = eff.param("amount", 1) * n
    cap = eff.param("cap")
    if cap is not None:
        total = min(total, cap)
    _grant(game, eff.param("resource"), total)


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


@effect("mark_visited", Hook.ON_ENTER)
def mark_visited(game, room, eff, ctx_room) -> None:
    """Sauna / Morning Room / Freezer: set a per-day GameState bool flag on entry.

    The flag is read back out through Game.carryover() at day end and turned
    into next day's starting bonus by DayChain -- see the flag fields on
    GameState (sauna_visited, morning_room_visited, freezer_frozen) for what
    each one means.
    """
    setattr(game.state, eff.param("flag"), True)


# --- drafting-time relational grants ---

@effect("grant_on_draft_category", Hook.ON_DRAFT_ROOM)
def grant_on_draft_category(game, room, eff, ctx_room) -> None:
    """Nursery: whenever you draft a Bedroom, gain N steps.

    ``room is ctx_room`` identifies the room's own draft (see
    Game._place_room's self-fire); that case only proceeds when the effect's
    include_self param is set, so e.g. Indoor Nursery's "another Green Room"
    wording does not grant on its own draft.
    """
    if room is ctx_room and not eff.param("include_self", False):
        return
    if ctx_room is not None and ctx_room.is_category(eff.param("category")):
        _grant(game, eff.param("resource"), eff.param("amount", 0))


# --- house-state flags recomputed on placement (draft modifiers) ---

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


@effect("free_green_drafts", Hook.ON_PLACE)
def free_green_drafts(game, room, eff, ctx_room) -> None:
    """Terrace: green rooms cost no gems."""
    game.free_categories.add("green")


# archive_floorplan (Archives) and conceal_all_floorplans (Darkroom) are both
# consumed directly: archive_floorplan by effects/rooms/archives.py's ON_PLACE
# room_hook (sets a house-wide day flag), conceal_all_floorplans by
# draft._fill_options, keyed on the room being drafted FROM and read live
# against effects/rooms/darkroom.py's ON_ENTER-set switch state. Register
# both tags as no-ops here so neither is warned about as unhandled.
@effect("archive_floorplan", Hook.ON_PLACE)
def archive_floorplan(game, room, eff, ctx_room) -> None:
    pass


@effect("conceal_all_floorplans", Hook.ON_PLACE)
def conceal_all_floorplans(game, room, eff, ctx_room) -> None:
    pass


@effect("anti_luck", Hook.ON_PLACE)
def anti_luck(game, room, eff, ctx_room) -> None:
    """Maid's Chamber: items less likely in rooms drafted after it.

    Approximated as -N luck on placement (default N=3, mirroring Root Cellar's +3).
    Clamped at floor (0) so negative luck never misbehaves with luck_probability.
    As a red-room penalty, it is negated by Shelter.
    """
    if _red_negated(game, room):
        return
    amount = eff.param("amount", 3)
    game.state.luck = max(0, game.state.luck - amount)
