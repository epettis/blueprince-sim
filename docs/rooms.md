# Rooms: per-room mechanics

What individual rooms do, and the two house-wide systems that only rooms use:
the **spread effects** and the **Mail Room cycle**. Code: one module per room at
`engine/effects/rooms/<id>.py`, with shared parametric tags in
`data/rooms.json`; the split between the two is owned by
[`architecture.md`](architecture.md).

This document is authoritative for a room's own behaviour. Rules that are not
about one room are cited, never restated:

- how a hand is dealt, what a room's rarity and layout mean for placement,
  concealment, redraws, the Mechanarium's derived door mask, and how a rarity
  override moves a room's cards between decks — [`drafting.md`](drafting.md);
- how many items a room yields, the luck ladder, `never_roll_rooms` and the
  per-room count transforms — [`luck.md`](luck.md);
- lock chances, the unlock menu and the security-door system —
  [`locking.md`](locking.md);
- how long a room's effect lasts and which channel carries it overnight —
  [`scoping-and-carryover.md`](scoping-and-carryover.md);
- the outside-area graph a room may anchor, and what those nodes hold —
  [`areas.md`](areas.md);
- which rooms carry steam power and how it spreads between them —
  [`power.md`](power.md);
- items found in rooms, containers, ignition, commerce —
  [`special-items-behaviour.md`](special-items-behaviour.md);
- assumed-solved puzzles, trophies, source precedence, and the rule that a
  supplemental-sourced room must be edited in **both**
  `tools/supplemental_rooms.json` and `rooms.json` —
  [`doctrine.md`](doctrine.md);
- what the Antechamber levers pay — [`rewards.md`](rewards.md).

## Reading a room record

**Never read a currency off the mojibake in `meta.effect_text`.** Three glyphs
collide visually once the decompiled sheet is decoded — steps, coins and gems —
and the ingest `GLYPH_MAP` resolves by UTF-8 byte value for exactly that
reason. Every ambiguous glyph carries its own `meta.glyph_resolution` entry with
a confidence, and that is the authoritative resolver. The Sauna, the Nurse's
Station and the Spare Master Bedroom all pay **steps** where the raw text looks
like coins; the Sauna was nearly implemented as coins from a ruling that read
the glyph rather than the resolution.

**A room's colour is a SET of categories, not one value.** `Room.category`
holds the primary and `Room.extra_categories` the rest; the derived
`Room.categories` property is what `is_category()` answers from, and it is
derived rather than stored so `dataclasses.replace(room, category=X)` cannot
leave membership stale. Anything counting rooms by colour must call
`is_category()`, never compare `category ==` — the Maid's Chamber is red **and**
bedroom, and the Aquarium family counts as every colour.

**`pool` is not a colour.** Sixteen rooms once carried a pool name
(`studio_addition`, `outer`) in `category`, which made them invisible to every
category-targeted draw — the Secret Passage colour choice, scepter colours,
`grant_per_category`, the Cloister and Terrace green boosts, and every category
bias. All sixteen now carry real colours. `CATEGORIES` in `env/obs.py` keeps its
now-inert `studio_addition` / `outer` slots deliberately: removing them would
renumber every later category for no behavioural gain.

**The two unlockable pools are two mechanics, not one.** Sixteen rooms are
absent from a fresh save's deck and unlock one at a time, and the wiki splits
them evenly:

- **`studio_addition`** (8: Casino, Classroom, Clock Tower, Dormitory, Dovecote,
  Solarium, The Kennel, Vestibule) — the Drafting Studio's drawing board offers
  three at a time and one is permanently added to the pool. Gated by
  `cfg.studio_additions`.
- **`found_floorplan`** (8: Planetarium, Mechanarium, Treasure Trove, Throne
  Room, Tunnel, Conservatory, Lost & Found, Closed Exhibit) — each is hidden
  somewhere on the estate and must be found individually. Gated by
  `cfg.found_floorplans`.

Because a found floorplan is found *individually*, its gate is per room. Three
of the eight also carry a dedicated `GameConfig` bool
(`treasure_trove_blackprint`, `throne_room_blueprint`,
`conservatory_floorplan_found`) recording that the engine watched the player
find that specific floorplan; `decks.py::eligible_pool` checks each by room id,
never by pool, so the Conservatory's campsite dig cannot unlock the other seven.

**A large `blueprint` category is correct, not a catch-all bug.** It is by far
the biggest colour and that is the game's own joke; do not "fix" it. The earlier
finding it resembles was genuinely different — those rooms carried a *pool name*
where a colour belonged.

**A room stating an exact coin amount grants exactly that amount.**
`items.guaranteed`'s `coins` count means *piles*, each rolling 1–5, so a room
whose text promises a figure systematically misses it: the Vault's 8 piles
average 24 against an advertised 40, the Rumpus Room's 2 average 6 against 8,
the Pantry's 1 averages 3 against 4. These three name a figure and get it
exactly; the pile roll stays for rooms that genuinely scatter piles. **This is
the sim disagreeing with both sources, not a source conflict** — the wiki and
the datamined `effect_text` agree on the numbers, so
[`doctrine.md`](doctrine.md)'s datamine-beats-wiki rule has nothing to
arbitrate. Check what a count counts before calling it wrong.

## Spread effects

A spreader does not grant on entry. It parks per-cell payouts in
`GameState.spread_pending`, and `Game._collect_spread` pays each cell out
when the player arrives there. Everything below shares that pipeline, though
not every spreader's *trigger* is placement: the Tomb's is each Dead End's
draft, its own included, and the Office's Spread Gold in Estate (below) is a
player action at its terminal, not a draft at all.

Two invariants hold across every spreader:

- **The estate is snapshotted at the draft moment.** Rooms drafted later get
  nothing.
- **A spreader with no grid cell spreads nothing.** Drafted from the outer-room
  pool, the Secret Garden has no cell to spread from, which matches the only
  reported evidence.

**The second invariant constrains spreading *outward*, not receiving.** It is
about a spreader having no cell to reach out *from*, so it does not silence the
Tomb, whose every payout lands in the Tomb itself: those park under the `-1`
off-grid sentinel the rest of the outer-room pipeline already uses
(`effects/rooms/tomb.py`'s `OFF_GRID_CELL`), and `Game.travel_to` drains that
key on arrival the way `Game._enter` drains a cell's.

### The Patio's gems

Every Green Room on the estate at the draft moment gets **exactly one gem**,
the Patio itself included. The Spare Patio is identical, and unusually that is
affirmatively sourced four separate ways rather than assumed from matching text
— which matters, because the Spare Great Hall's text is byte-identical to the
Great Hall's and its mechanic is materially different. **Identical text is not
evidence.**

*What the game does, and why the difference is deliberate:* the wiki
contradicts itself — the Gems page says "each Green Room", the general Spread
page says every room "has a **chance**", and the Spare Patio page says it will
"**often**" spread to itself. No rate is published anywhere, so the
deterministic reading wins.

**Gem colour is mechanically inert** — the six colours "are purely cosmetic and
are lost once the gems are collected" — so the green-to-blue switch a Conference
Room causes needs no representation.

### The Locker Room's keys

A bucketed number of basic keys is parked in that many **distinct** occupied
cells, drawn from its own RNG substream, excluding the 18 rooms the wiki names
as never receiving one (`rooms.json`'s `flags.no_locker_keys`, read through
`Room.no_locker_keys` rather than an id list in code). The room count includes
the outer room.

The bucket — 0–9 rooms → 3, 10–24 → 4, 25+ → 6 — is **borrowed from the Secret
Garden**, the one spreader with a published formula, and is marked
`confidence: inferred`. The wiki publishes no count and no rate for the Locker
Room; its only quantitative claim is relative and unanchored ("a slightly lower
chance of receiving a key than they do of receiving items from other spread
effects", with the comparison class itself unquantified). Since keys are
*rarer* than other spread items, this borrowed figure probably **overstates**
the Locker Room. **It is a placeholder chosen for consistency, not a
measurement — do not cite it as sourced, and replace it the moment real play
gives a number.**

Lockers themselves are not part of the spread: [`locking.md`](locking.md) owns
the rule that a locked locker costs exactly one basic key and that no
lock-opening item touches it, which is what makes this spread load-bearing
rather than flavour.

### The Secret Garden's fruit

Total fruit = the room-count bucket (same thresholds as above, counting the
Entrance Hall, Antechamber and outer room) **plus a soil bonus**, capped at 10.
That many fruit are parked in distinct occupied cells.

**It spreads apples and oranges only — never bananas**, each spread fruit a
50/50 roll, mean 3.5 steps. *This overrides the wiki*, whose Food page states
"the effect of the Secret Garden spreads all three fruits"; owner play outranks
it, and the conflict is recorded here rather than resolved silently so a later
wiki citation does not look like it contradicts a bug. The datamining settles
nothing in either direction — the republished box gives only the *total*, never
a per-type split — and the one place bananas are datamined into a Secret Garden
outcome is the Conference Room case, whose fixed payout carries no banana
either.

Fruit are worth **apple 2 steps, orange 5, banana 3**. Owner play and the wiki
agree here, independently: the Food page states each value and the Pantry page
derives the same three from a note puzzle, so neither source needs re-checking.

### Soil quality

The soil term is a flat **Good (+4)** for every cell. The real bonus is keyed to
the cell the Secret Garden was drafted on (Poor +2, Good +4, Rich +6), and that
map **is not published anywhere in wiki text** — it exists only as an image in
the Gardener's Logbook, and "barren", named on the House page as the low end,
has no published value at all. Encoded flat and marked `confidence: inferred`
rather than blocking the feature or inventing a 12-cell map; the Secret Garden
is wing-only across ranks 3–8, so a real map needs just 12 cells and can replace
the constant with no code change.

**Every Secret Garden total measured before a real soil map lands is an
estimate, not a bound** — unlike the open stub gates in
[`areas.md`](areas.md), it can err in either direction.

### Florealis's gem flowers

The one payout here that no room owns. While the Florealis constellation is
active, **every Green Room drafted after the activation** parks gems in its
own cell — **two for the Courtyard and the Cloister, one for every other Green
Room** — and they are collected on arrival like any other parked payout.
[`rl-environment.md`](rl-environment.md) owns the constellation block; the
amounts and the shop-free half of that mechanic live in
`data/constellations.json`'s own record.

It breaks both invariants above on purpose, because it is **not a spreader**:

- **The estate is not snapshotted.** The trigger is the *draft*, not the
  activation, so Green Rooms already standing when Florealis fires get nothing
  and every later draft blooms. That is why the payout is emitted from
  `Game._place_room` rather than from the activation, and why it needs no
  per-cell bookkeeping — a cell is drafted once, so N Observatories cannot pay
  N times.
- **No Conference Room redirect.** These gems are the drafted room's own
  contents, not something reaching out to other cells, and nothing published
  says the Conference Room absorbs them.

**The effect text is a lie and the wiki says so** — "more likely to contain"
describes nothing random. Florealis "is entirely deterministic and does not
depend on the location of rooms within the house", so there is no rate to
source and none is invented.

Two published cases are deliberately out of scope: a Green Room's **own** gem
flowers, which the wiki states "are independent and do not interact with
Florealis' effect", and the **Greenhouse drafted as an Outer Room**, which has
no grid cell to park anything in — the same invariant that already silences the
outer-room Secret Garden.

### The Tomb's coins

**Every Dead End drafted in the house spreads 5 coins into the Tomb, the Tomb
itself included** — so a Tomb entered on a day when nothing else Dead-Ended
still pays 5, which is the owner ruling this models. "Dead End" is the
drafted orientation having exactly one door on a room whose card can print
that shape, not `Room.layout` alone: a Greenhouse drafted in a corner rotation
does not pay, and the Mechanarium's derived one-door mask never counts.

The Tomb qualifies under its own rule on both halves of that test — printed
`layout` `dead_end` and a one-door `door_mask` of 4 — even though it is never
*placed* on the grid. An outer room is dealt in its printed shape and never
rotated, so its own `door_mask` **is** the orientation it was drafted with,
and that is what `Game._choose_outer` publishes for the hook to read.

**The effect is draft-ordered.** The trigger is each Dead End's draft, so a
Dead End already standing when the Tomb is drafted pays nothing — there was no
Tomb to spread into at its draft moment. This is the same direction as the
first invariant above and the opposite of Run Payroll, which is keyed by room
id precisely so draft order does *not* matter.

**No Conference Room redirect applies.** These coins are the Tomb's own
contents accumulating in it rather than a spread reaching out to other cells —
the same distinction that exempts Florealis's gem flowers — and no source puts
the Tomb among the spreaders a Conference Room absorbs.

### The Conference Room absorbs everything, including the self-item

A Conference Room already on the estate redirects **everything** a spreader
would have spread — its own self-item included — into the Conference Room's own
cell. The Patio, the Locker Room, the Secret Garden and the Office's Spread
Gold are what "everything" covers; the two payouts that reach no cell but their
own, Florealis's gem flowers and the Tomb's coins, are exempt for the reason
each section above gives. For the Locker Room the `no_locker_keys` exclusion
list does not apply to that redirect.

*The wiki is asymmetric here and the asymmetry is treated as loose wording:* the
Patio page says the redirected gems "**include the gem that would spread in the
Patio itself**", while the Locker Room page says "any key that would be spread
to **another room**", which read literally would leave its own self-key behind.
Both spreaders behave the same way.

### The Office's coins

Spread Gold in Estate is triggered by a **player action** at the Office's
terminal (`SPREAD_GOLD_ACTION`), once per day — not by a draft — and it
targets **every currently drafted room**, not a bucketed sample: every
occupied cell at the moment the terminal is used gets its own pile, the
Office's own cell included, none drafted afterward. A placed Conference Room
still absorbs the whole batch into its own cell, the same "including the
self-pile" shape as the Patio/Locker Room above.

Pile size is a random **3, 4, or 5 coins per receiving room** — an owner
ruling. The Office page and the Spread page both describe the effect without
a figure, unlike the Tomb's flat 5 coins, which the wiki states outright; the
ruling reuses the Office's own published floor-item pile sizes (3/4/5 coins)
as the game's own answer for what an Office coin pile looks like.

**Run Payroll is not part of this pipeline at all.** It puts 10 coins in
each of the Maid's Chamber and the Servant's Quarters (two piles of 5), and
the wiki states outright that it is not a spread effect and has no
Conference Room interaction. It is paid out through a separate
`GameState.payroll_pending` dict keyed by room id (not cell), so a target
drafted *after* the terminal is used still receives its pile — draft order
does not matter, per the wiki. Its weekly cooldown is an owner ruling: it
resets on the coming in-game Saturday after use (`day % 7 == 0`; Day One is
Sunday, 7 November 1993, per the wiki's Time page, so this is now a
derivation rather than an inference — see the README's week-boundaries
note). The wiki's own open question box offers a second reading ("the
Saturday afterwards, with no clear pattern") and a claimed removal "after
Day 85"; neither is modelled. See `engine/effects/rooms/office.py`.

**It is not a pure redirect.** The Secret Garden's Conference Room case is a
completely different fixed formula — **4 apples + 3 oranges**, replacing the
bucket-plus-soil computation outright. **How many keys land there is still
unstated**: the wiki gives "a number of keys" with no quantity and, unlike the
Patio, not even a dependency hint, so the borrowed bucket supplies the number by
default.

### Allowance, and the Mora Jai boxes

**Allowance is a permanent accumulating total, and it is the next day's starting
money** — three +2 tokens collected over seven days means 6 coins at the start
of the eighth. Base 0, no ceiling; neither is stated anywhere, so neither is
invented. The packet appears in the Entrance Hall each morning and the sim
grants it at `reset()`, which is the modelling simplification.
[`scoping-and-carryover.md`](scoping-and-carryover.md) owns the channel and the
fact that `allowance` resets at the attempt wrap while `stars` does not.

**Most sources are one-time, and uniqueness does not implement that.** A unique
item is only blocked while *held*, so a source re-mints the next day; one-time
allowance sources ride the carried-set shape (`collected_allowance_tokens`)
instead. That exact bug was measured at 7 duplicate disks per day before
`collected_disks` was added.

- **One-time**: the Cloister, every Mora Jai box, the Reservoir and Vault boxes,
  the Entrance Hall vase.
- **Repeatable**: Trading Post tier-5 trades, Jack Hammer digging, Room 8, the
  Quest Bedroom (once per day maximum), Cloister of Lydia, Casino roulette, the
  Guess Bedroom, the Laundry Room's Star/Allowance swap, and an experimental
  effect worth +1.

**Every Mora Jai box holds a +2 allowance token**, across all ten standard
locations. The wiki states the contents for only four; the owner ruled the
pattern holds for the rest, replacing an earlier deliberate refusal to guess
them.

| location | boxes | allowance |
|---|---|---|
| Cloister | 1 | +2 |
| Master Bedroom | 1 | +2 |
| Solarium | 1 | +2 |
| Trading Post | 1 | +2 |
| Closed Exhibit | 1 | +2 |
| Tomb | 1 | +2 |
| Lost & Found | 1 | +2 |
| Tunnel | 1 | +2 |
| Throne Room | 1 | +2 |
| Underpass (**area node**) | 1 | +2 |
| Inner Sanctum (**area node**) | **8** | **+16** |

**One gap left open on purpose:** the wiki lists a Vault deposit box **53**
alongside 149 and 233, and this repo carries no `vault_key_53`. Whether that is
a missing box or a wiki-only number is unverified, and it is stated rather than
guessed in either direction.

**A fully explored save banks +36 allowance from boxes alone**, before any
repeatable source — 36 coins at the start of every subsequent day. Allowance is
unspendable income arriving before any decision is made, so it shifts what an
early-day gem or key purchase is worth; that is worth watching the first time a
policy trains against it. **+16 of the +36 sits behind Room 46 and the eight
Sanctum Keys**, so no allowance figure from untrained play is representative.

The endgame sets are excluded: Aries Court's 8 boxes and Rough Draft's 46
contain a note instead of a token and are not permanently opened.

**Two of the eleven cannot use `guaranteed_in`.** The Underpass and the Inner
Sanctum are area nodes, not rooms, so a room record cannot reach them; they use
`special_items.py::on_area_arrival`, the same channel as the Abandoned Mine's
Upgrade Disk.

## The Mail Room family

Four records share one cycle: the base `mail_room` and the three upgrade
variants Same Day Delivery (`__ix89`), No Contact Delivery (`__ix90`) and
Freight Shipping (`__ix91`). All four are Tomorrow Rooms.

### The cycle is not a countdown

The base Mail Room's own card text — "a package will be delivered here the day
after drafting this room" — **is wrong, and the wiki wins**: the package can
wait any number of days for a Mail Room to be drafted again and **cannot be
missed**. So the base room is a persistent per-attempt state machine, not a
timer:

- **EMPTY + draft** → an order is placed, the cycle becomes AWAITING, nothing
  else happens.
- **AWAITING + draft** → the package is delivered into *that* Mail Room's own
  cell and the cycle returns to EMPTY. Walking into the cell grants it; leaving
  it uncollected loses it, because the next day's floorplan is a fresh draft
  with no memory of an unentered cell.

*An implementer coding to `effect_text` alone would build a one-day timer that
loses the package — a strictly harsher room than the real one. The card text is
a game string, not a spec.*

### The three variants

- **Same Day Delivery** arms its cell to deliver the moment Rank 8 is entered
  (immediately, if Rank 8 was already reached today). If Rank 8 is never
  reached, it falls back overnight to the base AWAITING state: the next draft
  delivers immediately, places no new order, and a later Rank 8 arrival does not
  deliver a second package.
- **No Contact Delivery** places an order on **every** draft and arrives as a
  **day-start inventory injection** through `GameConfig.starting_items`, rather
  than as a physical package on the entrance steps. *The simplification: the
  player cannot decline or fail to collect one, whereas in the real game they
  could in principle walk past it. The sim has no "decline the loot" concept
  anywhere, so the difference is unobservable today.*
- **Freight Shipping** places an order on an empty cycle and enters TRANSIT for
  two days, during which drafting the room does nothing at all — no re-order, no
  delivery. Once transit elapses the cycle promotes to AWAITING and behaves like
  the base room. Freight's contents are rolled at **draft** time, not entry
  time, since the items are immediately available.

### Contents

**The package contents are fully datamined** — three independently rolled slots,
slot 2 with a 50% chance of 2 gems, slot 3 conditioned on what slot 2 produced —
and every item involved already exists in `special_items.json`. This retired an
earlier assumption that the contents were an unpinnable weighted tree and only
the timing could be modelled.

**Freight's resource configurations are the one genuine gap.** The wiki states
the set — 4 keys, or 2 keys + 2 gems, or 4 gems — and publishes no weights, so
each is a uniform third, `confidence: inferred`, replaceable by a data edit the
moment a real weighting appears.

The observation key is `[cycle code, transit days remaining, No Contact
ordered]`. Slot `[2]` reads the **forward-looking** flag — drafted today,
package lands tomorrow — not "a package arrived this morning": the key exists so
`V(s)` can price a cross-day investment, and the investment is the order, not
the already-collected payout.

## Per-room rules

Alphabetical by room id. A room whose whole behaviour already belongs to another
document is not repeated here.

**`aquarium` and its three upgrade variants** — the Aquarium counts as **every
colour**, carried as `extra_categories` rather than a one-room escape hatch. The
Electric Eel Aquarium additionally counts as Mechanical. Measured before the
fix: a Patio spread targeted **24** rooms where the wiki implies **29**,
understating the payout by up to 5 gems in a large house. *A ruling recorded but
never implemented is indistinguishable from one never made* — this one sat
written-down-but-unbuilt for a day while every category-keyed mechanic quietly
ignored the Aquarium. The Starfish Aquarium separately grants +1
permanent star on every draft.

**`billiard_room`** — the Dartboard is a puzzle object inside the room, never a
room of its own, so it has no `rooms.json` record and no action id: entering a
freshly drafted Billiard Room auto-solves it under
[`doctrine.md`](doctrine.md)'s assumed-solved rule and grants a day-banded
prize, **at most once per day across every Billiard Room cell** rather than once
per cell — a second `billiard_room` can reach the grid through the Chamber of
Mirrors and would otherwise pay out again.

**`boudoir` and `boudoir__ix16/17/18`** — each of the four carries the safe gem
in its own right. Room effects are **not** inherited through `variant_of`, so
without the repeat, upgrading the Boudoir would silently delete its safe. A safe
is a fixture of the room and survives every upgrade.

### Safes grant their gem every day

A safe's gem **respawns**: the wiki's Safes page states that safes "remain open
permanently once they are first opened, and the gem respawns, making opening a
safe a permanent upgrade to a room". Under the assumed-solved doctrine that is a
plain per-entry `grant` of 1 gem, not a one-time pickup — which is why the
Boudoir, Drawing Room, Office, Study and Shelter each carry one. The one off-grid
safe is at Upper Rotating Gear; [`areas.md`](areas.md) owns it.

**Two published safes deliberately grant nothing, and their absence is not an
oversight**: the Drafting Studio's safe "does not contain a gem", and the Apple
Orchard's contains neither gem nor red letter. The Study's safe additionally
holds the Closed Exhibit floorplan, which is not modelled.

**`bunk_room`** — counts as 2 Bedrooms (`counts_as_bedrooms`). *The true
behaviour is unpublished: the wiki carries its own open-question box saying it
"is not consistent from effect to effect", counting as one Bedroom for some and
three for the Day Overview. A flat 2 is consistent with the rest of the codebase
and wrong only where the wiki itself cannot say.*

**`clock_tower`** — pays for every Tomorrow room **present in the house** at day
end, **including the Clock Tower itself**. The page contradicts itself — the
infobox says "for each Tomorrow room you draft today", the prose says "present
in the mansion" — and the prose wins. The two readings differ whenever a
Tomorrow room enters the house without being drafted, which the Foundation
already does by persisting across days.

**The Cloister variants** — each pays "for each X drafted **from this
Cloister**", resolved by comparing the pending draft's `from_cell` against the
Cloister's own cell. Dauja's "room with an animal" and Veia's "room with a
fireplace" are **ad-hoc wiki enumerations, not semantic rules** — a mounted fish
and stuffed plushies qualify where taxidermy elsewhere does not — so they are
carried as `has_animal` / `has_fireplace` flags on the named records. The Dining
Room's fireplace is the one exception: it depends on the cell the room lands on.
Joya's Main Course bonus is read as per-attempt, an owner-flagged assumption
since the wiki never says "across the save".

**`conference_room`** — see "Spread effects" above; it has no effect of its own.

**`conservatory`** — a Green Room (it was wrongly `blueprint`, a plain data
error). Reachable only through its **Found Floorplan**: arriving at the
campsite while holding a shovel permanently sets
`state.conservatory_floorplan_found`, and `decks.py::eligible_pool` adds the
room to the pool from the *following* day, since `build_decks` runs at day
start. It is `rarity: unusual`, `gem_cost: 1` — so it deals from the **gem**
decks — `corner_only`, and it counts as a Drafting Room.

Its content is the **drawing board** (`engine/effects/rooms/conservatory.py`,
`Capability.DRAWING_BOARD`). Drafting the room stocks the board with three
floorplans; standing in the room, each row may be clicked once to set that
room's rarity to any of the four levels (`Game.can_remodel`/`remodel`, action
ids `REMODEL_BASE`). Five rules govern it, four of them owner rulings from
play, which outrank the wiki and the datamine:

- **The three offers are drawn uniformly at random WITH replacement**, so the
  same room can occupy two rows. This settles what the datamine left open — it
  says only *"the table presents three random rooms that passed the filters"*,
  with no rarity term and no with/without-replacement statement — and it also
  reads the datamine's "bugged entries that appear like one of the other
  entries already present" as a plain non-de-duplicated draw rather than a
  special case.
- **The rarity change is ALL THREE, not any one**: each row is clicked
  independently, so a player may set one, two or all three.
- **A no-op click counts as a use.** Picking a floorplan's own current rarity
  spends the row exactly as any other pick does. It leaves no
  `permanent_rarity` entry behind, the same idempotent pop
  `Game.set_wrench_rarity` performs, because the room's rarity genuinely is its
  natal one.
- **A modified room stays eligible**, so the offer pool never shrinks. This
  *contradicts the datamine*, which drops from future offers any room whose
  rarity has been changed by any method (and says a Room Directory reset does
  not un-drop it). Owner play governs; the conflict is recorded, not smoothed
  over.
- **Frequency is unsourced**, and is the one assumption here:
  `conservatory.CLICKS_PER_FLOORPLAN = 1`, with the board re-stocked on every
  Conservatory draft. The wiki's own effect text ("re-rolls the rarity of 3
  rooms in your pool **each time you draft it**") is the closest thing to a
  source. Because a floorplan is drafted at most once a day, once-per-draft and
  once-per-day coincide today. Any finite value bounds the day: the board
  offers at most `BOARD_OFFERS * CLICKS_PER_FLOORPLAN` clicks between
  stockings, each strictly incrementing `GameState.remodel_clicks`.

A click writes the **same permanent slot the Gear Wrench writes** — one shared
`Game._write_permanent_rarity`, so a remodel can reset a wrench-set rarity and
vice versa, exactly as the wiki requires. The wiki's rider that a room whose
rarity is ever set has its **Dynamic Rarity permanently ignored afterwards**
costs nothing here for the same reason it costs nothing for the wrench: this
sim does not model Dynamic Rarity at all ([`drafting.md`](drafting.md)).

The offer pool is `decks.eligible_pool` (which already enforces the datamined
"Studio Additions must have been added" / "Found Floorplans must have been
found" clauses, plus Repellent bans and Upgrade-Disk substitution) minus
`data/conservatory.json`'s two lists: `always_excluded` (Freezer, Pump Room,
Dovecote, and the Conservatory itself) and `draft_gated` (the Gift Shop, until
drafted once). **That list is deliberately incomplete**: the datamine implies
16 unchangeable rooms and no source in this repo names the other twelve, so the
sim's pool runs ~90 where the game's runs ~85. Disclosed in the data file, not
silently absorbed.

The board is deliberately **absent from `Game._in_place_actions`**, for the
Royal Scepter's reason: a click grants nothing and opens nothing, so it must
never be what holds a day open. It is bounded anyway, so including it would
have been safe — see that method's docstring.

**`funeral_parlor__ix110`** — the prize box holds one gem per Red Room in the
house, counted at the moment the box is opened (this room's own first entry),
via `is_category("red")` so the Aquarium family and the room's own red record
both count — the latter is why the grant is never zero. Capped at 16, the
physical limit on gems in the box. **Its 30-step penalty never fires**: it
applies only to opening an empty box, and under the assumed-solved doctrine the
box opened is always the prize box.

**`geist_bedroom__ix69`** — the dice are on a table **inside** the room and are
picked up by entering, confirming the entry-time reading the wiki only hinted at
with "spawns" and matching every other resource grant in the engine.

**`great_hall`** — **all three** non-entry doorways are guaranteed locked
(`data/locks.json`'s `always_locked_rooms`, the symmetric counterpart of
`always_unlocked_rooms`, consumed at `locks.py::roll_segment` before any hook
fires). The room's effect text says "7 Locked Doors" and our grid has no
subchambers: in the real game the far doorway is a genuinely locked drafting
door while the two side drafting doors are themselves unlocked but sit behind
three locked inner doors each, only one of which is the passage. So the side
doorways additionally carry the **expected cost of finding the right inner
door** — the wiki's theoretical table gives the centre door 50% and each edge
25%, and opening in the optimal order costs 1.75 keys in expectation, stored as
extra keys beyond the base 1. [`locking.md`](locking.md) owns how that surcharge
reaches the agent through `grid_search_cost`. Entering pulls the Antechamber's
east lever, behind the prize room's own locked side door, so a key is spent and
no key in hand means no lever. A Foyer on the estate overrides the guaranteed
locks, matching "unless some other effect forces them to be unlocked".

**`guess_bedroom__ix70`** — loses the base Guest Bedroom's +10 steps and instead
secretly picks one Bedroom from today's draft pool **when it is drafted**,
taking on that room's effects. The chosen id is state, not a local, because once
one Guess Bedroom mimics something every later one that day does too. Published
selection rules honoured: never itself, Her Ladyship's Chamber, the Master
Bedroom, or the Spare Bedroom and its upgrades; Repellent-banned floorplans are
excluded **except the Hovel**, which is always selectable even if already
drafted and even before unlock; rooms already on the estate are eligible if the
Chamber of Mirrors returned them to the pool; the **upgraded** version is
mimicked where an upgrade applies; and if no valid option exists and the Hovel
was not chosen, the mimic fails and the room has no effect. **The Aquarium
family is outside the selectable set** — mimicking it means inheriting its extra
colours, and `Room.is_category` would have to become state-aware for one cell,
which backs category biases, `grant_per_category`, the Cloister and Terrace
green boosts and scepter colours. The wiki records that the real game is buggy
here too. Reversible; the gap is on the record's own `meta.blocked_on`. The wiki
says Servant's Quarters is "more commonly selected than the other floorplans"
and gives no number: recorded as `null`, **not invented**.

**`inner_sanctum`** (area node) — eight chambers, one per realm (Arch Aries,
Corarica, Eraja, Fenn Aries, Mora Jai, Nuance, Orinda Aries, Verra), each
permanently opened by one consumed Sanctum Key and each holding a Mora Jai box.
[`areas.md`](areas.md) owns the graph edges. **All eight Sanctum Keys require
Room 46 and simply do not spawn before it** — owner play, overriding a wiki that
states that condition for exactly one key and says of the others only that they
are "usually discovered around the same time". The gate reads the existing
`room46_reached` carry-over flag at spawn time, so no new state was needed. *The
consequence is deliberate, not a side effect:* every Sanctum Key, all eight
chambers and the +16 allowance behind them are unreachable until Room 46 is
first reached, and measured `P(room 46)` is 0.000 — acceptable under
[`doctrine.md`](doctrine.md)'s features-are-built-to-be-PLAYED rule, because the
owner reaches Room 46 by playing and the recorded day teaches the policy.

**`lost_and_found`** — its item count runs the published transform (add one to
the ladder's result, then clamp to 2–4) rather than the earlier fixed,
luck-independent 2-item draw that bypassed the ladder entirely. The steal and
gift behaviour lives on the same path and is owned by
[`special-items-behaviour.md`](special-items-behaviour.md).

**`maids_chamber`** — red **and** bedroom. Its −7 luck on placement is owned by
[`luck.md`](luck.md), including the proof that only −7 satisfies the Dowsing
Rod's datamined "four Maid's Chambers" branch.

**`mechanarium`** — **the door count is set at draft and never grows.** Drafting
more Mechanical rooms afterward adds no doors, confirmed verbatim by the wiki
and independently by `Template:Interactions/Mechanical Room`. This is what makes
the room buildable at all: a count that grew would need live mutation of a
placed room's door mask, and `placed_doors` is written in exactly three places,
none reachable from an effect handler. [`drafting.md`](drafting.md) owns how the
mask is derived and why a doorway blocked by a neighbour's blank wall is
**skipped without consuming its slot**.

Mechanical rooms beyond the cardinal doors open **diagonal compartments**,
modelled as containers at the Mechanarium's cell in a fixed order: 1st a Broken
Lever, 2nd a key, 3rd the Upgrade Disk, 4th a Sanctum Key. **The real gate is
that spawn threshold, not "gated mechanical arms"** — a full pass over the
Mechanarium page found no wiki support for any arm mechanic, and the phrase has
been removed everywhere it appeared.

The eight Mechanical rooms, all `category: blueprint` with `mechanical` as an
extra category: `utility_closet`, `boiler_room`, `pump_room`, `security`,
`workshop`, `laboratory`, `electric_eel_aquarium__ix4`, `mechanarium`.

**`observatory`** — **+1 permanent star every time it is drafted**, uncapped,
fired on `ON_PLACE` rather than on entry, so a draft pays even if the player never
walks in. No published cap exists, so capping it would be an invention. **This is a
known self-amplifying loop and it is left open on purpose because it is faithful**:
draft Observatory → +1 star → a richer night sky → more resources → more drafts,
with up to four Observatories reachable in a day through the Chamber of Mirrors.
Stars are save-scoped and buy constellations, so the loop compounds across an
attempt rather than resetting nightly — the same shape as the Vestibule's farmable
reroll below, but with a permanent currency rather than a per-entry one. Whether it
dominates a trained policy is an open question; the point is that it is known
before the retrain, not discovered after it.

**`office`** — its terminal runs two independent processes
(see "The Office's coins" above), both gated on standing at its cell
(`Capability.OFFICE_TERMINAL`, `engine/effects/rooms/office.py`), distinct
from the room's own `flags.disk_reader` (a third, unrelated terminal
process, already shipped):

- **Spread Gold in Estate** (once per day) IS a spread: a pile of coins into
  every currently drafted room, including the Office itself but never a room
  drafted afterward, via `GameState.spread_pending`/`Game._collect_spread` —
  so a placed Conference Room redirects every pile into its own cell, the
  same way it redirects the Patio/Locker Room/Secret Garden. Pile size is a
  random 3, 4, or 5 coins per receiving room — an owner ruling, since the
  wiki publishes no figure for this spread (unlike the Tomb's flat 5 coins),
  reusing the Office's own published floor-item pile sizes as the game's own
  answer.
- **Run Payroll** puts 10 coins in each of the Maid's Chamber and the
  Servant's Quarters (two piles of 5; the Servant's Spare Quarters upgrade
  variant is not named by any source describing this process, so it does
  not receive a pile). NOT a spread — the wiki states no Conference Room
  interaction — so it pays out through a separate `GameState.payroll_pending`
  dict keyed by room id, letting a target drafted *after* the terminal is
  used still receive its pile. Its weekly cooldown resets on the coming
  in-game Saturday after use (owner ruling: the wiki's own open question box
  offers two readings and a claimed Day-85 removal; this models the shorter
  "coming Saturday" reading with no Day-85 special case). Saturdays are
  exactly `day % 7 == 0`: the wiki's Time page states Day One is Sunday, 7
  November 1993, so this is a derivation, not an inference.

**`parlor` and its variants** — the box always grants a fixed number of gems on
first entry. [`special-items-behaviour.md`](special-items-behaviour.md) owns the
grant and why the Wind-up Key is deliberately not modelled;
`parlor__ix109` ("2 Wind-up Keys") therefore references a concept that no longer
exists and is a **deliberate permanent finding**, not an oversight. Do not
"fix" it by reintroducing the item.

**`planetarium`** — a Tomorrow Room whose Telescope unlock permanently upgrades
it: once a planet is unlocked the room carries that planet's payload every day
going forward, re-applied generically from the data table rather than by
hard-coding which planet is which. **Its 2 stars are gated on ending the day
there**, not on entry: `Hook.ON_DAY_END` fires only for the room the player
stands in at termination.

**`quest_bedroom__ix71`** — a **Bedroom**, not an objective room. Our ingest let
`type2 == "Objective"` override the real type, so the room landed as
`category: "objective"` and **every Bedroom-counting mechanic silently skipped
it** — the per-Bedroom gem cost, Cloister of Mila, the Sleeping Mask, bedroom
category biases. "Objective" in the sheet marks *pays out on reaching the
objective*, which is a reward condition, not a room type; the ingest rule is now
narrowed to the two rooms that **are** the objective, and `objective` names
exactly the Antechamber and Room 46. Entering the Quest Bedroom arms an
Allowance Token paid on the next Antechamber arrival — registered on the
Antechamber at `ON_ARRIVE` so re-entry counts, and paid at most once per day.

**`room_8`** — the first solve of an **attempt** grants 2 Allowance Tokens and
every later solve grants 1. The wiki's real discriminator is trophy
*possession*, not solve ordinality; with no trophy concept
([`doctrine.md`](doctrine.md)) the sim cannot tell those branches apart, so the
reading that matches how a real player behaves was chosen — the trophy is taken
on the first solve. **Room 8 is repeatable per draft, not once per save**: it
resets each time it is drafted, and multiple Key 8s allow multiple simultaneous
Room 8s, each paying on its own first entry.

Its placement rule is **any Rank-8 cell**, not the two cells `placement.py` once
whitelisted. The wiki says Key 8 works on "any locked door that leads to a room
on Rank 8"; the two whitelisted cases were the wiki's enumeration of when the
room is **mirrored**, not of where it may be placed. The decisive evidence is
the wiki's own "reliable" route — Room 8 can be reliably drafted from the far
door in the Great Hall, which is a `cross` with no draft conditions and so sits
in any column. Under the old rule that route was impossible and Room 8 was very
nearly undraftable, which is why its unmodelled reward never surfaced in play.
**A `draft_conditions` tag that encodes an orientation rule as a legality rule
silently deletes most of a room's placements**; mirroring belongs in the
orientation layer.

**`secret_garden`** — see "Spread effects". Entering also pulls the
Antechamber's west lever at no extra cost.

**`servants_quarters` and `servants_spare_quarters__ix134`** — one key per
Bedroom, **cap 15**, on both records. A placement or behaviour rule applies to
an upgrade variant that inherits the base's rule; the variant carried the
uncapped version for a while because the base gained its cap during unrelated
work. This is an invisible-until-the-count-gets-large shape.

**`shelter`** — negates the effects of the next 3 red rooms **drafted after
it**, and grants its safe gem. It is an **outer** room, so the grant rides
`Game.travel_to`'s `ON_ENTER` rather than the grid path.

**Protection is scoped by draft order, never by when a room's own penalty
happens to resolve.** The three protected rooms are exactly the first three red
rooms drafted after the Shelter, and which three they are is settled the moment
they are drafted. `effects/rooms/shelter.py`'s `ON_PLACE` grants three
unclaimed charges into `game.red_negations`; its `on_room_drafted`, called from
`Game._place_room` before the drafted room's own `ON_PLACE`, hands one charge to
each red room drafted afterwards until they run out, naming the room in
`game.shelter_protected_ids`. `effects/tier1.py::_red_negated` negates a
penalty only for a room in that set, and releases that room's claim as it does.

Two consequences follow, both deliberate:

- A red room already on the board when the Shelter is drafted is never offered
  a charge, so it keeps its penalty even if that penalty is entry-triggered and
  does not fire until much later.
- A charge is spent by *drafting* a red room, not by negating something. A
  Darkroom drafted with its lights already off keeps its claim unused for the
  rest of the day rather than returning it to the pool. Returning it would put
  a fourth red room's protection back at the mercy of which penalties happened
  to resolve first, which is the whole thing draft-time claiming removes.

The Shelter is a `blueprint` room, not a red one, so its own draft claims
nothing. Claims are keyed on the room's own id rather than
`upgrades.root_base_id`: the room claiming and the room whose penalty later
resolves are the same `Room`, and a red upgrade variant carries its penalty on
its own record, so both sides already agree without normalising. Both
`red_negations` and `shelter_protected_ids` are plain `Game` attributes blanked
by `Game.reset`, so a claim is scoped to the day that made it and rides no
carryover channel.

**`shrine`** — deposit 1–80 gold and receive one of eight blessings lasting 3–7
days (the granting day counts as day 1); taking the offering back curses you for
2 days instead, and only one blessing or curse is active at a time. The band
table, the 8×5 coin pairs and all eight blessing effects are published. **Six of
the eight are live** — Dancer, High Roller, Gardener, Tinkerer, General, Berry
Picker; Chef (needs Dining Room dish tracking) and Monk (needs grounds drafting)
stay inert.

The draft-time half of a blessing or curse fires on **every** room you draft,
the once-per-day **outer** draft on the grounds included: those checks read only
the drafted room's own categories, never the grid, and the wiki's West Path page
says drafting effects unrelated to the draft pool still work when drafting on
the grounds. So the High Roller's die lands on a Trading Post drafted at the
Outer Room door, and the curse takes its per-category coin/gem/step from a
Trading Post, Root Cellar or Hovel drafted there. `Game._choose_outer` and
`Game._place_room` both call `shrine.on_room_drafted` for this. The General and
Tinkerer checks are unreachable from the outer pool, none of whose eight rooms
is Red or Mechanical.

The action space is **8 blessings × 5 durations = 40 actions** with the coin
cost derived, rather than 80 raw donation amounts: nothing is lost, since the
wiki notes there is little reason to offer an even number of coins except to
deprive oneself of gold. The state is save-scoped and day-decayed — a blessing
id, a remaining-days count, a parallel curse-days count and a monk-room key,
carried the way `stars` is but decremented the way `mail_transit_days` is (see
[`scoping-and-carryover.md`](scoping-and-carryover.md)). The curse path is the
only gate to `cursed_effigy_unlocked`.

**Unpublished, do not encode:** the Shrine page source carries a commented-out
claim that the Veranda incurs the curse penalty when its cost is bypassed. It
was drafted by an editor and never published.

**`spare_great_hall__ix139`** — its layout is **`straight`**, not `cross`: the
wiki wins over our datamine row's `4-Door`, saying flatly that the Spare Great
Hall does not inherit the Great Hall's shape and drawing the consequence
explicitly — *it may be drafted along the edges of the house*, which a 4-way
never can under the outer-wall invariant. This changes which of the 45 cells the
room can legally occupy. The correction goes through `LAYOUT_OVERRIDE` in
`tools/ingest_sheet.py`, **not** a hand-edit to `rooms.json`, or the next
re-ingest reverts it.

Per the wiki it has no side doorways, no Antechamber lever, no Upgrade Disk, and
its far door is not necessarily locked — so its entire published effect is
invisible at grid granularity. Rather than declare it permanently inert it
grants its **published prize contents** (four cyan gems / a key + a cyan gem + 5
coins / 20 coins) as an items roll, which is the only option that leaves the
room doing something a player can observe. Gem colour is not modelled, so a cyan
gem is granted as a gem.

**`the_kennel`** — once drafted, digging in **any** room with locked doors
unlocks that room's doors, security doors included. All dig spots count, as does
a Treasure Map dig, and every dig tool triggers it: the hook sits in
`special_items.dig_all`, the single path all tools funnel through. The Kennel
need only be drafted, never entered. *The wiki's own note that the effect "often
does not work in the Foundation" carries an open question asking why, so it is
unexplained behaviour rather than a rule and the Foundation is treated like any
other room.*

**`throne_room`** — a backup north-door lever, pulling the same segment the
Inner Sanctum's main lever opens, at no extra cost beyond entering
([`rewards.md`](rewards.md) owns what that pays), plus a Mora Jai box worth +2
allowance. Only the crown objective is genuinely out of scope. The room is
**supplemental-sourced**, so both `tools/supplemental_rooms.json` and
`rooms.json` change together — see [`doctrine.md`](doctrine.md).

**`tomb`** — 5 coins per Dead End drafted in the house, the Tomb itself
included, spread into the Tomb and collected when the player walks in (see
"The Tomb's coins" above, which owns the rule). Drafting it as the outer room
**and entering it** sets `catacombs_unlocked`, opening the Catacombs for that
day only.
Deliberately **not** a permanent carry-over flag even though the wiki says the
angel-statue puzzle opens the wall permanently: reaching the Catacombs still
needs the Tomb present that day. Modelled as `flags.unlocks_catacombs` on the
Tomb record rather than a hardcoded id, so the rule is a data edit.

**`treasure_trove`** — permanently gains a 5-coin pile per draft, and **every
draft collects the whole surface**, so the Nth draft of an attempt pays 5 × N.

| draft | pays |
|---|---|
| 1st | 5 |
| 2nd | 10 |
| Nth (N ≤ 32) | 5 × N |
| 33rd and every later one | **160** |

The wiki's "maximum of 32 piles (160 Gold Coin total)" caps **what a single
draft is worth, not what the room earns over an attempt** — past 32 piles the
payout stops growing, it does not stop. The first 32 drafts alone come to
5 × (1+2+…+32) = **2640 coins**. The payout is a pure function of
`state.draft_counts`, incremented immediately before `ON_PLACE` fires, so it
cannot double-count on re-entry. *The first implementation read the cap as
ending the payout — a flat 5 per draft, 160 lifetime, then nothing — worth 6% of
the real figure. When a source gives a cap alongside a per-event gain, establish
whether the cap bounds the event or the total before coding it; here the two
readings differ by 16×.*

**`vestibule`** — every entry closes all four doors, locks **one at random** and
unlocks the other three, regardless of what was locked before. Registered at
`ON_ARRIVE` so re-entry retriggers it, which is exactly the wiki's own framing:
the player can reroll a bad lock at the cost of 2 steps per attempt. The roll
draws from one fixed named substream, so re-entering consumes the next value —
**a deterministic reroll a policy can farm, left uncapped on purpose because it
is faithful.** A Foyer on the estate skips the roll and forces every doorway
open. Vestibule doors are never security-locked. The sim has no separate
open/closed door state, so forcing three open and one locked is the entire
observable effect.

## Deliberate divergences

- **The Conservatory's offer pool is wider than the game's**, ~90 rooms against
  the datamine's implied ~85, because no source in this repo names twelve of
  the sixteen rooms whose rarity cannot be changed. See the `conservatory`
  entry above and `data/conservatory.json`.
- **The Mail Room's Dynamic Rarity effect is not modelled.** A waiting package
  sets the Mail Room to Commonplace for the day, which makes the delivered room
  far easier to draw again — a real strategic effect, not flavour. **Any
  measurement of how often a delivered package is actually collected is an
  underestimate until this lands.** The original reason for deferring (no
  rarity-override channel in `decks.py`) has **expired**: `set_dynamic_rarity`
  is exactly that channel. This is the Mail Room specifically, not the wiki's
  ~25-room Dynamic Rarity table, which [`drafting.md`](drafting.md) records as
  unmodelled.
- **The Mail Room's cycle state is shared across all three variants.**
  `GameState.mail_cycle` and `mail_package_cell` are a single global slot, so an
  `awaiting` cycle placed by one variant is delivered against by a different
  variant. Narrow — it needs two different Mail Room upgrades applied across one
  attempt, and only one variant is normally active at a time. Recorded rather
  than patched; fixing it means keying the cycle by variant id.
- **The Locker Room's locker loot is inferred, not datamined.** The 3 open and
  17 locked lockers are modelled as containers at the room's cell (one key
  each for the locked ones, free for the open ones —
  [`special-items-behaviour.md`](special-items-behaviour.md) owns the kinds),
  but their loot tables are inferred from the item pages that name a locker as
  a source. The wiki's 36-locker total minus 16 sealed is what fixes the 3/17
  split.
- **Per-room spread failure is not modelled.** The wiki notes some targeted
  rooms do not actually receive their spread, with no published success rate, so
  the computed count is simply the number of items placed.
- **The Cloister of Draxus's pool restriction is not modelled.** Its "you WILL
  draft" wording is a certainty in the real game because that Cloister's draft
  pool is restricted to Dead Ends; only the reward half is modelled here, paying
  out for whatever Dead End is actually drafted.
- **The Mechanarium's compartments open in a fixed order at no cost**, rather
  than the player's free choice of which door to open first, and which physical
  corner each occupies is not tracked — only the deterministic open order, which
  is enough to reproduce the fixed loot-per-position table.
- **The Guess Bedroom cannot mimic an Aquarium**, because that needs a
  state-aware `is_category`. Recorded on the record's own `meta.blocked_on`.
- **The Speakeasy is a modelled no-op**, not a gap: its "Basic Addition" only
  makes the Dartboard Puzzle easier, and the puzzle is already assumed won, so
  it pays exactly what the Billiard Room pays. [`doctrine.md`](doctrine.md) owns
  the general form of that rule and the `_AUDIT_DOCTRINE_EXEMPT_IDS` channel.
- **`parlor__ix109` is permanently inert on purpose** — see above.
