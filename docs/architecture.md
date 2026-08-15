# Architecture: what lives in data, what lives in code

One question runs through every design decision in this repo: **does this fact
belong in a JSON table, or in a Python module?** Getting it wrong in either
direction has cost real work — a tag duplicated in both places becomes a second
source of truth, and behaviour scattered across engine modules becomes
invisible to every audit that looks for it.

This document is authoritative for that boundary. Rules about *how long a fact
lives* are in [`scoping-and-carryover.md`](scoping-and-carryover.md); rules
about *which source wins a disagreement* are in [`doctrine.md`](doctrine.md);
rules about *how to work* are in [`process.md`](process.md).

## The doctrine: the engine provides capabilities, rooms declare effects

**Tabular data stays tabular; complex functions belong in code.**

That is the whole rule, and it settles a question that keeps re-opening in a
misleading form. The visible symptom is "two radically different paths for room
definitions" — some room behaviour in `rooms.json`, some in Python. The
tempting fix is to pick one file format. **That is the wrong layer.**

### `rooms.json` is not converted to Python

Four reasons, recorded so the question does not reopen:

- **It is generated.** `tools/ingest_sheet.py` builds it from the datamined
  dump. Converting it breaks the re-ingest path that absorbs a future datamine
  and carries `meta.source` / `meta.confidence` forward.
- **The content is densely tabular.** 170 rooms, with 46 carrying effects tags,
  plus flags, draft conditions, dig spots and guaranteed items.
- **`validate_data.py`'s cross-record schema and referential checks are natural
  over one document** and awkward over 170 modules.
- **`test_ingest_overrides.py`'s round-trip guarantee only exists because the
  data is data.**

There is a real inconsistency underneath the complaint, but it sits one layer
below where it first appears. It is not JSON versus Python. It is that Python
room behaviour was scattered across twenty engine modules while only a minority
of rooms had a discoverable module of their own. **The fix is an invariant, not
a file-format migration.**

### The three layers

1. **Data (JSON)** — tabular facts only. Room stats (rarity, layout, gem cost,
   category, deck copies, draft conditions, dig spots, flags) and subsystem
   tables (`shops.json` prices and stock, `locks.json` chances, container loot,
   `mail_packages`, `weights.json`, `priority_draws.json`). Generated from the
   datamine wherever it can be.
2. **Engine capabilities** — mechanisms that know nothing about specific rooms:
   drafting, locks, containers, commerce, digging, food, carry-over, terminals.
3. **Room modules** — one per room at `effects/rooms/<id>.py`, declaring which
   capabilities the room uses and with what parameters, plus anything bespoke.

**The invariant: no engine module may branch on a room id.** Everything
room-specific is a registration.

The Shop is the pattern-setter. Before the migration `game.py` read
`if room.category == "shop" or room.id == "workshop"` — the engine knowing
which rooms are shops. Under the capability model `shops.py` keeps the
mechanism, `shops.json` keeps the table, and each shop room module *registers*
commerce for itself; the Workshop's special case disappears.

### A registry keyed by room id, not a class per room

The alternative design — give every room a class derived from the JSON, with
`when_drawn` / `when_drafted` / `when_entered` / `when_room_drafted` hooks over
a base class — was researched and rejected. The diagnosis behind it was
accepted; the prescription was not. Three findings decided it, and each is
worth keeping because each looks obviously wrong until measured:

**The inheritance argument is refuted by the data.** Of the 56 upgrade variants
that have both a parent and an `effect_text`, **zero** share their parent's
text. Of the six variants that model nothing while their parent models
something, inheritance would be correct for exactly one — and
`empty_closet__ix41`'s text is literally "0 items", which would have silently
inherited the Closet's two. The historical bug that motivated inheritance was
*unauthored records*; inheritance would have hidden it behind plausible numbers
instead of exposing it as conspicuous zeros.

**Three costs the class proposal does not account for.** Six sites read
`room.effects` *generically* rather than executing it — including
`items.py::expected_yields`, which feeds both the greedy policy and the Play
tab — so opaque methods would need a duplicate second method surface. `Room` is
frozen and the `Registry` is shared across episodes, so room *instances* with
methods invite a per-episode state leak that room-keyed *functions* cannot. And
a base class would need roughly fourteen hooks to cover the five distinct query
signatures the engine already fires (classroom context, two different rotation
predicates, drafting-from-Library, placement legality, action masking), leaving
170 subclasses inheriting a dozen no-ops each.

**Performance is not a factor in either direction.** `effects.fire` measured at
**0.2%** of runtime (1,401 calls, 0.003s cumulative of 1.40s). The hot path is
`obs.encode` at 31% and `action_mask` at 27%. Any argument for or against this
design that leans on dispatch cost is arguing about the wrong 0.2%.

The deeper observation that makes the registry obviously right: **the codebase
had already converged on per-room handlers.** It just keyed them by a tag
string that was a synonym for the room, and routed the call through a JSON file
to get there — `solarium_weights`, `study_redraws`, `coins_per_deadend`,
`pay_gems_with_steps`. And **the JSON is a cache of a Python source of truth
already**: `EFFECT_MAP` and `EFFECT_OVERRIDE` are hand-authored Python dicts,
`rooms.json` is their build artifact, and `test_ingest_overrides.py` exists
solely to prove the two agree.

## The registries

Five registries live in `engine/effects/__init__.py`. All of them are populated
by import-time calls from modules under `effects/rooms/` and `effects/items/`,
and none of them can validate an id at registration time, because no `Registry`
exists yet when the decorators run.

| registry | primitive | shape |
|---|---|---|
| room handlers | `room_hook(room_id, Hook)` | decorator; one handler per (room, hook) |
| room capabilities | `provides(room_id, Capability)` | fact only |
| levers | `provides_lever(room_id, pull, cost)` | parameterised handlers |
| containers | `provides_containers(room_id)` | decorator returning a kind→count dict |
| item capabilities | `item_provides(item_id, ItemCapability, **params)` | **data only** |
| item handlers | `item_hook(item_id, ItemHook)` | decorator; returns a value |

`Capability.LEVER` taught the shape: **a plain boolean is not enough for a
capability that needs a per-room handler and a live cost query.** `COMMERCE`
gets away with a bare fact; levers need `pull` and `cost` functions. Expect any
capability with per-room behaviour or a live query to need parameterised
handlers too.

### The item capability registry is a fold, not a hook

`item_provides` declares only *the fact and its parameters*; the **engine owns
the fold** (`item_capability_sum`, `item_capability_any`). **No item module
registers a handler function for a capability.**

This is a deliberate divergence from `room_hook`, and the reason matters. A
room has a natural event boundary — the player standing in it — so firing a
handler there maps onto a real moment. **Items have no such boundary.** Item
behaviour is overwhelmingly "the engine is about to charge N; ask every held
item whether it changes N". Registering forty modules against a
constantly-firing hook would also make fold *order* implicit in import order,
where today it is visible as sequential lines of engine code.

Params are stored per `(item_id, capability)` rather than pre-flattened into
one number, which is what let the ordered chains below arrive later as sibling
functions over the same registry rather than as a redesign.

### The item hook registry needs arbitration; the room registry never did

The claim that "items have no natural event boundary, so they cannot use
handlers" was wrong and shaped two phases of design before it was challenged. A
payment, a move, a coin grant and a red-room effect are game events, and an
item handler on one is as legitimate as a room handler on `ON_ENTER`.

**The real difference is arity and arbitration:**

| | room handler | item handler |
|---|---|---|
| fire per event | exactly one | any number of held items |
| signature | `(game, room, context_room) -> None` | `(state, registry, *args) -> value \| None` |
| conflict | impossible | routine, and rule-bearing |
| order | irrelevant | decides the outcome |

`fire(game, room, hook)` is called with *the* room the event is about and
dispatches to that one room's handler. Two rooms never answer the same event,
so **the room registry never needed arbitration — the grid supplies exclusivity
for free.** Items have no such guarantee: a gem-cost modifier must produce one
number from N held items, and "only one waiver applies, no double-decrement" is
a game rule that something has to enforce.

So the conclusion is not "avoid handlers" but **"use handlers, plus the one
thing rooms never needed: explicit arbitration."** An item handler therefore
returns a value rather than running for effect, and `None` always means *this
item does not apply right now* — never a legitimate outcome.

Two arbitration shapes exist, and which one a hook uses is itself a game rule:

- **`fire_item_chain`** — first-match-wins. Items after the winner are never
  even queried, so a charge-consuming handler later in the tuple cannot fire
  once an earlier one has answered.
- **`fold_item_chain`** — an ordered fold. Every applicable item transforms the
  running value in turn.

Unlike `room_hook`, an item handler is called on every fire regardless of
whether the item is held; deciding that is the handler's own context predicate,
exactly like a room category or a rank check.

### The priority tuples live in engine code

One named, ordered, engine-owned tuple per `ItemHook`, all declared together in
`engine/special_items.py` — **never a `priority=` number on the registration
itself, which would scatter the total order across the very modules it is
supposed to rank.**

Reading the tuples reads the rules:

- `GEM_COST_PRIORITY` — Emerald Bracelet (unconditional) before Hall Pass
  (conditional). Only one waiver, ever.
- `MOVE_STEP_COST_PRIORITY` — Hall Pass first, so a free hallway-to-hallway
  move never touches a counter; then Stopwatch, so an active timer is spent
  down before distance-based Running Shoes gets a turn.
- `COINS_GRANTED_PRIORITY` — Lucky Purse before Coin Purse, because Coin
  Purse's interest accumulator must not advance while Lucky Purse is held.
- `GEM_PAYMENT_WAIVER_PRIORITY`, `RED_ROOM_NEGATE_PRIORITY` — one item each
  today, kept as chains so a second slots in without reshaping the caller.
- `FOOD_STEPS_PIPELINE` — the one genuine ordered fold. Salt Shaker's flat +1
  must land before Silver Spoon's doubling: `(base+1)×2`, not `base+(1×2)`.
- `DIG_PRIORITY` — better dig tables win; shared with `shops.py`.

A single commutative sum (`item_capability_sum` over `SHOP_DISCOUNT`) cannot by
itself prove an ordering design. **The ordered tuples are the load-bearing
artefact**; pin the arithmetic before moving anything in them.

### Validation

Because every registration runs at import time, a typo'd id cannot be caught
where it is written — it would simply never fire, silently. Each registry
therefore has a `validate_*` function returning ids the loaded `Registry` does
not know, and `tools/validate_data.py` calls
`validate_room_registry`, `validate_capability_registry`,
`validate_container_registry` and `validate_item_registry`. **A typo'd id in
any of them fails the data validator, not only the test suite.**

## What stays in data

### Shared parametric tags

**The mixed-ownership boundary is the shared/singleton split, and drawing it
anywhere else is the failure mode.** A tag used by several rooms with different
parameters is a table; a tag used by exactly one room, usually named after that
room, is a function wearing a table's clothes.

The migration started with thirteen singleton tags in `rooms.json`. **Three
remain**: `anti_luck`, `archive_floorplan`, `conceal_all_floorplans`. Everything
else is shared and parametric — `grant` alone carries most of the instances —
and the shared tags are also exactly what `items.py::expected_yields`
introspects generically, which is the second reason they cannot become opaque
methods.

**On the item side the test is parameters, not carrier count.** A multi-carrier
tag *with parameters* stays in data; a **parameterless** multi-carrier marker
may become a capability with several registrants, which is what
`item_capability_any` exists for. `compass` migrated on exactly that reading —
it carries no parameters, so nothing published moved into Python. By the same
test `lockpick` (rates `[54, 35, 30, 19]`), `metal_detector_spawns`
(`{coins: 60, key: 25}`), `dig_tool`, `luck_bonus` and `allowance` all carry
published numbers and stay in data.

**`allowance` is a false shared tag.** All 19 instances are the same `+2
allowance` payload on 19 differently-*sourced* tokens; the variation is
one-shot bookkeeping (which token grants it), not effect. It stays in data
regardless — `env/obs.py` and `env/multiday.py` both read it — but a carrier
count of 19 overstates how much genuine sharing is happening.

**A tag lives in data or in code, never both.** Leaving a tag in `rooms.json`
while a Python handler also exists creates precisely the second source of truth
the registry exists to remove. When `coupon_book` registered `SHOP_DISCOUNT`,
its `shop_discount` data tag was **deleted, not left alongside** — the same
defect already deleted twice for `ignition_tool` and `silver_key_bias`.

### `effects: []` does not mean a room is effectless

The registry migration deliberately moves behaviour *out* of the `effects`
array and into code. That is the point — but it means **`effects: []` is
uninformative as a signal of what a room or item does.**

The Throne Room is the standing example: `effects: []`, and both its north
Antechamber lever (`effects/rooms/throne_room.py`, via `provides_lever`) and
its Mora Jai box's +2 allowance (`allowance_token_throne_room`, via
`guaranteed_in`) are fully modelled. Reading `effects` alone produced the
conclusion "a rare, 5-gem, effectless room, plausibly negative for an agent",
which was wrong in the direction that would have cancelled a whole build.

**Anything reading `effects` to judge whether something is inert must also
check the room registry, `provides*`, and guaranteed items.** The registry
makes `implemented` derivable; the flip side is that it makes `effects: []`
misleading.

The same asymmetry is why the item census reports "not found in those
registries" rather than "genuinely inert": **the registries cannot see
hand-written branches in `game.py`.**

### `blocked_on` carries something no registry can derive: WHY

Deleting `implemented` / `blocked_on` in favour of registry membership was
planned and then cancelled on measurement. The premise — that a per-item
registry makes implementation status derivable — covered a small minority of
items. Three findings killed it, and `tools/validate_data.py` prints the
current census on every run, so re-measure there rather than trusting a number
written here:

- Almost every item marked `implemented: false` is in **no** registry at all,
  so membership says nothing about the ones that matter.
- Most records with `effects: []` are in no registry either — which is why the
  census reads "not found in those registries" rather than "genuinely inert".
- At least one item is in a registry **and** `implemented: false` — its
  Tomorrow-Rooms bias is wired, its redraw rewind is not. **Registry membership
  does not even imply full implementation.**

And `blocked_on` carries a *reason*: "the Telescope needs constellation
activation", "the Axe needs a permanent gem-cost override layer", "the Trophy
of Wealth's purchase path is unverified end to end". None of that is a fact
about handler presence. **The derivable half went to the validators; the reason
half stays in data, where a human writes it.**

`meta.wont_implement` is mutually exclusive with `blocked_on`: "blocked" and
"decided against" were the same field, and they are different claims. See
[`doctrine.md`](doctrine.md) for the `implemented: true` /
`meta.simplification` pairing that makes a partial gap machine-detectable.

## The ratchets

An architecture invariant that is not measured rots back. Two allowlist tests
turn "are we done?" into a number.

### The room-id allowlist

`tests/test_room_id_allowlist.py` AST-scans the direct children of `engine/`
for string literals equal to a real room id, against a per-module allowlist
keyed `module filename -> {room ids}`. It currently carries **78 pairs across
11 modules**.

**The scanner is deliberately dumb.** It flags every literal that equals a room
id and makes no attempt to guess whether the site is a behaviour branch
(`room.id == "chapel"`), a fixture lookup, or incidental data that merely
collides — Blue Prince has rooms literally named Bedroom and Hallway, so a
Royal Scepter colour tuple and an `is_category("bedroom")` call are textually
indistinguishable from an id branch. Guessing that distinction from syntax
would hide exactly the cases a human most needs to re-examine after a refactor.
Every occurrence must instead be justified by an allowlist entry, and the
comment on that entry records the judgement call.

It fails in **both** directions, and the second half is what makes it a ratchet
rather than a record:

- a room-id literal appears for an id not listed for that module — a new
  hardcoded id landed;
- an allowlisted id no longer appears — the refactor happened and nobody shrank
  the list. Unchecked, an allowlist only ever grows and stops measuring
  anything.

Per-module-per-id is the coarsest grain that still answers "did this module
stop naming this room", and it is deliberately robust to line-shuffling
refactors that change nothing about which ids a module names.

The ratchet has twice converted "just add it to the allowlist" into a better
design: the Electro Magnet's category union and colour drafting's default
triples both moved into data rather than growing the list.

Not every listed id is debt. `upgrades.py` (the disk selection tables) and
`placement.py` (named conditions and fixtures) legitimately name rooms, as do
`env/actions.py`, `env/obs.py`, `web/play.py`, `cli/render.py`, `config.py` and
`rl/train.py`, which are outside the scan entirely.

### The item allowlist, split into architecture and debt

The item side splits its allowlist in two, and the split is the point:
**architecture may grow; debt may not.**

- **`ITEM_ARCHITECTURE`** (47 pairs) — ids that name engine-owned, permanent
  structure. Four kinds: the engine-owned priority tuples, id-prefix family
  constants, named draft conditions, and trade-graph/pipeline carve-outs.
- **`ITEM_DEBT`** (1 pair) — a genuine per-item behaviour branch that should be
  a registration. `ITEM_DEBT_CAP = 1` enforces the asymmetry.

Without the split, a successful migration and a wash look identical: extending
a priority chain legitimately adds architecture pairs, and a conflated total
would let that hide a failure to migrate anything.

Three corrections to the original taxonomy are worth keeping, because all three
came from reading call sites rather than reasoning about categories: an item
classified as debt because **the same construct must classify the same way** as
its two line-neighbours; an item reclassified as debt because it never appears
in a priority ordering at all, having been grouped by association rather than
evidence; and an item classified as architecture because it sits in a
`frozenset` beside three strings that are not item ids at all.

**A mutation-testing note that matters for any allowlist guard.** Removing an
entry for a still-present literal fires the *outside-the-allowlist* test, not
the *stale-entry* test. The genuine stale-entry direction is only exercised by
removing the literal from the **source** while keeping the dict entry. A plan
that conflates the two would let the stale-entry guard pass vacuously forever.

### A live RNG-label hazard

The `extra_item_kind` RNG substream is drawn from two separate modules,
`game.py` and `items.py`. `rng.py` substreams are independent per label, so
this only matters for *same-label* ordering — but within that label the two
call sites are a live hazard for anything touching `roll_extra_items`:
reordering which one draws first shifts seed-stream consumption for every
seed downstream of it, independent of any migration in flight.

### What the ratchets buy

- **The hand-maintained id-to-module audit exemption map disappears.** It
  exists only because behaviour hides where the audit cannot see it. With every
  room registering, `registered_rooms()` is complete and the audit credits
  Python automatically.
- **The "four channels" gotcha collapses to two**: stats and shared parametric
  tags in data, everything bespoke in one module per room.
- A large fraction of an audit's findings are false positives caused precisely
  by the scatter — 24 of 62 in one triage pass.

## Lazy seeding is a bug waiting for a code path that reads it early

`special_items.configure()` seeds config-carried running values onto
`GameState`, guarded to run once per episode. Its call sites were repeatedly
too narrow, and each narrowing produced a distinct bug:

- reachable only from `on_enter`, so a day spent travelling off-grid never
  seeded the one-time gates and area grants re-paid;
- not called from `shops.carryover()`, so a day that never entered a drafted
  room reported an unseeded `mail_cycle` at day end and silently cancelled an
  outstanding Mail Room order;
- not called at reset, so a day's **first** observation reported the field
  default rather than the carried value — and an agent cannot learn from a
  state vector that lies at the start of every day.

Fixed at the root: `Game.reset` calls it directly, alongside every other field
it seeds from config. **Anything added to `configure()` is seeded at reset and
needs no new call site. Do not re-introduce a lazy one.**

## Deliberate divergences

- **`item_provides` registers data, `room_hook` registers a function.** The two
  registries are deliberately different shapes for the reason above — items
  have no event boundary — even though the surface symmetry invites making them
  match.
- **The room-id allowlist has no architecture/debt split**, unlike the item
  one. Room-id entries carry their justification as a per-entry comment
  instead. The item split exists because a phase of work was measured *by* the
  debt number; the room list has never had that requirement.
- **`effects/tier1.py` is outside the room-id scan**, because the scan covers
  direct children of `engine/` only, matching the granularity the measurement
  table used. Its remaining id branch is tracked by a dedicated test rather
  than by the allowlist.
- **`validate_*` functions are not called at registration time.** They cannot
  be — no `Registry` exists at import. The cost is that a typo'd id is a
  validator failure rather than an import failure, which is later than ideal
  and is accepted.
- **`Registry` is shared across episodes and `Room` is frozen.** This is what
  forbids per-room instance state, and it is a constraint rather than a
  preference: any design putting mutable state on a room object leaks it
  between episodes.
