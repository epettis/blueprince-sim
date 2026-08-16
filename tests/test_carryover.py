"""Tests for PR2 task D: Royal Scepter grants, vase smash, West Path chip,
scepter activation + category bias, and the carryover() report.
"""

from __future__ import annotations

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.draft import deal_draft
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N
from blueprince_sim.env.multiday import DayChain


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

# Most green rooms (like most rooms overall) are gem-cost, so the bias needs an
# ordinary Gem Draw to actually be likely to move the needle -- DRAFT_TARGET
# above (rank 2, 0 gems by default) is now a datamined ~0% Gem Draw cell (see
# tests/test_free_gem_draws.py), which is why this collapsed to 0.0000/0.0000
# once draft.py stopped over-delivering gem rooms at low rank. Dealt instead
# at the table's high cell (rank 8, 4+ gems -> 59.26%/93.75%) via
# draft.deal_draft directly, the same way tests/rooms/test_schoolhouse.py's
# analogous bias test was rebuilt -- do not move this back to DRAFT_TARGET.
BIAS_FROM_CELL = 32     # rank 7, col 2 (unplaced; from_room resolves to None)
BIAS_TARGET_CELL = 37   # rank 8, col 2
BIAS_DIRECTION = N
BIAS_GEMS = 5            # the "4+ gems" column
BIAS_DRAFTS_TODAY = 6    # past the first-five-drafts low-gem carve-out

N_SCEPTER_DRAFTS = 200   # 200 seeds * 3 options = 600 samples; 40% bias is detectable


def _green_options(game: Game, seed: int, activate_color: str | None) -> tuple[int, int]:
    """Return (green_count, total_count) across all options dealt in one draft.

    Dealt at BIAS_TARGET_CELL/BIAS_GEMS/BIAS_DRAFTS_TODAY -- see that block's
    comment for why this is not DRAFT_TARGET."""
    game.reset(seed)
    game.state.steps = 999
    game.state.gems = BIAS_GEMS
    game.state.drafts_today = BIAS_DRAFTS_TODAY
    if activate_color is not None:
        # Grant the scepter and activate the color
        si.grant(game.state, game.registry, "royal_scepter", source="test")
        game.state.shops.scepter_color = activate_color
    pending = deal_draft(game.state, game.registry, game.cfg, game.rng, game.placed_ids,
                         BIAS_FROM_CELL, BIAS_DIRECTION, BIAS_TARGET_CELL)
    green = sum(
        1 for opt in pending.options
        if game.registry.rooms[opt.room_idx].category == "green"
    )
    return green, len(pending.options)


def test_scepter_green_bias_raises_green_rate():
    """With the green scepter activated, green rooms appear more often in drafts.

    40% bias chance (inferred from wiki). Over 200 seeds * 3 slots the uplift
    must be visible: require green rate at least 1.5x baseline.

    Sampled at BIAS_TARGET_CELL (rank 8, 4+ gems): most green rooms are
    gem-cost, and DRAFT_TARGET's rank-2/0-gems setup is now a datamined ~0%
    Gem Draw cell, which would starve the bias regardless of whether it still
    works -- that is correct post-fix behaviour, not something to paper over
    with a lower threshold."""
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
    """Drive open_outer_draft to put the player on the doorstep and trigger on_doorstep.

    open_outer_draft walks to the cheapest departure anchor, pays the area-graph
    hops, sets state.area to "west_path", and calls shops.on_doorstep internally.
    """
    game.state.steps = 999  # prevent step exhaustion en route
    game.open_outer_draft()


def test_doorstep_chip_granted_with_outer_chip_dug_flag():
    """With outer_chip_dug=True the microchip is granted upon reaching the doorstep.

    The chip already dug carry-over: on_doorstep grants a microchip immediately.
    """
    g = _game(GameConfig(west_gate_unlatched=True, outer_chip_dug=True))
    chips_before = si.count(g.state, "microchip")
    _reach_doorstep(g)
    assert si.count(g.state, "microchip") == chips_before + 1


def test_doorstep_first_time_dig_with_shovel_sets_chip_dug():
    """First-time dig at the doorstep with a Shovel sets state.shops.chip_dug=True.

    chip_dug is the in-run discovery flag that carryover() reads to set
    outer_chip_dug for the next day.
    """
    g = _game(GameConfig(west_gate_unlatched=True,
                         starting_items=frozenset({"shovel"})))
    _reach_doorstep(g)
    assert g.state.shops.chip_dug is True


def test_doorstep_first_time_dig_grants_microchip():
    """First-time dig at the doorstep also grants a microchip to inventory."""
    g = _game(GameConfig(west_gate_unlatched=True,
                         starting_items=frozenset({"shovel"})))
    chips_before = si.count(g.state, "microchip")
    _reach_doorstep(g)
    assert si.count(g.state, "microchip") == chips_before + 1


def test_doorstep_no_chip_without_dig_tool_or_flag():
    """No microchip is granted at the doorstep without a dig tool or the carry-over flag.

    The chip requires either the discovered flag or a digging tool; neither present
    means the player walks past empty-handed.
    """
    g = _game(GameConfig(west_gate_unlatched=True))  # no shovel, no flag
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
        "west_gate_unlatched",
        "weight_room_wall_broken",
        "greenhouse_wall_broken",
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
    g = _game(GameConfig(west_gate_unlatched=True,
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

    The bool keys must always be present; the non-bool keys are also always
    included.

    planetarium_planets (Telescope-in-Planetarium) joins allowance/stars/
    main_course_bonus as a SAVE-scoped "replace wholesale" key reported
    directly by shops.carryover().
    """
    bool_keys = {
        "lunch_box_unlocked",
        "cursed_effigy_unlocked",
        "entrance_vase_broken",
        "outer_chip_dug",
        "royal_scepter_found",
        "west_gate_unlatched",
        "weight_room_wall_broken",
        "greenhouse_wall_broken",
        "room46_reached",
        "room8_solved",
        "mine_south_visited",
        "sealed_entrance_broken",
        "boiler_room_steam",
        "lab_visited",
        "lab_powered",
        "treasure_trove_blackprint",
        "orchard_unlocked",
        "throne_room_blueprint",
        "satellite_dish_unlocked",
        "conservatory_floorplan_found",
    }
    expected_keys = bool_keys | {
        "starting_items", "banned_rooms", "used_vault_keys",
        "lit_targets", "collected_disks", "chapel_tithes",
        "upgrade_disks", "draft_counts",
        "foundation_cell", "foundation_doors",
        "allowance", "stars", "spiral_words", "main_course_bonus", "planetarium_planets",
        "letters_delivered",
        "collected_allowance_tokens", "mail_cycle", "mail_transit_days",
        "hallway_tomorrow_extra",
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


# ======================================================== CLOCK TOWER

def test_clock_tower_day_end_carries_a_key_per_tomorrow_room_via_daychain():
    """Ending a day with the Clock Tower and two other Tomorrow rooms standing
    carries 3 starting keys (one per Tomorrow room, Clock Tower included) into
    tomorrow's GameConfig, driven end-to-end through DayChain (Game.carryover()
    -> DayChain.advance() -> next_config()), the same shape as the Tomorrow
    Hallway's hallway_tomorrow_extra carry."""
    chain = DayChain(GameConfig(), n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    clock_tower = g1.registry.by_id["clock_tower"]
    sauna = g1.registry.by_id["sauna"]
    freezer = g1.registry.by_id["freezer"]
    g1._place_room(clock_tower, 6, clock_tower.door_mask)
    g1._place_room(sauna, 7, sauna.door_mask)
    g1._place_room(freezer, 8, freezer.door_mask)
    g1.state.steps = 0
    g1._check_termination()

    chain.advance(g1.carryover())
    assert chain.next_config().clock_tower_tomorrow_keys == 3

    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.keys == 3


def test_clock_tower_bonus_lapses_the_day_after_it_is_granted():
    """The key bonus applies only to the immediate next day: a later day
    ending without the Clock Tower standing does not keep inheriting it --
    a one-day pulse, not a permanent unlock."""
    chain = DayChain(GameConfig(), n_days=5)
    g1 = Game(chain.next_config(), seed=1)
    clock_tower = g1.registry.by_id["clock_tower"]
    g1._place_room(clock_tower, 6, clock_tower.door_mask)
    g1.state.steps = 0
    g1._check_termination()
    chain.advance(g1.carryover())            # day 2 gets 1 key
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.keys == 1

    chain.advance(g2.carryover())            # day 2 did not stand up a Clock Tower
    g3 = Game(chain.next_config(), seed=3)
    assert g3.state.keys == 0


def test_clock_tower_carry_resets_on_daychain_attempt_wrap():
    """The carried key count does not survive a DayChain attempt wrap -- a
    fresh attempt starts with no Clock Tower bonus pending. Pins the carry as
    PER-ATTEMPT, the same shape as hallway_tomorrow_extra/sauna_bonus, not
    SAVE-scoped like stars/main_course_bonus."""
    chain = DayChain(GameConfig(), n_days=2)
    chain.advance({"clock_tower_tomorrow_keys": 5})   # day 1 -> day 2
    chain.advance({})                                 # day 2 -> wraps to day 1

    assert chain.next_config().clock_tower_tomorrow_keys == 0


# ======================================================== SHRINE

def test_shrine_blessing_day_count_decays_by_one_each_advance():
    """DayChain replaces shrine_blessing_days/id from carryover, then decays
    the day count by 1 each advance() -- the mail_transit_days shape."""
    chain = DayChain(GameConfig(), n_days=10)
    chain.advance({"shrine_blessing_id": "dancer", "shrine_blessing_days": 3})
    assert chain.next_config().shrine_blessing_id == "dancer"
    assert chain.next_config().shrine_blessing_days == 2

    chain.advance({})  # no new donation reported today; the running value still decays
    assert chain.next_config().shrine_blessing_days == 1

    chain.advance({})
    assert chain.next_config().shrine_blessing_days == 0


def test_shrine_curse_day_count_decays_independently_of_the_blessing():
    """The curse's own day-count decays the same way as the blessing's,
    tracked on its own separate field."""
    chain = DayChain(GameConfig(), n_days=10)
    chain.advance({"shrine_curse_days": 2})
    assert chain.next_config().shrine_curse_days == 1

    chain.advance({})
    assert chain.next_config().shrine_curse_days == 0


def test_shrine_offered_coins_and_monk_room_are_replaced_not_decayed():
    """The two non-day-count fields (parked coins, the reserved Monk-room key)
    are replaced wholesale from each day's carryover, with no mechanical decay."""
    chain = DayChain(GameConfig(), n_days=10)
    chain.advance({"shrine_offered_coins": 17, "shrine_monk_room": 9})
    assert chain.next_config().shrine_offered_coins == 17
    assert chain.next_config().shrine_monk_room == 9

    chain.advance({})  # no new value reported: the running value carries unchanged
    assert chain.next_config().shrine_offered_coins == 17
    assert chain.next_config().shrine_monk_room == 9


def test_shrine_state_is_save_scoped_across_a_daychain_attempt_wrap():
    """Unlike mail_transit_days (reset at the wrap), the shrine_* fields are
    SAVE-scoped: a blessing survives a DayChain attempt wrap (decayed by the
    one day the wrap itself represents), the same carve-out as stars/
    main_course_bonus."""
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"shrine_blessing_id": "gardener", "shrine_blessing_days": 6})
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    assert chain.next_config().shrine_blessing_id == "gardener"
    assert chain.next_config().shrine_blessing_days == 5


#: Every save-scoped carve-out, mapped to the value one day reports and the
#: value that must still be readable on the next config AFTER an attempt wrap.
#: The two differ only for the shrine day-counters, which decay by the one day
#: the wrap itself represents. docs/scoping-and-carryover.md owns the list.
_SAVE_SCOPED: dict[str, tuple[object, object]] = {
    "stars": (4, 4),
    "spiral_words": (7, 7),
    "main_course_bonus": (15, 15),
    "letters_delivered": (3, 3),
    "shrine_blessing_id": ("gardener", "gardener"),
    "shrine_blessing_days": (6, 5),
    "shrine_curse_days": (4, 3),
    "shrine_offered_coins": (17, 17),
    "shrine_monk_room": (9, 9),
    "axed_rooms": (("bookshop",), ("bookshop",)),
    "permanent_rarity": ({"utility_closet": 3}, {"utility_closet": 3}),
    "planetarium_planets": (("mars",), ("mars",)),
    "lab_visited": (True, True),
    "lab_powered": (True, True),
    "basement_doors_open": (["basement_key_well"], frozenset({"basement_key_well"})),
}

#: Attempt-scoped counterparts, one per shape above, with the value the wrap
#: must reset them to. Present so the test cannot pass against a wrap block
#: that stopped clearing anything at all.
_ATTEMPT_SCOPED: dict[str, tuple[object, object]] = {
    "allowance": (30, 0),                       # int, next to stars
    "chapel_tithes": (12, 0),                   # int
    "mail_cycle": ("awaiting", "empty"),        # str, next to shrine_blessing_id
    "mail_transit_days": (5, 0),                # decaying int, next to shrine_*_days
    "boiler_room_steam": (True, False),         # _CARRYOVER_KEYS bool, next to lab_visited
    "lit_targets": (["mine_south"], frozenset()),   # union-merged set
    "draft_counts": ({"bookshop": 2}, {}),      # dict, next to permanent_rarity
    "water_levels": ({"fountain": 3}, {}),      # dict
}


def test_the_save_scoped_carve_out_set_is_exactly_this():
    """The save-scoped carve-outs are exactly the fourteen fields listed in
    docs/scoping-and-carryover.md, and everything beside them still resets.

    Each carve-out already has its own per-field test, but nothing pinned the
    LIST, so a fifteenth field could be left out of the wrap block and no test
    would notice. Both directions are asserted from one real wrap: survivors
    survive, and a representative attempt-scoped field of each shape (int, str,
    decaying int, _CARRYOVER_KEYS bool, set, dict) is cleared -- the second
    half is what stops this passing against a wrap block that no longer runs.

    Adding a save-scoped field is a deliberate edit to _SAVE_SCOPED above,
    which is the point.
    """
    reported = {k: v[0] for k, v in _SAVE_SCOPED.items()}
    reported.update({k: v[0] for k, v in _ATTEMPT_SCOPED.items()})

    chain = DayChain(GameConfig(), n_days=1)
    chain.advance(reported)  # day 1 of 1 -> wraps immediately
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    cfg = chain.next_config()

    survived = {k: getattr(cfg, k) for k in _SAVE_SCOPED}
    assert survived == {k: v[1] for k, v in _SAVE_SCOPED.items()}

    cleared = {k: getattr(cfg, k) for k in _ATTEMPT_SCOPED}
    assert cleared == {k: v[1] for k, v in _ATTEMPT_SCOPED.items()}
