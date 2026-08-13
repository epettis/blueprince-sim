"""Crown of the Blueprints: guaranteed in Room 46, but gated out of the
spawn pipeline until Room 46 has been reached on an earlier day
(``cfg.room46_reached``).

The wiki's obtain rule is *"It cannot be obtained the first time the room is
reached, but is present in other times."* ``cfg.room46_reached`` is the
permanent carry-over flag that first turns True at the *next* day's reset, so
reading it here blocks the whole day on which Room 46 is first entered and
allows every later day -- the same day-granularity convention the eight
Sanctum Keys already use for this flag (special_items.configure) and that
``GameConfig.gem_gate_active`` uses.

The effect (owner ruling 2026-08-12, overriding the wiki): while holding the
Crown, drawing a Red Room (Room.is_category('red')) offers a once-per-hand
option to filter that room id from EVERY draw for the rest of the day -- no
exemption for colour-selective drafts, the Silver Key, the Prism Key, or
ducts, contrary to the wiki's "Drafting/Advanced" page. Taking the option
grants 1 gem and redeals the hand (Game.crown_block); the filter itself lives
in draft.py::room_draftable, keyed off ``SpecialItemsState.crown_blocked_rooms``.
This module owns the item id and the two predicates gating that mechanic;
the room-id filter check itself is exposed id-free via
special_items.crown_room_blocked_from_state for draft.py to call.
"""

from __future__ import annotations

ITEM_ID = "crown_of_the_blueprints"
TAG = "crown_of_blueprints"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``crown_of_the_blueprints`` to ``gated`` until Room 46 has been
    reached on an earlier day."""
    if not cfg.room46_reached:
        gated.append(ITEM_ID)


def block_offered(state, registry, room) -> bool:
    """True when the Crown's once-per-hand filter option is offered for a
    dealt ``room`` at a draft slot.

    Requires the item held, its own data record still carrying the
    crown_of_blueprints tag (defensive, mirrors knights_shield.py's guard),
    the filter not already spent on the CURRENT hand
    (``SpecialItemsState.crown_block_used``), and ``room`` being a Red Room
    (Room.is_category('red') -- 18 rooms, not just the 13 whose ``category``
    field literally reads "red"; the Aquarium family counts as every colour).
    """
    if state.inventory.get(ITEM_ID, 0) <= 0:
        return False
    item = registry.special.by_id.get(ITEM_ID)
    if item is None or item.effect(TAG) is None:
        return False
    if state.special.crown_block_used:
        return False
    return room.is_category("red")


def is_blocked(state, room_id: str) -> bool:
    """True when ``room_id`` has already been filtered from every draw for
    the rest of today by an earlier Crown use this day."""
    return room_id in state.special.crown_blocked_rooms
