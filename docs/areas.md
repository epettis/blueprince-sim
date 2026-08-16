# Outside-area connectivity graph

Status: **owner-reviewed; implemented.** This is the specification for
the off-grid area graph. [`areas.dot`](areas.dot) is the same graph in Graphviz
form; the two must be kept in step.

The graph ships as `src/blueprince_sim/data/areas.json`, parsed by
`engine/areas.py` into an immutable `AreaGraph` with gate evaluation and BFS
pathfinding at 1 step per edge. It is the engine's only model of where the
player is when off the 5x9 grid: `GameState.area` holds an area node id (or
None on the grid), and route costs are derived by BFS rather than declared.

Delivered in two parts. PR1 shipped the graph as data plus the pure traversal
library, calling nothing. The second PR adopted it in the engine *and* changed
the action and observation spaces together — originally planned as two PRs,
merged once it was clear the retrain they force was already owed for PR #36, so
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
- **One "travel to area" action per node**, masked to reachable
  destinations. The engine pathfinds and charges the cost, mirroring how
  `MOVE_TO_BASE` already works for grid cells. This is the action-space change
  that the per-area travel actions delivered.

### The 1-step rule reproduces the existing constants

This is the main evidence the rule is right — these three values were verified
in play and are *derived* by the graph rather than contradicted by it:

| Path | Graph | `GameConfig`, before removal |
|---|---|---|
| Entrance Hall -> doorstep | House -> Grounds -> West Path = 2 | `outer_path_entrance_cost = 2` |
| Garage -> doorstep | Garage -> West Path = 1 | `outer_path_garage_cost = 1` |
| doorstep -> inside the outer room | West Path -> outer room = 1 | `outer_enter_cost = 1` |

These three fields no longer exist; the graph derives all three, and keeping
them would be a second source of truth for one number (see "How it works in
code").

It only works because **the Outer Room drafting cave IS the West Path's south
section**, not a separate node. An earlier draft split them and was off by one on
both routes.

## Nodes

**On-grid / drafted anchors** — not area nodes; shown only because outside edges
attach to them: `house`, `antechamber`, `garage`, `the_foundation`, `tomb`,
`schoolhouse`, `hovel`, `toolshed`, `root_cellar`, `shelter`, `shrine`,
`trading_post`.
`the_foundation` is only usable as a departure anchor once it has actually
been drafted that attempt (`GameConfig.foundation_cell >= 0`); before that,
routes through it are unavailable the way an unplaced Garage is.
`antechamber` (`kind: anchor`, `modelled: true`) is the rank 9 center grid
cell; it deliberately carries **no** area edges to `house` — reaching it from
the grid is a walk through a lever-opened door, not an area traversal, and an
area edge would let `travel_to()` hop past the seal for roughly zero steps
(`tools/validate_data.py`'s areas.dot/areas.json node-and-edge-set check
enforces this, alongside the SPEC_NODE_COUNT/SPEC_EDGE_COUNT check). Its only
area-graph edge is the return leg from `room_46`, so `modelled: true` only
ever advertises the Antechamber as a travel destination from Room 46 itself
— it does not open any new route from `house`.

**Surface**

| Node | Notes |
|---|---|
| `grounds` | Hub south of the Entrance Hall |
| `west_path` | Also the outer-room doorstep and drafting cave |
| `private_drive` | |
| `blackbridge_grotto` | **5th disk-reader terminal**; the one modelled terminal with no room record |
| `orindian_ruins` | Throne Room floorplan |
| `campsite` | **modelled**; the Conservatory's hidden dig spot (arriving with a held shovel permanently sets `conservatory_floorplan_found`), and the only approach to Apple Orchard |
| `apple_orchard` | **modelled**; +20 steps/day (permanent from first arrival, `GameState.orchard_unlocked`); lights a torch on ENTRY (**not modelled** — see "Stateful mechanisms" below) |
| `gemstone_cavern` | 2 gems/day; lights a torch on ENTRY |
| `crate_tunnel` | **Entrance only.** Igniting the torches grants the Tunnel floorplan; everything deeper is story, not progression |
| `sealed_entrance` | |

**Underground**

| Node | Notes |
|---|---|
| `basement` | **modelled** — the Foundation's elevator lands here |
| `well` | |
| `reservoir_south` / `reservoir_north` | Two halves; joined only through the Mine |
| `safehouse` | Sanctum Key |
| `catacombs` | |
| `mine_south` | **modelled, Upgrade Disk**; the mine cart is moved from here |
| `mine_north` | |
| `rotating_gear` / `upper_rotating_gear` | The game's **"Underground"** is `upper_rotating_gear`: a room one step off a hallway from the Underpass, not reachable from `rotating_gear`. **modelled** — holds the estate's one off-grid safe (see below) |
| `underpass` | Holds a Mora Jai box (`allowance_token_underpass`, +2 allowance, granted on arrival by `special_items.py::on_area_arrival`). **`modelled: false`, so built and unreachable**: no travel action ever targets it (`env/actions.py` masks travel to `modelled` nodes only), and routing *through* it — e.g. `rotating_gear -> underpass -> upper_rotating_gear` — jumps straight to the final destination without an intermediate arrival, so it never fires the hook either (verified: `allowance` is unchanged after such a route). Same shape as the `reservoir_north`/`safehouse` Sanctum Key sources (their `special_items.json` notes say so explicitly; this row is the Underpass's missing equivalent). |
| `inner_sanctum` | **modelled** — lever opening the Antechamber **north** door |
| `sigil_chambers` | 8 chambers, one Sanctum Key each |
| `precipice` | |
| `unknown_underground` | Key of Aries clock |
| `room_46` | **modelled** — the game's actual objective, reached only through `antechamber`'s north door. Its only edge back is to `antechamber` (also `modelled`, see above), so once the room's one-time arrival grants (Crown of the Blueprints, Sanctum Key) are collected, travelling back to the Antechamber is still an offered, purposeful action, and the day continues. |

Both Upgrade Disks that were off-grid are now reachable: The Foundation's is an
ordinary `guaranteed_in` room pickup now that the room is on the grid; the
Abandoned Mine's is a bespoke arrival grant (`special_items.py::on_area_arrival`,
called from `Game.travel_to` on arrival at `mine_south`, since it is a pure area
node with no `rooms.json` record for `guaranteed_in` to key off). See
[`upgrade-disks-design.md`](upgrade-disks-design.md) for the disk supply.

### The Upper Rotating Gear safe pays out on two different clocks

Arriving there grants **both** halves of the estate's one off-grid safe, and they
are scoped differently — folding them together would be wrong in one direction or
the other:

- **+1 gem, every day.** A safe's gem respawns
  ([`rooms.md`](rooms.md)), so this fires once per day, guarded by
  `GameState.upper_rotating_gear_gem_granted` — a per-day flag deliberately kept
  out of `_CARRYOVER_KEYS` so a fresh `GameState` clears it each morning.
- **The Treasure Trove floorplan, once ever.** `treasure_trove_blackprint` is a
  permanent carry-over flag adding the room to the draft pool from the following
  day (`decks.py::eligible_pool`).

The wiki files this safe under The Underpass ("the gate in the upper Rotating
Gear"); the sim puts both grants on `upper_rotating_gear`, the node the player
actually arrives at.

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
| `private_drive` -> `blackbridge_grotto` | Laboratory **powered once ever** + **visited once ever** | P |
| `blackbridge_grotto` -> `orindian_ruins` | all 3 microchips in the pedestal | D |
| `private_drive` <-> `campsite` | none | - |
| `campsite` -> `apple_orchard` | padlock code 1128 | P |
| `campsite` -> `gemstone_cavern` | V.A.C. puzzle (Utility Closet) + lever | P |
| `grounds` -> `sealed_entrance` | Power Hammer breaks through, permanently | P |
| `grounds` -> `well` | Pump Room: **Fountain** level <= 8 (live check, every traversal) | D |
| `grounds` -> `crate_tunnel` | ignition tool lights the torches | D |
| `grounds` -> `precipice` | cliffside elevator: 4 torches lit AND car at the top | D |
| `precipice` -> `grounds` | elevator, **only if the car was ridden down** | D |

### Underground

| From -> To | Gate | |
|---|---|---|
| `the_foundation` -> `basement` | elevator (open stub) **AND** the Basement Key (live) | P |
| `basement` -> `the_foundation` | elevator: **keycard to SUMMON** if the car is not already down | D |
| `sealed_entrance` -> `basement` | Power Hammer breaks through, permanently | P |
| `basement` -> `sealed_entrance` | same permanent break (`sealed_entrance_broken`) | P |
| `basement` -> `reservoir_north` | pallet-jack puzzle | P |
| `well` -> `reservoir_south` | Basement Key (not consumed) **+ Fountain == 0**, both checked (the second live, every traversal) | P |
| `reservoir_south` <-> `mine_south` | none | - |
| `reservoir_north` <-> `reservoir_south` | rowboat; **Reservoir** level has EVER been set to exactly 13, permanent once set (two-way) | P |
| `reservoir_north` -> `mine_north` | mine cart moved (**requires Mine South visited**) | P |
| `reservoir_north` <-> `rotating_gear` | none | - |
| `reservoir_south` <-> `safehouse` | rowboat; **Reservoir** level exactly 6, live (two-way) | D |
| `tomb` -> `catacombs` | seven-angel puzzle; wall permanent, but the Tomb must be drafted that day | P |
| `catacombs` -> `mine_south` | lower Draxus's scythe. **ONE-WAY**, shuts at day end | D |
| `mine_south` <-> `precipice` | stairway lit from **INSIDE** the mine only; permanent | P |
| `precipice` -> `unknown_underground` | Castling Puzzle | P |
| `rotating_gear` -> `underpass` | gear positioned (**requires Mine South visited**) | P |
| `underpass` -> `upper_rotating_gear` | red door, powered by Boiler Room steam | P |
| `underpass` -> `inner_sanctum` | mid-tunnel metal door (no key) | D |
| `inner_sanctum` -> `sigil_chambers` | 1 Sanctum Key per chamber, consumed | P |

**Mine North and Mine South are NOT directly connected.** Getting between them
means going back out through Reservoir South and around via Reservoir North.
There is deliberately **no** `mine_south <-> mine_north` edge, in either
direction: a mine cart permanently blocks that passage (owner ruling,
2026-08-06, from play). This is recorded here so the missing edge is never
mistaken for an omission and "fixed" — there is nothing to add.

**The mine-cart simplification (owner):** visiting `mine_south` unlocks *both*
`reservoir_north -> mine_north` *and* `rotating_gear -> underpass`. Physically
the cart is shifted from the south side to clear the north entrance, which is
what makes the Rotating Gear puzzle solvable for Underpass access; the sim
collapses that to a single "South visited" flag.

**Three Basement doors, three independent gates.** The wiki treats
`Basement_door` as a door *type* with three instances — the Grounds side (the
drained Fountain's floor), the Foundation's elevator, and the Crate Tunnel —
each unlocking permanently and independently the first time a Basement Key is
used on it; any other key, and the Lock Pick Kit, do not fit. The graph
therefore carries one gate per instance rather than one shared gate: the
Well's is `basement_key_well` (on `well -> reservoir_south`), the Foundation's
is `basement_key_foundation` (on `the_foundation -> basement`), and the Crate
Tunnel's is **not modelled at all** — `crate_tunnel` is truncated to its
entrance, and everything past it is "story, not progression" (see the Nodes
table above). All three model the simplification recorded below.

**Modelling simplification, both live gates.** The real rule is "this door has
been unlocked, permanently, by a Basement Key at some point"; the sim instead
checks "a Basement Key is currently held". The two coincide because
`basement_key` is `persistence: "permanent"` and is re-granted from the
Antechamber pillar every day the player visits it, so once earned it is always
held — there is no in-game scenario where the key was used and then given up.

**The Well's traversal condition has two independent parts.** Per the wiki,
`well -> reservoir_south` needs the Basement Key unlock (modelled, permanent)
**and** the Fountain drained to level 0, checked on *every* traversal, not
just the first (the Well page: *"this passage is only traversible while the
fountain water level is 0"*). The gate is `basement_key_well` (an item gate)
**plus** `fountain_water_0` (a live flag gate, re-derived from
`Game.water_level("fountain")` on every `_gate_ctx()` call rather than
latched) — the two are independent conditions, and both must hold at the
moment of traversal.

## Stateful mechanisms this graph requires

Of these, only the Pump Room's water levels are modelled directly. The mine cart
and the Rotating Gear position are both collapsed into the single
`mine_south_visited` flag rather than tracked as positions. The rest do not
exist today.

| Mechanism | Behaviour | Persists overnight? |
|---|---|---|
| **Cliffside elevator position** | Moves ONLY by being ridden; cannot be called from the far side. Appears at the top once all 4 torches are lit | **No** |
| **Foundation elevator position** | The keycard **summons** the car; it is not a ride toll | **No** |
| **Four torches** | Apple Orchard and Gemstone Cavern light on ENTRY; Schoolhouse and Hovel light on **DRAFT**. All four lit summons the cliffside elevator | **Yes** |
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

The alternative — closing them — was rejected because it would have stranded
Blackbridge Grotto (POWER) and Orindian Ruins (behind the Grotto), deleting the
one modelled terminal with no room record. An unreachable node measures exactly
zero, which is a worse and more misleading failure than a slightly-too-generous
world. **The four elevator stubs are all that argument now covers**, and it no
longer applies to any of them: measured, closing either elevator pair strands
nothing, because the Underpass chain is held open by the real
`mine_south_visited` and `boiler_room_steam` flags. They are kept for their
step-cost and car-position fidelity, not for reachability. The Grotto's own
gates are both real (see "Blackbridge Grotto gate" below), so the Grotto and
Orindian Ruins are no longer reachable on a stub at all.

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
| `cliffside_elevator_down` | PR-torches-elevator | Grounds -> Precipice: 4 torches lit AND car at the top |
| `cliffside_elevator_up` | PR-torches-elevator | Precipice -> Grounds: only if the car was ridden down |

**`boiler_room_steam` is not a stub.** Owner ruling: the player unlocks
Underpass -> Upper Rotating Gear permanently the first time they enter the
Boiler Room, no power system needed. It is `kind: "flag"`, `stub: false`, set from
`state.boiler_room_steam` (Boiler Room entry) OR the carried `cfg.boiler_room_steam`,
the same shape as `west_gate_unlatched`.

Every gate not listed in the stub table above is already live — item, flag, room,
`outer_room`, and the `puzzle` gates that pass under the sim's standing "the
player solves every puzzle in a room they enter" doctrine.
`engine/areas.py::stub_gates()` derives the stub list from the data, so the
complement is whatever `areas.json` says it is.

### Blackbridge Grotto gate

The owner's rule has two conjuncts: the Laboratory must be **powered AND
visited**. The edge carries two separate gates rather than one collapsed stub,
so each conjunct is judged on its own. Both are real:

- `lab_steam_and_power` — `kind: "flag"`, `stub: false`, `permanence:
  "permanent"`. A Laboratory has been powered at least once, on this day or any
  prior day. [`power.md`](power.md) owns the mechanic: `engine/power.py`
  propagates power over the door graph from the Boiler Room and the Electric
  Eel Aquarium; `effects/rooms/laboratory.py`'s `ON_DRAFT_ROOM` hook records
  the first moment a placed Laboratory is powered on `state.lab_powered`;
  `shops.py::carryover` ORs that with `cfg.lab_powered`; and the named
  `DayChain.lab_powered` attribute carries the result. Same save-scoped shape
  as `lab_visited` below, and for the same reason.

  Note the engine's own `keycard_power_on`/`offline_unlocked` are unrelated:
  they gate Security's card readers specifically and do not generalize.
- `lab_visited` — `kind: "flag"`, `stub: false`, `permanence: "permanent"`.
  The Laboratory has been entered at least once, on this day or any prior day.
  `effects/rooms/laboratory.py`'s `ON_ENTER` hook sets `state.lab_visited`;
  `shops.py::carryover` ORs that with `cfg.lab_visited`, and the named
  `DayChain.lab_visited` attribute carries the result into the next day's
  `GameConfig`; `Game._gate_ctx` puts the `"lab_visited"` flag in the
  `GateContext` whenever either side is set.

  **Save-scoped, not attempt-scoped.** Owner ruling: *"You only need to unlock
  the Blackbridge Grotto once for the entire save. However, you need to power
  and enter the Laboratory for that to happen."* `lab_visited` is therefore
  left out of the `DayChain` wrap block and survives into the next attempt —
  unlike `boiler_room_steam`, whose otherwise-identical shape is a
  `_CARRYOVER_KEYS` bool and so resets with each attempt. It and `lab_powered`
  are the only two bools among the save-scoped carve-outs
  (docs/scoping-and-carryover.md).

  **Why a flag gate and not `kind: "room"` with `permanence: "permanent"`.**
  `permanence` is descriptive metadata; the behaviour lives in
  `areas.py::gate_open`, whose `"room"` arm tests `room_id in
  ctx.rooms_entered` and nothing else. `rooms_entered` is rebuilt from
  `state.entered` every day, so a `kind: "room"` gate is day-scoped by
  construction — marking one `permanent` would be a label the code does not
  honour, and teaching the `"room"` arm to latch would wrongly make
  `tomb_catacombs`, which really is daily, permanent too. A one-time unlock is
  what the `"flag"` arm is for.

Both must hold (edge `requires` is AND), and neither passes on its own, so a
fresh save is closed on both counts. **No number taken through this edge is an
upper bound any more** — it is the reachability a player really has.

**Consequence: Orindian Ruins is gated behind the same requirement.**
`blackbridge_grotto -> orindian_ruins` is reachable only through Blackbridge
Grotto, so it needs the Laboratory powered and visited too — including the
Throne Room's blueprint pickup, which `orindian_ruins` grants
(`GameState.throne_room_blueprint`). This reads as intended: the owner's
report was specifically about the Grotto being open on a fresh save, and nothing
in the wiki or the owner's play notes suggests Orindian Ruins should be reachable
independently of it — the Grotto is its only recorded approach.

## The Pump Room's water levels

**Built.** Six independent per-source integer levels
(`data/pump_room.json`: Fountain 0-12, Reservoir 2-14, Aquarium 0-6, Kitchen
0-3, Greenhouse 0-5, Pool 0-9), each permanent for the rest of the attempt
once changed. The real Pump Room is a water-pouring puzzle — two tanks and
four pumps move water one stroke at a time — but the sim's standing
assumed-solved doctrine (every room puzzle is taken as solved) licenses a
macro action instead: `Game.set_pump_source`/`Game.set_pump_level`, a
factored two-step menu (`env/actions.py`'s `PUMP_SOURCE_BASE`/
`PUMP_LEVEL_BASE`, `Phase.PUMP_LEVEL_PENDING`) that sets a source directly to
any level the wiki says the real panel can reach — *"it is possible to set
any water source to any valid water level except for the Reservoir, which
cannot be drained below water level 2"* — so it costs only the interaction
count, never a reachable state. The tanks, the four pumps, and the
disconnected Reserve Tank (1/6) are not modelled at all; see
`data/rooms.json`'s `pump_room.meta.simplification`. Levels are carried
across days through a dedicated non-bool `DayChain` channel
(`GameConfig.water_levels`/`DayChain.water_levels`), **not**
`_CARRYOVER_KEYS`, which stays bool-only.

Four gates read the six levels, three of them **live checks re-derived every
traversal** (not latched — the level can move both ways within a day as the
panel is operated) and one **permanent once satisfied**:

| Gate | Edge | Rule | Live or latched |
|---|---|---|---|
| `pump_water_lte8` | `grounds -> well` | Fountain <= 8 | Live |
| `rowboat_water_6` | `reservoir_south <-> safehouse` | Reservoir == 6 | Live |
| `fountain_water_0` | `well -> reservoir_south`, ADDITIONAL to `basement_key_well` | Fountain == 0 | Live |
| `reservoir_water_13` | `reservoir_north <-> reservoir_south` | Reservoir has EVER been 13 | **Latched permanent** (`GameState.reservoir_13_reached`, carried via `_CARRYOVER_KEYS`) |

All four are `kind: "flag"`, `stub: false` — ordinary live gates, the same
shape as `west_gate_unlatched`/`boiler_room_steam` — computed in
`Game._gate_ctx()` from `Game.water_level(source_id)` rather than stored
directly on `GateContext`.

**The sequencing trap this build had to land against.** Before this PR,
`pump_water_lte8`/`rowboat_water_6` were `stub: true` (passed
unconditionally) and the Fountain's real default (12) sits above the `<= 8`
threshold — so shipping the water-LEVEL state without the action that moves
it would have *tightened* those two gates and made the Well unreachable by
default, a strictly worse world than the stub. `reservoir_water_13` was the
opposite case: `kind: "unmodelled"`, `default_closed: true` (never passed) —
a deliberate exception to "deferred gates default open", because an OPEN
crossing there is a loophole around `basement_key_well`. Measured, empty
inventory, only `sealed_entrance_broken` set (the free
`house -> grounds -> sealed_entrance -> basement -> reservoir_north` route):
**before** this build, `reservoir_south`/`mine_south`/`safehouse` are all
unreachable (the Fountain sits at 12, not <=8; the Reservoir sits at 14, not
6 or ever-13). **After**, they stay unreachable in that SAME default state —
but become reachable at the identical hop counts the old stub-open data once
measured (`reservoir_south` 5, `mine_south` 6, `safehouse` 6) the moment the
player actually walks to the Pump Room and sets the Reservoir to 13 then 6.
The loophole is real, but now costs two deliberate player decisions instead
of being a free default — see `tests/test_pump_room.py`'s
`test_reservoir_loophole_reachability_before_and_after_choosing_the_levels`,
which pins both sides of this measurement as a test rather than a one-off
script.

**Sealed Entrance permanence (owner decision).** The wiki distinguishes which
barrier breaks: *"If just the Basement wall is destroyed, it will respawn on the
next day, whereas if just the planks are destroyed, neither side will
respawn"* (`Sealed_Entrance` wiki page). The owner, who plays the game, says
there is no such distinction — breaking either barrier permanently opens the
whole route. The sim models the owner's version: one `sealed_entrance_broken`
flag gates all three of `grounds -> sealed_entrance`, `sealed_entrance ->
basement`, and `basement -> sealed_entrance` (the reverse `sealed_entrance ->
grounds` trip was always ungated). The flag is set permanently the first time
the player arrives at `sealed_entrance`, and is also satisfied on the spot by
currently holding a Power Hammer. The wiki's
plank-versus-wall conditional is deliberately not modelled; this document owns
that ruling.

## Systems the sim lacks entirely

Surfaced by building this graph:

- **Power.** Required to open Blackbridge Grotto and to run the Laundry Room's
  special functions. A keycard/power notion exists for security doors but does
  not cover this.

## Contents worth modelling

- **Apple Orchard**: +20 steps/day, permanent from first unlock. **Modelled,
  2026-08-08**: arrival sets `GameState.orchard_unlocked` (never written back
  to `GameConfig` — same carry-over shape as `west_gate_unlatched`), surfaced
  by `shops.carryover()` and carried by `DayChain`, so `cfg.orchard_unlocked`
  is `True` at the next day's `reset()`, which is where `Game.reset` actually
  adds the +20 (`st.steps = cfg.starting_steps + (20 if cfg.orchard_unlocked
  else 0)`). A same-day visit does not retroactively top up the day already in
  progress. The node's own name promises a torch lights **on ENTRY**; that
  requirement is explicitly **not modelled** (out of scope for this change) —
  see "Stateful mechanisms this graph requires" above, which already tracks it
  as one of the four torches nothing implements yet.
- **Gemstone Cavern**: 2 gems/day, passive.
- **Sigil chambers**: each is opened by one Sanctum Key, stays open permanently,
  and grants a **permanent +2 allowance** from the Mora Jai box inside — 8
  chambers, so +16 allowance in total. A further **+2 allowance** sits in the
  Underpass's own Mora Jai box (`allowance_token_underpass`, owner ruling that
  every Mora Jai box holds one) — not counted in the +16 above, and not
  presently collectible: `underpass` is `modelled: false`, so nothing ever
  travels there and the grant is built but unreachable (see the `underpass`
  row in the Underground table above).
- **Inner Sanctum**: the lever opening the Antechamber's **north** door. See
  [`antechamber-lever-design.md`](antechamber-lever-design.md)'s B2 section.
- **Abandoned Mine (South)**: an Upgrade Disk **sitting openly on a table**. It
  is obtainable **without** lighting the candlesticks — the candles independently
  open the Precipice stairway. Modeled as a plain area-arrival pickup
  (`on_area_arrival`) with the candles as an ignition target (`mine_south`,
  `"area": true` in `special_items.json`) gating the `mine_south <-> precipice`
  edges via the `candlestick_stairway_lit` flag, not an item gate. Coupling the
  disk to the candles would make it unreachable without an ignition tool. See the
  note in `engine/special_items.py::on_enter`.

## Items this unblocks

The items whose whole point is an area gate. All are settled — implemented, or
explicitly decided against; the list stays because it records what each one is
*for*.

- `microchip` — 3 exist; all three gate the Orindian Ruins door, the Apple
  Orchard sundial, and one Crate Tunnel door. See the gate design below.
- `sanctum_key` — one per sigil chamber, consumed. Modelled as eight
  per-source ids, so each respawns independently.
- `basement_key` — a deliberate **KEEP**: an item that gates traversal is
  never puzzle-only, and this is the clearest example of it — holding it is
  the literal difference between `reservoir_south` and the far side of the
  Basement being reachable or not, via `basement_key_well` and
  `basement_key_foundation` (both directions of `the_foundation <-> basement`).
- `key_of_aries` — from the Unknown (Underground) clock. The one **decided
  against** rather than pending: `meta.wont_implement`, because its payoff is
  already granted.
- `file_cabinet_key` — modelled as exactly one key, buried in the Patio's
  dig spot, gating the Archives Upgrade Disk. The wiki's other two keys
  (Laundry Room, Crate Tunnel) are not modelled.

### The three-microchip gate, and two designs rejected for it

`blackbridge_grotto -> orindian_ruins` needs three microchips, but the third
never enters the inventory: it sits in the Grotto pedestal. `Gate.counts_flag`
resolves this — `three_microchips` keeps `count: 3` and gains
`counts_flag: "grotto_chip_in_place"`, emitted by `_gate_ctx` while
`GameState.grotto_chip_taken` is false, so the gate counts an in-place copy the
player does not carry.

`grotto_chip_taken` is **day-scoped with no `_CARRYOVER_KEYS` entry**, which
inverts the obvious reading of "match `entrance_vase_broken` / `outer_chip_dug`".
Those two are carry-over keys because they record a permanent *discovery*, with
the day-start re-grant layering respawn on top. The Grotto chip has no
discovery — it is in the pedestal from day 1 with no prerequisite — so respawn
falls out of the field defaulting `False` at every `reset()`. Matching their
semantics meant **not** copying their plumbing.

Two alternatives were rejected, recorded so they are not re-proposed:

- **`count: 2` plus a flag gate on the edge's `requires` list.** `requires` is
  AND, so "took the chip, still holding three" would be shut.
- **Injecting a synthetic microchip into `held_items`.** That makes
  `held_items` lie to every other item gate.

Note the chip economy does not close: the sundial at `apple_orchard` needs
three *held* microchips and the engine's ceiling is two (Entrance Hall vase,
West Path dig). It is built correct-and-unreachable deliberately — inventing a
third source would be making up a game rule, and no ruling exists for one.

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

### `OUTER_DRAFT_ACTION` is legal on the grid AND off it

Its mask entry gates on `Game.outer_draft_available()` alone, with no position
guard of its own, because the action is a walk-and-draft macro:
`Game.open_outer_draft` walks from wherever the player stands. That makes the
doorstep the action's *cheapest* starting point — the walk is a 0-step no-op at
`west_path` — rather than an excluded one. Being refused the draft while
standing on the doorstep is the shape of bug this rule exists to prevent.

The mask is not the only surface. `Game._outer_action_in_budget`, the off-grid
half of the day-end purposefulness test, counts the outer draft too, exactly as
its on-grid twin `_action_in_budget` does; without it, arriving at the doorstep
with a step or two left ends the day on top of a free room. **Engine and mask
must agree in both directions** — a mask bit the engine rejects trips
`open_outer_draft`'s assert, and an engine "yes" the mask hides is an action the
day-end budget keeps counting but the player can never take. The
random-masked-play sweep in `tests/test_game.py` pins that agreement.

### `modelled`: which areas are offered as destinations

Every node carries a required boolean `modelled`. Only modelled nodes are offered
as travel actions; the pathfinder still routes *through* the rest. **`areas.json`
is the list** — do not restate it here, it has been wrong twice. A node graduates
when it holds something worth walking to: the Sanctum route's disks and keys, the
Orchard's step bonus, the Grotto's disk terminal.

This is not tidiness, it is a measured fix. With every node exposed, 13 nodes were
reachable on day 1 through open stub gates, none of them holding anything
modelled, and a random policy spent **80% of its steps** wandering them; off-grid,
99.8% of the legal mask was travel. Gating on `modelled` cut that to 30%.

**The Sanctum route's four nodes move that number, and it is worth watching.**
Measured over 300 seeds of uniform-random masked play under the **pre-#364**
`all_unlocks_config()`, whose underground carry flags were still unset:
off-grid step share rose from **29.93%** (the pre-Sanctum 12-node `modelled`
set) to **41.88%** with the four new nodes added, and the travel-action share of
all actions taken rose from 43.90% to 54.03%. The driver was `mine_south`: it sat
behind the open `cliffside_elevator_down` stub (`grounds -> precipice -> mine_south`,
free), so it was offered from day 1 in 100% of seeds, and a random policy
routinely wandered into it and the area graph beyond. Nowhere near the earlier
80% problem, but a real, measured cost of advertising a destination that a stub
gate makes look cheaper than it is — see the PR1 stub-gate caveat below.

These figures were measured against the pre-fix graph, where the free
`precipice -> mine_south` leg was the item-gate bug described in "Corrections
already applied". `mine_south` is unreachable on a fresh day 1 now that both
directions require `candlestick_stairway_lit`, so the off-grid share is lower
than 41.88% by an unmeasured amount. The numbers are kept because they are
what justified the `modelled` flag, and that decision still stands.

**The off-grid step share is a standing debt, not a settled number.** The tax
does not matter while too few victory paths exist for training to be worthwhile,
and optimising a training cost before the game is winnable is optimising the
wrong thing. **Re-measure it, and revisit which nodes stay `modelled`, before
any training run is started.** Until then the usual discipline — a node goes
`modelled: true` only if it holds something worth walking to — is suspended, not
repealed.

**Where it stands on the shipped training baseline.** Measured over 300 seeds
of uniform-random masked play under `all_unlocks_config()` as it ships (day-20,
every unlock and every carry flag on, one flat action chosen uniformly from the
legal mask each step, single-day episodes): off-grid step share (steps paid by
an action taken while already off-grid, over all steps paid by any action) is
**85.67%** (17,649 of 20,601 steps) and the travel-action share of all actions
taken is **82.61%** (4,475 of 5,417). Both are stable in n — at seeds 0–3999
they read 86.11% and 81.96%. This is a **single absolute reading, not an A/B**:
it says where the tax sits today, not what any one node costs. The
underground carry flags (`reservoir_13_reached`, `sealed_entrance_broken`,
`boiler_room_steam`, `mine_south_visited`) are all on in this preset, so the
whole underground is open to the walker from step 1 and is part of what is
being counted.

**Both per-node A/B pairs in this section — the Sanctum route's and the Apple
Orchard/Campsite one — are keyed to a superseded fixture.** Each measured a
data flip against the config as it then stood, so their *deltas* are not
additive with, or comparable to, the absolute reading above; and neither arm of
either pair can be reproduced without reverting `areas.json`. **Each pair needs
re-measuring against the shipped preset before it is used to argue about any
single node's cost.**

**Apple Orchard/Campsite moved the number sharply, 2026-08-08.** Measured
with the same method (300 seeds, uniform-random masked play, the **pre-#364**
`all_unlocks_config()`, one flat action chosen uniformly from the legal mask
each step, single-day episodes) directly before and after flipping only
`campsite`/`apple_orchard` to `modelled: true` (all other data unchanged from
whatever the tree held at measurement time — this is a same-tree A/B, not a
comparison against the 29.93/41.88 figures above, which predate the candlestick
fix): off-grid step share rose from **35.67%** to **69.28%**, and the
travel-action share of all actions taken rose from **42.62%** to **64.10%** — a
far sharper move than the Sanctum route's ~12-point rise. The driver is
structural rather
than a stub-gate artefact this time: from `campsite`, the only two legal travel
destinations are `apple_orchard` and `house`; from `apple_orchard`, the only two
are `campsite` and `house`. A uniform-random walker that lands on either node
has even odds of taking the 1-step hop to the other rather than heading back
toward `house`, so the pair forms a cheap, freely-repeatable oscillation that a
random policy falls into and stays in for many steps once it arrives. Reported
here in full per the 2026-08-04 measurement requirement rather than only citing
a summary number, since the owner may weigh this differently for a permanent
step bonus than for the Sanctum route's disks/keys — but it should not be
discovered later in a training run.

An action slot exists for **every** node, modelled or not, so switching an area on
later is a mask-only change: **no action-space change and therefore no retrain.**
That is the whole reason the flag lives in the data rather than in a Python list
of "useful" areas.
- `env/obs.py` — `player_area` (`Discrete(n_area_nodes + 1)`; 0 = on the grid) says where the
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
  they open a Mine -> Precipice stairway, not a direct Precipice-Reservoir
  connection.
- **No soft-lock in the Orindian Ruins** — the microchips live in the Grotto.
- The **car trunk re-locks nightly** and needs Car Keys every time; the Vault box
  is the one that stays open permanently.
- The first-ever West Path visit **must** come through the Garage, because the
  west gate only unlatches from the inside.
- The `precipice -> mine_south` edge was briefly ungated (`requires: []`) while
  the other direction carried an item gate (`candlestick_stairway`, torch/burning
  glass held). That made the Precipice a free front door into the mine — holding
  a torch opened the stairway without ever lighting it. Owner correction
  (2026-08-05): the Abandoned Mine is reached from the **house side**
  (Catacombs/Tomb, drained Fountain + Basement Key, or the lowered Reservoir
  crossing), and the stairway is something the player **creates from inside the
  mine**, not an entrance. Both directions now share one `candlestick_stairway_lit`
  flag gate, set only once the candles are actually lit standing in `mine_south`.

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

Appears below the 5x9 house grid.  Displays all area nodes as an inline SVG.
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
  legend instead of identically-shaded nodes.

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
