"""Vestibule: hallway-category movement rules reach it, and it closes and
rerolls its own lock every time it is entered.

special_items.py::move_step_cost waives the step cost of a move between two
"hallway"-category rooms while a Hall Pass is held. Vestibule could never
satisfy either side of that check while its category was the pool name
"studio_addition" instead of "hallway".

The lock-reroll half fires Hook.ON_ARRIVE directly (via effects.fire), the
same call Game.move and Game.travel_to already make unconditionally on
every landing -- this reproduces exactly what a real walk into the room
triggers without needing to build a walkable floorplan around it.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.effects import Hook, fire
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import DIRS, E, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN


def test_vestibule_qualifies_for_hall_pass_free_move(registry):
    """move_step_cost's Hall Pass shortcut only fires hallway-to-hallway
    (special_items.py:773). Vestibule now qualifies as "hallway" rather than
    the pool name "studio_addition", so a Hall Pass move from another
    hallway room into it costs 0 steps instead of the normal 1."""
    g = Game(GameConfig(special_items=True), seed=0)
    si.grant(g.state, g.registry, "hall_pass", source="test")

    corridor = registry.by_id["corridor"]  # a pre-existing, correctly-tagged hallway room
    vestibule = registry.by_id["vestibule"]
    assert vestibule.category == "hallway"
    g.state.grid[7] = corridor.idx

    cost = si.move_step_cost(g, 7, S, vestibule)
    assert cost == 0


def test_vestibule_move_costs_a_step_without_hall_pass(registry):
    """Without a Hall Pass, the same hallway-to-hallway move costs the normal
    1 step -- the free move is the item's doing, not an unconditional
    category shortcut."""
    g = Game(GameConfig(special_items=True), seed=0)

    corridor = registry.by_id["corridor"]
    vestibule = registry.by_id["vestibule"]
    g.state.grid[7] = corridor.idx

    cost = si.move_step_cost(g, 7, S, vestibule)
    assert cost == 1


# --------------------------------------------------------------- lock reroll

VESTIBULE_CELL = 22  # rank 5, center column -- clear of the Entrance Hall/Antechamber


def _game(registry, seed: int = 1, **cfg) -> Game:
    return Game(GameConfig(**cfg), seed=seed, registry=registry)


def _place_vestibule(g: Game, cell: int = VESTIBULE_CELL) -> int:
    vestibule = g.registry.by_id["vestibule"]
    g._place_room(vestibule, cell, vestibule.door_mask)
    return cell


def _arrive(g: Game, cell: int) -> None:
    """Fire ON_ARRIVE for the room at ``cell``, as Game.move does post-arrival."""
    g.state.pos = cell
    fire(g, g.registry.rooms[g.state.grid[cell]], Hook.ON_ARRIVE)


def test_arrival_locks_exactly_one_door_and_opens_the_rest(registry):
    """"One of the four doors becomes locked at random, and the other three
    become unlocked" -- checked against the Vestibule's own placed door mask
    (all four directions, since it is a cross-layout room)."""
    g = _game(registry)
    cell = _place_vestibule(g)
    _arrive(g, cell)

    states = [g.door_state_of(cell, d) for d in DIRS]
    assert states.count(DOOR_LOCKED) == 1
    assert states.count(DOOR_OPEN) == 3


def test_reentry_rerolls_which_door_is_locked(registry):
    """Re-entering retriggers the effect: swept across seeds, a later arrival
    eventually locks a different doorway than the first did, and the
    previously-locked doorway ends up open -- "regardless of which doors
    were previously locked or unlocked"."""
    for seed in range(30):
        g = _game(registry, seed=seed)
        cell = _place_vestibule(g)
        _arrive(g, cell)
        first_locked = next(d for d in DIRS if g.door_state_of(cell, d) == DOOR_LOCKED)

        _arrive(g, cell)
        second_locked = next(d for d in DIRS if g.door_state_of(cell, d) == DOOR_LOCKED)

        if first_locked != second_locked:
            assert g.door_state_of(cell, first_locked) == DOOR_OPEN
            return
    raise AssertionError("expected at least one seed where re-entry changes the locked door")


def test_foyer_present_keeps_all_four_doors_open(registry):
    """"The effect of the Foyer overrides the Vestibule's, forcing all four
    doors to remain unlocked" -- even on arrival, which still runs the
    reroll logic but opens every doorway instead of locking one."""
    g = _game(registry)
    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 10, E | W)
    cell = _place_vestibule(g)

    _arrive(g, cell)

    assert all(g.door_state_of(cell, d) == DOOR_OPEN for d in DIRS)
