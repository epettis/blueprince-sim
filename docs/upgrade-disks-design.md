# Upgrade Disk draw mechanism — design

Status: **implemented** 2026-07-26 — tables in
`src/blueprince_sim/data/upgrade_selection.json`, selection in
`engine/upgrades.py`, deck substitution in `decks.apply_upgrade`, the player-facing
API on `Game` (`can_insert_disk` / `insert_disk` / `choose_upgrade`).
The individual upgrade *effects* are still unwritten — that is the next task.
Authoritative for the draw mechanism;
[`upgrade-value-measurement.md`](upgrade-value-measurement.md) covers whether an
upgrade is worth anything.

Scope of this document: **how inserting a disk picks which room gets upgraded,
and how the chosen upgrade takes effect.** Writing the individual upgrade
*effects* is separate work (owner rated all 57 options; only HIGH and MEDIUM get
effects, LOW stay inert with `meta.blocked_on`).

## Owner decisions driving this design

1. **Full fidelity to the datamined selection tables** — transcribe them into
   data, mirroring the `priority_draws.json` idiom, rather than approximating.
2. **Upgrades apply immediately, same day** — wiki-faithful, via in-place deck
   substitution rather than waiting for the next day's config.
3. **Use the Patch 1.7 tables and document the version skew** — see below.
4. **Ship disks alone, then retrain**, so Cloister of Orinda's pre-Antechamber
   -lock value could be measured as a baseline before the Antechamber lever
   gate shipped. See [`upgrade-value-measurement.md`](upgrade-value-measurement.md)'s
   status note: that baseline was never taken, and the window to take it is
   now closed.

## Version skew — read this first

The repo reproduces the decompiled **v1.3** draft algorithm (`README.md`,
`docs/drafting.md`). The upgrade-selection tables below are explicitly
**post-Patch-1.7** behavior — the wiki states these behaviors "were changed
significantly in Patch 1.7", and no v1.3 upgrade table has been published.

This is an accepted, deliberate skew. Upgrade selection is a separate subsystem
from the draft core, so the v1.3 claim about *drafting* remains true. Every
record in `upgrade_selection.json` carries `meta.source` naming the patch.

## The selection universe: 15 rooms, 16 upgrades

Fifteen rooms are upgradable. Spare Room is upgraded **twice**, which is why
there are 16 upgrades but the saturation case is "an even 1/15 chance to choose
each room".

The two Spare Room stages appear in the tables as the pseudo-slots `Spare 1` and
`Spare 2`:

- `spare_1` — upgrades `spare_room` to Spare Bedroom / Greenroom / Hall.
- `spare_2` — upgrades whichever of those was chosen to one of *its* three
  sub-variants. `rooms.json` already models this as a second-level chain:
  `spare_bedroom__ix131`, `spare_greenroom__ix132` and `spare_hall__ix133` each
  carry `pool: upgrade_variant` and are themselves the `variant_of` base for
  three further records.

So `spare_2`'s three options depend on what `spare_1` chose. It is the only
slot whose option set is not fixed.

The other fourteen: Closet, Storeroom, Courtyard, Boudoir, Nook, Hallway,
Nursery, Bunk Room, Parlor, Cloister, Billiard Room, Mail Room, Guest Bedroom,
Aquarium.

### Always three options, sampled

The terminal always offers **exactly three** upgrades. Rooms with exactly three
variants offer all of them; **Cloister has 8 variants, so three are sampled**
(owner-confirmed from play — he drew neither Orinda nor Draxus on his first
playthrough). This keeps the choose block uniform at 3 slots for every room.

Sampling is **uniform without replacement** over the room's variants; whether the
real game weights them is unknown, so the tables carry `confidence: inferred`.

The offered three are **not** filtered against the already-applied variant. At
saturation the roll re-offers a room so its upgrade can be changed, and for a
three-variant room excluding the current one would leave only two options while
the terminal must always show three. The wiki does not claim exclusion either.
Re-picking the variant a room already has is therefore a legal no-op.

This is load-bearing for the Antechamber-lever validation signal
([`upgrade-value-measurement.md`](upgrade-value-measurement.md)): Cloister of
Orinda is only offered on ~3/8 of Cloister rolls, so any measured value of
Orinda must account for its availability, not just its win rate when chosen.

## Data: `data/upgrade_selection.json`

New file, same shape as `priority_draws.json` — `schema_version`, a `comment`
explaining the mechanisms, and entries carrying `meta.confidence` /
`meta.source`.

Top-level keys:

- `slots` — the 16 selectable slots, each mapping to the room id it upgrades.
  Sixteen slots over fifteen rooms, because `spare_1` and `spare_2` both map to
  `spare_room`. Saturation's "even 1/15" is a roll over *rooms*, not slots.
- `non_veteran.first_upgrade` — the weighted table for the very first upgrade.
- `non_veteran.chains` — the ordered fallback lines.
- `veteran.first_upgrade`, `veteran.day1_shortcut`, `veteran.chains`.

### Non-veteran, first upgrade

A plain weighted roll over seven slots. Nothing else can be a first upgrade —
Cloister, Aquarium, Nursery, Bunk Room, Parlor, Billiard Room, Mail Room and
Guest Bedroom are all unreachable until at least one upgrade exists.

| Slot | Weight |
|---|---|
| Storeroom | 35% |
| Courtyard | 25% |
| Boudoir | 10% |
| Spare Room | 10% |
| Hallway | 10% |
| Closet | 5% |
| Nook | 5% |

### Non-veteran, subsequent upgrades — the chain walk

One line is chosen **uniformly at random from the top-level lines only**, then
walked left to right. Sub-lines (marked `**` in the wiki source) are *not*
eligible for the initial pick; they are reachable only by falling through from
the line above.

Entry grammar — three forms:

- **Plain slot** — if that slot is not yet upgraded, select it and stop.
  If it is already upgraded, continue to the next entry in the line.
- **Check** (*italicised* in the wiki, e.g. *2 Boiler Room drafts*, *Unlocked
  Catacombs*) — if the condition fails, **abandon the entire rest of the line**
  and fall to the next line. This is the key asymmetry: a failed check kills the
  line, an already-upgraded room merely advances within it.
- **Bracketed slot** (`[2] Spare 1`) — sugar for a check immediately followed by
  the slot. `[N] Room` means "has Room been drafted at least N times during this
  attempt". Per the wiki: `[2] Spare 1` is equivalent to
  *2 Spare Room drafts* > Spare 1.

Reaching the end of a line also falls through to the next line, in written
order — and the next line may be a sub-line.

The eleven top-level lines and four sub-lines, in written order:

```
 1  [1] Nursery > Bunk Room > Parlor > Cloister > Billiard Room > Mail Room
      > Boudoir > Nook > Hallway > Closet > Guest Bedroom > Aquarium
      > Spare 1 > Courtyard > Spare 2 > Storeroom
 2  [2] Spare 1 > Boudoir > Hallway > [2] Mail Room
 3  Closet > (2 Boiler Room drafts) > [2] Aquarium > Parlor
 4  Hallway > Storeroom > Nook > Billiard Room
 5  [1] Courtyard > Parlor > Spare 1 > Guest Bedroom > Spare 2 > Nursery
 5a   -- sub -- (2 Boiler Room drafts) > [2] Aquarium > Nursery > Bunk Room
                > Cloister
 5b   -- sub -- [1] Guest Bedroom > Storeroom > Boudoir > Spare 1 > Spare 2
                > Cloister > Nook > Mail Room > Bunk Room > Hallway > Closet
                > Billiard Room > Parlor > Nursery > Aquarium > Courtyard
 6  Storeroom > Guest Bedroom > Spare 1 > Spare 2 > Nook
 7  (Unlocked Catacombs) > [1] Cloister > Parlor > Aquarium > Mail Room
 8  (2 Library drafts) > [1] Nook > [1] Courtyard > Hallway > Closet > Boudoir
      > Aquarium
 9  [5] Billiard Room > [4] Mail Room > Guest Bedroom > Courtyard
10  [2] Parlor > [2] Bunk Room > Closet > Hallway > Guest Bedroom
10a   -- sub -- [4] Mail Room > Bunk Room > Guest Bedroom > Storeroom
11  [1] Boudoir > (2 Library drafts) > [1] Nook > [4] Mail Room > Bunk Room
      > Hallway > Closet > Guest Bedroom > Billiard Room > Cloister > Parlor
      > Nursery > Aquarium > Spare 1 > Courtyard > Storeroom > Spare 2
11a   -- sub -- Storeroom > Hallway > Boudoir > Bunk Room > Nook > Mail Room
                > Closet > Spare 1 > Guest Bedroom > Billiard Room > Cloister
                > Parlor > Nursery > Aquarium > Courtyard > Spare 2
```

So the uniform pick is over lines 1–11 (p = 1/11 each); 5a, 5b, 10a and 11a are
fallthrough-only.

### Veteran mode

- **First upgrade**: uniform over all 15 slots.
- **Day 1, past the first upgrade**: 70% chance to use a shortcut — pick one of
  the 15 slots uniformly; if it is already drafted *or* already upgraded, walk
  the fixed order Spare Room > Bunk Room > Closet > Billiard Room > Parlor >
  Storeroom > Courtyard > Mail Room > Hallway > Boudoir > Guest Bedroom >
  Nursery > Aquarium > Nook > Cloister until one is available. If that
  exhausts, walk the same order again **ignoring the drafted requirement**,
  checking only for already-upgraded.
- **Otherwise** (after day 1, or the 70% failed): uniform over 15 veteran lines,
  same walk semantics. Falling off the last veteran line continues into
  **non-veteran line 1**, including its checks.

The veteran lines carry no sub-lines and no `[N]` brackets, so their walk is
simply "first not-yet-upgraded slot wins, else next line":

```
 1  Storeroom > Guest Bedroom > Spare 1 > Spare 2 > Nook
 2  Spare 1 > Boudoir > Hallway > Spare 2 > Mail Room
 3  Courtyard > Parlor > Spare 1 > Guest Bedroom > Spare 2 > Nursery
 4  Mail Room > Bunk Room > Guest Bedroom > Storeroom
 5  Bunk Room > Guest Bedroom > Storeroom
 6  (always false) > Closet
 7  Hallway > Storeroom > Nook > Billiard Room
 8  Boudoir > Nook > Mail Room > Bunk Room > Hallway > Closet > Guest Bedroom
      > Billiard Room > Cloister > Parlor > Nursery > Aquarium > Spare 1
      > Courtyard > Storeroom > Spare 2
 9  Parlor > Bunk Room > Closet > Hallway > Guest Bedroom
10  Billiard Room > Mail Room > Guest Bedroom > Courtyard
11  Guest Bedroom > Storeroom > Boudoir > Spare 1 > Spare 2 > Cloister > Nook
      > Mail Room > Bunk Room > Hallway > Closet > Billiard Room > Parlor
      > Nursery > Aquarium > Courtyard
12  Nursery > Bunk Room > Parlor > Cloister > Billiard Room > Mail Room
      > Boudoir > Nook > Hallway > Closet > Guest Bedroom > Aquarium > Spare 1
      > Courtyard > Spare 2 > Storeroom
13  Aquarium > Nursery > Bunk Room > Cloister
14  Nook > Courtyard > Hallway > Closet > Boudoir > Aquarium > Hallway
15  Cloister > Parlor > Aquarium > Mail Room
```

Two quirks are faithful to the source, not transcription slips. **Line 6** is
documented on the wiki as bugged — it carries an always-false check, so it can
never select Closet and always falls through to line 7. **Line 14** really does
list Hallway twice; the second occurrence is unreachable whenever the first was.

### Saturation

Once all 16 upgrades are applied, selection becomes a flat 1/15 over slots and
the chosen slot's upgrade is **re-offered for replacement** — the player picks a
different variant for a room already upgraded.

So a room is not retired once upgraded — the tracking of applied upgrades exists
to steer the chain walk, not to permanently exclude a room. Low practical impact
either way: reaching saturation needs all 16 disks.

## New state

### Per-attempt draft counters

The `[N]` and *N Room drafts* checks need cumulative per-attempt counts of how
many times each room has been drafted. Nothing like this exists today.

Model as `dict[str, int]` carried on `DayChain`, incremented on placement,
following the `used_vault_keys` pattern exactly: union/merge in `advance()`,
passed through `next_config()`, **cleared on chain wrap**.

Two subtleties:
- "drafted" means *placed*, not entered — drafting and moving are distinct in
  this engine, and the wiki's wording is about the draft.
- Counts are per attempt (200 days), not per day.

### Applied upgrades

`GameConfig.upgrade_disks` already holds applied variant ids and already drives
deck building. Slot-level "is this room upgraded" is derived from it by walking
`variant_of`. Spare Room's two stages fall out naturally: `spare_1` is applied
when any of the three first-level variants is present, `spare_2` when a
second-level one is.

Carryover follows `used_vault_keys` verbatim: a `DayChain` field, union-merged
in `advance()`, passed to `dataclasses.replace` in `next_config()`, reset on
wrap. This is the union-merge channel described in
[`scoping-and-carryover.md`](scoping-and-carryover.md).

### Catacombs

Line 7's *Unlocked Catacombs* check has no counterpart — there is no `catacombs`
record in `rooms.json` (it is task-4 area content). Model it as **permanently
false**, so line 7 always falls through to line 8, and register it as a known
simplification. Revisit when the area graph lands.

## Applying the upgrade immediately

Decks are built once per day in `build_decks()` from `eligible_pool()`, and
`GameConfig` never mutates mid-day. `eligible_pool` does a clean 1-for-1 swap:
a variant id in `cfg.upgrade_disks` puts the variant in the pool and drops its
base.

To make an upgrade land the same day, substitute the **undealt** cards in the
live decks:

- **51 of 59 variants share their base's rarity and gem cost.** For these the
  substitution is purely in place — walk the deck, rewrite each remaining base
  card as the variant. No RNG is consumed and no card changes position, so
  determinism given a seed (a tested invariant) is preserved exactly.
- **The 8 Cloister variants are the exception**: all move `unusual` -> `standard`,
  and Cloister of Draxus additionally drops `gem_cost` 3 -> 0, which moves it
  from the gem deck to the free one. These need a cross-deck move: drop the base
  card from the unusual/gem deck's undealt slice and insert the variant into the
  standard deck at a uniform random undealt index (see "Resolved calls" 3).
  Note the existing `DeckState.add_copies` is the wrong tool here — it reshuffles
  the whole deck and resets the cursor, which would make cards already dealt
  today dealable again.

Already-dealt cards and rooms already placed on the grid are untouched — the
upgrade affects future draws only. Cards are substituted, not added, so deck
sizes are unchanged except in the Cloister case.

## Actions and observation

- `INSERT_DISK_ACTION` (1 slot) — legal in `NAVIGATE` when standing in a
  terminal room, holding at least one upgrade disk item, and not already
  mid-upgrade. Consumes one disk (deterministic order over the seven disk ids;
  they are mechanically identical).
- `CHOOSE_UPGRADE_BASE` (3 slots) — legal only while an upgrade is pending.

`N_ACTIONS` 275 -> **279**. Observation gains the three offered variant ids (and
plausibly a held-disk count). **This is a retrain point** — which is why the
owner chose to ship disks alone.

Three slots suffice for every room, including Cloister — see "Always three
options, sampled" above.

### Terminal rooms

Security, Laboratory, Office and Shelter carry `flags.disk_reader: true`
(alongside `no_library_draft` / `powered` / `duct`, mirrored into
`tools/ingest_sheet.py` so a re-ingest does not revert it), and
`Game.disk_reader_here()` checks it — via `game.inside_outer_room` /
`drafted_outer_room.disk_reader` for Shelter, which has `pool: outer` and
sits off the 5x9 grid, or via the grid room at the player's cell otherwise.

**Blackbridge Grotto is the fifth terminal.** It has no `rooms.json` record
at all — it exists only as an area-graph node — so it carries the same
`disk_reader` flag on its `areas.json` node instead (`Area.disk_reader`,
mirroring `Room.disk_reader`). `disk_reader_here()`'s off-grid branch reads
it the same way the on-grid/outer-room branches read the room flag.
`Game._terminal_room_id_here()` returns the area node id
(`"blackbridge_grotto"`) as the `experiments.on_terminal_accessed` dedup key
in this case — the function only ever uses the value as an opaque set
member, never a registry lookup, so an area id works exactly like a room id.

## Resolved calls

1. **The 3-of-8 Cloister sample is uniform without replacement.** The wiki is
   silent on whether the eight are equally likely, and no datamine gives
   weights, so uniform is the only defensible reading. Tables carry
   `confidence: inferred` on this point specifically.
2. **The roll ignores house and pool state.** Confirmed against the wiki: "All
   upgradable rooms are rooms that appear in the initial draft pool" describes
   which room *types* can ever be upgraded, not a per-day filter. The only house
   state any non-veteran line consults is the `[N]` per-attempt draft counts.
   A room can therefore be selected for upgrade on a day it is unreachable, or
   while it is Repellent-banned.
3. **Cloister deck-move insertion is a uniform random index into the
   destination deck's undealt slice**, drawn from the dedicated
   `upgrade_deck_insert` substream. The cursor and every already-dealt card are
   left alone, so the upgrade cannot resurrect a card dealt earlier today. Any
   fixed position would bias the draw; the real game's position is unknown.

## Simplifications this design accepts

Each is faithful-where-known and flagged where invented.

- **Catacombs is permanently locked.** There is no `catacombs` record, so line
  7's check never passes and the line always falls through. Revisit if a
  `catacombs` room record is ever added.
- **The veteran day-1 shortcut ignores "already drafted".** The wiki's shortcut
  skips rooms already drafted as well as already upgraded; selection is
  otherwise provably independent of house state, and the drafted test would be
  the only place the roll consults the grid. Modelled as upgraded-only.
- **Chain exhaustion falls back to a uniform pick over selectable slots.** The
  wiki does not say what happens when every line is walked without a hit.
  Wrapping to line 1 instead risks a non-terminating walk.
- **Spare Room at saturation re-offers `spare_2`, never `spare_1`.** Saturation
  rolls a *room*; re-rolling Spare Room's first stage would orphan the second.
- **`spare_2` is unselectable until `spare_1` is applied**, and the chain walk
  treats it exactly like an already-upgraded slot — it advances within the line
  rather than abandoning it.
- **Draft counters key on the root base room id.** `[2] Mail Room` counts every
  Mail Room variant too, so an upgraded room keeps accumulating toward the
  brackets that mention it. Counting only the unupgraded base id would silently
  freeze those checks the moment the room was upgraded.

## The one semantic most likely to be got wrong

A bracketed slot is a **check**, not a filter. `[2] Spare 1` desugars to
*2 Spare Room drafts* > Spare 1, and a failed check abandons the entire rest of
the line. So a failing bracket must **not** merely advance to the next entry —
it drops the walk to the next line. Contrast a plain slot that happens to be
already upgraded, which does merely advance. Both failure modes for a *line*
land in the same place (the next line in written order), which is why the walk
returns a single "no selection" result for both.

## Test plan

Mirroring `tests/test_draft_stats.py`, which treats the datamined distributions
as a correctness invariant rather than a flaky statistic:

- **Chi-square on the non-veteran first-upgrade table** — the 35/25/10/10/10/5/5
  split must be reproduced.
- **Chain-walk units** — already-upgraded advances within a line; a failed check
  abandons the line; end-of-line falls to the next line including sub-lines;
  sub-lines are never picked directly. Assert reachability, not table contents.
- **Determinism** — same seed, same insertion point, same selection.
- **Immediacy** — a disk inserted mid-day changes what can be drafted *that day*
  (this is the behavior that distinguishes the chosen design from the simpler
  next-day one, so it is the regression test that matters most).
- **Carryover and wrap** — upgrades persist across days and clear on wrap.

Per CLAUDE.md: no change-detector tests reading `data/*.json` values back
through a lookup; schema and range checks belong in `tools/validate_data.py`,
which must gain `upgrade_selection.json` validation (every slot resolves to a
real room id, weights sum to 1, every chain entry names a known slot).
