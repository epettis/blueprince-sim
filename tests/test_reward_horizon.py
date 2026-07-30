"""Tests for the reward-horizon feature: terminated/truncated semantics
and new observation keys for day-chain episodes.

Part 1 pins the day-end terminated/truncated split that allows SB3 to
bootstrap V(s) across day boundaries. Part 2 pins the new 'day' and
'carryover' observation keys.
"""

from __future__ import annotations

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain, _CARRYOVER_KEYS


# ------------------------------------------------------------------ helpers

def _chain_env(n_days: int = 3, starting_steps: int = 3,
               **cfg_kwargs) -> BluePrinceEnv:
    """Return a BluePrinceEnv wired to a short DayChain for fast testing."""
    base = GameConfig(starting_steps=starting_steps, **cfg_kwargs)
    chain = DayChain(base, n_days=n_days)
    return BluePrinceEnv(cfg=base, day_chain=chain)


def _run_episode(env: BluePrinceEnv, seed: int = 0):
    """Step an episode to completion; returns (obs, reward, terminated, truncated, info)."""
    obs, info = env.reset(seed=seed)
    rng = np.random.default_rng(seed)
    last = (obs, 0.0, False, False, info)
    while True:
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        action = int(rng.choice(legal))
        last = env.step(action)
        obs, reward, terminated, truncated, info = last
        if terminated or truncated:
            break
    return last


# ================================================================= Part 1: terminated/truncated

def test_chain_midattempt_day_end_is_truncated():
    """A day ending mid-attempt (not the last day) reports terminated=False, truncated=True.

    SB3's DummyVecEnv converts truncated=True into info['TimeLimit.truncated']=True,
    which triggers bootstrapping of V(terminal_observation) so cross-day value flows back.
    """
    env = _chain_env(n_days=3)
    env.reset(seed=0)
    _, _, terminated, truncated, _ = _run_episode(env, seed=0)
    # Day 1 of 3: not the last day, so must be a truncation
    assert not terminated, "mid-attempt day end must not be terminated"
    assert truncated, "mid-attempt day end must be truncated"


def test_chain_final_day_is_terminated():
    """The last day of an attempt reports terminated=True, truncated=False.

    Only the attempt boundary is a true absorbing state; bootstrapping there
    would be incorrect (the game resets to day 1, not continues from the value).
    """
    env = _chain_env(n_days=3)
    # Run all 3 days; the 3rd day end should be a true terminal
    found_terminal = False
    for seed in range(5):
        env.reset(seed=seed)
        _, _, terminated, truncated, info = _run_episode(env, seed=seed)
        if info.get("day") == 3:
            assert terminated, "final day must be terminated"
            assert not truncated, "final day must not be truncated"
            found_terminal = True
            break
    assert found_terminal, "never reached the final day (day 3) in 5 seeds"


def test_no_chain_day_end_is_terminated():
    """Single-day mode (no chain) still reports terminated=True at game end.

    Regression guard: the chain changes must not alter single-day behaviour
    that existing tests and deployments depend on.
    """
    env = BluePrinceEnv(cfg=GameConfig(starting_steps=3))
    env.reset(seed=0)
    _, _, terminated, truncated, _ = _run_episode(env, seed=0)
    assert terminated, "single-day mode must report terminated=True at game end"


# ================================================================= Part 2: observation keys

def test_day_obs_advances_across_days():
    """The 'day' obs key advances across consecutive days and days_remaining decreases.

    Without this the value function cannot distinguish day 2 from day 190,
    diluting any cross-day investment signal.
    """
    env = _chain_env(n_days=5)
    env.reset(seed=0)
    obs_step, _, _, _, _ = env.step(int(np.flatnonzero(env.action_masks())[0]))
    day1_vec = obs_step["day"]
    assert int(day1_vec[0]) == 1, "current_day should be 1 on day 1"
    assert int(day1_vec[1]) == 4, "days_remaining should be n_days-1=4 on day 1"

    # End day 1, advance to day 2
    _run_episode(env, seed=0)
    env.reset(seed=1)
    obs2, _, _, _, _ = env.step(int(np.flatnonzero(env.action_masks())[0]))
    day2_vec = obs2["day"]
    assert int(day2_vec[0]) == 2, "current_day should be 2 on day 2"
    assert int(day2_vec[1]) == 3, "days_remaining should be 3 on day 2"


def test_carryover_obs_reflects_discovery_next_day():
    """A carry-over flag set during a day appears in the next day's carryover obs.

    Pins the flow: flag set in carried_flags -> advance() -> next reset() ->
    carryover obs shows it. Cleared after an attempt wrap.
    """
    env = _chain_env(n_days=3)
    env.reset(seed=0)

    # Inject a flag directly to simulate in-game discovery
    env.day_chain.carried_flags["lunch_box_unlocked"] = True

    # Complete day 1 (advance() fires, flag persists into day 2)
    _run_episode(env, seed=0)

    # Day 2: carryover obs should reflect the discovered flag
    obs2, _ = env.reset(seed=1)
    carryover_vec = obs2["carryover"]
    key_order = sorted(_CARRYOVER_KEYS)
    idx = key_order.index("lunch_box_unlocked")
    assert carryover_vec[idx] == 1, "lunch_box_unlocked must appear in day 2 carryover obs"

    # Run days 2 and 3 (day 3 ends the attempt and wraps to a fresh attempt)
    _run_episode(env, seed=1)
    _run_episode(env, seed=2)

    # Day 1 of the new attempt: carryover should be all zeros
    obs_fresh, _ = env.reset(seed=3)
    assert all(obs_fresh["carryover"] == 0), "carryover obs must be all-zero after attempt wrap"


def test_carryover_vector_length_matches_carryover_keys():
    """The carryover obs vector length equals len(DayChain._CARRYOVER_KEYS).

    Pins the derivation so that adding a carry-over key cannot silently desync
    the observation vector from the declared space.
    """
    env = _chain_env(n_days=3)
    obs, _ = env.reset(seed=0)
    assert len(obs["carryover"]) == len(DayChain._CARRYOVER_KEYS)


def test_observation_space_contains_chain_obs():
    """observation_space.contains(obs) holds for a freshly encoded chain-mode obs.

    Catches dtype/bounds drift between the space declaration and the encoder.
    """
    env = _chain_env(n_days=3)
    obs, _ = env.reset(seed=0)
    assert env.observation_space.contains(obs), (
        "Chain-mode observation is outside the declared observation_space"
    )


def test_observation_space_contains_single_day_obs():
    """observation_space.contains(obs) holds for a freshly encoded single-day obs.

    Catches dtype/bounds drift in the no-chain path.
    """
    env = BluePrinceEnv(cfg=GameConfig(starting_steps=3))
    obs, _ = env.reset(seed=0)
    assert env.observation_space.contains(obs), (
        "Single-day observation is outside the declared observation_space"
    )


# ------------------------------------------- Part 3: upgrade observability

def test_all_slot_ids_is_sorted_and_matches_the_registry_mapping():
    """all_slot_ids is sorted and covers exactly the slots upgraded_slots can produce.

    Sorted order is load-bearing: the vector's field positions must be identical
    across processes, and Python randomises string hashing, so an unsorted
    derivation would silently permute the observation between training runs.
    """
    from blueprince_sim.engine.model import Registry
    from blueprince_sim.engine.upgrades import all_slot_ids, upgraded_slots

    registry = Registry.load()
    slots = all_slot_ids(registry)
    assert list(slots) == sorted(slots), "slot order must be deterministic across processes"

    every_variant = frozenset(r.id for r in registry.rooms if r.variant_of is not None)
    assert set(slots) == set(upgraded_slots(every_variant, registry)), (
        "the slot vocabulary must equal what upgraded_slots can emit, or the "
        "observation vector has positions nothing can ever fill"
    )


def test_applying_an_upgrade_sets_exactly_that_slot_bit():
    """Applying one upgrade variant flips its own slot to 1 and no other slot.

    This is the signal that makes a permanent upgrade visible to the value
    function at all; without it V(s) cannot tell an upgraded attempt from a fresh one.
    """
    from blueprince_sim.engine.model import Registry
    from blueprince_sim.engine.upgrades import all_slot_ids, upgraded_slots
    from blueprince_sim.env import obs as O

    registry = Registry.load()
    slot_ids = all_slot_ids(registry)
    variant = next(r for r in registry.rooms if r.variant_of == "cloister")

    env = BluePrinceEnv(cfg=GameConfig(special_items=True))
    env.reset(seed=3)
    before = O.encode(env.game)["upgrade_slots"]
    assert not before.any(), "a fresh day must start with no slots upgraded"

    env.game.state.applied_upgrades.add(variant.id)
    after = O.encode(env.game)["upgrade_slots"]

    expected = upgraded_slots(frozenset({variant.id}), env.game.registry)
    flipped = {slot_ids[i] for i in range(len(slot_ids)) if after[i] and not before[i]}
    assert flipped == set(expected), (
        f"applying {variant.id} must flip exactly {expected}, but flipped {flipped}"
    )


def test_upgrade_slots_survive_the_day_boundary():
    """An upgrade applied on one day is still visible in the next day's observation.

    This is the cross-day investment property the horizon change exists to make
    learnable: if it regressed, the bootstrapped V(s) would value a permanent
    upgrade at nothing on the very next day.
    """
    from blueprince_sim.engine.model import Registry
    from blueprince_sim.env import obs as O

    registry = Registry.load()
    variant = next(r for r in registry.rooms if r.variant_of == "cloister")

    env = _chain_env(n_days=3, special_items=True)
    env.reset(seed=5)
    # Record the upgrade the way a real insert does: on the day's carryover path.
    env.game.state.applied_upgrades.add(variant.id)
    day1 = O.encode(env.game, env.day_chain)["upgrade_slots"].copy()
    assert day1.any(), "the upgrade must be visible on the day it is applied"

    env.day_chain.advance(env.game.carryover())
    env.reset(seed=6)
    day2 = O.encode(env.game, env.day_chain)["upgrade_slots"]

    assert (day2 == day1).all(), (
        "a permanent upgrade must still be observable on the following day; "
        f"day1={day1.tolist()} day2={day2.tolist()}"
    )


def test_disks_spent_reflects_permanently_consumed_sources():
    """disks_spent counts the one-time disk sources already used up.

    It tells the agent how much of the finite 16-disk supply remains, which is
    what makes 'spend a disk now' a priceable decision rather than a free action.
    """
    from blueprince_sim.env import obs as O

    plain = BluePrinceEnv(cfg=GameConfig(special_items=True))
    plain.reset(seed=7)
    assert int(O.encode(plain.game)["disks_spent"][0]) == 0, (
        "nothing spent yet, so the count must be zero"
    )

    spent = BluePrinceEnv(cfg=GameConfig(
        special_items=True,
        collected_disks=frozenset({"upgrade_disk_office", "upgrade_disk_tomb"}),
    ))
    spent.reset(seed=7)
    assert int(O.encode(spent.game)["disks_spent"][0]) == 2, (
        "two permanently-spent sources must show as 2"
    )
