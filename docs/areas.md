# Outside-area connectivity graph

Status: **owner-reviewed; implemented.** This is the specification for
`open_tasks.md` task 4. [`areas.dot`](areas.dot) is the same graph in Graphviz
form; the two must be kept in step.

The graph ships as `src/blueprince_sim/data/areas.json`, parsed by
`engine/areas.py` into an immutable `AreaGraph` with gate evaluation and BFS
pathfinding at 1 step per edge. It is the engine's only model of where the
player is when off the 5x9 grid: `GameState.area` holds an area node id (or
None on the grid), and route costs are derived by BFS rather than declared.

Delivered in two parts. PR1 shipped the graph as data plus the pure traversal
library, calling nothing. The second PR adopted it in the engine *and* changed
the action and observation spaces together — originally planned as two PRs,
merged once it was clear the retrain they force was already owed for #36, so
splitting them bought nothing and cost a throwaway compatibility layer.

Render the picture with:

```bash
dot -Tpng -Gdpi=150 docs/areas.dot -o /tmp/areas.png    # or -Tsvg
```

## Ground rules

- **Every edge costs exactly 1 step** (owner-confirmed).
- **Every edge is directed.** The gate that admits you to an area is usually not
  the gate that lets you out, and one passage is strictly one-way. Reverse trips
  are separate edges with their own conditions.
- **One "travel to area" action per node** (~36 actions), masked to reachable
  destinations. The engine pathfinds and charges the cost, mirroring how
  `MOVE_TO_BASE` already works for grid cells. This is the action-space change
  that makes task 4 worth bundling with a retrain.

### The 1-step rule reproduces the existing constants

This is the main evidence the rule is right — these three values were verified
in play and are *derived* by the graph rather than contradicted by it:

| Path | Graph | `GameConfig` |
|---|---|---|
| Entrance Hall -> doorstep | House -> Grounds -> West Path = 2 | `outer_path_entrance_cost = 2` |
| Garage -> doorstep | Garage -> West Path = 1 | `outer_path_garage_cost = 1` |
| doorstep -> inside the outer room | West Path -> outer room = 1 | `outer_enter_cost = 1` |

It only works because **the Outer Room drafting cave IS the West Path's south
section**, not a separate node. An earlier draft split them and was off by one on
both routes.

## Nodes

**On-grid / drafted anchors** — not area nodes; shown only because outside edges
attach to them: `house`, `garage`, `the_foundation`, `tomb`, `schoolhouse`,
`hovel`, `toolshed`, `root_cellar`, `shelter`, `shrine`, `trading_post`.

**Surface**

| Node | Notes |
|---|---|
| `grounds` | Hub south of the Entrance Hall |
| `west_path` | Also the outer-room doorstep and drafting cave |
| `private_drive` | |
| `blackbridge_grotto` | **5th disk-reader terminal**; the one modelled terminal with no room record |
| `orindian_ruins` | Throne Room floorplan |
| `campsite` | |
| `apple_orchard` | +20 steps/day; lights a torch on ENTRY |
| `gemstone_cavern` | 2 gems/day; lights a torch on ENTRY |
| `crate_tunnel` | **Entrance only.** Igniting the torches grants the Tunnel floorplan; everything deeper is story, not progression |
| `sealed_entrance` | |

**Underground**

| Node | Notes |
|---|---|
| `basement` | |
| `well` | |
| `reservoir_south` / `reservoir_north` | Two halves; joined only through the Mine |
| `safehouse` | Sanctum Key |
| `catacombs` | |
| `mine_south` | **Upgrade Disk**; the mine cart is moved from here |
| `mine_north` | |
| `rotating_gear` / `upper_rotating_gear` | |
| `underpass` | |
| `inner_sanctum` | Lever opening the Antechamber **north** door |
| `sigil_chambers` | 8 chambers, one Sanctum Key each |
| `precipice` | |
| `unknown_underground` | Key of Aries clock |

**Upgrade Disks off-grid:** `mine_south` and `the_foundation` — the two of the
real game's 16 the sim still cannot reach. See `open_tasks.md`.

## Edges

Free/ungated reverse trips are omitted from this table for brevity; see
`areas.dot` for the complete directed set. Gate permanence: **P** = permanent
once satisfied, **D** = resets daily, **-** = ungated.

### Surface

| From -> To | Gate | |
|---|---|---|
| `house` <-> `grounds` | none | - |
| `garage` <-> `west_path` | garage door, breaker on | D |
| `grounds` -> `west_path` | west gate, only once unlatched from inside | P |
| `west_path` -> `grounds` | unlatch the gate from inside (first time) | P |
| `west_path` -> outer room | drawn as today's outer room (1 of 8) | D |
| `grounds` <-> `private_drive` | none | - |
| `private_drive` -> `blackbridge_grotto` | Laboratory steam/lever puzzle **+ POWER** | P |
| `blackbridge_grotto` -> `orindian_ruins` | all 3 microchips in the pedestal | D |
| `private_drive` <-> `campsite` | none | - |
| `campsite` -> `apple_orchard` | padlock code 1128 | P |
| `campsite` -> `gemstone_cavern` | V.A.C. puzzle (Utility Closet) + lever | P |
| `grounds` -> `sealed_entrance` | Power Hammer breaks the planks | P |
| `grounds` -> `well` | Pump Room: water level <= 8 | D |
| `grounds` -> `crate_tunnel` | ignition tool lights the torches | D |
| `grounds` -> `precipice` | cliffside elevator: 4 torches lit AND car at the top | D |
| `precipice` -> `grounds` | elevator, **only if the car was ridden down** | D |

### Underground

| From -> To | Gate | |
|---|---|---|
| `the_foundation` -> `basement` | elevator: crank revealed AND car at the top | P |
| `basement` -> `the_foundation` | elevator: **keycard to SUMMON** if the car is not already down | D |
| `sealed_entrance` -> `basement` | Power Hammer breaks the wall | P |
| `basement` -> `sealed_entrance` | regrows daily unless the Grounds planks are also broken | D |
| `basement` -> `reservoir_north` | pallet-jack puzzle | P |
| `well` -> `reservoir_south` | Basement Key (not consumed) | P |
| `reservoir_south` <-> `mine_south` | none | - |
| `reservoir_north` -> `mine_north` | mine cart moved (**requires Mine South visited**) | P |
| `reservoir_north` <-> `rotating_gear` | none | - |
| `reservoir_south` <-> `safehouse` | rowboat; water level exactly 6 (two-way) | D |
| `tomb` -> `catacombs` | seven-angel puzzle; wall permanent, but the Tomb must be drafted that day | P |
| `catacombs` -> `mine_south` | lower Draxus's scythe. **ONE-WAY**, shuts at day end | D |
| `mine_south` -> `precipice` | ignition tool lights all 8 candlesticks -> permanent stairway | P |
| `precipice` -> `unknown_underground` | Castling Puzzle | P |
| `rotating_gear` -> `underpass` | gear positioned (**requires Mine South visited**) | P |
| `underpass` -> `upper_rotating_gear` | red door, powered by Boiler Room steam | P |
| `underpass` -> `inner_sanctum` | mid-tunnel metal door (no key) | D |
| `inner_sanctum` -> `sigil_chambers` | 1 Sanctum Key per chamber, consumed | P |

**Mine North and Mine South are NOT directly connected.** Getting between them
means going back out through Reservoir South and around via Reservoir North.

**The mine-cart simplification (owner):** visiting `mine_south` unlocks *both*
`reservoir_north -> mine_north` *and* `rotating_gear -> underpass`. Physically
the cart is shifted from the south side to clear the north entrance, which is
what makes the Rotating Gear puzzle solvable for Underpass access; the sim
collapses that to a single "South visited" flag.

## Stateful mechanisms this graph requires

None of these exist today.

| Mechanism | Behaviour | Persists overnight? |
|---|---|---|
| **Cliffside elevator position** | Moves ONLY by being ridden; cannot be called from the far side. Appears at the top once all 4 torches are lit | **No** |
| **Foundation elevator position** | The keycard **summons** the car; it is not a ride toll | **No** |
| **Four torches** | Apple Orchard and Gemstone Cavern light on ENTRY; Schoolhouse and Hovel light on **DRAFT**. All four lit summons the cliffside elevator | **Yes** |
| **Water level** | Set from the Pump Room. `<= 8` opens the Well descent; exactly `6` enables the Safehouse rowboat | **Yes** |
| **Rotating Gear position** | Stays where it was left | **Yes** |
| **Mine cart** | Blocks `reservoir_north -> mine_north` until moved from the south side | (via the South-visited flag) |

The torches **must** persist, and this is load-bearing rather than a detail:
Schoolhouse and Hovel are both outer rooms and only one outer room exists per
day, so the fourth torch could never be lit within a single day.

Both elevators need **position tracked**, because arriving at an area overland
does not bring the car with you. Reaching the Precipice via the Abandoned Mine
strands you there unless the car was already ridden down.

## PR1 stub gates — the deferred mechanisms, and what they cost

PR1 ships graph traversal only. The mechanisms above are not modelled, so the
edges that depend on them are gated by **stubs that pass unconditionally**
(owner decision, 2026-07-27).

The alternative — closing them — was rejected because it strands **8 of the 36
nodes**: Blackbridge Grotto (POWER), Orindian Ruins (behind the Grotto), the
Safehouse and the Well (water level), and Underpass / Inner Sanctum / Sigil
Chambers / Upper Rotating Gear (Rotating Gear position). That would delete
Blackbridge Grotto, the one thing task 4 uniquely supplies. An unreachable node
measures exactly zero, which is a worse and more misleading failure than a
slightly-too-generous world.

> **Anything measured while these stubs are open is an UPPER BOUND** on what a
> real player could reach. Print that caveat next to any number taken before the
> mechanism PRs land.

Each stub carries `stub: true` and a `retire_in` in `areas.json`;
`validate_data.py` enforces that both are present and that `kind: "unmodelled"`
implies `stub: true`, so an unmodelled gate can never silently go *closed* and
kill its edges. `engine/areas.py::stub_gates()` derives this table from the data
rather than repeating it, so the two cannot drift.

| Gate | Retires in | Real condition it stands in for |
|---|---|---|
| `foundation_elevator_down` | PR-foundation-elevator | The Foundation -> Basement: crank revealed AND car at the top |
| `foundation_elevator_up` | PR-foundation-elevator | Basement -> The Foundation: keycard to SUMMON if the car is not already down |
| `boiler_room_steam` | PR-power-system | Underpass -> Upper Rotating Gear: red door powered by Boiler Room steam |
| `lab_steam_and_power` | PR-power-system | Private Drive -> Blackbridge Grotto: Laboratory steam/lever puzzle AND POWER |
| `pump_water_lte8` | PR-pump-room | Grounds -> Well: water level <= 8 |
| `rowboat_water_6` | PR-pump-room | Reservoir South <-> Safehouse: rowboat, water level exactly 6 |
| `cliffside_elevator_down` | PR-torches-elevator | Grounds -> Precipice: 4 torches lit AND car at the top |
| `cliffside_elevator_up` | PR-torches-elevator | Precipice -> Grounds: only if the car was ridden down |

Gates that are **not** stubs are already live: item gates (Power Hammer, Basement
Key, ignition tools, microchips, Sanctum Keys), the `west_gate_unlatched`,
`mine_south_visited`, `garage_door_breaker`, and `basement_sealed_entrance_return`
flags, the `outer_room_drawn` outer_room gate, the `tomb_catacombs` room gate,
and the six `puzzle` gates that pass under the sim's standing "the player solves
every puzzle in a room they enter" doctrine.

## Systems the sim lacks entirely

Surfaced by building this graph:

- **Power.** Required to open Blackbridge Grotto and to run the Laundry Room's
  special functions. A keycard/power notion exists for security doors but does
  not cover this.
- **Pump Room water level.** No action exists to raise or lower it, and two
  edges depend on specific levels.

## Contents worth modelling

- **Apple Orchard**: +20 steps/day, permanent from first unlock.
- **Gemstone Cavern**: 2 gems/day, passive.
- **Sigil chambers**: each is opened by one Sanctum Key, stays open permanently,
  and grants a **permanent +2 allowance** from the Mora Jai box inside — 8
  chambers, so +16 allowance in total. Relates to `open_tasks.md` task 10.
- **Inner Sanctum**: the lever opening the Antechamber's **north** door. Task 9.
- **Abandoned Mine (South)**: an Upgrade Disk **sitting openly on a table**. It
  is obtainable **without** lighting the candlesticks — the candles independently
  open the Precipice stairway. Model the disk as a plain `guaranteed_in` pickup
  and the candles as an ignition target granting a graph edge, not an item.
  Coupling them would make the disk unreachable without an ignition tool. See the
  note in `engine/special_items.py::on_enter`.

## Items this unblocks

All currently inert with `meta.blocked_on` set:

- `microchip` — 3 exist; all three gate the Orindian Ruins door, the Apple
  Orchard sundial, and one Crate Tunnel door.
- `sanctum_key` — one per sigil chamber, consumed.
- `key_of_aries` — from the Unknown (Underground) clock.
- `file_cabinet_key` — Crate Tunnel. Note the Archives disk sits behind it.

## How it works in code

- `engine/state.py` — `GameState.area` is `str | None`: None means "on the 5x9
  grid, position is `pos`", otherwise it is an area node id. It replaced an
  `outer_loc` int that encoded 0/1/2 and doubled as a phase flag.
- `engine/game.py` — `area_route_cost(dest)` runs BFS from each grid anchor and
  returns the cheapest walk-to-anchor plus area hops; `travel_to(dest)` pays it.
  The `off_grid` and `inside_outer_room` properties replace bare integer
  comparisons at ~40 call sites. The three `GameConfig` outer step costs are
  gone: the graph derives all three, so keeping them would be a second source
  of truth for one number.
- `env/actions.py` — one travel action per node, masked to destinations that are
  reachable, affordable, and **modelled** (see below), replacing the two hardcoded
  return actions and the enter-outer action. The node ordering is derived from the
  graph, never hand-listed. `OUTER_DRAFT_ACTION` survives: travelling to
  `west_path` and opening the draft while standing there are deliberately
  separate, which is the same drafting-is-not-moving split the grid already uses.

### `modelled`: which areas are offered as destinations

Every node carries a required boolean `modelled`. Only modelled nodes are offered
as travel actions; the pathfinder still routes *through* the rest. Today 11 are
modelled — `house`, `garage`, `west_path`, and the 8 outer rooms — which is
exactly the set that has contents worth walking to.

This is not tidiness, it is a measured fix. With all 36 exposed, 13 nodes were
reachable on day 1 through open stub gates, none of them holding anything
modelled, and a random policy spent **80% of its steps** wandering them; off-grid,
99.8% of the legal mask was travel. Gating on `modelled` cut that to 30%.

An action slot exists for **every** node, modelled or not, so switching an area on
later is a mask-only change: **no action-space change and therefore no retrain.**
That is the whole reason the flag lives in the data rather than in a Python list
of "useful" areas.
- `env/obs.py` — `player_area` (`Discrete(37)`; 0 = on the grid) says where the
  player is. `player_pos` still holds a grid cell but is only meaningful when
  `player_area == 0`.
- `tools/validate_data.py` — referential checks over `areas.json`, plus the
  edge check that an `outer_room`-gated edge must end at an anchor whose room
  has `pool == "outer"`.

**The west gate is `GameConfig.west_gate_unlatched`**. It controls only the
`grounds <-> west_path` shortcut. It does **not** gate outer-room drafting: on
a fresh save, the Garage + breaker route (`garage -> west_path`) is available
from day 1 without any unlock. The gate unlatches the first time the player
arrives at `west_path` (necessarily via the Garage on a fresh save). That is
recorded on `GameState`, **never written back to the config** — one `GameConfig`
is shared by every episode of a training worker, so mutating it would leak the
unlock into later "fresh save" episodes. `carryover()` ORs state with config and
`DayChain` carries the result, so the 2-step Grounds route stays open for the
rest of the attempt. Same shape as `entrance_vase_broken` / `outer_chip_dug`.

## Corrections already applied

Recorded so they are not re-litigated:

- The ignition candles are in the **Abandoned Mine**, not by the Reservoir, and
  they open a Mine -> Precipice stairway. `open_tasks.md` task 7 previously said
  they connected the Precipice and the Reservoir; that text is deleted.
- **No soft-lock in the Orindian Ruins** — the microchips live in the Grotto.
- The **car trunk re-locks nightly** and needs Car Keys every time; the Vault box
  is the one that stays open permanently.
- The first-ever West Path visit **must** come through the Garage, because the
  west gate only unlatches from the inside.

## Open questions

- Do the **elevator positions** reset to a known place each morning, or start
  wherever they were left? Recorded as not persisting, but not independently
  confirmed.
- **Crate Tunnel**: modelled to its entrance only. Confirm the Tunnel floorplan
  is the sole progression-relevant reward.
- Should `unknown_underground` be modelled at all, or truncated like the Crate
  Tunnel?
- Step costs are a flat 1 per edge. If any long haul (Grounds -> Reservoir, or
  the Underpass run) should cost more, it has not been identified.

## Observatory panels

The Training Observatory (`blueprince-dash`) renders two panels that consume the
area graph.

### Outside-areas panel (Runs tab)

Appears below the 5x9 house grid.  Displays all 36 area nodes as an inline SVG.
Layout is derived from the API response — x from `depth` (BFS hops from
`house`, house at the left), y from `band` (surface near the top, anchor on the
centre line, underground near the bottom).  Nodes that share a depth within a
band are spread evenly.  Any node with `depth: null` is parked in a separate
"unreachable" strip at the right edge rather than stacked at x=0.

**Visual encodings:**

- **Filled circle** — modelled area (engine has contents; the agent can travel
  there).
- **Dashed-ring circle** — unmodelled area (`modelled: false`).  The engine
  never offers travel to these; they appear to make the graph navigable but are
  visually distinguished so a viewer does not read them as reachable destinations.
  A legend entry reads "unmodelled (no engine contents)".
- **Dashed edge** — `stub: true`.  The gate on this edge passes unconditionally
  in the current sim; the real game requires a mechanism not yet modelled.  Any
  visit count measured while stubs are open is an upper bound.  A legend entry
  reads "stub gate (passes unconditionally — upper bound)".

**Two modes, toggled by buttons in the panel header:**

- **Replay mode (default):** driven by the scrubber.  The node matching the
  current frame's `area` field is highlighted gold; nodes visited earlier in
  the episode are shown in their band colour; unvisited nodes are dim.  When
  `area` is null the player is on the 5x9 grid — the `house` node is
  highlighted so the panel is never blank.
- **Aggregate mode:** shades each node by total visit count summed across all
  buckets in `/api/area_stats`.  Opacity encodes relative frequency (0.25 at
  any nonzero visit to the full band colour at the maximum).  Nodes with zero
  visits are drawn at low opacity in a dark fill.  When no area-stats data has
  been recorded yet, a "no off-grid travel recorded yet" note appears in the
  legend instead of 36 identically-shaded nodes.

Band colours: surface = `#2a9d8f` (teal, matching the existing `outer` palette
entry), underground = `#7a50a0` (purple), anchor = `#8a919c` (grey).

### Upgrade statistics panel (Dashboard tab)

Appears below the "Latest checkpoints" card.  Populated from `/api/upgrade_stats`.
All three blocks show an explicit empty state when `upgrades.jsonl` is absent.

**Block 1 — Chosen vs offered per variant.**  One horizontal bar per upgrade
variant.  A dark background fill spans the offered width; a bright accent fill
spans the chosen width within it.  The right label shows `selection_rate` as a
percentage.  Variants offered but never chosen render with 0% and an empty
bright fill — they do not disappear.  Sorted by `offered` descending (the
server pre-sorts; the client does not reorder).

**Block 2 — Disk economy over time.**  Line chart of `mean_disks_held` (blue)
and `mean_slots_upgraded` (gold) against `bucket_start`.  A low grey bar behind
the lines shows relative decision count per bucket.  The x-axis label is taken
from `economy_axis` in the response (`"day"` for multi-day runs, `"decision"`
for single-day runs) so the label is never hardcoded.

**Block 3 — Gate context.**  Three tiles showing raw counts and percentages of
`decisions`: total decisions, decisions where `catacombs_unlocked` was true, and
decisions where every slot's draft count was zero (`slot_draft_count_zero`).
Percentages are guarded against `decisions == 0`.
