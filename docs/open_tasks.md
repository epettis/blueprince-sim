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
  Disks, this disk can appear repeatedly" — which is the 16th. The sim models the
  six reachable fixed sources today (`upgrade_disk_vault_304`, `_commissary`,
  `_garage`, `_trading_post`, `_lost_and_found`, `_tomb`) plus `upgrade_disk_trade`;
  the other nine sit in unmodeled rooms/areas and should be added with their rooms.
  Because every disk id is a UNIQUE item, the supply cap enforces itself: once the
  traded disk is held, tier-5 trades stop offering it and decay to dice.
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

**Now a prerequisite for measuring upgrades — schedule it before the upgrade
retrain.** This task supplies the `catacombs` record, and the Catacombs check
gates non-veteran chain line 7, the only line where Cloister sits first. Held
permanently false, Cloister of Orinda is offered on 0.07% of upgrade events;
unlocked, 2.96% — a 42x difference, and the difference between measurable and
not. It also supplies Blackbridge Grotto, the fifth disk-reader terminal. See
[`upgrade-value-measurement.md`](upgrade-value-measurement.md) for the numbers
and the sequencing argument.

Everything beyond the 5×9 grid — West Path / Outer Rooms, the Grounds, Blackbridge
Grotto, Orindian Ruins, the Precipice, the Abandoned Mine, Crate Tunnel, the Inner
Sanctum — is modeled today only as the single "outer room" doorstep abstraction
(`outer_loc` 0/1/2 plus fixed step costs in `GameConfig`).

**Owner is supplying the area graph** (nodes, edges, and the dependencies that gate
each edge — microchips, keys, opened walls, lit candles). Until then this stays
blocked. When it arrives, the natural shape is a data file (`data/areas.json`)
of nodes/edges with per-edge requirements, replacing the hard-coded outer costs, and
an action set for moving between areas. Several currently-inert items unblock with
it: microchips, Power Hammer wall breaks, the Sanctum keys.

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
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md). Consequence: the
  42x lift quoted there assumed the check simply being true, so the realized gain is
  that figure scaled by P(Tomb drafted and entered) — roughly a 1-in-8 outer-room
  draw, times the chance the agent spends the steps to walk the West Path. The real
  offer rate must be **measured**, not assumed.

- **2026-07-27, area-graph scope**: task 4 is NOT a prerequisite for making Cloister
  of Orinda measurable. The Catacombs gate needs only the Tomb (already modelled),
  and 7 of the 9 unmodelled Upgrade Disks sit in rooms that already deal (Office,
  Morning Room, Her Ladyship's Chamber, Great Hall, Freezer, Archives, Mechanarium).
  Only **The Foundation** (record exists but `pool=none`) and the **Abandoned Mine**
  (no record) are genuinely off-grid. Task 4 still owns Blackbridge Grotto (the 5th
  disk terminal) and the action-space change worth bundling with the retrain.

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
