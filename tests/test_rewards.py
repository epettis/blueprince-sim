"""The phased reward: keys appreciate with depth, frontier breadth pays.

Covers the observable shaping behaviors of the ``phased`` reward function:
holding keys is worth more the deeper the run has pushed, spending a key
late costs more than spending it early, only passable frontier doorways
carry potential (a key in hand makes a locked doorway count again), rank
progress is back-loaded past rank 4, and the mode is selectable through
the env config.

Also covers the path-preservation potential (_phi_paths / _ante_paths):
sealing the last viable route to the Antechamber costs ~-1.0, dropping
from two routes to one costs -0.15, reopening routes pays back the
potential, when the Antechamber is already reachable on foot the
potential is 0 so the win bonus is undiluted, and the potential is forced
to 0.0 on a `terminated` step so a dead-ended day's phi_paths contribution
telescopes to 0 rather than ending on the sealing penalty.
"""

from __future__ import annotations

import numpy as np
import pytest

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import E, N, S, W, neighbor
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, segment_key
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env import rewards as R
from blueprince_sim.env.rewards import (
    PATHS_ONE_PENALTY,
    _ante_paths,
    _phi_paths,
    phased,
    shaped,
    snapshot,
)


def _game(registry, **cfg) -> Game:
    return Game(GameConfig(**cfg), seed=1, registry=registry)


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    """Overwrite a doorway segment's state, bumping door_version so caches
    (distance maps, action masks) notice the change."""
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


def test_keys_appreciate_with_depth(registry):
    """The same deepest-rank advance pays strictly more phased reward when
    keys are held: carrying keys into lock territory is itself rewarded."""
    g = _game(registry)

    g.state.keys = 2
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 6
    with_keys = phased(g, prev, False)

    g.state.keys = 0
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 6
    without_keys = phased(g, prev, False)

    assert with_keys > without_keys


def test_no_appreciation_below_lock_territory(registry):
    """Advancing within ranks 1-3, where locks never roll by chance, pays the
    same whether or not keys are held: appreciation starts at rank 4."""
    g = _game(registry)

    g.state.keys = 2
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 3
    with_keys = phased(g, prev, False)

    g.state.keys = 0
    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 3
    without_keys = phased(g, prev, False)

    assert with_keys == pytest.approx(without_keys)


def test_spending_a_key_costs_more_late(registry):
    """Losing a key at deepest rank 8 is penalized more than at rank 2, so an
    early spend must clear a lower bar than a late one."""
    g = _game(registry)

    g.deepest_rank = 2
    g.state.keys = 2
    prev = snapshot(g)
    g.state.keys = 1
    early = phased(g, prev, False)

    g.deepest_rank = 8
    g.state.keys = 2
    prev = snapshot(g)
    g.state.keys = 1
    late = phased(g, prev, False)

    assert late < early < 0


def test_frontier_potential_counts_only_passable_doorways(registry):
    """A locked frontier doorway with no key in hand drops out of the frontier
    potential; holding a key makes it count again (a banked key literally buys
    back a pathway)."""
    g = _game(registry)
    g.state.keys = 0
    doorways = g.frontier_doorways()
    assert doorways, "fresh game should have frontier doorways off the Entrance Hall"
    assert all(g.doorway_passable(c, d) for c, d in doorways)
    open_phi = snapshot(g)["phi_frontier"]
    assert open_phi > 0

    cell, d = doorways[0]
    _force_state(g, cell, d, DOOR_LOCKED)
    assert snapshot(g)["phi_frontier"] < open_phi

    g.state.keys = 1
    assert snapshot(g)["phi_frontier"] == pytest.approx(open_phi)


def test_rank_progress_backloaded(registry):
    """One rank of progress deep in the house (4 -> 5) out-pays one rank early
    (1 -> 2), leaving the resource terms dominant during the gathering phase."""
    g = _game(registry)
    g.state.keys = 0

    g.deepest_rank = 1
    prev = snapshot(g)
    g.deepest_rank = 2
    early = phased(g, prev, False)

    g.deepest_rank = 4
    prev = snapshot(g)
    g.deepest_rank = 5
    late = phased(g, prev, False)

    assert late > early > 0


def test_phased_selectable_via_env():
    """The phased reward mode is selectable via config and yields plain float
    rewards from step()."""
    env = make_env(GameConfig(reward="phased"))
    env.reset(seed=3)
    mask = env.action_masks()
    action = int(np.flatnonzero(mask)[0])
    _, reward, *_ = env.step(action)
    assert isinstance(reward, float)


# ------------------------------------------------- special-item valuation

def test_inventory_value_uses_tier_values(registry):
    """A held item is worth its Trading Post tier's value; untradeable items
    use the flat value; counts multiply.

    Items must carry shaping worth or every purchase reads as a coin loss.
    royal_scepter_found=False is explicit because the default is now True (the unlock
    puzzle is unmodeled; False keeps the starting inventory empty for this test).
    """
    from blueprince_sim.engine.special_items import inventory_value
    g = _game(registry, royal_scepter_found=False)
    values = registry.tuning["special_item_values"]
    assert inventory_value(g.state, registry) == 0.0
    g.state.inventory["magnifying_glass"] = 1  # tier 1
    g.state.inventory["master_key"] = 1        # tier 5
    g.state.inventory["royal_scepter"] = 1     # untradeable (tier null)
    g.state.inventory["microchip"] = 2         # tier 2, stacks
    expected = (values["by_tier"]["1"] + values["by_tier"]["5"]
                + values["untradeable"] + 2 * values["by_tier"]["2"])
    assert inventory_value(g.state, registry) == expected


def test_buying_an_item_is_roughly_reward_neutral(registry):
    """Under both shaped and phased, a fair-priced purchase trades coin value
    for item value instead of reading as a pure loss.

    Before this valuation, every buy cost 0.01*price reward and made shopping
    look strictly bad to the policy.
    """
    from blueprince_sim.engine import shops
    from blueprince_sim.env.rewards import shaped
    g = _game(registry)
    room = registry.by_id["commissary"]
    st = g.state
    cell = 7
    st.grid[cell] = room.idx
    st.placed_doors[cell] = room.door_mask
    st.entered[cell] = True
    st.pos = cell
    st.coins = 50
    shops.on_enter_shop(g, room)
    stock = shops.stock_for(g)
    idx, entry = next((i, d) for i, d in enumerate(stock) if d["kind"] == "item")
    for fn in (shaped, phased):
        prev = snapshot(g)
        g_coins = st.coins
        shops.buy(g, idx)
        r = fn(g, prev, terminated=False)
        # Coin spend really happened, but the reward is near the time-pressure
        # floor.
        assert st.coins < g_coins
        assert r > -0.001 - 0.01 * entry["price"] / 2
        st.inventory.clear()  # reset for the second reward fn
        st.coins = 50
        g.state.shops.stock.clear()
        shops.on_enter_shop(g, room)


def test_losing_an_item_costs_reward(registry):
    """An item vanishing from the inventory (Lost & Found steal, consumption)
    shows up as a negative shaped delta.

    The same valuation that credits acquisition must charge for loss, so the
    Lost & Found's steal is a real pathing cost to the policy.
    """
    from blueprince_sim.engine.special_items import grant, remove
    from blueprince_sim.env.rewards import shaped
    g = _game(registry)
    grant(g.state, registry, "shovel", source="test")
    prev = snapshot(g)
    remove(g.state, "shovel", consumed=True)
    assert shaped(g, prev, terminated=False) < -0.001  # worse than time pressure alone


# ------------------------------------------------- path-preservation potential

def _sealed_game(registry):
    """Helper: fresh game with Entrance Hall cleared (grid[2] reset) so tests
    can place custom rooms without inheriting the default door locks and
    layout of the pre-placed Entrance Hall.

    Uses the DEFAULT config, lever gate included: optimistic_distances ignores
    door state, so the Antechamber's sealed doors cannot hide cell 37 from the
    shaped reward's potential.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    st = g.state
    st.grid[2] = -1
    st.placed_doors[2] = 0
    st.door_version += 1
    return g


def _place(g: Game, cell: int, mask: int, *, pos: bool = False) -> None:
    """Place a minimal room at ``cell`` with ``mask`` doors, optionally setting
    player position there.  Uses the Entrance Hall room record (idx=1) as a
    stand-in; only the placed_doors mask is significant for frontier/BFS logic.
    """
    room = g.registry.by_id["entrance_hall"]
    st = g.state
    st.grid[cell] = room.idx
    st.placed_doors[cell] = mask
    st.entered[cell] = True
    if pos:
        st.pos = cell
    st.door_version += 1


def test_sealing_last_route_shaped_is_very_negative(registry):
    """Drafting the room that closes the final Antechamber route eats ~-1.0 in
    shaped reward, dwarfing any resource payout a dead-end room could offer.

    Before: one frontier doorway (cell 32, N) → cell 37, which has an
    optimistic path to the Antechamber (optdist=1).  After: a room placed at
    cell 37 with S-only mask occupies that slot; no remaining frontier
    doorways have valid optimistic targets → _ante_paths drops 1→0.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)          # rank 7 col 2, one N-door frontier

    assert _ante_paths(g) == 1
    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(PATHS_ONE_PENALTY)

    _place(g, 37, S)                    # seal: connects to 32, no N door → can't reach ante

    assert _ante_paths(g) == 0
    r = shaped(g, prev, terminated=False)
    assert r < -0.5                     # delta ~-0.85 plus time pressure ~-0.001


def test_sealing_last_route_phased_is_very_negative(registry):
    """Same sealing scenario as above but using the phased reward function,
    which carries additional phi_keys and phi_frontier potentials.

    The path-preservation delta still dominates: reward is well below -0.5.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)

    assert _ante_paths(g) == 1
    prev = snapshot(g)

    _place(g, 37, S)

    assert _ante_paths(g) == 0
    r = phased(g, prev, terminated=False)
    assert r < -0.5


def test_two_to_one_path_costs_less_than_one_to_zero(registry):
    """Dropping from 2 open paths to 1 costs PATHS_ONE_PENALTY (-0.15), which
    is strictly better (less negative) than the 1→0 drop (-0.85 delta).

    The two-paths doctrine treats 1-path-remaining as a danger zone but not
    yet a fatal outcome; the policy must see a real cost difference.
    """
    g = _sealed_game(registry)
    # Two frontier doorways: N→cell 37 and E→cell 33, both with optdist != -1
    _place(g, 32, N | E, pos=True)

    assert _ante_paths(g) == 2
    prev_two = snapshot(g)
    assert prev_two["phi_paths"] == pytest.approx(0.0)

    # Seal the east route: place room at cell 33 with W-only (connects but has no N/S frontier)
    _place(g, 33, W)

    assert _ante_paths(g) == 1
    cost_two_to_one = shaped(g, prev_two, terminated=False)

    # Reset to 1→0 scenario for comparison
    g2 = _sealed_game(registry)
    _place(g2, 32, N, pos=True)
    prev_one = snapshot(g2)
    _place(g2, 37, S)
    assert _ante_paths(g2) == 0
    cost_one_to_zero = shaped(g2, prev_one, terminated=False)

    assert cost_two_to_one < 0          # losing a path always costs something
    assert cost_two_to_one > cost_one_to_zero   # but far less than sealing the last


def test_two_or_more_paths_no_penalty(registry):
    """When two or more open routes exist throughout a step, the phi_paths
    delta is exactly 0.0 and only the time-pressure term affects the reward.
    """
    g = _sealed_game(registry)
    _place(g, 32, N | E, pos=True)     # two frontier doorways → n_paths=2, phi=0.0

    assert _ante_paths(g) == 2
    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(0.0)

    # No state change: same potential before and after → delta = 0.0
    r = shaped(g, prev, terminated=False)
    assert r == pytest.approx(-0.001)   # only time pressure


def test_reopening_path_gives_positive_delta(registry):
    """Going from 1 surviving path back to 2 yields a positive reward delta
    of roughly PATHS_ONE_PENALTY magnitude, as the potential is reclaimed.

    Adding an east door to a room that previously had only a north door
    models a scenario where a new branch route is opened.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)         # 1 frontier doorway → n_paths=1, phi=-0.15

    assert _ante_paths(g) == 1
    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(PATHS_ONE_PENALTY)

    # Reopen: add east door, creating a second frontier (32, E) → cell 33, optdist=3
    g.state.placed_doors[32] = N | E
    g.state.door_version += 1

    assert _ante_paths(g) == 2
    r = shaped(g, prev, terminated=False)
    # Delta is 0.0 - (-0.15) = +0.15, minus time pressure 0.001 ≈ +0.149
    assert r > 0.0                      # positive: reclaiming potential is rewarded


def test_time_term_scales_with_steps_not_flat_per_decision(registry):
    """A decision that consumes several game-steps costs strictly more shaped
    reward than a single-step decision, and a zero-step decision still pays
    the flat -0.001 floor.

    The time term is priced against game-steps (the resource that actually
    ends 68% of runs via out_of_steps) rather than decision count, so a
    multi-step travel hop costs more than a single-cell move.
    """
    g = _sealed_game(registry)
    _place(g, 32, N | E, pos=True)  # two open paths -> phi_paths delta 0.0 throughout

    g.state.steps = 50
    prev_zero = snapshot(g)
    zero_step = shaped(g, prev_zero, terminated=False)  # no steps consumed at all
    assert zero_step == pytest.approx(-0.001)

    g.state.steps = 50
    prev_one = snapshot(g)
    g.state.steps = 49  # single-step move
    one_step = shaped(g, prev_one, terminated=False)
    assert one_step == pytest.approx(-0.001)  # floor: same as the zero-step charge

    g.state.steps = 50
    prev_multi = snapshot(g)
    g.state.steps = 44  # 6-step travel hop, same as travel_to's area_hop + walk cost
    multi_step = shaped(g, prev_multi, terminated=False)
    assert multi_step == pytest.approx(-0.006)
    assert multi_step < one_step < 0  # the travel hop strictly outprices the single move


def test_time_term_clamped_when_steps_gained(registry):
    """Steps GAINED during a decision (food, the Orchard bonus, other
    step-granting effects) must not turn the time-pressure term into a
    reward bonus.

    A naive ``prev["steps"] - game.state.steps`` delta goes negative when a
    decision nets a step gain; without clamping, that would make step-granting
    actions look strictly better than a free decision, the opposite of the
    intended time pressure and a new exploit in a change meant to close one.
    """
    g = _sealed_game(registry)
    _place(g, 32, N | E, pos=True)  # two open paths -> phi_paths delta 0.0 throughout

    g.state.steps = 50
    prev = snapshot(g)
    g.state.steps = 70  # net +20 steps this decision (e.g. a food pickup on entry)
    r = shaped(g, prev, terminated=False)
    assert r == pytest.approx(-0.001)  # floored at the flat per-decision charge, not a bonus


def test_antechamber_reachable_returns_open_goal_constant(registry):
    """When the Antechamber is already reachable on foot, _ante_paths returns 99
    and the potential is 0.0, leaving the +1.0 win bonus undiluted.

    This scenario has room 37 (rank 8, col 2) directly connected to the
    Antechamber via forced-open door segments.
    """
    g = _sealed_game(registry)
    _place(g, 37, N | S, pos=True)     # rank 8 col 2: N door into Antechamber, S door back

    # Antechamber doors are locked by default; force them open
    _force_state(g, 37, N, DOOR_OPEN)
    _force_state(g, ANTECHAMBER_CELL, S, DOOR_OPEN)

    dm = g.distance_map()
    assert dm[ANTECHAMBER_CELL] > 0     # Antechamber is reachable on foot

    n = _ante_paths(g)
    assert n == 99
    assert _phi_paths(n) == pytest.approx(0.0)


def test_ante_paths_pocket_doorway_does_not_count(registry):
    """A frontier doorway whose target cell has optimistic_dist == -1 (cut off
    from the Antechamber even under optimistic assumptions) does not count
    toward _ante_paths.

    Setup: full rank-2 barrier (cells 5-9 with E|W-only mask) severs the
    optimistic BFS path from the Antechamber to all rank-1 cells.  The player
    room at cell 2 has E and W doors pointing into empty rank-1 cells (3 and 1),
    both of which have optimistic_dist == -1.  Hence _ante_paths returns 0.
    """
    g = _sealed_game(registry)
    # Rank-2 barrier: E|W mask blocks all N-S optimistic BFS passage at rank 2
    for cell in [5, 6, 7, 8, 9]:
        _place(g, cell, E | W)
    # Player room at rank 1 with east and west frontiers into isolated rank-1 cells
    _place(g, 2, E | W, pos=True)

    od = g.optimistic_distances()
    frontier = g.frontier_doorways()
    # All frontier targets are in rank 1 and are cut off from the Antechamber
    assert all(od[neighbor(cell, d)] == -1 for cell, d in frontier)
    assert len(frontier) == 2           # two frontiers exist but neither counts
    assert _ante_paths(g) == 0


def test_ante_paths_open_doorway_counts(registry):
    """A frontier doorway whose target cell has optimistic_dist != -1 is counted
    by _ante_paths, confirming that live routes are correctly recognised.

    Room at rank 7 col 2 (cell 32) with a single N door points into cell 37
    (rank 8 col 2), which the optimistic BFS can reach from the Antechamber
    in one step.  _ante_paths therefore returns 1.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)         # one frontier: (32, N) → cell 37

    od = g.optimistic_distances()
    target = neighbor(32, N)            # cell 37
    assert od[target] != -1             # optimistically reachable from Antechamber
    assert _ante_paths(g) == 1


# ------------------------------------------------- terminal-zero phi_paths


def test_dead_ended_episode_nets_zero_phi_paths_contribution(registry):
    """Over a scripted episode that ends dead-ended, the phi_paths component
    summed across every step is 0.0.

    Potential-based shaping is policy-invariant only when the potential is
    zero at terminal states; forcing it to 0.0 on the `terminated` step makes
    the episode sum telescope to phi(end) - phi(start) = 0 - 0, rather than
    ending on the sealing -1.0 as an uncancelled bias against drafting.
    """
    g = _sealed_game(registry)
    _place(g, 32, N | E, pos=True)   # two open routes: N->37, E->33; phi=0.0

    prev1 = snapshot(g)
    assert prev1["phi_paths"] == pytest.approx(0.0)
    g.state.placed_doors[32] = N     # drop the east route: 2 paths -> 1
    g.state.door_version += 1
    r1 = shaped(g, prev1, terminated=False)

    prev2 = snapshot(g)
    assert prev2["phi_paths"] == pytest.approx(PATHS_ONE_PENALTY)
    g.state.placed_doors[32] = 0     # drop the last route: 1 path -> 0 (sealed)
    g.state.door_version += 1
    r2 = shaped(g, prev2, terminated=False)

    prev3 = snapshot(g)
    assert prev3["phi_paths"] == pytest.approx(-1.0)
    r3 = shaped(g, prev3, terminated=True)   # the step the dead-ended day ends on

    # No cell is ever newly filled (only placed_doors on an already-placed
    # cell changes), so placement_frontier is 0.0 throughout; no steps,
    # resources, rank or milestones change either, so the only per-step
    # constant is the -0.001 time-pressure floor on each of the 3 decisions.
    total = r1 + r2 + r3
    phi_component_total = total - (-0.001 * 3)
    assert phi_component_total == pytest.approx(0.0, abs=1e-9)


def test_a_non_terminal_seal_still_charges_the_full_delta(registry):
    """A mid-episode draft that seals the last route still charges the full
    sealing delta; only a step where `terminated=True` zeroes the potential.

    The fix must key off the `terminated` flag, not off the potential's
    value, or it would silently swallow the per-step warning phi_paths gives
    during ordinary play (the property `test_sealing_last_route_shaped_is_
    very_negative` already pins for the non-terminal case).
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)       # one open route -> 37; phi=-0.15
    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(PATHS_ONE_PENALTY)

    _place(g, 37, S)                 # seals the last route: zero paths remain
    assert _ante_paths(g) == 0

    mid_episode = shaped(g, prev, terminated=False)
    terminal = shaped(g, prev, terminated=True)

    assert mid_episode == pytest.approx(-0.851)  # full ~-0.85 delta, not zeroed
    assert terminal == pytest.approx(0.149)      # potential forced to 0 instead


def test_a_healthy_terminal_step_is_unaffected(registry):
    """A day that ends with two or more routes still open pays the same
    reward whether or not the step is flagged `terminated`.

    The potential was already 0.0 before the terminal override in this case,
    so the fix has nothing to zero and must not perturb a healthy ending.
    """
    g = _sealed_game(registry)
    _place(g, 32, N | E, pos=True)   # two open routes: N->37, E->33; phi=0.0
    prev = snapshot(g)
    assert prev["phi_paths"] == pytest.approx(0.0)

    non_terminal = shaped(g, prev, terminated=False)
    terminal = shaped(g, prev, terminated=True)
    assert terminal == pytest.approx(non_terminal)


def test_phased_shares_the_terminal_zero_fix(registry):
    """`phased` charges the identical `_phi_paths` telescoping construct as
    `shaped`, so the same terminal-zero delta applies to it: flagging the
    sealing step `terminated` recovers exactly the 1.0 that a non-terminal
    call to the same state would have left charged.
    """
    g = _sealed_game(registry)
    _place(g, 32, N, pos=True)
    prev = snapshot(g)
    _place(g, 37, S)                 # seals the last route
    assert _ante_paths(g) == 0

    mid_episode = phased(g, prev, terminated=False)
    terminal = phased(g, prev, terminated=True)
    assert terminal - mid_episode == pytest.approx(1.0)


def test_phased_also_zeroes_keys_and_frontier_potentials_at_terminal(registry):
    """`phased` carries two more potentials besides phi_paths -- phi_keys and
    phi_frontier -- and forces both to 0.0 on a `terminated` step for the
    same reason: a dead-ended day must not leave a held key stock or a
    standing frontier as an uncancelled residue in the reward sum.

    Nothing about the game state changes between the two calls here, so a
    non-terminal call's delta for each potential is 0 (current value equals
    `prev`) while a terminal call's delta is `0 - prev[potential]` -- the gap
    between the two calls is exactly the sum of all three starting
    potentials.
    """
    g = _sealed_game(registry)
    g.deepest_rank = 8
    g.state.keys = 3
    _place(g, 32, N | E | S, pos=True)  # rank 7 == deepest_rank - 1: on the frontier edge

    prev = snapshot(g)
    assert prev["phi_keys"] == pytest.approx(0.315)   # 0.01 * 3 keys * 3.0 key value * 3.5x
    assert prev["phi_frontier"] == pytest.approx(0.06)  # 0.02 * 3 passable frontier doors
    assert prev["phi_paths"] == pytest.approx(0.0)      # 3 optimistic routes: healthy

    mid_episode = phased(g, prev, terminated=False)
    terminal = phased(g, prev, terminated=True)

    assert mid_episode - terminal == pytest.approx(
        prev["phi_keys"] + prev["phi_frontier"] + prev["phi_paths"]
    )


# ------------------------------------------- the placement-frontier bonus


def _plant(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Put a room on the grid directly, bypassing the draft."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.door_version += 1


def test_open_ways_counts_only_doors_into_empty_cells(registry):
    """A placed room's score is the ways forward it opens, not its door count.

    Doors facing an occupied cell or the outer wall lead nowhere new, so they
    must not count -- otherwise a room wedged into a filled corner would score
    the same as one opening the board up.
    """
    g = _game(registry)
    # Cell 22 is rank 5, column 2: interior, so all four neighbours are on-grid.
    _plant(g, "corridor", 22, N | E | S | W)
    assert R._open_ways(g, 22) == 4, "all four neighbours empty -> four ways"

    _plant(g, "corridor", neighbor(22, N), N | S)   # block one side
    assert R._open_ways(g, 22) == 3, "a door into an occupied cell is not a way forward"


def test_open_ways_ignores_doors_into_the_outer_wall(registry):
    """Doors pointing off the grid are not ways forward.

    A wing room's outward door cannot be drafted through, so counting it would
    pay for a frontier that does not exist.
    """
    g = _game(registry)
    _plant(g, "corridor", 20, N | E | S | W)   # rank 5, column 0: west door faces the wall
    assert R._open_ways(g, 20) == 3


def test_a_dead_end_placement_scores_nothing(registry):
    """A room whose only door is the one it was entered by opens nothing.

    The bonus exists to separate placements that keep the house branching from
    placements that close it; a Dead End is the case it must not pay for.
    """
    g = _game(registry)
    _plant(g, "corridor", 21, N | S)
    _plant(g, "corridor", 22, W)               # its single door faces the placed cell 21
    assert R._open_ways(g, 22) == 0


def test_the_bonus_is_paid_for_cells_placed_since_the_snapshot(registry):
    """Only rooms placed by THIS decision pay; standing still pays nothing.

    Without the snapshot diff the term would re-pay the whole board on every
    step, which is the farm the bonus must not become.
    """
    g = _game(registry)
    prev = R.snapshot(g)
    assert R._placement_frontier(g, prev) == 0.0, "no placement, no bonus"

    _plant(g, "corridor", 22, N | E | S | W)
    paid = R._placement_frontier(g, prev)
    assert paid == pytest.approx(4 * R.FRONTIER_PLACEMENT_BONUS)

    # A fresh snapshot now includes that cell, so it cannot be paid for twice.
    assert R._placement_frontier(g, R.snapshot(g)) == 0.0


def test_shaped_pays_the_placement_bonus_and_phased_does_not(registry):
    """The bonus belongs to `shaped` alone.

    `phased` prices forward pathways through its own _phi_frontier potential;
    paying both would count the same idea twice, and the two modes are supposed
    to be distinguishable shaping strategies rather than one plus an extra.
    """
    g = _game(registry)
    prev = R.snapshot(g)
    _plant(g, "corridor", 22, N | E | S | W)

    shaped_r = shaped(g, prev, terminated=False)
    phased_r = phased(g, prev, terminated=False)
    assert shaped_r - phased_r == pytest.approx(
        4 * R.FRONTIER_PLACEMENT_BONUS - (R._phi_frontier(g) - prev["phi_frontier"]),
        abs=1e-9,
    ), "shaped must carry the placement bonus and phased must carry _phi_frontier"


# ------------------------------------------------ the repetition brake


def _plant_entered(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Put an already-entered room on the grid, bypassing the draft."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = True
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def test_the_first_three_uses_of_a_pair_are_free_then_it_escalates():
    """The curve is flat for REPEAT_FREE_USES, then rises a step at a time.

    Flat at the start so the rare legitimate fourth use of a switch is nearly
    free; rising after so a loop gets more expensive the longer it runs; capped
    so no single step can return an unbounded value the critic must fit.
    """
    free = R.REPEAT_FREE_USES
    assert [R.repetition_penalty(k) for k in range(1, free + 1)] == [0.0] * free
    assert R.repetition_penalty(free + 1) == pytest.approx(R.REPEAT_PENALTY_STEP)
    assert R.repetition_penalty(free + 2) == pytest.approx(2 * R.REPEAT_PENALTY_STEP)
    ceiling = R.REPEAT_PENALTY_STEP * R.REPEAT_PENALTY_CAP
    assert R.repetition_penalty(free + R.REPEAT_PENALTY_CAP) == pytest.approx(ceiling)
    assert R.repetition_penalty(free + R.REPEAT_PENALTY_CAP + 50) == pytest.approx(ceiling)


def test_a_repeated_zero_step_switch_gets_progressively_dearer(registry):
    """Flipping one switch in one room escalates in cost after the free uses.

    The Darkroom breaker spends no game step, so nothing but this brake bounds
    it; a recorded episode flipped it 622 times out of 687 actions.
    """
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7
    assert A.action_mask(g)[A.TOGGLE_DARKROOM_ACTION], "setup: the toggle must be legal"

    rewards = []
    for _ in range(R.REPEAT_FREE_USES + 3):
        prev = R.snapshot(g)
        A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)
        rewards.append(shaped(g, prev, terminated=False))

    free = rewards[:R.REPEAT_FREE_USES]
    assert max(free) - min(free) < 1e-9, "the free uses must all cost the same"
    after = rewards[R.REPEAT_FREE_USES:]
    assert all(b < a for a, b in zip(after, after[1:])), (
        f"each further use must cost more than the last, got {after}"
    )
    assert g.state.steps == 50, "setup check: the toggle really does spend no step"


def test_a_step_spending_action_is_never_charged_for_repetition(registry):
    """Only zero-step actions are tallied; walking is left to the step budget.

    Measured over 60 fresh-save days of drafting play, every (location, action)
    pair used more than three times was a move. Charging those would tax normal
    play for something that already pays for itself in steps.
    """
    g = Game(GameConfig(day=1, special_items=True), seed=1, registry=registry)
    g.reset()
    _plant_entered(g, "corridor", 7, N | S)
    g.state.entered[7] = False          # so moving in is legal and costs a step

    before_steps = g.state.steps
    A.apply_action(g, A.MOVE_TO_BASE + 7)
    assert g.state.steps < before_steps, "setup: the move must spend a step"
    assert g.state.repeat_counts == {}, "a step-spending action must not be tallied"
    assert g.state.repeat_penalty == 0.0


def test_the_tally_is_keyed_by_where_the_player_stands(registry):
    """The key is (location, action), so the same id in two places is two habits.

    Keyed by action alone, a switch flipped once in each of four rooms would
    read as a loop and a player working around the house would be charged for
    it. Location is the grid cell on-grid and the area node id off it, so an
    off-grid habit is tallied separately from anything on the board.
    """
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7
    assert A._repetition_location(g) == 7, "on-grid, the location is the cell"

    for _ in range(R.REPEAT_FREE_USES):
        A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)
    assert g.state.repeat_counts == {(7, A.TOGGLE_DARKROOM_ACTION): R.REPEAT_FREE_USES}

    g.state.area = "apple_orchard"
    assert A._repetition_location(g) == "apple_orchard", (
        "off-grid, the location is the area node, never the stale grid cell"
    )


# ------------------------------------------- the day must always be able to end


def test_a_zero_step_switch_ends_the_day_once_the_budget_is_gone(registry):
    """At 0 steps a zero-step action must end the day, not be repeatable forever.

    Termination fires on "nothing purposeful remains", and a zero-step action
    stays legal at 0 steps -- so before Game.settle_day a player who spent their
    last step at the Utility Closet could flip the Darkroom breaker until the env
    hit max_env_steps. One recorded episode did exactly that, 622 times out of
    687 actions, with no other legal action available.
    """
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7
    g.state.steps = 0
    assert A.action_mask(g)[A.TOGGLE_DARKROOM_ACTION], (
        "setup: the zero-step toggle must still be legal at 0 steps"
    )

    A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)
    assert g.phase is Phase.TERMINAL, "the day must end once the budget is gone"
    assert not any(A.action_mask(g)), "a terminal day offers no action"


def test_every_dispatched_action_leaves_a_day_that_can_still_end(registry):
    """Drive random legal play and assert the day never outlives its budget.

    An agreement test rather than one check per handler: the rule "an action at
    0 steps ends the day" lived in twenty handlers and was missing from the
    zero-step switches, which is the shape this repo keeps paying for. Driving
    the real mask means a newly added action is covered the day it ships.
    """
    import random
    for seed in range(12):
        env = BluePrinceEnv(GameConfig(day=1, special_items=True, door_locks=True))
        env.reset(seed=seed)
        rnd = random.Random(seed)
        for _ in range(env.max_env_steps):
            mask = A.action_mask(env.game, env._prev_action)
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            env.step(rnd.choice(legal))
            if env.game.phase is Phase.TERMINAL:
                break
            assert env.game.state.steps > 0, (
                f"seed {seed}: still playing at {env.game.state.steps} steps"
            )


def test_a_doorway_walled_off_from_the_antechamber_is_not_a_way_forward(registry):
    """A door into a region already severed from the Antechamber scores nothing.

    That is the illusion of a frontier: the room looks like it opened the house
    up, while the direction it opened is already cut off. `_ante_paths` applies
    this same optimistic-distance filter, so the placement bonus has to agree
    with it or the two terms describe different boards.
    """
    g = _game(registry)
    # Seal rank 2 across its whole width with rooms that have no north or south
    # door, severing rank 1 from everything above it.
    for cell in range(5, 10):
        _plant(g, "corridor", cell, E | W)
    od = g.optimistic_distances()
    assert od[1] == -1, f"setup: rank 1 must be severed, got optimistic distance {od[1]}"

    # A room at the rank-1 corner with one spare door east, into empty cell 1.
    _plant(g, "corridor", 0, E)
    assert g.state.grid[1] < 0, "setup: the door's target must be empty"
    assert R._open_ways(g, 0) == 0, (
        "a door into a severed region is not a way forward and must score nothing"
    )


# --------------------------------------------------------- the switch cap


def test_a_switch_stops_being_offered_after_its_use_limit(registry):
    """A control switch may be flipped SWITCH_USE_LIMIT times from one spot a day.

    Pricing this in the reward was tried and did not change behaviour: 96% of
    episodes never touched a switch while 4% flipped one hundreds of times, and
    the penalty made those episodes expensive without making them rarer. A mask
    makes the loop impossible, which is what worked for the lock menu and the
    area tour.
    """
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7

    for i in range(A.SWITCH_USE_LIMIT):
        assert A.action_mask(g)[A.TOGGLE_DARKROOM_ACTION], f"use {i} must be offered"
        A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)

    assert not A.action_mask(g)[A.TOGGLE_DARKROOM_ACTION], (
        "past the limit the switch must stop being offered"
    )
    assert any(A.action_mask(g)), "capping one switch must not strand the day"


def test_the_switch_cap_does_not_charge_the_repetition_brake(registry):
    """The mask removes a switch at exactly the use the brake would start pricing.

    Held together so a capped switch never contributes a reward penalty: the two
    constants are the same number for that reason, and a drift between them would
    reintroduce the rare large negative returns the mask exists to prevent.
    """
    assert A.SWITCH_USE_LIMIT == R.REPEAT_FREE_USES
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7
    for _ in range(A.SWITCH_USE_LIMIT):
        A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)
    assert g.state.repeat_penalty == 0.0, (
        "a switch flipped only as often as the mask allows must cost nothing"
    )


def test_the_switch_cap_is_per_location(registry):
    """The allowance is keyed by where the switch was worked, not by its id.

    A player who flips a breaker in one room has spent nothing toward the same
    id elsewhere; keyed by action alone, working around the house would read as
    a loop.
    """
    g = Game(GameConfig(day=1, door_locks=True, special_items=True), seed=1,
             registry=registry)
    g.reset()
    _plant_entered(g, "utility_closet", 7, N | S)
    _plant_entered(g, "darkroom", 12, N | S)
    g.state.pos = 7
    for _ in range(A.SWITCH_USE_LIMIT):
        A.apply_action(g, A.TOGGLE_DARKROOM_ACTION)
    assert g.state.repeat_counts[(7, A.TOGGLE_DARKROOM_ACTION)] == A.SWITCH_USE_LIMIT
    assert (12, A.TOGGLE_DARKROOM_ACTION) not in g.state.repeat_counts, (
        "another location must carry its own, untouched allowance"
    )
