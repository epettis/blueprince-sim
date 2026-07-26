"""Tests for the multi-day loop: DayChain semantics and BluePrinceEnv integration.

All tests pin observable behavior (day index, carryover dict contents, config flags)
rather than DayChain internals.
"""

from __future__ import annotations

import numpy as np

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain


# ------------------------------------------------------------------ helpers

def _chain(n_days: int = 200, **cfg_kwargs) -> DayChain:
    """Return a DayChain with a minimal base config."""
    return DayChain(GameConfig(**cfg_kwargs), n_days=n_days)


def _env_with_chain(n_days: int = 3, starting_steps: int = 3,
                    **cfg_kwargs) -> BluePrinceEnv:
    """Return a BluePrinceEnv wired to a DayChain with fast-terminating episodes."""
    base = GameConfig(starting_steps=starting_steps, **cfg_kwargs)
    chain = DayChain(base, n_days=n_days)
    return BluePrinceEnv(cfg=base, day_chain=chain)


def _run_to_done(env: BluePrinceEnv, seed: int = 0):
    """Step an episode to completion; returns the terminal info dict."""
    obs, info = env.reset(seed=seed)
    done = False
    last_info = info
    rng = np.random.default_rng(seed)
    while not done:
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        action = int(rng.choice(legal))
        obs, reward, terminated, truncated, info = env.step(action)
        last_info = info
        done = terminated or truncated
    return last_info


# ================================================================= DayChain unit tests

def test_daychain_starts_at_day_one():
    """DayChain.current_day is 1 before any advance() call."""
    chain = _chain()
    assert chain.current_day == 1


def test_daychain_next_config_uses_current_day():
    """next_config().day matches current_day; advancing increments day."""
    chain = _chain(n_days=5)
    assert chain.next_config().day == 1
    chain.advance({})
    assert chain.next_config().day == 2
    chain.advance({})
    assert chain.next_config().day == 3


def test_daychain_wraps_after_n_days():
    """After n_days advances, current_day wraps to 1 and carried_flags are cleared."""
    chain = _chain(n_days=3)
    chain.advance({"lunch_box_unlocked": True})
    chain.advance({})
    # After day 3's advance, current_day was 3; now advancing past n_days wraps.
    chain.advance({})
    assert chain.current_day == 1
    assert chain.carried_flags == {}


def test_daychain_wrap_produces_day1_config():
    """Config yielded after a full-cycle wrap has day=1 with no carry-over flags."""
    chain = _chain(n_days=2)
    chain.advance({"lunch_box_unlocked": True})
    # Day 2's advance wraps.
    chain.advance({"outer_chip_dug": True})
    # Now at day 1, fresh slate.
    cfg = chain.next_config()
    assert cfg.day == 1
    assert not cfg.lunch_box_unlocked
    assert not cfg.outer_chip_dug


def test_daychain_advance_merges_true_flags_only():
    """advance() only persists flags whose value is True; False flags are ignored."""
    chain = _chain()
    chain.advance({"lunch_box_unlocked": True, "outer_chip_dug": False})
    assert chain.carried_flags.get("lunch_box_unlocked") is True
    assert "outer_chip_dug" not in chain.carried_flags


def test_daychain_advance_accumulates_across_days():
    """Flags discovered on different days all persist until the cycle resets."""
    chain = _chain(n_days=10)
    chain.advance({"lunch_box_unlocked": True})
    chain.advance({"entrance_vase_broken": True})
    assert chain.carried_flags.get("lunch_box_unlocked") is True
    assert chain.carried_flags.get("entrance_vase_broken") is True


def test_daychain_true_flag_discovery_reaches_next_config():
    """A True flag from advance() appears in next_config() on the following day."""
    chain = _chain(n_days=10)
    assert not chain.next_config().lunch_box_unlocked  # day 1: not yet found
    chain.advance({"lunch_box_unlocked": True})
    assert chain.next_config().lunch_box_unlocked      # day 2: discovered yesterday


def test_daychain_false_flag_does_not_override_carried():
    """A False entry in advance() does not un-discover a previously True flag."""
    chain = _chain(n_days=10)
    chain.advance({"lunch_box_unlocked": True})
    chain.advance({"lunch_box_unlocked": False})       # should be ignored
    assert chain.next_config().lunch_box_unlocked


def test_daychain_sequence_day1_to_n():
    """Successive next_config().day calls yield 1, 2, … n_days (monotone before wrap)."""
    n = 5
    chain = _chain(n_days=n)
    days = []
    for _ in range(n):
        days.append(chain.next_config().day)
        chain.advance({})
    assert days == list(range(1, n + 1))


# ================================================================= env integration

def test_env_without_chain_is_unchanged():
    """BluePrinceEnv without a day_chain behaves exactly as before: no day/carryover in info."""
    env = BluePrinceEnv(cfg=GameConfig(starting_steps=3))
    obs, info = env.reset(seed=0)
    assert "day" not in info
    assert "carryover" not in info


def test_env_without_chain_same_day_after_two_resets():
    """Without a chain, two reset() calls yield the same cfg.day (no accidental coupling)."""
    env = BluePrinceEnv(cfg=GameConfig(day=42, starting_steps=3))
    env.reset(seed=0)
    day_a = env.game.state.day
    env.reset(seed=1)
    day_b = env.game.state.day
    assert day_a == day_b == 42


def test_env_with_chain_info_contains_day():
    """With a day_chain, reset() returns info['day'] equal to the chain's current day."""
    env = _env_with_chain(n_days=5)
    _, info = env.reset(seed=0)
    assert "day" in info
    assert info["day"] == 1


def test_env_with_chain_info_contains_carryover():
    """With a day_chain, info always includes a 'carryover' key (dict, possibly empty)."""
    env = _env_with_chain(n_days=5)
    _, info = env.reset(seed=0)
    assert "carryover" in info
    assert isinstance(info["carryover"], dict)


def test_env_with_chain_day_advances_across_episodes():
    """After running episode 1 to termination, reset() starts episode 2 at day 2."""
    env = _env_with_chain(n_days=5, royal_scepter_found=False)
    _run_to_done(env, seed=0)         # episode 1 complete; advance() fires
    _, info2 = env.reset(seed=1)
    assert info2["day"] == 2


def test_env_with_chain_day_in_terminal_info():
    """The terminal step's info dict carries the day of the episode that just ended."""
    env = _env_with_chain(n_days=5, royal_scepter_found=False)
    env.reset(seed=0)
    terminal_info = _run_to_done(env, seed=0)
    assert terminal_info.get("day") == 1


def test_env_carryover_snapshot_stable_after_advance():
    """info['carryover'] at terminal step reflects flags active at EPISODE START,
    not the updated flags after advance().

    This ensures observers reading the terminal info see the day's starting
    conditions, not the next day's.
    """
    env = _env_with_chain(n_days=5, royal_scepter_found=False)
    # Day 1: no carry-over flags yet
    env.reset(seed=0)
    terminal_info = _run_to_done(env, seed=0)
    # Even after advance() ran, the carryover snapshot in the terminal info
    # must show the STARTING state of day 1 (empty dict).
    assert terminal_info["carryover"] == {}


def test_env_game_registry_reused_across_days():
    """The Game object built each day reuses the same Registry instance (no re-parse)."""
    env = _env_with_chain(n_days=3, royal_scepter_found=False)
    env.reset(seed=0)
    registry_id = id(env.game.registry)
    _run_to_done(env, seed=0)
    env.reset(seed=1)
    assert id(env.game.registry) == registry_id


# ================================================================= scepter default

def test_scepter_held_at_reset_under_new_default():
    """With royal_scepter_found=True (the new default), the scepter is in inventory at reset.

    The unlock puzzle is unmodeled, so the default is True to exercise the scepter;
    pass False to disable.
    """
    g = Game(GameConfig(), seed=0)
    assert si.has(g.state, "royal_scepter")


def test_scepter_absent_when_flag_false():
    """With royal_scepter_found=False the scepter is NOT in inventory at day start.

    The flag gates the day-start grant; False means the unlock was never triggered.
    """
    g = Game(GameConfig(royal_scepter_found=False), seed=0)
    assert not si.has(g.state, "royal_scepter")
