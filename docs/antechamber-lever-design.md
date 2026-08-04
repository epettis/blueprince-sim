# The Antechamber lever gate — design

Authoritative spec for open task 9. Read this before implementing; where it and a
summary elsewhere disagree, this wins.

Scope: **B1, the entry gate only.** Room 46 and the north door are B2 and are
described here only far enough to show the seam.

## The rule

The Antechamber has four doors. Three of them — **West, South, East** — are sealed
walls until a lever elsewhere on the estate is pulled. The fourth, **North**, leads
off-grid to Room 46 and is a separate matter (B2).

Today the sim opens all four unconditionally (`game.py`, `placed_doors[42] = 0xF`)
and a day is won by walking into cell 42. That skips the entire gate.

### Doors reset every night

Wiki, verbatim: *"The Antechamber resets at the end of each day, closing all doors
and resetting all levers to their initial states."*

So the gate is **per-day**. Every winning day must reach a lever room *that day*.
This is the single most important fact in this document, and it is easy to get
wrong, because two of the lever sources have genuinely permanent components:

- Secret Garden — *"The state of the vane and niche are permanent and do not reset
  from day to day."* The **vane alignment** persists. The **door** still closes.
- Weight Room — the Power Hammer wall break reveals a space that is *"always
  accessible on future days."* The **wall** stays broken. The **door** still closes.

In both cases permanence reduces the *cost of reaching the lever* on later days. It
never leaves an Antechamber door open overnight.

## Geometry

The Antechamber is cell 42 (rank 9, col 2). `segment_key` canonicalises to the lower
cell, so each door is named from its neighbour:

| Antechamber door | Segment | Neighbour cell | Lever source |
|---|---|---|---|
| South | `(37, N)` | 37 = rank 8, col 2 | Greenhouse (already modelled), Weight Room |
| West  | `(41, E)` | 41 = rank 9, col 1 | Secret Garden |
| East  | `(43, W)` | 43 = rank 9, col 3 | Great Hall |
| North | off-grid   | —                  | Inner Sanctum / Throne Room (B2) |

The Antechamber's north side faces the outer wall, which is why Room 46 lives
off-grid and belongs to the area graph rather than the 5×9 grid.

Note the south door is the one that matters most in practice: the natural approach to
rank 9 centre is from rank 8 centre. West and East only matter when a room is drafted
at rank 9 col 1 or col 3.

## Lever sources

Per-day unless stated. The sim's standing assumption — *the player solves the puzzle
of any room they enter* — means **entering the room pulls its lever**, subject to the
access cost below.

| Source | Opens | Access cost | Persistence of the access |
|---|---|---|---|
| Greenhouse | South | holds `broken_lever`; installs it | day (already modelled) |
| Weight Room | South | `power_hammer` to break the wall the **first** time | wall break is permanent |
| Secret Garden | West | none beyond entering (vane assumed solved) | vane is permanent |
| Great Hall | East | lever sits in a prize room behind a locked side door | per-day key cost |

Draftability is the real throttle, and it is uneven — worth knowing before reading
any measured number:

- Weight Room — `standard`, base pool. The cheapest route to the south door.
- Great Hall — `unusual`, base pool.
- Secret Garden — `rare`, and gated by `secret_garden_key` + wing + rank 3–8.
- Greenhouse — `commonplace`, but needs the `broken_lever` item in hand.

## Sealed is not locked

A sealed Antechamber door is **not** a locked door. A locked door costs a key; a
sealed one cannot be opened by any key, only by its lever. They must be distinct
states, and everything that reasons about traversal has to treat sealed as
impassable rather than as expensive:

- movement and reachability (`reachable_cells`, `_antechamber_reachable`)
- the action mask: opening a sealed door is never a legal action
- termination: "no frontier and the Antechamber is unreachable" must still fire
  correctly, or days will hang instead of ending

**But NOT `optimistic_distances` / `grid_ante_dist`.** That map answers "could a
route exist at best?", and it already ignores locked and security doors on exactly
that reasoning — you might find a key. A sealed door is the same kind of claim: you
might pull the lever. Treating it as a wall there makes the Antechamber read as
unreachable from day one, which flattens the navigation signal and the shaped
reward's potential, and the measured win rate falls to *exactly* zero rather than
merely low. An objective that never fires teaches nothing.

The seal must bite at real traversal, not at planning.

Getting this wrong in the permissive direction silently restores today's behaviour
and the gate measures nothing. Getting it wrong in the strict direction strands the
player and ends days early. Both need tests.

## Expected impact, and why it needs a flag

Today `P(reach Antechamber)` is **3.405%** (20k paired episodes, `greedy_rank`,
all-unlocks day-20). Requiring a lever multiplies that by the probability of
drafting *and* entering a lever room on the same day. The result will be materially
lower, and that is correct rather than a regression.

But it makes the pre-lock baseline irreproducible, and
[`upgrade-value-measurement.md`](upgrade-value-measurement.md) requires that the
pre-lock and post-lock measurements differ *only* by locks. So the gate is behind

```
GameConfig.antechamber_levers: bool = True   # False reproduces the old open-door model
```

Default **True** because it is the faithful model. `False` exists so the existing
baseline can be re-measured on demand, not as a soft launch.

## Deliberate simplifications

Each of these is a place the sim is knowingly less faithful than the game. They are
listed so they can be revisited rather than rediscovered:

- **Entering a lever room pulls its lever**, immediately and for free. The real game
  requires walking to the lever and interacting. This follows the sim's existing
  puzzle-solved doctrine.
- **Levers cannot be pushed back up.** The game lets a player close a door again;
  nothing in the reward structure would motivate that here.
- **The Secret Garden vane is assumed already aligned west.** Modelling the first-time
  alignment as a separate step would add a permanent flag whose only effect is on
  day one of an attempt.
- **The Great Hall prize door is charged as a flat key cost**, not modelled as one of
  the two specific prize rooms.

## B2 — Room 46, the north door, and the two-tier objective

**Room 46 is the objective; the Antechamber is a prerequisite, not a victory**
(owner, 2026-08-02). This is the part of task 9 that changes what "winning" means.

### The Antechamber stops ending the day

`game.py` terminates the day the moment the player stands on cell 42
(`_terminate("antechamber")`). Room 46 lies *through* the Antechamber, so that
termination makes the real objective unreachable by construction — it has to go.

It was always a simplification: the README lists "Antechamber entry model" among
the known ones, and the wiki says the day continues (a pillar presents the Basement
Key: *"To continue up, you must go down."*). Removing it is a fidelity fix that B2
forces rather than a new liberty.

Consequences, all of which must be handled together:

- `Game.success()` means **reached Room 46**, not reached the Antechamber.
- `termination_reason` loses the value `"antechamber"`. Days end on `out_of_steps`
  or `dead_end` as they already do.
- `GameState` records `antechamber_reached` and `room46_reached` as separate
  per-day facts, so both remain measurable.
- **Six code sites currently key the win off `termination_reason == "antechamber"`**
  — `game.py::success`, three in `env/rewards.py`, three in `rl/train.py`, plus
  `cli/batch.py` and `cli/play.py`. All must move to the Room 46 flag together, or
  the reward and the reported win rate will silently disagree.

`P(reach Antechamber)` stops being the headline metric. It stays reported as a
milestone rate; `P(reach Room 46)` becomes the victory rate. **Numbers from before
this change are not comparable to numbers after it.**

### The north door and Room 46

Room 46 sits beyond the Antechamber's north door, which faces the outer wall — so
Room 46 is an **area node**, not a grid cell, reached by travelling north from
cell 42. It joins `areas.json` like any other node and reuses the travel machinery.

The north door has two levers, and neither is on the grid:

- **Inner Sanctum** — the main lever, and the common first win. The lever is in the
  sanctum's *main area*: *"In the main area of the room, there is a lever to open the
  north door of the Antechamber."* It does **not** require the 8 Sanctum Keys —
  those open the sigil chambers, which are side content. Reaching `inner_sanctum` is
  sufficient.
- **Throne Room** — the backup. A `studio_addition` room, so it needs that unlock;
  the wiki notes it cannot be used on day one because the room enters the pool a day
  late.

The measured route is **8 area hops**: `house -> grounds -> sealed_entrance ->
basement -> reservoir_north -> mine_north -> rotating_gear -> underpass ->
inner_sanctum`, at one step per edge. Round trip is ~16 steps against a 50–70 step
budget, *plus* reaching rank 9, *plus* a side lever room. A winning day is therefore
demanding, which is correct — but it makes the Throne Room backup load-bearing for
any policy that cannot afford the walk.

### Everything resets overnight

The north door is an Antechamber door and resets with the rest: *"The Antechamber
resets at the end of each day, closing all doors and resetting all levers to their
initial states."* `room46_reached` is the exception — it is a permanent save-level
fact (`GameConfig.room46_reached` already exists as a gem-deck gate) and must be set
on first arrival.

### Reaching Room 46 does not end the day

Owner's decision, and it interacts well with the reward horizon: the win reward is
paid on arrival and **play continues** — the agent keeps collecting disks and
permanent upgrades to fund tomorrow, until steps run out or no legal action remains.
The cross-day bootstrap is what lets the value function see that continued
collection as worth something.

### Reward split

- Antechamber, first arrival of the day: **+0.25**, once.
- Room 46, first arrival of the day: **+1.0**, once.

4:1 keeps Room 46 dominant while the Antechamber stays a dense enough milestone to
train against, and a 1.25 ceiling stays close to today's scale so the existing
shaping constants remain roughly calibrated. Both are single constants, easy to
retune once there is real run data.

### Upper bound, stated plainly

The Sanctum route runs through `rotating_gear`, `underpass` and `reservoir_north`,
whose gates are still **open stubs** — the Rotating Gear position and the Pump Room
water level are not modelled, and there is no notion of POWER. So any Room 46 rate
measured now is an **UPPER BOUND**, and that caveat belongs next to every number.
