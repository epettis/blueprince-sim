"""Tests for the 7 Ingrid Upgrade Disks and the widened disks_held observation.

All seven disks (office, morning_room, her_ladyships_chamber, great_hall,
freezer, archives, mechanarium) are granted on first room entry; none of their
real-game gates is modelled, so there is no "gate unsatisfied" case to test.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env import obs as O
from blueprince_sim.env.multiday import DayChain

_INGRID_DISK_ROOMS = [
    ("office", "upgrade_disk_office"),
    ("morning_room", "upgrade_disk_morning_room"),
    ("her_ladyships_chamber", "upgrade_disk_her_ladyships_chamber"),
    ("great_hall", "upgrade_disk_great_hall"),
    ("freezer", "upgrade_disk_freezer"),
    ("archives", "upgrade_disk_archives"),
    ("mechanarium", "upgrade_disk_mechanarium"),
]


def _game() -> Game:
    g = Game(GameConfig(special_items=True), seed=0)
    si.configure(g.state, g.cfg)
    return g


def _enter(game: Game, room_id: str, cell: int = 5) -> None:
    """Put ``room_id`` at ``cell`` and fire the room-entry hook."""
    room = game.registry.by_id[room_id]
    game.state.grid[cell] = room.idx
    game.state.placed_doors[cell] = room.door_mask
    si.on_enter(game, room, cell)


def test_entering_grants_one_disk_and_reentry_grants_none():
    """Each Ingrid room hands over its disk on entry, and entering it again yields nothing.

    Uniqueness is what caps disk supply: a second grant of a `unique` item must be
    refused, otherwise a player could farm one room for unlimited upgrades.
    """
    for room_id, disk_id in _INGRID_DISK_ROOMS:
        g = _game()
        assert g.state.inventory.get(disk_id, 0) == 0, f"{disk_id} held before entering {room_id}"

        _enter(g, room_id)
        assert g.state.inventory.get(disk_id, 0) == 1, (
            f"entering {room_id} must grant exactly one {disk_id}"
        )

        _enter(g, room_id)
        assert g.state.inventory.get(disk_id, 0) == 1, (
            f"re-entering {room_id} granted a duplicate {disk_id}"
        )


def test_disks_held_encodes_counts_above_the_old_cap():
    """Holding more disks than the old cap of 7 encodes the true count, in-range for the space.

    The pre-Ingrid space was Discrete(8) with a min(..., 7) clamp; leaving either in
    place would silently report 7 forever once 8+ disks became reachable.
    """
    g = _game()
    for _, disk_id in _INGRID_DISK_ROOMS:
        si.grant(g.state, g.registry, disk_id, source="test")
    si.grant(g.state, g.registry, "upgrade_disk_vault_304", source="test")
    held = len(g.held_disk_ids())
    assert held == 8, f"fixture should hold 8 disks, holds {held}"

    space = O.observation_space(
        len(g.registry.rooms),
        len(g.registry.special.items),
        len(g.registry.special.fabrication),
    )
    encoded = O.encode(g)["disks_held"]

    assert encoded == held, f"disks_held encoded {encoded}, expected {held}"
    assert space["disks_held"].contains(np.int64(encoded)), (
        f"disks_held={encoded} is outside the declared {space['disks_held']}"
    )


def test_consumed_disk_is_not_regranted_on_a_later_day():
    """A fixed-location disk collected and spent on day 1 is not handed out again on day 2.

    `guaranteed_in` re-fires on every day's first entry and `state.special.removed`
    only lasts the day, so without the collected_disks carryover each of these rooms
    would mint a fresh disk daily against a real-game cap of one per attempt.
    """
    g = _game()
    _enter(g, "office")
    si.remove(g.state, "upgrade_disk_office", consumed=True)
    assert g.state.inventory.get("upgrade_disk_office", 0) == 0, "disk should be spent"

    carry = shops.carryover(g)
    assert "upgrade_disk_office" in carry["collected_disks"], (
        "a disk found today must appear in collected_disks even after being spent"
    )

    day2 = Game(
        GameConfig(special_items=True, collected_disks=frozenset(carry["collected_disks"])),
        seed=1,
    )
    si.configure(day2.state, day2.cfg)
    _enter(day2, "office")
    assert day2.state.inventory.get("upgrade_disk_office", 0) == 0, (
        "re-entering the Office on a later day re-granted an already-collected disk"
    )


def test_repeated_days_cannot_exceed_one_disk_per_fixed_location():
    """Re-drafting every Ingrid room across many days yields each disk at most once.

    This is the supply cap the upgrade economy depends on: 7 fixed disks per attempt,
    not 7 per day.
    """
    collected: frozenset[str] = frozenset()
    total_grants = 0
    for day in range(5):
        g = Game(GameConfig(special_items=True, collected_disks=collected), seed=day)
        si.configure(g.state, g.cfg)
        for cell, (room_id, disk_id) in enumerate(_INGRID_DISK_ROOMS):
            _enter(g, room_id, cell=cell)
            if g.state.inventory.get(disk_id, 0):
                total_grants += 1
                si.remove(g.state, disk_id, consumed=True)
        collected = frozenset(shops.carryover(g)["collected_disks"])

    assert total_grants == len(_INGRID_DISK_ROOMS), (
        f"expected {len(_INGRID_DISK_ROOMS)} disks over the whole attempt, got {total_grants}"
    )


def test_unspent_disk_still_carries_in_inventory_to_the_next_day():
    """A disk found but not spent is still held the next day; gating must not eat it.

    collected_disks blocks re-granting, not possession — breaking the normal
    permanent-item carry would quietly delete disks the player is saving for a reader.
    """
    g = _game()
    _enter(g, "office")
    assert g.state.inventory.get("upgrade_disk_office", 0) == 1

    carry = shops.carryover(g)
    assert "upgrade_disk_office" in carry["starting_items"], (
        "an unspent permanent disk must carry over as a starting item"
    )

    day2 = Game(
        GameConfig(
            special_items=True,
            collected_disks=frozenset(carry["collected_disks"]),
            starting_items=frozenset(carry["starting_items"]),
        ),
        seed=1,
    )
    assert day2.state.inventory.get("upgrade_disk_office", 0) == 1, (
        "the carried disk was lost on the next day"
    )


def test_daychain_accumulates_collected_disks_and_clears_them_on_a_new_attempt():
    """DayChain unions collected_disks across days and resets it when the attempt wraps.

    Training drives days through DayChain, not carryover() directly, so a break in this
    wiring would restore the duplicate-disk bug for every trained agent while the
    carryover-level tests stayed green.
    """
    chain = DayChain(GameConfig(special_items=True), n_days=3)
    assert chain.next_config().collected_disks == frozenset(), "attempt starts with none collected"

    chain.advance({"collected_disks": ["upgrade_disk_office"]})
    chain.advance({"collected_disks": ["upgrade_disk_freezer"]})
    assert chain.next_config().collected_disks == {
        "upgrade_disk_office",
        "upgrade_disk_freezer",
    }, "collected disks must accumulate as a union across days"

    chain.advance({})  # day 4 exceeds n_days=3, so the attempt wraps
    assert chain.next_config().collected_disks == frozenset(), (
        "a fresh attempt puts every fixed-location disk back in the house"
    )


def test_disks_held_cap_can_represent_every_disk_in_the_registry():
    """The disks_held cap is at least the number of distinct disk items that exist.

    Disks are unique, so a player can hold every one at once; if the registry ever
    grows past the cap the observation would clamp and hide real inventory.
    """
    g = _game()
    n_disks = sum(1 for item in g.registry.special.items if item.id.startswith("upgrade_disk_"))
    assert n_disks >= 8, f"expected the Ingrid disks to be registered, found {n_disks}"
    assert O.MAX_DISKS_HELD >= n_disks, (
        f"MAX_DISKS_HELD={O.MAX_DISKS_HELD} cannot represent {n_disks} distinct disks"
    )
