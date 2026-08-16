# Open tasks

Work the project owner has identified and that is NOT in `docs/plan.md`'s
delivered set -- each needs its own design pass. Two sources so far: a review of
the special-items PR stack, and a recorded session of real play through the
Training Observatory. That first session's findings have shipped; a second
session produced tasks 44-48, of which 48 remains.

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
[`power.md`](power.md) (the steam-power rule, the powered-room lists),
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
multi-day run data behind them.

**The statistics now exist, and they are the finding.** `runs/postplay-v1`
(`--multi-day 1000 --unlocks all`, 30 envs) reached **1.4M episodes across 66
full 1000-day chains with zero tracebacks** -- the engine holds up over long
chains. But **`win_rate` is 0.0 for every one of those episodes**: the policy
has never once reached the Antechamber. `ep_rew_mean` drifted 0.669 -> 0.764
while `ep_len_mean` stayed near 15.6 actions per day, against
`frontier_greedy`'s 24.3 rooms placed per day.

**The cause is measured, and it is the fixture, not the constants.**
Evaluating `ep1700003.zip` on the same `all_unlocks_config()` the run trains
against:

| measure | trained policy | `frontier_greedy` | `random` |
|---|---|---|---|
| mean deepest rank | **1.00** | 7.19 | 3.04 |
| mean rooms placed | **1.00** | 23.99 | 9.16 |
| P(reach Antechamber) | 0.000% | 6.675% | 0.000% |

Rank 1.00 and one room placed means **the Entrance Hall and nothing else**:
the policy never drafts. It is not merely losing, it is doing worse than
`random`. This is not a deterministic-evaluation artifact -- sampling the
stochastic policy instead only moves rank to 1.20.

What it does instead is leave the house and tour the grounds. Its three most
frequent actions are travel to `blackbridge_grotto`, `mine_south` and
`upper_rotating_gear`, and over 40 episodes it visited
`blackbridge_grotto`, `mine_south`, `upper_rotating_gear` and `west_path` in
**40 of 40**. Two independent measurements agree on this: the action
histogram and `state.areas_visited`.

The fixture is what makes that possible. Counting legal travel actions on the
first step of day 1:

- `all_unlocks_config()` -- **9** targets, including `blackbridge_grotto`,
  `mine_south`, `upper_rotating_gear` and `basement`
- `fresh_save_config()` -- **3**: `apple_orchard`, `campsite`, `private_drive`

Because the preset's job is to set every carry flag, the whole area graph is
open from the first decision, and touring it pays shaping reward with no
drafting required. The agent found the highest-reward-per-step loop available
and it does not involve playing the game. That is why `ep_rew_mean` rises
while rank does not.

**This answers the owner's own question** -- *"I would ask why that is called
for the training baseline instead of a `default_config()`"*. Empirically, it
should not be: `all_unlocks_config()` is correct as a spec (it must enable
every unlock) but it is a degenerate training fixture.

**The single most-taken action in that policy was travel to
`blackbridge_grotto`**, whose edge passed on a POWER conjunct that stood in for
an unbuilt mechanism. Both of its conjuncts are now real and independently
load-bearing ([`power.md`](power.md)), so that action is gated.

So calibration does not start from the constants. The fixture is settled and
POWER is built; **what is left is the retune, and it needs statistics from a
run that actually plays the game.**

**OWNER RULING: stop the run and train from a fresh save.** `runs/postplay-v1`
was stopped at ~1.85M episodes; its checkpoints remain on disk. *"The training
should start from a fresh save. The default config should just be a fresh
save."* So `--unlocks` and `make_single_env` default to `none`, and there is no
third `default_config()` -- fresh save **is** the default.
`all_unlocks_config()` remains correct as a spec and stays available as an
explicit preset; it simply stops being what training starts from.

The fixture is only the *starting* state: `DayChain` carries earned flags
forward, so a chain can in principle reach the late game by playing into it.
Measured, the default now starts with **1 of 19 carry flags and 3 legal travel
targets** instead of 19 and 9.

**But no policy we have ever plays into it, and that is measured.** Over a
250-day fresh-save chain, `frontier_greedy` reaches rank 9 and averages 6.54 --
it drafts well -- and earns **0 of the 19 carry flags, on every day**. Over 60
fresh-save days each, `greedy_rank`, `economy` and `random` also earn **none**.

The carryover plumbing is not the problem: all 19 keys appear in
`Game.carryover()`'s output, so anything earned would be carried. Nothing is
ever earned. The unlocks need specific rooms drafted *and* deliberate off-grid
routing (reaching `west_path`, `mine_south`, the Orchard), and drafting-led
policies never go there.

**So a fresh-save run has an exploration problem, not just a calibration one.**
A 1000-day chain from a fresh save currently replays day 1 a thousand times.
The fixture ruling stands -- `all_unlocks_config()` is degenerate for the
opposite reason, handing the whole map over for free -- but the retune cannot
assume the chain will progress on its own. Whether to shape toward the first
unlock, seed the chain part-way, or accept a long flat start is the open
question, and it should be settled before committing a long run.

**What remains on this task is the reward calibration itself.** The fixture
explains why touring beat drafting; it does not calibrate
`special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY` or the scepter
bias. Those still need statistics from a run that actually plays the game, so
this task stays open behind the next one.

## 48. A colour-selective draft loses a slot when a default is already placed

> "I was only able to draft *two* yellow rooms instead of *three* from a Secret
> Passage on the east wing (r4c4). I had already drafted the Commissary. Inspect
> what yellow rooms are draftable in r5c4."

**Reproduced, and the owner is right: the sim is wrong.** "Yellow" is the
**shop** colour -- the game's borders are violet/bedroom, orange/hallway,
green, **yellow/shop**, red, black/blackprint, which maps onto the engine's five
categories exactly (blueprince.wiki.gg). The Commissary is a shop, so the report
is a shop-colour draft with a shop already on the grid.

Dealing the shop hand at r5c4 (cell 24) entering north, over 200 seeds:

| Commissary already placed | slots dealt |
|---|---|
| no | **3** in 200/200 |
| yes | **2** in 159/200, 3 in 41/200 |

In 159 of those the hand is exactly `(kitchen, locksmith)` -- the two survivors
of shop's published default triple `[commissary, kitchen, locksmith]`.

**Root cause, and it is already written down.** A colour-locked slot draws from
the rank/rarity pool, then falls back to that default triple, which for a
colour-locked slot is the *final* fallback. The wiki's other thin-pool
fallback -- **reserve copies**, tried between the pool and the triple -- is
deliberately unmodelled. [`drafting.md`](drafting.md) predicted this exact
outcome: *"That branch is reachable only because reserve copies are unmodelled:
it is a modelling artifact, not a game rule."*

So this is not deck depletion and not geometry -- the earlier enumeration found
7 legal shop rooms at that cell. It is the unmodelled reserve-copy tier, firing
in the common case rather than a rare one.

**It is not shop-specific, and green is worse.** Placing each colour's first
default and dealing that colour, 100 seeds:

| colour | first default | slots dealt |
|---|---|---|
| bedroom | Bedroom | 3 in 100/100 |
| red | Gymnasium | 3 in 98/100 |
| hallway | Hallway | 3 in 87/100 |
| shop | Commissary | **2 in 75/100** |
| green | Courtyard | **1 in 61/100**, 2 in 25/100 |

**The fix is to model reserve copies, and their rules are now researched** --
see [`drafting.md`](drafting.md)'s colour-selective section, which owns the gap.
The answer to the question this task asked is that a reserve is **not** filtered
by the one-copy-per-grid rule (*"may be duplicates of rooms in the estate"*),
which is exactly why it fills a slot the defaults cannot.

Because that relaxes the one-copy invariant for one draw tier and moves the
draft distribution, building it needs a ruling first: **question (a)** below.
Until then a thin colour keeps dealing short hands whenever one of its three
defaults is on the grid.

## 23. OPEN OWNER QUESTIONS

The single home for questions that need an owner ruling before the work they
block can start. A question is added as a lettered item, and cited from
elsewhere by that letter.

**(a) Should reserve copies be modelled?** They are the fix for task 48's short
colour hands, and researched in [`drafting.md`](drafting.md). The cost is that a
reserve *"may be duplicates of rooms in the estate"* -- so building it relaxes
the one-copy-per-grid rule for one draw tier and moves the draft distribution.

**(b) Should the Garage's West Path door want POWER?** It is gated today on
`garage_door_breaker` (the Utility Closet breaker), not on the Garage being a
powered room, though the Garage is a powerable room and the wiki gives it a
powered behaviour. Switching it would move reachability on a route the greedy
policies use heavily.

**(c) Should the Boiler Room's daily switch and single-door routing be
modelled?** The owner's power rule is "shares a doorway", implemented as all
doors always on; the wiki has the Boiler Room switched on each day and routing
to one door at a time. Recorded in [`power.md`](power.md). Modelling it needs a
per-day activation act and a chosen-door state, i.e. an action-space change.

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

  **OWNER RULING: uniform random WITH replacement.** *"The Conservatory is
  quite simple. Select three random rooms to permit their rarity to be
  changed... Use 'uniform random with replacement' as the model."* This settles
  the point the datamine left open — it never uses the word "uniform" and never
  says whether the three are drawn with or without replacement. With
  replacement means the three offers can repeat a room, which also matches the
  bug clause — *"this list contains bugged entries that, if they appear, appear
  like one of the other entries already present"* — reading as a
  non-de-duplicated draw rather than a special case.

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

  **OWNER RULING: a modified room stays eligible.** *"The modified room can be
  modified in future days."* **This contradicts the datamine and is recorded as
  a conflict, not smoothed over.** The datamined filter chain drops from future
  offers *any room whose rarity has been changed by any method*, and adds that
  resetting via the Room Directory *"acts like setting the rarity back to the
  base rarity, rather than as if the rarity was never set in the first place"*
  — i.e. the room stays filtered out. Owner play governs, so the filter chain
  loses its "already changed" exclusion entirely and the offer list does not
  shrink as rooms are used.

  **One datamined rule survives untouched**, because it is about a different
  thing: the Conservatory writes **the same permanent slot as the Gear
  Wrench**, so *"if a room's rarity is ever set... that room's Dynamic Rarity is
  permanently ignored"*. That governs Dynamic Rarity, not Conservatory
  eligibility, and the ruling above does not disturb it.

  **Frequency is still unsourced**, and the ruling changes what the open
  question means: with no "already changed" exclusion the offer list never
  shrinks, so "unlimited re-interaction" would be unbounded rather than
  self-limiting. Whether the board is once per day, once per Conservatory, or
  unlimited is the remaining gap.

  **Still unbuilt alongside the remodel: the Conservatory's 15% forced draw.**
  Its Found Floorplan gate has shipped; the forced-draw entry has not, and
  [`drafting.md`](drafting.md) records that gap.

- **Re-filing seven Found Floorplans out of `studio_addition`.** The
  Conservatory's build introduced `pool: "found_floorplan"` as a value of its
  own rather than reusing `studio_addition`. Seven other Found Floorplans still
  sit under `studio_addition` because the repo conflated the two concepts. The
  new value stops entrenching that; moving the other seven is this separate
  pass.

  **OWNER RULING: do it.** *"Move the 'found' floorplans from studio_addition
  into found_floorplan."*

  **Care is required around `throne_room` and `treasure_trove`.** Both are
  `pool: "studio_addition"`, and each reaches the pool by two doors:
  `cfg.studio_additions`, and its own blueprint flag
  (`cfg.throne_room_blueprint` / `cfg.treasure_trove_blackprint`), which
  `all_unlocks_config()` sets. Repointing either one therefore no longer drops
  it from the training pool silently: the Throne Room still arrives by its own
  flag, and the Treasure Trove is held out of that pool deliberately and
  visibly by `banned_rooms`, because its black-box reward is unmodelled
  (`rl/train.py`). Check both doors and the ban before moving either.

- **The Spiral of Stars — OWNER RULING: land it.** *"Just land the spiral of
  stars."* Twelve of the thirteen constellations are
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

  **OWNER RULING, and it settles all three readings:** *"The Basement Key will
  open locked basement doors. You need to enter the room with the door holding
  the Basement Key to unlock the door. Once unlocked, the door will remain
  unlocked for the rest of the seed."*

  Three things follow, and each rules out one of the readings that were open:
  - **Per door, not global.** Unlocking needs the player to *enter the room
    with that door* while holding the key, so `special_items.json`'s *"opens
    every basement door"* is wrong: the key opens the door you bring it to.
  - **A save-scoped SET, not a boolean.** Since doors open one at a time and
    each stays open, the state is which doors are open --
    [`scoping-and-carryover.md`](scoping-and-carryover.md)'s
    `basement_doors_open` reading wins over the save-scoped bool.
  - **Seed-scoped, so it survives the attempt wrap.** *"For the rest of the
    seed"* puts it with `lab_visited`/`lab_powered` as a named `DayChain`
    carve-out rather than a `_CARRYOVER_KEYS` member, which the wrap clears.

  That also retires the shipped modelling choice [`areas.md`](areas.md)
  records — *"Models 'unlocked at some point' as 'key currently held'"* — since
  the two no longer coincide: under the ruling a door stays open after the key
  is gone, and holding the key does not open a door the player has not visited.
  `_CARRYOVER_KEYS` stays bool-only and does not grow.

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
