# Upgrade Disk draw mechanism — design

Status: **spec-ready**, not implemented. Owner decisions recorded 2026-07-26.
Authoritative for the draw mechanism; `docs/open_tasks.md` §2 covers the
surrounding task (disk sources, terminal rooms, supply).

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
   -lock value can be measured as the baseline for task 9's validation signal.

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

Sampling is assumed **uniform without replacement** over the room's variants;
whether the real game weights them is unknown and should be flagged as an
assumption in `meta`. Already-applied variants are excluded at saturation, when
the roll re-offers a room so its upgrade can be changed.

This is load-bearing for task 9's validation signal: Cloister of Orinda is only
offered on ~3/8 of Cloister rolls, so the measured baseline value of Orinda must
account for its availability, not just its win rate when chosen.

## Data: `data/upgrade_selection.json`

New file, same shape as `priority_draws.json` — `schema_version`, a `comment`
explaining the mechanisms, and entries carrying `meta.confidence` /
`meta.source`.

Top-level keys:

- `slots` — the 15 selectable slots, each mapping to the room id it upgrades
  (`spare_1` / `spare_2` are the pseudo-slots described above).
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
wrap. This is exactly what decision 3 in `open_tasks.md` already specified.

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
  and Cloister of Draxus additionally drops `gem_cost` 3 -> 0. These need a
  cross-deck move (remove from the unusual deck, insert into the standard one).
  Insertion position is arbitrary and must be made deterministic by an explicit
  documented rule; this is a genuine simplification and should be recorded as
  one.

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

Security, Laboratory, Office and Shelter exist as records (`security`,
`laboratory`, `office`, `shelter`). **Blackbridge Grotto has no record at all**
and stays gated behind task 4.

There is no "terminal" concept in code or data today — the word is otherwise
taken by `Phase.TERMINAL`, Security's control hardware, and trade-graph terminal
nodes, so **pick a different name** (`disk_reader`, say) to avoid collision.
Suggest a room `flags` entry alongside `no_library_draft` / `powered` / `duct`,
mirrored into `tools/ingest_sheet.py` so a re-ingest does not revert it.

Note `shelter` has `pool: outer` — it sits in the outer-room abstraction rather
than on the 5x9 grid, so "standing in it" needs checking against `outer_loc`
rather than a cell. Verify before implementing.

## Open questions

1. **Is the 3-of-8 Cloister sample uniform?** Resolved that the game samples 3
   (owner-confirmed), but not whether the 8 are equally likely. Assumed uniform.
2. **Does the roll consider rooms not in today's pool?** The wiki says
   upgradable rooms are "rooms that appear in the initial draft pool" (room
   *types*), and only the veteran day-1 shortcut checks "already drafted". Read
   literally, the non-veteran chains ignore the house entirely. Worth confirming.
3. **Cloister deck-move insertion position** — needs an explicit deterministic
   rule (see above).

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
