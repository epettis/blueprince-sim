"""Patio and Spare Patio: on placement, spread one gem to each Green Room.

Implemented:
  - spread_gems -- "The Patio spreads 1 gem to each Green Room when
    drafted" (wiki Gems page); "This includes the Patio itself, but not any
    Green Room drafted after the Patio" (wiki Patio page). Deterministic:
    every occupied cell whose room ``is_category("green")`` at the draft
    moment gets exactly one gem parked in GameState.spread_pending, paid out
    on arrival (Game._collect_spread) -- not a sampled subset, not a chance
    roll. A Conference Room already on the estate redirects every one of
    those gems, including the one the Patio would have kept for itself,
    into the Conference Room's own cell instead.
  - Spare Patio (spare_patio__ix142) registers its own identical handler;
    sourced separately from the base Patio, not assumed from matching text.

Not modelled:
  - Gem colour: gems are cosmetically green or blue but "the differences are
    purely cosmetic and are lost once the gems are collected" (wiki Gems
    page), so no colour is tracked and the green-to-blue switch under a
    Conference Room needs no representation.
"""

from __future__ import annotations

from .. import Hook, room_hook


def _spread_gems(game, room) -> None:
    """Park one gem per Green Room on the estate, or redirect all of them
    into a Conference Room's cell if one is already placed -- see the
    module docstring.
    """
    state = game.state
    cell = game.room_cells.get(room.id)
    if cell is None:
        return  # no grid cell to spread from

    green_cells = [c for c, idx in enumerate(state.grid)
                   if idx >= 0 and game.registry.rooms[idx].is_category("green")]
    if not green_cells:
        return

    conference_cell = game.room_cells.get("conference_room")
    if conference_cell is not None:
        state.spread_pending.setdefault(conference_cell, []).append(("gem", len(green_cells)))
        return

    for target_cell in green_cells:
        state.spread_pending.setdefault(target_cell, []).append(("gem", 1))


@room_hook("patio", Hook.ON_PLACE)
def spread_gems_patio(game, room, ctx_room) -> None:
    """"Spread 1 gem to each Green Room" -- see the module docstring."""
    _spread_gems(game, room)


@room_hook("spare_patio__ix142", Hook.ON_PLACE)
def spread_gems_spare_patio(game, room, ctx_room) -> None:
    """Spare Patio: the same gem spread as the base Patio -- see the module docstring."""
    _spread_gems(game, room)
