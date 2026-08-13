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

Four of the twenty effects stay inert (``implemented: false``), all packet
pool: ``pantry_fruit`` (needs a Pantry-stocking mechanic this simulator does
not have), ``reservoir_water_level`` (the Reservoir is an area node only, not
a room in rooms.json), ``remove_tunnel_crate`` (the Crate Tunnel -- owner
ruled out of scope), ``permanent_lockpicking_skill`` (needs a lockpicking
stat that does not exist, and its own magnitude is unpublished besides).
``keys_per_30_steps``, ``unseal_antechamber_door``, ``random_item_then_zero_keys``,
and ``half_steps_for_dice`` (all packet pool) ARE implemented mechanically
below -- see :func:`_apply_unseal_antechamber_door`,
:func:`_apply_random_item_then_zero_keys`, and
:func:`_apply_half_steps_for_dice` for the latter three -- but stay
undrawable until the packet subsystem (phases 5-8) is authorised, since
:func:`draw_offers` only samples the base pool. All twelve base effects are
now implemented.

``add_aquariums`` (the last base effect, uncapped) injects ``aquariums_added``
(3) copies of the ``aquarium__experiment`` floorplan into the live decks via
``decks.inject_rooms_undealt``, moves both the base Aquarium and that
experiment copy to the Commonplace bucket via ``decks.set_dynamic_rarity``
(idempotent past the first firing, per that function's own contract), and
sets ``state.add_aquariums_active`` -- see :func:`_apply_add_aquariums` for
why the injection must run before the rarity move. The flag does two more
things outside this module: it activates two ``condition``-gated
priority_draws.json entries (13% and 3%, applying independently -- 15.61%
combined, since :func:`_priority_draw` already rolls every entry on its own)
read by draft.py's ``_active_conditions``, and it waives the one-copy-per-room
rule for ``aquarium__experiment`` (only that id, never the base Aquarium) in
draft.py's ``room_draftable``, since all three (and every later) injected
copy share that single id. An Aquarium is a Shop, Red, Hallway and Bedroom
room at once (``extra_categories``), so drafting one while any of those four
triggers is configured can re-fire this effect -- ``Game._place_room``'s own
comment documents why that cannot recurse.

``spread_dig_spots`` only builds the wiki's Conference Room branch: with a
Conference Room on the estate, each firing adds dig spots to its cell via
its record's ``magnitude.spots_per_trigger_usual`` (3, the wiki's usual
batch; the 2/3/4 distribution itself is unpublished and not modelled) on top
of ``SpecialItemsState.veia_dig_bonus``, up to
``magnitude.conference_room_spot_cap`` (50, clamping the final batch). Without
a Conference Room this is a no-op: the Grounds branch (off-grid dig spots
starting outside the Entrance Hall) needs a dig-spot concept this simulator
does not have and is deliberately not built -- see
:func:`_apply_spread_dig_spots` and the id's own ``meta.blocked_on``. This
effect's ``cross_column_exclude`` availability (never offered alongside the
``trash_while_digging`` trigger) is enforced in :func:`_effect_offerable`,
which is why :func:`draw_offers` must sample triggers before filtering the
effect pool.

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

All twelve base triggers are now implemented. Of the eight packet triggers,
six are now wired: ``rank9_first_entry``, ``upgraded_floorplan_draft``,
``tomorrow_room_draft``, ``antechamber_lever_pull``, ``fireplace_draft``, and
``terminal_access`` (see each's own section below). ``speed_40_seconds`` and
``map_view`` stay permanently unimplemented -- this simulator has no wall
clock and no interactive map, so neither condition can ever be observed,
regardless of the packet subsystem's own phase. None of the eight packet
triggers is reachable in play yet even though six now have firing sites: the
packet pool is still never sampled by :func:`draw_offers` (``or_packet``
stays hardcoded False in :func:`_effect_offerable`), so wiring the firing
sites is dead code today, ready for the day a later PR flips that gate.
``immediately`` fires once, at setup completion, from
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

Six of the eight packet triggers now have firing sites (still unreachable in
play -- see above). ``rank9_first_entry`` fires from :func:`on_room_entered`,
called from ``Game._enter`` right after its own ``entered[cell]`` guard
confirms this is the cell's first entry today; a Rank 9 room (including the
Antechamber) entered before the experiment was configured never reaches this
call site a second time, which is exactly the wiki's "prior visits ... do not
count." ``upgraded_floorplan_draft`` and ``tomorrow_room_draft`` are detected
by :func:`on_room_drafted` alongside the six base draft-site triggers:
the former on ``room.variant_of is not None`` (every ``pool ==
"upgrade_variant"`` record carries one, and only those records do), firing
twice for an upgraded Bunk Room via :func:`_fire_upgraded_floorplan_draft`
(mirrors :func:`_fire_archived_floorplan`'s own ``counts_as_bedrooms`` read);
the latter on ``room.is_category("tomorrow")`` (the 12 records carrying
``extra_categories: ["tomorrow"]``). ``fireplace_draft`` is also detected by
:func:`on_room_drafted`, via :func:`_room_has_fireplace`: six of the seven
fireplace rooms read straight off ``Room.has_fireplace``; the Dining Room's
case is decided against the cell it lands on (centre columns or Rank 9)
instead, duplicating ``effects/rooms/cloister.py``'s
``_dining_room_has_fireplace`` rather than importing it, since that would
cycle back through ``effects.rooms.drawing_room``'s own import of this
module. ``antechamber_lever_pull`` fires from :func:`on_lever_pulled`, called
from every site that actually opens one of the Antechamber's four sealed
segments as a lever pull -- ``Game._open_north_door`` (shared by the Inner
Sanctum's main lever and the Throne Room's backup lever), ``great_hall.
pull_east_lever``, ``secret_garden.pull_west_lever``, ``weight_room.
pull_south_lever``, and ``special_items.install_lever``'s Greenhouse
``antechamber_lever`` branch, which targets the same south segment as the
Weight Room's own lever through a wholly separate guard (``machines_used``,
not door state) -- so ``ExperimentState.levers_pulled`` (a per-day distinct
segment set, the same shape as ``GameState.areas_visited``) is what actually
keeps a Weight-Room-then-Greenhouse day from double-counting the south
lever, not any incidental one-shot behaviour of the door state.
``terminal_access`` fires from :func:`on_terminal_accessed`, called from
``Game.insert_disk`` after a disk is actually inserted (not on a failed
insert with no selectable slot): this is the only discrete "operate a
terminal" action modelled, shared by every ``disk_reader`` room (Security,
Laboratory, Office, Shelter); Blackbridge Grotto's off-grid 5th reader has no
room record and can never fire this. ``ExperimentState.terminals_accessed``
(room ids, per-day distinct set) is the dedup, since a player can insert
several disks at the same terminal in one day.

Two of the twelve base triggers carry a ``day_gate`` availability
(``security_door``, ``drawing_room_drawn``): both are excluded from
:func:`draw_offers`'s sampling pool before day 8 unless ``cfg.veteran_mode``
is set (the default). One of the twelve base effects carries a
``day_or_packet_gate`` availability (``mail_room_letter``): excluded before
day 11 (``or_packet`` is permanently False -- see :func:`_effect_offerable`);
also excluded once its cap is spent, though see that function's docstring
for why this half of the check cannot yet see a prior day's deliveries.
Another base effect carries a ``cross_column_exclude`` availability
(``spread_dig_spots``): excluded whenever ``trash_while_digging`` is among
the 3 triggers offered that same setup (not merely eligible to be offered --
see :func:`_effect_offerable`). No other availability kind, on either
triggers or effects, is enforced yet.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .grid import E, N, W, is_center_column, neighbor, rank_of
from .model import RARITY_INDEX

# Aquarium ids the add_aquariums effect touches. model.py's top-level import
# is cycle-safe (it does not import this module); decks.py is NOT imported at
# module scope because decks -> state -> experiments would cycle, so
# _apply_add_aquariums imports it lazily instead.
AQUARIUM_BASE_ID = "aquarium"
AQUARIUM_EXPERIMENT_ID = "aquarium__experiment"

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
    # Antechamber lever segments (cell, direction) already counted toward
    # antechamber_lever_pull today -- a per-day distinct set, the same shape
    # as GameState.areas_visited, since a lever can be reached by more than
    # one call site (see on_lever_pulled's own docstring for the Weight
    # Room / Greenhouse case this specifically guards against).
    levers_pulled: set[tuple[int, int]] = field(default_factory=set)
    # Upgrade Disk terminal room ids already counted toward terminal_access
    # today -- a per-day distinct set; a player can insert several disks at
    # the same terminal, so this is not a plain counter (see
    # on_terminal_accessed).
    terminals_accessed: set[str] = field(default_factory=set)

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


def _effect_offerable(effect: ExperimentEffect, cfg, ex: ExperimentState,
                      offered_triggers: tuple[str, ...] = ()) -> bool:
    """True unless an availability rule or a spent cap blocks this effect today.

    ``day_or_packet_gate`` (mail_room_letter's day-11 gate) and
    ``cross_column_exclude`` (spread_dig_spots vs. trash_while_digging) are
    enforced; any other availability kind, or none, is always offerable --
    entrance_hall_trunk carries no availability record at all (it stays
    offerable forever and simply no-ops past its cap in :func:`apply_effect`;
    the wiki never says it stops being offered, unlike mail_room_letter's
    explicit "never offered again"). ``or_packet`` is permanently False here:
    the packet subsystem (phases 5-8) is not authorised, so no custom
    experiment packet can ever exist to satisfy it.

    ``cross_column_exclude`` reads ``offered_triggers`` -- the 3 triggers
    already drawn for today's setup, per :func:`draw_offers`'s own ordering
    (triggers are sampled first) -- not the whole offerable trigger pool: the
    wiki's "will never be offered if [trigger] is offered" means offered to
    the player at setup, not merely eligible to be offered.

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
    if gate is not None and gate.get("kind") == "cross_column_exclude":
        if gate.get("excludes_trigger_id") in offered_triggers:
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
    are dropped from the trigger sampling pool and sampled first -- their
    result then feeds the effect pool's own ``cross_column_exclude`` filter
    (see :func:`_effect_offerable`), so triggers must be drawn before effects
    are filtered; this is the same order the two were already sampled in, so
    no RNG substream draw is reordered by the dependency, only the effect
    pool's filtering moment. Effects also gated by their own availability/cap
    are dropped from the effect sampling pool before that draw. None of the 2
    day-gated triggers, the single gated/cappable effect (mail_room_letter),
    or spread_dig_spots's cross-column exclusion (which can drop at most 1 of
    the 12 base effects) can ever shrink either pool below the 3 the draw
    needs.
    """
    ex = registry.experiments
    trig_pool = [t for t in ex.base_trigger_ids if _trigger_offerable(ex.trigger_by_id[t], cfg)]
    assert len(trig_pool) >= 3, "day_gate filtering must never shrink the trigger pool below 3"
    sampled_triggers = rng.stream("experiment_triggers").sample(trig_pool, 3)
    sampled_triggers.sort(key=trig_pool.index)

    eff_pool = [e for e in ex.base_effect_ids
                if _effect_offerable(ex.effect_by_id[e], cfg, state.experiment, sampled_triggers)]
    assert len(eff_pool) >= 3, "effect availability filtering must never shrink the pool below 3"
    sampled_effects = rng.stream("experiment_effects").sample(eff_pool, 3)
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
    """Detect and fire the nine placement-site triggers for a freshly-placed room.

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
    archived_floorplan. Three of the nine are packet triggers (still
    unreachable in play, see the module docstring): ``upgraded_floorplan_draft``,
    ``tomorrow_room_draft``, and ``fireplace_draft``.
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
        case "upgraded_floorplan_draft" if room.variant_of is not None:
            _fire_upgraded_floorplan_draft(game, room)
        case "tomorrow_room_draft" if room.is_category("tomorrow"):
            trigger_success(game)
        case "fireplace_draft" if _room_has_fireplace(room, cell):
            trigger_success(game)
    if room.is_category("bedroom"):
        _count_bedroom_draft(game, room, ex.trigger_id)


def _room_has_fireplace(room, cell: int) -> bool:
    """True when ``room``, placed at ``cell``, has a fireplace today.

    Six of the seven fireplace rooms read straight off the static
    ``Room.has_fireplace`` flag; the Dining Room's fireplace instead depends
    on the cell it lands on -- centre columns or Rank 9 have one, the wings
    and Rank 1 have windows instead (per the packet trigger's own
    ``meta.notes``). Duplicates ``effects/rooms/cloister.py``'s
    ``_dining_room_has_fireplace`` rather than importing it: this module ->
    ``effects.rooms.cloister`` would import the ``effects.rooms`` package,
    which imports ``effects.rooms.drawing_room``, which itself imports this
    module (``from ... import experiments``) -- a cycle.
    """
    if room.id == "dining_room" or room.variant_of == "dining_room":
        return (is_center_column(cell) and rank_of(cell) != 1) or rank_of(cell) == 9
    return room.has_fireplace


def _fire_upgraded_floorplan_draft(game, room) -> None:
    """Fire upgraded_floorplan_draft once, or twice for an upgraded Bunk Room.

    Mirrors :func:`_fire_archived_floorplan`'s own ``counts_as_bedrooms``
    read: an upgraded Bunk Room (``bunk_room__ixNN``, ``variant_of ==
    "bunk_room"``) carries the same tag/amount as the base Bunk Room, so the
    two agree by construction ("an upgraded Bunk Room triggers twice", per
    the trigger's own ``meta.notes``).
    """
    bed_effect = next((e for e in room.effects if e.tag == "counts_as_bedrooms"), None)
    times = bed_effect.param("amount", 1) if bed_effect is not None else 1
    for _ in range(times):
        trigger_success(game)


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


# ------------------------------------------------------------------ interaction-site packet triggers

def on_room_entered(game, cell: int) -> None:
    """Fire rank9_first_entry: ``cell`` (a Rank 9 room, possibly the Antechamber)
    was just entered for the first time today.

    Called from Game._enter right after its own ``entered[cell]`` guard has
    confirmed this call is genuinely the first entry to ``cell`` today -- a
    Rank 9 room entered before the experiment was configured has already set
    ``entered[cell]``, so this site is never reached for it again, which is
    exactly the trigger's own "prior visits before the experiment started do
    not count" (``meta.notes``).
    """
    if game.state.experiment.trigger_id == "rank9_first_entry" and rank_of(cell) == 9:
        trigger_success(game)


def on_lever_pulled(game, cell: int, direction: int) -> None:
    """Fire antechamber_lever_pull once per distinct Antechamber lever segment.

    Called from every site that actually opens one of the Antechamber's four
    sealed doorway segments as a lever pull: ``Game._open_north_door`` (the
    Inner Sanctum's main lever and the Throne Room's backup lever both route
    through it), ``great_hall.pull_east_lever``, ``secret_garden.
    pull_west_lever``, ``weight_room.pull_south_lever``, and
    ``special_items.install_lever``'s Greenhouse ``antechamber_lever``
    branch. The last of those targets the SAME south segment as the Weight
    Room's own lever, through an entirely separate guard
    (``machines_used``, not door state) -- so a day that pulls the Weight
    Room's lever and then installs a Broken Lever in the Greenhouse would
    double-count the south lever without ``ExperimentState.levers_pulled``,
    a per-day distinct segment set (the same shape as
    ``GameState.areas_visited``).
    """
    ex = game.state.experiment
    if ex.trigger_id != "antechamber_lever_pull":
        return
    seg = (cell, direction)
    if seg in ex.levers_pulled:
        return
    ex.levers_pulled.add(seg)
    trigger_success(game)


def on_terminal_accessed(game, room_id: str) -> None:
    """Fire terminal_access once per distinct Upgrade Disk terminal today.

    Called from Game.insert_disk after a disk has actually been inserted
    (not on a failed attempt where no slot was selectable and nothing was
    consumed) -- this is the only discrete "operate a terminal" action this
    simulator models, shared by every ``disk_reader`` room (Security,
    Laboratory, Office, Shelter). Blackbridge Grotto's off-grid 5th disk
    reader has no room record, so it can never fire this.
    ``ExperimentState.terminals_accessed`` (room ids, per-day distinct set)
    is the dedup: a player can insert several disks at the same terminal in
    one day, so a plain counter would overcount.
    """
    ex = game.state.experiment
    if ex.trigger_id != "terminal_access":
        return
    if room_id in ex.terminals_accessed:
        return
    ex.terminals_accessed.add(room_id)
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
        case "add_aquariums":
            _apply_add_aquariums(game, effect)
        case "spread_dig_spots":
            _apply_spread_dig_spots(game, effect)
        case "unseal_antechamber_door":
            _apply_unseal_antechamber_door(game)
        case "random_item_then_zero_keys":
            _apply_random_item_then_zero_keys(game, effect)
        case "half_steps_for_dice":
            _apply_half_steps_for_dice(game, effect)
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


def _apply_add_aquariums(game, effect: ExperimentEffect) -> None:
    """Inject aquariums_added copies, move Aquarium to commonplace, flag the day.

    Order matters. inject_rooms_undealt (decks.py) always inserts into the
    room's own static Room.rarity bucket, ignoring any dynamic_rarity override
    -- so the copies are injected FIRST, then set_dynamic_rarity sweeps
    everything (the pre-existing base Aquarium card, plus the batch just
    injected) into the target bucket in one move. Doing it in the other order
    would leave a first-firing batch stranded outside the destination deck.

    set_dynamic_rarity is idempotent (a no-op, no RNG, once a room's bucket
    already reads the target) -- required since this effect carries no cap and
    can fire many times a day; the wiki's "sets the Dynamic Rarity" reads as a
    standing state, not a repeatable action. One consequence: on a second (or
    later) firing, that same idempotency means the freshly-injected batch stays
    in the room's own static bucket rather than following the earlier batches
    to the target rarity -- still genuinely drawable (at the room's ordinary
    rarity odds), just not Commonplace like the first batch. Fixing that would
    need inject_rooms_undealt itself to consult dynamic_rarity, out of scope
    for this module.

    Applied to both the base Aquarium and the experiment-added copy: the wiki
    names "the Aquarium's Dynamic Rarity" (singular) while also describing the
    added copies as living in "different draft pools" -- both cannot be true
    under this engine's single-deck-per-rarity model, so both ids are moved
    here rather than silently picking one reading over the other.

    decks.py is imported locally: importing it at module scope would cycle
    (decks -> state -> experiments), per this module's own docstring.
    """
    from . import decks

    st, registry, rng = game.state, game.registry, game.rng
    n = effect.magnitude.get("aquariums_added", 3)
    decks.inject_rooms_undealt(st, registry, [AQUARIUM_EXPERIMENT_ID] * n, rng,
                               label="add_aquariums_inject")
    target_idx = RARITY_INDEX[effect.magnitude.get("rarity_override", "commonplace")]
    for room_id in (AQUARIUM_BASE_ID, AQUARIUM_EXPERIMENT_ID):
        decks.set_dynamic_rarity(st, registry, room_id, target_idx, rng,
                                 label="add_aquariums_rarity")
    st.add_aquariums_active = True


def _apply_spread_dig_spots(game, effect: ExperimentEffect) -> None:
    """"Spread dirt on the driveway" -- Conference Room branch only.

    The wiki's Grounds branch (dig spots placed outside the house, starting
    just outside the Entrance Hall) is not modelled: this simulator has no
    off-grid dig-spot concept (special_items.dig_all reads state.grid[cell]
    only; engine/areas.py has no dig-spot representation at all), so without
    a Conference Room already on the estate this call is a no-op.

    With a Conference Room present, every firing adds
    magnitude.spots_per_trigger_usual (3) dig spots to its cell via
    SpecialItemsState.veia_dig_bonus, the same additive per-cell overlay
    Cloister of Veia writes and special_items.dig_all already reads -- until
    SpecialItemsState.conference_room_dig_spots reaches
    magnitude.conference_room_spot_cap (50), at which point the final batch is
    clamped to whatever is left and every later firing adds nothing. The
    "first five on the table, the rest on the floor" placement flavour (wiki)
    has no mechanical consequence at this engine's per-cell granularity and
    is not modelled.
    """
    conference_cell = game.room_cells.get("conference_room")
    if conference_cell is None:
        return  # Grounds branch unbuilt; see the module docstring
    st = game.state
    cap = effect.magnitude.get("conference_room_spot_cap", 50)
    remaining_capacity = cap - st.special.conference_room_dig_spots
    if remaining_capacity <= 0:
        return
    batch = min(effect.magnitude.get("spots_per_trigger_usual", 3), remaining_capacity)
    st.special.conference_room_dig_spots += batch
    bonus = st.special.veia_dig_bonus
    bonus[conference_cell] = bonus.get(conference_cell, 0) + batch


def _apply_unseal_antechamber_door(game) -> None:
    """Unseal the first still-sealed Antechamber segment, west/south/east/north.

    Reuses ``Game._open_segment`` -- the exact call every lever room already
    makes to unseal one of the Antechamber's four segments (Great Hall's
    ``pull_east_lever``, Secret Garden's ``pull_west_lever``, Weight Room's
    ``pull_south_lever``, and ``special_items.install_lever``'s Greenhouse
    branch all call it directly; the two north levers share
    ``Game._open_north_door``, which itself wraps the same call) -- rather
    than writing new door-state logic.

    Deliberately does NOT go through ``_open_north_door`` for the north
    segment, and does not call ``on_lever_pulled`` for any segment: those
    exist to attribute a genuine player lever-pull to the antechamber_lever_pull
    trigger and (for north only) the env reward's north_door_opened flag; this
    effect unseals a door programmatically, not by pulling a lever, so
    crediting either would misattribute an unrelated experiment's trigger/
    reward to this one. Only ``_open_segment`` -- the shared low-level
    mechanism both paths bottom out in -- is reused.

    The (cell, direction) segments and their order are copied verbatim from
    Game.__init__'s own antechamber_levers sealing loop (west (41, E), south
    (37, N), east (43, W), north (ANTECHAMBER_CELL, N) -- ANTECHAMBER_CELL is
    42, hardcoded here since importing it from game.py would cycle, per the
    module docstring). "First still-sealed in that order" reproduces the
    wiki's unweighted "west/east/south appear to be preferred over north"
    without inventing the unpublished per-door weights (magnitude.weighting
    stays null; see this id's own meta.notes) -- the order among west/south/
    east itself is not stated by the wiki either, so this resolves that half
    of the ambiguity by reusing the one ordering already in the codebase
    rather than inventing a second one.

    If every segment is already unsealed (including when antechamber_levers
    is off, so none was ever sealed), this is a no-op -- "has no effect once
    all four doors are unsealed (still triggers, no-op)" per the record's own
    notes.

    locks.py is imported locally: importing it at module scope would cycle
    (experiments -> locks -> state -> experiments), per the module docstring.
    """
    from .locks import DOOR_SEALED, segment_key

    st = game.state
    segments = (
        (41, E),  # West door: Antechamber's west face (Secret Garden lever)
        (37, N),  # South door: Antechamber's south face (Weight Room lever)
        (43, W),  # East door: Antechamber's east face (Great Hall lever)
        (42, N),  # North door: off-grid door to Room 46 (Inner Sanctum/Throne Room lever)
    )
    for cell, direction in segments:
        if st.door_state.get(segment_key(cell, direction)) == DOOR_SEALED:
            game._open_segment(cell, direction)
            return


def _apply_random_item_then_zero_keys(game, effect: ExperimentEffect) -> None:
    """Grant one random item via the shared extra-item table, THEN zero keys.

    magnitude.item_pool is deliberately null: the wiki's true pool is a live
    Cargo query ("Items where Locations HOLDS 'Experiment'") not present in
    static wikitext, and the record's own meta.notes says not to invent one.
    Rather than fabricate a list of special items, this reuses the SAME
    generic random-item table and RNG label (items.EXTRA_ITEM_TABLE,
    "extra_item_kind") that Closet/Walk-In/Attic's own "random" guaranteed
    entries, the Closet-family adjacency bonus (items.roll_extra_items), and
    gain_key_gem_or_die's own weighted-roll pattern already draw from -- an
    existing label, not an invented one, per the module's RNG discipline. The
    wiki's "grant a Silver Key instead when fewer than 2 pool items are
    currently available" fallback has no analogue here since this table is a
    fixed 4 entries, never that small; not modelled for that reason, not
    overlooked.

    Order matters and is pinned by a test: the item is granted FIRST, and
    keys are zeroed SECOND -- reversing this would let a "key" roll from the
    table survive the zeroing (final keys == 1 instead of 0) whenever the
    extra-item table happens to resolve to "key".

    items.py is imported locally: importing it at module scope would cycle
    (experiments -> items -> state -> experiments), per the module docstring.
    """
    from .items import EXTRA_ITEM_TABLE, grant_item

    weights = tuple(w for _, w in EXTRA_ITEM_TABLE)
    idx = game.rng.roll_weighted("extra_item_kind", weights)
    grant_item(game, EXTRA_ITEM_TABLE[idx][0], 1)
    game.state.keys = effect.magnitude.get("keys_after", 0)


def _apply_half_steps_for_dice(game, effect: ExperimentEffect) -> None:
    """Halve steps (floored), THEN grant Ivory Die -- both halves apply unconditionally.

    Order matters and is pinned by a test: the step loss is applied FIRST
    (``math.floor(steps * steps_multiplier)``, so an odd count like 7 becomes
    3, not 4), and the dice are granted SECOND, regardless of whether the
    step loss already brought steps to 0. Nothing in this function checks
    termination -- granting the dice unconditionally, even when the step loss
    alone is enough to end the day, matches the wiki's plain "lose half your
    steps, then gain 4 Ivory Die" (a sequential description of one atomic
    effect, not a conditional grant) and matches this module's own existing
    precedent for every other step-draining effect/trigger (steps_for_gold,
    set_steps, and a triggering red_room_draft's own steps_lost in
    trigger_success): none of them call ``game._check_termination()``
    themselves either, instead relying on whichever action method
    (``choose``, ``move``, ``redraw``, ``open_door``) is already about to
    check termination as its own last statement once the whole action --
    including this effect -- has finished.

    That reliance has one genuine gap, investigated for this effect
    specifically since it (unlike the draft-site-only steps_for_gold/
    set_steps precedent) can be paired with ANY trigger, including
    interaction-site ones: ``Game.insert_disk`` (the only call site for the
    packet ``terminal_access`` trigger) never calls ``_check_termination``
    at all, and neither does ``Game.choose_upgrade`` afterward, so a day that
    hits 0 steps here while configured with ``terminal_access`` would not be
    marked TERMINAL until the *next* NAVIGATE-phase action re-checks (the env
    layer's own post-step "no legal action" fallback, or a CLI policy's
    explicit ``_check_termination()`` call, both eventually catch it one
    action late, just under the "dead_end" reason rather than
    "out_of_steps"). This is a pre-existing gap in ``insert_disk``/
    ``choose_upgrade`` themselves -- already latent for steps_for_gold and
    set_steps, since either could already be paired with terminal_access
    today -- not something introduced here, and deliberately NOT patched by
    adding a ``_check_termination()`` call inside this function: that would
    diverge from every other step-draining effect above and, worse, risks
    firing mid-``Game._place_room`` when this effect is reached via a
    draft-site trigger instead -- ON_PLACE/ON_DRAFT_ROOM hooks for the room
    being placed still run AFTER ``on_room_drafted`` returns, and would then
    run on a state ``_terminate`` has already swept for day-end. Fixing
    ``insert_disk``/``choose_upgrade`` generally is out of scope for a
    three-effect pass; see the id's own test for what this function does and
    does not guarantee.
    """
    st = game.state
    multiplier = effect.magnitude.get("steps_multiplier", 0.5)
    st.steps = math.floor(st.steps * multiplier)
    st.dice += effect.magnitude.get("dice_gained", 4)
