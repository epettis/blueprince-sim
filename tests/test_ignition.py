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
    LIGHT_ACTION, INSTALL_LEVER_ACTION, action_mask, apply_action,
    _cell_has_ignition_target, _cell_has_machine,
)
from blueprince_sim.env.multiday import DayChain


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


def test_light_chapel_grants_accumulated_tithes():
    """Lighting the Chapel grants the Keeper of Tithes accumulated total (coins banked by entry penalty).

    The altar pays out exactly what was banked, not a flat amount.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    # Manually seed some banked tithes (as configure() would inject from cfg.chapel_tithes)
    st.special.chapel_tithes = 7
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins == before + 7, (
        f"Chapel must grant exactly the banked tithes (7); got coins delta {st.coins - before}"
    )


def test_light_chapel_zero_tithes_grants_zero_coins():
    """Lighting the Chapel with no tithes banked grants zero coins (piggy bank is empty)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "chapel", 5)
    st.pos = 5
    st.special.chapel_tithes = 0
    game = _fake_game(st, reg)
    before = st.coins
    si.light(game)
    assert st.coins == before, "empty tithe bank must grant 0 coins"


# ====================================================== ignition: Chapel tithes accumulation


def _game_with_chapel_at_cell(cell: int = 5, starting_coins: int = 5) -> Game:
    """Return a Game with the Chapel placed at *cell* and the player standing there.

    Uses a real Game (not _fake_game) so that tier1.grant has access to game.red_negations
    and the full effect dispatch infrastructure.
    """
    cfg = GameConfig(special_items=True)
    g = Game(cfg, seed=0)
    chapel_room = g.registry.by_id["chapel"]
    g.state.grid[cell] = chapel_room.idx
    g.state.placed_doors[cell] = chapel_room.door_mask
    g.state.pos = cell
    g.state.entered[cell] = True
    g.state.coins = starting_coins
    return g


def test_chapel_entry_penalty_banks_coin_when_player_has_coins():
    """The Chapel -1 coin entry penalty increments chapel_tithes when the player has coins.

    The Keeper of Tithes banks each coin actually taken; a player with coins loses one and
    the tithe counter goes up by one.
    """
    from blueprince_sim.engine.effects.tier1 import grant as tier1_grant

    g = _game_with_chapel_at_cell(starting_coins=5)
    chapel_room = g.registry.by_id["chapel"]

    # Find and fire the -1 coin grant effect directly (as on_enter would)
    for eff in chapel_room.effects:
        if eff.tag == "grant" and eff.param("resource") == "coins" and eff.param("amount", 0) < 0:
            tier1_grant(g, chapel_room, eff, None)
            break

    assert g.state.coins == 4, "player must lose 1 coin"
    assert g.state.special.chapel_tithes == 1, "tithe counter must increment by the coin taken"


def test_chapel_entry_penalty_banks_nothing_when_broke():
    """The Chapel -1 coin penalty banks nothing when the player has zero coins.

    No coins to take means the Keeper of Tithes receives nothing.
    """
    from blueprince_sim.engine.effects.tier1 import grant as tier1_grant

    g = _game_with_chapel_at_cell(starting_coins=0)
    chapel_room = g.registry.by_id["chapel"]

    for eff in chapel_room.effects:
        if eff.tag == "grant" and eff.param("resource") == "coins" and eff.param("amount", 0) < 0:
            tier1_grant(g, chapel_room, eff, None)
            break

    assert g.state.coins == 0, "player with no coins must not go negative"
    assert g.state.special.chapel_tithes == 0, "tithe counter must not increment when player is broke"


def test_chapel_tithes_persist_across_days_via_daychain():
    """Chapel tithes accumulated on day N appear in the GameConfig on day N+1.

    The counter must carry through DayChain so the total grows across multiple
    days of entering the Chapel before the altar is lit.
    """
    chain = DayChain(GameConfig(), n_days=5)
    # Simulate day 1: 3 tithes banked
    chain.advance({"chapel_tithes": 3})
    cfg_day2 = chain.next_config()
    assert cfg_day2.chapel_tithes == 3, (
        "chapel_tithes from day 1 must appear in day 2's config"
    )

    # Simulate day 2: 2 more tithes banked (total 5)
    chain.advance({"chapel_tithes": 5})
    cfg_day3 = chain.next_config()
    assert cfg_day3.chapel_tithes == 5, (
        "chapel_tithes must reflect the latest running total (5 after payout update)"
    )


def test_chapel_tithes_reset_on_chain_wrap():
    """DayChain resets chapel_tithes to 0 when wrapping to a fresh attempt."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"chapel_tithes": 10})
    chain.advance({"chapel_tithes": 10})  # this advance wraps the chain
    assert chain.chapel_tithes == 0, "tithe bank must reset when the attempt wraps"


# ====================================================== ignition: Tomb


def test_tomb_can_be_lit_without_diary_key():
    """can_light at the Tomb returns True when holding a torch (Diary Key is not required).

    Wiki-verified: the Diary Key is a REWARD of lighting the Tomb, not a prerequisite.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    assert si.can_light(game), "Tomb must be lightable with only a torch (no diary_key required)"


def test_lighting_tomb_grants_diary_key():
    """Lighting the Tomb grants the diary_key as a reward (wiki-documented)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.light(game)
    assert st.inventory.get("diary_key", 0) > 0, "lighting the Tomb must grant diary_key"


def test_lighting_tomb_grants_upgrade_disk_tomb():
    """Lighting the Tomb grants the upgrade_disk_tomb (near candles, wiki-documented)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.light(game)
    assert st.inventory.get("upgrade_disk_tomb", 0) > 0, (
        "lighting the Tomb must grant upgrade_disk_tomb"
    )


def test_lighting_tomb_grants_four_dice():
    """Lighting the Tomb grants 4 dice (near candles, wiki-documented)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "tomb", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.light(game)
    # Dice are granted through the items module (die roll items)
    dice_entries = sum(amt for kind, amt in st.items_found_log if kind == "die")
    assert dice_entries >= 4, f"lighting the Tomb must grant 4 dice; found_log dice: {dice_entries}"


# ====================================================== ignition: Trading Post


def test_trading_post_fuse_grants_upgrade_disk_trading_post():
    """Lighting the Trading Post fuse grants upgrade_disk_trading_post (wiki-documented reward)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "torch", source="test")
    _place_room(st, reg, "trading_post", 5)
    st.pos = 5
    game = _fake_game(st, reg)
    si.light(game)
    assert st.inventory.get("upgrade_disk_trading_post", 0) > 0, (
        "Trading Post fuse must grant upgrade_disk_trading_post"
    )


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


# ====================================================== ignition: permanence across days


def test_lit_target_blocks_can_light_on_next_day():
    """A target lit on day N cannot be lit on day N+1 (ignition persists across days).

    Lighting is permanent: configure() injects cfg.lit_targets into state.special.lit_targets
    so can_light returns False even though state starts fresh.
    """
    # Day 1: light the chapel
    st1, reg = _state_with_registry()
    si.grant(st1, reg, "torch", source="test")
    _place_room(st1, reg, "chapel", 5)
    st1.pos = 5
    game1 = _fake_game(st1, reg)
    si.light(game1)
    assert "chapel" in st1.special.lit_targets

    # Simulate carryover: chapel is now in lit_targets
    cfg_day2 = GameConfig(lit_targets=frozenset({"chapel"}), special_items=True,
                          starting_items=frozenset({"torch"}))

    # Day 2: fresh state, torch in starting_items, chapel in lit_targets from config
    g2 = Game(cfg_day2, seed=0)
    chapel_room = g2.registry.by_id["chapel"]
    cell = 5
    g2.state.grid[cell] = chapel_room.idx
    g2.state.placed_doors[cell] = chapel_room.door_mask
    g2.state.pos = cell
    # configure() is called lazily on on_enter; trigger it manually
    si.configure(g2.state, cfg_day2)

    assert not si.can_light(g2), (
        "Chapel already lit on a prior day must not be lightable again"
    )


def test_lit_targets_persist_via_daychain():
    """lit_targets accumulate in DayChain and appear in the next day's GameConfig.

    A target lit on day N must appear in cfg.lit_targets on day N+1, blocking re-ignition.
    """
    chain = DayChain(GameConfig(), n_days=5)
    chain.advance({"lit_targets": ["chapel"]})
    cfg_day2 = chain.next_config()
    assert "chapel" in cfg_day2.lit_targets, (
        "chapel lit on day 1 must appear in day 2 cfg.lit_targets"
    )
    # After another day with no new lit targets the value should persist
    chain.advance({"lit_targets": ["chapel"]})
    cfg_day3 = chain.next_config()
    assert "chapel" in cfg_day3.lit_targets, "lit_targets must persist across multiple days"


def test_lit_targets_reset_on_chain_wrap():
    """DayChain resets lit_targets to frozenset() when wrapping to a fresh attempt."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"lit_targets": ["chapel", "tomb"]})
    chain.advance({"lit_targets": ["chapel", "tomb"]})  # wraps
    assert chain.lit_targets == frozenset(), "lit_targets must be empty after attempt wrap"


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
        st.special.chapel_tithes = 5
        game = _fake_game(st, reg, seed=seed)
        si.light(game)
        return st.coins

    assert _run(42) == _run(42)
    assert _run(99) == _run(99)


# ====================================================== env: action ids and masks


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
