"""Game loop, effects, determinism, and full-episode behavior.

Room-specific behaviour has moved out to tests/rooms/: Archives and Darkroom
mystery drafts, the Weight Room's halved steps, Hovel/Nursery/The Pool/
Solarium/Maid's Chamber. The outer-draft and Garage-route tests below stay
here because they exercise the outer-area travel SYSTEM (west_gate,
area-graph routing, off-grid redraws), using whichever room is drafted or
the Garage/Utility Closet breaker only as vehicles.
"""

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase, RedrawKind
from blueprince_sim.engine.grid import N, E, S, W
from blueprince_sim.engine.state import DraftOption
from blueprince_sim.cli.batch import run_episode
from blueprince_sim.cli.policies import POLICIES, greedy_rank
from blueprince_sim.env import actions as A


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
    assert not hasattr(g, "decline")   # no decline API exists
    # slot 1 is always the free forced fallback, so a choice is always possible
    assert any(o.slot == 0 for o in g.state.pending.options)


def test_without_darkroom_no_extra_hidden(registry, cfg):
    """Baseline: drafting from a plain room hides nothing."""
    g = Game(cfg, seed=3)
    # Stand at the Entrance Hall (rank-1 center, always placed) and draft north.
    pending = g.open_door(2, N)
    assert not any(o.hidden for o in pending.options)


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


def test_prev_options_all_negative_one_when_stack_empty(registry, cfg):
    """prev_options is all -1 whenever the Chronograph's rewind_stack is
    empty (including an ordinary DRAFTING hand that has never been
    redrawn) -- the sentinel that lets a policy tell "nothing to rewind
    to" apart from "a rewind would restore floorplan X"."""
    from blueprince_sim.engine.state import PendingDraft
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=1)
    room = next(r for r in registry.rooms if r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=room.idx, orientation=N | S, gem_cost=0, slot=0)]
    g.state.pending = pd  # rewind_stack left at its default_factory []

    assert all(v == -1 for row in O.encode(g)["prev_options"] for v in row)


def test_prev_options_encodes_the_stack_top_like_options(registry, cfg):
    """prev_options is populated from rewind_stack[-1] using the same
    per-slot row encoding "options" uses -- pinned via the same N|S / E|W
    door-bit literals test_option_obs_exposes_door_directions uses for
    "options", with the two hands given DIFFERENT orientations so this
    cannot pass by prev_options accidentally aliasing options."""
    from blueprince_sim.engine.state import PendingDraft
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=1)
    room = next(r for r in registry.rooms if r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=room.idx, orientation=E | W, gem_cost=0, slot=0)]
    pd.rewind_stack = [[DraftOption(room_idx=room.idx, orientation=N | S, gem_cost=0, slot=0)]]
    g.state.pending = pd

    def door_bits(key):                             # obs features N,E,S,W = idx 6..9
        return tuple(int(x) for x in O.encode(g)[key][0][6:10])

    assert door_bits("options") == (0, 1, 0, 1)          # live hand: E|W
    assert door_bits("prev_options") == (1, 0, 1, 0)     # stack top: N|S


def test_prev_options_space_shape_matches_options(registry):
    """prev_options is declared with the identical shape/dtype as options in
    observation_space -- an ADDITIVE Dict key, never a shape change to
    options itself (which would silently reinterpret trained weights)."""
    from blueprince_sim.env import obs as O

    space = O.observation_space(len(registry.rooms), 1, 1)
    assert space.spaces["prev_options"].shape == space.spaces["options"].shape
    assert space.spaces["prev_options"].dtype == space.spaces["options"].dtype


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


def test_outer_draft_once_per_day(registry):
    """The outer draft deals 3 options, all from the outer pool, and is
    available at most once per day."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    assert g.outer_draft_available()
    p = g.open_outer_draft()
    assert len(p.options) == 3
    outer_ids = {registry.rooms[o.room_idx].pool for o in p.options}
    assert outer_ids == {"outer"}
    g.choose(0)
    assert not g.outer_draft_available()


def test_outer_draft_available_while_already_at_the_doorstep():
    """Standing at west_path in NAVIGATE phase (reached by ordinary off-grid
    travel, not by opening the draft) must not refuse the outer draft, and
    opening it from there costs no extra steps.

    ``outer_draft_available()`` must not key off ``off_grid`` alone: the
    doorstep itself is exactly where the draft is legal, and refusing it
    there would force a wasted round-trip back onto the grid and out again
    just to reopen it.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    g.travel_to("west_path")
    assert g.state.area == "west_path" and g.off_grid
    assert g.phase is Phase.NAVIGATE
    assert not g.state.outer_room_drafted
    assert g.outer_draft_available()
    steps_before = g.state.steps
    g.open_outer_draft()
    assert g.state.steps == steps_before  # already at the doorstep: free to open
    assert g.phase is Phase.DRAFTING
    assert g.state.area == "west_path"


def test_outer_draft_unavailable_once_drafted_today_even_at_the_doorstep():
    """Once today's outer room has been drafted, standing at the doorstep
    does not make the draft available again -- the once-per-day guard still
    applies off-grid."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.choose(0)
    assert g.state.outer_room_drafted
    assert g.state.area == "west_path" and g.off_grid
    assert not g.outer_draft_available()


def test_outer_draft_unavailable_mid_draft_phase():
    """While a grid draft is already open (DRAFTING phase), the outer draft
    is not available -- the phase guard is unaffected by the off-grid fix."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_door(2, N)
    assert g.phase is Phase.DRAFTING
    assert not g.outer_draft_available()


def test_outer_draft_unavailable_off_grid_when_route_unaffordable():
    """Off-grid but short of steps, the draft is still refused; one more
    step makes it available -- affordability is enforced uniformly whether
    the route starts on or off the grid, not bypassed by removing the
    ``off_grid`` guard.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 20
    g.travel_to("grounds")  # off-grid, one edge short of west_path
    assert g.off_grid and g.state.area == "grounds"
    cost, _ = g.area_route_cost("west_path")
    g.state.steps = cost  # exactly the route cost: no step left over on arrival
    assert not g.outer_draft_available()
    g.state.steps = cost + 1
    assert g.outer_draft_available()


def test_outer_draft_cost_from_entrance_hall():
    """Drafting from the Entrance Hall deducts exactly 2 steps (house->grounds->west_path).

    The player starts at the Entrance Hall (0 walk) and the area graph charges 2
    steps to reach west_path from the house anchor; the step budget must reflect that.
    """
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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
    """Garage route to west_path needs power; with neither route supplying it only EH works.

    The breaker is off and no power source stands on the grid, so neither route to
    the garage_door_powered flag holds and the graph cannot route garage->west_path.
    The cheapest affordable route must be the EH route (cost 2).
    """
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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


def _outer_pending_room_idxs(g: Game) -> list[int]:
    """The room_idx of each option in the currently pending outer hand."""
    return [o.room_idx for o in g.state.pending.options]


def test_outer_hand_redraw_via_die_redeals_from_the_outer_pool():
    """Holding a die, redrawing an open outer hand spends exactly one die and
    deals a fresh 3-slot hand from the fixed outer pool -- not the grid
    pipeline, which has no doorway to deal against for an outer hand and
    would silently misread ``state.grid[-1]`` as the "from room" if reused.

    Redrawing an outer hand must be possible: ``Game.redraw()`` must not
    assert it unreachable regardless of what the player holds.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.state.dice = 3
    assert g.state.pending.target_cell == -1
    dice_before = g.state.dice
    g.redraw(RedrawKind.DIE)
    assert g.state.dice == dice_before - 1
    assert g.state.pending.target_cell == -1  # still an outer hand
    assert len(g.state.pending.options) == 3
    assert all(g.registry.rooms[i].pool == "outer" for i in _outer_pending_room_idxs(g))


def test_outer_hand_redraw_via_study_spends_a_gem_and_counts_toward_the_cap():
    """A Study redraw on an open outer hand costs 1 gem and increments the
    hand's ``study_redraws_used`` counter, the same bookkeeping a grid hand
    gets -- the 8-per-hand cap is meant to keep applying off-grid."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.state.study_placed = True
    g.state.gems = 5
    g.redraw(RedrawKind.STUDY)
    assert g.state.gems == 4
    assert g.state.pending.study_redraws_used == 1
    assert all(g.registry.rooms[i].pool == "outer" for i in _outer_pending_room_idxs(g))


def test_outer_hand_study_redraw_refused_at_the_8_cap():
    """With 8 Study redraws already used on the open hand, ``_redraw_kind``
    offers no source at all (no dice, Study capped) -- the cap holds on an
    outer hand exactly as it does on a grid hand."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.state.study_placed = True
    g.state.gems = 5
    g.state.dice = 0
    g.state.pending.study_redraws_used = 8
    assert A._redraw_kind(g) is None
    assert not A.action_mask(g)[A.REDRAW_ACTION]


def test_outer_hand_redraw_via_free_source_spends_no_resource():
    """A free-redraw source (``pending.redraws_left > 0``, the Classroom's
    mechanism) applies to an outer hand the same way it would to a grid hand:
    it is preferred over dice/Study, spends no gem or die, and decrements the
    per-hand counter by exactly one.

    Under real play this counter is never populated for an outer hand today
    (it is only set when drafting from inside a placed Classroom, which has
    no meaning off-grid), so this exercises the mechanism directly rather
    than a reachable play scenario -- see the accompanying report.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.state.pending.redraws_left = 1
    g.state.dice = 3
    g.state.study_placed = True
    g.state.gems = 5
    assert A._redraw_kind(g) is RedrawKind.FREE  # free beats die/study
    gems_before, dice_before = g.state.gems, g.state.dice
    g.redraw(RedrawKind.FREE)
    assert g.state.pending.redraws_left == 0
    assert g.state.gems == gems_before
    assert g.state.dice == dice_before
    assert all(g.registry.rooms[i].pool == "outer" for i in _outer_pending_room_idxs(g))


def test_outer_hand_cannot_be_redrawn_without_any_source():
    """With no dice, no Study placed, and no free-redraw source, the outer
    hand's redraw stays refused in both the source lookup and the action
    mask -- redraw must not become unconditionally legal on an outer hand
    just because outer hands can be redrawn at all."""
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    g.state.dice = 0
    g.state.study_placed = False
    assert A._redraw_kind(g) is None
    assert not A.action_mask(g)[A.REDRAW_ACTION]


def test_outer_hand_redraw_is_deterministic_for_a_given_seed():
    """Redrawing the outer hand via a die produces the same dealt hand every
    time for the same seed -- the redraw must draw from its own seeded RNG
    substream (rng.py's per-label determinism invariant), not from
    unseeded/global randomness.
    """
    def _redrawn_hand(seed: int) -> list[int]:
        cfg = GameConfig(west_gate_unlatched=True)
        g = Game(cfg, seed=seed)
        g.open_outer_draft()
        g.state.dice = 1
        g.redraw(RedrawKind.DIE)
        return _outer_pending_room_idxs(g)

    assert _redrawn_hand(9) == _redrawn_hand(9)


def test_outer_hand_redraw_leaves_the_initial_deal_stream_untouched():
    """A redraw must draw from its own RNG label, not the initial deal's
    "outer_draft" label -- pinned by inspecting that label's substream state
    directly (identical before and after a redraw), since two independent
    Game instances can't otherwise distinguish a shared-label bug (each gets
    its own fresh Rng regardless of what a *different* instance's redraw did).
    Reusing "outer_draft" for redraws would shift every subsequent draw from
    that label for the same seed -- the exact risk the brief calls out.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.open_outer_draft()
    state_after_initial_deal = g.rng.stream("outer_draft").getstate()

    g.state.dice = 1
    g.redraw(RedrawKind.DIE)
    assert g.rng.stream("outer_draft").getstate() == state_after_initial_deal


def test_return_costs_doorstep_to_eh():
    """Returning from the doorstep to the Entrance Hall costs 2 steps (west_path->grounds->house).

    The graph derives this: west_path -> grounds (1) -> house (1) = 2 steps total.
    After returning, area is None (on-grid) and pos is the Entrance Hall cell.
    """
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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
    cfg = GameConfig(west_gate_unlatched=True)
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


def test_action_mask_offers_the_outer_draft_at_the_doorstep():
    """Standing at west_path with today's outer room still undrafted, the action
    mask must offer OUTER_DRAFT_ACTION, and taking it must open the hand.

    The doorstep is exactly where the outer room is drafted from, so hiding the
    action there strands the player: the only way back to a state that offers it
    would be a round trip onto the grid and out again. ``open_outer_draft``'s
    walk is a 0-step no-op when the player is already at west_path, so the
    action is not just legal there, it is free.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    g.travel_to("west_path")
    assert g.off_grid and g.state.area == "west_path"
    assert g.phase is Phase.NAVIGATE and not g.state.outer_room_drafted

    assert A.action_mask(g)[A.OUTER_DRAFT_ACTION]
    steps_before = g.state.steps
    A.apply_action(g, A.OUTER_DRAFT_ACTION)
    assert g.phase is Phase.DRAFTING
    assert g.state.area == "west_path"
    assert g.state.steps == steps_before
    assert len(g.state.pending.options) == 3


def test_action_mask_offers_the_outer_draft_from_an_inner_off_grid_node():
    """From an off-grid node that is not the doorstep, the mask still offers the
    outer draft and taking it walks to west_path, paying the route cost.

    OUTER_DRAFT_ACTION is a walk-and-draft macro, the same off the grid as on
    it, so its mask entry gates on affordability (``outer_draft_available``)
    rather than on the player's node -- otherwise the engine would keep counting
    an action the mask refuses to hand over.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    g.travel_to("grounds")
    assert g.off_grid and g.state.area == "grounds"
    cost, _ = g.area_route_cost("west_path")
    assert cost > 0, "setup: grounds must be a real walk short of the doorstep"

    assert A.action_mask(g)[A.OUTER_DRAFT_ACTION]
    steps_before = g.state.steps
    A.apply_action(g, A.OUTER_DRAFT_ACTION)
    assert g.phase is Phase.DRAFTING
    assert g.state.area == "west_path"
    assert g.state.steps == steps_before - cost


def test_off_grid_day_survives_while_the_outer_draft_is_still_free():
    """At the doorstep with too few steps to travel anywhere, the day must NOT
    end while today's outer draft is still open: it is free from there and it
    places a room.

    ``_outer_action_in_budget`` is the off-grid half of the purposefulness test
    that ``_check_termination`` runs after every action; it must count the outer
    draft for the same reason its on-grid twin ``_action_in_budget`` does.
    Drafting it flips ``outer_room_drafted``, after which nothing purposeful is
    left in the budget and the day does end.
    """
    cfg = GameConfig(west_gate_unlatched=True)
    g = Game(cfg, seed=9)
    g.state.steps = 10
    g.travel_to("west_path")
    cheapest = min(cost for node, (cost, _) in g.area_route_costs().items()
                   if node != "west_path")
    g.state.steps = cheapest  # not strictly affordable: no travel is purposeful
    assert not any(A.action_mask(g)[A.TRAVEL_BASE:A.OPEN_SIGIL_DOOR_BASE])
    assert g.outer_draft_available()

    g._check_termination()
    assert g.phase is Phase.NAVIGATE, "the free outer draft must keep the day alive"

    A.apply_action(g, A.OUTER_DRAFT_ACTION)
    g.choose(0)
    assert g.state.outer_room_drafted
    assert g.phase is Phase.TERMINAL, "with the draft spent, nothing purposeful is left"


def test_outer_draft_mask_and_engine_agree_under_random_masked_play():
    """Across hundreds of NAVIGATE states from uniform-random legal play, the
    OUTER_DRAFT_ACTION mask bit equals ``outer_draft_available()`` exactly.

    Both directions matter and each is a real bug: a mask bit the engine rejects
    trips ``open_outer_draft``'s assert, and an engine "yes" the mask hides is
    the owner's report -- an action the day-end budget keeps counting but the
    player can never take. The sweep must actually visit the doorstep off-grid,
    which the guards below pin.
    """
    from blueprince_sim.env.blueprince_env import BluePrinceEnv

    off_grid_states = 0
    doorstep_states = 0
    offered_off_grid = 0
    for seed in range(24):
        env = BluePrinceEnv(cfg=GameConfig(west_gate_unlatched=True, day=20))
        env.reset(seed=seed)
        rng = random.Random(seed)
        for _ in range(80):
            game = env.game
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            if game.phase is Phase.NAVIGATE:
                assert bool(mask[A.OUTER_DRAFT_ACTION]) == game.outer_draft_available(), (
                    f"seed={seed} area={game.state.area} steps={game.state.steps}"
                )
                if game.off_grid:
                    off_grid_states += 1
                    offered_off_grid += int(mask[A.OUTER_DRAFT_ACTION])
                    if game.state.area == "west_path":
                        doorstep_states += 1
            _, _, terminated, truncated, _ = env.step(rng.choice(legal))
            if terminated or truncated:
                break
    assert off_grid_states >= 100, "setup: the sweep barely left the grid"
    assert doorstep_states >= 10, "setup: the sweep never stood at the doorstep"
    assert offered_off_grid >= 10, "setup: the draft was never offered off-grid"


def test_travel_via_garage_from_outer_fires_entry(registry):
    """Returning to garage that was never entered fires its ON_ENTER effects."""
    cfg = GameConfig(west_gate_unlatched=True)
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


