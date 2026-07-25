"""Pluggable reward functions."""

from __future__ import annotations

from typing import Protocol

from ..engine.game import Game


class RewardFn(Protocol):
    def __call__(self, game: Game, prev_snapshot: dict, terminated: bool) -> float: ...


def snapshot(game: Game) -> dict:
    """Pre-action baseline (deepest rank + resource counts) for delta-based rewards."""
    st = game.state
    return {
        "deepest_rank": game.deepest_rank,
        "steps": st.steps, "gems": st.gems, "keys": st.keys,
        "coins": st.coins, "dice": st.dice,
    }


def sparse(game: Game, prev: dict, terminated: bool) -> float:
    """Win-only signal: 1.0 when the episode ends in the Antechamber, else 0.0."""
    return 1.0 if terminated and game.success() else 0.0


def shaped(game: Game, prev: dict, terminated: bool) -> float:
    """Dense shaping around the sparse win signal.

    0.1 per new deepest rank reached, 0.01 per unit of resource value gained
    (gems/keys/coins/dice at the datamined item values), -0.001 per decision
    as time pressure, plus 1.0 on a winning termination.
    """
    values = game.registry.item_rules["item_values"]
    r = 0.1 * (game.deepest_rank - prev["deepest_rank"])
    d_res = (
        (game.state.gems - prev["gems"]) * values["gem"]
        + (game.state.keys - prev["keys"]) * values["key"]
        + (game.state.coins - prev["coins"]) * values["coin"]
        + (game.state.dice - prev["dice"]) * values["die"]
    )
    r += 0.01 * d_res
    r -= 0.001  # per-decision time pressure
    if terminated and game.success():
        r += 1.0
    return r


REWARDS = {"sparse": sparse, "shaped": shaped}
