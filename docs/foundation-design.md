# The Foundation, and the route it opens

The Foundation is the room that makes the underground reachable: it is drafted
once, never resets, and its elevator drops into the Basement. From the Basement
the estate's whole underground chain opens up, and at the end of that chain sits
the Inner Sanctum, whose lever opens the Antechamber's north door to Room 46.

This document is authoritative for the room and for the route changes that ship
with it.

## Why this is not just a room record

`the_foundation` already has a room record (`pool: "none"`, so it never deals)
and an area-graph anchor node (`modelled: false`). Turning the room on does
**not**, by itself, make the Basement or the Inner Sanctum reachable. Three
separate things blocked the route, measured before this change:

- `game.py::_gate_ctx` never set `mine_south_visited`. That flag gates
  `rotating_gear -> underpass`, and `underpass` has exactly one real entrance
  (`upper_rotating_gear -> underpass` is only reachable *from* the Underpass).
  So `inner_sanctum` was unreachable **by construction**, in every config, on
  every day.
- `basement_key` was `implemented: false`, so it never spawned. It gates
  `well -> reservoir_south`, which is the route to `mine_south`.
- `basement`, `mine_south` and `inner_sanctum` were all `modelled: false`, and
  `env/actions.py` only offers travel to modelled nodes.

Measured over 300 seeds of uniform-random masked play under `all_unlocks`:
`area_route_cost("inner_sanctum")` was finite **0.00%** of the time, travel to
it was offered **0.00%**, and the Antechamber's north door opened **0.00%**.
The Inner Sanctum lever in `travel_to` — the wiki's *"main area of the room,
there is a lever to open the north door of the Antechamber"*, and the common
first win — was dead code. The Throne Room was the only live north lever.

## The room

Wiki facts, quoted from `https://blueprince.wiki.gg/wiki/The_Foundation`:

- *"The Foundation does not reset each day, similar to the Entrance Hall and
  Antechamber."*
- *"This means that it will permanently remain in whatever position and
  orientation it is initially drafted in."*
- *"It can only be drafted in the center 3 columns of the house, making its
  placement similar to that of 4-way rooms."*
- *"It cannot be drafted on the Rank 8 location directly below the Antechamber."*
- *"It cannot be drafted anywhere on Rank 2."*
- *"This leaves just 17 positions in which the Foundation can be drawn and placed."*
- *"When drafting on Rank 3, there is a 90% chance that The Foundation will be
  removed from the draft pool for that draft."*
- *"The Foundation always contains two dig spots near the wooden walkways. It may
  contain up to two additional dig spots either side of the elevator."*
- *"Unlike other permanent rooms, Repellent can be used on The Foundation."*

### The 17 positions

The three stated placement rules do not reconcile with the stated count. Interior
columns across all nine ranks is 27 cells; removing Rank 2 (3) and the cell below
the Antechamber (1) leaves 23, or 21 once the Entrance Hall and Antechamber cells
are excluded. Only dropping Ranks 1 and 9 as well gives exactly 17:

    cols 1-3  x  ranks 3-8  =  18,  minus cell 37  =  17

The wiki never mentions Rank 1 or Rank 9 for this room, so **ranks 3-8 is an
inference from the count, not a sourced rule** (owner decision, 2026-08-04: match
the 17). It is encoded as one named `the_foundation` draft condition rather than
as a stack of primitives, following the `garage` / `boiler_room` idiom for
coupled column+rank rules.

### The Rank-3 removal

The 90% is rolled **once per hand**, not once per card: the wiki says "for that
draft". Rolling inside the per-card predicate would make the number of RNG draws
depend on deck order and break determinism. The roll happens only when the
Foundation is still placeable at all, to keep the disturbance to existing RNG
streams as small as possible.

**Rank 4 is an open question.** The wiki also says the Foundation's rarity
"adjusts dynamically after reaching Rank 4" without saying how. Nothing is
implemented for it; inventing a curve would be worse than a documented gap.

### Persistence

The placement carries in `GameConfig` as a cell plus a door mask, set from state
on the day it is drafted and re-placed by `reset()` on every later day. Being in
`placed_ids` from the start of the day is what keeps it out of the deck — the
existing one-copy-on-the-grid rule does the work, with no second mechanism.

Like every other carry-over it **resets on chain wrap**, consistent with
`used_vault_keys`, `lit_targets` and `collected_disks`. The wiki says nothing
about attempt boundaries; this follows repo convention rather than a source.

## Deliberate simplifications

- **The elevator crank is not modelled.** The wiki requires a room drafted so
  that a door faces the Foundation's back wall to reveal the FOUNDATION crank,
  and the car resets to the top nightly with a Keycard needed to summon it from
  below. `foundation_elevator_down` / `foundation_elevator_up` stay **open
  stubs** (owner decision, 2026-08-04), so `the_foundation -> basement` is free.
  Anything measured through it is an upper bound.
- **Repellent on a placed Foundation is not modelled.** `banned_rooms` keeps it
  out of the deck, but a Foundation already on the grid is not removed by it.
- **The Basement Key opens one graph edge, not "basement doors".** The wiki says
  it *"permanently unlocks that door"* for basement doors generally;
  `areas.json` models the single edge `well -> reservoir_south`. That edge is
  what puts the key on the critical path to `mine_south`, and so to the Sanctum.

## The route changes shipping with the room

Owner decisions, 2026-08-04, after measuring the three blockers above:

1. **Three nodes become `modelled: true`**: `basement`, `mine_south`,
   `inner_sanctum` — plus the `the_foundation` anchor itself. Everything else in
   the underground stays routed-through-but-unadvertised, so the step tax that
   drove the original `modelled` flag stays contained. `mine_south` earns its
   place by holding an Upgrade Disk rather than being a pure step sink.
2. **`mine_south_visited` becomes real**: set on arrival at `mine_south`, and
   carried across days, because `areas.md` marks the mine-cart move permanent.
3. **`basement_key` becomes implemented**: guaranteed on the Antechamber's
   central pillar on first entry, not consumed, permanent.

### The Basement Key is on a pillar, not a pedestal

*"Entering the Antechamber for the first time each day causes a pillar to emerge
from the ground in the center of the room, presenting the Basement Key and a note
stating 'To continue up, you must go down.'"* (`Antechamber`). *"Using the
Basement Key does not consume the key, allowing multiple basement doors to be
opened in the same day."* (`Basement_Key`).

### Both remaining Upgrade Disks land

`open_tasks.md` task 2 recorded 14 of the real game's 16 disks as modelled, with
The Foundation and the Abandoned Mine off-grid and unreachable. Both are now
reachable, so the supply is complete at **16 of 16**:

- **The Foundation** — an ordinary `guaranteed_in` room pickup, now that the room
  is on the grid, exactly like the seven existing in-grid disks.
- **`mine_south`** — a bespoke arrival source, like the Lost & Found and Tomb
  disks.

Both carry `persistence: "day"`, so they respawn nightly and only *spending* one
is permanent, per the 2026-07-27 disk-respawn decision.

**Sourcing caveat.** The Foundation's own wiki page does not mention an Upgrade
Disk. Only the `Upgrade_Disk` article does: *"The Foundation: An Upgrade Disk can
be found on a pile of boxes near the back of the room."* The two pages disagree
about whether the detail exists; the disk is modelled on the strength of the
`Upgrade_Disk` list, which is the same source the other fifteen come from.

## Opening the north door scores +0.5

Owner decision, 2026-08-04. The objective becomes three-tier:

| Milestone | Reward | Why |
|---|---|---|
| Antechamber, first arrival of the day | +0.25 | prerequisite, and the source of the Basement Key |
| Antechamber north door opened | **+0.5** | the thing standing between the estate and Room 46 |
| Room 46, first arrival of the day | +1.0 | the win |

**The reward is for the door opening, not for standing in the Sanctum.** Both
levers pay it: the Inner Sanctum's main lever and the Throne Room's backup. They
accomplish the same thing, so they score the same, and the reward stays neutral
about which route a policy learns.

The ordering tracks a real dependency chain rather than being merely numeric.
The Basement Key spawns on the Antechamber's central pillar, and it is what opens
`well -> reservoir_south` and so the route to `mine_south`, whose visit is what
opens `rotating_gear -> underpass`. So the Sanctum route runs
**Antechamber -> Sanctum -> back to the Antechamber -> Room 46**, and 0.25 < 0.5
< 1.0 pays each step of it in order.

It fires once per day, on the first opening, and is recorded as a per-day event
flag set at the two lever sites — *not* derived from the north segment's door
state. Those are different facts: with `antechamber_levers=False` (the config
that reproduces the pre-lever baseline) the segment is never sealed to begin
with, so a state-derived reward would pay +0.5 for free on every such day.

Two consequences worth stating rather than discovering later:

- **The per-day ceiling rises from 1.25 to 1.75.** The B2 note argued for 1.25
  on the grounds that it "stays close to today's scale so the existing shaping
  constants remain roughly calibrated". A 40% rise puts that back in play; the
  shaping constants are not rescaled here, and if the retrain shows the dense
  terms drowned out, this is the first place to look.
- **The Throne Room is now worth more than the Antechamber.** Drafting and
  entering one grid room pays +0.5, while the whole rank-9 grind pays +0.25.
  That is the honest consequence of pricing the door rather than the walk — the
  Throne Room genuinely does the necessary thing cheaply — but it is an
  incentive inversion, and a policy could settle into farming it daily without
  ever winning. It cannot repeat *within* a day; nothing stops it repeating
  across the days of an attempt. Watch `P(north door opened)` against
  `P(reach Room 46)` in the first retrain; a wide gap is the signature.

## What this does not fix

`inner_sanctum` is 8 area hops from the house, so the round trip is ~16 steps
against a 50-70 step budget, on top of reaching rank 9 and pulling a side lever.
Making the route *exist* is not the same as making it *worth walking*. If the
retrain still never finds Room 46, the two-tier constants in `env/rewards.py`
(`ANTECHAMBER_REWARD`, `ROOM46_REWARD`) are the knobs, not this route.

The open stub gates elsewhere in the underground (`pump_water_lte8`,
`rowboat_water_6`, the two elevators) are untouched and still pass
unconditionally, so **any Room 46 rate measured now is an upper bound**.
