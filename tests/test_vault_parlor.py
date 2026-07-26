"""Vault Key deposit boxes and Parlor Wind-up Key box systems."""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.actions import (
    OPEN_VAULT_BOX_ACTION, OPEN_PARLOR_BOX_ACTION, action_mask, apply_action,
)
from blueprince_sim.env.multiday import DayChain


# ----------------------------------------------------------------- helpers

def _state_with_registry(cfg: GameConfig | None = None):
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    if cfg is not None:
        si.configure(st, cfg, reg)
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


# ====================================================== vault deposit boxes


def test_vault_box_opens_with_matching_key():
    """can_open_vault_box returns a key id only when standing in the Vault holding that key.

    The Vault is the only room where the action is legal; the key must be in inventory.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    assert si.can_open_vault_box(game) == "vault_key_149"


def test_vault_box_blocked_outside_vault():
    """can_open_vault_box returns None when holding a vault key but not standing in the Vault."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "entrance_hall", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    assert si.can_open_vault_box(game) is None


def test_vault_box_blocked_without_key():
    """can_open_vault_box returns None when standing in the Vault but holding no vault key."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    assert si.can_open_vault_box(game) is None


def test_vault_box_149_grants_allowance_token():
    """Vault key 149 opens a box that grants an allowance_token."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    granted = si.open_vault_box(game)
    assert "allowance_token" in granted


def test_vault_box_304_grants_upgrade_disk():
    """Vault key 304 opens a box that grants an upgrade_disk."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_304", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    granted = si.open_vault_box(game)
    assert "upgrade_disk" in granted


def test_vault_box_370_grants_sanctum_key():
    """Vault key 370 opens a box that grants a sanctum_key."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_370", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    granted = si.open_vault_box(game)
    assert "sanctum_key" in granted


def test_vault_key_stays_in_inventory_after_use():
    """Opening a vault box does not remove the key from inventory — it is permanently kept."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    si.open_vault_box(game)
    assert st.inventory.get("vault_key_149", 0) > 0, "vault key must remain in inventory after use"


def test_vault_key_added_to_removed_after_use():
    """After opening a vault box the key id is in state.special.removed, blocking re-spawn this run."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    si.open_vault_box(game)
    assert "vault_key_149" in st.special.removed


def test_vault_box_opens_at_most_once_per_key():
    """A vault deposit box can only be opened once; the second call is blocked."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    si.open_vault_box(game)
    assert si.can_open_vault_box(game) is None, "same box cannot be opened again today"


def test_vault_box_blocked_when_key_in_used_vault_keys():
    """can_open_vault_box returns None for a key listed in cfg.used_vault_keys (permanently used)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_233", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    cfg = GameConfig(used_vault_keys=frozenset({"vault_key_233"}))
    game = _fake_game(st, reg, cfg=cfg)
    assert si.can_open_vault_box(game) is None, "key in used_vault_keys is permanently blocked"


def test_vault_box_key_priority_order():
    """When holding multiple vault keys, 149 is tried first, then 233, 304, 370."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_304", source="test")
    si.grant(st, reg, "vault_key_149", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    assert si.can_open_vault_box(game) == "vault_key_149"


def test_vault_box_vault_boxes_opened_tracks_key():
    """After opening, the key id is recorded in state.special.vault_boxes_opened."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_370", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    si.open_vault_box(game)
    assert "vault_key_370" in st.special.vault_boxes_opened


# ====================================================== DayChain carryover


def test_used_vault_keys_carries_across_days():
    """used_vault_keys accumulates across days via DayChain.advance(); never resets mid-attempt."""
    cfg = GameConfig()
    chain = DayChain(cfg)
    assert chain.used_vault_keys == frozenset()

    chain.advance({"used_vault_keys": ["vault_key_149"]})
    assert "vault_key_149" in chain.used_vault_keys

    chain.advance({"used_vault_keys": ["vault_key_233"]})
    assert "vault_key_149" in chain.used_vault_keys
    assert "vault_key_233" in chain.used_vault_keys


def test_used_vault_keys_injected_into_config():
    """DayChain.next_config() passes used_vault_keys into GameConfig.used_vault_keys."""
    cfg = GameConfig()
    chain = DayChain(cfg)
    chain.advance({"used_vault_keys": ["vault_key_304"]})

    day_cfg = chain.next_config()
    assert "vault_key_304" in day_cfg.used_vault_keys


def test_used_vault_keys_resets_on_attempt_wrap():
    """used_vault_keys is cleared when the DayChain wraps to a new attempt."""
    cfg = GameConfig()
    chain = DayChain(cfg, n_days=2)
    chain.advance({"used_vault_keys": ["vault_key_149"]})
    assert "vault_key_149" in chain.used_vault_keys

    chain.advance({})  # day 2 -> wrap
    assert chain.current_day == 1
    assert chain.used_vault_keys == frozenset()


# ====================================================== parlor wind-up key


def test_parlor_grants_wind_up_key_on_entry():
    """Entering a Parlor room grants 1 wind_up_key to the player."""
    st, reg = _state_with_registry()
    cell = 5
    _place_room(st, reg, "parlor", cell)
    st.pos = cell
    room = reg.by_id["parlor"]

    game = _fake_game(st, reg)
    si.on_enter(game, room, cell)
    assert st.inventory.get("wind_up_key", 0) >= 1


def test_can_open_parlor_box_with_wind_up_key():
    """can_open_parlor_box is True when standing in Parlor holding a wind_up_key."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    _place_room(st, reg, "parlor", 5)
    st.pos = 5

    game = _fake_game(st, reg)
    assert si.can_open_parlor_box(game)


def test_cannot_open_parlor_box_without_wind_up_key():
    """can_open_parlor_box is False when standing in Parlor without a wind_up_key."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "parlor", 5)
    st.pos = 5

    game = _fake_game(st, reg)
    assert not si.can_open_parlor_box(game)


def test_cannot_open_parlor_box_outside_parlor():
    """can_open_parlor_box is False when holding a wind_up_key but not standing in a Parlor."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    _place_room(st, reg, "entrance_hall", 5)
    st.pos = 5

    game = _fake_game(st, reg)
    assert not si.can_open_parlor_box(game)


def test_opening_parlor_box_consumes_wind_up_key():
    """Opening a Parlor box removes exactly 1 wind_up_key from inventory."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    si.grant(st, reg, "wind_up_key", source="test")
    _place_room(st, reg, "parlor", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=1)
    before = st.inventory.get("wind_up_key", 0)
    si.open_parlor_box(game)
    after = st.inventory.get("wind_up_key", 0)
    assert after == before - 1


def test_parlor_box_cap_is_one_per_cell_for_base_parlor():
    """The base Parlor has a cap of 1 box per cell; the second open attempt is blocked."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    si.grant(st, reg, "wind_up_key", source="test")
    _place_room(st, reg, "parlor", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=2)
    si.open_parlor_box(game)
    assert not si.can_open_parlor_box(game), "base Parlor cap is 1 box per cell"


def test_parlor_box_open_returns_loot_string():
    """open_parlor_box returns a non-None loot descriptor when successful."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    _place_room(st, reg, "parlor", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=3)
    result = si.open_parlor_box(game)
    assert result is not None, "open_parlor_box must return a loot string on success"


def test_parlor_box_loot_is_deterministic():
    """open_parlor_box produces the same result given the same seed (RNG substream determinism)."""
    def _run(seed):
        st, reg = _state_with_registry()
        si.grant(st, reg, "wind_up_key", source="test")
        _place_room(st, reg, "parlor", 5)
        st.pos = 5
        game = _fake_game(st, reg, seed=seed)
        return si.open_parlor_box(game)

    assert _run(42) == _run(42)
    assert _run(99) == _run(99)


def test_parlor_box_parlor_boxes_opened_increments():
    """After opening a Parlor box, parlor_boxes_opened[cell] is incremented by 1."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "wind_up_key", source="test")
    cell = 5
    _place_room(st, reg, "parlor", cell)
    st.pos = cell

    game = _fake_game(st, reg, seed=4)
    si.open_parlor_box(game)
    assert st.special.parlor_boxes_opened.get(cell, 0) == 1


# ====================================================== env: actions


def test_open_vault_box_action_id():
    """OPEN_VAULT_BOX_ACTION is 272, one past the two existing container actions."""
    assert OPEN_VAULT_BOX_ACTION == 272


def test_open_parlor_box_action_id():
    """OPEN_PARLOR_BOX_ACTION is 273, adjacent to the vault box action."""
    assert OPEN_PARLOR_BOX_ACTION == 273


def test_vault_box_action_masked_when_available():
    """OPEN_VAULT_BOX_ACTION is True in the mask when a vault box can be opened at current cell."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig(starting_items=frozenset({"vault_key_149"}))
    g = Game(cfg, seed=42)
    vault = g.registry.by_id["vault"]
    cell = 5
    g.state.grid[cell] = vault.idx
    g.state.placed_doors[cell] = vault.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    mask = action_mask(g)
    assert mask[OPEN_VAULT_BOX_ACTION], "vault box action must be legal in the Vault with matching key"


def test_vault_box_action_masked_when_unavailable():
    """OPEN_VAULT_BOX_ACTION is False when holding a vault key but not in the Vault."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig(starting_items=frozenset({"vault_key_149"}))
    g = Game(cfg, seed=42)
    # Don't place a Vault; player starts at entrance_hall by default.
    mask = action_mask(g)
    assert not mask[OPEN_VAULT_BOX_ACTION]


def test_parlor_box_action_masked_when_available():
    """OPEN_PARLOR_BOX_ACTION is True in the mask when standing in Parlor with a wind_up_key."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig(starting_items=frozenset({"wind_up_key"}))
    g = Game(cfg, seed=42)
    parlor = g.registry.by_id["parlor"]
    cell = 5
    g.state.grid[cell] = parlor.idx
    g.state.placed_doors[cell] = parlor.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    mask = action_mask(g)
    assert mask[OPEN_PARLOR_BOX_ACTION]


def test_parlor_box_action_masked_when_unavailable():
    """OPEN_PARLOR_BOX_ACTION is False when holding no wind_up_key."""
    from blueprince_sim.engine.game import Game

    g = Game(GameConfig(), seed=42)
    mask = action_mask(g)
    assert not mask[OPEN_PARLOR_BOX_ACTION]


def test_apply_vault_box_action():
    """apply_action(OPEN_VAULT_BOX_ACTION) calls open_vault_box and grants the box contents."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig(starting_items=frozenset({"vault_key_233"}))
    g = Game(cfg, seed=42)
    vault = g.registry.by_id["vault"]
    cell = 5
    g.state.grid[cell] = vault.idx
    g.state.placed_doors[cell] = vault.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    apply_action(g, OPEN_VAULT_BOX_ACTION)
    assert "vault_key_233" in g.state.special.vault_boxes_opened


def test_apply_parlor_box_action():
    """apply_action(OPEN_PARLOR_BOX_ACTION) calls open_parlor_box and decrements wind_up_key count."""
    from blueprince_sim.engine.game import Game

    cfg = GameConfig(starting_items=frozenset({"wind_up_key"}))
    g = Game(cfg, seed=42)
    parlor = g.registry.by_id["parlor"]
    cell = 5
    g.state.grid[cell] = parlor.idx
    g.state.placed_doors[cell] = parlor.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell

    before = g.state.inventory.get("wind_up_key", 0)
    apply_action(g, OPEN_PARLOR_BOX_ACTION)
    assert g.state.inventory.get("wind_up_key", 0) == before - 1
