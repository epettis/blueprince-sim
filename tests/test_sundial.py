"""The Apple Orchard sundial: an ignition target that unlocks the Satellite
Dish (phase 6a of the Microchip branch).

This is the UNLOCK only -- the data packet the Satellite Dish grants (8
triggers + 8 effects in engine/experiments.py's packet pool) is a later PR;
engine/experiments.py's or_packet stays permanently False here, same as
before this file existed.

The sundial needs THREE held microchips plus any ignition tool (torch or
burning_glass -- the wiki says "an ignition tool" without naming one, and the
tools list already treats the two as interchangeable everywhere else). Two
sources grant a chip automatically as the day is played (Entrance Hall vase +
West Path doorstep, engine/shops.py::on_day_start/on_doorstep), capping
automatic holding at two; the third sits in the Blackbridge Grotto's pedestal
and only reaches inventory when the player deliberately takes it
(TAKE_GROTTO_CHIP_ACTION, engine/special_items.py::take_grotto_chip). Tests
below at the two-chip ceiling (before the pedestal chip is taken) pin the
sundial as unlightable; tests/test_grotto_chip.py covers taking the pedestal
chip and the sundial becoming lightable afterward.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain


def _at_apple_orchard(g: Game) -> None:
    """Walk ``g`` to apple_orchard via the real area graph (house -> ... -> orchard)."""
    g.state.steps = 50
    g.travel_to("apple_orchard")
    assert g.state.area == "apple_orchard", "setup must actually reach apple_orchard"


# --------------------------------------------------------------------- 1: masked legal


def test_light_action_masked_legal_with_three_chips_and_a_tool(registry):
    """LIGHT_ACTION is legal at apple_orchard when holding 3 microchips + a torch.

    Proves the action is reachable through the real masking path (action_mask),
    not just through the lower-level can_light() predicate.
    """
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 3
    g.state.inventory["torch"] = 1

    assert si.can_light(g)
    mask = A.action_mask(g)
    assert mask[A.LIGHT_ACTION], "LIGHT_ACTION must be legal with 3 microchips + a torch"


def test_light_action_masked_legal_with_burning_glass_too(registry):
    """The Burning Glass lights the sundial just as the Torch does (either
    ignition tool works: the wiki says "an ignition tool" without naming one,
    and ignition.tools already treats torch/burning_glass as interchangeable
    for every other target)."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 3
    g.state.inventory["burning_glass"] = 1

    assert si.can_light(g)


# ------------------------------------------------------------- 2: lighting sets the flag


def test_lighting_the_sundial_sets_satellite_dish_unlocked(registry):
    """apply_action(LIGHT_ACTION) at apple_orchard with 3 chips + a tool sets
    GameState.satellite_dish_unlocked and records apple_orchard as lit."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 3
    g.state.inventory["torch"] = 1

    A.apply_action(g, A.LIGHT_ACTION)

    assert g.state.satellite_dish_unlocked is True
    assert "apple_orchard" in g.state.special.lit_targets


# ------------------------------------------------------------------ 3: carries a day


def test_satellite_dish_unlock_carries_to_the_next_day_through_a_daychain(registry):
    """Full lifecycle: light the sundial -> carryover() -> DayChain.advance() ->
    next_config().satellite_dish_unlocked is True on the following day.

    Same shape as test_orindian_ruins.py's throne_room_blueprint lifecycle test.
    """
    cfg = GameConfig(special_items=True)
    chain = DayChain(cfg)

    g = Game(chain.next_config(), seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 3
    g.state.inventory["torch"] = 1
    A.apply_action(g, A.LIGHT_ACTION)
    assert g.state.satellite_dish_unlocked is True

    report = carryover(g)
    assert report["satellite_dish_unlocked"] is True
    chain.advance(report)

    next_cfg = chain.next_config()
    assert next_cfg.satellite_dish_unlocked is True


def test_arriving_at_the_sundial_sets_state_not_the_shared_config(registry):
    """Lighting the sundial records the flag on GameState only -- the shared
    GameConfig object (reused across every episode of a trainer worker) must
    not be mutated, same shape as throne_room_blueprint/treasure_trove_blackprint."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 3
    g.state.inventory["torch"] = 1

    A.apply_action(g, A.LIGHT_ACTION)

    assert g.state.satellite_dish_unlocked is True
    assert cfg.satellite_dish_unlocked is False, "the shared config must not be mutated"


# --------------------------------------------------------------- 4: not legal with two


def test_light_action_not_legal_with_only_two_chips(registry):
    """LIGHT_ACTION stays masked False with only 2 held microchips: the
    sundial needs three, and the engine never grants a third to hold."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    _at_apple_orchard(g)
    g.state.inventory["microchip"] = 2
    g.state.inventory["torch"] = 1

    assert not si.can_light(g)
    mask = A.action_mask(g)
    assert not mask[A.LIGHT_ACTION], "LIGHT_ACTION must stay illegal with only 2 microchips"


# ------------------------------------------------------ 5: reachability of the location

def test_apple_orchard_itself_is_reachable_and_offered(registry):
    """apple_orchard is offered as a travel destination and its route
    (house -> ... -> apple_orchard) is affordable within the default step
    budget -- standing at the sundial at all is not the blocked part of this
    feature; holding three microchips simultaneously is (see the module
    docstring and test_sundial_not_reachable_with_the_engines_microchip_ceiling)."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    g.state.steps = 50

    assert g.area_route_cost("apple_orchard") is not None

    node_ids = A._build_area_node_ids(g.registry)
    mask = A.action_mask(g)
    i = node_ids.index("apple_orchard")
    assert mask[A.TRAVEL_BASE + i], "apple_orchard must be offered as a travel destination"


def test_sundial_not_reachable_with_the_engines_microchip_ceiling(registry):
    """The two automatic microchip sources (Entrance Hall vase, West Path
    doorstep dig) cap holding at 2 by themselves -- the third held chip only
    comes from deliberately taking the Blackbridge Grotto pedestal chip
    (TAKE_GROTTO_CHIP_ACTION, see tests/test_grotto_chip.py), not from these
    two. So a player who has only discovered the vase and doorstep sources
    still cannot satisfy the sundial's requires_items."""
    from blueprince_sim.engine import shops as shops_mod

    cfg = GameConfig(
        special_items=True,
        entrance_vase_broken=True,   # both permanent discovery flags earned
        outer_chip_dug=True,
    )
    g = Game(cfg, seed=1, registry=registry)
    # Game.reset() already calls shops.on_day_start(); on_doorstep() fires when
    # the player reaches the outer-area doorstep, simulated directly here rather
    # than walking the whole route, since the ceiling (not the walk) is what
    # this test pins.
    shops_mod.on_doorstep(g)
    assert g.state.inventory.get("microchip", 0) == 2, (
        "the engine's microchip ceiling must be exactly 2 held at once"
    )
