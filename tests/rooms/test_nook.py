"""Nook guaranteed key grants, for the base room and its three upgrade variants.

``nook__ix97`` grants 2 keys; ``reading_nook__ix99`` and
``breakfast_nook__ix98`` grant 1 each. Items are not inherited through
``variant_of``, so each record carries its own count.

Reading Nook's guaranteed LIBRARY draw and Breakfast Nook's Bacon & Eggs are
not modelled -- ``items.guaranteed`` has no way to name a specific dish -- so
only the key grants are asserted here.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game instance with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` luck-rolled extra item
    never procs, keeping the guaranteed-key assertions below deterministic."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=seed)
    g.state.luck = 0
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
    (its "always draw LIBRARY" half is a new mechanic, out of scope)."""
    cell = 5
    g = _make_game_with_room("reading_nook__ix99", cell)
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1


def test_breakfast_nook_grants_one_key():
    """breakfast_nook__ix98's "+1 key" half of its text lands on first entry
    (its Bacon & Eggs half cannot be expressed by the current items schema,
    see the audit report)."""
    cell = 5
    g = _make_game_with_room("breakfast_nook__ix98", cell)
    keys0 = g.state.keys

    g._enter(cell)
    assert g.state.keys == keys0 + 1
