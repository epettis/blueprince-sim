"""Vault Key deposit boxes.

See tests/rooms/test_parlor.py for the Parlor's gem-grant tests.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.actions import (
    OPEN_VAULT_BOX_ACTION, action_mask, apply_action,
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


def _game_with_room(room_id: str, cell: int, seed: int = 0, cfg: GameConfig | None = None) -> Game:
    """Return a real Game with ``room_id`` placed at ``cell``, not yet entered.

    Unlike ``_state_with_registry``/``_fake_game`` above (a duck-typed stand-in
    used for the vault-box helpers), the coin-grant tests below call
    ``Game._enter`` directly -- the real first-entry item-roll pipeline
    (``roll_room_items`` -> ``grant_item``) -- so they need a real Game.
    """
    g = Game(cfg or GameConfig(), seed=seed)
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


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
    """Vault key 304 opens a box that grants upgrade_disk_vault_304 (one per source, unique)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_304", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    granted = si.open_vault_box(game)
    assert "upgrade_disk_vault_304" in granted


def test_vault_box_370_grants_sanctum_key():
    """Vault key 370 opens a box that grants a sanctum_key_vault."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "vault_key_370", source="test")
    _place_room(st, reg, "vault", 4)
    st.pos = 4

    game = _fake_game(st, reg)
    granted = si.open_vault_box(game)
    assert "sanctum_key_vault" in granted


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


# ====================================================== env: actions


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


# ====================================================== exact coin grant (see docs/open_tasks.md)
#
# The Vault's effect_text states "+40 coins", and entering the Vault grants
# exactly 40 coins every time, unconditional on RNG -- not a probabilistic
# 8-40 pile roll.


def test_vault_entry_grants_exactly_40_coins_every_seed():
    """The Vault's guaranteed grant is a literal 40 coins, not an 8-40 pile roll.

    Luck is pinned to the floor so the room's additional_max=1 luck-rolled
    bonus item never fires; that isolates the guaranteed coins_exact grant
    under test from an unrelated (and still probabilistic) extra-item roll.
    Checked across many seeds because the grant must land on exactly 40
    regardless of RNG.
    """
    cell = 5
    for seed in range(1, 31):
        g = _game_with_room("vault", cell, seed=seed)
        g.state.luck = 0
        g._enter(cell)
        assert g.state.coins == 40, f"seed {seed}: expected exactly 40 coins, got {g.state.coins}"


def test_vault_exact_grant_still_pays_coin_purse_interest():
    """A Coin Purse held while entering the Vault still earns interest on the exact grant.

    This is the regression guard for the "obvious but wrong" fix described in
    the task: routing the exact amount through a bare `_grant` effect (bypassing
    grant_item's "coins" dispatch) would silently stop paying Coin Purse
    interest. grant_item's "coins_exact" case must still call
    special_items.on_coins_granted, so 40 coins at 1 bonus per 3 collected pays
    floor(40/3)=13 bonus coins, landing on 53 total.
    """
    cell = 5
    g = _game_with_room("vault", cell)
    g.state.luck = 0  # isolate the guaranteed grant from the luck-rolled extra item
    si.grant(g.state, g.registry, "coin_purse", source="test")

    g._enter(cell)

    assert g.state.coins == 40 + 13, (
        "Coin Purse interest (1 per 3 coins) must still apply to an exact grant"
    )
    assert g.state.special.coin_interest == 40 % 3


def test_vault_single_exact_entry_does_not_trigger_two_plus_items_luck_penalty():
    """A single coins_exact guaranteed entry counts as ONE item found, not per pile.

    roll_room_items increments `found` once per items.guaranteed ENTRY and only
    applies the luck.penalty_two_plus_items penalty when found >= 2. The exact
    40-coin grant must stay one entry (found=1) rather than splitting into
    per-unit entries, which would flip the room into the 2+-items penalty.
    """
    cell = 5
    g = _game_with_room("vault", cell)
    g.state.luck = 0  # pin at floor: no luck-rolled additional item can fire
    luck_before = g.state.luck

    g._enter(cell)

    assert g.state.luck == luck_before, (
        "a lone coins_exact guaranteed entry must not trip the 2+ items luck penalty"
    )
