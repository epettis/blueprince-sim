"""When the day ends, and when it must not.

Two owner reports drive this file, and they turn out to be the same bug seen
twice: the day ended the moment the last frontier doorway was consumed, so a
room that had just been placed through that doorway could never be walked
into. The Coat Check never stored anything; the Sauna never set the flag that
pays +20 steps tomorrow.

The termination rule these pin: running out of steps ends the day outright,
and otherwise the day ends only when no purposeful action remains. Having no
frontier doorway left is a REASON ("dead_end"), not a trigger.

Grids are hand-built rather than seeded: three rooms whose door masks face
only the Entrance Hall leave zero frontier doorways with total certainty,
where a seed would only make it likely.
"""

from __future__ import annotations

import random

from blueprince_sim.cli.policies import frontier_greedy
from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops as _shops
from blueprince_sim.engine import special_items as _si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, ENTRANCE_CELL, N, S, W

#: North of the Entrance Hall (rank 2, centre column). The Sauna's own door
#: mask is S alone -- a dead end -- so placing it here consumes the Entrance
#: Hall's north doorway and creates no new one.
NORTH_CELL = ENTRANCE_CELL + 5
WEST_CELL = ENTRANCE_CELL - 1
EAST_CELL = ENTRANCE_CELL + 1


def _sealed_house(cfg: GameConfig, seed: int = 3) -> Game:
    """A house with no frontier doorway left and three unentered rooms around
    the player: Sauna north, Coat Check east, Closet west.

    Each is placed with an orientation holding exactly the one door that faces
    the Entrance Hall, so every one of the Entrance Hall's three doorways is
    consumed and none is created.
    """
    game = Game(cfg, seed=seed)
    game._place_room(game.registry.by_id["closet"], WEST_CELL, E)
    game._place_room(game.registry.by_id["coat_check"], EAST_CELL, W)
    game._place_room(game.registry.by_id["sauna"], NORTH_CELL, S, entry_dir=S)
    assert not game.frontier_doorways(), "scenario needs a house with no doors left"
    assert not game._antechamber_reachable(), "scenario needs the Antechamber walled off"
    return game


def _plain_cfg(**kwargs) -> GameConfig:
    """A config with locks and special items off, so only the walk rules are
    in play and no item-gated action can quietly keep a day alive."""
    return GameConfig(door_locks=False, special_items=False, **kwargs)


def _spent_house(cfg: GameConfig, north_room_id: str, seed: int = 3) -> Game:
    """A sealed house with every room already entered and the player standing
    in ``north_room_id``: nothing left to draft, walk to, or enter.

    The baseline for every in-place test below. What such a day does next is
    down to what sits at the player's feet and nothing else, which is asserted
    here rather than assumed: ``_action_in_budget`` must already be False, so a
    day that keeps running can only be doing it for an in-place action.
    """
    game = Game(cfg, seed=seed)
    game._place_room(game.registry.by_id["closet"], WEST_CELL, E)
    game._place_room(game.registry.by_id["coat_check"], EAST_CELL, W)
    game._place_room(game.registry.by_id[north_room_id], NORTH_CELL, S, entry_dir=S)
    st = game.state
    for cell in (ENTRANCE_CELL, WEST_CELL, EAST_CELL, NORTH_CELL):
        st.entered[cell] = True
    st.pos = NORTH_CELL
    st.steps = 10
    st.outer_room_drafted = True  # remove the West Path draft from the question
    assert not game.frontier_doorways(), "scenario needs a house with no doors left"
    assert not game._action_in_budget(), "scenario needs nothing left that costs a step"
    return game


def _outer_room_stand(room_id: str, seed: int = 1) -> Game:
    """A day standing inside ``room_id`` as today's drafted outer room, off the
    grid -- the only way to reach the Shrine and the Trading Post, which have
    no on-grid presence."""
    game = Game(GameConfig(), seed=seed)
    game.placed_ids.add(room_id)
    game.state.outer_room_drafted = True
    game.state.area = room_id
    assert game.inside_outer_room, f"scenario needs the player inside the {room_id}"
    return game


def _in_place_ids(game: Game) -> list[str]:
    """Ids of every in-place action the engine currently counts as purposeful."""
    return [name for name, _do in game._in_place_actions()]


# ------------------------------------------- the day must not end too early

def test_the_day_does_not_end_while_a_placed_room_is_still_unentered():
    """The owner's Coat Check report: the last frontier doorway is gone, but
    three just-placed rooms are still unentered and one step away, so there is
    plenty left to do and the day must keep running."""
    game = _sealed_house(_plain_cfg())
    game.state.steps = 10

    game._check_termination()

    assert game.phase is Phase.NAVIGATE
    assert game.termination_reason == ""


def test_a_room_behind_the_last_frontier_doorway_can_still_be_entered():
    """Not ending is only half of it -- the walk into the Coat Check has to
    actually succeed and mark the cell entered, which is what makes its
    on-entry effect fire. The termination check runs first, exactly as the
    placement that consumed the last doorway would have run it."""
    game = _sealed_house(_plain_cfg())
    game.state.steps = 10
    game._check_termination()

    game.move_to(EAST_CELL)

    assert game.state.pos == EAST_CELL
    assert game.state.entered[EAST_CELL]


def test_the_sauna_entered_through_the_last_frontier_doorway_pays_tomorrow():
    """The owner's stated arithmetic, end to end: the Sauna placed through the
    final doorway is entered, which sets state.sauna_visited, which carries as
    sauna_bonus, which makes tomorrow start on 50 base + 20 Apple Orchard +
    20 Sauna = 90 steps. The termination check runs first, exactly as the
    placement that consumed the last doorway would have run it."""
    game = _sealed_house(_plain_cfg(orchard_unlocked=True))
    game.state.steps = 10
    game._check_termination()

    game.move_to(NORTH_CELL)

    assert game.state.sauna_visited
    assert game.carryover()["sauna_bonus"] is True

    tomorrow = Game(_plain_cfg(orchard_unlocked=True, sauna_bonus=True), seed=4)
    assert tomorrow.state.steps == 90


def test_the_sauna_bonus_is_not_paid_when_the_sauna_is_never_entered():
    """The other direction, so the test above cannot pass on a bonus that is
    granted unconditionally: a Sauna standing on the grid but never walked
    into pays nothing tomorrow."""
    game = _sealed_house(_plain_cfg(orchard_unlocked=True))
    game.state.steps = 10

    assert not game.state.sauna_visited
    assert game.carryover()["sauna_bonus"] is False

    tomorrow = Game(_plain_cfg(orchard_unlocked=True, sauna_bonus=False), seed=4)
    assert tomorrow.state.steps == 70


# ----------------------------------------------- the day must still end

def test_the_day_ends_once_every_reachable_room_has_been_entered():
    """The anti-vacuity direction: with the same doorless house but all three
    rooms already entered, nothing purposeful is left and the day ends. A rule
    that never terminates would let an RL episode run to its step cap."""
    game = _sealed_house(_plain_cfg())
    for cell in (WEST_CELL, EAST_CELL, NORTH_CELL):
        game.state.entered[cell] = True
    game.state.steps = 10
    game.state.outer_room_drafted = True  # remove the West Path from the question

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == "dead_end"


def test_running_out_of_steps_ends_the_day_even_with_rooms_unentered():
    """Steps are the hard stop: at zero the day is over regardless of how much
    remains undone, so the productivity rule can never resurrect a spent day."""
    game = _sealed_house(_plain_cfg())
    game.state.steps = 0

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == "out_of_steps"


def test_a_door_that_is_out_of_reach_records_out_of_steps_not_dead_end():
    """The reason taxonomy survives the reordering: "dead_end" is reserved for
    a house with no frontier doorway anywhere and no path to the Antechamber.
    A doorway that exists but sits beyond the step budget is "out_of_steps"."""
    game = Game(_plain_cfg(), seed=3)
    game._place_room(game.registry.by_id["closet"], WEST_CELL, E)
    game._place_room(game.registry.by_id["coat_check"], EAST_CELL, W)
    # A north-south corridor: its far door is the house's only frontier
    # doorway, and it stands one room away from the player.
    game._place_room(game.registry.by_id["hallway"], NORTH_CELL, N | S, entry_dir=S)
    for cell in (WEST_CELL, EAST_CELL, NORTH_CELL):
        game.state.entered[cell] = True     # nothing left to gain by walking
    game.state.steps = 1                    # a draft must arrive with a step to spare
    game.state.outer_room_drafted = True
    assert game.frontier_doorways(), "scenario needs a doorway that still exists"

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == "out_of_steps"


# ----------------------------------- the bound on what counts as purposeful

def test_a_reversible_switch_does_not_keep_the_day_alive():
    """The safety bound on "productive": a Utility Closet breaker can be
    flipped and flipped back forever, so a day whose only remaining action is
    a toggle must still end. Counting toggles is how a day never terminates."""
    cfg = GameConfig(special_items=False)
    game = Game(cfg, seed=3)
    game._place_room(game.registry.by_id["closet"], WEST_CELL, E)
    game._place_room(game.registry.by_id["coat_check"], EAST_CELL, W)
    game._place_room(game.registry.by_id["utility_closet"], NORTH_CELL, S, entry_dir=S)
    for cell in (WEST_CELL, EAST_CELL, NORTH_CELL):
        game.state.entered[cell] = True
    game.state.pos = NORTH_CELL
    game.state.steps = 10
    game.state.outer_room_drafted = True
    assert not game.frontier_doorways()
    assert game.can_toggle_keycard_power(), "scenario needs a live toggle underfoot"

    game._check_termination()

    assert game.phase is Phase.TERMINAL
# -------------------------------------------- in-place actions keep it alive

def test_a_free_locker_underfoot_keeps_the_day_alive():
    """The owner's Coat Check complaint in its second form: the Locker Room's
    three unlocked lockers cost no step and need no doorway, so a day with one
    under the player's feet is not over, however sealed the house is."""
    game = _spent_house(GameConfig(), "locker_room")
    assert _in_place_ids(game) == ["open_container"], "scenario needs a free locker"

    game._check_termination()

    assert game.phase is Phase.NAVIGATE
    assert game.termination_reason == ""


def test_the_day_ends_once_the_lockers_are_emptied():
    """The other direction, so the test above cannot pass on a day that simply
    never ends: with every container at the cell already opened, the same house
    has nothing free left and closes on "dead_end"."""
    game = _spent_house(GameConfig(), "locker_room")
    game.state.special.opened_containers[NORTH_CELL] = 99  # every locker emptied
    assert not _in_place_ids(game)

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert game.termination_reason == "dead_end"


def test_the_office_terminal_keeps_the_day_alive():
    """A second, unrelated in-place action, so the rule reads as "any zero-step
    action" rather than "containers": Spread Gold and Run Payroll are worked
    from where the player stands and each is capped once per day."""
    game = _spent_house(GameConfig(), "office")

    assert _in_place_ids(game) == ["spread_gold", "run_payroll"]
    game._check_termination()

    assert game.phase is Phase.NAVIGATE


def test_a_priced_shop_row_keeps_the_day_alive():
    """Buying spends coins, so a shop row the player can afford is real work
    left -- the positive control for the free-row exclusion below."""
    game = _spent_house(GameConfig(), "locksmith")
    game.state.coins = 20
    game.state.shops.stock["locksmith"] = [
        {"id": "key", "kind": "resource", "grant": {"keys": 1}, "price": 5}]

    assert _in_place_ids(game) == ["buy"]
    game._check_termination()

    assert game.phase is Phase.NAVIGATE


# --------------------------------------- the bound: every counted act consumes

def test_taking_the_free_actions_always_runs_the_day_out():
    """The invariant the whole rule rests on: every counted in-place action
    strictly consumes something, so repeatedly taking one has to terminate.
    The Locker Room holds 3 open plus 17 locked lockers and nothing reachable
    here can create a twenty-first, so the day must be over inside that many
    rounds -- a non-consuming entry (a toggle, a free unlimited shop row)
    would spin here forever instead."""
    game = _spent_house(GameConfig(), "locker_room")
    total_containers = sum(
        game.registry.special.containers["rooms"]["locker_room"].values())

    rounds = 0
    while game.phase is not Phase.TERMINAL:
        entry = next(game._in_place_actions(), None)
        if entry is None:
            game._check_termination()
            break
        entry[1]()
        rounds += 1
        assert rounds <= total_containers, "in-place actions are not consuming anything"

    assert game.phase is Phase.TERMINAL
    assert not _in_place_ids(game)


def test_a_free_and_unlimited_shop_row_does_not_keep_the_day_alive():
    """The one place the consuming-bound is not automatic: a resource row with
    no purchase limit (the Locksmith's keys) never sells out, so at price 0 it
    would stay buyable forever. Such a row consumes nothing and must not hold
    the day open -- the priced row above shows the exclusion is not blanket."""
    game = _spent_house(GameConfig(), "locksmith")
    game.state.coins = 20
    game.state.shops.stock["locksmith"] = [
        {"id": "key", "kind": "resource", "grant": {"keys": 1}, "price": 0}]
    display = game.shop_stock()
    assert display[0]["affordable"] and not display[0]["sold_out"], \
        "scenario needs a row that is free and never sells out"

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert not _in_place_ids(game)


# ------------------------------------ what is deliberately NOT counted, and why

def test_reversible_panels_do_not_keep_the_day_alive():
    """The Utility Closet breaker, the Security setpoint and the Pump Room
    panel can all be worked and un-worked forever, so none of them may hold a
    day open. Counting a toggle is how a day never terminates at all."""
    for room_id, predicate in (
            ("utility_closet", "can_toggle_keycard_power"),
            ("security", "can_set_security_level"),
            ("pump_room", "can_set_pump_source"),
    ):
        game = _spent_house(GameConfig(door_locks=True), room_id)
        assert getattr(game, predicate)(), f"scenario needs a live {room_id} panel"

        game._check_termination()

        assert game.phase is Phase.TERMINAL, room_id
        assert not _in_place_ids(game), room_id


def test_the_shrine_offering_does_not_keep_the_day_alive():
    """Donating at the Shrine is undone by taking the offering back, so the
    pair is reversible however much each half looks like a purchase."""
    game = _outer_room_stand("shrine")
    game.state.coins = 50
    assert any(game.can_donate_shrine(b, d) for b in range(6) for d in range(4)), \
        "scenario needs an affordable blessing"

    assert not _in_place_ids(game)


def test_an_upgrade_disk_at_a_terminal_does_not_keep_the_day_alive():
    """``insert_disk`` returns False and consumes nothing when no slot is
    selectable, so ``can_insert_disk`` can answer True for the rest of the day
    however often it is taken -- exactly the shape the bound forbids."""
    game = _spent_house(GameConfig(), "office")
    game.state.special.office_spread_gold_used = True
    game.state.payroll_last_used["office_payroll"] = game.cfg.day
    _si.grant(game.state, game.registry, "upgrade_disk_vault_304", source="test")
    assert game.can_insert_disk(), "scenario needs a disk at a reader"

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert not _in_place_ids(game)


def test_the_scepter_and_the_axe_do_not_keep_the_day_alive():
    """Neither pays out today. The Royal Scepter only biases later drafts, and
    this check runs precisely when no draft is left; the Axe's three uses are
    save-scoped, so tomorrow serves it exactly as well."""
    game = _spent_house(GameConfig(), "office")
    game.state.special.office_spread_gold_used = True
    game.state.payroll_last_used["office_payroll"] = game.cfg.day
    _si.grant(game.state, game.registry, "royal_scepter", source="test")
    _si.grant(game.state, game.registry, "the_axe", source="test")
    assert game.can_activate_scepter(), "scenario needs an unspent Scepter"
    assert game.can_axe_room("attic"), "scenario needs a legal Axe target"

    game._check_termination()

    assert game.phase is Phase.TERMINAL
    assert not _in_place_ids(game)


def test_asking_whether_the_day_is_over_never_rolls_the_trade_graph():
    """Why trades are excluded, and it is not a taste call: ``trade_offers``
    is not a query -- its first call inside the Trading Post rolls the day's
    whole trade graph off the RNG and stores it on the state. The termination
    check runs after every single action, so counting trades would roll that
    graph at an arbitrary early moment and publish it through the observation.
    The predicate must leave it untouched; asking for real still rolls it."""
    game = _outer_room_stand("trading_post")
    _si.grant(game.state, game.registry, "compass", source="test")
    assert _shops._inside_trading_post(game), "scenario needs the player in the post"

    assert not game._in_place_action_available()
    assert not game.state.shops.trade_graph_rolled
    assert game.state.shops.trade_graph == {}

    assert game.trade_offers(), "scenario needs a trade the post would actually offer"
    assert game.state.shops.trade_graph_rolled


# ---------------------------------------- the policies can take what it counts

def test_a_scripted_policy_finishes_a_day_the_engine_holds_open():
    """The engine/policy contract. ``Game._in_place_actions`` is the single
    enumeration: the engine keeps the day alive while it yields anything and
    cli/policies.py drains that same generator, so an action the engine counts
    is always one a policy can take. Were the two to drift, this house would
    sit in NAVIGATE with a free locker underfoot instead of ending."""
    game = _spent_house(GameConfig(), "locker_room")
    rnd = random.Random(3)
    assert _in_place_ids(game), "scenario needs work the engine will hold the day open for"

    for _ in range(200):
        if game.phase is Phase.TERMINAL:
            break
        frontier_greedy(game, rnd)

    assert game.phase is Phase.TERMINAL
    assert not _in_place_ids(game)
    assert game.state.special.opened_containers[NORTH_CELL] > 0, "the lockers went unopened"


def test_no_episode_ends_with_free_work_left_on_the_table():
    """The same contract swept over whole episodes rather than one house: a
    policy may seal itself in, but while it still has a step in hand it must
    never concede a day with a zero-step action legal.

    Days that end AT zero steps are exempt and not a loophole: running out of
    steps is the unconditional hard stop (see the test above), so a Workshop
    bench still holding a recipe at 0 steps is a day that is genuinely over.
    Both counters guard against a vacuous sweep -- one for episodes that ever
    saw free work, one for episodes that actually reach the assertion.
    """
    episodes_with_free_work = 0
    episodes_checked = 0
    for seed in range(25):
        game = Game(GameConfig(), seed=seed)
        rnd = random.Random(seed)
        saw_free_work = False
        for _ in range(2000):
            if game.phase is Phase.TERMINAL:
                break
            saw_free_work = saw_free_work or bool(_in_place_ids(game))
            frontier_greedy(game, rnd)
        assert game.phase is Phase.TERMINAL, f"seed {seed} never terminated"
        episodes_with_free_work += int(saw_free_work)
        if game.state.steps <= 0:
            continue
        episodes_checked += 1
        game.phase = Phase.NAVIGATE          # every predicate gates on NAVIGATE
        assert not _in_place_ids(game), f"seed {seed} ended with free work left"

    assert episodes_with_free_work > 0, "the sweep never produced an in-place action"
    assert episodes_checked >= 5, "the sweep never reached the assertion it exists for"
