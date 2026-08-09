"""Hovel: lets the player pay rooms' gem costs with steps instead.

The 3-steps-per-gem ratio is enforced where the cost is charged
(``Game._effective_cost`` / ``Game._pay``); this only flips the flag that
switches payment from gems to steps.
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("hovel", Hook.ON_PLACE)
def enable_step_payment(game, room, ctx_room) -> None:
    game.hovel_placed = True
