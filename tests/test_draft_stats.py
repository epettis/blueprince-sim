"""Statistical verification of the rarity roll against the datamined tables."""

import pytest
from scipy import stats

from blueprince_sim.engine.decks import build_decks, roll_rarity
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState

N_DRAWS = 30_000
ALPHA = 0.001 / 36  # Bonferroni over stage x slot x sampled-ranks cells


def _fresh_state(registry, cfg, stage, solarium, seed=0):
    rng = Rng(seed)
    st = GameState()
    st.stage = stage
    st.solarium_placed = solarium
    st.decks = build_decks(registry, cfg, rng)
    return st, rng


@pytest.mark.parametrize("stage", ["week1", "week2", "late"])
@pytest.mark.parametrize("slot", [0, 1])
@pytest.mark.parametrize("rank", [1, 5, 9])
def test_rarity_roll_matches_table(registry, cfg, stage, slot, rank):
    """The rarity roll reproduces the datamined stage/slot/rank weight table
    (chi-square over 30k draws), after zeroing rarities whose decks fail the
    size gates exactly as the engine does. A failure here means the draft math
    regressed, not that the test is flaky."""
    st, rng = _fresh_state(registry, cfg, stage, solarium=False)
    slot_class = "slot1" if slot == 0 else "slot23"
    expected = list(registry.weight_row(stage, False, slot_class, rank))

    # Zero out rarities whose decks fail the size gates, as the engine will.
    from blueprince_sim.engine.decks import rarity_deck_ok
    for i in range(4):
        if not rarity_deck_ok(st, registry, cfg, i, free_only=(slot == 0)):
            expected[i] = 0.0
    total = sum(expected)
    expected = [e / total for e in expected]

    counts = [0, 0, 0, 0]
    for _ in range(N_DRAWS):
        r = roll_rarity(st, registry, cfg, rng, slot, rank)
        counts[r] += 1

    exp_counts = [e * N_DRAWS for e in expected]
    # chi-square over cells with nonzero expectation
    obs, exp = zip(*[(c, e) for c, e in zip(counts, exp_counts) if e > 0])
    assert all(c == 0 for c, e in zip(counts, exp_counts) if e == 0), \
        "rolled a rarity whose weight is zero"
    _, p = stats.chisquare(obs, exp)
    assert p > ALPHA, f"distribution mismatch: counts={counts} expected={exp_counts}"


def test_solarium_flattens_slot23(registry, cfg):
    """A placed Solarium flattens the slot-2/3 rarity weights, so rare rooms
    are dealt far more often (>2x) than without it."""
    def rare_rate(solarium):
        st, rng = _fresh_state(registry, cfg, "late", solarium=solarium)
        rares = sum(roll_rarity(st, registry, cfg, rng, 2, 9) == 3
                    for _ in range(N_DRAWS))
        return rares / N_DRAWS

    # The Solarium flattens slot-2/3 weights, so rare rooms roll far more often.
    assert rare_rate(solarium=True) > 2 * rare_rate(solarium=False)


def test_solarium_does_not_affect_slot1(registry, cfg):
    """The Solarium's flattening applies only to slots 2/3; slot-1 rarity
    weights are identical with or without it."""
    assert registry.weight_row("late", True, "slot1", 5) == \
        registry.weight_row("late", False, "slot1", 5)


def test_slot1_always_free(registry, cfg):
    """Slot 1 is always dealt and always holds a free room (gem cost 0), so a
    draft can never leave the player unable to afford any option."""
    game = Game(cfg, seed=3)
    for seed in range(60):
        game.reset(seed)
        doors = game.open_doorways()
        pending = game.open_door(*doors[0])
        slot0 = [o for o in pending.options if o.slot == 0]
        assert slot0, "slot 1 must always be dealt"
        assert slot0[0].gem_cost == 0
        room = game.registry.rooms[slot0[0].room_idx]
        assert room.is_free, f"slot 1 dealt gem room {room.name}"


def test_weights_rows_sum_to_100(registry):
    """Every rarity-weight row (including the Solarium slot-2/3 table) sums to
    100%, so the roll's percentage interpretation is well-formed."""
    tables = registry.weights["tables"]
    for stage, slots in tables.items():
        for slot_class, rows in slots.items():
            for rank, row in rows.items():
                assert abs(sum(row) - 100.0) < 0.02, (stage, slot_class, rank, row)
    for rank, row in registry.weights["solarium_slot23"].items():
        assert abs(sum(row) - 100.0) < 0.02
