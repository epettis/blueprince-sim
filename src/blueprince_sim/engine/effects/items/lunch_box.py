"""Lunch Box: a config-gated one-time Gift Shop unlock (``cfg.lunch_box_unlocked``)
that, once unlocked, is also guaranteed in the Dining Room, and consumes
itself for food-modified steps once the player reaches its rank threshold
(datamined "steps_at_rank" tag, checked both on pickup and on every later
arrival).
"""

from __future__ import annotations

ITEM_ID = "lunch_box"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``lunch_box`` to ``gated`` while it has not been unlocked."""
    if not cfg.lunch_box_unlocked:
        gated.append(ITEM_ID)


def hide_from_gift_shop(item_id: str, cfg) -> bool:
    """True for the Gift Shop's Lunch Box stock line once already unlocked
    (the purchase is one-time; showing it again would be a second unlock)."""
    return item_id == ITEM_ID and cfg.lunch_box_unlocked


def on_purchased(item_id: str, state) -> None:
    """Records the Gift Shop's one-time Lunch Box purchase for tomorrow's
    carry-over, when ``item_id`` is the entry that was just bought."""
    if item_id == ITEM_ID:
        state.shops.gift_unlocks.append("lunch_box_unlocked")


def grant_guaranteed(game, room) -> None:
    """Grants the Dining Room's guaranteed Lunch Box, once unlocked, on
    entering the Dining Room (or an upgrade variant) while still available."""
    if not game.cfg.lunch_box_unlocked:
        return
    if room.id != "dining_room" and room.variant_of != "dining_room":
        return
    from ...special_items import _is_available, grant
    state, registry = game.state, game.registry
    if _is_available(state, ITEM_ID, registry):
        grant(state, registry, ITEM_ID, source="guaranteed")


def check_rank_threshold(state, registry, item=None) -> None:
    """Consumes the Lunch Box and grants food-modified steps once at/above
    its rank threshold.

    The Lunch Box's step count (10, from data) is the *base* fed into the
    food pipeline, so Salt Shaker / Silver Spoon modify it: 10 -> 11 -> 22.

    Called from special_items._on_pickup (pickup at high rank) and
    special_items.on_arrive (rank-crossing check on each arrival); ``item``
    is None from on_arrive, which has no specific item in hand.
    """
    from ...grid import rank_of
    from ...special_items import food_steps, has, remove
    if item is None:
        item = registry.special.by_id.get(ITEM_ID)
        if item is None or not has(state, ITEM_ID):
            return
    e = item.effect("steps_at_rank")
    if e is None:
        return
    if rank_of(state.pos) < e.param("rank", 5):
        return
    remove(state, ITEM_ID, consumed=True)
    base = e.param("steps", 3)
    steps_gained = food_steps(state, registry, base)
    state.steps += steps_gained
    state.items_found_log.append(("food", 1))
