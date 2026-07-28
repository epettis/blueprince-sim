# Outside-area connectivity graph

Status: **owner-reviewed, not implemented.** This is the specification for
`open_tasks.md` task 4. [`areas.dot`](areas.dot) is the same graph in Graphviz
form; the two must be kept in step.

Render the picture with:

```bash
dot -Tpng -Gdpi=150 docs/areas.dot -o /tmp/areas.png    # or -Tsvg
```

Everything beyond the 5x9 grid is modelled today as a single "outer room
doorstep" abstraction — `GameState.outer_loc` (0 = on grid, 1 = doorstep,
2 = inside the outer room) plus three fixed step costs in `GameConfig`. This
graph replaces that.

## Ground rules

- **Every edge costs exactly 1 step** (owner-confirmed).
- **Every edge is directed.** The gate that admits you to an area is usually not
  the gate that lets you out, and one passage is strictly one-way. Reverse trips
  are separate edges with their own conditions.
- **One "travel to area" action per node** (~31 actions), masked to reachable
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
`hovel`.

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

## What changes in code

- `engine/state.py` — `outer_loc` (0/1/2) becomes an area node id. It currently
  doubles as a phase flag for the action masker, so it cannot simply be widened
  in place; the graph needs its own observation key.
- `env/obs.py` — `outer_loc` is packed as element 3 of the 4-wide `progress`
  vector. `player_pos` is `Discrete(45)` and holds a grid cell even when
  off-grid, so "where is the player" needs to stop being a single field.
- `env/actions.py` — `RETURN_EH_ACTION` (194) and `RETURN_GARAGE_ACTION` (195)
  are replaced by per-area travel actions. The off-grid mask branch currently
  admits only 6 action families.
- `engine/game.py` — `_outer_route_cost`, `open_outer_draft`,
  `return_from_outer`, and the off-grid budget checks all assume the two
  hard-coded routes.
- `tools/validate_data.py` — needs referential checks for a new `data/areas.json`
  (node ids in edges, room ids, item ids in gates). While there: it does **not**
  currently check `special_items.json`'s `absent_spawn_rooms`, which already
  names `reservoir`, `safehouse`, `crate_tunnel` and `precipice` — room ids that
  do not exist.

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
