"""Room rotation behavior: south bias, Compass, mirroring, and free rotation."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.draft import redeal
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
    """Drafting northward, the orientation roll strongly favors the T without
    a north door (the south bias)."""
    # The no-north orientation is chosen more than either north-door option.
    counts = _sample(T_SOUTH, S, day=20, compass=False)
    assert counts[0] > counts[1] and counts[0] > counts[2]
    assert counts[0] > counts[1] + counts[2]   # in fact more than both combined


def test_compass_makes_a_north_door_the_likely_outcome():
    """The Compass inverts the south bias: with it, a north-door orientation
    becomes the common outcome instead of the rare one."""
    without = _sample(T_SOUTH, S, day=20, compass=False)
    withc = _sample(T_SOUTH, S, day=20, compass=True)
    # A north-door orientation is rare by default but the common case with one.
    assert without[0] > without[1] + without[2]
    assert (withc[1] + withc[2]) > withc[0]


def test_south_bias_relaxes_on_later_days():
    """The south bias weakens as days pass: the no-north weight drifts down
    while north-door weights drift up."""
    early = orientation_weights(T_SOUTH, S, day=1, compass=False)
    late = orientation_weights(T_SOUTH, S, day=25, compass=False)
    # The favored no-north share drifts down over the run; north doors drift up.
    assert late[0] < early[0]
    assert late[1] > early[1]


def test_east_and_west_rolls_are_mirror_images():
    """Orientation weights are symmetric across the N-S axis: an L drafted
    from the west rolls identically to its east-drafted mirror image."""
    # An L drafted from the west vs. the east is the same shape reflected across
    # the N-S axis, so the two must roll identically.
    west = orientation_weights([S | W, N | W], W, day=10, compass=False)
    east = orientation_weights([S | E, N | E], E, day=10, compass=False)
    assert west == east


def test_a_single_legal_orientation_takes_no_roll():
    """A room with one legal orientation is placed as-is - no weighted roll."""
    assert len(orientation_weights([N | S], S, day=20, compass=False)) == 1


def _drafting_hand(g, options, target=7, direction=N):
    """Put the game into DRAFTING with a hand-built pending draft."""
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=direction, target_cell=target)
    pd.options = options
    g.state.pending = pd
    return pd


def test_dovecote_enables_free_rotation():
    """A Dovecote in the hand grants free rotation: spinning advances an
    option to its next legal orientation while keeping the connecting door."""
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
    """Without a rotation source (Dovecote in hand or Ornate Compass),
    rotation is not available."""
    g = Game(GameConfig(), seed=1)
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    _drafting_hand(g, [
        DraftOption(room_idx=troom.idx, orientation=E | S | W, gem_cost=0, slot=0),
    ])
    assert not g.rotation_available()


def test_rotation_budget_covers_every_orientation_then_closes():
    """The per-hand rotation budget lets every option show all its legal
    orientations, then closes (rotation is cyclic, so an uncapped policy
    could spin forever); a redraw restores the budget."""
    # Free rotation is capped at max(legal orientations) - 1 spins per hand:
    # enough for every option to have shown each of its orientations, after
    # which further rotation could only revisit hand states already seen
    # (rotation is cyclic, so an uncapped deterministic policy can spin
    # forever). Here the T-room cycles with period 3 and the Dovecote with
    # period 2, so the budget is 2.
    g = Game(GameConfig(), seed=1)
    dov = g.registry.by_id["dovecote"]
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    pd = _drafting_hand(g, [
        DraftOption(room_idx=troom.idx, orientation=E | S | W, gem_cost=0, slot=0),
        DraftOption(room_idx=dov.idx, orientation=S | W, gem_cost=0, slot=1),
    ])
    seen = [{o.orientation} for o in pd.options]
    spins = 0
    while g.rotation_available():
        g.rotate_options()
        spins += 1
        for i, o in enumerate(pd.options):
            seen[i].add(o.orientation)
    assert spins == 2
    assert seen[0] == {E | S | W, N | S | W, N | E | S}   # all 3 south-door T's
    assert seen[1] == {S | W, E | S}                      # both south-door corners
    # A redraw deals a fresh hand and restores the budget.
    redeal(g.state, g.registry, g.cfg, g.rng, g.placed_ids, pd)
    assert pd.rotations_used == 0


def test_rotation_not_offered_when_every_option_is_pinned():
    """When every option has a single legal orientation, rotation is not
    offered (a deterministic policy would loop on the no-op), but
    rotate_options() stays a callable no-op so old recordings replay."""
    # Seed-1001214244 pathology: a Dovecote hand drafted on the top rank from
    # the west pins every floorplan to one legal orientation (no north doors on
    # rank 9, a west door is required), so rotating changes nothing. The action
    # must not be offered - a deterministic policy loops on the no-op forever -
    # but rotate_options() itself stays callable so old recordings replay.
    g = Game(GameConfig(), seed=1)
    dov = g.registry.by_id["dovecote"]
    dead = next(r for r in g.registry.rooms if r.layout == "dead_end" and r.rarity)
    pd = _drafting_hand(g, [
        DraftOption(room_idx=dead.idx, orientation=W, gem_cost=0, slot=0),
        DraftOption(room_idx=dov.idx, orientation=S | W, gem_cost=0, slot=1),
    ], target=41, direction=E)
    assert not g.rotation_available()
    before = [o.orientation for o in pd.options]
    g.rotate_options()                     # tolerated no-op for replay compat
    assert [o.orientation for o in pd.options] == before


def test_ornate_compass_rotates_every_draft():
    """The Ornate Compass grants rotation on every hand, with no Dovecote
    required among the options."""
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
    """Off-grid outer drafts (fixed orientation, no entry doorway) are never
    rotatable - regression guard for a KeyError crash in legal_orientations."""
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
