"""Geist Bedroom: Tomb-conditional dice, no steps, no item spawn/luck touch.

blueprince.wiki.gg/wiki/Guest_Bedroom/Upgrades (Geist tab): "+2[dice] If you
have TOMB on the estate today, gain an additional 4[dice]." "This upgrade
removes the normal steps effect, and disables the random item spawns in the
room." "The additional 4 dice only spawns if the Tomb was drafted before the
Geist Bedroom."
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game

ROOM_ID = "geist_bedroom__ix69"


def test_geist_bedroom_grants_two_dice_with_no_tomb(registry, cfg):
    """With no Tomb anywhere on the estate, first entry grants exactly 2 dice."""
    g = Game(cfg, seed=0)
    room = registry.by_id[ROOM_ID]
    cell = 7
    g._place_room(room, cell, room.door_mask)
    dice0 = g.state.dice

    g._enter(cell)

    assert g.state.dice == dice0 + 2


def test_geist_bedroom_grants_six_dice_with_tomb_drafted_first(registry, cfg):
    """A Tomb drafted BEFORE the Geist Bedroom raises the grant to 6 dice
    (2 base + 4 bonus)."""
    g = Game(cfg, seed=1)
    tomb = registry.by_id["tomb"]
    room = registry.by_id[ROOM_ID]
    tomb_cell, geist_cell = 6, 7
    g._place_room(tomb, tomb_cell, tomb.door_mask)
    g._place_room(room, geist_cell, room.door_mask)
    dice0 = g.state.dice

    g._enter(geist_cell)

    assert g.state.dice == dice0 + 6


def test_geist_bedroom_stays_at_two_dice_when_tomb_drafted_after(registry, cfg):
    """A Tomb drafted AFTER the Geist Bedroom does not retroactively raise the
    grant -- the ordering check is a strict draft-time snapshot, not "on the
    estate by the time of entry"."""
    g = Game(cfg, seed=2)
    tomb = registry.by_id["tomb"]
    room = registry.by_id[ROOM_ID]
    geist_cell, tomb_cell = 7, 6
    g._place_room(room, geist_cell, room.door_mask)
    g._place_room(tomb, tomb_cell, tomb.door_mask)
    dice0 = g.state.dice

    g._enter(geist_cell)

    assert g.state.dice == dice0 + 2


def test_geist_bedroom_grants_no_steps(registry, cfg):
    """Unlike the base Guest Bedroom's +10 steps, the Geist Bedroom grants
    none -- its own effects list is empty (rooms.json)."""
    g = Game(cfg, seed=3)
    room = registry.by_id[ROOM_ID]
    cell = 7
    g._place_room(room, cell, room.door_mask)
    steps0 = g.state.steps

    g._enter(cell)

    assert g.state.steps == steps0


def test_geist_bedroom_never_touches_luck_across_a_seed_sweep(registry, cfg):
    """Luck (including the two-plus-items penalty) is never processed for the
    Geist Bedroom, across a sweep of seeds.

    Mechanism: rooms.json sets its items.additional_max to 0 (down from the
    blueprint-category default of 1), so items.roll_room_items's luck-rolled
    loop -- ``for _ in range(room.items.additional_max)`` -- never executes
    at all; with no items.guaranteed either, "found" stays 0 and the
    two-plus-items luck penalty never fires. No dedicated code path is needed
    in effects/rooms/guest_bedroom.py to keep luck untouched.
    """
    room = registry.by_id[ROOM_ID]
    assert room.items.additional_max == 0
    cell = 7
    for seed in range(30):
        g = Game(cfg, seed=seed)
        g._place_room(room, cell, room.door_mask)
        luck0 = g.state.luck
        g._enter(cell)
        assert g.state.luck == luck0
