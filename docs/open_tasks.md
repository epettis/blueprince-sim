# Open tasks

Features the project owner identified while reviewing the special-items PR stack
(2026-07-26). These are NOT in `docs/plan.md`'s delivered set — each needs its own
design pass. Ordered roughly by how self-contained they are.

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

- a **numbered open task**, cited by number — `open_tasks.md` task 11;
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

## 1. Resource spreading through the house

Several rooms scatter resources into OTHER rooms when drafted, rather than granting
them on entry. None of this is modeled today (the Tomb's per-dead-end gold is the
one exception — `coins_per_deadend` in `engine/effects/tier1.py`).

Known spreaders (owner-reported; **two rows corrected against the wiki 2026-08-06**,
marked below):

| Room | Trigger | Spreads | Target |
|---|---|---|---|
| Patio | on draft | gems | Green Rooms, including itself |
| Secret Garden | on draft | apples and oranges (food) | throughout the house |
| Locker Room | on draft | basic keys | the estate minus its named exclusions (see `rooms.md`); can seed itself |
| Conference Room | passive, while placed | — | absorbs others' spreads, **altering them** |
| Office | **player action, once/day** | money | throughout the house |
| Tomb | on other rooms' drafts | 5 gold per Dead End | into the Tomb itself (ALREADY MODELED) |

**Correction 1 — the Office is not an on-draft effect.** It is a player-triggered,
once-per-day terminal action ("Spread Gold in Estate"), gated behind walking to the
Office and operating its terminal — the same terminal concept as the shipped
`disk_reader` flag. That makes it an **action-space change**, so per this file's own
standing rule it belongs bundled with a retrain, not with the on-draft spreaders. Do
not conflate it with the Office *safe* (+1 gem), which is already shipped.

**Correction 2 — the Conference Room is not a pure redirect.** The wiki: *"Spread
effects do not necessarily spread the same number of items to the Conference Room as
they would spread if the Conference Room were not present."* Patio's gems change
colour; Secret Garden's CR case is a **completely different fixed formula** (always 4
apples + 3 oranges, regardless of house size or soil quality) rather than the same
roll redirected. So each spreader needs its own Conference-Room branch — a single
generic "change the destination cell" function is the wrong shape.

**A spread is a one-shot event, not a standing rule.** *"Spreading only applies to
rooms currently on the estate. Rooms drafted after the spread is done cannot benefit
from it unless the spread is performed a second time later."* It is evaluated once, at
the spreader's own draft moment, over the cells occupied at that instant. This applies
symmetrically to a Conference Room placed afterward: it absorbs nothing retroactively.

Design notes: this writes resources into *other* cells' pending contents, so it needs
a per-cell "resources waiting here" store. Note the drain cannot hang off first entry
as originally sketched — `_enter()` returns early once `entered[cell]` is true, and
the common case is a spreader drafted *after* its targets were already walked through,
so the drain must sit above that gate and fire on every arrival. The Locker Room case
matters for balance: its keys are what make the room's 17 locked lockers openable (see
PR #26).

## 2. Upgrade Disk functionality

Disks are collected today (Vault box 304, Commissary reserve stock, Trading Post
tier-5 trades, the Garage car trunk) but cannot be *used*. `GameConfig.upgrade_disks`
already swaps a base room for its variant in the deck build, so the missing piece is
the in-run action that awards one.

Wiki research (https://blueprince.wiki.gg/wiki/Upgrade_Disk):
- **Terminals**: standing at any terminal with a disk lets you insert it. Owner adds
  Security, Laboratory, Office, Shelter, Blackbridge Grotto as the terminal rooms.
- **Selection**: the terminal settles on one room to upgrade, then offers **three**
  upgrade options for it; only the new icons are inspectable before choosing. The
  disk is consumed, the upgrade applies **immediately** (a room still in today's
  draft pool can be drafted in its upgraded form the same day), and it is
  **permanent** across days. Which room gets picked is a weighted, chained
  algorithm — [`upgrade-disks-design.md`](upgrade-disks-design.md) is authoritative.
- **Supply**: exactly **16** disks exist, one per upgrade slot.
  The wiki enumerates **15 fixed one-time locations** (Office desk, Morning Room,
  Her Ladyship's Chamber, Commissary reserve 15g, Garage car trunk, Great Hall
  prize door, Vault box 304, Trading Post dynamite chamber, Freezer ice wall, Tomb
  candles, The Foundation, Abandoned Mine, Lost & Found pool, Mechanarium, Archives
  cabinet) plus **one repeatable Trading Post trade** — "Unlike the other Upgrade
  Disks, this disk can appear repeatedly" — which is the 16th. The sim now models
  **16 of the 16**: seven bespoke sources (`upgrade_disk_vault_304`, `_commissary`,
  `_garage`, `_trading_post`, `_lost_and_found`, `_tomb`, `_mine_south`), the
  repeatable `upgrade_disk_trade`, and eight fixed room pickups added via
  `guaranteed_in` (`_office`, `_morning_room`, `_her_ladyships_chamber`,
  `_great_hall`, `_freezer`, `_archives`, `_mechanarium`, `_the_foundation`).
  **The Foundation** and the **Abandoned Mine** were the last two, off-grid until
  the Sanctum-route PR made `the_foundation`/`basement`/`mine_south`/`inner_sanctum`
  reachable (see [`areas.md`](areas.md) and [`foundation-design.md`](foundation-design.md)).
  The Foundation's disk is an ordinary `guaranteed_in` pickup now that the room is
  on the grid; the Abandoned Mine's is a bespoke arrival grant
  (`special_items.py::on_area_arrival`, called from `Game.travel_to` on arrival at
  `mine_south`, since it is a pure area node with no `rooms.json` record).

  **Disks respawn; only SPENDING is permanent** (owner, 2026-07-27): "The disks
  reappear in their location every day. The safe remains open permanently." So an
  unspent disk drops from inventory overnight and returns to its source; inserting
  one at a terminal is the only thing that removes it from the world.

  Every disk therefore carries `persistence: "day"` except `upgrade_disk_trade`,
  which is genuinely repeatable. The permanence is enforced by the
  `GameConfig.collected_disks` carryover — populated from *spent* disks only,
  seeded into `gated_out` at day start, accumulated as a union by `DayChain`, and
  cleared on attempt wrap, the same shape as `used_vault_keys` and `lit_targets`.
  `fixed_disks_spent_today` keys off `persistence == "day"`, which makes the
  trade-disk exemption data-driven rather than a hardcoded id list.

  **Uniqueness alone does NOT enforce this.** A unique item is only blocked while
  *held*; `remove(consumed=True)` records it in `state.special.removed`, which is
  per-day state. Without `collected_disks` a spent disk is re-minted the next day —
  measured at 7 duplicates per day before the fix.

  Re-collection cost differs by source, and this is deliberate, not an oversight:

  - **Vault box 304** — the box stays open permanently; no key needed again.
  - **Garage car trunk** — re-locks *every night*; Car Keys are required on every
    single open (owner-confirmed). The most expensive disk to re-collect.
  - **Tomb / Trading Post** — candles stay lit; the disk returns on re-entry with
    no ignition tool.
  - **Commissary** — ordinary stock at 15g, offered on ~31% of days.
  - **Lost & Found** — stays in the random pool until spent.

  **Pre-existing bug found 2026-07-27: the Commissary disk was never obtainable.**
  It was flagged `reserve: true`, and the reserve branch only fired when available
  primary entries fell below `slots`. Four of the thirteen entries are
  `kind: resource`, which the availability filter never inspects, so primary was
  permanently >= 4 with `slots = 4` and reserve was unreachable dead code. Measured
  0/400 daily rolls. The sim was documented as modelling 7 disks but only **6** were
  ever reachable. Fixed by making it ordinary stock and deleting the dead reserve
  machinery, so a stray `reserve` key can no longer silently hide an item.
- **Upgradable rooms**: **15 rooms carrying 16 upgrade slots**, because Spare Room
  is upgraded twice — the first pick turns it into Spare Bedroom / Greenroom / Hall,
  and the second upgrades whichever of those was chosen into one of *its* own three
  sub-variants (`rooms.json` models this as a second-level `variant_of` chain).
  The other fourteen: Parlor (Gems / Keys / Funeral), Billiard Room (Speakeasy /
  Break Room / Pool Hall), Closet (Hallway / Bedroom / Empty), Storeroom (Keys /
  Gems / Coins), Nook (Extra Key / Breakfast / Reading), Mail Room (Same Day / No
  Contact / Freight), Aquarium (Goldfish / Starfish / Electric Eel), plus
  unnumbered Boudoir, Guest Bedroom, Nursery, Bunk Room, Hallway, Courtyard, and
  Cloister. Cloister has **8** variants but the terminal still shows only three, so
  three of the eight are sampled.
- The wiki publishes **no** tier list of "best" upgrades. It notes one endgame trick:
  switching *off* Cloister of Joya keeps its benefit while applying another upgrade.

**Owner decisions** (interview, 2026-07-26) — implement to these:
1. **The draw mechanism** — which room gets picked, how its three options are
   offered, and how the chosen upgrade is applied — is specified in full in
   [`upgrade-disks-design.md`](upgrade-disks-design.md). Read that before
   implementing; it is authoritative and covers the selection tables, the
   same-day application, and the action/observation cost.
2. **Terminals**: Security, Laboratory, Office, Shelter, Blackbridge Grotto (the
   last is outside the grid, reached through the area graph). Insert requires standing in a
   terminal room holding a disk; the disk is consumed.
3. **Persistence**: an upgrade takes effect immediately, lasts the rest of the
   200-day attempt, and **resets on chain wrap**, consistent with every other
   carry-over flag. Mechanically that is two paths: the live decks are rewritten
   the moment the upgrade is chosen (design doc, "Applying the upgrade
   immediately"), and `carryover()` adds the chosen variant id to
   `GameConfig.upgrade_disks` — which already drives deck building — so later days
   rebuild with it, until `DayChain` clears it on wrap.
4. Supply cap: 16 disks exist in the real game, one per upgrade slot. Once every
   slot is filled the game keeps offering rooms, at a flat 1/15, so an upgrade
   already applied can be swapped for a different variant of the same room.

## 6. Remove "puzzle only" items

Some items exist solely to open one specific thing and are consumed doing it. They
cost an inventory slot, a spawn roll, trade-tier membership and often an action id,
and return nothing an agent can reason about — the sim already assumes the player
solves the puzzle of any room they enter, so the *reward* can simply arrive on
entry. The Wind-up Key was removed on exactly this reasoning (design doc
simplification #17); apply the same test to the rest of the catalogue.

Candidates to audit: `diary_key` (opens the Sleep Diary only), `key_of_aries`
(opens the Treasure Trove box only), `file_cabinet_key` (one drawer each),
`basement_key`, `mora_jai`-adjacent records if any. For each: does holding it ever
present the agent with a *choice*? If not, delete the item and grant its payoff
directly.

**Audited and ruled 2026-08-06 — see the decisions log.** Outcome: **`diary_key`
removed; everything else kept or deferred.** `file_cabinet_key` KEEP,
`basement_key` KEEP, `sanctum_key` and `key_of_aries` DEFER. Two findings that
changed the task's premise: the removal candidates were already
`implemented: false` with zero Python references, so this frees an observation
dimension and a spawn slot — **not** the action id and inventory slot the task
assumed; and there is no `mora_jai` record at all, the item standing in for
"opens a Mora Jai box" is `sanctum_key`. The calibration example for the
decisive test is `basement_key`: holding it is the literal difference between
`reservoir_south` and the far side of the Basement being reachable or not.

## 7. Ignition candles in the Abandoned Mine

**Unblocked — the area graph has landed.** Eight candlesticks stand in the
Abandoned Mine's circular room; lighting them all with an ignition tool (Torch or
Burning Glass) permanently sinks the floor into a stairway down to **the
Precipice**. So it is a graph edge, not just a reward — add it as a permanent `abandoned_mine -> precipice` edge.

The Mine is also what connects the Reservoir's north and south halves, which is
the likely source of the earlier belief that the candles linked the Reservoir to
the Precipice. They do not: the Reservoir reaches the Precipice only by walking
through the Mine.

## 8. Model the Casino games

The Casino is a room of gambling minigames (slot machine, roulette). Two pieces:
1. **Expected value** for the reward function, so a policy can price entering.
2. **Outcome simulation** so those rewards actualize — seeded rolls, per-game odds
   in data.

Ties into the Broken Lever (its golden slot machine gives 5 bonus spins instead of
3) and the Allowance Token (roulette is a repeatable source).

## 9. The Antechamber needs a lever, not just a door

Landing this is the validation test for the Upgrade Disk work: Cloister of
Orinda opens a random Antechamber door, which is worthless while the Antechamber
has no locks, so Orinda's measured value should rise once this lands. How to
measure that — and why the comparison needs control upgrades and a fixed
instrument — is in
[`upgrade-value-measurement.md`](upgrade-value-measurement.md). Take the
pre-lock baseline **before** starting this task.

**Current model is wrong in an important way**: the run is resolved by walking into
the Antechamber, but in the real game its doors must first be opened by a lever
found in the **Secret Garden**, **Great Hall**, **Greenhouse** (with a Broken
Lever), or **Weight Room** (after breaking the wall with a Power Hammer). The
Greenhouse case is already modeled (PR #28) as opening the Antechamber's south
segment; the other three are not, and neither is the requirement itself.

This changes the shape of a winning run and therefore the reward landscape — treat
it as a design pass, not a patch. The north Antechamber door is a separate matter:
it opens only from the Throne Room and the Sanctum lever.

## 10. Allowance for assumed-solved puzzles

Because the sim assumes the player solves every puzzle in a room they enter,
several rooms should carry a standing **+2 allowance**: the **Cloister**, the
**Trading Post**, and the **Closed Exhibit**. Verify against the wiki whether this
is allowance (the daily gold packet) or a one-time grant, then encode it the same
way the room safes are ([`rooms.md`](rooms.md)).

## 11. Model the Pump Room's water levels

Write-up only (owner decision, 2026-08-04: gate the Basement doors on the
Basement Key now, take on the Pump Room next) — not built in this pass. Two
graph edges already carry stub gates waiting on this
(`pump_water_lte8`, `rowboat_water_6`, both `retire_in: "PR-pump-room"`), and a
third traversal condition (below) is not modelled at all yet.

**The room.** Six water sources, each with its own independent integer level
— there is no single estate-wide "water level":

| Source | Initial / max level |
|---|---|
| Fountain | 12 / 12 |
| Reservoir | 14 / 14 |
| Aquarium | 6 / 6 |
| Kitchen | 0 / 3 |
| Greenhouse | 1 / 5 |
| Pool | 8 / 9 |

Two tanks (capacity 4 each) and four pumps move water between a tank and any
one of the six sources: *"Switching a pump up causes water to drain from a
selected water source into a tank. Switching a pump down causes water to fill
a selected water source from a tank."*

**Persistence rule.** *"Changes to the water levels are permanent, although
the selected source and position of the pump levers will reset each day."*
So: the six integer levels need to live in carry-over state (permanent, like
`collected_disks`), while which source each pump currently targets and each
lever's position are ordinary per-day `GameState` (reset every `reset()`,
never carried).

**Gates this retires:**
- `pump_water_lte8` (`grounds -> well`): Fountain level `<= 8`.
- `rowboat_water_6` (`reservoir_south <-> safehouse`): Reservoir level
  `== 6`.
- `reservoir_water_13` (`reservoir_north <-> reservoir_south`): Reservoir level
  `== 13` lets the boat cross the Reservoir side-to-side. **The edge and gate now
  exist** (2026-08-06) — this entry used to say the crossing was "not represented
  as a graph edge/gate at all". Distinct from the Safehouse rowboat gate.

  **Unlike every other gate in this list it defaults CLOSED**, so retiring it
  *opens* a route rather than tightening one. That is the reverse of the usual
  stub-retirement direction and it must be re-measured, not assumed safe: an open
  crossing puts the `safehouse` (a Sanctum Key source) 6 key-free hops from the
  house. See `docs/areas.md` for the measurement and the reasoning.

**New traversal condition to add**, not currently modelled even as a stub:
`well -> reservoir_south` needs Fountain level `== 0`, checked on **every**
traversal (not just once) — *"this passage is only traversible while the
fountain water level is 0"* (Well). This is on top of the existing permanent
Basement Key unlock (`basement_key_well`); the two are independent conditions
(key unlocks the door permanently, water level gates whether the passage is
currently passable). See `areas.md` for the full edge-table writeup.

**Action-space consequence.** Setting pump target/direction is a player
action with no equivalent today — this is not a pure data/gate change like
the other stub retirements in this file, it adds to the action space and
therefore **belongs bundled with a retrain**, the same reasoning that governed
the area graph's sequencing.

## 12. The Greenhouse's Power Hammer wall changes its layout

Write-up only — not built in this pass.

**The Greenhouse is the only room whose doors change when a Power Hammer wall
comes down** (owner, 2026-08-04). Quoting
`https://blueprince.wiki.gg/wiki/Greenhouse`:

- *"The Greenhouse, while initially a Dead End, has a hidden passage which
  includes an extra exit door. This hidden section can be permanently opened
  by using the Power Hammer on the brick wall to the left after entering."*
- *"After the wall is removed, the floorplan is updated to reveal the new
  door and the room permanently changes to an L-shape room."*
- *"if the wall was opened on a previous day, it no longer counts towards the
  total number of Dead Ends in the house."*

The sim already carries the destination shape: the `greenhouse` record in
`rooms.json` is `layout: "dead_end"` with `alt_layouts: ["corner"]`. What is
missing is anything that switches between them.

**The Weight Room is NOT this mechanism, and must not be folded into it.** Its
Power Hammer wall reveals *"a lever for the south Antechamber door as well as
two documents"* (`https://blueprince.wiki.gg/wiki/Weight_Room`), and the space
*"will always be accessible on future days"*. The room's own doors are
unchanged — it has no `alt_layouts` entry, and the wiki says nothing about its
shape. `Game._enter_lever_room` already models it correctly, as a permanent
lever unlock (`weight_room_wall_broken`) that opens the Antechamber's south
segment. Nothing about the Weight Room needs to change.

**Why the Greenhouse is harder than a doorway flip:**

- **Layout, not just doors.** A room's shape comes from an immutable `Room`
  record (`model.Registry.load()`) and is consumed by `legal_orientations` at
  draft/placement time. Nothing lets a room already on the grid swap its shape
  record mid-run, and nothing carries such a swap across the day boundary the
  way `foundation_cell` carries a placement.
- **Two distinct cases.** Breaking the wall today mutates a room already
  standing on the grid; on every later day the Greenhouse must instead be
  *drafted and placed* in its `corner` layout from the start. The second case
  is the easy one — it is a carry-over flag consulted at deck/placement time.
  The first needs live mutation of a placed room.
- **Dead End counting.** The Greenhouse starts as a Dead End and stops being
  one once broken, for the rest of the attempt. That count feeds the Tomb's
  `coins_per_deadend` effect (`effects/tier1.py`, which reads
  `ctx_room.layout == "dead_end"` at draft time) and the `dead_end`
  day-termination path (`game.py`). A layout change that does not also move
  the Dead End count would leave the Tomb paying out for a room that is no
  longer a Dead End.
- **Retroactive across days.** A wall broken on an earlier day stays broken
  and stays un-counted, so this needs the authoritative-once-set carry-over
  shape of `foundation_cell`, not a same-day flag like `garage_door_breaker`.

**Suggested shape for a future PR:** a `greenhouse_wall_broken` carry-over
flag, set when the player breaks the wall with a Power Hammer; consulted at
placement/legality time to substitute the `corner` layout for `dead_end`; plus
the matching correction to Dead End counting so the Tomb effect and the
termination path both stop seeing it as a Dead End.

## 14. Category biases that nothing ever activates

Found while auditing the Cloister boosts (2026-08-05). `data/priority_draws.json`
declares **22 `category_biases` entries; only 8 can ever fire.**
`draft.py::_active_conditions` emits exactly three condition families —
`furnace_or_king` (from `state.furnace_placed`), `greenhouse_or_king` (from
`state.greenhouse_placed`), and `scepter_<color>` (from
`state.shops.scepter_color`). Verified by grep over all of `src/`: no other code
path produces any of the remaining tags.

The **14 inert entries**, spanning **9 distinct condition names**:

| Condition | Entries | Biases toward |
|---|---|---|
| `king` | 5 | blueprint, hallway, bedroom, shop, blackprint categories |
| `southern_cross_constellation` | 1 | `layout: cross`, 40% |
| `draxus_constellation` | 1 | `layout: dead_end`, 30% |
| `drafting_from_library` | 2 | the Bookshop (50%) and `rarity: rare` (100%) |
| `schoolhouse` | 1 | the Classroom, 35% |
| `electromagnet` | 1 | mechanical/rotunda, 40% |
| `chronograph` | 1 | tomorrow rooms, 40% |
| `adjacent_duct` | 1 | `flag: powered`, 40% |
| `adjacent_powered` | 1 | `flag: duct`, 40% |

**Owner decision (interview, 2026-08-05): fold the whole set into the Southern
Cross work** — build the activation plumbing once and light up every condition
that has a modelled source, leaving the rest documented as still-unsourced.

**Why Southern Cross is the one that matters for the upgrade study.** The two
Cloister boosts that already work bias by **category** (`green`); Southern Cross
biases by **layout** (`cross`). Every Cloister variant is `layout: cross`, but
`cloister_of_orinda__ix35` is `category: blackprint` and
`cloister_of_draxus__ix36` is `category: red` — so the two working boosts stop
applying to exactly the two variants the Orinda measurement cares about.
Southern Cross is the only one that does not.

**Research needed before any code**: what activates a constellation in the real
game (Observatory / Telescope?), whether it is per-day or permanent, and whether
`king` is the Banner of the King (`scepter_*` already cites the Royal Scepter as
having "the same effect as Banner of the King", which suggests the `king` tag and
the scepter tags may be the same mechanism entered from two directions). Do not
infer any of this from the existing table.

### Status after PR #60 and 2026-08-06 — the table above is stale

`_active_conditions` now also emits `schoolhouse`, `southern_cross_constellation`,
`draxus_constellation` and `drafting_from_library`, so most of the 14 are wired.
What actually remains:

- **`drafting_from_library` — DONE, and it was the wrong mechanism.** The Library
  does not bias a re-deal; it **replaces the rarity table outright** (Commonplace
  0%, Standard 0.01%, Unusual 49.99%, Rare 50%, datamined). Implemented in
  `decks.py::roll_rarity` with the table in `weights.json`; the inert
  `category_biases` signpost entry is deleted. The Bookshop 50% entry is separate
  and still a genuine category bias.
- **`schoolhouse` — the last small one.** `state.schoolhouse_placed` is read by
  `_active_conditions` but **nothing ever sets it**. It needs one `Hook.ON_PLACE`
  effect tag mirroring `greenhouse_bias`/`furnace_bias` in `effects/tier1.py`.
  The Schoolhouse record already has a working `inject_pool` ON_PLACE effect, so
  this is a second tag on an existing list. 35% Classroom bias is datamined.

  **Completeness gap worth flagging separately**: the wiki says the Schoolhouse
  also boosts the Library and Studio Addition: Dormitory, but our data encodes
  only the Classroom entry. That is a missing-entries problem, not a wrong
  magnitude — do not invent the other two percentages.
- **The two constellations' activation chains — DONE.** Activating the Southern
  Cross or Draxus from an Observatory night sky sets its day-scoped flag
  (`engine/constellations.py::apply_effect`, driven by each record's own
  `effect.condition` naming the `category_biases` entry). Measured over 300
  seeds × 3 option slots at an interior cell: `layout: cross` options go
  3.3% → 39.4%, `layout: dead_end` 27.2% → 46.4%.
- **Still genuinely unsourced** (no modelled activation source): the five `king_*`
  tags, `electromagnet`, `chronograph`, `adjacent_duct` and `adjacent_powered`.

## 15. Room-behaviour fidelity: audit every room against the wiki

Opened 2026-08-08. The owner played several days through the Play tab and found
four modelling gaps in one sitting. Every one is a room whose *record exists* and
whose behaviour is wrong or missing, which is the class of bug no measurement
against the sim can find -- every probe agrees with the engine, because the
engine is what it measures. That makes this a systematic problem rather than
four tickets.

### The four found by play (verified against the data, not just reported)

- **Secret Passage — colour choice not modelled.** `effects: []`. Its own
  `meta.effect_text` says "Leads to a room of a color of your choice", and the
  owner reports the real mechanic: you pick one of **red, green, yellow, orange
  or purple** (blue and black are NOT offered), and then every room drafted from
  that room is that colour, unless none of that colour remain. Nothing
  implements this, and it is a *player choice*, so it needs an action, not just
  an effect tag.

- **Pantry — grants nothing.** `effects: []`, `meta.effect_text: "+4<coin>"`.
  Owner: it always gives **one random fruit (apple, orange or banana) and +4
  coins**. Note apples and oranges do not exist in `data/items.json` today (only
  `banana` among fruit) -- the same gap the resource-spreading design note hit
  for the Secret Garden, so the two should be fixed together.

- **Nursery — missing its immediate self-grant.** It has
  `grant_on_draft_category`, which pays when a Bedroom is drafted *later*, but
  the owner reports it **immediately grants the bedroom step bonus (+5 by
  default) on its own draft**. The forward-looking half works; the on-draft half
  is absent.

- **Eight rooms have a POOL name where a COLOUR should be.** The owner's example
  was the Vestibule (should be orange). The underlying fault is broader:
  `category: "studio_addition"` is not a colour at all, and eight rooms carry it
  -- `solarium`, `classroom`, `clock_tower`, `dormitory`, `vestibule`, `casino`,
  `dovecote`, `the_kennel`. Category drives real behaviour (category biases,
  `grant_per_category`, the Cloister/Terrace green boosts, scepter colours), so
  these eight are silently excluded from every category-keyed mechanic.
  `lost_and_found` is already correctly `red` -- the owner cited it as the
  *expected* colour, not a defect.

### The work: a per-room fidelity pass

Ad-hoc fixing has now missed four rooms in a row. Do this systematically instead:

1. **Split room-specific behaviour into per-room unit test files.** Today room
   behaviour is scattered across `test_game.py`, `test_effects*.py` and others,
   so "is the Pantry right?" has no single place to look or to fail.
2. **Research every room's behaviour from the wiki**, with verbatim citations,
   the way the Garage and Tunnel investigations were done.
3. **For each room, evaluate the codebase** to determine whether all of that
   room's functionality is actually modelled -- record present / partial /
   missing per room, and note where `meta.effect_text` describes something the
   `effects` list does not implement. That mismatch found three of the four
   above and is the cheapest first sweep.
4. **Write unit tests for each room's functionality**, following the repo rule
   that tests assert observable behaviour rather than data contents.
5. **Iterate until every room's functionality is properly implemented.**

Expect this to be large -- 169 room records, ~80 in the base pool. It is worth
scoping as a sequence of PRs (a batch of rooms each) rather than one change, and
worth starting with the rooms most likely to matter for the win condition, since
the 2026-08-08 measurement showed victory is unreachable on ~89% of days for
lack of lever rooms.

**Do not start a training run mid-audit** — room behaviour changes what the
policy learns. The rule, and the two runs discarded for breaking it, are in
[`process.md`](process.md).

## 17. Room behaviour: registry migration

Opened 2026-08-10 from the architecture memo (see
[`architecture.md`](architecture.md) for the reasoning and the measurements).
Runs alongside task 15 rather
than blocking it -- task 15 authors what a room does, task 17 changes where that
lives.

| Phase | Content | Status |
|---|---|---|
| 0 | Divergence validator in `validate_data.py` | DONE |
| 1 | Widen `Hook`: `ON_DRAFT_FROM`, `ON_HAND_DEALT`, `ON_ARRIVE`, `ON_DAY_END` | DONE |
| 2 | `room_hook` registry with opt-in `inherit` | DONE |
| 3 | Migrate the 13 singleton tags to `engine/effects/rooms/` | DONE |
| 4 | Relocate room-behaviour branches out of `game.py` / `draft.py` | DONE |
| 5 | Retire the behaviour half of the ingest tables | DONE |

The 13 singleton tags, which are the phase-3 worklist: `study_redraws`,
`allow_duplicates`, `greenhouse_bias`, `anti_luck`, `halve_steps`,
`furnace_bias`, `solarium_weights`, `coins_per_deadend`, `negate_red_rooms`,
`pay_gems_with_steps`, `schoolhouse_bias`, `conservatory_rerolls`,
`coins_per_draft`.

**Two effects draw from the RNG** -- `conservatory_rerolls` and `inject_pool` --
so migrating them can shift seed-stream consumption order. Keep each handler
firing at the same point in `fire()` and re-run `test_draft_stats.py`; a move
there is evidence the draft math regressed, not a flaky test.

**What stays in data, deliberately**: the 9 shared parametric tags -- `grant`,
`grant_per_category`, `grant_on_draft_category`, `set_resource_on_enter`,
`counts_as_bedrooms`, `counts_as_drafting_room`, `inject_pool`,
`free_green_drafts`, `reduce_draft_options`. They carry 44 of 57 effect instances
and are everything `items.py::expected_yields` introspects.

**Done.** CLAUDE.md no longer says "prefer changing behavior by editing data
over editing code" -- it carries the three-way guidance instead: tabular facts
in data, shared parametric tags in data, singleton behaviour in a room module.

## 20. Research outcomes feeding the worklist (2026-08-10)

### Sourced room lists, previously thought unpublished

- **Cloister of Dauja's "rooms with an animal" -- six, enumerated**: Rumpus
  Room, Aquarium, Nursery, Bunk Room (**once only**, despite counting as two
  bedrooms elsewhere), Dovecote, The Kennel. Grants **2 stars** on draft.
  It is an **ad-hoc id list, not a room type** -- the wiki itself cannot
  explain why the Rumpus Room (a mounted fish) and Nursery (plushies) qualify
  while taxidermy rooms like the Trophy Room do not. **Do not derive membership
  from a semantic rule**; it gets both of those wrong.
- **Cloister of Veia's "rooms with a fireplace" -- seven draftable**: Parlor,
  Den, Trophy Room, Drawing Room, Furnace, The Armory, and the Dining Room
  **only when placed in the centre columns or on Rank 9** (on the wings or Rank
  1 it has windows instead). A dirt pile IS our `dig_spots`, and the grant is
  **+8 additive**, not "set to 8" -- which matters only for the Furnace, whose
  baseline is 1, so it reaches 9.

The Dining Room condition is placement-dependent, so `has_fireplace` cannot be
a static room flag for it.

### Conflicts found, unresolved

- **The trunk loot table diverges from the datamined one in two ways.** We
  carry coin totals **11, 13 and 14, which do not exist in the game**, and we
  make the key+gem+coin outcome **three times rarer** than it is (one entry at
  5% against the game's three at 1/20 each). We also do not model the wiki's
  "fall back to the option directly below" rule for already-owned items.
- **The Clock Tower's wiki page contradicts itself**: its infobox says "for
  each Tomorrow room **you draft today**", its prose says "for every Tomorrow
  room **present in the mansion**". Our own text picks neither and omits that
  the Clock Tower counts itself.
- **`spare_great_hall__ix139` has text byte-identical to `great_hall` but a
  different mechanic**: its 7th door is not necessarily locked, it has no side
  doorways, no Antechamber lever and no Upgrade Disk, and a different prize
  table. **They must not share an implementation.**
- **The Funeral Parlor's 30-step penalty applies only to the FIRST box opened**,
  not per empty box, and its gem count is read **when the box is opened**, not
  at draft. Our text implies otherwise on both counts.
- **`her_ladyships_chamber` omits a second effect entirely**: drafting it sets
  the Boudoir's and Walk-In Closet's Dynamic Rarity to Commonplace.

### Resolved, needing no owner call

- **`guess_bedroom__ix70` is fully documented** -- the trailing "?" is in-game
  flavour ("Your guess is as good as mine."), not datamine uncertainty, and
  "Guess Bedroom" is the canonical pun name beside Quest and Geist, not a typo.
  It mimics a random Bedroom in the draft pool, excluding itself, Her
  Ladyship's Chamber, the Master Bedroom and the Spare Bedroom line, and adds a
  once-per-day quiz-sheet guess for a random resource prize.
  **Deferred anyway**: it needs runtime effect and type inheritance from an
  arbitrary other room, which the engine has no mechanism for. The wiki itself
  records that the mimicry is inconsistent in-game.
- **The Aquarium is every room TYPE, not merely every colour** -- Red, Green,
  Hallway, Bedroom, Shop and Blackprint on top of its native Blueprint -- and
  it counts for **penalties as well as bonuses** (cursed, it loses 2 of every
  resource; the Dare Mode shop dare auto-fails on it).
  `electric_eel_aquarium__ix4` **additionally gains the Mechanical type**,
  which our record does not encode.
- **The Speakeasy is a genuine no-op in our model.** "Basic Addition" only
  makes the Dartboard Puzzle easier (one board, one ring, two numbers, addition
  only). We do not model the Dartboard Puzzle and we assume puzzles are solved,
  so there is nothing to implement.
- **The Vestibule's effect is rerollable for 2 steps** by leaving and
  re-entering, and the wiki frames that as the intended strategy. Worth
  watching as a farming incentive once it lands.

### Open question for the owner

- **Cloister of Joya's "permanent" Main Course bonus**: +5 steps to all five
  main courses, cumulative and uncapped, surviving a change of the Cloister's
  upgrade. The wiki never says whether "permanent" means the attempt or the
  whole save. Defaulting to **per attempt**, consistent with every other
  carry-over resetting on wrap -- flagged for confirmation rather than assumed
  silently.

## 21. Capability architecture: the engine provides, rooms declare

Opened 2026-08-10 on an owner ruling; the doctrine, the three layers and the
enforcement invariant are stated in [`architecture.md`](architecture.md), and
this section is the remaining worklist. **Started; the invariant is now
measured rather than estimated.**

`tests/test_room_id_allowlist.py` (PR #188) AST-scans `engine/*.py` and
`engine/effects/*.py` for string literals equal to a real room id, against a
per-module allowlist. It fails in **both** directions: a new literal in an
unlisted module, and an allowlisted id that no longer appears. The second
half is what makes it a ratchet rather than a record.

**The measured starting point below is stale and was already wrong when
written** -- the real count at the time the test landed was 55 pairs, not 45,
because `draft.py` had grown and two modules with room-id literals did not
exist when that table was made. That gap is the argument for the test.

`Capability.LEVER` (PR #189) converted the first four rooms and taught us the
shape: `COMMERCE`'s plain boolean is not enough for a capability that needs a
per-room handler and a live cost query. **Expect locks and containers to need
parameterised handlers too.**

The ratchet has twice converted "just add it to the allowlist" into a better
design -- the Electro Magnet's category union and colour drafting's default
triples both moved to data rather than growing the list.

The target is three layers:

1. **Data (JSON)** -- tabular facts only. Room stats (rarity, layout, gem cost,
   category, deck copies, draft conditions, dig spots, flags) and subsystem
   tables (`shops.json` prices and stock, `locks.json` chances, container loot,
   `mail_packages`). Generated from the datamine wherever it can be.
2. **Engine capabilities** -- mechanisms that know nothing about specific rooms:
   drafting, locks, containers, commerce, digging, food, carry-over, terminals.
3. **Room modules** -- one per room at `effects/rooms/<id>.py`, declaring which
   capabilities the room uses and with what parameters, plus anything bespoke.

**The invariant: no engine module may branch on a room id.** Everything
room-specific is a registration.

The Shop is the pattern-setter. Today `game.py` reads:

```python
if room.category == "shop" or room.id == "workshop":
    shops.on_enter_shop(self, room)
```

which is the engine knowing which rooms are shops. Under the capability model
`shops.py` keeps the mechanism and `shops.json` keeps the table, but each shop
room module *registers* commerce for itself, and the Workshop's special-case
`or room.id == "workshop"` disappears.

### Measured starting point (2026-08-10)

Room ids are hardcoded in 20 modules outside `effects/rooms/`. The behaviour
targets, worst first:

| module | room ids |
|---|---|
| `engine/game.py` | 14 |
| `engine/shops.py` | 12 |
| `engine/special_items.py` | 9 |
| `engine/draft.py` | 7 |
| `engine/decks.py`, `engine/locks.py` | 2, 1 |

**Not targets, and not debt** -- these legitimately name rooms:
`engine/upgrades.py` (15, the disk selection tables), `engine/placement.py` (6,
where the ids are fixtures and named conditions and the tags are already
room-agnostic), `env/actions.py` / `env/obs.py` / `web/play.py` /
`cli/render.py` (env and UI wiring), `config.py` / `rl/train.py` (presets).

Only **27** rooms have a discoverable `effects/rooms/<id>.py` module today.

### Enforcement

A conventions test scanning engine modules for room-id literals against an
explicit allowlist, in the same spirit as `tests/test_conventions.py`'s
docstring rule. **The allowlist starts at today's count and may only shrink.**
That is what stops the architecture rotting back, and it turns "are we done?"
into a number rather than a judgement call.

### Sequencing

Capability by capability, each PR independently green, cheapest first.
Done: commerce (the pattern-setter), containers and digging, the Antechamber
levers. **Locks need nothing** -- `locks.py` reads `locks.json` and carries no
room-id branch at all, which the allowlist confirms.

Next, largest first: `shops.py`'s stock builders (12 ids), `draft.py`'s
named-constant branches, `special_items.py`'s (10). The two day-end branches
in `game.py` (`break_room__ix11`'s keycard pulse, `clock_tower`'s tally) want
one shared `Capability.DAY_END` between them.

### What it buys

- **`_AUDIT_PYTHON_EXEMPT_IDS` disappears.** That hand-maintained id-to-module
  map, added 2026-08-10 with a staleness guard, exists only because behaviour
  hides where the audit cannot see it. With every room registering,
  `registered_rooms()` is complete and the audit credits Python automatically.
- **The "four channels" gotcha collapses to two.** `effects: []` stops being
  ambiguous: stats and shared parametric tags in data, everything bespoke in
  one module per room.
- 24 of the 62 findings triaged on 2026-08-10 were false positives caused
  precisely by this scatter.

## 22. Item behaviour: registry migration (scoping)

Opened 2026-08-11, owner directive. The question, in their words: should items
be "broken out into a registry similarly to how we broke out the rooms"? The
stated reasoning -- "the engine can keep track of the capabilities while the
registry implements those capabilities for each item and special item", and it
"would also likely make it easier for you to stop re-litigating abilities".

Note **"each item and special item"**: two distinct systems are in scope,
`engine/items.py` (the luck / room-item yield system, 201 LOC) and
`engine/special_items.py` (the ~102 inventory items, 2,465 LOC).

**Measured starting point, 2026-08-11.** String literals in `engine/*.py`
(non-recursive) matched against the 102 ids in `special_items.json`:

| | count |
|---|---|
| `(module, item_id)` pairs | **58** -- `special_items.py` 42, `shops.py` 11, `game.py` 4, `placement.py` 1 |
| `(module, effect_tag)` pairs | **36**, over **37** distinct tags (corrected 2026-08-12: the original 35/38 scanned only `engine/*.py`, missing `effects/tier1.py`, and predates #199 deleting `ignition_tool`) |
| item-logic LOC | 4,440 -- `special_items.py` 2,465, `shops.py` 1,200, `upgrades.py` 574, `items.py` 201 |

**For comparison the room-id debt is 79 pairs and is held under an enforced
ratchet (`tests/test_room_id_allowlist.py`). The item debt of 58 is 73% of that,
and has no equivalent enforcement at all** -- it was unmeasured until
this entry.

The motivating observation: `implemented: false` in
`special_items.json` is an *asserted* fact that has repeatedly gone stale (five
false `blocked_on` strings found the same day, two of them on items the engine
already grants or reads). A per-item module would make it *derivable*. Whether
it actually does is the test the recommendation has to pass.

An architecture pass is in flight. It must take a position on the item
equivalent of task 17's central call -- that migration moved 13 singleton tags
and **deliberately left 9 shared parametric ones in data** -- and must propose
an enforcement mechanism that ratchets down rather than only growing.

**Recommendation, 2026-08-12: qualified yes, in two parts.**

**`engine/items.py` is out of scope and already right.** It has zero item-id
branches and dispatches on eight resource kinds via `match`. That is what task
21 asks an engine capability to look like; there is nothing to break out.

**`special_items.py` + the item half of `shops.py` (~3,665 LOC): migrate.**

**The finding that decides the shape: items are the mirror image of rooms.**
Task 17 moved 13 singleton tags and left 9 shared parametric ones carrying 77%
of instances. Items are **30 singletons against 7 genuinely shared tags**
(16 instances). By task 17's own rule -- singleton behaviour belongs in a
module -- **items are a stronger migration candidate than rooms ever were.**

Two refinements to that count, both load-bearing:

- **`allowance` is a false shared tag.** All 19 instances are the same
  `+2 allowance` payload on 19 differently-*sourced* tokens; the variation is
  one-shot bookkeeping, not effect. It still stays in data -- `env/obs.py` and
  `env/multiday.py` read it.
- **`ignition_tool` is dead data.** Nothing reads the tag; `_ignition_tools()`
  reads `registry.special.ignition["tools"]`, a separate list in the same file
  naming the same items. Two sources of truth, one never consulted.

**The registration primitive must NOT be a `room_hook` clone.** A room has a
natural event boundary; an item does not. Item behaviour is overwhelmingly a
**fold over the inventory** -- `move_step_cost`, `gem_cost_modifier`,
`food_steps`, `shield_negates` all ask "does any held item modify this number".
Copying the hook shape yields 40 modules registered against a constantly-firing
hook, and makes fold *order* implicit in import order where today it is visible
as sequential lines. **A bad item registry is strictly worse than the current
2,465 lines, which are at least readable top to bottom.** The shape is
`provides(item_id, Capability, **params)` -- following `Capability.LEVER` --
with the **engine owning the fold and its order** as one explicit tuple, and
the item declaring only its contribution. Genuine hooks are the minority:
`ON_PICKUP`, `ON_ENTER_ROOM`, `ON_DAY_END`.

**Scope is ~40 modules, not 102.** The four id-prefix families
(`upgrade_disk_*` 16, `sanctum_key_*` 8, `vault_key_*` 4, `allowance_token*`
19 -- 47 items) stay generic; `upgrades.py` already matches them by prefix.

**What it does and does not buy.** It makes the *flag* derivable and kills
`implemented`/`blocked_on` for `coupon_book`, `microchip` and
`trophy_of_wealth`. **It does not make the *reason* derivable** -- a blocker is
a claim about a subsystem, not about the item, so `dowsing_rod` and
`crown_of_the_blueprints` stay asserted. Roughly 60% of the observed failure.
**Phase 0 catches more of it, sooner, than the migration does**, which is why
it comes first and stands alone.

**Phases** (each independently mergeable, gates green throughout):

**Phase 1 landed early, in #199**, before the phase table was written: that PR corrected all fourteen `blocked_on` strings, added `meta.reachability`, and deleted the `ignition_tool` tag. Six phases remain, not seven.

| Phase | Content | Size | Risk |
|---|---|---|---|
| 0 | Two scanners + allowlists (`item_id`, `effect_tag`), bidirectional. **No code moves.** | S | Low | **DONE in #200** |
| 1 | Truth pass on the 14 records; delete the `ignition_tool` tag | XS | Low | **DONE in #199** |
| 2 | `ItemCapability` primitives + `effects/items/`; migrate `coupon_book` as pattern-setter | S | Low | **DONE in #203** |
| 3 | Pure-query **singleton** capabilities (8 modules) | M | Low | **DONE in #204** |
| 4 | Item handlers on game events + the engine-owned priority tuples | M | **Med** | **DONE in #205** |
| 5 | Id-branch items, split on RNG risk: 5a RNG-free, 5b RNG-adjacent | M | Med | **DONE in #207, #208** |
| 6 | RNG-touching migrations, **last and alone** | M | **High** | **DONE in #209** |
| 7 | Shrink both allowlists; ~~delete `implemented`/`blocked_on`~~ | S | Low | **allowlist split DONE in #206. The flag deletion is CANCELLED -- its premise does not hold; see [`architecture.md`](architecture.md) on what `blocked_on` carries that no registry can derive.** |

**No phase is a retrain trigger provided the `items` array is never reordered
and nothing is inserted mid-array.** `env/obs.py` enumerates it positionally
for the `inventory` Box -- structurally identical to `Room.idx`. `env/actions.py`
is item-count-independent (`BUY_BASE` etc. are display slots), so the action
space is unaffected.

**Two constraints the scoping brief got wrong, corrected here:**

- **`special_items.json` is hand-maintained.** `ingest_sheet.py` touches only
  `rooms.json`, so the silent-revert hazard does not apply to item data.
- **RNG risk is narrower than feared.** `rng.py` substreams are independent per
  label, so only *same-label* ordering matters. Three item-relevant labels have
  multiple draw sites: `treasure_map` (two functions, one stream -- migrate
  alone), `lost_and_found` (contained), and **`extra_item_kind`, which spans
  `game.py` and `items.py`** -- in the module this plan puts out of scope, so
  it is a hazard for anything touching `roll_extra_items`, independent of this
  work.

**There is no item-side divergence audit at all.** The five guarded exemption
channels are room-only; the entire validation of item implementation status is
a check that `blocked_on` is non-empty -- never that it is *true*. A registry
does not create a sixth exemption channel, it creates the **first** item audit.

**Enforcement floor: ~10 of 58**, better than rooms will ever reach, because
**item ids and room ids are disjoint** -- none of the `"bedroom"`-is-also-a-
category ambiguity that permanently pins ~20 of the room allowlist. Two
separate scanners are required: **13 of the 38 effect tags are spelled
identically to an item id**, so a merged scanner would double-count. The tag
scanner gets a second job: **a tag with zero readers is a hard failure, not an
allowlist entry** -- that rule alone catches `ignition_tool` today.

**Cost: ~8 PRs, ~650 LOC moved, ~500 LOC new.** `special_items.py` should land
around 1,800 LOC.

## Also outstanding (from `docs/plan.md`)

- **Reward calibration** from multi-day training statistics — all shaping constants
  (`special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY`, scepter bias)
  are deliberate knobs awaiting real run data.
- **Inner Sanctum**: the 8 Sanctum Keys have sources and persist, but the area
  behind the 8 doors is unmodeled.

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
built yet.** Two subjects account for most of them.

- **The Conservatory** — undraftable today (`rarity: null`, `gem_cost: 0`, no
  `counts_as_drafting_room`), so its reachability build, its datamined filter
  chain, and the "all three, and a no-op click counts" rulings have no code to
  sit beside.
- **The constellations** — the width has landed and
  [`rl-environment.md`](rl-environment.md) owns it; what remains is the
  per-constellation build.

Plus two standalone unbuilt items: the **Mail Room's Dynamic Rarity** package,
now unblocked by `set_dynamic_rarity`, and the **jack hammer's four unsourced
vault keys**, which need a research pass before the table is rebuilt
(cited from [`special-items-behaviour.md`](special-items-behaviour.md)).

Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

- **2026-08-14, OWNER RULINGS x4: the Conservatory is fully specified for
  reachability. Nothing in that build is now blocked.**

  1. **Fix BOTH `rarity` and `gem_cost` to the wiki: `unusual` and `1`.** The
     repo's `rarity: null` was a misreading of *"the Conservatory cannot have
     its rarity changed"* -- which excludes it from its own re-rarity list, not
     from having a rarity. **This is a fidelity change, not a typo fix:**
     `gem_cost: 1` moves the room out of the free decks and into the **gem**
     decks, changing which slot can draw it and whether a gem-poor player can
     afford it.
  2. **Finding the floorplan REQUIRES A HELD SHOVEL.** *(Rejects the
     recommendation, which was unconditional-on-arrival following the Throne
     Room and Treasure Trove precedent.)* The wiki calls it a **hidden dig
     spot** at the campsite, and the owner ruled the dig is real. **The sim
     models no off-grid area digging at all today** -- dig tooling exists only
     for room dig spots -- so this introduces the first one. Scope it as a
     shovel-held condition on campsite arrival, not a new digging subsystem.
  3. **`pool` gets a NEW value, `found_floorplan`** -- not a reuse of
     `studio_addition`. Seven of the eight Found Floorplans currently sit under
     `studio_addition` because the repo conflates the two concepts; the new
     value stops entrenching that, and **re-filing the other seven is a
     separate later pass**, not part of this build.
  4. **Available from the NEXT day onward**, not the same day. `build_decks`
     runs at day start, so the deck is already built when the floorplan is
     found. Matches the Treasure Trove and Throne Room comments, and needs no
     `inject_rooms` call.

  5. **ADD `counts_as_drafting_room`.** The wiki types the Conservatory as a
     Drafting Room and its page carries that interaction template, so drafting
     it grants a Classroom redraw and a Dormitory step grant. **This is a real
     behaviour change on all-unlocks configs**, not just a tag.
  6. **Fix `priority_draws.json`'s decayed Morning Room clause in this work**,
     not in a later sweep. It currently tells the reader that the Bacon & Eggs
     prerequisite is **unbuilt**; it is built (`effects/rooms/nook.py` sets the
     `breakfast` condition and injects the room) and only the forced draw
     itself is missing. The note sits in the same file and block the
     Conservatory's forced-draw entry lands in.

  **CORRECTION to this entry as first written.** It recorded
  `counts_as_drafting_room` as **NOT added**, on the reading that an unselected
  option in a multi-select meant "declined". **That reading was wrong** -- the
  question was presented as multi-select and read as pick-one, so the omission
  carried no meaning. Re-asked as a single choice and answered **yes**.
  **The offering was the defect, not the answer**: a multi-select that looks
  like a radio group silently converts "I picked the one I cared about" into
  "I declined the rest". Ask one decision per question.

- **2026-08-14, OWNER RULINGS x8. The constellation width is now SETTLED at
  `N_ACTIONS` 442 -> 457, and two live defects are cleared to fix.**

  **TRADING**
  1. **Adopt the wiki's same-item collapse** for Sanctum Keys and Upgrade
     Disks. A trade-offer identity key (game item, not sim id) applied in
     `shops.py::trade_offers` **before the sort**. Takes tier 5's worst case
     from 12 offers to 5. **No obs-width change, so no retrain trigger** --
     and it makes "raise the 8-offer cap" stop being urgent.
  2. **Make the Keycard tradeable**, via the precedent that already exists:
     the Lost & Found steal path special-cases `keycard.held`/`keycard.steal`
     around the generic inventory logic, because the keycard lives in
     `state.has_keycard`, not `state.inventory`. Trading never got the
     equivalent. **A naive fix -- deleting the three exclusion checks -- would
     let a player give it away and KEEP door access**, and would write a
     phantom inventory entry no door code reads. Use the special-case shape.

  **CONSTELLATIONS -- the width is committed by PR1 and cannot move after**
  3. **14 action ids, reserving a permanently-masked slot for the Spiral of
     Stars**, so that build later lands at zero width and zero extra retrain.
  4. **The Ink Well gets its OWN action id**, not a silent `_redraw_kind`
     tail. **Reason, and it is the load-bearing one:** every other redraw
     source spends a hand- or day-scoped resource with a natural bound, while
     `STAR` spends a **permanent, save-scoped** one with no cap -- behind an id
     the agent already presses reflexively. An agent that learned "press
     REDRAW on a bad hand" would convert its entire star bank into rerolls in
     a single day and destroy the constellation engine it spent weeks
     building. **Total: 15 appended ids, `N_ACTIONS` 442 -> 457.**
  5. **Florealis is IN**, reversing the earlier "out to keep the PR down".
     The reversal is on corrected facts, not preference: the orchestrator
     reported it had "no primitive whatsoever" (zero hits for `flower` in
     `src/`). **The measurement was right and the conclusion was wrong** --
     `GameState.spread_pending` already parks per-cell payouts collected by
     `Game._collect_spread`, and `state.py` names this exact future use.
     **~40 lines of reuse, not a subsystem**, so the reason to defer expired.
  6. **The night sky needs an EXPLICIT VIEW ACTION**, not auto-generation on
     entry. Skies lock at the star count when first viewed and higher counts
     partition into strictly more value, so the optimal line is *draft every
     Observatory first, then walk in and look*. **Auto-generating silently
     deletes that timing decision.** Costs no extra id -- the view action
     exists for the Telescope regardless.
  7. **The Observatory's uncapped `+1 star per draft` stays uncapped.** It is
     verified faithful and no published cap exists, so capping it would be an
     invention. **Recorded as a known self-amplifying loop** (draft Observatory
     -> +1 star -> richer sky -> more resources -> more drafts, up to 4
     Observatories/day via the Chamber of Mirrors). The retrain reveals
     whether it dominates; the point is that it is known *before* the retrain.

  **CONSERVATORY**
  8. **Forced-draw blocking is POSITIONAL, not literal** -- a Forced Draw
     blocks later entries in the precedence order **only where its own
     conditions hold**, not merely by being in the pool. This was a 0%-or-100%
     switch on shipped behaviour: the literal reading would have erased the
     Garage's measured 17.6% -> 53.6% forced-draw gain the moment a
     Conservatory floorplan was found. The positional reading is the only one
     consistent with the sim's single global deck model, and the Morning
     Room's documented wings-only exception suggests the game works this way.
     **Conservatory and Garage are provably non-interacting**: corners
     `{0, 4, 40, 44}` vs West Wing `{15, 20, 25, 30, 35}`, disjoint.

- **2026-08-14, OWNER RULINGS x14 -- the queue is now UNBLOCKED. Plus new
  ground truth on the Basement Key that overrides the wiki.**

  **NEW GROUND TRUTH (owner play, supersedes the wiki):** *"Add the Basement
  Key to the Antechamber. It appears on a pedestal in the Antechamber when you
  enter the room, allowing you to take it and go through The Foundation or the
  fountain door to open a basement door permanently across an entire save,
  granting permanent access without needing to return to the Antechamber."*
  The wiki lists the **Spiral** as `basement_key`'s only location; **owner play
  outranks it.** Two consequences: (1) the Spiral is no longer any item's sole
  route, which may shrink that scoping question; (2) *"permanently across an
  entire save"* is a **save-scoped BOOLEAN** -- so this may be the first
  legitimate reason to grow `DayChain._CARRYOVER_KEYS` past **16**, where it
  has sat unchanged all session with every set-valued thing pushed to the
  separate channel. **That is a design question, not an implementation detail;
  it is being answered by a scoping pass, not decided in passing.**

  **CONSTELLATIONS**
  1. **Model the TRUE SUM-PARTITION**, not a `stars >= N` threshold. A
     threshold over-rewards stars and the star engine is what an RL agent will
     exploit.
  2. **Model the PER-CONSTELLATION CHOICE**, not auto-activate. *(Rejects the
     recommendation put to the owner.)* **~1000-1450 lines, 12 appended action
     ids: `N_ACTIONS` 442 -> 454, plus one NEW obs key.** Appended only; no
     existing id shifts. **A retrain is owed** -- see below.
  3. Florealis: not separately ruled; still open if the arm reaches it.

  **CONSERVATORY**
  4. **Build REACHABILITY FIRST** -- the 15% forced draw and the Found
     Floorplan gate -- *then* remodel. The room is undraftable today
     (`"rarity": null`), so remodelling first ships more dead code.
  5. **The wiki wins on "all three"**, not the owner's earlier "any of the
     three" -- explicitly reversing that reading.
  6. **A no-op click COUNTS as a use.** `permanent_rarity` cannot represent it
     (`set_wrench_rarity` *pops* the entry when the pick equals the natal
     rarity), so this needs a **second save-scoped set, ~40 lines + an obs
     key.**

  **DRAFTING FIDELITY**
  7. **Priority Draws are NOT Slot-3-only -- the two mechanisms were
     CONFLATED.** Remove the `slot == 2` gate; Forced Draws stay Slot-3-only.
  8. **BUILD the Day 1 opening draw** -- deterministically Bedroom, Closet,
     Hallway. The sim produced **292 distinct opening hands over 300 seeds**
     and no code for it exists, which already invalidated one queue entry's
     evidence.
  9. **The Commissary/Observatory 46:1 skew is a SECOND DEFECT** -- fix it.
     `_priority_draw` returns the first candidate in list order, so Observatory
     is unreachable by that route: a content gap, not a skew.
  10. **Fix both `priority_draws.json` data gaps** -- the 3% group is
      {Garage, Classroom}, and the Greenhouse moves Secret Passage 5% -> 3%.
  11. **Fix the card consumption WITH the slot-gate work** -- `_priority_draw`
      never calls `deal_next`, so a drawn floorplan stays in its deck.

  **ITEMS**
  12. **BUILD `morning_star`'s star grant on wiki confidence.** Wiki-only and
      unconfirmable by datamine, and the owner accepted that basis.
  13. **BUILD the contraption carry-over lockout.** The shape exists
      -- `collected_disks`/`collected_allowance_tokens`/`collected_sanctum_keys`
      all feed `gated_out`.
      **CORRECTION (this entry was wrong as first written).** It said "6 items"
      with "Dowsing Rod and Pick Sound Amplifier exempt". The wiki says the
      opposite: **every contraption blocks something**, those two included --
      the Dowsing Rod blocks the Compass, the Pick Sound Amplifier blocks the
      Lock Pick Kit. The shipped table (#297) has **8 entries**, and it blocks a
      **curated subset** of each recipe, not the whole recipe. The orchestrator
      briefed the exemptions inverted, the implementing agent checked the source
      and shipped the correct rule, and the correction was recorded in that PR
      body **but not here** -- so this record stated the wrong rule until a later
      agent noticed the doc and the code disagreed. **A correction recorded only
      in a PR body does not reach the file people read.**
  14. **REBUILD `running_shoes` to the real rule.** The `n=3` cadence is
      **invented**, not simplified, and the shoes are **inert off-grid** where
      the wiki gives them their highest rates.
  15. **SCOPE the Spiral and the Dartboard** (both, alongside the Basement Key).

  **SMALL**
  16. **Delete the dead `t5_special_chance` fallback of 50** -- no live reader.
  17. **Real-game patch history IS allowed in data notes**, even when it reads
      like code history. Settles the `experiments.json:417` precedent a sweep
      agent deliberately declined to set.
  18. **Fix the `laundry_room` coupon discount now** -- latent, symptomless
      only because laundry stock is empty.
  19. **`meta.confidence` stays as-is -- labels are ADVISORY.** The owner's
      reasoning: there may simply be more in the wiki than the datamine, and
      wiki interpretation is more reliable here. **Consequence: stop citing
      `confidence` as authority.** The measured inversion (items labelled
      `datamined` are the *least* complete) is therefore not a defect to chase.
  20. **RETRAIN ONCE, after the batch lands** -- not per change.
      `baseline-ep8275991` was trained against rules the sim no longer
      implements: the width change from ruling 2, the lockpick ladder fix, the
      priority-draw free/gem fix, and spawn rates moving up to 6.6x.

- **2026-08-14, CONSTELLATIONS researched. Four corrections to the
  orchestrator, and ITEMS HAVE NO FIDELITY AUDIT AT ALL.**

  Research was read-only and is **wiki-sourced throughout**: the repo's only
  raw datamine (`tools/raw/tfmurphy_room_table.md`) is the v1.3 **room** table
  and contains **zero** constellation data. So the owner's stated priority
  (datamine, then wiki) **could not be exercised here** -- there is no
  datamine to prefer and **no disagreement to report**. Say so when relaying;
  do not let "researched" imply "datamined".

  **Corrections to the orchestrator's brief, all verified:**
  1. **There are 13 constellations, not 11.** The 11 are the 0-49 base set;
     **The Ink Well (50)** and **Spiral of Stars (100)** are the other two.
     `open_tasks.md:1157-1161`'s "all eleven" silently drops them.
  2. **The two wired constellations ARE sourced -- thoroughly.**
     `priority_draws.json:180-207` carries `confidence: datamined`, a sheet
     constant, a wiki URL, the wiki's own selection query transcribed into
     `exclude_rooms`, and a note stating plainly that nothing sets the flag.
     The orchestrator's "wired but never sourced" premise was **wrong**. This
     is the repo's dominant failure mode **not** occurring; record it as such.
     Both magnitudes re-derived and **both are correct**.
  3. **The Telescope's planet arm is PR #264, not #260.** #260 is the
     Planetarium's `on_day_end` star change.
  4. **Unlock is a SUM-PARTITION, not a threshold.** The night sky shows a set
     of constellations whose star values sum **exactly** to the current star
     count. At 6 stars: Twins(2)+Diamondus Minor(4) -- **not** North Star, not
     Slice. Verified by checking the partition invariant across 0-49: **49 of
     50 sum exactly**, the sole exception n=0, which the wiki documents.

  **Why (4) matters more than the auto-vs-choice question it sits under:** a
  naive `stars >= N` gate grants all seven constellations at or below 25 stars;
  the true rule grants five and is strictly weaker. **Collapsing it to a
  threshold over-rewards stars**, and the Observatory/Aquarium/Planetarium star
  engine is exactly what an RL agent will find and exploit. This question is
  **upstream** of the owner's open constellation question and reframes it.

  **Scope, measured:** nothing is permanent except Spiral of Stars' word count.
  Everything else is immediate or day-scoped. **The constellation work does not move `_CARRYOVER_KEYS`**, a
  channel that is bool-only, though its length is not fixed (see
  [`scoping-and-carryover.md`](scoping-and-carryover.md)). Four of the eleven base
  constellations are **non-stacking**, so the Telescope's second sky is a
  **no-op for four of them** -- any cost case assuming it doubles everything is
  wrong.

  **Costs, for the ruling:** auto-activate ~650-950 lines / 8-10 files, and
  **`N_ACTIONS` stays 442** -- because `env/actions.py:840 _redraw_kind`
  already auto-selects the cheapest redraw source behind the single
  `REDRAW_ACTION`, so The Ink Well is a **zero-action-width** change (verified).
  Per-constellation choice: ~1000-1450 lines / 13-16 files, **12 appended
  ids, 442 -> 454**, plus one **new** obs key. No existing key resizes either
  way; day-scoped draft-bias flags are already invisible to the agent
  (`southern_cross_active`, `draxus_active`, `schoolhouse_placed`,
  `add_aquariums_active` appear nowhere in `env/obs.py`).

  **THE STRUCTURAL FINDING, and it is the important part of this entry.**
  Chasing a suspected `morning_star` gap turned up something larger:
  **`find_divergences` is entirely room-scoped.** Item records carry **no
  `meta.effect_text` field at all** -- verified across all **102** of them --
  so there is **no item text-vs-model fidelity audit in existence**. The item
  side has only a registry-consistency check, an empty-effects census, and a
  **hand-maintained `implemented` flag**.

  Therefore **"102 special items (1 unimplemented)" counts items whose FLAG
  says unimplemented -- not items verified complete.** Nothing would notice a
  half-implemented item. `morning_star` is the candidate instance:
  `implemented: true`, `effects: [{"tag": "smash"}]`, `blocked_on: null`, and
  per the wiki its text is *"Can knock the locks off chests and trunks.
  **Tomorrow morning, gain 1 Star**"* -- the star half absent and unflagged.
  **Wiki-sourced and UNCONFIRMED by datamine or owner play; treat as a
  candidate, not an established bug.**

  **This is the same shape as #270 one level up.** Rooms got a fidelity audit;
  items got a registry check that answers "is this id known?" and never asks
  "does the model match the published text?". A hand-maintained completeness
  flag with no detector behind it is a liveness check wearing a different hat.

  **Other findings:** the reconstructed 0-49 partition table was **never
  persisted** -- only `southern_cross` and `draxus` appear anywhere in the
  repo, so the table exists solely as a prose assertion at
  `open_tasks.md:1157-1161` and must be re-derived from scratch. And
  `special_items.json:647` claims *"Spiral has no wiki page at all"*; it has
  one. The conclusion it supports (keep Spiral out of `spawn_rooms`) is still
  right, but the stated reason is false and would mislead a re-deriver.

  **Florealis is unbuildable today**: zero hits for `flower` anywhere in
  `src/`. In = a new subsystem; out = 10 of 11 with a recorded reason.

- **2026-08-13, THE CONSERVATORY: researched to datamined ground truth, and it
  is CORRUPTING `gear_wrench` 14.3% of the time. Four rulings outstanding.**

  Owner set the research priority: *"Go with whatever comes from the data mining
  followed by the wiki in that order"*, and offered a hypothesis -- *"I suspect
  it's uniform random irrespective of rarity."*

  **The hypothesis is SUPPORTED.** The Conservatory page's `DataMinedBox` says
  *"the table presents three random rooms that passed the filters"*, with **no
  rarity term anywhere** -- unlike the normal draft (*"the game first chooses a
  rarity and then selects a room of that rarity"*) and matching the Duct Draw
  shape, which the wiki states outright as *"uniformly at random from the list
  (ignoring rarity and other modifiers)"*.

  **Two honest qualifications, recorded rather than smoothed over:** the
  datamine never uses the word "uniform", and it never says whether the three
  are drawn **with or without replacement**. The bug clause -- *"this list
  contains bugged entries that, if they appear, appear like one of the other
  entries already present"* -- implies the **fallback** path is not
  de-duplicated. Treat "uniform, without replacement" as the reading and
  "with replacement" as unverified.

  **The datamined filter chain, which belongs in DATA when this is built:** from
  86 rooms, drop any whose rarity has been changed **by any method** (so a
  wrenched room disappears from future offers); Studio Additions and Found
  Floorplans must have been added or found; Gift Shop drops if never drafted;
  Freezer, Pump Room and Dovecote always drop. **If fewer than 3 survive, it
  presents three from the full 86 ignoring every filter.**

  **The sim's matching concept lands at 85, not 86** -- `pool in {base,
  studio_addition}` = 95, minus the 16 named unchangeable rooms = 85. The 8
  outer rooms are already excluded. **The 1-room gap is unresolved** and was not
  worth chasing. *"Interior room" is the owner's term, not the game's*: the
  game-side concept is "rooms whose rarity can be changed", and 16 interior
  rooms are excluded, so interior alone is not the criterion.

  **The rarity change is ALL three, not any one** -- *"the player may interact
  with the drawing board to change the rarity of each one"*. **Surfaced as a
  possible conflict with the owner's "any of the three"**, which may be phrasing.

  **Three further datamined rules, each load-bearing:**
  - *"Clicking a floorplan, even without actually changing the rarity, counts as
    changing the rarity."* A no-op click consumes the room permanently.
  - It writes **the same permanent slot as the Gear Wrench**: *"If a room's
    rarity is ever set using the Conservatory and/or Gear Wrench (even if the
    rarity was not changed from the default), that room's Dynamic Rarity is
    permanently ignored."*
  - **Reset does not un-consume.** Resetting via the Room Directory *"acts like
    setting the rarity back to the base rarity, rather than as if the rarity was
    never set in the first place"* -- the room stays filtered out.

  **Frequency is unsourced.** Neither source says once per day, once per
  Conservatory, or unlimited. The likely reading is unlimited re-interaction with
  a shrinking offer list, but that is inference.

  ### The live bug the research found, fixed ahead of any remodel

  **`reroll_random_rarities` moved cards between rarity decks without writing
  `state.dynamic_rarity`** -- the dict every other deck helper consults. So a
  later `set_dynamic_rarity` looked in the **wrong bucket, found nothing, and
  silently dropped the move.** Reproduced at seed 0: `secret_passage` moved 2->0
  while `dynamic_rarity` stayed `{}`; the follow-up placed **0 copies** in the
  target while one stayed stuck.

  **It corrupts `gear_wrench`**: over 300 seeds the reroll moved a Mechanical
  Room in **43 (14.3%)**. A player who drafts the Conservatory then wrenches an
  affected room records a permanent rarity while the card sits elsewhere.

  **THE CONSERVATORY IS UNDRAFTABLE, and that is what masked it.** Its record has
  `"rarity": null`, and `eligible_pool` drops rarity-less rooms **before** it
  checks the pool, so it can never enter `build_decks`; its forced-draw entry is
  explicitly unbuilt. **The entire effect is dead code** -- and goes live the
  moment anyone makes the room reachable.

  **All six existing Conservatory tests were self-consistent with the buggy
  model.** They pin card conservation, deck perturbation, determinism and
  substream consumption; **none asserted anything about `dynamic_rarity`
  bookkeeping**, so the bug was invisible to them. Fixed by routing each move
  through `set_dynamic_rarity`, which already maintains it -- one implementation
  rather than two, same draw count and label.

  **Generalisable: dead code can still be a hazard, and being unreachable is not
  the same as being harmless.** This sat behind a `"rarity": null` that nobody had
  connected to it, and would have gone live silently.

  ### Rulings outstanding before any remodel
  1. **Is the Conservatory in scope at all, given it is undraftable?** Making it
     reachable needs its 15% forced draw and the Found Floorplan gate, neither of
     which exists. The remodel buys nothing until that lands.
  2. **Does "a click counts even with no change" get modelled?** It is the
     difference between reusing `permanent_rarity` and adding a second
     save-scoped set -- because `set_wrench_rarity` **pops** the entry when the
     pick equals the natal rarity, so `permanent_rarity` alone cannot express
     "consumed but unchanged".
  3. **"Any of the three" (owner) vs "all three" (wiki and datamine).**
  4. **Constellations: auto-activate, or model the per-constellation choice?**
     Auto halves the `telescope` constellation arm and removes an action-width
     change; the game explicitly makes activation optional.

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
