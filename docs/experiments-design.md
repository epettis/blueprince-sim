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

### `cap`

A hard, wiki-*stated* trigger-count limit — `3` (chests), `10` (map views),
`16` (letters), `17` (Entrance Hall trunks), `40` (tunnel crates) — or `null`.
Approximate figures the wiki hedges with "around" or "approximately" (the dig
spots effect's "~100 spots after ~34 triggers") are **not** encoded as `cap`;
they live in `meta.notes` instead, because a `cap` field implies an exact
enforceable number and these explicitly aren't that.

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

Phases 0 and 1 have landed. `engine/experiments.py` holds the registry, the
per-day `ExperimentState`, the uniform 3-of-12 setup draw, and effect
application; `Game` exposes the terminal (`start_setup`,
`choose_experiment_trigger`, `choose_experiment_effect`, `toggle_experiment`)
gated on standing in the Laboratory, with `Phase.EXPERIMENT_PENDING` and
actions 319–326.

**Seven of the twelve base effects and one of the twelve base triggers are
live.** `draw_offers` samples the base pool uniformly and does not filter on
`implemented`, which is faithful to the game's own offer distribution but has a
consequence worth knowing while phases 2–3 are outstanding: only `immediately`
has a firing site, so a setup offers at least one live trigger 25% of the time
(`1 - C(11,3)/C(12,3)`). The rest configure an experiment that stays silent for
the day. Phases 2 and 3 are what close this — they add the draft-site and
interaction firing sites for the other eleven base triggers.

Filtering the draw to implemented records is not an option in the meantime:
with one live trigger there is nothing to draw three from.

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
