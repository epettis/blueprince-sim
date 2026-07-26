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
- **Selection**: the program "flips through various floorplans, seemingly at random,
  before settling on one to upgrade", then offers **three** upgrade options for that
  room; only the new icons are inspectable before choosing. The disk is consumed and
  the upgrade is **permanent** across days.
- **Supply**: exactly **16** disks exist — enough to perform every upgrade once.
- **Upgradable rooms** (16 upgrades): Spare Room (Spare Bedroom / Greenroom / Hall),
  Parlor (Gems / Keys / Funeral), Billiard Room (Speakeasy / Break Room / Pool Hall),
  Closet (Hallway / Bedroom / Empty), Storeroom (Keys / Gems / Coins), Nook (Extra
  Key / Breakfast / Reading), Mail Room (Same Day / No Contact / Freight), Aquarium
  (Goldfish / Starfish / Electric Eel), plus unnumbered Boudoir, Guest Bedroom,
  Nursery, Bunk Room, Hallway, Courtyard, Cloister (8 variants); Spare Bedroom
  uniquely allows a second upgrade.
- The wiki publishes **no** tier list of "best" upgrades. It notes one endgame trick:
  switching *off* Cloister of Joya keeps its benefit while applying another upgrade.

**Owner decisions** (interview, 2026-07-26) — implement to these:
1. **Random room, agent picks the upgrade.** Inserting a disk rolls a random
   upgradable room (wiki-faithful), then the agent chooses among that room's three
   upgrades — 3 new action slots, masked to the offered options. Keeps the luck
   element while leaving a real strategic choice.
2. **Terminals**: Security, Laboratory, Office, Shelter, Blackbridge Grotto (the
   last is outside the grid — gate it behind task 4). Insert requires standing in a
   terminal room holding a disk; the disk is consumed.
3. **Persistence**: an upgrade lasts the rest of the 200-day attempt and **resets on
   chain wrap**, consistent with every other carry-over flag. Mechanically this
   means `carryover()` adds the chosen variant id to `GameConfig.upgrade_disks`
   (which already drives deck building) and `DayChain` clears it on wrap.
4. Supply cap: 16 disks exist in the real game; each upgrade can be applied once.
   Track applied upgrades so a room is never offered twice in one attempt.

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

## 5. Throttle the training terminal output

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

Worth measuring before and after with `tools/benchmark_env.py` or a short timed run
so the win is quantified rather than assumed.
