"""Laboratory / Experiments: setup/pause/resume core, the pure-resource
effects, the five placement-site draft triggers (shops, red_room_draft,
hallway_from_hallway, bedrooms_after_second, gems_spent), the generic cap
machinery, the trunks_opened and security_door interaction-site triggers, the
day_gate availability filter, and the scoped termination checks added at
open_door/open_container/_maybe_finish_experiment_setup.

Mirrors test_upgrade_env.py's shape (direct Game construction plus the flat
action space) for the setup flow, and calls engine.experiments functions
directly for the effect-math checks, the same "engine function, not full
action loop" style test_special_items.py uses for its own effect pins. The
draft-trigger tests mostly drive Game._place_room directly (like the
existing _place helper), reaching for the real open_door/choose pipeline
only where the threading between them matters (gem cost, Stopwatch, Study,
security-door state).
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import experiments
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY, segment_key
from blueprince_sim.engine.state import DraftOption, PendingDraft
from blueprince_sim.env import actions as A


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game_at_laboratory(seed: int = 0, cfg: GameConfig | None = None) -> Game:
    """Fresh game with the player standing in a placed Laboratory (the terminal room)."""
    g = Game(cfg or GameConfig(), seed=seed)
    lab = g.registry.by_id["laboratory"]
    g._place_room(lab, 7, lab.rotations[0])
    g.state.pos = 7
    g.state.entered[7] = True
    return g


def _place(game: Game, room_id: str, cell: int) -> None:
    """Place ``room_id`` directly at ``cell`` with its canonical orientation."""
    room = game.registry.by_id[room_id]
    game._place_room(room, cell, room.rotations[0])


def _configure(game: Game, trigger_id: str, effect_id: str) -> None:
    """Configure today's experiment directly, bypassing the terminal's offer/choice flow."""
    game.state.experiment.trigger_id = trigger_id
    game.state.experiment.effect_id = effect_id


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
    experiments.apply_effect(g, "add_aquariums")  # implemented=false
    after = (g.state.keys, g.state.gems, g.state.dice, g.state.coins, g.state.allowance)
    assert before == after


def test_gain_star_effect_adds_one_star():
    """apply_effect('gain_star') adds 1 to the permanent star total."""
    g = _game_at_laboratory()
    g.state.stars = 2
    experiments.apply_effect(g, "gain_star")
    assert g.state.stars == 3


# ---------------------------------------------------------------------------
# Placement-site triggers: shops, red_room_draft, hallway_from_hallway,
# bedrooms_after_second, gems_spent
# ---------------------------------------------------------------------------

def test_shops_trigger_fires_on_a_shop_room_not_on_a_hallway():
    """shops fires for a Shop-category room (Bookshop) and not for a Hallway."""
    g = _game_at_laboratory()
    _configure(g, "shops", "permanent_allowance")
    _place(g, "hallway", 10)
    assert g.state.experiment.success_count == 0
    _place(g, "bookshop", 11)
    assert g.state.experiment.success_count == 1
    assert g.state.allowance == 1


def test_red_room_draft_trigger_fires_on_a_red_room_not_on_a_hallway():
    """red_room_draft fires for a Red-category room (Lavatory) and not for a Hallway."""
    g = _game_at_laboratory()
    _configure(g, "red_room_draft", "permanent_allowance")
    _place(g, "hallway", 10)
    assert g.state.experiment.success_count == 0
    _place(g, "lavatory", 11)
    assert g.state.experiment.success_count == 1


def test_red_room_draft_step_loss_lands_before_the_chosen_effect_and_floors_at_zero():
    """red_room_draft's own 5-step loss (floored at 0) applies on top of whatever
    effect is configured -- here with only 3 steps in hand, it floors instead of
    going negative, and the chosen effect (unrelated to steps) still applies."""
    g = _game_at_laboratory()
    _configure(g, "red_room_draft", "permanent_allowance")
    g.state.steps = 3
    _place(g, "lavatory", 10)
    assert g.state.steps == 0
    assert g.state.allowance == 1


def test_red_room_draft_step_loss_is_suppressed_while_paused():
    """Both the trigger's own step loss and its chosen effect are no-ops while
    the experiment is paused -- trigger_success's active gate covers the whole
    red_room_draft branch, not just apply_effect."""
    g = _game_at_laboratory()
    _configure(g, "red_room_draft", "permanent_allowance")
    g.state.experiment.paused = True
    g.state.steps = 50
    _place(g, "lavatory", 10)
    assert g.state.steps == 50
    assert g.state.allowance == 0
    assert g.state.experiment.success_count == 0


def test_weight_room_ordering_sets_steps_to_forty_then_halves_to_twenty():
    """Wiki: 'If this effect is triggered by drafting the Weight Room, steps
    are first set to 40, then halved to 20.' The experiment's set_steps effect
    (fired from the new call site, before ON_PLACE) must resolve before the
    Weight Room's own ON_PLACE step-halving."""
    g = _game_at_laboratory()
    _configure(g, "red_room_draft", "set_steps")
    g.state.steps = 3
    _place(g, "weight_room", 10)
    assert g.state.steps == 20


def test_hallway_from_hallway_fires_only_when_drafted_from_a_hallway():
    """hallway_from_hallway fires when the new Hallway's entry doorway faces
    another Hallway, and not when it faces a non-Hallway room."""
    g = _game_at_laboratory()
    hallway = g.registry.by_id["hallway"]
    office = g.registry.by_id["office"]
    _configure(g, "hallway_from_hallway", "permanent_allowance")

    g._place_room(office, 10, office.rotations[0])
    g._place_room(hallway, 11, hallway.rotations[0], entry_dir=W)  # from cell 10 (Office)
    assert g.state.experiment.success_count == 0

    g._place_room(hallway, 12, hallway.rotations[0], entry_dir=W)  # from cell 11 (Hallway)
    assert g.state.experiment.success_count == 1


def test_counting_effect_sees_the_room_that_triggered_it():
    """Wiki: 'if there are three Hallways in the estate and the experiment is
    triggered by drafting a fourth, then two keys will be gained' -- the
    counting effect must see all four Hallways, including the one that just
    triggered it, because the fire site runs after the grid write."""
    g = _game_at_laboratory()
    hallway = g.registry.by_id["hallway"]
    for cell in (10, 11, 12):
        g._place_room(hallway, cell, hallway.rotations[0])
    _configure(g, "hallway_from_hallway", "keys_per_hallway_pair")
    g.state.keys = 0
    g._place_room(hallway, 13, hallway.rotations[0], entry_dir=W)  # from cell 12 (Hallway)
    assert g.state.keys == 2


def test_bunk_room_worked_example_counter_one_to_three_fires_once():
    """Wiki worked example: with the counter already at 1 Bedroom, drafting a
    Bunk Room (counts as 2) takes it to 3, crossing the 'after your second'
    line exactly once, not twice."""
    g = _game_at_laboratory()
    bedroom = g.registry.by_id["bedroom"]
    g._place_room(bedroom, 10, bedroom.rotations[0])  # counter -> 1, unconfigured
    _configure(g, "bedrooms_after_second", "permanent_allowance")
    bunk_room = g.registry.by_id["bunk_room"]
    g._place_room(bunk_room, 11, bunk_room.rotations[0])
    assert g.state.experiment.bedroom_draft_count == 3
    assert g.state.experiment.success_count == 1


def test_bedrooms_after_second_counts_bedrooms_drafted_before_the_experiment():
    """All of today's Bedrooms count toward the two-Bedroom threshold, whether
    drafted before or after the experiment started -- two Bedrooms drafted
    while unconfigured still make the next one the third."""
    g = _game_at_laboratory()
    bedroom = g.registry.by_id["bedroom"]
    for cell in (10, 11):
        g._place_room(bedroom, cell, bedroom.rotations[0])  # counter -> 2, unconfigured
    _configure(g, "bedrooms_after_second", "permanent_allowance")
    g._place_room(bedroom, 12, bedroom.rotations[0])  # the 3rd Bedroom overall
    assert g.state.experiment.success_count == 1


def test_gems_spent_fires_at_two_or_more_gems_not_below():
    """gems_spent fires for a >=2 gem_cost draft and not for a 1-gem draft --
    driven by the gem_cost value Game._place_room receives, not the room id."""
    g = _game_at_laboratory()
    _configure(g, "gems_spent", "permanent_allowance")
    office = g.registry.by_id["office"]
    g._place_room(office, 10, office.rotations[0], gem_cost=1)
    assert g.state.experiment.success_count == 0
    g._place_room(office, 11, office.rotations[0], gem_cost=2)
    assert g.state.experiment.success_count == 1


def test_hovel_disables_gems_spent_even_at_a_high_gem_cost():
    """With the Hovel placed, gems_spent never fires, since gem costs are paid
    in steps rather than gems ('this trigger becomes useless with it on the
    estate' -- wiki)."""
    g = _game_at_laboratory()
    _configure(g, "gems_spent", "permanent_allowance")
    g.hovel_placed = True
    office = g.registry.by_id["office"]
    g._place_room(office, 10, office.rotations[0], gem_cost=5)
    assert g.state.experiment.success_count == 0


def test_gems_spent_fires_through_the_real_choose_pipeline():
    """The open_door -> choose pipeline threads the actual gem cost paid into
    the trigger: choosing a 2-gem room from a non-zero slot fires gems_spent
    and deducts the gems."""
    g = _game_at_laboratory()
    _configure(g, "gems_spent", "permanent_allowance")
    office = g.registry.by_id["office"]
    g.phase = Phase.DRAFTING
    g.state.pos = 7
    pd = PendingDraft(from_cell=7, direction=N, target_cell=12)  # neighbor(7, N) == 12
    pd.options = [DraftOption(room_idx=office.idx, orientation=office.door_mask,
                              gem_cost=2, slot=1)]
    g.doorway_drafts[(7, N)] = pd
    g.state.pending = pd
    g.state.gems = 5
    g.choose(1)
    assert g.state.gems == 3
    assert g.state.experiment.success_count == 1


def test_stopwatch_waiver_does_not_count_as_gems_spent():
    """The Stopwatch's gem waiver does not count as spending (gems are
    required in hand but never deducted), so gems_spent must not fire even
    though the nominal cost is >= 2."""
    g = _game_at_laboratory(cfg=GameConfig(special_items=True))
    _configure(g, "gems_spent", "permanent_allowance")
    office = g.registry.by_id["office"]
    g.phase = Phase.DRAFTING
    g.state.pos = 7
    pd = PendingDraft(from_cell=7, direction=N, target_cell=12)
    pd.options = [DraftOption(room_idx=office.idx, orientation=office.door_mask,
                              gem_cost=2, slot=1)]
    g.doorway_drafts[(7, N)] = pd
    g.state.pending = pd
    g.state.gems = 5
    g.state.special.stopwatch_left = 3
    g.choose(1)
    assert g.state.gems == 5  # waived: gems left untouched
    assert g.state.experiment.success_count == 0


def test_study_redraw_gem_spend_never_fires_gems_spent(cfg):
    """A Study redraw spends a gem through Game.redraw, which never calls
    _place_room -- gems_spent's only firing site -- so it cannot fire even
    though a gem was genuinely spent."""
    g = Game(cfg, seed=5)
    g.state.experiment.trigger_id = "gems_spent"
    g.state.experiment.effect_id = "permanent_allowance"
    g.open_door(2, N)
    g.state.study_placed = True
    g.state.gems = 3
    g.redraw(RedrawKind.STUDY)
    assert g.state.gems == 2
    assert g.state.experiment.success_count == 0


def test_entered_true_skips_draft_trigger_detection():
    """entered=True (used only for the day-start Entrance Hall) skips the whole
    draft-counting block in Game._place_room, including trigger detection --
    even a would-be-qualifying gem_cost never reaches on_room_drafted."""
    g = _game_at_laboratory()
    _configure(g, "gems_spent", "permanent_allowance")
    office = g.registry.by_id["office"]
    g._place_room(office, 10, office.rotations[0], entered=True, gem_cost=5)
    assert g.state.experiment.success_count == 0


def test_aquarium_draft_fires_shops_red_room_and_bedrooms_after_second_triggers():
    """The Aquarium's extra_categories (shop, red, hallway, bedroom, ...) mean
    a single Aquarium draft qualifies for four of the five placement-site
    triggers -- checked one trigger per fresh game so only one is active."""
    for trigger_id in ("shops", "red_room_draft"):
        g = _game_at_laboratory()
        _configure(g, trigger_id, "permanent_allowance")
        aquarium = g.registry.by_id["aquarium"]
        g._place_room(aquarium, 10, aquarium.rotations[0])
        assert g.state.experiment.success_count == 1, trigger_id

    # bedrooms_after_second: needs to be the 3rd Bedroom-equivalent overall.
    g = _game_at_laboratory()
    bedroom = g.registry.by_id["bedroom"]
    for cell in (10, 11):
        g._place_room(bedroom, cell, bedroom.rotations[0])
    _configure(g, "bedrooms_after_second", "permanent_allowance")
    aquarium = g.registry.by_id["aquarium"]
    g._place_room(aquarium, 12, aquarium.rotations[0])
    assert g.state.experiment.success_count == 1

    # hallway_from_hallway: needs to be drafted from a Hallway.
    g = _game_at_laboratory()
    hallway = g.registry.by_id["hallway"]
    g._place_room(hallway, 10, hallway.rotations[0])
    _configure(g, "hallway_from_hallway", "permanent_allowance")
    aquarium = g.registry.by_id["aquarium"]
    g._place_room(aquarium, 11, aquarium.rotations[0], entry_dir=W)
    assert g.state.experiment.success_count == 1


# ---------------------------------------------------------------------------
# Generic cap machinery
# ---------------------------------------------------------------------------

def test_capped_trigger_stops_firing_at_its_cap():
    """trunks_opened caps at 3: a 4th direct trigger_success call is a no-op --
    success_count and the chosen effect both stop advancing past the cap."""
    g = _game_at_laboratory()
    _configure(g, "trunks_opened", "permanent_allowance")
    for _ in range(4):
        experiments.trigger_success(g)
    assert g.state.experiment.success_count == 3
    assert g.state.allowance == 3


def test_pausing_preserves_cap_charges_across_a_qualifying_event():
    """A qualifying event suppressed by pause does not consume one of the cap's
    charges: pausing after 1 of 3 fires and resuming still allows the full
    remaining 2 fires, for 3 total (not 2) -- caps count fires, not events."""
    g = _game_at_laboratory()
    _configure(g, "trunks_opened", "permanent_allowance")
    assert experiments.trigger_success(g) is True
    assert g.state.experiment.success_count == 1

    g.state.experiment.paused = True
    assert experiments.trigger_success(g) is False  # suppressed, not counted
    assert g.state.experiment.success_count == 1

    g.state.experiment.paused = False
    assert experiments.trigger_success(g) is True
    assert experiments.trigger_success(g) is True
    assert g.state.experiment.success_count == 3
    assert experiments.trigger_success(g) is False  # genuinely capped out now
    assert g.state.experiment.success_count == 3


def test_capped_out_fire_does_not_charge_its_own_steps_lost():
    """map_view carries both cap=10 and a steps_lost magnitude; a call already
    at the cap must leave steps untouched, since the cap check sits before the
    steps_lost deduction in trigger_success."""
    g = _game_at_laboratory()
    _configure(g, "map_view", "permanent_allowance")
    g.state.experiment.success_count = 10  # already at map_view's cap
    g.state.steps = 50
    assert experiments.trigger_success(g) is False
    assert g.state.steps == 50
    assert g.state.allowance == 0


# ---------------------------------------------------------------------------
# trunks_opened: special_items.py::open_container
# ---------------------------------------------------------------------------

def test_trunks_opened_fires_on_a_smash_opened_trunk():
    """trunks_opened fires when a trunk is opened via a smash-tagged item
    (Sledge Hammer) -- 'or breaking the locks with the Sledge Hammer or
    equivalent' (wiki) -- even though no key was spent."""
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell
    _configure(g, "trunks_opened", "permanent_allowance")
    result = g.open_container()
    assert result is not None
    assert g.state.experiment.success_count == 1


def test_trunks_opened_fires_on_a_key_opened_trunk():
    """trunks_opened also fires for the ordinary key-unlock path, not only
    smash-opens -- 'unlock and open a chest' is the primary wording."""
    g = Game(GameConfig(), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.pos = cell
    g.state.keys = 1
    _configure(g, "trunks_opened", "permanent_allowance")
    result = g.open_container()
    assert result is not None
    assert g.state.keys == 0
    assert g.state.experiment.success_count == 1


def test_trunks_opened_does_not_fire_on_a_failed_open():
    """No keys and no smasher: open_container returns None and trunks_opened
    never fires -- only a container that actually opened can count."""
    g = Game(GameConfig(), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.pos = cell
    g.state.keys = 0
    _configure(g, "trunks_opened", "permanent_allowance")
    result = g.open_container()
    assert result is None
    assert g.state.experiment.success_count == 0


def test_trunks_opened_does_not_fire_on_a_locker():
    """Lockers (open or locked) are a distinct containers.kinds family from
    trunk/chest; opening one never fires trunks_opened."""
    g = Game(GameConfig(), seed=3)
    locker_room = g.registry.by_id["locker_room"]
    g.state.grid[7] = locker_room.idx
    g.state.placed_doors[7] = locker_room.door_mask
    g.state.pos = 7
    g.state.keys = 5
    _configure(g, "trunks_opened", "permanent_allowance")
    opened = 0
    while g.can_open_container() and opened < 4:
        g.open_container()
        opened += 1
    assert opened > 0, "Locker Room must have offered at least one container"
    assert g.state.experiment.success_count == 0


def test_trunks_opened_does_not_fire_on_the_garage_car_trunk():
    """The Garage car trunk is a separate one-per-day mechanic (open_car_trunk),
    never routed through open_container, so trunks_opened never fires for it."""
    g = Game(GameConfig(), seed=0)
    si.grant(g.state, g.registry, "car_keys", source="test")
    garage = g.registry.by_id["garage"]
    g._place_room(garage, 5, garage.rotations[0])
    g.state.pos = 5
    _configure(g, "trunks_opened", "permanent_allowance")
    assert g.can_open_car_trunk()
    granted = g.open_car_trunk()
    assert granted
    assert g.state.experiment.success_count == 0


def test_trunks_opened_does_not_fire_on_a_vault_box():
    """Vault deposit boxes (open_vault_box) are a distinct mechanic from
    trunks_opened, even though both are unlock-and-open container actions."""
    g = Game(GameConfig(), seed=0)
    vault = g.registry.by_id["vault"]
    g._place_room(vault, 10, vault.rotations[0])
    g.state.pos = 10
    g.state.inventory["vault_key_149"] = 1
    _configure(g, "trunks_opened", "permanent_allowance")
    assert g.can_open_vault_box()
    granted = g.open_vault_box()
    assert granted
    assert g.state.experiment.success_count == 0


# ---------------------------------------------------------------------------
# security_door: game.py's two sites (_unlock_for_passage, _roll_new_segments)
# ---------------------------------------------------------------------------

def test_security_door_fires_when_drafted_from_site_a():
    """Site A: drafting THROUGH a security doorway (open_door, for_draft=True)
    fires security_door -- the wiki's 'must be drafted from' requirement."""
    g = Game(GameConfig(), seed=0)
    g.state.has_keycard = True
    g.state.keycard_power_on = True
    g.state.door_state[segment_key(2, N)] = DOOR_SECURITY
    _configure(g, "security_door", "permanent_allowance")
    g.open_door(2, N)
    assert g.state.experiment.success_count == 1


def test_security_door_does_not_fire_on_a_plain_walk_through_site_a():
    """Site A is gated on for_draft=True: merely walking through an already
    security-doored connection (move, for_draft defaults False) opens the
    door but never fires the trigger -- 'just unlocking is not enough' (wiki)."""
    g = Game(GameConfig(), seed=0)
    hallway = g.registry.by_id["hallway"]
    g._place_room(hallway, 7, 13)  # 13 = W|S|N, connects south to the entrance
    g.state.has_keycard = True
    g.state.keycard_power_on = True
    seg = segment_key(2, N)
    g.state.door_state[seg] = DOOR_SECURITY
    _configure(g, "security_door", "permanent_allowance")
    g.move(N)
    assert g.state.pos == 7
    assert g.state.door_state[seg] == DOOR_OPEN  # the door did open for passage
    assert g.state.experiment.success_count == 0


def test_security_door_reopening_a_cached_doorway_does_not_double_fire():
    """Site A is idempotent: a second open_door call on the same doorway (the
    pending draft still cached, phase reset to NAVIGATE without a choose())
    reads the segment as already DOOR_OPEN and cannot fire a second time."""
    g = Game(GameConfig(), seed=0)
    g.state.has_keycard = True
    g.state.keycard_power_on = True
    g.state.door_state[segment_key(2, N)] = DOOR_SECURITY
    _configure(g, "security_door", "permanent_allowance")
    g.open_door(2, N)
    assert g.state.experiment.success_count == 1
    g.phase = Phase.NAVIGATE  # simulate re-opening before a choose() commits it
    g.open_door(2, N)
    assert g.state.experiment.success_count == 1


def test_security_door_fires_when_drafting_into_a_security_segment_site_b():
    """Site B: placing a room whose own door faces a neighbor's already-rolled
    DOOR_SECURITY segment converts it to open and fires security_door -- the
    wiki's 'opening a security door in a different room by drafting into it'."""
    g = _game_at_laboratory()
    hallway = g.registry.by_id["hallway"]
    seg = segment_key(12, E)
    g.state.door_state[seg] = DOOR_SECURITY
    _configure(g, "security_door", "permanent_allowance")
    g._place_room(hallway, 12, 7)  # 7 = N|E|S, faces the pre-rolled E segment
    assert g.state.experiment.success_count == 1


def test_security_door_does_not_fire_on_a_merely_locked_segment_site_b():
    """Site B only fires for a converted DOOR_SECURITY segment; converting an
    already-rolled DOOR_LOCKED segment the same way fires nothing."""
    g = _game_at_laboratory()
    hallway = g.registry.by_id["hallway"]
    seg = segment_key(12, E)
    g.state.door_state[seg] = DOOR_LOCKED
    _configure(g, "security_door", "permanent_allowance")
    g._place_room(hallway, 12, 7)
    assert g.state.experiment.success_count == 0


def test_security_door_site_b_can_fire_up_to_three_times_in_one_placement():
    """A 4-way room facing three already-rolled security segments fires once
    per segment -- up to 3 times in a single _place_room call, expected per
    the module's own documentation, not a bug."""
    g = _game_at_laboratory()
    entrance_hall = g.registry.by_id["entrance_hall"]
    for d in (N, E, S):
        g.state.door_state[segment_key(12, d)] = DOOR_SECURITY
    _configure(g, "security_door", "permanent_allowance")
    g._place_room(entrance_hall, 12, 15)  # 15 = N|E|S|W
    assert g.state.experiment.success_count == 3


# ---------------------------------------------------------------------------
# Availability: the day_gate filter in draw_offers
# ---------------------------------------------------------------------------

def test_day_gate_excludes_gated_triggers_before_day_8_without_veteran_mode():
    """With veteran_mode off and day < 8, security_door and drawing_room_drawn
    never appear in the offered pool -- yet the pool still has exactly 3
    entries, confirming the filter never shrinks the sampling pool below 3."""
    for seed in range(15):
        g = _game_at_laboratory(seed=seed, cfg=GameConfig(veteran_mode=False, day=1))
        g.start_setup()
        offered = g.state.experiment.offered_triggers
        assert len(offered) == 3
        assert "security_door" not in offered
        assert "drawing_room_drawn" not in offered


def test_day_gate_allows_gated_triggers_with_veteran_mode():
    """veteran_mode=True (the default) bypasses the day_gate regardless of
    day, so both gated triggers remain eligible for the sampling pool."""
    cfg = GameConfig(veteran_mode=True, day=1)
    g = Game(cfg, seed=0)
    trig_security = g.registry.experiments.trigger_by_id["security_door"]
    trig_drawing = g.registry.experiments.trigger_by_id["drawing_room_drawn"]
    assert experiments._trigger_offerable(trig_security, cfg) is True
    assert experiments._trigger_offerable(trig_drawing, cfg) is True


def test_day_gate_allows_gated_triggers_at_day_8_even_without_veteran_mode():
    """The gate only blocks days 1-7 without veteran_mode; day >= 8 always
    passes regardless of the veteran_mode setting."""
    cfg = GameConfig(veteran_mode=False, day=8)
    g = Game(cfg, seed=0)
    trig = g.registry.experiments.trigger_by_id["security_door"]
    assert experiments._trigger_offerable(trig, cfg) is True


# ---------------------------------------------------------------------------
# Scoped termination checks
# ---------------------------------------------------------------------------

def test_open_door_ends_the_day_when_the_fired_effect_drains_steps_to_zero():
    """security_door + steps_for_gold: drafting through a security doorway with
    few steps left zeroes them out, and open_door's own termination check
    ends the day inside the call rather than on some later NAVIGATE action."""
    g = Game(GameConfig(), seed=0)
    g.state.has_keycard = True
    g.state.keycard_power_on = True
    g.state.door_state[segment_key(2, N)] = DOOR_SECURITY
    g.state.steps = 5
    _configure(g, "security_door", "steps_for_gold")
    g.open_door(2, N)
    assert g.state.steps == 0
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"


def test_open_container_ends_the_day_when_the_fired_effect_drains_steps_to_zero():
    """trunks_opened + steps_for_gold: opening a trunk with few steps left
    zeroes them out, and open_container's own termination check ends the day."""
    g = Game(GameConfig(starting_items=frozenset({"sledge_hammer"})), seed=42)
    attic = g.registry.by_id["attic"]
    cell = 5
    g.state.grid[cell] = attic.idx
    g.state.placed_doors[cell] = attic.door_mask
    g.state.pos = cell
    g.state.steps = 5
    _configure(g, "trunks_opened", "steps_for_gold")
    g.open_container()
    assert g.state.steps == 0
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"
