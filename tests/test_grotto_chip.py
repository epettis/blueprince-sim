"""Taking the Blackbridge Grotto pedestal's microchip (TAKE_GROTTO_CHIP_ACTION).

The engine already modelled the pedestal chip as an in-place contributor to
the three_microchips gate (GameState.grotto_chip_taken, Game._gate_ctx), but
nothing could ever set it True -- no action existed to take the chip out of
the pedestal. This file exercises the action end to end: masking, granting,
the one-shot-per-day rule, the Ruins gate staying open while all three chips
are held (test_areas.py pins the gate-logic truth table directly; this file
proves the same row through real gameplay), the Apple Orchard sundial
becoming lightable for the first time, and the next-day respawn.

Reaching the Grotto at all needs the Laboratory entered too (the lab_visited
gate, alongside the still-stub lab_steam_and_power -- see docs/areas.md's
"Blackbridge Grotto gate"); every setup below enters it directly via
``_enter_laboratory``.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain


def _enter_laboratory(g: Game) -> None:
    """Place and enter the Laboratory directly, satisfying the ``lab_visited``
    gate on private_drive -> blackbridge_grotto without going through a draft.

    Cell 12 (rank 3, center column) is free in every test below.
    """
    g._place_room(g.registry.by_id["laboratory"], 12, N | S, entered=True)


def _at_grotto_with_two_chips(registry) -> Game:
    """A Game standing at blackbridge_grotto holding 2 microchips (the vase +
    West Path ceiling), pedestal chip still in place."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _enter_laboratory(g)
    g.travel_to("blackbridge_grotto")
    assert g.state.area == "blackbridge_grotto", "setup must actually reach the Grotto"
    return g


# --------------------------------------------------------------- 1: masked legal


def test_take_grotto_chip_masked_legal_at_grotto_with_chip_in_place(registry):
    """TAKE_GROTTO_CHIP_ACTION is legal through the real masking path
    (action_mask) once the player stands at blackbridge_grotto with the
    pedestal chip still in place."""
    g = _at_grotto_with_two_chips(registry)

    assert g.can_take_grotto_chip()
    mask = A.action_mask(g)
    assert mask[A.TAKE_GROTTO_CHIP_ACTION], "must be legal at the Grotto with the chip in place"


def test_take_grotto_chip_not_legal_off_the_grotto_node(registry):
    """Standing anywhere else off-grid, the action stays masked False -- it is
    scoped to the blackbridge_grotto node specifically."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.travel_to("grounds")

    assert not g.can_take_grotto_chip()
    mask = A.action_mask(g)
    assert not mask[A.TAKE_GROTTO_CHIP_ACTION]


# ------------------------------------------------------- 2: granting + one-shot


def test_taking_the_chip_grants_it_sets_the_flag_and_blocks_a_second_take(registry):
    """apply_action(TAKE_GROTTO_CHIP_ACTION) grants one microchip via the
    ordinary special_items.grant() path, flips grotto_chip_taken, and the
    action then masks False -- no double-take of the same pedestal today."""
    g = _at_grotto_with_two_chips(registry)

    A.apply_action(g, A.TAKE_GROTTO_CHIP_ACTION)

    assert g.state.inventory.get("microchip", 0) == 3
    assert g.state.grotto_chip_taken is True
    assert not g.can_take_grotto_chip()
    mask = A.action_mask(g)
    assert not mask[A.TAKE_GROTTO_CHIP_ACTION], "the pedestal cannot be taken twice in one day"


# --------------------------------------------- 3: the Ruins gate stays open (row 2)


def test_taking_the_chip_does_not_shut_the_ruins_gate_while_holding_all_three(registry):
    """Row 2 of the owner's truth table: 2 held + the pedestal in place is 3
    for the three_microchips gate; after taking the pedestal chip, 3 held +
    0 in place is still 3 -- orindian_ruins must stay offered as a travel
    destination across the take, proved through the real action_mask rather
    than a hand-built GateContext (see tests/test_areas.py for that)."""
    g = _at_grotto_with_two_chips(registry)
    node_ids = A._build_area_node_ids(g.registry)
    i = node_ids.index("orindian_ruins")

    mask_before = A.action_mask(g)
    assert mask_before[A.TRAVEL_BASE + i], "2 held + pedestal in place must already satisfy the gate"

    A.apply_action(g, A.TAKE_GROTTO_CHIP_ACTION)

    mask_after = A.action_mask(g)
    assert mask_after[A.TRAVEL_BASE + i], "3 held chips alone must still satisfy the gate"


# ------------------------------------------------ 4: the sundial becomes lightable


def test_sundial_becomes_lightable_after_taking_the_grotto_chip(registry):
    """The point of the feature: before taking the pedestal chip, holding
    only 2 microchips, LIGHT_ACTION is illegal at apple_orchard even with a
    torch held. After walking to the Grotto and taking its chip (3rd held),
    walking on to apple_orchard makes LIGHT_ACTION legal -- proved through
    action_mask on a single continuous playthrough, not synthetic state."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    g.state.inventory["torch"] = 1
    _enter_laboratory(g)

    g.travel_to("apple_orchard")
    mask_before = A.action_mask(g)
    assert not mask_before[A.LIGHT_ACTION], "2 held chips must not be enough to light the sundial"

    g.travel_to("blackbridge_grotto")
    A.apply_action(g, A.TAKE_GROTTO_CHIP_ACTION)
    assert g.state.inventory["microchip"] == 3

    g.travel_to("apple_orchard")
    mask_after = A.action_mask(g)
    assert mask_after[A.LIGHT_ACTION], "3 held chips + a torch must light the sundial"


# ------------------------------------------------------- 5: next-day respawn


def test_grotto_chip_respawns_the_next_day_through_a_daychain(registry):
    """grotto_chip_taken carries no _CARRYOVER_KEYS entry and no GameConfig
    field, so a DayChain never carries the taken-ness forward: the next
    day's Game starts with the flag False and the action legal again at the
    Grotto, even though today's carryover() report does not mention it.

    lab_visited is ALSO day-scoped (open_tasks.md 37): tomorrow's fresh Game
    needs its own Laboratory entry to reach the Grotto again, same as today's.
    """
    cfg = GameConfig()
    chain = DayChain(cfg)

    g = Game(chain.next_config(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _enter_laboratory(g)
    g.travel_to("blackbridge_grotto")
    A.apply_action(g, A.TAKE_GROTTO_CHIP_ACTION)
    assert g.state.grotto_chip_taken is True

    report = carryover(g)
    assert "grotto_chip_taken" not in report
    chain.advance(report)

    next_cfg = chain.next_config()
    assert not hasattr(next_cfg, "grotto_chip_taken")

    tomorrow = Game(next_cfg, seed=2, registry=registry)
    assert tomorrow.state.grotto_chip_taken is False
    tomorrow.state.steps = 50
    _enter_laboratory(tomorrow)
    tomorrow.travel_to("blackbridge_grotto")
    assert tomorrow.can_take_grotto_chip(), "the pedestal chip must be back in place the next day"
