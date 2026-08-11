# Laboratory / Experiments — design

Status: **phase 0 — data and validation only.** `src/blueprince_sim/data/experiments.json`
transcribes every trigger and effect the wiki publishes; `tools/validate_data.py`
checks it for referential integrity and shape. There is no engine module, no
`GameState` wiring, no hooks, and no player-facing actions yet — every record in
the data file carries `"implemented": false`. Mirrors the shape of
`docs/special-items-design.md`; read that doc for the idiom this one follows.

Scope of this document: the Experiments mechanic itself (triggers, effects, the
draw/setup procedure), the data shape that transcribes it, the availability
layer that gates individual triggers/effects, the phase plan, and a table of
every number the wiki does not publish.

Source data: fetched directly from `blueprince.wiki.gg` (see each record's
`meta.source`); no separate `docs/research/` digest exists for this subsystem
the way `docs/research/special-items-wiki.md` does for items — the wiki pages
are short enough that `experiments.json` cites them directly.

## The mechanic

An **experiment** pairs one **trigger** with one **effect**, active for exactly
one day, set up at the Mt. Holly Laboratory terminal:

- Three triggers and three effects are drawn **uniformly** from the available
  pool; the player picks one of each to form the day's experiment.
- Only **one** experiment can be active on a given day.
- Once running, the experiment fires every time the trigger's condition is met
  — "no limit... other than the physical limits of its trigger" — and the
  chosen effect is carried out on each success.
- Experiments can be **paused and resumed** from the terminal at will.
- **Twelve triggers and twelve effects at base.** Raising the Satellite Dish
  and downloading its data packet permanently adds **eight more of each**,
  bringing the total to twenty each; a Packet Management screen then lets the
  player choose which ≥8 of each may actually appear.

Every successful trigger, regardless of the chosen effect, also raises a
hidden daily **radiation level** that gates the Shelter terminal's
unlock-all-doors ability (radiation level and Shelter are both out of scope —
see "Deliberately never modelled" below).

## Data shape — `data/experiments.json`

```jsonc
{
  "schema_version": 1,
  "meta": {"source": "...", "confidence": "wiki", "notes": [...]},
  "mechanic": {
    "one_at_a_time": true,
    "pausable": true,
    "duration": "day",
    "setup": "...",
    "base_trigger_count": 12, "base_effect_count": 12,
    "packet_trigger_count": 8, "packet_effect_count": 8,
    "packet_note": "..."
  },
  "triggers": [
    {
      "id": "security_door",            // stable snake_case id, coined here
      "text": "Each time you unlock or bypass a security door,",  // wiki wording, verbatim
      "pool": "base",                   // base | packet
      "availability": {                 // gating rule, or null
        "kind": "day_gate",
        "day": 8,
        "veteran_bypass": true,
        "text": "If Veteran Mode is not enabled, this trigger cannot appear before Day 8."
      },
      "cap": null,                      // hard trigger-count limit, or null
      "rooms": [...],                   // only on records that name specific rooms (fireplace trigger)
      "magnitude": {...},               // structured numbers the wiki gives; absent if none
      "implemented": false,             // every record, phase 0
      "meta": {
        "source": "https://blueprince.wiki.gg/wiki/Experiments/Triggers",
        "confidence": "wiki",
        "blocked_on": "phase 0: no experiments engine exists yet (data/validation only)",
        "notes": [...]                  // gaps, editorial cautions, provenance
      }
    }
  ],
  "effects": [ /* same shape */ ]
}
```

`effects` records use the same shape as `triggers` (no `rooms` field is used
there in practice, since no base/packet effect names specific rooms).

### `pool`

`"base"` (12 triggers, 12 effects, always available) or `"packet"` (the 8+8
the Satellite Dish data packet adds). The packet pool is transcribed here for
completeness even though the packet *subsystem* — Satellite Dish, Packet
Management, the radio/network flow that unlocks it — is out of scope for
phases 0–4 (see "Phase plan" below). A `packet`-pool record can still be
implemented mechanically as a trigger/effect in phases 1–4; what stays out of
scope is the download-and-select machinery that makes it choosable in the
first place.

### `availability`

A tagged object describing when a trigger/effect may be drawn at all, or
`null` when there is no gating. Every `kind` carries the wiki's own wording
verbatim in a `text` field, so the structured fields are a parse of that text,
not a paraphrase:

| `kind` | fields | records |
|---|---|---|
| `day_gate` | `day`, `veteran_bypass` | `security_door`, `drawing_room_drawn` |
| `room_drafted_gate` | `room_id`, `veteran_bypass` | `archived_floorplan` |
| `item_obtained_gate` | `item_id`, `veteran_bypass` | `trash_while_digging` |
| `resource_or_gate` | `resource`, `amount`, `or_veteran`, `or_packet` | `gain_star` |
| `day_or_packet_gate` | `day`, `or_packet` | `mail_room_letter` |
| `room_present_gate` | `room_id`, `checked_at` | `pantry_fruit` |
| `cross_column_exclude` | `excludes_trigger_id` | `spread_dig_spots` |
| `cross_column_probability` | `removes_effect_id`, `chance_pct` | `map_view` |
| `value_variant` | `condition`, `swap_text` | `reservoir_water_level` |

The two `cross_column_*` kinds are the pairs that reach across the
trigger/effect split: offering the `trash_while_digging` trigger excludes the
`spread_dig_spots` effect from the pool entirely, and offering the `map_view`
trigger gives a 95% chance of removing the `set_steps` effect from the pool.
`tools/validate_data.py` resolves both id references against the file's own
trigger/effect id sets, so a rename on one side that forgets the other side is
a validation **error**, not a silent drift.

`cross_column_exclude` is enforced in `engine/experiments.py::_effect_offerable`,
which is why `draw_offers` samples the 3 triggers before filtering the effect
pool: the exclusion reads which triggers were actually *offered* that setup
(the sampled 3), not the whole eligible trigger pool, so the trigger draw must
finish first. `cross_column_probability` (`map_view`) stays unenforced --
`map_view` is a packet-pool trigger, and the packet pool is never offered
(phases 5-8, out of scope), so the rule it would gate can never fire anyway.

### `cap`

A hard, wiki-*stated* limit on how many times the record's own effect
actually applies — `3` (chests), `10` (map views), `16` (letters), `17`
(Entrance Hall trunks), `40` (tunnel crates) — or `null`. `cap` lives on both
triggers and effects, and the two mean different things once past the limit,
enforced at two different sites in `engine/experiments.py`:

- A **trigger's** `cap` (`trunks_opened`, `map_view`) is checked in
  `trigger_success` and suppresses the *whole fire*: the trigger no longer
  succeeds at all, `success_count` stops advancing, and the trigger's own
  `steps_lost` (if any) is not charged either.
- An **effect's** `cap` (`entrance_hall_trunk`, `mail_room_letter`) is
  checked in `apply_effect`, never in `trigger_success`: the trigger it is
  paired with keeps succeeding (`success_count` still advances, `steps_lost`
  is still charged) and only the effect itself goes silent. This matches each
  id's own wiki wording ("will no longer have any effect" / "never offered
  again" — neither says the *trigger* stops firing) — a capped-out letter
  still displays its delivery message, a capped-out trunk effect just no-ops.

Approximate figures the wiki hedges with "around" or "approximately" (the dig
spots effect's "~100 spots after ~34 triggers" on the Grounds) are **not**
encoded as `cap`; they live in `meta.notes` instead, because a `cap` field
implies an exact enforceable number and these explicitly aren't that. The
same record's Conference Room branch (the only branch this sim builds -- see
"Phase plan" / Status) *does* carry a wiki-exact limit ("up to 50 dig spots...
after 17 triggers"), but it is still not the top-level `cap`: `cap` counts
successful *applications*, while this branch's limit is a spot *total* (17
applications of 3 spots each would be 51, one over the stated 50), so it lives
in `magnitude.conference_room_spot_cap` instead and is enforced directly
against the running spot count, clamping the final batch rather than
overshooting by one spot.

### `magnitude`

Structured numbers the wiki gives directly (amounts, percentages, room/step
counts) — omitted entirely from a record when the wiki gives no numbers at
all. Six specific concepts the wiki mentions but never quantifies get their
`magnitude` sub-field set to `null` rather than omitted, so the gap is visible
in the schema rather than silently absent — see "Unpublished numbers" below.

## Availability rules transcribed

- **Security door trigger** and **Drawing Room trigger**: gated to Day 8+
  unless Veteran Mode.
- **Archived trigger**: gated until an Archives has been drafted at least
  once, unless Veteran Mode.
- **Trash trigger**: gated until a Shovel has been obtained, unless Veteran
  Mode.
- **Stars effect**: requires ≥3 stars, OR Veteran Mode, OR a packet has been
  set up.
- **Letters effect**: gated to Day 11+ unless a packet exists; separately
  capped at 16 total and never offered again once all are delivered.
- **Dig-spots effect**: never offered when the trash trigger is offered (a
  cross-column exclusion — see above).
- **Map trigger** offered ⇒ the "set steps to 40" effect has a 95% chance of
  being removed from the effect pool that same setup (cross-column
  probability).
- **Pantry effect**: requires a Pantry already on the estate the first time
  experiment options are viewed.
- **Reservoir effect**: its displayed text swaps to "Raise the Reservoir by 1"
  if the water level is 0 at the moment of selection; once either variant is
  rolled it is locked in for the day even if the water level changes again
  before the experiment starts.

## Unpublished numbers — record the gap, never invent

These are concepts the wiki names but does not quantify. Each is recorded as a
`null` field inside the relevant record's `magnitude`, with the gap spelled
out in that record's `meta.notes`:

| Gap | Record | Field |
|---|---|---|
| Key / gem / die selection split | `gain_key_gem_or_die` (base effect) | `magnitude.split` |
| Dig-spot count distribution (2 / 3 / 4 per trigger) | `spread_dig_spots` (base effect) | `magnitude.distribution` |
| Antechamber-door preference weights (W/E/S over N) | `unseal_antechamber_door` (packet effect) | `magnitude.weighting` |
| Pantry fruit mix (apple vs. banana vs. orange) — ordinal only | `pantry_fruit` (packet effect) | `magnitude.mix_weights` |
| Lockpicking-skill magnitude per trigger | `permanent_lockpicking_skill` (packet effect) | `magnitude.amount` |
| "Gain 1 random item" pool — a live wiki Cargo query, not present in static wikitext | `random_item_then_zero_keys` (packet effect) | `magnitude.item_pool` |

## Not transcribed as real — commented-out wiki rules

The wiki source contains two rules wrapped in HTML comments (`<!-- ... -->`),
i.e. never rendered on the live page, alongside an editor's own caveat that "a
lot of the datamined info on experiments has been off or just straight up
wrong":

1. A **30% chance the crates-removal effect is dropped** from the pool if
   fewer than 36 of the 40 tunnel crates have been removed. The commenting
   editor says they tested this and found no meaningful frequency change.
2. A **mutual exclusion** between the "set dice to 2" effect and the "gain 1
   key/gem/die" effect (the two effects would never be offered together).

Both are recorded in `meta.notes` on `remove_tunnel_crate` and `set_dice`
respectively, explicitly flagged as unpublished and **not to be implemented**.
They are not modelled as `availability` or any other live field — a future
reader should not "recover" them from the notes without independent
confirmation.

## Deliberately never modelled

These stay out of scope at **every** future phase, not just phase 0, because
the concept they describe doesn't exist in this simulator or targets a system
that is out of scope on its own terms:

- **The 40-second real-time trigger** and **the map-view trigger** — this
  simulator has no wall-clock and no interactive map-viewing action; both are
  meaningless here regardless of implementation phase.
- **The setup-menu reroll timing exploit** — revisiting the Experimental Setup
  menu before committing lets a player reroll the three-of-each draw; this is
  a UI-timing quirk, not a data rule, and has no analogue in a turn-based sim.
- **Blessing of the Tinkerer cross-triggers** — any active experiment also
  fires whenever a Mechanical Room is drafted, independent of the chosen
  trigger. This is a global modifier on the whole subsystem (and on the
  Blessing system, itself unimplemented), not a per-record rule.
- **Radiation level** — the hidden daily counter that experiment successes
  feed, gating the Shelter terminal. Shelter and the Grounds are out of scope.
- **Dare Mode** — an alternate, harder experiments ruleset on its own wiki
  subpage.
- **Research Logs** — an in-fiction log of experiment activation history; not
  a mechanical system.

## Phase plan

Phases 0–4 are authorised. Phases 5–8 are a separate subsystem and are
explicitly **not** in scope for this work — see below for why.

0. **This document and this data file.** Transcription and validation only.
   No engine code, no `GameState`, no hooks, no actions. Makes the research
   reviewable before anything depends on it.
1. **Engine module + `GameState`.** A `special.py`-shaped
   `engine/experiments.py`: frozen `ExperimentsRegistry` parsed from
   `experiments.json`, a mutable `ExperimentsState` (active trigger/effect ids,
   per-day trigger count, pause flag, cross-column pool adjustments applied at
   setup time).
2. **Setup + the twelve base triggers/effects.** `Game.setup_experiment`,
   `pause_experiment`/`resume_experiment`; wire the base-pool availability
   rules (`day_gate`, `room_drafted_gate`, `item_obtained_gate`). Packet-pool
   records stay undrawable (no Satellite Dish/packet system yet), but their
   `implemented` flag can flip once their trigger/effect logic is written,
   independent of whether the packet *download* flow exists.
3. **Trigger detection hooks.** Wire each base trigger's condition into the
   relevant call sites (draft, move, dig, lock-open, apple-eat) the way
   `special_items.py`'s hooks are wired into `game.py` today.
4. **Effect application + env/obs wiring.** Apply each base effect on trigger
   success; expose active-experiment state (trigger id, effect id, today's
   trigger count) to the observation space; add setup/pause/resume actions.

**Phases 5–8 (not authorised, separate subsystem):** the Satellite Dish
prerequisite chain, the data-packet download flow, Packet Management (the
≥8-of-20 selection UI), and the eight packet triggers/effects' own detection
and application logic. These are gated behind the Satellite Dish being raised
at all — a Grounds/outer-area prerequisite this codebase does not yet model —
so building packet *behavior* ahead of that prerequisite would be simulating a
state the player can never actually reach yet. The packet pool's *data* is
transcribed now (phase 0) because the table is more reviewable complete than
partial; its *behavior* waits for its own authorization.

### Status

Phases 0 and 1 landed the engine core: `engine/experiments.py` holds the
registry, the per-day `ExperimentState`, the uniform 3-of-12 setup draw, and
effect application; `Game` exposes the terminal (`start_setup`,
`choose_experiment_trigger`, `choose_experiment_effect`, `toggle_experiment`)
gated on standing in the Laboratory, with `Phase.EXPERIMENT_PENDING` and
actions 319–326. A later pass wired the five draft-site triggers (`shops`,
`gems_spent`, `bedrooms_after_second`, `hallway_from_hallway`,
`red_room_draft`) through `on_room_drafted`, called from `Game._place_room`.
A further pass added the generic `cap` field (enforced in `trigger_success`, which
also gates the trigger's own `steps_lost` on a capped-out fire — pausing
suppresses a qualifying event without spending one of the cap's charges,
since `success_count` only ever increments inside that same call); the
`trunks_opened` trigger (`special_items.py::open_container`, gated on
`kind in ("trunk", "chest")`, firing only after the opened-count bump so a
failed open never counts, and covering smash-opens the same way key-opens
are covered); the `security_door` trigger, fired from two sites in
`game.py` — `_unlock_for_passage`, gated on `for_draft=True` (drafting
*through* a security doorway, not merely walking through it) and
`_roll_new_segments` (drafting *into* a room whose own door converts an
already-rolled `DOOR_SECURITY` segment to open); and the `day_gate`
availability filter in `draw_offers`, excluding `security_door` and
`drawing_room_drawn` from the sampling pool before day 8 unless
`cfg.veteran_mode` is set (the default — the filter is a no-op unless a
caller explicitly turns veteran mode off). Most recently, the
`trash_while_digging` trigger, fired from `special_items.dig_all`'s per-spot
loop on a `junk` table outcome (`nothing` never counts, per the wiki). Both
dig tables already fold Scraps of Paper into a second `junk` row rather than
a distinct kind, so the Patch 1.6 addition needed no separate handling.
`dig_all` digs every remaining spot at a cell in one call, so this trigger
fires in bursts, not once per player action. Courtyard carries the highest
plain `dig_spots` in `rooms.json` (5), but it is not one of the six
fireplace rooms, so it cannot also collect Cloister of Veia's +8-per-fireplace-
room bonus (`veia_dig_bonus`); of the fireplace rooms, only Furnace carries a
nonzero baseline (1), so the highest single-cell total reachable through
normal play is 1 + 8 = 9 spots, not the two maxima naively summed. Most
recently, the `apples` trigger, fired from `special_items.eat_food`'s
per-item loop on `food_id == "apple"` — the one dish id covering all three
visual varieties (green, red, with leaves; purely visual per the wiki) — once
per apple, after that apple's own steps have already been granted. The
ordering matters: a same-day `set_steps` effect must land last, not be
overwritten by the apple's own steps, per the wiki's stated interaction. A
single `eat_food` call with `count` > 1 (the Secret Garden's Conference Room
spread, which pays out 4 apples in one call) fires the trigger once per apple
inside the loop, matching apples being eaten one at a time in the real game.
That refactor also threaded the `game` orchestrator through `items.py`'s
`grant_item`/`roll_room_items`/`roll_extra_items` and this module's
`eat_food`/`_maybe_serve_main_course`, replacing their loose
`(state, registry, rng)` parameter triples — the same idiom `dig_all` and the
rest of this module already followed — with no behavior change.

Most recently, the last two base triggers landed, plus a termination gap
fix. `Game.redraw` now calls `_check_termination()` at the end, after the
redealt hand's `ON_HAND_DEALT` loop, the same convention `open_door` already
follows — previously an experiment could drain steps to 0 inside a redraw
(e.g. `drawing_room_drawn` + `steps_for_gold`) and the day would not end
until some later NAVIGATE-phase action noticed. `drawing_room_drawn` fires
from a new `on_drawing_room_dealt`, called by a one-line `room_hook` on
`Hook.ON_HAND_DEALT` in `engine/effects/rooms/drawing_room.py` — kept out of
`experiments.py`'s own dispatch so a Drawing-Room-id literal lives in a room
module, not an engine one (the standing rule that no engine module may
branch on a room id). `fire()` already ran that hook at all three
`ON_HAND_DEALT` sites (the initial grid deal, the initial outer deal, and
every redraw), so no new call site was needed; the outer deal is a permanent
no-op since the fixed outer pool can never contain the Drawing Room. A
hidden or archived Drawing Room still counts (the hook receives no
concealment info at all, matching the wiki's plain "drawn" wording).
`archived_floorplan` became a sixth branch of `on_room_drafted`, gated on the
chosen `DraftOption.archived` flag now threaded through `Game.choose` ->
`Game._place_room` (mirroring how `gem_cost` already reaches that function) —
it fires on *choosing* an archived option, not its earlier deal, and fires
twice for a Bunk Room by reading the same `counts_as_bedrooms`/`amount` tag
`bedrooms_after_second` already reads, rather than hard-coding a room id.
`archived_floorplan`'s own `room_drafted_gate` availability (Archives
drafted, veteran-bypassable) stays unbuilt, same as before — only `day_gate`
is enforced, and it never applied to this trigger.

**All twelve base triggers are now live; eleven of the twelve base effects
are.** The one unimplemented base effect is `spread_dig_spots` — a live
trigger can still be paired with it, a no-op the draw does not filter out.
(`spread_dig_spots` itself landed in a later pass, described further down.)

Most recently, the effect-side `cap` field landed (`ExperimentEffect.cap`,
loaded but previously dropped on the floor — `tools/validate_data.py`
validated its shape without ever wiring it into the engine, so the gap
passed clean), enforced in `apply_effect` rather than `trigger_success` (see
the `### cap` section above for why the two differ), plus the two effects it
unblocks:

- `entrance_hall_trunk` adds a `trunk` container to the Entrance Hall,
  capped at 17 per day. The counter lives on `SpecialItemsState`
  (`entrance_hall_trunks`), not `ExperimentState`, named for the room rather
  than this experiment record because the wiki treats The Twins constellation
  as sharing the same 17-trunk limit ("identical to triggering this effect
  twice") — a future Twins hook can bump the same field.
  `special_items.py::_container_kinds_at` gained an Entrance Hall branch
  (`_entrance_hall_container_kinds`) alongside its existing Mechanarium
  per-cell branch, so `_next_container_kind`/`can_open_container`/
  `open_container` all pick the added trunks up automatically, including
  the re-entrant case where opening one (with `trunks_opened` also
  configured) adds another to the same room mid-call — safe, because the
  container `kind` and its loot config are captured before the trigger
  fires. `env/obs.py`'s `grid_containers` was also fixed to route through
  `_container_kinds_at` instead of reading the static per-room table
  directly, which had made the Mechanarium's own per-cell compartments (and
  now these trunks) invisible to the observation space. Per the owner's
  ruling from play, the 17 is a **daily** maximum: no `GameConfig` field, no
  `carryover()` entry, no `DayChain` merge — `SpecialItemsState` being
  rebuilt fresh with `GameState` every day already gives the right reset for
  free.
- `mail_room_letter` becomes a pure delivered-count bump
  (`ExperimentState.letters_delivered`); the 16 letters' actual contents stay
  deliberately unmodelled (owner ruling: they are flavour — safe codes, a
  network password, a puzzle solution — and the assumed-solved doctrine
  already grants what they convey, the same reasoning as the Speakeasy). Its
  `day_or_packet_gate` availability is now enforced by a new
  `_effect_offerable` (mirroring `_trigger_offerable`): excluded before day
  11 (`or_packet` is permanently False, since the packet subsystem is
  unauthorised) and excluded once `letters_delivered` reaches the cap.
  **Known gap:** `letters_delivered` is day-scoped, like the rest of
  `ExperimentState`, but `draw_offers` only ever runs once per day on fresh
  state — so the "already delivered 16, never offered again" half of the
  check cannot yet observe a *prior* day's deliveries. Making that true
  needs a persistent cross-day total, the same shape as
  `GameConfig.chapel_tithes` (seeded into per-day state, reported by
  `carryover()`, merged by `DayChain`); that wiring is a follow-up.

`draw_offers` samples the base pool uniformly (modulo the trigger-side
`day_gate` filter and the effect-side `day_or_packet_gate`/`cross_column_exclude`/cap
filters above) and still does not filter on `implemented`, so a setup can
configure an experiment pairing a live trigger with a silent effect, or vice
versa, or both silent — narrower now that every trigger and every base effect
has a firing site (`spread_dig_spots`'s own is partial — see below), but still
possible. Filtering the draw to fully-implemented records remains future
work, not something addressed so far.

Most recently, `add_aquariums` landed — the last base effect, and the risky
one: it deliberately breaks `room_draftable`'s one-copy-per-room invariant.
`apply_effect` injects `magnitude.aquariums_added` (3) copies of the
`aquarium__experiment` floorplan via `decks.inject_rooms_undealt`, then moves
both the base Aquarium and that experiment copy to the Commonplace bucket via
`decks.set_dynamic_rarity` (idempotent past the first firing — the injection
must run first, since `inject_rooms_undealt` always inserts into a room's own
static rarity bucket, ignoring any dynamic override), then sets
`state.add_aquariums_active`. That flag does two things outside
`experiments.py`: it activates two new `condition`-gated `priority_draws.json`
entries (`add_aquariums_13`/`add_aquariums_3`, 13% and 3%, applying
independently per `_priority_draw`'s existing per-entry roll — 15.61%
combined, appended after the three existing entries so their own substream
labels and order are untouched), and it waives `room_draftable`'s one-copy
rule for `aquarium__experiment` specifically — never the base Aquarium —
following the shape of the existing Tunnel-chain exception rather than a
second global waiver like the Chamber of Mirrors'. Without the waiver all
three injected copies (and every later one) share the single
`aquarium__experiment` id, so the grid caps at 2 Aquariums total; with it, the
grid is the only remaining bound.

That bound was the actual risk: an Aquarium is a Shop, Red, Hallway and
Bedroom room at once (`extra_categories`), so drafting one while any of those
four triggers is configured re-fires `add_aquariums`, the wiki's own designed
loop. `Game._place_room` carried a comment flagging this as the case its
non-recursion argument had not yet been checked against. Re-verified: the
loop cannot recurse *within* one `_place_room` call, because
`_apply_add_aquariums` only mutates deck/rarity state and never calls
`_place_room`, `open_door`, or `choose`; *across* separate placements it is
bounded by the finite grid, since each fire only makes more Aquariums
draftable, it does not place one itself. `tests/test_experiments.py` drives
this to exhaustion — placing `aquarium__experiment` at all 43
non-Entrance-Hall, non-Antechamber cells with `shops` configured — and pins
that it terminates normally. `Game._place_room`'s comment now states this
argument instead of asking for it to be re-verified.

Most recently, `spread_dig_spots` landed — the Conference Room branch only.
The wiki's Grounds branch (dig spots placed outside the house, starting just
outside the Entrance Hall) needs an off-grid dig-spot concept this simulator
does not have (`special_items.dig_all` reads `state.grid[cell]` only;
`engine/areas.py` has no dig-spot representation) and stays unbuilt; the
record's `implemented` flipped to `true` anyway since the Conference Room
branch is a complete, self-contained behavior, and its `meta.blocked_on` was
rewritten to name the Grounds gap specifically rather than the stale "no
experiments engine exists yet." With a Conference Room on the estate,
`_apply_spread_dig_spots` adds `CONFERENCE_ROOM_DIG_SPOT_BATCH` (3, the
wiki's stated usual batch — the 2/3/4 distribution stays unpublished and
`magnitude.distribution` stays `null`, per the existing gap) dig spots to its
cell on top of `SpecialItemsState.veia_dig_bonus` — the same per-cell overlay
Cloister of Veia writes and `dig_all` already reads — each firing, up to
`CONFERENCE_ROOM_DIG_SPOT_CAP` (50, clamping the final batch); without a
Conference Room the call is a no-op. The 50-spot figure is wiki-exact for
this branch (unlike the Grounds branch's hedged totals) but is *not* the
generic `ExperimentEffect.cap` field, which counts applications rather than
spots — 17 applications of 3 would overshoot 50 by one — so it lives in
`magnitude.conference_room_spot_cap` and is enforced against a dedicated
running total (`SpecialItemsState.conference_room_dig_spots`) instead.

This pass also built the prerequisite the effect could not safely ship
without: `cross_column_exclude` enforcement. The wiki states
`spread_dig_spots` "will never be offered if the 'find trash while digging'
experiment trigger is offered," and `experiments.json` had carried that as a
`cross_column_exclude` availability record since phase 0, but nothing read
it — `draw_offers` could offer both in the same setup. `_effect_offerable`
now takes the setup's already-sampled `offered_triggers` and excludes any
effect whose `cross_column_exclude.excludes_trigger_id` is among them, which
forces an ordering change in `draw_offers`: triggers must be sampled (and
their RNG substream consumed) *before* the effect pool is filtered, since the
exclusion depends on which 3 triggers were actually offered, not the whole
eligible trigger pool. This does not reorder any RNG substream draw relative
to before (triggers were already sampled first); it only moves the moment
the effect pool is filtered to after that draw completes. The exclusion can
drop at most 1 of the 12 base effects, so — like the existing day-gate and
day-or-packet-gate filters — it can never shrink the effect pool below the 3
`draw_offers` needs; `draw_offers` asserts this the same way it already
asserted for the trigger-side filter.

Two more wiki-described pieces of this effect are recorded but not built, in
`meta.notes`: the **Dovecote birdbath sub-effect** (with a Dovecote on the
estate, this effect *also* fills 6 off-grid birdbaths with dirt in a fixed
3-trigger pattern, independent of the main effect — blocked on the same
missing off-grid concept as the Grounds branch) and the **Blessing of the
Chef's "Mudslide Icecream"** dish (a unique Dining Room dish this effect can
add while that Blessing is active — blocked on the Blessing system itself
being unimplemented). Also not modelled, at this engine's per-cell
granularity: the wiki's "first five [dig spots] appear on the conference
table, the remainder on the surrounding floor" placement detail, which has no
mechanical consequence here.

`special_items.py::dig_all`'s per-spot loop carries a safety comment arguing
that `remaining` (the spot count fixed before the loop starts) can never grow
mid-loop. That argument used to lean on `spread_dig_spots` being
unimplemented; it still holds now that the effect is live, for a narrower
reason: the loop's only within-loop mutation site is the `trash_while_digging`
branch (which calls `apply_effect` for *today's* configured effect), and
`spread_dig_spots` can never be that day's configured effect while
`trash_while_digging` is that day's configured trigger, because the two can
never even be *offered* together — the `cross_column_exclude` enforcement
above. The comment now states this argument directly instead of pointing at
an unimplemented effect.

## Validation (`tools/validate_data.py`)

- Every trigger/effect `id` is unique (checked across triggers and effects
  together, not just within each list).
- `pool` ∈ `{base, packet}`.
- Exactly 12 base triggers, 12 base effects, 8 packet triggers, 8 packet
  effects — a count drift is an **error**, not a warning, the same way the
  areas-graph node/edge counts are pinned elsewhere in this file.
- Every `availability.room_id` / `rooms[]` entry resolves against
  `rooms.json`; every `availability.item_id` resolves against
  `special_items.json`.
- Every `availability.excludes_trigger_id` / `removes_effect_id` resolves
  against this file's own trigger/effect id sets.
- `cap`, when present, is a positive int.
- `availability.chance_pct` and `magnitude.priority_draw_chance_pct` entries
  fall in `[0, 100]`.
- `implemented` must be `false` for every record in phase 0; `implemented:
  false` requires `meta.blocked_on` (same rule `special_items.json` enforces).
- `meta.confidence` is one of the standard four values.

These are **errors**, not warnings, per this task's own instruction: a
referenced id that fails to resolve is exactly the silent failure this tool
exists to catch.

The Laboratory room's `effect_text` ("Experimental House Features") is
unaffected by this phase — it carries no `effects` tag in `rooms.json`, so it
remains on the room-fidelity divergence audit's kind-2 worklist (`effect_text`
present, no modelling) until an engine phase lands.
