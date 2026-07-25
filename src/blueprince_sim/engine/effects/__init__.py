"""Effect registry.

Room effects are structured tags in rooms.json. Handlers register per tag and
fire at hook points. Unknown tags no-op (logged once) so the sim degrades
gracefully while data coverage grows.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger("blueprince_sim.effects")


class Hook(Enum):
    ON_PLACE = "on_place"          # room placed on the grid (drafted)
    ON_ENTER = "on_enter"          # player enters the room (first time)
    ON_DRAFT_ROOM = "on_draft_room"  # some OTHER room was drafted (Nursery etc.)
    ON_DAY_START = "on_day_start"


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


def fire(game, room, hook: Hook, context_room=None) -> None:
    """Run all of ``room``'s effects that belong to ``hook``."""
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


from . import tier1  # noqa: E402,F401  (registers handlers on import)
