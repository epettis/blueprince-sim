"""Room 8: allowance reward on entry, standing in for the figure-shelf puzzle.

Implemented:
  - award_allowance -- grants Allowance Tokens on entry, per the sim's
    assumed-solved doctrine (see e.g. every Mora Jai box): a structurally
    identical multi-step in-room puzzle that this sim resolves on first entry
    rather than modelling step by step. The first solve of an attempt grants
    two Allowance Tokens; every later solve, including a second Room 8 drafted
    the same day, grants one. Room 8 resets each time it is drafted, so each
    placed Room 8 pays on its own first entry rather than once per attempt.

Not modelled:
  - Trophy 8: not represented anywhere in the sim -- trophies are achievements,
    not game state.
  - The eight figure pickups and their placement onto the shelves: the sim's
    assumed-solved doctrine grants the reward on entry instead of modelling
    each figure individually.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

ALLOWANCE_PER_TOKEN = 2  # an Allowance Token is worth +2 allowance
FIRST_SOLVE_ALLOWANCE = 2 * ALLOWANCE_PER_TOKEN  # first solve: two Allowance Tokens
LATER_SOLVE_ALLOWANCE = 1 * ALLOWANCE_PER_TOKEN  # later solves: one Allowance Token


@room_hook("room_8", Hook.ON_ENTER)
def award_allowance(game, room, ctx_room) -> None:
    """"Placing all eight figures correctly causes a wall segment near the
    figure shelves to raise and present the player with Trophy 8 and two
    Allowance Tokens." "If Room 8 is solved after the trophy has already been
    collected, it instead contains a single Allowance Token."
    """
    already_solved = game.cfg.room8_solved or game.state.room8_solved
    amount = LATER_SOLVE_ALLOWANCE if already_solved else FIRST_SOLVE_ALLOWANCE
    _grant(game, "allowance", amount)
    game.state.room8_solved = True
