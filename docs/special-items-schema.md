# Special items: the data contract

`data/special_items.json` is the record of every special item in the sim, plus
the shared subsystem tables the item engine reads. This document owns **the
shape of that file and what its flags mean**. What each item and each subsystem
actually *does* is [`special-items-behaviour.md`](special-items-behaviour.md).

The file is **hand-maintained**. `tools/ingest_sheet.py` builds `rooms.json`
from the datamine and never touches this one, so there is no re-ingest path to
revert an edit here — and no round-trip test to catch a mistake either.

Rules about which source wins a disagreement are in
[`doctrine.md`](doctrine.md); rules about what belongs in data at all are in
[`architecture.md`](architecture.md); rules about how long a value lives are in
[`scoping-and-carryover.md`](scoping-and-carryover.md).

## The record

```jsonc
{
  "id": "lock_pick_kit",             // snake_case, unique across the file
  "name": "Lock Pick Kit",
  "kind": "standard",                // standard|special_key|contraption|showroom|armory|unique
  "tier": 3,                         // 1-5 Trading Post tier; null = untradeable
  "receive": true,                   // false: tradeable away, never offered back; absent = true
  "unique": true,                    // at most one held (false only for microchip)
  "persistence": "day",              // day|until_used|permanent — drives carry-over
  "spawn_rooms": ["archives", ...],  // room ids where it can lie on the floor
  "spawn_rooms_high_luck": [...],    // extra pool entries at luck >= spawn.high_luck_at
  "guaranteed_in": [...],            // room ids that ALWAYS hold it on first entry
  "requires_item": "torch",          // another item id that must be held first; null if none
  "effects": [{"tag": "lockpick", "rates": [...], "pity": 3}],
  "implemented": true,
  "meta": {
    "source": "https://blueprince.wiki.gg/wiki/Lock_Pick_Kit",
    "confidence": "datamined",       // datamined|wiki|inferred|placeholder
    "absent_spawn_areas": ["spiral"],// off-grid AREA ids the wiki lists as sources
    "blocked_on": null,              // implemented:false — what is missing
    "wont_implement": null,          // implemented:false — why it never will be
    "reachability": null,            // implemented:false — "inert" or "absent"
    "simplification": null,          // implemented:true — what is deliberately partial
    "notes": "..."
  }
}
```

Alongside `items`, the file carries the shared subsystem tables:
`spawn`, `dig`, `treasure_map`, `battery_pack`, `lost_and_found`,
`fabrication`, `contraption_lockout`, `trading`, `containers`, `ignition`,
`machines`, `mail_packages`, `freight_packages`, `planetarium_planets`, and a
file-level `_notes`. Each is described where its behaviour is —
[`special-items-behaviour.md`](special-items-behaviour.md).

## The four status flags, and why there are four

One boolean cannot carry the difference between *not built yet*, *never will
be*, and *built but partial*. Collapsing them left permanent exclusions sitting
in the backlog forever, looking like pending work.

| flag | set when | means |
|---|---|---|
| `implemented: false` + `meta.blocked_on` | something is missing that could be built | a blocker: names the absent system |
| `implemented: false` + `meta.wont_implement` | a decision was taken not to build it | not a blocker: names the reason to decline |
| `implemented: false` + `meta.reachability` | always, alongside either of the above | `inert` (obtainable, does nothing) or `absent` (cannot be obtained) |
| `implemented: true` + `meta.simplification` | the record works but a part is deliberately missing | the gap, stated on the record |

`blocked_on` and `wont_implement` are **mutually exclusive**, enforced by the
validator and pinned by a test. `wont_implement` is meaningless while
`implemented` is true, and also an error.

[`doctrine.md`](doctrine.md) owns the two rulings that make this work — that
`implemented: true` never means "complete", and that a disclosure must live on
the record it concerns. [`architecture.md`](architecture.md) owns why
`blocked_on` survived the proposal to derive implementation status from
registry membership: it carries a *reason*, which no registry can compute.

**A blocker decays faster than anything else in the file.** One record —
`microchip` — carried three successive `blocked_on` strings that were each true
when written and false within weeks (`outer_areas_not_modeled`,
`grotto_pedestal_chip_not_modeled`, `orindian_ruins_not_reachable`). A blocker
on a record whose feature is actively being built goes stale about as fast as
it is written. Two consequences, and the first is the one that costs work:

- **A `blocked_on` string is not evidence.** Re-derive it before building on
  it, and treat a precise-looking file:line citation inside one as a reason for
  *more* suspicion, not less — one such citation named a line that was wrong
  too, in a note whose three other claims were also false.
- The durable answer is a derived check, not better prose. That is what the
  registry validators wired into `tools/validate_data.py` are for.

**Deleting a record is not a bookkeeping change.** `env/obs.py` enumerates the
`items` array **positionally**, so removing an item shifts every later item's
index and invalidates a policy's learned inventory layout. An item decided
against stays in the file with `wont_implement` set; it is only ever removed
when the *concept* leaves the sim entirely (`diary_key`, `wind_up_key`).

## Provenance

Every record carries `meta.source` and `meta.confidence` from the standard
ladder `datamined > wiki > inferred > placeholder`, and
[`doctrine.md`](doctrine.md) owns what that ordering licenses.

Two limits on it are specific to this file and worth knowing before leaning on
a label:

- **There is no repo-datamined item data.** `tools/raw/` holds a room table and
  a wiki snapshot; neither carries item spawn locations or Trading Post tiers.
  Every tier claim traces to the wiki's own DataMinedBox. **Do not describe
  them as repo-datamined** — the datamine-outranks-wiki rule does not bite
  here, and the wiki is the best available authority. `confidence: "datamined"`
  is therefore **an error anywhere in this file**, enforced by
  `validate_data.py::find_datamined_item_confidence_findings` rather than left
  to prose: nothing in the engine branches on `confidence`, so a wrong label
  changes no behaviour and fails silently, which is exactly how it drifted onto
  six records — four items plus the `containers` and `mail_packages` tables —
  each citing a wiki URL as its own source.
- **`meta.confidence` did not track accuracy when the spawn tables were last
  measured.** Against the wiki's `Locations` field, items labelled `wiki` were
  59% complete while the two labelled `datamined` — the top of the ladder —
  were 49%, the worst band. The label inverted. The tables have since been
  swept and are pinned by the guard below, but the finding is kept because it
  softens the provenance ordering the whole repo leans on: **a `datamined`
  label is a claim about where a value came from, not about whether it is
  right.**

## Spawn tables

Four fields decide where an item can be found, and keeping them apart is the
point:

- **`spawn_rooms`** — loose on the floor of a drafted room. Purchasability is a
  separate concept in `shops.json`; the wiki's single `Locations` field mixes
  the two and this file does not. [`doctrine.md`](doctrine.md) owns that rule.
- **`spawn_rooms_high_luck`** — additional pool entries that open at
  `spawn.high_luck_at`. On the wiki these are the `!`-prefixed entries.
- **`guaranteed_in`** — always present on first entry, granted before any roll.
  An item the wiki calls guaranteed belongs here, never in `spawn_rooms`.
- **`meta.absent_spawn_areas`** — sources the wiki names that the sim models as
  **off-grid area-graph nodes** rather than draftable rooms.

`absent_spawn_areas` is validated in both directions: an id that is a room in
`rooms.json` is an error (it belongs in `spawn_rooms`), and an id that is
neither a room nor an area node is an error too. **Its limit, confirmed by
mutation: the check catches a nonexistent id but not a wrong-yet-valid one.**
Naming the wrong real node passes validation. That class of correction comes
from research, not tooling.

### What a spawn table controls, measured

`spawn_rooms` inverts into `spawn_pool_by_room` and is consumed at exactly one
site: per extra-item slot, roll `spawn.special_share`, then pick **uniformly**
from that room's pool. So **the table controls WHICH item you get, never HOW
MANY.**

A/B over 3000 seeded days per variant: total special finds per 1000 days
**1550 → 1550, unchanged**, while per-item rates move hard (`car_keys` 6.6×,
`vault_key_149` 0.40×). Adding a room takes mass *from* the other items sharing
that room — total flow is conserved. **No item is unobtainable because its
table is short**; every diverging item has another grant channel.

That is what makes a spawn-table divergence a *distribution* finding rather
than a reachability one — and also what makes it a live distribution shift for
any trained checkpoint, since the tables were what it learned against.

### The regression guard

`tools/raw/wiki_item_locations.tsv` holds the verbatim `|Locations=` field per
item with its fetch date and URL, and `validate_data.py` diffs every table
against it, honouring `!` as the high-luck tier. Each exemption must name the
file and channel that models the item instead.

**The honest limit, recorded with it:** the snapshot pins the wiki as of the
fetch date, so it catches sim drift and never wiki drift. Refreshing it must be
a deliberate act with a visible diff.

**And an exemption needs a necessity test, not a liveness test.** A test must
remove each exemption and assert the checker then flags that pair. The
question "is the thing this exemption names still there?" answers yes forever;
the question that matters is "would the checker still fire without me?" Any
exemption, allowlist or suppression list in this repo needs the second one, or
it accretes entries that are individually defensible and collectively dead.

## What `validate_data.py` enforces

Errors, not warnings, except where noted:

- ids unique; `kind`, `persistence` and `meta.confidence` drawn from their
  valid sets; `tier` is 1–5 or null.
- `receive: false` **requires a tier** — a give-only item with no tier is
  unreachable by the trade graph and therefore meaningless.
- every `spawn_rooms` / `spawn_rooms_high_luck` / `guaranteed_in` id resolves
  against `rooms.json`; `requires_item` resolves against this file and may not
  be self-referential.
- `meta.absent_spawn_areas` resolves against `areas.json` and must **not** name
  a room.
- the four status flags above, including their mutual exclusions.
- `lost_and_found.pool`, `fabrication` inputs and outputs, container loot
  grants, `ignition` target and tool ids, and `machines` item ids all resolve
  (the token `die` is a resource, not an item, and is allowed in the pools that
  take it).
- dig table weights sum to ~100 and every outcome `kind` is known.
- `ignition.meta.absent_targets` entries must genuinely be absent from both
  `rooms.json` and `areas.json`, so the list cannot rot silently if such a room
  is later added.
- effect tags outside `KNOWN_ITEM_EFFECT_TAGS` are a **warning**, so partial
  data coverage degrades gracefully rather than failing the build.

The validator also prints a census on every run — item count, unimplemented
count, and deliberately-not-modelled count. **Re-measure there rather than
trusting a number written in a document**; the counts move as records land.

### What the census does not measure

**There is no text-versus-model fidelity audit on the item side at all.**
`find_divergences` is entirely room-scoped, and item records carry no
`meta.effect_text` field — verified across every record — so nothing compares
what an item is published to do against what it does. The item side has only a
registry-consistency check, an empty-`effects` census, and the hand-maintained
`implemented` flag. **So an unimplemented count is a count of records whose
flag says so, never of records verified complete**, and a half-implemented item
is invisible: `morning_star` sat `implemented: true` with a correct smash and a
missing star grant until someone read the wiki line.

Two findings shape any detector built for this, and both cut against the
obvious design. **Their counts are a snapshot of one scan — re-run it rather
than trusting the numbers here; what does not decay is the shape of each
argument.**

- **`effects` cannot be the basis.** An AST scan over the functions that look a
  tag up on a `SpecialItem` found **7 of 28 item tags never read as tags at
  all** — for six the tag string merely coincides with the item's own id while
  the behaviour lives in a per-item module keyed on `ITEM_ID`. An item can be
  fully modelled with an inert tag or partly modelled with a live one, and the
  array states neither. A tags-versus-registries detector would flag six fully
  modelled items and clear the one real gap.
- **The room audit's "text exists, zero modelling" rule ports badly**; it fires
  only on total absence, so every partial gap passes it. The rule that does
  work on items is the sibling comparison — *identical modelling to a sibling
  but differing published text means the differentiating step was never
  authored*. Across all records there are exactly three identical-`effects`
  groups, so it yields two flags on day one and needs no triage phase.

### The prose notes are validated too

`meta.notes` and the file-level `_notes` are checked against the data they
describe wherever the claim is mechanically decidable: a note claiming a field
is empty is an error if the field is populated, and a note quoting a count from
the wiki snapshot is an error if the snapshot disagrees. This exists because
prose notes in this file have repeatedly outlived the condition they describe.

## Deliberate divergences

- **A tag lives in data or in code, never both.** Several effect tags that were
  once in this file are now `ItemCapability` registrations in
  `engine/effects/items/<id>.py` and were **deleted** from the data, not left
  alongside. See [`architecture.md`](architecture.md) — the same defect was
  fixed three times before the rule stuck.
- **`meta.simplification` is a required disclosure but is not machine-checked.**
  The validator enforces the `implemented: false` flags; nothing yet asserts
  that a record with a known partial gap carries a `simplification`. The rule
  in [`doctrine.md`](doctrine.md) is currently held by review, not by tooling.
- **`meta.effects` is uninformative about whether an item is inert.** An empty
  `effects` array says nothing once behaviour can live in a registration
  instead — and the item census reports "not found in those registries" rather
  than "genuinely inert", because the registries cannot see hand-written
  branches in `game.py`. See [`architecture.md`](architecture.md).
- **Four channels of the spawn-table guard are exclusions, and each is a
  modelling claim.** Shop rooms (Commissary, Locksmith, Lost & Found, Trading
  Post) are excluded because they are modelled through `shops.json` stock and
  the Trading Post graph, not the spawn pool — adding them to `spawn_rooms`
  would double-count. Non-room mechanic tokens (Dig Spot, Trunk, Package,
  Locker, Crate, Spiral, Dartboard, Experimental Setup) are excluded because
  they are not rooms. Three items whose wiki location is a single fixed spot
  (`key_8`, `basement_key`, `master_key`) are excluded wholesale. And
  `guaranteed_in` counts as coverage in the *missing* direction but never in
  the *extra* direction — a guaranteed find is a stronger channel than a roll,
  but it names a mechanic the wiki's `Locations` field generally does not list
  at all, so comparing it in that direction would be a category error.
- **The Dartboard is an unmodelled source; the Spiral is not a *spawn* source.**
  The Dartboard is the likely origin of a `keycard` spawn entry that was never
  on the wiki's list, and is excluded as a mechanic token rather than modelled.
  The Spiral appears as a wiki location for eleven items — for `basement_key`
  it is the *only* one — and those grants are modelled, but they belong to the
  Spiral of Stars constellation's word-tier payout (`data/constellations.json`,
  its `special_item_pool`) rather than to any room's spawn table. It stays
  excluded as a mechanic token for exactly that reason: those items arrive
  through an activation, never off a floor.
