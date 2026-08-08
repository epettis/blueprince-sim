"""Tests for the Garage's Forced Draw (data/priority_draws.json "forced_draws";
blueprince.wiki.gg/wiki/Garage). See draft.py's ``_forced_draw_garage`` /
``_garage_dead_end_gate``. Distinct from the pre-existing ``_priority_draw``
mechanism (patio group / commissary-observatory / classroom), which this does
not touch.
"""

from __future__ import annotations

from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry

GARAGE_ID = "garage"

# West Wing (col 0) cells, entered heading N -- legal Garage doorways (ranks 4-8).
SRC_A, TARGET_A = 15, 20   # rank4 -> rank5
SRC_B, TARGET_B = 25, 30   # rank6 -> rank7 (independent doorway, for the once-per-day test)

# Center column (col 2), entered heading N -- illegal for the Garage (not a wing),
# used to prove the mechanic never fires (and never even rolls) off-target.
CENTER_SRC, CENTER_TARGET = 17, 22


def _base_cfg(**kw) -> GameConfig:
    return GameConfig(door_locks=False, starting_steps=50, special_items=True, **kw)


def _place_corridor(game: Game, cell: int) -> None:
    """Hand-place an inert N|S corridor filler, mirroring test_foundation.py's
    ``_chain_to`` -- gives the source cell a north door without depending on
    what the ordinary draft RNG would have dealt there."""
    corridor = game.registry.by_id["corridor"]
    game._place_room(corridor, cell, N | S)


def _open_from(game: Game, cell: int, direction: int):
    game.state.pos = cell
    return game.open_door(cell, direction)


def _deal_at(cfg: GameConfig, seed: int, registry: Registry, src: int, direction: int):
    game = Game(cfg, seed=seed, registry=registry)
    _place_corridor(game, src)
    pending = _open_from(game, src, direction)
    return game, pending


def _offer_hits(cfg: GameConfig, registry: Registry, src: int, direction: int,
               n: int, seed0: int = 0) -> int:
    """Count, over ``n`` seeds, how many single-hand deals at ``(src, direction)``
    include the Garage among the dealt options."""
    garage_idx = registry.by_id[GARAGE_ID].idx
    hits = 0
    for seed in range(seed0, seed0 + n):
        game, pending = _deal_at(cfg, seed, registry, src, direction)
        if any(o.room_idx == garage_idx for o in pending.options):
            hits += 1
    return hits


def test_forced_draw_offer_rate_jumps_when_gate_satisfied(registry: Registry):
    """At a doorway where the Garage's placement conditions are always met (West
    Wing, rank 4->5, entered north), the offer rate goes from ~never (Day 2, gate
    unmet) to the wiki's ~90% (Day 5, gate met) -- pinning the Forced Draw as an
    actual behavior change in the real deal_draft pipeline, not just data.

    The Day-2 arm sets veteran_mode=False explicitly: the gate is "Veteran Mode
    OR Day 3", so leaving it to the config default would silently stop testing
    the day half of it once that default is veteran (which it now is).
    """
    n = 600
    before = _offer_hits(_base_cfg(day=2, veteran_mode=False), registry, SRC_A, N, n, seed0=0)
    after = _offer_hits(_base_cfg(day=5), registry, SRC_A, N, n, seed0=10_000_000)
    assert before < n * 0.05, f"Day 2 (gate unmet) offered the Garage {before}/{n} times"
    assert after > n * 0.6, f"Day 5 (gate met) only offered the Garage {after}/{n} times"


def test_forced_draw_blocked_before_day_3(registry: Registry):
    """The wiki's "Veteran Mode is active, or Day 3 has been reached" gate: Day 2
    with Veteran Mode off must not trigger the Forced Draw, even though the same
    doorway lights up dramatically on Day 3."""
    n = 400
    day2 = _offer_hits(_base_cfg(day=2, veteran_mode=False), registry, SRC_A, N, n, seed0=0)
    day3 = _offer_hits(_base_cfg(day=3, veteran_mode=False), registry, SRC_A, N, n,
                       seed0=10_000_000)
    assert day2 == 0, f"Forced Draw must not fire before Day 3: got {day2}/{n} on Day 2"
    assert day3 > n * 0.6, f"Forced Draw should be active on Day 3: got {day3}/{n}"


def test_forced_draw_veteran_mode_substitutes_for_day_gate(registry: Registry):
    """Veteran Mode alone (independent of the day counter) satisfies the same
    gate as Day 3+ -- the wiki phrases the two as alternatives ("or"), and a
    Day-2 veteran run must behave like the Day-5 case above, not the Day-2 one."""
    n = 400
    hits = _offer_hits(_base_cfg(day=2, veteran_mode=True), registry, SRC_A, N, n, seed0=0)
    assert hits > n * 0.6, f"Veteran Mode should unlock the Forced Draw pre-Day-3: {hits}/{n}"


def test_forced_draw_west_gate_boosts_success_chance(registry: Registry):
    """The wiki's West Gate boost (90% -> 92.5%) is a small but real, measurable
    increase in offer rate at the same always-legal doorway -- large N because the
    effect size is only 2.5 points, unlike the Day-3 gate's all-or-nothing jump."""
    n = 20_000
    without = _offer_hits(_base_cfg(day=5, west_gate_unlatched=False), registry, SRC_A, N, n,
                          seed0=0)
    with_gate = _offer_hits(_base_cfg(day=5, west_gate_unlatched=True), registry, SRC_A, N, n,
                            seed0=30_000_000)
    table = [[without, n - without], [with_gate, n - with_gate]]
    _, p, _, _ = stats.chi2_contingency(table)
    assert with_gate > without, (without, with_gate)
    assert p < 0.01, (
        f"West Gate boost not statistically distinguishable: without={without}/{n} "
        f"with={with_gate}/{n} p={p}"
    )


def test_forced_draw_never_fires_at_an_illegal_doorway(registry: Registry):
    """Off a doorway where the Garage's own draft conditions fail (here: center
    column, never a "wing"), the Forced Draw must not fire -- and must consume no
    randomness at all, so doorways where the Garage was never a candidate cannot
    perturb any other draw's RNG stream (see draft.py's eligibility-first design
    and the sibling "the Foundation" rank-3 mechanic's identical contract)."""
    cfg = _base_cfg(day=10, veteran_mode=True)  # gate wide open; only geometry should matter
    garage_idx = registry.by_id[GARAGE_ID].idx
    for seed in range(50):
        game, pending = _deal_at(cfg, seed, registry, CENTER_SRC, N)
        assert not any(o.room_idx == garage_idx for o in pending.options), (
            "Garage must never be dealt at a doorway where its own conditions fail"
        )
        # The "forced_draw_garage" RNG substream is created lazily on first use
        # (engine/rng.py::Rng.stream); if it was never created, the roll was
        # never attempted, proving zero perturbation of unrelated draws.
        assert "forced_draw_garage" not in game.rng._streams, (
            "an ineligible doorway must not consume the forced-draw RNG stream"
        )


def test_forced_draw_fires_at_most_once_per_day(registry: Registry):
    """Once the per-day flag is set (a real success already happened), the Forced
    Draw must not re-trigger at a second, independent legal doorway the same
    day -- the wiki: "they will no longer be available for Forced Draws" once
    the roll has succeeded, even on a fresh empty doorway elsewhere in the house."""
    cfg = _base_cfg(day=5, veteran_mode=False)
    garage_idx = registry.by_id[GARAGE_ID].idx
    game = Game(cfg, seed=7, registry=registry)
    game.state.garage_forced_draw_succeeded = True  # simulate an earlier success today
    _place_corridor(game, SRC_B)
    pending = _open_from(game, SRC_B, N)
    assert not any(o.room_idx == garage_idx and o.forced for o in pending.options), (
        "a second legal doorway must not force-draw the Garage once today's roll "
        "has already succeeded"
    )


def test_forced_draw_is_deterministic_for_a_given_seed(registry: Registry):
    """Same seed, same doorway -> identical dealt hand (room/orientation/cost/slot/
    forced/hidden for every option) -- the engine's seeded-replay invariant must
    hold for the new mechanic exactly like every other RNG-driven draft feature."""
    cfg = _base_cfg(day=5)

    def _snapshot(seed: int):
        _game, pending = _deal_at(cfg, seed, registry, SRC_A, N)
        return [(o.room_idx, o.orientation, o.gem_cost, o.slot, o.forced, o.hidden)
                for o in pending.options]

    for seed in (1, 2, 3, 42):
        assert _snapshot(seed) == _snapshot(seed), f"seed {seed} was not deterministic"
