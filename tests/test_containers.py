"""Containers: trunks, chests, lockers, and the Garage car trunk."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.actions import (
    OPEN_CONTAINER_ACTION, OPEN_CAR_TRUNK_ACTION,
    action_mask, apply_action, N_ACTIONS,
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

def test_locker_room_has_open_and_locked_kinds():
    """The Locker Room has both locker_open (free) and locker_locked (key cost) kinds.

    This pins the wiki split (3 open, 17 locked out of 20 accessible lockers)
    as a behavioral property: containers_in returns both kinds with nonzero counts.
    """
    st, reg = _state_with_registry()
    kinds = si.containers_in(reg, "locker_room")
    assert kinds.get("locker_open", 0) > 0, "Locker Room must have at least one free locker"
    assert kinds.get("locker_locked", 0) > 0, "Locker Room must have at least one locked locker"


def test_locker_open_kind_requires_no_key():
    """A locker_open container is openable with zero keys and costs nothing to open.

    Uses a single-kind stub room to isolate the free-locker branch.
    """
    st, reg = _state_with_registry()
    reg.special.containers["kinds"]["locker_open_stub"] = {
        "locked": False,
        "opener": [],
        "loot": [{"weight": 1, "grants": [{"kind": "coins", "amount": 1}]}],
    }
    reg.special.containers["rooms"]["entrance_hall"] = {"locker_open_stub": 3}
    _place_room(st, reg, "entrance_hall", 7)
    st.keys = 0

    game = _fake_game(st, reg, seed=3)
    opened = 0
    while si.can_open_container(game, 7):
        si.open_container(game, 7)
        opened += 1
        assert opened <= 4, "loop guard"
    assert opened == 3, "all three free lockers must open with 0 keys"
    assert st.keys == 0, "no keys spent on free lockers"


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
    """Opening a locker_open container requires no key and no smash item."""
    st, reg = _state_with_registry()
    st.keys = 0
    _place_room(st, reg, "locker_room", 5)

    game = _fake_game(st, reg)
    # The first container in order is locker_open (free)
    assert si.can_open_container(game, 5), "locker_open should be openable with 0 keys"
    si.open_container(game, 5)
    assert st.keys == 0, "opening a locker_open must not spend any key"


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
    st.keys = 100
    total = sum(si.containers_in(reg, "locker_room").values())
    _place_room(st, reg, "locker_room", 7)

    game = _fake_game(st, reg, seed=3)
    for _ in range(total):
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
    """Car Keys first use () grants upgrade_disk_garage (unique per source)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig())
    assert si.can_open_car_trunk(game)
    granted = si.open_car_trunk(game)
    assert "upgrade_disk_garage" in granted or st.inventory.get("upgrade_disk_garage", 0) > 0, \
        "first car trunk use must grant upgrade_disk_garage"


def test_garage_car_later_use_regranted_disk_when_not_spent():
    """Trunk opened on an earlier day but disk NOT spent: re-grants upgrade_disk_garage.

    The trunk re-locks nightly, so this re-open still costs Car Keys; what carries
    over is the disk, which returns until the player spends it (inserts at a
    terminal). Without the disk in collected_disks the engine re-grants it.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig()
    game = _fake_game(st, reg, seed=1, cfg=cfg)
    si.configure(st, cfg)
    si.open_car_trunk(game)
    assert st.inventory.get("upgrade_disk_garage", 0) == 1, (
        "trunk opened before but disk not spent -> disk re-granted from open trunk"
    )


def test_garage_car_draws_from_pool_after_disk_spent():
    """Once upgrade_disk_garage is spent, later trunk uses draw from the later_pool.

    With the disk id in collected_disks, the engine treats the disk as permanently
    gone and falls through to the pool-draw path (items + coins).
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig(
        collected_disks=frozenset({"upgrade_disk_garage"}),
    )
    game = _fake_game(st, reg, seed=1, cfg=cfg)
    si.configure(st, cfg)
    granted = si.open_car_trunk(game)
    later_pool = reg.special.containers.get("garage_car", {}).get("later_pool", [])
    later_gold = reg.special.containers.get("garage_car", {}).get("later_gold", 5)
    coins_granted = st.coins >= later_gold
    items_granted = any(iid in later_pool for iid in granted)
    assert coins_granted or items_granted, (
        "after disk spent, later trunk use must grant gold and/or pool items"
    )


def test_garage_car_once_per_day():
    """Car trunk can only be opened once per day; second call is blocked."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig())
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


def test_garage_disk_is_not_marked_collected_by_opening_alone():
    """Opening the trunk without inserting the disk leaves collected_disks empty.

    Only spending a disk at a terminal retires it. Opening the container is not
    itself consumption, so the next day must still be able to offer the disk.
    """
    from blueprince_sim.config import GameConfig
    from blueprince_sim.engine.game import Game
    from blueprince_sim.env.multiday import DayChain
    base = GameConfig(starting_items=frozenset({"car_keys"}))
    chain = DayChain(base, n_days=5)
    game = Game(chain.next_config(), seed=4)
    game.state.special.garage_car_opened = True  # the trunk was opened today
    chain.advance(game.carryover())
    assert "upgrade_disk_garage" not in chain.next_config().collected_disks, (
        "opening the trunk must not retire the disk; only spending it does"
    )


# ------------------------------------------------ trunk datamined table (new tests)

def test_trunk_multi_grant_item_and_gem():
    """A trunk outcome granting an item AND a gem applies both grants.

    The car_keys + 1 gem entry must add the item to inventory and increment gems.
    Uses seed fishing to hit that outcome; falls back to direct injection via a
    single-entry stub table for determinism.
    """
    st, reg = _state_with_registry()
    # Inject a 1-entry table that always gives car_keys + 1 gem
    reg.special.containers["rooms"]["entrance_hall"] = {"trunk": 1}
    reg.special.containers["kinds"]["trunk_test"] = {
        "locked": False,
        "opener": [],
        "loot": [
            {"weight": 1, "grants": [
                {"kind": "item", "id": "car_keys"},
                {"kind": "gems", "amount": 1},
            ]},
        ],
    }
    reg.special.containers["rooms"]["entrance_hall"] = {"trunk_test": 1}
    _place_room(st, reg, "entrance_hall", 5)
    gems_before = st.gems

    game = _fake_game(st, reg, seed=0)
    si.open_container(game, 5)
    assert st.inventory.get("car_keys", 0) >= 1, "car_keys must be in inventory"
    assert st.gems == gems_before + 1, "gem grant must be applied alongside item"


def test_trunk_keycard_outcome_sets_has_keycard():
    """A trunk outcome granting a keycard sets state.has_keycard = True.

    The keycard is PIPELINE_EXCLUDED from normal item grants, so the container
    handler must use the direct has_keycard path (mirroring open_car_trunk).
    """
    st, reg = _state_with_registry()
    reg.special.containers["kinds"]["trunk_kc"] = {
        "locked": False,
        "opener": [],
        "loot": [{"weight": 1, "grants": [{"kind": "keycard"}]}],
    }
    reg.special.containers["rooms"]["entrance_hall"] = {"trunk_kc": 1}
    _place_room(st, reg, "entrance_hall", 5)

    game = _fake_game(st, reg, seed=0)
    assert not st.has_keycard
    si.open_container(game, 5)
    assert st.has_keycard, "keycard grant from trunk must set state.has_keycard"


# ------------------------------------------------ locker_locked: key-only rule

def test_locked_locker_costs_exactly_one_key():
    """Opening a locker_locked spends exactly 1 key."""
    st, reg = _state_with_registry()
    # Use locker_locked directly via a single-kind room stub
    reg.special.containers["rooms"]["entrance_hall"] = {"locker_locked": 1}
    _place_room(st, reg, "entrance_hall", 5)
    st.keys = 3

    game = _fake_game(st, reg, seed=0)
    assert si.can_open_container(game, 5)
    si.open_container(game, 5)
    assert st.keys == 2, "locker_locked must spend exactly 1 key"


def test_locked_locker_refused_with_zero_keys_even_with_all_door_bypasses():
    """A locker_locked is refused with 0 keys even when holding Sledge Hammer,
    Lock Pick Kit, and Master Key.

    Lockers are not doors (wiki: 'cannot be lockpicked or opened by special keys
    or unlock effects'), so only a basic key works.
    """
    st, reg = _state_with_registry()
    reg.special.containers["rooms"]["entrance_hall"] = {"locker_locked": 1}
    _place_room(st, reg, "entrance_hall", 5)
    st.keys = 0

    # Grant all door-bypass tools
    si.grant(st, reg, "sledge_hammer", source="test")
    si.grant(st, reg, "lock_pick_kit", source="test")
    si.grant(st, reg, "master_key", source="test")

    game = _fake_game(st, reg, seed=0)
    assert not si.can_open_container(game, 5), (
        "locker_locked must be refused with 0 keys even with every door-bypass tool"
    )
    result = si.open_container(game, 5)
    assert result is None
    assert st.keys == 0


def test_open_locker_open_costs_nothing():
    """A locker_open container requires no key and no smash item."""
    st, reg = _state_with_registry()
    reg.special.containers["rooms"]["entrance_hall"] = {"locker_open": 1}
    _place_room(st, reg, "entrance_hall", 5)
    st.keys = 0

    game = _fake_game(st, reg, seed=0)
    assert si.can_open_container(game, 5), "locker_open must be free"
    si.open_container(game, 5)
    assert st.keys == 0, "locker_open must not spend a key"


# ------------------------------------------------ trunk special-item share (statistical)

def test_trunk_special_item_share_plausible():
    """Over many seeded trunk rolls, the item-granting outcome share is in a plausible band.

    The datamined table has ~26% item outcomes; the band 0.15-0.40 guards against
    a broken weight list without hard-coding the exact value.
    """
    N = 500

    def _outcome_has_item(result: str | None) -> bool:
        """True when any slash-separated part of result is an item id (not a resource tag)."""
        if not result:
            return False
        for part in result.split("/"):
            if part and not (
                part.startswith("coins:") or part.startswith("keys:")
                or part.startswith("gems:") or part.startswith("dice:")
                or part in ("", "keycard")
            ):
                return True
        return False

    item_count = 0
    for seed in range(N):
        st, reg = _state_with_registry()
        st.keys = 5
        _place_room(st, reg, "attic", 5)
        game = _fake_game(st, reg, seed=seed)
        outcome = si.open_container(game, 5)
        if _outcome_has_item(outcome):
            item_count += 1

    share = item_count / N
    assert 0.15 <= share <= 0.40, (
        f"trunk special-item share {share:.3f} outside expected band 0.15-0.40"
    )


# ------------------------------------------------ container action space: structural

def test_open_container_action_mask_length_matches_n_actions():
    """The action mask produced by action_mask() has exactly N_ACTIONS entries.

    This pins the relationship (mask length == N_ACTIONS) rather than the
    literal value, so it stays valid when the action space grows.
    """
    g = Game(GameConfig(), seed=0)
    mask = action_mask(g)
    assert len(mask) == N_ACTIONS, (
        f"mask length {len(mask)} must equal N_ACTIONS={N_ACTIONS}"
    )
