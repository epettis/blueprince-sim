"""Tests for the fresh-save config split (Task 1-6):

- west_gate_unlatched only controls the Grounds shortcut, not outer-room drafting.
- outer_draft_available() relies solely on route reachability, not a config flag.
- Arriving at west_path sets west_gate_unlatched; DayChain carries it forward.
- fresh_save_config preset has no unlocks but the scepter on.
- configs/fresh_save.yaml loads and matches fresh_save_config.
"""

from __future__ import annotations

from pathlib import Path


from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.rl.train import fresh_save_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _place_garage_with_breaker(game: Game, garage_cell: int = 1) -> None:
    """Place a Garage variant adjacent to EH and activate the Utility Closet breaker.

    garage_cell=1 (rank 1, far-west column) with an east door connects to EH at cell 2.
    The Utility Closet is placed at cell 7 (rank 2 center) and marked entered.
    """
    from blueprince_sim.engine.grid import E, W, N, S

    garage = game.registry.by_id["garage"]
    uc = game.registry.by_id["utility_closet"]
    game._place_room(garage, garage_cell, E | W)
    game._place_room(uc, 7, N | S)
    # Mark the Utility Closet as entered (breaker on) WITHOUT walking to it,
    # so we don't spend steps or fire side-effects.
    game.state.entered[game._utility_closet_cell()] = True


# ---------------------------------------------------------------------------
# Task 5, test 1 — Garage route works from day 1 on a fresh save
# ---------------------------------------------------------------------------

def test_outer_draft_available_garage_route_fresh_save(registry):
    """On a fresh-save config with a Garage placed and breaker ON, the outer draft
    is available and _outer_route_cost() reaches the doorstep via the Garage.

    west_gate_unlatched=False: the Grounds shortcut is closed. The ONLY path is
    Garage -> west_path (1 step from the garage anchor). This verifies that the
    draft is NOT gated by any config flag — route reachability alone decides.
    """
    cfg = fresh_save_config()
    assert not cfg.west_gate_unlatched
    g = Game(cfg, seed=9, registry=registry)
    g.state.steps = 50  # prevent accidental step-out
    _place_garage_with_breaker(g)

    assert g._breaker_on(), "breaker must be on for the garage route"
    assert g.outer_draft_available(), (
        "outer draft must be available via Garage route on a fresh save"
    )
    cost = g._outer_route_cost()
    assert cost is not None
    assert cost < 50


# ---------------------------------------------------------------------------
# Task 5, test 2 — Breaker OFF: west_path unreachable, draft unavailable
# ---------------------------------------------------------------------------

def test_outer_draft_unavailable_without_breaker(registry):
    """On a fresh-save config with the breaker OFF, west_path is unreachable
    and the outer draft is NOT available.

    west_gate_unlatched=False, and no garage_door_powered flag because the Utility
    Closet is unentered and no power source stands on the grid: neither route to
    west_path is open. outer_draft_available() must return False.
    """
    from blueprince_sim.engine.grid import E, W, N, S

    cfg = fresh_save_config()
    g = Game(cfg, seed=9, registry=registry)

    garage = registry.by_id["garage"]
    uc = registry.by_id["utility_closet"]
    # Place Garage and Utility Closet but do NOT enter the Utility Closet.
    g._place_room(garage, 1, E | W)
    g._place_room(uc, 7, N | S)
    assert not g._breaker_on(), "breaker must be off"
    assert not g._garage_powered(), "the Garage must have no power of its own either"

    assert g.area_route_cost("west_path") is None, (
        "west_path must be unreachable without breaker or gate"
    )
    assert not g.outer_draft_available()


# ---------------------------------------------------------------------------
# Task 5, test 3 — No Garage: outer draft unavailable on fresh save
# ---------------------------------------------------------------------------

def test_outer_draft_unavailable_no_garage():
    """On a fresh-save config with no Garage placed, the outer draft is not available.

    Without a Garage the garage anchor does not exist, and west_gate_unlatched=False
    closes the Grounds shortcut. west_path is completely unreachable.
    """
    cfg = fresh_save_config()
    g = Game(cfg, seed=9)
    g.state.steps = 999

    assert g._garage_cell() < 0, "no garage must be placed"
    assert g.area_route_cost("west_path") is None
    assert not g.outer_draft_available()


# ---------------------------------------------------------------------------
# Task 5, test 4 — west_gate_unlatched=True opens the Grounds route
# ---------------------------------------------------------------------------

def test_west_gate_unlatched_opens_grounds_route():
    """With west_gate_unlatched=True, the doorstep is reachable from the Entrance
    Hall without any Garage placed (the 2-step Grounds shortcut is open).

    This is the fast path on a fully-explored save: grounds -> west_path = 1 step
    from the house anchor's grounds connection.
    """
    cfg = GameConfig(west_gate_unlatched=True, starting_steps=50)
    g = Game(cfg, seed=9)

    assert g._garage_cell() < 0, "no garage placed; must use Grounds route"
    result = g.area_route_cost("west_path")
    assert result is not None, "west_path must be reachable via Grounds when gate unlatched"
    cost, anchor = result
    assert cost >= 1


# ---------------------------------------------------------------------------
# Task 5, test 5 — Arriving at west_path sets the flag; DayChain carries it
# ---------------------------------------------------------------------------

def test_arriving_at_west_path_unlatches_gate_and_daychain_carries_forward(registry):
    """Arriving at west_path for the first time sets west_gate_unlatched on the config;
    DayChain.advance() carries it to the next day's config so the Grounds route is open.

    This pins the full lifecycle: arrive -> flag set -> carryover -> next_config includes it.
    """
    from blueprince_sim.engine import shops

    cfg = fresh_save_config()
    assert not cfg.west_gate_unlatched

    g = Game(cfg, seed=9, registry=registry)
    g.state.steps = 999
    _place_garage_with_breaker(g)

    # Travel to west_path — this should unlatch the gate.
    g.travel_to("west_path")
    assert g.state.west_gate_unlatched, (
        "west_gate_unlatched must be recorded on the STATE after arriving at west_path"
    )
    assert not g.cfg.west_gate_unlatched, (
        "the config must NOT be mutated -- it is shared across every episode of a worker"
    )
    assert g.state.area == "west_path"

    # carryover() must report the flag as True.
    report = shops.carryover(g)
    assert report["west_gate_unlatched"] is True, (
        "carryover() must include west_gate_unlatched=True after arriving at west_path"
    )

    # DayChain should carry the flag into the next day.
    chain = DayChain(cfg)
    chain.advance(report)
    next_cfg = chain.next_config()
    assert next_cfg.west_gate_unlatched, (
        "DayChain must carry west_gate_unlatched forward so the Grounds route is open next day"
    )


# ---------------------------------------------------------------------------
# Task 5, test 6 — configs/fresh_save.yaml loads correctly
# ---------------------------------------------------------------------------

def test_fresh_save_yaml_loads_no_unlocks_scepter_on():
    """configs/fresh_save.yaml loads via GameConfig.from_yaml and produces a config
    with no permanent unlocks, but with the two documented exceptions on.

    The YAML is the --config path for blueprince-sim play/batch; its contents must
    match the documented fresh-save state.
    """
    yaml_path = Path(__file__).resolve().parent.parent / "configs" / "fresh_save.yaml"
    assert yaml_path.exists(), f"configs/fresh_save.yaml not found at {yaml_path}"

    cfg = GameConfig.from_yaml(yaml_path)

    # No permanent unlocks.
    assert cfg.west_gate_unlatched is False
    assert cfg.orchard_unlocked is False
    assert cfg.mine_unlocked is False
    assert not cfg.studio_additions
    assert not cfg.upgrade_disks

    # The two deliberate exceptions. veteran_mode is NOT a permanent unlock --
    # an experienced player triggers it on day 1 (draft the first three rooms out
    # of the Entrance Hall quickly), so it is assumed on rather than earned, and
    # it belongs here beside the scepter rather than in the block above.
    assert cfg.veteran_mode is True
    assert cfg.royal_scepter_found is True

    # Everything else is clean.
    assert cfg.day == 1
    assert cfg.lunch_box_unlocked is False
    assert cfg.cursed_effigy_unlocked is False
    assert cfg.entrance_vase_broken is False
    assert cfg.outer_chip_dug is False
    assert not cfg.lit_targets
    assert not cfg.collected_disks
    assert cfg.chapel_tithes == 0


def test_reaching_the_doorstep_does_not_leak_into_a_later_episode() -> None:
    """Unlatching the gate in one episode must not unlatch it for the next on the same config.

    The trainer builds ONE GameConfig per worker and reuses it for every episode,
    so recording the discovery on the config would make every later "fresh save"
    start with the shortcut already open -- silently ending the fresh-save preset
    after the first episode that reached the doorstep.
    """
    cfg = GameConfig(day=1, west_gate_unlatched=False)

    first = Game(cfg, seed=9)
    _place_garage_with_breaker(first)
    first.travel_to("west_path")
    assert first.state.west_gate_unlatched, "the gate should unlatch within the episode"
    assert "west_gate_unlatched" in first._gate_ctx().flags

    assert not cfg.west_gate_unlatched, "the shared config must not have been mutated"

    # A brand-new episode on the SAME config object, with no Garage at all.
    second = Game(cfg, seed=123)
    assert "west_gate_unlatched" not in second._gate_ctx().flags
    assert second.area_route_cost("west_path") is None, (
        "a later fresh-save episode must not inherit the shortcut"
    )


def test_yaml_preset_and_python_preset_do_not_drift() -> None:
    """configs/fresh_save.yaml and fresh_save_config() must describe the same config.

    They are deliberately two artifacts -- configs/ lives outside the package so the
    trainer cannot load it -- which means nothing but this test stops them drifting
    apart and silently giving the CLI and the trainer different "fresh saves".
    """
    import dataclasses

    from_yaml = GameConfig.from_yaml(
        Path(__file__).resolve().parent.parent / "configs" / "fresh_save.yaml"
    )
    from_python = fresh_save_config()
    mismatched = {
        f.name: (getattr(from_yaml, f.name), getattr(from_python, f.name))
        for f in dataclasses.fields(GameConfig)
        if getattr(from_yaml, f.name) != getattr(from_python, f.name)
    }
    assert not mismatched, f"YAML and Python fresh-save presets disagree: {mismatched}"


def test_training_defaults_to_a_fresh_save():
    """Training starts from a fresh save: both the --unlocks CLI flag and
    make_single_env default to 'none'. Nothing pinned this before, so the
    default was free to drift -- and it matters, because all_unlocks_config
    sets every carry flag on day 1, which opens the whole area graph before a
    room is drafted and makes touring it out-earn playing (open task 24)."""
    import inspect

    from blueprince_sim.rl.train import build_parser, make_single_env

    assert inspect.signature(make_single_env).parameters["unlocks"].default == "none"
    args = build_parser().parse_args([])
    assert args.unlocks == "none"


def test_the_fresh_save_default_hands_over_almost_nothing():
    """The point of the default, stated as the numbers that make it the
    default: a fresh save starts with one carry flag set, where all-unlocks
    starts with all nineteen. DayChain carries earned flags forward, so the
    fixture is only the starting state -- a long chain still reaches the late
    game, but has to play into it."""
    from blueprince_sim.env.multiday import DayChain
    from blueprince_sim.rl.train import all_unlocks_config, fresh_save_config

    def carried(cfg):
        return {k for k in DayChain._CARRYOVER_KEYS if getattr(cfg, k, False)}

    fresh, everything = carried(fresh_save_config()), carried(all_unlocks_config())
    assert len(everything) == len(DayChain._CARRYOVER_KEYS)
    assert len(fresh) == 1, f"fresh save should hand over one flag, got {fresh}"
    assert fresh < everything
