# Open tasks

Work the project owner has identified and that is NOT in `docs/plan.md`'s
delivered set -- each needs its own design pass. Two sources so far: a review of
the special-items PR stack, and a recorded session of real play through the
Training Observatory. That first session's twelve findings have shipped,
leaving the remainders in tasks 37-41; a second session produced tasks
43-48.

**Play findings outrank the wiki**, per [`doctrine.md`](doctrine.md) -- but where
one contradicts a published rule, surface the conflict rather than silently
picking a side.

The file reads in three parts: **open tasks** (numbered sections), then the
**open owner questions** in task 23, then the **decisions log**, which is always
the last section. Lessons about *how to work* are not here; they are in
[`process.md`](process.md).

## The decisions log is a waiting room, not an archive

**A ruling belongs in the design document that owns the mechanism, or in a
comment beside the code it governs — never here once the work has landed.**
Architectural decisions spanning many parts of the codebase go to a design doc;
a decision that explains why one function does something surprising goes in that
function, not in a doc and not here. A ruling whose work has shipped and whose
rule is already stated elsewhere is **deleted**; git keeps it.

What is left in the log is therefore only rulings for work that is **not yet
built**, where there is no code to comment and stating the rule in a design doc
would describe behaviour the engine does not have. Each one leaves the log the
day its work lands.

A completed task is deleted too, rather than marked DONE — but read it for live
remainders first. Sections have twice hidden real content under a DONE heading.

## How to cite this file

**An entry here records what was true when it was written; the topic docs
record what is true now.** Readers have repeatedly taken the first for the
second, and four false claims propagated out of this file in a single day
before a fifth was caught.

So a cross-reference in `src/`, `tests/`, `tools/`, `data/` or another doc must
point at **the doc that owns the rule**, never at the log. `open_tasks.md` may
be cited for exactly two things:

- a **numbered open task**, cited by its number;
- an **open owner question**, cited by its letter within task 23.

Anything else — a mechanic, a magnitude, a ruling, a doctrine, a deliberate
divergence — cites the topic doc that owns it. If nothing owns it yet, that is
the signal to create or extend a topic doc, not to cite the log. In particular
**do not write "owner ruling, see the decisions log"**: state the rule in the
topic doc and cite that, because the reason a rule holds is not the same fact
as who said it.

Current owners:
[`scoping-and-carryover.md`](scoping-and-carryover.md) (persistence scope and
the carry channels), [`doctrine.md`](doctrine.md) (sources of truth,
assumed-solved, trophies, the acceptance bar),
[`architecture.md`](architecture.md) (data-vs-code ownership, the registries,
the id allowlists), [`rl-environment.md`](rl-environment.md) (observation and
action spaces, the width register, replay and measurement discipline),
[`luck.md`](luck.md),
[`locking.md`](locking.md), [`rewards.md`](rewards.md) (reward shaping),
[`foundation-design.md`](foundation-design.md), [`areas.md`](areas.md),
[`rooms.md`](rooms.md) (per-room mechanics, the spread effects, the Mail
Room cycle),
[`drafting.md`](drafting.md) (the whole draft pipeline, concealment, redraws),
[`special-items-schema.md`](special-items-schema.md) (the
`special_items.json` data contract and its status flags),
[`special-items-behaviour.md`](special-items-behaviour.md) (per-item and
per-system item rules, commerce, containers, ignition),
[`experiments-design.md`](experiments-design.md),
[`upgrade-disks-design.md`](upgrade-disks-design.md),
[`greedy-strategy.md`](greedy-strategy.md), [`process.md`](process.md).

## 24. Reward calibration

All shaping constants (`special_item_values`, `PATHS_ONE_PENALTY` /
`PATHS_ZERO_PENALTY`, scepter bias) are deliberate knobs, set without real
multi-day run data behind them. Calibrating them needs training statistics
from actual attempts, which do not exist yet.

## 37. The Laboratory unlock is day-scoped, and POWER is unmodelled

> "You need to unlock it by powering and visiting the Laboratory first."

The Grotto edge carries the owner's two conjuncts as two gates, and neither is
finished. `lab_visited` is real and live, but it is checked fresh against
`GateContext.rooms_entered` every day, so reaching the Grotto needs the
Laboratory drafted and entered *that day* -- tighter than the owner's wording,
which reads as a **one-time** unlock. Latching a first-ever visit across days
needs a `GameState`/`GameConfig` field plus a room-entry hook, both outside
`engine/areas.py`, which only evaluates the `GateContext` it is handed.

`lab_steam_and_power`, the POWER conjunct, is still `stub: true` and
`kind: "unmodelled"`, passing unconditionally: **nothing in the engine
represents whether the house is powered.** Building that is the same
off-`engine/areas.py` plumbing, so both halves ride `PR-power-system`
together. [`areas.md`](areas.md) owns the gate's current shape and records
this as its known gap.

## 38. Should a wing exclude its corners? Owner ruling needed

`west_or_east_wing` is carried by six rooms, and only three of them also carry
`no_corner`: the Morning Room, the Greenhouse, and the Secret Garden, whose
`rank_gte_3`/`rank_lte_8` bounds exclude ranks 1 and 9 anyway. **The Terrace,
the Patio and the Veranda can therefore be drawn onto a corner tile today**,
while the wiki says a wing never includes the corners and names the Patio
specifically -- *"rooms like the Patio can never be drawn on Rank 1"*.

The clean fix is to make `west_or_east_wing` corner-excluding in
`placement.py::satisfies_draft_conditions` rather than tagging three rooms
individually, which narrows three rooms' legal tiles at once and changes the
draft distribution. **That is an owner ruling, not an implementation
detail** -- it turns a data question into a semantics change on a shared tag,
and nothing should move until the ruling exists.

## 39. The Shelter's three charges are not strictly draft-ordered

"The Shelter protects against the next three red rooms that I draft" is exact
on its forward-looking half: `effects/rooms/shelter.py` snapshots
`game.placed_ids` at its own `ON_PLACE`, so an already-drafted red room keeps
its penalty. Among rooms drafted **after** the Shelter, though, the three
charges are still spent in penalty-resolution order rather than draft order.

The two only diverge when more than three red rooms are drafted after the
Shelter before the earliest of them is entered, and today only the Maid's
Chamber has a placement-time penalty, so the window is narrow. Closing it
needs per-draft notification plumbing: the Shelter is an outer-pool room and
never receives `ON_DRAFT_ROOM`, so it cannot currently count drafts as they
happen. [`rooms.md`](rooms.md) owns the shipped scoping rule.

## 40. Scripted policies never take the outer draft

`cli/policies.py::_navigate_frontier` never calls `Game.open_outer_draft`,
though `Game._action_in_budget` has always counted the outer draft as a reason
the day is not over. The two disagreeing is the pre-existing `decision_limit`
rate -- roughly 40% of `frontier_greedy` episodes.

**A naive fallback makes it worse.** `open_outer_draft` travels off-grid, and
`_navigate_frontier` has no off-grid handling at all: a measured trial dropped
mean rooms placed from 24.1 to 18.1. This needs real off-grid navigation in
the policy, not another branch at the bottom of the frontier loop.

## 41. Room 46 has no on-grid CLI travel verb

`Game._action_in_budget` counts area travel toward the off-grid `room_46` node
as a purposeful action while the player is on the grid, but `cli/play.py`
only prints its "Travel to:" menu inside the `game.off_grid` branch. On-grid,
there is no verb that takes it.

No silent spin: the NAVIGATE branch always falls through to `input()` and
`'q'` always works, and no reproduction was constructible -- travel to Room 46
being the *only* purposeful action left needs the grid simultaneously
exhausted. It is still a menu the engine believes exists and the CLI does not
offer.

## 43. The Blessing of the High Roller granted no dice for a Trading Post draft

> "I did not receive dice when drafting the Trading Post with the Blessing of the
> High Roller."

`data/shrine.json`'s `high_roller` record is one of the six live blessings.
Establish by execution whether the grant fires on **draft** or on **entry**, and
whether the Trading Post is eligible at all — it is an outer-pool room, and
outer-pool rooms do not receive `ON_DRAFT_ROOM` broadcasts, which is the same
structural gap that made the Shelter miscount (see task 39).

## 44. There is no "Call it a day" action

> "I need a 'Call it a day' action to end my day. It should ask for confirmation
> before executing."

The engine ends a day when nothing purposeful remains; a player who simply wants
to stop has no way to say so. **Confirmation is part of the request**, not a
nicety — the action is irreversible and cannot be distinguished from a misclick.

Note the interaction with the purposefulness rule: this action must end the day
*even when* the engine considers work still available, so it cannot be
implemented as "terminate if `_check_termination` agrees".

## 45. The action log should read newest-first

> "The action log would actually work better in reverse, showing the most recent
> action on the top and shifting the rest down, so I can see the most recent
> action and returns without scrolling."

The payout badges added for task 28 are exactly what the owner wants to see
without scrolling, so this is the other half of that change rather than a
cosmetic preference.

## 46. The Tomb should pay for itself as a dead end

> "The Tomb collects +5 gold for every dead end, including itself. Therefore, it
> should have +5 gold upon first entry."

The claim is specific and checkable: the Tomb counts **itself** among the dead
ends it pays for, so entering it with no other dead end on the grid should still
pay 5. Establish what the engine does today before changing it, and note that
PR #334 redefined "Dead End" as *printed dead-end shape AND a one-door placed
mask* — so whether the Tomb qualifies under its own placed mask is part of the
question.

## 47. Shops should show stock the player cannot yet afford

> "The Commissary (and other shops) should show me what is available, even if I
> can't afford it. I may eventually have the money and want to return."

A shop menu filtered to affordable rows hides the reason to come back. Note this
is a **display** change, not an affordability change: the unaffordable rows must
be shown and remain unbuyable. `shops.py::stock_for` already computes an
`affordable` flag per row, so the data needed is present.

## 48. A Secret Passage on the east wing offered two yellow rooms, not three

> "I was only able to draft *two* yellow rooms instead of *three* from a Secret
> Passage on the east wing (r4c4). I had already drafted the Commissary. Inspect
> what yellow rooms are draftable in r5c4."

**The count is the finding.** A colour-selective draft rolls each slot
independently, and a slot whose colour deck has nothing legal at that cell comes
up unfilled — the same mechanism behind the Secret Passage's free-first-option
bug, where slots 0 and 1 produced nothing and only slot 2 dealt.

So the question is whether the third slot was legitimately unfillable at r5c4 —
too few yellow rooms surviving geometry, the deck-size gate, and the Commissary
already being placed — or whether a legal candidate was wrongly rejected. The
owner names the cell and the prior draft, so this is directly reproducible.
Enumerate the yellow pool against r5c4's legal orientations before concluding
anything.

## 23. OPEN OWNER QUESTIONS

The single home for questions that need an owner ruling before the work they
block can start. **Nothing is open here right now**; a new question is added as
a lettered item, and cited from elsewhere by that letter.

Answered questions are **deleted from this section, not annotated** -- a
question left in a questions list reads as open whatever note sits under it.
When one turns out to be answered, delete it here and record the answer in the
doc that owns the rule. **Do not restate the count in prose elsewhere**: this
header has already been wrong once, because a question was removed and the
count above it was not.

## Decisions log

Every entry here is held for one reason only: **it specifies work that is not
built yet.** Each one leaves the log the day its work lands.

- **The Conservatory's remodel** — the drawing board that re-rolls three rooms'
  rarities. Its *reachability* has shipped, so only the remodel's rules wait
  here.
- **The Spiral of Stars** — the one constellation of thirteen still inert.
- **Re-filing seven Found Floorplans** out of the `studio_addition` pool.
- **The Mail Room's Dynamic Rarity** package, unblocked by `set_dynamic_rarity`.
- **The jack hammer's four unsourced vault keys**, which need a research pass
  before the table is rebuilt (cited from
  [`special-items-behaviour.md`](special-items-behaviour.md)).

Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

- **The Conservatory remodel, researched to datamined ground truth.** Owner set
  the research priority: *"Go with whatever comes from the data mining followed
  by the wiki in that order"*, and offered a hypothesis — *"I suspect it's
  uniform random irrespective of rarity."*

  **The hypothesis is SUPPORTED.** The Conservatory page's `DataMinedBox` says
  *"the table presents three random rooms that passed the filters"*, with **no
  rarity term anywhere** — unlike the normal draft (*"the game first chooses a
  rarity and then selects a room of that rarity"*), and matching the Duct Draw
  shape, which the wiki states outright as *"uniformly at random from the list
  (ignoring rarity and other modifiers)"*.

  **Two honest qualifications, recorded rather than smoothed over:** the
  datamine never uses the word "uniform", and it never says whether the three
  are drawn **with or without replacement**. The bug clause — *"this list
  contains bugged entries that, if they appear, appear like one of the other
  entries already present"* — implies the **fallback** path is not
  de-duplicated. Treat "uniform, without replacement" as the reading and "with
  replacement" as unverified.

  **The datamined filter chain, which belongs in DATA when this is built:** from
  86 rooms, drop any whose rarity has been changed **by any method** (so a
  wrenched room disappears from future offers); Studio Additions and Found
  Floorplans must have been added or found; Gift Shop drops if never drafted;
  Freezer, Pump Room and Dovecote always drop. **If fewer than 3 survive, it
  presents three from the full 86 ignoring every filter.**

  **The sim's matching concept lands at 85, not 86** — `pool in {base,
  studio_addition}` = 95, minus the 16 named unchangeable rooms = 85. The 8
  outer rooms are already excluded. **The 1-room gap is unresolved** and was not
  worth chasing. *"Interior room" is the owner's term, not the game's*: the
  game-side concept is "rooms whose rarity can be changed", and 16 interior
  rooms are excluded, so interior alone is not the criterion.

  **OWNER RULING: the rarity change is ALL THREE, not any one** — *"the player
  may interact with the drawing board to change the rarity of each one"*. The
  wiki wins here, explicitly reversing the owner's earlier "any of the three".

  **OWNER RULING: a no-op click COUNTS as a use.** *"Clicking a floorplan, even
  without actually changing the rarity, counts as changing the rarity."*
  `permanent_rarity` **cannot represent this** — `set_wrench_rarity` *pops* the
  entry when the pick equals the natal rarity, so it cannot express "consumed
  but unchanged". This needs a **second save-scoped set**, roughly 40 lines plus
  an obs key.

  **Two further datamined rules, each load-bearing:**
  - It writes **the same permanent slot as the Gear Wrench**: *"If a room's
    rarity is ever set using the Conservatory and/or Gear Wrench (even if the
    rarity was not changed from the default), that room's Dynamic Rarity is
    permanently ignored."*
  - **Reset does not un-consume.** Resetting via the Room Directory *"acts like
    setting the rarity back to the base rarity, rather than as if the rarity was
    never set in the first place"* — the room stays filtered out.

  **Frequency is unsourced.** Neither source says once per day, once per
  Conservatory, or unlimited. The likely reading is unlimited re-interaction
  with a shrinking offer list, but that is inference.

  **Still unbuilt alongside the remodel: the Conservatory's 15% forced draw.**
  Its Found Floorplan gate has shipped; the forced-draw entry has not, and
  [`drafting.md`](drafting.md) records that gap.

- **Re-filing seven Found Floorplans out of `studio_addition`.** The
  Conservatory's build introduced `pool: "found_floorplan"` as a value of its
  own rather than reusing `studio_addition`. Seven other Found Floorplans still
  sit under `studio_addition` because the repo conflated the two concepts. The
  new value stops entrenching that; moving the other seven is this separate
  pass.

  **Care is required around `throne_room` and `treasure_trove`.** Both are
  `pool: "studio_addition"`, and each reaches the pool by two doors:
  `cfg.studio_additions`, and its own blueprint flag
  (`cfg.throne_room_blueprint` / `cfg.treasure_trove_blackprint`), which
  `all_unlocks_config()` sets. Repointing either one therefore no longer drops
  it from the training pool silently: the Throne Room still arrives by its own
  flag, and the Treasure Trove is held out of that pool deliberately and
  visibly by `banned_rooms`, because its black-box reward is unmodelled
  (`rl/train.py`). Check both doors and the ban before moving either.

- **The Spiral of Stars.** Twelve of the thirteen constellations are
  `implemented: true`; the Spiral is the exception, carrying
  `blocked_on: spiral_word_growth_not_modeled`. Its word growth is the only
  permanent, save-scoped quantity in the constellation system and has no
  primitive to hang off. [`rl-environment.md`](rl-environment.md) owns the
  action-width register; the reserved, permanently-masked slot for this build
  already exists, so landing it costs zero width and no extra retrain.

- **The Basement Key's persistence scope is unsettled, and three sources
  disagree.** New ground truth from owner play, which **supersedes the wiki**:
  *"Add the Basement Key to the Antechamber. It appears on a pedestal in the
  Antechamber when you enter the room, allowing you to take it and go through
  The Foundation or the fountain door to open a basement door permanently across
  an entire save, granting permanent access without needing to return to the
  Antechamber."*

  What shipped is different: `basement_key` is a `persistence: "permanent"` item
  re-granted daily from the Antechamber pillar, gating the area edges, with
  [`areas.md`](areas.md) recording the modelling choice — *"Models 'unlocked at
  some point' as 'key currently held' — they coincide since basement_key is
  permanent and re-granted daily."*

  **The three readings that need reconciling**, and this is a design question,
  not an implementation detail:
  - Owner play: *"permanently across an entire save"* — a save-scoped
    **boolean**.
  - [`scoping-and-carryover.md`](scoping-and-carryover.md): the closure would
    need a save-scoped **set** (`basement_doors_open`), **not a bool**, because
    the ruling was "open *a* basement door", singular, and there are three.
  - `special_items.json`: the key *"opens every basement door for the rest of
    the day and every later day"*.

  Since `carried_items` is attempt-scoped, none of the three is save-scoped
  today. `DayChain._CARRYOVER_KEYS` remains **bool-only**, and its length is
  never frozen, so growing it is available if the boolean reading wins --
  though not free: `test_all_unlocks_config_sets_every_carryover_key` fails
  until any new key is enabled in `all_unlocks_config()` too.

- **The retrain is owed, and is held on the owner's explicit say-so alone.**
  `baseline-ep8275991` was trained against rules the sim no longer implements —
  it was built at `N_ACTIONS` 196 against today's width, so by
  [`rl-environment.md`](rl-environment.md)'s own rule it cannot load. **Retrain
  once, after the batch lands**, not per change. Task 24's reward calibration is
  blocked behind it.

- **2026-08-11, the Mail Room's Dynamic Rarity deferral is re-opened.**
  Owner. It was deferred on 2026-08-09 with the stated reason that
  `decks.py` had no rarity-override channel and building one was its own work
  touching the draft hot path. **That reason expires the moment the Aquarium
  groundwork lands** -- the card-move primitive is exactly the channel it
  wanted. A waiting package setting the Mail Room to Commonplace becomes a
  few lines on the same primitive.

  Its own small PR, after the groundwork. Note the wiki publishes a ~25-room
  Dynamic Rarity table, none of it modelled; this re-opens the Mail Room
  specifically, not the table.

- **2026-08-11, the jack hammer's unsourced vault keys are resolved by what
  they unlock.** Owner, on the four vault keys our dig table carries that the
  datamine does not list: *"Research the items blocked by the keys. Drop any
  keys that only block puzzles or story items. Model those that block items we
  do model, like gems."*

  So this is not a keep-all or delete-all call. Each of `vault_key_304`,
  `vault_key_149`, `vault_key_233` and `vault_key_370` is judged on its own
  vault's contents: a vault holding modelled resources justifies keeping its
  key in the table; a vault holding only puzzle or story content does not.

  Act on this cold as: this needs a research pass over what each vault
  contains before the full table reconciliation runs, and the outcome must be
  written into `dig.meta.note` so the next reader does not re-open it.
