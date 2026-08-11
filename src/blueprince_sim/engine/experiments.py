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

Twelve of the twenty effects stay inert (``implemented: false`` or, for
``keys_per_30_steps``, undrawable — see below): ``entrance_hall_trunk``,
``gain_star``, ``spread_dig_spots``, ``add_aquariums``, ``mail_room_letter``
(base pool); ``pantry_fruit``, ``reservoir_water_level``,
``remove_tunnel_crate``, ``unseal_antechamber_door``,
``permanent_lockpicking_skill``, ``random_item_then_zero_keys``,
``half_steps_for_dice`` (packet pool). ``keys_per_30_steps`` (packet pool) IS
implemented mechanically below, but stays undrawable until the packet
subsystem (phases 5-8) is authorised, since :func:`draw_offers` only samples
the base pool.

Every trigger except ``immediately`` stays unimplemented: the eleven other
base triggers and all eight packet triggers need firing sites (draft hooks,
move hooks, dig hooks, ...) that are a later phase's work. ``immediately``
needs no firing site — it fires exactly once, when the experiment starts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExperimentTrigger:
    id: str  # stable snake_case id, unique across experiments.json
    text: str  # wiki wording, verbatim
    pool: str  # base|packet
    implemented: bool  # False = inert; no firing site wired for this trigger
    magnitude: dict = field(default_factory=dict)  # structured numbers, raw from JSON
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

    @property
    def configured(self) -> bool:
        """True once both a trigger and an effect have been chosen for today."""
        return self.trigger_id is not None and self.effect_id is not None

    @property
    def active(self) -> bool:
        """True when the experiment is configured and not paused -- the firing gate."""
        return self.configured and not self.paused


# ------------------------------------------------------------------ setup draw

def draw_offers(registry, rng) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Draw 3 triggers and 3 effects uniformly from the base pool.

    Sampled without replacement via named RNG substreams (seed-deterministic),
    then restored to the registry's own file order -- the same "sample, then
    sort back to canonical order" shape as upgrades.py's Cloister variant draw
    -- so the offered order is stable and readable rather than reflecting
    sample order.

    Only the base pool is ever drawn: the packet pool (Satellite Dish, phases
    5-8) is out of scope, so its 8 triggers and 8 effects are never offered.
    """
    ex = registry.experiments
    trig_pool = list(ex.base_trigger_ids)
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
    when the experiment is configured and not paused; returns False and does
    nothing otherwise (no experiment configured, or paused). This is the
    single fire site every trigger's own detection hook is meant to call --
    today only the "immediately" trigger (fired once, at setup completion in
    Game._maybe_finish_experiment_setup) actually calls it; later phases wire
    the other eleven base triggers' own detection hooks (draft, move, dig,
    apple-eat, ...) through this same function.
    """
    ex = game.state.experiment
    if not ex.active:
        return False
    ex.success_count += 1
    apply_effect(game, ex.effect_id)
    return True


def apply_effect(game, effect_id: str) -> None:
    """Apply one successful trigger's chosen effect.

    No-ops for any effect_id whose record is not ``implemented`` (the twelve
    inert effects listed in the module docstring) -- reachable only if a
    caller sets state.experiment.effect_id directly, since draw_offers only
    samples the base pool and every base effect below "implemented: true" is
    already one of the eight this phase implements.
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
