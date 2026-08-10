"""Foyer / Spare Foyer: forces every Hallway-category room's doors unlocked.

Every test places rooms directly via Game._place_room, as the other room
tests do, and forces a guaranteed-lock cell (rank 8<->9, E-W within rank 8:
110% base chance -- always locks regardless of seed, per data/locks.json)
so the roll needs no seed search. Security doors are exercised by forcing a
segment straight into DOOR_SECURITY, the same helper pattern test_locks.py
uses, since the security-door roll is independently probabilistic on top of
the lock roll and would need its own seed search otherwise.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY, segment_key


def _game(registry) -> Game:
    return Game(GameConfig(), seed=1, registry=registry)


def _force_state(g: Game, cell: int, d: int, state: int) -> None:
    """Overwrite a doorway segment's state directly, bumping door_version."""
    g.state.door_state[segment_key(cell, d)] = state
    g.state.door_version += 1


def test_hallway_drafted_before_foyer_becomes_unlocked(registry):
    """A Hallway placed before the Foyer, holding both a locked and a
    security doorway, has both forced open the moment the Foyer lands --
    "regardless of if they were drafted before ... the Foyer"."""
    g = _game(registry)
    hallway = g.registry.by_id["hallway"]
    g._place_room(hallway, 36, E | W)  # rank 8, col 1
    _force_state(g, 36, E, DOOR_LOCKED)
    _force_state(g, 36, W, DOOR_SECURITY)

    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 10, E | W)  # rank 3, col 0 -- unrelated cell

    assert g.door_state_of(36, E) == DOOR_OPEN
    assert g.door_state_of(36, W) == DOOR_OPEN


def test_hallway_drafted_after_foyer_becomes_unlocked(registry):
    """A Hallway placed after the Foyer never shows a locked door in the
    first place: comparing against the same placement without a Foyer on the
    estate proves the roll really would have locked here, so the "after"
    case is not passing vacuously."""
    without_foyer = _game(registry)
    hallway_id = "hallway"
    without_foyer._place_room(without_foyer.registry.by_id[hallway_id], 36, E | W)
    assert without_foyer.door_state_of(36, E) == DOOR_LOCKED, (
        "setup: rank 8 E-W is a guaranteed-lock cell"
    )

    g = _game(registry)
    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 10, E | W)
    g._place_room(g.registry.by_id[hallway_id], 36, E | W)

    assert g.door_state_of(36, E) == DOOR_OPEN
    assert g.door_state_of(36, W) == DOOR_OPEN


def test_foyer_own_doors_are_unlocked(registry):
    """The Foyer's own doors are unlocked too -- "includes the Foyer
    itself" -- even though they were freshly rolled (guaranteed-locked) in
    the very same placement that arms the effect."""
    g = _game(registry)
    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 36, E | W)  # rank 8 E-W: guaranteed-lock cell

    assert g.door_state_of(36, E) == DOOR_OPEN
    assert g.door_state_of(36, W) == DOOR_OPEN


def test_non_hallway_room_locked_door_is_unaffected(registry):
    """A non-Hallway room's locked door is left alone: the Foyer's sweep is
    scoped to category "hallway" only."""
    g = _game(registry)
    closet = g.registry.by_id["closet"]
    g._place_room(closet, 36, E)  # rank 8 E: guaranteed-lock cell
    assert g.door_state_of(36, E) == DOOR_LOCKED, "setup: guaranteed lock"

    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 10, E | W)

    assert g.door_state_of(36, E) == DOOR_LOCKED


def test_second_foyer_has_no_additional_effect(registry):
    """A second Foyer is redundant: re-sweeping after everything is already
    unlocked changes nothing and raises nothing."""
    g = _game(registry)
    hallway = g.registry.by_id["hallway"]
    g._place_room(hallway, 36, E | W)
    _force_state(g, 36, E, DOOR_LOCKED)

    foyer = g.registry.by_id["foyer"]
    g._place_room(foyer, 10, E | W)
    assert g.door_state_of(36, E) == DOOR_OPEN

    spare_foyer = g.registry.by_id["spare_foyer__ix137"]
    g._place_room(spare_foyer, 15, E | W)  # rank 4, col 0

    assert g.door_state_of(36, E) == DOOR_OPEN
    assert g.door_state_of(10, E) == DOOR_OPEN
    assert g.door_state_of(15, E) == DOOR_OPEN
