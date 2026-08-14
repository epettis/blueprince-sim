# Special items: behaviour

What the items and their subsystems actually do. The shape of the data they
are declared in is [`special-items-schema.md`](special-items-schema.md).

Code: `engine/special_items.py` (spawning, pickup, digging, containers,
ignition, machines, carry-over), `engine/shops.py` (commerce, the Trading Post
graph, the Repellent, the day's carry-over report), and one module per item at
`engine/effects/items/<id>.py`.

Where a rule already belongs to another document, it is cited rather than
restated:

- draft-time effects of held items — the Chronograph's priority draw, the
  Dowsing Rod, colour-selective drafting with the Silver and Prism Keys, the
  Repellent's ban shape, the Conservatory/Gear Wrench rarity interaction —
  belong to [`drafting.md`](drafting.md);
- persistence scope and which channel carries a fact overnight belong to
  [`scoping-and-carryover.md`](scoping-and-carryover.md);
- the item capability and item hook registries, the ordered priority tuples,
  and the item-id allowlist belong to [`architecture.md`](architecture.md);
- observation and action widths, and the trade-offer row cap, belong to
  [`rl-environment.md`](rl-environment.md).

## The four standing principles

- **Data-driven, with graceful degradation.** Behaviour is keyed by effect tags
  and capability registrations; an unknown tag no-ops, so partial data coverage
  never breaks a run.
- **One module for the mechanism, one module per item.** The shared machinery
  lives in `engine/special_items.py`; per-item behaviour lives in
  `effects/items/<id>.py` and registers itself. `game.py` holds thin delegates.
- **Inert until modelled.** An item whose target system is out of scope still
  ships as a full record: it can spawn, be held, be stolen by the Lost & Found
  and be traded. Only its *use* is absent.
- **Determinism.** Every roll uses a named RNG substream (`special_spawn`,
  `special_kind`, `lockpick`, `dig`, `dig_kind`, `lost_and_found`,
  `treasure_map`, `container`, `trade_graph`, `shop_stock`,
  `moon_pendant_carry`).

## Spawning and pickup

At most **one** special item spawns per room per day. When a luck-rolled
additional item procs, it resolves to a special item from the room's pool with
probability `spawn.special_share` (25%, inferred), else the ordinary extra-item
kind. `guaranteed_in` items are granted separately and unconditionally, before
any roll. Pool entries already held, consumed for good, or removed by the Lost
& Found are excluded.

**Spawned items are always taken.** There is no leave-behind choice — a
deliberate simplification, since declining a free item is dominated.

**A contraption held at day start locks out its own inputs.** An assembled
contraption carried overnight (via the Coat Check or the Moon Pendant) blocks a
wiki-curated subset of its fabrication inputs from spawning, being purchased,
or being granted as a guaranteed find for that day —
`contraption_lockout.table`. Assembling one *today* does not lock anything out;
the rule is about starting the day already holding it.

**The Keycard is outside the generic pipeline.** It lives on
`GameState.has_keycard`, not in `state.inventory`, and is excluded from
spawning so `engine/locks.py` remains its single source. `effects/items/
keycard.py` exposes `held` / `grant` / `steal` as the special-case shape every
other subsystem must use to touch it. The Lost & Found *can* steal it, and does
so through that shape.

### The Lost & Found

Entering the room steals one uniformly random held special item — the Keycard
included, via the special case above — then grants two draws from
`lost_and_found.pool`, excluding already-held uniques. The token `die` in that
pool grants a die rather than an item. Stolen items return to the spawn pool
for the rest of the day; the Keycard becomes re-findable through `locks.py`'s
own source-room rolls, which stands in for that return.

## Movement, locks and costs

Held items modify three engine quantities, and the *order* in which competing
items apply is an engine-owned ordered tuple, not a per-item priority number —
see [`architecture.md`](architecture.md) for the tuples and why they live in
code.

**Only one gem waiver ever applies.** The Emerald Bracelet's unconditional
waiver is queried before the Hall Pass's conditional one, and a first match
ends the chain, so no cost is decremented twice.

**The Stopwatch spends a charge only when a cost is actually paid.**
Affordability queries stay pure; the waiver fires inside the payment path.

**Every lock-opening item applies to REGULAR key locks only.** The Master Key,
the Lock Pick Kit chain, the Silver Key's consume-for-a-door path and the
Stopwatch all hook the door-locked branches exclusively. **Security doors stay
entirely on the keycard/power/offline system** — the Master Key never opens
one — and a test pins it.

**Lock-item legality and door passability are one rule, queried from two
places.** The action mask and the engine's own passability check must both
consult the free-open predicate. When they did not, the three highest-value
lock items were unusable at zero keys held while the engine considered the door
passable: one rule written twice, drifted.

## Digging

Digging is free in the real game, so an explicit dig action would be strictly
dominated. Instead, standing in a room with undug spots while holding a digging
tool digs **all** remaining spots at once, using the best tool held (Shovel <
Detector Shovel < Jack Hammer). The Treasure Map's marked cell triggers its own
one-per-day treasure roll on the same terms.

Because one call drains a whole cell, anything counting dig outcomes fires in
**bursts**, not once per player action.

**Dig-spot counts are inferred.** The wiki's Dig Spot list names rooms but not
counts, so every listed room carries one spot except the datamined Tomb (2) and
Tunnel (3). A per-cell overlay (written by the Cloister of Veia and by the
`spread_dig_spots` experiment effect) adds to that baseline.

**The `jack_hammer` table is knowingly unreconciled.** The `shovel` and
`detector_shovel` tables reproduce the wiki row for row. The jack hammer's does
not: it lumps outcomes the wiki lists separately (gem 1/3, dice 1/2/3, the
Stopwatch) and **adds four vault keys the wiki does not list**. Its trash rows
and `nothing` row carry the wiki's published absolute rates and the remainder
is scaled to fill; the rest of the table awaits a full reconciliation. The
open question — where the vault keys came from — is a live task in
`open_tasks.md`, and it must be settled before a rebuild deletes them.

## Containers

Eight container kinds exist: `trunk`, `chest`, `locker_open`, `locker_locked`,
and four Mechanarium compartment kinds. Trunks are smashable (any item carrying
the `smash` tag) or key-openable; chests are key-only and never smashable;
`locker_locked` is key-only with no smash path; `locker_open` is free.

**No room carries a chest.** The kind is fully modelled and validated, but the
wiki documents no per-room chest assignment.

**There is no auto-open.** Unlike dig spots, opening can cost a key, so
skipping is a real choice and the agent must press the action. Within a cell
the open order is deterministic by kind.

**Container contents are inferred as a whole.** Loot tables are derived from
items whose wiki pages name trunks or lockers as a source; actual per-container
tables are not datamined. Trunk rooms are sourced from those same lists for
four rooms and inferred from vague mentions for the rest, and locker counts are
inferred from the number of distinct item types mentioned.

**Container counts are per-cell, not per-room.** `containers_in` reads a static
per-room table, but the live query resolves per cell so that the Mechanarium's
own compartments and any dynamically added trunks are visible. Anything reading
the static table directly — including the observation encoder — is wrong; the
observation's container plane once did exactly that and could not see the
Mechanarium at all.

**The Garage car re-locks every night**, so Car Keys are required on every
open. What decides the loot is whether the disk has been *spent*: while
`upgrade_disk_garage` is absent from the collected set the trunk yields the
disk again, and once it is inserted the trunk switches to the later pool. The
Keycard appears in that pool and is granted through the Keycard special case,
never the generic grant.

**Vault deposit boxes are a distinct mechanic**, not a container kind for
counting purposes. Each vault key opens its own numbered box; the key stays in
inventory but is permanently removed from the spawn pool.

## Ignition targets and machines

Either ignition tool — Torch or Burning Glass — lights any target; there is no
per-target tool restriction. **This follows the wiki over a play-report.** An
owner play-report had named the Burning Glass specifically, and the owner
themselves ruled for the published text, on the ground that a single
play-report cannot distinguish "this tool is required" from "this tool was in
my hand". [`doctrine.md`](doctrine.md) owns the general form of that rule; what
this instance adds is that **surfacing the conflict rather than resolving it
silently is what made the weaker-evidence call possible at all.**

Five targets are modelled. Three are rooms — Chapel, Tomb, Trading Post — and
two are area-graph nodes, marked `area: true`:

- **Chapel**: pays out the accumulated Keeper of Tithes total, the coins the
  Chapel's −1 entry penalty has ever banked.
- **Tomb**: an Upgrade Disk and 4 dice. The wiki's two candle pairs (near
  candles for the disk and dice, far candles revealing Clara Epsen's resting
  place) are collapsed into one ignition event.
- **Trading Post**: an Upgrade Disk and 40 gold. The dynamite barrels' permanent
  secret room is collapsed to an immediate grant, since the room is not
  modelled.
- **Abandoned Mine (south)**: eight candlesticks; no grants, because lighting
  them lowers the stairway to the Precipice — a **route**, set as a permanent
  flag. The Upgrade Disk sitting in the mine is a separate ungated pickup
  granted on arrival; granting it here too would double-pay.
- **Apple Orchard**: requires three held Microchips; no grants, because it
  unlocks the Satellite Dish — a **config unlock**, set as a permanent flag.

The tool is **not consumed** (a Torch relights all day); each target lights at
most once, ever, and lit targets persist across days. The Freezer thaw is
deliberately skipped: the wiki describes it as temporary and daily, which the
one-shot lit-target model cannot express. Targets the wiki names that exist in
neither `rooms.json` nor `areas.json` are recorded in
`ignition.meta.absent_targets` and asserted absent by the validator, so the
list cannot rot silently if such a room is later added.

Two requirement forms exist — a single required item id, and a dict of item id
to minimum held count — and both are checked in one shared helper that the
action mask also calls, so **legality and effect cannot drift apart.**

Machines take a Broken Lever, which is consumed. The Casino's slot bonus is
inferred (the wiki gives bonus spins, not an expected value).

### The Greenhouse lever and the Antechamber's south door

Installing the lever unlocks the Antechamber's south doorway **segment** for
free and bumps the door version so the navigation caches invalidate. The
direction here is a live trap worth stating explicitly:

- **N increases rank in this grid**, so the neighbour north of cell 37 is the
  Antechamber at 42.
- The Antechamber's own south door and cell 37's north door are the **same
  segment**.

So the wiki's "south Antechamber lever" is modelled as opening cell 37's
**north** segment. Using S there would silently unlock an unrelated door two
ranks away and leave the Antechamber untouched. **A test that seeds and asserts
the same segment key cannot catch that inversion**, which is why the test pins
the identity against the Antechamber's own south segment, and a second test
asserts the payoff behaviourally: passable with zero keys held, no key
consumed.

Because a rank-8↔9 segment sits at 130% base lock chance, the Antechamber
normally starts locked, so this is a genuinely useful late-run play rather than
a no-op.

## Commerce

Shop stock rolls on **first entry** to each placed shop. Owned or consumed
special items never stock. The Coupon Book applies a per-purchase *reduction*,
not a refund, so an item priced one above your gold becomes buyable; sale days
halve prices, rounded up.

The Showroom picks two items from each of its two tiers, avoiding owned ones,
and reveals the Trophy of Wealth once all four displayed items are bought.
[`doctrine.md`](doctrine.md) owns why the Trophy is an ordinary item and not a
trophy concept: it is a coin sink the player can act on.

**The Electromagnet robs the Locksmith** on first entry: the 24 basic wall keys
are auto-collected and both key purchase options are disabled for the day. The
Locksmith's *special* key is **not** taken — special keys are never
auto-collected.

### The Trading Post

For each tier the receivable ids are shuffled into one cycle, each pointing at
the next. **Give-only ids** (`no_receive: true`) attach as extra *sources* into
that cycle: they can be given, but nothing's successor ever lands on them, so
they can never be received. Per-item `dice_chance` may replace a successor with
a die; tier 5 checks its special chance first. The graph is rolled once, on the
first offer query of the day, and is fixed for the day.

Offers resolve by walking the graph from the held item, skipping nodes that are
held or unavailable and following each skipped node's own successor; sentinels
terminate, and a full loop back to the start means the item is untradeable
today. The player sees the resolved receive before committing, matching the
real-game UI, and the trade re-resolves at execution time.

Traded-away items return to the spawn pool, deliberately bypassing the
once-per-day spawn uniqueness so that a two-cycle milking loop works exactly as
it does in the real game. **`trades_per_day` is the only bound on that loop**,
and it is set generously because the graph is discoverable only by
experimenting — players burn trades learning the chains.

**A tier with one receivable id is a self-edge and cannot be traded.** Tier 5
has *zero* receivable ids of twelve, so its all-give-only fallback fires on
every tier-5 roll — the case a comment once described as unreachable.

**Every tier-5 item is give-only.** The wiki's tier-5 line carries no
receivable markers at all, and the datamine says so outright. The tier-5
special chance is therefore the **split between the two tier-5 specials**
(Allowance Token and the Upgrade Disk), not a chance of falling through to the
cycle; read as a fall-through it self-edged and left the Master Key with no
offer at all in 40% of seeds. When the disk is unavailable a tier-5 trade
decays to a tier-4 item, which incidentally reproduces the wiki's "tier 5 items
can sometimes trade for tier 4 items". The wiki's menu-timing quirk behind that
line is not modelled.

**Re-tiering moves reward shaping**, because `inventory_value` keys off `tier`.
The last sweep took a plausible held inventory from 88.0 to 161.0 — a 1.83×
increase — and `items.json`'s per-tier values were deliberately **not** adjusted
to compensate, so the effect stays visible rather than hidden.

#### Two live identity defects

**The sim's trade identity is the sim id; the wiki's is the game item.** The
wiki states twice that all Sanctum Keys count as one item and that Upgrade
Disks do the same, so holding many produces one offer. This sim emits one offer
per inventory id, so eight held Sanctum Keys emit eight offers and sixteen disk
ids can emit sixteen. **Ruled to fix**, by applying a trade-offer identity key
on the game item before the sort. The counter-case that was weighed and
accepted: the per-source ids exist to gate respawn independently, so this is a
second identity notion living alongside the first.

**The same bug runs the other way for Microchips.** The wiki says three
Microchips give three distinct offers; the sim emits one regardless of count.
`microchip` is the only item with `unique: false`.

The consequence of the first defect — silent truncation past the offer row cap,
and which entries get crowded out — is owned by
[`rl-environment.md`](rl-environment.md), together with the ruling that fixing
identity is what makes raising the cap stop being urgent.

**The Keycard is excluded from trading in three places** (two graph-build
filters and one offer guard) because it lives on `state.has_keycard` rather
than in the inventory. **Ruled to fix**, via the `keycard.held`/`keycard.steal`
precedent the Lost & Found already uses. **A naive fix — deleting the three
exclusion checks — would let a player give the Keycard away and keep door
access**, and would write a phantom inventory entry that no door code reads.
Use the special-case shape.

### The Workshop and fabrication

Fabricating consumes the recipe's inputs and grants the contraption, any time
the player stands in the Workshop. First entry spawns one free component,
uniform over available components, with a coin fallback. Fabrication options
are queryable anywhere, not only in the Workshop, so a policy can see that its
held items *could* become something before walking there.

## Per-item rulings

### The Crown of the Blueprints

**It is a filter, not a removal.** The wiki says so in as many words: it claims
to remove a room from the draft pool but only blocks it from drafting. The
filter belongs in the single gate every draw path already passes through.
Removing cards instead would change deck *sizes*, which feed rarity legality —
so the blocked room would silently alter which rarities are legal to roll for
the rest of the day.

**There is no exemption.** Owner play overrides the wiki here: the wiki claims
a blocked Red Room is still obtainable through Silver Key and Prism Key
drafting and that duct-carrying reds still appear. It is filtered from **every**
draw path for the rest of the day. This is worth keeping as a general shape:
**a correction can invalidate a question rather than answer it** — an earlier
ruling about how to scope those exemptions became void, not amended, because
the exemptions it scoped do not exist.

The effect is a player choice ("an option appears", "you may"), so it needs its
own action ids — one per Red Room slot in the hand, three in total.

### The Gear Wrench

**The target is the RARITY, not the room.** Drafting a Mechanical Room while
holding the wrench lets the player permanently adjust *that* room's rarity, so
the action block is four ids (one per rarity level), not one per room and not
one per room-rarity pair.

**It has two effects with two different scopes**, and collapsing them is what
produced a wrong reading and then a wrong retraction of it:

- the **main effect** — drafting a Mechanical Room sets that room's rarity
  **permanently**;
- the **pickup effect** — Workshop and Boiler Room to Standard, **that day
  only**.

A `blocked_on` naming cross-day persistence was correct for the second and
wrong for the first. The lesson kept from that exchange: **a pattern asserted
from N instances needs each instance verified, not the pattern.** A
generalisation drawn from one research reading and applied within the hour is
exactly the claim that gets inherited rather than re-derived.

**The wiki's "Dynamic Rarity is permanently ignored afterwards" rule costs
nothing here**, because this sim does not model Dynamic Rarity at all — the
per-room hidden table has no representation. The headline rule has nothing to
ignore.

**A wrenched room must be placed by build-time bucket assignment**, not by a
mid-day deck edit. Deck injection and upgrade application index decks by the
room's *static* rarity without consulting the dynamic one, so a wrenched room
that is also in a temporary pool is a reachable corruption, not a theoretical
one. Every Mechanical Room has a single deck copy and the one-copy-per-grid
rule holds, so folding the assignment into deck construction is both correct
and consumes no RNG.

[`drafting.md`](drafting.md) records the standing divergence that the
Conservatory's re-roll never writes the same permanent record.

### The Chronograph

Its Tomorrow-Rooms bias is a **priority draw**, not a category bias — see
[`drafting.md`](drafting.md) for where it sits. It was once wired as a
per-slot category bias firing on all three slots, which ran roughly 3× too
strong: measured at the first doorway, 37.7% of options were Tomorrow Rooms
with the item held against 0.93% without, where the correct model gives ~13%.
**The Tomorrow-Room id list must be generated from the category, never
hand-typed** — it includes upgrade variants that a hand list reliably misses.

**Its rewind is not time travel**, and that is what collapses the hard problem.
The wiki calls it a normal redraw with the three rooms fixed, *activating*
effects that rely on drawing a floorplan. So it is a **forward-pinned
re-deal**: overwrite the pending options from a saved stack, re-fire the
hand-dealt hook, reset the rotation counter. No RNG restore, no deck rewind, no
refund. A true state restore would need a deep copy of all eight decks plus
stream states and **would still be wrong**, because it models a mechanic the
game does not have.

The saved stack lives on the pending draft, alongside the other per-hand
counters — the item is day-scoped, so no carry-over channel is involved. The
previous hand must be **in the observation**, as an additive key: without it
the agent knows a rewind is legal but has no signal on whether the previous
hand was better, so the action is noise and will be learned as "never press".

### The Axe

Four rulings define it:

- **Targets are root-base keyed** — one target per floorplan family with a gem
  cost, matching how the Room Directory holds one entry per family and how
  draft counting already works. Axing a family covers its upgrade variants.
- **Axed rooms and the use cap are save-scoped**, surviving the attempt wrap
  alongside the other explicit carve-outs in
  [`scoping-and-carryover.md`](scoping-and-carryover.md). That is the strongest
  reading of "permanently", and it makes the purchase a real long-horizon
  investment.
- **An unused Axe drops overnight.** Buying it is a same-day commitment.
- **Deck membership ignores the discount.** An axed room stays in the Gem
  decks; the Axe zeroes the *charged* cost, never the room's free/gem identity.
  See [`drafting.md`](drafting.md).

**The Axe does not belong on the gem-cost item chain.** Both existing gem
chains are held-item chains whose handlers guard on the item being held. The
Axe is consumed at use time and its discount **outlives the item**, so
registering it there would mean a handler that deliberately fires when its item
is not held — inverting the contract the chain is built on. The override is a
branch in gem-cost resolution instead, which already takes the game state, so
no signature change propagates.

**The Room Directory does not exist in this sim.** The only trace is a
directory number in `rooms.json` that is never parsed, is missing on 34 of 170
rooms, and has 13 rooms sharing one value. It is not usable as an action index;
"Room Directory action" means inventing a target-selection block, not building
a Directory.

**The guard this item needed did not exist and had to be written first.** The
chi-square draft suite recomputes its expected weights through the same
deck-legality predicate the engine uses, so a free/gem bucket move changes deck
sizes, the gate self-adjusts, and the test still passes. **A guard that pins
the wrong number is worse than no guard**, and the trap the Axe was most likely
to fall into was the one thing the sharpest suite in the repo could not catch.

### The Battery Pack

**Its Workshop/Boiler Room rarity choice is a toggle, not a coin flip, after
the first trigger.** Both wiki pages say a second trigger the same day always
switches to the other option. A second pickup is reachable despite the item
being unique, because a re-grant is blocked only while the item is *currently
held* — fabricating the pack away frees a later grant.

**The draw is deferred, not resolved at pickup.** The pickup records intent in
state and the roll happens at the next site where RNG is in scope. This is the
repo's established idiom, already used by the Treasure Map and pinned by a
test, and it is **provably unobservable**: dynamic rarity appears nowhere in
the environment layer, so no agent can see the gap between pickup and
resolution. It also changes zero call sites — the real cost of threading RNG
into pickup is not the 32 engine call sites (31 of which already have it) but
the 83 test sites that call the grant helper against a bare state with no RNG
anywhere in scope. **Price the test suite, not the engine.**

The effect is **day-scoped**, so it needs no carry-over entry and no width
change.

### The Microchips

Three exist, from three sources: the Entrance Hall vase (smashed with any
`smash`-tagged item — "a Sledge Hammer **or equivalent**", so the Morning Star
counts and narrowing the tag to the two the owner named would have been a
regression), the West Path dig, and the Blackbridge Grotto pedestal.

All three reappear the next day. The vase and West Path chips do so because
their *discovery* is a permanent flag and the chip is re-granted at day start.
The Grotto chip has **no discovery** — it is in the pedestal from day 1 — so
its day-scoped taken-flag defaults false at every reset and the respawn falls
out for free. **Matching the owner's semantics meant deliberately not copying
the other two chips' plumbing**, and it kept the carry-over vector width
untouched.

The Orindian Ruins gate counts held chips **plus** the pedestal chip while it
is still in place, so two carried chips open the Ruins; taking the pedestal
chip gives three held, which keeps the gate open and also satisfies the Apple
Orchard sundial's three-chip requirement.

Chips are tier-2 give-only, so they can be traded away or lost to the Lost &
Found but never received.

### The Parlor

The Parlor's box always grants a fixed number of gems on first entry — no loot
roll, no key. The base Parlor gives 2 and the "3 Prize" upgrade variant gives
3, identified by its own datamined effect text; the remaining variants inherit
the base grant or none.

**The Wind-up Key is deliberately not modelled**, and this is the standing
example of the puzzle-only-item rule. In the real game the Parlor desk spawns
Wind-up Keys that open the Parlor boxes, one key per box. The key has exactly
one purpose and is consumed on use. Rather than widen the action space with an
open-box action plus walk-to re-entry, box-cap tracking and per-run key spawn
suppression, the gems are granted directly through the guaranteed-item
pipeline. **Do not "fix" this back to the key-based model without weighing the
action-space cost** — the Wind-up Key adds no strategy surface the agent needs
to learn.

The consequence is that the "2 Wind-up Keys" Parlor variant references a
concept that no longer exists and stays permanently inert. That is a
**deliberate** finding on the room worklist, not an oversight.

### Items decided against

`meta.wont_implement` records these, and they are decisions rather than
blockers:

- **The Magnifying Glass** — its own effect is puzzle-only and this sim has no
  lore layer. **But it keeps spawning.** It is the sole input to the Burning
  Glass, which has no spawn source of its own and is one of only two ignition
  tools, so dropping it from the pools would silently remove an ignition path
  and one of the sundial's two lighting routes. The ruling is: *keep it
  spawning, stop counting it.*
- **The Key of Aries** — no policy will learn the castling puzzle, and its
  payoff is already granted regardless: the Royal Scepter's found-flag defaults
  **true on purpose**, so the scepter is exercised as a mechanic without its
  unlock chain.

**The Diary Key was removed from the item table entirely.** The wiki is
explicit that it unlocks only flavour text and has no other known use — unlike
the Wind-up Key precedent, which at least opened a box holding real gems, there
is no mechanical payoff for an agent to reason about. The Tomb's ignition
grants are unaffected and still fire unconditionally.

## Multi-day items

[`scoping-and-carryover.md`](scoping-and-carryover.md) owns the channels. Two
item-specific carries have their own rules:

- **The Coat Check** stores the highest-tier held item (ties broken
  alphabetically by id) and returns it exactly the next day. The real game lets
  the player choose which item to store and retrieve it on any later day; the
  stored item is **not** removed from today's inventory.
- **The Moon Pendant** draws 2 uniformly random distinct held items at end of
  day, itself eligible, on its own named substream. The wiki says "2 random
  inventory items"; that is taken literally at end of day rather than mid-day,
  regardless of what happened to the inventory during the day.

### The Repellent

A Repellent is consumed on use and bans one floorplan. `entrance_hall`,
`antechamber` and `room_46` are refused, per the wiki's exclusions.

**A ban does not affect decks already built today** — it takes effect from the
next day. The counter starts at 7 and the day-advance that immediately follows
the use does **not** decrement it, so the ban is active for exactly 7
subsequent days before dropping.
[`scoping-and-carryover.md`](scoping-and-carryover.md) owns the decay-and-cap
discipline the ban dict follows; [`drafting.md`](drafting.md) owns what a ban
covers (the floorplan, so its upgrade variants too) and where the pool is
filtered.

## Deliberate divergences

- **Auto-dig and auto-treasure-dig replace a dig action**, because digging is
  free and skipping it is dominated. Container opening is deliberately *not*
  auto-executed for the opposite reason: it can cost a key.
- **The Knight's Shield auto-applies** to the first red room entered that day.
  No choice is offered.
- **The Stopwatch's 60 real-time seconds become 10 free cost events**, and the
  **Running Shoes' 2.2 room-length trigger becomes every third move free.**
  Both are turn-based stand-ins for real-time quantities, and both are data
  knobs rather than constants.
- **The Prism Key opens a locked door and recycles**; its colour-draft trigger
  is deferred. See [`drafting.md`](drafting.md) for colour-selective drafting.
- **The Silver Key's cross/T bias applies to the initial deal only.**
  [`drafting.md`](drafting.md) owns this one and holds it as an open question
  for owner play — do not change it speculatively.
- **The Metal Detector's extra-spawn chances are not datamined** (coins 60%,
  key 25% per drafted room, inferred, data knobs).
- **Shop dish identity is not exposed to the observation.** A food purchase
  encodes as the food resource code; which dish it is does not reach the agent.
- **The Trading Post's tier-5 menu-timing quirk is not modelled**, and neither
  is the real game's undocumented shop-combination table — the Commissary
  offers a uniform sample of distinct available entries instead.
- **The Mechanarium's compartments open in a fixed order at no cost**, rather
  than the real game's own sequence, and several Upgrade Disks are granted on
  first entry where the real game gates them behind a prize door, an ice wall
  or a Power Hammer. Each such record carries the gap on itself, per
  [`doctrine.md`](doctrine.md).
