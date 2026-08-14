# Laboratory / Experiments

The Experiments mechanic: its triggers and effects, the draw that sets one up,
the data shape that transcribes it, the availability layer that gates
individual records, and the table of every number the wiki does not publish.

Code: `engine/experiments.py` (registry, setup draw, trigger detection, effect
application), `data/experiments.json` (the transcription),
`tools/validate_data.py` (referential integrity and shape).

Source: fetched directly from `blueprince.wiki.gg`; each record cites its own
`meta.source`. There is no separate `docs/research/` digest for this subsystem
the way there is for items — the wiki pages are short enough that the data file
cites them directly.

This document follows the idiom of
[`special-items-schema.md`](special-items-schema.md) and
[`special-items-behaviour.md`](special-items-behaviour.md): a data contract
plus the rules the engine enforces over it.

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
- **Blessing of the Tinkerer cross-triggers.** While that blessing holds, an
  active experiment also fires whenever a **Mechanical Room** is drafted,
  independent of the chosen trigger. Implemented in
  `effects/rooms/shrine.py`, which calls `experiments.trigger_success` on
  each Mechanical draft while the blessing is active. The four blessing/curse
  checks there are independent, so a room that is both Shop and Mechanical
  fires more than one.
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
      "implemented": true,
      "meta": {
        "source": "https://blueprince.wiki.gg/wiki/Experiments/Triggers",
        "confidence": "wiki",
        "blocked_on": "...",            // required while implemented is false
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
the Satellite Dish data packet adds, sample-eligible once
`cfg.satellite_dish_unlocked` is set). A `packet`-pool record's own
`implemented` flag governs whether it has a trigger/effect detection or apply
site at all; `pool` and `implemented` are independent fields, so a packet
record can be — and six currently are — `implemented: false` regardless of
whether the packet pool itself is open.

### `availability`

A tagged object describing when a trigger/effect may be drawn at all, or
`null` when there is no gating. Every `kind` carries the wiki's own wording
verbatim in a `text` field, so the structured fields are a parse of that text,
not a paraphrase:

| `kind` | fields | records | enforced |
|---|---|---|---|
| `day_gate` | `day`, `veteran_bypass` | `security_door`, `drawing_room_drawn` | yes |
| `day_or_packet_gate` | `day`, `or_packet` | `mail_room_letter` | yes |
| `cross_column_exclude` | `excludes_trigger_id` | `spread_dig_spots` | yes |
| `room_drafted_gate` | `room_id`, `veteran_bypass` | `archived_floorplan` | no |
| `item_obtained_gate` | `item_id`, `veteran_bypass` | `trash_while_digging` | no |
| `resource_or_gate` | `resource`, `amount`, `or_veteran`, `or_packet` | `gain_star` | no |
| `room_present_gate` | `room_id`, `checked_at` | `pantry_fruit` | no |
| `cross_column_probability` | `removes_effect_id`, `chance_pct` | `map_view` | no |
| `value_variant` | `condition`, `swap_text` | `reservoir_water_level` | no |

The unenforced kinds divide into two groups, and the distinction matters
because only one of them is a gap:

- `room_present_gate`, `cross_column_probability` and `value_variant` sit on
  records that are permanently `implemented: false` and therefore can never be
  offered. Enforcing them would gate something unreachable.
- `room_drafted_gate`, `item_obtained_gate` and `resource_or_gate` sit on
  **live** records. Each needs persistent state the sim does not track yet (an
  Archives-drafted-ever flag, a Shovel-obtained-ever flag, a star threshold
  read at draw time), so `archived_floorplan` and `trash_while_digging` are
  offerable before their prerequisite, and `gain_star` is offerable regardless
  of stars, veteran mode or packet. **These are real, and the default config
  hides them**: `veteran_mode` defaults to true, and the first two carry a
  veteran bypass, so under shipped defaults they would be no-ops even if built.

The two `cross_column_*` kinds are the pairs that reach across the
trigger/effect split. `tools/validate_data.py` resolves both id references
against the file's own trigger/effect id sets, so a rename on one side that
forgets the other side is a validation **error**, not a silent drift.

`cross_column_exclude` is enforced in `_effect_offerable`, and its enforcement
**forces an ordering** in `draw_offers`: the 3 triggers must be sampled before
the effect pool is filtered, because the exclusion reads which triggers were
actually *offered*, not which were eligible. That ordering costs nothing — the
triggers were already sampled first — it only moves the moment the effect pool
is filtered.

**No availability filter may ever shrink a pool below 3.** `draw_offers`
asserts it on both sides. The day gate can drop at most 2 triggers, and the
effect-side filters at most 2 effects (`mail_room_letter` plus at most one
cross-column exclusion), so the bound holds with or without the packet pool
appended.

### `cap`

A hard, wiki-*stated* limit on how many times the record's own effect actually
applies — `3` (chests), `10` (map views), `16` (letters), `17` (Entrance Hall
trunks), `40` (tunnel crates) — or `null`. `cap` lives on both triggers and
effects, and the two mean different things once past the limit, enforced at two
different sites:

- A **trigger's** `cap` is checked in `trigger_success` and suppresses the
  *whole fire*: the trigger no longer succeeds at all, the success count stops
  advancing, and the trigger's own step loss is not charged either.
- An **effect's** `cap` is checked in `apply_effect`, never in
  `trigger_success`: the trigger it is paired with keeps succeeding and only
  the effect goes silent. This matches each id's own wiki wording ("will no
  longer have any effect" / "never offered again" — neither says the *trigger*
  stops firing).

**A capped trigger counts fires, not qualifying events**, so pausing the
experiment preserves charges. The success count only ever increments inside
`trigger_success`, so a qualifying event that arrives while paused is
suppressed without spending a charge.

Approximate figures the wiki hedges with "around" or "approximately" are **not**
encoded as `cap`; they live in `meta.notes` instead, because a `cap` field
implies an exact enforceable number and these explicitly are not that. The dig
spots effect's Conference Room branch *does* carry a wiki-exact limit ("up to
50 dig spots... after 17 triggers"), but it is still not the top-level `cap`:
`cap` counts successful *applications*, while this branch's limit is a spot
*total* (17 applications of 3 spots each would be 51, one over the stated 50),
so it lives in `magnitude.conference_room_spot_cap` and is enforced against the
running spot count, clamping the final batch rather than overshooting.

### `magnitude`

Structured numbers the wiki gives directly (amounts, percentages, room/step
counts) — omitted entirely from a record when the wiki gives no numbers at all.
Six specific concepts the wiki mentions but never quantifies get their
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
- **Dig-spots effect**: never offered when the trash trigger is offered.
- **Map trigger** offered ⇒ the "set steps to 40" effect has a 95% chance of
  being removed from the effect pool that same setup.
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

The security door trigger's own hedge — that it *"occasionally triggers an
additional time, possibly due to a bug"* — is recorded the same way, as a
`null` magnitude with the gap in `meta.notes`. The wiki gives no rate.

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

These stay out of scope permanently, because the concept they describe doesn't
exist in this simulator or targets a system that is out of scope on its own
terms:

- **The 40-second real-time trigger** and **the map-view trigger** — this
  simulator has no wall-clock and no interactive map-viewing action; both are
  meaningless here.
- **The setup-menu reroll timing exploit** — revisiting the Experimental Setup
  menu before committing lets a player reroll the three-of-each draw; this is
  a UI-timing quirk, not a data rule, and has no analogue in a turn-based sim.
- **Radiation level** — the hidden daily counter that experiment successes
  feed, gating the Shelter terminal. Shelter and the Grounds are out of scope.
- **Dare Mode** — an alternate, harder experiments ruleset on its own wiki
  subpage.
- **Research Logs** — an in-fiction log of experiment activation history; not
  a mechanical system.
- **Packet Management** — the wiki's own ≥8-of-20 selection screen. Every
  `implemented` packet record becomes sample-eligible the instant the packet
  flag is set. This is a deliberate simplification, equivalent to assuming the
  player always enables the maximal legal set, and not a partial implementation
  of the selection screen.
- **The 16 letters' contents.** `mail_room_letter` is a pure delivered-count
  bump. The letters are flavour — safe codes, a network password, a puzzle
  solution — and the assumed-solved doctrine already grants what they convey.
  See [`doctrine.md`](doctrine.md); this is the same reasoning as the
  Speakeasy.

**Blessing of the Tinkerer is *not* on this list.** It was once, on the ground
that it is a global modifier on the subsystem rather than a per-record rule.
That reading was reversed: the blocker the deferral rested on ("needs the
experiments subsystem") no longer exists, and the cross-trigger is built. If
you find a source still calling it never-modelled, that source is stale.

## What is built

**All 12 base triggers and all 12 base effects are live.** Of the 8+8 packet
records, **6 triggers and 4 effects** are live; the six inert ones are
permanently so, each for its own verified reason:

| record | why it stays inert |
|---|---|
| `speed_40_seconds` | no wall clock in this simulator |
| `map_view` | no interactive map-viewing action |
| `pantry_fruit` | no Pantry-stocking mechanic |
| `reservoir_water_level` | no `reservoir` **room** — it is an area node only |
| `remove_tunnel_crate` | the Crate Tunnel is owner-ruled out of scope |
| `permanent_lockpicking_skill` | no lockpicking-skill stat exists |

The Laboratory terminal is a player-operable action set — start setup, choose a
trigger, choose an effect, toggle pause — gated on standing in the Laboratory,
with its own pending phase. [`rl-environment.md`](rl-environment.md) owns the
action-space register.

### The packet pool opens at load time, not draw time

`ExperimentsRegistry` builds `packet_trigger_ids` / `packet_effect_ids` as
`pool == "packet" and implemented`, and `draw_offers` appends them to the base
tuples only while `cfg.satellite_dish_unlocked` is set. The base tuples carry
**no** `implemented` filter, and must not start carrying one: every base record
happens to be implemented, so the distinction never had to exist there, and
adding it would change base sampling as a side effect of a packet change.

**The filter belongs at load time, and that is the point.** Appending packet
ids to the base tuples is the obvious one-line implementation and would have
made six dead records drawable and silently inert — an agent could select an
experiment that does nothing and never learn otherwise. Filtering at load gives
every consumer a safe-by-construction id set instead of relying on draw-time
diligence.

**Ordering: contents before the gate.** The packet triggers and effects got
their firing sites *before* the flag was wired. Flipping the gate first would
have made sixteen records drawable while fifteen did nothing — reachable
content that silently does nothing, the inverse of the unreachable-feature
failure and just as invisible.

With the flag unset, both sampling pools are the unmodified base tuples, so
every RNG draw is unchanged from before the gate existed — verified
byte-identical across 500 seeds and pinned by a seed-0 regression test.

### The draw does not filter on `implemented`

A setup can still pair a live trigger with a silent effect. Every base record
now has a firing site, so this is narrow, but it is not closed. Filtering the
draw to fully-implemented records remains future work.

The owner ruled **against** the cheaper alternative of filtering the four
then-unimplemented base effects out of the draw, and the reason generalises: a
player who can be offered — and pick — an experiment that does nothing is the
clearest failure of the "features are built to be PLAYED" bar in the subsystem
(see [`doctrine.md`](doctrine.md)), and a day replay containing a chosen no-op
experiment does not read clean.

### Where triggers fire

Trigger detection is wired at the site the condition actually occurs, the same
shape the item hooks use. Three rules govern those sites:

- **Draft triggers fire between draft counting and the placement hooks.** Both
  bounds are wiki-stated: after the grid write, so the triggering room counts
  itself; before the placement hooks, so the Weight Room halves the
  experiment's steps rather than the reverse.
- **Outer-room drafts do not fire draft triggers.** Outer rooms are never on
  the grid, so the counting effects already exclude them. The wiki says outer
  rooms count only under a Blessing, and Blessings of that kind are out of
  scope.
- **A room-id literal belongs in a room module, never in this engine module.**
  The Drawing Room trigger binds through `effects/rooms/drawing_room.py` as a
  one-line hook on the hand-dealt event, delegating here. The hand-dealt hook
  already ran at all three deal sites, so no new call site was needed. See
  [`architecture.md`](architecture.md) for the standing invariant.

Individual scoping calls worth keeping because each looked obviously the other
way first:

- **The Hovel kills the `gems_spent` trigger** (wiki: *"this trigger becomes
  useless with it on the estate"*). This engine models the Hovel by paying gem
  costs in steps while the effective cost still returns the gem number, so a
  naive cost check would fire on **every** expensive draft — the exact opposite
  of the published behaviour.
- **The Stopwatch's gem waiver does not count as spending.** Unpublished, and
  consistent with the Emerald Bracelet rule the wiki does state.
- **The "next 3 times you unlock and open a chest" trigger counts trunks
  only** — not locked lockers, not free lockers, not the Garage car trunk, not
  Mechanarium compartments, and not Vault deposit boxes. The wiki uses "chest"
  to mean trunk. Including locked lockers would let a single Locker Room visit
  burn the whole 3-fire cap deterministically, since that room holds 17 in one
  cell. The gate reads `kind in ("trunk", "chest")` so it stays correct if a
  room ever gets a real chest, and it fires only after the opened-count bump,
  so a failed open never counts.
- **The "for each Bedroom after your second" trigger counts all of today's
  Bedrooms**, not only those drafted after the experiment started. The wiki's
  live text says the opposite, but that sentence has never been grammatically
  clean — created as "before or starting", repaired to "before or after" by a
  later grammar edit that left "does matter" untouched — so a dropped "not" is
  at least as plausible as a deliberate "does". This is the harsher reading: a
  bedroom-heavy morning can burn the grace before the player reaches the
  Laboratory. It reads the same bedroom-equivalents tag the Bunk Room uses, so
  no room id is hard-coded.
- **The `security_door` trigger fires from two sites**: drafting *through* a
  security doorway, and drafting *into* a room whose own door converts an
  already-rolled security segment to open. Merely walking through does not
  count.
- **A hidden Drawing Room counts as drawn.** The trigger fires on the floorplan
  being dealt into the hand, concealed or not — concealment is about display,
  not the deal. **Known consequence, accepted: this leaks the concealed
  option's identity** through the success counter the observation exposes.
  Under the Archives the leak is *total*: the Archives conceals exactly one
  slot, a hand holds at most one Drawing Room, and no other trigger fires at
  deal time, so a counter tick plus two visible non-Drawing-Rooms identifies
  the hidden card with certainty. Suppressing the counter would not close it,
  since the effect's own result is observable too.
- **Two independent code paths open the same Antechamber lever.** The Weight
  Room's south lever and the Greenhouse's Broken Lever target the same segment
  through wholly separate guards, so a Weight-Room-then-Greenhouse day would
  double-count a "different lever" trigger. Tracked with a per-day distinct
  **set**, not a counter. **A counter would have looked correct and been wrong
  only on the one day ordering that matters.**
- **The Upgrade Disk reader is this codebase's "terminal"**, deliberately
  renamed to dodge a name collision (see
  [`upgrade-disks-design.md`](upgrade-disks-design.md)). The
  `terminal_access` trigger is scoped to a successful disk insert, and tracks
  which terminals were used as a per-day distinct set, since several disks can
  be inserted at one terminal.
- **The `apples` trigger fires once per apple**, after that apple's own steps
  have been granted. The ordering matters: a same-day `set_steps` effect must
  land last rather than be overwritten by the apple's own steps, per the wiki's
  stated interaction. One call granting several apples fires once per apple,
  matching apples being eaten one at a time.
- **The trash trigger fires on a `junk` dig outcome only** — `nothing` never
  counts, per the wiki. Both dig tables fold Scraps of Paper into a second junk
  row rather than a distinct kind, so a later patch's addition needed no
  separate handling. Because digging drains a whole cell in one call, this
  trigger fires in bursts.

### Termination is checked by the action, never by the effect

No step-draining effect or trigger calls the termination check itself. Each
relies on whichever action method is already about to check termination as its
own last statement. **Putting the check inside `trigger_success` would fire
mid-placement, against a half-constructed grid, before the placement hooks that
still have to run** — a worse bug than the one it fixes.

The check was therefore added at four specific action sites rather than
blanket-applied, each justified by a new fire site. The redraw one closed a
real gap: an experiment could drain steps to zero inside a redraw and the day
would not end until some later navigation action noticed.

**One identified gap remains, and it is pre-existing.** Disk insertion and
upgrade selection never check termination at all, so a day ended by a
step-draining effect while the `terminal_access` trigger is configured is
caught one action late — by the environment's no-legal-action fallback — and
reported under the wrong reason. Deliberately not patched, for the reason
above.

### The effects that were subsystems in costume

Four base effects were the last to land and each needed real machinery:

**`entrance_hall_trunk`** adds a trunk to the Entrance Hall, capped at 17 per
day. **The 17 is a DAILY maximum and nothing carries over** — owner ruling from
play, correcting the natural reading of the wiki's "maximum of 17" alongside a
predetermined spawn order across four walls, which reads like a lifetime cap on
numbered physical objects. It is not. So there is no config field, no
carry-over entry and no chain merge: the per-day item state is rebuilt with the
game state every day and already gives the right reset for free.

The counter is named for the **room**, not for this experiment record, because
the wiki treats The Twins constellation as sharing the same 17-trunk limit
("identical to triggering this effect twice"). The Twins now uses it: both
sources call `SpecialItemsState.add_entrance_hall_trunks`, which is the single
place the cap is compared, and both read the number from **this** record —
`experiments.py::entrance_hall_trunk_cap` is the accessor, so the constellation
does not restate 17. `_effect_apply_count` deliberately does **not** list
`entrance_hall_trunk`: routing it through the generic experiment cap gate would
have meant a second copy of the check on the constellation side.

A Twins pair that would overshoot lands **partially** rather than being
refused — with one slot left, an activation adds one trunk, not zero. Note that
The Twins alone cannot reach the cap in a day: only the first seven night skies
hold constellations, so seven activations is 14 trunks against a cap of 17.

Adding a container to a room that has no static container entry is what forced
container counts to resolve **per cell** rather than per room — including the
re-entrant case where opening one trunk adds another to the same room mid-call,
which is safe because the container kind and its loot config are captured
before the trigger fires. It also fixed the observation's container plane,
which had been reading the static table directly and could not see the
Mechanarium's own compartments either.

**Still open:** whether trunks appear in the Outer Entrance Hall too (the wiki
says they do under the Shrine's Monk blessing). Outer rooms have no grid cell,
so a cell-keyed overlay cannot reach them.

**`add_aquariums`** injects copies of a **second, distinct** Aquarium floorplan
— the experiment-added copy, which the wiki gives its own placement
restriction — then moves both it and the base Aquarium to the Commonplace
bucket. The injection must run before the rarity move, because injection always
inserts into a room's *static* bucket and ignores a dynamic override.

Three premises behind the original scoping were wrong, and all three are worth
keeping because each looked obviously true:

- **The priority-draw resolver is not a first-match loop.** It rolls every
  entry independently, so the compounding this effect needs already works. What
  was missing was only day-scoping of an entry, and the condition idiom for
  that already existed. See [`drafting.md`](drafting.md).
- **There is no deal-time rarity read**, so a "rarity override channel" is the
  wrong shape. A card's effective rarity **is** the deck it sits in, so setting
  a Dynamic Rarity is a *card move* between buckets, which the repo already
  does elsewhere. **A mid-day deck rebuild would be actively unsafe** — it
  resets all eight cursors and silently discards the day's upgrades,
  injections and Conservatory re-rolls.
- **A new room record is the retrain trigger, not the effect.** The observation
  uses the room count as a bound and a room's index is its position in file
  order, so a record inserted mid-file shifts every later room's index and
  invalidates the learned room embedding far more deeply than a bound change.
  It must be appended at the end, through `tools/supplemental_rooms.json` —
  see [`doctrine.md`](doctrine.md) on why editing `rooms.json` alone for a
  supplemental-sourced room is silently reverted.

This effect **deliberately breaks the one-copy-per-room invariant** for the
experiment copy specifically, never the base Aquarium, following the existing
Tunnel-chain exception rather than a second global waiver. Without the waiver
every injected copy shares one id and the grid caps at two Aquariums; with it,
the grid is the only remaining bound — and that bound was the real risk, since
an Aquarium is a Shop, Red, Hallway and Bedroom room at once, so drafting one
while any of those four triggers is configured re-fires the effect. That is the
wiki's own designed loop. **It cannot recurse within one placement**, because
the effect only mutates deck and rarity state and never places a room; **across
placements it is bounded by the finite grid**, since each fire only makes more
Aquariums draftable. A test drives it to exhaustion across every legal cell.

**`spread_dig_spots`** builds the Conference Room branch only. With a
Conference Room on the estate it adds the wiki's stated usual batch of 3 dig
spots to that cell each firing, on the same per-cell overlay the Cloister of
Veia writes, up to the wiki-exact 50-spot total; without one the call is a
no-op. The wiki's **Grounds branch** (dig spots outside the house) needs an
off-grid dig-spot concept this simulator does not have and stays unbuilt — the
record is `implemented: true` anyway, because the Conference Room branch is a
complete self-contained behaviour, and its `blocked_on` names the Grounds gap
specifically.

This effect could not ship before `cross_column_exclude` was enforced. It also
narrowed a safety argument elsewhere: the per-spot dig loop's fixed spot count
can never grow mid-loop, and the reason is no longer "this effect is
unimplemented" but that the two records **can never even be offered together**.

Two further wiki-described pieces are recorded and not built: the **Dovecote
birdbath sub-effect** (blocked on the same missing off-grid concept) and the
**Blessing of the Chef's "Mudslide Icecream"** dish (blocked on the Blessing
system). Also not modelled, at this engine's per-cell granularity: the wiki's
"first five appear on the conference table, the remainder on the surrounding
floor" placement detail, which has no mechanical consequence here.

**`mail_room_letter`** is a pure delivered-count bump; see "Deliberately never
modelled" for the letters themselves. Its delivered count is **cross-day and
save-scoped** — seeded from config at reset, reported by the carry-over dict,
carried by the day chain, and deliberately absent from the attempt wrap. That
is what makes the wiki's "16 ever, never offered again" rule genuinely
enforceable rather than per-day.

### The packet effects

Four are live. Three notes are worth keeping:

- **The unseal effect deliberately does NOT credit the lever trigger.** It
  opens the segment directly rather than going through the north-door wrapper,
  and never calls the lever hook. Both of those exist to attribute a genuine
  *player* lever pull to the `antechamber_lever_pull` trigger and to the
  environment's own reward flag. **Routing an unrelated experiment effect
  through them would be misattribution wearing the costume of code reuse** —
  the effect would silently advance a trigger the player never fired.
- **It picks the first still-sealed segment in west/south/east/north order,
  copied verbatim from the sealing loop that already exists.** The wiki says
  west/east/south "appear to be preferred" over north with no numbers, and the
  order among the first three is unstated either way, so this resolves the
  unstated half by reusing the one ordering already in the codebase rather than
  inventing a second one.
- **Two-part effects apply in the stated order and the second half is
  unconditional.** The halve-steps effect floors the halved count (7 becomes 3,
  not 4) and **grants its dice even when the step loss alone ends the day** —
  the alternative silently drops the reward on exactly the days it matters
  most. The random-item effect grants the item *before* zeroing keys, pinned by
  a test that exploits a seed whose draw lands on "key", so a reversed order
  would leave the final count at 1 rather than 0.

**No invented magnitudes.** The random-item effect grants from the shared
extra-item table on its existing RNG label — reused, not invented — because the
wiki's true pool is a live Cargo query and `magnitude.item_pool` stays null.

## Validation (`tools/validate_data.py`)

- Every trigger/effect `id` is unique, checked across triggers and effects
  together, not just within each list.
- `pool` ∈ `{base, packet}`.
- Exactly 12 base triggers, 12 base effects, 8 packet triggers, 8 packet
  effects — a count drift is an **error**, not a warning.
- Every `availability.room_id` / `rooms[]` entry resolves against
  `rooms.json`; every `availability.item_id` resolves against
  `special_items.json`.
- Every `availability.excludes_trigger_id` / `removes_effect_id` resolves
  against this file's own trigger/effect id sets.
- `cap`, when present, is a positive int.
- `availability.chance_pct` and `magnitude.priority_draw_chance_pct` entries
  fall in `[0, 100]`.
- `implemented: false` requires `meta.blocked_on` — the same rule
  `special_items.json` enforces.
- `meta.confidence` is one of the standard four values.

These are **errors**, not warnings: a referenced id that fails to resolve is
exactly the silent failure this tool exists to catch.

## Deliberate divergences

- **Packet Management is not modelled**, so the packet pool is wider than a
  real player's would be. See "Deliberately never modelled".
- **The draw does not filter on `implemented`.** A live trigger can still be
  paired with a silent effect. Known, narrow, and not yet closed.
- **Three availability kinds sit unenforced on live records**
  (`room_drafted_gate`, `item_obtained_gate`, `resource_or_gate`), each needing
  persistent state that does not exist. Under shipped defaults `veteran_mode`
  is true, which bypasses two of the three anyway — so the gap is real but
  currently invisible. Do not read the default's silence as enforcement.
- **The Laboratory room's own effect text carries no effects tag in
  `rooms.json`**, so it still reads as an unmodelled room to the room-fidelity
  audit even though the whole subsystem behind it is built. The audit's
  worklist entry is about the room record, not the mechanic.
- **`spread_dig_spots` is `implemented: true` with half its wiki behaviour
  unbuilt.** That is the correct flag, not a lie: `implemented` means
  *reachable and functional*, and the Grounds gap is disclosed on the record.
  See [`doctrine.md`](doctrine.md).
- **The Conference Room spot cap is enforced against a spot total, not against
  the generic `cap` field.** The two count different things and conflating them
  overshoots by one spot.
