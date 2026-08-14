# Open tasks

Features the project owner identified while reviewing the special-items PR stack
(2026-07-26). These are NOT in `docs/plan.md`'s delivered set — each needs its own
design pass. Ordered roughly by how self-contained they are.

The file reads in three parts: **open tasks** (numbered sections), then the
**open owner questions** in task 23, then the **decisions log** — the history,
which is always the last section. Lessons about *how to work* are not here; they
are in [`process.md`](process.md).

## How to cite this file

**The decisions log records what was true when each entry was written; the
topic docs record what is true now.** Readers have repeatedly taken the first
for the second, and four false claims propagated out of this file in a single
day before a fifth was caught.

So a cross-reference in `src/`, `tests/`, `tools/`, `data/` or another doc must
point at **the doc that owns the rule**, never at the log. `open_tasks.md` may
be cited for exactly two things:

- a **numbered open task**, cited by number — `open_tasks.md` task 11;
- an **open owner question**, cited as task 23's item — `open_tasks.md` §23 A.

Anything else — a mechanic, a magnitude, a ruling, a doctrine, a deliberate
divergence — cites the topic doc that owns it. If nothing owns it yet, that is
the signal to create or extend a topic doc, not to cite the log. In particular
**do not write "owner ruling, see the decisions log"**: state the rule in the
topic doc and cite that, because the reason a rule holds is not the same fact
as who said it.

Current owners:
[`scoping-and-carryover.md`](scoping-and-carryover.md) (persistence scope and
the carry channels), [`doctrine.md`](doctrine.md) (sources of truth,
assumed-solved, trophies, the acceptance bar), [`luck.md`](luck.md),
[`locking.md`](locking.md), [`rewards.md`](rewards.md),
[`foundation-design.md`](foundation-design.md), [`areas.md`](areas.md),
[`drafting.md`](drafting.md), [`special-items-design.md`](special-items-design.md),
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
| Locker Room | on draft | basic keys | the estate minus 17 named rooms; can seed itself |
| Conference Room | passive, while placed | — | absorbs others' spreads, **altering them** |
| Office | **player action, once/day** | money | throughout the house |
| Tomb | on other rooms' drafts | 5 gold per Dead End | into the Tomb itself (ALREADY MODELED) |

**Correction 1 — the Office is not an on-draft effect.** It is a player-triggered,
once-per-day terminal action ("Spread Gold in Estate"), gated behind walking to the
Office and operating its terminal — the same terminal concept as the shipped
`disk_reader` flag. That makes it an **action-space change**, so per this file's own
standing rule it belongs bundled with a retrain, not with the on-draft spreaders. Do
not conflate it with the Office *safe* (+1 gem), which is task 3 and already shipped.

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
   last is outside the grid — gate it behind task 4). Insert requires standing in a
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

## 3. Room safes — permanent +1 gem

The sim assumes the player solves every puzzle in a room they enter. Several rooms
contain a safe holding gems daily, so those rooms should simply grant **+1 gem** on
entry, every day: **Drawing Room, Shelter, Boudoir, Study, Office, Underground**.

Implementation is small: add a `grant` effect (`resource: gems, amount: 1`) to each
room's record in `data/rooms.json` AND the matching `tools/ingest_sheet.py` override
so a re-ingest preserves it. Verify each room id exists (the "Underground" may be an
area rather than a room record — check before authoring). Worth confirming whether
the safe gem is truly daily and per-room-instance.

## 4. Connectivity graph for the outside areas

**The graph is specified and owner-reviewed: [`areas.md`](areas.md), with the
Graphviz source in [`areas.dot`](areas.dot).** 38 nodes, 75 directed edges, one
step per edge, plus the stateful mechanisms it implies — two position-tracked
elevators, four persistent torches, Pump Room water level, Rotating Gear
position. `data/areas.json`, the per-area travel action set and the observation
change are all delivered; the stateful mechanisms are not (see the stub-gate
decision below).

**No longer a prerequisite for measuring upgrades.** It was scheduled ahead of the
retrain on the strength of a projected 42x lift to Cloister of Orinda's offer rate
from unlocking the Catacombs. That projection came from synthetic contexts and did
not survive measurement: under real play the realized lift is **1.11x (z = 1.06,
not significant)** and the always-unlocked ceiling is **1.91x**. The Catacombs gate
also turned out to need only the Tomb, not this graph.

What task 4 still uniquely supplies: **Blackbridge Grotto**, the fifth disk-reader
terminal and the one modelled terminal with no room record; and the currently
inert `microchip`, `sanctum_key` and `key_of_aries` items. (The two off-grid
Upgrade Disks it used to list, The Foundation and the Abandoned Mine, are no
longer unique to this task — the Sanctum-route PR reached both.) It also
changes the action space, so it is still worth bundling with a retrain rather
than paying for two.

See [`upgrade-value-measurement.md`](upgrade-value-measurement.md) for the measured
numbers and why Cloister's Unusual rarity — not the gate — is the real bottleneck.

### Implementation plan (2026-07-27)

`outer_loc` was read at 40+ sites across `game.py`, `env/actions.py`, `env/obs.py`,
`engine/shops.py`, `engine/special_items.py` and `cli/play.py`, and doubled as a
phase flag for the action masker — so it could not be widened in place. Task 4
was delivered as two PRs, each independently green:

1. **The graph as data plus a pure library.** `src/blueprince_sim/data/areas.json`
   (nodes, directed edges, gates as declarative string tags in the
   `draft_conditions` idiom) plus `engine/areas.py` (frozen dataclasses, gate
   evaluation, BFS pathfinding at 1 step per edge) and `validate_data.py`
   referential checks. Nothing calls it, so there is zero behaviour change.
2. **Engine adoption and the env layer, together.** `GameState.area` replaces
   `outer_loc`; BFS derives the route costs, so the three `GameConfig` outer step
   costs are deleted rather than kept as a second source of truth; per-area
   travel actions replace `RETURN_EH_ACTION` / `RETURN_GARAGE_ACTION` /
   `ENTER_OUTER_ACTION`; and `player_area` joins the observation so position
   stops being a single grid-only `Discrete(45)` field.

Several currently-inert items unblock with this: microchips, Power Hammer wall
breaks, the Sanctum keys.

## 5. Throttle the training terminal output — DONE

Delivered as `--dashboard-every FRACTION` on `blueprince-train` (default 0.05 =
one line in 20; 0 disables the per-episode lines). Only the per-episode chain
note is throttled -- checkpoint writes, the stop signal, the resume banner and
the final summary are lifecycle events and stay unthrottled, and
`dashboard.deactivate()` still renders a true final frame.

**Live remainder:** the throughput win is assumed, not quantified. Worth a
timed before/after on a real run.

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

Blocked on task 4 (outside-area movement graph). Eight candlesticks stand in the
Abandoned Mine's circular room; lighting them all with an ignition tool (Torch or
Burning Glass) permanently sinks the floor into a stairway down to **the
Precipice**. So it is a graph edge, not just a reward — add it when the area graph
lands, as a permanent `abandoned_mine -> precipice` edge.

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
way task 3's safes are.

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
task 4's sequencing.

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

## 13. Bound the Observatory's in-memory replay index — DONE

`web/server.py`'s `Observatory._records` is a `(offset, length)` index into
`replays.jsonl` plus the metadata `runs_index()` returns, with `run_frames()`
seeking and parsing a single line on demand, and an `OrderedDict` capped at
`--max-runs` (default 20000). It replaced a full-record dict measured at 3,089
bytes per episode -- 5.24x the on-disk size, ~31 GB at 10M episodes -- which
was the real blocker on raising `--record-sample-rate`.

**Two live residuals, stated rather than glossed:**

- **The best-of-window dict is NOT capped.** `why: "top_window"` records are
  held separately and never evicted, growing at one per `--record-top-every`
  episodes (trainer default 1000), so ~10k entries at 10M episodes.
  `--record-top-every 1` would defeat the cap entirely.
- **`/api/runs` has no pagination** and `refreshRuns()` builds the whole list
  into `innerHTML`. The cap bounds that payload as a side effect; raise
  `--max-runs` far above the default and the browser becomes the next limit,
  not the server.

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
- **Still genuinely unsourced** (no modelled activation source): the five `king_*`
  tags, `electromagnet`, `chronograph`, `adjacent_duct`, `adjacent_powered`, and
  the two constellations' activation chains.

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

## 16. Sweep comments that re-litigate past behaviour -- DONE (2026-08-14)

Closed by #273-#276: 69 candidates found by a read-only discovery pass, 67
edited, 2 ruled KEEP with git evidence. What the sweep found, and the two
rulings it could not make mechanically, are in the 2026-08-14 decisions-log
entry. The standing rule -- a comment says what the code does, never what it
used to do -- and the lessons about rotting counts are in
[`process.md`](process.md).

**One remainder, reported rather than silently left:** `tests/luck_utils.py`'s
module docstring still phrases a live constraint historically ("the pre-ladder
idiom, no longer guarantees..."). Borderline: the constraint is real and
current, only the framing is historical.

**Two exemptions that must survive any future sweep.** `docs/` is exempt --
this file exists to record history. And a comment explaining a non-obvious
constraint the code must still honour is describing the present even when it
sounds historical: that `rooms.json` round-trips at 1-space indent, or that
`_CARRYOVER_KEYS` is sorted because Python randomises string hashing per
process.

## 17. Room behaviour: registry migration

Opened 2026-08-10 from the architecture memo (see the decisions log entry of the
same date for the reasoning and the measurements). Runs alongside task 15 rather
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

Opened 2026-08-10 on an owner ruling (see the decisions log entry of the same
date). **Started; the invariant is now measured rather than estimated.**

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

The motivating link to task 16's neighbour work: `implemented: false` in
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
| 7 | Shrink both allowlists; ~~delete `implemented`/`blocked_on`~~ | S | Low | **allowlist split DONE in #206. The flag deletion is CANCELLED -- its premise does not hold; see the 2026-08-12 closing entry.** |

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
  behind the 8 doors is unmodeled. Overlaps heavily with task 4.

## 23. OPEN OWNER QUESTIONS -- re-verified and re-consolidated (2026-08-14)

A pass re-checked every question this section previously carried against the
code, the data, and the decisions log. Almost all of them were already
answered -- by shipped code, by an owner ruling recorded in the log, or both --
and had simply never been removed from this list. **Two remain.**

### A. Florealis: in or out? (constellations)

It is the only base-set constellation with no primitive whatsoever -- **zero
hits for `flower` in `src/`**. In = a new subsystem; out = 10 of 11 with a
recorded reason. Not separately ruled when the other constellation questions
were decided (sum-partition vs. threshold; auto-activate vs. per-constellation
choice) -- still open if the Telescope/constellation work reaches it.

### B. Does the Greenhouse move Secret Passage from the 5% group to the 3% group?

The wiki: Secret Passage sits in the Patio priority-draw group (5%, boosted to
50% while a Greenhouse is placed) only until a Greenhouse is drafted, then
moves to the Garage/Classroom group (3%). `priority_draws.json`'s own note
explains precisely why this isn't modelled: it needs a room excluded from one
priority-draw entry's list exactly when it becomes included in another's, and
the condition vocabulary (`_active_conditions` / entry-level `condition`) only
supports gating a whole entry on or off, with no negation or per-room
membership primitive. Secret Passage stays in the 5% group unconditionally
pending that primitive.

## Decisions log

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

- **2026-08-14, TRADE OFFERS: a LIVE DEFECT, plus a note that was true when
  written and had the data changed under it.**

  **The defect.** The wiki states, twice: *each Sanctum Key is considered the
  same item, so having multiple only produces one trade offer* -- and the same
  rule for Upgrade Disks. **The sim emits one offer per inventory id**
  (`shops.py::trade_offers`), so eight held Sanctum Keys emit **eight** offers
  and sixteen Upgrade Disk ids can emit sixteen. This rule appears nowhere in
  `src/` or `docs/`.

  **It breaches a cap that truncates silently.** `env/actions.py` masks only
  `TRADE_BASE..+8`; beyond slot 7 an offer is never legal and never encoded --
  no assertion, no log. Measured: holding all **12** tier-5 items yields 12
  offers and leaves four **unreachable**. Because offers sort alphabetically,
  the truncated ones include `sanctum_key_room_46` itself, and an ordinary
  tier-2 `shovel` gets crowded off the menu by a wall of Sanctum Keys.

  **A mirror of the same identity bug, in the opposite direction:** the wiki
  says three Microchips give three distinct offers; `trade_offers` emits one
  regardless of count. `microchip` is the only item with `unique: false`.

  **How it happened, and this is the part worth keeping.** The
  `sanctum_key_room_46` note claimed the other seven were `tier: null`, and
  gave the reason: making all eight tradeable *would breach the 8-offer cap*.
  **That note was TRUE when written** (2026-08-09). **#213 then set all eight
  to tier 5** (2026-08-12) -- deliberately, wiki-driven, and better-informed
  about tiers -- rewriting `shops.json`, `shops.py` and three tests **without
  touching the note it invalidated**. So the note's prophecy came true and was
  ignored, because the person who made it true never read it.

  **Not "the note decayed OR the data drifted" -- both, in that order.** A
  note that was always wrong is a documentation error. **A guard that was
  removed without reading why it was there is a different failure**, and the
  only way to tell them apart is `git log -S`.

  **A second comment died in the same 29 minutes.** `shops.py`'s
  `_next_receivable` said its all-give-only fallback *does not occur for any
  tier in the current data* -- written by #212 at 15:08, falsified by #213 at
  15:37. Tier 5 has **0 receivable ids of 12**, so that fallback now fires on
  every tier-5 roll. Corrected here.

  **Also corrected here:** the `sanctum_key_room_46` note, and
  `special-items-design.md`'s claim that `sanctum_key`, `microchip` and
  `file_cabinet_key` are all non-unique -- only `microchip` is, and the
  `sanctum_key` id no longer exists.

  **Two owner questions, separable:**
  1. **Adopt the wiki's same-item collapse** for Sanctum Keys and Upgrade
     Disks? A trade-offer identity key (game item, not sim id) applied in
     `trade_offers` before the sort takes the tier-5 worst case from 12 to 5.
     **No observation-width change, so no retrain trigger.** The counter-case:
     the per-source ids exist to gate respawn independently, and collapsing
     them for trading is a second identity notion.
  2. **Raise `TRADE_OFFER_ROWS`/`TRADE_BASE` past 8?** Already recorded as an
     obs-width change and therefore a retrain trigger. **Answering (1) yes
     makes this stop being urgent; answering no forces it.**

  **Provenance, plainly:** the repo holds **no datamined trading data**.
  `tools/raw/` has a room table and a wiki-locations snapshot, neither
  mentioning tiers. Every tier claim traces to the wiki's own DataMinedBox --
  **do not describe them as repo-datamined.**

- **2026-08-14, RETRACTION. THE BASEMENT KEY IS ALREADY BUILT. Three claims in
  the entry below are FALSE, and one of them originated in this file.**

  A scoping pass verified by **execution**, not reading:

  ```
  grid[42] = antechamber
  inventory before: {'royal_scepter': 1}
  inventory after antechamber entry: {'royal_scepter': 1, 'basement_key': 1}
  day2 starting_items: ['basement_key']
  ```

  `special_items.json:803-825` has carried `guaranteed_in: ["antechamber"]`,
  `persistence: "permanent"`, `implemented: true` since commit `3250263`, the
  original special-items system. **Cost to build: 0 lines. Nothing to do.**

  **FALSE CLAIM 1 -- "the wiki lists the Spiral as `basement_key`'s only
  location" (this file, and repeated into the rulings entry below).** The wiki
  lists **three** sources and puts **the Antechamber FIRST**. **There was never
  an owner-vs-wiki conflict.** The owner's ground truth and the wiki agree, and
  have always agreed. The "owner play overrides the wiki" framing was applied
  to a conflict that did not exist. **This claim originated here and
  propagated into a brief, a PR body, and a ruling record before anyone
  checked it against the page.**

  **FALSE CLAIM 2 -- "a 17th `_CARRYOVER_KEYS` member would give save-scoped
  permanence."** `_CARRYOVER_KEYS` is **ATTEMPT-scoped, not save-scoped** --
  `multiday.py:503` clears `carried_flags` at the wrap. **There is no
  save-scoped bool channel in this codebase at all**; creating one would be a
  new mechanism, not an addition. The permanence is already carried by a
  **third channel neither option named**: `persistence: "permanent"` ->
  `end_of_day_carry()` -> `carryover()["starting_items"]` ->
  `DayChain.carried_items`. **`_CARRYOVER_KEYS` stays 16.**

  **FALSE CLAIM 3 -- "the Spiral" is a place.** It is the **Spiral of Stars**,
  a **100-star secret constellation**, not a room and not an area node. The
  "11 items" figure is its stage-43/46 payload list (12 named, 11 modelled --
  the Wind-up Key is deliberately unmodelled), never a location list. **No item
  ever had the Spiral as its only route** -- every one of the twelve has a
  shop, spawn, or `guaranteed_in` source. The conclusion drawn earlier was
  right; **the stated cause was wrong**, and crediting the owner's ruling with
  shrinking the question was also wrong.

  **The one genuine residual, honestly stated:** `carried_items` **is** cleared
  at the 200-day attempt wrap, so the sim is narrower than *"across an entire
  save"* -- on day 1 of a new attempt the basement doors re-lock until the
  agent walks back to the Antechamber. Closing it means a **save-scoped set**
  (`basement_doors_open`, built like `sigil_doors_open`), **not a bool** --
  the owner said *"open **a** basement door"*, singular, and there are three.
  **~40-60 lines + an obs key + a retrain. Recommendation: do not build it**;
  the divergence window is a few days at the start of each attempt.

  **Lesson, and it is the one this repo keeps re-learning:** a false claim in
  `open_tasks.md` is not inert. This one was written once, then inherited by a
  research brief, a PR body, and a ruling entry -- each restatement making it
  look better-established -- and it was only caught because a scoping pass
  **ran the code instead of reading the file**. **Verify a claim against the
  source before building a brief on it, especially a claim this file asserts
  about the outside world.**

  **Revised plan for the three scoped mechanics:**
  1. **Basement Key -- DO NOT BUILD.** Already correct.
  2. **Dartboard -- BUILD, but GATED.** ~60-75 lines, no action-space change,
     a fully-specified day-banded wiki reward table, and it restores real
     Keycard access that #289 removed through the wrong channel (the *channel*
     was invented; the *fact* is real -- the Keycard genuinely is obtainable in
     the Billiard Room, via the Dartboard). **Blocked on: how often can it be
     solved -- per entry, per day, or unlimited?** Unlimited re-entry makes the
     Billiard Room a Silver Key farm at 30% a solve, the same farming-incentive
     class already flagged for the Vestibule.
  3. **Spiral of Stars -- DEFER with a recorded reason.** It sits on top of the
     unbuilt constellation subsystem (~1000-1450 lines) and adds ~400-700 more,
     introducing per-resource lockouts and a forced day-end that have no
     precedent in the engine. Gated behind **100 stars**, plus 43 further
     sightings before its first item stage. It grants nothing not already
     obtainable. **Fold it into the constellation entry as its last stage,
     not a peer item.**

  **Two more decayed notes found in the same pass:** `special_items.json:9`
  claims `master_key` is `guaranteed_in: [showroom]` -- it is `[]` today, a
  Showroom purchase; and the false "Spiral has no wiki page at all" is at
  `special_items.json:648`, **not :647** as this file said -- the wrong line
  number propagated too.

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

- **2026-08-14, OWNER RULINGS x4. The governing principle, in the owner's
  words: "multiple sources of truth means we have none."**

  **A. `effects` IS VESTIGIAL -- and the vestigial configuration is to be
  DELETED.** *"Rely upon the modules/registries and delete the vestigial
  configuration so we stop having this conversation."* This goes further than
  the recommendation put to the owner (which was to make `effects` normative):
  the ruling is not to define the ambiguous field but to **remove it where it
  is dead**. Behaviour is owned by `engine/effects`' three registries -- tag
  lookups (`effect()`/`_has_item_effect()`), `item_provides`/`ItemCapability`,
  and `item_hook`/`ItemHook`.
  **Scope, to be established by AST across ALL THREE registries, not by grep:**
  delete only tags with **zero** readers. A tag whose params are still read is
  live. **7 of 28 tags** were measured inert; re-verify before deleting, since
  a prior scan got tag liveness wrong **in both directions**.
  **Note the tension to respect:** an item may be fully implemented with
  `"effects": []` (Coupon Book, Hall Pass, Silver Spoon), and `lucky_purse` is
  **half data, half Python** -- its `luck_bonus` tag is live while its
  coin-doubling lives in `effects/items/lucky_purse.py`. Deleting a live tag
  would break it.

  **B. A partial gap keeps `implemented: true`, and REQUIRES
  `meta.simplification`.** The third state, reusing vocabulary 7 records
  already carry. `implemented` keeps meaning *reachable and functional*; the
  simplification field names what is missing and makes the gap
  machine-detectable rather than prose-only. **This defines the item audit's
  flagging rule, which had none.**

  **C. A disclosure MUST live on the record it concerns.** A pointer elsewhere
  does not count. Four cases are to be migrated: `power_hammer`'s Freezer gap
  (on `upgrade_disk_freezer`'s record), `secret_garden_key`'s simplification
  (in `locks.json`), plus `torch` and `knights_shield`. **A disclosure a
  reader cannot reach is not a disclosure.**

  **D. SEPARATE "purchasable" FROM "obtainable" -- do not interpret the
  ambiguity, eliminate it.** The question put to the owner was whether the
  wiki's `Locations` field means *spawns here* or *is obtainable here*. The
  answer rejects the frame: **model the two concepts as separate fields so the
  ambiguity never has to be re-litigated.** `spawn_rooms` means loose-on-the-
  floor only; purchasability is already modelled in `shops.json`, and the
  24 Commissary/Locksmith/Lost & Found/Trading Post entries are *obtainable*,
  not spawns -- so they stay out of `spawn_rooms` regardless. **Sweep (b)+(c)
  is 121 entries, not 145.**

  **Consequence for `items.json`, raised by the owner as "why do we need it
  when we have a registry":** the registry answers *which code runs*;
  `items.json` answers *what numbers the rules use* -- they are different axes,
  and deleting the tables would move the luck ladder into Python constants,
  which doctrine forbids. **But the file is doing three jobs and one is the
  disease being treated:**
  1. published game tables with no other home (`item_ladder`,
     `never_roll_rooms`, `count_transforms`, `dowsing_rod`, `coins`, `food`);
  2. **sim tuning that is not game data at all** -- `item_values` /
     `special_item_values`, which the file's own comment admits: *"Relative
     resource values used by shaped rewards and greedy policies; not game
     data."* A filing error, not a duplication;
  3. **one genuine second source of truth, and it is dead** --
     `luck.rabbits_foot_bonus: 3`, unread since #274; the live value is
     `special_items.json`'s `luck_bonus` param.
  **Actions: delete `rabbits_foot_bonus`; move `item_values` /
  `special_item_values` out to a tuning file**, leaving `items.json` holding
  published game tables only.

  **The test to apply, generalised: "could two places disagree about this
  fact?"** For `effects` and `rabbits_foot_bonus`, yes -- those are the
  disease. For the luck ladder, no -- nothing else claims to hold it.

- **2026-08-14, SPAWN TABLES measured across all 102 items. 26 of 28 diverge
  -- but it is DISTRIBUTION, not reachability, and that is measured, not
  argued.**

  **Denominator first: only 33 of 102 items carry a spawn table**, 28 of them
  comparable against a wiki `Locations` field. **26 diverge; 2 are clean**
  (`coupon_book`, `telescope`). The earlier "3 of 5" understated it.

  **All 33 tables were authored in a single commit** (`3250263`, 2026-07-25).
  One pass, one source -- which is the real evidence for "systemic", stronger
  than any hit rate.

  **Direction A (wiki lists, sim omits): 145 pairs -- but 121 net.** All 145
  name rooms that **exist in `rooms.json`**; none are unmodelled rooms. **24
  are false positives already modelled through another channel** -- 8
  Commissary entries matching `shops.json` commissary stock exactly, 5
  Locksmith, 7 Lost & Found, 4 Trading Post. **Do not add those**: they would
  double-count and dilute pools that are correct today.

  **Direction B (sim has, wiki does not) -- NOBODY HAD CHECKED THIS, and it is
  where the actual falsehoods are.** 6 pairs. `car_keys`/`garage` is
  **contradicted outright** (the Garage page: *"does not usually contain
  special items lying around"*) -- the digest recorded the *use* location as
  the spawn location. `compass`/`mail_room` and `sleeping_mask`/`mail_room`
  are **double-counts** of `mail_packages`. `repellent`/`spare_bedroom__ix131`
  and `lunch_box`/`dining_room` are **misfiled** -- both are *guaranteed*, so
  they belong in `guaranteed_in`. `keycard`/`billiard_room` is not on the
  wiki's list and is likely the **Dartboard** conflated with its room.

  **DOES IT MATTER -- measured, not asserted.** `spawn_rooms` inverts into
  `spawn_pool_by_room`, consumed at exactly one site (`items.py:658` ->
  `roll_special_spawn`): per extra-item slot, roll a **25%** `special_share`,
  then pick **uniformly** from the room's pool. So **the table controls WHICH
  item you get, never HOW MANY.**

  A/B over 3000 seeded days per variant (data copied to scratch, repo
  untouched): **total special finds per 1000 days 1550 -> 1550, unchanged.**
  Per-item rates move hard: `car_keys` **6.6x**, `vault_key_149` **0.40x**,
  `salt_shaker` 0.57x, `running_shoes` 0.67x. Adding a room takes mass *from*
  the other items in that room -- total flow is conserved.

  **No item is currently unobtainable because its table is short.** Every
  grant channel was enumerated for all 102; every diverging item has another
  path.

  **Corrections to the orchestrator, all mine to own:**
  - **"`magnifying_glass` is the sole input to `burning_glass`" is FALSE.** The
    recipe is `metal_detector + magnifying_glass`. I paraphrased #286's note
    ("the recipe is the burning glass's only source") into a different claim.
    **And the chain is not spawn-gated at all** -- the Commissary sells the
    glass for 4g. Its table is load-bearing for *rate*, not *access*.
  - The `_notes[4]` digest admission **is itself stale**: it says the wiki
    lists 15 rooms for Car Keys; today it lists 21+2.
  - **The raw datamine has no item-spawn data** (`tfmurphy_room_table.md` is a
    17-column *room* table), so datamine-outranks-wiki does not bite here and
    the wiki is the best available authority. Say so rather than implying
    otherwise.

  **`meta.confidence` INVERTS.** Items labelled `wiki` are 59% complete; the
  two labelled **`datamined`** -- the highest tier -- are **49%**, the worst
  band. **The label is not tracking reality**, which softens the provenance
  ordering the whole repo leans on. Added as an owner question.

  **The one real cluster is bimodal, not graded:** 9 items have
  `spawn_rooms_high_luck` exactly right; **7 have the entire tier empty**
  while the wiki gives them `!` entries. That reads as two authoring passes,
  one of which dropped the `!` prefix -- 30 of the 121.

  **Ruling: sweep in three PRs, reverse direction FIRST**, because that is
  where the sim asserts things the source denies:
  (a) the **6 wrong/misfiled** entries -- not gated, doing now;
  (b) the **30 missing high-luck** entries -- one tier, one clear cause;
  (c) the **91 remaining** normal-tier entries.
  **(b) and (c) are GATED** on owner question 1 below, which decides whether
  the exclusion set is 24 or 0.

  **Regression guard, when (b)/(c) land:** commit
  `tools/raw/wiki_item_locations.tsv` -- verbatim `|Locations=` per item, with
  fetch date and URL -- and have `validate_data.py` diff every table against
  it, honouring `!` as the high-luck tier. **Each exemption must name the file
  and channel that models it instead, and a test must remove each exemption
  and assert the checker then flags that pair** -- necessity, not liveness.
  **Honest limit to record with it:** the snapshot pins the wiki as of the
  fetch date, so it catches sim drift and never wiki drift. Refreshing it must
  be a deliberate act with a visible diff.

  **Six new owner questions**, the first of which gates (b) and (c):
  1. **Does the wiki's `Locations` field mean "spawns on the floor here" or
     "is obtainable here"?** The 8-for-8 match between Commissary-listed items
     and Commissary shop stock says the latter. **If owner play says items also
     lie on the Commissary floor, the sweep is 145, not 121.**
  2. **Should `_notes[4]`'s digest be cited as a source at all?** It was wrong
     about the count and its conclusion is contradicted by the Garage page. If
     the digest is unreliable for locations, other fields sourced from it
     deserve the same suspicion.
  3. **The Spiral is unmodelled and appears as a location for 11 items** --
     including `basement_key`, where it is the **only** wiki location. Bigger
     than everything measured here. In scope?
  4. **The Dartboard is unmodelled** and is the likely origin of the invented
     `keycard/billiard_room` entry. Model it, or defer with a reason?
  5. **Does `meta.confidence` need a repo-wide audit?** See the inversion above.
  6. **Is a retrain owed?** `baseline-ep8275991` was trained against today's
     tables; a 6.6x shift in `car_keys` is a distribution shift for any live
     checkpoint.

- **2026-08-14, THE "GEMS-IN-HAND RANK AXIS" QUEUE ENTRY WAS WRONG IN EVERY
  PARTICULAR -- and a real engine defect was underneath it.**

  The entry read: *"Free/Gem landed; day-1 still shows ~5% from `forced=True`
  priority draws, an orthogonal mechanism."* **All three claims are false:**
  - **The rate is ~17.7%, not ~5%** -- wiki Slot 3, on rounds the Free/Gem step
    ruled a **Free Draw**, day 1, 2000 episodes / 8542 options,
    episode-clustered bootstrap 95% CI **16.88-18.44%**.
  - **It is not a day-1 phenomenon.** Day 20 measures **17.57%**. The mechanism
    fires identically every day.
  - **"Orthogonal" was the substantive error.** Priority draws are **not**
    independent of the Free/Gem axis. The published procedure makes a priority
    draw *"an additional filter on the floorplans"* applied within *"the
    (free/gem) group being worked in"* -- so during a Free Draw its pool is
    empty and attempt 1 must fall through. A gem room **cannot** appear.

  **THE DEFECT** (`engine/draft.py:604`): `_priority_draw(ctx, cell, entry_dir,
  exclude)` is called **without `is_gem`**, while the sibling calls on the next
  two lines -- `_deal_from_rarity` (:613) and `_apply_category_bias` (:614) --
  both thread it. `_priority_draw`'s candidate loop (:228-239) applies **no
  free/gem class filter** and force-inserts regardless of class. **It is the
  only draw path that ignores the class**; the calls bracketing it establish
  the convention it breaks. Verified directly, not relayed.

  **Every room in the priority groups is gem-cost** -- `commissary`,
  `observatory`, `patio`, `veranda`, `greenhouse`, `secret_passage`,
  `classroom` -- which is why the leak is near-total. The only free room in an
  always-active group is `morning_room`, gated behind draft conditions.

  **~1.1pp of the 17.7% is CORRECT and must survive the fix.** That is the
  **Garage**, arriving via `_forced_draw_garage`. Forced Draws precede the
  Free/Gem decision per the wiki's Special Draws section, so a Garage in a Free
  Draw is legitimate. **A fix that drives the rate to 0.00% is wrong.**

  **Why this matters at this size:** it is a direct leak in the gem economy a
  trained policy trades against -- the same class of error, and roughly the
  same magnitude, as the missing Free/Gem step #244 built from nothing.

  **Two measurement traps recorded so the next person does not repeat them:**
  **`GameConfig()` defaults to `day = 20`** (`config.py:16`), so any "day 1"
  measurement must pass `GameConfig(day=1)` explicitly; and **`state.pending`
  is `None` after `reset()`** -- the hand is dealt by `Game.open_door`, not by
  reset. The orchestrator's own attempt to measure this failed on both.

  **A LARGER FINDING, unrelated to the fix:** the wiki states the **Day 1
  opening draw is deterministically Bedroom, Closet, Hallway in that order**.
  The sim produced **292 distinct opening hands across 300 seeds, none of them
  that triple**, and no code or data for it exists anywhere. **Unimplemented.**
  It also means every "first hand of day 1" measurement -- including the one
  this queue entry rested on -- was measuring a hand that should not exist.

  **Provenance caution, re-derived:** `priority_draws.json`'s 5%/13%/3%
  constants cite a "TFMurphy decompiled sheet v1.3 constants block" that **is
  not in this repo**. `tools/raw/tfmurphy_room_table.md` is a 147-line **room**
  table with nothing on draw procedure. **Do not describe those chances as
  repo-datamined** -- they are not independently checkable here.

  **Ruling: close the queue entry as written** (its number, its day-1 scoping,
  and its "orthogonal, therefore not our problem" conclusion are all wrong) and
  replace it with the defect as measured. **Fix the minimal version only** --
  pass `is_gem` and filter the candidate loop. **Do NOT** rebuild
  `_priority_draw` into the wiki's per-floorplan acceptance-filter model or
  remove its `slot == 2` gate in the same PR; those are larger and carry their
  own owner questions, below.

  **Five new questions for the owner** (this pushes the open count to twelve;
  they need consolidating before the next batch):
  1. **Slot-3-only priority draws.** The sim gates `_priority_draw` on
     `slot == 2` and `docs/drafting.md:48` states it as fact, but **the wiki
     puts Priority Draws under Filters with no slot restriction** -- only
     *Forced* Draws are Slot-3-only. Deliberate simplification, or were the two
     mechanisms conflated?
  2. **Commissary beats Observatory 46:1.** `_priority_draw` returns the first
     draftable candidate in **list order**, so Commissary always wins its 13%
     group (2436 vs 0 over 20,000 first hands). Both have empty
     `draft_conditions`; the skew is pure list precedence. The wiki gives each
     floorplan an independent acceptance roll. Acceptable, or a second defect?
  3. **Build the Day 1 opening draw?** See above.
  4. **Two data gaps**: the wiki's 3% group is **{Garage, Classroom}** where
     the repo has `{classroom}` alone; and the wiki says the Greenhouse effect
     **moves Secret Passage from the 5% group to the 3%**, where the repo keeps
     it at 5% unconditionally.
  5. **`_priority_draw` never consumes its card** -- it returns a room without
     calling `deal_next`, so the room stays in its deck, while the wiki says a
     drawn floorplan *"gets added to the discard filter for future draws"*.

- **2026-08-14, ITEM FIDELITY AUDIT scoped. THE OBVIOUS DESIGN DOES NOT WORK,
  and `effects` cannot be trusted as its basis. Two rulings needed before
  building; two real gaps filed now so they are not lost.**

  **Correction to the orchestrator first:** this finding was **already written
  up** at `open_tasks.md:995-1023` and again at `:858-868`. It was scoped as if
  new. Read the log before commissioning research against it.

  **The decisive finding: a direct port of the room audit's KIND 2 would NOT
  catch `morning_star`** — the very item that motivated the work. Kind 2 fires
  only when text exists and there is *zero* modelling; `morning_star` carries
  `effects: [{"tag": "smash"}]`, so it passes. So do both other real gaps found.
  Kind 2's yield on items is near zero anyway: only 8 items have no route under
  an id-literal scan and **all 8 are false positives**, because the
  `upgrade_disk_*` family is modelled generically by id prefix
  (`Game.held_disk_ids`) — a route no literal scan can see.

  **Recommended instead: port KIND 1** (*identical modelling to a sibling but
  differing text ⇒ the differentiating step was never authored*). Across all 102
  items there are exactly three identical-`effects` groups; the rule flags
  **exactly two on day one** — `morning_star` (real) and `lucky_rabbits_foot`
  (false positive, whose text is the *poorer* one). **Two is small enough to act
  on with no triage phase.**

  **WHY `effects` CANNOT BE THE BASIS — the structural finding.** An AST scan
  (resolving module-level `NAME = "literal"` bindings, over the only functions
  that look a tag up on a `SpecialItem`) shows **7 of 28 item tags are never
  read as tags at all.** For six, the tag string merely coincides with the
  item's own id while the behaviour lives in a per-item module keyed on
  `ITEM_ID`; `effects/items/sledge_hammer.py:3-6` documents this outright.
  **So an item can be fully modelled with an inert tag, or partly modelled with
  a live one, and the `effects` array states neither.** The scoping agent's own
  first-pass string scan got this wrong **in both directions** before its AST
  scan corrected it — `smash` called dead (it is live), `treasure_map` called
  live (it is inert). **This kills the tags-vs-registries design outright**: it
  would flag six fully-modelled items and clear `morning_star`.

  **Sample and rate, measured.** 20 of 102 chosen by `sha256(id)` order — a rule
  fixed before looking, so it cannot be cherry-picked; `morning_star` was
  excluded and checked separately so it could not inflate the rate. **2/20
  hidden gaps, 6/20 counting disclosed ones.** Wilson 95% CI puts hidden gaps at
  **3-31 of 102**. The agent argued *against its own headline*: the draw
  included 8 items from the trivially-modelled `allowance_token_*` and
  `upgrade_disk_*` families, so among behaviourally complex items the rate is
  more like 20-30%, and the true figure is likely mid-range (~10-15).

  **TWO REAL HIDDEN GAPS, FILED NOW because no proposed detector catches them:**
  - **`power_hammer`** models **2 of ~7** breakable-wall sites (Weight Room
    lever; grounds/sealed_entrance/basement gate). Greenhouse, Secret Garden's
    third valve, Precipice and Crate Tunnel are unmodelled — zero hits for
    `valve`/`weathervane` in `src/`. `implemented: true`, `notes: null`.
  - **`ornate_compass`** applies no redraw gate (`Game._free_rotation_source`),
    while the wiki restricts it to the **first draw only**. `implemented: true`,
    undisclosed.
  Both need per-item review — the ~15-PR job, not the first PR.

  **Disclosure has a location problem.** `secret_garden_key`'s simplification is
  disclosed **in `locks.json`**, and `power_hammer`'s Freezer gap is disclosed on
  **`upgrade_disk_freezer`'s** record. Neither is reachable from the flagged
  item's own record, so a per-item audit cannot follow either.

  **NOT BUILT YET — deliberately.** The detector's flagging rule is undefined
  until two questions are ruled on (both added to the owner queue):
  1. **Does a partial gap invalidate `implemented: true`?** `morning_star`
     smashes correctly and misses a star. 7 items already use
     `meta.simplification`, so the vocabulary half-exists.
  2. **Is `effects` normative or vestigial?** Right now it is neither,
     consistently — **and that ambiguity is exactly what let `morning_star` look
     modelled.** Ruling it normative (every behaviour gets a tag; a tag with no
     reader is a hard failure) makes an item audit far cheaper forever. **Highest
     leverage available, and it costs nothing today.**

  **Exemptions get a necessity guard from day one** if this is built: re-run the
  detector with the exemption dict passed as `{}` and assert every exempted id
  still appears in the raw findings. **Cheaper here than for rooms** — the item
  detector is pure data and can run against the real file. Better still, at three
  groups and two flags **the day-one design may need no exemption at all.**

- **2026-08-14, TASK 16 COMPLETE (#273-#276). 69 candidates, and the
  composition mattered more than the count.**

  Run as **read-only discovery first, then three parallel edit lanes** —
  because this task's own recorded history is **false positives**: it was
  written naming three violations and **two did not exist**. Discovery quoted
  every candidate verbatim so it could be ruled on without opening the file.

  **Only ~40 of 69 were the history-narration the task was written to catch.
  Eight asserted facts that had become FALSE**, and those were the valuable
  ones — none of which any keyword grep would find, because their wording is
  entirely present-tense:
  - `engine/areas.py`'s module docstring called itself an unadopted "PR1
    deliverable... Nothing in the engine calls this yet." `game.py:11` imports
    `reachable` and calls it at four sites.
  - `web/server.py` said "three-tab SPA". There are four.
  - `test_behavioural_cloning.py` said `draft_counts` is "the only dict-typed
    `GameConfig` field"; `permanent_rarity` joined it with the Gear Wrench.
    **Checked whether that was load-bearing: it was not** -- `multiday.py`
    handles `permanent_rarity` at `:464-469` exactly as `:409-412` handles
    `draft_counts`. Comment rot, not a bug.
  - Two docstrings pinned behaviour "ahead of" migrations already landed.
  - `luck_utils.py` counted 76 `suppress_luck` sites; there are 82.

  **The rule that came out of it: a hardcoded count in a comment rots by
  construction.** Counts were **dropped, not corrected** -- and on review one
  agent's rewrite that replaced a rotting *count* with a rotting *enumeration*
  ("draft_counts, permanent_rarity") was corrected to name neither.

  **Two rulings made with git evidence rather than by pattern**, which is why
  they were routed through judgment instead of a sweep:
  - `env/rewards.py`'s "the old flat rate" **could** have been a legitimate
    counterfactual (a KEEP here). `git log -p` shows the code genuinely was
    `r -= 0.001` with no steps math. **History -> rewritten.**
  - `test_in_grid_disks.py`'s reference to the previous cap: `git log -p -S`
    confirms the space really was `Discrete(8)` with a `min(...,7)` clamp.
    Without it, testing exactly 8 disks looks arbitrary. **KEEP.**

  **The hard part was never the stripping.** These docstrings are load-bearing
  -- `tests/test_conventions.py` requires each to state its property *and why*
  -- and in several the history **was** the only justification. `test_vault.py`
  justified itself entirely by a deleted invented rule
  (`found >= 2 items -> luck -= 1`); the rewrite had to establish the real
  mechanism (`luck_penalty` grows only from high-luck `item_ladder` bands,
  never from a guaranteed grant) and never mention the deleted rule. Naive
  deletion would have left docstrings that **pass the convention test while
  explaining nothing** -- a green gate measuring the wrong thing, the same
  failure this repo keeps re-learning.

  **Boundary that had to be defended:** the largest false-positive class was
  **wiki-quoted game mechanics** ("will no longer have any effect") -- that
  describes Blue Prince, not this repo. ~60 near-misses were examined and
  cleared. `experiments.json:417` is left **unruled**: it cites real Patch
  1.04.5 game history but self-labels "(provenance only, not current
  behavior)" -- the shape of a violation wrapped around legitimate content.
  **Owner call; a sweep agent should not set that precedent.**

  **Found and NOT fixed, because it is not a comment problem:**
  `test_trading_fabrication.py:249-263` documents a "self-edge / untradeable
  that day" branch citing `t5_special_chance=50%`. Shipped `shops.json` sets
  it to **100** (50 is only the engine's fallback default), so **that branch
  is unreachable in shipped configuration** -- verified empirically across 200
  seeds, **0** of which hit it. The test still asserts something real and is
  not vacuous, but its `continue` is dead. **Test logic, not prose; queued
  separately.**

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
  Everything else is immediate or day-scoped. **`_CARRYOVER_KEYS` does not
  move** (it is bool-only, 16, and never has). Four of the eleven base
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

- **2026-08-14, CONTAINER DEBT: took the free win, DEFERRED the
  `provides_containers` refactor. And found the shape of a whole bug class.**

  Scoping said the room-id allowlist would shrink 8 -> 5 (AST-verified), at
  ~130 LOC, fixing **no divergence**. Its own confidence that this was worth
  spending *now* was **65%**. With two substantive items gated on owner
  rulings, a style-rule PR is the wrong trade -- **deferred, not rejected**.

  The scoping also **corrected the orchestrator**: the claim that the Break
  Room's payoff would repeat here conflated two different lists. The room-id
  allowlist is a **dumb string-literal scan with no registry awareness**; the
  audit-exemption list is the one that consults `registered_rooms()`. Those two
  payoffs are **decoupled** -- one shrink here, not two.

  **What shipped instead (#270), and why it is the more valuable half:**
  `_AUDIT_PYTHON_EXEMPT_IDS["mechanarium"]` was dead. Not *wrong* --
  **superseded**. `draft.py:729` still branches on `room.id == MECHANARIUM_ID`
  for the door mask, exactly as the entry's comment claimed, so the entry was
  truthful to its last day. The room simply later gained a `room_hook` that
  `find_divergences` can see for itself, and the exemption quietly stopped
  doing anything.

  **The generalisable lesson: a liveness check is not a necessity check.** The
  channel asked "is the code this entry names still there?" (yes, forever) and
  never asked "would the audit still flag this without me?" (no, for months).
  Any exemption, allowlist, or suppression list needs the *second* question, or
  it accretes entries that are individually defensible and collectively dead.
  The deferred channel already had that test; the Python channel now does too.
  Dict is 15 -> 14 entries; each of the 15 was tested by removal against real
  `rooms.json`, and `mechanarium` was the only dead one.

  **Known limit, recorded rather than hidden:** the new guard uses constructed
  records (as the whole file does, deliberately, to pin the rule and not
  today's finding count). It catches an exemption superseded by a `room_hook`
  -- how this one died -- but **not** one superseded by `effects` being
  authored into the room's data record. That second path was checked by hand
  across all 15 entries here and is **not yet automated**.

  Also removed: a `room_cells.get()` whose value was discarded by a callee that
  never reads the argument. `pull_west_lever` **keeps** the parameter -- it is
  the shared `LeverPullFn` signature, and `throne_room`/`weight_room` ignore it
  identically; only `great_hall` reads it.

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

- **2026-08-13, the last id-hardcoded fire site in `_terminate` is retired, and
  it made a false comment true rather than editing it.**

  `game.py` carried `if room.id == "break_room__ix11": st.break_room_keycard =
  True` **immediately after** `effects.fire(..., Hook.ON_DAY_END)` on the same
  room -- a hand-rolled day-end handler written before that hook had consumers.
  The Planetarium became the first (2026-08-13), proving the hook fires only for
  the room the player stands in at termination.

  **`tests/test_effect_hooks.py` had claimed all along** that these hooks exist
  *"so ... the Break Room no longer needs id-hardcoded fire sites in game.py"* --
  **false since it was written**. Making it true beats editing it.

  **A `room_hook`, not a tag, decided by looking**: `mark_visited` is registered
  at `ON_ENTER` and keys off first entry (wrong trigger); `grant` is a flat
  numeric delta, not a boolean pulse. Break Room's record has `effects: []` --
  there was never a tag to reuse.

  **The audit exemption was REMOVABLE, not repointable.**
  `_AUDIT_PYTHON_EXEMPT_IDS` existed because the audit cannot see hand-written
  Python -- but `find_divergences` already skips any id in the live `room_hook`
  registry, so once the handler registered the entry was dead. **A second stale
  reference** in `tests/test_room_id_allowlist.py` had to go with it. Two
  allowlist shrinks; `game.py` now contains **zero** occurrences of the id.

  **Ordering was checked, not assumed**: moving the write from after
  `effects.fire` to inside it only matters if something observes the flag in
  that window. Every read traced -- one at the start of a later day, one in
  `carryover()`, which the `DayChain` driver calls strictly **after**
  `_terminate` returns. Behaviourally invisible.

- **2026-08-13, FOUR MORE OWNER RULINGS: the `telescope` is unblocked, and the
  Patio simplification is confirmed deliberate.**

  1. **The Planetarium moves from `guaranteed_in` to `spawn_rooms`**, and the
     record gains the four locations it was missing (Her Ladyship's Spare Room,
     Lost & Found, Trading Post, Spiral). Today `guaranteed_in: ["planetarium"]`
     **mints a Telescope on every first Planetarium entry** -- verified firing --
     which no wiki text supports; the wiki gives a flat Locations list with no
     guarantee language. Harmless only because the item is inert; once it works
     it would have been a free tier-4 item on every visit.
  2. **Model the >=1-star pool gate.** The wiki: the Telescope *"is only present
     in the item pool if the player has at least 1 star at the start of the
     day."* Absent from both the record and the code. Uses the existing
     `state.special.gated_out` channel, keyed on **start-of-day** stars.
  3. **`planetarium_planets` is SAVE-SCOPED -- the third carve-out**, alongside
     `stars` and `main_course_bonus`. **`tests/test_carryover.py` pins that pair
     together deliberately so adding a third is an explicit edit**, which is
     exactly what that test is for. `_CARRYOVER_KEYS` does not move: it is a
     frozenset of bool fields and a running integer belongs in the separate
     channel.
  4. **The `file_cabinet_key` Patio dig was intended -- leave it.** Confirms the
     divergence is a deliberate owner simplification rather than a slip for the
     drawer name. **This matters more than it looks:** the wiki puts both real
     keys inside the drained Aquarium, and the key *names* refer to which
     Archives drawer each opens, not where each is found. Without this
     confirmation a future reader would have had to guess whether "Patio" was a
     considered choice or a mistake. **A confirmed divergence is cheap; an
     unconfirmed one costs someone a re-derivation.**

  **The `telescope`'s blocker was OVER-SCOPED and must be rewritten, not
  cleared.** It has two independent uses and
  `constellation_activation_not_modeled` names only one. The **Planetarium arm**
  -- a permanent, once-per-day, non-consuming room upgrade unlocking one of five
  planets (Mora always last), each granting a fixed item -- touches no stars,
  no night sky and no constellations. **Building it must NOT flip
  `implemented: true`**: `chronograph` is the standing precedent for exactly that
  error, a wired half with the flag flipped, and it took a session to notice.
  **A slow counter is better than a false one.**

- **2026-08-13, FOUR OWNER RULINGS clearing the whole outstanding queue -- and
  the fourth rejected the question rather than answering it.**

  **1. `file_cabinet_key`: model exactly ONE key, buried in the Patio.** Owner,
  verbatim:

  > "The Archives upgrade disk is locked by the file cabinet key buried in the
  > Patio. The player receives it if they can dig in the Patio. Model exactly one
  > file cabinet key in the Patio."

  **This reframes the item from never-buildable to buildable now.** The options
  offered were reclassify-as-`wont_implement`, keep-blocked, or build the full
  gate behind the Pump Room. The owner took none: they **specified the model**,
  and it drops every expensive part.
  - **One key, not three.** The wiki's Laundry Room and Tunnel keys -- newspaper
    clippings and a letter, both lore, one of them in the out-of-scope Crate
    Tunnel -- are not modelled.
  - **No Aquarium drain, no water levels, no Pump Room.** The acquisition path
    is a **Patio dig**, and digging is already fully modelled. `patio` already
    carries `dig_spots: 1`.
  - **`upgrade_disk_archives` stops being free.** It is `guaranteed_in:
    ["archives"]` and `implemented: true` today, granted on first entry under the
    assumed-solved doctrine. It now gates on holding the key.

  **This is the one place the assumed-solved doctrine is deliberately reversed,
  and the reason is that the gate became cheap.** The doctrine exists to avoid
  modelling puzzles; a dig is not a puzzle, it is a mechanic that already works.
  **When the cost of a gate collapses, re-ask whether the simplification is still
  earning its place.**

  **2. `chronograph`'s rewind is FREE, UNLIMITED, and ONE-WAY down the stack.**
  Rewind as many times as there are prior hands, back to the original three.
  **The hand you leave is NOT pushed**, so it walks strictly backwards and cannot
  oscillate. Spends no redraw, no die, no gem. The wiki never states a cost, and
  "acts as a normal redraw" refers to draw effects firing, not to cost.
  Confirmed as a **forward-pinned re-deal, not a state restore** -- no RNG
  snapshot, no deck rewind.

  **3. `gear_wrench` is SAVE-SCOPED; the Conservatory conflict is filed
  separately.** Axed rarities survive the `DayChain` attempt wrap, joining
  `stars` / `main_course_bonus` / shrine -- matching the ruling already made for
  `the_axe`'s permanent gem-cost override. **Recorded as its own backlog item:**
  the wiki says the Conservatory writes the *same* permanent rarity slot and can
  reset a wrench-set rarity, but this sim models the Conservatory as a random
  day-scoped reroll of three undealt cards. **Two incompatible models of one game
  mechanic will coexist until the Conservatory is revisited.** That is a
  deliberate, recorded divergence, not an oversight.

  **4. Lost & Found: REPLACE the existing path with the published transform.**
  The sim spawns its items through `lost_and_found_on_enter`, a fixed
  luck-independent 2-item draw that bypasses the ladder entirely; the wiki gives
  it *"One item is added to the result, and the item count then clamped to be in
  2-4."* PR-B recorded the transform but deliberately did **not** wire it,
  because layering it on top would **double-grant** -- correctly stopping rather
  than building. Owner ruled: the published rule wins, the fixed draw goes.
  **Care needed:** the room's steal/gift behaviour also lives on that path, so
  removing the draw must not remove the steal.

  **Generalisable, and the second instance today: a prose answer to a
  multiple-choice question is a rejection of the frame.** The locked-door ruling
  did the same thing -- both times the options were reasonable and the frame was
  what was wrong. **When the owner writes prose instead of picking, the prose is
  the ruling, and the first thing to check is which presupposition it discards.**

- **2026-08-13, BOTH remaining "subsystem-blocked" blockers re-derived, and both
  are wrong -- in opposite directions.**

  Re-derived on the strength of the session's record: three `blocked_on` strings
  had already turned out to name mechanics the game does not have. Neither of
  these two survived either.

  **`telescope` is OVER-SCOPED, twice.**
  1. **It has two independent uses and the blocker names one.** The
     **Planetarium arm** -- a permanent, once-per-day, non-consuming room upgrade
     unlocking a planet that grants a fixed item (Dauja->Trunk, Fennmora->Apple,
     Mamora->Ivory Die, Veia->Dirt Pile, Mora->Prism Key, Mora always last) --
     touches no stars, no night skies, no constellations. **Buildable today on
     existing primitives. M, not L.**
  2. **"Constellation activation" is not a missing subsystem.** It is a
     published data table dispatched over primitives that already exist.
     Enumerated all eleven: nine map onto `tier1._grant`, the food-steps
     pipeline, or an existing green-room grant, and **two are already wired and
     reachable** -- `southern_cross_active` and `draxus_active` are LOADed at
     `draft.py:326,328` and STOREd **only in tests**. That is one missing
     *source*, not a subsystem.

  **The star table is published, complete for 0-49, and self-validating.**
  Reconstructed from the per-constellation appearance lists and checked against
  the wiki's own invariant ("the total stars of those constellations always
  equalling the player's star count"): **49 of 50 counts partition exactly**, and
  the single exception is the one the wiki documents (0 stars still shows the
  North Star). A validator can assert that invariant.

  **`file_cabinet_key` is the reverse: the blocker is literally true and
  entirely beside the point.** Its whole mechanically-relevant payload is **one
  Upgrade Disk that the assumed-solved doctrine already grants**
  (`upgrade_disk_archives`, `implemented: true`, `guaranteed_in: ["archives"]`,
  whose own note says so). The other two of the three keys yield newspaper
  clippings and a letter -- lore, and this sim has no document layer by standing
  ruling -- and one lives in the **Crate Tunnel, ruled out of scope three
  separate times**. **Implementing it would only add a gate the assumed-solved
  doctrine exists to remove.** Fully built, it moves an agent's expected value
  by **zero**, and would cost the entire Pump Room water subsystem
  (~800-1200 lines, an action-width change, an obs-width change, a retrain) to
  do it.

  **So it is not blocked work -- it is a decision nobody wrote down**, carried
  as work-in-waiting across five separate entries in this file. **Recommended:
  reclassify to `meta.wont_implement`**, exactly as the Magnifying Glass and Key
  of Aries were. The validator already enforces the pairing and
  `test_wont_implement_items_carry_a_reason_and_no_blocker` is the existing
  guard, so it is **a data edit with no new test**: real backlog 5 -> 4 without a
  line of engine code. **Owner ruling outstanding.**

  **A FOURTH failure mode for the catalogue.** The three earlier ones named
  mechanics that do not exist. `dowsing_rod`'s was *literally true but
  materially misleading* -- a real gap filed under "a subsystem is missing",
  making it look far larger than it was. `file_cabinet_key`'s is the same shape
  and worse: **a decision mis-filed as a blocker.** A blocker says "cannot yet";
  a decision says "will not". Filing the second as the first keeps dead work
  alive forever and inflates the backlog.

  **Two live defects found in passing, neither part of either item:**
  - **The day-20/21 sale applied to all EIGHT shops** (`stock_display` computed
    `is_sale` with no `shop_id` filter). The wiki: *"This sale is unique to the
    Commissary ... and does not apply to other Shops."* Fixed.
  - **The Planetarium's 2 stars fire on ENTRY, not on ending the day there.**
    `rooms.json` grants them via `tier1.grant` on `Hook.ON_ENTER`; the wiki gates
    them on *"If you call it a day in PLANETARIUM."* **`Hook.ON_DAY_END` exists,
    is fired for the room the player stands in, and an AST decorator scan across
    all of `engine/effects/` finds ZERO handlers registered on it** -- a live,
    never-used capability. Queued.
  - Also: `file_cabinet_key` **spawns today**, gated on nothing, eating
    probability mass from the Aquarium's real item roll, and its
    `persistence: "until_used"` means it returns every day forever as a dead
    inventory slot. Couples to the reclassification ruling.

- **2026-08-13, THE LUCK MODEL IS BEING REBUILT. Four owner rulings, and the
  discovery that the sim's luck axis is largely invented.**

  The sim uses a **flat Bernoulli ramp** (`p = luck/29`, rolled
  `additional_max` times). The game uses a published **item-count ladder**.
  These are not the same currency and no arithmetic reconciles them.

  **The behavioural delta is not a recalibration -- it inverts the strategic
  gradient.** E[items] per rolling room, sim vs game:

  | luck | 4 | 10 | 16 | 19 | 23 | 29+ |
  |---|---|---|---|---|---|---|
  | sim | .138 | **.345** | .552 | .655 | .793 | 1.000 |
  | game | .070 | **.250** | .832 | **2.050** | 3.000 | 4.000 |

  At day-start luck 10 the sim is **1.4x too generous** (2.3x once Room 46 is
  reached). Above luck 19 it is **3-4x too stingy**. **The game's payoff has a
  cliff at 19; the sim's is a flat line.** A policy stacking luck -- the exact
  behaviour the Veranda and Rabbit's Foot exist to encourage -- is currently
  being told the payoff is roughly linear.

  **THE OWNER'S MAID'S CHAMBER RULING IS PROVABLE, NOT A TRUST CALL.** The
  Dowsing Rod's datamined box says its low-luck branch is reachable *"only ...
  having 4 Maid's Chambers drafted"*. At **-3**: 4 drafted gives luck -2, +32
  = 30, never <= 18. At **-7**: -18, +32 = **14** (match), and 3 drafted gives
  21 (> 18), so four really is the only way. **Only -7 satisfies both halves.**
  The proof belongs in the test docstring so nobody "simplifies" it back.

  **HIDDEN DEPENDENCY: that ruling also kills the zero-clamp.** -7 x 4 = -28
  requires `state.luck` to reach **-18**. `effects/tier1.py:198` clamps
  `anti_luck` at 0 -- while `_grant` 150 lines above it explicitly does not,
  and its docstring says luck may go negative. **The same file contradicts
  itself.** Correcting the magnitude without removing the clamp would make the
  sim wrong in a new way. `env/obs.py`'s `resources` low bound (-1) must widen
  too -- a **bound change, not a width change**; the vector stays 7 wide.
  (A latent bug already exists: two `penalty_two_plus_items` procs from 0 reach
  -2, outside the declared Box.)

  **The rulings:**
  1. **The Luck Penalty is per-day**, resetting each morning -- a `GameState`
     field alongside luck. The wiki mentions the Luck Penalty on exactly three
     pages and **never states its reset scope**; the owner ruled it. This also
     avoids a real cost: a per-save penalty would have needed a **new carry
     channel**, because `_CARRYOVER_KEYS` is a frozenset of **bool** fields and
     cannot hold an int.
  2. **Delete `penalty_two_plus_items`** -- the sim lowers luck by 1 when a room
     yields 2+ items. **No such game mechanic exists.** The real mechanic is the
     Luck Penalty accumulator. Must go in the same PR as the ladder or the two
     double-count.
  3. **Rebuild the Veranda and Spare Veranda**, which are wrong in **four ways
     at once**: +3 (should be +12 first-per-day / +6 later, and +6 for Spare),
     *stored* (should be per-draft), *unconditional* (should apply only when the
     drafted room is green), and *on entry* (should be on draft).
  4. **Staged into three PRs**, not one: PR-A the ladder + penalty + the
     migration; PR-B the published never-roll list, the
     `additional_max` -> `item_cap` rename and the per-room transforms; PR-C the
     Maid's -7 unclamped and the Veranda rebuild. **The reason is review
     quality**: PR-A's 76 mechanical test edits and PR-C's 10 semantic magnitude
     changes are different kinds of review, and mixing them is how a wrong
     magnitude slips through a 27-file diff.

  **THE MIGRATION TAX IS FIXED AND LARGE: 76 occurrences of `state.luck = 0`
  across 27 test files.** They all break, because **the ladder has no zero
  point** -- at luck <= 4 it is still 7% for 1 item. The idiom "floor luck to
  suppress the roll" ceases to exist and needs a replacement helper. That helper
  needs its own test: if it silently stops suppressing, 27 files go flaky at 7%,
  which is the vacuous-by-luck failure this repo has recorded four times.

  **`additional_max` is not data -- it is a guess in a Python constant.**
  `tools/ingest_sheet.py`'s `ADDITIONAL_MAX_DEFAULT` is a per-category default
  whose own comment reads *"Item Spawns table is Cloudflare-blocked; these are
  community-informed estimates ... editable in `data/overrides/`"* -- **and
  `data/overrides/` does not exist.** That reframes the pending
  `additional_max` task from "fix 12 rooms" to "replace a guessed default table
  with a published one". Recommended: keep it, renamed **`item_cap`**, as the
  honest stand-in for the unmodellable spawn-pool cap.

  **A SECOND self-referential test found.** `tests/test_draft_tracking.py:118`
  recomputes `p_extra` from `registry.item_rules["luck"]` -- the identical dict
  `items.py` reads. **It passes for any value of `max_effect_at`.** It is the
  only test of `expected_yields` and it tests nothing. That is the same
  anti-pattern as `test_draft_stats.py:34`, now found twice.

  **The luck -> item-count axis has NO distributional guard at all.** Not
  `test_draft_stats.py` (rarity only, zero `luck` references), not
  `test_draft_items.py` (zero occurrences of "luck" despite the name). **It can
  be rebuilt with the arithmetic wrong and the suite stays green.** Fourteen
  named tests are specified; the rule for every one is that **no expectation may
  be derived by calling the function under test or by reading the same data file
  the engine reads** -- wiki percentages get hard-coded as literals with the
  verbatim wiki line as the docstring.

  **Accepted, recorded gap:** the ladder is fully documented but per-room count
  transforms are documented for **5 rooms out of ~170** (Nook, Study, Guest
  Bedroom, Den, Lost & Found), while `/Luck` states *"Most rooms don't use the
  item count given directly"*. **A faithful ladder applied uniformly is still
  wrong for the other 165 -- just wrong differently than today.** Owner ruled:
  model the five, record the gap, proceed. Play observation is the only path to
  the rest.

  **`docs/luck.md` carries eleven false statements**, of which the stale
  Rabbit's Foot line is the *least* consequential. The load-bearing ones:
  *"the real curve shape is not documented"* (it is fully documented as a step
  ladder -- the sim never fetched the box) and *"self-balancing: finding 2+
  items lowers luck by 1"* (a sim invention). Rewritten in PR-C.

  **`dowsing_rod` lands AFTER the rebuild, as its own PR.** Its table is defined
  *by reference* to the base ladder ("variable items", "runs the regular
  non-Dowsing Rod routine", "+2 Luck Penalty") -- building it first means
  building the ladder twice. Its avoid-list (26 rooms) and the never-roll list
  (19 rooms) share 15 entries but **neither contains the other**; they are two
  separately published tables and must stay two data fields.

- **2026-08-13, the Free/Gem Draw step is built -- and five existing tests were
  passing BECAUSE of the bug it fixed.**

  Slot 1's gem rate (engine indexing) fell **31.79% -> 2.14%** at ranks 1-2,
  which is what the published table actually specifies there (0% at 0 gems, 2%
  at rank 1 with 1-3). The old rate was the size-sort artifact. Slot 0 stayed
  **exactly 0%** across 1776 draws -- the "slot 1 is always free" invariant
  survived, verified before and after.

  **Three category-bias tests (`schoolhouse`, `scepter green`, `library ->
  bookshop`) were only ever passing because the bug over-delivered gem rooms at
  low rank.** Each targets a gem-cost room from a rank/gem setup where the real
  table gives ~0%. Their *properties* are still true; their *setups* were
  invalidated. Rebuilt at rank 8-9 / 4+ gems, where the table gives 59.26%.
  **A test that only passes under a bug is not a test.**

  Two others: an Archives test asserted `steps == steps_before` while coupled to
  *which* room got dealt (a different room now lands and grants +5 steps) --
  decoupled rather than reseeded; and a behavioural-cloning fixture used a seed
  as a scenario *constructor* -- rebuilt to construct the scenario
  deterministically, because hunting a replacement seed is seed-tuning in
  disguise and would rot again on the next draft change.

  **A test helper was itself exploiting the bug**: `test_experiments.py`'s
  `_force_drawing_room_dealable` trimmed the free deck below the gem deck's
  count so the size-sort would try gem first. It had to be rewritten.

- **2026-08-12, THE FREE/GEM DRAW STEP IS MISSING ENTIRELY. Owner ruled: model
  it fully. This is the largest divergence found this session.**

  The investigation was commissioned to check one sentence on `The_Axe`
  (*"spawn at the same rates as gem rooms (more often with more gems in hand,
  and on higher rank)"*). **The sentence is precise and traceable to a datamined
  table, and the gap is bigger than the question.** It is not a missing *bias*
  on an existing roll -- there is **no Free/Gem Draw step in this codebase at
  all.**

  **What the sim does instead**, `draft.py::_deal_from_rarity`: it takes the free
  and gem decks for the rolled rarity, sorts them by `remaining()`, and deals
  from **whichever currently holds more undealt cards**. Deterministic, consumes
  no RNG. Whether slot 2/3 shows a gem room is an artifact of pool composition.
  The comment there claims this makes the pair "behave like one combined deck";
  it does not -- it is "always deal from the larger deck".

  **What the game does**, `Drafting/Advanced` -> "Free/Gem Draws": slot 2's
  chance to be a Gem Draw is a published rank x gems-in-hand table (buckets
  **0 / 1-3 / 4+**, ranging 0% at rank 1-3 with no gems to **59.26%** at rank
  8-9 with 4+), **slot 2 succeeding forces slot 3**, slot 1 is always free, and
  early drafts are carved out (veteran: first 2 drafts all free; otherwise the
  first `6-Day`). Slot 3 has its own rank table when slot 2 stayed free
  (75% / 87.5% / 93.75%). Corroborated on `Gems`: *"When more gems are held, the
  odds of drawing Special Floorplans is higher than with fewer gems."*

  **`state.gems` reaches the draft pipeline nowhere.** Proved by execution, not
  grep: every `GameState` slot and `GameConfig` field was wrapped in a
  read-tracing descriptor over 240 drafts. `gems` was **never read** from
  `decks.py` or `draft.py`, and dealt hands were **bit-identical** for starting
  gems in {0, 1, 3, 4, 10, 50} at fixed seed. The gem-rate/gem-count correlation
  the sim *does* show is confounded -- gems accumulate with time of day, which
  correlates with deck depletion.

  **Measured divergence**, 250 episodes x 3 days, `greedy_rank`: sim slot 3 runs
  **~44%** gem where the real game past its carve-outs is **75-93.75%** by rank
  plus slot-2 spill-over; and day 1 should force **0%** for the first 2 drafts
  under veteran mode (the repo default) where the sim deals **8.6%**.

  **I was wrong about the consequence, and the correction matters more than the
  claim.** I recorded that this would mean `tests/test_draft_stats.py` is
  asserting a wrong distribution. **It is not.** That suite tests the *rarity*
  axis only, and the rarity tables are correct. **The free/gem axis has never
  been tested at all.** A missing guard, not a lying one -- and that absence is
  precisely why a whole decision step could go unmodelled without anything going
  red. **When a suite is called "the sharpest guard in the repo", ask what axis
  it guards before trusting it with a different one.** That is now three times
  this session the same suite has been credited with coverage it does not have.

  **Not previously recorded anywhere.** `docs/drafting.md` says only "Slot 1 is
  always free; slots 2-3 may deal gem-cost rooms" and never states how slots 2-3
  choose -- so the deck-size heuristic was undocumented rather than
  documented-as-simplified. A genuine discovery.

  **Owner ruled Option B, model it fully** (~150-220 lines): the table into
  `weights.json` as `confidence: datamined`, a `drafts_today` counter (none
  exists -- `draft_counts` is cumulative per-room), a per-draft round counter,
  the free/gem decision rolled once per round and threaded through
  `draw_slot`/`_deal_from_rarity`/`_deal_biased`, replacing the size-sort.
  **Materially changes the gem economy a policy trades against; a retrain is
  already owed.** The required new guard is a chi-square on the **free/gem
  axis**, which has no existing coverage.

  **Note for `the_axe` when it resumes:** `Drafting/Advanced` says deck
  membership "uses the actual gem cost of the room, **ignoring any modifiers
  like The Axe**". So an axed room stays in the Gem decks -- zero the *charged*
  cost, never `Room.is_free`. That is independent of this work.

- **2026-08-12, OWNER RULING: fix the forced-Closet colour crash next, ahead of
  the item queue.** Found incidentally by the free/gem investigation and
  reproducible without instrumentation: `greedy_rank`, day 10, seeds 4 and 97,
  ~2 in 250 episodes, `AssertionError: secret_passage dealt 'closet', not a
  'hallway' room`. `draw_slot`'s 4th-attempt forced-Closet fallback escapes the
  colour filter that the Secret Passage's handler asserts on.

  **It is being fixed as a correctness question, not silenced.** Three outcomes
  are open -- the Closet is legitimate and the assertion is too strict; the
  Closet is illegitimate and the fallback must respect `ctx.colour`; or the
  fallback should prefer an on-colour room first. The wiki decides, and if it
  does not, the owner does. **An assertion that fires twice in 250 episodes is
  doing its job**; weakening it to make a crash go away would trade a loud
  failure for a silent draft-math divergence.

- **2026-08-12, `gear_wrench`: the target is the RARITY, not the room -- an
  error repeated in three places, mine included.**

  The wiki's own one-line description: *"Each time you draft a mechanical
  floorplan, you may permanently adjust its rarity."* The room is **whichever
  Mechanical Room you just drafted**; the **choice is over the four rarity
  levels**, seeded at the room's current one. So the action block is **4 ids,
  not 8 (rooms) and not 32 (rooms x rarities)**.

  **That error is written in three places and all three need correcting**: this
  file's earlier entry, `special_items.json`'s `meta.notes`, and my brief.

  **Why the earlier "misreading" finding was itself a misreading.** The retracted
  claim came from reading only the item's `DataMinedBox` -- the *pickup* side
  effect, which really is scoped "that day" -- and missing the infobox and Usage
  text, which say **"permanently"**. **The Gear Wrench has two separate effects
  with two different scopes and two different blockers**, and collapsing them is
  what produced both the original error and my retraction of it:
  - **Main effect**: drafting a Mechanical Room while holding it -> permanent
    rarity set. Fires in `Game.choose_option`, where `self.rng` exists. **Not
    blocked.**
  - **Pickup effect**: Workshop + Boiler Room -> Standard, that day. Needs `rng`
    inside `_on_pickup`, i.e. exactly `battery_pack`'s constraint. **Still
    blocked, and must keep a named blocker rather than having it deleted when
    the main half ships.**

  **The second permanent rule is free.** `Rarity` says that once a room's rarity
  has been set by the Conservatory or Gear Wrench, *"that room's Dynamic Rarity
  is **permanently** ignored"*, surviving even a Conservatory reset. **This sim
  does not model Dynamic Rarity at all** -- `state.dynamic_rarity` is
  bookkeeping for the card-move primitive, not the game's hidden per-room table,
  and `weights.json`/`rooms.json` carry no such data. So the headline rule has
  nothing to ignore and costs **zero lines**.

  **The Conservatory is NOT the template**, contrary to my brief's hope that it
  would make this cheap. `reroll_random_rarities` is a *random* 3-undealt-card
  reroll, day-scoped, that never writes `state.dynamic_rarity` and has no config
  field. The real saving came from Dynamic Rarity being unmodelled instead.
  **Flagged: the sim's Conservatory and the wrench would model the same game
  mechanic two incompatible ways** -- an owner question before the wrench lands.

  **A reachable silent-corruption hazard, found by the researcher and not in any
  brief:** `decks.py::inject_rooms` and `apply_upgrade` index decks by
  `room.rarity_idx` **without consulting `dynamic_rarity`**, while
  `inject_rooms_undealt` does. `pump_room` is both Mechanical and `pool_temp`,
  so **The Pool plus a wrenched Pump Room is a reachable corruption**, not a
  theoretical one. Every Mechanical Room has `deck_copies == 1` and
  `room_draftable` enforces one copy on the grid, so the right implementation is
  a **build-time bucket assignment** folded into `build_decks` -- which consumes
  **no RNG at all**.

  Re-derived size **~400-450 lines**, not the "cheap" of the 2026-08-11 audit.

- **2026-08-12, `chronograph`: the half everyone believed was finished is
  ~3x too strong.**

  The Tomorrow-Rooms bias is wired -- as a **`category_biases` entry rolling 40%
  per slot, on all three slots including the free-only slot 0**. The wiki's
  datamined box says it is a **Priority Draw (40% for all Tomorrow Rooms)**,
  which fires **once, into slot 3 only**. Measured over 500 seeds, first
  doorway: **0.93% of options are Tomorrow Rooms without the item, 37.7% with
  it.** A slot-3 priority draw would give ~13%. P(at least one Tomorrow Room in
  a hand) is ~78% rather than 40%.

  **So `chronograph` is not "half implemented with the easy half done" -- the
  done half is wrong.** Fix it as its own PR, landed before the rewind: it is an
  independent distribution regression, and coupling a 3x change to an
  action-width change makes both un-bisectable. Caveat for whoever takes it: the
  12 Tomorrow-Room ids include four `mail_room__ix*` variants and
  `hallway__ix76`, so the list must be **generated, not hand-typed**, or
  `_priority_draw` needs a category selector it does not have.

  **The rewind is not time travel, and that collapses the hard problem.** The
  wiki: *"This acts as a normal redraw but with the three rooms drawn being
  fixed, **activating** effects that rely on drawing a floorplan."* So it is a
  **forward-pinned re-deal** -- overwrite `pending.options` from a saved stack,
  re-fire `ON_HAND_DEALT`, reset `rotations_used`. **No RNG restore, no deck
  rewind, no refund.** A true state restore would need a deep copy of all eight
  decks plus stream states, would cost ~250 lines more, and **would still be
  wrong**, because it models a mechanic the game does not have. Recorded as the
  design, not as an approximation.

  State belongs on **`PendingDraft`** (per-hand, alongside `study_redraws_used`
  and `colour`), not on `GameState` and not in any carryover channel -- the item
  is `persistence: "day"`, so **`_CARRYOVER_KEYS` is irrelevant here**, a third
  brief of mine in which that worry did not apply.

  **`prev_options` must be in the observation**, as an **additive Dict key** --
  never a shape change to `options`, which would silently reinterpret trained
  weights. Without it the agent knows a rewind is *legal* but has no signal on
  whether the previous hand was better, so it is noise and will be learned as
  "never press". Re-derived size **~485 lines**.

  **A correction to a correction, worth keeping:** I had recorded that
  `test_draft_stats.py` "never constructs a `Game` in its chi-square tests".
  The chi-square tests indeed do not, but `test_slot1_always_free` **does**. The
  conclusion (not at risk here) survives; the stated reason did not.

- **2026-08-12, `the_axe`: four owner rulings, and a wiki sentence that may
  describe a mechanic this repo does not have AT ALL.**

  **The rulings:**
  1. **Targets are root-base keyed -- 48, not 170 or 64.** One target per
     floorplan family with a gem cost, via `upgrades.root_base_id`, matching how
     the Room Directory holds one entry per family and how `draft_counts`
     already does family-level accounting. **`N_ACTIONS` 376 -> 424**, appended.
     Axing `cloister` covers its upgrade variants.
  2. **Save-scoped**: axed rooms and the 3-use cap survive the `DayChain` wrap,
     joining `stars` / `main_course_bonus` / shrine as explicit save-scoped
     carve-outs. The strongest reading of "permanently", and it makes the
     32-coin purchase a real long-horizon investment.
  3. **An unused Axe drops overnight** -- confirms the record's existing
     `persistence: "day"`, which was an *unsourced* value the wiki does not
     settle. Buying it is a same-day commitment.
  4. **Investigate the missing gems-in-hand draft bias BEFORE building the
     item.** See below.

  **The thing that stopped the item: `weights.json` has no gems-in-hand table.**
  The Axe's datamined note says axed rooms *"spawn at the same rates as gem
  rooms (**more often with more gems in hand**, and on higher rank)"*. The rank
  half is modelled. The gems-in-hand half appears to be modelled **nowhere** --
  `weights.json` carries only `tables` / `solarium_slot23` / `library_override`
  / `deck_size_gates`, and the only gem-adjacent gate, `cfg.gem_gate_active()`,
  is veteran-mode/Room-46/day-based, **not** gems-in-hand.

  **Owner ruled this outranks the item that surfaced it**, and the reasoning is
  worth keeping: a missing draft-rate input would affect **every gem room in
  every draft**, not just axed ones -- and if it is real, then
  `tests/test_draft_stats.py`, the chi-square suite treated as the sharpest
  guard in the repo, **is currently asserting a distribution that is wrong.**
  A guard that pins the wrong number is worse than no guard.

  **Live prior, stated so the investigation is honest: the sentence may simply
  be loose.** Three `blocked_on` strings this session named mechanics the game
  does not have. "The wiki is loosely worded and there is no separate mechanic"
  is a perfectly good outcome and cheaper than building something imaginary.

  **Three of my own brief's premises were wrong**, all found by re-derivation:
  - *"`_CARRYOVER_KEYS` must grow to hold this."* **False.** It is a
    `frozenset` of **bool** `GameConfig` fields only; ordered and set-valued
    permanent state lives in a separate documented channel alongside
    `sigil_doors_open` and `collected_sanctum_keys`. **16 stays 16.** ("Append
    at the end" is meaningless for a frozenset anyway -- only `sorted()` order
    matters, and inserting a key *does* shift the `carryover` obs vector.)
  - *"It needs an observation width change."* **Misleading.** No existing obs
    key changes shape; it is an additive Dict key. And the gem cost the agent
    actually drafts against **already reads 0 for free**, because
    `options[].gem_cost` routes through `_effective_cost`.
  - *"Confirm `tests/test_draft_stats.py` would catch a deck-move
    mis-implementation."* **It would not**, and this is the most actionable
    finding: `test_rarity_roll_matches_table` recomputes its own expected
    weights through the very same `rarity_deck_ok` the engine uses, so a
    free/gem bucket move changes deck sizes, the gate self-adjusts, and the
    test still passes. **The repo currently has NO guard against the exact trap
    the Axe is most likely to fall into.** Writing that guard is a required part
    of the item's work, and it must be written *before* the action layer.

  **The Room Directory does not exist in the sim.** The only trace is
  `meta.directory_number` in `rooms.json`, which is never parsed into `Room`,
  is missing on 34 of 170 rooms, and has only 77 distinct values across 136
  rooms (13 rooms share `"3"`). **Not usable as an action index.** "Room
  Directory action" means: invent a target-selection block, do not build a
  Directory subsystem.

  **The Axe does NOT belong on `ItemHook.GEM_COST`.** Both existing gem chains
  are *held-item* chains -- every handler guards on `item_capability_any`. The
  Axe is **consumed at use time and its discount outlives the item**, so
  registering it there would mean a handler that deliberately fires when its
  item is not held, inverting the contract the chain is built on. The override
  is a two-line branch in `resolve_gem_cost`, which already takes `GameState`
  -- so **no signature changes propagate anywhere.**

  **Re-derived size: ~520-570 lines** (~220 source, ~300-350 tests), not "obs +
  action width change", which accounts for maybe 60 of the 220. The real cost is
  that the item introduces a **new kind of persistent state** -- an ordered,
  capped, room-keyed permanent price override -- touching the
  config -> state -> carryover -> config loop end to end, plus a shop-supply
  gate. Mitigating that: `sigil_doors_open` is a near-exact structural template
  for all of it, so this is a port, not a design.

- **2026-08-12, OWNER CORRECTION: the Crown of the Blueprints filters a Red Room
  from ALL draws for the rest of the day. There is no exemption -- and this
  VOIDS an earlier ruling rather than amending it.**

  Owner play overrides the wiki. The wiki's `Drafting/Advanced` claims a blocked
  Red Room is still obtainable *"through special drafting like Silver Key and
  Prism Key"*, and that duct-carrying red rooms still appear. **That is wrong.**
  It is filtered from every draw path for the rest of the day.

  **Ruling 4 of the 2026-08-12 crown rulings is VOID, not answered.** That
  ruling ("exempt colour-selective drafting AND rework the Silver Key so its
  exemption is real") was the answer to a question that only existed because the
  wiki claimed there were exemptions to scope. **A correction can invalidate the
  question, not just the answer** -- and this one did.

  **Three consequences, all of them simplifications:**
  1. **The Crown effect PR no longer collides with `prism_key`.** The collision
     was created entirely by the Silver Key rework that ruling 4 pulled in. They
     can run in parallel again.
  2. **The Silver Key rework is not required by the Crown at all.** It does not
     disappear -- it belongs to the locked-door subsystem ruling, which is where
     it now sits.
  3. **The implementation gets smaller**: the filter still belongs in
     `draft.py::room_draftable`, the single gate every draw path passes through,
     but with no `ctx.colour is None` exemption guard. A filter, never a removal
     -- deck *sizes* feed rarity legality via `rarity_deck_ok`, so removing cards
     would change which rarities are legal to roll for the rest of the day.

- **2026-08-12, OWNER CORRECTION: the Gear Wrench's rarity adjustment IS
  permanent, like the Conservatory -- retracting a finding I recorded earlier
  today.**

  Earlier in this session I recorded that `gear_wrench`'s
  `blocked_on: rarity_change_not_persisted_across_days` "rests on a misreading",
  on the strength of the wiki spelling the pickup effect *"that day"*. **Owner
  play says permanent. The blocker is correct and the item is genuinely blocked
  on cross-day persistence.**

  **The generalisation I drew from it was therefore also wrong.** I wrote that
  *three* blockers this session had been found to name a mechanic the game does
  not have. **It is two** -- `crown_of_the_blueprints` and the digest's "~15
  lines". The rule itself survives, and `crown_of_the_blueprints` remains a
  clean instance of it, but the count does not.

  **This is the failure mode this session has been cataloguing, committed by me,
  from the same cause each time: a claim inherited rather than re-derived.** I
  took the research agent's wiki reading and generalised from it inside the same
  hour, without the owner's play to check it against. **A pattern asserted from
  N instances needs each instance verified, not the pattern.**

  Note the wiki distinction the research turned up is still real and still
  useful, it just does not license what I claimed: the *pickup* effect is
  spelled "that day", while a **separate** permanent effect says a room whose
  rarity has been set by the Conservatory or Gear Wrench has its Dynamic Rarity
  *permanently ignored*. `battery_pack` stays **day-scoped** on the owner's
  direct ruling -- that ruling stands on its own authority, but **the analogy to
  the Gear Wrench that motivated the question is now dead** and must not be
  reused.

- **2026-08-12, the locked-door subsystem is scoped, and it surfaced a live
  shipped bug that has nothing to do with the redesign.**

  **THE BUG (fixing first, separately): the action mask makes the Master Key,
  Silver Key and Lock Pick Kit unusable at zero keys.** `env/actions.py`'s
  `NAVIGATE` branch gates opening a locked doorway purely on
  `st.keys < key_cost + lock_open_cost`, and **never consults
  `can_open_locked_free`** -- unlike `game.py::doorway_passable`, which does.
  Probed on a locked frontier doorway at `keys=0`: `doorway_passable=True`,
  `can_open_locked_free=True`, **open action legal = False**, for each of the
  three items. **The highest-tier item in the game is unusable at 0 keys**, and
  it contradicts the wiki in as many words (`Keys`: *"This menu can appear even
  when no basic keys are held."*). Two copies of one rule that drifted.

  **Lock state is ALREADY fully visible to the agent.** `env/obs.py` builds
  `grid_locked`, `grid_security` and `grid_sealed` as 9x5 direction-mask planes,
  set on both cells of every segment. So "trying a door reveals whether it is
  locked" is **an observation *reduction*, not an addition** -- which makes it a
  much bigger and riskier change than it sounds, and it is separated out below.

  **The wiki confirms the owner's first sentence as datamined fact**, not
  inference: *"A door being locked or not is determined dynamically the first
  time the door is clicked."* And clicking then exiting **latches** the roll --
  you cannot re-roll a door by walking away.

  **The menu is six keys in a published fixed order** -- Basement Key, Secret
  Garden Key, Silver Key, Key 8, Master Key, Prism Key -- so it is **a published
  table and belongs in `data/locks.json`, not a Python constant.** Two
  corrections to the owner's list, which was right but incomplete: it omitted
  **Basement Key** and **Master Key**. And two of the four named
  (`secret_garden_key`, `key_8`) are modelled in this repo as
  `draft_conditions` tags, **not as door keys at all** -- so the mechanic is
  unimplemented for them in both directions.

  **Two premises of my own brief were wrong.** There is no "fixed precedence
  among free-opening tools" to model, because the category does not exist:
  **Master Key is a menu row**, and the **Stopwatch is not in the unlock menu at
  all** -- it is a passive refund on the *Use key* option that requires >=1 key
  in hand. Only the Lock Pick Kit is a genuine third prompt, and it is
  restricted to doors that take a regular key. Separately, I costed the designs
  against `tests/test_draft_stats.py` as the guard at risk; **it is not at
  risk**, because `Rng` substreams are independent per label and that suite
  never opens a door. The exposed statistical guard is `tests/test_locks.py`'s
  bias tests, and only under the hidden-lock-state design.

  **Design chosen: `Phase.LOCK_PENDING`**, a structural clone of the existing
  `COLOUR_PENDING` precedent. `open_door` on a locked segment stops unlocking,
  parks the doorway, and the agent picks one menu row or abandons. **+9 appended
  action ids** (`use_key`, `lockpick`, the six menu keys in published order,
  `abandon`), `phase` `Discrete(6)` -> `Discrete(7)`, `_CARRYOVER_KEYS`
  unchanged at 16. Unimplemented keys get a permanently-False mask slot -- a
  reserved id costs nothing and never shifts later. **~350 lines, ~14 files,
  ~20 existing tests changed.**

  **It directly models the play the owner cares about**: `abandon` returns to
  `NAVIGATE` with the segment still locked, which is the wiki's *"option to
  exit the menu"*.

  **`grid_search_cost` ships in the same PR, and this is the load-bearing
  detail.** `door_search_cost` appears **nowhere in `env/`**, so a Great Hall
  side door costing 3 keys is today indistinguishable from an ordinary 1-key
  door. Without it, "spend keys versus walk further" is **unlearnable at exactly
  the doors where it matters most** -- and shipping a choice whose stakes the
  agent cannot see is worse than leaving the choice automatic.

  **No new ItemHook priority chain.** A menu is a player-ordered choice, the
  precise opposite of a first-match-wins chain; there is no total order for the
  engine to own. Per-key *fit* predicates live in each
  `effects/items/<key>.py`, keeping room and rank knowledge out of the engine.

  **This design also lets `SECRET_PASSAGE_IDS` be paid down** -- once unlocking
  is a distinct step ahead of dealing, the Secret Passage colour pick and the
  Prism Key colour pick become the same mechanism, and the room-id branches at
  `game.py` and `draft.py` can become a room-declared effect. Sequenced as a
  follow-up, not folded in.

  **Deferred to its own owner ruling: hidden lock state.** Rolling the lock on
  first click and *deleting* `grid_locked` from the observation is the literal
  reading of the owner's first sentence, and it is the only design that
  endangers `tests/test_locks.py`'s bias sequences. It is ~600+ lines and makes
  the learning problem strictly harder by removing information the agent has
  today. **Faithfulness bought with sample efficiency** -- escalate separately;
  do not ride it in on the menu work.

- **2026-08-12, `battery_pack`: defer the draw now, thread `rng` later if
  wanted -- and the "37 `grant()` call sites" figure was wrong by 4.7x.**

  **The measurement.** An AST scan (not a grep -- string search gives false
  negatives here repeatedly) counts **173** `special_items.grant` call sites:
  **32 in `src/`, 141 in `tests/`**. The 37 appears to have been copied from
  `tests/test_item_tag_allowlist.py:9`, *"13 of the 37 effect tags"* -- **a tag
  count that got written into a call-site slot.**

  **And the cost was in the wrong place.** 31 of the 32 `src/` sites already
  have `rng` reachable, and the 32nd (`royal_scepter.grant_carry_over`) needs
  exactly one propagated line from a caller that already has `game`. The real
  blast radius is the **83 test sites that call `grant()` against a bare
  `GameState` with no `rng` or `game` anywhere in scope.** Whoever prices this
  should price the test suite, not the engine.

  **Owner ruling: defer the draw** -- record the pickup in state, resolve the
  50/50 at the next deal where `rng` is in scope. **0 call sites change.**
  This is not an invention: it is **the repo's own established idiom**, already
  declared in `_on_pickup`'s docstring (*"resolved lazily in on_arrive/dig_all
  where game.rng is available; no action is taken here at pickup time"*) and
  implemented by `treasure_map`, with `tests/test_digging.py:272` pinning it as
  deliberate. It is provably unobservable: `dynamic_rarity` appears **nowhere in
  `src/blueprince_sim/env/`**, so no agent can see the gap between pickup and
  resolution. The signature change remains available later with no data or
  test-semantics consequence.

  **Owner ruling: the effect is day-scoped.** `state.dynamic_rarity` is already
  a fresh dict per `GameState`, so **no carryover entry and no width change.**

  **The mechanic is a toggle, not a coin flip, after the first trigger.** Both
  the Battery Pack and Workshop wiki pages say a second trigger in the same day
  *"will always switch to the other one"*. The item's own `meta.notes` omitted
  this. A second pickup **is** reachable despite `unique: true`, because
  `grant()` only blocks a re-grant while the item is *currently held*, and
  fabricating the pack away frees a later grant.

- **2026-08-12, `crown_of_the_blueprints`: four owner rulings, and the blocker
  that ordered the queue turns out to have named a mechanic the game does not
  have.**

  **The blocker was a misread.** `blocked_on:
  "within_day_pool_removal_not_modeled"` asserted that the Crown removes a Red
  Room from today's draft pool. The wiki says the opposite in as many words:
  *"Although it claims to remove the room from the draft pool, it actually only
  blocks it from normal drafting."* `Drafting/Advanced` files the Crown under
  **filters** and explicitly contrasts it with effects that *"actually remove
  the room from the draft pool"* (Blessing of the Monk). The exemptions the
  wiki lists -- Silver Key, Prism Key, duct drafting -- only make sense for a
  filter. **Modelled as a filter this is S, not M.**

  **Three further claims in that note were also false**, each of which would
  have misdirected an implementer:
  - *"There is no mechanism to pull a room out of an already-built deck
    mid-day."* `DeckState.remove_card` has existed at `state.py:70` the whole
    time and is called twice mid-day from `decks.py` (255, 292). Whoever wrote
    the note read `build_decks` and stopped.
  - *"`cfg.banned_rooms` is consumed at `decks.py:47`."* It is read at
    **`decks.py:57`** and again at 74-75; line 47 is the `upgrade_disks` check.
  - *"`Hook.ON_HAND_DEALT` is the right trigger."* **A category error, not a
    detail.** `Hook` and `ItemHook` are disjoint enums with disjoint
    registries, and `effects.fire` never consults items at any `Hook`. An item
    cannot register for `ON_HAND_DEALT` at all. Implementing from the note as
    written produces a `@room_hook` that fires whether or not the Crown is
    held.

  **And "the only one of the four that needs no new width at all" is false.**
  The effect is a player choice -- *"an option appears"*, *"you **may**"*,
  *"**Selecting** this option awards..."* -- so it needs `N_ACTIONS`
  **376 -> 379** and `item_state` **11 -> 12**. That was the entire reason it
  was sequenced first. **The reason is dead; the item stays first anyway**, on
  the owner's sequencing ruling below.

  **The four rulings:**
  1. **Fires once per hand**, unlimited hands. The wiki self-contradicts here
     (infobox *"The first time you draw a RED ROOM"* against four statements
     implying no limit, incl. Gems: *"gives 1 gem per use"*). Owner ruled the
     middle reading from play. Neither pure reading was correct.
  2. **One option per Red Room slot** -- 3 action ids, `N_ACTIONS` 376 -> 379,
     appended, no existing id shifts. Resolves the wiki's silence on two reds
     in one hand.
  3. **Reachability first, effect after** -- two PRs, in that order. See below.
  4. **Exempt colour-selective drafting AND rework the Silver Key** so its
     exemption is real. This is the expensive ruling and it was taken with the
     collision surfaced: it puts the Crown-effect PR into the same code as
     `prism_key`, so **those two can no longer run in parallel.**

  **The Crown cannot be picked up in the sim at all today, for a reason
  unrelated to its effect.** `spawn_rooms: ["room_46"]` is dead:
  `roll_special_spawn` is reached only from `items.py:187` under
  `range(room.items.additional_max)`, and `room_46` has `additional_max: 0`.
  Worse, `room_46` is an **area-graph node** reached via `Game.travel_to`, which
  never calls `roll_room_items` for it. Verified by execution. So implementing
  the effect alone would have given a correct mechanic that nothing can ever
  trigger -- **the mirror of the "contents before the gate" lesson**, and the
  owner sequenced against it. `sanctum_key_room_46` sits in the same dead pool
  marked `implemented: true` with no `reachability` field: **a latent falsehood
  in the data**, worth its own look.

  **Generalisable, and this is the third time it has bitten:** a blocker is a
  claim about the world, and it decays exactly like a size estimate. This one
  was written confidently enough to carry a file:line, and the file:line was
  wrong too. **A `blocked_on` string is not evidence; re-derive it before
  building on it, and treat a precise-looking citation inside one as a reason
  for more suspicion rather than less.**

- **2026-08-12, the config digest is ~185 lines, not ~15, and it is a two-part
  PR -- the first part being a defect nobody had recorded.**

  **The unrecorded defect:** `env/blueprince_env.py::_serialize_config_value`
  (lines 20-33) returns `None` for any value that is not
  `frozenset`/`bool`/`int`/`str`, and lines 51-53 then skip it. `draft_counts`
  is a `dict`, so **it is silently dropped from every `day_config` diff.**
  Measured over a 5-day chain under `all_unlocks_config`, seed 42: day 1
  reconstructs exactly; days 2-5 all mismatch, live `draft_counts`
  `{'gymnasium': 1, ...}` against reconstructed `{}`. So **multi-day replay is
  already not exact from day 2 onward, on the working trainer path**, entirely
  independently of the wrong-preset bug the digest exists to catch.
  `draft_counts` feeds the observation (`env/obs.py:549`) and gates upgrade-disk
  offers (`engine/upgrades.py:275,310`) and the Treasure Trove pile.

  **This inverts the digest's cost.** Shipped without that fix, the digest
  fires on **100% of legitimate multi-day day>=2 records** rather than 0% --
  verified: match was `True, False, False, False` unpatched, `True` for all five
  days with a two-line dict branch added. The `draft_counts` fix is therefore
  a behaviour fix in its own right, lands first, and carries its own test.

  **It also falsifies a verified-facts entry.** *"`train.py` filters records by
  their own `unlocks` stamp and rebuilds the config from that same stamp, so the
  two cannot disagree"* is true of the **preset** and false of the whole config:
  nothing checks `day_config`, and `day_config` is precisely where the
  reconstruction is lossy. Severity stays low-ish -- `draft_counts` gates
  upgrade-disk offers, not the common draft/travel actions -- but the claim as
  written is wrong.

  **Design ruling, taken as assume-build:** hash **only non-default fields**,
  canonicalised (`frozenset` -> sorted list, `dict` -> key-sorted, `Path` ->
  `str`), `json.dumps(sort_keys=True)` -> `blake2b(digest_size=8)`. Never
  `hash()`. `GameConfig` is **not frozen and not hashable at all**
  (`__hash__ is None`) -- 63 fields, 11 frozensets, one dict, one `Path | None`.
  The non-default filter is what makes the corpus survivable: `config.py` took
  **47 commits since 2026-06-01**, ~40 of them field additions, and hashing every
  field would invalidate the whole corpus roughly weekly. **Known hole,
  accepted: a change to a field's *default* is invisible to the digest** (2 real
  instances in ~10 weeks, always a deliberate semantics PR). Mitigation is
  procedural -- pair a default change with deleting the corpus, the convention
  `n_actions` already carries. Do not close it by hashing defaults; that
  reintroduces the weekly churn.

  **Missing digest is refused, not defaulted**, in `behavioral_cloning` only,
  via a new `ConfigDigestError(DemoError)` raised from `config_for_record` --
  the single choke point, per the precedent at `UnstampedDemoError`.
  `web/replay.py` keeps its deliberate asymmetry and only **flags** a mismatch
  in the `divergence` dict; raising there would 500 the replay UI.

  **The corpus is disposable, which is what licenses all of the above.**
  `runs/postfix-v2/demos.jsonl` is the only demo file on disk -- 2 records,
  untracked (`.gitignore: runs/`), and **already unloadable**: `n_actions=311`
  against today's 376, so `StaleDemoError` rejects both. Two comments assert the
  opposite and are now false (`behavioral_cloning.py:319` and
  `tests/test_behavioural_cloning.py:4`, both "no real demos.jsonl exists
  anywhere in the repo yet"); they get swept with this work under the
  comments-state-current-behaviour rule.

- **2026-08-12, observation and action width changes are ACCEPTABLE: a retrain
  is already required.** Owner. This unblocks the whole remaining item backlog,
  which #227 had just re-sized as M-or-larger precisely because every item costs
  a width change.

  **What this permits, concretely:**
  - `gear_wrench` -- a `_CARRYOVER_KEYS` entry (obs width) **and** a
    room-choice action (action width). Both were the blocker; neither is now.
  - `chronograph` -- new redraw-history state plus a rewind action.
  - `prism_key` -- a special-key choice action.
  - `the_axe` -- a Room Directory action plus a permanent gem-cost override
    carried across days.
  - `crown_of_the_blueprints` -- within-day pool removal, the only one of the
    four that needs no new width at all.

  **What it does NOT license.** The standing rule is *"model correctness
  outranks observation/action-space stability while no run is live -- but record
  every width change."* The recording half still applies: every PR that moves
  `N_ACTIONS` or `len(_CARRYOVER_KEYS)` states the before and after, and
  confirms **no existing id shifted** (append at the end; a mid-array insert
  invalidates a policy's learned embedding far more deeply than a bound change).

  **`battery_pack` is still awkward for an unrelated reason** -- its cost is a
  37-call-site signature change to thread `rng` into `grant()`, not a width
  change. This ruling does not make it cheaper.

- **2026-08-12, three owner rulings, and a new `meta.wont_implement` marker to
  hold them.** "Blocked" and "decided against" were the same field; they are
  not the same thing, and conflating them left permanent exclusions sitting in
  the backlog forever looking like pending work.

  1. **Trophies are achievement-only and need no effects.** `trophy_of_wealth`
     stays `implemented: true` -- it is a real 100-coin Showroom purchase an
     agent can make, with `effects: []` deliberately. Nothing further queued.
  2. **The Magnifying Glass is decided against**: puzzle-only effect, and the
     sim has no lore layer and will not gain one.
  3. **The Key of Aries is decided against**: no RL policy will learn the
     castling puzzle, and its payoff is already granted regardless --
     `royal_scepter_found` defaults `True` **deliberately**, so the scepter is
     exercised as a mechanic without the unlock chain.

  **The consequence I surfaced before acting, which changed the shape of the
  ruling:** the Magnifying Glass's own effect is puzzle-only, but it is the
  **sole input to the Burning Glass**, which has no spawn source of its own and
  is one of only **two** ignition tools. Dropping it from the spawn pools would
  have silently removed an ignition path and one of the sundial's two lighting
  routes. Owner ruled: **keep it spawning, stop counting it.**

  Deleting the records outright was also rejected: `env/obs.py` enumerates the
  `items` array **positionally**, so removing `magnifying_glass` at index 9
  would shift 92 later items -- **a retrain trigger for a bookkeeping change.**

  **`meta.wont_implement` is mutually exclusive with `blocked_on`**, enforced by
  the validator and pinned by a test: a blocker names something missing that
  could be built; `wont_implement` records a decision that it never will be.

  **The validator now prints the split**: `102 special items (9 unimplemented,
  2 deliberately not modelled)`. Previously the backlog number could only be
  obtained by hand-counting the JSON -- which is how I came to assert twice that
  the validator already reported it.

  **The real remaining backlog is 9**, not 12: `battery_pack`, `chronograph`,
  `gear_wrench` (cheap); `prism_key`, `crown_of_the_blueprints`, `dowsing_rod`,
  `the_axe` (real but understood); `telescope`, `file_cabinet_key` (blocked on a
  subsystem).

  **A process note worth keeping:** I mutation-tested the new validator rule by
  editing the data in place and reverting with `git checkout --`, which wiped
  the *intended* uncommitted changes in that same file along with the mutation.
  Mutation-test against a copy, or stash first -- never `git checkout` a file
  that is holding work you want.

- **2026-08-12, TASK 22 IS COMPLETE -- and its final step is cancelled, on
  evidence.** Phases 0-6 landed across #200-#209; phase 7's allowlist split
  landed in #206. The remaining half, **"delete `implemented`/`blocked_on`", is
  NOT being done, because the premise it rested on turned out to be false.**

  **The premise:** a per-item registry makes implementation status *derivable*,
  so the asserted fields become redundant. **The measurement, from #217's
  census and a direct check:**

  - 12 items are `implemented: false`. **Exactly 1 of them is in any registry.**
  - 46 of 54 items with `effects: []` are not found in any registry, and 60 of
    123 such rooms -- because **the registries cannot see hand-written branches
    in `game.py`**. That is why #217's census says "not found in those
    registries" rather than "genuinely inert".
  - **`chronograph` is in a registry AND `implemented: false`** -- its
    Tomorrow-Rooms bias is wired (#201), its redraw rewind is not. So registry
    membership does not even imply full implementation.

  **And `blocked_on` carries something no registry can derive: WHY.** "The
  Telescope needs constellation activation", "the Axe needs a permanent
  gem-cost override layer", "the Trophy of Wealth's purchase path is
  unverified end to end" -- none of that is a fact about handler presence.
  Deleting the fields would trade information nobody can reconstruct for a
  check covering 8 of 54 items.

  **What the registry DID deliver is the part worth keeping**: #217 wired four
  validators that were previously called only by tests, so a typo'd id now
  fails the data validator; and the census makes "empty and unregistered"
  visible for the first time. That is the derivable half. The reason half stays
  in data, where a human writes it.

  **Final state: item-id debt 58 -> 1** (`microchip` in `shops.py`, which is
  where all three chip sources legitimately live), 38 pairs reclassified as
  permanent architecture, tag pairs 36 -> 22, and `game.py` and
  `special_items.py` carrying no item-id debt at all.

  **The generalisable lesson: a refactor plan written before the measurement
  should be re-checked against it, not executed on faith.** Three of this
  plan's steps changed on contact -- phase 3's scope (the shared-tag
  contradiction), phase 4's shape ("folds" were really first-match-wins chains
  that mutate state), and now phase 7's deletion. Each was written by a careful
  pass that simply could not see what the work would reveal.

- **2026-08-12, the Satellite Dish packet gate is open. Experiments phases 5-8
  are complete.** Keyed on `cfg.satellite_dish_unlocked`, the permanent
  carry-over flag the Apple Orchard sundial sets. Live: **6 of 8 packet triggers
  and 4 of 8 packet effects**; the six that stay inert each have a permanent
  reason (no wall clock, no interactive map, no Pantry-stocking mechanic, no
  reservoir room, the owner-ruled-out Crate Tunnel, no lockpicking stat).

  **The trap this PR existed to avoid, and how it was avoided.**
  `base_trigger_ids` / `base_effect_ids` are built at load time as
  `pool == "base"` with **no `implemented` filter** -- always safe, because every
  base record is implemented, so the distinction never had to exist. The packet
  breaks that assumption. Appending packet ids to those tuples is the obvious
  one-line implementation and would have made **six dead records drawable and
  silently inert** -- an agent could select an experiment that does nothing and
  never learn otherwise.

  Solved **at load time**, not draw time: `packet_trigger_ids` /
  `packet_effect_ids` are built as `pool == "packet" and implemented`, so every
  consumer gets a safe-by-construction id set rather than relying on draw-time
  diligence. Verified: no inert id appears in either tuple.

  **Verified empirically, not argued.** With the flag **False**, offers are
  **byte-identical to `HEAD` across 500 seeds** (independently reconfirmed over
  200). With it **True**, packet records appear. Across 4000 sampled draws in
  both states, **no inert record was ever offered.** `test_draft_stats.py`
  unmoved at 22.

  **My brief said "eight of sixteen records are inert". It is six** -- 2
  triggers + 4 effects. I repeated the wrong figure twice; the agent checked the
  data rather than taking it.

  **A documented simplification worth knowing:** Packet Management's own
  >=8-of-20 selection screen is **not** modelled. Every implemented packet
  record becomes sample-eligible the instant the flag is set.

  **An adjacent pre-existing gap, flagged not touched:** `gain_star`'s
  `resource_or_gate` availability is **not enforced by `_effect_offerable` at
  all** -- only `day_or_packet_gate` and `cross_column_exclude` are -- so
  `gain_star` is always offerable regardless of stars, veteran mode or packet.
  Unchanged by this PR, but real.

- **2026-08-12, three packet effects implemented; four remain genuinely
  blocked.** Live now: `unseal_antechamber_door`, `random_item_then_zero_keys`,
  `half_steps_for_dice`, joining the already-built `keys_per_30_steps`. Still
  inert with real blockers: `pantry_fruit` (no Pantry-stocking mechanic),
  `reservoir_water_level` (no reservoir *room* -- it is an area node only),
  `remove_tunnel_crate` (Crate Tunnel, owner-ruled out of scope),
  `permanent_lockpicking_skill` (no such stat).

  **The subtle correctness call: the unseal effect deliberately does NOT credit
  the lever trigger.** It calls `Game._open_segment` directly rather than
  `_open_north_door`, and never calls `on_lever_pulled`. Both of those exist to
  attribute a genuine *player* lever pull to the `antechamber_lever_pull`
  trigger and the env's `north_door_opened` reward flag. Routing an unrelated
  experiment effect through them would have been misattribution wearing the
  costume of code reuse -- the effect would have silently advanced a trigger the
  player never fired.

  **Two-part effects apply in the stated order, and the second half is
  unconditional.** `half_steps_for_dice` floors (7 -> 3, verified on an odd
  count), and **grants the dice even when the step loss alone would end the
  day** -- the alternative silently drops the reward on exactly the days it
  matters most.

  **A pre-existing gap found and deliberately left:** `Game.insert_disk` (the
  only `terminal_access` call site) and `Game.choose_upgrade` never call
  `_check_termination`, so a day ended by a step-draining effect there is caught
  one action later and reported as `"dead_end"` rather than `"out_of_steps"`.
  **Already latent for `steps_for_gold` and `set_steps`**, so not introduced
  here; documented rather than patched, because calling `_check_termination`
  mid-effect risks terminating inside `Game._place_room` before that same call's
  later ON_PLACE hooks run -- a worse bug than the mislabel.

  **No invented magnitudes.** The wiki gives no ordering weights for which
  Antechamber door unseals and no published item pool for the random grant, so
  `magnitude.weighting` and `magnitude.item_pool` stay `null`; the effect uses
  the existing `EXTRA_ITEM_TABLE` and its existing `extra_item_kind` substream
  rather than a new table nobody published.

  **`or_packet` still hardcoded `False`.** The gate is the last step.

- **2026-08-12, six of the eight Satellite Dish packet triggers are wired.**
  Experiments phases 5-8, first slice. `speed_40_seconds` and `map_view` stay
  inert and always will -- no wall clock, no interactive map.

  **Both triggers I flagged as uncertain turned out to be expressible, because
  the concepts exist under different names:**
  - `fireplace_draft` -> `Room.has_fireplace`, already used by
    `effects/rooms/cloister.py` (Cloister of Veia), Dining Room caveat included.
  - `terminal_access` -> **`disk_reader` IS this codebase's "terminal"**,
    deliberately renamed to dodge a name collision, as
    `docs/upgrade-disks-design.md` says. Scoped to a successful disk insert.

  **The subtle catch: two independent code paths open the same Antechamber
  lever.** The Weight Room's south lever and the Greenhouse's Broken Lever
  target the **same segment** through wholly separate guards, so a
  Weight-Room-then-Greenhouse day would have double-counted a "different lever"
  trigger. Tracked with a per-day distinct `set` on `ExperimentState` (mirroring
  `GameState.areas_visited`), not a counter, and pinned by a dedicated test.
  **A counter would have looked correct and been wrong only on the one day
  ordering that matters.**

  **A stale data note found and corrected**: `tomorrow_room_draft.meta.notes`
  claimed no Tomorrow flag existed in `rooms.json`. False --
  `room.is_category("tomorrow")` is in production use at `game.py:2238` for the
  Clock Tower's own day-end pulse.

  **Ordering is deliberate: contents before the gate.** `or_packet` stays
  hardcoded `False` and `draw_offers` filters on `pool == "base"` regardless, so
  the packet is still never sampled. Flipping the gate first would have made 16
  records drawable while 15 did nothing -- reachable content that silently does
  nothing, the inverse of the unreachable-feature failure and just as invisible.

  **Room-id debt +1** (`experiments.py: "dining_room"`), matching the identical
  entry `special_items.py` already carries for the same Dining Room comparison.

- **2026-08-12, the microchip record is finished and consistent. Owner: "model it
  as I described."** Audited against their description; three inconsistencies
  found, of which only two were real.

  **1. `implemented: false` was stale for the THIRD time on this one record.**
  It said `blocked_on: orindian_ruins_not_reachable`, which #214 falsified. The
  chain is complete and was re-verified end to end: three sources
  (vase carry-over, West Path dig, Grotto pedestal take), the gate, reachable
  Ruins, a lightable sundial, tier-2 give-only trading. Now
  `implemented: true`, `blocked_on: null`, and `meta.reachability` removed --
  the validator only requires it while `implemented` is false.

  **This record alone has had three stale blockers**: `outer_areas_not_modeled`
  (false once the area graph landed), `grotto_pedestal_chip_not_modeled` (false
  the moment #210 merged), and `orindian_ruins_not_reachable` (false the moment
  #214 merged). Each was true when written. **A blocker on a record whose
  feature is actively being built goes stale about as fast as it is written**;
  the answer is not better prose but a derived check -- the registry
  validators now wired into `validate_data.py`.

  **2. `docs/special-items-design.md` was false in three places** -- it said the
  microchip "remains inert (`blocked_on: outer_areas_not_modeled`)", that "chip
  holders/placement are not modeled (outer areas out of scope)", and it never
  mentioned the third chip at all. All corrected, including the respawn rule and
  the `counts_flag` arithmetic.

  **3. NOT a discrepancy: the vase accepts the Morning Star.** The owner named
  "sledgehammer or power hammer", and the `smash` tag also carries
  `morning_star`. The wiki settles it -- **"A Sledge Hammer or equivalent is
  needed to smash the vase"** -- so the tag is right and the owner named the two
  they use. Checked before changing anything; changing it would have narrowed
  correct behaviour to match an incomplete list.

  The wiki also independently confirms the respawn rule the owner gave: "If this
  microchip is lost without being placed, it reappears on the table right beside
  the broken vase the next day."

- **2026-08-12, demo replay's two silent-failure paths are closed.** Both had
  the same shape: **the code chose to continue rather than complain**, handing
  back plausible-looking data instead of raising.

  1. **Silent truncation.** `replay_demo` broke out on a TERMINAL phase and
     returned normally, discarding the remaining recorded actions -- one record
     dropped 24 of 33 and raised nothing. Now raises. **Verified no legitimate
     replay ends early**: both producers (`web/play.py::PlaySession._close_day`,
     `rl/train.py::EpisodeRecorder.on_episode_end`) append the action *before*
     checking termination, and `Phase.TERMINAL` is set in exactly one place, so a
     record's last action is always the one that ends the day. Pinned by a test.
     The new branch is genuinely reachable, not theoretical: **7 of 659** tampered
     replays hit it, and seed 24 reproduces it deterministically.
  2. **A missing `unlocks` stamp defaulted to `"all"`** -- which for a legacy
     fresh-save record is precisely the tampering the divergence test simulates.
     Now raises `UnstampedDemoError`, following the module's own precedent
     (`StaleDemoError` refuses outright rather than guessing) rather than
     `web/replay.py`'s tolerant default, which exists because that path has a UI
     to surface the doubt to a human. This one has no such side-channel.

  **The defect was at TWO sites, not the one I cited.** `load_demo_dataset:149`
  *and* `config_for_record:199` -- and `replay_demo` calls the latter directly,
  so fixing only the line in my brief would have left the main path still
  guessing. Both now route through one `_record_unlocks()` helper.

  **No existing test needed changing**, because every one builds records via
  `synthetic_demo_records`, which always stamps `unlocks`. And the one real demo
  file on disk (`runs/postfix-v2/demos.jsonl`, 2 human days) already carries
  `"unlocks": "fresh"`, so nothing real breaks.

  **Still open, and needing a ruling:** the config-digest recommendation. These
  two fixes close the *silent* paths; they do not make a wrong-preset replay
  detectable in general, which remains ~17% on the synthetic fixture and ~72%
  on a human-like action mix.

- **2026-08-12, the sundial takes any ignition tool: trust the wiki.** Owner,
  resolving the conflict #215 recorded rather than decided. The wiki says "an
  ignition tool"; an owner play-report had named the Burning Glass specifically.
  **The Torch lights it too.**

  No behaviour change -- #215 already implemented "any tool in `ignition.tools`",
  on the reasoning that a per-target tool restriction would be new machinery for
  a fact the owner themselves flagged as probably just what was in hand. The
  ruling confirms that call.

  What *did* need changing is the record: `special_items.json`'s ignition note
  described the conflict as **open**. Leaving it would have been the same
  stale-reason failure this session has now hit thirteen times -- a note
  outliving the question it described. Updated to state the ruling.

  **Worth generalising: "owner play overrides the wiki" is a tie-breaker, not an
  automatic win.** Here the owner read their own observation as weaker evidence
  than the published text, because a single play-report cannot distinguish "this
  tool is required" from "this tool was in my hand". Surfacing the conflict
  rather than resolving it silently is what let them make that call.

- **2026-08-12, the Orindian Ruins are reachable end to end, and widening the
  action space destabilised three tests whose invariants were already
  luck-dependent.**

  Built by mirroring `treasure_trove_blackprint` at all six of its sites; every
  one mapped cleanly. **Deliberate retrain trigger: `_CARRYOVER_KEYS` 14 -> 15**,
  so the `carryover` Box widens `(14,) -> (15,)`. **`N_ACTIONS` is unchanged at
  375** -- `env/actions.py` derives a travel slot per graph node regardless of
  `modelled`, so flipping the flag is mask-only, exactly as documented.
  **Room-id debt +1**: `decks.py`'s pool gate names `throne_room`, inherently
  per-room, exactly as `treasure_trove` already is.

  **The three test failures were exposed, not caused.** The agent bisected them
  to `private_drive` alone -- the cheapest new destination -- and correctly left
  them red rather than adjusting seeds.

  1. **`test_day_replays_clean_through_colour_pending`** required all 5 seeds of
     a *purely random* walk to open a forced Secret Passage door. That held only
     because the action set was narrow. Fixed by **steering the rollout to prefer
     opening doorways** -- the test's stated point is that a day replays clean
     *through* colour selection, so passing through it should be guaranteed, not
     hoped for.
  2. **`test_replay_demo_raises_on_wrong_preset`** pinned one trajectory and
     asserted a wrong-preset replay *must* diverge. **Measured on `HEAD`, before
     this change: it diverges in only 2 of 12 trajectories.** The test was
     already passing on luck; `action_rng_seed=3` was simply one of the two.
     Now sweeps 3 game seeds x 20 action seeds and asserts the detector fires at
     all (10/60), so it cannot pass on a single lucky draw.
  3. **`test_pretrain_raises_agreement_with_demo_actions`** asserted an absolute
     `acc_after > 0.5`. Untrained accuracy tracks 1/(legal actions), so an
     absolute bar silently encodes the action-space size. Measured: **0.147 ->
     0.441, a 3.0x improvement** -- BC learns fine. Replaced with
     `acc_after > 2 * acc_before`, which is what the docstring actually claims.

  **This is the third and fourth vacuous-by-luck test found this session**,
  after `test_no_offer_list_exceeds_eight_rows` and the pinned give-only set.
  The pattern is consistent: **a test that constructs its scenario by random
  rollout, or asserts an absolute bar over a stochastic quantity, passes on the
  seed it was written with and silently stops testing anything later.**

  **Real gap recorded, not fixed:** a fresh-save record replayed under the
  all-unlocks base diverges only ~17% of the time (10/60 measured). The rest
  replay to the end without any recorded action becoming illegal -- i.e.
  `replay_demo` can silently produce a wrong trajectory, which is exactly what
  that test's docstring says must not happen. Worth its own investigation.

- **2026-08-12, the Trading Post tier table was wrong in 54 places, not ~10,
  and the sweep exposed a misread datamined rule.**

  **My brief was wrong about three items.** It listed `ornate_compass`,
  `emerald_bracelet` and `cursed_effigy` as wiki-receivable. Verified against
  the raw page: **the tier-5 line carries no bold markers at all**, so every
  tier-5 item is give-only. The datamine says it outright -- *"The Upgrade Disk
  is in the list of items given as Tier 5 trades (which contains no other
  items)."*

  **Scope was 54 items.** The receivable/null gap was only half of it; the
  give-only side had the same gap (all 8 contraptions, 16 upgrade disks, 8
  sanctum keys, 6 tier-3 relics, and more). Also fixed a pre-existing bug:
  `master_key` and `sanctum_key_room_46` already carried `tier: 5` but were
  missing `no_receive`, so they were wrongly receivable before this branch
  existed. All 102 items now match the wiki.

  **Reward shaping moved and was deliberately left exposed.** `inventory_value`
  keys off `tier`, so re-tiering changes worth: 1 item to tier 1 (-2.0), 10 to
  tier 3 (+4.0 each), 30 to tier 4 (+9.0 each), 10 to tier 5 (+34.0 each). A
  plausible held inventory goes **88.0 -> 161.0, a 1.83x increase**.
  `items.json::special_item_values` was NOT adjusted to compensate -- doing so
  would have hidden the effect the PR exists to expose. **No A/B was run.**

  **`t5_special_chance: 50` was a misreading, and the sweep made it visible.**
  The wiki's *"50% chance to offer Allowance Token"* is the split between the
  two tier-5 specials, **not** a 50% chance of falling through to the cycle.
  With tier 5 correctly all-give-only, that fall-through self-edged and
  `master_key` had **no trade offer in 24 of 60 seeds**. Corrected to 100.
  Tier-5 items now always trade into Allowance Token (~52% measured, matching
  the published 50%) or the Upgrade Disk -- and when the disk is unavailable it
  decays to a tier-4 item, which incidentally reproduces the wiki's *"tier 5
  items can sometimes trade for tier 4 items"*. **Not modelled**: that decay is
  the wiki's menu-timing quirk, which this engine has no notion of.

  **Three tests changed, none by seed.** One was a change-detector pinning the
  give-only id set literally (the thing `CLAUDE.md` warns against) and now
  derives it from the registry; one asserted an item was untradeable that is now
  correctly tier-1 give-only; one called `trade()` unconditionally and now
  checks for an offer first. Each reflected a genuine behaviour change.

- **2026-08-12, the Trading Post now has a give-only concept, and a vacuous
  test was found doing the opposite of its job.**

  `_roll_trade_graph` built each tier's cycle from ONE id list serving as both
  the give side and the receive side, so an id could not be removed from only
  one. Each tier's cycle is now built over **receivable ids only**, with
  give-only ids attached as extra sources resolving into it and nothing pointing
  back. `microchip` (tier 2), `treasure_map` and `watering_can` are marked
  `no_receive`, all three confirmed unbolded (give-only) on the wiki's
  Trading Post page.

  **Deliberately shaping-neutral**: `items.json` has `untradeable = 6.0` and
  `by_tier["2"] = 6.0`, so the microchip's tier change leaves `inventory_value`
  identical; the other two keep their tiers. **The approved tier-table sweep --
  adding tiers to the ~8 wiki-receivable items currently `tier: null` -- is held
  for its own PR**, because it does change shaping and adds cycle members.

  **`tests/test_obs_items.py::test_no_offer_list_exceeds_eight_rows` was
  vacuous, and pre-existing.** It asserted `trade_offers()` never exceeds
  `TRADE_OFFER_ROWS` (8). Measured against `HEAD` *before* this PR: with all 24
  tradeables held, **36 of 60 seeds exceed 8**, up to 24 offers. The test passed
  only because seed 3 happened to yield 4.

  The agent's fix was to change the seed to one that still passes. **Rejected --
  that is enshrining wrong behaviour, and picking a lucky seed is exactly how
  the test came to be vacuous in the first place.** Replaced with a test of the
  property that is actually true and actually matters: `_encode_trade_offers`
  slices `offers[:TRADE_OFFER_ROWS]`, so **the Box is never overflowed**. It
  sweeps 40 seeds and **asserts that at least one exceeds the cap**, so it can
  never again pass without exercising truncation.

  **The real gap it exposes, for the owner:** `TRADE_OFFER_ROWS = 8` is
  commented "generous; 24 tradeables, real sessions hold far fewer", but a full
  inventory routinely produces 10-24 offers, and **everything past the eighth is
  invisible to the policy.** Raising the cap is an observation width change and
  therefore a retrain trigger, so it is recorded rather than done.

- **2026-08-12, `throne_room.meta.effect_text` corrected in BOTH sources.** It
  claimed "entirely out of scope, no effect modeled" while two of its effects
  are modelled: the north Antechamber lever
  (`effects/rooms/throne_room.py::provides_lever`) and the Mora Jai box's +2
  allowance (`allowance_token_throne_room`, `guaranteed_in`). Only the crown
  objective is genuinely out of scope.

  **`throne_room` is supplemental-sourced** -- present in
  `tools/supplemental_rooms.json`, absent from `tools/raw/`. Editing
  `rooms.json` alone would have been **silently reverted by a future
  re-ingest**, the hazard `HANDOFF.md` §7 names. Both files updated; both still
  parse; 170 rooms, order unchanged.

  This is the concrete cost of the `effects: []` ambiguity recorded earlier: the
  room's `effects` array is empty because its behaviour lives in the room
  registry and a guaranteed item, and the prose note drifted to match the array
  rather than the code. **Wiring the registry validators into
  `validate_data.py` is what would have caught it mechanically** -- done since,
  in the work the task 22 closing entry describes.

- **2026-08-12, the Microchip gate is corrected. Phase 1 of the branch.**
  `Gate.counts_flag` lets an item gate count an in-place copy the player does
  not carry; `three_microchips` keeps `count: 3` and gains
  `counts_flag: "grotto_chip_in_place"`, emitted by `_gate_ctx` while
  `GameState.grotto_chip_taken` is false. All four rows of the owner's model
  verified independently of the tests written alongside the code.

  **`grotto_chip_taken` is day-scoped with no carry-over key**, and that is the
  design point worth remembering: the owner said match `entrance_vase_broken` /
  `outer_chip_dug`, but those are carry-over keys because they record a
  permanent *discovery*, with the day-start re-grant layering respawn on top.
  The Grotto chip has no discovery -- it is in the pedestal from day 1 -- so the
  respawn rule falls out of the field defaulting `False` at every `reset()`.
  **Matching their semantics meant not copying their plumbing.**
  `_CARRYOVER_KEYS` stays at 14, so the observation width is untouched and this
  is **not a retrain trigger.**

  **Two tests were deleted, correctly.**
  `test_two_microchips_do_not_open_orindian_ruins` and
  `test_three_microchips_open_orindian_ruins` asserted the gate needs exactly
  three *held* -- they pinned the bug. Replaced by four tests, one per row, with
  the "next day" row driven through a real second `Game` on the shared config
  rather than a hand-built context, so it exercises the actual respawn path.

  **Nothing became reachable.** Both nodes stay `modelled: false`, so
  `env/actions.py` still offers no travel there. The gate is now correct and
  still unreachable, deliberately -- the reachability arm is its own PR.

- **2026-08-12, task 22 is substantively complete. `ITEM_DEBT` = 1.** Phase 6
  migrated `treasure_map` and `moon_pendant`; the single remaining entry is
  `microchip` in `shops.py`, which the Microchip branch owns.

  Journey: **58 (module, item_id) pairs measured at phase 0 -> 1 of genuine
  debt**, with 38 reclassified as permanent architecture (priority tuples,
  family constants, named draft conditions, trade-graph outcomes, and the
  `treasure_map` data-section load). Tag pairs 36 -> 22. `game.py` and
  `special_items.py` now carry **no item-id debt at all**.

  **`treasure_map` migrated after all.** I briefed that declining might be
  correct, because its two draws share one substream across two functions
  (`on_arrive` picks the cell, `dig_all` picks the reward) and are sequenced by
  gameplay rather than code adjacency. Both extracted 1:1 with nothing
  interposed, so the ordering held.

  **The verification is the part worth keeping.** The static grep-sequence check
  is *useless here by construction*: the new module calls
  `game.rng.choice(ITEM_ID, ...)`, so both draws stop being greppable literals
  and read as *removed* rather than relocated. What settled it was dynamic --
  patch `Rng.{choice,shuffle,chance,roll_weighted,randint}` to log every
  `(method, label, result)`, drive a full seeded game against both trees, and
  diff the logs. **Byte-identical across four seeds.** Independently confirmed
  by a state digest over five seeds, identical before and after.

  **Generalisable: when a refactor moves an RNG draw behind a constant, string
  search cannot verify it. Compare execution, not source.** This is the fourth
  variant of one hazard this session -- `silver_key_bias` behind a same-named
  local, RNG labels behind constants, `effects: []` behind the registry, and now
  draw labels behind `ITEM_ID`. Every time, a string search returned a confident
  wrong answer.

  **One prediction of mine was wrong**: I expected the room-id allowlist to
  shrink again (it had for three consecutive migrations). It did not -- neither
  of these items touches a room-id literal.

  **Phase 7's remaining half -- deleting `implemented`/`blocked_on` -- is
  deliberately NOT done**, and should not be until the existing registry
  validators (`registered_rooms()`, `validate_room_registry`,
  `validate_capability_registry`, `validate_item_registry`) are wired into
  `validate_data.py`. Deleting those fields now would
  remove the only machine-readable statement of what is inert, in exchange for
  nothing.

- **2026-08-12, `effects: []` in `rooms.json` does NOT mean a room is
  effectless, and I read it that way.** Owner correction, and it overturns the
  analysis I gave against building the Ruins arm.

  I reported the Throne Room as "a rare, 5-gem, `effects: []` room -- plausibly
  negative for an agent". The owner: **it has a Mora Jai box (+2 allowance) and
  a north Antechamber lever.** Both are **already modelled**, just not in the
  `effects` array:

  - `effects/rooms/throne_room.py` calls
    `provides_lever("throne_room", pull_north_lever)`.
  - `allowance_token_throne_room` carries `guaranteed_in: ["throne_room"]` and
    the `allowance` effect.

  **The lesson is structural and it cuts against task 22.** The registry
  migration deliberately moves behaviour OUT of the `effects` array and into
  code, which is the point -- but it means **`effects: []` is now uninformative
  as a signal of what a room or item does.** I noted earlier that the registry
  makes `implemented` *derivable*; the flip side is that it makes `effects: []`
  *misleading*, and I then made exactly that mistake within the day. Anything
  reading `effects` to judge whether something is inert must also check the room
  registry, `provides*`, and guaranteed items.

  **`throne_room.meta.effect_text` is also wrong**: it says "entirely out of
  scope, no effect modeled" while the lever and the token are both modelled.
  Fix when the Ruins arm lands.

  **Ruling: build the whole Ruins arm.** Owner, on the corrected facts. The
  Throne Room is worth adding to the pool for the lever and the allowance token
  even though the Ruins themselves grant nothing further. My deferral
  recommendation rested on the room being effectless and does not survive.

- **2026-08-12, three owner rulings on the Microchip branch.**
  1. **Experiments phases 5-8 are AUTHORISED**, scoped honestly: the Apple
     Orchard sundial unlocks the Satellite Dish, whose packet is those phases.
     Only ~6 of 8 triggers and ~4 of 8 effects are expressible --
     `speed_40_seconds` and `map_view` never (no wall-clock, no interactive
     map), `reservoir_water_level` needs a room that does not exist,
     `remove_tunnel_crate` is the out-of-scope Crate Tunnel,
     `permanent_lockpicking_skill` needs a stat that does not exist.
     `keys_per_30_steps` is already implemented. **This reverses
     `docs/experiments-design.md`'s written deferral, deliberately and on the
     record** rather than by inference.
  2. **Build the full Ruins reachability arm** (see the entry above).
  3. **Build the no-receive trade concept AND sweep the tier table.** The table
     is already broadly wrong independently of this branch: `treasure_map` and
     `watering_can` are receivable in the sim but give-only on the wiki, and
     eight wiki-receivable items carry `tier: null`. A spot fix for the
     microchip alone would leave a known-wrong table wrong.

- **2026-08-12, phase 5a landed: `ITEM_DEBT` 27 -> 11**, cap lowered to match.
  The 11 remaining are exactly phase 5b's six RNG-adjacent items plus
  `treasure_map`, `moon_pendant` (phase 6) and `microchip`.

  **Refinement to the multi-carrier rule, from a deviation that was right.**
  The rule was "a tag carried by more than one item stays in data". `compass` is
  multi-carrier and was migrated anyway -- correctly, because **the rule's
  rationale is `CLAUDE.md`'s "published tables go in data", and `compass` has no
  parameters at all.** Nothing published moved into Python; it became one
  capability with two registrants, which is what `item_capability_any` exists
  for. OR-semantics verified preserved across both carriers.

  **So the rule is properly: a multi-carrier tag WITH PARAMETERS stays in data;
  a parameterless multi-carrier marker may become a capability.** By that test
  `smash` (3 carriers, no params) is also migratable; `dig_tool`, `lockpick`,
  `luck_bonus`, `metal_detector_spawns` and `allowance` all carry published
  numbers and stay.

  Phase 5a also shrank `tests/test_room_id_allowlist.py` -- `special_items.py`'s
  `"bedroom"` entry went stale once the Sleeping Mask loop moved out. **Second
  time an item migration has reduced ROOM debt as a side effect.**

- **2026-08-12, the Microchip branch's payoff is already in the training config,
  and nobody had recorded it.** Verified: `rl/train.py::all_studio_additions()`
  derives its set from the registry, `throne_room` is in it, and
  `all_unlocks_config` passes it wholesale. **`'throne_room' in
  all_studio_additions()` is `True` today.**

  So building the chain Grotto -> gate -> Ruins -> floorplan -> carryover ->
  `eligible_pool` delivers **zero new content for the config the agent actually
  trains on.** It matters only under `fresh_save_config`, which passes no
  `studio_additions` -- and there it adds a **rare, 5-gem, `effects: []`** room
  to the rare deck. `throne_room.meta.effect_text` says the room is "entirely
  out of scope, no effect modeled". Adding an expensive effectless rare is
  plausibly *negative* for an agent.

  **And the route is not real.** `blackbridge_grotto` is reached through
  `lab_steam_and_power`, which is `kind: "unmodelled", stub: true,
  retire_in: "PR-power-system"` -- it passes unconditionally, standing in for
  the unmodelled power system. `areas.py::stub_gates`' own docstring says
  anything measured through a stub is an upper bound. Flipping the nodes to
  `modelled: true` would make the Ruins "reachable" through a gate that does
  not exist yet.

  **Ruling to take: build the gate correction, not the reachability arm.** The
  gate is a live latent bug -- unsatisfiable in play, and semantically wrong per
  the 2026-08-12 owner ruling -- and fixing it is XS, changes no reachable
  behaviour, and stops the wrong model propagating into the next brief. The
  reachability arm is deferred **on its measured value**, not on difficulty.

  This is the third time this session that a feature looked worth building until
  someone checked whether it was reachable or whether its payoff already
  existed. **Check the payoff before costing the work.**

- **2026-08-12, the item-id allowlist is split into architecture and debt.**
  Pulled forward from phase 7 because phase 5's whole job is to drive the debt
  number down, and a conflated number cannot show that -- a successful
  migration and a wash looked identical.

  **`ITEM_ARCHITECTURE` = 37, `ITEM_DEBT` = 27** (sum 64, no overlap).
  `ITEM_DEBT_CAP = 27` enforces the asymmetry that makes the split worth
  having: **architecture may grow, debt may not.** Phase 5 will legitimately add
  priority-tuple members as chains extend; that must not be able to hide a
  failure to migrate anything.

  Architecture is four kinds: engine-owned priority tuples (the six `ItemHook`
  chains plus `DIG_PRIORITY` and the lockpick preference), id-prefix family
  constants, named draft conditions, and trade-graph/pipeline carve-outs.

  **The debt half is now a worklist, not a score:**

  - `game.py` (4): `keycard`, `paper_crown`, `power_hammer`, `silver_key`
  - `shops.py` (7): `car_keys`, `lunch_box`, `microchip`, `repellent`,
    `royal_scepter`, `silver_key`, `stopwatch`
  - `special_items.py` (16): `battery_pack`, `broken_lever`, `car_keys`,
    `compass`, `cursed_effigy`, `key_8`, `keycard`, `lunch_box`, `moon_pendant`,
    `royal_scepter`, `secret_garden_key`, `silver_key`, `sledge_hammer`,
    `sleeping_mask`, `treasure_map`, `watering_can`

  `treasure_map` and `moon_pendant` are **phase 6** (RNG-touching, migrate
  alone). `microchip` overlaps the Microchip branch.

  **Three corrections to my own taxonomy, all from reading the call sites:**

  1. **`sledge_hammer` is debt, not architecture.** Its only occurrence is the
     Mechanarium compartment fallback, on the same line and construct as
     `battery_pack` and `broken_lever` -- which I had already classified as
     debt. The same construct must classify the same way.
  2. **`compass` is debt.** It never appears in a priority ordering; it is a
     `_has_item_effect` tag-collision lookup. I had grouped it with the
     tool-preference question by association rather than by evidence.
  3. **`shops.py`'s `secret_garden_key` is architecture.** It sits in a
     `frozenset` beside three strings that are not item ids at all -- the same
     named-condition class as `placement.py`'s own exemption.

  **And a mislabel in my mutation plan worth remembering:** removing an entry
  for a still-present literal fires the *outside-the-allowlist* test, not the
  *stale-entry* test. The genuine stale-entry direction is only exercised by
  removing the literal from the **source** while keeping the dict entry. Both
  were verified separately; a plan that conflates them would let the stale-entry
  guard pass vacuously forever.

- **2026-08-12, phase 4 landed, and it moved the item-id debt UP -- correctly.**
  Numbers: **item tag pairs 27 -> 22**, **room id pairs 79 -> 78**, but
  **item id pairs 56 -> 64**.

  The increase is the design working, not a regression. The engine-owned
  priority tuples (`GEM_COST_PRIORITY`, `MOVE_STEP_COST_PRIORITY`,
  `COINS_GRANTED_PRIORITY`, `GEM_PAYMENT_WAIVER_PRIORITY`,
  `RED_ROOM_NEGATE_PRIORITY`, `FOOD_STEPS_PIPELINE`) **have to name their member
  item ids somewhere** -- that is what an explicit total order *is*. The
  alternative, a `priority=` number on each registration, is exactly what the
  owner rejected because it scatters the order across the modules it ranks.

  **Consequence: phase 0's "irreducible floor is ~8-10 of 58" is now wrong.**
  The floor is that plus the priority-tuple members -- call it **~18-22**. More
  importantly, **the item-id allowlist no longer measures one thing.** Part of
  it is genuine debt (an engine module branching on an item id) and part is
  permanent architecture (an arbitration order naming its members). A scoreboard
  that conflates the two stops measuring anything, which is the failure its own
  bidirectional check exists to prevent. **Phase 7 should split the allowlist
  into those two sections** rather than report one number.

  Bonus result: **the room-id debt fell without anyone targeting it.**
  `"hallway"` sat in `special_items.py` only for the Hall Pass's
  `is_category("hallway")` test; moving that into `hall_pass.py` (glob-excluded)
  removed a *room*-id literal from a scanned module.

- **2026-08-12, item handlers fire on game events, exactly like room handlers.
  The claim that "items have no natural event boundary" was wrong.** Owner
  challenged it directly and the challenge holds: a payment, a move, a coin
  grant and a red-room effect are game events, and an item handler on one is as
  legitimate as a room handler on `ON_ENTER`. The claim had been repeated across
  several PRs and shaped the phase 2 and 3 designs.

  **The real difference is arity and arbitration:**

  | | room handler | item handler |
  |---|---|---|
  | fire per event | exactly one | any number of held items |
  | signature | `(game, room, context_room) -> None` | must return a value |
  | conflict | impossible | routine, and rule-bearing |
  | order | irrelevant | decides the outcome |

  `fire(game, room, hook)` is called with *the* room the event is about and
  dispatches to that one room's handler. Two rooms never answer the same event,
  so **the room registry never needed arbitration -- the grid supplies
  exclusivity for free.** Items have no such guarantee: `gem_cost_modifier`
  must produce one number from N held items, and "only one waiver applies, no
  double-decrement" is a game rule something has to enforce.

  So the conclusion is not "avoid handlers" but **"use handlers, plus the one
  thing rooms never needed: explicit arbitration."**

- **2026-08-12, the phase 4 design, three owner rulings.**

  1. **Item modules register handlers on game events.** Item hooks
     (`ON_PAY`, `ON_MOVE`, `ON_COINS_GRANTED`, `ON_RED_EFFECT`, `ON_FOOD`),
     mirroring `Hook`. This is what makes the charge-consuming effects
     migratable at all -- an item that spends a Stopwatch charge cannot declare
     a value, it has to run code.
  2. **The engine owns one explicit priority tuple per chain**, in engine code:
     e.g. `GEM_WAIVER_ORDER = (EMERALD_BRACELET, FREE_HALLWAY_MOVES, STOPWATCH)`.
     Visible, diffable, testable in one place. **Never a `priority=` number on
     the registration** -- that would scatter the total order across 40 modules
     so no single place shows what beats what.
  3. **Context predicates belong to the item.** The Hall Pass registers its own
     hallway-from-hallway test rather than the engine hard-coding it, so each
     item's rule is self-contained. Accepted cost: item modules gain some grid
     and pending-draft knowledge.

  **What phase 4 actually covers, corrected.** The architecture pass called
  these six "folds", i.e. ordered reductions. **Five of six are first-match-wins
  priority chains and four mutate state** -- `move_step_cost` consumes a
  stopwatch charge, `on_coins_granted` accumulates `coin_interest`,
  `shield_negates` sets `shield_used`, `stopwatch_waives_gems` spends a charge.
  Only `food_steps` (Salt Shaker adds, then Silver Spoon doubles) is a genuine
  ordered fold. Anyone briefing this work from the word "fold" will build the
  wrong thing.

- **2026-08-12, the recorded phase table contradicted itself, and the
  contradiction is resolved against migrating shared tags.** The architecture
  pass listed phase 3 as migrating `luck_bonus`, `compass`, `dig_tool`,
  `lockpick`, `metal_detector_spawns` and `smash`, **and separately said those
  same six must stay in data** as shared parametric tags. Both statements were
  in this file.

  **Resolved: a tag carried by more than one item stays in data; singletons
  migrate.** Two reasons, the second decisive:

  1. The rooms rationale does not transfer. Task 17 kept shared parametric
     tags in data because `items.py::expected_yields` introspects them
     generically. **Nothing introspects item effect tags generically** --
     `SpecialItem.effect(tag)` is a keyed lookup, and every
     `for e in ... .effects` site in the engine iterates *room* effects.
  2. **`CLAUDE.md`'s standing rule settles it regardless: published tables go
     in data, not Python constants.** `lockpick` carries rates
     `[54, 35, 30, 19]`, `metal_detector_spawns` carries
     `{coins: 60, key: 25}`, `dig_tool` names three dig tables. Migrating them
     would put published numbers in Python -- which three earlier PRs had to
     undo in review.

  This also matches task 17's precedent exactly: singletons move, shared
  parametric stays. Phase 3's real scope was **8 tags, not ~12**.

- **2026-08-12, task 22 phase 2 landed, and the item registry is a fold, not a
  hook.** The primitive is `item_provides(item_id, ItemCapability, **params)`:
  the item declares only the *fact and its parameters*, and the **engine owns
  the fold** (`item_capability_sum` in `engine/effects/__init__.py`). No item
  module registers a handler function.

  This is the deliberate divergence from `room_hook`, and the reason it matters
  is worth keeping: a room has a natural event boundary -- the player standing
  in it -- so firing a handler there maps onto a real moment. **Items have no
  such boundary.** Item behaviour is overwhelmingly "the engine is about to
  charge N; ask every held item whether it changes N". Registering 40 modules
  against a constantly-firing hook would also make fold *order* implicit in
  import order, where today it is visible as sequential lines.

  **`SHOP_DISCOUNT` is a sum and therefore commutative, so phase 2 cannot by
  itself prove the ordering design.** The API is shaped so it does not need
  redesigning: params are stored per `(item_id, capability)` rather than
  pre-flattened, so phase 4's ordered folds become a *sibling* function walking
  the same registry in a caller-supplied order with a combine step. **Phase 4
  is where that gets tested for real** -- treat its ordered tuple as the
  load-bearing artefact and pin the current arithmetic before moving anything.

  **The data tag was deleted, not left alongside.** Once `coupon_book`
  registers the capability in a module, its `shop_discount` effect tag is a
  second source of truth for the same fact -- the defect deleted twice this
  week (`ignition_tool` #199, `silver_key_bias` #202). Building a registry
  while leaving the tag would have recreated the problem the registry exists
  to solve.

  **The tag allowlist shrank 6 -> 5 for `shops.py`: the first downward movement
  of the item debt**, and the measure phases 3-7 are judged by.

  **Brief error worth recording: there is no production call site for
  `validate_capability_registry` or `validate_room_registry`.** Both are
  exercised only by dedicated tests; nothing in `game.py` or
  `validate_data.py` invokes them. `validate_item_registry` follows that same
  pattern. So a typo'd id in any of the three registries is caught by the test
  suite, never by the data validator -- worth knowing before anyone assumes
  `tools/validate_data.py` covers it.

- **2026-08-12, delete the `silver_key_bias` effect record rather than wiring a
  reader.** Owner, resolving the binary question phase 0 raised.

  The silver-key draft bias is real and works, through an id branch:
  `game.py` tests `has(st, "silver_key")` and sets
  `state.special.silver_key_draft`, which `draft.py` reads. The
  `silver_key_bias` effect entry in `special_items.json` was a **second,
  never-consulted source of truth** for behaviour already implemented
  elsewhere -- the `ignition_tool` shape, but harder to detect, because the
  item is `implemented: true` with `blocked_on: null` so no existing check had
  anything to say about it.

  **Deleting is the right direction and worth stating as a general rule:
  when a record and an implementation disagree about where behaviour lives,
  and the implementation works, the record is what is redundant.** Wiring a
  reader purely to justify an existing record would be inventing a consumer
  for data nobody needs.

  Removed in four places -- the item's `effects` list (now `[]`),
  `KNOWN_ITEM_EFFECT_TAGS` in `validate_data.py`,
  `DEFERRED_UNREAD_TAGS` in the phase 0 tag scanner, and the tag inventory in
  `docs/special-items-design.md`. All 10 silver-key tests stay green; the
  mechanic never moved. **Zero-reader tags 4 -> 3**, and the three that remain
  (`crown_of_blueprints`, `dowsing_rod`, `gear_wrench`) are all legitimately
  deferred against real blockers.

  Note the deletion order was itself a check on the ratchet: removing the tag
  from the data made `test_deferred_unread_tags_are_real_tags` fail before the
  scanner was updated, which is the scanner refusing to let its own list go
  stale.

  **This closes the second of the two dead-tag findings.** `ignition_tool`
  went in #199; `silver_key_bias` here. Both were found by looking for tags
  nothing reads, and that check now exists permanently.

- **2026-08-12, how the Microchips actually work, from play. This invalidates
  the fix approved the day before, not just its details.** Owner, and it
  outranks both the wiki's wording and the audit built on it.

  1. **The third Microchip is already in the Blackbridge Grotto.** The player
     only ever needs to *bring two* -- the Entrance Hall vase chip and the West
     Path dig chip.
  2. **The Grotto's chip can be removed**, and once removed it can be traded at
     the Trading Post or lost in the Lost & Found.
  3. **Every Microchip respawns the next day at its starting location** if it
     was removed from the Grotto.

  **What this overturns.** The 2026-08-11 audit concluded the ceiling was two
  against a gate needing three, and called it a dead gate needing a third grant
  site. The ceiling of two is correct and was reproduced against the live
  engine; **the conclusion drawn from it was not.** Two is the right number to
  carry, and the defect is in the gate, not in the grant sites:
  `areas.json`'s `three_microchips` is `kind: "item", count: 3`, i.e. three held
  *in inventory*. It should be satisfied by **two held plus the Grotto's own
  chip in place**.

  So the approved bundle's first step -- "grant a microchip on Grotto arrival"
  -- **is wrong and must not be built.** The Grotto's chip is not a pickup that
  tops the player up to three; it is a chip already sitting in the pedestal.
  Granting it on arrival would model a fourth chip that does not exist.

  **The shape that fits all three facts:**

      gate opens when  (chips held) + (1 if grotto chip in place else 0) >= 3

  - Bring two, never touch the Grotto's chip: `2 + 1 = 3`, opens.
  - Take the Grotto's chip, hold all three: `3 + 0 = 3`, still opens.
  - Take it and trade or lose it: `2 + 0 = 2`, locked out **for that day only**
    -- rule 3 puts it back tomorrow.

  This needs one new piece of day-scoped state for whether the Grotto's chip has
  been removed, resetting daily rather than carrying over. Note the existing
  `entrance_vase_broken` / `outer_chip_dug` day-start re-grants are already
  exactly rule 3's respawn behaviour for the other two chips, so the convention
  is established and should be matched, not reinvented.

  **The wiki does not contradict this** -- "all three Microchips must be found
  and inserted into the pedestal" is consistent with one of the three being
  found *in situ*. Recorded because reading it as "hold three" is what produced
  the wrong plan.

- **2026-08-11, the stale-blocker retag widens to an audit of all 14
  unimplemented special items.** Owner. The queue named two records whose
  `meta.blocked_on` was false; verifying them turned up five, and three of the
  five are worse than merely stale because the engine already touches the item:

  - `dowsing_rod`, `crown_of_the_blueprints` -- `color_biased_drafting_not_modeled`,
    built in #193.
  - `coupon_book` -- `shop_purchases_not_modeled`, but `shops.py::buy` exists
    and its effect tag `shop_discount` is **already read** at `shops.py:384`.
  - `gear_wrench` -- `mechanical_room_rarity_not_modeled`, but the 8 Mechanical
    Rooms carry `extra_categories: ["mechanical"]` (fixed #159). The real gap is
    a rarity card-move, which the 2026-08-11 entry above establishes the repo
    already performs twice.
  - `microchip` -- `outer_areas_not_modeled`, but the 36-node area graph landed;
    and `shops.py:904/920` already **grant** the item while its record says
    unimplemented and its `effects` list is empty.

  So: audit the remaining nine as well (`battery_pack`, `magnifying_glass`,
  `telescope`, `prism_key`, `chronograph`, `trophy_of_wealth`, `the_axe`,
  `file_cabinet_key`, `key_of_aries`) rather than fixing only what was reported.
  A research pass first, then one data PR.

  **`implemented: false` is carrying two different meanings** -- "nothing in the
  engine touches this" and "the engine grants it but it does nothing" -- and
  that ambiguity is what let `coupon_book` and `microchip` sit miscategorised.
  The audit should say which of the two each record means.

  On `coupon_book` specifically: **trace the discount end to end before flipping
  the flag.** A wired effect tag is not proof; Room 8 was reachable on 2 of 45
  cells and granted nothing while looking built.

- **2026-08-11, task 16's scope, in four rulings.** Owner. The brief in
  `HANDOFF.md` measured ~35-45 edits across ~25 files; re-measuring found ~74
  files, because two large categories were never enumerated. The raw greps do
  overstate as recorded -- 48 `#`-comment hits on history verbs reduce to about
  8 genuine ones, since "on an earlier day", "used to prove" and "rejected by
  the geometry gate" all describe the present. The extra size is real, not
  grep noise.

  **1. The 26 `tests/rooms/` "Split out of the old test_X.py" module
  docstrings: strip the history clause, keep the cross-reference.** The pointer
  ("see tests/rooms/test_dining_room.py for the Dining Room's main course") is
  live navigation and stays; where the file came from is not.

  **2. Dated references: strip the date, keep an undated pointer to
  `docs/open_tasks.md`.** "owner spec, docs/open_tasks.md decisions log
  2026-08-06" becomes "owner spec, see docs/open_tasks.md". A reader must still
  be able to find the reasoning behind a surprising rule; they do not need to
  know the day it was ruled. **Source-provenance stamps are exempt and keep
  their dates** -- "The wiki's Cargo Rooms table, fetched 2026-08-11" is the
  same kind of fact as `meta.source`/`meta.confidence`, and a fetch date is
  what makes a wiki claim auditable later.

  **3. The ~20 test docstrings that narrate the bug they pin get rewritten to
  state the property, not deleted down to their first clause.** Deleting only
  the trailing "-- previously this granted nothing" leaves "Hovel now
  qualifies" implying a change the reader cannot see. This is the highest-value
  part of the sweep and the only editorial part; every rewrite gets reviewed
  individually.

  **4. Two PRs: `src/` + `tools/` first (~17 files), then `tests/`.** Engine
  comments encode constraints the code must still honour and need the closer
  read; the test sweep is bulk and lower-risk.

  Also noted: `HANDOFF.md` §3's pointers to `engine/game.py:1359` and
  `config.py:249` are stale -- both line numbers now land on clean code. The
  named offenders in this task's own body (`tools/validate_data.py`,
  `engine/items.py`, `tests/rooms/test_vault.py`) were re-verified and are
  still there.

- **2026-08-11, three premises behind the `add_aquariums` scoping were wrong,
  and the groundwork is far smaller than costed.** Recorded because the owner
  accepted a cost estimate built on them.

  **1. `draft.py::_priority_draw` is NOT a first-match loop.** It rolls
  **every** entry independently and `continue`s past a failed roll, returning
  only on a roll that succeeded *and* yielded a draftable room. Measured over
  400k seeds, the two existing rows fire at **0.15606** against the wiki's
  stated **0.1561**. The compounding the Aquarium needs **already works**; no
  new mechanism is required. What is missing is only *day-scoping* of an
  entry, and `_apply_category_bias` already has the `condition` idiom to copy.

  **2. There is no deal-time rarity read, so a "rarity override channel" is
  the wrong shape.** `_deal_from_rarity` is handed a `rarity_idx` and never
  asks a card what rarity it is -- **a card's effective rarity IS the deck it
  sits in**. So "set Aquarium's Dynamic Rarity to Commonplace" is a *card
  move* between buckets, which the repo already does twice
  (`reroll_random_rarities` for the Conservatory, `apply_upgrade`'s
  cross-bucket path). **No rebuild of the decks is needed, and a mid-day
  rebuild would be actively unsafe** -- it resets all eight cursors, silently
  discarding today's upgrades, injections and Conservatory rerolls.

  **3. The Aquarium room record already exists.** The new record is a
  *second, distinct* floorplan (the experiment-added copy, which the wiki
  gives its own placement restriction), not the Aquarium itself.

  **Scheduling consequence, and it inverts what I told the owner: the room
  record is the retrain trigger, not the effect.** `obs.py` uses
  `len(registry.rooms)` as a Box high bound, and `Room.idx` is *position in
  rooms.json order* -- so a new record inserted mid-file shifts every later
  room's index and invalidates the policy's learned room embedding far more
  deeply than a bound change. **It must be appended at the end**, through
  `tools/supplemental_rooms.json` rather than a hand-edit.

  `decks.py::add_copies` is confirmed wrong for this effect: it reshuffles the
  whole deck and rewinds the cursor, by design, because it serves once-per-day
  callers. Firing it 40+ times a day would re-arm the entire bucket each time.
  The replacement inserts into the **undealt** region only.

- **2026-08-11, the Aquarium gets two separate condition-gated priority-draw
  rows, not a place in the existing ones.** Owner. The wiki says the effect
  "adds Aquarium to the 3/13% passive filters", but our `_priority_draw`
  resolves a row's `rooms` list by **fixed order, first draftable wins**,
  while the real game treats a priority draw as a *filter* and draws by deck
  order among the survivors.

  Joining the rows would therefore starve the Aquarium behind the Commissary
  and Observatory -- materially wrong once the Aquarium has 3, 6 or 9 copies
  in the deck against the Commissary's single card. Separate rows reproduce
  the published 15.61% exactly, at the cost of two extra RNG substreams.

  Act on this cold as: this is a **deliberate divergence from the wiki's
  literal wording, chosen because our priority-draw resolution differs from
  the game's.** If the resolution is ever fixed to draw by deck order among
  survivors, revisit -- joining the rows would then be both literal and
  correct.

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

- **2026-08-11, Entrance Hall trunks are entirely per-day: 17 is a DAILY
  maximum, and nothing carries over.** Owner, from play. Neither the spawned
  trunks nor the spawn counter survives the night -- the effect can add up to
  17 trunks to the Entrance Hall each day, and the next day starts clean.

  This corrects an assumption I stated in the other direction. The wiki
  publishes a "maximum of 17" alongside a predetermined spawn order across the
  Entrance Hall's four walls, which reads like a lifetime cap on numbered
  physical objects; it is not.

  Act on this cold as: **this makes `entrance_hall_trunk` materially cheaper
  than scoped.** Everything lives in `SpecialItemsState`, which is rebuilt
  with `GameState` every day -- so there is **no `GameConfig` field, no
  `shops.py::carryover()` entry, and no `DayChain` merge**. The per-cell
  container overlay and the per-day spawn counter are the whole of it. Do not
  build the save-persistent counter the earlier scoping called for.

  The 17 remains shared with **The Twins** constellation within a day (the
  wiki: The Twins is "identical to triggering this effect twice"), so the
  counter must still be named for the Entrance Hall rather than for the
  experiment, so The Twins can reuse it when it lands.

  Still open and not settled by this ruling: whether trunks appear in the
  **Outer Entrance Hall** too (the wiki says they do under the Shrine's Monk
  blessing). Outer rooms have no grid cell, so a cell-keyed overlay cannot
  reach them; recorded as a gap.

- **2026-08-11, the four remaining base experiment effects get built.** Owner,
  rejecting the cheaper option of filtering them out of the setup draw. The
  Laboratory's `draw_offers` does not filter on `implemented`, so a player can
  be offered -- and pick -- an experiment that does nothing. That is the
  clearest failure of the "features are built to be PLAYED" bar in the
  subsystem: a day replay containing a chosen no-op experiment does not read
  clean.

  The four: `entrance_hall_trunk`, `spread_dig_spots`, `add_aquariums`,
  `mail_room_letter`.

  Act on this cold as: **two of these are subsystems wearing an experiment
  costume, and one may not be buildable at all.**
  - `mail_room_letter` looks cheapest -- the Mail Room family is fully
    modelled and the wiki publishes a 16-letter collection in fixed order.
  - `entrance_hall_trunk` needs **dynamic per-cell container counts**;
    `containers_in()` reads a static per-room table and the Entrance Hall has
    no entry.
  - `add_aquariums` needs live deck injection with a per-day rarity override,
    and it must defeat `draft.py::room_draftable`'s one-copy-on-grid rule --
    which is also the thing that currently makes it non-re-entrant with the
    shops/bedrooms/hallways/red triggers. **Re-verify that non-recursion
    argument before it goes live.**
  - `spread_dig_spots` is **blocked on off-grid dig spots**, which do not
    exist: `dig_all` reads `state.grid[cell]` only, and `areas.py` has no dig
    concept. Report back rather than inventing a model. Note the wiki also
    forbids pairing it with `trash_while_digging`, already encoded as
    `cross_column_exclude`.

- **2026-08-11, Blessing of the Tinkerer IS built -- reversing its
  never-model entry.** Owner, resolving a conflict between two of their own
  rulings. The Shrine ruling stubbed Tinkerer on "needs the experiments
  subsystem"; [`experiments-design.md`](experiments-design.md) lists "Blessing
  of the Tinkerer cross-triggers" under *Deliberately never modelled* because it
  is a global modifier on the whole subsystem rather than a per-record rule.

  The blocker named in the Shrine ruling is gone, so that ruling now governs:
  any active experiment also triggers whenever a Mechanical Room is drafted,
  independent of the chosen trigger.

  Act on this cold as: **the eight Mechanical rooms are already typed**
  (`is_category("mechanical")`, landed in #159), so the detection is cheap.
  The care needed is at the fire site -- this is a second, unconditional path
  into `trigger_success` that bypasses the configured trigger's own gate, so
  it must respect the pause gate and any cap exactly as the normal path does.

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

- **2026-08-11, the Spare Great Hall grants its published prize contents.**
  Owner, closing a question deliberately left open on 2026-08-10. Per the wiki
  the room has no side doorways, no Antechamber lever, no Upgrade Disk, and
  its far door is not necessarily locked -- so its entire published *effect*
  is invisible at our grid granularity. Rather than declare it permanently
  inert, it gets its published prize contents (four cyan gems / key + cyan gem
  + 5 coins / 20 coins) as an items roll.

  This clears two of the eleven divergence findings, and is the only option
  that leaves the room doing something a player can observe.

- **2026-08-11, two orchestrator decisions taken without escalation.**

  - **`servants_spare_quarters__ix134` gets `cap: 15`.** The base
    `servants_quarters` gained the published cap while the Guess Bedroom mimic
    was being built; the upgrade variant carries the same uncapped
    `grant_per_category` and was missed. Per CLAUDE.md a placement/behaviour
    rule applies to upgrade variants that inherit the base's rule. This is the
    same invisible-until-the-count-gets-large shape as the original.
  - **The divergence audit gains a fifth exemption channel,
    `_AUDIT_DEFERRED_EXEMPT_IDS`,** carrying an id and a reason, guarded
    against staleness the way the Python channel already is. The owner asked
    for Closed Exhibit / Throne Room / Pump Room to be marked deferred; there
    was never a mechanism that could express it, so it was never done -- and
    `parlor__ix109`, ruled permanent, is still counted too. Exempting those
    four takes the count **11 -> 7**, after which every remaining finding is
    genuinely actionable.

- **2026-08-11, the redraw cap is DROPPED. This reverses the earlier ruling to
  add a per-hand redraw cap, and the reversal is my fault.** When I asked for
  that ruling I described `drawing_room_drawn` x `set_dice` as an unbounded
  zero-step loop.
  Measured in this engine, it is not: **mean 2.34 redraws, median 2, p90 3,
  p99 4, max 4 over 53 sampled hands; zero runs exceeded 8.** It is a decaying
  random walk, not a divergence.

  The closed form agrees. Each redraw spends a die and the Drawing Room
  reappears with probability p, so `E[length | 2 dice] = (2-p)/(1-p)^2`, which
  is 2.35 at the measured p = 0.10 and only diverges as p -> 1.

  **Both of the wiki's methods for driving p -> 1 are unavailable here.** The
  Chronograph is not modelled at all, and the Silver Key draft bias is cleared
  after the initial deal (`draft.py`, commented "Redraws clear the flag"), so
  the depleted-pool method cannot persist across redraws. An adversarial probe
  that reduced the commonplace/gem deck to the Drawing Room alone still
  produced 0 fires in the available redraws.

  **Owner ruling: drop the cap.** Do not add a per-hand redraw budget. The
  termination check in `redraw` still goes in -- it is a live bug independent
  of the cap.

  Act on this cold as: **a cap would have been a permanent, invented deviation
  from the game justified by a premise that was never true of our engine.**
  The wiki is explicit that the real game has no such limit: *"There is no
  limit to how many times floorplans can be redrawn in one draft."* The lesson
  is that "this looks unbounded" is a hypothesis to measure, not a fact to
  rule on -- especially when the proposed fix is a deviation.

- **2026-08-11, the Silver Key bias clearing on redraw is an OPEN question,
  held for play.** `draft.py` clears the Silver Key's cross/T draft bias after
  the initial deal, so it does not apply to redrawn hands. The wiki's
  description of the dice-farming exploit implies the real game's bias **does**
  persist -- that is what would make a Drawing Room appear on every draw and
  make the loop real.

  Owner is checking in play: draft with a Silver Key, redraw, and see whether
  the bias still applies to the new hand.

  Act on this cold as: **if the bias should persist, this is a fidelity bug and
  the redraw loop becomes genuinely unbounded**, which would re-open the cap
  ruling above. Until then the clearing behaviour stands. Do not change it
  speculatively.

- **2026-08-11, four `drawing_room_drawn` scoping calls made without
  escalation.**

  - **The trigger binds through `effects/rooms/drawing_room.py`**, a one-line
    `room_hook` at `ON_HAND_DEALT` delegating to `experiments`. The
    alternative -- an `on_hand_dealt` function called from three sites --
    would put a `"drawing_room"` literal inside an engine module, which the
    standing architectural rule forbids. The room module is where a room-id
    binding belongs, and `fire()` already runs per option at all three deal
    sites, so it needs no new call sites.
  - **The cap does not gate on `set_dice` being configured.** Action legality
    that depends on experiment configuration is opaque to both the agent and a
    human reading the mask. Moot now that the cap is dropped, recorded so it
    is not re-proposed.
  - **No observation change.** Neither `rotations_used` nor
    `study_redraws_used` is exposed today, the mask already makes an
    unavailable redraw unselectable in a MaskablePPO env, and widening
    `resources` would invalidate every released checkpoint.
  - **`_check_termination()` goes at the very end of `redraw`**, after the
    `ON_HAND_DEALT` loop, so a trigger firing on the redealt hand is what gets
    checked. Verified reachable today: `steps_for_gold` drives steps to 0
    inside a redraw and the day does not end.

  Also found: the hidden-Drawing-Room leak the owner accepted is **total, not
  partial, under the Archives**. Archives conceals exactly one slot, a hand
  holds at most one Drawing Room, and no other trigger fires at deal time --
  so a success-counter tick plus two visible non-Drawing-Rooms identifies the
  hidden card with certainty. Under the Darkroom it leaks only "one of these
  three". Suppressing the counter would not close it, since the effect's own
  result is observable too.

- **2026-08-11, the `jack_hammer` dig table diverges from the datamine and gets
  a partial fix now.** Our table has **zero** trash entries, and
  `DIG_PRIORITY` auto-selects the jack hammer as the best tool -- so
  `trash_while_digging` would be silently unfireable for any player holding
  one. The wiki's datamined table gives it **18.4%** trash.

  Our `shovel` and `detector_shovel` tables reproduce the wiki row for row.
  `jack_hammer` alone does not: no trash, no `nothing`, no dice, no Stopwatch,
  and it **adds four vault keys the wiki does not list**, with nothing in
  `dig.meta.note` explaining any of it.

  **Owner ruling: add the six trash rows plus `nothing` at the wiki's weights
  now, and do the full table reconciliation as its own data PR** -- a real
  change to the dig economy should not be buried inside an experiments PR.

  Act on this cold as: the unsourced vault keys are the open question. They may
  be a deliberate addition nobody recorded, or an ingest artifact. Establish
  which before the full rebuild deletes them.

- **2026-08-11, a hidden Drawing Room counts as drawn.** Owner. The trigger
  fires on the floorplan being dealt into the hand, whether or not the Archives
  concealed it -- concealment is about display, not the deal.

  Known consequence, accepted: firing **leaks the concealed option's identity**
  through the experiment's success counter, which the observation exposes. An
  agent watching the counter tick learns what the face-down card is. This
  partially defeats the Archives whenever this trigger is configured.

- **2026-08-11, six phase 3 scoping calls made without escalation.**

  - **The `apples` trigger gets `game` threaded through `items.py`**, rather
    than a deferred counter drained at enclosing sites. Every leaf already has
    `game` reachable -- the "no game in scope" problem is a property of current
    signatures, not a real constraint -- and threading *removes* parameters
    (`grant_item`, `roll_room_items`, `roll_extra_items` each drop two or
    three). A missed thread is a `TypeError`; a missed drain is a silently
    misattributed effect that counts the wrong house. Threading also gives
    per-apple interleaving, which is the faithful shape.
  - **Termination gets four scoped insertions, not a blanket call**:
    `open_door`, `open_container`, `redraw`, and
    `_maybe_finish_experiment_setup` (the last already live since phase 1).
    Each is justified by a specific new fire site. **Not** inside
    `trigger_success`, which runs mid-`_place_room` before the placement is
    finished -- terminating there would fire ON_DAY_END against a
    half-constructed grid.
  - **The availability layer gets the two free `day_gate`s only.** `cfg.day`
    and `cfg.veteran_mode` already exist; `item_obtained_gate` needs a new
    persistent `shovel_ever_obtained` flag and is deferred. Note
    `veteran_mode` defaults to True, so all of this is a no-op by default. Any
    filter must never shrink the pool below 3, since `draw_offers` samples 3.
  - **The `security_door` trigger's "occasionally triggers an additional time,
    possibly due to a bug"** stays unmodelled, recorded as a `null` magnitude
    with the gap in `meta.notes`. The wiki hedges it and gives no rate.
  - **The dead `chest` container kind counts as a trunk** (the wiki says chest
    *is* trunk), so the gate is `kind in ("trunk", "chest")` and stays correct
    if a room ever gets one. **Vault deposit boxes do not count** -- a
    distinct mechanic.
  - **`trunks_opened` ships with its designed partner dead.** The wiki pairs
    it with the Entrance Hall trunk effect from both sides; that effect is
    inert and needs dynamic per-cell container counts, which
    `containers_in()` cannot express today.

  Also found: `docs/experiments-design.md`'s Status section went stale the
  moment PR #169 landed -- it still claims one live base trigger and a 25%
  offer rate. And `pantry_fruit`'s note about apples being less common is
  **not** in conflict with `items.json`'s fruit weights; they describe two
  different pools, which is worth one clarifying line so nobody re-opens it.

- **2026-08-11, our Archives is scoped wrong: the effect is house-wide for
  the day, not per-doorway.** Research triggered by the owner's archived/hidden
  correction. The wiki is unambiguous: *"The Archives ... will 'archive' one of
  the three floorplans drawn whenever a room is drafted after Archives"* --
  no from-room qualifier anywhere on the page. Our `draft.py::_hidden_count`
  keys off the room being drafted **from**, so archiving only happens through
  an Archives doorway.

  The owner's own sentence is the proof, independent of the wiki: under our
  model a Darkroom draft sets `from_room = Darkroom`, so no option could ever
  be archived -- yet the owner observes that one of a Darkroom's concealed
  options can be. That is only possible if the Archives effect is persistent
  and house-wide.

  Corroborated a third way: the Shelter interaction is worded *"drafting the
  Archives under the effect of the Shelter ... Archived floorplans do not
  appear"*, i.e. the negation is applied once at placement and suppresses
  archiving for the whole day. That only makes sense for a day-long
  capability.

  Our stored `meta.effect_text` for the Archives says *"While drafting from
  this room, one of the 3 floorplans is hidden (modeled: one fewer option)"* --
  wrong twice: the from-room scoping, and the parenthetical, which is a
  project annotation that is stale against the wiki **and** against our own
  code (nothing anywhere drops an option).

- **2026-08-11, neither the Archives nor the Darkroom reduces the option
  count -- both conceal.** The `reduce_draft_options` tag name asserts a
  mechanic the game does not have. Our runtime behaviour is right (we mark
  options hidden and keep them draftable); only the name and the annotation
  lie. Archived floorplans remain fully selectable, and the game deliberately
  preserves side channels: gem cost, Coat Check label, power lines, rotation
  (which leaks shape), the Furnace's red haze, and rarity when drafting
  through a security door.

  So **archived is a per-option-instance flag produced by a day-long
  house-wide capability**, while Darkroom concealment is a genuine from-room
  effect. The two compose independently. Split the tag: `archive_floorplan`
  for the Archives, `conceal_all_floorplans` for the Darkroom, and retire
  `reduce_draft_options`.

- **2026-08-11, the archived slot is uniformly random across all three.**
  Owner. We currently archive **slot 2 deterministically** and always keep
  slot 0 visible; the wiki only says "one of the three". The owner ruled
  random across all three, which is strictly harder than what we ship -- there
  is no longer a guaranteed fully-informed option. This materially changes
  agent play, so it needs a named RNG substream and a test.

- **2026-08-11, the Shelter's negation of the Archives is spent once, at
  placement.** Owner, matching the wiki's *"drafting the Archives under the
  effect of the Shelter"* wording: one charge when the Archives is drafted,
  and no archiving for the rest of the day. The alternative -- a charge per
  draft -- would drain all three Shelter charges in three doorways.

  Act on this cold as: `_red_negated` is currently never consulted on the
  `draft.py` path, so today a Shelter negates neither room. The trap is that
  every existing caller uses a per-event pattern; this one must latch into a
  day flag at placement or it silently drains the resource.

- **2026-08-11, the Darkroom light switch and the security-door rarity leak
  are both in scope.** Owner, on two published gaps found in the same pass.

  The Utility Closet can restore the Darkroom's lights, fully disabling its
  drafting penalty; we model that switch system but have **no Darkroom
  switch** anywhere in `src/` or `data/`. Without it the agent has no counter
  to a Darkroom at all. (The wiki also notes the fuse never blows if the
  switch is already off when the Darkroom is drafted, but flipping it off and
  on again beforehand does not prevent it.)

  Separately, the wiki says a concealed floorplan's **rarity is visible** when
  drafting through a security door. Our `env/obs.py` zeroes rarity for every
  hidden option unconditionally, so the agent loses information a real player
  has. Note `forced` is zeroed there too, which discards real information for
  no stated reason -- worth checking while in that code.

- **2026-08-11, "archived" is independent of "hidden" -- our data conflates
  two different mechanics.** Owner, correcting a question I asked badly. I
  offered a choice between counting only Archives-hidden options or any hidden
  option for the `archived_floorplan` experiment trigger. The owner rejected
  the framing: *"Archived is independent from hidden. You can't see rooms
  drafted from the Darkroom, but one of them can still be archived."*

  So `opt.hidden` is **the wrong signal entirely**. Being archived is a
  property a floorplan has; being hidden is a property of how it was dealt.
  A Darkroom draft hides its options from the player, and one of those hidden
  options may independently be archived.

  Our `rooms.json` gives the Archives and the Darkroom the **same effect tag**
  (`reduce_draft_options`, differing only in `amount`), so the engine cannot
  currently tell the two apart, and `opt.hidden` conflates them. The trigger
  needs a distinct archived marker, set by the Archives' mechanic only.

  Act on this cold as: this is a **modelling gap in the drafting system**, not
  just a blocked trigger. Whether the Darkroom's "you cannot see the options"
  is even correctly modelled as `reduce_draft_options` is now open --
  reducing the option count and concealing the options are different things.
  Worth a research pass before the trigger is built.

- **2026-08-11, experiment trigger and cap semantics.** Owner, on three of the
  twelve ambiguities raised while scoping experiment phases 2-3.

  **The "for each Bedroom after your second" trigger counts all of today's
  Bedrooms**, not only those drafted after the experiment started. The wiki's
  live text says the opposite -- *"It does matter whether those two initial
  Bedrooms are drafted before or after starting the experiment"* -- but that
  sentence has never been grammatically clean (created 2025-09-29 as "before
  or starting", repaired to "before or after" by a 2025-11-25 grammar edit
  that left "does matter" untouched), so a dropped "not" is at least as
  plausible as a deliberate "does". This is the harsher reading: a
  bedroom-heavy morning can burn the grace before the player reaches the
  Laboratory.

  **The "next 3 times you unlock and open a chest" trigger counts trunks
  only** -- not locked lockers, not free lockers, not the Garage car trunk,
  not Mechanarium compartments. The wiki uses "chest" to mean trunk and its
  Sledge Hammer clause describes trunks specifically. Including locked lockers
  would have let a single Locker Room visit burn the whole 3-trigger cap
  deterministically, since that room holds 17 in one cell.

  **A capped trigger counts fires, not qualifying events** -- so pausing the
  experiment preserves charges. This sets the precedent for the packet pool's
  `map_view`, the only other capped trigger.

- **2026-08-11, eight experiment scoping calls made without escalation.**
  Recorded so they are visible rather than buried in a PR.

  - The **Hovel kills the `gems_spent` trigger** (wiki: *"this trigger becomes
    useless with it on the estate"*). Our engine models the Hovel by paying
    gem costs in steps at 3:1 while `_effective_cost` still returns the gem
    number, so a naive `cost >= 2` check would fire on every expensive draft
    -- the exact opposite of the published behaviour.
  - **The Stopwatch's gem waiver does not count as spending.** Unpublished;
    consistent with the Emerald Bracelet rule, which the wiki does state.
  - **Outer-room drafts do not fire draft triggers.** Self-consistent: outer
    rooms are never in `st.grid`, so the counting effects already exclude
    them. The wiki says outer rooms count only under a Blessing, and
    Blessings are out of scope.
  - **The Red Rooms trigger's own 5-step loss is suppressed while paused**,
    which falls out for free from applying it inside `trigger_success` after
    the active gate.
  - **The `security_door` trigger fires at `open_door`**, not `choose` --
    matching "drafted from". The in-drafting site naturally lands after
    placement, the same way the game's two paths differ.
  - **Draft triggers fire between draft counting and `ON_PLACE`.** Both
    bounds are wiki-stated: after the grid write so the triggering room counts
    itself, and before `ON_PLACE` so the Weight Room halves the experiment's
    steps rather than the reverse.
  - **`gain_star` is flipped live** -- `state.stars` is already fully wired
    for carryover, so it is one line, and it drops the all-inert-offer rate
    from 4.55% to 1.8%.
  - **Availability gating is split into its own PR.** Under shipped defaults
    only the `spread_dig_spots`/`trash_while_digging` cross-column exclusion
    binds; the two gates needing new persistent config are bypassed by
    `veteran_mode`.

  Two data-file corrections also fall out: `bedrooms_after_second`'s note must
  quote the wiki verbatim and record the ruling above, and `security_door`'s
  note omits the published in-drafting clause entirely.

  **Deliberately not modelled:** the wiki's own hedge that `security_door`
  *"occasionally triggers an additional time, possibly due to a bug"* -- it
  gives no frequency. And Scraps of Paper, which Patch 1.6 added to the trash
  table, do not exist in `special_items.json`.

- **2026-08-10, expired scope annotations are re-opened as real work.** Nine
  `meta.effect_text` values are not game text at all -- they are annotations
  this project wrote, and several have expired:

  | record | claims | why it is false now |
  |---|---|---|
  | `clock_tower` | "out of single-day scope" | multi-day has been in scope since `DayChain` |
  | `shrine` | "out of single-day scope" | same |
  | `the_kennel` | "lock system out of scope" | `locks.py` models locked doors |
  | `vestibule` | "on enter, 3 doors unlock and the 4th locks (lock system out of scope)" | same |
  | `lost_and_found` | "no effect modeled" | the steal/gift behaviour IS modelled (`special_items.py`), per CLAUDE.md |

  Owner decision, on interview: **implement them, and rewrite each annotation to
  say what is actually true.** This is the "a scope annotation is a claim with
  an expiry date" lesson firing for the second time -- the first cost seven
  rooms suppressed long after the sim grew multi-day support.

  Act on this cold as: an annotation asserting something is out of scope must
  be re-checked whenever that scope changes, because nothing else will
  invalidate it. Prefer a dated task entry in this file over a scope claim
  buried in a data record.

- **2026-08-10, `parlor__ix109` stays unmodelled, and the reason is recorded.**
  Its entire payload is "2 Wind-up Keys", and the Wind-up Key item was
  deliberately **removed** from the sim (design doc simplification #17:
  puzzle-only items are deleted and their payoff granted directly). So the
  variant references a concept that no longer exists.

  Owner decision, on interview: leave it inert rather than re-add the item or
  invent a substitute payoff. Act on this cold as: this is a **deliberate**
  permanent finding on the worklist, not an oversight -- do not "fix" it by
  reintroducing the Wind-up Key.

- **2026-08-10, the Aquarium counts as every colour via a data flag.** All three
  Aquarium records say "AQUARIUM is every color of room." `Room.category` is a
  single string, and category drives category biases, `grant_per_category`, the
  Cloister/Terrace green boosts and scepter colours.

  Owner decision, on interview: add a **`counts_as_all_colors`** flag honoured
  at each category-comparison site, rather than widening `category` itself or
  applying the rule only where convenient. One flag, consistent everywhere.

- **2026-08-10, the Cloister of Dauja and Veia need sourced room lists first.**
  Dauja pays "for each room with an animal", Veia gives dirt piles "in each room
  with a fireplace". Neither an animal nor a fireplace concept exists in
  `rooms.json`. Owner decision: research the wiki, then encode the result as
  data flags -- and **if the wiki does not publish the lists, come back rather
  than guessing which rooms qualify.**

- **2026-08-10, `guess_bedroom__ix70` gets a research pass, then an owner call
  if it is unsourced.** Its datamined text is "Hidden effect of a random BEDROOM
  in your draft pool?" -- with a literal question mark, so the datamine itself
  is unsure. Owner decision: research it; if the wiki is as vague as the
  datamine, leave it unmodelled and record the gap rather than invent a
  mechanic.

- **2026-08-10, the Laboratory is the big subsystem to take on.** Of the four
  large unmodelled subsystems on the worklist -- Throne Room (the "reclaim the
  crown" objective), Closed Exhibit (security-lock puzzle), Mechanarium (dynamic
  door count per Mechanical room) and Laboratory ("Experimental House Features")
  -- the owner chose the **Laboratory**. It gates several other mechanics
  already met elsewhere in this file: the Satellite Dish Pantry restock, the
  experimental dig-spot spread to the Grounds, and the apple-eating trigger.

  The other three stay unstarted; each needs its scope written up before it is
  picked, not during.

- **2026-08-10, work the cheap findings breadth-first.** Owner decision for an
  unattended day: clear the many small findings in batched PRs rather than
  going deep on one subsystem. Maximum findings cleared per unit of risk, and
  each PR stays reviewable.

- **2026-08-10, the Guess Bedroom excludes the Aquarium family and treats a
  mimicked Bunk Room as a flat 2 Bedrooms.** Owner, on two ambiguities raised
  by the research pass. The Guess Bedroom loses its own +10 steps and instead
  secretly picks one Bedroom from today's draft pool when it is **drafted**,
  taking on that room's effect.

  **The Aquarium is out of the selectable set for now**, with the gap in
  `meta.blocked_on`. Mimicking it would require inheriting the Aquarium's
  extra colours, and `Room` is frozen -- so `Room.is_category` would have to
  become state-aware for one cell. That primitive backs category biases,
  `grant_per_category`, the Cloister/Terrace green boosts and scepter colours,
  which is a lot of load-bearing code to change for one room. The wiki records
  that the real game is buggy here too ("in rare cases, only some of the
  effects are applied, despite still mimicking an Aquarium"). Reversible.

  **A mimicked Bunk Room counts as 2 Bedrooms**, matching the real Bunk Room's
  existing `counts_as_bedrooms: 2`. The true behaviour is **unpublished** --
  the wiki carries its own open-question box saying it "is not consistent from
  effect to effect. For some effects, it still only counts as one Bedroom. For
  some, such as the Day Overview, it actually counts as three." A flat 2 is
  consistent with the rest of the codebase and wrong only where the wiki
  itself cannot say.

  The remaining four mimics are cheap, because every payload is already
  implemented on the source room: Bedroom (+2 steps, retriggerable, does not
  become an Entry Room), Boudoir (no effect), Nursery (the persistent
  +5-steps-per-Bedroom effect, including for itself; not a Drafting Room for
  the Classroom; own item spawns disabled), Servant's Quarters (keys equal to
  Bedrooms in the house, **cap 15** -- a cap the existing `servants_quarters`
  record does not have either, so that is a pre-existing gap).

  Published selection rules to honour: never the Guess Bedroom itself, Her
  Ladyship's Chamber, the Master Bedroom, or the Spare Bedroom and its
  upgrades; Repellent-banned floorplans are excluded **except the Hovel**,
  which can always be selected even if already drafted and even before unlock;
  rooms already on the estate are eligible if the Chamber of Mirrors returned
  them to the pool; the **upgraded** version is mimicked where an upgrade
  applies; and if no valid option exists and the Hovel was not chosen, the
  mimic fails and the room has no effect. Once one Guess Bedroom mimics an
  Aquarium every later one does too -- moot while the Aquarium is excluded,
  but it is why the chosen id has to be state, not a local.

  **UNPUBLISHED magnitude:** the wiki says Servant's Quarters is "more commonly
  selected than the other floorplans" and gives no number. Record as `null`
  with the gap in `meta.notes`; do not invent a weight.

  Also corrected by this work: `docs/open_tasks.md` previously recorded that
  the Guess Bedroom "gets a research pass, then an owner call if it is
  unsourced ... if the wiki is as vague as the datamine, leave it unmodelled."
  The wiki is **not** vague -- it is one of the better-documented upgrade
  pages on the site, with per-mimic sections. So this is implementable, not a
  shelve.

- **2026-08-10, the Great Hall locks all three grid doorways AND models the
  search cost.** Owner, choosing the more faithful of three options. The room's
  effect is "7 Locked Doors", but our grid has no subchambers: a `cross` has
  only 3 non-entry doorways. In the real game the far doorway is a genuinely
  locked drafting door, while the two side drafting doors are themselves
  unlocked but sit behind three locked inner doors each, only one of which is
  the passage.

  So all three doorways lock, and the side doorways additionally carry the
  expected cost of finding the right inner door. The wiki publishes a
  theoretical table for that search: edge doors 25% to be the doorway, the
  centre door 50%. The owner rejected the cheaper "lock all three, flat 1 key
  per side" option in favour of modelling it.

  Mechanism: `data/locks.json` already has `always_unlocked_rooms`, consumed at
  `engine/locks.py::roll_segment`. A symmetric `always_locked_rooms` is the
  natural counterpart. The lock roll happens inside `_place_room` before hooks
  fire, so this belongs in data, not a `room_hook`. A Foyer already on the
  estate correctly overrides it, matching "unless some other effect forces them
  to be unlocked".

- **2026-08-10, the Spare Great Hall's layout is `straight`, not `cross` --
  the wiki wins over the datamine.** Owner, on a conflict surfaced rather than
  resolved silently. Our datamine row says `4-Door`; the wiki says flatly that
  the Spare Great Hall **does not inherit the Great Hall's shape** and draws
  the consequence explicitly: *it may be drafted along the edges of the house*,
  which a 4-way can never be under `grid.py`'s outer-wall invariant.

  This is not cosmetic -- it changes which of the 45 cells the room can legally
  occupy. The change must go through `LAYOUT_OVERRIDE` in
  `tools/ingest_sheet.py`, **not** a hand-edit to `rooms.json`, or the next
  re-ingest reverts it. Precedent exists: two datamined rooms are already
  corrected this way.

  Still open, and deliberately not asked yet: whether the Spare Great Hall gets
  any modelled effect at all. Per the wiki it has no side doorways, no
  Antechamber lever, no Upgrade Disk, and -- despite its own effect text -- its
  far door is *not* necessarily locked. That would make its entire published
  effect invisible at grid granularity, i.e. the `parlor__ix109` treatment. Its
  prize contents are published and could be granted as an items roll if the
  room should do something.

- **2026-08-10, colour-selective drafting gets filter + default floorplans, no
  reserve copies.** Owner, choosing the middle of four options. The Secret
  Passage lets the player pick one of five colours (Bedroom, Hallway, Green
  Room, Shop, Red Room) and restricts the whole resulting hand to it.

  **No colour-selective machinery exists anywhere in the codebase** -- a grep
  for `color_selective|prism|color_filter` across `src/` returns zero hits. The
  nearest primitive, `draft.py::_apply_category_bias`, is a *bias* (roll a
  chance, try to swap one card), not a *filter*, and the wiki warns explicitly
  that the two must not be confused.

  Scope as ruled: restrict the deal to the chosen colour, and fall back to the
  published per-colour default triples when the pool is thin. Reserve copies
  are out. The owner rejected filter-only because the wiki says thin pools are
  *frequent* for Green Rooms and Shops, so filter-only would diverge often; and
  rejected full fidelity because it requires relaxing the out-drafting
  invariant in `placement.py`/`rotation.py`, which is load-bearing.

  This clears two findings and one item at once: `secret_passage`,
  `spare_secret_passage__ix138` (which reuses the same handler, as `foyer.py`
  already does for its Spare), and `prism_key`, whose `meta.blocked_on` is
  literally `color_biased_drafting_not_modeled`.

  Separate side finding, since **resolved in PR #190**: both Secret Passage
  ids now carry `rank_gte_2`/`rank_lte_8`, so the rank half is modelled and
  the stateful wing rule is recorded on both records as a named gap. What
  follows describes the state before that:
  `secret_passage.draft_conditions` was `[]` and nothing in `src/` referenced
  the room, so **none** of its published placement restrictions were modelled --
  it cannot be drafted on Rank 1 or 9, and is blocked from wing drafts leading
  north into Rank 8 or south into Rank 2 until another vertical wing draft
  occurs. The rank rule is two existing primitives away; the stateful wing rule
  is not.

- **2026-08-10, the Shrine is built, with five of eight blessings live.**
  Owner. Deposit 1-80 gold, receive one of eight blessings lasting 3-7 days;
  taking the gold back curses you for 2 days instead. The band table, the 8x5
  coin pairs, and all eight blessing effects are fully published.

  Buildable now: Dancer, High Roller, Gardener, General, Berry Picker. Stubbed
  with `meta.blocked_on`: Tinkerer (needs the experiments subsystem), Chef
  (needs Dining Room dishes), Monk (needs grounds drafting).

  **This is save-scoped state** -- blessings survive an attempt wrap, joining
  `stars` and `main_course_bonus`. It needs the `mail_transit_days` shape (a
  raw day count DayChain decays mechanically), not the allowance/stars
  "replaced wholesale" shape: a blessing id, a remaining-days count, a parallel
  curse-days count, and a monk-room key.

  Action space as ruled: expose 8 blessings x 5 durations = 40 actions and
  derive the coin cost, rather than 80 raw donation amounts. Nothing is lost --
  the wiki notes there is little reason to offer an even number of coins except
  to deliberately deprive oneself of gold.

  Two corrections fall out. Our stored `effect_text` is *"Donate money for
  multi-day blessings (out of single-day scope)"* -- not game text at all, but
  a project annotation whose scope claim expired when DayChain landed; the wiki
  infobox reads *"Make an offering, Receive a blessing."* And the curse path is
  the gate to `cursed_effigy_unlocked`, a flag that already exists in
  `config.py` and that today can never be set by play.

  **UNPUBLISHED, do not encode:** the Shrine page source carries a commented-out
  claim that the Veranda *does* incur the curse penalty when its cost is
  bypassed. Drafted by an editor, never published.

- **2026-08-10, the Mechanarium's door count is CONFIRMED fixed at draft.** The
  owner's claim from play -- "the number of doors is set when drafted; it does
  not add doors later for newly drafted engineering rooms" -- is confirmed
  verbatim by the wiki: *"The number and orientation of the doors in the
  Mechanarium are set in stone the moment it is drafted. Drafting more
  Mechanical Rooms after the Mechanarium has been drafted will not cause more
  doors in the Mechanarium to spawn."* Independently corroborated by
  `Template:Interactions/Mechanical Room`.

  This is what makes the room buildable at all. A count that grew would need
  live mutation of a placed room's door mask, and `placed_doors` is written in
  exactly three places, none of which any effect handler can reach. A count
  frozen at draft is an ordinary placement-time decision.

  **Owner ruling: build BOTH the doors and the four diagonal compartments.**

  **The eight Mechanical rooms**, all resolving to our ids: `utility_closet`,
  `boiler_room`, `pump_room`, `security`, `workshop`, `laboratory`,
  `electric_eel_aquarium__ix4`, `mechanarium`. All eight are `category:
  blueprint`, so this needs the multi-valued `extra_categories` field added
  earlier the same day -- and it **also unblocks** `priority_draws.json`'s
  dead `mechanical_or_rotanda` entry, whose own note records that it "matches
  nothing in rooms.json", plus the Gear Wrench and Powered Electromagnet.

- **2026-08-10, a Mechanarium doorway blocked by a neighbour's blank wall does
  not consume its slot.** Owner. The wiki says such a doorway is "skipped" and
  the room "tries again at the next position", without saying whether the slot
  is spent. An **unpublished** note in the page source lists blocking a side
  door as a way to reach the eighth door, which implies the count carries over.

  Act on this cold as: the supporting evidence is commented-out wiki source,
  not published text, so this is the owner's call resting on a hint rather than
  a statement. It makes the Mechanarium's door count depend on its neighbours'
  door masks at draft time, which is worth re-testing in play.

- **2026-08-10, the Southern Cross excludes the Mechanarium, the Chamber of
  Mirrors and every upgrade variant.** Owner, on a divergence found while
  scoping the Mechanarium. Our `priority_draws.json` keys the 40% draw on
  `layout: "cross"`, which sweeps in all 19 cross-layout rooms; the wiki's own
  query excludes the two rooms by name and filters `Type HOLDS "Upgrade"`, and
  the Mechanarium page repeats it independently ("It is also unaffected by the
  Southern Cross").

  Currently inert -- nothing sets `state.southern_cross_active` -- so this is
  wrong data rather than wrong behaviour, which is why it was safe to correct
  in passing.

- **2026-08-10, "gated mechanical arms" is unsourced and should not be
  repeated.** Both CLAUDE.md and `upgrade_disk_mechanarium.meta.simplification`
  describe the Mechanarium's Upgrade Disk as being behind "gated mechanical
  arms". A full pass over the Mechanarium page found **no wiki support for any
  arm mechanic**. The real gate is the diagonal-door spawn threshold: the disk
  sits behind the third diagonal door, which needs three more Mechanical rooms
  than spawned drafting doors, and the Sanctum Key sits behind the fourth.

  Act on this cold as: correct the wording when the compartments land. If the
  phrase came from play rather than the wiki it needs attributing, but nothing
  in the sources supports it as written.

- **2026-08-10, the Laboratory is GO for phases 0-4 only.** Owner. That
  delivers a playable, trainable Laboratory: the data file, the
  offer/choose/start/pause core, the eight pure-resource effects, the
  draft-site triggers and the interaction triggers -- the last of which is what
  the apple-eating trigger elsewhere in this file has been waiting on.

  **Phases 5-8 are explicitly NOT authorised.** They are four separate
  subsystems wearing an experiment costume ("model the Grounds' dig spots",
  "model Pantry stock", "model Dynamic Rarity", "model the Satellite Dish
  unlock chain") and each comes back as its own line item.

  Budgeted costs, all recorded in advance: action space **319 -> 327**, a new
  `Phase.EXPERIMENT_PENDING`, and three observation width changes (a new
  `experiment` key, `phase` 4 -> 5, `carryover` 14 -> 16). The subsystem's
  scope, phase plan and current status are in
  [`experiments-design.md`](experiments-design.md).

- **2026-08-10, the Clock Tower counts Tomorrow rooms PRESENT in the house.**
  Owner, resolving a page that contradicts itself: the infobox says "for each
  Tomorrow room **you draft today**", the prose says "for every Tomorrow room
  **present in the mansion**". The prose wins -- an end-of-day tally over what
  is actually standing, **including the Clock Tower itself**, which our own
  effect text omits.

  The two readings differ whenever a Tomorrow room enters the house without
  being drafted, which the Foundation already does by persisting across days.

- **2026-08-10, the Parlor's box is always the prize box.** Owner. The real
  Parlor is a deterministic logic puzzle the wiki says is *always* uniquely
  solvable, so there is no probability to sample: a perfect solver never opens
  an empty box, a guesser is wrong two times in three.

  The assumed-solved doctrine already governs every other puzzle room -- Mora
  Jai boxes, the room safes, Room 8 -- so the Parlor follows it. Consequence,
  stated rather than discovered later: **the Funeral Parlor's 30-step penalty
  never fires**, because it only applies to opening an empty box.

  This also unblocks the Parlor line without reviving the Wind-up Key, which
  stays removed. `parlor__ix109` ("2 Wind-up Keys") remains a deliberate
  permanent finding.

- **2026-08-10, a room's colour is a SET of categories, not one value.** Owner:
  "It just means that color needs to be a set of enums instead of an enum.
  Maid's Quarters is another room -- both red and purple."

  `Room.extra_categories` is stored beside the primary `category`, and the
  derived `categories` property is what `is_category()` answers from.
  `counts_as_all_colors` -- a one-room escape hatch added hours earlier -- is
  deleted, because a set makes it unnecessary.

  **The evidence was already in our own data.** `maids_chamber`'s datamined
  `effect_text` reads "Counts as red room AND bedroom" while the record stored
  `category: "red"`, dropping the second membership silently. The raw sheet
  carries a **colour column** distinct from its two type columns, and the
  wiki's `Type=` field is a list -- the Aquarium's reads seven types.

  `categories` is **derived, not stored**, so it cannot drift from `category`.
  The first cut stored it, and `dataclasses.replace(room, category=X)` then
  left membership stale -- caught by a real test that builds a deliberately
  stale room exactly that way.

  Populated for two rooms only: the four Aquariums and Maid's Chamber.
  Enumerating every other multi-category room needs its own pass against the
  wiki's `Type=` lists; guessing would be inventing data.

- **2026-08-10, the Quest Bedroom is a Bedroom, not an objective room.** Owner:
  "Quest Bedroom is a bedroom, not an objective room. It rewards on an
  objective."

  The raw sheet's row settles it: colour **Purple**, type1 **Bedroom**, type2
  Objective. Our ingest let `type2 == "Objective"` override the real type, so
  the room landed as `category: "objective"` and **every Bedroom-counting
  mechanic silently skipped it** -- the per-Bedroom gem cost, Cloister of Mila,
  the Sleeping Mask, bedroom category biases.

  The ingest rule is now narrowed to the two rooms that *are* the objective,
  Antechamber and Room 46, which a separate name check already covered. Nothing
  else in the sheet changes category as a result.

  Act on this cold as: "Objective" in the sheet marks *pays out on reaching the
  objective*, which is a reward condition, not a room type. `objective` as a
  category now means exactly two rooms.

- **2026-08-10, 72 blueprints is correct, not a default bucket.** Owner, on my
  flagging that `blueprint` holds 43% of all rooms and looked like the
  catch-all bug task 15 found: "There are a lot of blueprints. That's why the
  game is called Blue Prince. It's a pun."

  Recorded so the count is not "fixed" later. The earlier task-15 finding was
  genuinely different -- eight rooms carried the **pool name**
  `studio_addition` where a colour belonged, which is not the same as a large,
  legitimate colour.

- **2026-08-10, the Patio spreads exactly one gem to each Green Room.**
  Owner, on a wiki that contradicts itself: the Gems page says it "spreads
  1 gem to **each** Green Room", the general Spread page says every room "has a
  **chance**" of receiving a spread item, and the Spare Patio page says it will
  "**often**" spread a gem to itself. No rate is published anywhere.

  Deterministic wins: every Green Room on the estate at the draft moment gets
  exactly one gem, the Patio itself included, and rooms drafted later get
  nothing. Gem colour is **mechanically inert** -- the wiki states the six
  colours "are purely cosmetic and are lost once the gems are collected" -- so
  the green-to-blue switch under a Conference Room needs no representation.

  The Spare Patio is identical, and unusually this is affirmatively sourced
  four separate ways rather than assumed from matching text. That matters
  because `spare_great_hall__ix139` has text byte-identical to `great_hall`
  and a materially different mechanic; identical text is not evidence.

- **2026-08-10, the Locker Room's key spread reuses the Secret Garden's
  room-count bucket.** Owner. The wiki publishes **no** count and no rate for
  this spread; its only quantitative claim is relative and unanchored -- each
  room has "a slightly lower chance of receiving a key than they do of
  receiving items from other spread effects", with that comparison class
  itself unquantified.

  So the bucket (0-9 rooms -> 3, 10-24 -> 4, 25+ -> 6) is borrowed from the one
  spreader that does have a published formula, marked `confidence: inferred`.

  Act on this cold as: the wiki says keys are **rarer** than other spread
  items, so this borrowed figure probably **overstates** the Locker Room. It is
  a placeholder chosen for consistency, not a measurement -- replace it the
  moment real play gives a number, and do not cite it as sourced.

- **2026-08-10, the Conference Room absorbs a spreader's self-item too.**
  Owner, on an asymmetry in the wiki: the Patio page explicitly says the
  redirected gems "**include the gem that would spread in the Patio itself**",
  while the Locker Room page says "any key that would be spread to **another
  room**", which read literally would leave its own self-key behind.

  Both spreaders behave the same way: everything they would have spread,
  including their own self-item, lands in the Conference Room. The Locker
  Room's wording is treated as loose rather than meaningful.

  Still unstated and still unresolved: **how many** keys land there. The wiki
  gives "a number of keys" with no quantity and, unlike the Patio, not even a
  dependency hint. The bucket above supplies the number by default.

- **2026-08-10, the Conservatory is a Green Room, and the Aquariums count as
  every colour.** Owner, on a Patio spread having to decide what "Green Room"
  means and our data disagreeing with the wiki twice.

  The Conservatory is `MainType=Green Room` on the wiki and was `blueprint`
  here -- a plain data error, now corrected. The four Aquarium records were
  also `blueprint`, with the `counts_as_all_colors` flag ruled in on
  2026-08-10 existing **only in prose**: a repo-wide grep found it in the
  ruling itself and in one "Not modelled" note, nowhere in code or data. It is
  now implemented, because a Patio spread is exactly the category-comparison
  site that ruling described.

  Measured before the fix: a Patio spread would have targeted **24** rooms
  where the wiki implies **29**, understating the payout by up to 5 gems in a
  large house.

  Act on this cold as: a ruling recorded but never implemented is
  indistinguishable from one never made. The `counts_as_all_colors` flag sat
  in the decisions log for a day while every category-keyed mechanic quietly
  ignored the Aquarium.

- **2026-08-10, the Geist Bedroom's dice are picked up inside the room.**
  Owner: "Dice are on the table inside. You have to enter to pick them up."
  Confirms the entry-time reading the wiki only hinted at with the word
  "spawns", and matches every other resource grant in the engine. No change
  was needed; the open question is closed.

- **2026-08-10, the Speakeasy is a no-op and is exempt from the worklist.**
  Owner: "speakeasy is a no-op because we assume they can solve puzzles."

  `speakeasy__ix10`'s effect ("Basic Addition") only makes the Dartboard Puzzle
  easier -- one board instead of two to five, one ring, two numbers, addition
  only. The puzzle is not modelled and its reward is assumed won, so an easier
  puzzle pays exactly what the Billiard Room already pays.

  Recorded through a new `_AUDIT_DOCTRINE_EXEMPT_IDS` table rather than left on
  the worklist, because "we model this as nothing, deliberately" is a claim
  worth stating once, not a gap worth re-triaging every pass. That is now the
  **fourth** exemption channel, alongside locks.json, hand-written Python
  branches, and texts that merely restate a field.

- **2026-08-10, the engine provides capabilities and rooms declare effects.**
  Owner, raised as a concern about "two radically different paths for room
  definitions" and settled in the same exchange: **tabular data stays tabular;
  complex functions belong in code.**

  So `rooms.json` is NOT converted to Python. Four reasons, recorded so the
  question does not reopen: it is **generated** by `tools/ingest_sheet.py` from
  the datamined dump, and converting it would break the re-ingest path that
  absorbs a future datamine and carries `meta.source`/`meta.confidence`; the
  content is densely tabular (169 rooms, with 47 carrying effects tags, 43
  flags, 37 draft conditions, 32 dig spots, 31 guaranteed items);
  `validate_data.py`'s cross-record schema and referential checks are natural
  over one document and awkward over 169 modules; and
  `test_ingest_overrides.py`'s round-trip guarantee only exists because the
  data is data.

  What the ruling *does* change is where **behaviour** lives -- see task 21 for
  the three layers, the measured starting point, the enforcement test and the
  sequencing.

  Act on this cold as: the inconsistency the owner named is real but sits one
  layer below where it first appears. It is not JSON versus Python -- it is
  that Python room behaviour is scattered across 20 modules while only 27 rooms
  have a discoverable module of their own. The fix is an invariant ("no engine
  module branches on a room id"), not a file-format migration.

- **2026-07-27, Catacombs unlock**: `catacombs_unlocked` is true only on days the
  Tomb has been **drafted as the outer room AND entered**. It is deliberately NOT a
  permanent carry-over flag, even though the wiki says the angel-statue puzzle opens
  the wall permanently, because reaching the Catacombs still needs the Tomb present
  that day. Modelled as a data flag `flags.unlocks_catacombs` on the Tomb record
  rather than a hardcoded room id, so the rule is a data edit.

  This also settles the "Catacombs unlock condition" open decision in
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md).

  **Measured afterwards, and it does not deliver.** Real multi-day play with
  `greedy_rank` (~83k upgrade events per arm) gives a paired lift of **1.11x at
  z = 1.06 — not significant**; the always-unlocked ceiling is **1.91x**. Diagnosis:
  `P(catacombs_unlocked at insert)` is 8.24%, but line 7 also requires
  `min_drafts['cloister'] >= 1`, which fails on 88.7% of upgrade events because the
  Cloister is offered on only 5.87% of days. The gate is correct modelling that
  does not move the number.

- **2026-07-27, deferred gates default OPEN, explicitly stubbed**: each deferred
  mechanism gets a named stub that currently passes, carried in the data as
  `stub: true` and listed in a table so later PRs know exactly what to tighten.

  The alternative — closing them — was rejected because it kills **8 of the 36
  nodes**:
  Blackbridge Grotto needs POWER, Orindian Ruins sits behind the Grotto, the
  Safehouse needs water level exactly 6, the Well needs water ≤ 8, and Underpass /
  Inner Sanctum / Sigil Chambers / Upper Rotating Gear all sit behind the Rotating
  Gear position. That would delete Blackbridge Grotto, the one thing task 4
  uniquely supplies. An unreachable node measures exactly zero, which is a worse
  and more misleading failure than a slightly-too-generous world.

  **Consequence to print next to any number measured before the mechanism PRs
  land: it is an upper bound.** The `stub: true` flag is what keeps that visible
  rather than mysterious.

- **2026-07-27, Cloister frequency boosts**: model **all three** — the Terrace
  (makes the Cloister free while on the estate) and the Southern Cross / Greenhouse
  boosts. These touch Cloister's 5.87% per-day offer rate, which is the actual
  bottleneck on observing an Orinda decision. This is Phase 3 of
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md) and is independent
  of task 4; it does not block the Phase 1 A/B, which needs no offer and no rare draw.

  **Audited 2026-08-05: two of the three were already implemented when this was
  written.** The Terrace boost works (`free_green_drafts`, `effects/tier1.py`, adds
  `"green"` to `free_categories`; Cloister is `category: "green"`), and so does the
  Greenhouse boost (`priority_draws.json` carries `category: green, chance: 0.4,
  condition: greenhouse_or_king`, and `draft.py::_active_conditions` emits
  `greenhouse_or_king` from `state.greenhouse_placed`). Only **Southern Cross** is
  genuinely missing, and it is the one that matters most here — see task 14.

- **2026-07-27, `absent_spawn_rooms` resolved**: the field named off-grid AREAS,
  never rooms, and the check was silent in both directions. Renamed to
  `meta.absent_spawn_areas` and validated against `areas.json` node ids as well as
  `rooms.json`. Corrections from the wiki: `sanctum_key`'s `reservoir` became
  `reservoir_north` (the graph splits the halves; the box is on the Foundation
  Elevator side — inferred, not datamined, since the wiki gives no side), and
  `key_of_aries`'s `precipice` became `unknown_underground` (the clock is in the
  Unknown; the Precipice is only the access route). `file_cabinet_key` ->
  `crate_tunnel` was already correct: there are three distinct File Cabinet Keys,
  and the Archives Upgrade Disk sits behind the Patio key from the Aquarium, which
  is already modelled.

  Note the limit, confirmed by mutation: the new check catches nonexistent ids but
  **not** a wrong-yet-valid one. Restoring `precipice` passes validation, because
  it is a real node. That correction came from research, not tooling.

- **2026-07-27, travel actions are offered only to `modelled` areas**: exposing all
  36 nodes made the open stub gates expensive for the first time. 13 nodes are
  reachable on day 1 — including Blackbridge Grotto, the Precipice and the
  Safehouse — and none has modelled contents, so a random policy spent **80% of
  its steps** wandering an empty map (off-grid, 99.8% of the legal mask was
  travel). That is a direct tax on the fresh retrain.

  Fixed with a required boolean `modelled` on each area node. Only modelled nodes
  are offered as destinations; the pathfinder still routes through the others.
  Eleven are modelled today: `house`, `garage`, `west_path`, and the 8 outer
  rooms. Off-grid step share fell to 30%.

  **An action slot exists for every node regardless**, so switching an area on
  later is mask-only — no action-space change, no extra retrain. The flag lives in
  the data precisely so it is not a Python list of "useful areas" to hand-maintain.

  This does NOT touch the earlier "stubs default OPEN" decision: the stubs are
  still open and anything measured is still an upper bound. It only stops the sim
  from advertising empty rooms as somewhere worth walking.

  Note `greedy_rank` is unaffected — it never uses travel actions, and batch
  results are byte-identical to before this PR, so the Phase 1 A/B instrument is
  unchanged.

- **2026-07-28, `outer_rooms_unlocked` split into `west_gate_unlatched` and
  route-based outer-draft gating**: `GameConfig.outer_rooms_unlocked` was doing
  two jobs — gating the Grounds<->West Path shortcut AND gating outer-room
  drafting entirely. These are different facts (owner-confirmed 2026-07-28):
  on a brand-new save you CAN reach the West Path and draft an outer room from
  day 1 by going through the Garage (whose `garage <-> west_path` edge is gated
  only by `garage_door_breaker`, i.e. the Utility Closet placed and entered).

  **What changed:**
  - `outer_rooms_unlocked` renamed to `west_gate_unlatched`. The new name means
    exactly one thing: the Grounds<->West Path shortcut is open. It does NOT gate
    outer-room drafting.
  - `outer_draft_available()` no longer checks any config flag. It requires only
    an affordable route to `west_path` (via `_outer_route_cost()`) plus the
    existing once-per-day and phase conditions.
  - `west_gate_unlatched` is now earned in-run: `travel_to("west_path")` sets it
    on first arrival (necessarily via the Garage on a fresh save). `shops.carryover()`
    surfaces it; `DayChain._CARRYOVER_KEYS` carries it across days.
  - `fresh_save_config()` added to `rl/train.py` as the day=1 counterpart to
    `all_unlocks_config()`. `configs/fresh_save.yaml` provides the same preset for
    the `--config` CLI path.
  - `blueprince-train --unlocks {all,none}` selects between presets (default `all`).

  **The in-run discovery is recorded on `GameState`, never written back to the
  config.** The first implementation mutated `game.cfg` directly; the trainer builds
  ONE `GameConfig` per worker and reuses it for every episode, so that leaked the
  unlock into every later "fresh save" episode — measured: a second episode with no
  Garage placed at all inherited the 2-step Grounds route. `carryover()` ORs state
  with config, the same shape as `entrance_vase_broken` / `outer_chip_dug`.

- **2026-08-04, the three Basement doors are independent, Basement-Key-only
  locks**: the wiki treats `Basement_door` as a door *type* with three
  instances — the Grounds side (the drained Fountain's floor, feeding
  `well -> reservoir_south`), the Foundation's elevator (feeding
  `the_foundation -> basement`), and the Crate Tunnel (unmodelled). Each
  unlocks **permanently and independently** the first time a Basement Key is
  used on it; any other normal or special key, and the Lock Pick Kit, do not
  fit. Owner decision, on interview: gate the Foundation's own door
  (`basement_key_foundation`, a second `kind: "item"` gate alongside the
  existing `basement_key_well`, same shape) rather than reusing the Well's
  gate id, since the two doors are genuinely separate locks that happen to
  share one key item. Before this, `the_foundation -> basement` was gated only
  by the (open, stub) elevator mechanism, so an empty inventory could reach
  `basement` for free through the Foundation once it was drafted and
  grid-connected — measured at 5 hops from the house with the Foundation
  placed. That loophole is closed; holding the Basement Key restores the same
  5 hops (a Power Hammer via `sealed_entrance` remains a 3-hop alternative that
  needs no key at all).

  **Held-key modelling simplification, stated explicitly rather than left to
  look like an oversight**: the real rule is "this door has been unlocked,
  permanently, by a Basement Key at some point"; the sim instead checks "a
  Basement Key is currently held right now". The two coincide in practice
  because `basement_key` is `persistence: "permanent"` and is re-granted from
  the Antechamber pillar on first entry every day, so once earned it is always
  held for the rest of the save — there is no path by which the key is used
  and then given up. See `areas.md` for the full writeup and
  `foundation-design.md` for the corrected critical-path analysis.

- **2026-08-04, the Sealed Entrance break is unconditionally permanent**: the
  three area-graph gates that used to model this (`power_hammer_planks` on
  `grounds -> sealed_entrance`, `power_hammer_wall` on `sealed_entrance ->
  basement`, and `basement_sealed_entrance_return` on `basement ->
  sealed_entrance`) were all item/flag gates checked fresh every day, so
  despite their own `detail` text claiming "permanent once broken" nothing
  ever latched that — and `basement_sealed_entrance_return` was never even
  added to `_gate_ctx`'s flag set, per the docstring's own admission ("NOT
  modelled; never added here"). Replaced with one `sealed_entrance_broken`
  flag gate shared by all three edges, set permanently in `state` the first
  time the player arrives at `sealed_entrance` (`Game.travel_to`), carried
  across days the same way as `west_gate_unlatched`/`mine_south_visited`.

  The wiki's `Sealed_Entrance` page states a conditional the owner was shown
  and explicitly overrode: *"If just the Basement wall is destroyed, it will
  respawn on the next day, whereas if just the planks are destroyed, neither
  side will respawn."* Owner decision, on interview, having played the game:
  there is no such distinction — breaking either barrier is permanent. That
  plank-vs-wall conditional is deliberately **not** modelled; this is an
  unresolved discrepancy between the sim and the wiki's stated mechanic,
  recorded here to be re-tested in game rather than re-derived from memory.

- **2026-08-06, the Precipice is an EXIT from the Abandoned Mine, not an
  entrance.** Owner correction, from play: the mine is reached from the house
  side — the Catacombs via the Tomb, the drained Fountain plus the Basement
  Key, or the lowered Reservoir crossing from the north — and only then are the
  8 candlesticks lit to *lower* the stairway to the Precipice. The graph had one
  physical stairway as two edges with different rules (`mine_south -> precipice`
  behind an item gate, `precipice -> mine_south` ungated), making the Precipice
  a free front door.

  This was not only a free Upgrade Disk. The route
  `house -> grounds -> precipice -> mine_south -> reservoir_south` walked
  **around the `basement_key_well` door**, so a day-1 empty inventory reached
  `reservoir_south` (4 hops) and the `safehouse` (5) — a **Sanctum Key source**.
  All three are now unreachable without the key; holding it restores
  `reservoir_south` at 3 and `mine_south` at 4, so the legitimate routes are
  untouched.

  An item gate was the wrong instrument regardless: measured, gating the reverse
  edge on the old `candlestick_stairway` item gate left the mine unreachable
  with an empty inventory but reachable again in 3 steps while **merely carrying
  a torch**. Both directions now share a `candlestick_stairway_lit` **flag**
  gate, set through the existing ignition system (`mine_south` became an
  `"area": true` ignition target; `lit_targets` already persists across days).
  Act on this cold as: the held-item simplification that is fine for
  `basement_key` (holding ≈ having used) **breaks** whenever reaching the place
  to use the item is itself the difficulty.

- **2026-08-06, the Shelter and the Boudoir both grant the safe gem.** The
  assumed-solved doctrine covers the Shelter's real-time timed safe and the
  Boudoir's 1225 code exactly as it covers the Office/Study/Drawing Room codes.
  This **overrides** the earlier hold-back that excluded both pending a call.
  Because a safe is a fixture of the room it survives every upgrade, and room
  effects are NOT inherited through `variant_of`, so `boudoir__ix16/17/18` each
  carry the grant in their own right — without that, upgrading the Boudoir would
  silently delete its safe. The Shelter is an OUTER room: its grant rides
  `Game.travel_to`'s `Hook.ON_ENTER`, which was verified to fire before the edit
  was made rather than after.

- **2026-08-06, "Underground" in task 3 is Rotating Gear (upstairs).** Owner
  clarification of a name that matched no room id. It is a room off a hallway
  from the **Underpass**, opened by Boiler Room steam; **assume the player
  unlocks it permanently after entering the Boiler Room**. One step from the
  Underpass, holding **a gem** and the **Treasure Trove blackprint**, with a
  return step back down. It is **not** reachable from the existing
  `rotating_gear` node.

  This maps onto the existing `upper_rotating_gear` node and its
  `boiler_room_steam` gate (an open stub), so the work is making that gate real,
  not adding a node — and it settles the reverse-edge audit's open question:
  `boiler_room_steam` **is** permanent.

- **2026-08-06, the Treasure Trove permanently gains +5 coins every time it is
  drafted**, making it a very valuable room. The Key of Aries / black-chest
  mechanics are **explicitly deferred** — do not model them with this.

  **Clarified 2026-08-07, after the first implementation got it wrong.** The
  room accumulates a 5-coin pile per draft and **every draft collects the whole
  surface**, so the Nth draft this attempt pays **5 × N**:

  | draft | pays |
  |---|---|
  | 1st | 5 |
  | 2nd | 10 |
  | Nth (N ≤ 32) | 5 × N |
  | 32nd | 160 |
  | 33rd and every later one | **160** |

  The wiki's "maximum of 32 piles (160 Gold Coin total)" caps **what a single
  draft is worth, not what the room earns over an attempt**. Past 32 piles the
  payout stops *growing*; it does not stop. The first 32 drafts alone come to
  5 × (1+2+…+32) = **2640 coins**, which is what "a very valuable room" meant.

  The first implementation read the cap as ending the payout — a flat 5 per
  draft, 160 lifetime, then nothing — which is worth 6% of the real figure and
  would have made the room barely worth drafting. Act on this cold as: when a
  source gives a cap alongside a per-event gain, establish whether the cap
  bounds the *event* or the *total* before coding it; here the two readings
  differ by 16x. Pinned by `test_drafts_past_the_cap_keep_paying_160` and
  `test_attempt_total_is_not_capped_at_160`.

- **2026-08-06, `king` splits into per-colour tags.** The Banner of the King
  picks ONE colour per day, identical to the Royal Scepter, so emitting a bare
  `king` tag would fire all five category biases at once. The five entries
  become `king_blueprint` / `king_hallway` / `king_bedroom` / `king_shop` /
  `king_blackprint`, mirroring the `scepter_<colour>` shape. **The Banner item
  itself is deliberately not wired** — no source for how it is obtained exists
  in our data, so the tags are correctly shaped and stay inert.

- **2026-08-06, task 6 ruled: `diary_key` is removed, everything else stays.**
  Owner, after the audit. Only `diary_key` goes — the wiki itself says it has
  "no other known use", and the sim double-sources it (a Tomb luck-roll spawn
  *and* an unconditional Tomb-ignition grant) for an item that then sits inert.
  Removing it is data-only; no Python references it. Its ignition-grant entry
  must go in the same change, because `validate_data.py` resolves every ignition
  grant id against the special-items table.

  **`file_cabinet_key` is now an explicit KEEP**, reversing the audit's
  recommendation. `basement_key` remains a KEEP because it gates traversal --
  the argument, and the two gates it holds, are in
  [`areas.md`](areas.md#items-this-unblocks).
  `sanctum_key` stays **deferred**: unlike `diary_key` it is genuinely consumed
  and genuinely gates traversal, and it fails the removal test only because
  Inner Sanctum is unbuilt — not because the item is inherently choice-free.
  With 8 chambers and non-unique keys it may present a real choice once that
  lands, so re-run the decisive test then rather than assuming the answer now.
  `key_of_aries` stays deferred pending the Treasure Trove work.

- **2026-08-06, the Reservoir water gate is a NEW `reservoir_north <->
  reservoir_south` edge, not a gate on the mine crossing.** Owner correction of
  an earlier ruling that named `reservoir_south <-> mine_south`: the two
  Reservoir halves are freely traversable in both directions once the water
  level is set, and `reservoir_south <-> mine_south` stays **free and ungated**.
  This is the level-13 side-to-side boat crossing task 11 already records as
  "not currently represented as a graph edge/gate at all" — a **different** gate
  from `rowboat_water_6` (level exactly 6, the Safehouse rowboat); both retire
  in `PR-pump-room`.

  **Also owner, from play: `mine_south <-> mine_north` can NEVER be traversed —
  a mine cart blocks the way.** The graph already has no such edge, so this
  needs no data change, but it is now a sourced fact rather than an accident and
  is recorded in `docs/areas.md` so nobody later "fixes" the missing edge.

  **This gate defaults CLOSED — a deliberate exception to the 2026-07-27
  "deferred gates default OPEN" convention**, and the reason is measured, not
  assumed. With an empty inventory and only `sealed_entrance_broken` set (a
  Power Hammer sets it; it carries across days), an *open* crossing puts
  `reservoir_south` at 5 hops from the house, `mine_south` at 6 and the
  **`safehouse` at 6 — a Sanctum Key source** — all of which need the Basement
  Key today. The free route is `house -> grounds -> sealed_entrance -> basement
  -> reservoir_north -> ...`, walking straight around `basement_key_well`; that
  is exactly the loophole the Precipice fix closed one entry above. The
  convention's own rationale ("closing a gate kills 8 of 36 nodes") does not
  apply, because the edge is **new**: closed, the reachable set is identical to
  today's, so nothing is deleted and there is no empty-action-mask risk. Act on
  this cold as: the stubs-default-open rule is about not deleting existing
  reachability — it is not a licence to *grant* reachability the real game
  gates.

- **2026-08-07, the Tunnel chain deals THREE options, not one.** Owner, from
  play: the chain offers three rooms every time and merely *guarantees* a Tunnel
  is one of them. The sim dealt exactly ONE forced Tunnel and skipped the
  three-slot deal — its own docstring said so. Measured, 60 seeds: drafting
  north from a Tunnel dealt 1 option in 60/60; drafting south dealt 3.

  **This explains the apparent "Tunnel spam" completely, and it was never a
  reward exploit.** Across the 329 recorded episodes of `runs/postfix-v1` there
  were 210 Tunnel placements in 45 episodes: **exactly 45 genuine choices, one
  per episode, and 165 forced single-option hands (78.6%)**. No episode ever
  held two real Tunnel choices. A policy taking the only card it is dealt is not
  gaming anything, so **no reward change was made on this evidence**.

  The guaranteed Tunnel goes in **slot 0**, which **overrides the owner's own
  recollection** of a middle slot. The wiki's `Drafting/Advanced` says "a Tunnel
  is drawn into Slot 1", and that page is 1-indexed — its "Slot 1 always makes a
  Free Draw" matches this engine's free-only slot 0, and "a Library is drawn
  into Slot 3" matches the existing priority-draw index 2. The conflict was
  surfaced rather than silently resolved, and the owner ruled for the wiki.

  **Sourced but deliberately NOT implemented**: the same wiki line ends "This
  does not repeat on redraws" — redealing a chain hand should not re-guarantee
  the Tunnel. The code re-triggers on every redeal because it keys only off
  `from_room`/`direction`; distinguishing the initial deal needs new per-hand
  state.

- **2026-08-07, the Garage gets its Forced Draw; the other three precedence
  rooms do not.** Owner, from play: the Garage appears far more often in the
  real game, typically ranks 4-5 in column 0. Cause: `forced_draw_precedence`
  has been **dead data since the area work** — nothing in `src/` ever read it.

  Datamined rule, now implemented: forced into **slot 3** at **90%** (**92.5%**
  with the West Gate), gated on **Veteran Mode or Day 3**, blocked when the
  first two slots are both Dead Ends, **once per day**, with the roll retrying
  at each eligible doorway until it succeeds. Measured over 5000 episodes at
  every doorway where the Garage is legal: `greedy_rank` **17.61% → 53.59%**,
  `random` **39.06% → 78.31%**.

  The Garage's **placement rule was already correct** (West Wing, ranks 4-8,
  entered north or west — five legal tiles, wiki-verbatim), so the owner's
  "ranks 4-5" observation was about frequency, not geometry.

  **Scope is the Garage slice only**, for specific reasons: Conservatory sits
  behind the unmodelled Found Floorplan mechanic, Morning Room behind a Bacon &
  Eggs prerequisite of unverified completeness, and Utility Closet's own forced
  draw is *gated on the Garage having already been drafted*. The precedence list
  stays data. The Garage's separate **Day-5**-or-Veteran 3% passive priority
  draw is a **different gate** from the **Day-3** forced-draw gate and is
  deliberately not implemented — do not conflate the two thresholds.

  Two unsourced readings, recorded rather than buried: "or Slot 2 was not drawn
  by a normal draw" is read as slot 1's `DraftOption.forced` being False; and
  the forced draw is checked **before** the existing priority draws, because no
  source specifies precedence between the two systems. Note also that Forced
  Draws and Priority Draws are **different mechanics** — the wiki is explicit
  that one filters the deck for a round and the other pushes a room into slot 3.

- **2026-08-07, per-option orientation choice is NOT a mechanic.** `ALT_BASE`
  reserved three action ids nothing could ever select: `action_mask` never set
  them (verified live as all-False at every draft), and `apply_action` routed
  them through the identical `game.choose(slot)`, which takes no orientation
  argument. `GameConfig.orientation_choice` was read nowhere. Owner ruling: an
  option arrives with a rolled orientation, and rotation is a separate effect
  (Ornate Compass / Rotunda / Dovecote) already modelled by `ROTATE_ACTION`,
  which advances every option together. Both removed; `N_ACTIONS` 314 → 311.

  Act on this cold as: a dead id in a masked action space misleads every later
  investigation — this one survived long enough to be mistaken for a missing
  feature. `test_macro_actions.py::test_every_action_kind_has_a_masking_site`
  now asserts every declared `*_BASE`/`*_ACTION` has a write in `action_mask`.

- **2026-08-07, the depth-vs-reachability question is DEFERRED, to be measured
  after the Tunnel fix.** A Tunnel corridor proves `deepest_rank` can reach 9
  while the Antechamber stays literally unreachable: a `straight` room drafted
  north is always N|S, so a Tunnel spine has **zero lateral connectivity by
  construction**, and a column-1 corridor can never reach the Antechamber in
  column 2. In the traced episode `distance_map()` reported the Antechamber
  unreachable from step 1 through termination while `deepest_rank` hit 9, and
  `antechamber_reached` stayed false throughout. `_phi_paths` misses it because
  it counts *global* frontier doorways, not whether a room added branching.
  Measured, Tunnel placements net **+0.109** each against **+0.030-0.033** for
  ordinary rooms — ~3.3x the reward density, risk-free and gem-free.

  That gap applies to a *chosen* Tunnel too, so it survives the drafting fix.
  **Owner decision: change no reward constants yet.** Once the Tunnel is one of
  three options, measure how often the policy actually **chooses** it; well
  above the ~33% base rate means the reward genuinely overvalues cheap depth and
  can then be tuned against evidence rather than a 50k-episode artifact.

- **2026-08-08, Veteran Mode is the default, including on a fresh save.** Owner:
  the sim is written for experienced players, who trigger Veteran Mode on day 1
  by drafting the first three rooms out of the Entrance Hall quickly. **The
  trigger is not modelled — only its outcome**, the same assumed-solved doctrine
  applied to room puzzles.

  It gates three systems, and the effect differs sharply by preset because
  `all_unlocks_config` runs at day=20, where the day counter already satisfied
  two of them:

  | | all_unlocks (day 20) | fresh_save (day 1) |
  |---|---|---|
  | gem deck-size gates | already on via day >= 16 | **now active** |
  | Garage forced draw | already on via day >= 3 | **now active before day 3** |
  | Upgrade Disk slots | **veteran tables** | **veteran tables** |

  Non-veteran picks the first upgrade from a weighted table (Storeroom 35%,
  Courtyard 25%, then a tail); veteran is **uniform over all 16 slots** plus a
  **day-1 shortcut firing 70%** of the time.

  **Consequence worth acting on: a fresh save is no longer the loosest possible
  draw environment**, because the gem gates now bind from day 1. The
  `fresh_save_config` docstring previously claimed `gem_gate_active()` is off
  until day 16; that is no longer true and was removed. Veteran Mode is also
  **not a permanent unlock** — it is triggered per save by how the player opens
  day 1 — so it sits with `royal_scepter_found` under the deliberate exceptions,
  not with the earned unlocks.

- **2026-08-08, redraws work on the outer-room draft, from every source.**
  Owner: "Assume that the study works outdoors. I think the reroll works on all
  drafts" — clarified as the Study's **gem** rerolls specifically. So the
  `target_cell == -1` early-return in `_redraw_kind` goes away entirely rather
  than being narrowed to dice: the Classroom's free redraws, an ivory die, and
  the Study's 1-gem reroll (still capped at 8 per hand) all apply to an outer
  hand, with the existing cheapest-first precedence unchanged.

  **Recorded as owner-ruled and hedged ("I think"), not as sourced.** If the
  wiki later contradicts it, this is the entry to revisit.

  Not a one-line unblock, and worth knowing why: `Game.redraw()` also asserts on
  outer hands, and it calls `redeal()`, which runs the GRID pipeline
  (`_fill_options`: rarity rolls, decks, priority draws, the Tunnel chain) while
  outer hands come from a fixed pool of 8 shuffled on the `"outer_draft"` RNG
  label. Worse, `redeal()` opens with `state.grid[pending.from_cell]` and an
  outer hand has `from_cell = -1`, which Python does not reject — it silently
  reads the LAST grid cell. Lifting the assert alone would have dealt grid rooms
  into an outer hand from a fabricated "from room". The redeal needs its own
  outer path and its own RNG label, so the initial-deal sequence is untouched.

- **2026-08-08, the Apple Orchard becomes reachable and its +20 steps earnable.**
  Owner. `apple_orchard` and `campsite` flip to `modelled: true` so they are
  offered as travel destinations, and visiting the Orchard grants a permanent
  +20 starting steps through the carry-over machinery — the same shape as
  `west_gate_unlatched` and `sealed_entrance_broken`, which are likewise earned
  in-run rather than configured.

  Note this is a deliberate exception to the 2026-08-04 rule that a node only
  goes `modelled: true` if it "holds something worth walking to". The Orchard
  now does hold something: a permanent step bonus. The step-share measurement
  that rule exists to protect should be re-checked after it lands.

- **2026-08-08, the win rate is probably a CONTENT problem, not a learning
  problem.** Owner hypothesis, from playing: "the game is struggling to achieve
  the victory condition because there are exceedingly few implemented paths to
  victory." Measured, and it holds up.

  Reaching Room 46 needs an Antechamber door opened, which needs a lever room
  drafted AND entered. Over **400 `greedy_rank` days** on `all_unlocks_config`
  (mean 8.43 rooms placed):

  | lever room | placed |
  |---|---|
  | `weight_room` | 6.8% |
  | `great_hall` | 3.3% |
  | `greenhouse` | 1.3% |
  | `secret_garden` | 0.0% |
  | `throne_room` | 0.0% |
  | **any of them** | **11.0%** |

  `P(antechamber reached) = 0.000`, `P(room 46) = 0.000`.

  **So on ~89% of days no lever room is placed at all, and victory is
  structurally unreachable before the policy makes a single decision.** No
  amount of reward shaping fixes a day where the win condition cannot be
  opened. This reframes the standing `p_antechamber = 0.000` question, which
  three separate investigations have attacked from the reward side.

  Caveat, stated so the number is not over-read: `greedy_rank` pushes north and
  does not *seek* lever rooms, so 11.0% is "how often one turns up incidentally",
  not "how often a determined player could get one". `secret_garden` reads 0.0%
  because its key must first be found in the Attic or Music Room and this policy
  never pursues items — the key mechanism itself works (verified: holding
  `secret_garden_key` flips `satisfies_draft_conditions` from False to True).

  Act on this cold as: **before tuning the reward again, check whether the
  objective was reachable at all that day.** A win-rate denominator that
  includes structurally-unwinnable days is measuring room availability, not
  policy skill.

  Owner's plan is to re-measure after the Pump Room lands, since that opens
  routes the sim currently closes.

- **2026-08-09, training is parked; room fidelity is the only priority.** Owner,
  ruling on PR #84's open question. The Apple Orchard's off-grid step-share jump
  (35.67% -> 69.28%, 300 seeds, uniform-random masked play) is **accepted as-is**:
  both `campsite` and `apple_orchard` stay `modelled: true`. The reasoning is not
  that the tax is small -- it is that **the tax does not matter yet**, because
  "too few victory paths exist to make training worthwhile" (the 11.0% lever-room
  measurement one entry above). Optimising a training cost before the game is
  winnable is optimising the wrong thing.

  Two consequences to act on. First, this **suspends the usual "a node only goes
  `modelled: true` if it holds something worth walking to" discipline** (2026-08-04)
  for the duration of the audit -- but only suspends it: the step share must be
  re-measured, and this decision revisited, before any run is started. Second, the
  standing "do not start a training run mid-audit" rule now has a second and
  stronger reason behind it than checkpoint churn.

- **2026-08-09, task 15 sequencing: the test split ships FIRST, alone, to buy
  parallelism.** Owner. PR 1 is a pure reorganisation -- room-specific behaviour
  moves out of `test_game.py` / `test_effects*.py` / the scattered feature files
  into `tests/rooms/test_<room_id>.py`, one file per room. No behaviour change, no
  new assertions. It ships before any room fix because per-room files are what make
  the later PRs **genuinely disjoint**, and the repo rule is that parallel subagents
  need disjoint files including `tests/`. Without the split every room fix collides
  in `test_game.py` and the audit serialises.

  Granularity ruled: **one file per room, created as the audit reaches it**, not
  169 stubs up front and not per-category groupings. Rooms with no behaviour to pin
  get no file. The **absence** of a file is therefore a deliberate, readable record
  of what has not been audited yet -- the audit's own progress bar, kept in the test
  tree rather than in a document that can drift.

  After PR 1: identify sets of rooms whose behaviour is genuinely independent and
  give **each set its own PR**, rather than one large audit change.

- **2026-08-09, research doctrine for task 15: full wiki pass per room, with
  `effect_text` as a strongly-weighted prior.** Owner, refining the 2026-08-06
  "our datamined tables beat the wiki" ruling rather than repeating it. That ruling
  was about **magnitudes** -- exact percentages and payouts, where the decompiled
  sheet has won before. It does not extend to **coverage**: `meta.effect_text` is a
  single curated line and routinely elides an entire mechanic (the Secret Passage's
  five-colour choice, the Pantry's fruit). So every room gets a full wiki pass whose
  specific job is **finding mechanics the effect_text omits**, while `effect_text`
  stays authoritative on the numbers it does state.

  **Discrepancies are batched, not streamed.** Where the wiki and `effect_text`
  disagree on a *mechanic* (not a number), the room is parked and carried into a
  single consolidated question round put to the owner **before implementation
  begins** -- explicitly so the owner's involvement is one sitting rather than
  interruptions spread over hours. This is a process ruling with teeth: an agent
  that hits a discrepancy mid-implementation has already sequenced the work wrong.

- **2026-08-09, cross-day room mechanics are IN scope; "out of single-day scope"
  is retired as stale doctrine.** Owner, on being shown that seven rooms are
  unimplemented only because their own `meta.effect_text` annotates the mechanic
  as spanning days: `sauna`, `morning_room`, `master_bedroom`, `clock_tower`,
  `mail_room`, `freezer`, `break_room__ix11`.

  The annotation describes the simulator's past, not its present.
  `env/multiday.py:30` already carries 13 boolean flags across days plus
  `applied_upgrades`, `draft_counts`, `foundation_cell`/`foundation_doors`,
  `repellent_bans` and `carried_items`. The decisive precedent is one line in
  that same list, merged the previous day in PR #84:

      "orchard_unlocked",   # grants +20 starting steps next day

  which is exactly the shape `morning_room` ("+2 gems tomorrow") and `sauna`
  ("+20 STEPS tomorrow") need. All seven are implemented on that pattern.
  `mail_room` and `clock_tower` additionally need a small day-counter rather
  than a bool, which is new but shallow.

  **The stale annotations are corrected in the same work**, deliberately: an
  effect_text that wrongly says "out of scope" does not merely mislead a reader,
  it suppressed these rooms from THIS audit — several batches accepted the
  annotation and marked the room blocked. Two more of the same kind were found
  and are corrected with them: `throne_room` claims "entirely out of scope, no
  effect modeled" while `game.py:1510-1517` implements its north Antechamber
  lever, and `lost_and_found` claims the same while `special_items.py:499-668`
  implements its steal/gift. `trading_post` is a third (`shops.py` implements
  the full tier graph its metadata calls out of scope).

  Act on this cold as: **a scope annotation is a claim with an expiry date.**
  When the engine grows a capability, sweep the annotations that denied it.

  **Correction, same day: the Sauna grants STEPS, not coins.** The question
  round and the first version of this entry both said "+20 coins". The
  record's own `meta.glyph_resolution` resolves its glyph as `steps` at
  `datamined` confidence. The ruling is unchanged -- cross-day mechanics are
  in scope whatever the resource -- but the wrong resource would have been
  implemented from this entry.

  Act on this cold as: **never read a currency off the mojibake in
  `effect_text`.** Every ambiguous glyph carries its own
  `meta.glyph_resolution` entry with a confidence, and that is the
  authoritative resolver -- the ingest `GLYPH_MAP` resolves by UTF-8 byte
  value for exactly this reason. Three glyphs collide visually once the sheet
  is decoded: steps, coins and gems. `nurses_station__ix102` and
  `spare_master_bedroom__ix136` are steps too, not the coins they look like.

- **2026-08-09, a room stating an exact coin amount grants exactly that amount.**
  Owner. `items.guaranteed`'s `coins` count means *piles*, each rolling 1-5
  (`engine/items.py:92-106`, `items.json` `pile_min: 1, pile_max: 5`), so every
  room whose text promises a specific figure systematically misses it:

  | room | piles | range | mean | effect_text |
  |---|---|---|---|---|
  | `vault` | 8 | 8-40 | 24.0 | +40 coins |
  | `rumpus_room` | 2 | 2-10 | 6.0 | +8 coins |
  | `pantry` | 1 | 1-5 | 3.0 | +4 coins |

  The Vault is the case that decided it: a room the player spends keys to open,
  quietly worth **60%** of its advertised value. This needs a schema addition
  distinguishing "N coins" from "N piles"; the pile roll stays for rooms that
  genuinely scatter piles.

  **Note this is the sim disagreeing with BOTH sources, not a source conflict** —
  the wiki and the datamined effect_text agree on the numbers. It is therefore
  not covered by the 2026-08-06 "datamined beats the wiki" ruling, which
  arbitrates between sources and has nothing to say when they concur.

  Recorded because an earlier audit pass misread this as a data-entry slip
  ("count 2 against +8 coins, a fourfold under-grant"). It is not: 2 piles
  average 6, not 2. Act on this cold as: check what a count counts before
  calling it wrong.

- **2026-08-09, all 16 pool-name categories are corrected to real colours.**
  Owner. Task 15 recorded eight rooms carrying `category: "studio_addition"`;
  there are **sixteen** — the eight outer rooms carry `category: "outer"`, the
  identical fault.

      studio_addition: solarium, classroom, clock_tower, dormitory,
                       vestibule, casino, dovecote, the_kennel
      outer:           tomb, toolshed, root_cellar, shelter, hovel,
                       schoolhouse, shrine, trading_post

  The exclusion mechanism is `draft.py:302`, the category-targeted draw filter:
  a room whose category is a pool name can never be drawn by a category-targeted
  draw, which silently removes all 16 from the Secret Passage colour choice,
  scepter colours, `grant_per_category`, the Cloister/Terrace green boosts and
  every category bias.

  **It also left two branches unreachable**: `game.py:994` and `shops.py:359`
  both gate outer-room shop behaviour on `outer_room.category == "shop"`, which
  no outer room can satisfy. Verified behaviourally rather than by grep, per the
  standing lesson: all eight shops declared in `shops.json` are on-grid base
  rooms already carrying `category: "shop"`, and no outer room is a declared
  shop. This is the `forced_draw_precedence` shape again — a branch written for
  a condition the data never produces, silent in both directions. The Trading
  Post is the room it most likely concerns; its own effect_text opens "Counts as
  a Shop."

  Lands as its own PR: `Room.category` has 22 read sites, and this changes
  behaviour at `draft.py`, `tier1.py`, `state.py`, `special_items.py` and the
  `env/obs.py` category feature. **`CATEGORIES` in `env/obs.py` is left alone** —
  removing the now-inert `studio_addition`/`outer` slots would renumber every
  later category for no behavioural gain. `test_draft_stats.py` keys on rarity,
  not category, so it should be unaffected — confirm rather than assume.

- **2026-08-09, model correctness outranks observation- and action-space
  stability.** Owner: "Do not worry about changing the observation vector or
  action vector. I need the game to function properly before we train anything
  meaningful."

  This **suspends** the standing caution that has shaped several earlier
  decisions -- the 2026-07-27 "an action slot exists for every node regardless,
  so switching an area on later is mask-only", the PR2/PR3 merge whose split
  existed to keep the action space frozen, and the standing rule that an
  observation-space change kills every checkpoint the moment it merges
  ([`process.md`](process.md)). Those
  were correct while a run was live or imminent. No run is live, no checkpoint
  is being preserved, and the 11.0% lever-room measurement says a trained
  policy would be measuring room availability rather than skill.

  So during the room audit: **if widening the observation vector or adding an
  action is the natural model for a mechanic, do it.** Do not contort a design
  to preserve a vector nobody is training against.

  Two things this does NOT license, because neither is about checkpoints:

  - The carry-over vector and `upgrade_slots` must stay **sorted, never
    set-ordered**. Python randomises string hashing per process, so a
    set-ordered vector permutes between runs *within* a training session and
    silently corrupts learned field positions. That hazard is unchanged.
  - A dead action id is still a defect. `ALT_BASE` reserved three ids nothing
    could select and survived long enough to be mistaken for a missing feature
    (2026-08-07). `test_macro_actions.py` asserts every declared `*_BASE` has a
    masking site; keep it true.

  Act on this cold as: **record the width change even though it no longer
  blocks anything.** Whenever training resumes it forces a fresh run, and the
  cheapest time to know that is when it happens, not when a checkpoint fails to
  load.

- **2026-08-10, room behaviour moves to a room-id-keyed registry in Python; NOT
  to a class per room.** Owner asked for research on giving every room a class
  derived from the JSON, with `when_drawn` / `when_drafted` / `when_entered` /
  `when_room_drafted` hooks over a base class, on the premise that "we have
  moved past the point where we can represent functionality in data files".
  Owner explicitly invited a negative answer. The memo accepts the diagnosis and
  rejects the prescription; owner ruled to execute it.

  **The diagnosis holds, measurably.** 56 distinct room ids are hardcoded across
  20 Python files; 18 rooms have their behaviour split across data AND Python;
  16 base-pool rooms have an effect text, no data behaviour, and their whole
  implementation in Python. And **13 of the 22 effect tags are used by exactly
  one room**, most named after that room -- `solarium_weights`, `study_redraws`,
  `coins_per_deadend`, `pay_gems_with_steps`. The codebase had already converged
  on per-room handlers; it just keyed them by a tag string that is a synonym for
  the room and routed the call through a JSON file to get there.

  **The inheritance argument -- the part that looks most obviously right -- is
  refuted by the data.** Of the 56 upgrade variants that have both a parent and
  an `effect_text`, **zero** share their parent's text. Of the six variants that
  model nothing while their parent models something, inheritance would be correct
  for exactly one; `empty_closet__ix41`'s text is literally "0 items" and would
  have silently inherited the Closet's two. PR #90's bug was **unauthored
  records**, and inheritance would have hidden it behind plausible numbers
  instead of exposing it as conspicuous zeros.

  **Three costs the class proposal does not account for.** Six sites read
  `room.effects` *generically* rather than executing it -- including
  `items.py::expected_yields`, which feeds both the greedy policy and the Play
  tab -- so opaque methods would need a duplicate second method surface. `Room`
  is frozen and the `Registry` is shared across episodes
  (`blueprince_env.py:132`), so room *instances* with methods invite a
  per-episode state leak that room-keyed *functions* cannot. And a base class
  would need ~14 hooks to cover the five distinct query signatures the engine
  already fires (`_in_classroom_context`, two different rotation predicates,
  drafting-from-Library, placement legality, action masking), leaving 169
  subclasses inheriting a dozen no-ops each.

  **Performance is not a factor in either direction**: `effects.fire` measured at
  **0.2%** of runtime (1,401 calls, 0.003s cumulative of 1.40s). The hot path is
  `obs.encode` at 31% and `action_mask` at 27%.

  **What ships instead**, in this order, each green at every commit:

  0. A **divergence validator** in `validate_data.py` -- flag any variant that
     models exactly its parent while its effect text differs, and any record with
     an effect text that models nothing. Emits ~112 findings today, which is a
     machine-generated task-15 worklist and strictly better than the current
     "absence of a test file" progress bar. **Ships first and stands alone**,
     independent of every other decision here.
  1. **Widen `Hook`**: `ON_DRAFT_FROM`, `ON_HAND_DEALT`, `ON_ARRIVE`,
     `ON_DAY_END`. Four members today is why the Classroom and Dovecote branches
     are hardcoded in `game.py` -- there is no hook for "drafting FROM this room"
     or "this room is in the current hand".
  2. A **room-id-keyed handler registry** alongside the existing tag registry,
     with per-handler opt-in inheritance (`inherit=True`) rather than a blanket
     loader rule, so the Boudoir's fixture safe inherits and the Closet's items
     do not.
  3. Migrate the **13 singleton tags** to room modules under
     `engine/effects/rooms/`, mirroring `tests/rooms/` one-to-one.
  4. Relocate the genuine room-behaviour branches out of `game.py`/`draft.py`.
     Placement conditions, deck membership, shop stock, upgrade slots and action
     masking deliberately stay put -- those are subsystem concerns keyed by room,
     not room behaviour.
  5. Retire the behaviour half of `ingest_sheet.py`'s tables.

  **The mixed-ownership boundary is the shared/singleton split**, and drawing it
  anywhere else is the failure mode: the 9 shared parametric tags (44 of 57
  effect instances, and everything `expected_yields` introspects) stay in data. A
  tag lives in data or in code, **never both** -- leaving `effects` in
  `rooms.json` while Python handlers also exist creates exactly the second source
  of truth this is meant to remove.

  Act on this cold as: **the JSON is a cache of a Python source of truth
  already.** `EFFECT_MAP` and `EFFECT_OVERRIDE` are hand-authored Python dicts,
  `rooms.json` is their build artifact, and `test_ingest_overrides.py` exists
  solely to prove the two agree. Moving behaviour into code deletes that whole
  apparatus -- but only if the field moves out of the JSON entirely.

- **2026-08-09, allowance is a permanent accumulating total, and most of its
  sources are one-time.** Owner, prioritising it as the next lane-B item after
  noticing the Cloister's free token: "Most allowance tokens can only be
  collected once. Once collected, you cannot get another +2 boost from them
  again. The total accumulated allowance becomes your starting money the next
  day, so three +2 allowance tokens over seven days would result in 6 coins to
  start the eighth day."

  The wiki agrees: *"A set amount of gold granted at the beginning of each
  day"*, and *"As a permanent resource, allowance does not reset between each
  day and is generally never spent."* No base value and no cap are stated, so
  base 0 and no ceiling -- neither is invented. The packet appears in the
  Entrance Hall each morning; the sim starts the player there and assumes
  puzzles are solved, so granting it at `reset()` is the modelling
  simplification.

  **This settles task 10's open question** -- allowance is the daily gold
  packet, not a one-time grant -- and it makes the shape `orchard_unlocked`
  with an integer instead of a bool.

  **One-time sources need collection tracking, which uniqueness does not
  provide.** A unique item is only blocked while *held*; `remove(consumed=True)`
  records it in per-day state, so the source re-mints the next day. That exact
  bug was measured at 7 duplicate disks per day before `collected_disks` was
  added, so one-time allowance sources ride that same carried-set shape.

  Sourced from `https://blueprince.wiki.gg/wiki/Allowance`:

  - **One-time**: the Cloister (*"always present in the room until it is
    collected"*), Mora Jai boxes (*"do not respawn once solved"*), the
    Reservoir and Vault boxes (*"spawn only when their respective box are first
    unlocked and never again"*), the Entrance Hall vase.
  - **Repeatable**: Trading Post tier-5 trades, Jack Hammer digging, Room 8,
    the Quest Bedroom (owner: once per day maximum), Cloister of Lydia, Casino
    roulette (2 and 4 allowance prizes), the Guess Bedroom, the Laundry Room's
    Star/Allowance swap, and an "Experimental effect" worth +1.

  **Task 10 named the right three rooms; the mechanism is a Mora Jai box.** An
  earlier reading of this ruling claimed the Trading Post had no allowance
  source and that the Closed Exhibit was unsupported, because neither appears on
  the Allowance page. Both are wrong -- owner, from play: the Trading Post "has
  a Mora Jai box containing a +2 allowance token that can be opened exactly
  once", and the Closed Exhibit "has a Mora Jai box with a +2 allowance token".
  What the task got wrong was only the shape: it is a **one-time box**, not a
  standing per-day +2. The same is true of the Cloister's.

  **Mora Jai boxes are the general one-time allowance source.** From
  `https://blueprince.wiki.gg/wiki/Mora_Jai_Box`, ten standard locations, every
  one of which exists in our data:

  - **Master Bedroom** -- "one Allowance Token when completed"
  - **Solarium** -- allowance token
  - **Trading Post** -- owner-confirmed +2
  - **Closed Exhibit** -- owner-confirmed +2
  - **Tomb**, **Lost & Found**, **Tunnel**, **Throne Room** -- contents not stated
  - **Underpass** -- area node, contents not stated
  - **Inner Sanctum** -- area node, **8 boxes**, contents not stated

  Each is one-time: the Allowance page says Mora Jai boxes "do not respawn once
  solved". The endgame sets are explicitly excluded -- Aries Court's 8 boxes and
  Rough Draft's 46 contain "a note instead of an Allowance Token" and are not
  permanently opened.

  **Only the four confirmed boxes are implemented.** The six whose contents the
  wiki does not state are NOT assumed to match: inventing four to twelve more
  +2 sources on a pattern guess would move the economy invisibly. The Inner
  Sanctum matters most there -- eight boxes would be +16 from one area.

  Note `underpass` and `inner_sanctum` are area nodes, so `guaranteed_in` on a
  room record cannot reach them; the Abandoned Mine's disk uses
  `special_items.py::on_area_arrival` for exactly this case.

  Two things to check rather than carry forward: the wiki lists Vault box **53**
  alongside 149 and 233, which our data may not have; and the Entrance Hall vase
  is already modelled as a carry-over flag (`entrance_vase_broken`) that may not
  grant a token.

  Act on this cold as: **"the player gets a free X in room Y" needs its
  repeatability established before its magnitude.** A one-time pickup modelled
  as a standing bonus pays out forever, and nothing in a per-day test would show
  it.

- **2026-08-09, the Inner Sanctum's eight chambers are modelled separately, one
  per realm.** Owner: the Sanctum has "eight doors, each of which can be
  permanently opened by a Sanctum Key", and each Sanctum Key room needs its own
  model. `areas.json` currently collapses all eight into a single
  `sigil_chambers` node, whose own note already records the payoff: *"Each
  opened by 1 Sanctum Key (consumed), stays permanently open, grants +2
  allowance from its Mora Jai box."*

  The eight realms, from `https://blueprince.wiki.gg/wiki/Inner_Sanctum`:
  **Arch Aries**, **Corarica**, **Eraja**, **Fenn Aries**, **Mora Jai**,
  **Nuance**, **Orinda Aries**, **Verra**.

  Mechanics, verbatim from the same page and from
  `https://blueprince.wiki.gg/wiki/Sanctum_Key`:

  - *"Bringing a Sanctum Key here allows using it on one of the doors to
    permanently unlock that door."* *"The Sanctum Key is then consumed and
    cannot be used to open another door."*
  - *"There are a total of eight Sanctum Keys in the game."* Our data already
    carries exactly eight sources -- six `spawn_rooms` (`room_46`, `vault`,
    `clock_tower`, `throne_room`, `mechanarium`, `music_room`) plus two
    `absent_spawn_areas` (`reservoir_north`, `safehouse`).
  - *"Once used, the Sanctum Key is lost (and no longer spawns in the location
    it was obtained)."* Unused keys *"generally reappear in the same location on
    subsequent days"* unless stored in the Coat Check or retained by the Moon
    Pendant.
  - Each chamber holds a mechanism and a sigil puzzle; solving it reveals the
    rest of the chamber, which contains **a Mora Jai Box**. Under the
    assumed-solved doctrine that is a one-time +2 allowance per chamber, so
    **+16 across all eight**.

  **Open discrepancy, surfaced rather than resolved.** Owner: "The Sanctum Keys
  can only spawn after Room 46 has been reached for the first time." The wiki
  states that condition explicitly for **only one** key -- *"This Sanctum Key
  only spawns once Room 46 has been reached at least once"* -- and for the rest
  says merely that they are *"usually discovered around the same time Room 46
  has been reached for the first time."* The owner's rule is the stronger claim.
  Owner play outranks the wiki, but this one is worth re-checking in game before
  it is coded, because of the consequence below.

  **The consequence makes that gate load-bearing.** `P(room 46)` is currently
  **0.000** over 400 measured days. If all eight keys gate on having reached
  Room 46, the entire Inner Sanctum -- eight doors, eight Mora Jai boxes, +16
  allowance -- is unreachable content in every simulated day, and modelling it
  would produce a subsystem no policy can ever enter. If instead only one key
  carries that gate, seven remain collectable and the Sanctum is reachable
  before the win condition is.

  The owner also notes the first discoverable key sits in Room 46 alongside the
  Crown of the Blue Prince; the wiki adds that it *"can only be collected the
  second time the room is visited."*

  Act on this cold as: **check what a gate makes unreachable before implementing
  it.** A faithfully modelled subsystem behind a condition the sim never
  satisfies is indistinguishable, in every measurement, from not modelling it at
  all.

- **2026-08-09, all eight Sanctum Keys require Room 46, and simply do not
  spawn before it.** Owner, resolving the discrepancy surfaced by the Inner Sanctum
  chambers entry above: "All eight keys require reaching Room 46 for the first time. They
  simply do not spawn."

  **This overrides the wiki**, which states that condition for exactly one key
  (*"This Sanctum Key only spawns once Room 46 has been reached at least
  once"*) and says of the others only that they are *"usually discovered around
  the same time Room 46 has been reached for the first time."* Owner play
  outranks the wiki; the conflict is recorded here rather than resolved
  silently, so a later wiki edit does not look like it contradicts a bug.

  The gate mechanism already exists: `room46_reached` is a permanent carry-over
  flag, set on first arrival and carried by `DayChain`. No new state is needed
  for the gate itself -- keys check it at spawn time.

  **The consequence is deliberate, not a side effect.** Every Sanctum Key, all
  eight Sigil Chambers, and the +16 allowance behind them are unreachable until
  Room 46 is first reached -- and the measured `P(room 46)` is 0.000. That is
  acceptable under the features-are-built-to-be-PLAYED rule
  ([`doctrine.md`](doctrine.md)): the owner reaches Room 46 by
  playing, and the recorded day teaches the policy. The content exists so it can
  be demonstrated, not because the current policy will stumble into it.

  Act on this cold as: this is the first feature in the project built for the
  demonstration pipeline rather than for the policy's own exploration. Judge it
  by whether the owner can operate it in a recorded session, not by whether any
  measurement over untrained play ever exercises it -- none will.

- **2026-08-09, every Mora Jai box holds a +2 allowance token.** Owner, on the
  six locations whose contents the wiki leaves unstated: "They all include +2
  allowance tokens." So the pattern holds across all ten standard locations, and
  the earlier refusal to guess them is now resolved by ruling rather than by
  inference.

  The complete set, with the allowance each contributes once per save:

  | location | boxes | allowance | status |
  |---|---|---|---|
  | Cloister | 1 | +2 | landed |
  | Master Bedroom | 1 | +2 | landed |
  | Solarium | 1 | +2 | landed |
  | Trading Post | 1 | +2 | landed |
  | Closed Exhibit | 1 | +2 | landed |
  | Tomb | 1 | +2 | ruled here |
  | Lost & Found | 1 | +2 | ruled here |
  | Tunnel | 1 | +2 | ruled here |
  | Throne Room | 1 | +2 | ruled here |
  | Underpass (**area node**) | 1 | +2 | ruled here |
  | Inner Sanctum (**area node**) | **8** | **+16** | ruled here |

  **A fully explored save banks +36 allowance from Mora Jai boxes alone**, which
  is 36 coins at the start of every subsequent day, before any repeatable source
  (Cloister of Lydia, Trading Post trades, Jack Hammer digs, Casino roulette).
  That is a large permanent economy, and it is worth watching the first time a
  policy is trained against it: allowance is unspendable income that arrives
  before any decision is made, so it shifts what an early-day gem or key purchase
  is worth.

  **Two of the eleven cannot use `guaranteed_in`.** The Underpass and the Inner
  Sanctum are area nodes, not rooms, so a room record cannot reach them; the
  Abandoned Mine's Upgrade Disk solves the same problem through
  `special_items.py::on_area_arrival`, called from `Game.travel_to`.

  The endgame sets stay excluded: Aries Court's 8 boxes and Rough Draft's 46
  contain "a note instead of an Allowance Token" and are not permanently opened.

  Act on this cold as: the Inner Sanctum's eight boxes are **+16 of the +36**,
  so nearly half this economy sits behind Room 46 and the eight Sanctum Keys.
  Do not read a measured allowance figure from untrained play as representative
  -- none of it is reachable until Room 46 is.

- **2026-08-09, do not work on making Room 46 reachable by the policy.** Owner,
  asked directly whether the lever-room scarcity behind `P(room 46) = 0.000`
  should become a work item now that the Inner Sanctum, +16 of the +36 allowance
  and Room 8's reward all sit behind it. Answer: no -- keep authoring features so
  there is more to demonstrate. The 11.0% lever-room measurement stays a recorded
  fact rather than a task.

  This follows from the "features are built to be PLAYED" ruling: the owner
  reaches the late game by playing, so content value does not depend on the
  policy finding it unaided.

- **2026-08-09, `room_hook`'s `inherit=` parameter is removed.** It has had zero
  users across the Cloister, Sanctum and Closet features, all of which plausibly
  could have wanted it, and its docstring cites "the Boudoir's safe" as the
  example -- which is in fact a repeated data `grant`, not an inherited handler.
  So the parameter is unexercised and its only documentation points at code that
  does not exist.

  This is the `ALT_BASE` shape from 2026-08-07: an unused affordance that
  survives long enough to be mistaken for a working feature. Re-add it when
  something genuinely needs inheritance, with a real example.

  Owner selected both "tighten the docstring" and "remove entirely"; removal is
  the decisive reading and subsumes the other. Fall back to tightening only if
  removal turns out to be load-bearing.

  **Note the asymmetry this preserves**: the divergence audit's kind-1 check
  deliberately does NOT treat inherited coverage as authorship, and that
  reasoning stands on its own -- it is about what an inherited handler can
  demonstrate, not about whether the parameter exists.

- **2026-08-09, apple = 2 steps, orange = 5 steps, banana = 3 -- the wiki
  AGREES with the owner.** Recorded because the numbers were reported from play
  and then independently confirmed, so neither source needs re-checking. The
  Food page states each value directly, and the Pantry page derives the same
  three from a note puzzle ("one apple, one banana, and one orange grant 10 in
  total"). Our data already carried banana = 3.

- **2026-08-09, the Secret Garden spreads apples and oranges, uniformly -- NOT
  bananas.** Owner, from play, asked to check TFMurphy's datamining first.
  Checked: `tools/raw/tfmurphy_room_table.md` is a room table only and carries
  the effect *text* with no spread mechanics at all, and the datamined box
  republished on the wiki's Secret Garden page gives only the **total** fruit
  count -- room-count bucket plus soil bonus, capped at 10 -- and never a
  per-type split. **So the datamining does not settle it in either direction.**

  **This overrides the wiki**, whose Food page states: *"The effect of the
  Secret Garden spreads all three fruits."* Owner play outranks the wiki; the
  conflict is recorded here rather than resolved silently, so a later wiki
  citation does not look like it contradicts a bug. Each spread fruit is a
  50/50 apple-or-orange roll, mean 3.5 steps.

  Note the one place bananas ARE datamined into a Secret Garden outcome is the
  Conference Room case, and even there the fixed payout is **4 apples + 3
  oranges** with no banana -- which is consistent with the owner's account and
  mildly against the wiki's prose.

- **2026-08-09, soil quality is a flat Good (+4) everywhere until a real map
  exists.** The Secret Garden's spread total adds a soil term (Poor +2, Good
  +4, Rich +6) keyed to the cell it was drafted on. **That map is not published
  anywhere in wiki text** -- it exists only as an image in the Gardener's
  Logbook, and "barren", named on the House page as the low end of the range,
  has no published bonus value at all.

  Owner decision, on interview: encode a single flat +4, marked
  `confidence: inferred` in data, rather than block the feature or invent a
  12-cell map. The Secret Garden is wing-only across ranks 3-8, so a real map
  needs just 12 cells and can replace the constant with no code change.

  Act on this cold as: every Secret Garden spread total measured before a real
  soil map lands is an **estimate, not a bound** -- unlike the open stub gates,
  it can err in either direction (a Poor cell would spread 2 fewer, a Rich cell
  2 more).

- **2026-08-09, Room 8 pays 2 Allowance Tokens on the first solve of an
  attempt and 1 on every later solve.** Owner, on interview, following the
  trophies-are-achievements ruling. The wiki's real discriminator is trophy
  *possession*, not solve ordinality: *"If Room 8's puzzle is solved without
  ever collecting the trophy, it awards two Allowance Tokens on every
  completion."* With no trophy concept the sim cannot tell those branches
  apart, so the owner picked the reading that matches how a real player
  behaves -- the trophy is taken on the first solve, so the first solve pays
  +4 allowance and each later one +2.

  Room 8 is **repeatable per draft**, not once per save: *"Unlike the Gallery,
  Room 8 resets each time it is drafted even after being solved."* Multiple
  Key 8s allow multiple simultaneous Room 8s, each paying.

  The first-solve flag is per **attempt**, matching every other carry-over.

- **2026-08-09, `room8_placement` was wrong and is widened to any Rank-8
  cell.** Owner, on interview, shown the mismatch. `placement.py` permitted
  Room 8 on exactly **two cells** -- rank 8 col 4 entered northward, rank 8
  col 0 entered southward -- and its comment stated that as the rule. The wiki
  says Key 8 works on *"any locked door that leads to a room on Rank 8"*; the
  two cases the code whitelisted are the wiki's enumeration of when the room is
  **mirrored** (*"resulting in the corner room pointing left instead of
  right"*), not of where it may be placed.

  The decisive evidence is the wiki's own "reliable" route: Room 8 *"can be
  reliably drafted from the far door in the Great Hall, as it is always
  locked"*. The Great Hall is `layout: cross` with no draft conditions, so it
  sits in any column including the centre three -- under the old rule that
  route was impossible. Room 8 was very nearly undraftable, which is why the
  reward being unmodelled never surfaced in play.

  Act on this cold as: a `draft_conditions` tag that encodes an *orientation*
  rule as a *legality* rule silently deletes most of a room's placements. The
  mirroring belongs in the orientation layer, not in
  `satisfies_draft_conditions`.

- **2026-08-09, the `carryover` observation vector grew from 13 to 14.** Recorded
  under the standing rule that model correctness outranks observation-space
  stability while no run is live, **but that every width change is written
  down**. The new entry is `room8_solved`, added to
  `DayChain._CARRYOVER_KEYS` so Room 8's first-solve reward survives the day
  boundary.

  `env/obs.py` derives both the Box shape and the fill order from
  `len(DayChain._CARRYOVER_KEYS)` and `sorted(...)`, so the width moved with no
  edit to `obs.py` at all. That is convenient and also the hazard: **adding a
  carry-over flag silently changes the observation space.** Act on this cold as:
  any PR touching `_CARRYOVER_KEYS` is an observation-space change, whether or
  not it touches `env/`, and it invalidates every checkpoint trained before it.

  No run was live, so nothing was lost. Cumulative since the last training run:
  this is the only width change.

- **2026-08-09, the Mail Room's package contents ARE fully datamined -- the
  "implement timing only" fallback does not apply.** This retires the standing
  `[ASSUMABLE]` open question, which assumed the contents were "a randomised
  weighted tree" that might not be pinnable. The wiki publishes a datamined
  per-slot algorithm with exact probabilities: three independently rolled
  slots, slot 2 with a 50% chance of 2 gems, slot 3 conditioned on what slot 2
  produced. Freight's construction is deterministic given availability. Every
  item involved already exists in `special_items.json`.

  Only one number is genuinely unsourced -- see the Freight entry below.

- **2026-08-09, the base Mail Room's own effect text is wrong, and the wiki
  wins.** The in-game string, faithfully copied into
  `mail_room.meta.effect_text`, says a package "will be delivered here the day
  after drafting this room". The wiki contradicts it flatly: *"Despite the
  wording of the Mail Room's effect text, it does not have to be drafted the
  day immediately after placing the order; the package can wait any number of
  days for the Mail Room to be drafted again, and cannot be 'missed'."*

  Owner decision, on interview: model the wiki's mechanic. So the base Mail
  Room is **not a countdown at all** -- it is a persistent per-attempt state
  (`empty` -> `awaiting delivery`) advanced by the next draft of a Mail Room,
  whenever that happens.

  Act on this cold as: an implementer coding to `effect_text` alone would build
  a one-day timer that loses the package, which is a strictly harsher room than
  the real one. The card text is a game string, not a spec.

- **2026-08-09, No Contact Delivery arrives as a day-start inventory
  injection.** Owner, on interview. The wiki has the package sitting "immediately
  to the right of the starting position" in the Entrance Hall, openable. Rather
  than model a physical container, the contents are injected through the
  existing `GameConfig.starting_items` carry vehicle.

  The simplification, stated plainly: the player cannot decline or fail to
  collect a No Contact package, whereas in the real game they could in principle
  walk past it. Since the sim has no "decline the loot" concept anywhere, that
  difference is unobservable today.

- **2026-08-09, the Mail Room's Dynamic Rarity effect is DEFERRED, explicitly.**
  A waiting package sets the Mail Room's rarity to Commonplace for the day,
  which makes the delivered room far easier to draw again -- a real strategic
  effect, not flavour. `decks.py` has no rarity-override channel of any kind, so
  building it is its own piece of work touching the draft hot path that
  `test_draft_stats.py` guards.

  Owner decision, on interview: ship the delivery mechanic without it and
  record the gap here so the omission is visible rather than silent. Act on this
  cold as: any measurement of how often a delivered package is actually
  collected is an **under**estimate until this lands.

- **2026-08-09, Freight's four resource items are a uniform 1/3 across the three
  configurations.** The wiki states the set -- 4 keys, or 2 keys + 2 gems, or 4
  gems -- and publishes **no weights**. This is the single genuine gap in an
  otherwise fully datamined algorithm. Owner decision, on interview: encode a
  uniform third each, `confidence: inferred`, with a note saying only the set is
  sourced. Replaceable by a data edit the moment a real weighting appears.

- **2026-08-09, the `mail` observation went 2 -> 3 wide, a SECOND width change.**
  Recorded under the standing every-width-change rule, and recorded as a
  mispredicton: the base Mail Room PR sized the key at 2 (`[cycle, transit
  days]`) explicitly claiming that would make it "one width change, not two".
  That was wrong. No Contact Delivery's outstanding order is genuinely
  independent of the cycle -- it is placed on every draft and never uses the
  two-state machine -- so folding it into the cycle code would have made one
  field mean two things.

  Final shape: `[cycle code, transit days remaining, No Contact ordered]`.
  Slot `[2]` reads the **forward-looking** flag (drafted today, package lands
  tomorrow), not "a package arrived this morning" -- these keys exist so `V(s)`
  can price a cross-day investment, and the investment is the order, not the
  already-collected payout.

  Act on this cold as: reserving a slot for a *known* future field works (slot
  `[1]` absorbed Freight with no further change); reserving against an
  *unanalysed* one does not. Cumulative since the last training run: two width
  changes, `carryover` 13 -> 14 and `mail` 2 -> 3.

- **2026-08-09, lazy `configure()` seeding has now caused three separate bugs.**
  `special_items.configure()` is what seeds config-carried running values onto
  `GameState`, and it is guarded to run once per episode. Its call sites have
  repeatedly been too narrow:

  - PR #122: reachable only from `on_enter`, so a day spent travelling off-grid
    never seeded the one-time gates and area grants re-paid.
  - PR #134: not called from `shops.carryover()`, so a day that never entered a
    drafted room reported an unseeded `mail_cycle` at day end and silently
    cancelled an outstanding Mail Room order.
  - PR #136: not called at reset, so a day's **first** observation reported the
    field default rather than the carried value -- an agent cannot learn from a
    state vector that lies at the start of every day.

  Fixed at the root in #136: `Game.reset` now calls it directly, alongside every
  other field it seeds from config. Act on this cold as: **a lazily-seeded
  value is a bug waiting for a code path that reads it early.** Anything added
  to `configure()` from now on is seeded at reset and needs no new call site --
  do not re-introduce a lazy one.

- **2026-08-09, the Mail Room's cycle state is shared across all three variants
  -- a known gap, not fixed.** `GameState.mail_cycle` and `mail_package_cell`
  are a single global slot. If an `awaiting` cycle placed by one variant is
  still standing when a *different* variant is drafted, that variant delivers
  its own contents against the other's order.

  Narrow: it needs two different Mail Room upgrades applied across one attempt,
  and only one Mail Room variant is normally active at a time. Recorded rather
  than patched so it is not rediscovered as a surprise. Fixing it means keying
  the cycle by variant id, which is only worth doing if upgrade-swapping turns
  out to be common in real play.

