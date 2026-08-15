# Draw behavior: the drafting algorithm

How a hand of 1-of-3 room options is produced when the player opens a
doorway. This reproduces the decompiled v1.3 algorithm; the code path is
`engine/decks.py` → `engine/draft.py` → `engine/placement.py` →
`engine/rotation.py`.

This document is authoritative for the draft pipeline: deck construction, the
Free/Gem decision, the rarity roll, the four draw mechanisms that can override
it, placement and orientation, colour-selective drafting, redraws, and
concealment. Rules about how long a fact lives are in
[`scoping-and-carryover.md`](scoping-and-carryover.md); rules about which
source wins a disagreement are in [`doctrine.md`](doctrine.md).

## The order of operations

A hand is dealt by `draft.py::_fill_options`, once per *round*. A round is one
deal of three slots; a redraw of the same doorway is a new round of the same
draft, and a new doorway is a new draft. Both counters matter — `state.
drafts_today` gates the Free/Gem carve-outs and the Garage's once-per-day
forced draw, `PendingDraft.round_num` gates Slot 3's "third round or later"
rule.

Per hand, in this order:

1. **Tunnel chain** — drafting north from a placed Tunnel pre-fills slot 0.
2. **The Foundation's rank-3 removal** — one roll per hand, not per card.
3. **The Free/Gem Draw decision** — one roll per round, covering slots 1 and 2.
4. **Per slot**, in slot order:
   1. **Day 1's opening draw** (a Guaranteed Draw) fixes all three slots at
      once and short-circuits everything below.
   2. **Reading Nook's Library guarantee** on slot 2.
   3. **Silver Key** cross/T bias, initial deal only.
   4. **Garage Forced Draw**, slot 2 only.
   5. **Priority draws**, every slot, attempt 1 only.
   6. **Attempts 1–4**: rarity roll → deal → category bias, then reshuffle,
      then the forced Closet.
5. **Dowsing Rod** picks one dealt slot.
6. **Darkroom** concealment, then **Archives** archiving.

The four JSON-driven mechanisms in step 4 are genuinely different things and
the wiki is explicit that they are: a **Guaranteed Draw** runs ahead of the
normal algorithm and fixes the whole hand; a **Forced Draw** pushes one named
room into slot 3; a **Priority Draw** is an extra filter applied inside an
otherwise-normal draw on any slot; a **category bias** re-deals an
already-rolled slot. Conflating any two of them has cost real behaviour twice —
see "Deliberate divergences".

## Decks

Eight solitaire decks are built at day start from the enabled pools: 4
rarities (commonplace / standard / unusual / rare) × free / gem-cost
(`engine/decks.py`). Dealing is solitaire-style — a dealt room does not
repeat until its deck depletes and reshuffles. Every room with a rarity has
exactly one deck copy (`deck_copies == 1`, data-verified), so a card drawn out
of a deck is that room's only card.

A card's effective rarity IS the deck it sits in — dealing never reads a
card's own rarity, only the rarity index handed to it. That is what makes
every rarity-changing effect in the game a *card move* rather than a field
write, and three primitives implement it:

- **`inject_rooms`** adds copies mid-day by reshuffling the whole target deck
  and rewinding its cursor, so cards already dealt this cycle become dealable
  again. Correct for its once-per-day callers (The Pool, the Nook's Morning
  Room, the Hallway's extra copies).
- **`inject_rooms_undealt`** inserts at a uniformly random *undealt* position
  and leaves the cursor alone. This is the shape an effect that fires many
  times a day needs; `inject_rooms` would silently un-deal every card already
  drawn. Used by the Shrine's Gardener mode and the `add_aquariums` experiment.
- **`set_dynamic_rarity`** moves a room's cards to a different rarity's deck of
  the same free/gem class for the day (`GameState.dynamic_rarity`). Idempotent
  — a repeat call consumes no RNG — and it preserves dealt-ness by landing
  already-dealt copies just before the destination cursor. Leaving a dealt copy
  behind in the source deck would let it be re-dealt after attempt 3's full
  reshuffle. Used by the Gear Wrench, the Battery Pack, the Conservatory's
  re-roll and the `add_aquariums` experiment.

Every path that touches a deck bucket — `inject_rooms`,
`inject_rooms_undealt`, `apply_upgrade` — looks the room up through
`state.dynamic_rarity` before falling back to its static rarity, so a
wrenched or re-rolled room is never split across two buckets.

The Gear Wrench's choice is save-scoped rather than day-scoped: it lands in
`cfg.permanent_rarity`, `build_decks` reads it for the day-start bucket, and
`Game.reset` seeds `state.dynamic_rarity` from the same dict so both agree from
the first deal onward.

**Deck-size gates** suppress rarities that have run low
(`weights.json::deck_size_gates`): free decks need ≥ 3 cards; gem decks need
5/5/4/4 (by rarity) once veteran mode, day ≥ 16, or Room 46 has been reached
(`GameConfig.gem_gate_active`), and merely non-empty before that. Slot 0 checks
the free deck alone; slots 1–2 pass if *either* class satisfies its gate.

## Free/Gem Draws

Whether a slot deals from the free decks or the gem decks is a published
decision step, rolled **once per round** in `draft.py::_resolve_free_gem` and
threaded through every deal in that round. A Free Draw searches only the free
deck of the rolled rarity, a Gem Draw only the gem deck: *"Free Draws only use
the four decks made out of free rooms, while Gem Draws only use the four decks
made out of gem rooms."* The two are never combined for a single draw.

The cascade, in the order the code evaluates it (this engine's slots are
0-indexed; the wiki's Slot 1/2/3 are engine slots 0/1/2):

1. **Slot 0 is always free.** Never consults the roll.
2. **Early carve-out.** On days 1–3, the first drafts of the day are all free:
   the first 2 drafts under Veteran Mode, otherwise the first `6 − day`.
3. **Slot 1's chance** comes from a rank × gems-in-hand table
   (`weights.json::free_gem_draws.slot2_gem_chance`), gem buckets **0 / 1–3 /
   4+**, ranging from **0%** at rank 1–3 with no gems to **59.26%** at rank 7–9
   with 4+ gems.
4. **A Slot 1 success forces Slot 2 to Gem** as well. This is why the roll is
   per round rather than per slot.
5. **Otherwise Slot 2 rolls its own chance**: always Gem from the third round
   of this draft onward; 20% in the day's first two drafts with 2+ gems held
   (and never otherwise); 20% in drafts 3–5 with 0–1 gems; and otherwise a rank
   table of **75% / 87.5% / 93.75%** (ranks 1–4 / 5–6 / 7–9).

The percentages live in `weights.json`. The thresholds — the day-1–3
carve-out, "third round or later", "first two drafts", "first five drafts" —
are formulas rather than published numbers and are code, matching the existing
split at `deck_size_gates.gem_gate_condition`.

**Deck membership uses a room's actual gem cost, ignoring modifiers.** An axed
room stays in the Gem decks; The Axe zeroes the *charged* cost, never
`Room.is_free`.

Evidence this step is load-bearing, from the measurement that added it: slot
0's gem rate stayed **exactly 0%** across 1776 draws before and after, while
slot 1's fell **31.79% → 2.14%** at ranks 1–2, which is what the table
specifies there. Before it existed, slot 3 ran ~44% gem where the real game
past its carve-outs is 75–93.75%, and day 1 dealt 8.6% gem where Veteran Mode
forces 0%.

## Per-slot rarity roll

Each of the three option slots is dealt independently:

1. **Rarity roll** from the datamined weight tables in `data/weights.json`,
   keyed by rank (1–9), slot (slot 0 vs slots 1&2), game stage
   (week 1 / week 2 / late), and Solarium presence (the Solarium flips to a
   flatter, rarer table). Rarities whose decks fail the size gates are zeroed
   before the roll.
2. **Uniform deal** from that rarity's deck *of the round's Free/Gem class*,
   skipping rooms that fail the placement filters below.
3. **Four draw attempts** per slot: attempts 1 and 2 are a fresh rarity roll
   and deal (attempt 1 additionally runs the priority-draw filter); attempt 3
   reshuffles **every** deck and retries once; attempt 4 is a **forced Closet**,
   which cannot fail because the Closet is a free commonplace dead end with a
   legal orientation everywhere.

**Drafting from the Library replaces the rarity row outright** — a datamined
full override (`weights.json::library_override`: 0% / 0.01% / 49.99% / 50%),
not a re-deal bias. The substitution happens inside `weight_row`, so it lands
*before* the deck-size-gate zeroing and an exhausted rarity is still suppressed
exactly as it would be for any other draft.

## Priority draws, forced draws and guaranteed draws

### Priority draws

`data/priority_draws.json`'s `priority_draws` is an additional filter applied
during **attempt 1 of every slot**, not just slot 3:

| entry | chance | note |
|---|---|---|
| Patio group (Patio, Veranda, Greenhouse, Morning Room, Secret Passage) | 5% | 50% while a Greenhouse is placed |
| Commissary / Observatory | 13% | |
| Garage / Classroom | 3% | |
| Aquarium ×2 rows | 13% and 3% | only while `add_aquariums` is active |
| Tomorrow Rooms | 40% | only while a Chronograph is held |

**Every named floorplan in an entry gets its own independent acceptance
roll** — *"each floorplan has a chance to get accepted"* — rather than one roll
for the whole group. That is what makes the Commissary and the Observatory
each independently reachable instead of the first id in list order winning
outright whenever it happens to be draftable.

Accepted rooms are dealt through the same per-rarity deck machinery an ordinary
draw uses, searching rarities 0–3 in a fixed order, so a hit is actually
*removed* from its deck: *"the floorplan gets added to the discard filter for
future draws."*

An entry targets its candidates either with an explicit `rooms` list or with a
`category` selector resolved against `Room.is_category` at roll time — the
Chronograph's Tomorrow Rooms row uses the selector so its twelve room ids
(including the Mail Room's three upgrade variants) are never hand-typed.

**The 5% / 13% / 3% constants are not independently checkable in this repo.**
`priority_draws.json` cites a "TFMurphy decompiled sheet v1.3 constants block",
and that sheet is not here: `tools/raw/` holds a 147-line *room* table with
nothing about draw procedure. The values are almost certainly right, but **do
not describe them as repo-datamined** — the datamine-outranks-wiki rule cannot
be exercised on them, because there is no datamine here to read.

An entry may also carry a `condition` tag drawn from the same vocabulary
`category_biases` entries use. A conditioned entry is **skipped entirely,
consuming no RNG**, while its condition is inactive; the active-condition set
is computed lazily so the unconditional path never pays for it.

The condition vocabulary gates a **whole entry** on or off. It has no negation
and no per-room membership primitive, which is exactly what the Secret
Passage's Greenhouse migration would need — see `open_tasks.md` §23 A.

### Forced draws

`forced_draws` is a different mechanic: it pushes one specific room into
**slot 2** (the wiki's Slot 3) ahead of the priority draws. Only the Garage's
is implemented:

- **90%**, or **92.5%** with the West Gate unlatched.
- Gated on **Veteran Mode or day ≥ 3**.
- Blocked when slots 0 and 1 are *both* Dead Ends *and* slot 1 was placed by a
  normal roll-based draw.
- **Once per day**: the roll retries at each eligible doorway until it succeeds,
  and a success permanently disables it for the day even when the resulting
  placement then fails because the Garage already occupies an earlier slot of
  the same hand.

Measured over 5000 episodes at every doorway where the Garage is legal, adding
it moved Garage placement from **17.61% → 53.59%** under `greedy_rank` and
**39.06% → 78.31%** under `random`. Its *placement* rule was already correct
(West Wing, ranks 4–8, entered north or west — five legal tiles); the
divergence was frequency, not geometry.

**Forced-draw blocking is positional, not literal.** A forced draw blocks later
entries in `forced_draw_precedence` only where its own conditions actually
hold, not merely by being in the pool. The literal reading would have erased
the Garage's measured gain the moment a Conservatory floorplan was found;
Conservatory (corners `{0, 4, 40, 44}`) and Garage (West Wing
`{15, 20, 25, 30, 35}`) are provably non-interacting, and the Morning Room's
documented wings-only exception suggests the game works this way.

### Guaranteed draws

A Guaranteed Draw runs *ahead of* the normal drafting algorithm and fixes
slots outright — it never rolls a rarity and never consults the round's
Free/Gem decision. Three exist:

- **Day 1's opening draw**: the very first round of the very first draft of day
  1 is Bedroom, Closet, Hallway, in that order. Ending day 1 without drafting
  simply skips it, which needs no code — the guarantee only fires from inside
  an actual draft.
- **The Tunnel chain**: opening the north door of a placed Tunnel guarantees a
  Tunnel in slot 0 of an otherwise-normal three-option hand. Slots 1 and 2 deal
  ordinarily and cannot produce a second Tunnel. The chain ends naturally when
  the Tunnel is illegal at the target (rank 9 blocked by `rank_lte_8`, or the
  cell occupied): slot 0 then falls back to an ordinary draw and the hand is
  three ordinary options with no Tunnel.
- **The Reading Nook's Library**: slot 2 is always the Library when drafting
  from the Reading Nook's own doorway — *"even if floorplans are redrawn; even
  if the Library is no longer in the draft pool ...; even when using Silver Key
  or Prism Key; and even if it has been removed entirely via Repellent."*

All three still pull their card from its own deck when one remains, so the
hand actually spends it, but the *option* is built unconditionally through the
forced-orientation fallback: an empty deck or a Repellent ban never breaks the
guarantee.

The Tunnel chain is worth its own note because getting it wrong looked like a
reward exploit. The sim once dealt exactly **one** forced Tunnel and skipped
the three-slot deal — measured over 60 seeds, drafting north from a Tunnel
dealt 1 option in 60/60 while drafting south dealt 3. Across 329 recorded
episodes there were 210 Tunnel placements in 45 episodes: **exactly 45 genuine
choices, one per episode, and 165 forced single-option hands (78.6%)**. No
episode ever held two real Tunnel choices, so a policy taking the only card it
is dealt was gaming nothing, and **no reward change was made on that
evidence**. The guaranteed Tunnel goes in slot 0 rather than a middle slot,
overriding the owner's own recollection: the wiki's `Drafting/Advanced` is
1-indexed (its "Slot 1 always makes a Free Draw" matches this engine's
free-only slot 0, and "a Library is drawn into Slot 3" matches the existing
index 2). The conflict was surfaced rather than resolved silently, per
[`doctrine.md`](doctrine.md), and ruled for the wiki.

### Category biases

`category_biases` entries fire *after* a normal draw has landed: roll the
entry's chance, and on a hit try to deal a replacement matching the target
category / layout / flag from the remaining undealt cards of the same
free/gem class. The original stays consumed from its deck; if no match is
available the original is kept.

A target category is a colour identity check in most cases, so it matches a
multi-category room (the Aquarium, the Maid's Chamber) on any colour it counts
as. An entry may name a `category_base` plus `category_extra_rooms` for a
target that is a category plus specific rooms outside it — the Electro Magnet
targets Mechanical Rooms plus the Rotunda, which is a blueprint room, and those
rooms live in the record rather than in engine code.

The **Banner of the King** emits one of five per-colour tags
(`king_blueprint` / `king_hallway` / `king_bedroom` / `king_shop` /
`king_blackprint`), mirroring the `scepter_<colour>` shape, because the Banner
picks one colour per day exactly as the Royal Scepter does — a bare `king` tag
would fire all five biases at once. The tags are correctly shaped and
deliberately inert: no source in this repo's data models how the Banner is
obtained or how its daily colour is picked.

The **Southern Cross's** 4-way bias excludes the Mechanarium, the Chamber of
Mirrors, and every upgrade variant (`exclude_rooms` plus
`exclude_upgrade_variants`), matching the wiki's own query, which filters
`Type HOLDS "Upgrade"` and names the two rooms; the Mechanarium page repeats it
independently.

**Both constellation biases have an in-game setter.** Activating the Southern
Cross or Draxus from an Observatory night sky sets `state.southern_cross_active`
/ `state.draxus_active` for the rest of the day
(`engine/constellations.py::apply_effect`, keyed off each record's own
`effect.condition`, which names the entry here). Measured over 300 seeds × 3
option slots at an interior cell: four-door rooms go from **3.3%** of dealt
options to **39.4%**, Dead Ends from **27.2%** to **46.4%**. Draxus starts from
a far higher floor because Dead Ends are common in the base pool and the
attempt-4 fallback is the Closet, itself a dead end.

All three Cloister frequency boosts are now reachable: the **Terrace** makes
green rooms free while it is on the estate (`free_green_drafts`), the
**Greenhouse** boost is a `category: green, chance: 0.4` bias conditioned on
`greenhouse_or_king`, and the **Southern Cross** boost — the one that matters
most to the Cloister's 5.87% per-day offer rate — arrives through its
constellation.

## Placement filters

A candidate room must be placeable behind the opened doorway
(`engine/placement.py`):

- **Door-back rule**: the room needs a door facing back through the opened
  doorway (`entry_dir` is the direction the player moved, so the room needs
  a door on the opposite side).
- **No door may face the outer wall.** This single rule keeps 4-way rooms
  off edges, restricts corner cells to L-shapes and Dead Ends, and fixes a
  T-shape's orientation against an edge.
- **Draft conditions** (`Room.draft_conditions`, AND semantics): wing/corner
  /rank restrictions (Garage, Boiler Room, Her Ladyship's Chamber, …),
  cannot-draft-from-Library, and item-gated rooms (Pool → Swimming-gated
  rooms, Secret Garden key, Room 8 key, breakfast) via
  `GameConfig.satisfied_conditions`.
- Duplicates: a room already on the grid can't be dealt again (Chamber of
  Mirrors lifts this). Two ids are exempt by name: a Tunnel dealt via the
  chain, and `aquarium__experiment` once `add_aquariums` has fired — all its
  copies share one id, so without the exemption the grid would cap at two.
- **Crown of the Blueprints**: any room id the Crown has filtered for the rest
  of today is excluded unconditionally, ahead of every other check.

All of these go through the single `room_draftable` gate, which is why the
priority draws, the forced draw, the category biases and the colour filter all
compose without any of them carrying its own copy of the rules.

## Orientation roll

A floorplan with several legal orientations is rolled with datamined,
south-door-biased weights that drift by day — e.g. a T needing a south door
rolls 70/15/15 early, 60/20/20 late (`engine/rotation.py`). The **Compass**
(`cfg.compass`, or the held Compass item — see `special_items.compass_active`)
flips the bias toward north doors. Free rotation to any legal orientation is
granted by the **Ornate Compass** (`cfg.ornate_compass` or the held item, every
draft), the **Rotunda** (while placed), and the **Dovecote** (while drawn).

Rotation is a hand-level effect: it advances every option together and takes no
per-option argument.

The **Mechanarium's** door mask is the one exception — it is *derived* at draft
time from the number of placed Mechanical rooms rather than rolled, and
consumes no orientation RNG draw. The back door is always the one it was
drafted from; the remaining doors are tried forward, left, right, capped at the
four cardinal directions. A candidate direction whose occupied neighbour has no
facing door is **skipped without consuming its slot**. The count and
orientation are set at draft time and never grow: later Mechanical drafts add
no doors to an already-placed Mechanarium. Mechanical rooms beyond four open
diagonal *compartments* instead, modelled as containers at the Mechanarium's
cell.

Known gap: orientation weights are datamined for the South, West and East
connecting-door cases; the North case uses the published near-uniform
40/30/30, and the Compass column for North (and the 50/50 North/South 2-way
case) is unpublished, so those fall back to the base roll.

## Colour-selective drafting

A Secret Passage doorway (and the Prism Key) lets the player pick one of five
colours — Bedroom, Hallway, Green Room, Shop, Red Room — and restricts the
whole resulting hand to it. There is no way to select Blueprints or Blackprints
specifically, so `COLOUR_CATEGORIES` has exactly those five members.

The restriction is a **filter**, not a bias, and the wiki warns explicitly that
the two must not be confused. It is threaded through the same `room_draftable`
gate as everything else, so it composes for free with priority draws, forced
draws and category bias — none of those needs its own colour guard. A Secret
Passage variant can never itself be drawn during a colour-selective draft.

The pool for a thin colour is often empty, so the deal has a fallback ladder:

1. The ordinary rank/rarity attempts 1–3.
2. **Reserve copies** — the wiki's middle tier. **Not modelled.**
3. The published **default triple** for the colour
   (`priority_draws.json::colour_defaults`). Its swap rule replaces one default
   with another while a listed upgrade is applied: the Cloister leaves green
   when upgraded and the Solarium takes its place.

For a colour-locked slot the default triple **is** the final fallback. The
universal forced-Closet attempt 4 must never run, because the Closet's category
is `blueprint` — never one of the five selectable colours — and the wiki states
the colour invariant with no exhaustion exception. A default is still filtered
through `room_draftable` and can lose to the one-copy-per-grid rule like any
other candidate; if all three are unavailable the slot is left unfilled and the
caller falls back to NAVIGATE rather than parking in DRAFTING with nothing to
choose. That branch is reachable only because reserve copies are unmodelled: it
is a modelling artifact, not a game rule.

The **Silver Key's cross/T bias is skipped entirely** during a colour-selective
draft rather than merely narrowed by the filter — *"If the Silver Key is used in
the Secret Passage, the Secret Passage's effect will take priority and the
Silver Key's effect is ignored."*

## Redraws

The whole 3-option hand is redrawn together (per-slot semantics unverified,
so the sim redraws all three). Redrawing bumps `round_num` but not
`drafts_today`, which is what lets the Free/Gem "third round or later" rule
fire at all.

- **Study**: 1 gem per redraw, max 8 per draft, while the Study is placed.
- **Classroom**: free redraws equal to the drafting-room count.
- **Ivory Dice**: spend a die for a redraw.
- **Paper Crown**: +1 free redraw when the initial deal is all non-red.

**There is no per-hand redraw budget.** The wiki is explicit: *"There is no
limit to how many times floorplans can be redrawn in one draft."* The Study's
own 8-per-draft gem cap is a separate, real mechanic and stays.

**All redraw sources apply to the outer-room draft too.** An outer hand is
reshuffled from its own fixed pool of 8 on its own RNG label rather than going
through the grid pipeline — running `redeal()` on an outer hand would read
`state.grid[-1]`, silently fabricating a "from room" and dealing grid rooms
into an outer hand.

Each redraw re-runs the whole `_fill_options` pass, which is what gives several
mechanics their "re-select on redraw" behaviour for free: the Dowsing Rod picks
a fresh slot, the Archives re-rolls which slot is archived, the Darkroom
re-reads its light switch, and the Crown of the Blueprints' once-per-hand
filter becomes available again.

## Concealment: the Archives and the Darkroom

**Neither the Archives nor the Darkroom reduces the option count — both
conceal.** All three options remain fully draftable sight unseen, and the game
deliberately preserves side channels: gem cost, Coat Check label, power lines,
rotation (which leaks shape), the Furnace's red haze, and rarity when drafting
through a security door.

**Archived and hidden are different properties**, and conflating them was a
real modelling error. *Archived* is a property of the floorplan, produced by a
day-long house-wide capability; *hidden* is a property of how the option was
dealt. The archived option is always also hidden; never the reverse. They are
two independent passes, composed rather than computed as one index, and they
carry separate effect tags (`archive_floorplan` and `conceal_all_floorplans`).

**Archives** (`archive_floorplan`) is **house-wide and non-stacking**, not a
from-room effect. Once one is on the estate, every draft through **any**
doorway archives one of its three dealt options — a uniformly random slot from
its own named RNG stream (`archives_slot`), re-rolled on every redraw. The
uniform slot matters: there is no longer a guaranteed fully-informed option.

Three independent lines of evidence fix the scope as house-wide. The wiki says
*"will 'archive' one of the three floorplans drawn whenever a room is drafted
after Archives"* with no from-room qualifier anywhere on the page. A Darkroom
draft sets `from_room = Darkroom`, so under a from-room model no option could
ever be archived — yet one of a Darkroom's concealed options can be. And the
Shelter interaction is worded *"drafting the Archives under the effect of the
Shelter ... Archived floorplans do not appear"*, which only makes sense for a
day-long capability.

**The Shelter's / Knight's Shield's negation is spent once, at the Archives'
own placement**, and suppresses archiving for the rest of the day. A charge per
draft would drain all three Shelter charges in three doorways. The trap this
avoids: every other negation caller uses a per-event pattern, and copying it
here silently drains the resource.

**Darkroom** (`conceal_all_floorplans`) is a genuine from-room effect —
drafting from its own doorway hides all three options face-down, live-read
against `state.darkroom_lights_on` on every deal and redraw. Its lights start
on but blow a fuse the first time the Darkroom is entered each day, unless the
switch was already off, or Shelter / Knight's Shield negates it. The Utility
Closet's "Darkroom" switch can restore power at any time afterward, disabling
the concealment for later doorways from the room — but flipping it off and on
again *before* the Darkroom is first entered does not stop the fuse blowing.

In the observation (`env/obs.py`), a hidden option keeps its gem cost, step
cost, affordability and `archived` flag; its identity, orientation, layout and
category are zeroed. **Rarity leaks through a security door** — *"If the door
being drafted from is a security door, the rarity of the floorplan is
shown"* — and is `-1` otherwise. `forced` is suppressed on a hidden option for
the same reason: forced options come from a small named pool (Garage, Tunnel
chain, Reading Nook Library, priority draws), so exposing the flag would narrow
a concealed card's identity far more than any in-game tell does.

## Other draft-time modifiers

- **Conservatory**: on draft, re-rolls the rarity of 3 random undealt deck
  cards, uniformly over the four rarities (the real re-roll distribution is
  unpublished; uniform is inferred). Each move goes through
  `set_dynamic_rarity`, so a later same-day Gear Wrench pick on the same room
  finds the card where it actually is.
- **Hovel**: gem costs can be paid with steps at 3 steps : 1 gem.
- **Terrace**: green rooms cost no gems.
- **Dowsing Rod**: settles on one dealt option every deal and every redraw,
  preferring a slot whose room is not on its own 26-room avoid-list; if all
  three are avoid-listed, any of them is fair game. Uniform among the eligible
  candidates is a modelled assumption — the distribution is unpublished.
- **Repellent**: bans a floorplan from the pool for 7 days. A ban targets the
  floorplan, so it covers that room's upgrade variants too.
- **Upgrade Disks**: an applied variant *replaces* its base room in the pool.
  Cross-bucket upgrades (the 8 Cloister variants) move cards between decks;
  the deck retires the base floorplan completely, including cards dealt earlier
  this cycle, because attempt 3's reshuffle would otherwise make the
  un-upgraded room dealable again.

## Veteran Mode

**Veteran Mode is the default, including on a fresh save.** The sim is written
for experienced players, who trigger it on day 1 by drafting the first three
rooms out of the Entrance Hall quickly. **The trigger is not modelled, only its
outcome** — the same assumed-solved treatment [`doctrine.md`](doctrine.md)
applies to room puzzles. It is not a permanent unlock: it is triggered per save
by how the player opens day 1, so it sits with `royal_scepter_found` among the
deliberate exceptions rather than with the earned unlocks.

It gates three systems, and the effect differs sharply by preset because
`all_unlocks_config` runs at day 20, where the day counter already satisfied
two of them:

| | all_unlocks (day 20) | fresh_save (day 1) |
|---|---|---|
| gem deck-size gates | already on via day ≥ 16 | **now active** |
| Garage forced draw | already on via day ≥ 3 | **now active before day 3** |
| Free/Gem early carve-out | first 2 drafts free | first 2 drafts free |
| Upgrade Disk slots | veteran tables | veteran tables |

The consequence worth acting on: **a fresh save is no longer the loosest
possible draw environment**, because the gem gates bind from day 1. The
Upgrade Disk half is owned by
[`upgrade-disks-design.md`](upgrade-disks-design.md).

## Verifying the math

Two chi-square suites guard two different axes, and they do not cover for each
other:

- `tests/test_draft_stats.py` (30k draws per table cell) asserts the engine
  reproduces the datamined **rarity** distributions. Useful anchors: late-game
  slot 0 at rank 1 is 91.8% commonplace; with a Solarium, slots 1–2 at rank 9
  deal 10/20/50/20.
- `tests/test_free_gem_draws.py` guards the **free/gem** axis, which had no
  coverage at all until the step existed — which is precisely why a whole
  decision step could go unmodelled without anything going red.

Treat failures in either as evidence the draft math regressed, not as flaky
tests. And when a suite is described as the sharpest guard in the repo, **ask
which axis it guards before trusting it with a different one**; that mistake
was made three times in one session about `test_draft_stats.py` alone.

## Deliberate divergences

- **The redraw cap that was almost added.** A per-hand redraw budget was ruled
  in and then reversed before shipping. The premise was that
  `drawing_room_drawn` × `set_dice` is an unbounded zero-step loop; measured in
  this engine it is a decaying random walk — mean **2.34** redraws, median 2,
  p90 3, p99 4, max 4 over 53 sampled hands, zero runs over 8. The closed form
  agrees: each redraw spends a die and the Drawing Room reappears with
  probability *p*, so `E[length | 2 dice] = (2−p)/(1−p)²` = 2.35 at the measured
  *p* = 0.10, diverging only as *p* → 1. Both of the wiki's routes to *p* → 1
  are unavailable here. **Dropping the cap is what makes the sim match the
  wiki**; adding it would have been a permanent invented deviation justified by
  a premise that was never true of this engine.
- **The Silver Key's bias is cleared after the initial deal**, so it does not
  apply to redrawn hands. The wiki's description of the dice-farming exploit
  implies the real game's bias persists — which is what would make a Drawing
  Room appear on every draw. Held for owner verification in play; the clearing
  behaviour stands until then and must not be changed speculatively. If it
  should persist, the redraw loop becomes genuinely unbounded and the cap
  ruling above re-opens.
- **The Tunnel chain re-guarantees on redraws, and should not.** The wiki line
  ends *"This does not repeat on redraws."* The code keys only off
  `from_room`/`direction`, so a redealt chain hand re-guarantees the Tunnel.
  Sourced, deliberately not implemented: distinguishing the initial deal needs
  per-hand state.
- **The Aquarium gets two separate condition-gated priority-draw rows** where
  the wiki says the effect "adds Aquarium to the 3/13% passive filters". Our
  `_priority_draw` resolves a row's `rooms` list by fixed order, first
  draftable wins, while the real game treats a priority draw as a filter and
  draws by deck order among the survivors. Joining the rows would starve the
  Aquarium behind the Commissary and Observatory once it has 3, 6 or 9 copies
  in the deck against the Commissary's single card. Separate rows reproduce the
  published **15.61%** exactly, at the cost of two extra RNG substreams. If the
  resolution is ever fixed to draw by deck order among survivors, joining the
  rows becomes both literal and correct.
- **Reserve copies are not modelled** for colour-selective drafting. Filter-only
  was rejected because the wiki says thin pools are *frequent* for Green Rooms
  and Shops; full fidelity was rejected because it requires relaxing the
  out-drafting invariant in `placement.py`/`rotation.py`, which is load-bearing.
  Default triples are the middle option.
- **The Garage's passive priority draw and its forced draw are different
  gates.** The passive 3% row is Day-5-or-Veteran; the forced draw is
  Day-3-or-Veteran. Only the forced draw is implemented. Do not conflate the
  two thresholds.
- **Only the Garage slice of `forced_draw_precedence` is built.** The
  Conservatory, Morning Room and Utility Closet entries stay as data behind
  their own prerequisites; the Utility Closet's own forced draw is gated on the
  Garage having been drafted first.
- **Two unsourced readings in the Garage gate**, recorded rather than buried:
  *"or Slot 2 was not drawn by a normal draw"* is read as slot 1's
  `DraftOption.forced` being False, so a category-bias substitution still counts
  as normal; and the forced draw is checked **before** the priority draws
  because no source specifies precedence between the two systems.
- **The Conservatory's re-roll never touches the permanent rarity record.** The
  wiki says the Conservatory writes the same permanent slot the Gear Wrench
  does and can reset a wrench-set rarity; here it is a random day-scoped re-roll
  of three undealt cards. Known and deliberately unfixed.
- **Per-option orientation choice is not a mechanic.** An option arrives with a
  rolled orientation; rotation is a separate hand-level effect (Ornate Compass /
  Rotunda / Dovecote). The three action ids that once claimed otherwise were
  never selectable and were removed — see
  [`rl-environment.md`](rl-environment.md) on dead action ids.
- **The Secret Passage's stateful wing rule is unmodelled.** Its rank
  restrictions (`rank_gte_2` / `rank_lte_8`) are modelled; the rule blocking it
  from wing drafts leading north into rank 8 or south into rank 2 until another
  vertical wing draft occurs is recorded as a named gap on both records.
- **The wiki's ~25-room Dynamic Rarity table is not modelled.** The card-move
  primitive that would carry it exists (`set_dynamic_rarity`); the table does
  not.
