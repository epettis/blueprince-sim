"""Clock Tower: category-targeted draws can now select it, plus its real
day-end effect.

The category-draw section reuses the technique from tests/rooms/test_the_kennel.py
(a hand-built single-card deck plus a forced-chance category bias, so the proof
is deterministic rather than statistical).

The Clock Tower's real effect ("The Clock Tower increases the next day starting
key for every Tomorrow room present in the mansion. This includes the Clock
Tower itself.", wiki prose -- the infobox's "for each Tomorrow room you draft
today" is the losing reading, per the owner ruling) is a day-end grid tally,
implemented as a room_hook on Hook.ON_DAY_END_ALL (engine/effects/rooms/
clock_tower.py) rather than the room's own ON_DAY_END hook: ON_DAY_END only
fires for the room the player is standing in at day end, which would be
wrong for an effect that counts the whole grid. ON_DAY_END_ALL is broadcast
from Game._terminate to every room placed on the grid (mirroring
Hook.ON_DRAFT_ROOM's broadcast in Game._place_room), so this handler runs
whenever the Clock Tower is placed, regardless of where the player ends the
day. See tests/test_effect_hooks.py for the hook's own generic firing
mechanics and tests/test_carryover.py for the DayChain-driven next-day key
grant.
"""

from __future__ import annotations

import copy

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import DraftContext, _apply_category_bias
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DeckState, GameState

DIRECTION = S
TARGET_CELL = 12

# The wiki's Cargo Rooms table (Type HOLDS "Tomorrow"), fetched 2026-08-11:
# Billiard Room (Break Room upgrade), Clock Tower, Coat Check, Freezer,
# Hallway (its "tomorrow" upgrade), Mail Room plus its three upgrades (Same
# Day/No Contact/Freight), Morning Room, Planetarium, Sauna -- 12 room
# records in total.
TOMORROW_ROOM_IDS = {
    "clock_tower",
    "coat_check",
    "freezer",
    "mail_room",
    "mail_room__ix89",
    "mail_room__ix90",
    "mail_room__ix91",
    "morning_room",
    "planetarium",
    "sauna",
    "hallway__ix76",
    "break_room__ix11",
}

# Room.idx is the room's fixed position in rooms.json; a reorder or insertion
# ahead of any of these would shift it. Pinned so a future edit to rooms.json
# trips this test rather than silently renumbering every room.
TOMORROW_ROOM_IDX = {
    "clock_tower": 146,
    "coat_check": 64,
    "freezer": 69,
    "mail_room": 65,
    "mail_room__ix89": 66,
    "mail_room__ix90": 67,
    "mail_room__ix91": 68,
    "morning_room": 127,
    "planetarium": 163,
    "sauna": 63,
    "hallway__ix76": 102,
    "break_room__ix11": 22,
}


def _registry_with_forced_bias(registry: Registry, condition: str) -> Registry:
    """A copy of ``registry`` whose ``condition`` category-bias entry always fires."""
    neutered = copy.copy(registry)
    priority = copy.deepcopy(registry.priority)
    for entry in priority["category_biases"]:
        if entry.get("condition") == condition:
            entry["chance"] = 1.0
    object.__setattr__(neutered, "priority", priority)
    return neutered


def test_clock_tower_selectable_by_a_blueprint_category_targeted_draw():
    """With Royal Scepter's scepter_blueprint bias forced to fire and a deck
    holding ONLY Clock Tower's card, the bias deals Clock Tower in place of
    the original draw -- unreachable unless its category really is
    "blueprint" rather than the pool name "studio_addition"."""
    registry = _registry_with_forced_bias(Registry.load(), "scepter_blueprint")
    clock_tower = registry.by_id["clock_tower"]
    assert clock_tower.category == "blueprint"

    state = GameState()
    state.decks = [DeckState() for _ in range(8)]
    deck_idx = clock_tower.rarity_idx * 2 + (0 if clock_tower.is_free else 1)
    state.decks[deck_idx] = DeckState(order=[clock_tower.idx])
    state.shops.scepter_color = "blueprint"
    ctx = DraftContext(state, registry, GameConfig(), Rng(0), set(), None)
    placeholder = registry.by_id["closet"]

    # is_gem must match the deck Clock Tower's card actually sits in (deck_idx
    # above), or the round's Free/Gem Draw gate would hide the only card.
    result = _apply_category_bias(ctx, placeholder, slot=1, cell=TARGET_CELL,
                                  entry_dir=DIRECTION, exclude=set(),
                                  is_gem=not clock_tower.is_free)

    assert result.id == "clock_tower"


# ==================================================== TOMORROW-ROOM TYPING

def test_tomorrow_room_membership_is_exactly_the_researched_set(registry):
    """Every room the wiki's Cargo Rooms table tags Type HOLDS "Tomorrow"
    answers is_category("tomorrow"), and no other room does -- membership is
    scoped to exactly the researched 12, not accidentally global."""
    tomorrow_ids = {r.id for r in registry.rooms if r.is_category("tomorrow")}
    assert tomorrow_ids == TOMORROW_ROOM_IDS


def test_a_non_tomorrow_room_does_not_answer_is_category_tomorrow(registry):
    """A room absent from the researched list (Closet) is not Tomorrow-typed."""
    assert not registry.by_id["closet"].is_category("tomorrow")


def test_tomorrow_rooms_keep_their_original_idx(registry):
    """Typing the 12 Tomorrow rooms edited existing rooms.json records in
    place; it must not have inserted or reordered anything, which would
    silently renumber every later room's Room.idx."""
    for room_id, expected_idx in TOMORROW_ROOM_IDX.items():
        assert registry.by_id[room_id].idx == expected_idx, room_id
    assert len(registry.rooms) == 170


# ============================================================ DAY-END TALLY

def _place(game: Game, room_id: str, cell: int) -> None:
    """Place ``room_id`` on the grid via a normal draft-style placement."""
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, room.door_mask)


def test_clock_tower_counts_itself(cfg):
    """With ONLY the Clock Tower standing (no other Tomorrow room), the
    day-end tally is 1 -- the ruling's explicit point that the Clock Tower
    counts itself."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    g.state.steps = 0
    g._check_termination()
    assert g.state.clock_tower_tomorrow_keys == 1


def test_clock_tower_counts_every_other_tomorrow_room_present(cfg):
    """With the Clock Tower plus two other Tomorrow rooms standing, the tally
    is 3: one for the Clock Tower itself and one per other Tomorrow room."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    _place(g, "sauna", 7)
    _place(g, "freezer", 8)
    g.state.steps = 0
    g._check_termination()
    assert g.state.clock_tower_tomorrow_keys == 3


def test_no_clock_tower_grants_nothing_even_with_other_tomorrow_rooms(cfg):
    """Without the Clock Tower present, the tally stays 0 no matter how many
    other Tomorrow rooms are standing -- the grant is the Clock Tower's own
    effect, not an ambient count."""
    g = Game(cfg, seed=1)
    _place(g, "sauna", 7)
    _place(g, "freezer", 8)
    g.state.steps = 0
    g._check_termination()
    assert g.state.clock_tower_tomorrow_keys == 0


def test_non_tomorrow_rooms_placed_do_not_inflate_the_tally(cfg):
    """A non-Tomorrow room (Closet) standing alongside the Clock Tower does
    not add to the count -- the tally is over Tomorrow-category rooms only."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    _place(g, "closet", 7)
    g.state.steps = 0
    g._check_termination()
    assert g.state.clock_tower_tomorrow_keys == 1


def test_a_tomorrow_room_present_without_being_drafted_still_counts(cfg):
    """A Tomorrow room written directly onto the grid -- present in the
    mansion without having gone through a draft this day, the same way the
    Foundation re-appears on the grid at reset() without being re-drafted --
    still counts. This pins that the tally scans grid presence, not the
    drafted_rooms list."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    sauna = g.registry.by_id["sauna"]
    g.state.grid[7] = sauna.idx            # present, but never placed via _place_room
    g.state.steps = 0
    g._check_termination()

    assert sauna.name not in g.drafted_rooms
    assert g.state.clock_tower_tomorrow_keys == 2


def test_tally_is_over_the_grid_at_day_end_not_drafted_room_count(cfg):
    """Drafting many non-Tomorrow rooms this day does not change the tally --
    it is a snapshot of what is standing on the grid at day end, not a count
    of drafts made."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    for cell, room_id in ((7, "closet"), (8, "utility_closet"), (9, "sauna")):
        _place(g, room_id, cell)
    g.state.steps = 0
    g._check_termination()

    assert len(g.drafted_rooms) == 4          # clock_tower, closet, utility_closet, sauna
    assert g.state.clock_tower_tomorrow_keys == 2   # clock_tower + sauna only


def test_tally_still_runs_when_the_day_ends_off_grid_entirely(cfg):
    """The day ending off the 5x9 grid altogether -- inside today's drafted
    outer room, nowhere near the Clock Tower's own cell -- still runs the
    tally: Hook.ON_DAY_END_ALL is broadcast over state.grid regardless of
    where the player physically is when the day terminates, unlike the
    room-the-day-ends-in-only ON_DAY_END."""
    g = Game(cfg, seed=1)
    _place(g, "clock_tower", 6)
    _place(g, "sauna", 7)
    outer_room = g.outer_rooms[0]
    g.placed_ids.add(outer_room.id)
    g.state.outer_room_drafted = True
    g.state.area = outer_room.id
    g.state.steps = 0

    g._check_termination()

    assert g.is_done()[0]
    assert g.state.clock_tower_tomorrow_keys == 2
