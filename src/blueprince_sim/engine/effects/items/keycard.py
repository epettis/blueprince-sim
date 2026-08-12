"""Keycard: rolls a per-entry grant chance on arriving at one of locks.json's
source rooms, opens security doors while held (locks.py's own wiring reads
``state.has_keycard`` directly), can be stolen by the Lost & Found, and is a
late-game Garage car trunk pick once the Upgrade Disk has been spent.

Lives on ``state.has_keycard`` rather than the inventory dict -- kept there so
the security-door system stays self-contained -- so every site that grants,
steals, or queries it goes through this module instead of touching the flag
directly.
"""

from __future__ import annotations

ITEM_ID = "keycard"


def held(state) -> bool:
    """True while the Keycard is currently held."""
    return state.has_keycard


def grant(state) -> str:
    """Grants the Keycard and logs the pickup; returns the item id as a
    grant-log tag."""
    state.has_keycard = True
    state.items_found_log.append((ITEM_ID, 1))
    return ITEM_ID


def steal(state) -> None:
    """Lost & Found steal: clears ``has_keycard`` so the Keycard becomes
    re-findable via its own source-room rolls again."""
    state.has_keycard = False


def roll_source_room_grant(game, room) -> None:
    """Rolls the Keycard's chance grant on arriving at a locks.json source
    room, unless already held. Called from ``Game._enter`` under
    ``cfg.door_locks``.
    """
    state = game.state
    if held(state):
        return
    kc = game.registry.lock_rules[ITEM_ID]
    if room.id in kc["source_rooms"] and game.rng.chance(ITEM_ID, kc["chance"] / 100.0):
        grant(state)
