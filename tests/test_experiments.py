"""Laboratory / Experiments: setup/pause/resume core, the pure-resource
effects, the six placement-site draft triggers (shops, red_room_draft,
hallway_from_hallway, bedrooms_after_second, gems_spent, archived_floorplan),
the generic cap machinery, the trunks_opened, security_door,
trash_while_digging, apples, and drawing_room_drawn interaction-site
triggers, the day_gate availability filter, and the scoped termination
checks added at open_door/open_container/move/redraw/
_maybe_finish_experiment_setup. Also covers the six packet triggers with
firing sites (rank9_first_entry, upgraded_floorplan_draft,
tomorrow_room_draft, fireplace_draft, antechamber_lever_pull,
terminal_access), reachable in play once ``cfg.satellite_dish_unlocked`` is
set -- most of the tests below still configure the experiment directly via
``_configure`` and drive the actual engine event without going through
draw_offers, the same shape the base-trigger tests above use. The final
section (``cfg.satellite_dish_unlocked``) covers draw_offers's packet-pool
gate itself: unreachable with the flag unset, reachable (implemented records
only) once it is set, and byte-identical to the pre-gate draw on the unset
path.

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
from blueprince_sim.engine.draft import (DraftContext, _active_conditions, _priority_draw,
                                         room_draftable)
from blueprince_sim.engine.game import ANTECHAMBER_CELL, Game, Phase, RedrawKind
from blueprince_sim.engine.grid import E, ENTRANCE_CELL, N, S, W
from blueprince_sim.engine.items import EXTRA_ITEM_TABLE
from blueprince_sim.engine.locks import (DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, DOOR_SECURITY,
                                         segment_key)
from blueprince_sim.engine.model import RARITY_INDEX
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DraftOption, GameState, PendingDraft
from blueprince_sim.env import actions as A
from blueprince_sim.env.multiday import DayChain
from blueprince_sim.env import obs as obs_mod


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


def _place_at(game: Game, room_id: str, cell: int, mask: int) -> None:
    """Place ``room_id`` on the grid directly (test setup, no drafting, no ON_PLACE
    hook) -- matches tests/rooms/test_weight_room.py's own helper of the same name,
    used here so entering a lever room does not also fire an unrelated ON_PLACE
    effect (e.g. the Secret Garden's own fruit spread, which touches RNG)."""
    room = game.registry.by_id[room_id]
    game.state.grid[cell] = room.idx
    game.state.placed_doors[cell] = mask
    game.state.entered[cell] = False
    game.room_cells[room_id] = cell
    game.placed_ids.add(room_id)
    game.state.door_version += 1


def _enter_at(game: Game, cell: int) -> None:
    """Teleport the player to ``cell`` and fire ON_ENTER, without spending steps."""
    game.state.pos = cell
    game._enter(cell)


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
    """apply_effect no-ops for an effect whose record is implemented=false.

    spread_dig_spots is the last remaining inert base effect now that
    add_aquariums has its own firing site (see the add_aquariums tests below).
    """
    g = _game_at_laboratory()
    before = (g.state.keys, g.state.gems, g.state.dice, g.state.coins, g.state.allowance)
    experiments.apply_effect(g, "spread_dig_spots")  # implemented=false
    after = (g.state.keys, g.state.gems, g.state.dice, g.state.coins, g.state.allowance)
    assert before == after


def test_gain_star_effect_adds_one_star():
    """apply_effect('gain_star') adds 1 to the permanent star total."""
    g = _game_at_laboratory()
    g.state.stars = 2
    experiments.apply_effect(g, "gain_star")
    assert g.state.stars == 3


# ---------------------------------------------------------------------------
# Three packet effects: unseal_antechamber_door, random_item_then_zero_keys,
# half_steps_for_dice. All three are mechanically implemented but stay
# undrawable (pool="packet", or_packet stays False in _effect_offerable), the
# same shape keys_per_30_steps already established -- reachable only via
# direct apply_effect, as every test below does.
# ---------------------------------------------------------------------------

def test_unseal_antechamber_door_opens_west_first():
    """Unseals the Antechamber's west segment first, leaving south/east/north
    still sealed -- pins the west/south/east/north order _apply_unseal_antechamber_door
    copies from Game.__init__'s own sealing loop."""
    g = _game_at_laboratory()
    experiments.apply_effect(g, "unseal_antechamber_door")
    assert g.door_state_of(41, E) == DOOR_OPEN
    assert g.door_state_of(37, N) == DOOR_SEALED
    assert g.door_state_of(43, W) == DOOR_SEALED
    assert g.door_state_of(ANTECHAMBER_CELL, N) == DOOR_SEALED


def test_unseal_antechamber_door_unseals_all_four_in_order_then_no_ops():
    """Four successive applications unseal west, south, east, north in that
    order; a fifth application (all four already open) changes nothing --
    the record's own notes say it "still triggers, no-op" past that point."""
    g = _game_at_laboratory()
    segments = [(41, E), (37, N), (43, W), (ANTECHAMBER_CELL, N)]
    for cell, direction in segments:
        assert g.door_state_of(cell, direction) == DOOR_SEALED  # sealed to start
        experiments.apply_effect(g, "unseal_antechamber_door")
        assert g.door_state_of(cell, direction) == DOOR_OPEN
    experiments.apply_effect(g, "unseal_antechamber_door")  # no-op: none left sealed
    for cell, direction in segments:
        assert g.door_state_of(cell, direction) == DOOR_OPEN


def test_random_item_then_zero_keys_grants_before_zeroing():
    """Order matters: at seed 0 (_game_at_laboratory's default), the shared
    extra-item roll's first draw lands on 'key' (index 1 of items.EXTRA_ITEM_TABLE).
    If keys were zeroed BEFORE the grant, the final count would be 1, not 0 --
    this pins 'gain 1 random item, THEN set your keys to 0' in that order."""
    g = _game_at_laboratory()
    g.state.keys = 5
    experiments.apply_effect(g, "random_item_then_zero_keys")
    assert g.state.keys == 0
    assert g.state.items_found_log[-1] == ("key", 1)


def test_random_item_then_zero_keys_is_the_only_new_draw():
    """apply_effect consumes exactly one value from 'extra_item_kind' (an
    existing, reused label -- see the function's own docstring) -- not zero,
    not two. A fresh, untouched Rng on the same seed gives that substream's
    first two draws (1, then 2, all three of the seed-0 sequence's first
    three values are distinct); the game's own stream, after apply_effect
    runs once, must land on the SECOND of those, proving exactly one draw
    was consumed by the effect itself."""
    weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
    reference = Rng(0)
    reference.roll_weighted("extra_item_kind", weights)  # the draw apply_effect also makes
    second = reference.roll_weighted("extra_item_kind", weights)

    g = _game_at_laboratory()  # seed 0, same as `reference`
    experiments.apply_effect(g, "random_item_then_zero_keys")
    next_roll = g.rng.roll_weighted("extra_item_kind", weights)
    assert next_roll == second


def test_half_steps_for_dice_floors_an_odd_step_count():
    """7 steps halve to 3, not 4 -- math.floor(7 * 0.5), pinning the rounding
    direction the record's own magnitude.steps_rounding: 'floor' specifies."""
    g = _game_at_laboratory()
    g.state.steps = 7
    g.state.dice = 0
    experiments.apply_effect(g, "half_steps_for_dice")
    assert g.state.steps == 3
    assert g.state.dice == 4


def test_half_steps_for_dice_grants_dice_even_when_steps_hit_zero():
    """1 step (odd) floors to 0 steps, and the 4 Ivory Die are still granted
    afterward even though that alone is enough to end the day -- pins that the
    destructive first half never skips the second half's grant. Termination
    is not checked by apply_effect itself (see the function's own docstring),
    so the day is confirmed over only once _check_termination is called."""
    g = _game_at_laboratory()
    g.state.steps = 1
    g.state.dice = 0
    experiments.apply_effect(g, "half_steps_for_dice")
    assert g.state.steps == 0
    assert g.state.dice == 4
    assert g.phase is Phase.NAVIGATE  # not yet re-checked
    g._check_termination()
    assert g.phase is Phase.TERMINAL
    assert g.termination_reason == "out_of_steps"


def test_four_packet_effects_stay_genuinely_inert():
    """pantry_fruit, reservoir_water_level, remove_tunnel_crate, and
    permanent_lockpicking_skill are still implemented=false and apply_effect
    still no-ops for each -- the four the brief for this pass ruled out of
    scope (missing mechanics or an owner-scoped exclusion), not merely
    claimed inert without checking."""
    g = _game_at_laboratory()
    for effect_id in ("pantry_fruit", "reservoir_water_level",
                      "remove_tunnel_crate", "permanent_lockpicking_skill"):
        record = g.registry.experiments.effect_by_id[effect_id]
        assert not record.implemented
        before = (g.state.keys, g.state.gems, g.state.dice, g.state.coins,
                  g.state.steps, g.state.stars)
        experiments.apply_effect(g, effect_id)
        after = (g.state.keys, g.state.gems, g.state.dice, g.state.coins,
                 g.state.steps, g.state.stars)
        assert before == after


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


# ---------------------------------------------------------------------------
# Effect caps: entrance_hall_trunk (17) and mail_room_letter (16)
# ---------------------------------------------------------------------------

def test_effect_cap_no_ops_but_trigger_still_succeeds():
    """entrance_hall_trunk already at its 17-trunk cap: trigger_success still
    returns True and success_count still advances, but the effect itself adds
    no further trunk -- the distinction an effect cap draws from a trigger cap
    (trunks_opened, map_view), which suppresses the whole fire instead."""
    g = _game_at_laboratory()
    _configure(g, "immediately", "entrance_hall_trunk")
    g.state.special.entrance_hall_trunks = 17
    assert experiments.trigger_success(g) is True
    assert g.state.experiment.success_count == 1
    assert g.state.special.entrance_hall_trunks == 17


def test_entrance_hall_trunk_caps_at_seventeen():
    """18 direct fires of entrance_hall_trunk (an uncapped trigger paired with
    it) leave the trunk count at 17, not 18 -- the 17th application is the
    last, and success_count keeps advancing past it since the trigger itself
    never caps."""
    g = _game_at_laboratory()
    _configure(g, "immediately", "entrance_hall_trunk")
    for _ in range(18):
        experiments.trigger_success(g)
    assert g.state.special.entrance_hall_trunks == 17
    assert g.state.experiment.success_count == 18


def test_entrance_hall_trunk_adds_an_openable_trunk_at_the_entrance_hall():
    """Firing entrance_hall_trunk adds a container at ENTRANCE_CELL that the
    existing can_open_container/open_container actions can open, reusing the
    'trunk' containers.kind (the wiki: no difference from a regular trunk)."""
    g = Game(GameConfig(), seed=0)
    g.state.keys = 1
    _configure(g, "immediately", "entrance_hall_trunk")
    experiments.trigger_success(g)
    assert g.state.special.entrance_hall_trunks == 1
    assert g.state.pos == ENTRANCE_CELL
    assert g.can_open_container()
    result = g.open_container()
    assert result is not None
    assert g.state.special.opened_containers.get(ENTRANCE_CELL, 0) == 1


def test_entrance_hall_trunks_do_not_carry_to_the_next_day():
    """Owner ruling: 17 is a daily maximum -- reset() (a fresh day) clears both
    the trunk count and any opened-container record, with no carry-over field
    feeding either back in from GameConfig."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "immediately", "entrance_hall_trunk")
    experiments.trigger_success(g)
    assert g.state.special.entrance_hall_trunks == 1
    g.reset()
    assert g.state.special.entrance_hall_trunks == 0
    assert g.state.special.opened_containers.get(ENTRANCE_CELL, 0) == 0


def test_opening_entrance_hall_trunk_fires_trunks_opened():
    """An Entrance-Hall trunk added by entrance_hall_trunk routes through the
    same open_container path as any other trunk, so a configured trunks_opened
    trigger fires for it too -- the two effects/triggers are designed to pair."""
    g = Game(GameConfig(), seed=0)
    g.state.special.entrance_hall_trunks = 1
    g.state.keys = 1
    _configure(g, "trunks_opened", "permanent_allowance")
    assert g.can_open_container()
    result = g.open_container()
    assert result is not None
    assert g.state.experiment.success_count == 1


def test_obs_grid_containers_shows_the_entrance_hall_trunk():
    """grid_containers (env/obs.py) is routed through _container_kinds_at, so a
    per-cell overlay like the Entrance Hall's added trunk is visible there too,
    not just the static per-room containers.json table."""
    g = Game(GameConfig(), seed=0)
    g.state.special.entrance_hall_trunks = 1
    observation = obs_mod.encode(g)
    row, col = ENTRANCE_CELL // 5, ENTRANCE_CELL % 5
    assert observation["grid_containers"][row, col] == 1
    assert observation["grid_containers"].shape == (9, 5)


def test_mail_room_letter_not_offered_before_day_11():
    """mail_room_letter's day_or_packet_gate excludes it before day 11 -- unlike
    the trigger-side day_gate kind, this one carries no veteran_bypass field at
    all, so veteran_mode plays no part (set False here only to avoid any other
    gate's bypass muddying the assertion)."""
    g = Game(GameConfig(veteran_mode=False, day=10), seed=0)
    effect = g.registry.experiments.effect_by_id["mail_room_letter"]
    assert experiments._effect_offerable(effect, g.cfg, g.state.experiment) is False


def test_mail_room_letter_offered_at_day_11():
    """The same gate opens at day 11 exactly."""
    g = Game(GameConfig(veteran_mode=False, day=11), seed=0)
    effect = g.registry.experiments.effect_by_id["mail_room_letter"]
    assert experiments._effect_offerable(effect, g.cfg, g.state.experiment) is True


def test_mail_room_letter_never_offered_once_sixteen_delivered():
    """Once ExperimentState.letters_delivered reaches the effect's own cap (16),
    _effect_offerable excludes it regardless of the day gate having opened."""
    g = Game(GameConfig(veteran_mode=False, day=20), seed=0)
    effect = g.registry.experiments.effect_by_id["mail_room_letter"]
    g.state.experiment.letters_delivered = 16
    assert experiments._effect_offerable(effect, g.cfg, g.state.experiment) is False


def test_letters_delivered_is_seeded_from_config_at_reset():
    """A day starts with the save's letter total, not at zero.

    Without this the cap could only ever see today's deliveries, so "never
    offered again after 16" could never become true however many days passed.
    """
    g = Game(GameConfig(letters_delivered=9), seed=0)
    assert g.state.experiment.letters_delivered == 9


def test_letters_delivered_survives_a_day_and_an_attempt_wrap():
    """The letter total carries across days and through a fresh attempt.

    Letters are permanent additions to the Mail Room, so unlike almost every
    other carried value they are save-scoped -- an attempt wrap must not put
    already-delivered letters back on the table.
    """
    chain = DayChain(GameConfig(), n_days=2)
    assert chain.next_config().letters_delivered == 0

    chain.advance({"letters_delivered": 5})
    assert chain.next_config().letters_delivered == 5, "must carry to the next day"

    chain.advance({})  # day 3 exceeds n_days=2, so the attempt wraps
    assert chain.next_config().letters_delivered == 5, (
        "letters are save-scoped and must survive the attempt wrap"
    )


def test_mail_room_letter_exclusion_never_shrinks_effect_pool_below_three():
    """With mail_room_letter excluded (day < 11, veteran off), start_setup's
    offered_effects still has exactly 3 entries -- effect availability
    filtering must never shrink the sampling pool below what draw_offers
    needs to sample, mirroring the trigger-side day_gate guarantee."""
    for seed in range(15):
        g = _game_at_laboratory(seed=seed, cfg=GameConfig(veteran_mode=False, day=1))
        g.start_setup()
        offered = g.state.experiment.offered_effects
        assert len(offered) == 3
        assert "mail_room_letter" not in offered


# ---------------------------------------------------------------------------
# add_aquariums: inject_rooms_undealt + set_dynamic_rarity + the one-copy
# waiver in draft.py::room_draftable + the two condition-gated priority draws
# ---------------------------------------------------------------------------

# Interior cell (rank 3, col 2) reached moving south -- comfortably away from
# grid edges, mirroring tests/rooms/test_chamber_of_mirrors.py's own target
# cell so door-geometry legality is never the reason a room is rejected here.
_AQUARIUM_TARGET_CELL = 12
_AQUARIUM_DIRECTION = S


def test_add_aquariums_injects_three_copies_and_moves_both_aquariums_to_commonplace():
    """First firing: 3 aquarium__experiment cards are injected, and both the
    base Aquarium and the experiment copy end up in the Commonplace deck --
    the '3 Aquariums' headline number and the DataSpoiler's Dynamic-Rarity
    claim, pinned together since inject must run before the rarity move for
    either to land in the right bucket (see _apply_add_aquariums's own
    docstring)."""
    g = _game_at_laboratory()
    aqx = g.registry.by_id["aquarium__experiment"]
    aq = g.registry.by_id["aquarium"]
    unusual_idx = RARITY_INDEX["unusual"]
    commonplace_idx = RARITY_INDEX["commonplace"]
    unusual_gem_deck = g.state.deck(unusual_idx, True)  # both rooms cost 1 gem: is_free is False
    assert unusual_gem_deck.order.count(aq.idx) == 1, "base Aquarium starts in its own rarity"
    assert unusual_gem_deck.order.count(aqx.idx) == 0, "no experiment copies exist yet"

    experiments.apply_effect(g, "add_aquariums")

    commonplace_gem_deck = g.state.deck(commonplace_idx, True)
    assert commonplace_gem_deck.order.count(aqx.idx) == 3
    assert commonplace_gem_deck.order.count(aq.idx) == 1
    unusual_gem_deck = g.state.deck(unusual_idx, True)
    assert aqx.idx not in unusual_gem_deck.order
    assert aq.idx not in unusual_gem_deck.order

    ctx = DraftContext(g.state, g.registry, g.cfg, g.rng, set(), None)
    assert room_draftable(ctx, aqx, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set()), (
        "an injected copy must be genuinely draftable, not just present in a deck"
    )


def test_add_aquariums_firing_twice_does_not_move_the_rarity_twice():
    """set_dynamic_rarity's own idempotency means a second fire consumes no
    extra RNG on the rarity-move step and leaves the recorded bucket
    unchanged -- 'sets the Dynamic Rarity' is a standing state, not a
    repeatable action, matching the wiki wording and this effect's lack of a
    cap (it fires on every qualifying draft, uncapped)."""
    g = _game_at_laboratory()
    experiments.apply_effect(g, "add_aquariums")
    commonplace_idx = RARITY_INDEX["commonplace"]
    assert g.state.dynamic_rarity["aquarium"] == commonplace_idx
    assert g.state.dynamic_rarity["aquarium__experiment"] == commonplace_idx
    before_rarity_rng = g.rng.stream("add_aquariums_rarity").getstate()

    experiments.apply_effect(g, "add_aquariums")

    assert g.rng.stream("add_aquariums_rarity").getstate() == before_rarity_rng, (
        "the second firing's rarity move must consume no RNG"
    )
    assert g.state.dynamic_rarity["aquarium"] == commonplace_idx
    assert g.state.dynamic_rarity["aquarium__experiment"] == commonplace_idx


def test_add_aquariums_later_batches_land_in_commonplace_too():
    """Every firing's copies join the bucket the earlier ones were moved to.

    The rarity move is idempotent, so a second firing returns early without
    moving anything -- if injection used the room's static rarity the later
    batches would sit in Unusual while the first sat in Commonplace, and the
    effect would quietly stop delivering the odds it advertises.
    """
    g = _game_at_laboratory()
    commonplace_idx = RARITY_INDEX["commonplace"]
    exp = g.registry.by_id["aquarium__experiment"]
    gem_deck = g.state.deck(commonplace_idx, not exp.is_free)

    experiments.apply_effect(g, "add_aquariums")
    after_first = gem_deck.order.count(exp.idx)

    experiments.apply_effect(g, "add_aquariums")
    after_second = gem_deck.order.count(exp.idx)

    assert after_second > after_first, (
        f"second batch did not join the commonplace deck "
        f"({after_first} copies after one firing, {after_second} after two)"
    )


def test_add_aquariums_sets_the_day_flag_that_activates_the_condition():
    """state.add_aquariums_active flips from False to True on firing, and
    draft.py's _active_conditions reflects it immediately -- the wiring the
    two priority_draws.json entries key off."""
    g = _game_at_laboratory()
    ctx = DraftContext(g.state, g.registry, g.cfg, g.rng, set(), None)
    assert not g.state.add_aquariums_active
    assert "add_aquariums" not in _active_conditions(ctx)

    experiments.apply_effect(g, "add_aquariums")

    assert g.state.add_aquariums_active
    assert "add_aquariums" in _active_conditions(ctx)


def test_add_aquariums_priority_draws_inactive_before_active_after_firing(monkeypatch):
    """The two add_aquariums priority_draws entries (13%/3%) are skipped --
    consuming no RNG -- while the condition is inactive, and become live once
    the effect has fired. Isolated via a temporary priority_draws swap so the
    three unconditional entries (Patio/Commissary/Classroom) can never
    contaminate the pick once every chance roll is forced to hit."""
    g = _game_at_laboratory()
    monkeypatch.setattr(Rng, "chance", lambda self, label, p: True)  # force every roll to hit
    registry = g.registry
    add_aq_entries = [e for e in registry.priority["priority_draws"]
                      if e.get("condition") == "add_aquariums"]
    assert len(add_aq_entries) == 2
    original = registry.priority["priority_draws"]
    try:
        registry.priority["priority_draws"] = add_aq_entries

        ctx_inactive = DraftContext(g.state, registry, g.cfg, g.rng, set(), None)
        assert _priority_draw(ctx_inactive, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION,
                              set()) is None

        experiments.apply_effect(g, "add_aquariums")
        ctx_active = DraftContext(g.state, registry, g.cfg, g.rng, set(), None)
        picked = _priority_draw(ctx_active, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set())
        assert picked is not None and picked.id == "aquarium"
    finally:
        registry.priority["priority_draws"] = original


def test_add_aquariums_priority_draws_do_not_affect_the_three_existing_entries(monkeypatch):
    """Appending the two new entries after the three existing ones leaves
    their own picks and substreams untouched -- the same guarantee
    test_decks.py::test_priority_draw_skips_entry_with_inactive_condition
    pins for a gated entry spliced in ahead of the real ones, checked here in
    the other direction (gated entries appended at the end)."""
    g = _game_at_laboratory()
    registry = g.registry
    original = registry.priority["priority_draws"]
    trimmed = [e for e in original if e.get("condition") != "add_aquariums"]

    for seed in range(10):
        registry.priority["priority_draws"] = trimmed
        rng_trimmed = Rng(seed)
        ctx_trimmed = DraftContext(GameState(), registry, g.cfg, rng_trimmed, set(), None)
        pick_trimmed = _priority_draw(ctx_trimmed, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION,
                                      set())

        registry.priority["priority_draws"] = original
        rng_full = Rng(seed)
        ctx_full = DraftContext(GameState(), registry, g.cfg, rng_full, set(), None)
        pick_full = _priority_draw(ctx_full, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set())

        full_id = pick_full.id if pick_full else None
        trimmed_id = pick_trimmed.id if pick_trimmed else None
        assert full_id == trimmed_id, (
            f"seed {seed}: appending the inactive add_aquariums entries changed the pick"
        )
    registry.priority["priority_draws"] = original


def test_aquarium_experiment_blocked_without_add_aquariums_active(registry):
    """Without the day flag, aquarium__experiment obeys the ordinary
    one-copy-per-room rule like any other room."""
    aqx = registry.by_id["aquarium__experiment"]
    state = GameState()
    ctx = DraftContext(state, registry, GameConfig(), Rng(0),
                       {"aquarium__experiment"}, None)
    assert not room_draftable(ctx, aqx, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set())


def test_aquarium_experiment_waiver_allows_a_repeat_once_add_aquariums_has_fired(registry):
    """Once state.add_aquariums_active is True, aquarium__experiment can be
    dealt again even though its id is already among placed_ids -- the
    waiver that lets more than the ordinary 2-Aquarium cap reach the grid."""
    aqx = registry.by_id["aquarium__experiment"]
    state = GameState()
    state.add_aquariums_active = True
    ctx = DraftContext(state, registry, GameConfig(), Rng(0),
                       {"aquarium__experiment"}, None)
    assert room_draftable(ctx, aqx, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set())


def test_base_aquarium_still_capped_at_one_even_with_add_aquariums_active(registry):
    """The waiver names aquarium__experiment specifically -- the base Aquarium
    keeps the ordinary one-copy limit regardless of the day flag."""
    aq = registry.by_id["aquarium"]
    state = GameState()
    state.add_aquariums_active = True
    ctx = DraftContext(state, registry, GameConfig(), Rng(0), {"aquarium"}, None)
    assert not room_draftable(ctx, aq, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set())


def test_aquarium_experiment_restricted_cells_still_blocked_with_the_waiver_active(registry):
    """The waiver only touches the one-copy rule -- experiment_aquarium's own
    draft condition (the two Rank-1 cells southward, the two Rank-9 cells
    northward) still blocks aquarium__experiment even while add_aquariums is
    active and placed_ids is empty, so no duplicate-rule interaction is
    masking the restriction."""
    aqx = registry.by_id["aquarium__experiment"]
    state = GameState()
    state.add_aquariums_active = True
    ctx = DraftContext(state, registry, GameConfig(), Rng(0), set(), None)
    assert not room_draftable(ctx, aqx, 1, S, set()), "Rank-1 cell, southward: must be blocked"
    assert not room_draftable(ctx, aqx, 41, N, set()), "Rank-9 cell, northward: must be blocked"
    assert room_draftable(ctx, aqx, _AQUARIUM_TARGET_CELL, _AQUARIUM_DIRECTION, set()), (
        "an ordinary interior cell must remain unrestricted"
    )


def test_add_aquariums_self_refiring_loop_terminates_bounded_by_the_grid():
    """Drives the wiki's own designed loop to exhaustion: an Aquarium is a
    Shop, so with 'shops' configured, placing one re-fires add_aquariums,
    which only mutates deck/rarity state and never calls _place_room --
    so it cannot recurse within a single placement. Placing aquarium__experiment
    at every one of the 43 non-Entrance-Hall, non-Antechamber cells fires the
    trigger once per placement and completes without hanging or erroring,
    pinning that the loop across separate placements is bounded by the finite
    grid, not by anything add_aquariums itself controls."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "shops", "add_aquariums")
    aqx = g.registry.by_id["aquarium__experiment"]
    free_cells = [c for c in range(45) if c not in (ENTRANCE_CELL, ANTECHAMBER_CELL)]
    assert len(free_cells) == 43

    for cell in free_cells:
        g._place_room(aqx, cell, aqx.rotations[0])

    assert g.state.experiment.success_count == len(free_cells)
    assert sum(1 for idx in g.state.grid if idx == aqx.idx) == len(free_cells)
    assert g.state.add_aquariums_active


# ---------------------------------------------------------------------------
# spread_dig_spots: Conference Room branch + the cross_column_exclude gate
# ---------------------------------------------------------------------------

_CONFERENCE_TARGET_CELL = 12  # same interior cell test_add_aquariums's own tests use


def test_spread_dig_spots_adds_a_batch_to_the_conference_room_when_present():
    """Firing with a Conference Room on the estate adds
    CONFERENCE_ROOM_DIG_SPOT_BATCH (3) dig spots to its cell via
    veia_dig_bonus, the same per-cell overlay dig_all already reads."""
    g = _game_at_laboratory()
    _place(g, "conference_room", _CONFERENCE_TARGET_CELL)

    experiments.apply_effect(g, "spread_dig_spots")

    assert g.state.special.veia_dig_bonus[_CONFERENCE_TARGET_CELL] == 3
    assert g.state.special.conference_room_dig_spots == 3


def test_spread_dig_spots_digging_the_conference_room_yields_more_than_its_baseline():
    """The Conference Room's own items.dig_spots is 0 -- with no firing, digging
    it finds nothing; after one firing, three added spots each dig up a
    gold_coin outcome (the shovel table's row 4, forced deterministic), so the
    player actually finds more than the room's zero-spot baseline."""
    g = _game_at_laboratory(cfg=GameConfig(starting_items=frozenset({"shovel"})))
    g.state.pos = _CONFERENCE_TARGET_CELL
    conference_room = g.registry.by_id["conference_room"]
    assert conference_room.items.dig_spots == 0
    _place(g, "conference_room", _CONFERENCE_TARGET_CELL)

    si.dig_all(g, _CONFERENCE_TARGET_CELL)
    assert g.state.coins == 0, "no dig spots yet: the baseline digs up nothing"

    experiments.apply_effect(g, "spread_dig_spots")
    g.rng = _AlwaysIndexRng(0, 4)  # force the shovel table's gold_coin row
    si.dig_all(g, _CONFERENCE_TARGET_CELL)

    assert g.state.coins == 3, "three added spots, one gold coin each"


def test_spread_dig_spots_without_a_conference_room_adds_nothing_and_does_not_crash():
    """With no Conference Room on the estate, firing is a no-op -- the Grounds
    branch (off-grid dig spots) is unbuilt per this effect's own
    meta.blocked_on -- and must not raise."""
    g = _game_at_laboratory()

    experiments.apply_effect(g, "spread_dig_spots")

    assert g.state.special.veia_dig_bonus == {}
    assert g.state.special.conference_room_dig_spots == 0


def test_spread_dig_spots_cap_clamps_the_final_batch_and_then_stops():
    """The 50-spot cap clamps a batch that would overshoot it (48 already
    added -> only 2 more, not 3) and silently no-ops every firing after
    the cap is reached, matching entrance_hall_trunk's own no-op-past-cap
    shape for a capped effect."""
    g = _game_at_laboratory()
    _place(g, "conference_room", _CONFERENCE_TARGET_CELL)
    g.state.special.conference_room_dig_spots = 48

    experiments.apply_effect(g, "spread_dig_spots")
    assert g.state.special.conference_room_dig_spots == 50
    assert g.state.special.veia_dig_bonus[_CONFERENCE_TARGET_CELL] == 2

    experiments.apply_effect(g, "spread_dig_spots")
    assert g.state.special.conference_room_dig_spots == 50, "capped: no further spots"
    assert g.state.special.veia_dig_bonus[_CONFERENCE_TARGET_CELL] == 2


def test_trash_while_digging_and_spread_dig_spots_are_never_offered_together():
    """spread_dig_spots' cross_column_exclude means trash_while_digging
    (trigger) and spread_dig_spots (effect) can never both appear in one
    day's setup offers -- driven across many seeds since whether the
    exclusion actually bites depends on the trigger draw, not a static
    pool difference. Also confirms the exclusion is exercised at all
    (trash_while_digging appears in at least one of the sampled seeds)."""
    saw_trash_while_digging_offered = False
    for seed in range(200):
        g = _game_at_laboratory(seed=seed)
        g.start_setup()
        ex = g.state.experiment
        if "trash_while_digging" in ex.offered_triggers:
            saw_trash_while_digging_offered = True
            assert "spread_dig_spots" not in ex.offered_effects
    assert saw_trash_while_digging_offered, "test seed range never exercised the exclusion"


def test_offered_effect_pool_stays_at_three_when_the_exclusion_is_active():
    """Even on a setup where trash_while_digging is offered (dropping
    spread_dig_spots from the effect sampling pool), start_setup still
    offers exactly 3 effects -- draw_offers' own guarantee that
    availability filtering never shrinks the pool below what it needs to
    sample, exercised specifically on exclusion-active seeds."""
    saw_exclusion_active = False
    for seed in range(200):
        g = _game_at_laboratory(seed=seed)
        g.start_setup()
        ex = g.state.experiment
        assert len(ex.offered_effects) == 3
        if "trash_while_digging" in ex.offered_triggers:
            saw_exclusion_active = True
    assert saw_exclusion_active, "test seed range never exercised the exclusion"


def test_effect_offerable_excludes_spread_dig_spots_when_trash_while_digging_offered():
    """Direct unit check on _effect_offerable's cross_column_exclude branch:
    spread_dig_spots is excluded once trash_while_digging is among the
    offered_triggers passed in, and offerable otherwise."""
    g = _game_at_laboratory()
    effect = g.registry.experiments.effect_by_id["spread_dig_spots"]
    assert experiments._effect_offerable(
        effect, g.cfg, g.state.experiment, ("trash_while_digging", "shops", "apples")
    ) is False
    assert experiments._effect_offerable(
        effect, g.cfg, g.state.experiment, ("shops", "red_room_draft", "apples")
    ) is True


# ---------------------------------------------------------------------------
# Packet triggers with firing sites (still unreachable in play: or_packet
# stays False, so draw_offers can never sample any of these; every test
# below configures the experiment directly via _configure and drives the
# real engine event).
# ---------------------------------------------------------------------------

def _grant_disk(game: Game, disk_id: str) -> None:
    """Add one Upgrade Disk item to ``game``'s inventory."""
    si.grant(game.state, game.registry, disk_id, source="test")


# --------------------------------------------------- rank9_first_entry

def test_rank9_first_entry_fires_on_first_entry_to_a_rank9_room():
    """rank9_first_entry fires the first time a Rank 9 cell (not the
    Antechamber) is entered -- Game._enter's own entered[cell] guard is what
    makes this genuinely "first entry", not a helper re-implementing it."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "rank9_first_entry", "permanent_allowance")
    _place_at(g, "hallway", 40, g.registry.by_id["hallway"].door_mask)  # rank 9, west wing
    _enter_at(g, 40)
    assert g.state.experiment.success_count == 1


def test_rank9_first_entry_fires_for_the_antechamber():
    """"Includes the Antechamber" (meta.notes): entering cell 42 for the first
    time this day fires the trigger like any other Rank 9 room."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "rank9_first_entry", "permanent_allowance")
    assert not g.state.entered[ANTECHAMBER_CELL]
    _enter_at(g, ANTECHAMBER_CELL)
    assert g.state.experiment.success_count == 1


def test_rank9_first_entry_does_not_refire_on_a_second_entry_to_the_same_room():
    """Re-entering an already-entered Rank 9 room never reaches Game._enter's
    body a second time, so success_count cannot advance twice for one room."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "rank9_first_entry", "permanent_allowance")
    _place_at(g, "hallway", 40, g.registry.by_id["hallway"].door_mask)
    _enter_at(g, 40)
    assert g.state.experiment.success_count == 1
    _enter_at(g, 40)
    assert g.state.experiment.success_count == 1


def test_rank9_first_entry_does_not_fire_for_a_rank8_room():
    """A Rank 8 first entry is not Rank 9 and must not fire the trigger."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "rank9_first_entry", "permanent_allowance")
    _place_at(g, "hallway", 35, g.registry.by_id["hallway"].door_mask)  # rank 8
    _enter_at(g, 35)
    assert g.state.experiment.success_count == 0


def test_rank9_first_entry_does_not_fire_for_a_different_configured_trigger():
    """Entering a fresh Rank 9 room while an unrelated trigger is configured
    must not fire rank9_first_entry."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "shops", "permanent_allowance")
    _place_at(g, "hallway", 40, g.registry.by_id["hallway"].door_mask)
    _enter_at(g, 40)
    assert g.state.experiment.success_count == 0


# --------------------------------------------------- fireplace_draft

def test_fireplace_draft_fires_for_a_static_fireplace_room():
    """A room carrying the static has_fireplace flag (the Den) fires on draft."""
    g = _game_at_laboratory()
    _configure(g, "fireplace_draft", "permanent_allowance")
    _place(g, "den", 11)
    assert g.state.experiment.success_count == 1


def test_fireplace_draft_does_not_fire_for_a_room_without_a_fireplace():
    """An ordinary Hallway (no fireplace) drafted while configured must not fire."""
    g = _game_at_laboratory()
    _configure(g, "fireplace_draft", "permanent_allowance")
    _place(g, "hallway", 11)
    assert g.state.experiment.success_count == 0


def test_fireplace_draft_dining_room_fires_in_a_center_column():
    """The Dining Room's fireplace is cell-dependent: centre columns qualify
    (per meta.notes), unlike its static-flag siblings."""
    g = _game_at_laboratory()
    _configure(g, "fireplace_draft", "permanent_allowance")
    _place(g, "dining_room", 21)  # rank 5, column 1 (centre)
    assert g.state.experiment.success_count == 1


def test_fireplace_draft_dining_room_does_not_fire_on_a_wing():
    """Off the centre columns and off Rank 9, the Dining Room's fireplace wall
    is windows instead (meta.notes) -- no fire."""
    g = _game_at_laboratory()
    _configure(g, "fireplace_draft", "permanent_allowance")
    _place(g, "dining_room", 20)  # rank 5, column 0 (west wing)
    assert g.state.experiment.success_count == 0


def test_fireplace_draft_dining_room_fires_on_rank9_even_on_a_wing():
    """Rank 9 is its own alternative qualifier, independent of column
    (meta.notes) -- a wing Dining Room on Rank 9 still has its fireplace."""
    g = _game_at_laboratory()
    _configure(g, "fireplace_draft", "permanent_allowance")
    _place(g, "dining_room", 40)  # rank 9, column 0 (west wing)
    assert g.state.experiment.success_count == 1


# --------------------------------------------------- upgraded_floorplan_draft

def test_upgraded_floorplan_draft_fires_for_an_upgrade_variant():
    """Any record with pool == "upgrade_variant" (variant_of is not None) fires."""
    g = _game_at_laboratory()
    _configure(g, "upgraded_floorplan_draft", "permanent_allowance")
    _place(g, "mail_room__ix89", 11)
    assert g.state.experiment.success_count == 1


def test_upgraded_floorplan_draft_does_not_fire_for_the_base_room():
    """The base (non-upgraded) Bunk Room has variant_of == None and must not
    fire, even though it carries the same counts_as_bedrooms tag as its
    upgrade variants."""
    g = _game_at_laboratory()
    _configure(g, "upgraded_floorplan_draft", "permanent_allowance")
    _place(g, "bunk_room", 11)
    assert g.state.experiment.success_count == 0


def test_upgraded_floorplan_draft_fires_twice_for_an_upgraded_bunk_room():
    """"An upgraded Bunk Room triggers twice" (meta.notes) -- mirrors
    archived_floorplan's own Bunk Room doubling."""
    g = _game_at_laboratory()
    _configure(g, "upgraded_floorplan_draft", "permanent_allowance")
    _place(g, "bunk_room__ix20", 11)
    assert g.state.experiment.success_count == 2


# --------------------------------------------------- tomorrow_room_draft

def test_tomorrow_room_draft_fires_for_a_tomorrow_category_room():
    """A room carrying extra_categories: ["tomorrow"] (the Mail Room) fires."""
    g = _game_at_laboratory()
    _configure(g, "tomorrow_room_draft", "permanent_allowance")
    _place(g, "mail_room", 11)
    assert g.state.experiment.success_count == 1


def test_tomorrow_room_draft_does_not_fire_for_a_non_tomorrow_room():
    """An ordinary Hallway (not a Tomorrow room) drafted while configured
    must not fire."""
    g = _game_at_laboratory()
    _configure(g, "tomorrow_room_draft", "permanent_allowance")
    _place(g, "hallway", 11)
    assert g.state.experiment.success_count == 0


# --------------------------------------------------- antechamber_lever_pull

def test_antechamber_lever_pull_fires_once_per_distinct_lever():
    """Pulling two different Antechamber levers (Weight Room's south, Secret
    Garden's west) fires the trigger once each, for a total of 2."""
    g = Game(GameConfig(antechamber_levers=True,
                        starting_items=frozenset({"power_hammer"})), seed=0)
    _configure(g, "antechamber_lever_pull", "permanent_allowance")

    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)
    assert g.state.experiment.success_count == 1

    secret_garden = g.registry.by_id["secret_garden"]
    _place_at(g, "secret_garden", 41, secret_garden.door_mask)
    _enter_at(g, 41)
    assert g.state.experiment.success_count == 2
    assert g.state.experiment.levers_pulled == {(37, N), (41, E)}


def test_antechamber_lever_pull_does_not_double_count_the_south_lever_via_greenhouse():
    """The Weight Room's south lever and the Greenhouse's Broken Lever both
    open segment (37, N) through entirely independent guards (door state vs.
    machines_used) -- pulling the Weight Room's lever and then installing a
    Broken Lever in the Greenhouse must count as ONE distinct lever, not two,
    proving ExperimentState.levers_pulled (not the door state) is what
    prevents the double count."""
    g = Game(GameConfig(antechamber_levers=True,
                        starting_items=frozenset({"power_hammer", "broken_lever"})), seed=0)
    _configure(g, "antechamber_lever_pull", "permanent_allowance")

    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)
    assert g.state.experiment.success_count == 1

    greenhouse = g.registry.by_id["greenhouse"]
    _place_at(g, "greenhouse", 5, greenhouse.door_mask)
    g.state.pos = 5
    assert si.can_install_lever(g)
    si.install_lever(g)
    assert g.state.experiment.success_count == 1, "same south lever must not double-count"
    assert g.state.experiment.levers_pulled == {(37, N)}


def test_antechamber_lever_pull_fires_for_the_north_lever_via_the_throne_room():
    """The Throne Room's backup north lever routes through Game._open_north_door,
    the same call site the Inner Sanctum's own lever uses -- confirms that
    shared site fires the packet trigger too."""
    g = Game(GameConfig(antechamber_levers=True), seed=0)
    _configure(g, "antechamber_lever_pull", "permanent_allowance")
    throne_room = g.registry.by_id["throne_room"]
    throne_cell = 11  # the north segment is off-grid, so any ordinary cell works
    _place_at(g, "throne_room", throne_cell, throne_room.rotations[0])
    _enter_at(g, throne_cell)
    assert g.state.experiment.success_count == 1
    assert g.state.experiment.levers_pulled == {(ANTECHAMBER_CELL, N)}


def test_antechamber_lever_pull_does_not_fire_for_a_different_configured_trigger():
    """Pulling a lever while an unrelated trigger is configured must not fire
    antechamber_lever_pull."""
    g = Game(GameConfig(antechamber_levers=True,
                        starting_items=frozenset({"power_hammer"})), seed=0)
    _configure(g, "shops", "permanent_allowance")
    _place_at(g, "weight_room", 37, N | S)
    _enter_at(g, 37)
    assert g.state.experiment.success_count == 0


# --------------------------------------------------- terminal_access

def _game_with_two_terminals(seed: int = 1) -> Game:
    """Fresh game with Security at cell 7 and Laboratory at cell 8, player at Security."""
    g = Game(GameConfig(special_items=True), seed=seed)
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, 14)  # E|S|W
    lab = g.registry.by_id["laboratory"]
    g._place_room(lab, 8, lab.rotations[0])
    g.state.pos = 7
    g.state.entered[7] = True
    return g


def test_terminal_access_fires_on_the_first_disk_insert_at_a_terminal():
    """Inserting a disk at a disk-reader room (Security) fires the trigger."""
    g = _game_with_two_terminals()
    _configure(g, "terminal_access", "permanent_allowance")
    _grant_disk(g, "upgrade_disk_vault_304")
    assert g.insert_disk() is True
    assert g.state.experiment.success_count == 1
    assert g.state.experiment.terminals_accessed == {"security"}


def test_terminal_access_does_not_refire_for_a_second_disk_at_the_same_terminal():
    """A second disk inserted at the SAME terminal (Security again) does not
    advance the count -- "first access per terminal" (meta.notes), so this is
    a distinct-set dedup, not a plain counter."""
    g = _game_with_two_terminals()
    _configure(g, "terminal_access", "permanent_allowance")
    _grant_disk(g, "upgrade_disk_vault_304")
    _grant_disk(g, "upgrade_disk_commissary")
    assert g.insert_disk() is True
    assert g.state.experiment.success_count == 1
    g.choose_upgrade(0)
    assert g.insert_disk() is True
    assert g.state.experiment.success_count == 1, "same terminal twice must not double-count"
    assert g.state.experiment.terminals_accessed == {"security"}


def test_terminal_access_fires_again_for_a_different_terminal():
    """Moving to a different disk-reader room (Laboratory) and inserting there
    fires the trigger a second time -- a genuinely different terminal."""
    g = _game_with_two_terminals()
    _configure(g, "terminal_access", "permanent_allowance")
    _grant_disk(g, "upgrade_disk_vault_304")
    _grant_disk(g, "upgrade_disk_commissary")
    assert g.insert_disk() is True
    g.choose_upgrade(0)
    g.state.pos = 8  # Laboratory
    assert g.insert_disk() is True
    assert g.state.experiment.success_count == 2
    assert g.state.experiment.terminals_accessed == {"security", "laboratory"}


def test_terminal_access_does_not_fire_for_a_different_configured_trigger():
    """Inserting a disk while an unrelated trigger is configured must not fire
    terminal_access."""
    g = _game_with_two_terminals()
    _configure(g, "shops", "permanent_allowance")
    _grant_disk(g, "upgrade_disk_vault_304")
    assert g.insert_disk() is True
    assert g.state.experiment.success_count == 0


# ---------------------------------------------------------------------------
# Packet gate: cfg.satellite_dish_unlocked opens the packet pool in draw_offers.
# Hardcoded here (not read off the registry under test) so a regression in
# load_experiments's own implemented filter would fail these too, not just
# agree with itself.
# ---------------------------------------------------------------------------

_IMPLEMENTED_PACKET_TRIGGERS = frozenset({
    "rank9_first_entry", "fireplace_draft", "terminal_access",
    "upgraded_floorplan_draft", "antechamber_lever_pull", "tomorrow_room_draft",
})
_IMPLEMENTED_PACKET_EFFECTS = frozenset({
    "unseal_antechamber_door", "keys_per_30_steps",
    "random_item_then_zero_keys", "half_steps_for_dice",
})
# The two packet triggers and four packet effects that stay implemented=false
# and must never be offered, with the flag either way.
_INERT_PACKET_IDS = frozenset({
    "speed_40_seconds", "map_view",
    "pantry_fruit", "reservoir_water_level", "remove_tunnel_crate",
    "permanent_lockpicking_skill",
})


def test_draw_offers_seed_zero_is_unchanged_by_the_packet_gate():
    """Pins the exact seed-0 base-pool offer with satellite_dish_unlocked at its
    default (False) -- a regression guard for the requirement that opening the
    packet pool must not perturb a draw it does not otherwise touch (verified
    separately across 500 seeds against the pre-gate code; this pins one of
    them so a future change that breaks it fails loud)."""
    g = _game_at_laboratory()
    g.start_setup()
    assert g.state.experiment.offered_triggers == (
        "security_door", "bedrooms_after_second", "red_room_draft")
    assert g.state.experiment.offered_effects == (
        "set_steps", "gold_per_red_room", "add_aquariums")


def test_packet_pool_never_offered_with_flag_unset():
    """Across 300 seeds, satellite_dish_unlocked defaulting to False means no
    offered trigger or effect is ever a packet-pool id -- the packet pool
    stays completely unreachable until the flag is set."""
    for seed in range(300):
        g = _game_at_laboratory(seed=seed, cfg=GameConfig())
        g.start_setup()
        ex = g.state.experiment
        assert not (set(ex.offered_triggers) & _IMPLEMENTED_PACKET_TRIGGERS)
        assert not (set(ex.offered_effects) & _IMPLEMENTED_PACKET_EFFECTS)


def test_packet_pool_is_offered_with_flag_set():
    """Across 300 seeds, satellite_dish_unlocked=True means at least one setup
    offers a packet trigger and at least one offers a packet effect -- proves
    the gate actually opens the pool rather than merely not crashing."""
    saw_packet_trigger = False
    saw_packet_effect = False
    for seed in range(300):
        g = _game_at_laboratory(seed=seed, cfg=GameConfig(satellite_dish_unlocked=True))
        g.start_setup()
        ex = g.state.experiment
        if set(ex.offered_triggers) & _IMPLEMENTED_PACKET_TRIGGERS:
            saw_packet_trigger = True
        if set(ex.offered_effects) & _IMPLEMENTED_PACKET_EFFECTS:
            saw_packet_effect = True
    assert saw_packet_trigger
    assert saw_packet_effect


def test_inert_packet_records_are_never_offered_either_way():
    """Across 300 seeds with the flag both False and True, none of the two
    inert packet triggers or four inert packet effects is ever offered -- the
    load-time implemented filter on packet_trigger_ids/packet_effect_ids, not
    just draw-time luck, is what keeps them out."""
    for unlocked in (False, True):
        for seed in range(300):
            g = _game_at_laboratory(seed=seed, cfg=GameConfig(satellite_dish_unlocked=unlocked))
            g.start_setup()
            ex = g.state.experiment
            assert not (set(ex.offered_triggers) & _INERT_PACKET_IDS)
            assert not (set(ex.offered_effects) & _INERT_PACKET_IDS)


def test_registry_packet_ids_exclude_inert_records():
    """ExperimentsRegistry.packet_trigger_ids/packet_effect_ids -- the tuples
    draw_offers appends once the flag is set -- contain exactly the six
    implemented packet ids and none of the six inert ones, pinning the
    load-time filter draw_offers relies on directly rather than only through
    sampling."""
    reg = Game(GameConfig(), seed=0).registry.experiments
    assert not (set(reg.packet_trigger_ids) & _INERT_PACKET_IDS)
    assert not (set(reg.packet_effect_ids) & _INERT_PACKET_IDS)
    assert set(reg.packet_trigger_ids) == _IMPLEMENTED_PACKET_TRIGGERS
    assert set(reg.packet_effect_ids) == _IMPLEMENTED_PACKET_EFFECTS


def test_packet_trigger_fired_and_packet_effect_chosen_produces_its_outcome():
    """End to end: configure a packet trigger/effect pair (as if drawn from an
    opened pool) and drive the real firing path -- entering the Antechamber
    fires rank9_first_entry, which pays out keys_per_30_steps -- proving the
    packet subsystem is not just drawable but functionally live once reached."""
    g = Game(GameConfig(), seed=0)
    _configure(g, "rank9_first_entry", "keys_per_30_steps")
    g.state.steps = 65
    g.state.keys = 0
    _enter_at(g, ANTECHAMBER_CELL)
    assert g.state.experiment.success_count == 1
    assert g.state.keys == 2  # 65 // 30, floored


def test_mail_room_letter_offered_before_day_11_with_satellite_dish_unlocked():
    """mail_room_letter's day_or_packet_gate now honors or_packet: with
    satellite_dish_unlocked=True, it is offerable even before day 11."""
    g = Game(GameConfig(veteran_mode=False, day=1, satellite_dish_unlocked=True), seed=0)
    effect = g.registry.experiments.effect_by_id["mail_room_letter"]
    assert experiments._effect_offerable(effect, g.cfg, g.state.experiment) is True


def test_mail_room_letter_still_gated_before_day_11_without_satellite_dish_unlocked():
    """Unchanged control: with satellite_dish_unlocked at its default False,
    mail_room_letter is still excluded before day 11 -- confirms the new
    or_packet branch does not accidentally always evaluate True."""
    g = Game(GameConfig(veteran_mode=False, day=1), seed=0)
    effect = g.registry.experiments.effect_by_id["mail_room_letter"]
    assert experiments._effect_offerable(effect, g.cfg, g.state.experiment) is False
