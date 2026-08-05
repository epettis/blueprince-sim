# Open tasks

Features the project owner identified while reviewing the special-items PR stack
(2026-07-26). These are NOT in `docs/plan.md`'s delivered set — each needs its own
design pass. Ordered roughly by how self-contained they are.

## 1. Resource spreading through the house

Several rooms scatter resources into OTHER rooms when drafted, rather than granting
them on entry. None of this is modeled today (the Tomb's per-dead-end gold is the
one exception — `coins_per_deadend` in `engine/effects/tier1.py`).

Known spreaders (owner-reported; verify counts against the wiki before authoring):

| Room | Spreads | Target |
|---|---|---|
| Patio | gems | Green Rooms |
| Secret Garden | apples and oranges (food) | throughout the house |
| Locker Room | basic keys | throughout the estate (high chance to seed itself) |
| Conference Room | — | absorbs every other room's spread instead (see below) |
| Office | money | throughout the house |
| Tomb | 5 gold per Dead End drafted | into the Tomb itself (ALREADY MODELED) |

**Conference Room override**: if a Conference Room is on the estate, every spread
resource spawns there instead of being distributed.

Design notes: this is a placement-time effect that writes items into *other* cells'
pending contents, so it needs a per-cell "resources waiting here" store that
`roll_room_items` consumes on first entry — the current model grants a room's items
purely from its own record. The Locker Room case matters for balance: its keys are
what make the room's 17 locked lockers openable (see PR #26).

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

## Also outstanding (from `docs/plan.md`)

- **Reward calibration** from multi-day training statistics — all shaping constants
  (`special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY`, scepter bias)
  are deliberate knobs awaiting real run data.
- **Inner Sanctum**: the 8 Sanctum Keys have sources and persist, but the area
  behind the 8 doors is unmodeled. Overlaps heavily with task 4.

## Decisions log

- **2026-07-26, lockers**: locked lockers cost exactly one BASIC key — the wiki is
  explicit that lockers are not doors, so the Lock Pick Kit, Master Key, Stopwatch
  and smashers do nothing. This is what makes the Locker Room's key-spreading
  (task 1) load-bearing rather than flavour.

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

- **2026-07-27, area-graph scope**: task 4 is NOT a prerequisite for making Cloister
  of Orinda measurable. The Catacombs gate needs only the Tomb (already modelled),
  and 7 of the 9 unmodelled Upgrade Disks sit in rooms that already deal (Office,
  Morning Room, Her Ladyship's Chamber, Great Hall, Freezer, Archives, Mechanarium).
  Only **The Foundation** (record exists but `pool=none`) and the **Abandoned Mine**
  (no record) are genuinely off-grid. Task 4 still owns Blackbridge Grotto (the 5th
  disk terminal) and the action-space change worth bundling with the retrain.

- **2026-07-27, task 4 sequencing**: task 4 runs BEFORE the Phase 1 forced-upgrade
  A/B. Phase 1 needs no checkpoint and so looks runnable immediately, but
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md) is explicit that a
  Phase 1 run made before task 4 is a **harness shakedown, not a bankable
  baseline** — task 4 changes the world the baseline describes, and the pre-lock
  and post-lock measurements must differ *only* by locks. Before task 4 is the only
  cheap window.

- **2026-07-27, task 4 PR1 scope — "graph traversal only"**: the stateful
  mechanisms the graph implies (POWER, Pump Room water level, the two elevator
  positions, the Rotating Gear position, the four torches) are NOT modelled in the
  first implementation. They land in later PRs.

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

- **2026-07-27, `absent_spawn_rooms` names non-existent rooms** (found while
  building the area graph, deliberately NOT fixed in that PR). Three special
  items name ids that do not exist in `rooms.json`:
  `sanctum_key` -> `["reservoir", "safehouse"]`, `file_cabinet_key` ->
  `["crate_tunnel"]`, `key_of_aries` -> `["precipice"]`.

  `validate_data.py` does not catch these, because it only errors when an
  `absent_spawn_rooms` id *does* exist in `rooms.json` (the check exists to catch
  a room being re-added without promoting it to `spawn_rooms`). So the mistake is
  silent in both directions.

  They appear to be **area** ids, not room ids — `safehouse`, `crate_tunnel` and
  `precipice` are all area nodes in `areas.json`. But `reservoir` matches nothing
  even there, since the graph splits it into `reservoir_north` and
  `reservoir_south`. Resolve this when PR2 wires areas into the engine and the
  distinction between a room id and an area id becomes real; until then the
  entries are inert.

- **2026-07-27, Cloister frequency boosts**: model **all three** — the Terrace
  (makes the Cloister free while on the estate) and the Southern Cross / Greenhouse
  boosts. These are the only unmodelled levers that touch Cloister's 5.87% per-day
  offer rate, which is the actual bottleneck on observing an Orinda decision. This
  is Phase 3 of [`upgrade-value-measurement.md`](upgrade-value-measurement.md) and
  is independent of task 4; it does not block the Phase 1 A/B, which needs no offer
  and no rare draw.

- **2026-07-27, task 4 PR2 and PR3 merged into one PR**: the split existed to keep
  the action space frozen until the env PR, protecting live checkpoints. That
  protection was already void — PR #36 moved `disks_held` to `Discrete(15)` and
  `n_items` to 76, so no checkpoint loads regardless. One retrain is owed either
  way, so splitting bought nothing and cost a throwaway compatibility layer
  (an `outer_loc`-shaped observation re-encoded from `state.area` purely to keep
  the old space alive for one commit).

- **2026-07-27, the West Gate is a save-level unlock, not a per-attempt one**:
  unlatching it is permanent across the whole save (owner-confirmed), so a
  `GameConfig` field models it and maps onto the `west_gate_unlatched` graph flag.

  This also retracts an earlier worry: honouring the gate does **not** shift the
  measurement baseline — day-1 outer-room access is unchanged.

  Refined 2026-07-28 (next-but-one entry): the field was also gating outer-room
  drafting, which is a different fact, and the gate CAN now be earned in-run.

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

- **2026-07-29, reward horizon — bootstrap across the day boundary**: a mid-attempt
  day ending is now `truncated=True` rather than `terminated=True`. SB3 bootstraps on
  `TimeLimit.truncated`, so `V(day N end)` picks up the value of day N+1 and cross-day
  investment becomes real value the agent can discover. Only the final day of an
  attempt (`current_day >= n_days`) is a true terminal.

  Chosen over making the episode span the whole attempt because the day boundary is
  genuinely non-absorbing, so this is the correct model rather than merely the cheap
  one — and every per-day telemetry consumer (`EpisodeRecorder`, `DraftStats`,
  `AreaStats`, win-rate) fires on `done = terminated | truncated`, which is still true
  at day end, so none of them changed.

  **Tradeoff, stated honestly**: credit propagates by one-step TD through the value
  function rather than by GAE across all within-attempt steps. The TD target is
  unbiased, but it is slower to propagate than multi-step returns; a within-attempt
  rollout would expose every cross-day transition to GAE at once. This is a
  convergence-speed cost, not a correctness one.

  `gamma` stayed at 0.999 and became a `--gamma` flag. An earlier claim that it
  "barely spans one day" was wrong: it was reasoned from `max_env_steps = 1000`, which
  is a safety cap, not a typical day. A day measures ~31 env steps, so 0.999 already
  gives ~32 days of lookahead. The discount was never the bottleneck.

  **Observability is half the fix, and the first cut got it wrong.** Bootstrapping is
  useless if the agent cannot see what it accumulated: `V(s)` has to be able to tell a
  heavily-upgraded attempt from a fresh one. The first implementation exposed only
  `DayChain._CARRYOVER_KEYS` — 6 booleans — while the chain also carries
  `applied_upgrades` and `collected_disks`, which are the actual "spend today to win
  later" investments. Four observation keys now cover it:

  - `day` — `[current_day, days_remaining]`; single-day mode is `[1, 0]`.
  - `carryover` — the 6 carry-over bools, sorted for stable field order.
  - `upgrade_slots` — one bit per upgrade slot, in `upgrades.all_slot_ids()` order.
  - `disks_spent` — how many of the finite one-time disk sources are used up.

  `all_slot_ids()` is derived by running `upgraded_slots()` over every registry
  variant, so the Spare Room's two-level chain stays defined in one place; it yields
  16 slots, matching the documented "15 rooms carrying 16 upgrade slots". Both it and
  the `carryover` vector are **sorted, never set-ordered**: Python randomises string
  hashing per process, so a set-ordered vector would permute between training runs and
  silently invalidate a checkpoint's learned field positions.

- **2026-08-04, The Foundation's 17 placement positions are ranks 3-8, not
  sourced**: the wiki states three placement rules (center 3 columns; never Rank
  2; never the Rank-8 cell directly under the Antechamber) plus a headline count
  of "17 positions", but the three rules alone leave 21 candidate cells once the
  Entrance Hall and Antechamber are excluded (23 before excluding them), not 17.
  The only way to land on exactly 17 is to also drop Ranks 1 and 9:
  `cols 1-3 x ranks 3-8 = 18, minus the Rank-8-under-Antechamber cell = 17`.
  Owner decision, on interview: **match the 17** — ranks 3-8 is now the coded
  rule (`the_foundation` draft condition, `placement.py`), understood as an
  inference from the stated count rather than a directly sourced rule. Act on
  this cold as: if a future wiki edit clarifies Rank 1 or Rank 9 explicitly,
  revisit the count derivation before trusting this rule further.

- **2026-08-04, only three area nodes plus the Foundation anchor go `modelled:
  true`**: of everything the Foundation's elevator opens up, only `basement`,
  `mine_south`, and `inner_sanctum` (plus the `the_foundation` grid anchor
  itself) are advertised as travel destinations. Owner decision, on interview,
  after measuring: everything else underground (`well`, `reservoir_south`,
  `reservoir_north`, `mine_north`, `rotating_gear`, `upper_rotating_gear`,
  `underpass`, `sigil_chambers`, `safehouse`, `catacombs`, `precipice`,
  `unknown_underground`) stays routed-through-but-unadvertised, so the step tax
  that motivated the original `modelled` flag (see the 2026-07-27 entry above)
  stays contained. `mine_south` earns its place specifically because it holds an
  Upgrade Disk, not because it is merely on the path. Act on this cold as: do
  not flip additional underground nodes to `modelled: true` without a similar
  "holds something worth walking to" justification and a fresh off-grid
  step-share measurement — the Sanctum route alone measured moving the off-grid
  step share from 29.93% to 41.88% under uniform-random play (see `areas.md`).

- **2026-08-04, the Foundation and Basement elevator gates stay open stubs**:
  `foundation_elevator_down` / `foundation_elevator_up` are not modelled this
  round — the wiki's elevator crank reveal (requires a room drafted so a door
  faces the Foundation's back wall) and nightly car-reset-to-the-top mechanic
  are real but deferred. Owner decision, on interview: leave them as the
  existing PR1 stub-gate convention (`stub: true`, passes unconditionally,
  `retire_in: PR-foundation-elevator`), consistent with every other deferred
  mechanism in this file. Consequence stated plainly: `the_foundation ->
  basement` is free once the room is drafted and grid-reachable, so any number
  measured through it (including the batch/reachability numbers in the PR that
  landed this) is an upper bound, exactly like the other open stub gates.

- **2026-08-04, Rank-3 draft removal implemented; Rank-4 dynamic rarity left
  open**: the wiki's "90% chance the Foundation is removed from the draft pool"
  when drafting on Rank 3 is implemented as a single per-hand roll (not
  per-card, to keep the RNG-draw count independent of deck order — see
  `foundation-design.md`). The wiki's separate claim that the Foundation's
  rarity "adjusts dynamically after reaching Rank 4" is explicitly NOT
  implemented — no curve is invented for it. Act on this cold as: if this
  becomes load-bearing later, it needs its own wiki research pass before any
  code is written; do not infer a curve from the Rank-3 number, they are
  different mechanics.

- **2026-08-04, the north-door reward is +0.5, paid by either lever, once per
  day**: the objective becomes three-tier — Antechamber first arrival (+0.25,
  existing), the Antechamber's north door opening (+0.5, new), Room 46 first
  arrival (+1.0, existing, the win). Owner decision, on interview: both levers
  (Inner Sanctum's main lever, Throne Room's backup) pay the same +0.5, because
  they accomplish the identical thing and the reward should stay neutral about
  which route a policy learns. Implemented as a per-day EVENT flag
  (`GameState.north_door_opened`) set only at the two lever call sites (unified
  through one `Game._open_north_door()` helper so they cannot drift), **never**
  derived from the north segment's own door state — with
  `antechamber_levers=False` the segment is never sealed to begin with, so a
  state-derived reward would pay +0.5 for free on every day of that arm and
  silently corrupt the pre-lever baseline that config exists to reproduce (this
  is guarded by a dedicated test in `test_sanctum_route.py`). Two consequences
  worth acting on: the per-day reward ceiling rises from 1.25 to 1.75 (the
  earlier 1.25 note argued for staying close to today's scale; a 40% rise puts
  that back in play, and shaping constants are not rescaled here — check
  whether dense terms get drowned out in the first retrain); and the Throne
  Room (one room, +0.5) is now priced higher than the whole rank-9 grind to the
  Antechamber (+0.25), which is an honest consequence of pricing the door
  rather than the walk, but is watchable as a farming incentive — compare
  `P(north door opened)` against `P(reach Room 46)` in the first retrain; a wide
  gap is the signature.

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

## 5. Throttle the training terminal output — DONE

The trainer currently refreshes the dashboard after every completed seed, which
costs real throughput on long runs (terminal writes are synchronous and the render
rebuilds the whole frame).

Requirements:
- Emit updates roughly **5% of the time** rather than every episode.
- Expose the cadence as a **command-line flag** on `blueprince-train` (e.g.
  `--dashboard-every 0.05` as a fraction, or `--dashboard-every 20` as "every Nth
  episode" — pick one and document it; a fraction reads better against "5% of the
  time").
- The rate should apply to the per-episode refresh path only. Keep terminal events
  that matter regardless of cadence (checkpoint writes, the chain's day rollover
  note, warnings) unthrottled, and make sure the final frame after a run ends is
  always rendered so the last numbers on screen are true.
- Relevant code: `src/blueprince_sim/rl/train.py` (the callback that calls
  `Dashboard.update` / `emit`) and `src/blueprince_sim/rl/dashboard.py`.

Implemented as `--dashboard-every FRACTION` (default 0.05 = one line in 20; 0
disables the per-episode lines entirely). The per-episode chain note was the only
high-frequency terminal output — every other emit is lifecycle (checkpoint, stop
signal, resume banner, final summary) and stays unthrottled, and
`dashboard.deactivate()` still renders a true final frame.

Not yet measured: the throughput win is assumed, not quantified. Worth a timed
before/after on a real run.

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
- Reservoir level `== 13` additionally lets the boat cross the Reservoir
  side-to-side (not currently represented as a graph edge/gate at all —
  needs its own gate once this lands, distinct from the Safehouse rowboat
  gate).

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
