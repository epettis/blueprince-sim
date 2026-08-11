"""Laboratory / Experiments: setup/pause/resume core, the pure-resource
effects, the six placement-site draft triggers (shops, red_room_draft,
hallway_from_hallway, bedrooms_after_second, gems_spent, archived_floorplan),
the generic cap machinery, the trunks_opened, security_door,
trash_while_digging, apples, and drawing_room_drawn interaction-site
triggers, the day_gate availability filter, and the scoped termination
checks added at open_door/open_container/move/redraw/
_maybe_finish_experiment_setup.

Mirrors test_upgrade_env.py's shape (direct Game construction plus the flat
action space) for the setup flow, and calls engine.experiments functions
directly for the effect-math checks, the same "engine function, not full
action loop" style test_special_items.py uses for its own effect pins. The
draft-trigger tests mostly drive Game._place_room directly (like the
existing _place helper), reaching for the real open_door/choose pipeline
only where the threading between them matters (gem cost, Stopwatch, Study,
security-door state).

drawing_room_drawn's own tests need a real Drawing Room in a real dealt
hand -- rewriting a deck's ``order`` alone is not enough, since the "rarity"
roll that picks which deck a slot draws from runs first and is not itself
seed-searchable in one step. ``_force_drawing_room_dealable`` instead forces
that roll to always pick commonplace (the Drawing Room's own rarity) via
``monkeypatch``, then reorders the two commonplace decks so the deal reaches
the Drawing Room's own gem-deck card without ever emptying a deck outright
(an emptied deck triggers draw_slot's attempt-3 full reshuffle, which would
scramble the surgery). This drives the real open_door/redraw/open_outer_draft
pipeline end to end rather than constructing a hand by hand, so it also
exercises the deal-site plumbing the trigger depends on.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import experiments
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import E, N, S, W
from blueprince_sim.engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY, segment_key
from blueprince_sim.engine.rng import Rng
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


def _force_drawing_room_dealable(monkeypatch, game: Game) -> None:
    """Rig ``game`` so the next 3-slot fill (initial deal or redraw) deals the Drawing Room.

    Forces every "rarity" roll to commonplace (the Drawing Room's own
    rarity), then reorders the commonplace decks so a slot's deal reaches the
    Drawing Room's own gem-deck card (gem_cost 1, so it lives in the gem
    deck) ahead of the free deck: trims the free deck's remaining cards below
    the gem deck's remaining count (never to zero -- an empty deck triggers a
    full reshuffle that would undo the ordering below) so draw_slot's
    remaining-count sort tries the gem deck first, then swaps the Drawing
    Room's card to the gem deck's cursor position. Leaves slot 0 (which only
    ever draws from the free deck) untouched, so it still deals normally.
    """
    orig_roll_weighted = Rng.roll_weighted

    def forced(self, label, weights):
        if label == "rarity":
            return 0  # commonplace
        return orig_roll_weighted(self, label, weights)

    monkeypatch.setattr(Rng, "roll_weighted", forced)
    dr = game.registry.by_id["drawing_room"]
    free_deck = game.state.deck(dr.rarity_idx, False)
    gem_deck = game.state.deck(dr.rarity_idx, True)
    del free_deck.order[free_deck.pos + 5:]
    i, pos = gem_deck.order.index(dr.idx), gem_deck.pos
    gem_deck.order[i], gem_deck.order[pos] = gem_deck.order[pos], gem_deck.order[i]


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


def _choose_archived(game: Game, room, archived: bool, hidden: bool = True) -> None:
    """Deal one option in slot 1 (from the Laboratory, north to cell 12) and choose it,
    with DraftOption.archived/hidden set directly -- the site under test is choose()'s
    own handling of an already-dealt option, not the deal that concealed it."""
    game.phase = Phase.DRAFTING
    game.state.pos = 7
    pd = PendingDraft(from_cell=7, direction=N, target_cell=12)
    pd.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                              gem_cost=0, slot=1, hidden=hidden, archived=archived)]
    game.doorway_drafts[(7, N)] = pd
    game.state.pending = pd
    game.choose(1)


def test_archived_floorplan_fires_when_choosing_an_archived_option():
    """archived_floorplan fires on choosing an option DraftOption.archived flags --
    an Archives-archived floorplan -- not on the earlier deal that archived it."""
    g = _game_at_laboratory()
    _configure(g, "archived_floorplan", "permanent_allowance")
    _choose_archived(g, g.registry.by_id["closet"], archived=True)
    assert g.state.experiment.success_count == 1


def test_archived_floorplan_does_not_fire_for_a_merely_hidden_option():
    """A Darkroom-hidden option (hidden=True, archived=False) never fires the
    trigger -- only an Archives' own archived flag counts, per DraftOption's
    "archived implies hidden, never the converse" contract."""
    g = _game_at_laboratory()
    _configure(g, "archived_floorplan", "permanent_allowance")
    _choose_archived(g, g.registry.by_id["closet"], archived=False, hidden=True)
    assert g.state.experiment.success_count == 0


def test_archived_floorplan_does_not_fire_for_a_visible_option():
    """A plain, unconcealed option never fires archived_floorplan."""
    g = _game_at_laboratory()
    _configure(g, "archived_floorplan", "permanent_allowance")
    _choose_archived(g, g.registry.by_id["closet"], archived=False, hidden=False)
    assert g.state.experiment.success_count == 0


def test_archived_floorplan_bunk_room_fires_twice():
    """Wiki: "If the archived floorplan is a Bunk Room, it triggers twice" -- read
    off the same counts_as_bedrooms/amount tag bedrooms_after_second uses, not a
    hard-coded Bunk Room id."""
    g = _game_at_laboratory()
    _configure(g, "archived_floorplan", "permanent_allowance")
    _choose_archived(g, g.registry.by_id["bunk_room"], archived=True)
    assert g.state.experiment.success_count == 2


def test_archived_floorplan_does_not_fire_for_a_different_configured_trigger():
    """A different configured trigger never fires archived_floorplan's own branch,
    even for a genuinely archived option."""
    g = _game_at_laboratory()
    _configure(g, "shops", "permanent_allowance")
    _choose_archived(g, g.registry.by_id["closet"], archived=True)
    assert g.state.experiment.success_count == 0


def test_archived_floorplan_does_not_fire_while_paused():
    """Pausing suppresses a qualifying archived-option choice like every other trigger."""
    g = _game_at_laboratory()
    _configure(g, "archived_floorplan", "permanent_allowance")
    g.state.experiment.paused = True
    _choose_archived(g, g.registry.by_id["closet"], archived=True)
    assert g.state.experiment.success_count == 0


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
# trash_while_digging: special_items.py::dig_all
# ---------------------------------------------------------------------------

class _AlwaysIndexRng(Rng):
    """Rng whose roll_weighted always returns a fixed index, forcing every
    dig roll onto one chosen table row regardless of its actual weight."""

    def __init__(self, seed: int, index: int) -> None:
        super().__init__(seed)
        self._index = index

    def roll_weighted(self, label: str, weights: tuple) -> int:  # noqa: ARG002
        return self._index


def test_trash_while_digging_fires_on_a_junk_outcome():
    """A dig outcome of 'junk' (the shovel table's row 0) fires the trigger
    and applies the chosen effect."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    storeroom = g.registry.by_id["storeroom"]
    cell = 10
    g.state.grid[cell] = storeroom.idx
    _configure(g, "trash_while_digging", "permanent_allowance")
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 1
    assert g.state.allowance == 1


def test_trash_while_digging_does_not_fire_on_a_nothing_outcome():
    """'Digging up nothing does not count as finding trash' (wiki): a
    'nothing' outcome (the shovel table's row 5) must not fire the trigger,
    even with it configured and unpaused."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    storeroom = g.registry.by_id["storeroom"]
    cell = 10
    g.state.grid[cell] = storeroom.idx
    _configure(g, "trash_while_digging", "permanent_allowance")
    g.rng = _AlwaysIndexRng(0, 5)  # force the shovel table's nothing row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


def test_trash_while_digging_fires_once_per_junk_spot_in_a_bulk_dig():
    """dig_all digs every remaining spot at a cell in one call; an all-junk
    dig on a 2-spot room fires the trigger twice, once per spot, not once
    per arrival (call)."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    tomb = g.registry.by_id["tomb"]
    assert tomb.items.dig_spots == 2
    cell = 10
    g.state.grid[cell] = tomb.idx
    _configure(g, "trash_while_digging", "permanent_allowance")
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 2
    assert g.state.allowance == 2


def test_trash_while_digging_does_not_fire_for_a_different_configured_trigger():
    """Digging up junk while a different trigger (shops) is configured must
    not fire trash_while_digging's effect -- only the currently configured
    trigger's own branch may call trigger_success."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    storeroom = g.registry.by_id["storeroom"]
    cell = 10
    g.state.grid[cell] = storeroom.idx
    _configure(g, "shops", "permanent_allowance")
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


def test_trash_while_digging_does_not_fire_while_paused():
    """trigger_success's active gate suppresses trash_while_digging the same
    way it suppresses every other trigger while the experiment is paused."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    storeroom = g.registry.by_id["storeroom"]
    cell = 10
    g.state.grid[cell] = storeroom.idx
    _configure(g, "trash_while_digging", "permanent_allowance")
    g.state.experiment.paused = True
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


def test_trash_while_digging_burst_drains_steps_and_floors_at_zero():
    """The burst case: Furnace is the only fireplace room with a nonzero base
    dig_spots (1), so a Furnace drafted from a Cloister of Veia reaches the
    highest single-cell dig-spot total reachable through normal play, 1 + 8
    (the Cloister's fireplace-room bonus) = 9 -- not the 5 + 8 = 13 a naive
    sum of the two maxima would suggest, since Courtyard (the room with the
    highest plain dig_spots, 5) is not one of the seven fireplace rooms and so
    never collects the Cloister bonus. An all-junk dig there with
    steps_for_gold configured fires 9 times (-10 steps / +20 coins each): 90
    steps of drain against a starting balance of 50 floors at 0 rather than
    going negative, while every fire still pays out its coins."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    furnace = g.registry.by_id["furnace"]
    assert furnace.items.dig_spots == 1
    assert furnace.has_fireplace
    cell = 10
    g.state.grid[cell] = furnace.idx
    g.state.special.veia_dig_bonus[cell] = 8  # Cloister of Veia fireplace-room bonus
    _configure(g, "trash_while_digging", "steps_for_gold")
    g.state.steps = 50
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    si.dig_all(g, cell)
    assert g.state.experiment.success_count == 9
    assert g.state.steps == 0
    assert g.state.coins == 9 * 20


def test_move_ends_the_day_when_a_dig_burst_drains_steps_to_zero():
    """move()'s own termination check runs after on_arrive (which runs
    dig_all), so a single move() into a multi-spot dig room that drains steps
    via repeated trash_while_digging fires still ends the day correctly."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0)
    tomb = g.registry.by_id["tomb"]
    g._place_room(tomb, 7, S)
    _configure(g, "trash_while_digging", "steps_for_gold")
    g.state.steps = 5
    g.rng = _AlwaysIndexRng(0, 0)  # force the shovel table's junk row
    g.move(N)
    assert g.state.experiment.success_count == tomb.items.dig_spots
    assert g.state.steps == 0
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"


# ---------------------------------------------------------------------------
# apples: special_items.py::eat_food's per-item loop
# ---------------------------------------------------------------------------

def test_apples_fires_when_eating_an_apple():
    """Eating an apple with the apples trigger configured fires it once and
    applies the chosen effect."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "permanent_allowance")
    si.eat_food(g, "apple", 1)
    assert g.state.experiment.success_count == 1
    assert g.state.allowance == 1


def test_apples_does_not_fire_for_a_banana_or_orange():
    """'No other fruit count for this trigger' (wiki): eating a banana or an
    orange, the two other dishes food.fruit_weights can roll, must not fire
    the apples trigger."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "permanent_allowance")
    si.eat_food(g, "banana", 1)
    si.eat_food(g, "orange", 1)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


def test_apples_with_set_steps_ends_at_40_not_42():
    """The wiki's stated interaction: 'the steps from the apple are gained
    before the experimental effect applies', so set_steps (steps := 40)
    fires and overwrites the apple's own step gain last -- steps end at the
    flat 40, not 42 (10 starting + 2 for the apple + a hypothetical 40 on
    top, the wrong order this test rules out)."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "set_steps")
    g.state.steps = 10
    si.eat_food(g, "apple", 1)
    assert g.state.steps == 40


def test_apples_fires_once_per_apple_in_a_bulk_eat():
    """eat_food's count parameter (the Secret Garden Conference Room path
    passes 4 apples in a single call) fires the trigger once per apple
    inside the loop, not once per call -- apples are eaten one at a time in
    the real game."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "permanent_allowance")
    si.eat_food(g, "apple", 4)
    assert g.state.experiment.success_count == 4
    assert g.state.allowance == 4


def test_apples_conference_room_spread_fires_four_times():
    """The real firing site, exercised end to end: a Secret Garden's
    Conference Room spread parks 4 apples in one spread_pending entry
    (effects/rooms/secret_garden.py's CONFERENCE_ROOM_APPLES), collected by
    Game._collect_spread on arrival -- which must fire the trigger four
    times, interleaved with each apple's own step gain, not once."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "permanent_allowance")
    g.state.spread_pending[10] = [("apple", 4)]
    g._collect_spread(10)
    assert g.state.experiment.success_count == 4
    assert g.state.allowance == 4


def test_apples_does_not_fire_for_a_different_configured_trigger():
    """Eating an apple while a different trigger (shops) is configured must
    not fire the apples effect -- only the currently configured trigger's
    own branch may call trigger_success."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "shops", "permanent_allowance")
    si.eat_food(g, "apple", 1)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


def test_apples_does_not_fire_while_paused():
    """trigger_success's active gate suppresses apples the same way it
    suppresses every other trigger while the experiment is paused."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "apples", "permanent_allowance")
    g.state.experiment.paused = True
    si.eat_food(g, "apple", 1)
    assert g.state.experiment.success_count == 0
    assert g.state.allowance == 0


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
# Interaction-site trigger: drawing_room_drawn
# ---------------------------------------------------------------------------

def test_drawing_room_drawn_fires_on_an_initial_deal_containing_it(monkeypatch):
    """drawing_room_drawn fires once when a real open_door() initial deal
    contains the Drawing Room -- not fired more times just because two other
    unrelated options were dealt alongside it in the same hand."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    _force_drawing_room_dealable(monkeypatch, g)
    dr_idx = g.registry.by_id["drawing_room"].idx
    pending = g.open_door(2, N)
    assert dr_idx in [o.room_idx for o in pending.options]
    assert g.state.experiment.success_count == 1


def test_drawing_room_drawn_fires_again_on_each_redraw_that_deals_it(monkeypatch):
    """A redraw that deals a fresh Drawing Room fires the trigger again --
    ON_HAND_DEALT is deliberately re-fired for every redealt hand."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    pending = g.open_door(2, N)  # ordinary initial deal, no Drawing Room forced
    assert g.registry.by_id["drawing_room"].idx not in [o.room_idx for o in pending.options]
    assert g.state.experiment.success_count == 0
    g.state.dice = 1
    _force_drawing_room_dealable(monkeypatch, g)
    dr_idx = g.registry.by_id["drawing_room"].idx
    g.redraw(RedrawKind.DIE)
    assert dr_idx in [o.room_idx for o in g.state.pending.options]
    assert g.state.experiment.success_count == 1


def test_drawing_room_drawn_never_fires_twice_for_one_hand(monkeypatch):
    """Reopening an already-dealt doorway returns the cached hand without
    re-dealing, so a second open_door() on the same doorway never re-fires
    ON_HAND_DEALT (and the trigger) for the same hand."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    _force_drawing_room_dealable(monkeypatch, g)
    g.open_door(2, N)
    assert g.state.experiment.success_count == 1
    g.phase = Phase.NAVIGATE  # simulate returning to NAVIGATE without choosing
    g.open_door(2, N)  # same doorway: doorway_drafts cache hit, no re-deal
    assert g.state.experiment.success_count == 1


def test_drawing_room_drawn_never_fires_on_an_outer_deal():
    """The fixed 8-room outer pool can never contain the Drawing Room, so a
    real open_outer_draft() never fires the trigger -- a permanent no-op site."""
    g = Game(GameConfig(west_gate_unlatched=True, starting_steps=50), seed=0)
    assert g.registry.by_id["drawing_room"].id not in {r.id for r in g.outer_rooms}
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    g.open_outer_draft()
    assert g.state.experiment.success_count == 0


def test_drawing_room_drawn_fires_for_a_hidden_drawing_room(monkeypatch):
    """A Darkroom-hidden Drawing Room still counts: the room_hook receives no
    concealment info at all, matching the wiki's plain "drawn" wording."""
    g = Game(GameConfig(), seed=0)
    darkroom = g.registry.by_id["darkroom"]
    g._place_room(darkroom, 7, N | S)
    g.state.pos = 7
    g.state.darkroom_lights_on = False
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    _force_drawing_room_dealable(monkeypatch, g)
    dr_idx = g.registry.by_id["drawing_room"].idx
    pending = g.open_door(7, N)
    dealt = next(o for o in pending.options if o.room_idx == dr_idx)
    assert dealt.hidden
    assert g.state.experiment.success_count == 1


def test_drawing_room_drawn_fires_for_an_archived_drawing_room(monkeypatch):
    """An Archives-archived Drawing Room still counts, for the same reason a
    merely-hidden one does."""
    g = Game(GameConfig(), seed=0)
    g.state.archives_active = True
    orig_randint = Rng.randint

    def forced_randint(self, label, lo, hi):
        if label == "archives_slot":
            return 1  # matches the slot _force_drawing_room_dealable lands it in
        return orig_randint(self, label, lo, hi)

    monkeypatch.setattr(Rng, "randint", forced_randint)
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    _force_drawing_room_dealable(monkeypatch, g)
    dr_idx = g.registry.by_id["drawing_room"].idx
    pending = g.open_door(2, N)
    dealt = next(o for o in pending.options if o.room_idx == dr_idx)
    assert dealt.archived
    assert g.state.experiment.success_count == 1


def test_drawing_room_drawn_does_not_fire_for_a_different_configured_trigger(monkeypatch):
    """A different configured trigger never fires drawing_room_drawn's own hook,
    even when the Drawing Room really is dealt."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "shops", "permanent_allowance")
    _force_drawing_room_dealable(monkeypatch, g)
    pending = g.open_door(2, N)
    assert g.registry.by_id["drawing_room"].idx in [o.room_idx for o in pending.options]
    assert g.state.experiment.success_count == 0


def test_drawing_room_drawn_does_not_fire_while_paused(monkeypatch):
    """Pausing suppresses a qualifying deal like every other trigger."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "drawing_room_drawn", "permanent_allowance")
    g.state.experiment.paused = True
    _force_drawing_room_dealable(monkeypatch, g)
    pending = g.open_door(2, N)
    assert g.registry.by_id["drawing_room"].idx in [o.room_idx for o in pending.options]
    assert g.state.experiment.success_count == 0


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


def test_redraw_ends_the_day_when_the_fired_effect_drains_steps_to_zero(monkeypatch):
    """drawing_room_drawn + steps_for_gold: a redraw that deals the Drawing Room
    with few steps left zeroes them out, and redraw()'s own termination check
    (added at the end, after the ON_HAND_DEALT loop) ends the day inside the
    call rather than on some later NAVIGATE action."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "drawing_room_drawn", "steps_for_gold")
    g.open_door(2, N)  # ordinary initial deal; does not itself contain the Drawing Room
    g.state.dice = 1
    g.state.steps = 5
    _force_drawing_room_dealable(monkeypatch, g)
    g.redraw(RedrawKind.DIE)
    assert g.state.steps == 0
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"
