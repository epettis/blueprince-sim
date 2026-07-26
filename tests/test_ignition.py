"""Ignition system (Torch / Burning Glass) and Broken Lever machine placements."""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.actions import (
    LIGHT_ACTION, INSTALL_LEVER_ACTION, N_ACTIONS,
    action_mask, apply_action,
    _cell_has_ignition_target, _cell_has_machine,
)


# ----------------------------------------------------------------- helpers

def _state_with_registry(cfg: GameConfig | None = None):
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, seed: int = 0, cfg: GameConfig | None = None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    g.cfg = cfg or GameConfig()
    return g


def _place_room(state, registry, room_id: str, cell: int) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


# ====================================================== ignition: basic rules


def test_light_requires_tool_in_hand():
    """can_light returns False when standing in a target room without a torch or burning_glass."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert not si.can_light(game)


def test_light_requires_target_room():
    """can_light returns False when holding a torch but standing in a non-target room."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "entrance_hall", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert not si.can_light(game)


def test_torch_can_light_chapel():
    """can_light returns True when holding a torch and standing in the Chapel."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert si.can_light(game)


def test_burning_glass_interchangeable_with_torch():
    """Burning Glass and Torch are interchangeable ignition tools; either enables can_light."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "burning_glass", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert si.can_light(game), "burning_glass must be accepted as an ignition tool"


def test_target_lights_at_most_once_per_day():
    """A target room can only be lit once per day; can_light returns False after the first use."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.light(game)
    assert not si.can_light(game), "chapel must not be lightable twice in one day"


def test_light_chapel_grants_coins():
    """Lighting the Chapel grants coins (wiki-documented: candles; amount is inferred)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins > before, "lighting the Chapel must grant coins"


# ====================================================== ignition: Tomb gate


def test_tomb_requires_diary_key():
    """can_light at the Tomb returns False when holding a torch but no diary_key."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert not si.can_light(game), "Tomb candles require the Diary Key"


def test_tomb_unlocked_with_diary_key():
    """can_light at the Tomb returns True when holding both a torch and the diary_key."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    si.grant(st, reg, "diary_key", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert si.can_light(game), "Diary Key must unlock Tomb candles"


# ====================================================== ignition: Trading Post


def test_trading_post_fuse_grants_upgrade_disk():
    """Lighting the Trading Post fuse grants an upgrade_disk (wiki-documented reward)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "trading_post", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    before_disk = st.inventory.get("upgrade_disk", 0)
    si.light(game)
    assert st.inventory.get("upgrade_disk", 0) > before_disk, "fuse must grant upgrade_disk"


def test_trading_post_fuse_grants_40_coins():
    """Lighting the Trading Post fuse grants 40 coins (wiki-documented reward)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "trading_post", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins >= before + 40, "Trading Post fuse must grant at least 40 coins"


# ====================================================== broken lever: greenhouse


def test_greenhouse_lever_opens_antechamber_south_segment():
    """Installing the lever in the Greenhouse sets the Antechamber's south doorway to DOOR_OPEN.

    That doorway is the rank-8-centre (cell 37) to Antechamber (cell 42) segment:
    the Antechamber's own south door, since segment_key(42, S) == segment_key(37, N).
    """
    from blueprince_sim.engine.locks import segment_key
    from blueprince_sim.engine.grid import N, S
    from blueprince_sim.engine.game import ANTECHAMBER_CELL

    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)

    # The Antechamber's south door and cell 37's north door are one segment.
    seg = segment_key(37, N)
    assert seg == segment_key(ANTECHAMBER_CELL, S), "lever must target the Antechamber's south door"
    # Force it locked so the unlock is observable rather than incidental.
    g.state.door_state[seg] = DOOR_LOCKED

    # Place the greenhouse at a reachable cell and stand there
    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    assert si.can_install_lever(g)
    si.install_lever(g)
    assert g.state.door_state.get(seg, DOOR_OPEN) == DOOR_OPEN, (
        "Antechamber south segment must be DOOR_OPEN after lever install"
    )


def test_greenhouse_lever_makes_antechamber_passable_without_a_key():
    """After the lever, the Antechamber's south doorway is passable holding zero keys.

    This is the point of the lever: a locked Antechamber normally costs a key to
    enter, so the unlock has to change passability, not just the stored flag.
    """
    from blueprince_sim.engine.locks import segment_key
    from blueprince_sim.engine.grid import N

    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    g.state.door_state[segment_key(37, N)] = DOOR_LOCKED
    g.state.keys = 0

    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    assert not g.doorway_passable(37, N), "locked Antechamber must be impassable with no keys"
    si.install_lever(g)
    assert g.doorway_passable(37, N), "lever must open the Antechamber without spending a key"
    assert g.state.keys == 0, "the lever must not consume a key"


def test_greenhouse_lever_door_version_bumped():
    """Installing the Greenhouse lever bumps door_version, invalidating nav caches."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    greenhouse = g.registry.by_id["greenhouse"]
    cell = 5
    g.state.grid[cell] = greenhouse.idx
    g.state.placed_doors[cell] = greenhouse.door_mask
    g.state.pos = cell

    before = g.state.door_version
    si.install_lever(g)
    assert g.state.door_version > before, "door_version must increase after lever install"


# ====================================================== broken lever: casino


def test_casino_lever_grants_loot():
    """Installing the lever in the Casino grants its configured slot bonus loot."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    _place_room(st, reg, "casino", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    before_coins = st.coins
    before_gems = st.gems
    si.install_lever(game)
    assert st.coins > before_coins or st.gems > before_gems, (
        "Casino lever must grant coins or gems"
    )


# ====================================================== broken lever: consumption


def test_lever_consumed_after_install():
    """The broken_lever is consumed after installation and cannot be installed again."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    _place_room(st, reg, "casino", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.install_lever(game)
    assert st.inventory.get("broken_lever", 0) == 0, "broken_lever must be removed after install"
    assert "broken_lever" in st.special.removed, "broken_lever must be in removed list"


def test_second_install_refused():
    """A second install_lever call is blocked after the first (machine already used)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    si.grant(st, reg, "broken_lever", source="test")  # add a second one (unique=True so only 1)
    _place_room(st, reg, "casino", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.install_lever(game)
    assert not si.can_install_lever(game), "can_install_lever must be False after first use"


def test_lever_requires_broken_lever_item():
    """can_install_lever returns False when standing in a machine room without a broken_lever."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "greenhouse", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert not si.can_install_lever(game)


def test_lever_requires_machine_room():
    """can_install_lever returns False when holding a broken_lever but not in a machine room."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "broken_lever", source="test")
    _place_room(st, reg, "entrance_hall", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert not si.can_install_lever(game)


# ====================================================== determinism


def test_light_deterministic():
    """light() produces the same state change given the same seed (RNG determinism)."""
    def _run(seed: int) -> int:
        st, reg = _state_with_registry()
        si.grant(st, reg, "torch", source="test")
        _place_room(st, reg, "chapel", 5)
        st.pos = 5
        game = _fake_game(st, reg, seed=seed)
        si.light(game)
        return st.coins

    assert _run(42) == _run(42)
    assert _run(99) == _run(99)


# ====================================================== env: action ids and masks


def test_light_action_id():
    """LIGHT_ACTION is 274, directly after the parlor box action."""
    assert LIGHT_ACTION == 274


def test_install_lever_action_id():
    """INSTALL_LEVER_ACTION is 275, directly after the light action."""
    assert INSTALL_LEVER_ACTION == 275


def test_n_actions_is_276():
    """N_ACTIONS is 276 after adding light and install_lever actions."""
    assert N_ACTIONS == 276


def test_light_action_masked_when_available():
    """LIGHT_ACTION is True in the mask when holding a torch in a lightable room."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"torch"}))
    g = Game(cfg, seed=42)
    chapel = g.registry.by_id["chapel"]
    cell = 5
    g.state.grid[cell] = chapel.idx
    g.state.placed_doors[cell] = chapel.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    mask = action_mask(g)
    assert mask[LIGHT_ACTION], "LIGHT_ACTION must be legal when torch held in chapel"


def test_light_action_masked_when_unavailable():
    """LIGHT_ACTION is False when holding a torch but not in a lightable room."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"torch"}))
    g = Game(cfg, seed=42)
    # Default position is entrance_hall, not a target
    mask = action_mask(g)
    assert not mask[LIGHT_ACTION]


def test_install_lever_action_masked_when_available():
    """INSTALL_LEVER_ACTION is True in the mask when holding a broken_lever in a machine room."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    casino = g.registry.by_id["casino"]
    cell = 5
    g.state.grid[cell] = casino.idx
    g.state.placed_doors[cell] = casino.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    mask = action_mask(g)
    assert mask[INSTALL_LEVER_ACTION], "INSTALL_LEVER_ACTION must be legal in casino with broken_lever"


def test_install_lever_action_masked_when_unavailable():
    """INSTALL_LEVER_ACTION is False when no broken_lever is held."""
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=42)
    mask = action_mask(g)
    assert not mask[INSTALL_LEVER_ACTION]


def test_apply_light_action():
    """apply_action(LIGHT_ACTION) calls light() and marks the target as lit."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"torch"}))
    g = Game(cfg, seed=42)
    chapel = g.registry.by_id["chapel"]
    cell = 5
    g.state.grid[cell] = chapel.idx
    g.state.placed_doors[cell] = chapel.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    apply_action(g, LIGHT_ACTION)
    assert "chapel" in g.state.special.lit_targets


def test_apply_install_lever_action():
    """apply_action(INSTALL_LEVER_ACTION) calls install_lever() and consumes the item."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    casino = g.registry.by_id["casino"]
    cell = 5
    g.state.grid[cell] = casino.idx
    g.state.placed_doors[cell] = casino.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    apply_action(g, INSTALL_LEVER_ACTION)
    assert g.state.inventory.get("broken_lever", 0) == 0


def test_cell_has_ignition_target_re_entry():
    """_cell_has_ignition_target returns True for an unlit target cell when a tool is held."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"torch"}))
    g = Game(cfg, seed=42)
    chapel = g.registry.by_id["chapel"]
    cell = 5
    g.state.grid[cell] = chapel.idx
    g.state.placed_doors[cell] = chapel.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell  # current position irrelevant for re-entry check

    assert _cell_has_ignition_target(g, cell)
    # After lighting, re-entry is no longer needed
    si.light(g)
    assert not _cell_has_ignition_target(g, cell)


def test_cell_has_machine_re_entry():
    """_cell_has_machine returns True for an unused machine room when broken_lever held."""
    cfg = GameConfig(special_items=True, starting_items=frozenset({"broken_lever"}))
    g = Game(cfg, seed=42)
    casino = g.registry.by_id["casino"]
    cell = 5
    g.state.grid[cell] = casino.idx
    g.state.placed_doors[cell] = casino.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    assert _cell_has_machine(g, cell)
    si.install_lever(g)
    assert not _cell_has_machine(g, cell)
