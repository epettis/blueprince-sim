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

from ..upgrades import root_base_id

logger = logging.getLogger("blueprince_sim.effects")


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
# Per (room_id, hook): whether the handler also applies to upgrade variants
# whose root base is room_id (see room_hook).
_ROOM_INHERIT: dict[tuple[str, Hook], bool] = {}


def room_hook(room_id: str, hook: Hook, *, inherit: bool = False):
    """Decorator registering a handler for one room id at one hook.

    ``inherit=False`` (the default) means the handler fires only for
    ``room_id`` itself. ``inherit=True`` also applies it to every upgrade
    variant whose root base (``upgrades.root_base_id``) is ``room_id`` --
    covering variants at any chain depth, e.g. both stages of the Spare
    Room's two-level chain -- unless the variant has its own registration
    at the same hook, which shadows the inherited one. Default False because
    of the 56 upgrade variants with both a parent and an effect_text, zero
    share their parent's text; blanket inheritance would be wrong far more
    often than right. Use inherit=True for a fixture that genuinely survives
    every upgrade, e.g. the Boudoir's safe.
    """
    def deco(fn: RoomHandler) -> RoomHandler:
        _ROOM_REGISTRY[(room_id, hook)] = fn
        _ROOM_INHERIT[(room_id, hook)] = inherit
        return fn
    return deco


def registered_rooms() -> tuple[frozenset[str], frozenset[str]]:
    """Room ids with a ``room_hook`` handler, and those whose handler inherits.

    The first set is every room id registered at any hook. The second is the
    subset registered with ``inherit=True``, which also covers upgrade
    variants whose root base is that id. Callers outside this module use this
    rather than reading the registries directly.
    """
    registered = frozenset(room_id for room_id, _hook in _ROOM_REGISTRY)
    inheriting = frozenset(
        room_id for (room_id, _hook), inherit in _ROOM_INHERIT.items() if inherit)
    return registered, inheriting


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
    if room_handler is None:
        root_id = root_base_id(game.registry, room)
        if root_id != room.id and _ROOM_INHERIT.get((root_id, hook), False):
            room_handler = _ROOM_REGISTRY.get((root_id, hook))
    if room_handler is not None:
        room_handler(game, room, context_room)


from . import tier1  # noqa: E402,F401  (registers handlers on import)
from . import rooms  # noqa: E402,F401  (registers room_hook handlers on import)
