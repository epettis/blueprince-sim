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

## B2 seam (not this PR)

Room 46 is the real objective; the Antechamber is a waypoint. B2 adds: an
`areas.json` node for `room_46` reached through the Antechamber's north door, the
north lever from the Throne Room (backup) and the Inner Sanctum (the main one, and
the common first win), and the two-tier reward where the Antechamber scores and Room
46 wins. Reaching Room 46 pays the win reward but does **not** end the day — the
player keeps collecting to fund tomorrow.

The Inner Sanctum route runs through area-graph nodes whose gates are still open
stubs, so any Room 46 rate measured before those mechanisms land is an **upper
bound**.
