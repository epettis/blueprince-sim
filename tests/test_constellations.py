"""The constellation data, the night-sky mechanic, the observation key, and
what an activation does.

All thirteen records are live: five pure resource grants, seven whose effect
lands somewhere else in the engine, and the Spiral of Stars, whose payout is
indexed by a permanent word count that grows whenever a sky containing it is
generated. What these tests pin is the mechanic (a true sum-partition,
resolved at LIVE star count, under two independent per-day caps), the effect
each activation actually has DOWNSTREAM rather than the flag it sets, and the
part that cannot be changed later -- the action-space width and the
observation-space shape.

Every expected sky here is read out of the ``appearances`` table directly,
never by calling the generator: a test that asked the generator what it
generates would pass against any self-consistent wrong rule, which is exactly
the failure the partition is worth testing for.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import constellations, experiments, shops, special_items
from blueprince_sim.engine.decks import build_decks
from blueprince_sim.engine.draft import deal_draft
from blueprince_sim.engine.effects.items.telescope import ITEM_ID as TELESCOPE_ID
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import ENTRANCE_CELL, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.upgrades import root_base_id
from blueprince_sim.env import actions as A
from blueprince_sim.env import obs as O
from blueprince_sim.env.multiday import _CARRYOVER_KEYS, DayChain
from blueprince_sim.rl.train import all_unlocks_config

DATA = Path(__file__).resolve().parents[1] / "src" / "blueprince_sim" / "data"
DOC = json.loads((DATA / "constellations.json").read_text(encoding="utf-8"))
STARS = {c["id"]: c["stars"] for c in DOC["constellations"]}
APPEARANCES = DOC["appearances"]
RECORDS = DOC["constellations"]
INDEX = {c["id"]: i for i, c in enumerate(RECORDS)}
GRANTING = {c["id"]: c for c in RECORDS if "grant" in c}
MAX_SKIES = DOC["max_skies_per_day"]
MAX_CONSTELLATION_SKIES = DOC["max_constellation_skies_per_day"]

#: Eight cells with no shared doorway logic needed: the tests below drive
#: Game.view_night_sky directly at a chosen position, so only the grid contents
#: and state.pos matter. Eight is enough to exhaust MAX_SKIES using each
#: Observatory's own telescope alone.
_OBSERVATORY_CELLS = (1, 2, 3, 6, 7, 8, 11, 12)


@pytest.fixture(scope="module")
def registry() -> Registry:
    """The packaged data, loaded once and shared: the sampling tests below build
    hundreds of games and every one of them only reads it."""
    return Registry.load()


def _observatory_game(*, cells=(1,), stars=0, telescope=False, seed=0,
                      items=(), registry=None, spiral_words=0, day=None) -> Game:
    """A game standing in an Observatory at ``cells[0]`` with ``stars`` stars.

    Rooms are written onto the grid rather than drafted so the Observatory's
    own +1-star-per-draft hook does not move the star count out from under a
    test that is about the star count. ``items`` are placed straight into the
    inventory for the same reason: what is being tested is what a held item
    does to an activation's payout, not how it was found.

    ``spiral_words`` and ``day`` go through ``GameConfig`` rather than being
    written onto the state afterwards, so the Spiral tests exercise the same
    reset-seeding path a carried-over word count actually arrives by.
    """
    kwargs = {"spiral_words": spiral_words}
    if telescope or items:
        kwargs["special_items"] = True
    if day is not None:
        kwargs["day"] = day
    cfg = GameConfig(**kwargs)
    game = Game(cfg, seed=seed, registry=registry)
    room = game.registry.by_id["observatory"]
    for cell in cells:
        game.state.grid[cell] = room.idx
        game.state.placed_doors[cell] = room.door_mask
    game.state.pos = cells[0]
    game.state.stars = stars
    game.phase = Phase.NAVIGATE
    if telescope:
        game.state.inventory[TELESCOPE_ID] = 1
    for item_id in items:
        game.state.inventory[item_id] = 1
    return game


# ------------------------------------------------------------------ the rule


def test_a_night_sky_partitions_the_star_count():
    """Every night sky from 1 to 49 stars is a partition of the star count:
    the constellations shown are a set whose star values sum to exactly that
    count, never everything at or below a threshold.

    This is the mechanic itself, not a schema check -- an engine written
    against "show every constellation with stars <= N" would pass any
    range/type validation and still generate the wrong sky at every count
    above 5. tools/validate_data.py holds the same invariant as the gate that
    blocks a bad edit to the table; this pins the rule the activation code
    will be built against.
    """
    for count in range(1, 50):
        sky = APPEARANCES[str(count)]
        assert sum(STARS[c] for c in sky) == count, (
            f"{count} stars: sky {sky} sums to {sum(STARS[c] for c in sky)}"
        )


def test_no_constellation_appears_twice_in_one_sky():
    """A sky holds each constellation at most once, so its star values are a
    partition into DISTINCT parts -- 4 stars is Diamondus Minor, never The
    Twins twice."""
    for count in range(50):
        sky = APPEARANCES[str(count)]
        assert len(sky) == len(set(sky)), f"{count} stars: repeat in {sky}"


def test_the_zero_star_sky_is_the_only_count_that_does_not_sum():
    """0 stars shows the North Star (1 star) alone, the sole count whose sky
    does not sum to it.

    Asserted positively rather than as "skip 0" so the exception cannot widen:
    a second non-summing count would fail the partition test above instead of
    being silently tolerated alongside this one.
    """
    assert APPEARANCES["0"] == ["north_star"]


def test_every_constellation_appears_alone_at_its_own_star_count():
    """A constellation of N stars is the whole sky at exactly N stars -- the
    base case every larger partition is assembled from, and what makes the
    star values recoverable from the table alone."""
    for cid, stars in STARS.items():
        if stars < 50:
            assert APPEARANCES[str(stars)] == [cid], f"{stars} stars is not just {cid}"


def test_the_largest_sky_holds_seven_constellations():
    """The most constellations visible at once in the 0-49 range is 7, which is
    what the observation key's bound and any future per-sky array have to
    accommodate."""
    assert max(len(APPEARANCES[str(n)]) for n in range(50)) == 7


def test_record_order_is_ascending_by_star_value():
    """Record order in constellations.json is the action-block and obs-vector
    order, so it is positional: a reorder would silently repoint every
    ACTIVATE_CONSTELLATION id at a different constellation. Ascending stars
    pins it to one arrangement."""
    stars = [c["stars"] for c in DOC["constellations"]]
    assert stars == sorted(stars) and len(set(stars)) == len(stars)


def test_the_action_block_has_one_id_per_record():
    """The block's width and the data agree, so no record is unreachable and no
    id points past the end of the table."""
    assert A._N_CONSTELLATIONS == len(DOC["constellations"]) == 13


# ------------------------------------------------------- the action space


def test_action_space_width_is_481():
    """The constellation block's own id range, and N_ACTIONS, agree with
    docs/rl-environment.md's width-change register.

    Action ids are positional, so any PR that moves this width must state the
    before and after there (see the register) and record why -- but nothing
    below the constellation block prevents an EARLIER block (e.g. the Axe
    target range) from widening in a later, unrelated PR; that only shifts
    ids at or above the earlier block's own end, which
    test_no_existing_action_id_shifted below is what actually pins.

    N_ACTIONS is no longer REDRAW_WITH_STAR_ACTION + 1: the Pump Room panel
    block (docs/areas.md's Pump Room section) appends 21 more ids after it
    (458..478, a source pick plus a target-level pick), and the Office
    terminal block (docs/rooms.md) appends 2 more after that
    (479 Spread Gold in Estate, 480 Run Payroll), so this test only pins
    where the constellation block itself ends, not the space's final width.
    """
    assert A.ACTIVATE_CONSTELLATION_BASE == A.USE_TELESCOPE_PLANETARIUM_ACTION + 1
    assert A.VIEW_NIGHT_SKY_ACTION == A.ACTIVATE_CONSTELLATION_BASE + A._N_CONSTELLATIONS
    assert A.REDRAW_WITH_STAR_ACTION == A.VIEW_NIGHT_SKY_ACTION + 1
    assert A.REDRAW_WITH_STAR_ACTION == 457
    assert A.PUMP_SOURCE_BASE == A.REDRAW_WITH_STAR_ACTION + 1
    assert A.PUMP_LEVEL_BASE == A.PUMP_SOURCE_BASE + A._N_PUMP_SOURCES
    assert A.SPREAD_GOLD_ACTION == A.PUMP_LEVEL_BASE + A._N_PUMP_LEVELS == 479
    assert A.RUN_PAYROLL_ACTION == A.SPREAD_GOLD_ACTION + 1 == 480
    assert A.N_ACTIONS == A.RUN_PAYROLL_ACTION + 1 == 481


def test_no_existing_action_id_shifted():
    """Every action id declared before the constellation block still has the
    value the current width register commits it to -- an append, never a
    mid-array insert.

    A mid-array insert is the failure this guards: it costs nothing at import
    time and silently makes every id after the insertion point mean something
    else, which no test that only checks N_ACTIONS would catch. Ids from
    AXE_TARGET_BASE through USE_TELESCOPE_PLANETARIUM_ACTION are pinned at
    their CURRENT values, not frozen forever -- the Axe target range is
    itself a pinned-but-registry-derived width (see
    env/actions.py::_build_axe_target_ids) that can legitimately widen in its
    own dedicated, recorded PR, shifting every id from LOCK_MENU_BASE onward.
    What must never happen is a shift with no recorded width-register entry.
    """
    assert (A.OPEN_BASE, A.CHOOSE_BASE, A.REDRAW_ACTION) == (0, 180, 183)
    assert (A.OUTER_DRAFT_ACTION, A.TOGGLE_POWER_ACTION, A.SET_LEVEL_BASE) == (184, 185, 186)
    assert (A.ROTATE_ACTION, A.MOVE_TO_BASE, A.BUY_BASE) == (189, 190, 235)
    assert (A.TRADE_BASE, A.FABRICATE_BASE, A.SCEPTER_BASE) == (241, 249, 257)
    assert (A.SMASH_VASE_ACTION, A.OPEN_CONTAINER_ACTION) == (263, 264)
    assert (A.OPEN_CAR_TRUNK_ACTION, A.OPEN_VAULT_BOX_ACTION) == (265, 266)
    assert (A.LIGHT_ACTION, A.INSTALL_LEVER_ACTION, A.INSERT_DISK_ACTION) == (267, 268, 269)
    assert (A.CHOOSE_UPGRADE_BASE, A.TRAVEL_BASE, A.OPEN_SIGIL_DOOR_BASE) == (270, 273, 311)
    assert (A.START_SETUP_ACTION, A.EXP_TRIGGER_BASE, A.EXP_EFFECT_BASE) == (319, 320, 323)
    assert (A.TOGGLE_EXPERIMENT_ACTION, A.TOGGLE_DARKROOM_ACTION) == (326, 327)
    assert (A.CHOOSE_COLOUR_BASE, A.DONATE_BASE, A.TAKE_BACK_OFFERING_ACTION) == (328, 333, 373)
    assert (A.BERRY_PICK_ACTION, A.TAKE_GROTTO_CHIP_ACTION, A.CROWN_BLOCK_BASE) == (374, 375, 376)
    assert (A.AXE_TARGET_BASE, A.LOCK_MENU_BASE, A.LOCK_USE_KEY_ACTION) == (379, 428, 428)
    assert (A.LOCK_LOCKPICK_ACTION, A.LOCK_ABANDON_ACTION, A.LOCK_SPECIAL_KEY_BASE) == (
        429, 430, 431)
    assert (A.REWIND_ACTION, A.WRENCH_RARITY_BASE) == (437, 438)
    assert A.USE_TELESCOPE_PLANETARIUM_ACTION == 442


def test_no_constellation_id_is_masked_by_an_unimplemented_record():
    """Every record is implemented, so no id in the constellation block can be
    pressed into a missing payload -- and none is dead either.

    The sweep is kept from when spiral_of_stars was the one reserved slot: it
    walks played-out days on both presets and asserts that no id belonging to
    an unimplemented record ever goes legal. That set is empty today, which is
    the property being pinned -- if a record were ever flipped back to
    unimplemented, this recomputes the reserved list from the data and starts
    guarding it again without being edited.
    """
    reserved = [A.ACTIVATE_CONSTELLATION_BASE + INDEX[c["id"]]
                for c in RECORDS if not c["implemented"]]
    assert reserved == [], (
        "every constellation record is implemented; an unimplemented one would "
        "need its action id proven inert here")
    for cfg in (GameConfig(), all_unlocks_config()):
        for seed in range(6):
            game = Game(cfg, seed=seed)
            for _ in range(120):
                mask = A.action_mask(game)
                assert len(mask) == A.N_ACTIONS
                live = [i for i in reserved if mask[i]]
                assert not live, f"seed {seed}: reserved ids went legal: {live}"
                legal = [i for i, ok in enumerate(mask) if ok]
                if not legal:
                    break
                A.apply_action(game, legal[0])


def test_action_group_buckets_the_constellation_block():
    """The web UI's action_group names every id in the block, so
    tests/test_play_session.py's full-space sweep does not fall through to
    'other' -- the failure mode that only shows up once the whole space is
    walked."""
    from blueprince_sim.web.play import action_group

    for action_id in range(A.ACTIVATE_CONSTELLATION_BASE, A.N_ACTIONS):
        assert action_group(action_id) != "other"


# --------------------------------------------------------- the observation


#: Shape, bounds and dtype of every observation key as of the width commit,
#: for the fixed registry sizes passed below. The constellation key was this
#: file's own addition; "carryover" has since grown three times more: 16 -> 17
#: for the Conservatory's conservatory_floorplan_found flag, 17 -> 18 for the
#: Greenhouse's greenhouse_wall_broken flag, then 18 -> 19 for the Pump Room's
#: reservoir_13_reached flag (env/multiday.py's _CARRYOVER_KEYS); "phase" has
#: widened 8 -> 9 for Phase.PUMP_LEVEL_PENDING; and "water_levels" is a new
#: key for the Pump Room's six source levels (docs/areas.md's Pump Room section) --
#: every other row must stay exactly as it is, because a bound change is a
#: retrain trigger on the same terms as a shape change (docs/rl-environment.md).
#: "axed_rooms" stays 48 here because this call never overrides
#: observation_space()'s n_axe_targets default (48); the real env
#: (BluePrinceEnv) always passes the registry-derived count instead.
_EXPECTED_SPACE = {
    "allowance": ((1,), 0, 9999, "int16"),
    "axed_rooms": ((48,), 0, 1, "uint8"),
    "carryover": ((19,), 0, 999, "int16"),
    "constellations": ((15,), 0, 99, "int16"),
    "day": ((2,), 0, 9999, "int16"),
    "disks_held": ("Discrete", 17, "int64"),
    "disks_spent": ((1,), 0, 99, "int16"),
    "dowsing": ((2,), 0, 999, "int16"),
    "experiment": ((10,), 0, 999, "int16"),
    "fabricate": ((8,), 0, 1, "uint8"),
    "grid_ante_dist": ((9, 5), -1, 99, "int16"),
    "grid_containers": ((9, 5), 0, 9, "uint8"),
    "grid_dig": ((9, 5), 0, 9, "uint8"),
    "grid_dist": ((9, 5), -1, 99, "int16"),
    "grid_doors": ((9, 5), 0, 15, "uint8"),
    "grid_entered": ((9, 5), 0, 1, "uint8"),
    "grid_frontier": ((9, 5), 0, 15, "uint8"),
    "grid_locked": ((9, 5), 0, 15, "uint8"),
    "grid_room": ((9, 5), 0, 170, "int16"),
    "grid_sealed": ((9, 5), 0, 15, "uint8"),
    "grid_search_cost": ((9, 5), 0, 99, "uint8"),
    "grid_security": ((9, 5), 0, 15, "uint8"),
    "house_flags": ((13,), 0, 999, "int16"),
    "inventory": ((102,), 0, 99, "int16"),
    "item_state": ((12,), -2, 999, "int16"),
    "mail": ((3,), 0, 99, "int16"),
    "options": ((3, 13), -1, 999, "int16"),
    "phase": ("Discrete", 9, "int64"),
    "planetarium_planets": ((5,), 0, 1, "uint8"),
    "player_area": ("Discrete", 39, "int64"),
    "player_pos": ("Discrete", 45, "int64"),
    "prev_options": ((3, 13), -1, 999, "int16"),
    "progress": ((5,), -1, 999, "int16"),
    "resources": ((7,), -99, 999, "int16"),
    "secret_passage_colour": ("Discrete", 6, "int64"),
    "shop_stock": ((6, 5), -1, 999, "int16"),
    "shrine": ((4,), 0, 999, "int16"),
    "sigil_doors_open": ((8,), 0, 1, "uint8"),
    "stage": ("Discrete", 3, "int64"),
    "stars": ((1,), 0, 9999, "int16"),
    "trade_offers": ((8, 2), -1, 999, "int16"),
    "treasure_trove_piles": ((1,), 0, 32, "int16"),
    "upgrade_options": ((3,), -1, 999, "int16"),
    "upgrade_slots": ((16,), 0, 1, "uint8"),
    "water_levels": ((6,), 0, 14, "uint8"),
    "wrench_rarity": ((8,), 0, 4, "uint8"),
}


def _signature(space) -> dict:
    out = {}
    for key, sub in space.spaces.items():
        if hasattr(sub, "low"):
            out[key] = (tuple(int(d) for d in sub.shape),
                        int(np.min(sub.low)), int(np.max(sub.high)), str(sub.dtype))
        else:
            out[key] = ("Discrete", int(sub.n), str(sub.dtype))
    return out


def test_only_the_constellation_key_was_added_to_the_observation_space():
    """The observation space matches this pinned full-key snapshot exactly.

    Originally "the constellation key was this file's own addition and
    nothing else moves"; three more width changes have landed since (see the
    comment above _EXPECTED_SPACE) and each updated this same snapshot rather
    than adding a parallel test, so the name is now a historical label, not a
    literal description of what this test guards today.

    Both a resized key and a widened BOUND matter -- a resized key silently
    reinterprets trained weights, and a widened bound does the same to a
    normalising policy, so the snapshot pins low and high as well as shape.
    Registry sizes are passed as literals so the expected table is a function
    of the code alone, not of how many rooms happen to be in rooms.json.
    """
    actual = _signature(O.observation_space(170, 102, 8, 38))
    assert actual == _EXPECTED_SPACE


def test_the_constellation_observation_reports_activations_skies_and_this_cell():
    """[0:13] counts today's activations per record, [13] skies generated today,
    [14] un-activated constellations in the sky at the player's cell.

    [14] is the one that has to be per-cell: with two Observatories holding
    different skies, an agent standing in one must not see the other's
    remaining value, or "walk to the other Observatory" becomes invisible.
    """
    game = _observatory_game(cells=(1, 2), stars=6)
    assert not O.encode(game)["constellations"].any()

    game.view_night_sky()  # 6 stars -> the_twins + diamondus_minor
    encoded = O.encode(game)["constellations"]
    assert encoded[A._N_CONSTELLATIONS] == 1  # one sky generated today
    assert encoded[A._N_CONSTELLATIONS + 1] == 2  # both still un-activated here
    assert not encoded[:A._N_CONSTELLATIONS].any()  # nothing activated yet

    game.activate_constellation(INDEX["diamondus_minor"])
    encoded = O.encode(game)["constellations"]
    assert encoded[INDEX["diamondus_minor"]] == 1
    assert encoded[A._N_CONSTELLATIONS + 1] == 1  # one left in this sky

    # Standing at the other Observatory: no sky there yet, so [14] is 0 while
    # the day-scoped counts at [0:13] and [13] are unchanged.
    game.state.pos = 2
    encoded = O.encode(game)["constellations"]
    assert encoded[INDEX["diamondus_minor"]] == 1
    assert encoded[A._N_CONSTELLATIONS] == 1
    assert encoded[A._N_CONSTELLATIONS + 1] == 0


def test_the_constellation_observation_keeps_its_dtype_and_bound_in_play():
    """The key stays int16 and within the space's 0..99 bound across real play,
    so the encoder cannot drift from the declared Box."""
    for seed in range(5):
        game = Game(GameConfig(), seed=seed)
        for _ in range(40):
            encoded = O.encode(game)["constellations"]
            assert encoded.shape == (O.CONSTELLATION_OBS_LEN,)
            assert encoded.dtype == np.int16
            assert encoded.min() >= 0 and encoded.max() <= 99
            mask = A.action_mask(game)
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            A.apply_action(game, legal[0])


def test_the_observation_width_is_pinned_not_derived():
    """CONSTELLATION_OBS_LEN tracks the action block's own record count, so the
    two cannot drift, and both are constants rather than registry reads -- a
    fourteenth record must not be able to move an observation width that this
    PR commits permanently."""
    assert O.CONSTELLATION_OBS_LEN == A._N_CONSTELLATIONS + 2 == 15


# ------------------------------------------------------- the sky, end to end


def test_the_generated_sky_is_the_tables_partition_at_the_live_star_count():
    """At each star count, the sky Game.view_night_sky generates is exactly the
    set the appearances table names for that count.

    The expectation comes from the table, never from a second call into the
    generator: this is the check a "show everything with stars <= N" gate
    cannot pass. At 25 stars a threshold would show all seven constellations
    up to 20; the partition shows exactly the five that sum to 25.
    """
    for count in (0, 1, 3, 6, 13, 25, 33, 40, 49):
        game = _observatory_game(stars=count)
        assert game.view_night_sky() == tuple(APPEARANCES[str(count)]), (
            f"{count} stars generated the wrong sky")


def test_a_sky_above_the_tables_range_still_sums_to_its_star_count():
    """Star counts run past the table's 49: stars are save-scoped and grow +1
    per Observatory draft, so a long attempt reaches the Ink Well's 50 and the
    Spiral's 100, where the table repeats against those anchors.

    The property is the same partition rule, checked by summing rather than by
    table lookup, because past 49 there is no table row to compare against.
    The band boundaries are the failure worth catching: at exactly 50 stars,
    reusing the table's 0-star row (its one entry that does not sum) would add
    a phantom North Star and make the sky total 51.
    """
    game = _observatory_game()
    registry = game.registry.constellations
    for count in (50, 51, 63, 99, 100, 101, 149, 150, 199):
        sky = registry.sky_at(count)
        assert sum(STARS[c] for c in sky) == count, f"{count} stars: {sky} does not sum"
        assert len(sky) == len(set(sky)), f"{count} stars: repeat in {sky}"


def test_each_observatory_offers_its_own_sky_and_a_held_telescope_adds_one():
    """Viewing is per-CELL, twice: the room's own telescope once, plus a held
    Telescope once more, which generates an additional night sky for each
    Observatory it is used in.

    Keyed by cell rather than room id because game.room_cells keeps only the
    lowest cell per id, so with two Observatories it cannot say which one has
    already been looked through -- the second would silently inherit the
    first's spent sources.
    """
    game = _observatory_game(cells=(1, 2), stars=6, telescope=True)
    assert game.can_view_night_sky()
    game.view_night_sky()  # cell 1, the room's own telescope
    assert game.can_view_night_sky()
    game.view_night_sky()  # cell 1, the held Telescope
    assert not game.can_view_night_sky(), "a third sky at one Observatory"

    game.state.pos = 2  # the second Observatory re-offers both sources
    assert game.can_view_night_sky()
    game.view_night_sky()
    assert game.can_view_night_sky()
    game.view_night_sky()
    assert not game.can_view_night_sky()
    assert len(game.state.night_skies[1]) == len(game.state.night_skies[2]) == 2


def test_a_constellation_activates_once_per_sky_so_two_skies_fire_it_twice():
    """Activation is tracked per sky, so the held Telescope's extra sky at the
    same Observatory lets one constellation grant its resource a second time --
    the documented "constellations activate twice"."""
    game = _observatory_game(stars=4, telescope=True)  # 4 stars -> diamondus_minor
    index = INDEX["diamondus_minor"]
    game.view_night_sky()
    assert game.can_activate_constellation(index)
    game.activate_constellation(index)
    assert not game.can_activate_constellation(index), "re-fired within one sky"
    assert game.state.gems == 1

    game.view_night_sky()  # the held Telescope's second sky at this cell
    assert game.can_activate_constellation(index)
    game.activate_constellation(index)
    assert game.state.gems == 2


# ------------------------------------------------------------- the two caps


def test_only_the_first_seven_skies_of_a_day_hold_constellations():
    """The 7-sky cap: skies 1..7 generate the table's partition, and the eighth
    comes back EMPTY -- only the first seven night skies generated per day can
    actually consist of constellations.

    This seven counts SKIES PER DAY and is unrelated to the seven
    CONSTELLATIONS in the widest sky (at 40 and 49 stars). The eighth sky is
    still viewed, not refused: modelling it as an illegal action would be a
    different mechanic, so the assertion is on its contents, not on the mask.
    """
    game = _observatory_game(cells=_OBSERVATORY_CELLS, stars=6)
    expected = tuple(APPEARANCES["6"])
    for i, cell in enumerate(_OBSERVATORY_CELLS):
        game.state.pos = cell
        assert game.can_view_night_sky(), f"sky {i + 1} could not be viewed"
        sky = game.view_night_sky()
        if i < MAX_CONSTELLATION_SKIES:
            assert sky == expected, f"sky {i + 1} of the day should hold constellations"
        else:
            assert sky == (), f"sky {i + 1} of the day must be empty"


def test_the_eighth_sky_is_viewable_and_the_ninth_is_not():
    """The 8-sky cap is a limit on VIEWING, and it binds one sky after the
    constellation cap: eight skies can be generated, a ninth cannot.

    Checked on the mask rather than the contents, because this cap is the one
    that really does make the action illegal -- the opposite of the 7-sky cap
    above, which leaves the action legal and empties the result.
    """
    cells = _OBSERVATORY_CELLS + (13,)
    game = _observatory_game(cells=cells, stars=6)
    for cell in cells[:MAX_SKIES]:
        game.state.pos = cell
        assert game.can_view_night_sky()
        game.view_night_sky()
    game.state.pos = cells[MAX_SKIES]
    assert not game.can_view_night_sky(), "a ninth sky was offered"
    assert not A.action_mask(game)[A.VIEW_NIGHT_SKY_ACTION]


# --------------------------------------------------- live vs snapshot stars


def test_a_sky_resolves_at_the_live_star_count_when_it_is_first_viewed():
    """A star gained mid-day enriches every sky generated AFTER it.

    The count is live state.stars, not the start-of-day cfg.stars snapshot --
    the opposite convention from the Telescope's own spawn gate, which reads
    cfg.stars deliberately. Reusing that convention here would freeze every
    sky at the day's opening star count and delete the draft-then-look
    decision the explicit view action exists to create.
    """
    game = _observatory_game(cells=(1, 2), stars=3)
    assert game.cfg.stars == 0 != game.state.stars
    assert game.view_night_sky() == tuple(APPEARANCES["3"])

    game.state.stars += 1  # a fourth star, mid-day
    game.state.pos = 2
    assert game.view_night_sky() == tuple(APPEARANCES["4"]), (
        "the later sky ignored the star gained since the first one")


def test_a_star_gained_after_a_sky_is_viewed_does_not_change_that_sky():
    """A sky locks at the count it was first viewed at and never re-resolves.

    This is what makes the timing a real decision rather than a free option:
    looking early is a commitment, so drafting every Observatory before
    looking has to be paid for in advance.
    """
    game = _observatory_game(stars=3)
    assert game.view_night_sky() == tuple(APPEARANCES["3"])
    locked = game.state.night_skies[1][0]

    game.state.stars += 7  # now 10 stars, a different partition entirely
    assert APPEARANCES["10"] != APPEARANCES["3"]
    assert locked.constellation_ids == tuple(APPEARANCES["3"]), "a locked sky re-resolved"
    assert locked.stars == 3


# ----------------------------------------------------------- the five grants


def test_each_implemented_constellation_grants_exactly_its_published_amount():
    """The five pure-resource constellations pay out their own record's grant:
    North Star +1 coin, The Slice +3 steps, Diamondus Minor +1 gem, Clavis +1
    key, Diamondus Major +5 gems.

    Driven from the data so no amount is restated here -- a test that
    hardcoded 5 gems would keep passing if the record and the engine drifted
    apart together. Keyed on carrying a ``grant`` rather than on
    ``implemented``: the four records whose effect is not a resource delta are
    implemented too, and asserting they grant nothing here would only restate
    the schema.
    """
    assert len(GRANTING) == 5
    for cid, record in GRANTING.items():
        resource = record["grant"]["resource"]
        game = _observatory_game(stars=record["stars"])
        before = getattr(game.state, resource)
        assert game.view_night_sky() == (cid,), f"{cid} should be the whole sky here"
        assert game.can_activate_constellation(INDEX[cid])
        game.activate_constellation(INDEX[cid])
        assert getattr(game.state, resource) - before == record["grant"]["amount"], (
            f"{cid} granted the wrong amount of {resource}")


def test_every_constellation_activates():
    """No record can be flipped implemented without a payload the engine reads,
    so no activation is a silent no-op.

    Each constellation is set up at its own star count, where it is the entire
    sky -- which is also what proves it was really present and really
    activated rather than simply absent. Counted from the data, so a
    thirteenth record added later is covered without editing this.
    """
    for record in RECORDS:
        cid = record["id"]
        assert record["implemented"], f"{cid} is not implemented"
        assert ("grant" in record) != ("effect" in record), (
            f"{cid} must carry exactly one payload")
        game = _observatory_game(stars=record["stars"])
        sky = game.view_night_sky()
        assert cid in sky, f"{cid} was not in the sky at {record['stars']} stars"
        assert game.can_activate_constellation(INDEX[cid]), f"{cid} would not activate"
        assert A.action_mask(game)[A.ACTIVATE_CONSTELLATION_BASE + INDEX[cid]], (
            f"{cid}'s action id stayed masked")


def test_the_sky_is_generated_only_by_the_explicit_view_action():
    """Standing in an Observatory generates nothing until VIEW_NIGHT_SKY is
    pressed.

    Auto-generating on entry would lock the sky at whatever the star count
    happened to be on arrival, deleting the draft-every-Observatory-then-look
    line the owner ruling preserves.
    """
    game = _observatory_game(stars=6)
    assert not game.state.night_skies, "a sky appeared without the view action"
    assert A.action_mask(game)[A.VIEW_NIGHT_SKY_ACTION]
    A.apply_action(game, A.VIEW_NIGHT_SKY_ACTION)
    assert game.state.night_skies[game.state.pos]


def test_night_sky_viewing_is_a_capability_not_a_room_id_test():
    """Game.can_view_night_sky asks the capability registry, so the Observatory
    is the only room offering a sky today but no engine module names it.

    The registry is typo-guarded besides: a misspelled id in provides() would
    register a capability no real room has, which validate_capability_registry
    is what catches.
    """
    from blueprince_sim.engine import effects
    from blueprince_sim.engine.effects import Capability

    assert effects.provides_capability("observatory", Capability.NIGHT_SKY)
    providers = {r for r in effects.registered_capability_rooms()
                 if effects.provides_capability(r, Capability.NIGHT_SKY)}
    assert providers == {"observatory"}


def test_night_skies_do_not_survive_the_night():
    """Skies are day-scoped: a fresh GameState clears them, so nothing here
    reaches env/multiday.py's _CARRYOVER_KEYS and the permanent star count
    stays the only thing a night sky leaves behind."""
    from blueprince_sim.engine.state import GameState

    game = _observatory_game(stars=6)
    game.view_night_sky()
    assert game.state.night_skies
    assert not GameState().night_skies


# ------------------------------------------------ the four non-grant effects

#: A lone interior target cell (rank 3, col 2), entered by moving south from
#: rank 2, col 2. Interior because no door may face the outer wall, which rules
#: 4-way rooms off every edge -- measuring the Southern Cross against an edge
#: cell would measure geometry instead of the bias. Same cells as
#: tests/test_category_biases.py, for the same reason.
_DRAFT_FROM_CELL = 7
_DRAFT_DIR = S
_DRAFT_TARGET_CELL = 12

#: Seeds per arm for the two draw-bias measurements, three option slots each.
#: Both biases are large (40% and 30% re-deal chances), so this separates them
#: by a wide margin rather than marginally; it is a fixed count, and a failure
#: here means the wiring broke, never that the seeds need changing.
_DRAFT_SEEDS = 300


def _layout_rate(registry, *, cid, layout, activate) -> tuple[int, int]:
    """Deal one hand per seed at ``_DRAFT_TARGET_CELL``; count options of ``layout``.

    Every seed gets its own game, its own decks and its own Rng, so the two
    arms differ in exactly one thing: whether the constellation was activated
    -- and it is activated by viewing a real night sky and pressing a real
    activation, never by writing the flag.
    """
    cfg = GameConfig()
    hits = total = 0
    for seed in range(_DRAFT_SEEDS):
        game = _observatory_game(stars=STARS[cid], seed=seed, registry=registry)
        game.view_night_sky()
        if activate:
            game.activate_constellation(INDEX[cid])
        state = game.state
        rng = Rng(seed)
        state.decks = build_decks(registry, cfg, rng)
        pending = deal_draft(state, registry, cfg, rng, set(),
                             _DRAFT_FROM_CELL, _DRAFT_DIR, _DRAFT_TARGET_CELL)
        for option in pending.options:
            total += 1
            hits += registry.rooms[option.room_idx].layout == layout
    return hits, total


@pytest.mark.parametrize("cid,layout", [("southern_cross", "cross"), ("draxus", "dead_end")])
def test_activating_a_draft_bias_constellation_measurably_shifts_the_draw(
        registry, cid, layout):
    """Activating the Southern Cross deals four-door rooms far more often, and
    Draxus deals Dead Ends far more often, than the same seeds do unactivated.

    The point of measuring the DRAW rather than the flag: the flag was already
    there and already read, so a test that only checked it would pass against
    an activation wired to the wrong flag, or to a condition tag with no
    surviving category_biases entry behind it. The un-activated arm doubles as
    the proof that viewing the sky alone changes nothing.
    """
    hits_on, total_on = _layout_rate(registry, cid=cid, layout=layout, activate=True)
    hits_off, total_off = _layout_rate(registry, cid=cid, layout=layout, activate=False)
    rate_on = hits_on / total_on
    rate_off = hits_off / total_off
    assert rate_on > rate_off * 1.5, (
        f"{cid}: activation barely moved the draw -- "
        f"on={rate_on:.4f} ({hits_on}/{total_on}) off={rate_off:.4f} "
        f"({hits_off}/{total_off})")


def test_a_draft_bias_constellation_is_inert_until_it_is_activated(registry):
    """Drafting the Observatory and looking at the sky sets neither flag; the
    activation is what sets exactly one of them, and only its own.

    Pairs with the draw measurement above: that one shows the flag reaches the
    deal, this one shows nothing else on the path sets it early. Both flags are
    checked on each activation so a dispatch that ignored the record's own
    condition tag and set both would fail here rather than pass twice.
    """
    game = _observatory_game(cells=(1, 6), stars=STARS["southern_cross"], registry=registry)
    game.view_night_sky()
    assert not game.state.southern_cross_active and not game.state.draxus_active

    game.activate_constellation(INDEX["southern_cross"])
    assert game.state.southern_cross_active and not game.state.draxus_active

    game.state.pos = 6
    game.state.stars = STARS["draxus"]
    game.view_night_sky()
    game.activate_constellation(INDEX["draxus"])
    assert game.state.southern_cross_active and game.state.draxus_active


def test_no_activation_survives_the_night(registry):
    """Every effect this block writes is day-scoped: a new day clears both
    draft-bias flags and the Entrance Hall's trunks.

    Nothing here is carried, so env/multiday.py's _CARRYOVER_KEYS does not
    move -- and it could not carry these anyway, since two of the three are not
    even GameConfig fields.
    """
    game = _observatory_game(cells=(1, 6), stars=STARS["southern_cross"], registry=registry)
    game.view_night_sky()
    game.activate_constellation(INDEX["southern_cross"])
    game.state.pos = 6
    game.state.stars = STARS["the_twins"]
    game.view_night_sky()
    game.activate_constellation(INDEX["the_twins"])
    assert game.state.southern_cross_active
    assert game.state.special.entrance_hall_trunks

    game.reset()
    assert not game.state.southern_cross_active
    assert not game.state.draxus_active
    assert not game.state.special.entrance_hall_trunks


# ------------------------------------------------------------- The Twins


def _twins_pair() -> int:
    """Trunks one Twins activation adds, from the record rather than restated."""
    return next(c for c in RECORDS if c["id"] == "the_twins")["effect"]["trunks"]


def test_activating_the_twins_puts_openable_trunks_in_the_entrance_hall(registry):
    """The pair reaches the container system, not just a counter: the Entrance
    Hall's observed container count rises by two and one of them can be opened.

    Opening is what makes this a behaviour test -- the overlay is resolved per
    CELL rather than per room precisely so dynamically added containers are
    visible, and a counter nothing reads would satisfy an equality on the
    counter alone.
    """
    game = _observatory_game(stars=STARS["the_twins"], registry=registry)
    row, col = ENTRANCE_CELL // 5, ENTRANCE_CELL % 5
    before = int(O.encode(game)["grid_containers"][row, col])

    game.view_night_sky()
    game.activate_constellation(INDEX["the_twins"])
    after = int(O.encode(game)["grid_containers"][row, col])
    assert after - before == _twins_pair()

    game.state.pos = ENTRANCE_CELL
    game.state.keys = 1
    assert game.can_open_container()
    assert game.open_container() is not None


def test_the_twins_stacks_so_each_activation_adds_another_pair(registry):
    """A second activation at a second Observatory adds a second pair, because
    this record stacks -- unlike the two day-long draft biases, for which the
    held Telescope's extra sky is documented as worth nothing."""
    game = _observatory_game(cells=(1, 6), stars=STARS["the_twins"], registry=registry)
    for cell in (1, 6):
        game.state.pos = cell
        game.view_night_sky()
        game.activate_constellation(INDEX["the_twins"])
    assert game.state.special.entrance_hall_trunks == 2 * _twins_pair()


def test_the_twins_and_the_experiment_effect_share_one_trunk_cap(registry):
    """The two Entrance-Hall trunk sources draw down a single per-day cap, and
    a Twins pair that would overshoot lands PARTIALLY rather than being refused.

    Both directions are exercised because a per-source cap would pass a
    one-source test: the experiment effect fills the hall to one short of the
    cap, The Twins gets in a single trunk instead of its pair, and after that
    neither source adds anything. Partial rather than all-or-nothing matters --
    refusing the pair outright would lose a trunk the cap leaves room for.
    """
    cap = experiments.entrance_hall_trunk_cap(registry)
    assert cap is not None and cap > _twins_pair()
    game = _observatory_game(cells=(1, 6), stars=STARS["the_twins"], registry=registry)
    for _ in range(cap - 1):
        experiments.apply_effect(game, experiments.ENTRANCE_HALL_TRUNK_EFFECT_ID)
    assert game.state.special.entrance_hall_trunks == cap - 1

    game.view_night_sky()
    game.activate_constellation(INDEX["the_twins"])
    assert game.state.special.entrance_hall_trunks == cap, "The Twins overshot the shared cap"

    game.state.pos = 6
    game.view_night_sky()
    game.activate_constellation(INDEX["the_twins"])
    experiments.apply_effect(game, experiments.ENTRANCE_HALL_TRUNK_EFFECT_ID)
    assert game.state.special.entrance_hall_trunks == cap


# --------------------------------------------------------- Farmer's Apple


def _apple_effect() -> dict:
    """Farmer's Apple's own effect block: which dish, and how many steps."""
    return next(c for c in RECORDS if c["id"] == "farmers_apple")["effect"]


def _eat_one(game, food_id: str) -> int:
    """Eat one ``food_id`` and return the steps it granted."""
    before = game.state.steps
    special_items.eat_food(game, food_id, 1)
    return game.state.steps - before


def test_farmers_apple_adds_its_published_steps_to_each_apple_and_stacks(registry):
    """Every activation raises what one apple is worth by the record's own
    ``steps``, and a second activation raises it again by the same amount.

    Measured by eating apples rather than by reading a counter: "apples are
    extra delicious today" has to reach the step total, and the increment must
    be per-apple, not a one-off grant at activation time.
    """
    effect = _apple_effect()
    game = _observatory_game(cells=(1, 6), stars=STARS["farmers_apple"], registry=registry)

    plain = _eat_one(game, effect["food_id"])
    game.view_night_sky()
    game.activate_constellation(INDEX["farmers_apple"])
    once = _eat_one(game, effect["food_id"])
    game.state.pos = 6
    game.view_night_sky()
    game.activate_constellation(INDEX["farmers_apple"])
    twice = _eat_one(game, effect["food_id"])

    assert once - plain == effect["steps"]
    assert twice - once == effect["steps"]


def test_farmers_apple_leaves_every_other_dish_alone(registry):
    """A banana is worth the same under seven activations as under none: the
    bonus is keyed on the dish id in data, so it cannot leak into the rest of
    the food table."""
    game = _observatory_game(cells=_OBSERVATORY_CELLS[:MAX_CONSTELLATION_SKIES],
                             stars=STARS["farmers_apple"], registry=registry)
    plain = _eat_one(game, "banana")
    for cell in _OBSERVATORY_CELLS[:MAX_CONSTELLATION_SKIES]:
        game.state.pos = cell
        game.view_night_sky()
        game.activate_constellation(INDEX["farmers_apple"])
    assert _eat_one(game, "banana") == plain


def test_seven_activations_with_a_salt_shaker_and_a_silver_spoon_reach_48_steps(registry):
    """The wiki's own worked example, end to end: seven Farmer's Apple
    activations plus a Salt Shaker and a Silver Spoon take one apple to 48
    steps -- (2 + 7*3 + 1) * 2.

    Pinned as one whole number because what it really fixes is the ORDER. The
    constellation bonus sits INSIDE the Salt Shaker's flat +1 and the Silver
    Spoon's doubling; applying it after that fold would give 25, and between
    the two would give 27. Seven activations is also exactly the day's
    constellation-sky cap, so this is the ceiling rather than an arbitrary
    number -- one Observatory per sky, seven skies, no eighth.
    """
    cells = _OBSERVATORY_CELLS[:MAX_CONSTELLATION_SKIES]
    game = _observatory_game(cells=cells, stars=STARS["farmers_apple"], registry=registry,
                             items=("salt_shaker", "silver_spoon"))
    for cell in cells:
        game.state.pos = cell
        game.view_night_sky()
        game.activate_constellation(INDEX["farmers_apple"])
    steps = _eat_one(game, _apple_effect()["food_id"])
    assert steps == 48, (
        f"the apple was worth {steps}, not the published 48 -- 27 or 25 means the "
        f"Farmer's Apple bonus landed outside the Salt Shaker / Silver Spoon fold "
        f"instead of on the apple's own base")


def test_a_non_stacking_record_neither_re_applies_nor_re_multiplies(registry):
    """``stacks`` is honoured on both sides of the split: a non-stacking
    record's second activation writes nothing, and its bonus is counted once
    however many times it fired.

    Exercised against synthetic copies because no shipped record is both
    non-stacking and additive -- the four non-stacking ones set day-scoped
    flags, where a repeat is invisible. Without this the published "no
    additional effect on a second activation" would quietly become "double it"
    the day such a constellation lands.
    """
    game = _observatory_game(cells=(1, 6), stars=STARS["the_twins"], registry=registry)
    once_only = replace(registry.constellations.by_id["the_twins"], stacks=False)
    for cell in (1, 6):
        game.state.pos = cell
        game.view_night_sky()
        game.state.night_skies[cell][0].activated.add(once_only.id)
        constellations.apply_effect(game, once_only)
    assert game.state.special.entrance_hall_trunks == _twins_pair()

    apples = _observatory_game(cells=(1, 6), stars=STARS["farmers_apple"], registry=registry)
    for cell in (1, 6):
        apples.state.pos = cell
        apples.view_night_sky()
        apples.activate_constellation(INDEX["farmers_apple"])
    con = registry.constellations
    stacking = constellations.food_step_bonus(con, apples.state, _apple_effect()["food_id"])
    non_stacking = replace(
        con, records=tuple(replace(r, stacks=False) for r in con.records))
    assert stacking == 2 * _apple_effect()["steps"]
    assert constellations.food_step_bonus(
        non_stacking, apples.state, _apple_effect()["food_id"]) == _apple_effect()["steps"]


# ------------------------------------------------------------------ The Sail


def _sail_effect() -> dict:
    """The Sail's own effect block: the shop ids its sale covers."""
    return next(c for c in RECORDS if c["id"] == "the_sail")["effect"]


#: A cell to stand a shop in, away from the Observatory at cell 1. Nothing
#: about the sale is positional, so any occupied non-Observatory cell does.
_SHOP_CELL = 7


def _shop_prices(registry, shop_id, *, activate, day=1, seed=0, items=()) -> list:
    """Roll ``shop_id``'s stock and return its displayed (id, price) pairs.

    Both arms share a seed, so the two stock rolls are identical and the only
    difference between them is whether The Sail was activated -- through a real
    night sky and a real activation, never by writing a flag.
    """
    game = _observatory_game(stars=STARS["the_sail"], seed=seed, registry=registry,
                             items=items)
    game.state.day = day
    game.view_night_sky()
    if activate:
        game.activate_constellation(INDEX["the_sail"])
    room = game.registry.by_id[shop_id]
    game.state.grid[_SHOP_CELL] = room.idx
    game.state.placed_doors[_SHOP_CELL] = room.door_mask
    game.state.entered[_SHOP_CELL] = True
    game.state.pos = _SHOP_CELL
    shops.on_enter_shop(game, room)
    return [(e["id"], e["price"]) for e in shops.stock_display(game, shop_id)]


@pytest.mark.parametrize("shop_id", ["commissary", "locksmith", "kitchen"])
def test_the_sail_halves_every_price_at_a_shop_it_names(registry, shop_id):
    """Activating The Sail actually halves what each entry costs, rounding up,
    at every shop its record lists -- the price a purchase would spend, not a
    flag set beside it.

    Measured against the same seed unactivated, so the stock is the same items
    in the same order and the only thing that moved is the price. Rounding is
    asserted as a ceil rather than as fixed numbers, since the stock roll is
    seeded and the entries may change; what must not drift is the rule.
    """
    off = _shop_prices(registry, shop_id, activate=False)
    on = _shop_prices(registry, shop_id, activate=True)
    assert off and [i for i, _ in off] == [i for i, _ in on]
    for (item, before), (_, after) in zip(off, on):
        assert after == math.ceil(before / 2), (
            f"{shop_id}/{item}: {before} became {after}, not {math.ceil(before / 2)}")
        assert after < before, f"{shop_id}/{item}: the price did not move at all"


def test_every_shop_the_sail_names_is_a_real_shop_and_goes_on_sale(registry):
    """All four listed shops are put on sale by one activation, and none of
    them is an id that no longer names a shop.

    The Bookshop is why this sits next to the price test above: it is a real
    shop the sale really covers, but its stock is deliberately empty (lore
    books are out of scope), so a price measurement cannot see it. Without
    this, the Bookshop could silently fall out of the allowlist unnoticed.
    """
    game = _observatory_game(stars=STARS["the_sail"], registry=registry)
    game.view_night_sky()
    game.activate_constellation(INDEX["the_sail"])
    con = registry.constellations
    for shop_id in _sail_effect()["shops"]:
        assert shop_id in registry.shop_rules.shops, f"{shop_id} is not a shop"
        assert constellations.shop_half_price(con, game.state, shop_id), (
            f"{shop_id} is listed by the record but was not put on sale")


def test_the_sail_leaves_every_shop_it_does_not_name_alone(registry):
    """A shop outside the record's list charges exactly what it charged before
    -- "no Shops other than the four listed Shops benefit from the sale".

    A discount wired as "every shop" instead of "these shops" would halve the
    Showroom and the Armory too, and fail here rather than pass silently
    against the four that are supposed to move.
    """
    named = set(_sail_effect()["shops"])
    others = [s for s in registry.shop_rules.shops if s not in named]
    assert others, "no control shop left to compare against"
    for shop_id in others:
        off = _shop_prices(registry, shop_id, activate=False)
        on = _shop_prices(registry, shop_id, activate=True)
        assert off == on, f"{shop_id} is not on the list but its prices moved"


def test_the_sail_does_not_stack(registry):
    """A second Sail activation at a second Observatory charges the same prices
    as the first -- "no additional effect if it is activated multiple times".

    A sale implemented as a repeatable reduction rather than a yes/no would
    quarter these prices instead of halving them.
    """
    once = _shop_prices(registry, "commissary", activate=True)

    game = _observatory_game(cells=(1, 6), stars=STARS["the_sail"], registry=registry)
    for cell in (1, 6):
        game.state.pos = cell
        game.view_night_sky()
        game.activate_constellation(INDEX["the_sail"])
    assert constellations.activation_count(game.state, "the_sail") == 2
    room = registry.by_id["commissary"]
    game.state.grid[_SHOP_CELL] = room.idx
    game.state.placed_doors[_SHOP_CELL] = room.door_mask
    game.state.entered[_SHOP_CELL] = True
    game.state.pos = _SHOP_CELL
    shops.on_enter_shop(game, room)
    twice = [(e["id"], e["price"]) for e in shops.stock_display(game, "commissary")]
    assert twice == once


def test_the_sail_and_the_commissary_own_sale_halve_the_price_once(registry):
    """On Days 20-21 the Commissary is already half price, and activating The
    Sail on top of it changes nothing -- the wiki calls the two effects
    identical, so overlapping them cannot quarter a price.

    The day-1 arm is what makes this a test of the overlap rather than of the
    calendar: it shows the Sail alone reaches the same prices the sale day
    reaches, so both paths lead to exactly one halving.
    """
    sale_day = registry.shop_rules.sale["days"][0]
    day_only = _shop_prices(registry, "commissary", activate=False, day=sale_day)
    both = _shop_prices(registry, "commissary", activate=True, day=sale_day)
    sail_only = _shop_prices(registry, "commissary", activate=True, day=1)
    full = _shop_prices(registry, "commissary", activate=False, day=1)
    assert day_only == both == sail_only
    assert full != sail_only, "nothing was discounted in any arm"


def test_a_sail_priced_banana_is_free_with_a_coupon_book(registry):
    """The wiki's published worked example: Kitchen bananas cost 1 coin on
    sale, and "with a Coupon Book, they can be purchased free of charge".

    This pins the ORDER of the two reductions, which no other test can see.
    Halving first gives ceil(2 / 2) - 1 = 0; applying the Coupon Book first
    would give ceil((2 - 1) / 2) = 1, and the banana would never be free.
    """
    priced = dict(_shop_prices(registry, "kitchen", activate=True,
                               items=("coupon_book",)))
    assert priced["banana"] == 0, (
        f"a banana cost {priced['banana']} under the Sail plus a Coupon Book, not "
        f"0 -- 1 means the Coupon Book was applied before the halving, not after")


# ----------------------------------------------------------------- Florealis


def _florealis_effect() -> dict:
    """Florealis's own effect block: the default gem count, and the per-room
    overrides keyed by root base room id."""
    return next(c for c in RECORDS if c["id"] == "florealis")["effect"]


def _green_room_ids(registry) -> list:
    """Every room the engine counts as Green -- the same ``green`` category
    membership the Patio's own gem spread reads."""
    return [r.id for r in registry.rooms if r.is_category("green")]


#: The cell each test drafts its room under test into. Interior, so no room's
#: door geometry can make the placement itself the thing being measured.
_GREEN_CELL = 12


def _gems_from_drafting(registry, room_id, *, activate, cells=(1,)) -> int:
    """Gems the player actually holds after drafting ``room_id`` and walking in.

    Returns the DELTA against the identical un-activated game, so a Green Room
    that pays gems of its own on entry -- which the wiki says is independent of
    Florealis -- cancels out, leaving only Florealis's contribution. Placement
    goes through Game._place_room, the real draft site, and the gems are read
    after a real arrival, so they travel the whole spread_pending ->
    _collect_spread path instead of being read back out of the parking spot.
    """
    def run(activated: bool) -> int:
        game = _observatory_game(cells=cells, stars=STARS["florealis"],
                                 registry=registry)
        if activated:
            for observatory_cell in cells:
                game.state.pos = observatory_cell
                game.view_night_sky()
                game.activate_constellation(INDEX["florealis"])
        room = registry.by_id[room_id]
        before = game.state.gems
        game._place_room(room, _GREEN_CELL, room.door_mask)
        game.state.pos = _GREEN_CELL
        game._enter(_GREEN_CELL)
        return game.state.gems - before

    return run(True) - run(False) if activate else run(False)


def test_florealis_puts_gems_in_the_players_hands_from_a_newly_drafted_green_room(
        registry):
    """Drafting a Green Room under an active Florealis and walking into it
    actually raises the player's gem count.

    The whole path is exercised -- parked at the draft, collected on arrival --
    because a flag reaching neither would look identical to this one when seen
    from the activation site.
    """
    assert _gems_from_drafting(registry, "terrace", activate=True) > 0


@pytest.mark.parametrize("room_id", ["terrace", "patio", "veranda", "greenhouse",
                                     "courtyard", "cloister", "courtyard__ix48",
                                     "cloister_of_rynna__ix29", "corriyard__ix50"])
def test_florealis_pays_each_green_room_its_published_count(registry, room_id):
    """The Courtyard and the Cloister bloom two gem flowers and every other
    Green Room one, and an upgraded Courtyard or Cloister of X inherits its
    base's two.

    The amounts come from the record, so what this asserts is the LOOKUP: that
    the per-room override is keyed by root base id and that the default catches
    everything else. A lookup keyed by the placed room's own id would pay the
    upgrades one gem apiece and fail here.
    """
    effect = _florealis_effect()
    expected = effect["gems_by_room"].get(
        root_base_id(registry, registry.by_id[room_id]), effect["gems"])
    assert _gems_from_drafting(registry, room_id, activate=True) == expected


def test_florealis_pays_nothing_for_a_room_that_is_not_green(registry):
    """A non-Green room drafted under an active Florealis grows no gem
    flowers: the effect is scoped by the room's category, not by the fact that
    a draft happened."""
    assert _gems_from_drafting(registry, "kitchen", activate=True) == 0


def test_florealis_leaves_green_rooms_already_on_the_estate_alone(registry):
    """A Green Room standing before the activation gains nothing from it --
    "Green Rooms already on the estate before this constellation is activated
    are not affected".

    This is the difference between the draft being the trigger and the
    activation being the trigger, and it is the only test that can tell them
    apart: an implementation that swept the grid when the constellation fired
    would pay this room and still pass everything else here.
    """
    game = _observatory_game(stars=STARS["florealis"], registry=registry)
    terrace = registry.by_id["terrace"]
    game._place_room(terrace, _GREEN_CELL, terrace.door_mask)
    game.view_night_sky()
    game.activate_constellation(INDEX["florealis"])
    assert _GREEN_CELL not in game.state.spread_pending

    before = game.state.gems
    game.state.pos = _GREEN_CELL
    game._enter(_GREEN_CELL)
    assert game.state.gems == before


def test_florealis_pays_once_however_many_observatories_activated_it(registry):
    """Two Observatories, two activations, and a drafted Green Room still
    blooms exactly what one activation gives it.

    The multi-cell case is the one an activation-time sweep or a broadcast hook
    gets wrong: ON_DRAFT_ROOM fires once per placed room, so a payout hung
    there would pay once per Observatory on the estate. Paying at the draft
    instead makes the count independent of how the day was played.
    """
    one = _gems_from_drafting(registry, "courtyard", activate=True, cells=(1,))
    two = _gems_from_drafting(registry, "courtyard", activate=True, cells=(1, 6))
    assert one == two == _florealis_effect()["gems_by_room"]["courtyard"]


def test_florealis_blooms_every_green_room_and_nothing_in_between(registry):
    """Under one activation every Green Room the engine knows blooms when
    drafted, and always by the record's default or its own override -- never
    zero, never something in between.

    Swept across the whole category rather than a sample, so a Green Room added
    later cannot quietly bloom nothing.
    """
    effect = _florealis_effect()
    game = _observatory_game(stars=STARS["florealis"], registry=registry)
    game.view_night_sky()
    game.activate_constellation(INDEX["florealis"])
    con = registry.constellations
    for room_id in _green_room_ids(registry):
        root = root_base_id(registry, registry.by_id[room_id])
        expected = effect["gems_by_room"].get(root, effect["gems"])
        assert expected > 0, room_id
        assert constellations.green_room_gems(con, game.state, root) == expected, room_id


def test_neither_new_effect_is_active_before_its_constellation_is(registry):
    """Viewing a night sky changes no price and blooms no Green Room; the
    activation is what does both.

    Pairs with the measurements above the way the draft-bias pair does: those
    show each effect reaches its consumption site, this shows nothing else on
    the path switches it on early.
    """
    con = registry.constellations
    game = _observatory_game(stars=STARS["the_sail"], registry=registry)
    game.view_night_sky()
    assert not constellations.shop_half_price(con, game.state, "commissary")
    game.activate_constellation(INDEX["the_sail"])
    assert constellations.shop_half_price(con, game.state, "commissary")

    bloom = _observatory_game(stars=STARS["florealis"], registry=registry)
    bloom.view_night_sky()
    assert constellations.green_room_gems(con, bloom.state, "courtyard") == 0
    bloom.activate_constellation(INDEX["florealis"])
    assert constellations.green_room_gems(con, bloom.state, "courtyard") > 0


def test_the_sail_and_florealis_do_not_survive_the_night(registry):
    """Both new effects are day-scoped: a new day restores full prices and
    stops Green Rooms blooming.

    Neither needs a GameState field, so what is really pinned here is that the
    activations they read live on the night skies, which a fresh GameState
    clears -- nothing new reaches env/multiday.py's _CARRYOVER_KEYS.
    """
    con = registry.constellations
    game = _observatory_game(cells=(1, 6), stars=STARS["the_sail"], registry=registry)
    game.view_night_sky()
    game.activate_constellation(INDEX["the_sail"])
    game.state.pos = 6
    game.state.stars = STARS["florealis"]
    game.view_night_sky()
    game.activate_constellation(INDEX["florealis"])
    assert constellations.shop_half_price(con, game.state, "commissary")
    assert constellations.green_room_gems(con, game.state, "courtyard") > 0

    game.reset()
    assert not constellations.shop_half_price(con, game.state, "commissary")
    assert constellations.green_room_gems(con, game.state, "courtyard") == 0


# ------------------------------------------------------------- The Ink Well


def _drafting_game(*, seed=0) -> Game:
    """A game in Phase.DRAFTING with a pending hand, reached via the
    once-per-day outer draft (no grid doorway geometry needed) so the Ink
    Well's redraw mechanic can be exercised against a real pending hand.
    """
    game = Game(GameConfig(west_gate_unlatched=True), seed=seed)
    game.open_outer_draft()
    assert game.phase is Phase.DRAFTING and game.state.pending is not None
    return game


def test_the_ink_well_flag_is_set_by_activation_and_not_before(registry):
    """Viewing the sky the Ink Well appears in sets nothing; activating it
    sets exactly ``ink_well_active``."""
    game = _observatory_game(stars=STARS["ink_well"], registry=registry)
    game.view_night_sky()
    assert not game.state.ink_well_active
    game.activate_constellation(INDEX["ink_well"])
    assert game.state.ink_well_active


def test_a_star_redraw_spends_one_star_and_replaces_the_hand():
    """RedrawKind.STAR spends exactly 1 star and redeals the hand, pushing the
    discarded one onto the rewind stack the same way every other redraw
    source does.
    """
    game = _drafting_game()
    game.state.ink_well_active = True
    game.state.stars = 5
    stack_before = len(game.state.pending.rewind_stack)
    game.redraw(RedrawKind.STAR)
    assert game.state.stars == 4
    assert len(game.state.pending.rewind_stack) == stack_before + 1
    assert len(game.state.pending.options) == 3


def test_the_star_redraw_option_is_unavailable_until_the_ink_well_is_activated():
    """REDRAW_WITH_STAR_ACTION is gated on ``ink_well_active``, not merely on
    holding stars: masked off with the flag unset, legal once it is set."""
    game = _drafting_game()
    game.state.stars = 5
    assert not game.can_redraw_with_star()
    assert not A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]

    game.state.ink_well_active = True
    assert game.can_redraw_with_star()
    assert A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]
    A.apply_action(game, A.REDRAW_WITH_STAR_ACTION)
    assert game.state.stars == 4


def test_the_star_redraw_option_is_masked_off_at_zero_stars():
    """An activated Ink Well still needs at least 1 star: the option is
    refused and masked off once the balance hits 0."""
    game = _drafting_game()
    game.state.ink_well_active = True
    game.state.stars = 0
    assert not game.can_redraw_with_star()
    assert not A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]


def test_the_star_redraw_keeps_working_below_50_stars():
    """The published rule: dropping below 50 stars does not disable the Ink
    Well once it is active. Activated at exactly 50, spent down to 48, the
    option is still legal and still spends a star each time.
    """
    game = _drafting_game()
    game.state.ink_well_active = True
    game.state.stars = 50
    game.redraw(RedrawKind.STAR)
    assert game.state.stars == 49
    assert game.can_redraw_with_star(), "the option disabled itself crossing below 50"
    assert A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]

    game.redraw(RedrawKind.STAR)
    assert game.state.stars == 48
    assert game.can_redraw_with_star(), "the option disabled itself under 50"
    assert A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]


def test_redraw_kind_never_returns_star():
    """``_redraw_kind`` -- the picker behind the plain REDRAW_ACTION -- never
    offers ``RedrawKind.STAR``, even with the Ink Well active and stars held:
    the star redraw is reachable only through its own dedicated action id.
    """
    game = _drafting_game()
    game.state.ink_well_active = True
    game.state.stars = 5
    game.state.dice = 0
    game.state.study_placed = False
    game.state.pending.redraws_left = 0
    assert A._redraw_kind(game) is None
    assert not A.action_mask(game)[A.REDRAW_ACTION]
    assert A.action_mask(game)[A.REDRAW_WITH_STAR_ACTION]


def test_the_ink_well_does_not_survive_the_night():
    """``ink_well_active`` is day-scoped: it clears at reset and is not
    carried over, so the option must be re-activated from a fresh sky.

    This matters more than for the other day-scoped flags. The Ink Well is the
    only mechanic that spends a permanent, save-scoped resource, so a flag that
    survived the night would turn an uncapped star drain on for every later day
    without the player ever activating it again.
    """
    game = _drafting_game()
    game.state.ink_well_active = True
    game.state.stars = 50
    game.reset()
    assert not game.state.ink_well_active
    assert not game.can_redraw_with_star()
    assert "ink_well_active" not in _CARRYOVER_KEYS


# ------------------------------------------------- the Spiral of Stars' words

SPIRAL = next(c for c in RECORDS if c["id"] == "spiral_of_stars")
SPIRAL_EFFECT = SPIRAL["effect"]
SPIRAL_TIERS = SPIRAL_EFFECT["tiers"]
SPIRAL_CAP = SPIRAL_EFFECT["word_cap"]
SPIRAL_STARS = SPIRAL["stars"]


def test_a_word_is_added_when_a_spiral_sky_is_generated_not_when_activated():
    """The Spiral's word arrives on GENERATION, which is the mechanic's whole
    surprise: its own flavour text says the word is added on activation, and
    the wiki says outright that it is not.

    Driven as two separate games from the same setup so the two triggers are
    isolated: one views and walks away, the other views and activates. Both
    must land on the same word count, which is what proves activation
    contributes nothing to growth.
    """
    viewed_only = _observatory_game(stars=SPIRAL_STARS)
    assert "spiral_of_stars" in viewed_only.view_night_sky()
    assert viewed_only.state.spiral_words == 1

    activated = _observatory_game(stars=SPIRAL_STARS)
    activated.view_night_sky()
    activated.activate_constellation(INDEX["spiral_of_stars"])
    assert activated.state.spiral_words == 1, (
        "activating must not add a second word on top of the generation")


def test_a_sky_without_the_spiral_adds_no_word():
    """Growth is keyed to the Spiral being IN the sky, not to looking at a sky.

    Generated one star below the Spiral's own count, where the partition
    cannot contain it -- the negative case that stops "any night sky adds a
    word" from passing.
    """
    game = _observatory_game(stars=SPIRAL_STARS - 1)
    assert "spiral_of_stars" not in game.view_night_sky()
    assert game.state.spiral_words == 0


def test_word_growth_stops_at_the_published_cap():
    """Words stop at word_cap: "no new words are added" past it.

    Seeded one word below the cap so a single generation reaches it and the
    next cannot exceed it -- the boundary, not an arbitrary interior point.
    Two Observatories are used because each cell offers its own telescope once.
    """
    game = _observatory_game(cells=(1, 2), stars=SPIRAL_STARS, spiral_words=SPIRAL_CAP - 1)
    game.view_night_sky()
    assert game.state.spiral_words == SPIRAL_CAP
    game.state.pos = 2
    game.view_night_sky()
    assert game.state.spiral_words == SPIRAL_CAP, "growth must clamp at the cap"


def test_the_word_count_is_save_scoped_across_an_attempt_wrap():
    """The words "never reset", so spiral_words survives the DayChain attempt
    wrap the way stars does rather than resetting with a fresh attempt.

    Driven through a real one-day chain that wraps immediately, so this tests
    the wrap block itself and not a restatement of the carve-out list.
    """
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"spiral_words": 12})
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    assert chain.next_config().spiral_words == 12


def test_the_word_count_survives_the_star_total_falling_back_below_the_spiral():
    """Losing the stars that revealed the Spiral does not cost the words:
    they persist "even if the spiral temporarily vanishes from the night sky
    due to falling below 100 stars".

    The star drop is applied between two generations, so the second sky
    genuinely no longer contains the Spiral while the count from the first
    still stands.
    """
    game = _observatory_game(cells=(1, 2), stars=SPIRAL_STARS)
    assert "spiral_of_stars" in game.view_night_sky()
    assert game.state.spiral_words == 1
    game.state.stars = SPIRAL_STARS - 1
    game.state.pos = 2
    assert "spiral_of_stars" not in game.view_night_sky()
    assert game.state.spiral_words == 1, "the word must not be lost with the stars"


def test_the_spiral_tier_table_is_the_published_one():
    """spiral_tier returns the last tier the word count has reached, so each
    tier owns the whole span up to the next one's min_words.

    Checked at every boundary in the table rather than at sampled points: the
    failure this guards against is an off-by-one at a min_words edge, which a
    midpoint check cannot see. The tiers themselves are read from the data, so
    this pins the LOOKUP, not the numbers.
    """
    record = constellations.load_constellations(DATA).by_id["spiral_of_stars"]
    for i, tier in enumerate(SPIRAL_TIERS):
        low = tier["min_words"]
        assert constellations.spiral_tier(record, low) == tier, (
            f"word {low} must land on its own tier")
        if i + 1 < len(SPIRAL_TIERS):
            assert constellations.spiral_tier(record, SPIRAL_TIERS[i + 1]["min_words"] - 1) == tier, (
                f"the word before tier {i + 1} must still be tier {i}")
        else:
            assert constellations.spiral_tier(record, SPIRAL_CAP) == tier


def _spiral_activation(*, words, steps=100, day=20, stars=None, rank=1, seed=0):
    """An Observatory game with a Spiral sky already generated and activated.

    ``words`` is seeded one BELOW the target, because generating the sky adds
    the word that the activation then pays out -- setting the target directly
    would test a word count one higher than the tier under test. Steps, day and
    deepest rank are set explicitly rather than played into, so each payout
    test states the inputs its expected number is computed from.
    """
    game = _observatory_game(
        stars=SPIRAL_STARS if stars is None else stars,
        spiral_words=words - 1, day=day, seed=seed)
    game.state.steps = steps
    game.deepest_rank = rank
    assert "spiral_of_stars" in game.view_night_sky()
    assert game.state.spiral_words == words
    game.activate_constellation(INDEX["spiral_of_stars"])
    return game


def test_the_spiral_pays_nothing_below_its_first_paying_tier():
    """Words 1-3 are "no effect": the constellation is activatable and costs
    nothing, but moves no resource.

    The guard against a table whose first tier accidentally pays out -- which
    a test that only checked the paying tiers would never catch.
    """
    game = _spiral_activation(words=3, steps=100)
    assert (game.state.keys, game.state.gems, game.state.coins) == (0, 0, 0)
    assert game.state.steps == 100
    assert game.state.stars == SPIRAL_STARS


def test_the_spiral_scales_keys_and_gems_by_the_deepest_rank_entered_today():
    """From word 11 the keys and gems are the maximum rank reached today, not a
    flat amount -- "ranks must be physically entered for them to be considered
    reached", which is the engine's deepest_rank.

    Two ranks are checked from the same tier so the result is proven to TRACK
    the rank rather than coincide with one value of it.
    """
    for rank in (3, 7):
        game = _spiral_activation(words=11, rank=rank)
        assert game.state.keys == rank, f"rank {rank} must pay {rank} keys"
        assert game.state.gems == rank, f"rank {rank} must pay {rank} gems"


def test_the_spiral_pays_flat_amounts_at_word_ten():
    """Word 10 is the one flat 10-keys-and-10-gems tier, and it is replaced by
    the per-rank amounts at word 11.

    Pinned at rank 1 so a per-rank regression would show as 1 rather than 10 --
    the two clauses are indistinguishable at rank 10.
    """
    game = _spiral_activation(words=10, rank=1)
    assert (game.state.keys, game.state.gems) == (10, 10)


def test_the_spiral_scales_coins_by_the_day_number():
    """From word 26 the coin payout is the current day, replacing word 23's
    flat single coin.

    Two days are checked so the payout is proven to track the day rather than
    match one value of it, and both are away from the flat 1 that would pass
    for day 1.
    """
    for day in (4, 31):
        game = _spiral_activation(words=26, day=day)
        assert game.state.coins == day, f"day {day} must pay {day} coins"


def test_the_spiral_step_loss_scales_with_rank_and_precedes_the_item_gates():
    """The per-rank step loss (word 19+) resolves BEFORE the step-gated
    clauses, which is what "less than forty steps after accounting for previous
    step losses" pins.

    Set up at 48 steps and rank 3: the -9 loss lands exactly on 39, so the
    item gate passes only if the loss was applied first. An engine that
    checked the gate against the pre-loss 48 would grant nothing, and the
    item assertion below is what separates the two orders.
    """
    game = _spiral_activation(words=43, steps=48, rank=3)
    assert game.state.steps == 39, "48 - 3*3 must be 39 before the gate is read"
    granted = [i for i in SPIRAL_EFFECT["special_item_pool"]
               if special_items.has(game.state, i)]
    assert len(granted) == 1, (
        f"the special item gate reads the step count AFTER the loss; got {granted}")


def test_the_spiral_item_gates_refuse_above_their_step_ceiling():
    """The step gates are ceilings, so a player one step above one gets nothing
    from it -- the negative half of the ordering test above.

    One step over the boundary rather than far above it, since an off-by-one
    is the realistic failure.
    """
    ceiling = next(t for t in SPIRAL_TIERS if t["min_words"] == 43)["special_item_max_steps"]
    game = _spiral_activation(words=43, steps=ceiling + 1, rank=0)
    granted = [i for i in SPIRAL_EFFECT["special_item_pool"]
               if special_items.has(game.state, i)]
    assert granted == [], f"{ceiling + 1} steps is above the ceiling; got {granted}"


def test_the_spiral_sets_steps_after_the_gates_it_would_otherwise_close():
    """``set_steps`` (word 63+) resolves AFTER the step-gated clauses, which is
    what lets one activation both collect the gated items and end at 40 steps.

    If it ran first, 40 steps would close the 39-step item gates and the
    19-step Antechamber gate -- so asserting the item WAS granted alongside the
    final 40 is what pins the order rather than just the value.
    """
    tier = next(t for t in SPIRAL_TIERS if t["min_words"] == 63)
    game = _spiral_activation(words=63, steps=10, rank=0)
    assert game.state.steps == tier["set_steps"]
    granted = [i for i in SPIRAL_EFFECT["special_item_pool"]
               if special_items.has(game.state, i)]
    assert len(granted) == 1, "the item gate must have been read before set_steps"


def test_the_spiral_sets_luck_absolutely():
    """``set_luck`` (word 69+) is an absolute set that overrides any changes,
    not a bonus added to the day's accumulated luck.

    Seeded from a luck value well away from the target so a ``+=`` regression
    lands somewhere the assertion can see.
    """
    tier = next(t for t in SPIRAL_TIERS if t["min_words"] == 69)
    game = _observatory_game(stars=SPIRAL_STARS, spiral_words=68)
    game.state.luck = 40
    game.state.steps = 100
    game.view_night_sky()
    game.activate_constellation(INDEX["spiral_of_stars"])
    assert game.state.luck == tier["set_luck"]


def test_the_spiral_loses_two_stars_from_word_thirty_two():
    """The star loss is a real deduction from the permanent total, applied
    through the same clamped grant path every other resource uses.

    Asserted against the count the sky was generated at, so a payout that
    silently skipped the deduction reads as unchanged rather than as zero.
    """
    game = _spiral_activation(words=32, rank=0)
    assert game.state.stars == SPIRAL_STARS - 2


def test_the_spiral_ends_the_day_at_the_two_tiers_that_say_so():
    """The day ends at words 88 and 100 and NOT at 89-99, where the clause is
    removed again before word 100 restores it.

    All three are checked from one test because the property is the gap: a
    table that simply kept ends_day from 88 onward would pass either boundary
    checked alone.
    """
    assert _spiral_activation(words=88).phase is Phase.TERMINAL
    assert _spiral_activation(words=89).phase is not Phase.TERMINAL
    assert _spiral_activation(words=100).phase is Phase.TERMINAL


def test_the_spiral_opens_the_antechamber_under_its_step_ceiling():
    """Word 57+ unseals every sealed Antechamber segment when the step count is
    at or under the gate -- all four, not the single door the experiment effect
    opens.

    The preset is asserted to start with sealed segments, so an engine that
    unsealed nothing cannot pass by having nothing to unseal.
    """
    from blueprince_sim.engine.locks import DOOR_SEALED, segment_key

    tier = next(t for t in SPIRAL_TIERS if t["min_words"] == 57)
    game = _observatory_game(stars=SPIRAL_STARS, spiral_words=56)
    game.state.steps = tier["antechamber_max_steps"]
    sealed_before = [s for s in experiments.ANTECHAMBER_SEGMENTS
                     if game.state.door_state.get(segment_key(*s)) == DOOR_SEALED]
    assert sealed_before, "the preset must start with sealed segments to mean anything"
    game.view_night_sky()
    game.activate_constellation(INDEX["spiral_of_stars"])
    still_sealed = [s for s in experiments.ANTECHAMBER_SEGMENTS
                    if game.state.door_state.get(segment_key(*s)) == DOOR_SEALED]
    assert still_sealed == [], f"every segment must be unsealed; {still_sealed} remain"
