"""Billiard Room: the Dartboard puzzle's day-banded reward and its once-per-day cap.

The puzzle itself is unmodelled -- this sim assumes puzzles are solved -- so
entering a freshly-drafted Billiard Room auto-resolves it via
effects/rooms/billiard_room.py. These tests force the reward roll
deterministically (mirroring tests/test_locks.py's _FixedChoiceRng idiom, but
for Rng.roll_weighted rather than Rng.choice) so the distribution is proved
against real band data, not a statistical bar over a stochastic quantity.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.effects.rooms import billiard_room as br
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.rng import Rng


class _FixedWeightedRng:
    """Wraps a real engine.rng.Rng, overriding ``.roll_weighted`` for exactly
    one label to a fixed index -- every other draw still comes from the real
    substream underneath. Mirrors test_locks.py's ``_FixedChoiceRng`` idiom,
    adapted to ``roll_weighted`` since the Dartboard's reward roll uses that
    method, not ``.choice``.
    """

    def __init__(self, real: Rng, label: str, index: int) -> None:
        self._real = real
        self._label = label
        self._index = index

    def __getattr__(self, name):
        return getattr(self._real, name)

    def roll_weighted(self, label, weights):
        if label == self._label:
            return self._index
        return self._real.roll_weighted(label, weights)


def _game(day: int, *, veteran_mode: bool = False, room46_reached: bool = False,
          seed: int = 1) -> Game:
    """A fresh Game on ``day``, Veteran Mode off by default so day-band tests
    actually exercise the finite bands instead of always hitting the
    open-ended one (GameConfig.veteran_mode defaults True)."""
    return Game(GameConfig(day=day, veteran_mode=veteran_mode, room46_reached=room46_reached),
                seed=seed)


def _force_index(g: Game, index: int) -> None:
    """Forces the Dartboard's own reward roll to ``index`` regardless of the
    band's real weights, so the test proves the grant logic rather than
    hunting for a seed that happens to land on the desired outcome."""
    g.rng = _FixedWeightedRng(g.rng, br.REWARD_ROLL_LABEL, index)


def _place(g: Game, room_id: str, cell: int) -> None:
    """Place a room on the grid directly (test setup, no drafting)."""
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = 0
    g.state.entered[cell] = False


def _enter(g: Game, cell: int) -> None:
    """Teleport the player to cell and fire ON_ENTER, without spending steps."""
    g.state.pos = cell
    g._enter(cell)


# --------------------------------------------------------- band selection


def test_band_for_selects_day_1_7_band():
    """_band_for returns the day_1_7 band for a day inside [1, 7], with
    Veteran Mode and Room 46 both off."""
    g = _game(day=5)
    assert br._band_for(g).id == "day_1_7"


def test_band_for_selects_day_8_12_band():
    """_band_for returns the day_8_12 band for a day inside [8, 12]."""
    g = _game(day=10)
    assert br._band_for(g).id == "day_8_12"


def test_band_for_selects_day_13_21_band_in_nineteenths():
    """_band_for returns the day_13_21 band, whose weights sum to 19 (the
    published nineteenths), not 100 like every other band."""
    g = _game(day=17)
    band = br._band_for(g)
    assert band.id == "day_13_21"
    assert sum(band.weights) == 19


def test_band_boundary_day_21_uses_the_finite_band_not_the_open_one():
    """Mutation guard on the day-22 boundary: day 21 (the last day of the
    finite day_13_21 band) must NOT fall into the open-ended band -- a
    boundary shifted by one (e.g. `>= 21` instead of `>= 22`) would make this
    fail."""
    g = _game(day=21)
    assert br._band_for(g).id == "day_13_21", (
        "day 21 must still resolve to the finite day_13_21 band")


def test_band_boundary_day_22_uses_the_open_ended_band():
    """Mutation guard on the day-22 boundary: day 22 must switch to the
    open-ended Veteran/Room46/Day22+ band -- the complement of the test
    above, pinning the exact cutoff from both sides."""
    g = _game(day=22)
    assert br._band_for(g).id == "veteran_room46_day22plus", (
        "day 22 must switch to the open-ended band")


def test_veteran_mode_selects_the_open_ended_band_even_on_an_early_day():
    """Veteran Mode forces the open-ended band regardless of the day counter,
    per the wiki's own top row ('Veteran Mode active ... OR Day 22+')."""
    g = _game(day=1, veteran_mode=True)
    assert br._band_for(g).id == "veteran_room46_day22plus"


def test_room46_reached_selects_the_open_ended_band_even_on_an_early_day():
    """Room 46 having been reached before also forces the open-ended band,
    independent of Veteran Mode and the day counter (the wiki's third OR
    condition on that top row)."""
    g = _game(day=1, room46_reached=True)
    assert br._band_for(g).id == "veteran_room46_day22plus"


# --------------------------------------------------------- reward granting


def test_dartboard_grants_secret_garden_key_at_index_zero():
    """Forcing the reward roll to index 0 grants a Secret Garden Key -- the
    first outcome in every band's fixed (secret_garden_key, silver_key,
    keycard, two_keys) order."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _force_index(g, 0)

    _enter(g, 5)

    assert g.state.inventory.get("secret_garden_key", 0) == 1
    assert g.state.dartboard_solved_today is True


def test_dartboard_grants_silver_key_at_index_one():
    """Forcing the reward roll to index 1 grants a Silver Key."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _force_index(g, 1)

    _enter(g, 5)

    assert g.state.inventory.get("silver_key", 0) == 1


def test_dartboard_grants_keycard_at_index_two():
    """Forcing the reward roll to index 2 grants the Keycard (state.has_keycard,
    not the inventory dict -- see effects/items/keycard.py)."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _force_index(g, 2)

    _enter(g, 5)

    assert g.state.has_keycard is True


def test_dartboard_grants_two_keys_at_index_three():
    """Forcing the reward roll to index 3 grants 2 plain keys (state.keys),
    the wiki's 'A pile of 2 keys' prize -- not a special/door-specific key."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _force_index(g, 3)
    before = g.state.keys

    _enter(g, 5)

    assert g.state.keys == before + 2


# --------------------------------------------------------- fallback chain


def test_secret_garden_key_unavailable_falls_back_to_the_keycard():
    """Published fallback: when the rolled Secret Garden Key cannot be
    granted (already held, so special_items._is_available is False), the
    Dartboard falls back to the Keycard instead of silently granting
    nothing."""
    g = _game(day=3)
    g.state.inventory["secret_garden_key"] = 1  # already held: unavailable again today
    _place(g, "billiard_room", 5)
    _force_index(g, 0)  # rolled outcome: secret_garden_key

    _enter(g, 5)

    assert g.state.inventory["secret_garden_key"] == 1, "must not double-grant the held key"
    assert g.state.has_keycard is True, "must fall back to the Keycard"


def test_secret_garden_key_and_keycard_both_unavailable_falls_back_to_two_keys():
    """Published fallback chain's second link: Secret Garden Key unavailable
    AND the Keycard already held falls all the way through to 2 plain keys,
    per the wiki's 'Keycard -> 2 keys' fallback priority."""
    g = _game(day=3)
    g.state.inventory["secret_garden_key"] = 1
    g.state.has_keycard = True
    _place(g, "billiard_room", 5)
    _force_index(g, 0)
    before = g.state.keys

    _enter(g, 5)

    assert g.state.keys == before + 2, "must fall all the way through to 2 keys"


# --------------------------------------------------------- once per day


def test_dartboard_solves_only_once_per_day_across_two_billiard_room_cells():
    """Owner ruling: the Dartboard pays out at most once per day. A second
    billiard_room cell entered the same day (e.g. from the Chamber of
    Mirrors -- game.py's own comment: 'duplicates are only possible via the
    Chamber of Mirrors') must NOT pay out again, even though st.entered is
    keyed per cell and would otherwise let ON_ENTER fire a second time."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _place(g, "billiard_room", 6)
    _force_index(g, 3)  # two_keys: easiest outcome to count precisely
    before = g.state.keys

    _enter(g, 5)
    assert g.state.keys == before + 2, "the first solve must pay out"

    _enter(g, 6)
    assert g.state.keys == before + 2, (
        "a second billiard_room cell must NOT pay out a second time in one day")


def test_dartboard_second_entry_the_same_cell_grants_nothing_additional():
    """Mutation guard on the once-per-day flag itself: flipping
    ``if st.dartboard_solved_today: return`` to its opposite (or dropping it)
    would let a manually-repeated call re-grant -- calling the handler
    directly a second time (bypassing st.entered's own first-entry guard)
    must still be a no-op."""
    g = _game(day=3)
    room = g.registry.by_id["billiard_room"]
    _force_index(g, 3)
    before = g.state.keys

    br.solve_dartboard(g, room, None)
    assert g.state.keys == before + 2

    br.solve_dartboard(g, room, None)
    assert g.state.keys == before + 2, (
        "dartboard_solved_today must block every subsequent solve this day")


def test_dartboard_resets_and_solves_again_the_next_game():
    """dartboard_solved_today carries no _CARRYOVER_KEYS entry and no
    GameConfig field (same shape as grotto_chip_taken): a fresh Game starts
    with it False and the Dartboard pays out again."""
    g = _game(day=3)
    _place(g, "billiard_room", 5)
    _force_index(g, 3)
    _enter(g, 5)
    assert g.state.dartboard_solved_today is True

    tomorrow = _game(day=4)
    assert tomorrow.state.dartboard_solved_today is False
    _place(tomorrow, "billiard_room", 5)
    _force_index(tomorrow, 3)
    before = tomorrow.state.keys

    _enter(tomorrow, 5)

    assert tomorrow.state.keys == before + 2, "the pedestal-equivalent must be solvable again"
