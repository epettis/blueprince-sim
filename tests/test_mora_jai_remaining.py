"""The five remaining Mora Jai allowance boxes: Tomb, Lost & Found, Tunnel,
Throne Room and the Underpass.

Each holds a one-time +2 Allowance Token, the same shape as the five sources
landed earlier (Cloister, Master Bedroom, Solarium, Trading Post, Closed
Exhibit -- see tests/test_allowance.py) and the eight Sigil Chamber boxes.
Four are ordinary rooms and use ``guaranteed_in``, fired from
``special_items.py::on_enter``. The Underpass is an off-grid area node with
no rooms.json record, so it is granted from ``on_area_arrival``, called from
``Game.travel_to`` -- the same mechanism the Abandoned Mine's Upgrade Disk
and the two off-grid Sanctum Key sources use.

Tests drive the real DayChain carryover path for the cross-day claims, since
Game.reset() alone does not apply carryover.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env.multiday import DayChain
from luck_utils import suppress_luck

# room id -> its dedicated Allowance Token item id
ROOM_TOKENS = {
    "tomb": "allowance_token_tomb",
    "lost_and_found": "allowance_token_lost_and_found",
    "tunnel": "allowance_token_tunnel",
    "throne_room": "allowance_token_throne_room",
}


def _place(state, registry, room_id: str, cell: int) -> None:
    """Put room_id on the grid at cell without going through the draft pipeline."""
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


# ---------------------------------------------------------------------------
# The four rooms: guaranteed_in pays +2 once, gated across days
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("room_id,token_id", sorted(ROOM_TOKENS.items()))
def test_room_token_pays_once_and_not_on_a_later_day(registry, room_id, token_id):
    """Each room's Mora Jai box pays +2 allowance on first entry, and a
    second entry on a LATER day (after the source id is carried across via
    collected_allowance_tokens) pays nothing further."""
    room = registry.by_id[room_id]

    # Day 1: first entry pays out.
    g1 = Game(GameConfig(special_items=True), seed=1, registry=registry)
    suppress_luck(g1)
    _place(g1.state, g1.registry, room_id, 10)
    si.on_enter(g1, room, 10)
    assert g1.state.allowance == 2

    carry = carryover(g1)
    assert token_id in carry["collected_allowance_tokens"]

    # Day 2: the carried config gates the same source id out.
    day2_cfg = GameConfig(
        special_items=True,
        allowance=carry["allowance"],
        collected_allowance_tokens=frozenset(carry["collected_allowance_tokens"]),
    )
    g2 = Game(day2_cfg, seed=2, registry=registry)
    suppress_luck(g2)
    assert g2.state.allowance == 2  # carried total, no new gain yet

    _place(g2.state, g2.registry, room_id, 10)
    si.on_enter(g2, room, 10)
    assert g2.state.allowance == 2, (
        f"a later day's entry must not re-pay {room_id}'s one-time token"
    )


@pytest.mark.parametrize("room_id,token_id", sorted(ROOM_TOKENS.items()))
def test_room_token_entering_twice_same_day_pays_once(registry, room_id, token_id):
    """Two first-entry hooks fired in the same day (e.g. re-entering after
    leaving) grant the room's Mora Jai box exactly once, not twice."""
    room = registry.by_id[room_id]
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    suppress_luck(g)
    _place(g.state, g.registry, room_id, 10)

    si.on_enter(g, room, 10)
    si.on_enter(g, room, 10)

    assert g.state.allowance == 2
    assert g.state.inventory.get(token_id, 0) == 0


# ---------------------------------------------------------------------------
# The Tomb's own item pipelines are not double-counted by the new token
# ---------------------------------------------------------------------------

def test_tomb_token_does_not_alter_ignition_grants(registry):
    """The Tomb's Mora Jai box (+2 allowance, guaranteed_in) and its separate
    candle-ignition rewards (Upgrade Disk, dice) both fire without either
    one blocking or double-granting the other."""
    room = registry.by_id["tomb"]
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    suppress_luck(g)
    _place(g.state, g.registry, "tomb", 10)

    si.on_enter(g, room, 10)
    assert g.state.allowance == 2
    assert g.state.inventory.get("upgrade_disk_tomb", 0) == 0  # ignition, not entry-gated

    # Light the Tomb's candles and re-enter: the ignition disk grants
    # independently of the already-collected allowance token.
    g.state.special.lit_targets.append("tomb")
    si.on_enter(g, room, 10)
    assert g.state.inventory.get("upgrade_disk_tomb", 0) == 1
    assert g.state.allowance == 2, "the already-collected token must not re-grant"


# ---------------------------------------------------------------------------
# The Underpass: an area node, granted from on_area_arrival, not guaranteed_in
# ---------------------------------------------------------------------------

def test_underpass_has_no_room_record(registry):
    """No rooms.json entry exists for "underpass", confirming guaranteed_in
    cannot reach it and the area-arrival hook is the only path to the grant."""
    assert "underpass" not in registry.by_id


def test_underpass_token_arrives_on_area_arrival(registry):
    """Standing at the Underpass area node with no on-grid room entry
    involved still pays the +2 allowance, via Game.travel_to's arrival hook."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    suppress_luck(g)
    g.state.steps = 50
    g.state.area = "inner_sanctum"  # unconditional edge to underpass

    assert g.state.allowance == 0
    g.travel_to("underpass")
    assert g.state.area == "underpass"
    assert g.state.allowance == 2


def test_underpass_token_arriving_twice_same_day_pays_once(registry):
    """Leaving and returning to the Underpass within the same day does not
    re-pay its already-collected Mora Jai box."""
    g = Game(GameConfig(special_items=True), seed=1, registry=registry)
    suppress_luck(g)
    g.state.steps = 50
    g.state.area = "inner_sanctum"

    g.travel_to("underpass")
    assert g.state.allowance == 2

    g.travel_to("inner_sanctum")
    g.travel_to("underpass")
    assert g.state.allowance == 2


def test_underpass_token_pays_once_and_not_on_a_later_day(registry):
    """The Underpass's +2 allowance is earned once; DayChain carries the
    source id so a later day's arrival at the same node pays nothing more."""
    chain = DayChain(GameConfig(special_items=True), n_days=200)

    # Day 1: first arrival pays out.
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    suppress_luck(g1)
    g1.state.steps = 50
    g1.state.area = "inner_sanctum"
    g1.travel_to("underpass")
    assert g1.state.allowance == 2

    carry = carryover(g1)
    assert "allowance_token_underpass" in carry["collected_allowance_tokens"]
    chain.advance(carry)

    # Day 2: the carried total pays out as starting coins; a fresh arrival
    # at the Underpass gains nothing further.
    day2_cfg = chain.next_config()
    assert day2_cfg.allowance == 2
    g2 = Game(day2_cfg, seed=2, registry=registry)
    suppress_luck(g2)
    assert g2.state.coins == 2
    assert g2.state.allowance == 2

    g2.state.steps = 50
    g2.state.area = "inner_sanctum"
    g2.travel_to("underpass")
    assert g2.state.allowance == 2, (
        "a later day's arrival must not re-pay the Underpass's one-time token"
    )
