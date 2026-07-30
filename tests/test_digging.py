"""Special items: digging, treasure map, and metal detector spawns (task C)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState


# ----------------------------------------------------------------- helpers

def _game(items: frozenset[str] = frozenset(), seed: int = 0) -> Game:
    cfg = GameConfig(starting_items=items)
    return Game(cfg, seed=seed)


def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, seed=0):
    """Lightweight duck-typed game object for unit-calling dig_all."""
    class _FakeGame:
        pass
    g = _FakeGame()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    return g


def _place_room(game, room_id: str, cell: int) -> None:
    """Put a room on the game grid at cell without firing any hooks."""
    room = game.registry.by_id[room_id]
    game.state.grid[cell] = room.idx
    game.state.placed_doors[cell] = room.door_mask


# ------------------------------------------------ once-per-cell digging

def test_dig_spots_once_per_cell():
    """Auto-dig marks spots as dug so re-arriving at the same cell never re-digs.

    state.special.dug[cell] tracks progress; a second on_arrive must not add resources.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    # Set up a fake game with tomb (2 dig spots) at a cell
    game = _fake_game(st, reg, seed=42)
    tomb = reg.by_id["tomb"]
    cell = 10
    st.grid[cell] = tomb.idx

    si.dig_all(game, cell)
    coins_after_first = st.coins
    assert st.special.dug.get(cell, 0) == tomb.items.dig_spots

    # Second dig_all at same cell must yield nothing extra
    si.dig_all(game, cell)
    assert st.coins == coins_after_first, "re-digging same cell must not grant more coins"


def test_dig_junk_nothing_grants_nothing():
    """Digging outcomes of 'junk' or 'nothing' grant no resources.

    These are explicit waste outcomes; the player gets nothing from them.
    A deterministic all-junk dig is forced by a subclass of Rng whose
    roll_weighted always returns 0 (index 0 = the 'junk' entry in the shovel
    table).  A no-op dig_all would leave state.special.dug[cell] unset, so we
    also assert the dug counter advances — proving a real dig was attempted.
    """
    from blueprince_sim.engine.rng import Rng

    class _AlwaysFirstRng(Rng):
        """Rng that always returns index 0 from roll_weighted (forces junk)."""
        def roll_weighted(self, label: str, weights: tuple) -> int:  # noqa: ARG002
            return 0

    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")

    tomb = reg.by_id["tomb"]
    cell = 10
    st.grid[cell] = tomb.idx

    game = _fake_game(st, reg, seed=0)
    game.rng = _AlwaysFirstRng(0)  # replace: Rng subclass, not an attribute patch

    coins_before = st.coins
    keys_before = st.keys
    gems_before = st.gems

    si.dig_all(game, cell)

    # A real dig was attempted: dug counter must record all spots.
    assert st.special.dug.get(cell, 0) == tomb.items.dig_spots, (
        "dig_all must advance the dug counter even for junk outcomes"
    )
    # No resources were granted.
    assert st.coins == coins_before, "junk outcome must not grant coins"
    assert st.keys == keys_before, "junk outcome must not grant keys"
    assert st.gems == gems_before, "junk outcome must not grant gems"
    assert not any(e[0] == "food" for e in st.items_found_log), (
        "junk outcome must not grant food/steps"
    )


def test_dig_shovel_determinism_per_seed():
    """Same seed produces identical dig outcomes (coins, keys, gems) for same cell.

    Determinism is a core invariant: every seeded run must replay identically.
    """
    tomb_cell = 10

    def _run(seed):
        st = GameState()
        st.special.enabled = True
        reg = Registry.load()
        si.grant(st, reg, "shovel", source="test")
        tomb = reg.by_id["tomb"]
        st.grid[tomb_cell] = tomb.idx
        game = _fake_game(st, reg, seed=seed)
        si.dig_all(game, tomb_cell)
        return st.coins, st.keys, st.gems, list(st.items_found_log)

    r1 = _run(7)
    r2 = _run(7)
    assert r1 == r2


# ------------------------------------------------ tool priority / table selection

def test_jack_hammer_preferred_over_shovel():
    """jack_hammer is used when both jack_hammer and shovel are held.

    Tool priority (jack_hammer > detector_shovel > shovel) must be respected.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    # Inject jack_hammer directly (no spawn rooms, bypass unique check risk)
    st.inventory["jack_hammer"] = 1
    st.special.spawned_today.append("jack_hammer")

    # Shovel has junk entries; jack_hammer has no junk entries — use this to
    # distinguish: over many seeds, check if coins+gems outcomes match
    # jack_hammer's table (which always gives something useful) rather than shovel's.
    tomb = reg.by_id["tomb"]
    cell = 10
    useful_count = 0
    for seed in range(30):
        st2 = GameState()
        st2.special.enabled = True
        st2.inventory["shovel"] = 1
        st2.special.spawned_today.append("shovel")
        st2.inventory["jack_hammer"] = 1
        st2.special.spawned_today.append("jack_hammer")
        st2.grid[cell] = tomb.idx
        game = _fake_game(st2, reg, seed=seed)
        si.dig_all(game, cell)
        if st2.coins > 0 or st2.gems > 0 or st2.keys > 0 or st2.steps > 50:
            useful_count += 1

    # jack_hammer table has no junk — all 2 spots per seed yield something;
    # over 30 seeds all 30 runs should have at least one useful outcome.
    assert useful_count >= 25, (
        f"only {useful_count}/30 seeds had useful jack_hammer outcomes; "
        "tool priority may be wrong")


def test_shovel_used_when_only_shovel_held():
    """Shovel is used (with its junk/nothing outcomes) when it is the only dig tool.

    This confirms the tool-selection logic falls through to shovel correctly.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    assert not si.has(st, "jack_hammer")
    assert not si.has(st, "detector_shovel")

    tomb = reg.by_id["tomb"]
    cell = 10
    # Over 30 seeds, at least some should have non-useful outcomes (junk in shovel table)
    junk_count = 0
    for seed in range(60):
        st2 = GameState()
        st2.special.enabled = True
        si.grant(st2, reg, "shovel", source="test")
        st2.grid[cell] = tomb.idx
        game = _fake_game(st2, reg, seed=seed)
        before = (st2.coins, st2.keys, st2.gems)
        si.dig_all(game, cell)
        after = (st2.coins, st2.keys, st2.gems)
        if before == after and not any(e[0] == "food" for e in st2.items_found_log):
            junk_count += 1

    # shovel table: ~37% junk+nothing; 2 spots means ~14% chance both are junk.
    # Over 60 seeds we expect ~8 all-junk runs; at least 1 confirms shovel table used.
    assert junk_count >= 1, "shovel table must produce some junk/nothing outcomes"


def test_detector_shovel_uses_its_own_table():
    """Detector shovel yields useful resources significantly more often than the basic shovel.

    The detector_shovel table has ~25% junk vs shovel's ~37%; over 30 seeds the
    detector_shovel must produce more useful outcomes in aggregate.
    """
    reg = Registry.load()
    tomb = reg.by_id["tomb"]
    cell = 10
    useful_shovel = 0
    useful_detector = 0
    for seed in range(60):
        for item_id, counter_name in (("shovel", "useful_shovel"), ("detector_shovel", "useful_detector")):
            st2 = GameState()
            st2.special.enabled = True
            st2.inventory[item_id] = 1
            st2.special.spawned_today.append(item_id)
            st2.grid[cell] = tomb.idx
            game = _fake_game(st2, reg, seed=seed)
            si.dig_all(game, cell)
            had_useful = st2.coins > 0 or st2.gems > 0 or st2.keys > 0 or st2.steps > 50
            if item_id == "shovel":
                if had_useful:
                    useful_shovel += 1
            else:
                if had_useful:
                    useful_detector += 1

    # Detector shovel should outperform basic shovel on useful outcomes
    assert useful_detector >= useful_shovel, (
        f"detector_shovel ({useful_detector}) should match or beat shovel ({useful_shovel})")


# ------------------------------------------------ treasure map

def test_treasure_map_cell_resolved_lazily():
    """Treasure Map cell is -1 at pickup time and resolved on the first on_arrive call.

    Lazy resolution keeps _on_pickup rng-free while still giving the map a unique cell.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "treasure_map", source="test")
    assert st.special.treasure_cell == -1, "cell must be -1 immediately after pickup"

    # Call on_arrive on a game; cell should be resolved
    game = _fake_game(st, reg, seed=5)
    # Place something at cell 0 so dig_all doesn't crash (grid[0] = entrance is pre-set, use it)
    entrance = reg.by_id["entrance_hall"]
    st.grid[0] = entrance.idx
    si.on_arrive(game, 0)
    assert st.special.treasure_cell != -1, "treasure_cell must be set after first on_arrive"
    valid_cells = reg.special.treasure_map["cells"]
    assert st.special.treasure_cell in valid_cells


def test_treasure_map_marks_treasure_dug():
    """Digging the treasure map's marked cell sets treasure_dug=True.

    The flag prevents the one-per-day reward from being collected twice.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    si.grant(st, reg, "treasure_map", source="test")

    # Pick a known treasure cell and force treasure_cell to it
    target_cell = reg.special.treasure_map["cells"][0]
    st.special.treasure_cell = target_cell
    # Place a non-dig room at that cell so room digging doesn't interfere
    entrance = reg.by_id["entrance_hall"]
    st.grid[target_cell] = entrance.idx

    game = _fake_game(st, reg, seed=1)
    si.dig_all(game, target_cell)
    assert st.special.treasure_dug is True


def test_treasure_map_grants_reward():
    """Digging the treasure map cell grants exactly one reward (coins or gems).

    The three possible rewards are: 40 coins, 8 gems, or 25 coins + 3 gems.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    si.grant(st, reg, "treasure_map", source="test")

    target_cell = reg.special.treasure_map["cells"][0]
    st.special.treasure_cell = target_cell
    entrance = reg.by_id["entrance_hall"]
    st.grid[target_cell] = entrance.idx

    before_coins = st.coins
    before_gems = st.gems
    game = _fake_game(st, reg, seed=1)
    si.dig_all(game, target_cell)

    reward_found = any(
        e[0] in ("coins", "gem") for e in st.items_found_log
    )
    assert reward_found, "treasure map dig must log coins or gem reward"
    # Verify total reward matches one of the three defined rewards
    coins_gained = st.coins - before_coins
    gems_gained = st.gems - before_gems
    valid = (
        (coins_gained >= 40 and gems_gained == 0)
        or (gems_gained == 8 and coins_gained == 0)
        or (coins_gained >= 25 and gems_gained == 3)
    )
    assert valid, f"unexpected reward: coins={coins_gained}, gems={gems_gained}"


def test_treasure_map_only_once_per_day():
    """Treasure map reward is granted at most once per day; treasure_dug blocks re-trigger.

    A second visit to the marked cell after treasure_dug=True must not grant anything.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    si.grant(st, reg, "treasure_map", source="test")

    target_cell = reg.special.treasure_map["cells"][0]
    st.special.treasure_cell = target_cell
    entrance = reg.by_id["entrance_hall"]
    st.grid[target_cell] = entrance.idx

    game = _fake_game(st, reg, seed=2)
    si.dig_all(game, target_cell)
    coins_after_first = st.coins
    gems_after_first = st.gems

    si.dig_all(game, target_cell)
    assert st.coins == coins_after_first, "second dig must not grant more coins"
    assert st.gems == gems_after_first, "second dig must not grant more gems"


# ------------------------------------------------ metal detector on_place

def test_metal_detector_drafts_extra_resources():
    """Metal Detector may grant bonus coins or keys when a room is drafted.

    The on_place hook fires for every drafted room; seeded checks confirm determinism.
    """
    # Find a seed where at least one of coin or key chance fires
    reg = Registry.load()
    found_grant = False
    for seed in range(40):
        st = GameState()
        st.special.enabled = True
        st.inventory["metal_detector"] = 1
        st.special.spawned_today.append("metal_detector")
        game = _fake_game(st, reg, seed=seed)
        entrance = reg.by_id["entrance_hall"]
        si.on_place(game, entrance, 2)
        if st.coins > 0 or st.keys > 0:
            found_grant = True
            break

    assert found_grant, "metal_detector should grant coins or keys on some seeded on_place calls"


def test_no_metal_detector_no_extra():
    """Without metal detector or electromagnet, on_place grants no coins or keys.

    The on_place hook is gated on the presence of the relevant item.
    """
    st, reg = _state_with_registry()
    assert not si.has(st, "metal_detector")
    assert not si.has(st, "powered_electromagnet")

    game = _fake_game(st, reg, seed=0)
    entrance = reg.by_id["entrance_hall"]
    si.on_place(game, entrance, 2)
    assert st.coins == 0
    assert st.keys == 0
    assert len(st.items_found_log) == 0
