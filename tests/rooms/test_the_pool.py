"""The Pool: injects its 3 temp rooms into the draft decks.
"""

from blueprince_sim.engine.game import Game


def test_the_pool_injects_rooms(registry, cfg):
    """Placing The Pool injects its 3 temp rooms (Locker Room, Sauna, Pump
    Room) into the draft decks."""
    g = Game(cfg, seed=2)
    pool_room = registry.by_id["the_pool"]
    sizes0 = [d.size() for d in g.state.decks]
    g._place_room(pool_room, 7, 4)
    sizes1 = [d.size() for d in g.state.decks]
    assert sum(sizes1) == sum(sizes0) + 3  # locker room, sauna, pump room
