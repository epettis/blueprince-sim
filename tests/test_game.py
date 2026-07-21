"""Game loop, effects, determinism, and full-episode behavior."""

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.cli.batch import run_episode
from blueprince_sim.cli.policies import POLICIES, greedy_rank


def test_reset_state(registry, cfg):
    g = Game(cfg, seed=1)
    assert g.state.steps == 50
    assert g.state.grid[2] == registry.by_id["entrance_hall"].idx
    assert g.state.grid[ANTECHAMBER_CELL] == registry.by_id["antechamber"].idx
    assert g.state.luck == 10
    assert sorted(g.open_doorways()) == [(2, 1), (2, 2), (2, 8)]  # N, E, W


def test_unlock_toggles(registry):
    g = Game(GameConfig(orchard_unlocked=True, mine_unlocked=True), seed=1)
    assert g.state.steps == 70
    assert g.state.gems == 2


def test_draft_hand_persists_on_decline(cfg):
    g = Game(cfg, seed=5)
    p1 = g.open_door(2, 1)
    names1 = [o.room_idx for o in p1.options]
    g.decline()
    p2 = g.open_door(2, 1)
    assert [o.room_idx for o in p2.options] == names1


def test_choose_places_and_charges(registry, cfg):
    g = Game(cfg, seed=5)
    steps0 = g.state.steps
    p = g.open_door(2, 1)
    g.choose(0)  # slot 1 free
    assert g.state.grid[7] >= 0
    assert g.state.pos == 7
    # 1 step to walk in, +/- whatever the drafted room's effects did
    assert g.state.steps < steps0
    assert g.phase is Phase.NAVIGATE


def test_determinism_same_seed_same_episode(cfg):
    def transcript(seed):
        g = Game(cfg, seed=seed)
        rnd = random.Random(0)
        log = []
        while g.phase is not Phase.TERMINAL and len(log) < 300:
            greedy_rank(g, rnd)
            log.append((g.phase.value, g.state.steps, g.state.gems, g.rooms_placed,
                        tuple(g.state.grid)))
        return log, g.termination_reason

    t1, r1 = transcript(123)
    t2, r2 = transcript(123)
    assert t1 == t2 and r1 == r2
    t3, _ = transcript(124)
    assert t3 != t1


def test_all_policies_terminate(cfg):
    for name in POLICIES:
        for seed in range(10):
            result = run_episode(cfg, POLICIES[name], seed)
            assert result["reason"] in ("antechamber", "out_of_steps", "dead_end")


def test_weight_room_halves_steps(registry, cfg):
    g = Game(cfg, seed=1)
    g.state.steps = 40
    room = registry.by_id["weight_room"]
    g._place_room(room, 7, 4)
    assert g.state.steps == 20


def test_hovel_negates_red_rooms(registry, cfg):
    g = Game(cfg, seed=1)
    g.red_negations = 1
    g.state.steps = 40
    g._place_room(registry.by_id["weight_room"], 7, 4)
    assert g.state.steps == 40  # negated
    g._place_room(registry.by_id["gymnasium"], 8, 4)
    g._enter(8)
    assert g.state.steps == 38  # negation exhausted


def test_nursery_grants_on_bedroom_draft(registry, cfg):
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["nursery"], 7, 4)
    steps0 = g.state.steps
    g._place_room(registry.by_id["guest_bedroom"], 8, 4)
    assert g.state.steps == steps0 + 5


def test_outer_draft_once_per_day(registry):
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    assert g.outer_draft_available()
    p = g.open_outer_draft()
    assert len(p.options) == 3
    outer_ids = {registry.rooms[o.room_idx].pool for o in p.options}
    assert outer_ids == {"outer"}
    g.choose(0)
    assert not g.outer_draft_available()


def test_the_pool_injects_rooms(registry, cfg):
    g = Game(cfg, seed=2)
    pool_room = registry.by_id["the_pool"]
    sizes0 = [d.size() for d in g.state.decks]
    g._place_room(pool_room, 7, 4)
    sizes1 = [d.size() for d in g.state.decks]
    assert sum(sizes1) == sum(sizes0) + 3  # locker room, sauna, pump room


def test_solarium_flag_set_on_place(registry):
    cfg = GameConfig(studio_additions=frozenset({"solarium"}))
    g = Game(cfg, seed=2)
    assert not g.state.solarium_placed
    g._place_room(registry.by_id["solarium"], 7, 4)
    assert g.state.solarium_placed
