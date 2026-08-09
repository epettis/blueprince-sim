"""Room 8 grants no modelled resource on entry.

The wiki's completion reward is Trophy 8 plus Allowance Tokens. Trophy 8 is an
inert collectible, and Allowance Tokens feed the allowance system, which this
sim does not model (special_items.json's allowance_token carries
blocked_on "allowance_not_modeled"). So the room has no guaranteed grant.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _make_game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell``, not yet entered.

    Luck is floored so the room's ``additional_max`` extra-item roll never
    fires, isolating the guaranteed grant from the ordinary luck pipeline.
    """
    g = Game(GameConfig(special_items=True), seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_room_8_entry_grants_no_modeled_resource():
    """Room 8 has no guaranteed grant, so entry moves no tracked resource.

    Swept across seeds because the room still rolls a luck-driven extra item in
    ordinary play; the property here is about the guaranteed grant alone."""
    cell = 5
    for seed in range(30):
        g = _make_game_with_room("room_8", cell, seed=seed)
        before = (g.state.gems, g.state.coins, g.state.keys, g.state.dice, g.state.steps)

        g._enter(cell)
        after = (g.state.gems, g.state.coins, g.state.keys, g.state.dice, g.state.steps)
        assert after == before, f"seed {seed}: Room 8 has no modeled reward to grant on entry"
