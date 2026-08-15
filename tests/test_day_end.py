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

from blueprince_sim.config import GameConfig
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
