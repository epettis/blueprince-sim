"""Laboratory / Experiments: registry, per-day state, and effect application.

An experiment pairs one trigger with one effect, active for exactly one day,
set up at the Mt. Holly Laboratory terminal: three triggers and three effects
are drawn uniformly from the base pool, the player picks one of each, and the
effect fires every time the trigger's condition is met until the day ends.
Only one experiment can be configured per day; it can be paused and resumed
from the terminal.

Design doc: docs/experiments-design.md. Data: data/experiments.json.

Like special_items.py, the hook functions here take the ``game`` orchestrator
duck-typed (no import of Game) to keep this module free of import cycles:
state.py imports ExperimentState from here, model.py lazily imports the
loader, and this module imports only model/rng-adjacent types.

## Not modelled (this phase)

Nine of the twenty effects stay inert (``implemented: false`` or, for
``keys_per_30_steps``, undrawable — see below): ``spread_dig_spots``,
``add_aquariums`` (base pool); ``pantry_fruit``, ``reservoir_water_level``,
``remove_tunnel_crate``, ``unseal_antechamber_door``,
``permanent_lockpicking_skill``, ``random_item_then_zero_keys``,
``half_steps_for_dice`` (packet pool).
``keys_per_30_steps`` (packet pool) IS implemented mechanically below, but
stays undrawable until the packet subsystem (phases 5-8) is authorised,
since :func:`draw_offers` only samples the base pool.

Two effects carry a ``cap`` and both are now implemented: ``entrance_hall_trunk``
(17, adds a trunk to the Entrance Hall -- see special_items.py's
``_container_kinds_at`` for the per-cell overlay this reads) and
``mail_room_letter`` (16, a pure delivered-count bump; the wiki-described
letter contents are deliberately unmodelled under the assumed-solved
doctrine -- see the id's own ``meta.notes``). An effect's cap is enforced in
:func:`apply_effect`, not :func:`trigger_success`: a capped-out effect still
lets its trigger succeed (``success_count`` advances, any ``steps_lost`` is
still charged) and only the effect itself goes silent, per each id's own
wiki wording ("will no longer have any effect" / "never offered again" --
neither says the trigger stops firing). This is a different shape from a
*trigger's* own cap (``trunks_opened``, ``map_view``), which suppresses the
whole fire including the trigger's ``steps_lost``.

All twelve base triggers are now implemented; the eight packet triggers stay
unimplemented pending the packet subsystem (phases 5-8). ``immediately``
fires once, at setup completion, from
:meth:`Game._maybe_finish_experiment_setup`. Six -- ``shops``, ``gems_spent``,
``bedrooms_after_second``, ``hallway_from_hallway``, ``red_room_draft``,
``archived_floorplan`` -- are all detected by :func:`on_room_drafted`, called
from ``Game._place_room`` on every non-entrance draft. ``archived_floorplan``
gates on the chosen ``DraftOption.archived`` flag threaded through from
``Game.choose`` (it fires on *choosing* an archived option, not its earlier
deal) and fires twice for a Bunk Room (see :func:`_fire_archived_floorplan`).
``trunks_opened`` (capped at 3) fires from
``special_items.open_container`` after a trunk or chest is opened, including a
smash-open; vault boxes, lockers, and the Garage car trunk do not count.
``security_door`` fires from two sites in game.py: drafting through a security
doorway (``_unlock_for_passage``, gated on ``for_draft=True`` -- merely
walking through does not count) and drafting a room whose own door faces an
already-rolled security segment on a neighbor (``_roll_new_segments``,
converting it to open). ``trash_while_digging`` fires from
``special_items.dig_all``'s per-spot loop on a ``junk`` outcome (the six named
trash items plus, since Patch 1.6, Scraps of Paper -- both dig tables fold the
scrap into a second ``junk`` row rather than a distinct kind); ``nothing``
outcomes never count, per the wiki. Because ``dig_all`` digs every remaining
spot at a cell in one call, this trigger can fire many times from a single
``move()`` -- no cap and no cross-call state, so it is a legitimate burst, not
a bug. ``apples`` fires from ``special_items.eat_food``'s per-item loop, once
per apple eaten (``food_id == "apple"``, the one dish id covering all three
visual varieties), after that apple's own steps have already been granted --
so a same-day ``set_steps`` effect lands last, per the wiki, rather than being
overwritten by the apple's steps. A single ``eat_food`` call with ``count`` >
1 (the Secret Garden's Conference Room spread) fires once per apple in the
loop, matching apples being eaten one at a time in the real game.
``drawing_room_drawn`` fires from :func:`on_drawing_room_dealt`, called by a
``room_hook`` on ``ON_HAND_DEALT`` in ``effects/rooms/drawing_room.py`` --
kept out of this module's own dispatch so that a Drawing-Room-id literal
lives in a room module rather than an engine one; ``fire()`` already runs the
hook at all three ON_HAND_DEALT sites (the initial grid deal, the initial
outer deal, and every redraw), so no new call site was needed. A hidden or
archived Drawing Room still counts, per the wiki's plain "drawn" wording.

Two of the twelve base triggers carry a ``day_gate`` availability
(``security_door``, ``drawing_room_drawn``): both are excluded from
:func:`draw_offers`'s sampling pool before day 8 unless ``cfg.veteran_mode``
is set (the default). One of the twelve base effects carries a
``day_or_packet_gate`` availability (``mail_room_letter``): excluded before
day 11 (``or_packet`` is permanently False -- see :func:`_effect_offerable`);
also excluded once its cap is spent, though see that function's docstring
for why this half of the check cannot yet see a prior day's deliveries. No
other availability kind, on either triggers or effects, is enforced yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .grid import neighbor


@dataclass(frozen=True, slots=True)
class ExperimentTrigger:
    id: str  # stable snake_case id, unique across experiments.json
    text: str  # wiki wording, verbatim
    pool: str  # base|packet
    implemented: bool  # False = inert; no firing site wired for this trigger
    magnitude: dict = field(default_factory=dict)  # structured numbers, raw from JSON
    cap: int | None = None  # max successful fires today, or None for unlimited
    availability: dict | None = None  # gate on whether this can be offered, or None
    confidence: str = "wiki"  # data provenance: datamined > wiki > inferred > placeholder


@dataclass(frozen=True, slots=True)
class ExperimentEffect:
    id: str  # stable snake_case id, unique across experiments.json
    text: str  # wiki wording, verbatim
    pool: str  # base|packet
    implemented: bool  # False = inert; apply_effect no-ops for this id
    magnitude: dict = field(default_factory=dict)  # structured numbers, raw from JSON
    cap: int | None = None  # max successful APPLICATIONS today, or None for unlimited
    availability: dict | None = None  # gate on whether this can be offered, or None
    confidence: str = "wiki"  # data provenance: datamined > wiki > inferred > placeholder


@dataclass(frozen=True)
class ExperimentsRegistry:
    triggers: tuple[ExperimentTrigger, ...]  # every trigger, in experiments.json order
    effects: tuple[ExperimentEffect, ...]  # every effect, in experiments.json order
    trigger_by_id: dict[str, ExperimentTrigger]
    effect_by_id: dict[str, ExperimentEffect]
    base_trigger_ids: tuple[str, ...]  # pool == "base", file order
    base_effect_ids: tuple[str, ...]  # pool == "base", file order


def load_experiments(data_dir: Path) -> ExperimentsRegistry:
    """Parse data/experiments.json into the frozen registry."""
    raw = json.loads((Path(data_dir) / "experiments.json").read_text())

    def _trigger(t: dict) -> ExperimentTrigger:
        return ExperimentTrigger(
            id=t["id"],
            text=t["text"],
            pool=t["pool"],
            implemented=bool(t.get("implemented", False)),
            magnitude=t.get("magnitude") or {},
            cap=t.get("cap"),
            availability=t.get("availability"),
            confidence=t.get("meta", {}).get("confidence", "wiki"),
        )

    def _effect(e: dict) -> ExperimentEffect:
        return ExperimentEffect(
            id=e["id"],
            text=e["text"],
            pool=e["pool"],
            implemented=bool(e.get("implemented", False)),
            magnitude=e.get("magnitude") or {},
            cap=e.get("cap"),
            availability=e.get("availability"),
            confidence=e.get("meta", {}).get("confidence", "wiki"),
        )

    triggers = tuple(_trigger(t) for t in raw["triggers"])
    effects = tuple(_effect(e) for e in raw["effects"])
    return ExperimentsRegistry(
        triggers=triggers,
        effects=effects,
        trigger_by_id={t.id: t for t in triggers},
        effect_by_id={e.id: e for e in effects},
        base_trigger_ids=tuple(t.id for t in triggers if t.pool == "base"),
        base_effect_ids=tuple(e.id for e in effects if e.pool == "base"),
    )


@dataclass(slots=True)
class ExperimentState:
    """Mutable per-day Laboratory/Experiments bookkeeping, reset with GameState.

    Per-day only: an experiment "lasts for the day" (wiki), so nothing here is
    seeded from GameConfig or reported by carryover() -- a fresh GameState
    starts with no offers and no configured experiment every day.
    """

    offered_triggers: tuple[str, ...] = ()  # 3 trigger ids offered at setup; () before/after setup
    offered_effects: tuple[str, ...] = ()  # 3 effect ids offered at setup; () before/after setup
    trigger_id: str | None = None  # chosen trigger for today's experiment; None = not configured
    effect_id: str | None = None  # chosen effect for today's experiment; None = not configured
    paused: bool = False  # True = configured but the effect is not currently firing
    success_count: int = 0  # times the trigger has succeeded (and apply_effect was called) today
    # Bedroom-equivalents drafted today (Bunk Room counts as 2), tracked from the
    # day's first Bedroom draft regardless of whether/when an experiment is
    # configured -- bedrooms_after_second's threshold counts all of today's
    # Bedrooms, not just ones drafted after the trigger became active.
    bedroom_draft_count: int = 0
    # mail_room_letter deliveries actually applied today (not counted past its
    # cap): distinct from success_count, which also counts a trigger fire whose
    # effect no-opped past its own cap. Day-scoped only -- see
    # _effect_offerable's docstring for why this can't yet enforce the wiki's
    # cross-day "16 ever, never offered again" rule.
    letters_delivered: int = 0

    @property
    def configured(self) -> bool:
        """True once both a trigger and an effect have been chosen for today."""
        return self.trigger_id is not None and self.effect_id is not None

    @property
    def active(self) -> bool:
        """True when the experiment is configured and not paused -- the firing gate."""
        return self.configured and not self.paused


# ------------------------------------------------------------------ setup draw

def _trigger_offerable(trig: ExperimentTrigger, cfg) -> bool:
    """True unless a ``day_gate`` availability record blocks this trigger today.

    Only the ``day_gate`` kind is enforced (``security_door`` and
    ``drawing_room_drawn``, both gated at day 8 with a veteran-mode bypass);
    any other availability kind, or none at all, is always offerable -- the
    remaining kinds (``room_drafted_gate``, ``item_obtained_gate``) stay
    unbuilt this phase, per the module docstring.
    """
    gate = trig.availability
    if gate is None or gate.get("kind") != "day_gate":
        return True
    if cfg.veteran_mode and gate.get("veteran_bypass", False):
        return True
    return cfg.day >= gate.get("day", 0)


def _effect_offerable(effect: ExperimentEffect, cfg, ex: ExperimentState) -> bool:
    """True unless an availability rule or a spent cap blocks this effect today.

    Only ``day_or_packet_gate`` (mail_room_letter's day-11 gate) is enforced;
    any other availability kind, or none, is always offerable -- entrance_hall_
    trunk carries no availability record at all (it stays offerable forever
    and simply no-ops past its cap in :func:`apply_effect`; the wiki never
    says it stops being offered, unlike mail_room_letter's explicit "never
    offered again"). ``or_packet`` is permanently False here: the packet
    subsystem (phases 5-8) is not authorised, so no custom experiment packet
    can ever exist to satisfy it.

    mail_room_letter is also excluded once its cap has already been reached
    -- but see ExperimentState.letters_delivered's own comment: that counter
    is day-scoped, and draw_offers only ever runs once per day on fresh
    state, so this half of the check cannot yet observe a PRIOR day's
    deliveries. It is still applied (rather than left out entirely) so the
    mechanism is correct and testable in isolation, ready for the day it is
    seeded from a persistent cross-day total.
    """
    gate = effect.availability
    if gate is not None and gate.get("kind") == "day_or_packet_gate":
        or_packet = False  # packet subsystem (phases 5-8) unauthorised; never satisfiable
        if not (cfg.day >= gate.get("day", 0) or or_packet):
            return False
    if effect.id == "mail_room_letter" and effect.cap is not None:
        if ex.letters_delivered >= effect.cap:
            return False
    return True


def draw_offers(registry, rng, cfg, state) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Draw 3 triggers and 3 effects uniformly from the base pool.

    Sampled without replacement via named RNG substreams (seed-deterministic),
    then restored to the registry's own file order -- the same "sample, then
    sort back to canonical order" shape as upgrades.py's Cloister variant draw
    -- so the offered order is stable and readable rather than reflecting
    sample order.

    Only the base pool is ever drawn: the packet pool (Satellite Dish, phases
    5-8) is out of scope, so its 8 triggers and 8 effects are never offered.
    Triggers gated by a ``day_gate`` availability (see :func:`_trigger_offerable`)
    and effects gated by their own availability/cap (see :func:`_effect_offerable`)
    are dropped from their respective sampling pools before the draw. Neither
    the 2 day-gated triggers nor the single gated/cappable effect (base pool
    has only mail_room_letter) can ever shrink either pool below the 3 the
    draw needs.
    """
    ex = registry.experiments
    trig_pool = [t for t in ex.base_trigger_ids if _trigger_offerable(ex.trigger_by_id[t], cfg)]
    assert len(trig_pool) >= 3, "day_gate filtering must never shrink the trigger pool below 3"
    eff_pool = [e for e in ex.base_effect_ids
                if _effect_offerable(ex.effect_by_id[e], cfg, state.experiment)]
    assert len(eff_pool) >= 3, "effect availability filtering must never shrink the pool below 3"
    sampled_triggers = rng.stream("experiment_triggers").sample(trig_pool, 3)
    sampled_effects = rng.stream("experiment_effects").sample(eff_pool, 3)
    sampled_triggers.sort(key=trig_pool.index)
    sampled_effects.sort(key=eff_pool.index)
    return tuple(sampled_triggers), tuple(sampled_effects)


# ------------------------------------------------------------------ firing

def trigger_success(game) -> bool:
    """Call this when the active trigger's condition has been met.

    Returns True and applies the chosen effect (incrementing success_count)
    when the experiment is configured and not paused, and the trigger has not
    already fired its ``cap`` (e.g. trunks_opened's "next 3 times"); returns
    False and does nothing otherwise (no experiment configured, paused, or
    capped out). This is the single fire site every trigger's own detection
    hook is meant to call: "immediately" (fired once, at setup completion,
    from Game._maybe_finish_experiment_setup), the five draft-site triggers
    detected by :func:`on_room_drafted`, trunks_opened (special_items.py's
    open_container), and security_door (game.py's _unlock_for_passage and
    _roll_new_segments) all route through here; the remaining base and packet
    triggers still need their own detection hooks wired in.

    A capped-out fire does not charge its own ``steps_lost`` either -- the cap
    check sits before both. Because success_count only ever increments here,
    and this function returns early while paused, a cap counts *fires*, not
    qualifying events: pausing an experiment preserves its remaining charges
    rather than burning them on suppressed events.

    A trigger carrying ``steps_lost`` in its magnitude (red_room_draft, and
    map_view in the packet pool) takes that loss on top of whichever effect
    the player chose, floored at its ``floor``. The loss is applied here,
    after the active gate, so a paused experiment suppresses it the same way
    it suppresses the effect -- and before apply_effect, so an effect that
    writes steps outright (set_steps) lands last.
    """
    ex = game.state.experiment
    if not ex.active:
        return False
    trig = game.registry.experiments.trigger_by_id.get(ex.trigger_id)
    if trig is not None and trig.cap is not None and ex.success_count >= trig.cap:
        return False
    ex.success_count += 1
    steps_lost = trig.magnitude.get("steps_lost", 0) if trig is not None else 0
    if steps_lost:
        game.state.steps = max(trig.magnitude.get("floor", 0), game.state.steps - steps_lost)
    apply_effect(game, ex.effect_id)
    return True


# ------------------------------------------------------------------ draft-site triggers

def on_room_drafted(game, room, cell: int, entry_dir: int | None, gem_cost: int,
                    archived: bool = False) -> None:
    """Detect and fire the six placement-site triggers for a freshly-placed room.

    Called from Game._place_room after the room is written to the grid and
    before its ON_PLACE hook fires, for every non-entrance draft (never for
    the day-start Entrance Hall, never for outer-room drafts). Only the
    currently configured trigger's own branch can call trigger_success --
    drafting a Shop while "gems_spent" is configured must not fire it.
    ``gem_cost`` is the nominal gem cost paid (0 if free, or waived by a
    Stopwatch, which does not count as spending). ``archived`` is the chosen
    DraftOption's own ``archived`` flag -- an outer-room draft never sets it
    (draft.py's Archives pass only ever touches a grid hand), so that path
    (which does not route through this function at all) can never fire
    archived_floorplan.
    """
    ex = game.state.experiment
    match ex.trigger_id:
        case "shops" if room.is_category("shop"):
            trigger_success(game)
        case "red_room_draft" if room.is_category("red"):
            trigger_success(game)
        case "hallway_from_hallway" if room.is_category("hallway"):
            if _drafted_from_hallway(game, cell, entry_dir):
                trigger_success(game)
        case "gems_spent" if gem_cost >= 2 and not game.hovel_placed:
            trigger_success(game)
        case "archived_floorplan" if archived:
            _fire_archived_floorplan(game, room)
    if room.is_category("bedroom"):
        _count_bedroom_draft(game, room, ex.trigger_id)


def _fire_archived_floorplan(game, room) -> None:
    """Fire archived_floorplan once, or twice if ``room`` is a Bunk Room.

    Reads the same "counts_as_bedrooms" tag/``amount`` param
    :func:`_count_bedroom_draft` reads for bedrooms_after_second, rather than
    hard-coding a Bunk Room id, so the two agree by construction: "If the
    archived floorplan is a Bunk Room, it triggers twice" (wiki).
    """
    bed_effect = next((e for e in room.effects if e.tag == "counts_as_bedrooms"), None)
    times = bed_effect.param("amount", 1) if bed_effect is not None else 1
    for _ in range(times):
        trigger_success(game)


def on_drawing_room_dealt(game) -> None:
    """Fire drawing_room_drawn: the Drawing Room was just dealt into a hand.

    Called by effects/rooms/drawing_room.py's ``ON_HAND_DEALT`` room_hook,
    which ``effects.fire`` already invokes at all three ON_HAND_DEALT sites
    (open_door's initial deal, open_outer_draft's initial deal, and every
    redraw) -- no new call site is needed. The outer pool can never contain
    the Drawing Room, so that site is a permanent no-op. A hidden or
    archived Drawing Room still counts: the wiki's "drawn" wording draws no
    distinction for concealment, so this does not read opt.hidden/archived.
    """
    if game.state.experiment.trigger_id == "drawing_room_drawn":
        trigger_success(game)


def _drafted_from_hallway(game, cell: int, entry_dir: int | None) -> bool:
    """True when the room at ``cell`` was drafted through a doorway on a Hallway.

    ``entry_dir`` is the direction the player would move to reach ``cell``, so
    the from-room sits at its opposite neighbor -- the same derivation
    Game._roll_new_segments and special_items.gem_cost_modifier's Hall Pass
    check use, rather than threading PendingDraft.from_cell separately.
    """
    if entry_dir is None:
        return False
    from_cell = neighbor(cell, entry_dir)
    if from_cell < 0:
        return False
    from_idx = game.state.grid[from_cell]
    return from_idx >= 0 and game.registry.rooms[from_idx].is_category("hallway")


def _count_bedroom_draft(game, room, trigger_id: str | None) -> None:
    """Advance today's bedroom-equivalent counter and fire bedrooms_after_second.

    The counter advances for every Bedroom drafted today regardless of
    ``trigger_id``: all of today's Bedrooms count toward the two-Bedroom
    threshold, including ones drafted before the trigger was configured; only
    the fire count is gated on the trigger actually being configured. Firing
    ``crossed`` times reproduces the Bunk Room worked example: counter 1 -> 3
    crosses the "after your second" line once, not twice.
    """
    ex = game.state.experiment
    bed_effect = next((e for e in room.effects if e.tag == "counts_as_bedrooms"), None)
    amount = bed_effect.param("amount", 1) if bed_effect is not None else 1
    before, after = ex.bedroom_draft_count, ex.bedroom_draft_count + amount
    ex.bedroom_draft_count = after
    if trigger_id != "bedrooms_after_second":
        return
    crossed = max(0, after - 2) - max(0, before - 2)
    for _ in range(crossed):
        trigger_success(game)


def _effect_apply_count(state, effect_id: str) -> int:
    """Times ``effect_id`` has already applied (not no-opped) today, for cap checks.

    entrance_hall_trunk counts against a dedicated Entrance-Hall counter
    (SpecialItemsState.entrance_hall_trunks) rather than a generic experiment
    counter, because it is designed to be shared with The Twins constellation
    -- an unrelated future trigger for the same 17-trunk limit (wiki: "identical
    to triggering this effect twice") -- so it must not live on ExperimentState,
    which is specific to this one experiment record. mail_room_letter counts
    against ExperimentState.letters_delivered. Neither is success_count, which
    counts trigger fires and keeps advancing even once an effect caps out.
    """
    match effect_id:
        case "entrance_hall_trunk":
            return state.special.entrance_hall_trunks
        case "mail_room_letter":
            return state.experiment.letters_delivered
        case _:
            return 0


def apply_effect(game, effect_id: str) -> None:
    """Apply one successful trigger's chosen effect.

    No-ops for any effect_id whose record is not ``implemented`` (the nine
    inert effects listed in the module docstring) -- reachable only if a
    caller sets state.experiment.effect_id directly, since draw_offers only
    samples the base pool and every base effect marked "implemented: true" is
    already one of the eleven this module implements.

    Also no-ops, without touching state, once a ``cap``-carrying effect has
    already applied that many times today (see :func:`_effect_apply_count`)
    -- entrance_hall_trunk's 17th trunk, mail_room_letter's 16th letter. This
    is deliberately NOT trigger_success's early return: the trigger that
    called us has already succeeded (success_count advanced, any steps_lost
    was already charged), and only the effect itself goes silent, matching
    the wiki's own wording for both ("will no longer have any effect" /
    "never offered again" -- neither says the trigger stops firing).
    """
    st = game.state
    registry = game.registry
    effect = registry.experiments.effect_by_id.get(effect_id)
    if effect is None or not effect.implemented:
        return
    if effect.cap is not None and _effect_apply_count(st, effect_id) >= effect.cap:
        return
    match effect_id:
        case "gain_key_gem_or_die":
            _apply_gain_key_gem_or_die(game, effect)
        case "set_steps":
            st.steps = effect.magnitude.get("steps", 40)
        case "entrance_hall_trunk":
            st.special.entrance_hall_trunks += 1
        case "mail_room_letter":
            st.experiment.letters_delivered += 1
        case "set_dice":
            st.dice = effect.magnitude.get("dice", 2)
        case "steps_for_gold":
            st.steps = max(0, st.steps - effect.magnitude.get("steps_lost", 10))
            st.coins += effect.magnitude.get("coins_gained", 20)
        case "keys_per_hallway_pair":
            n_hallways = sum(
                1 for idx in st.grid if idx >= 0 and registry.rooms[idx].is_category("hallway")
            )
            per = effect.magnitude.get("per_hallways", 2)
            st.keys += (n_hallways // per) * effect.magnitude.get("keys", 1)
        case "gold_per_red_room":
            n_red = sum(
                1 for idx in st.grid if idx >= 0 and registry.rooms[idx].is_category("red")
            )
            st.coins += n_red * effect.magnitude.get("coins_per_red_room", 3)
        case "permanent_allowance":
            st.allowance += effect.magnitude.get("allowance_gold", 1)
        case "gain_star":
            st.stars += 1
        case "keys_per_30_steps":
            per = effect.magnitude.get("steps_per_key", 30)
            st.keys += st.steps // per
        case _:
            pass  # inert effect id; nothing to apply


def _apply_gain_key_gem_or_die(game, effect: ExperimentEffect) -> None:
    """Roll one of key/gem/die per the record's magnitude.split weights.

    The split is not published; experiments.json carries it as an inferred
    uniform third each, and that record's meta.notes records the gap.
    """
    options = effect.magnitude.get("options", ["key", "gem", "die"])
    weights = tuple(effect.magnitude.get("split") or [1] * len(options))
    idx = game.rng.roll_weighted("experiment_gain_key_gem_die", weights)
    kind = options[idx]
    st = game.state
    match kind:
        case "key":
            st.keys += 1
        case "gem":
            st.gems += 1
        case "die":
            st.dice += 1
