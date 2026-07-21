"""Scripted heuristic policies for batch evaluation.

A policy is ``fn(game, rnd) -> None`` executing one decision. Policies act on
the Game API directly (not the env encoding) for speed and clarity.
"""

from __future__ import annotations

import random

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import N, rank_of


def _affordable(game: Game):
    p = game.state.pending
    return [o for o in p.options
            if game.state.gems >= game._effective_cost(game.registry.rooms[o.room_idx], o)]


def random_policy(game: Game, rnd: random.Random) -> None:
    if game.phase is Phase.NAVIGATE:
        doors = game.open_doorways()
        if doors:
            game.open_door(*rnd.choice(doors))
        else:
            game._check_termination()
    else:
        opts = _affordable(game)
        if opts:
            game.choose(rnd.choice(opts).slot)
        else:
            game.decline()


def greedy_rank(game: Game, rnd: random.Random) -> None:
    """Push north; prefer high-connectivity rooms with north doors."""
    if game.phase is Phase.NAVIGATE:
        doors = game.open_doorways()
        if not doors:
            game._check_termination()
            return
        doors.sort(key=lambda cd: (-rank_of(cd[0]), cd[1] != N))
        game.open_door(*doors[0])
        return
    opts = _affordable(game)
    if not opts:
        game.decline()
        return
    best, best_score = None, -1e9
    for o in opts:
        room = game.registry.rooms[o.room_idx]
        score = bin(o.orientation).count("1") * 1.5
        if o.orientation & N:
            score += 2.5
        score -= game._effective_cost(room, o) * 0.5
        if room.category == "red":
            score -= 2.0
        if best_score < score:
            best, best_score = o, score
    game.choose(best.slot)


def economy(game: Game, rnd: random.Random) -> None:
    """Like greedy_rank but values resource rooms and uses redraws on bad hands."""
    if game.phase is Phase.NAVIGATE:
        greedy_rank(game, rnd)
        return
    opts = _affordable(game)
    p = game.state.pending
    best, best_score = None, -1e9
    for o in opts:
        room = game.registry.rooms[o.room_idx]
        score = bin(o.orientation).count("1") * 1.2
        if o.orientation & N:
            score += 2.0
        score += sum(c for _, c in room.items.guaranteed) * 0.8
        score -= game._effective_cost(room, o) * 0.4
        if room.category == "red":
            score -= 2.5
        if best_score < score:
            best, best_score = o, score
    if best is None:
        game.decline()
        return
    # Redraw weak hands when free/cheap redraws are available.
    if best_score < 2.0:
        if p.redraws_left > 0:
            game.redraw(RedrawKind.FREE)
            return
        if game.state.dice > 0:
            game.redraw(RedrawKind.DIE)
            return
    game.choose(best.slot)


POLICIES = {"random": random_policy, "greedy_rank": greedy_rank, "economy": economy}
