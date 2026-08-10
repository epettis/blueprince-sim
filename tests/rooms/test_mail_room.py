"""Mail Room: the order-and-deliver cycle and its package contents roller."""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env.multiday import DayChain

CELL = 5


def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    """A Game with luck floored, so additional_max rolls cannot contaminate assertions."""
    g = Game(cfg if cfg is not None else GameConfig(special_items=True), seed=seed)
    g.state.luck = 0
    return g


def _place_mail_room(g: Game, cell: int = CELL) -> None:
    room = g.registry.by_id["mail_room"]
    g._place_room(room, cell, room.door_mask)


# ------------------------------------------------------------- order/deliver cycle

def test_first_draft_places_order_and_grants_nothing():
    """Drafting a Mail Room from the empty cycle places an order and grants
    nothing -- the effect text's package only arrives on a later draft."""
    g = _game()
    before_inventory = dict(g.state.inventory)
    before = (g.state.gems, g.state.keys, g.state.coins)
    _place_mail_room(g)
    assert g.state.mail_cycle == "awaiting"
    assert g.state.mail_package_cell == -1
    assert g.state.inventory == before_inventory
    assert (g.state.gems, g.state.keys, g.state.coins) == before


def test_awaiting_draft_delivers_into_its_own_cell():
    """A Mail Room drafted while the cycle is already awaiting delivers into
    its own cell and resets the cycle to empty."""
    g = _game(GameConfig(special_items=True, mail_cycle="awaiting"))
    _place_mail_room(g)
    assert g.state.mail_cycle == "empty"
    assert g.state.mail_package_cell == CELL


def test_entering_the_delivered_cell_grants_a_package():
    """Entering the cell holding a delivered package grants its contents and
    clears the delivery marker."""
    g = _game(GameConfig(special_items=True, mail_cycle="awaiting"))
    _place_mail_room(g)
    before = len(g.state.items_found_log)
    g._enter(CELL)
    assert g.state.mail_package_cell == -1
    assert len(g.state.items_found_log) > before


def test_uncollected_package_is_lost_and_next_draft_starts_a_fresh_order():
    """A delivered package that is never entered is lost: driven through
    DayChain, the day after a non-collection starts a brand new order rather
    than re-delivering the old one."""
    chain = DayChain(GameConfig(special_items=True), n_days=5)

    g1 = _game(chain.next_config(), seed=1)
    _place_mail_room(g1)  # day 1: order placed (empty -> awaiting)
    chain.advance(g1.carryover())

    g2 = _game(chain.next_config(), seed=2)
    _place_mail_room(g2)  # day 2: delivered into CELL, never entered
    assert g2.state.mail_cycle == "empty"
    assert g2.state.mail_package_cell == CELL
    chain.advance(g2.carryover())  # package left uncollected -> lost

    g3 = _game(chain.next_config(), seed=3)
    assert g3.state.mail_cycle == "empty", "a lost package must not re-arm the cycle"
    before = len(g3.state.items_found_log)
    _place_mail_room(g3)
    assert g3.state.mail_cycle == "awaiting", "the next draft must start a fresh order"
    assert len(g3.state.items_found_log) == before, "nothing is granted for a lost package"


def test_cycle_survives_multiple_days_before_being_drafted_again():
    """An order placed on one day waits for the Mail Room to be drafted
    again however many days that takes -- the cycle is not a countdown."""
    chain = DayChain(GameConfig(special_items=True), n_days=10)

    g1 = _game(chain.next_config(), seed=1)
    _place_mail_room(g1)  # day 1: order placed
    assert g1.state.mail_cycle == "awaiting"
    chain.advance(g1.carryover())
    assert chain.next_config().mail_cycle == "awaiting"

    # Day 2 passes with no Mail Room drafted at all; the order must not be missed.
    g2 = _game(chain.next_config(), seed=2)
    chain.advance(g2.carryover())
    assert chain.next_config().mail_cycle == "awaiting", (
        "a day with no Mail Room draft must not miss the order"
    )

    g3 = _game(chain.next_config(), seed=3)
    _place_mail_room(g3)  # day 3: drafted again -> delivered
    assert g3.state.mail_cycle == "empty"
    assert g3.state.mail_package_cell == CELL


# --------------------------------------------------------------- package contents

def test_every_package_has_slot1_and_slot2_grants_slot3_sometimes_absent():
    """Every rolled package contains at least a slot-1 and a slot-2 grant;
    slot 3 is sometimes present and sometimes absent across enough seeds."""
    lengths = set()
    for seed in range(60):
        g = _game(seed=seed)
        grants = si.roll_mail_package(g.state, g.registry, g.rng)
        assert len(grants) in (2, 3)
        lengths.add(len(grants))
    assert lengths == {2, 3}, f"expected both 2- and 3-grant packages across the sweep, got {lengths}"


def test_slot3_absent_when_slot2_is_compass():
    """When slot 2 resolves to the Compass, slot 3 never produces a third grant."""
    hits = 0
    for seed in range(200):
        g = _game(seed=seed)
        grants = si.roll_mail_package(g.state, g.registry, g.rng)
        slot2 = grants[1]
        if slot2.get("kind") == "item" and slot2["id"] == "compass":
            hits += 1
            assert len(grants) == 2, "slot2=Compass must never carry a slot-3 grant"
    assert hits > 0, "sweep did not hit slot2=Compass; widen the seed range"


def test_slot3_always_two_keys_when_slot2_is_silver_key():
    """When slot 2 resolves to the Silver Key, slot 3 always grants 2 keys."""
    hits = 0
    for seed in range(400):
        g = _game(seed=seed)
        grants = si.roll_mail_package(g.state, g.registry, g.rng)
        slot2 = grants[1]
        if slot2.get("kind") == "item" and slot2["id"] == "silver_key":
            hits += 1
            assert len(grants) == 3
            assert grants[2] == {"kind": "keys", "amount": 2}
    assert hits > 0, "sweep did not hit slot2=Silver Key; widen the seed range"


def test_availability_fallback_when_compass_already_held():
    """With the Compass already held, a slot-1 chain starting with the
    Compass falls through to its next entry instead of repeating it."""
    g = _game()
    si.grant(g.state, g.registry, "compass", source="test")
    chain = g.registry.special.mail_packages["slot1"]["chains"][0]
    assert chain[0]["id"] == "compass", "fixture chain must start with the Compass"
    resolved = si._resolve_mail_chain(g.state, g.registry, chain)
    assert resolved["id"] != "compass"
    assert resolved["id"] == "lock_pick_kit"
