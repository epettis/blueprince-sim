"""Pluggable reward functions."""

from __future__ import annotations

from typing import Protocol

from ..engine.game import Game


class RewardFn(Protocol):
    def __call__(self, game: Game, prev_snapshot: dict, terminated: bool) -> float: ...


def snapshot(game: Game) -> dict:
    st = game.state
    return {
        "deepest_rank": game.deepest_rank,
        "steps": st.steps, "gems": st.gems, "keys": st.keys,
        "coins": st.coins, "dice": st.dice,
    }


def sparse(game: Game, prev: dict, terminated: bool) -> float:
    return 1.0 if terminated and game.success() else 0.0


def shaped(game: Game, prev: dict, terminated: bool) -> float:
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
