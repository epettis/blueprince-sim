"""Her Ladyship's Chamber / Her Ladyship's Spare Room: pre-armed one-shot
Boudoir/Walk-In Closet entry bonuses.

Each test places rooms directly via Game._place_room (as the other room
tests do) rather than driving the full deal pipeline, then walks the player
in with Game._enter to fire ON_ENTER.

Boudoir's own additional_max=1 roll is luck-gated, so the step tests floor
luck to 0 to suppress it deterministically (as tests/rooms/test_courtyard.py
and test_cloister.py's Mila tests already do). Walk-In Closet instead
guarantees 4 "random" items regardless of luck, so the gem tests use a
same-seed baseline-vs-bonus diff instead: rng.py's named substreams make that
guaranteed roll's outcome independent of what else was placed first, so the
diff isolates exactly the Chamber/Spare Room bonus.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game

CHAMBER_CELL = 7  # rank 2, col 2 -- any on-grid cell works; _enter bypasses door legality
BOUDOIR_CELL = 12  # rank 3, col 2


def _place(g, room, cell):
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask


def _closet_gem_delta(registry, cfg, extra_rooms) -> int:
    """Gems gained entering a fresh Walk-In Closet, after first drafting
    ``extra_rooms`` (e.g. the Chamber/Spare Room) at earlier cells.

    Same seed every call, so the Closet's own guaranteed 4-random-item roll
    (rng.py named substreams) is identical regardless of what else was
    placed -- the return value isolates whatever ``extra_rooms`` added.
    """
    g = Game(cfg, seed=1)
    for i, room in enumerate(extra_rooms):
        g._place_room(room, CHAMBER_CELL + i, room.door_mask)
    closet = registry.by_id["walk_in_closet"]
    _place(g, closet, BOUDOIR_CELL)
    gems_before = g.state.gems
    g._enter(BOUDOIR_CELL)
    return g.state.gems - gems_before


def test_boudoir_after_the_chamber_grants_ten_steps_only_the_first_time(registry, cfg):
    """Entering a Boudoir after Her Ladyship's Chamber has been drafted grants
    10 steps exactly once; re-entering the same Boudoir grants nothing more."""
    g = Game(cfg, seed=1)
    g.state.luck = 0  # floors Boudoir's own luck-gated additional_max roll to 0
    chamber = registry.by_id["her_ladyships_chamber"]
    boudoir = registry.by_id["boudoir"]
    g._place_room(chamber, CHAMBER_CELL, chamber.door_mask)
    _place(g, boudoir, BOUDOIR_CELL)

    steps_before = g.state.steps
    g._enter(BOUDOIR_CELL)
    assert g.state.steps == steps_before + 10

    steps_after_first = g.state.steps
    g._enter(BOUDOIR_CELL)  # re-entry: ON_ENTER never refires for an already-entered cell
    assert g.state.steps == steps_after_first


def test_walk_in_closet_after_the_chamber_grants_three_gems(registry, cfg):
    """Entering the Walk-In Closet after Her Ladyship's Chamber has been
    drafted grants 3 gems more than entering it with no Chamber at all."""
    chamber = registry.by_id["her_ladyships_chamber"]
    baseline = _closet_gem_delta(registry, cfg, [])
    with_chamber = _closet_gem_delta(registry, cfg, [chamber])
    assert with_chamber == baseline + 3


def test_boudoir_upgrade_variants_also_pay_the_bonus(registry, cfg):
    """Boudoir's three upgrade variants (still literally "Boudoir", just with
    a stacked gem bonus) count as the target room too."""
    for variant_id in ("boudoir__ix16", "boudoir__ix17", "boudoir__ix18"):
        g = Game(cfg, seed=1)
        g.state.luck = 0
        chamber = registry.by_id["her_ladyships_chamber"]
        variant = registry.by_id[variant_id]
        g._place_room(chamber, CHAMBER_CELL, chamber.door_mask)
        _place(g, variant, BOUDOIR_CELL)

        steps_before = g.state.steps
        g._enter(BOUDOIR_CELL)
        assert g.state.steps == steps_before + 10, variant_id


def test_boudoir_with_no_chamber_drafted_grants_nothing(registry, cfg):
    """Entering a Boudoir with no Her Ladyship's Chamber (or Spare Room) on
    the estate grants no bonus steps -- only Boudoir's own base +1 gem."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    boudoir = registry.by_id["boudoir"]
    _place(g, boudoir, BOUDOIR_CELL)

    steps_before = g.state.steps
    g._enter(BOUDOIR_CELL)
    assert g.state.steps == steps_before


def test_chamber_and_spare_room_together_grant_twenty_steps(registry, cfg):
    """Her Ladyship's Chamber and Her Ladyship's Spare Room stack: with both
    drafted, entering one Boudoir pays both 10-step bonuses, for 20 total."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    chamber = registry.by_id["her_ladyships_chamber"]
    spare_room = registry.by_id["her_ladyships_spare_room__ix135"]
    boudoir = registry.by_id["boudoir"]
    g._place_room(chamber, CHAMBER_CELL, chamber.door_mask)
    g._place_room(spare_room, CHAMBER_CELL + 5, spare_room.door_mask)
    _place(g, boudoir, BOUDOIR_CELL)

    steps_before = g.state.steps
    g._enter(BOUDOIR_CELL)
    assert g.state.steps == steps_before + 20


def test_chamber_and_spare_room_together_grant_six_gems_for_the_closet(registry, cfg):
    """The same stacking applies to the Walk-In Closet's gem bonus: both
    sources pay independently, for 6 gems more than the no-Chamber baseline."""
    chamber = registry.by_id["her_ladyships_chamber"]
    spare_room = registry.by_id["her_ladyships_spare_room__ix135"]
    baseline = _closet_gem_delta(registry, cfg, [])
    with_both = _closet_gem_delta(registry, cfg, [chamber, spare_room])
    assert with_both == baseline + 6


def test_a_boudoir_already_entered_before_the_chamber_is_drafted_never_pays(registry, cfg):
    """"The first time the room is entered AFTER Her Ladyship's Chamber has
    been drafted": a Boudoir entered earlier the same day, before the Chamber
    lands, does not retroactively pay -- ON_ENTER never refires for a cell
    the engine already marked entered."""
    g = Game(cfg, seed=1)
    g.state.luck = 0
    boudoir = registry.by_id["boudoir"]
    _place(g, boudoir, BOUDOIR_CELL)
    g._enter(BOUDOIR_CELL)  # entered before any Chamber exists

    chamber = registry.by_id["her_ladyships_chamber"]
    g._place_room(chamber, CHAMBER_CELL, chamber.door_mask)

    steps_before = g.state.steps
    g._enter(BOUDOIR_CELL)  # re-entry: already entered, ON_ENTER does not refire
    assert g.state.steps == steps_before
