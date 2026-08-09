"""Aquarium upgrade variants: exact coin grant, unmodelled star bonus, and the Power Source flag.

Each of the three variants only ever repeats the base Aquarium's "AQUARIUM is
every color of room" text plus one addition of its own. Every test below
checks a variant against the base Aquarium in the same run, so a future edit
cannot let the two silently converge back to identical behaviour.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game


def _game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell`` and luck floored, not yet entered.

    Luck is floored so ``additional_max``'s luck-rolled bonus item never
    fires, isolating each assertion from an unrelated probabilistic roll.
    """
    g = Game(GameConfig(), seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_goldfish_aquarium_grants_exactly_10_coins_every_seed():
    """goldfish_aquarium__ix2's "+10" is a literal coin figure, not a 1-5 pile roll.

    Swept across seeds because coding "+10 coins" as a pile count (rather
    than coins_exact) would pay a mean of 30, and it stays a distribution
    under RNG unless the literal-amount item kind is used. The base Aquarium
    is entered in the same loop and asserted to grant no coins, so the two
    records cannot silently converge.
    """
    cell = 5
    for seed in range(1, 31):
        base = _game_with_room("aquarium", cell, seed=seed)
        base._enter(cell)
        assert base.state.coins == 0, f"seed {seed}: base Aquarium should grant no coins"

        goldfish = _game_with_room("goldfish_aquarium__ix2", cell, seed=seed)
        goldfish._enter(cell)
        assert goldfish.state.coins == 10, (
            f"seed {seed}: expected exactly 10 coins, got {goldfish.state.coins}")


def test_starfish_aquarium_star_bonus_is_unmodelled():
    """starfish_aquarium__ix3's "+1" star resource is out of scope for the engine.

    engine/effects/tier1.py's _grant treats stars (and other currencies
    outside steps/gems/keys/coins/dice/luck) as unmodelled and no-ops on
    them, by design - not a bug to fix here. This pins that the Starfish
    Aquarium therefore grants exactly what the base Aquarium grants
    (nothing), so a future change is forced to touch this test if stars
    ever become a modelled resource.
    """
    cell = 5
    for seed in range(1, 31):
        base = _game_with_room("aquarium", cell, seed=seed)
        base._enter(cell)
        starfish = _game_with_room("starfish_aquarium__ix3", cell, seed=seed)
        starfish._enter(cell)
        assert starfish.state.coins == base.state.coins == 0
        assert starfish.state.gems == base.state.gems
        assert starfish.state.keys == base.state.keys
        assert starfish.state.steps == base.state.steps


def test_electric_eel_aquarium_is_powered_and_the_others_are_not():
    """electric_eel_aquarium__ix4's "Power Source" text sets flags.powered, mirroring the Boiler Room.

    The Boiler Room expresses "Power Source" purely as a data flag
    (flags.powered = true, no effects entry), and this variant is sourced
    from the raw sheet's own "Yes" powered column the same way. The base
    Aquarium and the other two variants are asserted unpowered in the same
    test so the flag cannot silently spread to the wrong record.
    """
    registry = Game(GameConfig(), seed=0).registry
    assert registry.by_id["aquarium"].powered is False
    assert registry.by_id["goldfish_aquarium__ix2"].powered is False
    assert registry.by_id["starfish_aquarium__ix3"].powered is False
    assert registry.by_id["electric_eel_aquarium__ix4"].powered is True
