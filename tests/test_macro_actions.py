"""Macro navigation: draft_from / move_to actions, distance maps, masking."""

from __future__ import annotations

import numpy as np

from blueprince_sim import GameConfig, make_env
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import N, N_CELLS, neighbor
from blueprince_sim.env import actions as A


def _fresh_game(seed: int = 0) -> Game:
    return Game(GameConfig(), seed=seed)


def _first_frontier(game: Game) -> tuple[int, int]:
    doors = game.frontier_doorways()
    assert doors
    return doors[0]


def _draft_and_place(game: Game, cell: int, direction: int) -> int:
    """Draft through (cell, direction), place the free slot; return target cell."""
    pending = game.draft_from(cell, direction)
    assert pending is not None
    game.choose(0)  # slot 0 is always the free fallback
    return pending.target_cell


# --------------------------------------------------------------- distance maps


def test_distance_map_from_entrance():
    g = _fresh_game()
    dist = g.distance_map()
    assert dist[g.state.pos] == 0
    # Nothing else is placed/connected yet except the sealed Antechamber.
    assert all(d == -1 for i, d in enumerate(dist) if i != g.state.pos)


def test_distance_map_counts_hops():
    g = _fresh_game(seed=3)
    cell, d = _first_frontier(g)
    target = _draft_and_place(g, cell, d)
    dist = g.distance_map()
    assert dist[target] == 1  # adjacent to the entrance through the new door


def test_optimistic_distances_open_house():
    g = _fresh_game()
    opt = g.optimistic_distances()
    assert opt[ANTECHAMBER_CELL] == 0
    # Entrance (rank 1 center) to Antechamber (rank 9 center): 8 ranks north,
    # all empty in between, and the entrance has a north door.
    assert opt[g.state.pos] == 8


def test_optimistic_distances_respect_placed_walls():
    g = _fresh_game()
    st = g.state
    # A doorless (hypothetically sealed) room north of the entrance would
    # force the optimistic path around it.
    nb = neighbor(st.pos, N)
    st.grid[nb] = 0
    st.placed_doors[nb] = 0  # no doors at all: a plug
    opt = g.optimistic_distances()
    assert opt[nb] == -1  # unreachable itself
    assert opt[st.pos] == 10  # detour around the plug: 2 extra steps


# --------------------------------------------------------------- draft_from


def test_draft_from_current_room_matches_open_door():
    a, b = _fresh_game(seed=11), _fresh_game(seed=11)
    cell, d = _first_frontier(a)
    pa = a.draft_from(cell, d)
    pb = b.open_door(cell, d)
    assert [(o.room_idx, o.orientation, o.gem_cost) for o in pa.options] == \
           [(o.room_idx, o.orientation, o.gem_cost) for o in pb.options]


def test_draft_from_walks_and_matches_manual_sequence():
    """The macro is byte-identical to walking by hand: same state, same RNG."""
    a, b = _fresh_game(seed=5), _fresh_game(seed=5)

    # Build one room north of the entrance on both games.
    cell, d = _first_frontier(a)
    target_a = _draft_and_place(a, cell, d)
    target_b = _draft_and_place(b, cell, d)
    assert target_a == target_b

    # Pick a frontier door on the new (not yet entered) room, if any;
    # otherwise the entrance still has doors and the walk is a no-op.
    far = [(c, dd) for c, dd in a.frontier_doorways() if c == target_a]
    if not far:
        return  # dealt a dead-end: nothing to macro-walk to
    fcell, fd = far[0]

    # a: macro. b: manual move + open_door.
    a.draft_from(fcell, fd)
    b.move_to(fcell)
    b.open_door(fcell, fd)

    assert a.state.pos == b.state.pos
    assert a.state.steps == b.state.steps
    assert a.state.entered == b.state.entered
    assert (a.state.gems, a.state.keys, a.state.coins) == \
           (b.state.gems, b.state.keys, b.state.coins)
    assert [(o.room_idx, o.orientation) for o in a.state.pending.options] == \
           [(o.room_idx, o.orientation) for o in b.state.pending.options]


def test_draft_from_aborts_when_walk_ends_the_day():
    g = _fresh_game(seed=5)
    cell, d = _first_frontier(g)
    target = _draft_and_place(g, cell, d)
    far = [(c, dd) for c, dd in g.frontier_doorways() if c == target]
    if not far:
        return  # dead-end room: no doorway to walk to
    g.state.steps = 1  # exactly enough to arrive, none to spare
    result = g.draft_from(*far[0])
    assert result is None
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"


# --------------------------------------------------------------- termination


def test_stranded_when_frontier_out_of_budget():
    g = _fresh_game(seed=5)
    cell, d = _first_frontier(g)
    _draft_and_place(g, cell, d)
    g.move(d)  # enter the new room: nothing unentered remains behind us
    if g.phase is Phase.TERMINAL:
        return
    # Any remaining frontier doors need at least a one-step walk plus one
    # spare; with a single step nothing purposeful fits the budget.
    g.state.steps = 1
    if any(c == g.state.pos for c, _ in g.frontier_doorways()):
        return  # current room still has a door: drafting here is in budget
    g._check_termination()
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"


# --------------------------------------------------------------- env masking


def test_mask_layout_and_retired_actions():
    env = make_env()
    env.reset(seed=0)
    mask = env.action_masks()
    assert len(mask) == A.N_ACTIONS == 241
    # Retired single-tile moves are never legal.
    for action in (189, 190, 191, 192):
        assert not mask[action]
    # From a fresh entrance: its own doorways are draftable, nothing walkable.
    assert any(mask[A.OPEN_BASE:A.CHOOSE_BASE])
    assert not any(mask[A.MOVE_TO_BASE:A.MOVE_TO_BASE + N_CELLS])


def test_mask_draft_requires_step_to_spare():
    env = make_env()
    env.reset(seed=0)
    game = env.game
    game.state.steps = 1
    mask = A.action_mask(game)
    dist = game.distance_map()
    for cell, d in game.frontier_doorways():
        legal = mask[A.OPEN_BASE + cell * 4 + A.DIR_INDEX[d]]
        assert legal == (0 <= dist[cell] <= game.state.steps - 1)


def test_mask_move_to_targets_unentered_only():
    env = make_env()
    env.reset(seed=1)
    game = env.game
    cell, d = _first_frontier(game)
    _draft_and_place(game, cell, d)
    mask = A.action_mask(game)
    dist = game.distance_map()
    for c in range(N_CELLS):
        legal = mask[A.MOVE_TO_BASE + c]
        expected = 0 < dist[c] <= game.state.steps and not game.state.entered[c]
        assert legal == expected
    # And stepping the env with a legal move_to enters the room.
    targets = [c for c in range(N_CELLS) if mask[A.MOVE_TO_BASE + c]]
    assert targets
    env.step(A.MOVE_TO_BASE + targets[0])
    assert game.state.pos == targets[0]
    assert game.state.entered[targets[0]]


def test_masked_rollout_never_revisits_pointlessly():
    """No legal action sequence can walk A->B->A: re-entry is unreachable."""
    env = make_env()
    rng = np.random.default_rng(7)
    for episode in range(3):
        env.reset(seed=episode)
        for _ in range(200):
            mask = env.action_masks()
            legal = np.flatnonzero(mask)
            if len(legal) == 0:
                break
            # Every legal move_to target must be unentered (or the win cell).
            for a in legal:
                if A.MOVE_TO_BASE <= a < A.MOVE_TO_BASE + N_CELLS:
                    cell = a - A.MOVE_TO_BASE
                    assert not env.game.state.entered[cell]
            _, _, term, trunc, _ = env.step(int(rng.choice(legal)))
            if term or trunc:
                break


def test_draft_from_any_frontier_via_env():
    """The env can draft a doorway of a room the player is not standing in."""
    env = make_env()
    for seed in range(20):
        env.reset(seed=seed)
        game = env.game
        cell, d = _first_frontier(game)
        _draft_and_place(game, cell, d)
        mask = A.action_mask(game)
        remote = [(c, dd) for c, dd in game.frontier_doorways() if c != game.state.pos
                  and mask[A.OPEN_BASE + c * 4 + A.DIR_INDEX[dd]]]
        if not remote:
            continue
        c, dd = remote[0]
        env.step(A.OPEN_BASE + c * 4 + A.DIR_INDEX[dd])
        assert game.phase is Phase.DRAFTING
        assert game.state.pos == c  # walked there first
        return
    raise AssertionError("no seed produced a remote frontier doorway")


# --------------------------------------------------------------- observations


def test_obs_new_planes_consistent():
    env = make_env()
    obs, _ = env.reset(seed=4)
    game = env.game
    assert obs["grid_dist"].reshape(-1)[game.state.pos] == 0
    assert obs["grid_ante_dist"].reshape(-1)[ANTECHAMBER_CELL] == 0
    assert obs["grid_entered"].reshape(-1)[game.state.pos] == 1
    assert obs["progress"][0] == game.deepest_rank
    assert obs["stage"] in (0, 1, 2)
    assert obs["house_flags"].shape == (8,)
    # Frontier plane matches the engine's doorway list.
    frontier = np.zeros(45, dtype=np.uint8)
    for cell, d in game.frontier_doorways():
        frontier[cell] |= d
    assert np.array_equal(obs["grid_frontier"].reshape(-1), frontier)


def test_obs_option_cost_split_with_hovel():
    env = make_env()
    env.reset(seed=2)
    game = env.game
    cell, d = _first_frontier(game)
    game.draft_from(cell, d)
    from blueprince_sim.env import obs as O

    enc = O.encode(game)
    for opt in game.state.pending.options:
        room = game.registry.rooms[opt.room_idx]
        cost = game._effective_cost(room, opt)
        row = enc["options"][opt.slot]
        assert row[2] == cost and row[3] == 0  # gems without the Hovel
    game.hovel_placed = True
    enc = O.encode(game)
    for opt in game.state.pending.options:
        room = game.registry.rooms[opt.room_idx]
        cost = game._effective_cost(room, opt)
        row = enc["options"][opt.slot]
        assert row[2] == 0 and row[3] == 3 * cost  # steps at 3:1 with the Hovel


# --------------------------------------------------------------- policy


def test_frontier_greedy_runs_and_terminates():
    import random

    from blueprince_sim.cli.policies import POLICIES

    policy = POLICIES["frontier_greedy"]
    wins = 0
    for seed in range(10):
        game = Game(GameConfig(), seed=seed)
        rnd = random.Random(seed)
        for _ in range(2000):
            if game.phase is Phase.TERMINAL:
                break
            policy(game, rnd)
        assert game.phase is Phase.TERMINAL
        wins += int(game.success())
    assert wins >= 0  # smoke: no hangs, no crashes


def test_frontier_greedy_prefers_progress():
    """With two frontier doors, the policy drafts the one nearer the Antechamber."""
    g = _fresh_game(seed=0)
    doors = g.frontier_doorways()
    assert (g.state.pos, N) in doors  # entrance always has a north door
    from blueprince_sim.cli.policies import _navigate_frontier

    _navigate_frontier(g)
    assert g.phase is Phase.DRAFTING
    assert g.state.pending.direction == N  # north minimizes the optimistic distance
