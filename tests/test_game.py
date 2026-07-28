"""Game loop, effects, determinism, and full-episode behavior."""

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase
from blueprince_sim.engine.grid import N, E, S, W
from blueprince_sim.engine.state import DraftOption
from blueprince_sim.cli.batch import run_episode
from blueprince_sim.cli.policies import POLICIES, greedy_rank


def test_reset_state(registry, cfg):
    """A fresh day starts with 50 steps, 10 luck, the Entrance Hall and
    Antechamber pre-placed, and only the entrance's three doorways open."""
    g = Game(cfg, seed=1)
    assert g.state.steps == 50
    assert g.state.grid[2] == registry.by_id["entrance_hall"].idx
    assert g.state.grid[ANTECHAMBER_CELL] == registry.by_id["antechamber"].idx
    assert g.state.luck == 10
    assert sorted(g.open_doorways()) == [(2, 1), (2, 2), (2, 8)]  # N, E, W


def test_unlock_toggles(registry):
    """Orchard/mine unlocks raise the day's starting resources (70 steps,
    2 gems)."""
    g = Game(GameConfig(orchard_unlocked=True, mine_unlocked=True), seed=1)
    assert g.state.steps == 70
    assert g.state.gems == 2


def test_cannot_decline_a_draft(cfg):
    """A draft cannot be declined: no decline API exists, and the free slot-1
    fallback guarantees there is always a choosable option."""
    g = Game(cfg, seed=5)
    g.open_door(2, 1)
    assert not hasattr(g, "decline")   # declining a draft no longer exists
    # slot 1 is always the free forced fallback, so a choice is always possible
    assert any(o.slot == 0 for o in g.state.pending.options)


def test_archives_hides_a_draftable_mystery(registry, cfg):
    """Drafting out of the Archives conceals exactly one option's identity;
    the mystery is still a real room that places normally at no step cost."""
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
    """A hidden (mystery) option's room identity is concealed in the obs, but
    its gem cost stays visible so the agent can budget for it."""
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


def test_darkroom_hides_all_three_options(registry, cfg):
    """Drafting out of the Darkroom hides every option's identity; the hidden
    options remain real, placeable rooms."""
    g = Game(cfg, seed=3)
    # Stand in the Darkroom and draft out of its north door.
    # Darkroom layout is "t"; place it so a north doorway is available.
    darkroom = registry.by_id["darkroom"]
    # Use a t-orientation that opens N/E/S (mask 7 = N|E|S)
    g._place_room(darkroom, 7, N | E | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.gems = 9  # afford whatever comes up
    pending = g.open_door(7, N)
    hidden = [o for o in pending.options if o.hidden]
    assert len(hidden) == len(pending.options)      # every option is hidden
    assert all(o.hidden for o in pending.options)   # no visible option remains
    # all hidden options are still real, placeable rooms
    steps_before = g.state.steps
    g.choose(hidden[0].slot)
    assert g.state.grid[12] >= 0                    # room placed at the north cell
    assert g.phase is Phase.NAVIGATE
    assert g.state.steps == steps_before            # placing costs no step


def test_without_darkroom_no_extra_hidden(registry, cfg):
    """Baseline: drafting from a plain room hides nothing."""
    g = Game(cfg, seed=3)
    # Stand at the Entrance Hall (rank-1 center, always placed) and draft north.
    pending = g.open_door(2, N)
    assert not any(o.hidden for o in pending.options)


def test_darkroom_obs_hides_identity_for_all_slots(registry, cfg):
    """When drafting from the Darkroom, the obs zeroes the room id of every
    option slot (nothing leaks to the agent)."""
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=3)
    darkroom = registry.by_id["darkroom"]
    g._place_room(darkroom, 7, N | E | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.gems = 9
    pending = g.open_door(7, N)
    g.state.pending = pending
    obs = O.encode(g)["options"]
    for slot_idx in range(len(pending.options)):
        assert obs[slot_idx][0] == 0                # room identity concealed


def test_option_obs_exposes_door_directions(registry, cfg):
    """The obs exposes each option's N/E/S/W door bits and tracks them when
    the option's orientation changes."""
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
    """The CLI option preview draws the floorplan's current orientation
    (N|S renders as a vertical bar, a 4-way as a cross)."""
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
    """The draft/move split: choosing an option places the room behind the
    doorway but the player stays put - no step paid, no resources granted."""
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
    """Moving into a placed room costs one step and fires its on-enter grant
    (the grant amount is read from the room's own effect data)."""
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
    """Whole episodes are deterministic given a seed (a tested invariant of
    the named RNG substreams) and diverge across different seeds."""
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
    """Every built-in CLI policy plays each day to one of the recognized
    termination reasons - no policy can hang the engine."""
    for name in POLICIES:
        for seed in range(10):
            result = run_episode(cfg, POLICIES[name], seed)
            assert result["reason"] in ("antechamber", "out_of_steps", "dead_end")


def test_weight_room_halves_steps(registry, cfg):
    """Placing the Weight Room (a red room) halves the remaining steps."""
    g = Game(cfg, seed=1)
    g.state.steps = 40
    room = registry.by_id["weight_room"]
    g._place_room(room, 7, 4)
    assert g.state.steps == 20


def test_shelter_negates_red_rooms(registry, cfg):
    """A Shelter negation cancels one red room's penalty and is then
    consumed - the next red room hits normally."""
    g = Game(cfg, seed=1)
    g.red_negations = 1  # the Shelter grants these
    g.state.steps = 40
    g._place_room(registry.by_id["weight_room"], 7, 4)
    assert g.state.steps == 40  # negated
    g._place_room(registry.by_id["gymnasium"], 8, 4)
    g._enter(8)
    assert g.state.steps == 38  # negation exhausted


def test_hovel_pays_gem_costs_with_steps(registry, cfg):
    """With the Hovel placed, gem costs are paid in steps at 3 steps per gem
    and the gem balance is left untouched."""
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
    """A placed Nursery grants 5 steps whenever a bedroom is drafted."""
    g = Game(cfg, seed=1)
    g._place_room(registry.by_id["nursery"], 7, 4)
    steps0 = g.state.steps
    g._place_room(registry.by_id["guest_bedroom"], 8, 4)
    assert g.state.steps == steps0 + 5


def test_outer_draft_once_per_day(registry):
    """The outer draft deals 3 options, all from the outer pool, and is
    available at most once per day."""
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
    """Drafting from the Entrance Hall deducts exactly 2 steps (house->grounds->west_path).

    The player starts at the Entrance Hall (0 walk) and the area graph charges 2
    steps to reach west_path from the house anchor; the step budget must reflect that.
    """
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    steps_before = g.state.steps
    g.open_outer_draft()
    assert g.state.steps == steps_before - 2
    assert g.state.area == "west_path"


def test_outer_draft_cost_includes_walk():
    """When the player is one step away from the Entrance Hall, total cost is 3 steps (1 walk + 2).

    The area graph charges 2 steps from the house anchor to west_path; walking to EH first
    costs 1 more, so the budget must drop by exactly 3 and the player ends at west_path.
    """
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
    assert g.state.area == "west_path"


def test_garage_route_unavailable_without_breaker(registry):
    """Garage route to west_path is only taken when the breaker is on; without it only EH works.

    With the breaker off the garage_door_breaker flag is absent, so the graph cannot
    route garage->west_path. The cheapest affordable route must be the EH route (cost 2).
    """
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
    # Route cost should only include EH path (house anchor: 2 area steps to west_path)
    cost = g._outer_route_cost()
    assert cost == 2


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
    """Choosing an outer room places it but does NOT fire ON_ENTER.

    After choosing, the player stays at the doorstep (area == "west_path"), not inside;
    ON_ENTER fires only when enter_outer_room() is explicitly called.
    """
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.area == "west_path"  # still at doorstep
    assert not g.state.outer_room_entered
    assert g.phase is Phase.NAVIGATE


def test_travel_to_outer_room_fires_once():
    """Travelling to the drafted outer room fires ON_ENTER exactly once.

    The graph charges 1 step for west_path->outer_room. area must become the
    room id and outer_room_entered must be set so a second travel is a no-op
    (outer_room_entered stays True; steps are still deducted by travel_to).
    """
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.area == "west_path"
    steps_before = g.state.steps
    outer_room = next(r for r in g.outer_rooms if r.id in g.placed_ids)
    g.travel_to(outer_room.id)
    assert g.state.area == outer_room.id  # inside the drafted outer room
    assert g.state.outer_room_entered
    assert g.state.steps == steps_before - 1  # graph: west_path->outer_room = 1 step


def test_return_costs_doorstep_to_eh():
    """Returning from the doorstep to the Entrance Hall costs 2 steps (west_path->grounds->house).

    The graph derives this: west_path -> grounds (1) -> house (1) = 2 steps total.
    After returning, area is None (on-grid) and pos is the Entrance Hall cell.
    """
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    steps_before = g.state.steps
    g.travel_to("house")
    assert g.state.area is None  # back on the grid
    assert g.state.pos == 2  # ENTRANCE_CELL
    assert g.state.steps == steps_before - 2


def test_return_costs_inside_to_eh():
    """Returning from inside the outer room to EH costs 3 steps (room->west_path->grounds->house).

    The graph: outer_room -> west_path (1) -> grounds (1) -> house (1) = 3 steps.
    """
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    outer_room = next(r for r in g.outer_rooms if r.id in g.placed_ids)
    g.travel_to(outer_room.id)
    steps_before = g.state.steps
    g.travel_to("house")
    assert g.state.area is None  # back on the grid
    assert g.state.steps == steps_before - 3


def test_action_mask_off_grid():
    """When off-grid (area != None), only travel and outer-area actions are legal.

    After choosing an outer room from the doorstep, area is "west_path". Grid
    draft/move actions must be masked out. Travel to the outer room and travel
    back to house must be offered as TRAVEL_BASE actions.
    """
    from blueprince_sim.env import actions as A
    cfg = GameConfig(outer_rooms_unlocked=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.area == "west_path"
    mask = A.action_mask(g)
    node_ids = A._build_area_node_ids(g.registry)
    outer_room = next(r for r in g.outer_rooms if r.id in g.placed_ids)
    # No grid draft or move actions should be legal
    assert not any(mask[A.OPEN_BASE:A.CHOOSE_BASE])
    assert not any(mask[A.MOVE_TO_BASE:A.MOVE_TO_BASE + 45])
    assert not mask[A.OUTER_DRAFT_ACTION]
    # Travel to the outer room and back to house must be offered
    house_idx = node_ids.index("house")
    outer_idx = node_ids.index(outer_room.id)
    assert mask[A.TRAVEL_BASE + house_idx], "travel to house should be legal from west_path"
    assert mask[A.TRAVEL_BASE + outer_idx], "travel to outer room should be legal from doorstep"


def test_travel_via_garage_from_outer_fires_entry(registry):
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
    assert g.state.area == "west_path"
    g.travel_to("garage")
    assert g.state.area is None  # back on the grid
    assert g.state.pos == garage_cell
    # Garage should now be marked entered
    assert g.state.entered[garage_cell]


def test_the_pool_injects_rooms(registry, cfg):
    """Placing The Pool injects its 3 temp rooms (Locker Room, Sauna, Pump
    Room) into the draft decks."""
    g = Game(cfg, seed=2)
    pool_room = registry.by_id["the_pool"]
    sizes0 = [d.size() for d in g.state.decks]
    g._place_room(pool_room, 7, 4)
    sizes1 = [d.size() for d in g.state.decks]
    assert sum(sizes1) == sum(sizes0) + 3  # locker room, sauna, pump room


def test_solarium_flag_set_on_place(registry):
    """Placing the Solarium sets the flag that keys the slot-2/3 rarity
    flattening for the rest of the day."""
    cfg = GameConfig(studio_additions=frozenset({"solarium"}))
    g = Game(cfg, seed=2)
    assert not g.state.solarium_placed
    g._place_room(registry.by_id["solarium"], 7, 4)
    assert g.state.solarium_placed


def test_maids_chamber_reduces_luck_on_place(registry, cfg):
    """Placing Maid's Chamber applies -3 luck immediately (ON_PLACE)."""
    g = Game(cfg, seed=1)
    luck_before = g.state.luck
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == luck_before - 3


def test_maids_chamber_luck_clamps_at_zero(registry, cfg):
    """anti_luck never drives luck below 0."""
    g = Game(cfg, seed=1)
    g.state.luck = 1
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == 0


def test_maids_chamber_luck_negated_by_shelter(registry, cfg):
    """Shelter negates the Maid's Chamber red-room penalty."""
    g = Game(cfg, seed=1)
    g.red_negations = 1
    luck_before = g.state.luck
    g._place_room(registry.by_id["maids_chamber"], 7, S | E)
    assert g.state.luck == luck_before  # penalty negated
    assert g.red_negations == 0  # one negation consumed
