"""Pluggable reward functions."""

from __future__ import annotations

from typing import Protocol

from ..engine.game import Game
from ..engine.grid import rank_of
from ..engine.special_items import inventory_value


class RewardFn(Protocol):
    def __call__(self, game: Game, prev_snapshot: dict, terminated: bool) -> float: ...


def _key_multiplier(rank: int) -> float:
    """How much a held key is worth at a given deepest rank, relative to its
    base value: 1.0 through rank 3 (locks never roll by chance below rank 4),
    then +0.5 per rank, reaching 4.0 at rank 9."""
    return 1.0 + 0.5 * max(0, rank - 3)


def _rank_potential(rank: int) -> float:
    """Cumulative value of reaching a deepest rank: 0.05 per rank through
    rank 4, 0.15 per rank beyond (0.90 total at rank 9), back-loading
    progress so the resource terms dominate the early gathering phase."""
    return 0.05 * min(rank - 1, 3) + 0.15 * max(0, rank - 4)


def _phi_keys(game: Game) -> float:
    """Potential of the key stock: base item value scaled by the depth
    multiplier, so keys appreciate as the run pushes into lock territory."""
    key_value = game.registry.item_rules["item_values"]["key"]
    return 0.01 * game.state.keys * key_value * _key_multiplier(game.deepest_rank)


def _phi_frontier(game: Game) -> float:
    """Potential of forward pathways: passable frontier doorways (open,
    locked with a key in hand, or security-openable) in the deepest two
    ranks, capped at 4 for diminishing returns."""
    edge = game.deepest_rank - 1
    passable = sum(
        1 for cell, d in game.frontier_doorways()
        if rank_of(cell) >= edge and game.doorway_passable(cell, d)
    )
    return 0.02 * min(passable, 4)


def snapshot(game: Game) -> dict:
    """Pre-action baseline (deepest rank, resource counts, shaping potentials)
    for delta-based rewards."""
    st = game.state
    return {
        "deepest_rank": game.deepest_rank,
        "steps": st.steps, "gems": st.gems, "keys": st.keys,
        "coins": st.coins, "dice": st.dice,
        "phi_keys": _phi_keys(game), "phi_frontier": _phi_frontier(game),
        "inv_value": inventory_value(st, game.registry),
    }


def sparse(game: Game, prev: dict, terminated: bool) -> float:
    """Win-only signal: 1.0 when the episode ends in the Antechamber, else 0.0."""
    return 1.0 if terminated and game.success() else 0.0


def shaped(game: Game, prev: dict, terminated: bool) -> float:
    """Dense shaping around the sparse win signal.

    0.1 per new deepest rank reached, 0.01 per unit of resource value gained
    (gems/keys/coins/dice at the datamined item values, held special items at
    their tier values — so buying an item trades coin value for item value
    instead of reading as a pure loss), -0.001 per decision as time pressure,
    plus 1.0 on a winning termination.
    """
    values = game.registry.item_rules["item_values"]
    r = 0.1 * (game.deepest_rank - prev["deepest_rank"])
    d_res = (
        (game.state.gems - prev["gems"]) * values["gem"]
        + (game.state.keys - prev["keys"]) * values["key"]
        + (game.state.coins - prev["coins"]) * values["coin"]
        + (game.state.dice - prev["dice"]) * values["die"]
        + (inventory_value(game.state, game.registry) - prev["inv_value"])
    )
    r += 0.01 * d_res
    r -= 0.001  # per-decision time pressure
    if terminated and game.success():
        r += 1.0
    return r


def phased(game: Game, prev: dict, terminated: bool) -> float:
    """Two-phase shaping: gather resources low, spend keys and keep pathways
    open high.

    Differences from :func:`shaped`:

    - Rank progress is back-loaded (0.05/rank through rank 4, 0.15/rank for
      5-9) so racing upward is not the dominant early signal.
    - Keys are priced as a potential that appreciates with deepest rank
      (:func:`_phi_keys`): carrying keys into lock territory pays off per
      rank, spending them early forgoes the appreciation, and spending them
      late must be justified by the larger rank reward.
    - Passable frontier doorways at the leading edge carry a standing
      potential (:func:`_phi_frontier`), rewarding runs that keep several
      live ways forward instead of tunneling a single corridor.

    Gems/coins/dice/held-item deltas, time pressure, and the win bonus match
    `shaped`.
    """
    values = game.registry.item_rules["item_values"]
    r = _rank_potential(game.deepest_rank) - _rank_potential(prev["deepest_rank"])
    d_res = (
        (game.state.gems - prev["gems"]) * values["gem"]
        + (game.state.coins - prev["coins"]) * values["coin"]
        + (game.state.dice - prev["dice"]) * values["die"]
        + (inventory_value(game.state, game.registry) - prev["inv_value"])
    )
    r += 0.01 * d_res
    r += _phi_keys(game) - prev["phi_keys"]
    r += _phi_frontier(game) - prev["phi_frontier"]
    r -= 0.001  # per-decision time pressure
    if terminated and game.success():
        r += 1.0
    return r


REWARDS = {"sparse": sparse, "shaped": shaped, "phased": phased}
