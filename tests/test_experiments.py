"""Laboratory / Experiments (phase 1): setup/pause/resume core and the eight
pure-resource effects.

Mirrors test_upgrade_env.py's shape (direct Game construction plus the flat
action space) for the setup flow, and calls engine.experiments functions
directly for the effect-math checks, the same "engine function, not full
action loop" style test_special_items.py uses for its own effect pins.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import experiments
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.env import actions as A


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game_at_laboratory(seed: int = 0) -> Game:
    """Fresh game with the player standing in a placed Laboratory (the terminal room)."""
    g = Game(GameConfig(), seed=seed)
    lab = g.registry.by_id["laboratory"]
    g._place_room(lab, 7, lab.rotations[0])
    g.state.pos = 7
    g.state.entered[7] = True
    return g


def _place(game: Game, room_id: str, cell: int) -> None:
    """Place ``room_id`` directly at ``cell`` with its canonical orientation."""
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, room.rotations[0])


# ---------------------------------------------------------------------------
# Setup draw
# ---------------------------------------------------------------------------

def test_setup_draws_three_distinct_triggers_and_effects_from_base_pool_only():
    """start_setup offers exactly 3 distinct triggers and 3 distinct effects,
    all drawn from the base pool -- the packet pool (phase 5+) is never offered."""
    g = _game_at_laboratory()
    g.start_setup()
    ex = g.state.experiment
    assert len(ex.offered_triggers) == 3
    assert len(set(ex.offered_triggers)) == 3
    assert len(ex.offered_effects) == 3
    assert len(set(ex.offered_effects)) == 3
    base_triggers = set(g.registry.experiments.base_trigger_ids)
    base_effects = set(g.registry.experiments.base_effect_ids)
    assert set(ex.offered_triggers) <= base_triggers
    assert set(ex.offered_effects) <= base_effects


def test_same_seed_yields_same_offers():
    """Two games built from the same seed draw identical trigger/effect offers,
    pinning the named-substream determinism the RNG design promises."""
    g1 = _game_at_laboratory(seed=42)
    g2 = _game_at_laboratory(seed=42)
    g1.start_setup()
    g2.start_setup()
    assert g1.state.experiment.offered_triggers == g2.state.experiment.offered_triggers
    assert g1.state.experiment.offered_effects == g2.state.experiment.offered_effects


def test_setup_masked_out_when_not_in_laboratory():
    """START_SETUP_ACTION is illegal (and absent from the mask) away from the Laboratory,
    even standing in another disk-reader room like Security."""
    g = Game(GameConfig(), seed=0)  # starts at the Entrance Hall, not the Laboratory
    assert not g.can_start_setup()
    mask = A.action_mask(g)
    assert mask[A.START_SETUP_ACTION] is False


def test_setup_legal_and_masked_in_at_laboratory():
    """START_SETUP_ACTION is legal and present in the mask while standing in the Laboratory."""
    g = _game_at_laboratory()
    assert g.can_start_setup()
    mask = A.action_mask(g)
    assert mask[A.START_SETUP_ACTION] is True


# ---------------------------------------------------------------------------
# Choosing a trigger + effect
# ---------------------------------------------------------------------------

def test_choosing_trigger_and_effect_starts_experiment_and_returns_to_navigate():
    """Picking one offered trigger and one offered effect configures the experiment
    and returns the phase to NAVIGATE; picking only one leaves EXPERIMENT_PENDING active."""
    g = _game_at_laboratory()
    g.start_setup()
    assert g.phase is Phase.EXPERIMENT_PENDING
    g.choose_experiment_trigger(0)
    assert g.phase is Phase.EXPERIMENT_PENDING, "trigger alone must not finish setup"
    g.choose_experiment_effect(0)
    assert g.phase is Phase.NAVIGATE
    assert g.state.experiment.configured


def test_action_mask_walks_setup_then_trigger_then_effect_choices():
    """The flat action space legalizes setup, then both choice ranges, then neither,
    matching the same mask-driven flow the UPGRADE_PENDING menu already uses."""
    g = _game_at_laboratory()
    A.apply_action(g, A.START_SETUP_ACTION)
    assert g.phase is Phase.EXPERIMENT_PENDING
    mask = A.action_mask(g)
    assert all(mask[A.EXP_TRIGGER_BASE:A.EXP_TRIGGER_BASE + 3])
    assert all(mask[A.EXP_EFFECT_BASE:A.EXP_EFFECT_BASE + 3])
    A.apply_action(g, A.EXP_TRIGGER_BASE)
    mask = A.action_mask(g)
    assert not any(mask[A.EXP_TRIGGER_BASE:A.EXP_TRIGGER_BASE + 3])
    assert all(mask[A.EXP_EFFECT_BASE:A.EXP_EFFECT_BASE + 3])
    A.apply_action(g, A.EXP_EFFECT_BASE)
    assert g.phase is Phase.NAVIGATE


def test_second_setup_attempt_while_configured_does_not_redraw():
    """Only one experiment is active per day: once configured, can_start_setup is False
    and start_setup is a no-op that leaves the offered lists empty rather than redrawing."""
    g = _game_at_laboratory()
    g.start_setup()
    g.choose_experiment_trigger(0)
    g.choose_experiment_effect(0)
    assert g.state.experiment.configured
    assert not g.can_start_setup()
    g.start_setup()  # no-op: still not can_start_setup()
    assert g.phase is Phase.NAVIGATE
    assert g.state.experiment.offered_triggers == ()
    assert g.state.experiment.offered_effects == ()


# ---------------------------------------------------------------------------
# The "immediately" trigger
# ---------------------------------------------------------------------------

def test_immediately_trigger_fires_exactly_once_at_setup():
    """Choosing the 'immediately' trigger applies the chosen effect right away,
    with success_count landing at exactly 1 -- no repeat firing site exists for it."""
    g = _game_at_laboratory()
    g.phase = Phase.EXPERIMENT_PENDING
    g.state.experiment.offered_triggers = ("immediately", "apples", "shops")
    g.state.experiment.offered_effects = ("permanent_allowance", "set_dice", "set_steps")
    g.choose_experiment_trigger(0)
    g.choose_experiment_effect(0)
    assert g.state.experiment.success_count == 1
    assert g.state.allowance == 1


def test_non_immediately_trigger_does_not_fire_at_setup():
    """A trigger other than 'immediately' leaves success_count at 0 right after setup --
    it needs its own (later-phase) firing site."""
    g = _game_at_laboratory()
    g.phase = Phase.EXPERIMENT_PENDING
    g.state.experiment.offered_triggers = ("apples", "shops", "gems_spent")
    g.state.experiment.offered_effects = ("set_steps", "set_dice", "permanent_allowance")
    g.choose_experiment_trigger(0)
    g.choose_experiment_effect(0)
    assert g.state.experiment.success_count == 0


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------

def test_pause_stops_firing_resume_restarts_it():
    """trigger_success is a no-op while paused (no effect, no success_count bump) and
    fires normally again once resumed -- the generic gate every future trigger hook shares."""
    g = _game_at_laboratory()
    g.phase = Phase.EXPERIMENT_PENDING
    g.state.experiment.offered_triggers = ("apples", "shops", "gems_spent")
    g.state.experiment.offered_effects = ("permanent_allowance", "set_dice", "set_steps")
    g.choose_experiment_trigger(0)
    g.choose_experiment_effect(0)
    assert g.state.experiment.success_count == 0

    g.toggle_experiment()
    assert g.state.experiment.paused
    assert experiments.trigger_success(g) is False
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0

    g.toggle_experiment()
    assert not g.state.experiment.paused
    assert experiments.trigger_success(g) is True
    assert g.state.experiment.success_count == 1
    assert g.state.allowance == 1


def test_toggle_masked_out_without_a_configured_experiment():
    """TOGGLE_EXPERIMENT_ACTION requires a configured experiment, not just standing
    at the terminal -- pausing/resuming nothing is not a legal action."""
    g = _game_at_laboratory()
    assert not g.can_toggle_experiment()
    mask = A.action_mask(g)
    assert mask[A.TOGGLE_EXPERIMENT_ACTION] is False


# ---------------------------------------------------------------------------
# Does not survive the day
# ---------------------------------------------------------------------------

def test_experiment_does_not_survive_reset():
    """A configured experiment is cleared by Game.reset() -- 'lasts for the day' (wiki),
    with no carry-over field feeding it back from GameConfig."""
    g = _game_at_laboratory()
    g.start_setup()
    g.choose_experiment_trigger(0)
    g.choose_experiment_effect(0)
    assert g.state.experiment.configured
    g.reset()
    assert not g.state.experiment.configured
    assert g.state.experiment.offered_triggers == ()
    assert g.state.experiment.success_count == 0


# ---------------------------------------------------------------------------
# The eight pure-resource effects
# ---------------------------------------------------------------------------

def test_gain_key_gem_or_die_grants_exactly_one_of_the_three():
    """apply_effect grants exactly one of key/gem/die, leaving the other two untouched."""
    g = _game_at_laboratory()
    before = (g.state.keys, g.state.gems, g.state.dice)
    experiments.apply_effect(g, "gain_key_gem_or_die")
    after = (g.state.keys, g.state.gems, g.state.dice)
    deltas = tuple(a - b for a, b in zip(after, before))
    assert sorted(deltas) == [0, 0, 1]


def test_set_steps_sets_to_forty():
    """apply_effect('set_steps') sets steps to the data-driven magnitude value (40)."""
    g = _game_at_laboratory()
    g.state.steps = 3
    experiments.apply_effect(g, "set_steps")
    assert g.state.steps == 40


def test_set_dice_sets_to_two():
    """apply_effect('set_dice') sets dice to the data-driven magnitude value (2)."""
    g = _game_at_laboratory()
    g.state.dice = 0
    experiments.apply_effect(g, "set_dice")
    assert g.state.dice == 2


def test_steps_for_gold_loses_ten_steps_and_gains_twenty_gold():
    """apply_effect('steps_for_gold') moves exactly -10 steps / +20 coins."""
    g = _game_at_laboratory()
    g.state.steps = 50
    g.state.coins = 0
    experiments.apply_effect(g, "steps_for_gold")
    assert g.state.steps == 40
    assert g.state.coins == 20


def test_keys_per_hallway_pair_counts_the_aquarium_as_a_hallway():
    """gain 1 key per 2 Hallways: an Aquarium plus a real Hallway count as 2, granting 1 key
    -- Room.is_category is used so the Aquarium (which counts as every colour) is not missed."""
    g = _game_at_laboratory()
    _place(g, "aquarium", 12)
    _place(g, "hallway", 13)
    g.state.keys = 0
    experiments.apply_effect(g, "keys_per_hallway_pair")
    assert g.state.keys == 1


def test_gold_per_red_room_counts_the_aquarium_as_red():
    """gain 3 gold per Red Room: an Aquarium plus a real Red Room count as 2, granting 6 gold."""
    g = _game_at_laboratory()
    _place(g, "aquarium", 12)
    _place(g, "lavatory", 13)
    g.state.coins = 0
    experiments.apply_effect(g, "gold_per_red_room")
    assert g.state.coins == 6


def test_permanent_allowance_adds_one():
    """apply_effect('permanent_allowance') adds 1 to the permanent allowance total."""
    g = _game_at_laboratory()
    g.state.allowance = 5
    experiments.apply_effect(g, "permanent_allowance")
    assert g.state.allowance == 6


def test_keys_per_30_steps_floors_the_division():
    """apply_effect('keys_per_30_steps') grants floor(steps / 30) keys -- 65 steps grants 2,
    not 2.17. Reachable only via direct apply_effect: pool='packet' keeps it undrawable."""
    g = _game_at_laboratory()
    g.state.steps = 65
    g.state.keys = 0
    experiments.apply_effect(g, "keys_per_30_steps")
    assert g.state.keys == 2


def test_inert_effect_id_is_a_no_op():
    """apply_effect no-ops for an effect whose record is implemented=false."""
    g = _game_at_laboratory()
    before = (g.state.keys, g.state.gems, g.state.dice, g.state.coins, g.state.allowance)
    experiments.apply_effect(g, "gain_star")  # implemented=false, requires >=3 stars/veteran/packet
    after = (g.state.keys, g.state.gems, g.state.dice, g.state.coins, g.state.allowance)
    assert before == after
