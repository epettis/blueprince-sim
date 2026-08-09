"""Cloister variants: "...for each X you draft FROM THIS CLOISTER" tracking.

Covers the five variants implemented in effects/rooms/cloister.py (Rynna,
Mila, Orinda, Draxus, Lydia). Joya, Dauja and Veia are not modeled (see that
module's docstring) and have no tests here.

Every test bypasses the deal pipeline via Game._place_room directly (as the
other room tests do), but reproduces exactly what Game.choose leaves in place
at the moment ON_DRAFT_ROOM fires: state.pending still set, with from_cell
pointing at the doorway the new room was dealt from. That is the one piece of
state the whole "drafted from THIS Cloister" primitive depends on.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import E, N, W
from blueprince_sim.engine.locks import DOOR_OPEN, DOOR_SEALED, segment_key
from blueprince_sim.engine.state import PendingDraft

ANTECHAMBER_CELL = 42

# Matches the four segments Game.reset seals when antechamber_levers is True.
ANTECHAMBER_SEGMENTS = (
    segment_key(ANTECHAMBER_CELL, N),
    segment_key(41, E),
    segment_key(37, N),
    segment_key(43, W),
)


def _draft_from(g, from_cell: int, target_cell: int, room) -> None:
    """Place ``room`` at ``target_cell`` as if just dealt from ``from_cell``'s doorway.

    Mirrors the live state of Game.choose at the point it calls
    Game._place_room: state.pending is still populated (choose() only clears
    it afterward), with from_cell/target_cell set to the doorway drafted and
    the cell the new room lands on.
    """
    g.state.pending = PendingDraft(from_cell=from_cell, direction=N, target_cell=target_cell)
    g._place_room(room, target_cell, room.door_mask)


def test_rynna_raises_luck_for_a_green_room_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_rynna__ix29 raises luck when a green room is dealt from its
    own doorway; the base Cloister (identical effects: []) does not react."""
    patio = registry.by_id["patio"]
    assert patio.category == "green", "setup: Patio must be a green room"
    for room_id, expected_luck in (("cloister", 0), ("cloister_of_rynna__ix29", 6)):
        g = Game(cfg, seed=1)
        g.state.luck = 0
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, patio)
        assert g.state.luck == expected_luck, room_id


def test_rynna_does_not_react_to_a_green_room_drafted_from_elsewhere(registry, cfg):
    """Luck stays put when the green room's doorway is some other placed
    room's, even with Cloister of Rynna elsewhere on the grid."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    closet = registry.by_id["closet"]
    patio = registry.by_id["patio"]
    g._place_room(rynna, 10, rynna.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, patio)  # dealt from Closet's doorway, not Rynna's
    assert g.state.luck == 0


def test_rynna_does_not_react_to_a_non_green_room_from_its_own_doorway(registry, cfg):
    """A non-green room dealt from Rynna's own doorway grants no luck --
    the trigger is ctx_room.category == "green", not the doorway alone."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    closet = registry.by_id["closet"]  # category "blueprint", not green
    g._place_room(rynna, 10, rynna.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.luck == 0


def test_mila_grants_an_item_only_when_its_flagged_bedroom_is_entered(registry, cfg):
    """cloister_of_mila__ix33 grants exactly one extra item on the first entry
    of a Bedroom dealt from its own doorway; the base Cloister does not."""
    bedroom = registry.by_id["bedroom"]
    assert bedroom.category == "bedroom" and bedroom.items.additional_max == 1
    for room_id, expected_extra in (("cloister", 0), ("cloister_of_mila__ix33", 1)):
        g = Game(cfg, seed=1)
        g.state.luck = 0  # floors the room's own luck-gated additional_max roll to 0
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, bedroom)
        found_before = len(g.state.items_found_log)
        g._enter(11)
        assert len(g.state.items_found_log) == found_before + expected_extra, room_id


def test_mila_does_not_mark_a_bedroom_drafted_from_elsewhere(registry, cfg):
    """A Bedroom dealt from a doorway that is not Mila's own is never marked
    for the bonus item, even with Cloister of Mila elsewhere on the grid."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    mila = registry.by_id["cloister_of_mila__ix33"]
    closet = registry.by_id["closet"]
    bedroom = registry.by_id["bedroom"]
    g._place_room(mila, 10, mila.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, bedroom)
    assert 21 not in g.state.cloister_mila_bonus_cells
    found_before = len(g.state.items_found_log)
    g._enter(21)
    assert len(g.state.items_found_log) == found_before


def test_orinda_opens_exactly_one_antechamber_segment_per_blackprint(registry, cfg):
    """cloister_of_orinda__ix35 opens exactly one of the Antechamber's four
    sealed segments per blackprint dealt from its own doorway; the base
    Cloister leaves all four sealed."""
    throne_room = registry.by_id["throne_room"]
    assert throne_room.category == "blackprint"
    for room_id, expect_one_opened in (("cloister", False), ("cloister_of_orinda__ix35", True)):
        g = Game(cfg, seed=1)
        assert all(g.state.door_state[s] == DOOR_SEALED for s in ANTECHAMBER_SEGMENTS)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, throne_room)
        sealed_left = sum(1 for s in ANTECHAMBER_SEGMENTS if g.state.door_state[s] == DOOR_SEALED)
        assert sealed_left == (3 if expect_one_opened else 4), room_id


def test_orinda_does_not_react_to_a_non_blackprint_room_from_its_own_doorway(registry, cfg):
    """A non-blackprint room dealt from Orinda's own doorway opens nothing --
    the trigger is ctx_room.category == "blackprint", not the doorway alone."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    patio = registry.by_id["patio"]  # category "green", not blackprint
    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, patio)
    assert all(g.state.door_state[s] == DOOR_SEALED for s in ANTECHAMBER_SEGMENTS)


def test_draxus_grants_dice_for_a_dead_end_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_draxus__ix36 grants 4 dice when a Dead End is dealt from
    its own doorway; the base Cloister (identical effects: []) does not."""
    closet = registry.by_id["closet"]
    assert closet.layout == "dead_end", "setup: Closet must be a Dead End"
    for room_id, expected_dice in (("cloister", 0), ("cloister_of_draxus__ix36", 4)):
        g = Game(cfg, seed=1)
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, closet)
        assert g.state.dice == expected_dice, room_id


def test_draxus_does_not_react_to_a_non_dead_end_room_from_its_own_doorway(registry, cfg):
    """A non-Dead-End room dealt from Draxus's own doorway grants no dice --
    the trigger is ctx_room.layout == "dead_end", not the doorway alone."""
    g = Game(cfg, seed=1)
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    patio = registry.by_id["patio"]  # layout "corner", not a dead end
    g._place_room(draxus, 10, draxus.door_mask)
    _draft_from(g, 10, 11, patio)
    assert g.state.dice == 0


def test_two_cloisters_each_track_only_their_own_doorway(registry, cfg):
    """With Rynna and Draxus both on the grid, a room dealt from Rynna's
    doorway only ever raises luck, and a room dealt from Draxus's doorway
    only ever grants dice -- the two trackers never cross-react."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    rynna = registry.by_id["cloister_of_rynna__ix29"]
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    patio = registry.by_id["patio"]  # green, for Rynna
    closet = registry.by_id["closet"]  # dead end, for Draxus
    g._place_room(rynna, 10, rynna.door_mask)
    g._place_room(draxus, 30, draxus.door_mask)

    _draft_from(g, 10, 11, patio)  # dealt from Rynna's doorway
    assert (g.state.luck, g.state.dice) == (6, 0)

    _draft_from(g, 30, 31, closet)  # dealt from Draxus's doorway
    assert (g.state.luck, g.state.dice) == (6, 4)


def test_lydia_raises_allowance_for_a_shop_drafted_from_it_but_base_cloister_does_not(
        registry, cfg):
    """cloister_of_lydia__ix34 adds 2 permanent allowance when a Shop is dealt
    from its own doorway; the base Cloister (identical effects: []) does not."""
    commissary = registry.by_id["commissary"]
    assert commissary.category == "shop", "setup: Commissary must be a Shop"
    for room_id, expected_allowance in (("cloister", 0), ("cloister_of_lydia__ix34", 2)):
        g = Game(cfg, seed=1)
        g.state.luck = 0
        cloister = registry.by_id[room_id]
        g._place_room(cloister, 10, cloister.door_mask)
        _draft_from(g, 10, 11, commissary)
        assert g.state.allowance == expected_allowance, room_id


def test_lydia_does_not_react_to_a_non_shop_room_from_its_own_doorway(registry, cfg):
    """A non-Shop room dealt from Lydia's own doorway raises no allowance --
    the trigger is ctx_room.category == "shop", not the doorway alone."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    lydia = registry.by_id["cloister_of_lydia__ix34"]
    closet = registry.by_id["closet"]  # category "blueprint", not shop
    g._place_room(lydia, 10, lydia.door_mask)
    _draft_from(g, 10, 11, closet)
    assert g.state.allowance == 0


def test_lydia_does_not_react_to_a_shop_drafted_from_elsewhere(registry, cfg):
    """Allowance stays put when the Shop's doorway is some other placed
    room's, even with Cloister of Lydia elsewhere on the grid."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    lydia = registry.by_id["cloister_of_lydia__ix34"]
    closet = registry.by_id["closet"]
    commissary = registry.by_id["commissary"]
    g._place_room(lydia, 10, lydia.door_mask)
    g._place_room(closet, 20, closet.door_mask)
    _draft_from(g, 20, 21, commissary)  # dealt from Closet's doorway, not Lydia's
    assert g.state.allowance == 0


def test_orinda_opens_a_still_sealed_door_rather_than_one_already_open(registry, cfg):
    """With three of the four segments already open, Orinda opens the fourth.

    The room promises a door, so a trigger that landed on an already-open
    segment would silently deliver nothing. Leaving exactly one sealed makes
    the choice observable without depending on the RNG."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    throne_room = registry.by_id["throne_room"]
    still_sealed = ANTECHAMBER_SEGMENTS[1]
    for seg in ANTECHAMBER_SEGMENTS:
        if seg != still_sealed:
            g.state.door_state[seg] = DOOR_OPEN

    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, throne_room)

    assert g.state.door_state[still_sealed] != DOOR_SEALED


def test_orinda_is_a_no_op_when_every_antechamber_door_is_open(registry, cfg):
    """Orinda leaves the Antechamber alone once nothing is sealed, rather than
    failing on an empty set of candidates."""
    g = Game(cfg, seed=1)
    orinda = registry.by_id["cloister_of_orinda__ix35"]
    throne_room = registry.by_id["throne_room"]
    for seg in ANTECHAMBER_SEGMENTS:
        g.state.door_state[seg] = DOOR_OPEN

    g._place_room(orinda, 10, orinda.door_mask)
    _draft_from(g, 10, 11, throne_room)

    assert all(g.state.door_state[s] == DOOR_OPEN for s in ANTECHAMBER_SEGMENTS)
