"""Datamined room-rotation weights and free-rotation (Dovecote/Rotunda)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, E, S, W
from blueprince_sim.engine.rotation import orientation_weights
from blueprince_sim.engine.state import DraftOption, PendingDraft

# T-shape legal orientations when a south connecting door is required (back=S),
# identified by their missing door.
T_MISS_N, T_MISS_E, T_MISS_W = E | S | W, N | S | W, N | S | E


def test_t_shape_weights_match_datamine():
    masks = [T_MISS_N, T_MISS_E, T_MISS_W]
    assert orientation_weights(masks, S, 1, False) == (70.0, 15.0, 15.0)
    assert orientation_weights(masks, S, 20, False) == (64.0, 18.0, 18.0)
    assert orientation_weights(masks, S, 25, False) == (60.0, 20.0, 20.0)


def test_compass_flips_bias_toward_north():
    masks = [T_MISS_N, T_MISS_E, T_MISS_W]
    # Default favors the no-north orientation; the Compass zeroes it and splits
    # the remaining north-door orientations.
    assert orientation_weights(masks, S, 20, False)[0] > 60.0
    assert orientation_weights(masks, S, 20, True) == (0.0, 50.0, 50.0)


def test_l_shape_weights_and_mirror():
    # From West: south-cornered ╗ favored over north-cornered ╝; East mirrors it.
    assert orientation_weights([S | W, N | W], W, 1, False) == (57.0, 43.0)
    assert orientation_weights([S | E, N | E], E, 1, False) == (57.0, 43.0)
    assert orientation_weights([S | W, N | W], W, 1, True) == (10.0, 90.0)


def test_single_orientation_is_uniform():
    assert orientation_weights([N | S], S, 20, False) == (1.0,)


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
