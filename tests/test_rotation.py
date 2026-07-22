"""Room rotation behavior: south bias, Compass, mirroring, and free rotation."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, E, S, W
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.rotation import orientation_weights
from blueprince_sim.engine.state import DraftOption, PendingDraft

# A T-shape needing a south connecting door has three legal orientations; of
# them only T_NO_NORTH lacks a north door.
T_NO_NORTH = E | S | W
T_WITH_N1 = N | S | W
T_WITH_N2 = N | S | E
T_SOUTH = [T_NO_NORTH, T_WITH_N1, T_WITH_N2]


def _sample(masks, back, day, compass, n=4000):
    """How often each orientation is chosen, through the real weighted RNG."""
    weights = orientation_weights(masks, back, day, compass)
    counts = [0] * len(masks)
    for seed in range(n):
        counts[Rng(seed).roll_weighted("orientation", weights)] += 1
    return counts


def test_default_roll_usually_keeps_a_south_facing_back_wall():
    # The no-north orientation is chosen more than either north-door option.
    counts = _sample(T_SOUTH, S, day=20, compass=False)
    assert counts[0] > counts[1] and counts[0] > counts[2]
    assert counts[0] > counts[1] + counts[2]   # in fact more than both combined


def test_compass_makes_a_north_door_the_likely_outcome():
    without = _sample(T_SOUTH, S, day=20, compass=False)
    withc = _sample(T_SOUTH, S, day=20, compass=True)
    # A north-door orientation is rare by default but the common case with one.
    assert without[0] > without[1] + without[2]
    assert (withc[1] + withc[2]) > withc[0]


def test_south_bias_relaxes_on_later_days():
    early = orientation_weights(T_SOUTH, S, day=1, compass=False)
    late = orientation_weights(T_SOUTH, S, day=25, compass=False)
    # The favored no-north share drifts down over the run; north doors drift up.
    assert late[0] < early[0]
    assert late[1] > early[1]


def test_east_and_west_rolls_are_mirror_images():
    # An L drafted from the west vs. the east is the same shape reflected across
    # the N-S axis, so the two must roll identically.
    west = orientation_weights([S | W, N | W], W, day=10, compass=False)
    east = orientation_weights([S | E, N | E], E, day=10, compass=False)
    assert west == east


def test_a_single_legal_orientation_takes_no_roll():
    assert len(orientation_weights([N | S], S, day=20, compass=False)) == 1


def _drafting_hand(g, options, target=7, direction=N):
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=direction, target_cell=target)
    pd.options = options
    g.state.pending = pd
    return pd


def test_dovecote_enables_free_rotation():
    g = Game(GameConfig(), seed=1)
    dov = g.registry.by_id["dovecote"]
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    pd = _drafting_hand(g, [
        DraftOption(room_idx=troom.idx, orientation=E | S | W, gem_cost=0, slot=0),
        DraftOption(room_idx=dov.idx, orientation=dov.door_mask, gem_cost=0, slot=1),
    ])
    assert g.rotation_available()
    before = pd.options[0].orientation
    g.rotate_options()
    after = pd.options[0].orientation
    assert after != before                 # spun to the next legal orientation
    assert after & S                        # still connects back to the doorway


def test_no_rotation_without_a_source():
    g = Game(GameConfig(), seed=1)
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    _drafting_hand(g, [
        DraftOption(room_idx=troom.idx, orientation=E | S | W, gem_cost=0, slot=0),
    ])
    assert not g.rotation_available()


def test_ornate_compass_rotates_every_draft():
    # Unlike the Dovecote, the Ornate Compass grants rotation on any hand.
    g = Game(GameConfig(ornate_compass=True), seed=1)
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    pd = _drafting_hand(g, [
        DraftOption(room_idx=troom.idx, orientation=E | S | W, gem_cost=0, slot=0),
    ])
    assert g.rotation_available()          # no Dovecote in the hand, still rotatable
    before = pd.options[0].orientation
    g.rotate_options()
    assert pd.options[0].orientation != before and pd.options[0].orientation & S


def test_outer_draft_is_never_rotatable():
    # Outer rooms sit off-grid with a fixed orientation and no entry doorway
    # (target_cell == -1, direction == 0). Even with a rotation source in play,
    # rotation must not apply - previously this crashed in legal_orientations
    # with KeyError: 0 on OPPOSITE[direction].
    g = Game(GameConfig(ornate_compass=True), seed=1)
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    pd.options = [DraftOption(room_idx=troom.idx, orientation=E | S | W,
                              gem_cost=0, slot=0)]
    g.state.pending = pd
    assert not g.rotation_available()
