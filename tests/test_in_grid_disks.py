"""Tests for the entry-granted in-grid Upgrade Disks and the disks_held observation.

Five disks (office, morning_room, her_ladyships_chamber, great_hall, freezer)
are granted on first room entry unconditionally, with none of their real-game
gates modelled, so there is no "gate unsatisfied" case to test for them.

The sixth, archives, is the one exception (owner ruling): its real-game gate
IS modelled, via requires_item="file_cabinet_key" on upgrade_disk_archives.
Entry alone does not grant it -- see the file_cabinet_key-gated tests below,
and tests/test_digging.py for the key's own dig-guarantee mechanism.

The Mechanarium's disk is deliberately absent: it sits in that room's third
diagonal compartment, which only spawns with three more Mechanical rooms than
cardinal doors, so it is opened rather than granted on entry. See
tests/rooms/test_mechanarium.py.
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

_IN_GRID_DISK_ROOMS = [
    ("office", "upgrade_disk_office"),
    ("morning_room", "upgrade_disk_morning_room"),
    ("her_ladyships_chamber", "upgrade_disk_her_ladyships_chamber"),
    ("great_hall", "upgrade_disk_great_hall"),
    ("freezer", "upgrade_disk_freezer"),
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
    """Each in-grid room hands over its disk on entry, and entering it again yields nothing.

    Uniqueness is what caps disk supply: a second grant of a `unique` item must be
    refused, otherwise a player could farm one room for unlimited upgrades.
    """
    for room_id, disk_id in _IN_GRID_DISK_ROOMS:
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


def test_archives_disk_not_granted_without_file_cabinet_key():
    """Owner ruling: entering Archives without file_cabinet_key does not grant its disk.

    Unlike the other five in-grid disks, upgrade_disk_archives carries
    requires_item="file_cabinet_key" -- its real-game gate IS modelled, so
    entry alone is not enough.
    """
    g = _game()
    assert not si.has(g.state, "file_cabinet_key")
    assert g.state.inventory.get("upgrade_disk_archives", 0) == 0

    _enter(g, "archives")

    assert g.state.inventory.get("upgrade_disk_archives", 0) == 0, (
        "entering Archives without file_cabinet_key must not grant the disk"
    )


def test_archives_disk_granted_once_key_is_held():
    """Holding file_cabinet_key on first entry grants upgrade_disk_archives exactly once.

    Same uniqueness-capped supply as the other five in-grid disks, once the
    data-driven requires_item gate is satisfied.
    """
    g = _game()
    si.grant(g.state, g.registry, "file_cabinet_key", source="test")
    assert g.state.inventory.get("upgrade_disk_archives", 0) == 0

    _enter(g, "archives")

    assert g.state.inventory.get("upgrade_disk_archives", 0) == 1, (
        "entering Archives while holding file_cabinet_key must grant exactly one disk"
    )


def test_disks_held_encodes_counts_above_the_old_cap():
    """Holding more disks than the old cap of 7 encodes the true count, in-range for the space.

    Before these disks landed the space was Discrete(8) with a min(..., 7) clamp;
    leaving either in place would silently report 7 forever once 8+ disks became
    reachable.
    """
    g = _game()
    for _, disk_id in _IN_GRID_DISK_ROOMS:
        si.grant(g.state, g.registry, disk_id, source="test")
    # Granted directly rather than by entering: the Mechanarium's disk is
    # compartment-gated, archives now requires file_cabinet_key (si.grant
    # bypasses that requires_item gate same as it bypasses the compartment
    # one), and the point here is the held count, not any disk's own source.
    si.grant(g.state, g.registry, "upgrade_disk_mechanarium", source="test")
    si.grant(g.state, g.registry, "upgrade_disk_vault_304", source="test")
    si.grant(g.state, g.registry, "upgrade_disk_archives", source="test")
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
    """A fixed-location disk spent (inserted at a terminal) on day 1 is not re-granted on day 2.

    `guaranteed_in` re-fires on every day's first entry and `state.special.removed`
    only lasts the day, so without the collected_disks carryover each of these rooms
    would re-mint a disk after it had been consumed — undermining the upgrade economy's
    one-disk-per-attempt-per-room supply cap.
    """
    g = _game()
    _enter(g, "office")
    si.remove(g.state, "upgrade_disk_office", consumed=True)
    assert g.state.inventory.get("upgrade_disk_office", 0) == 0, "disk should be spent"

    carry = shops.carryover(g)
    assert "upgrade_disk_office" in carry["collected_disks"], (
        "a spent disk must appear in collected_disks so it cannot be re-granted later"
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
    """Re-drafting every in-grid room across many days yields each disk at most once.

    This is the supply cap the upgrade economy depends on: 7 fixed disks per attempt,
    not 7 per day.
    """
    collected: frozenset[str] = frozenset()
    total_grants = 0
    for day in range(5):
        g = Game(GameConfig(special_items=True, collected_disks=collected), seed=day)
        si.configure(g.state, g.cfg)
        for cell, (room_id, disk_id) in enumerate(_IN_GRID_DISK_ROOMS):
            _enter(g, room_id, cell=cell)
            if g.state.inventory.get(disk_id, 0):
                total_grants += 1
                si.remove(g.state, disk_id, consumed=True)
        collected = frozenset(shops.carryover(g)["collected_disks"])

    assert total_grants == len(_IN_GRID_DISK_ROOMS), (
        f"expected {len(_IN_GRID_DISK_ROOMS)} disks over the whole attempt, got {total_grants}"
    )


def test_unspent_disk_is_not_in_next_day_inventory():
    """An unspent in-grid disk drops at end-of-day and is absent from day 2's starting inventory.

    Disks have persistence="day", so end_of_day_carry() does not include them —
    only spending (inserting) a disk makes its removal permanent.
    """
    g = _game()
    _enter(g, "office")
    assert g.state.inventory.get("upgrade_disk_office", 0) == 1, "disk must be in hand after entry"

    carry = shops.carryover(g)
    assert "upgrade_disk_office" not in carry["collected_disks"], (
        "an unspent disk must not appear in collected_disks — it was not consumed"
    )
    assert "upgrade_disk_office" not in carry["starting_items"], (
        "an unspent day-persistence disk must not carry to the next day's starting_items"
    )

    day2 = Game(
        GameConfig(
            special_items=True,
            collected_disks=frozenset(carry["collected_disks"]),
            starting_items=frozenset(carry["starting_items"]),
        ),
        seed=1,
    )
    si.configure(day2.state, day2.cfg)
    assert day2.state.inventory.get("upgrade_disk_office", 0) == 0, (
        "the unspent disk must not appear in day 2's inventory — it dropped overnight"
    )


def test_unspent_disk_is_regranted_when_room_reentered():
    """A disk collected but not spent returns to its room and is re-granted on re-entry.

    This is the core drop-and-respawn rule: persistence="day" means the disk is absent
    from day 2's starting items, and because it was not spent (not in collected_disks),
    _is_available allows the room to re-grant it when entered again.
    """
    g = _game()
    _enter(g, "office")
    assert g.state.inventory.get("upgrade_disk_office", 0) == 1, "disk in hand after day 1 entry"

    carry = shops.carryover(g)
    # Disk was not spent -> not in collected_disks -> room can re-grant on day 2
    assert "upgrade_disk_office" not in carry["collected_disks"]

    day2 = Game(
        GameConfig(
            special_items=True,
            collected_disks=frozenset(carry["collected_disks"]),
            starting_items=frozenset(carry["starting_items"]),
        ),
        seed=1,
    )
    si.configure(day2.state, day2.cfg)
    assert day2.state.inventory.get("upgrade_disk_office", 0) == 0, (
        "disk must not be in day 2 starting inventory — it was not carried over"
    )

    _enter(day2, "office")
    assert day2.state.inventory.get("upgrade_disk_office", 0) == 1, (
        "re-entering the Office on day 2 must re-grant the disk that was not spent"
    )


def test_spend_vs_no_spend_diverge_across_days():
    """Spending a disk and not spending it produce opposite outcomes on the next day.

    Spend path: disk consumed -> in collected_disks -> room blocked -> disk absent on day 2.
    No-spend path: disk drops overnight -> not in collected_disks -> room re-grants on day 2.
    """
    # --- spend path ---
    g_spend = _game()
    _enter(g_spend, "office")
    si.remove(g_spend.state, "upgrade_disk_office", consumed=True)
    carry_spend = shops.carryover(g_spend)
    assert "upgrade_disk_office" in carry_spend["collected_disks"], "spent disk must be in carryover"

    day2_spend = Game(
        GameConfig(
            special_items=True,
            collected_disks=frozenset(carry_spend["collected_disks"]),
            starting_items=frozenset(carry_spend["starting_items"]),
        ),
        seed=1,
    )
    si.configure(day2_spend.state, day2_spend.cfg)
    _enter(day2_spend, "office")
    after_spend = day2_spend.state.inventory.get("upgrade_disk_office", 0)

    # --- no-spend path ---
    g_keep = _game()
    _enter(g_keep, "office")
    # disk is in inventory but NOT spent
    carry_keep = shops.carryover(g_keep)
    assert "upgrade_disk_office" not in carry_keep["collected_disks"], (
        "unspent disk must not be in collected_disks"
    )

    day2_keep = Game(
        GameConfig(
            special_items=True,
            collected_disks=frozenset(carry_keep["collected_disks"]),
            starting_items=frozenset(carry_keep["starting_items"]),
        ),
        seed=1,
    )
    si.configure(day2_keep.state, day2_keep.cfg)
    _enter(day2_keep, "office")
    after_keep = day2_keep.state.inventory.get("upgrade_disk_office", 0)

    assert after_spend == 0, (
        f"spent path: Office on day 2 must not re-grant the disk (got {after_spend})"
    )
    assert after_keep == 1, (
        f"no-spend path: Office on day 2 must re-grant the disk (got {after_keep})"
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
    assert n_disks >= 8, f"expected the in-grid disks to be registered, found {n_disks}"
    assert O.MAX_DISKS_HELD >= n_disks, (
        f"MAX_DISKS_HELD={O.MAX_DISKS_HELD} cannot represent {n_disks} distinct disks"
    )
