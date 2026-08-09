"""Bunk Room upgrade variants: each doubles one resource when the variant
itself is drafted with exactly 2 rooms of a given category already in the
house. Each variant reads a different category and doubles a different
resource (see each function below; resources come from the record's
``meta.glyph_resolution``, not the raw effect_text glyph).

The trigger is keyed to the variant's own draft (``room is ctx_room``), not
to category drafts in general, so a Bunk Room already on the grid does not
re-check itself every time some other room is drafted afterward. The counted
category is never "bedroom", so whether the Bunk Room's own placement (already
on the grid by the time this hook runs) counts toward its own total is moot:
its category is "bedroom", which can never match "hallway", "green", or
"shop".

Doubling reads the current resource total and adds that same amount back, so
doubling a zero total is a no-op, and clamping (gems/keys/coins never go
negative) matches every other grant in the game.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

REQUIRED_COUNT = 2  # exact count of the category needed for the doubling to fire


def _category_count(game, category: str) -> int:
    """Number of rooms of ``category`` currently placed on the grid."""
    return sum(
        1 for idx in game.state.grid
        if idx >= 0 and game.registry.rooms[idx].category == category
    )


def _double_on_exact_count(game, room, ctx_room, category: str, resource: str) -> None:
    """Double ``resource`` if ``room`` is the room just drafted and the house
    has exactly ``REQUIRED_COUNT`` rooms of ``category``."""
    if room is not ctx_room:
        return
    if _category_count(game, category) != REQUIRED_COUNT:
        return
    current = getattr(game.state, resource)
    if current:
        _grant(game, resource, current)


@room_hook("bunk_room__ix20", Hook.ON_DRAFT_ROOM)
def double_keys_on_two_hallways(game, room, ctx_room) -> None:
    """"exactly 2 HALLWAYS when drafting this room, DOUBLE your <key>"."""
    _double_on_exact_count(game, room, ctx_room, "hallway", "keys")


@room_hook("bunk_room__ix21", Hook.ON_DRAFT_ROOM)
def double_gems_on_two_green_rooms(game, room, ctx_room) -> None:
    """"exactly 2 GREEN ROOMS when drafting this room, DOUBLE your <gem>"."""
    _double_on_exact_count(game, room, ctx_room, "green", "gems")


@room_hook("bunk_room__ix22", Hook.ON_DRAFT_ROOM)
def double_coins_on_two_shops(game, room, ctx_room) -> None:
    """"exactly 2 SHOPS when drafting this room, DOUBLE your <coins>"."""
    _double_on_exact_count(game, room, ctx_room, "shop", "coins")
