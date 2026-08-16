# Room power

Status: **owner-ruled; implemented.** This document owns the steam-power rule,
the room lists it runs on, and every deliberate divergence from the wiki.
`engine/power.py` implements it; `Game.powered_map` / `cell_powered` /
`room_powered` expose it; `tests/test_power.py` pins it.

## The rule

Owner ruling, verbatim:

> The **house** isn't powered. A **room** is powered. A room is powered if it
> shares a doorway with another powered room.

So power is plain connectivity over the door graph, seeded at the power
sources, conducted only by rooms that are on the power network, and transitive
and branching in both directions. It is derived from the grid on every read
rather than latched per room, because placing a single room can light a whole
chain at once — a Laboratory drafted on its own goes from dark to powered the
moment a Boiler Room joins it, with no other act in between.

The wiki states the same rule in almost the same words
([Steam power](https://blueprince.wiki.gg/wiki/Steam_power)): *"Any powerable
or connector room that shares a doorway with a powered room becomes powered
itself... This power may come from a power source itself, or another powered
room."*

### "Shares a doorway" is a door pair

Two cells share a doorway when **both are placed** and **each has a door bit
facing the other** — `placed_doors[a] & d` and `placed_doors[b] & OPPOSITE[d]`,
the same test `Game._connected` and the navigation BFS use. Orthogonal
adjacency is not enough: a Laboratory with no north door and a Boiler Room with
no south door are neighbours on the grid with a solid wall between them, and
power does not cross it. A half-formed pair (a door on one side only) does not
carry power either.

An **empty cell never conducts**. The optimistic distance map treats empty
cells as freely passable, and a power search written against that map instead
of the placed grid would light rooms through open air.

### Door state is ignored

A locked, security or sealed segment still carries power. A doorway that needs
a key is still a doorway with ducts running through it, and coupling power to
`door_state` would make a room's power state change as keys are spent
elsewhere in the house — an invisible, non-local dependency. Nothing in the
wiki addresses the case; this is a deliberate simplification, and
`tests/test_power.py` pins both the locked and the sealed leg.

## The rooms

Membership of the network is `Room.powered` (`flags.powered` in `rooms.json`),
and `tools/validate_data.py` pins the whole set so a room cannot join or leave
it silently. The wiki's three-way split is recorded here for the per-room work
that is still owed; the propagation itself only needs "is it a source" and "is
it on the network".

**Sources** — generate power of their own:

- Boiler Room
- Electric Eel Aquarium (`electric_eel_aquarium__ix4`, the Aquarium's power
  upgrade; the base Aquarium and its Goldfish/Starfish upgrades are not
  sources)

The source set is `POWER_SOURCE_IDS` in `engine/power.py` rather than a
rooms.json field: it is a two-room wiki fact with no sheet column behind it,
and `tools/ingest_sheet.py` — which would have to learn it for the flag to
survive a regeneration — cannot currently run at all (see "The generator is
broken" below). `validate_data.py` checks every id in the set is a real room
that also carries `flags.powered`, so it cannot drift into nonsense.

**Connectors** — conduct power, no effect of their own: Passageway, Archives,
Darkroom, Weight Room, Locker Room, Security.

**Powerable** — act when powered: Laboratory, Garage, Laundry Room, Pump Room,
Furnace.

### The three Red Rooms the sheet never covered

Darkroom, Weight Room and Furnace carry power, and their records had
`powered: false`. All three are Red Rooms: absent from the decompiled sheet and
supplied by `tools/supplemental_rooms.json`, whose author set the flag on
`archives` (also a Red Room) but not on these three. The wiki is explicit on
each — the [Darkroom](https://blueprince.wiki.gg/wiki/Darkroom) *"is fitted
with steam ducts, allowing it to convey steam power from the Boiler Room"*, and
the [Furnace](https://blueprince.wiki.gg/wiki/Furnace) *"has power ducts running
across the ceiling and connecting to its door, allowing it to receive steam
power"* — so this is a gap in the supplemental data, not a divergence.

Corrected in `tools/supplemental_rooms.json` (the source of those three
records) **and** in the generated `rooms.json`, because the generator cannot be
run to propagate the source edit.

### The Guest Bedroom is not a source here

The wiki lists a third, conditional source: a Guest Bedroom upgraded to the
Guess Bedroom, whose hidden effect can mimic the Electric Eel Aquarium. The
Aquarium family is already excluded from that mimic pool for an unrelated
reason recorded on the room's own record (`guess_bedroom__ix70`'s
`meta.blocked_on`: mimicking it would need `Room.is_category` to become true
for one drafted cell only). So no Guest Bedroom in this engine can ever be a
source, and it is deliberately absent from `POWER_SOURCE_IDS`. If that mimic is
ever unblocked, this is the second thing it changes.

## Deliberate divergences

**OWNER RULING: the Boiler Room's daily switch and single-door routing are not
modelled, and that is correct rather than a gap.** *"Under the assumption that
the player can solve all puzzles, assume they can route power as desired."* The
wiki has the Boiler Room switched on each day and supplying one of its three
doors at a time; this sim powers all its doors always. That follows the standing
doctrine that the player solves every puzzle in a room they enter -- the same
rule that makes `puzzle` gates pass -- so a player who can always route power
where they want is indistinguishable from a room that supplies every door.
 from the wiki

- **The Boiler Room powers all of its doors at once.** The wiki says it *"must
  be activated by providing steam from all three tanks"* and then *"supplies
  power to only one of its three doors at a time (defaulting to the centre
  door), which can be dynamically switched via control panel"*. The owner's
  rule has neither the activation step nor the one-door restriction, and the
  owner outranks the wiki. Modelling the switch would need a per-day activation
  act and a chosen-door state, both of which change the action space.
- **Power is not switched on daily.** Same source, same reason.
- Door state is ignored, as above.

## What powering does, today

Exactly one thing: the **POWER conjunct of the Blackbridge Grotto unlock**.

`private_drive -> blackbridge_grotto` requires both `lab_steam_and_power` and
`lab_visited` (docs/areas.md's "Blackbridge Grotto gate"). Both are now real
`kind: "flag"` gates with `permanence: "permanent"`:

- `effects/rooms/laboratory.py`'s `ON_DRAFT_ROOM` hook sets
  `GameState.lab_powered` the first time a placed Laboratory is powered.
  That hook is broadcast to every placed room on every placement, and
  placement is the only thing that can change the power network — power reads
  the grid and the door masks alone, and both are written in `_place_room` and
  nowhere else.
- `shops.py::carryover` ORs that with `GameConfig.lab_powered`, and the named
  `DayChain.lab_powered` attribute carries the result.
- `Game._gate_ctx` puts `"lab_steam_and_power"` in the `GateContext` whenever
  either side is set.

**Latched, not re-derived.** The owner ruled the Grotto unlock is one-time for
the whole save ("You only need to unlock the Blackbridge Grotto once for the
entire save. However, you need to power and enter the Laboratory for that to
happen."), so a later day with no Laboratory on the grid still passes the gate.
`lab_powered` is save-scoped in exactly the way `lab_visited` is — a named
`DayChain` attribute left out of the attempt wrap, not a `_CARRYOVER_KEYS`
entry (docs/scoping-and-carryover.md).

**Known looseness in the conjunction.** The two conjuncts latch independently,
so powering a Laboratory on one day and entering an unpowered one on another
opens the edge even though the player never had both at once. Tightening it
would mean latching the *conjunction*, which reads worse against the gate's own
stated meaning; the two-gates-judged-separately shape is what `areas.md`
already specifies. Worth an owner ruling if it ever matters.

## The Garage's West Path door

The first powerable room whose effect is wired to this system. Owner ruling:
*"The Garage door needs power. It can get this power by having the breaker
turned on in the Utility Closet (assumed on entry) or by connecting it to any
powered room."*

A **disjunction**, not a replacement: the `garage_door_powered` gate on both
`garage <-> west_path` edges passes when the Utility Closet breaker is on
(`Game._breaker_on`) **or** when a placed Garage is a powered room here
(`Game._garage_powered`, i.e. `room_powered` over every Garage floorplan). The
two are different notions — one is "the breaker room has been entered", the
other is door-graph connectivity to a source — and neither implies the other.
[`areas.md`](areas.md)'s "The Garage door" owns the gate and explains why the OR
has to live in `Game._gate_ctx` rather than in `areas.json`.

The Garage carries `flags.powered`, so it is a member of the network like any
other powerable room; nothing about the propagation rule is special-cased for
it. Its `dead_end` floorplan has a single doorway, so the door that carries the
power in is the same one the West Path hangs off.

## What is deliberately not built

The **effects** of the other powerable rooms. A powered Pump Room's Tank 1
transfers, a powered Laundry Room's three exchange services, a powered Furnace
forging a key on entry — none of these are wired to `cell_powered`. Powering is
the mechanic; the payoffs are per-room work, each with its own design questions.

## The generator is broken

`tools/ingest_sheet.py` cannot regenerate `rooms.json`: it raises
`ValueError: resolve_glyphs: 1 unused ambiguous entries for room
'servants_spare_quarters__ix134'` before writing anything. This predates the
power system and is unrelated to it, but it is why the three Red Rooms' flag
had to be written into the generated `rooms.json` by hand alongside the
`supplemental_rooms.json` source edit, and why `POWER_SOURCE_IDS` lives in
Python rather than in a room record.

## Observation and action spaces

Untouched by the power system. `N_ACTIONS` is 493 and the observation is 1090
wide; neither moves when power moves.

Power state is not in the observation, on purpose and consistently with
`lab_visited`, which is not observable either. It is a deterministic function of
`grid_room` and `grid_doors`, which the agent already sees, and what it gates —
travel to Blackbridge Grotto, and the Garage's West Path door — is surfaced
through the action mask, which is where reachability has always been expressed.
Adding a field would be a retrain trigger for information the agent can already
act on.
