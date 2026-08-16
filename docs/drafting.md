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
  reshuffle. Used by the Gear Wrench, the Conservatory's drawing board, the
  Battery Pack, the `add_aquariums` experiment, and the Mail Room's
  waiting-package Dynamic Rarity ([`rooms.md`](rooms.md)) — the last of which
  is the only one decided at day start rather than mid-day, and so the only
  one `Game.reset` fires directly.

Every path that touches a deck bucket — `inject_rooms`,
`inject_rooms_undealt`, `apply_upgrade` — looks the room up through
`state.dynamic_rarity` before falling back to its static rarity, so an
overridden room is never split across two buckets.

**Two mechanics make an override permanent, and they share one slot.** The Gear
Wrench (on drafting a Mechanical Room) and the Conservatory's drawing board
(three offered floorplans, [`rooms.md`](rooms.md)) both write through
`Game._write_permanent_rarity`, which lands the choice in
`cfg.permanent_rarity`; `build_decks` reads it for the day-start bucket, and
`Game.reset` seeds `state.dynamic_rarity` from the same dict so both agree from
the first deal onward. One shared slot is what lets a remodel reset a
wrench-set rarity, as the wiki says it does. The Battery Pack's override is
day-scoped and never lands there.

**Deck-size gates** suppress rarities that have run low
(`weights.json::deck_size_gates`): free decks need ≥ 3 cards; gem decks need
5/5/4/4 (by rarity) once veteran mode, day ≥ 16, or Room 46 has been reached
(`GameConfig.gem_gate_active`), and merely non-empty before that. Slot 0 checks
the free deck alone; slots 1–2 pass if *either* class satisfies its gate.

## Free/Gem Draws

Whether a slot deals from the free decks or the gem decks is a published
decision step, rolled **once per round** in `draft.py::_resolve_free_gem` and
threaded through every deal in that round. On an ordinary hand a Free Draw
searches only the free deck of the rolled rarity, a Gem Draw only the gem deck:
*"Free Draws only use the four decks made out of free rooms, while Gem Draws
only use the four decks made out of gem rooms."* The two are never combined for
a single ordinary draw.

**A colour-selective draft ignores this split entirely** and reads both classes
— an owner ruling that overrides the sentence just quoted. See
[Colour-selective drafting](#colour-selective-drafting), which records the
conflict and the evidence. `draft.py::_deal_classes` is the single place the
choice is made, so every deal in the module (pool draw, priority draw,
category-bias re-deal) obeys the same rule.

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

## The free first option

A Free Draw is about which *deck* a slot reads, not about what the option
costs. Cost is a separate rule, and it is an owner ruling from play:

> "Always allow a free option. This is particularly important with the Secret
> Passage. The Secret Passage will grant the first option with zero cost, even
> if it would ordinarily cost gems. It simply zeroes out the cost. The normal
> drafting priorities apply. However, if left with no other option, the option
> is free."

`draft.py::waive_first_option` implements both halves as one rule: once the
hand is assembled, the **first option it presents** is granted free —
`gem_cost` set to 0 and `DraftOption.cost_waived` set, which
`Game._effective_cost` honours at pay time. It runs on every hand: the initial
deal, every redraw, and the outer-room draft.

This is a **price** rule, not a draw rule. Which rooms are dealt is settled
before it runs; it consumes no RNG and moves no draw statistic.

`pending.options` is built in slot order, so the first member is normally slot
0 — whose cost the deal already zeroes, making the rule a no-op on every
ordinary hand. It bites only when slot 0 dealt nothing, which today only a
colour-selective hand can do (its slots skip the universal forced-Closet
attempt; see [Colour-selective drafting](#colour-selective-drafting)). There
the waiver lands on slot 1 or 2 instead, which is exactly the Secret Passage
case the ruling names.

The consequence worth stating on its own: **DRAFTING always offers at least
one affordable option.** A hand that dealt nothing never enters DRAFTING at
all (`Game.open_door`/`choose_colour` fall back to NAVIGATE), and any hand that
did dealt a free first option. There is no decline, so without this the phase
could present zero legal actions — `env/actions.py::action_mask` enables CHOOSE
only for affordable slots, and every other DRAFTING row (redraw, rotate, berry
pick, crown block, rewind) needs resources the player may not hold.

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
| Patio group (Patio, Veranda, Greenhouse, Morning Room) | 5% | 50% while a Greenhouse is placed; also carries Secret Passage until a Greenhouse is placed |
| Commissary / Observatory | 13% | |
| Garage / Classroom | 3% | also carries Secret Passage once a Greenhouse is placed |
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

The condition vocabulary above gates a **whole entry** on or off. A separate,
file-level `membership_moves` list moves one *room* between two entries
instead: each record names a room, a `from` label, a `to` label and a
`condition` — a `GameState` boolean read directly by name (`getattr`), not one
of the `_active_conditions` tags above. `draft.py::_apply_membership_moves`
applies it wherever an entry's candidate room list is built, removing the room
from the `from` entry's list and adding it to the `to` entry's while the
condition holds; it is a no-op (same list object, no RNG-order change) while
the condition is inactive.

The only record today moves the **Secret Passage** between `patio_rooms` and
`garage_classroom`, keyed on `state.greenhouse_placed` — the same signal
`chance_with_greenhouse` above already reads — so the room sits in exactly one
of the two entries' lists in every state. This collapses a wording gap in the
wiki's two clauses (`patio_rooms`: "included if Greenhouse has not been
drafted"; `garage_classroom`: "included after Greenhouse effect is active"):
since the Greenhouse filter is "the same filter as king", a King's-green
activation could, read literally, satisfy the second clause with no Greenhouse
drafted. This model does not distinguish that case — see the
`membership_moves` entry's own `meta.notes` in `priority_draws.json`.

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
free-*deck*-only slot 0 — a draw-class rule, distinct from the free-first-
option price rule above — and "a Library is drawn into Slot 3" matches the
existing index 2). The conflict was surfaced rather than resolved silently, per
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
- **The Morning Room is wings-only**, on top of its breakfast gate: the west
  or east outer column, never a corner, and never rotated. Its fixed door
  sides (north+east on the West Wing, west+south on the East) then bar a
  northward draft on the West Wing and a southward one on the East, leaving
  exactly **four** legal (wing, direction) door slots — which is what the
  wiki's "Morning Room is in four Prismatic Pools, one for each of the four
  doors it can appear in" counts. **This is a source conflict resolved for the
  wiki**: the datamine's Draft Conditions column carries only "Eat Bacon &
  Eggs in Kitchen or Breakfast Nook" for the Morning Room and no wing rule,
  even though it spells "West Wing or East Wing" out for the Terrace, Patio,
  Veranda, Greenhouse and Secret Garden, and even concatenates two conditions
  into that one cell for the Secret Garden. The wiki states the wing rule
  twice — on the room's own page and in the House page's list of rooms
  draftable only on a wing — and owner play agrees, so the sheet's cell is
  read as carrying the unlock text at the expense of the placement rule.
- Duplicates: a **floorplan** already on the grid can't be dealt again
  (Chamber of Mirrors lifts this). The unit is the floorplan family
  (`upgrades.root_base_id`), not the room id, so a base room and its upgrade
  variants are one entry: an Upgrade Disk *upgrades* a floorplan rather than
  adding one, and the wiki's own removal rule is "drafting any floorplan will
  remove it from the draft pool for the rest of the day". This is what stops a
  base Parlor placed before a mid-day `parlor__ix108` upgrade from being joined
  by the upgraded Parlor after an attempt-3 reshuffle — `decks.py::apply_
  upgrade` deliberately retires the base card *including copies dealt earlier
  this cycle*, which puts the variant card back in play, so the grid check is
  the only thing standing between one floorplan and two rooms. Every documented
  way to get two of one floorplan is an explicit pool addition instead (Chamber
  of Mirrors, the `add_aquariums` experiment, the Pool Hall, the duplicating
  Hallway upgrade, the Schoolhouse, the Blessing of the Gardener). Two ids are
  exempt by name: a Tunnel dealt via the chain, and `aquarium__experiment` once
  `add_aquariums` has fired — all its copies share one id, so without the
  exemption the grid would cap at two.
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

### The Free/Gem split does not apply

**OWNER RULING: a colour-selective draft ignores the Free/Gem split. Attempts
1–3 draw from both classes.** `draft.py::_deal_classes` returns both deck
classes — free searched first — whenever `DraftContext.colour` is set, and one
otherwise.

**This contradicts a line the engine quotes verbatim elsewhere**, and the
contradiction is recorded rather than smoothed over: *"Free Draws only use the
four decks made out of free rooms, while Gem Draws only use the four decks made
out of gem rooms"* (Drafting/Advanced). The owner's ruling governs. Two things
already in the repo point the same way:

- The Free/Gem split is a **Normal Draws** mechanic, and the same page says
  *"Normal drawing does not normally occur when … drafting [from a] Secret
  Passage"* — the exact citation `draft.py` already uses to keep the universal
  forced-Closet attempt out of a colour-locked slot. One quote, two
  consequences.
- The wiki describes a colour draft's other fallback as *"drawn separately from
  the draft pool"*, so the colour path was never meant to be the normal pool
  procedure with a filter bolted on.

**Why it is load-bearing rather than cosmetic.** Slot 0 is always a Free Draw,
and on the day's first drafts with under 2 gems all three slots are. Every shop
floorplan is gem-side except `the_armory`, which is condition-locked — measured
over 900 (seed, cell) pairs, the free decks held a legal shop room **0/900**
times while the gem decks held one **900/900**. So a colour-locked Free Draw
restricted to the free decks finds nothing *at any rarity*, and re-rolling the
rarity cannot help: the pool draw was a guaranteed miss, and the hand fell
straight to the default triple.

Measured at r5c4 (cell 24) entering north with the Commissary on the grid, the
hand dealt 2 slots in **194/200** seeds before and **9/200** after — and the
short hand was `(kitchen, locksmith)`, shop's default triple minus the placed
Commissary, in every one of the 194. Green with the Courtyard placed dealt a
**one-room** hand in 75/100 before and 0/100 after; counting every short hand,
green went 97/100 → 1/100 and shop 194/200 → 9/200.

**Two things it deliberately does not change.**

- **Gem cost.** Opening the gem decks changes which *deck* a slot reads, never
  what the option costs: a gem room dealt into a Free Draw slot 1 or 2 carries
  its ordinary resolved cost. Slot 0's cost is zero as it always was — and slot
  0 is also the hand's first presented option, which the [free first
  option](#the-free-first-option) waiver zeroes anyway.
- **Slot 0's rarity gate.** `decks.py::rarity_deck_ok` still checks the free
  deck alone for slot 0, colour or not. It gates which *rarity* may be rolled
  rather than which deck is dealt from, the ruling speaks to the draw, and
  widening it changed no measured outcome — while it would have made "slot 0
  unfilled, a later slot dealt" unreachable and with it the non-trivial half of
  the free-first-option ruling.

### The fallback ladder

The pool can still come up empty, so the deal has a fallback ladder:

1. The ordinary rank/rarity attempts 1–3, across both deck classes.
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
other candidate; if all three are unavailable the slot is left unfilled and, if
that empties the whole hand, the caller falls back to NAVIGATE rather than
parking in DRAFTING with nothing to choose.

Reaching that last branch now needs a pool with nothing legal on-colour at the
rolled rarity in **either** deck class *and* all three defaults blocked. It is
no longer the common case — no zero-option hand appeared in the 200-seed shop or
green samples above — but it stays wider than the real game's, because the
reserve-copy tier ignores the one-copy-per-grid rule and would have filled it.

### Reserve copies, researched but unbuilt

The tier that would close that remaining gap, from
blueprince.wiki.gg/wiki/Drafting_effects:

- **When.** *"If there are not enough floorplans of that color, or if there is
  no Special Floorplan for the first slot, then the draft may draw upon reserve
  copies of floorplans."* Exactly the thin-colour case.
- **Where.** After the pool draw, before the default triple -- the position this
  file already assumes.
- **What they relax.** *"These reserve copies may ignore the unique drafting
  restrictions of those floorplans, though they still obey basic shape placement
  rules, and may be duplicates of rooms in the estate."* So a reserve is **not**
  filtered by the one-copy-per-grid rule, which is precisely why it can fill a
  slot the defaults cannot.
- **Persistence.** *"These reserve floorplans are drawn separately from the draft
  pool and will not be drawn again if they are discarded by redrawing
  floorplans."*
- **Which rooms.** The page names the Morning Room, Solarium, Dormitory and
  Casino, and adds that *"some relatively early-game additions are available for
  reserve floorplans, even if they are not currently in the draft pool"*.

**Two things the source does not settle**, and both change the build: whether a
room's reserve is limited in number per day or per attempt, and whether that
four-room list is exhaustive or illustrative -- the phrasing that follows it
reads as open-ended. Note the Casino is a shop and the Solarium is green, the
two colours measured as worst affected (`open_tasks.md` 48).

An earlier ruling aimed at the same short hands — *"If there are no valid rooms
to draw, just draw another room at the appropriate rarity"* — turned out to be
a **literal no-op** here, and knowing why is what produced the ruling above:
re-rolling the rarity searches the same single deck class, and for a shop-colour
Free Draw that class holds no legal room at any rarity. Nothing to re-roll into.
The ruling that replaced it is [The Free/Gem split does not
apply](#the-freegem-split-does-not-apply); the default triple still stands as
the last resort behind the pool.

Slots fail **independently**, so an unfilled slot does not imply an empty hand:
one slot's rarity roll can miss the rarity holding the colour's only legal room
while another slot's hits it. The [free first option](#the-free-first-option) is
what keeps the surviving one-option hand takeable.

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
- **Drawing Room**: +1 free redraw on the hand dealt from its own doorway —
  per door, since `ON_DRAFT_FROM` fires once per fresh doorway and not on a
  redraw of the same one; not a once-per-day flag, since a second Drawing
  Room doorway drafted later the same day grants another.
- **Ivory Dice**: spend a die for a redraw.
- **Paper Crown**: +1 free redraw when the initial deal is all non-red.
- **The Ink Well** (constellation, day-scoped once activated): spend 1
  permanent star, with no per-draft cap. It has its own action id rather than
  riding the shared REDRAW action, because every other redraw source spends a
  hand- or day-scoped resource with a natural bound while this one spends a
  save-scoped bank behind an id the agent presses reflexively.

**There is no per-hand redraw budget.** The wiki is explicit: *"There is no
limit to how many times floorplans can be redrawn in one draft."* The Study's
own 8-per-draft gem cap is a separate, real mechanic and stays.

**All redraw sources, including the Ink Well's star redraw, apply to the
outer-room draft too.** An outer hand is reshuffled from its own fixed pool of
8 on its own RNG label rather than going through the grid pipeline — running
`redeal()` on an outer hand would read `state.grid[-1]`, silently fabricating
a "from room" and dealing grid rooms into an outer hand.

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

- **Conservatory**: drafting it stocks a drawing board with three floorplans
  drawn uniformly at random with replacement; clicking a row sets that room's
  rarity permanently, through the same slot the Gear Wrench writes. Owned by
  [`rooms.md`](rooms.md).
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
  the wiki says the effect "adds Aquarium to the 3/13% passive filters" — each
  floorplan in a row gets its own independent acceptance roll (see "Priority
  draws" above), so this is modelled as independent 13% and 3% rolls rather
  than one combined entry. Separate rows reproduce the published **15.61%**
  exactly, at the cost of two extra RNG substreams.
- **Reserve copies are not modelled** for colour-selective drafting. Full
  fidelity requires relaxing the out-drafting invariant in
  `placement.py`/`rotation.py`, which is load-bearing. What carries the thin
  colours instead is the pool draw reading both deck classes (see
  [Colour-selective drafting](#colour-selective-drafting)), with the default
  triples behind it; the residue the reserves would still cover is a slot with
  nothing legal on-colour in either class *and* every default already placed.
- **The Garage's passive priority draw and its forced draw are different
  gates.** The passive 3% row is Day-5-or-Veteran; the forced draw is
  Day-3-or-Veteran. The passive draw itself is modelled (the
  `garage_classroom` `priority_draws` entry); what is not modelled is its own
  Day-5-or-Veteran gate, so it rolls unconditionally from Day 1. Do not
  conflate the two thresholds.
- **Only the Garage slice of `forced_draw_precedence` is built.** The
  Conservatory, Morning Room and Utility Closet entries stay as data behind
  their own prerequisites; the Utility Closet's own forced draw is gated on the
  Garage having been drafted first.
- **Two unsourced readings in the Garage gate**, recorded rather than buried:
  *"or Slot 2 was not drawn by a normal draw"* is read as slot 1's
  `DraftOption.forced` being False, so a category-bias substitution still counts
  as normal; and the forced draw is checked **before** the priority draws
  because no source specifies precedence between the two systems.
- **How often the Conservatory's drawing board answers is unsourced.** One
  click per offered floorplan, re-stocked on each Conservatory draft, is an
  assumption carried as `conservatory.CLICKS_PER_FLOORPLAN` —
  [`rooms.md`](rooms.md) states the reasoning and what the wiki does say.
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
  primitive that would carry it exists (`set_dynamic_rarity`), and three of the
  table's rows are built as their own room/item behaviour — the Workshop's
  Battery Pack row, the Aquarium's experiment row, and the Mail Room's
  waiting-package row ([`rooms.md`](rooms.md)) — but the table itself, and its
  day-number and Veteran-mode rows in particular, is not.
