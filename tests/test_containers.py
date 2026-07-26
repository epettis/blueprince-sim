"""Containers: trunks, chests, lockers, and the Garage car trunk."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.actions import (
    N_ACTIONS, OPEN_CONTAINER_ACTION, OPEN_CAR_TRUNK_ACTION,
    action_mask, apply_action,
)
from blueprince_sim.env import obs as obs_mod


# ----------------------------------------------------------------- helpers

def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, seed=0, cfg=None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    g.cfg = cfg or GameConfig()
    g._garage_ids = tuple(r.id for r in registry.rooms if r.id.startswith("garage"))
    return g


def _place_room(state, registry, room_id: str, cell: int) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


# ------------------------------------------------ container data

def test_room_container_count_bounds_how_many_can_be_opened():
    """A room yields exactly as many openable containers as its data count, then stops.

    Pins the count to data through behavior rather than reading the table back:
    the Locker Room's lockers are free, so every one of them opens and no more.
    """
    st, reg = _state_with_registry()
    expected = sum(si.containers_in(reg, "locker_room").values())
    _place_room(st, reg, "locker_room", 7)

    game = _fake_game(st, reg, seed=3)
    opened = 0
    while si.can_open_container(game, 7):
        si.open_container(game, 7)
        opened += 1
        assert opened <= expected + 1, "opening must terminate at the room's count"
    assert opened == expected


def test_room_without_containers_is_never_openable():
    """A room absent from the containers table offers nothing to open, even with keys.

    Guards against a missing-room lookup defaulting to a phantom container.
    """
    st, reg = _state_with_registry()
    st.keys = 5
    _place_room(st, reg, "entrance_hall", 5)

    game = _fake_game(st, reg)
    assert si.containers_in(reg, "entrance_hall") == {}
    assert not si.can_open_container(game, 5)
    assert si.open_container(game, 5) is None


# ------------------------------------------------ opening mechanics

def test_open_trunk_with_sledge_hammer_costs_no_key():
    """A Sledge Hammer shatters a trunk's padlock for free, even with keys to spare.

    Keys are stocked deliberately: the smash branch must be preferred over
    spending one, so the count is untouched rather than merely unaffordable.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "sledge_hammer", source="test")
    st.keys = 4
    _place_room(st, reg, "attic", 5)
    st.pos = 5

    game = _fake_game(st, reg)
    assert si.can_open_container(game, 5)
    si.open_container(game, 5)
    assert st.keys == 4, "sledge hammer trunk open must not spend a key"


def test_open_trunk_without_smasher_spends_key():
    """Opening a trunk without a smash item spends exactly 1 key."""
    st, reg = _state_with_registry()
    st.keys = 3
    _place_room(st, reg, "attic", 5)

    game = _fake_game(st, reg)
    assert si.can_open_container(game, 5)
    si.open_container(game, 5)
    assert st.keys == 2, "trunk open without smasher must spend exactly 1 key"


def test_chest_spends_a_key_even_while_holding_a_smasher():
    """A chest is not smashable: a Sledge Hammer still costs a key to open it.

    This is the one rule that separates chests from trunks, per the wiki
    ("shatters padlocks on locked trunks (not chests)"). No shipped room carries
    a chest yet, so the scenario injects one into this test's own registry copy.
    """
    st, reg = _state_with_registry()
    reg.special.containers["rooms"]["entrance_hall"] = {"chest": 1}
    si.grant(st, reg, "sledge_hammer", source="test")
    st.keys = 2
    _place_room(st, reg, "entrance_hall", 5)

    game = _fake_game(st, reg, seed=11)
    assert si.can_open_container(game, 5)
    si.open_container(game, 5)
    assert st.keys == 1, "a chest must spend a key even when a smasher is held"


def test_chest_is_unopenable_with_a_smasher_but_no_key():
    """Holding only a Sledge Hammer cannot open a chest — the key is mandatory."""
    st, reg = _state_with_registry()
    reg.special.containers["rooms"]["entrance_hall"] = {"chest": 1}
    si.grant(st, reg, "sledge_hammer", source="test")
    st.keys = 0
    _place_room(st, reg, "entrance_hall", 5)

    game = _fake_game(st, reg, seed=11)
    assert not si.can_open_container(game, 5)
    assert si.open_container(game, 5) is None


def test_open_locker_is_free():
    """Opening a locker requires no key and no smash item."""
    st, reg = _state_with_registry()
    st.keys = 0
    _place_room(st, reg, "locker_room", 5)

    game = _fake_game(st, reg)
    assert si.can_open_container(game, 5), "locker should be openable with 0 keys"
    si.open_container(game, 5)
    assert st.keys == 0, "opening a locker must not spend any key"


def test_cannot_open_trunk_with_no_key_no_smasher():
    """can_open_container is False when no key and no smash item."""
    st, reg = _state_with_registry()
    st.keys = 0
    _place_room(st, reg, "attic", 5)

    game = _fake_game(st, reg)
    assert not si.can_open_container(game, 5)


def test_open_container_grants_loot():
    """Opening a container grants resources or an item (logged in items_found_log)."""
    st, reg = _state_with_registry()
    st.keys = 5
    _place_room(st, reg, "attic", 5)

    game = _fake_game(st, reg, seed=1)
    result = si.open_container(game, 5)
    assert result is not None
    assert len(st.items_found_log) > 0, "opening a container must log at least one item"


def test_open_container_marks_opened():
    """After opening a container, opened_containers[cell] increments by 1."""
    st, reg = _state_with_registry()
    st.keys = 5
    _place_room(st, reg, "attic", 5)

    game = _fake_game(st, reg, seed=2)
    assert st.special.opened_containers.get(5, 0) == 0
    si.open_container(game, 5)
    assert st.special.opened_containers.get(5, 0) == 1


def test_open_all_containers_then_exhausted():
    """After all containers in a room are opened, can_open_container returns False."""
    st, reg = _state_with_registry()
    st.keys = 10
    # Locker Room has 3 lockers
    _place_room(st, reg, "locker_room", 7)

    game = _fake_game(st, reg, seed=3)
    for _ in range(3):
        assert si.can_open_container(game, 7)
        si.open_container(game, 7)
    assert not si.can_open_container(game, 7), "all lockers opened — none remain"


def test_second_open_at_cell_opens_next_container():
    """Opening a second container at the same cell opens one more, not re-opening the first."""
    st, reg = _state_with_registry()
    st.keys = 10
    _place_room(st, reg, "locker_room", 7)  # 3 lockers

    game = _fake_game(st, reg, seed=4)
    si.open_container(game, 7)
    count_after_first = st.special.opened_containers.get(7, 0)
    si.open_container(game, 7)
    count_after_second = st.special.opened_containers.get(7, 0)
    assert count_after_second == count_after_first + 1


def test_container_determinism_per_seed():
    """Same seed produces the same container loot at the same cell."""
    def _run(seed):
        st, reg = _state_with_registry()
        st.keys = 5
        _place_room(st, reg, "attic", 5)
        game = _fake_game(st, reg, seed=seed)
        result = si.open_container(game, 5)
        return result, st.coins, st.keys, list(st.items_found_log)

    r1 = _run(7)
    r2 = _run(7)
    assert r1 == r2, "same seed must produce identical container loot"


# ------------------------------------------------ garage car trunk

def test_garage_car_first_use_grants_upgrade_disk():
    """Car Keys first use (garage_car_used_before=False) grants the Upgrade Disk."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig(garage_car_used_before=False))
    assert si.can_open_car_trunk(game)
    granted = si.open_car_trunk(game)
    assert "upgrade_disk" in granted or st.inventory.get("upgrade_disk", 0) > 0, \
        "first car trunk use must grant Upgrade Disk"


def test_garage_car_later_use_draws_from_pool():
    """Car Keys later use (garage_car_used_before=True) draws from the later_pool."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig(garage_car_used_before=True)
    game = _fake_game(st, reg, seed=1, cfg=cfg)
    granted = si.open_car_trunk(game)
    later_pool = reg.special.containers.get("garage_car", {}).get("later_pool", [])
    later_gold = reg.special.containers.get("garage_car", {}).get("later_gold", 5)
    # Should grant some coins and/or items from the later pool
    coins_granted = st.coins >= later_gold
    items_granted = any(iid in later_pool for iid in granted)
    assert coins_granted or items_granted, \
        "later car trunk use must grant gold and/or pool items"


def test_garage_car_once_per_day():
    """Car trunk can only be opened once per day; second call is blocked."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig(garage_car_used_before=False))
    si.open_car_trunk(game)
    assert st.special.garage_car_opened is True
    assert not si.can_open_car_trunk(game), "car trunk already opened today"


def test_garage_car_requires_car_keys():
    """can_open_car_trunk is False without Car Keys even when standing in the Garage."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0)
    assert not si.can_open_car_trunk(game), "must hold Car Keys to open car trunk"


# ------------------------------------------------ env: actions

def test_n_actions_grew():
    """N_ACTIONS is now 276, accounting for container, lever, and ignition action ids."""
    assert N_ACTIONS == 276


def test_open_container_action_masked_when_available():
    """OPEN_CONTAINER_ACTION is True in the mask when a container is openable at current cell."""
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell
    mask = action_mask(g)
    assert mask[OPEN_CONTAINER_ACTION], "OPEN_CONTAINER_ACTION must be masked True"


def test_open_container_action_masked_false_without_key():
    """OPEN_CONTAINER_ACTION is False when no key and no smasher for a trunk."""
    g = Game(GameConfig(), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell
    g.state.keys = 0
    mask = action_mask(g)
    assert not mask[OPEN_CONTAINER_ACTION]


def test_open_car_trunk_action_masked():
    """OPEN_CAR_TRUNK_ACTION is True when Car Keys held in the Garage."""
    g = Game(GameConfig(starting_items=frozenset({"car_keys"})), seed=42)
    garage = g.registry.by_id["garage"]
    cell = 5
    g.state.grid[cell] = garage.idx
    g.state.placed_doors[cell] = garage.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell
    mask = action_mask(g)
    assert mask[OPEN_CAR_TRUNK_ACTION]


def test_apply_open_container_action():
    """apply_action with OPEN_CONTAINER_ACTION opens a container and marks it opened."""
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    apply_action(g, OPEN_CONTAINER_ACTION)
    assert g.state.special.opened_containers.get(cell, 0) >= 1


# ------------------------------------------------ env: obs

def test_obs_grid_containers_key_present():
    """The observation dict contains the 'grid_containers' key (9x5 uint8 plane)."""
    g = Game(GameConfig(), seed=1)
    observation = obs_mod.encode(g)
    assert "grid_containers" in observation
    arr = observation["grid_containers"]
    assert arr.shape == (9, 5)


def test_obs_grid_containers_decrements_after_open():
    """grid_containers count at a cell decreases by 1 after opening a container there."""
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    obs_before = obs_mod.encode(g)
    count_before = obs_before["grid_containers"][cell // 5, cell % 5]
    assert count_before >= 1, "attic should have at least 1 container in obs"

    apply_action(g, OPEN_CONTAINER_ACTION)
    obs_after = obs_mod.encode(g)
    count_after = obs_after["grid_containers"][cell // 5, cell % 5]
    assert count_after == count_before - 1


def test_cell_with_openable_container_is_walk_to_legal():
    """A cell entered but still holding openable containers returns True from the helper.

    The re-entry extension must let the agent return to collect containers it skipped.
    """
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 7
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True

    from blueprince_sim.env.actions import _cell_has_openable_container
    assert _cell_has_openable_container(g, cell), \
        "helper must return True for a cell with an openable trunk and smasher held"


def test_garage_disk_is_one_time_across_days():
    """Opening the car trunk marks the Upgrade Disk found for the whole save,
    so later days draw from the ordinary pool instead.

    Without this the chain would re-offer the one-time disk every morning.
    """
    from blueprince_sim.config import GameConfig
    from blueprince_sim.engine.game import Game
    from blueprince_sim.env.multiday import DayChain
    base = GameConfig(starting_items=frozenset({"car_keys"}))
    chain = DayChain(base, n_days=5)
    game = Game(chain.next_config(), seed=4)
    game.state.special.garage_car_opened = True  # the trunk was opened today
    chain.advance(game.carryover())
    assert chain.next_config().garage_car_used_before
