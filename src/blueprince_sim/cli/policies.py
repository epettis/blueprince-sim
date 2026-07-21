"""Scripted heuristic policies for batch evaluation.

A policy is ``fn(game, rnd) -> None`` executing one decision. Policies act on
the Game API directly (not the env encoding) for speed and clarity.

Drafting and moving are separate actions: a policy drafts a room at a doorway,
then walks into it (and onward) to spend steps and collect resources. The
navigation helper below pushes the frontier toward the Antechamber.
"""

from __future__ import annotations

import random

from ..engine.game import ANTECHAMBER_CELL, Game, Phase, RedrawKind
from ..engine.grid import N, neighbor, rank_of


def _affordable(game: Game):
    p = game.state.pending
    return [o for o in p.options
            if game.affordable(game.registry.rooms[o.room_idx], o)]


def _navigate_north(game: Game) -> None:
    """One NAVIGATE decision that pushes toward the Antechamber.

    Priority: (1) step into the Antechamber to win, (2) move into a freshly
    drafted room we haven't entered (deepest first), (3) draft a doorway of the
    current room (north first), (4) otherwise walk toward the deepest neighbor.
    """
    st = game.state
    pos = st.pos

    moves = game.adjacent_moves()
    for d in moves:
        if neighbor(pos, d) == ANTECHAMBER_CELL:
            game.move(d)
            return

    unentered = [d for d in moves if not st.entered[neighbor(pos, d)]]
    if unentered:
        unentered.sort(key=lambda d: -rank_of(neighbor(pos, d)))
        game.move(unentered[0])
        return

    doors = game.open_doorways()
    if doors:
        doors.sort(key=lambda cd: cd[1] != N)  # north door first
        game.open_door(*doors[0])
        return

    if moves:  # everything adjacent already entered: walk toward deeper rooms
        moves.sort(key=lambda d: -rank_of(neighbor(pos, d)))
        game.move(moves[0])
        return

    game._check_termination()


def _forced_slot(game: Game) -> int:
    """Lowest slot as a last resort - slot 0 is always the free fallback."""
    return min(o.slot for o in game.state.pending.options)


def random_policy(game: Game, rnd: random.Random) -> None:
    if game.phase is Phase.DRAFTING:
        opts = _affordable(game)
        # No decline: opening a door commits you to taking a room.
        game.choose(rnd.choice(opts).slot if opts else _forced_slot(game))
        return
    choices: list[tuple[str, int]] = [("move", d) for d in game.adjacent_moves()]
    choices += [("draft", d) for _cell, d in game.open_doorways()]
    if not choices:
        game._check_termination()
        return
    kind, d = rnd.choice(choices)
    if kind == "move":
        game.move(d)
    else:
        game.open_door(game.state.pos, d)


def _choose_best(game: Game, weights: dict) -> None:
    """DRAFTING decision: score affordable options, redraw weak hands if cheap."""
    opts = _affordable(game)
    if not opts:  # no decline: fall back to the guaranteed free slot
        game.choose(_forced_slot(game))
        return
    best, best_score = None, -1e9
    for o in opts:
        room = game.registry.rooms[o.room_idx]
        score = bin(o.orientation).count("1") * weights["connectivity"]
        if o.orientation & N:
            score += weights["north"]
        score += sum(c for _, c in room.items.guaranteed) * weights.get("items", 0.0)
        score -= game._effective_cost(room, o) * weights["cost"]
        if room.category == "red":
            score -= weights["red_penalty"]
        if best_score < score:
            best, best_score = o, score
    p = game.state.pending
    if best_score < weights.get("redraw_below", -1e9):
        if p.redraws_left > 0:
            game.redraw(RedrawKind.FREE)
            return
        if game.state.dice > 0:
            game.redraw(RedrawKind.DIE)
            return
    game.choose(best.slot)


_GREEDY_WEIGHTS = {"connectivity": 1.5, "north": 2.5, "cost": 0.5, "red_penalty": 2.0}
_ECONOMY_WEIGHTS = {"connectivity": 1.2, "north": 2.0, "items": 0.8, "cost": 0.4,
                    "red_penalty": 2.5, "redraw_below": 2.0}


def greedy_rank(game: Game, rnd: random.Random) -> None:
    """Push north; prefer high-connectivity rooms with north doors."""
    if game.phase is Phase.NAVIGATE:
        _navigate_north(game)
    else:
        _choose_best(game, _GREEDY_WEIGHTS)


def economy(game: Game, rnd: random.Random) -> None:
    """Like greedy_rank but values resource rooms and redraws on bad hands."""
    if game.phase is Phase.NAVIGATE:
        _navigate_north(game)
    else:
        _choose_best(game, _ECONOMY_WEIGHTS)


POLICIES = {"random": random_policy, "greedy_rank": greedy_rank, "economy": economy}
