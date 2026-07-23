"""Game loop, effects, determinism, and full-episode behavior."""

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import N, E, S, W
from blueprince_sim.engine.state import DraftOption
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


def test_cannot_decline_a_draft(cfg):
    g = Game(cfg, seed=5)
    g.open_door(2, 1)
    assert not hasattr(g, "decline")   # declining a draft no longer exists
    # slot 1 is always the free forced fallback, so a choice is always possible
    assert any(o.slot == 0 for o in g.state.pending.options)


def test_archives_hides_a_draftable_mystery(registry, cfg):
    g = Game(cfg, seed=3)
    # Stand in the Archives and draft out of its north door.
    g._place_room(registry.by_id["archives"], 7, N | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.gems = 9  # afford whatever the mystery turns out to be
    pending = g.open_door(7, N)
    hidden = [o for o in pending.options if o.hidden]
    assert len(hidden) == 1                       # exactly one mystery option
    assert not pending.options[0].hidden          # a visible option remains
    # the mystery is still a real, placeable room
    steps_before = g.state.steps
    g.choose(hidden[0].slot)
    assert g.state.grid[12] >= 0                   # room placed at the north cell
    assert g.phase is Phase.NAVIGATE
    assert g.state.steps == steps_before           # placing costs no step


def test_archives_mystery_still_shows_gem_cost(registry, cfg):
    from blueprince_sim.engine.state import PendingDraft
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=1)
    gem_room = next(r for r in registry.rooms if r.gem_cost > 0 and r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=gem_room.idx, orientation=gem_room.door_mask,
                              gem_cost=gem_room.gem_cost, slot=2, hidden=True)]
    g.state.gems = 9
    g.state.pending = pd
    row = O.encode(g)["options"][2]                 # obs row for slot 2
    assert row[0] == 0                              # identity (room id) concealed
    assert row[2] == g._effective_cost(gem_room, pd.options[0])  # gem cost visible
    assert row[2] > 0


def test_option_obs_exposes_door_directions(registry, cfg):
    from blueprince_sim.engine.state import PendingDraft
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=1)
    room = next(r for r in registry.rooms if r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=room.idx, orientation=N | S, gem_cost=0, slot=0)]
    g.state.pending = pd

    def door_bits():                                # obs features N,E,S,W = idx 6..9
        return tuple(int(x) for x in O.encode(g)["options"][0][6:10])

    assert door_bits() == (1, 0, 1, 0)             # N|S: north & south doors only
    pd.options[0].orientation = E | W
    assert door_bits() == (0, 1, 0, 1)             # rotating flips the exposed doors


def test_cli_preview_glyph_tracks_orientation(registry, cfg):
    from blueprince_sim.cli.render import render_options
    from blueprince_sim.engine.state import PendingDraft

    g = Game(cfg, seed=1)
    room = next(r for r in registry.rooms if r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=room.idx, orientation=N | S, gem_cost=0, slot=0)]
    g.state.pending = pd
    assert "║" in render_options(g)           # N|S renders as a vertical ║
    pd.options[0].orientation = N | E | S | W
    assert "╬" in render_options(g)           # a 4-way renders as a cross ╬


def test_choose_places_but_does_not_enter(registry, cfg):
    g = Game(cfg, seed=5)
    steps0 = g.state.steps
    g.open_door(2, 1)  # draft through the Entrance's north door
    g.choose(0)        # slot 1 (free): places the room, does not enter it
    assert g.state.grid[7] >= 0        # room placed behind the doorway
    assert g.state.pos == 2            # player has NOT moved in
    assert not g.state.entered[7]      # ...so no resources granted yet
    assert g.state.steps == steps0     # no step paid on a free draft
    assert g.phase is Phase.NAVIGATE


def test_move_charges_a_step_and_applies_the_room_effect(registry, cfg):
    g = Game(cfg, seed=1)
    # A room that grants steps on entry, placed north of the Entrance with doors
    # linking south (to the Entrance) and north. Read its grant from the room's
    # own effect so the test exercises the enter mechanism, not a literal value.
    room = registry.by_id["guest_bedroom"]
    grant = next(e.param("amount") for e in room.effects
                 if e.tag == "grant" and e.param("resource") == "steps")
    assert grant > 0
    g._place_room(room, 7, N | S)
    assert not g.state.entered[7]
    assert N in g.adjacent_moves()          # connected, walkable
    steps0 = g.state.steps
    g.move(N)
    assert g.state.pos == 7
    assert g.state.entered[7]               # entered now
    # one step spent walking in, then the room's on-enter grant applied
    assert g.state.steps == steps0 - 1 + grant


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


def test_shelter_negates_red_rooms(registry, cfg):
    g = Game(cfg, seed=1)
    g.red_negations = 1  # the Shelter grants these
    g.state.steps = 40
    g._place_room(registry.by_id["weight_room"], 7, 4)
    assert g.state.steps == 40  # negated
    g._place_room(registry.by_id["gymnasium"], 8, 4)
    g._enter(8)
    assert g.state.steps == 38  # negation exhausted


def test_hovel_pays_gem_costs_with_steps(registry, cfg):
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["hovel"], 7, N | S)  # ON_PLACE sets the flag
    assert g.hovel_placed
    room = next(r for r in registry.rooms if r.gem_cost > 0 and r.rarity)
    opt = DraftOption(room_idx=room.idx, orientation=room.door_mask,
                      gem_cost=room.gem_cost, slot=1)
    cost = g._effective_cost(room, opt)
    assert cost > 0
    g.state.steps, g.state.gems = 40, 5
    assert g.affordable(room, opt)          # 40 > 3*cost
    g._pay(room, opt)
    assert g.state.steps == 40 - 3 * cost   # paid in steps
    assert g.state.gems == 5                # gems untouched


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


def test_outer_draft_cost_from_entrance_hall():
    """Draft from EH = exactly 2 steps (0 walk + 2 EH path cost)."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    steps_before = g.state.steps
    g.open_outer_draft()
    # cost = dist[EH] + outer_path_entrance_cost = 0 + 2 = 2
    assert g.state.steps == steps_before - 2
    assert g.state.outer_loc == 1


def test_outer_draft_cost_includes_walk():
    """If player walked from EH, total cost = walk_dist + 2."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    # Place a room north of entrance and move there (1 step walk)
    from blueprince_sim.engine.grid import N, S
    room = g.registry.rooms[0]  # any room
    g._place_room(room, 7, N | S)  # cell 7 = rank 2 center, north of EH
    g.state.entered[7] = True
    g.state.pos = 7
    g.state.steps = 10
    steps_before = g.state.steps
    # dist[EH=2] = 1, so total = 1 + 2 = 3
    g.open_outer_draft()
    assert g.state.steps == steps_before - 3
    assert g.state.pos == 2  # walked back to EH
    assert g.state.outer_loc == 1


def test_garage_route_unavailable_without_breaker(registry):
    """Garage route requires utility_closet placed AND entered."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    uc = registry.by_id.get("utility_closet")
    garage = next((r for r in registry.rooms if r.id.startswith("garage")), None)
    if uc is None or garage is None:
        return  # not in registry, skip
    from blueprince_sim.engine.grid import N, S
    # Place utility_closet but don't enter it (breaker off)
    g._place_room(uc, 7, N | S)
    g._place_room(garage, 3, N | S)  # garage placed, also not entered
    assert not g._breaker_on()
    # Route cost should only include EH path (dist=0 + 2)
    cost = g._outer_route_cost()
    assert cost == g.cfg.outer_path_entrance_cost  # 2


def test_garage_route_available_with_breaker(registry):
    """Garage route is available when utility_closet is placed AND entered."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    uc = registry.by_id.get("utility_closet")
    garage = next((r for r in registry.rooms if r.id.startswith("garage")), None)
    if uc is None or garage is None:
        return
    from blueprince_sim.engine.grid import N, S, E, W
    # Place garage adjacent to entrance (west, cell 1) and utility_closet elsewhere
    g._place_room(garage, 1, E | W)  # cell 1, east door connects to EH cell 2
    g._place_room(uc, 7, N | S)
    g.state.entered[g._utility_closet_cell()] = True  # breaker on
    assert g._breaker_on()
    # Now both routes exist; garage route costs dist[garage_cell] + 1
    cost = g._outer_route_cost()
    assert cost is not None


def test_choose_outer_does_not_enter():
    """Choosing an outer room places it but does NOT fire ON_ENTER."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.outer_loc == 1  # still at doorstep
    assert not g.state.outer_room_entered
    assert g.phase is Phase.NAVIGATE


def test_enter_outer_room_fires_once():
    """enter_outer_room deducts 1 step, moves to inside, and can't be called again."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.outer_loc == 1
    steps_before = g.state.steps
    g.enter_outer_room()
    assert g.state.outer_loc == 2
    assert g.state.outer_room_entered
    assert g.state.steps == steps_before - cfg.outer_enter_cost
    # Entering again raises AssertionError
    import pytest
    with pytest.raises(AssertionError):
        g.enter_outer_room()


def test_return_costs_doorstep_to_eh():
    """Return from doorstep to EH costs outer_path_entrance_cost (2)."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    steps_before = g.state.steps
    g.return_from_outer("entrance_hall")
    assert g.state.outer_loc == 0
    assert g.state.pos == 2  # ENTRANCE_CELL
    assert g.state.steps == steps_before - cfg.outer_path_entrance_cost


def test_return_costs_inside_to_eh():
    """Return from inside the outer room to EH costs 3 (1 inside->doorstep + 2 EH path)."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    g.enter_outer_room()
    steps_before = g.state.steps
    g.return_from_outer("entrance_hall")
    assert g.state.outer_loc == 0
    assert g.state.steps == steps_before - (cfg.outer_path_entrance_cost + 1)


def test_action_mask_off_grid():
    """When outer_loc > 0, only outer-area actions (187/194) are legal; grid actions masked."""
    from blueprince_sim.env import actions as A
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.outer_loc == 1
    mask = A.action_mask(g)
    # No grid draft or move actions should be legal
    assert not any(mask[A.OPEN_BASE:A.CHOOSE_BASE])
    assert not any(mask[A.MOVE_TO_BASE:A.MOVE_TO_BASE + 45])
    assert not mask[A.OUTER_DRAFT_ACTION]
    # Enter and return-to-EH should be legal (outer room drafted, steps > 0)
    assert mask[A.ENTER_OUTER_ACTION]
    assert mask[A.RETURN_EH_ACTION]


def test_return_from_outer_into_unentered_garage_fires_entry(registry):
    """Returning to garage that was never entered fires its ON_ENTER effects."""
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    garage = next((r for r in registry.rooms if r.id.startswith("garage")), None)
    uc = registry.by_id.get("utility_closet")
    if garage is None or uc is None:
        return
    from blueprince_sim.engine.grid import N, S, E, W
    # Place garage west of entrance (cell 1) with an east door connecting to EH
    g._place_room(garage, 1, E | W)
    g._place_room(uc, 7, N | S)
    uc_cell = g._utility_closet_cell()
    g.state.entered[uc_cell] = True  # breaker on
    assert g._breaker_on()
    garage_cell = g._garage_cell()
    assert not g.state.entered[garage_cell]
    # Go to outer area and come back via garage
    g.open_outer_draft()
    g.choose(0)
    assert g.state.outer_loc == 1
    g.return_from_outer("garage")
    assert g.state.outer_loc == 0
    assert g.state.pos == garage_cell
    # Garage should now be marked entered
    assert g.state.entered[garage_cell]


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
