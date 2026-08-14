"""The constellation data, the reserved action block, and the observation key.

Everything the constellation build declares is inert here: the action ids exist
but are permanently masked, and the observation key is always zeros. What these
tests pin is the part that cannot be changed later -- the action-space width and
the observation-space shape -- plus the rule the data encodes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.env import actions as A
from blueprince_sim.env import obs as O
from blueprince_sim.rl.train import all_unlocks_config

DATA = Path(__file__).resolve().parents[1] / "src" / "blueprince_sim" / "data"
DOC = json.loads((DATA / "constellations.json").read_text(encoding="utf-8"))
STARS = {c["id"]: c["stars"] for c in DOC["constellations"]}
APPEARANCES = DOC["appearances"]


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


def test_every_constellation_id_is_masked_off():
    """No id in 442..456 is ever legal: nothing in the engine generates a night
    sky, so the whole block is reserved.

    Swept over played-out days on both presets rather than checked at a single
    reset, since the mask is phase- and position-dependent everywhere else --
    a block that only went legal deep in a day would pass a step-0 check.
    """
    for cfg in (GameConfig(), all_unlocks_config()):
        for seed in range(6):
            game = Game(cfg, seed=seed)
            for _ in range(120):
                mask = A.action_mask(game)
                assert len(mask) == A.N_ACTIONS
                assert not any(mask[A.ACTIVATE_CONSTELLATION_BASE:]), (
                    f"seed {seed}: a reserved constellation id went legal"
                )
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


def test_the_constellation_observation_is_always_zeros():
    """The key encodes as zeros in every state, because no night sky is ever
    generated -- nothing activated, no sky today, none at the player's cell.

    Swept over real play rather than a fresh reset: an encoder that read a
    real field would show up somewhere in a day, not at step 0.
    """
    for seed in range(5):
        game = Game(GameConfig(), seed=seed)
        for _ in range(40):
            encoded = O.encode(game)["constellations"]
            assert encoded.shape == (O.CONSTELLATION_OBS_LEN,)
            assert encoded.dtype == np.int16
            assert not encoded.any()
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
