"""Tests for PR2 task D: Royal Scepter grants, vase smash, West Path chip,
scepter activation + category bias, and the carryover() report.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _place_entrance_hall(game: Game) -> None:
    """Ensure pos is at the Entrance Hall (already the case after reset, but explicit)."""
    from blueprince_sim.engine.game import ENTRANCE_CELL
    game.state.pos = ENTRANCE_CELL


def _give(game: Game, *item_ids: str) -> None:
    """Grant items directly (bypassing effects; for inventory-presence tests)."""
    for iid in item_ids:
        game.state.inventory[iid] = game.state.inventory.get(iid, 0) + 1


# ============================================================ ROYAL SCEPTER
# ------------------------------------------------------------ day-start grant

def test_royal_scepter_granted_at_reset_with_flag():
    """With royal_scepter_found=True the scepter is in inventory immediately after reset.

    The Entrance Hall is pre-entered at reset, so on_day_start fires during
    reset and the scepter arrives before any player action.
    """
    g = _game(GameConfig(royal_scepter_found=True))
    assert si.has(g.state, "royal_scepter")


def test_royal_scepter_absent_without_flag():
    """Without royal_scepter_found the scepter is not in inventory at day start.

    The scepter is gated out of the spawn pool and not granted by on_day_start,
    so a fresh episode must have none.
    """
    g = _game(GameConfig(royal_scepter_found=False))
    assert not si.has(g.state, "royal_scepter")


def test_royal_scepter_gated_from_spawns_without_flag():
    """Without royal_scepter_found the scepter appears in gated_out, blocking spawn.

    configure() should add royal_scepter to the exclusion list when the flag is
    absent, preventing accidental spawn via the standard item pipeline.
    """
    from blueprince_sim.engine.special_items import configure
    from blueprince_sim.engine.state import GameState

    st = GameState()
    st.special.enabled = True
    configure(st, GameConfig(royal_scepter_found=False))
    assert "royal_scepter" in st.special.gated_out


def test_royal_scepter_not_gated_with_flag():
    """With royal_scepter_found the scepter is NOT in gated_out (grant path is open).

    The carry-over grant (on_day_start) requires the item to be available.
    """
    from blueprince_sim.engine.special_items import configure
    from blueprince_sim.engine.state import GameState

    st = GameState()
    st.special.enabled = True
    configure(st, GameConfig(royal_scepter_found=True))
    assert "royal_scepter" not in st.special.gated_out


# ------------------------------------------------------------ activation

def test_activate_scepter_sets_color():
    """activate_scepter sets state.shops.scepter_color to the chosen color.

    The activated color must be exactly the string passed; the bias condition
    is keyed by this string in priority_draws.json.
    """
    g = _game(GameConfig(royal_scepter_found=True))
    assert shops.can_activate_scepter(g)
    shops.activate_scepter(g, "green")
    assert g.state.shops.scepter_color == "green"


def test_activate_scepter_second_call_refused():
    """Activating the scepter a second time raises AssertionError (irrevocable).

    The color choice is locked for the day; can_activate_scepter returns False
    once a color is set, and activate_scepter asserts it.
    """
    g = _game(GameConfig(royal_scepter_found=True))
    shops.activate_scepter(g, "red")
    assert not shops.can_activate_scepter(g)
    with pytest.raises(AssertionError):
        shops.activate_scepter(g, "blue")


def test_activate_scepter_rejects_bad_color():
    """activate_scepter raises AssertionError for any color not in SCEPTER_COLORS.

    Only blueprint/green/red/bedroom/hallway/shop are valid scepter colors.
    """
    g = _game(GameConfig(royal_scepter_found=True))
    with pytest.raises(AssertionError):
        shops.activate_scepter(g, "purple")


def test_activate_scepter_requires_scepter_held():
    """can_activate_scepter returns False when no royal_scepter is in inventory.

    The scepter must actually be held; the flag alone is not enough (the item
    could theoretically have been stolen by the Lost & Found).
    """
    g = _game(GameConfig(royal_scepter_found=True))
    si.remove(g.state, "royal_scepter", consumed=False)
    assert not shops.can_activate_scepter(g)


def test_activate_scepter_all_valid_colors_accepted():
    """Each of the six valid scepter colors is accepted by activate_scepter.

    A fresh game per color ensures a clean can_activate state each time.
    """
    for color in shops.SCEPTER_COLORS:
        g = _game(GameConfig(royal_scepter_found=True))
        shops.activate_scepter(g, color)
        assert g.state.shops.scepter_color == color


# ------------------------------------------------------------ scepter bias (statistical)

# Mirror the furnace_bias test pattern: collect drafts with and without the scepter
# activated for "green", then compare green-room proportions.

DRAFT_FROM = 2   # Entrance Hall (rank 1 center)
DRAFT_DIR = N
DRAFT_TARGET = 7  # rank 2 center

N_SCEPTER_DRAFTS = 200   # 200 seeds * 3 options = 600 samples; 40% bias is detectable


def _green_options(game: Game, seed: int, activate_color: str | None) -> tuple[int, int]:
    """Return (green_count, total_count) across all options dealt in one draft."""
    game.reset(seed)
    game.state.steps = 999
    if activate_color is not None:
        # Grant the scepter and activate the color
        si.grant(game.state, game.registry, "royal_scepter", source="test")
        game.state.shops.scepter_color = activate_color
    pending = game.open_door(DRAFT_FROM, DRAFT_DIR)
    green = sum(
        1 for opt in pending.options
        if game.registry.rooms[opt.room_idx].category == "green"
    )
    return green, len(pending.options)


def test_scepter_green_bias_raises_green_rate():
    """With the green scepter activated, green rooms appear more often in drafts.

    40% bias chance (inferred from wiki). Over 200 seeds * 3 slots the uplift
    must be visible: require green rate at least 1.5x baseline.
    """
    cfg = GameConfig()
    game = Game(cfg, seed=0)

    green_with = green_with_total = 0
    green_without = green_without_total = 0

    for seed in range(N_SCEPTER_DRAFTS):
        gw, tw = _green_options(game, seed, activate_color="green")
        green_with += gw
        green_with_total += tw

        gn, tn = _green_options(game, seed, activate_color=None)
        green_without += gn
        green_without_total += tn

    rate_with = green_with / green_with_total
    rate_without = green_without / green_without_total

    assert rate_with > rate_without * 1.5, (
        f"Scepter green bias too weak: with={rate_with:.4f} without={rate_without:.4f} "
        f"(n={N_SCEPTER_DRAFTS} drafts)"
    )


# ============================================================ VASE SMASH

def test_smash_vase_grants_microchip():
    """Smashing the vase in the Entrance Hall with a Sledge Hammer grants exactly one microchip.

    The chip is the in-run discovery that carries over as entrance_vase_broken.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})))
    _place_entrance_hall(g)
    microchips_before = si.count(g.state, "microchip")
    shops.smash_vase(g)
    assert si.count(g.state, "microchip") == microchips_before + 1


def test_smash_vase_sets_vase_smashed_flag():
    """smash_vase sets state.shops.vase_smashed=True so the vase cannot be smashed twice."""
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})))
    _place_entrance_hall(g)
    shops.smash_vase(g)
    assert g.state.shops.vase_smashed is True


def test_can_smash_vase_false_after_smash():
    """can_smash_vase returns False once vase_smashed=True.

    A second smash_vase() call must raise AssertionError since the vase is gone.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})))
    _place_entrance_hall(g)
    shops.smash_vase(g)
    assert not shops.can_smash_vase(g)
    with pytest.raises(AssertionError):
        shops.smash_vase(g)


def test_can_smash_vase_requires_entrance_hall():
    """can_smash_vase returns False when the player is not in the Entrance Hall.

    The vase is fixed to the west side of the Entrance Hall; smashing elsewhere
    is not possible.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})))
    # Move player to a different cell
    g.state.pos = 0  # a different rank-1 cell (no room placed there)
    assert not shops.can_smash_vase(g)


def test_can_smash_vase_requires_smash_item():
    """can_smash_vase returns False without a smash-capable item in inventory.

    The vase requires something with the smash effect (Sledge Hammer, Morning
    Star, Power Hammer) to break it.
    """
    g = _game()  # no starting items
    _place_entrance_hall(g)
    assert not shops.can_smash_vase(g)


def test_can_smash_vase_false_when_already_broken_by_config():
    """can_smash_vase returns False when entrance_vase_broken=True in config.

    If the vase was broken in a prior run (carry-over flag), it cannot be
    broken again; the chip is granted at day start instead.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"}),
                         entrance_vase_broken=True))
    _place_entrance_hall(g)
    assert not shops.can_smash_vase(g)


def test_morning_star_also_smashes_vase():
    """The Morning Star (armory item) also satisfies the smash requirement.

    All three smash items (sledge_hammer, morning_star, power_hammer) carry the
    smash effect tag and must each allow can_smash_vase.
    """
    g = _game()
    _place_entrance_hall(g)
    _give(g, "morning_star")
    assert shops.can_smash_vase(g)


def test_power_hammer_also_smashes_vase():
    """The Power Hammer (Workshop contraption) satisfies the smash requirement."""
    g = _game()
    _place_entrance_hall(g)
    _give(g, "power_hammer")
    assert shops.can_smash_vase(g)


# ------------------------------------------------------------ vase chip via config

def test_entrance_vase_broken_grants_chip_at_reset():
    """With entrance_vase_broken=True the microchip is in inventory at day start.

    This is the carry-over path: the chip spawns via on_day_start, not smash_vase.
    """
    g = _game(GameConfig(entrance_vase_broken=True))
    assert si.count(g.state, "microchip") >= 1


def test_entrance_vase_broken_disables_can_smash_vase():
    """With the carry-over flag set, can_smash_vase is False even with a smash item.

    The vase was already broken in a prior run; nothing left to smash.
    """
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"}),
                         entrance_vase_broken=True))
    _place_entrance_hall(g)
    assert not shops.can_smash_vase(g)


# ============================================================ WEST PATH CHIP (doorstep)

def _reach_doorstep(game: Game) -> None:
    """Drive open_outer_draft to advance outer_loc to 1 and trigger on_doorstep.

    open_outer_draft moves the player to the Entrance Hall, deducts the offgrid
    cost, sets outer_loc=1, and calls shops.on_doorstep internally.
    """
    game.state.steps = 999  # prevent step exhaustion en route
    game.open_outer_draft()


def test_doorstep_chip_granted_with_outer_chip_dug_flag():
    """With outer_chip_dug=True the microchip is granted upon reaching the doorstep.

    The chip already dug carry-over: on_doorstep grants a microchip immediately.
    """
    g = _game(GameConfig(outer_rooms_unlocked=True, outer_chip_dug=True))
    chips_before = si.count(g.state, "microchip")
    _reach_doorstep(g)
    assert si.count(g.state, "microchip") == chips_before + 1


def test_doorstep_first_time_dig_with_shovel_sets_chip_dug():
    """First-time dig at the doorstep with a Shovel sets state.shops.chip_dug=True.

    chip_dug is the in-run discovery flag that carryover() reads to set
    outer_chip_dug for the next day.
    """
    g = _game(GameConfig(outer_rooms_unlocked=True,
                         starting_items=frozenset({"shovel"})))
    _reach_doorstep(g)
    assert g.state.shops.chip_dug is True


def test_doorstep_first_time_dig_grants_microchip():
    """First-time dig at the doorstep also grants a microchip to inventory."""
    g = _game(GameConfig(outer_rooms_unlocked=True,
                         starting_items=frozenset({"shovel"})))
    chips_before = si.count(g.state, "microchip")
    _reach_doorstep(g)
    assert si.count(g.state, "microchip") == chips_before + 1


def test_doorstep_no_chip_without_dig_tool_or_flag():
    """No microchip is granted at the doorstep without a dig tool or the carry-over flag.

    The chip requires either the discovered flag or a digging tool; neither present
    means the player walks past empty-handed.
    """
    g = _game(GameConfig(outer_rooms_unlocked=True))  # no shovel, no flag
    chips_before = si.count(g.state, "microchip")
    _reach_doorstep(g)
    assert si.count(g.state, "microchip") == chips_before
    assert g.state.shops.chip_dug is False


# ============================================================ CARRYOVER REPORT

def test_carryover_all_false_defaults():
    """carryover() returns all-False bool values on a fresh game with no discoveries.

    The bool keys must always be present and default to False when nothing was
    found or configured.  royal_scepter_found is explicitly False here because
    the default flipped to True (the unlock puzzle is unmodeled, so defaulting
    on is the only way the scepter is exercised; pass False to disable).  The
    gate, not the default, is what this test pins.  The non-bool keys
    (starting_items, banned_rooms) are always present but not False-typed.
    """
    g = _game(GameConfig(royal_scepter_found=False))
    report = shops.carryover(g)
    bool_keys = {
        "lunch_box_unlocked",
        "cursed_effigy_unlocked",
        "entrance_vase_broken",
        "outer_chip_dug",
        "royal_scepter_found",
    }
    assert bool_keys <= set(report.keys())
    assert all(not report[k] for k in bool_keys), f"expected all False, got {report}"


def test_carryover_entrance_vase_broken_from_smash():
    """carryover()['entrance_vase_broken'] is True after smashing the vase in-run."""
    g = _game(GameConfig(starting_items=frozenset({"sledge_hammer"})))
    _place_entrance_hall(g)
    shops.smash_vase(g)
    assert shops.carryover(g)["entrance_vase_broken"] is True


def test_carryover_entrance_vase_broken_from_config():
    """carryover()['entrance_vase_broken'] is True when already set in cfg."""
    g = _game(GameConfig(entrance_vase_broken=True))
    assert shops.carryover(g)["entrance_vase_broken"] is True


def test_carryover_outer_chip_dug_from_in_run_dig():
    """carryover()['outer_chip_dug'] is True after the first-time dig at the doorstep."""
    g = _game(GameConfig(outer_rooms_unlocked=True,
                         starting_items=frozenset({"shovel"})))
    _reach_doorstep(g)
    assert shops.carryover(g)["outer_chip_dug"] is True


def test_carryover_outer_chip_dug_from_config():
    """carryover()['outer_chip_dug'] is True when already set in cfg."""
    g = _game(GameConfig(outer_chip_dug=True))
    assert shops.carryover(g)["outer_chip_dug"] is True


def test_carryover_royal_scepter_found_from_config_only():
    """carryover()['royal_scepter_found'] is True only when the cfg flag is True.

    Finding the scepter in-run requires the unmodeled Treasure Trove / Key of
    Aries puzzle; until that is modeled, the flag propagates only from config.
    """
    g_true = _game(GameConfig(royal_scepter_found=True))
    assert shops.carryover(g_true)["royal_scepter_found"] is True

    g_false = _game(GameConfig(royal_scepter_found=False))
    assert shops.carryover(g_false)["royal_scepter_found"] is False


def test_carryover_lunch_box_from_gift_shop():
    """carryover()['lunch_box_unlocked'] is True after buying the Lunch Box in-run."""
    g = _game()
    # Simulate the gift_unlocks side-effect (same path as buy() triggers)
    g.state.shops.gift_unlocks.append("lunch_box_unlocked")
    assert shops.carryover(g)["lunch_box_unlocked"] is True


def test_carryover_shape_is_complete():
    """carryover() dict always contains all carry-over keys regardless of state.

    The six bool keys must always be present; the non-bool keys
    (starting_items, banned_rooms, used_vault_keys, lit_targets, collected_disks,
    chapel_tithes) are also always included.
    """
    bool_keys = {
        "lunch_box_unlocked",
        "cursed_effigy_unlocked",
        "entrance_vase_broken",
        "outer_chip_dug",
        "royal_scepter_found",
        "garage_car_used_before",
    }
    expected_keys = bool_keys | {
        "starting_items", "banned_rooms", "used_vault_keys",
        "lit_targets", "collected_disks", "chapel_tithes",
        "upgrade_disks", "draft_counts",
    }
    # Test a variety of configs
    for cfg in [
        GameConfig(),
        GameConfig(royal_scepter_found=True),
        GameConfig(entrance_vase_broken=True, outer_chip_dug=True),
        GameConfig(lunch_box_unlocked=True, cursed_effigy_unlocked=True),
    ]:
        g = _game(cfg)
        report = shops.carryover(g)
        assert set(report.keys()) == expected_keys, (
            f"Missing/extra keys for cfg={cfg}: got {set(report.keys())}"
        )
