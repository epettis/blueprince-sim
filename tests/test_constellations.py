"""The constellation data, the night-sky mechanic, and the observation key.

Sky generation and the five pure-resource constellations are live; the other
eight records stay unimplemented and their action ids permanently masked. What
these tests pin is the mechanic (a true sum-partition, resolved at LIVE star
count, under two independent per-day caps) plus the part that cannot be changed
later -- the action-space width and the observation-space shape.

Every expected sky here is read out of the ``appearances`` table directly,
never by calling the generator: a test that asked the generator what it
generates would pass against any self-consistent wrong rule, which is exactly
the failure the partition is worth testing for.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects.items.telescope import ITEM_ID as TELESCOPE_ID
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.env import actions as A
from blueprince_sim.env import obs as O
from blueprince_sim.rl.train import all_unlocks_config

DATA = Path(__file__).resolve().parents[1] / "src" / "blueprince_sim" / "data"
DOC = json.loads((DATA / "constellations.json").read_text(encoding="utf-8"))
STARS = {c["id"]: c["stars"] for c in DOC["constellations"]}
APPEARANCES = DOC["appearances"]
RECORDS = DOC["constellations"]
INDEX = {c["id"]: i for i, c in enumerate(RECORDS)}
IMPLEMENTED = {c["id"]: c for c in RECORDS if c["implemented"]}
MAX_SKIES = DOC["max_skies_per_day"]
MAX_CONSTELLATION_SKIES = DOC["max_constellation_skies_per_day"]

#: Eight cells with no shared doorway logic needed: the tests below drive
#: Game.view_night_sky directly at a chosen position, so only the grid contents
#: and state.pos matter. Eight is enough to exhaust MAX_SKIES using each
#: Observatory's own telescope alone.
_OBSERVATORY_CELLS = (1, 2, 3, 6, 7, 8, 11, 12)


def _observatory_game(*, cells=(1,), stars=0, telescope=False, seed=0) -> Game:
    """A game standing in an Observatory at ``cells[0]`` with ``stars`` stars.

    Rooms are written onto the grid rather than drafted so the Observatory's
    own +1-star-per-draft hook does not move the star count out from under a
    test that is about the star count.
    """
    cfg = GameConfig(special_items=True) if telescope else GameConfig()
    game = Game(cfg, seed=seed)
    room = game.registry.by_id["observatory"]
    for cell in cells:
        game.state.grid[cell] = room.idx
        game.state.placed_doors[cell] = room.door_mask
    game.state.pos = cells[0]
    game.state.stars = stars
    game.phase = Phase.NAVIGATE
    if telescope:
        game.state.inventory[TELESCOPE_ID] = 1
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


def test_action_space_width_is_457():
    """N_ACTIONS is 457 and the constellation block occupies 442..456.

    The width is committed here and cannot move afterwards: action ids are
    positional, so every later change to it invalidates a trained policy's
    embedding and every recorded demo.
    """
    assert A.ACTIVATE_CONSTELLATION_BASE == 442
    assert A.VIEW_NIGHT_SKY_ACTION == 455
    assert A.REDRAW_WITH_STAR_ACTION == 456
    assert A.N_ACTIONS == 457


def test_no_existing_action_id_shifted():
    """Every action id declared before the constellation block still has the
    value it had, so the block was appended and nothing was inserted.

    A mid-array insert is the failure this guards: it costs nothing at import
    time and silently makes every id after the insertion point mean something
    else, which no test that only checks N_ACTIONS would catch.
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
    assert (A.AXE_TARGET_BASE, A.LOCK_MENU_BASE, A.LOCK_USE_KEY_ACTION) == (379, 427, 427)
    assert (A.LOCK_LOCKPICK_ACTION, A.LOCK_ABANDON_ACTION, A.LOCK_SPECIAL_KEY_BASE) == (
        428, 429, 430)
    assert (A.REWIND_ACTION, A.WRENCH_RARITY_BASE) == (436, 437)
    assert A.USE_TELESCOPE_PLANETARIUM_ACTION == 441


def test_unimplemented_constellation_ids_and_the_star_redraw_stay_masked():
    """The eight unimplemented records and REDRAW_WITH_STAR are never legal, in
    any state reachable by play.

    The five implemented ids are deliberately excluded: they go legal in an
    Observatory, which is the point of this PR. What must not happen is an id
    whose effect does not exist becoming pressable -- that would silently
    no-op, or crash on a missing grant. Swept over played-out days on both
    presets rather than checked at a single reset, since a block that only
    went legal deep in a day would pass a step-0 check.
    """
    reserved = [A.ACTIVATE_CONSTELLATION_BASE + INDEX[c["id"]]
                for c in RECORDS if not c["implemented"]]
    reserved.append(A.REDRAW_WITH_STAR_ACTION)
    assert len(reserved) == 9
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
#: for the fixed registry sizes passed below. The constellation key is the one
#: addition; every other row must stay exactly as it is, because a bound change
#: is a retrain trigger on the same terms as a shape change
#: (docs/rl-environment.md).
_EXPECTED_SPACE = {
    "allowance": ((1,), 0, 9999, "int16"),
    "axed_rooms": ((48,), 0, 1, "uint8"),
    "carryover": ((16,), 0, 999, "int16"),
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
    "phase": ("Discrete", 8, "int64"),
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
    """The observation space gains exactly one key and nothing else moves.

    Both halves matter and only one is obvious: a resized key silently
    reinterprets trained weights, and a widened BOUND does the same to a
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
    apart together.
    """
    assert len(IMPLEMENTED) == 5
    for cid, record in IMPLEMENTED.items():
        resource = record["grant"]["resource"]
        game = _observatory_game(stars=record["stars"])
        before = getattr(game.state, resource)
        assert game.view_night_sky() == (cid,), f"{cid} should be the whole sky here"
        assert game.can_activate_constellation(INDEX[cid])
        game.activate_constellation(INDEX[cid])
        assert getattr(game.state, resource) - before == record["grant"]["amount"], (
            f"{cid} granted the wrong amount of {resource}")


def test_the_eight_unimplemented_constellations_refuse_to_activate():
    """An unimplemented constellation can APPEAR in a sky -- it is part of the
    partition -- but never activates, so its effect cannot silently no-op.

    Each is set up at its own star count, where it is the entire sky, which is
    also what proves it really was present and was refused on the
    ``implemented`` flag rather than simply absent.
    """
    unimplemented = [c for c in RECORDS if not c["implemented"]]
    assert len(unimplemented) == 8
    for record in unimplemented:
        cid = record["id"]
        game = _observatory_game(stars=record["stars"])
        sky = game.view_night_sky()
        assert cid in sky, f"{cid} was not in the sky at {record['stars']} stars"
        assert not game.can_activate_constellation(INDEX[cid])
        assert not A.action_mask(game)[A.ACTIVATE_CONSTELLATION_BASE + INDEX[cid]]


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
