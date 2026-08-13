"""Nook guaranteed key grants, plus the Breakfast Nook's free Bacon & Eggs and
the Reading Nook's guaranteed Library slot, for the base room and its three
upgrade variants.

``nook__ix97`` grants 2 keys; ``reading_nook__ix99`` and ``breakfast_nook__ix98``
grant 1 each. Items are not inherited through ``variant_of``, so each record
carries its own count.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import S
from luck_utils import suppress_luck


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` luck-rolled extra item
    never procs, keeping the guaranteed-key assertions below deterministic."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=seed)
    suppress_luck(g)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_nook_ix97_grants_two_keys():
    """nook__ix97 ("+2 key") grants exactly 2 keys on first entry."""
    cell = 5
    g = _make_game_with_room("nook__ix97", cell)
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 2


def test_reading_nook_grants_one_key():
    """reading_nook__ix99's "+1 key" half of its text lands on first entry
    (its "always draw LIBRARY" half is covered separately below)."""
    cell = 5
    g = _make_game_with_room("reading_nook__ix99", cell)
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1


def test_breakfast_nook_grants_one_key():
    """breakfast_nook__ix98's "+1 key" half of its text lands on first entry
    (its Bacon & Eggs half is covered separately below)."""
    cell = 5
    g = _make_game_with_room("breakfast_nook__ix98", cell)
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1


# --------------------------------------------------------- Breakfast Nook


def test_breakfast_nook_eats_free_bacon_and_eggs_on_entry():
    """Entering the Breakfast Nook grants the guaranteed key, +10 steps from
    the free Bacon & Eggs, and adds a Morning Room to today's draft pool."""
    cell = 5
    g = _make_game_with_room("breakfast_nook__ix98", cell)
    morning_room = g.registry.by_id["morning_room"]
    deck = g.state.deck(morning_room.rarity_idx, not morning_room.is_free)
    count_before = deck.order.count(morning_room.idx)
    keys0, steps0 = g.state.keys, g.state.steps

    g._enter(cell)

    assert g.state.keys == keys0 + 1
    assert g.state.steps == steps0 + 10
    assert deck.order.count(morning_room.idx) == count_before + morning_room.deck_copies


def test_plain_nook_grants_no_bacon_and_eggs():
    """Entering the plain Nook adds no Morning Room to today's pool and
    grants no free steps -- only its own guaranteed key."""
    cell = 5
    g = _make_game_with_room("nook", cell)
    morning_room = g.registry.by_id["morning_room"]
    deck = g.state.deck(morning_room.rarity_idx, not morning_room.is_free)
    count_before = deck.order.count(morning_room.idx)
    steps0 = g.state.steps

    g._enter(cell)

    assert g.state.steps == steps0
    assert deck.order.count(morning_room.idx) == count_before


# --------------------------------------------------------- Reading Nook


def _open_reading_nook_door(registry, cfg, room_id: str, seed: int = 0):
    """Place ``room_id`` (a corner room) at a fixed cell and open its S door.

    Returns (game, pending). Mirrors tests/rooms/test_archives.py's
    place-then-open_door pattern; the room is not entered, matching real
    drafting semantics (a doorway can be opened and dealt from before ever
    walking into the room that owns it).
    """
    g = Game(cfg, seed=seed)
    room = registry.by_id[room_id]
    cell = 12
    g._place_room(room, cell, room.door_mask)  # canonical corner mask: S|E
    g.state.pos = cell
    g.state.entered[cell] = True
    pending = g.open_door(cell, S)
    return g, pending


def test_reading_nook_forces_library_into_third_slot(registry, cfg):
    """A hand dealt from the Reading Nook's own doorway always shows LIBRARY
    in slot index 2 (the third slot), regardless of the normal draft roll."""
    g, pending = _open_reading_nook_door(registry, cfg, "reading_nook__ix99", seed=7)
    library = registry.by_id["library"]
    assert len(pending.options) == 3
    assert pending.options[2].room_idx == library.idx


def test_reading_nook_library_forcing_survives_a_redraw(registry, cfg):
    """The Library guarantee still holds after a redraw of the same hand, not
    just on the initial deal."""
    from blueprince_sim.engine.game import RedrawKind

    g, _pending = _open_reading_nook_door(registry, cfg, "reading_nook__ix99", seed=11)
    g.state.dice = 1
    g.redraw(RedrawKind.DIE)
    library = registry.by_id["library"]
    assert g.state.pending.options[2].room_idx == library.idx


def test_reading_nook_forces_library_even_when_already_drafted_elsewhere(registry, cfg):
    """The guarantee still fires when the Library has already been drafted
    elsewhere: no Library card left in any deck, and one already on the grid."""
    g = Game(cfg, seed=13)
    library = registry.by_id["library"]
    for is_gem in (False, True):
        deck = g.state.deck(library.rarity_idx, is_gem)
        deck.order = [c for c in deck.order if c != library.idx]
    g.placed_ids.add(library.id)

    room = registry.by_id["reading_nook__ix99"]
    cell = 12
    g._place_room(room, cell, room.door_mask)
    g.state.pos = cell
    g.state.entered[cell] = True
    pending = g.open_door(cell, S)
    assert pending.options[2].room_idx == library.idx


def test_plain_nook_does_not_force_library(registry, cfg):
    """A hand dealt from the plain Nook's doorway runs the ordinary draw for
    slot 2: across several seeds, at least one deals something other than
    LIBRARY, showing the slot is not forced the way the Reading Nook's is."""
    library = registry.by_id["library"]
    saw_non_library = False
    for seed in range(20):
        _g, pending = _open_reading_nook_door(registry, cfg, "nook", seed=seed)
        if pending.options[2].room_idx != library.idx:
            saw_non_library = True
            break
    assert saw_non_library, "slot 2 from the plain Nook was Library on every seed tried"
