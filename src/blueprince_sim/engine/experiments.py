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

Eleven of the twenty effects stay inert (``implemented: false`` or, for
``keys_per_30_steps``, undrawable — see below): ``entrance_hall_trunk``,
``spread_dig_spots``, ``add_aquariums``, ``mail_room_letter`` (base pool);
``pantry_fruit``, ``reservoir_water_level``, ``remove_tunnel_crate``,
``unseal_antechamber_door``, ``permanent_lockpicking_skill``,
``random_item_then_zero_keys``, ``half_steps_for_dice`` (packet pool).
``keys_per_30_steps`` (packet pool) IS implemented mechanically below, but
stays undrawable until the packet subsystem (phases 5-8) is authorised,
since :func:`draw_offers` only samples the base pool.

Two of the twelve base triggers stay unimplemented: ``archived_floorplan``
and ``drawing_room_drawn`` need firing sites (an Archives-drafted gate, the
Drawing Room's own draw) that are later work, same as all eight packet
triggers. ``immediately`` fires once, at setup completion, from
:meth:`Game._maybe_finish_experiment_setup`. Five -- ``shops``, ``gems_spent``,
``bedrooms_after_second``, ``hallway_from_hallway``, ``red_room_draft`` -- are
all detected by :func:`on_room_drafted`, called from ``Game._place_room`` on
every non-entrance draft. ``trunks_opened`` (capped at 3) fires from
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

Two of the twelve base triggers carry a ``day_gate`` availability
(``security_door``, ``drawing_room_drawn``): both are excluded from
:func:`draw_offers`'s sampling pool before day 8 unless ``cfg.veteran_mode``
is set (the default). No other availability kind is enforced yet.
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
    success_count: int = 0  # times the trigger has succeeded (and the effect applied) today
    # Bedroom-equivalents drafted today (Bunk Room counts as 2), tracked from the
    # day's first Bedroom draft regardless of whether/when an experiment is
    # configured -- bedrooms_after_second's threshold counts all of today's
    # Bedrooms, not just ones drafted after the trigger became active.
    bedroom_draft_count: int = 0

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


def draw_offers(registry, rng, cfg) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Draw 3 triggers and 3 effects uniformly from the base pool.

    Sampled without replacement via named RNG substreams (seed-deterministic),
    then restored to the registry's own file order -- the same "sample, then
    sort back to canonical order" shape as upgrades.py's Cloister variant draw
    -- so the offered order is stable and readable rather than reflecting
    sample order.

    Only the base pool is ever drawn: the packet pool (Satellite Dish, phases
    5-8) is out of scope, so its 8 triggers and 8 effects are never offered.
    Triggers gated by a ``day_gate`` availability (see :func:`_trigger_offerable`)
    are dropped from the sampling pool before the draw; effects carry no such
    filter yet. The base trigger pool (12) has only 2 day-gated members, so
    this can never shrink the pool below the 3 the draw needs.
    """
    ex = registry.experiments
    trig_pool = [t for t in ex.base_trigger_ids if _trigger_offerable(ex.trigger_by_id[t], cfg)]
    assert len(trig_pool) >= 3, "day_gate filtering must never shrink the trigger pool below 3"
    eff_pool = list(ex.base_effect_ids)
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

def on_room_drafted(game, room, cell: int, entry_dir: int | None, gem_cost: int) -> None:
    """Detect and fire the five placement-site triggers for a freshly-placed room.

    Called from Game._place_room after the room is written to the grid and
    before its ON_PLACE hook fires, for every non-entrance draft (never for
    the day-start Entrance Hall, never for outer-room drafts). Only the
    currently configured trigger's own branch can call trigger_success --
    drafting a Shop while "gems_spent" is configured must not fire it.
    ``gem_cost`` is the nominal gem cost paid (0 if free, or waived by a
    Stopwatch, which does not count as spending).
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
    if room.is_category("bedroom"):
        _count_bedroom_draft(game, room, ex.trigger_id)


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


def apply_effect(game, effect_id: str) -> None:
    """Apply one successful trigger's chosen effect.

    No-ops for any effect_id whose record is not ``implemented`` (the eleven
    inert effects listed in the module docstring) -- reachable only if a
    caller sets state.experiment.effect_id directly, since draw_offers only
    samples the base pool and every base effect marked "implemented: true" is
    already one of the nine this module implements.
    """
    st = game.state
    registry = game.registry
    effect = registry.experiments.effect_by_id.get(effect_id)
    if effect is None or not effect.implemented:
        return
    match effect_id:
        case "gain_key_gem_or_die":
            _apply_gain_key_gem_or_die(game, effect)
        case "set_steps":
            st.steps = effect.magnitude.get("steps", 40)
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
