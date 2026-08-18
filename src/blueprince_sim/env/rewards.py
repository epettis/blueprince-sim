"""Pluggable reward functions."""

from __future__ import annotations

from typing import Protocol

from ..engine.game import ANTECHAMBER_CELL, Game
from ..engine.grid import DIRS, N_CELLS, neighbor, rank_of
from ..engine.special_items import inventory_value

# ---------------------------------------------------------------------------
# Path-preservation shaping knobs — tunable constants
# ---------------------------------------------------------------------------
# The owner's doctrine: always keep at least TWO pathways toward the
# Antechamber open; drafting the last route closed should be scored very
# negatively, dwarfing any dead-end room's resource payout.
PATHS_ONE_PENALTY: float = -0.15   # potential when exactly 1 route survives
PATHS_ZERO_PENALTY: float = -1.0   # potential when all routes are sealed
ANTECHAMBER_REWARD: float = 0.25   # first Antechamber arrival each day (milestone)
NORTH_DOOR_REWARD: float = 0.5     # north door open AND Antechamber reached (either lever)
ROOM46_REWARD: float = 1.0         # first Room 46 arrival each day (win)
# Paid per way forward a newly placed room opens (see _open_ways). Small,
# certain and paid ON the placement, against a phi_paths risk that is also
# charged there -- see shaped()'s docstring for why the two must land together.
FRONTIER_PLACEMENT_BONUS: float = 0.01
# Repetition brake. A (location, action) pair may be applied REPEAT_FREE_USES
# times a day for nothing; past that each further use costs
# REPEAT_PENALTY_STEP more than the last, up to REPEAT_PENALTY_CAP steps of
# escalation. Only zero-step actions are counted -- see
# GameState.repeat_counts.
REPEAT_FREE_USES: int = 3
REPEAT_PENALTY_STEP: float = 0.01
REPEAT_PENALTY_CAP: int = 5


class RewardFn(Protocol):
    def __call__(self, game: Game, prev_snapshot: dict, terminated: bool) -> float: ...


def _key_multiplier(rank: int) -> float:
    """How much a held key is worth at a given deepest rank, relative to its
    base value: 1.0 through rank 3 (locks never roll by chance below rank 4),
    then +0.5 per rank, reaching 4.0 at rank 9."""
    return 1.0 + 0.5 * max(0, rank - 3)


def _rank_potential(rank: int) -> float:
    """Cumulative value of reaching a deepest rank: 0.05 per rank through
    rank 4, 0.15 per rank beyond (0.90 total at rank 9), back-loading
    progress so the resource terms dominate the early gathering phase."""
    return 0.05 * min(rank - 1, 3) + 0.15 * max(0, rank - 4)


def _phi_keys(game: Game) -> float:
    """Potential of the key stock: base item value scaled by the depth
    multiplier, so keys appreciate as the run pushes into lock territory."""
    key_value = game.registry.tuning["item_values"]["key"]
    return 0.01 * game.state.keys * key_value * _key_multiplier(game.deepest_rank)


def _ante_paths(game: Game) -> int:
    """Number of live routes toward the Antechamber.

    If the Antechamber is already reachable on foot or underfoot (distance >= 0),
    returns a large constant (99) so the potential is 0 and the arrival bonuses
    are undiluted on the step that earns them.

    Otherwise counts frontier doorways whose TARGET cell has a non-(-1)
    optimistic distance to the Antechamber: drafting through that doorway could
    still lead there.  Doorways into ante-walled-off pockets (target's optimistic
    distance is -1) do not count, so dead-end islands are correctly excluded.

    Must be a pure function of the GRID (placed rooms and door masks), not of
    where the player is standing: walking off the 5x9 grid into an outer area
    does not change the house's connectivity, so this uses ``game.grid_frontier_doorways()``
    (ungated) rather than ``game.frontier_doorways()`` (returns [] off-grid).
    Using the gated ``frontier_doorways()`` instead would collapse every path to
    "sealed" and back on return while off-grid — potential-neutral overall (so
    invisible in the reward sum) but capable of masking a real 1-open-path danger
    state as 0-paths while outside, and measured to make travel actions the
    dominant behavior of a policy trained under the collapsed signal.
    """
    if game.state.room46_reached:
        return 99  # already reached Room 46; win secured, no path penalty applies
    # >= 0 covers "standing in it" (distance 0) as well as "can walk there".
    # With > 0, a player inside the Antechamber would score as paths=0, the
    # all-routes-sealed penalty -- the best state on the board rated as the
    # worst, since the player can linger there to continue north rather than
    # the day ending on arrival.
    if game.distance_map()[ANTECHAMBER_CELL] >= 0:
        return 99  # Antechamber reachable on foot, or underfoot — no path penalty
    od = game.optimistic_distances()
    return sum(
        1 for cell, d in game.grid_frontier_doorways()
        if od[neighbor(cell, d)] != -1
    )


def _phi_paths(n_paths: int) -> float:
    """Potential encoding the owner's two-open-paths doctrine.

    Returns 0.0 when two or more routes survive (healthy), PATHS_ONE_PENALTY
    (-0.15) when exactly one remains (danger), and PATHS_ZERO_PENALTY (-1.0)
    when all routes are sealed (fatal).

    Interaction with terminals:
    - Winning (walking into the Antechamber): at that moment the Antechamber
      was reachable, so _ante_paths returned 99 and the potential is 0 — the
      +1.0 win bonus is undiluted.
    - dead_end termination: the sealing draft already charged ~-1.0 (or -0.15
      for the second-to-last route), so the penalty is already baked in before
      the terminal step fires.
    """
    if n_paths == 0:
        return PATHS_ZERO_PENALTY
    if n_paths == 1:
        return PATHS_ONE_PENALTY
    return 0.0


def _phi_frontier(game: Game) -> float:
    """Potential of forward pathways: passable frontier doorways (open,
    locked with a key in hand, or security-openable) in the deepest two
    ranks, capped at 4 for diminishing returns.

    Uses ``grid_frontier_doorways`` for the same reason ``_ante_paths`` does:
    the doorways the house still offers do not change because the player
    stepped outside, and the position-gated view would collapse this
    potential to 0 for the whole of an off-grid excursion.
    """
    edge = game.deepest_rank - 1
    passable = sum(
        1 for cell, d in game.grid_frontier_doorways()
        if rank_of(cell) >= edge and game.doorway_passable(cell, d)
    )
    return 0.02 * min(passable, 4)


def _open_ways(game: Game, cell: int) -> int:
    """Doorways from ``cell`` into an empty in-grid cell: the ways forward the
    room placed there opens.

    Counts the placed room's OWN outgoing doors, never a global frontier total.
    The doorway the room was drafted through faces a cell that is already
    occupied, so it is not counted, and the count is therefore bounded by 3
    without needing a cap. A Dead End scores 0.
    """
    mask = game.state.placed_doors[cell]
    n = 0
    for d in DIRS:
        if not mask & d:
            continue
        nb = neighbor(cell, d)
        if 0 <= nb < N_CELLS and game.state.grid[nb] < 0:
            n += 1
    return n


def _placement_frontier(game: Game, prev: dict) -> float:
    """Bonus for the ways forward opened by rooms placed since ``prev``.

    Paid at placement rather than on entry, which is the point: every other
    positive term in :func:`shaped` lands when the player *enters* a room, one
    decision later, while the ``phi_paths`` risk of that placement is charged
    immediately. Measured over masked-random fresh-save days, that left
    ``choose`` a near-zero-mean action (+0.0009) with a fat negative tail (8.9%
    of placements at or below -0.15, worst -1.0) against a certain, bounded
    -0.002 for a travel hop -- so burning the day on outdoor travel dominated
    drafting on risk without losing anything on mean.

    Not potential-based, so it does change the optimal policy, deliberately.
    It cannot be farmed: a cell is placed once and the grid holds 45 of them,
    so the whole term is bounded by the board rather than by a cap. It is
    deliberately NOT shared with :func:`phased`, which prices forward pathways
    its own way through :func:`_phi_frontier`.
    """
    filled = prev["filled"]
    total = 0
    for cell in range(N_CELLS):
        if game.state.grid[cell] >= 0 and not filled[cell]:
            total += _open_ways(game, cell)
    return FRONTIER_PLACEMENT_BONUS * total


def repetition_penalty(uses: int) -> float:
    """Cost of the ``uses``-th application of one (location, action) pair.

    Zero for the first ``REPEAT_FREE_USES``, then escalating by
    ``REPEAT_PENALTY_STEP`` per further use and flattening at
    ``REPEAT_PENALTY_CAP`` steps. Escalating rather than flat so the rare
    legitimate fourth use is nearly free while a hundredth is not, and capped
    so a long loop cannot produce an unbounded single-step return that would
    swamp the value function.
    """
    over = uses - REPEAT_FREE_USES
    if over <= 0:
        return 0.0
    return REPEAT_PENALTY_STEP * min(over, REPEAT_PENALTY_CAP)


def _north_door_credited(game: Game) -> bool:
    """Whether the north-door milestone has been earned: the door is open AND
    the Antechamber has been reached today.

    Both conditions are required because an open north door only advances the
    objective for a player who can also stand in the Antechamber.  Room 46 sits
    behind the ``antechamber -> room_46`` area edge, the only way in, so the
    door on its own leads nowhere; and every day start re-seals the segment
    (``Game.reset`` under ``antechamber_levers``), so a lever pulled on a day
    the Antechamber is never reached leaves nothing behind for tomorrow either.

    Order does not matter — whichever condition lands second earns the reward,
    so the Sanctum route (Antechamber first, lever second) and a lever pulled
    on the way in both pay exactly once.
    """
    return game.state.north_door_opened and game.state.antechamber_reached


def _milestones(game: Game, prev: dict) -> float:
    """The three objective milestones, each paid on the first step that earns it.

    Shared verbatim by :func:`sparse`, :func:`shaped` and :func:`phased`: the
    milestone signal is the one part of the reward that must not vary between
    modes, so all three read this single site rather than repeating the block.
    ``test_sanctum_route.py`` pins the three against each other.
    """
    st = game.state
    r = 0.0
    if st.antechamber_reached and not prev["antechamber_reached"]:
        r += ANTECHAMBER_REWARD
    if _north_door_credited(game) and not prev["north_door_credited"]:
        r += NORTH_DOOR_REWARD
    if st.room46_reached and not prev["room46_reached"]:
        r += ROOM46_REWARD
    return r


def snapshot(game: Game) -> dict:
    """Pre-action baseline (deepest rank, resource counts, shaping potentials)
    for delta-based rewards."""
    st = game.state
    return {
        "deepest_rank": game.deepest_rank,
        "steps": st.steps, "gems": st.gems, "keys": st.keys,
        "coins": st.coins, "dice": st.dice,
        "phi_keys": _phi_keys(game), "phi_frontier": _phi_frontier(game),
        "phi_paths": _phi_paths(_ante_paths(game)),
        "inv_value": inventory_value(st, game.registry),
        "antechamber_reached": st.antechamber_reached,
        "north_door_credited": _north_door_credited(game),
        "room46_reached": st.room46_reached,
        # Repetition brake; shaped/phased charge the per-step delta.
        "repeat_penalty": st.repeat_penalty,
        # Which cells hold a room, so shaped() can find the ones placed
        # by THIS decision without the engine having to report them.
        "filled": tuple(idx >= 0 for idx in st.grid),
    }


def sparse(game: Game, prev: dict, terminated: bool) -> float:
    """Milestone signal: +0.25 Antechamber, +0.5 north door credited, +1.0 Room 46 (win)."""
    return _milestones(game, prev)


def shaped(game: Game, prev: dict, terminated: bool) -> float:
    """Dense shaping around the sparse win signal.

    0.1 per new deepest rank reached, 0.01 per unit of resource value gained
    (gems/keys/coins/dice at the datamined item values, held special items at
    their tier values — so buying an item trades coin value for item value
    instead of reading as a pure loss), plus 1.0 on a winning termination.

    Time pressure is -0.001 per game-step the decision actually consumed
    (``prev["steps"] - game.state.steps``), floored at one decision's worth
    (``max(1, steps_spent)``) so a zero-step decision (opening a doorway,
    choosing an option, ...) pays -0.001 flat, and a multi-step decision (a
    grid walk or an area-graph travel hop covering several rooms at once)
    pays proportionally more. Steps GAINED during a decision (food, the
    Orchard bonus, other step-granting effects) are clamped to zero spent
    rather than turned into a reward bonus on this term.

    Path-preservation potential (phi_paths delta): the draft that closes the
    last viable route to the Antechamber eats ~-1.0, dwarfing any dead-end
    room's resource payout.  Dropping from 2 to 1 open path costs -0.15.
    Reopening routes pays the potential back.  On a winning step the
    Antechamber was already reachable (potential 0), so the +1.0 win bonus is
    undiluted.  A dead_end termination lands with the sealing -1.0 already
    charged on the prior draft.

    Placement frontier (:func:`_placement_frontier`): +0.01 per way forward a
    newly placed room opens into an empty cell, so a placement that keeps the
    house branching is paid at the moment it is made -- the same step the
    phi_paths risk is charged on. Every other positive term here lands one
    decision later, on entry, which left choosing a room a near-zero-mean
    action with a fat negative tail; see that function for the measurement.
    `phased` does NOT share it: it prices forward pathways through
    :func:`_phi_frontier` instead.

    The three milestones come from :func:`_milestones`, shared with `sparse`
    and `phased`.
    """
    values = game.registry.tuning["item_values"]
    r = 0.1 * (game.deepest_rank - prev["deepest_rank"])
    d_res = (
        (game.state.gems - prev["gems"]) * values["gem"]
        + (game.state.keys - prev["keys"]) * values["key"]
        + (game.state.coins - prev["coins"]) * values["coin"]
        + (game.state.dice - prev["dice"]) * values["die"]
        + (inventory_value(game.state, game.registry) - prev["inv_value"])
    )
    r += 0.01 * d_res
    r += _phi_paths(_ante_paths(game)) - prev["phi_paths"]
    r += _placement_frontier(game, prev)
    # Time pressure priced against the resource that actually ends runs (steps),
    # not decision count: clamp step GAINS to 0 first (food etc. must not turn
    # this term into a bonus), then floor at 1 so zero-step decisions pay
    # -0.001 flat and multi-step decisions pay proportionally more.
    steps_spent = max(0, prev["steps"] - game.state.steps)
    r -= 0.001 * max(1, steps_spent)
    r += _milestones(game, prev)
    r -= game.state.repeat_penalty - prev["repeat_penalty"]
    return r


def phased(game: Game, prev: dict, terminated: bool) -> float:
    """Two-phase shaping: gather resources low, spend keys and keep pathways
    open high.

    Differences from :func:`shaped`:

    - Rank progress is back-loaded (0.05/rank through rank 4, 0.15/rank for
      5-9) so racing upward is not the dominant early signal.
    - Keys are priced as a potential that appreciates with deepest rank
      (:func:`_phi_keys`): carrying keys into lock territory pays off per
      rank, spending them early forgoes the appreciation, and spending them
      late must be justified by the larger rank reward.
    - Passable frontier doorways at the leading edge carry a standing
      potential (:func:`_phi_frontier`), rewarding runs that keep several
      live ways forward instead of tunneling a single corridor.
    - Path-preservation potential (phi_paths delta): the draft that closes the
      last viable route to the Antechamber eats ~-1.0, dwarfing any dead-end
      room's resource payout.  Dropping from 2 to 1 open path costs -0.15.
      Reopening routes pays the potential back.  On a winning step the
      Antechamber was already reachable (potential 0), so the +1.0 win bonus
      is undiluted.  A dead_end termination lands with the sealing -1.0
      already charged on the prior draft.

    Gems/coins/dice/held-item deltas, time pressure, and the three milestones
    (:func:`_milestones`) match `shaped`.
    """
    values = game.registry.tuning["item_values"]
    r = _rank_potential(game.deepest_rank) - _rank_potential(prev["deepest_rank"])
    d_res = (
        (game.state.gems - prev["gems"]) * values["gem"]
        + (game.state.coins - prev["coins"]) * values["coin"]
        + (game.state.dice - prev["dice"]) * values["die"]
        + (inventory_value(game.state, game.registry) - prev["inv_value"])
    )
    r += 0.01 * d_res
    r += _phi_keys(game) - prev["phi_keys"]
    r += _phi_frontier(game) - prev["phi_frontier"]
    r += _phi_paths(_ante_paths(game)) - prev["phi_paths"]
    # Step-scaled time pressure, identical to `shaped` -- see its comment for
    # the clamp and the floor. Kept in lockstep deliberately: this docstring
    # promises the two match, and a silent divergence between reward modes is
    # the kind of thing that surfaces months later as an unreproducible run.
    steps_spent = max(0, prev["steps"] - game.state.steps)
    r -= 0.001 * max(1, steps_spent)
    r += _milestones(game, prev)
    r -= game.state.repeat_penalty - prev["repeat_penalty"]
    return r


REWARDS = {"sparse": sparse, "shaped": shaped, "phased": phased}
