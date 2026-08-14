"""Guess Bedroom (guess_bedroom__ix70): secretly mimics a Bedroom in the pool.

blueprince.wiki.gg/wiki/Guest_Bedroom/Upgrades (Guess tab): "loses its usual
ability of providing 10 steps on entry and instead mimics another Bedroom.
When it is drafted, it secretly chooses and mimics a Bedroom which is
currently in your draft pool."
"""

from __future__ import annotations

import dataclasses

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S

from luck_utils import suppress_luck

ROOM_ID = "guess_bedroom__ix70"

NEVER_SELECTED_IDS = (
    ROOM_ID,
    "her_ladyships_chamber",
    "master_bedroom",
    "spare_bedroom__ix131",
    "servants_spare_quarters__ix134",
    "her_ladyships_spare_room__ix135",
    "spare_master_bedroom__ix136",
)

AQUARIUM_IDS = (
    "aquarium",
    "goldfish_aquarium__ix2",
    "starfish_aquarium__ix3",
    "electric_eel_aquarium__ix4",
)


def test_all_six_never_selected_ids_exist_in_the_registry(registry):
    """Guards the exclusion list itself: every id it names must be a real
    room, or the exclusion would silently protect nothing."""
    for rid in NEVER_SELECTED_IDS:
        assert rid in registry.by_id, f"{rid!r} is not a real room id"


def test_drafting_records_a_bedroom_category_mimic(registry, cfg):
    """Drafting the Guess Bedroom picks some Bedroom-category room from the
    pool and records its id on GameState, ready for later hooks to delegate
    to -- never itself."""
    guess = registry.by_id[ROOM_ID]
    g = Game(cfg, seed=7)
    g._place_room(guess, 7, guess.door_mask)
    mimic_id = g.state.guess_bedroom_mimic_id
    assert mimic_id is not None
    assert registry.by_id[mimic_id].is_category("bedroom")
    assert mimic_id != ROOM_ID


def test_same_seed_yields_the_same_pick(registry, cfg):
    """Replaying the same seed against the same pool resolves to the same
    mimic id both times -- the draw uses its own seeded RNG substream."""
    guess = registry.by_id[ROOM_ID]
    picks = []
    for _ in range(2):
        g = Game(cfg, seed=42, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        picks.append(g.state.guess_bedroom_mimic_id)
    assert picks[0] is not None
    assert picks[0] == picks[1]


@pytest.mark.parametrize("extra_unlock", [
    ROOM_ID,
    "spare_bedroom__ix131",
    "servants_spare_quarters__ix134",
    "her_ladyships_spare_room__ix135",
    "spare_master_bedroom__ix136",
])
def test_never_selected_ids_are_never_picked(registry, extra_unlock):
    """Sweeping seeds with each never-selected upgrade variant unlocked (so
    it is genuinely present in the draft pool) confirms none of the six ids
    is ever chosen; Her Ladyship's Chamber and Master Bedroom need no such
    unlock, since both sit in the always-present base pool already."""
    upgrade_cfg = GameConfig(upgrade_disks=frozenset({extra_unlock}))
    guess = registry.by_id[ROOM_ID]
    for seed in range(25):
        g = Game(upgrade_cfg, seed=seed, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        assert g.state.guess_bedroom_mimic_id not in NEVER_SELECTED_IDS


def test_aquarium_family_is_never_picked(registry):
    """The Aquarium family is excluded from the mimic pool, since Room.is_category
    is not state-aware for a single mimicked cell; swept across both the
    always-present base Aquarium and an unlocked variant."""
    guess = registry.by_id[ROOM_ID]
    for seed in range(15):
        g = Game(GameConfig(), seed=seed, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        assert g.state.guess_bedroom_mimic_id not in AQUARIUM_IDS

    variant_cfg = GameConfig(upgrade_disks=frozenset({"goldfish_aquarium__ix2"}))
    for seed in range(15):
        g = Game(variant_cfg, seed=seed, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        assert g.state.guess_bedroom_mimic_id not in AQUARIUM_IDS


def test_banned_room_is_excluded_from_mimic_pool(registry):
    """A Repellent-banned floorplan is never mimicked, across a sweep of
    seeds -- decks.eligible_pool already drops banned rooms from the pool."""
    banned_cfg = GameConfig(banned_rooms=frozenset({"bedroom"}))
    guess = registry.by_id[ROOM_ID]
    for seed in range(40):
        g = Game(banned_cfg, seed=seed, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        assert g.state.guess_bedroom_mimic_id != "bedroom"


def test_banned_hovel_is_still_selectable(registry):
    """The Hovel bypasses Repellent bans entirely: with every other
    Bedroom-category base-pool room ALSO banned, the mimic still resolves to
    the (banned) Hovel instead of failing."""
    banned_cfg = GameConfig(banned_rooms=frozenset({
        "bedroom", "boudoir", "guest_bedroom", "maids_chamber",
        "nursery", "servants_quarters", "bunk_room", "hovel",
    }))
    guess = registry.by_id[ROOM_ID]
    for seed in range(5):
        g = Game(banned_cfg, seed=seed, registry=registry)
        g._place_room(guess, 7, guess.door_mask)
        assert g.state.guess_bedroom_mimic_id == "hovel"


def test_mimic_fails_with_no_valid_option_and_no_hovel(registry, cfg):
    """When the candidate pool is exhausted AND the Hovel itself is
    unavailable, the mimic fails: guess_bedroom_mimic_id stays None and the
    room grants nothing on entry (no leftover +10 steps either)."""
    stripped = dataclasses.replace(
        registry, by_id={k: v for k, v in registry.by_id.items() if k != "hovel"})
    banned_cfg = GameConfig(banned_rooms=frozenset({
        "bedroom", "boudoir", "guest_bedroom", "maids_chamber",
        "nursery", "servants_quarters", "bunk_room",
        "her_ladyships_chamber", "master_bedroom",
    }))
    guess = stripped.by_id[ROOM_ID]
    g = Game(banned_cfg, seed=0, registry=stripped)
    suppress_luck(g)  # isolate the mimic failure path from the room's own item luck roll
    steps0, gems0, keys0 = g.state.steps, g.state.gems, g.state.keys
    g._place_room(guess, 7, guess.door_mask)
    g._enter(7)
    assert g.state.guess_bedroom_mimic_id is None
    assert (g.state.steps, g.state.gems, g.state.keys) == (steps0, gems0, keys0)


def test_guess_bedroom_grants_no_steps_of_its_own(registry, cfg):
    """Unlike the base Guest Bedroom's +10 steps, the Guess Bedroom's own
    effects list is empty: with a mimic that itself grants nothing (Boudoir),
    entering it changes no resource."""
    guess = registry.by_id[ROOM_ID]
    g = Game(cfg, seed=0)
    g.state.guess_bedroom_mimic_id = "boudoir"
    g._place_room(guess, 7, guess.door_mask)
    steps0 = g.state.steps
    g._enter(7)
    assert g.state.steps == steps0


def test_boudoir_mimic_has_no_effect(registry, cfg):
    """Boudoir mimicry is forced to a no-op (published: "the Boudoir has no
    standard effect"), and also sidesteps her_ladyships_chamber.py's
    pay_boudoir_bonus room_hook, which is registered under the same id and
    would otherwise wrongly pay out an unarmed Her Ladyship's bonus."""
    guess = registry.by_id[ROOM_ID]
    g = Game(cfg, seed=0)
    suppress_luck(g)  # isolate the (no-op) mimic effect from the room's own item luck roll
    g.state.guess_bedroom_mimic_id = "boudoir"
    g.state.her_ladyships_chamber_boudoir_armed = True  # would pay 10 steps if wrongly triggered
    g._place_room(guess, 7, guess.door_mask)
    steps0, gems0, keys0 = g.state.steps, g.state.gems, g.state.keys
    g._enter(7)
    assert (g.state.steps, g.state.gems, g.state.keys) == (steps0, gems0, keys0)


def test_bedroom_mimic_grants_two_steps_and_retriggers_on_re_entry(registry, cfg):
    """Bedroom mimicry pays 2 steps on every arrival, including re-entry --
    unlike a normal room's ON_ENTER grant, which the engine only ever fires
    once per cell. "Does not become an Entry Room" per the wiki, i.e. it
    keeps paying out rather than going stale after the first visit."""
    guess = registry.by_id[ROOM_ID]
    corridor = registry.by_id["corridor"]
    a, b = 7, 12
    g = Game(cfg, seed=0)
    g.state.guess_bedroom_mimic_id = "bedroom"
    g._place_room(corridor, a, N | S)
    g._place_room(guess, b, N | S)
    g.state.pos = a
    g.state.entered[a] = True

    before_first = g.state.steps
    g.move(N)  # a -> b: first arrival, costs 1 step, Bedroom mimic grants 2
    assert g.state.steps == before_first - 1 + 2

    g.move(S)  # b -> a: costs 1 step, no grant (corridor)
    before_second = g.state.steps
    g.move(N)  # a -> b: second arrival, costs 1 step, must grant 2 again
    assert g.state.steps == before_second - 1 + 2


def test_nursery_mimic_grants_steps_on_bedroom_drafts_including_itself(registry, cfg):
    """Nursery mimicry adds the persistent "5 steps per Bedroom drafted"
    effect for the rest of the day, firing on the Guess Bedroom's own draft
    (include_self, since it is itself a Bedroom) and on every later one."""
    guess = registry.by_id[ROOM_ID]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    g.state.guess_bedroom_mimic_id = "nursery"
    steps0 = g.state.steps

    g._place_room(guess, 7, guess.door_mask)
    assert g.state.steps == steps0 + 5, "must fire on its own draft (include_self)"

    g._place_room(bedroom, 8, bedroom.door_mask)
    assert g.state.steps == steps0 + 10, "must keep firing for later Bedroom drafts"


def test_servants_quarters_mimic_grants_a_key_per_bedroom(registry, cfg):
    """Servant's Quarters mimicry grants 1 key per Bedroom-category room on
    the grid, counting the Guess Bedroom itself alongside two filler
    Bedrooms."""
    guess = registry.by_id[ROOM_ID]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    suppress_luck(g)  # isolate the mimic's key grant from the room's own item luck roll
    g.state.guess_bedroom_mimic_id = "servants_quarters"
    for cell in (8, 9):
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(guess, 7, guess.door_mask)
    keys0 = g.state.keys

    g._enter(7)

    assert g.state.keys == keys0 + 3  # 2 fillers + the Guess Bedroom itself


def test_servants_quarters_mimic_caps_at_fifteen(registry, cfg):
    """The published cap of 15 keys applies to the mimic, inherited from the
    real room's own capped grant_per_category tag rather than reimplemented
    here -- a house with 21 Bedrooms still pays out only 15."""
    guess = registry.by_id[ROOM_ID]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    suppress_luck(g)  # isolate the capped mimic payout from the room's own item luck roll
    g.state.guess_bedroom_mimic_id = "servants_quarters"
    filler_cells = range(10, 30)  # 20 filler Bedrooms
    for cell in filler_cells:
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(guess, 30, guess.door_mask)  # 21st Bedroom-category room
    keys0 = g.state.keys

    g._enter(30)

    assert g.state.keys == keys0 + 15


def test_real_servants_quarters_caps_at_fifteen(registry, cfg):
    """The actual Servant's Quarters pays at most 15 keys, however many Bedrooms stand.

    The cap is published for the real room, not only for the Guess Bedroom mimicking
    it; without it a late-day Bedroom-heavy house mints unbounded keys on one entry.
    """
    sq = registry.by_id["servants_quarters"]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    for cell in range(10, 30):  # 20 Bedrooms, well past the cap
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(sq, 30, sq.door_mask)
    keys0 = g.state.keys

    g._enter(30)

    assert g.state.keys == keys0 + 15, "Servant's Quarters must stop paying at 15 keys"


def test_servants_quarters_under_the_cap_still_pays_per_bedroom(registry, cfg):
    """Below the cap the payout is one key per Bedroom, counting the room itself.

    Pins two things at once: that the cap is inert under 15 rather than a flat
    payout, and that the Servant's Quarters is bedroom-category so it counts itself.
    """
    sq = registry.by_id["servants_quarters"]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    for cell in range(10, 14):  # 4 Bedrooms, plus the Servant's Quarters itself = 5
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(sq, 30, sq.door_mask)
    keys0 = g.state.keys

    g._enter(30)

    assert g.state.keys == keys0 + 5, "4 fillers plus the Servant's Quarters itself"


def test_real_servants_spare_quarters_caps_at_fifteen(registry, cfg):
    """The upgraded Servant's Spare Quarters pays at most 15 keys, however many
    Bedrooms stand -- the published cap applies to the upgrade variant too, not
    only to the base room it was missed on."""
    sq = registry.by_id["servants_spare_quarters__ix134"]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    for cell in range(10, 30):  # 20 Bedrooms, well past the cap
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(sq, 30, sq.door_mask)
    keys0 = g.state.keys

    g._enter(30)

    assert g.state.keys == keys0 + 15, "Servant's Spare Quarters must stop paying at 15 keys"


def test_servants_spare_quarters_under_the_cap_still_pays_per_bedroom(registry, cfg):
    """Below the cap the Servant's Spare Quarters pays one key per Bedroom,
    counting the room itself, the same as the base room's own uncapped range."""
    sq = registry.by_id["servants_spare_quarters__ix134"]
    bedroom = registry.by_id["bedroom"]
    g = Game(cfg, seed=0)
    for cell in range(10, 14):  # 4 Bedrooms, plus the Servant's Spare Quarters itself = 5
        g.state.grid[cell] = bedroom.idx
        g.state.placed_doors[cell] = bedroom.door_mask
    g._place_room(sq, 30, sq.door_mask)
    keys0 = g.state.keys

    g._enter(30)

    assert g.state.keys == keys0 + 5, "4 fillers plus the Servant's Spare Quarters itself"


def test_bunk_room_mimic_counts_as_two_bedrooms(registry, cfg):
    """Bunk Room mimicry is a flat 2-Bedrooms count, read
    through bedroom_bonus like the real Bunk Room's counts_as_bedrooms tag."""
    guess = registry.by_id[ROOM_ID]
    g = Game(cfg, seed=0)
    g.state.guess_bedroom_mimic_id = "bunk_room"
    bonus_before = g.bedroom_bonus

    g._place_room(guess, 7, guess.door_mask)

    assert g.bedroom_bonus == bonus_before + 1  # counts_as_bedrooms(amount=2) adds (2 - 1)


def test_bunk_room_upgrade_variant_mimic_skips_its_own_doubling(registry, cfg):
    """Mimicking an upgraded Bunk Room variant (e.g. bunk_room__ix20, "double
    KEYS on exactly 2 Hallways") still counts only as a flat 2 Bedrooms: its
    ON_DRAFT_ROOM doubling room_hook is deliberately not mimicked, since the
    Bunk Room mimicry is limited to the published flat-2 count."""
    guess = registry.by_id[ROOM_ID]
    hallway_a = registry.by_id["hallway"]
    hallway_b = registry.by_id["corridor"]
    g = Game(cfg, seed=0)
    g.state.guess_bedroom_mimic_id = "bunk_room__ix20"
    g.state.keys = 5
    g._place_room(hallway_a, 8, hallway_a.door_mask)
    g._place_room(hallway_b, 9, hallway_b.door_mask)

    g._place_room(guess, 7, guess.door_mask)  # exactly 2 Hallways already on the grid

    assert g.state.keys == 5, "the doubling room_hook must not fire for a mimic"
