"""Statistical verification of the rarity roll against the datamined tables."""

import pytest
from scipy import stats

from blueprince_sim.config import GameConfig
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
    st, rng = _fresh_state(registry, cfg, "late", solarium=True)
    row = registry.weight_row("late", True, "slot23", 9)
    assert tuple(row) == (10.0, 20.0, 50.0, 20.0)
    counts = [0, 0, 0, 0]
    for _ in range(N_DRAWS):
        counts[roll_rarity(st, registry, cfg, rng, 2, 9)] += 1
    # rare should now be ~20%, vastly above the non-solarium 8%
    assert counts[3] / N_DRAWS > 0.15


def test_solarium_does_not_affect_slot1(registry, cfg):
    assert registry.weight_row("late", True, "slot1", 5) == \
        registry.weight_row("late", False, "slot1", 5)


def test_slot1_always_free(registry, cfg):
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
    tables = registry.weights["tables"]
    for stage, slots in tables.items():
        for slot_class, rows in slots.items():
            for rank, row in rows.items():
                assert abs(sum(row) - 100.0) < 0.02, (stage, slot_class, rank, row)
    for rank, row in registry.weights["solarium_slot23"].items():
        assert abs(sum(row) - 100.0) < 0.02
