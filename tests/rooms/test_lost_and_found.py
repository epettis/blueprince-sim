"""Lost & Found: the Capability.LOST_AND_FOUND registration, and the wiring
through Game.move that fires the steal-and-draw on first entry.

See tests/test_special_items.py for the ladder-based draw-count coverage
(count_transform_raw, the guaranteed-item carve-out) via
lost_and_found_on_enter called directly -- this file covers the
registration itself and the on_enter dispatch that decides whether that
function fires at all.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.effects import Capability, provides_capability
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S


# ------------------------------------------------- Capability registration

def test_lost_and_found_provides_lost_and_found_capability():
    """Lost & Found registers Capability.LOST_AND_FOUND (effects/rooms/
    lost_and_found.py) -- the fact special_items.on_enter's shared
    dispatcher reads instead of comparing room.id directly. A room silently
    losing this registration would leave the steal-and-draw silently
    unfired rather than raising, so this pins the registration itself."""
    assert provides_capability("lost_and_found", Capability.LOST_AND_FOUND)


def test_ordinary_room_does_not_provide_lost_and_found_capability():
    """A room with no Lost & Found role (the Corridor) does not provide
    Capability.LOST_AND_FOUND -- the registry is opt-in, not a default."""
    assert not provides_capability("corridor", Capability.LOST_AND_FOUND)


# ---------------------------------------------------- wiring through Game

def _enter_room_from_entrance(game: Game, room_id: str, cell: int = 7) -> object:
    """Place ``room_id`` just north of the Entrance Hall and walk into it.

    Drives the real ON_ENTER path (Game.move -> Game._enter ->
    special_items.on_enter), the same wiring shape as
    tests/test_capabilities.py's helper of the same name -- this proves the
    dispatcher itself calls lost_and_found_on_enter for a Capability-
    registered room, not just that the function works in isolation.
    """
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, N | S)
    game.move(N)
    assert game.state.pos == cell
    return room


def test_entering_lost_and_found_steals_a_held_item_via_the_real_dispatcher():
    """Walking into the Lost & Found for the first time removes one held
    item, proving special_items.on_enter's Capability.LOST_AND_FOUND gate
    actually calls lost_and_found_on_enter through Game.move -- not just
    that the function works when called directly (see
    tests/test_special_items.py).

    collected_allowance_tokens gates out this room's own guaranteed
    allowance_token_lost_and_found (see special_items.configure), so the
    only held item when the steal fires is the one injected below --
    otherwise the steal's target would be a random pick between the two,
    which would need a pinned seed instead of following from the gate.
    """
    cfg = GameConfig(special_items=True,
                      collected_allowance_tokens=frozenset({"allowance_token_lost_and_found"}))
    game = Game(cfg, seed=0)
    si.grant(game.state, game.registry, "shovel", source="test")
    assert si.has(game.state, "shovel")

    _enter_room_from_entrance(game, "lost_and_found")

    assert not si.has(game.state, "shovel"), (
        "the Lost & Found's steal must fire through the real on_enter dispatch"
    )
