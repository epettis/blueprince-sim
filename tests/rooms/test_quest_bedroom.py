"""Quest Bedroom: the +10 steps grant and the Antechamber allowance bonus.

The Antechamber bonus is armed by entering a Quest Bedroom and paid on the
next Antechamber arrival, in that order -- entering the Antechamber first
pays nothing until the player returns. See tests/rooms/test_secret_garden.py
for the _place_at/_enter_at pattern this file copies.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game
from blueprince_sim.engine.grid import N, S


def _game(*, registry=None, seed: int = 1) -> Game:
    """Fresh game with locks/levers off, so a plain doorway is enough to walk
    into the Antechamber, and luck floored so filler rooms' additional_max
    rolls cannot contaminate step assertions.
    """
    cfg = GameConfig(antechamber_levers=False, door_locks=False, starting_steps=100)
    g = Game(cfg, seed=seed, **({"registry": registry} if registry is not None else {}))
    g.state.luck = 0
    return g


def _place_at(g: Game, room_id: str, cell: int, mask: int) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = mask
    g.state.entered[cell] = False
    g.room_cells[room_id] = cell
    g.placed_ids.add(room_id)
    g.state.door_version += 1


def _enter_at(g: Game, cell: int) -> None:
    """Teleport the player to cell and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)
    g.state.door_version += 1


# The Antechamber's south neighbor (rank 8, center column). A corridor placed
# here with a north-facing door is enough to walk into the Antechamber (N) and
# back out (S) via the real Game.move(), which is what fires Hook.ON_ARRIVE.
NEIGHBOR_CELL = 37


def _place_neighbor(g: Game) -> None:
    """Place a corridor adjoining the Antechamber and stand the player there."""
    _place_at(g, "corridor", NEIGHBOR_CELL, N)
    g.state.entered[NEIGHBOR_CELL] = True
    g.state.pos = NEIGHBOR_CELL


def test_entering_quest_bedroom_grants_ten_steps(registry):
    """Entering the Quest Bedroom grants the same +10 steps the base Guest
    Bedroom carries, since the variant record repeats that data effect.
    """
    g = _game(registry=registry)
    qb_cell = 5
    _place_at(g, "quest_bedroom__ix71", qb_cell, 0)
    before = g.state.steps

    _enter_at(g, qb_cell)

    assert g.state.steps == before + 10


def test_quest_bedroom_then_antechamber_pays_allowance(registry):
    """Entering the Quest Bedroom and then genuinely arriving at the
    Antechamber (via Game.move, which fires Hook.ON_ARRIVE) raises allowance
    by exactly 2.
    """
    g = _game(registry=registry)
    qb_cell = 5
    _place_at(g, "quest_bedroom__ix71", qb_cell, 0)
    _place_neighbor(g)

    _enter_at(g, qb_cell)
    g.state.pos = NEIGHBOR_CELL
    before = g.state.allowance
    g.move(N)  # real movement into the Antechamber

    assert g.state.pos == ANTECHAMBER_CELL
    assert g.state.allowance == before + 2


def test_antechamber_before_quest_bedroom_pays_nothing_until_return(registry):
    """Order matters: arriving at the Antechamber before any Quest Bedroom has
    been entered pays nothing. Only entering a Quest Bedroom and then
    returning to the Antechamber pays -- the card text alone, without the
    ordering rule, would pay on the first arrival too.
    """
    g = _game(registry=registry)
    qb_cell = 5
    _place_at(g, "quest_bedroom__ix71", qb_cell, 0)
    _place_neighbor(g)

    before = g.state.allowance
    g.move(N)  # arrive at the Antechamber first, before any Quest Bedroom
    assert g.state.allowance == before

    g.move(S)  # step back onto the neighbor cell
    _enter_at(g, qb_cell)  # now arm the effect
    g.state.pos = NEIGHBOR_CELL
    g.move(N)  # return to the Antechamber, now armed

    assert g.state.allowance == before + 2


def test_prior_antechamber_visit_does_not_block_the_payout(registry):
    """A prior Antechamber visit does not gate the payout: the second arrival
    at an already-entered Antechamber still pays once the Quest Bedroom has
    been entered in between. This is why the payout hangs off Hook.ON_ARRIVE
    (fires on every arrival) rather than Hook.ON_ENTER (gated on first entry
    only) -- an ON_ENTER implementation would never fire on this second
    arrival and this test would catch it.
    """
    g = _game(registry=registry)
    qb_cell = 5
    _place_at(g, "quest_bedroom__ix71", qb_cell, 0)
    _place_neighbor(g)

    g.move(N)  # first arrival marks the Antechamber entered
    assert g.state.entered[ANTECHAMBER_CELL]
    g.move(S)

    _enter_at(g, qb_cell)
    g.state.pos = NEIGHBOR_CELL
    before = g.state.allowance
    g.move(N)  # second arrival, at an already-entered Antechamber

    assert g.state.allowance == before + 2


def test_two_quest_bedrooms_do_not_stack_the_payout(registry):
    """Two Quest Bedrooms plus two Antechamber arrivals pay 2 allowance total,
    not 4 -- a second Quest Bedroom does not re-arm a payout already made.
    """
    g = _game(registry=registry)
    qb_cell_a, qb_cell_b = 5, 7
    _place_at(g, "quest_bedroom__ix71", qb_cell_a, 0)
    _place_at(g, "quest_bedroom__ix71", qb_cell_b, 0)
    _place_neighbor(g)

    _enter_at(g, qb_cell_a)
    g.state.pos = NEIGHBOR_CELL
    before = g.state.allowance
    g.move(N)  # first arrival: pays 2
    assert g.state.allowance == before + 2
    g.move(S)

    _enter_at(g, qb_cell_b)  # a second Quest Bedroom, entered the same day
    g.state.pos = NEIGHBOR_CELL
    g.move(N)  # second arrival: must not pay again

    assert g.state.allowance == before + 2


def test_quest_bedroom_placed_but_not_entered_pays_nothing(registry):
    """Merely drafting/placing a Quest Bedroom without walking into it does
    not arm the effect: arriving at the Antechamber afterward pays nothing.
    """
    g = _game(registry=registry)
    qb_cell = 5
    _place_at(g, "quest_bedroom__ix71", qb_cell, 0)
    _place_neighbor(g)

    before = g.state.allowance
    g.move(N)  # arrive at the Antechamber; the Quest Bedroom was never entered

    assert g.state.allowance == before
