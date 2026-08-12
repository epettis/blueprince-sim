"""Effect registry.

Room effects are structured tags in rooms.json. Handlers register per tag and
fire at hook points. Unknown tags no-op (logged once) so the sim degrades
gracefully while data coverage grows.

Alongside the tag registry, a second registry keys handlers by room id
directly (``room_hook``), for behaviour that belongs to exactly one room
rather than to a reusable data tag.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger("blueprince_sim.effects")


class Capability(Enum):
    COMMERCE = "commerce"  # room can be bought from, traded with, or fabricated at
    LEVER = "lever"  # room pulls an Antechamber lever on first entry


_CAPABILITY_REGISTRY: set[tuple[str, Capability]] = set()


def provides(room_id: str, capability: Capability) -> None:
    """Register that ``room_id`` provides ``capability``.

    Call at import time from a room module, the same way ``room_hook``
    registers a handler -- except a capability carries no handler function,
    just the fact that the room has it, so engine code can ask "does this
    room provide X" without knowing which rooms exist.
    """
    _CAPABILITY_REGISTRY.add((room_id, capability))


def provides_capability(room_id: str, capability: Capability) -> bool:
    """Does ``room_id`` provide ``capability``? False for any unregistered id."""
    return (room_id, capability) in _CAPABILITY_REGISTRY


def validate_capability_registry(registry) -> list[str]:
    """Return every room id registered via ``provides`` that ``registry`` lacks.

    Mirrors ``validate_room_registry`` below: ``provides`` runs at import
    time, before any ``Registry`` is loaded, so a typo'd room id cannot be
    checked at registration -- it would otherwise just never match a real
    room, silently. Callers run this once a ``Registry`` exists and treat a
    nonempty result as a hard failure.
    """
    return sorted(
        {room_id for room_id, _cap in _CAPABILITY_REGISTRY if room_id not in registry.by_id})


LeverPullFn = Callable  # (game, cell) -> None
LeverCostFn = Callable  # (game, cell) -> int (keys the pull would spend right now)
_LEVER_PULL: dict[str, LeverPullFn] = {}
_LEVER_COST: dict[str, LeverCostFn] = {}


def provides_lever(room_id: str, pull: LeverPullFn, cost: LeverCostFn | None = None) -> None:
    """Register ``room_id`` as providing ``Capability.LEVER``, with its pull handler.

    Unlike ``provides``, a lever capability needs a function to call, not just
    the fact -- so this both records the capability and stores the room's own
    ``pull`` (called on first entry) and optional ``cost`` (queried ahead of
    entry to price a route; a lever costs nothing unless its own module
    registers a cost function, e.g. one gated behind a locked door).
    """
    provides(room_id, Capability.LEVER)
    _LEVER_PULL[room_id] = pull
    if cost is not None:
        _LEVER_COST[room_id] = cost


def pull_lever(game, room_id: str, cell: int) -> None:
    """Fire ``room_id``'s registered lever pull; a no-op for any other id."""
    fn = _LEVER_PULL.get(room_id)
    if fn is not None:
        fn(game, cell)


def lever_key_cost(room_id: str, game, cell: int) -> int:
    """Keys pulling ``room_id``'s lever at ``cell`` would cost right now.

    0 for any id with no registered cost function -- the common case, since
    only a lever gated behind its own locked door needs one.
    """
    fn = _LEVER_COST.get(room_id)
    return fn(game, cell) if fn is not None else 0


class Hook(Enum):
    ON_PLACE = "on_place"          # room placed on the grid (drafted)
    ON_ENTER = "on_enter"          # player enters the room (first time)
    ON_DRAFT_ROOM = "on_draft_room"  # some OTHER room was drafted (Nursery etc.)
    ON_DAY_START = "on_day_start"
    ON_DRAFT_FROM = "on_draft_from"  # a hand is initially dealt from this room's doorway
    ON_HAND_DEALT = "on_hand_dealt"  # this room appears as an option in the current hand
    ON_ARRIVE = "on_arrive"        # player arrives at this cell, every time (incl. re-entry)
    ON_DAY_END = "on_day_end"      # the day terminates (out_of_steps / dead_end)


EffectHandler = Callable  # (game, room, effect, context_room) -> None
_REGISTRY: dict[tuple[str, Hook], EffectHandler] = {}
_warned: set[str] = set()

# Default hook per tag, so data files only need "when" for the exceptions.
DEFAULT_HOOK: dict[str, Hook] = {}


def effect(tag: str, hook: Hook):
    """Decorator registering a handler for ``(tag, hook)``.

    The first registration of a tag also becomes its default hook, so data
    records only need a "when" param to fire the tag at a different hook.
    """
    def deco(fn: EffectHandler) -> EffectHandler:
        _REGISTRY[(tag, hook)] = fn
        DEFAULT_HOOK.setdefault(tag, hook)
        return fn
    return deco


RoomHandler = Callable  # (game, room, context_room) -> None
_ROOM_REGISTRY: dict[tuple[str, Hook], RoomHandler] = {}


def room_hook(room_id: str, hook: Hook):
    """Decorator registering a handler for one room id at one hook.

    The handler fires only for ``room_id`` itself, never for its upgrade
    variants.
    """
    def deco(fn: RoomHandler) -> RoomHandler:
        _ROOM_REGISTRY[(room_id, hook)] = fn
        return fn
    return deco


def registered_rooms() -> frozenset[str]:
    """Room ids with a ``room_hook`` handler at any hook.

    Callers outside this module use this rather than reading the registry
    directly.
    """
    return frozenset(room_id for room_id, _hook in _ROOM_REGISTRY)


def validate_room_registry(registry) -> list[str]:
    """Return every room id registered via ``room_hook`` that ``registry`` lacks.

    ``room_hook`` runs at import time, before any ``Registry`` is loaded, so
    a typo'd room id cannot be checked at registration -- it would otherwise
    just never fire, silently. Callers run this once a ``Registry`` exists
    (a dedicated test, here) and treat a nonempty result as a hard failure.
    """
    return sorted({room_id for room_id, _hook in _ROOM_REGISTRY if room_id not in registry.by_id})


def fire(game, room, hook: Hook, context_room=None) -> None:
    """Run all of ``room``'s effects that belong to ``hook``, then its room-id handler.

    The tag loop runs first, in its existing per-effect order -- unchanged,
    since ``inject_pool`` consumes RNG and reordering it would shift
    seed-stream consumption. The room-id lookup always runs after, in this
    one fixed position, regardless of what tags ``room`` carries.
    """
    for eff in room.effects:
        when = eff.param("when")
        eff_hook = Hook(when) if when is not None else DEFAULT_HOOK.get(eff.tag)
        if eff_hook is not hook:
            if eff_hook is None and eff.tag not in _warned:
                _warned.add(eff.tag)
                logger.info("Effect tag %r has no registered handler; ignored", eff.tag)
            continue
        handler = _REGISTRY.get((eff.tag, hook))
        if handler is not None:
            handler(game, room, eff, context_room)

    room_handler = _ROOM_REGISTRY.get((room.id, hook))
    if room_handler is not None:
        room_handler(game, room, context_room)


from . import tier1  # noqa: E402,F401  (registers handlers on import)
from . import rooms  # noqa: E402,F401  (registers room_hook handlers on import)
