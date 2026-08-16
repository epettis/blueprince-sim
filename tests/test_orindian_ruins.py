"""Tests for the Orindian Ruins: reachability as a travel destination, and
earning the permanent Throne Room blueprint.

private_drive, blackbridge_grotto and orindian_ruins are offered as travel
destinations once flipped to modelled: true (data/areas.json), and reaching
Orindian Ruins sets GameConfig.throne_room_blueprint so the Throne Room joins
the draft pool. This file follows the exact carry-over shape used by
treasure_trove_blackprint (env/multiday.py, engine/shops.py::carryover): the
discovery is recorded on GameState, never written back to GameConfig (one
config object is shared by every episode of a trainer worker).

The route from Blackbridge Grotto to Orindian Ruins is gated by
``three_microchips``: 2 held microchips plus the Grotto's own in-place chip
(the ``grotto_chip_in_place`` counts_flag) satisfy it -- see
tests/test_areas.py for the gate's own dedicated coverage. The route from
Private Drive to Blackbridge Grotto crosses two real ``kind=flag`` gates
(docs/areas.md's "Blackbridge Grotto gate"): ``lab_steam_and_power``, requiring
a Laboratory powered at least once (docs/power.md), AND ``lab_visited``,
requiring the Laboratory entered at least once -- either on this or any earlier
day. Every test below that crosses this route powers and enters the Laboratory
directly via ``_power_and_enter_laboratory`` (deterministic setup, not a draft)
before travelling.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import eligible_pool
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain


def _power_and_enter_laboratory(g: Game) -> None:
    """Place, power and enter the Laboratory directly, satisfying both gates on
    private_drive -> blackbridge_grotto without going through a draft.

    Cells 12 and 17 (rank 3 and rank 4, center column) are free in every test
    below: none place anything else there, and both are clear of
    ENTRANCE_CELL/ANTECHAMBER_CELL. The two N|S masks form a door pair across
    cell 12's north side, which is what carries power from the Boiler Room into
    the Laboratory (engine/power.py).

    ``_enter`` rather than ``_place_room(entered=True)``: the visit latch is the
    room's own ON_ENTER hook (effects/rooms/laboratory.py), and only ``_enter``
    fires room hooks.
    """
    g._place_room(g.registry.by_id["laboratory"], 12, N | S)
    g._place_room(g.registry.by_id["boiler_room"], 17, N | S)
    g._enter(12)


# ---------------------------------------------------------------------------
# 1. Orindian Ruins (and its route) are offered destinations
# ---------------------------------------------------------------------------

def test_orindian_ruins_is_offered_as_a_travel_destination_with_two_chips(registry):
    """With two held microchips (the Grotto's own chip counts as the third)
    and enough steps, TRAVEL_BASE + index(orindian_ruins) is legal from day 1.

    Before the fix, private_drive/blackbridge_grotto/orindian_ruins all
    carried modelled: false, so this action stayed masked False even though
    the route (house -> grounds -> private_drive -> blackbridge_grotto ->
    orindian_ruins, 4 steps) was always reachable -- the gate opens but is
    never offered is exactly the bug this test pins shut. Reachability itself
    needs the Laboratory powered and entered at least once too (the
    lab_steam_and_power and lab_visited gates, docs/areas.md), so the setup
    does both directly.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _power_and_enter_laboratory(g)

    assert g.area_route_cost("orindian_ruins") == (4, "house")

    node_ids = A._build_area_node_ids(g.registry)
    mask = A.action_mask(g)
    for dest in ("private_drive", "blackbridge_grotto", "orindian_ruins"):
        i = node_ids.index(dest)
        assert mask[A.TRAVEL_BASE + i], f"{dest} must be offered as a travel destination"


def test_orindian_ruins_not_offered_without_two_held_chips(registry):
    """Without at least 2 held microchips, the three_microchips gate stays
    closed (2 held + the in-place Grotto chip is the minimum satisfying
    combination) and orindian_ruins must not be offered as a destination,
    even though the earlier legs of the route (private_drive,
    blackbridge_grotto) remain reachable once the Laboratory is entered.
    """
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    _power_and_enter_laboratory(g)

    node_ids = A._build_area_node_ids(g.registry)
    mask = A.action_mask(g)
    for dest in ("private_drive", "blackbridge_grotto"):
        i = node_ids.index(dest)
        assert mask[A.TRAVEL_BASE + i], f"{dest} must still be offered"
    i = node_ids.index("orindian_ruins")
    assert not mask[A.TRAVEL_BASE + i]


# ---------------------------------------------------------------------------
# 2. Arriving sets the flag on STATE, never on the shared config
# ---------------------------------------------------------------------------

def test_arriving_at_orindian_ruins_sets_state_not_config(registry):
    """travel_to("orindian_ruins") records throne_room_blueprint on GameState
    only. Same shape as treasure_trove_blackprint: the config object is
    shared across every episode of a trainer worker, so writing the
    discovery there would leak the unlock into later, unrelated episodes.
    """
    cfg = GameConfig()
    g = Game(cfg, seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _power_and_enter_laboratory(g)

    g.travel_to("orindian_ruins")

    assert g.state.area == "orindian_ruins"
    assert g.state.throne_room_blueprint is True
    assert cfg.throne_room_blueprint is False, "the shared config must not be mutated"


# ---------------------------------------------------------------------------
# 3. carryover() reports it; DayChain carries it into next_config(), and the
#    pool gate admits throne_room on the following day
# ---------------------------------------------------------------------------

def test_carryover_reports_throne_room_blueprint_after_arrival(registry):
    """shops.carryover()["throne_room_blueprint"] is True once Orindian Ruins
    has been reached."""
    g = Game(GameConfig(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _power_and_enter_laboratory(g)
    g.travel_to("orindian_ruins")

    report = carryover(g)
    assert report["throne_room_blueprint"] is True


def test_throne_room_blueprint_admits_throne_room_to_the_pool_the_following_day(registry):
    """The full lifecycle: arrive -> carryover -> DayChain.advance() ->
    next_config().throne_room_blueprint is True -> decks.py::eligible_pool
    for that config includes throne_room, where a config without the flag
    (or without studio_additions) does not.
    """
    cfg = GameConfig(starting_steps=50)
    chain = DayChain(cfg)

    g = Game(chain.next_config(), seed=1, registry=registry)
    g.state.steps = 50
    g.state.inventory["microchip"] = 2
    _power_and_enter_laboratory(g)
    g.travel_to("orindian_ruins")
    chain.advance(carryover(g))

    next_cfg = chain.next_config()
    assert next_cfg.throne_room_blueprint is True

    pool_ids = {r.id for r in eligible_pool(registry, next_cfg)}
    assert "throne_room" in pool_ids

    pool_without = {r.id for r in eligible_pool(registry, GameConfig())}
    assert "throne_room" not in pool_without
