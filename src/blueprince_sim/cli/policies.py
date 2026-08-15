"""Scripted heuristic policies for batch evaluation.

A policy is ``fn(game, rnd) -> None`` executing one decision. Policies act on
the Game API directly (not the env encoding) for speed and clarity.

Drafting and moving are separate actions: a policy drafts a room at a doorway,
then walks into it (and onward) to spend steps and collect resources. The
navigation helper below pushes the frontier toward the Antechamber.
"""

from __future__ import annotations

import random

from ..engine import locks
from ..engine.draft import COLOUR_CATEGORIES
from ..engine.game import ANTECHAMBER_CELL, Game, Phase, RedrawKind
from ..engine.grid import N, neighbor, rank_of
from ..engine.model import RARITIES


def _affordable(game: Game):
    """Pending draft options the player can currently pay for."""
    p = game.state.pending
    return [o for o in p.options
            if game.affordable(game.registry.rooms[o.room_idx], o)]


def _can_open_security_somehow(game: Game) -> bool:
    """Openable now, or after a walk to the Utility Closet breaker."""
    if game.security_openable():
        return True
    st = game.state
    if game.room_cells.get("utility_closet", -1) < 0:
        return False
    return st.offline_unlocked or st.has_keycard


def _security_admin(game: Game) -> bool:
    """One switch-flip per the greedy doctrine; True if an action was taken.

    Utility Closet: without the Keycard, cut the keycard power so every
    security door swings open once Security's offline mode is Unlocked (a
    Security visit sets that); with the Keycard, keep the readers powered so
    the card works. Security terminal: crank the frequency to high when
    security doors are effectively free doorways for us, drop it to low when
    they would just wall off the house.
    """
    st = game.state
    if not game.cfg.door_locks:
        return False
    if game.can_toggle_keycard_power():
        want_on = st.has_keycard
        if st.keycard_power_on != want_on:
            game.set_keycard_power(want_on)
            return True
    if game.can_set_security_level():
        want = "high" if _can_open_security_somehow(game) else "low"
        if st.security_level != want:
            game.set_security_level(want)
            return True
    return False


def _security_detour(game: Game) -> bool:
    """Walk to the Utility Closet when flipping the power would open security
    doorways we otherwise cannot pass; True if the walk was taken."""
    st = game.state
    if game.security_openable() or not game._security_toggle_helps():
        return False
    uc = game.room_cells.get("utility_closet", -1)
    dist = game.distance_map()
    if uc < 0 or st.pos == uc or not 0 <= dist[uc] <= st.steps - 2:
        return False
    game.move_to(uc)
    return True


def _navigate_north(game: Game) -> None:
    """One NAVIGATE decision that pushes toward the Antechamber.

    Priority: (1) step into the Antechamber to win, (2) move into a freshly
    drafted room we haven't entered (deepest first), (3) draft a doorway of the
    current room (north first), (4) otherwise walk toward the deepest neighbor.
    """
    st = game.state
    pos = st.pos

    if _security_admin(game):
        return

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

    doors = [cd for cd in game.open_doorways() if game.doorway_passable(*cd)]
    if doors:
        doors.sort(key=lambda cd: cd[1] != N)  # north door first
        game.open_door(*doors[0])
        return

    if moves:  # everything adjacent already entered: walk toward deeper rooms
        moves.sort(key=lambda d: -rank_of(neighbor(pos, d)))
        game.move(moves[0])
        return

    if _security_detour(game):
        return

    game._check_termination()


def _forced_slot(game: Game) -> int:
    """Lowest dealt slot as a last resort - the hand's first presented option
    is always granted free (draft.py::waive_first_option), so this slot is
    always affordable, whether or not the deal filled slot 0."""
    return min(o.slot for o in game.state.pending.options)


def _colour_pending(game: Game, rnd: random.Random) -> bool:
    """COLOUR_PENDING decision (a Secret Passage door was just opened): pick a
    uniform random colour. True if a decision was taken, so callers can
    return immediately -- shared by every policy below, since none of them
    has an opinion on which colour to draft."""
    if game.phase is not Phase.COLOUR_PENDING:
        return False
    game.choose_colour(rnd.choice(COLOUR_CATEGORIES))
    return True


def _lock_pending_choices(game: Game) -> list:
    """Every legal LOCK_PENDING action right now, as zero-arg callables.

    ``abandon`` is always included (Game.can_abandon_lock is unconditional
    in this phase), so the list is never empty."""
    choices = []
    if game.can_use_key_at_lock():
        choices.append(game.use_key_at_lock)
    if game.can_lockpick_at_lock():
        choices.append(game.lockpick_at_lock)
    for key_id in game.registry.lock_rules["special_key_menu"]["order"]:
        if game.can_use_special_key_at_lock(key_id):
            choices.append(lambda g=game, k=key_id: g.use_special_key_at_lock(k))
    choices.append(game.abandon_lock)
    return choices


def _wrench_pending(game: Game, rnd: random.Random) -> bool:
    """WRENCH_PENDING decision (a Mechanical Room was just drafted while
    holding the Gear Wrench): pick a uniform random rarity level. True if a
    decision was taken, so callers can return immediately -- shared by every
    policy below, same shape as _colour_pending, since none of them has an
    opinion on rarity manipulation."""
    if game.phase is not Phase.WRENCH_PENDING:
        return False
    game.set_wrench_rarity(rnd.randrange(len(RARITIES)))
    return True


def _lock_pending_random(game: Game, rnd: random.Random) -> bool:
    """LOCK_PENDING decision: pick uniformly among every legal row (matching
    _colour_pending's uniform-random spirit for random_policy). True if a
    decision was taken, so callers can return immediately. A lockpick
    failure leaves the phase unchanged (Game.lockpick_at_lock), so this may
    need to be called again on the next tick -- the same shape as any other
    still-NAVIGATE decision that made no progress."""
    if game.phase is not Phase.LOCK_PENDING:
        return False
    rnd.choice(_lock_pending_choices(game))()
    return True


def _lock_pending_greedy(game: Game, rnd: random.Random) -> bool:
    """LOCK_PENDING decision for the greedy/economy/frontier policies: prefer
    a reusable Master Key, then spend a regular key, then any other held and
    fitting special key, else abandon. Deliberately skips the lockpick row
    (probabilistic; a scripted heuristic has no use for a chance of staying
    parked in the same phase) so this always makes progress in one call.
    True if a decision was taken, so callers can return immediately.
    """
    if game.phase is not Phase.LOCK_PENDING:
        return False
    if game.can_use_special_key_at_lock("master_key"):
        game.use_special_key_at_lock("master_key")
    elif game.can_use_key_at_lock():
        game.use_key_at_lock()
    else:
        for key_id in game.registry.lock_rules["special_key_menu"]["order"]:
            if key_id != "master_key" and game.can_use_special_key_at_lock(key_id):
                game.use_special_key_at_lock(key_id)
                return True
        game.abandon_lock()
    return True


def random_policy(game: Game, rnd: random.Random) -> None:
    """Uniform random baseline: pick any affordable option / any legal move or draft."""
    if _colour_pending(game, rnd):
        return
    if _lock_pending_random(game, rnd):
        return
    if _wrench_pending(game, rnd):
        return
    if game.phase is Phase.DRAFTING:
        opts = _affordable(game)
        # No decline: opening a door commits you to taking a room.
        game.choose(rnd.choice(opts).slot if opts else _forced_slot(game))
        return
    choices: list[tuple[str, int]] = [("move", d) for d in game.adjacent_moves()]
    choices += [("draft", d) for cell, d in game.open_doorways()
                if game.doorway_passable(cell, d)]
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
_FRONTIER_LAMBDA = 1.5  # weight on optimistic Antechamber distance vs walk cost


def _navigate_frontier(game: Game) -> None:
    """One NAVIGATE decision: best-first frontier expansion toward the Antechamber.

    Priority: (1) walk into the Antechamber when it is connected and within
    the step budget, (2) draft the frontier doorway (anywhere reachable, via
    :meth:`Game.draft_from`) minimizing steps_to_reach + lambda * optimistic
    distance from the doorway's target to the Antechamber, (3) enter the
    nearest unentered room for its pickups.

    A locked frontier doorway's affordability is judged by
    :meth:`Game._frontier_lock_affordable` -- the same predicate
    :meth:`Game._action_in_budget` uses to decide whether the day can still
    progress -- rather than a plain key-count comparison, so this policy
    never treats a door as unaffordable (and falls through to the terminal
    ``_check_termination`` call below) while the engine itself still
    considers a Master Key, a fitting Silver/Prism Key, or a Stopwatch
    refund enough to open it; disagreeing here would stall the policy in
    NAVIGATE forever, since the day is not actually over.
    """
    st = game.state
    if _security_admin(game):
        return
    dist = game.distance_map()
    if 0 < dist[ANTECHAMBER_CELL] <= st.steps:
        game.move_to(ANTECHAMBER_CELL)
        return
    opt_dist = game.optimistic_distances()
    key_cost = game.key_cost_map()
    best, best_key = None, None
    security_blocked = False
    for cell, d in game.frontier_doorways():
        if not 0 <= dist[cell] <= st.steps - 1:  # must arrive with a step to spare
            continue
        seg = game.door_state_of(cell, d)
        if seg == locks.DOOR_LOCKED and not game._frontier_lock_affordable(cell, d, key_cost[cell]):
            continue
        if seg == locks.DOOR_SECURITY and not game.security_openable():
            security_blocked = True
            continue
        target = neighbor(cell, d)
        h = opt_dist[target] if opt_dist[target] >= 0 else 99  # walled off: last resort
        key = (dist[cell] + _FRONTIER_LAMBDA * h, h, cell, d)
        if best_key is None or key < best_key:
            best, best_key = (cell, d), key
    if best is not None:
        game.draft_from(*best)
        return
    if security_blocked and _security_detour(game):
        return
    unentered = [c for c in range(len(dist))
                 if 0 < dist[c] <= st.steps and not st.entered[c]]
    if unentered:
        unentered.sort(key=lambda c: (dist[c], c))
        game.move_to(unentered[0])
        return
    game._check_termination()


def frontier_greedy(game: Game, rnd: random.Random) -> None:
    """Draft anywhere reachable, best-first toward the Antechamber."""
    if _colour_pending(game, rnd):
        return
    if _lock_pending_greedy(game, rnd):
        return
    if _wrench_pending(game, rnd):
        return
    if game.phase is Phase.NAVIGATE:
        _navigate_frontier(game)
    else:
        _choose_best(game, _GREEDY_WEIGHTS)


def greedy_rank(game: Game, rnd: random.Random) -> None:
    """Push north; prefer high-connectivity rooms with north doors."""
    if _colour_pending(game, rnd):
        return
    if _lock_pending_greedy(game, rnd):
        return
    if _wrench_pending(game, rnd):
        return
    if game.phase is Phase.NAVIGATE:
        _navigate_north(game)
    else:
        _choose_best(game, _GREEDY_WEIGHTS)


def economy(game: Game, rnd: random.Random) -> None:
    """Like greedy_rank but values resource rooms and redraws on bad hands."""
    if _colour_pending(game, rnd):
        return
    if _lock_pending_greedy(game, rnd):
        return
    if _wrench_pending(game, rnd):
        return
    if game.phase is Phase.NAVIGATE:
        _navigate_north(game)
    else:
        _choose_best(game, _ECONOMY_WEIGHTS)


POLICIES = {"random": random_policy, "greedy_rank": greedy_rank, "economy": economy,
            "frontier_greedy": frontier_greedy}
