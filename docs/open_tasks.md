# Open tasks

Features the project owner identified while reviewing the special-items PR stack
(2026-07-26). These are NOT in `docs/plan.md`'s delivered set — each needs its own
design pass. Ordered roughly by how self-contained they are.

## 1. Resource spreading through the house

Several rooms scatter resources into OTHER rooms when drafted, rather than granting
them on entry. None of this is modeled today (the Tomb's per-dead-end gold is the
one exception — `coins_per_deadend` in `engine/effects/tier1.py`).

Known spreaders (owner-reported; **two rows corrected against the wiki 2026-08-06**,
marked below):

| Room | Trigger | Spreads | Target |
|---|---|---|---|
| Patio | on draft | gems | Green Rooms, including itself |
| Secret Garden | on draft | apples and oranges (food) | throughout the house |
| Locker Room | on draft | basic keys | the estate minus 17 named rooms; can seed itself |
| Conference Room | passive, while placed | — | absorbs others' spreads, **altering them** |
| Office | **player action, once/day** | money | throughout the house |
| Tomb | on other rooms' drafts | 5 gold per Dead End | into the Tomb itself (ALREADY MODELED) |

**Correction 1 — the Office is not an on-draft effect.** It is a player-triggered,
once-per-day terminal action ("Spread Gold in Estate"), gated behind walking to the
Office and operating its terminal — the same terminal concept as the shipped
`disk_reader` flag. That makes it an **action-space change**, so per this file's own
standing rule it belongs bundled with a retrain, not with the on-draft spreaders. Do
not conflate it with the Office *safe* (+1 gem), which is task 3 and already shipped.

**Correction 2 — the Conference Room is not a pure redirect.** The wiki: *"Spread
effects do not necessarily spread the same number of items to the Conference Room as
they would spread if the Conference Room were not present."* Patio's gems change
colour; Secret Garden's CR case is a **completely different fixed formula** (always 4
apples + 3 oranges, regardless of house size or soil quality) rather than the same
roll redirected. So each spreader needs its own Conference-Room branch — a single
generic "change the destination cell" function is the wrong shape.

**A spread is a one-shot event, not a standing rule.** *"Spreading only applies to
rooms currently on the estate. Rooms drafted after the spread is done cannot benefit
from it unless the spread is performed a second time later."* It is evaluated once, at
the spreader's own draft moment, over the cells occupied at that instant. This applies
symmetrically to a Conference Room placed afterward: it absorbs nothing retroactively.

Design notes: this writes resources into *other* cells' pending contents, so it needs
a per-cell "resources waiting here" store. Note the drain cannot hang off first entry
as originally sketched — `_enter()` returns early once `entered[cell]` is true, and
the common case is a spreader drafted *after* its targets were already walked through,
so the drain must sit above that gate and fire on every arrival. The Locker Room case
matters for balance: its keys are what make the room's 17 locked lockers openable (see
PR #26).

## 2. Upgrade Disk functionality

Disks are collected today (Vault box 304, Commissary reserve stock, Trading Post
tier-5 trades, the Garage car trunk) but cannot be *used*. `GameConfig.upgrade_disks`
already swaps a base room for its variant in the deck build, so the missing piece is
the in-run action that awards one.

Wiki research (https://blueprince.wiki.gg/wiki/Upgrade_Disk):
- **Terminals**: standing at any terminal with a disk lets you insert it. Owner adds
  Security, Laboratory, Office, Shelter, Blackbridge Grotto as the terminal rooms.
- **Selection**: the terminal settles on one room to upgrade, then offers **three**
  upgrade options for it; only the new icons are inspectable before choosing. The
  disk is consumed, the upgrade applies **immediately** (a room still in today's
  draft pool can be drafted in its upgraded form the same day), and it is
  **permanent** across days. Which room gets picked is a weighted, chained
  algorithm — [`upgrade-disks-design.md`](upgrade-disks-design.md) is authoritative.
- **Supply**: exactly **16** disks exist, one per upgrade slot.
  The wiki enumerates **15 fixed one-time locations** (Office desk, Morning Room,
  Her Ladyship's Chamber, Commissary reserve 15g, Garage car trunk, Great Hall
  prize door, Vault box 304, Trading Post dynamite chamber, Freezer ice wall, Tomb
  candles, The Foundation, Abandoned Mine, Lost & Found pool, Mechanarium, Archives
  cabinet) plus **one repeatable Trading Post trade** — "Unlike the other Upgrade
  Disks, this disk can appear repeatedly" — which is the 16th. The sim now models
  **16 of the 16**: seven bespoke sources (`upgrade_disk_vault_304`, `_commissary`,
  `_garage`, `_trading_post`, `_lost_and_found`, `_tomb`, `_mine_south`), the
  repeatable `upgrade_disk_trade`, and eight fixed room pickups added via
  `guaranteed_in` (`_office`, `_morning_room`, `_her_ladyships_chamber`,
  `_great_hall`, `_freezer`, `_archives`, `_mechanarium`, `_the_foundation`).
  **The Foundation** and the **Abandoned Mine** were the last two, off-grid until
  the Sanctum-route PR made `the_foundation`/`basement`/`mine_south`/`inner_sanctum`
  reachable (see [`areas.md`](areas.md) and [`foundation-design.md`](foundation-design.md)).
  The Foundation's disk is an ordinary `guaranteed_in` pickup now that the room is
  on the grid; the Abandoned Mine's is a bespoke arrival grant
  (`special_items.py::on_area_arrival`, called from `Game.travel_to` on arrival at
  `mine_south`, since it is a pure area node with no `rooms.json` record).

  **Disks respawn; only SPENDING is permanent** (owner, 2026-07-27): "The disks
  reappear in their location every day. The safe remains open permanently." So an
  unspent disk drops from inventory overnight and returns to its source; inserting
  one at a terminal is the only thing that removes it from the world.

  Every disk therefore carries `persistence: "day"` except `upgrade_disk_trade`,
  which is genuinely repeatable. The permanence is enforced by the
  `GameConfig.collected_disks` carryover — populated from *spent* disks only,
  seeded into `gated_out` at day start, accumulated as a union by `DayChain`, and
  cleared on attempt wrap, the same shape as `used_vault_keys` and `lit_targets`.
  `fixed_disks_spent_today` keys off `persistence == "day"`, which makes the
  trade-disk exemption data-driven rather than a hardcoded id list.

  **Uniqueness alone does NOT enforce this.** A unique item is only blocked while
  *held*; `remove(consumed=True)` records it in `state.special.removed`, which is
  per-day state. Without `collected_disks` a spent disk is re-minted the next day —
  measured at 7 duplicates per day before the fix.

  Re-collection cost differs by source, and this is deliberate, not an oversight:

  - **Vault box 304** — the box stays open permanently; no key needed again.
  - **Garage car trunk** — re-locks *every night*; Car Keys are required on every
    single open (owner-confirmed). The most expensive disk to re-collect.
  - **Tomb / Trading Post** — candles stay lit; the disk returns on re-entry with
    no ignition tool.
  - **Commissary** — ordinary stock at 15g, offered on ~31% of days.
  - **Lost & Found** — stays in the random pool until spent.

  **Pre-existing bug found 2026-07-27: the Commissary disk was never obtainable.**
  It was flagged `reserve: true`, and the reserve branch only fired when available
  primary entries fell below `slots`. Four of the thirteen entries are
  `kind: resource`, which the availability filter never inspects, so primary was
  permanently >= 4 with `slots = 4` and reserve was unreachable dead code. Measured
  0/400 daily rolls. The sim was documented as modelling 7 disks but only **6** were
  ever reachable. Fixed by making it ordinary stock and deleting the dead reserve
  machinery, so a stray `reserve` key can no longer silently hide an item.
- **Upgradable rooms**: **15 rooms carrying 16 upgrade slots**, because Spare Room
  is upgraded twice — the first pick turns it into Spare Bedroom / Greenroom / Hall,
  and the second upgrades whichever of those was chosen into one of *its* own three
  sub-variants (`rooms.json` models this as a second-level `variant_of` chain).
  The other fourteen: Parlor (Gems / Keys / Funeral), Billiard Room (Speakeasy /
  Break Room / Pool Hall), Closet (Hallway / Bedroom / Empty), Storeroom (Keys /
  Gems / Coins), Nook (Extra Key / Breakfast / Reading), Mail Room (Same Day / No
  Contact / Freight), Aquarium (Goldfish / Starfish / Electric Eel), plus
  unnumbered Boudoir, Guest Bedroom, Nursery, Bunk Room, Hallway, Courtyard, and
  Cloister. Cloister has **8** variants but the terminal still shows only three, so
  three of the eight are sampled.
- The wiki publishes **no** tier list of "best" upgrades. It notes one endgame trick:
  switching *off* Cloister of Joya keeps its benefit while applying another upgrade.

**Owner decisions** (interview, 2026-07-26) — implement to these:
1. **The draw mechanism** — which room gets picked, how its three options are
   offered, and how the chosen upgrade is applied — is specified in full in
   [`upgrade-disks-design.md`](upgrade-disks-design.md). Read that before
   implementing; it is authoritative and covers the selection tables, the
   same-day application, and the action/observation cost.
2. **Terminals**: Security, Laboratory, Office, Shelter, Blackbridge Grotto (the
   last is outside the grid — gate it behind task 4). Insert requires standing in a
   terminal room holding a disk; the disk is consumed.
3. **Persistence**: an upgrade takes effect immediately, lasts the rest of the
   200-day attempt, and **resets on chain wrap**, consistent with every other
   carry-over flag. Mechanically that is two paths: the live decks are rewritten
   the moment the upgrade is chosen (design doc, "Applying the upgrade
   immediately"), and `carryover()` adds the chosen variant id to
   `GameConfig.upgrade_disks` — which already drives deck building — so later days
   rebuild with it, until `DayChain` clears it on wrap.
4. Supply cap: 16 disks exist in the real game, one per upgrade slot. Once every
   slot is filled the game keeps offering rooms, at a flat 1/15, so an upgrade
   already applied can be swapped for a different variant of the same room.

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

**The graph is specified and owner-reviewed: [`areas.md`](areas.md), with the
Graphviz source in [`areas.dot`](areas.dot).** 38 nodes, 75 directed edges, one
step per edge, plus the stateful mechanisms it implies — two position-tracked
elevators, four persistent torches, Pump Room water level, Rotating Gear
position. `data/areas.json`, the per-area travel action set and the observation
change are all delivered; the stateful mechanisms are not (see the stub-gate
decision below).

**No longer a prerequisite for measuring upgrades.** It was scheduled ahead of the
retrain on the strength of a projected 42x lift to Cloister of Orinda's offer rate
from unlocking the Catacombs. That projection came from synthetic contexts and did
not survive measurement: under real play the realized lift is **1.11x (z = 1.06,
not significant)** and the always-unlocked ceiling is **1.91x**. The Catacombs gate
also turned out to need only the Tomb, not this graph.

What task 4 still uniquely supplies: **Blackbridge Grotto**, the fifth disk-reader
terminal and the one modelled terminal with no room record; and the currently
inert `microchip`, `sanctum_key` and `key_of_aries` items. (The two off-grid
Upgrade Disks it used to list, The Foundation and the Abandoned Mine, are no
longer unique to this task — the Sanctum-route PR reached both.) It also
changes the action space, so it is still worth bundling with a retrain rather
than paying for two.

See [`upgrade-value-measurement.md`](upgrade-value-measurement.md) for the measured
numbers and why Cloister's Unusual rarity — not the gate — is the real bottleneck.

### Implementation plan (2026-07-27)

`outer_loc` was read at 40+ sites across `game.py`, `env/actions.py`, `env/obs.py`,
`engine/shops.py`, `engine/special_items.py` and `cli/play.py`, and doubled as a
phase flag for the action masker — so it could not be widened in place. Task 4
was delivered as two PRs, each independently green:

1. **The graph as data plus a pure library.** `src/blueprince_sim/data/areas.json`
   (nodes, directed edges, gates as declarative string tags in the
   `draft_conditions` idiom) plus `engine/areas.py` (frozen dataclasses, gate
   evaluation, BFS pathfinding at 1 step per edge) and `validate_data.py`
   referential checks. Nothing calls it, so there is zero behaviour change.
2. **Engine adoption and the env layer, together.** `GameState.area` replaces
   `outer_loc`; BFS derives the route costs, so the three `GameConfig` outer step
   costs are deleted rather than kept as a second source of truth; per-area
   travel actions replace `RETURN_EH_ACTION` / `RETURN_GARAGE_ACTION` /
   `ENTER_OUTER_ACTION`; and `player_area` joins the observation so position
   stops being a single grid-only `Discrete(45)` field.

Several currently-inert items unblock with this: microchips, Power Hammer wall
breaks, the Sanctum keys.

## Also outstanding (from `docs/plan.md`)

- **Reward calibration** from multi-day training statistics — all shaping constants
  (`special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY`, scepter bias)
  are deliberate knobs awaiting real run data.
- **Inner Sanctum**: the 8 Sanctum Keys have sources and persist, but the area
  behind the 8 doors is unmodeled. Overlaps heavily with task 4.

## 15. Room-behaviour fidelity: audit every room against the wiki

Opened 2026-08-08. The owner played several days through the Play tab and found
four modelling gaps in one sitting. Every one is a room whose *record exists* and
whose behaviour is wrong or missing, which is the class of bug no measurement
against the sim can find -- every probe agrees with the engine, because the
engine is what it measures. That makes this a systematic problem rather than
four tickets.

### The four found by play (verified against the data, not just reported)

- **Secret Passage — colour choice not modelled.** `effects: []`. Its own
  `meta.effect_text` says "Leads to a room of a color of your choice", and the
  owner reports the real mechanic: you pick one of **red, green, yellow, orange
  or purple** (blue and black are NOT offered), and then every room drafted from
  that room is that colour, unless none of that colour remain. Nothing
  implements this, and it is a *player choice*, so it needs an action, not just
  an effect tag.

- **Pantry — grants nothing.** `effects: []`, `meta.effect_text: "+4<coin>"`.
  Owner: it always gives **one random fruit (apple, orange or banana) and +4
  coins**. Note apples and oranges do not exist in `data/items.json` today (only
  `banana` among fruit) -- the same gap the resource-spreading design note hit
  for the Secret Garden, so the two should be fixed together.

- **Nursery — missing its immediate self-grant.** It has
  `grant_on_draft_category`, which pays when a Bedroom is drafted *later*, but
  the owner reports it **immediately grants the bedroom step bonus (+5 by
  default) on its own draft**. The forward-looking half works; the on-draft half
  is absent.

- **Eight rooms have a POOL name where a COLOUR should be.** The owner's example
  was the Vestibule (should be orange). The underlying fault is broader:
  `category: "studio_addition"` is not a colour at all, and eight rooms carry it
  -- `solarium`, `classroom`, `clock_tower`, `dormitory`, `vestibule`, `casino`,
  `dovecote`, `the_kennel`. Category drives real behaviour (category biases,
  `grant_per_category`, the Cloister/Terrace green boosts, scepter colours), so
  these eight are silently excluded from every category-keyed mechanic.
  `lost_and_found` is already correctly `red` -- the owner cited it as the
  *expected* colour, not a defect.

### The work: a per-room fidelity pass

Ad-hoc fixing has now missed four rooms in a row. Do this systematically instead:

1. **Split room-specific behaviour into per-room unit test files.** Today room
   behaviour is scattered across `test_game.py`, `test_effects*.py` and others,
   so "is the Pantry right?" has no single place to look or to fail.
2. **Research every room's behaviour from the wiki**, with verbatim citations,
   the way the Garage and Tunnel investigations were done.
3. **For each room, evaluate the codebase** to determine whether all of that
   room's functionality is actually modelled -- record present / partial /
   missing per room, and note where `meta.effect_text` describes something the
   `effects` list does not implement. That mismatch found three of the four
   above and is the cheapest first sweep.
4. **Write unit tests for each room's functionality**, following the repo rule
   that tests assert observable behaviour rather than data contents.
5. **Iterate until every room's functionality is properly implemented.**

Expect this to be large -- 169 room records, ~80 in the base pool. It is worth
scoping as a sequence of PRs (a batch of rooms each) rather than one change, and
worth starting with the rooms most likely to matter for the win condition, since
the 2026-08-08 measurement showed victory is unreachable on ~89% of days for
lack of lever rooms.

**Do not start a training run mid-audit.** Room behaviour changes what the
policy learns; batch these and restart deliberately, per the two runs already
discarded for exactly that reason.

## 16. Sweep comments that re-litigate past behaviour

Opened 2026-08-09, from the PR #89 review. Blocked on task 15 finishing -- a
comment-only pass touches many files at once and would collide with every
in-flight room PR.

The standing rule is in the decisions log: a comment says what the code does.
It does not narrate what the code used to do, defend against an alternative
that was rejected, or cite the bug that prompted the change.

Known instances, all landed in #89 and left in place on purpose:

- `tools/validate_data.py` -- the `KNOWN_GUARANTEED_ITEM_KINDS` comment cites
  the "2026-08-09 exact-coin-amount ruling" and the inline comment in the
  guaranteed-items loop explains that a typo "fails exactly the same silent way
  the exact-coins bug did" and justifies itself against "a low-value
  round-trip test".
- `src/blueprince_sim/engine/items.py` -- `grant_item`'s docstring contrasts
  `coins_exact` against `coins` at length, where it need only state what each
  one grants.
- `tests/rooms/test_vault.py` -- the two guard tests' docstrings describe the
  "obvious but wrong" fix they defend against rather than the property they
  pin.

Do not treat that list as exhaustive; it is where the rule was first noticed.
The sweep should cover `src/`, `tools/` and `tests/`, and is a good candidate
for a mechanical first pass (grep for dated ruling references, "used to",
"previously", "no longer", "instead of", "would have") followed by judgment.

Two things NOT to strip, so the sweep does not overshoot:

- **`docs/`** is exempt. `open_tasks.md` in particular exists to record
  history, and its decisions log is explicitly a record of what was ruled and
  why.
- **A comment explaining a non-obvious constraint the code must still honour**
  is describing the present, even when it sounds historical -- e.g. that
  `rooms.json` round-trips at 1-space indent, or that `_CARRYOVER_KEYS` is
  sorted because Python randomises string hashing per process. Keep those.

## 17. Room behaviour: registry migration

Opened 2026-08-10 from the architecture memo (see the decisions log entry of the
same date for the reasoning and the measurements). Runs alongside task 15 rather
than blocking it -- task 15 authors what a room does, task 17 changes where that
lives.

| Phase | Content | Status |
|---|---|---|
| 0 | Divergence validator in `validate_data.py` | DONE |
| 1 | Widen `Hook`: `ON_DRAFT_FROM`, `ON_HAND_DEALT`, `ON_ARRIVE`, `ON_DAY_END` | DONE |
| 2 | `room_hook` registry with opt-in `inherit` | DONE |
| 3 | Migrate the 13 singleton tags to `engine/effects/rooms/` | DONE |
| 4 | Relocate room-behaviour branches out of `game.py` / `draft.py` | DONE |
| 5 | Retire the behaviour half of the ingest tables | DONE |

The 13 singleton tags, which are the phase-3 worklist: `study_redraws`,
`allow_duplicates`, `greenhouse_bias`, `anti_luck`, `halve_steps`,
`furnace_bias`, `solarium_weights`, `coins_per_deadend`, `negate_red_rooms`,
`pay_gems_with_steps`, `schoolhouse_bias`, `conservatory_rerolls`,
`coins_per_draft`.

**Two effects draw from the RNG** -- `conservatory_rerolls` and `inject_pool` --
so migrating them can shift seed-stream consumption order. Keep each handler
firing at the same point in `fire()` and re-run `test_draft_stats.py`; a move
there is evidence the draft math regressed, not a flaky test.

**What stays in data, deliberately**: the 9 shared parametric tags -- `grant`,
`grant_per_category`, `grant_on_draft_category`, `set_resource_on_enter`,
`counts_as_bedrooms`, `counts_as_drafting_room`, `inject_pool`,
`free_green_drafts`, `reduce_draft_options`. They carry 44 of 57 effect instances
and are everything `items.py::expected_yields` introspects.

**CLAUDE.md's "prefer changing behavior by editing data over editing code" needs
rewording when phase 3 lands.** It remains correct for stats and for the shared
parametric tags; it has been quietly wrong for singleton behaviour for a while.

## Decisions log

- **2026-07-26, lockers**: locked lockers cost exactly one BASIC key — the wiki is
  explicit that lockers are not doors, so the Lock Pick Kit, Master Key, Stopwatch
  and smashers do nothing. This is what makes the Locker Room's key-spreading
  (task 1) load-bearing rather than flavour.

- **2026-07-27, Catacombs unlock**: `catacombs_unlocked` is true only on days the
  Tomb has been **drafted as the outer room AND entered**. It is deliberately NOT a
  permanent carry-over flag, even though the wiki says the angel-statue puzzle opens
  the wall permanently, because reaching the Catacombs still needs the Tomb present
  that day. Modelled as a data flag `flags.unlocks_catacombs` on the Tomb record
  rather than a hardcoded room id, so the rule is a data edit.

  This also settles the "Catacombs unlock condition" open decision in
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md).

  **Measured afterwards, and it does not deliver.** Real multi-day play with
  `greedy_rank` (~83k upgrade events per arm) gives a paired lift of **1.11x at
  z = 1.06 — not significant**; the always-unlocked ceiling is **1.91x**. Diagnosis:
  `P(catacombs_unlocked at insert)` is 8.24%, but line 7 also requires
  `min_drafts['cloister'] >= 1`, which fails on 88.7% of upgrade events because the
  Cloister is offered on only 5.87% of days. The gate is correct modelling that
  does not move the number.

- **2026-07-27, area-graph scope**: task 4 is NOT a prerequisite for making Cloister
  of Orinda measurable. The Catacombs gate needs only the Tomb (already modelled),
  and 7 of the 9 unmodelled Upgrade Disks sit in rooms that already deal (Office,
  Morning Room, Her Ladyship's Chamber, Great Hall, Freezer, Archives, Mechanarium).
  Only **The Foundation** (record exists but `pool=none`) and the **Abandoned Mine**
  (no record) are genuinely off-grid. Task 4 still owns Blackbridge Grotto (the 5th
  disk terminal) and the action-space change worth bundling with the retrain.

- **2026-07-27, task 4 sequencing**: task 4 runs BEFORE the Phase 1 forced-upgrade
  A/B. Phase 1 needs no checkpoint and so looks runnable immediately, but
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md) is explicit that a
  Phase 1 run made before task 4 is a **harness shakedown, not a bankable
  baseline** — task 4 changes the world the baseline describes, and the pre-lock
  and post-lock measurements must differ *only* by locks. Before task 4 is the only
  cheap window.

- **2026-07-27, task 4 PR1 scope — "graph traversal only"**: the stateful
  mechanisms the graph implies (POWER, Pump Room water level, the two elevator
  positions, the Rotating Gear position, the four torches) are NOT modelled in the
  first implementation. They land in later PRs.

- **2026-07-27, deferred gates default OPEN, explicitly stubbed**: each deferred
  mechanism gets a named stub that currently passes, carried in the data as
  `stub: true` and listed in a table so later PRs know exactly what to tighten.

  The alternative — closing them — was rejected because it kills **8 of the 36
  nodes**:
  Blackbridge Grotto needs POWER, Orindian Ruins sits behind the Grotto, the
  Safehouse needs water level exactly 6, the Well needs water ≤ 8, and Underpass /
  Inner Sanctum / Sigil Chambers / Upper Rotating Gear all sit behind the Rotating
  Gear position. That would delete Blackbridge Grotto, the one thing task 4
  uniquely supplies. An unreachable node measures exactly zero, which is a worse
  and more misleading failure than a slightly-too-generous world.

  **Consequence to print next to any number measured before the mechanism PRs
  land: it is an upper bound.** The `stub: true` flag is what keeps that visible
  rather than mysterious.

- **2026-07-27, `absent_spawn_rooms` names non-existent rooms** (found while
  building the area graph, deliberately NOT fixed in that PR). Three special
  items name ids that do not exist in `rooms.json`:
  `sanctum_key` -> `["reservoir", "safehouse"]`, `file_cabinet_key` ->
  `["crate_tunnel"]`, `key_of_aries` -> `["precipice"]`.

  `validate_data.py` does not catch these, because it only errors when an
  `absent_spawn_rooms` id *does* exist in `rooms.json` (the check exists to catch
  a room being re-added without promoting it to `spawn_rooms`). So the mistake is
  silent in both directions.

  They appear to be **area** ids, not room ids — `safehouse`, `crate_tunnel` and
  `precipice` are all area nodes in `areas.json`. But `reservoir` matches nothing
  even there, since the graph splits it into `reservoir_north` and
  `reservoir_south`. Resolve this when PR2 wires areas into the engine and the
  distinction between a room id and an area id becomes real; until then the
  entries are inert.

- **2026-07-27, Cloister frequency boosts**: model **all three** — the Terrace
  (makes the Cloister free while on the estate) and the Southern Cross / Greenhouse
  boosts. These touch Cloister's 5.87% per-day offer rate, which is the actual
  bottleneck on observing an Orinda decision. This is Phase 3 of
  [`upgrade-value-measurement.md`](upgrade-value-measurement.md) and is independent
  of task 4; it does not block the Phase 1 A/B, which needs no offer and no rare draw.

  **Audited 2026-08-05: two of the three were already implemented when this was
  written.** The Terrace boost works (`free_green_drafts`, `effects/tier1.py`, adds
  `"green"` to `free_categories`; Cloister is `category: "green"`), and so does the
  Greenhouse boost (`priority_draws.json` carries `category: green, chance: 0.4,
  condition: greenhouse_or_king`, and `draft.py::_active_conditions` emits
  `greenhouse_or_king` from `state.greenhouse_placed`). Only **Southern Cross** is
  genuinely missing, and it is the one that matters most here — see task 14.

- **2026-07-27, task 4 PR2 and PR3 merged into one PR**: the split existed to keep
  the action space frozen until the env PR, protecting live checkpoints. That
  protection was already void — PR #36 moved `disks_held` to `Discrete(15)` and
  `n_items` to 76, so no checkpoint loads regardless. One retrain is owed either
  way, so splitting bought nothing and cost a throwaway compatibility layer
  (an `outer_loc`-shaped observation re-encoded from `state.area` purely to keep
  the old space alive for one commit).

- **2026-07-27, the West Gate is a save-level unlock, not a per-attempt one**:
  unlatching it is permanent across the whole save (owner-confirmed), so a
  `GameConfig` field models it and maps onto the `west_gate_unlatched` graph flag.

  This also retracts an earlier worry: honouring the gate does **not** shift the
  measurement baseline — day-1 outer-room access is unchanged.

  Refined 2026-07-28 (next-but-one entry): the field was also gating outer-room
  drafting, which is a different fact, and the gate CAN now be earned in-run.

- **2026-07-27, `absent_spawn_rooms` resolved**: the field named off-grid AREAS,
  never rooms, and the check was silent in both directions. Renamed to
  `meta.absent_spawn_areas` and validated against `areas.json` node ids as well as
  `rooms.json`. Corrections from the wiki: `sanctum_key`'s `reservoir` became
  `reservoir_north` (the graph splits the halves; the box is on the Foundation
  Elevator side — inferred, not datamined, since the wiki gives no side), and
  `key_of_aries`'s `precipice` became `unknown_underground` (the clock is in the
  Unknown; the Precipice is only the access route). `file_cabinet_key` ->
  `crate_tunnel` was already correct: there are three distinct File Cabinet Keys,
  and the Archives Upgrade Disk sits behind the Patio key from the Aquarium, which
  is already modelled.

  Note the limit, confirmed by mutation: the new check catches nonexistent ids but
  **not** a wrong-yet-valid one. Restoring `precipice` passes validation, because
  it is a real node. That correction came from research, not tooling.

- **2026-07-27, travel actions are offered only to `modelled` areas**: exposing all
  36 nodes made the open stub gates expensive for the first time. 13 nodes are
  reachable on day 1 — including Blackbridge Grotto, the Precipice and the
  Safehouse — and none has modelled contents, so a random policy spent **80% of
  its steps** wandering an empty map (off-grid, 99.8% of the legal mask was
  travel). That is a direct tax on the fresh retrain.

  Fixed with a required boolean `modelled` on each area node. Only modelled nodes
  are offered as destinations; the pathfinder still routes through the others.
  Eleven are modelled today: `house`, `garage`, `west_path`, and the 8 outer
  rooms. Off-grid step share fell to 30%.

  **An action slot exists for every node regardless**, so switching an area on
  later is mask-only — no action-space change, no extra retrain. The flag lives in
  the data precisely so it is not a Python list of "useful areas" to hand-maintain.

  This does NOT touch the earlier "stubs default OPEN" decision: the stubs are
  still open and anything measured is still an upper bound. It only stops the sim
  from advertising empty rooms as somewhere worth walking.

  Note `greedy_rank` is unaffected — it never uses travel actions, and batch
  results are byte-identical to before this PR, so the Phase 1 A/B instrument is
  unchanged.

- **2026-07-28, `outer_rooms_unlocked` split into `west_gate_unlatched` and
  route-based outer-draft gating**: `GameConfig.outer_rooms_unlocked` was doing
  two jobs — gating the Grounds<->West Path shortcut AND gating outer-room
  drafting entirely. These are different facts (owner-confirmed 2026-07-28):
  on a brand-new save you CAN reach the West Path and draft an outer room from
  day 1 by going through the Garage (whose `garage <-> west_path` edge is gated
  only by `garage_door_breaker`, i.e. the Utility Closet placed and entered).

  **What changed:**
  - `outer_rooms_unlocked` renamed to `west_gate_unlatched`. The new name means
    exactly one thing: the Grounds<->West Path shortcut is open. It does NOT gate
    outer-room drafting.
  - `outer_draft_available()` no longer checks any config flag. It requires only
    an affordable route to `west_path` (via `_outer_route_cost()`) plus the
    existing once-per-day and phase conditions.
  - `west_gate_unlatched` is now earned in-run: `travel_to("west_path")` sets it
    on first arrival (necessarily via the Garage on a fresh save). `shops.carryover()`
    surfaces it; `DayChain._CARRYOVER_KEYS` carries it across days.
  - `fresh_save_config()` added to `rl/train.py` as the day=1 counterpart to
    `all_unlocks_config()`. `configs/fresh_save.yaml` provides the same preset for
    the `--config` CLI path.
  - `blueprince-train --unlocks {all,none}` selects between presets (default `all`).

  **The in-run discovery is recorded on `GameState`, never written back to the
  config.** The first implementation mutated `game.cfg` directly; the trainer builds
  ONE `GameConfig` per worker and reuses it for every episode, so that leaked the
  unlock into every later "fresh save" episode — measured: a second episode with no
  Garage placed at all inherited the 2-step Grounds route. `carryover()` ORs state
  with config, the same shape as `entrance_vase_broken` / `outer_chip_dug`.

- **2026-07-29, reward horizon — bootstrap across the day boundary**: a mid-attempt
  day ending is now `truncated=True` rather than `terminated=True`. SB3 bootstraps on
  `TimeLimit.truncated`, so `V(day N end)` picks up the value of day N+1 and cross-day
  investment becomes real value the agent can discover. Only the final day of an
  attempt (`current_day >= n_days`) is a true terminal.

  Chosen over making the episode span the whole attempt because the day boundary is
  genuinely non-absorbing, so this is the correct model rather than merely the cheap
  one — and every per-day telemetry consumer (`EpisodeRecorder`, `DraftStats`,
  `AreaStats`, win-rate) fires on `done = terminated | truncated`, which is still true
  at day end, so none of them changed.

  **Tradeoff, stated honestly**: credit propagates by one-step TD through the value
  function rather than by GAE across all within-attempt steps. The TD target is
  unbiased, but it is slower to propagate than multi-step returns; a within-attempt
  rollout would expose every cross-day transition to GAE at once. This is a
  convergence-speed cost, not a correctness one.

  `gamma` stayed at 0.999 and became a `--gamma` flag. An earlier claim that it
  "barely spans one day" was wrong: it was reasoned from `max_env_steps = 1000`, which
  is a safety cap, not a typical day. A day measures ~31 env steps, so 0.999 already
  gives ~32 days of lookahead. The discount was never the bottleneck.

  **Observability is half the fix, and the first cut got it wrong.** Bootstrapping is
  useless if the agent cannot see what it accumulated: `V(s)` has to be able to tell a
  heavily-upgraded attempt from a fresh one. The first implementation exposed only
  `DayChain._CARRYOVER_KEYS` — 6 booleans — while the chain also carries
  `applied_upgrades` and `collected_disks`, which are the actual "spend today to win
  later" investments. Four observation keys now cover it:

  - `day` — `[current_day, days_remaining]`; single-day mode is `[1, 0]`.
  - `carryover` — the 6 carry-over bools, sorted for stable field order.
  - `upgrade_slots` — one bit per upgrade slot, in `upgrades.all_slot_ids()` order.
  - `disks_spent` — how many of the finite one-time disk sources are used up.

  `all_slot_ids()` is derived by running `upgraded_slots()` over every registry
  variant, so the Spare Room's two-level chain stays defined in one place; it yields
  16 slots, matching the documented "15 rooms carrying 16 upgrade slots". Both it and
  the `carryover` vector are **sorted, never set-ordered**: Python randomises string
  hashing per process, so a set-ordered vector would permute between training runs and
  silently invalidate a checkpoint's learned field positions.

- **2026-08-04, The Foundation's 17 placement positions are ranks 3-8, not
  sourced**: the wiki states three placement rules (center 3 columns; never Rank
  2; never the Rank-8 cell directly under the Antechamber) plus a headline count
  of "17 positions", but the three rules alone leave 21 candidate cells once the
  Entrance Hall and Antechamber are excluded (23 before excluding them), not 17.
  The only way to land on exactly 17 is to also drop Ranks 1 and 9:
  `cols 1-3 x ranks 3-8 = 18, minus the Rank-8-under-Antechamber cell = 17`.
  Owner decision, on interview: **match the 17** — ranks 3-8 is now the coded
  rule (`the_foundation` draft condition, `placement.py`), understood as an
  inference from the stated count rather than a directly sourced rule. Act on
  this cold as: if a future wiki edit clarifies Rank 1 or Rank 9 explicitly,
  revisit the count derivation before trusting this rule further.

- **2026-08-04, only three area nodes plus the Foundation anchor go `modelled:
  true`**: of everything the Foundation's elevator opens up, only `basement`,
  `mine_south`, and `inner_sanctum` (plus the `the_foundation` grid anchor
  itself) are advertised as travel destinations. Owner decision, on interview,
  after measuring: everything else underground (`well`, `reservoir_south`,
  `reservoir_north`, `mine_north`, `rotating_gear`, `upper_rotating_gear`,
  `underpass`, `sigil_chambers`, `safehouse`, `catacombs`, `precipice`,
  `unknown_underground`) stays routed-through-but-unadvertised, so the step tax
  that motivated the original `modelled` flag (see the 2026-07-27 entry above)
  stays contained. `mine_south` earns its place specifically because it holds an
  Upgrade Disk, not because it is merely on the path. Act on this cold as: do
  not flip additional underground nodes to `modelled: true` without a similar
  "holds something worth walking to" justification and a fresh off-grid
  step-share measurement — the Sanctum route alone measured moving the off-grid
  step share from 29.93% to 41.88% under uniform-random play (see `areas.md`).

- **2026-08-04, the Foundation and Basement elevator gates stay open stubs**:
  `foundation_elevator_down` / `foundation_elevator_up` are not modelled this
  round — the wiki's elevator crank reveal (requires a room drafted so a door
  faces the Foundation's back wall) and nightly car-reset-to-the-top mechanic
  are real but deferred. Owner decision, on interview: leave them as the
  existing PR1 stub-gate convention (`stub: true`, passes unconditionally,
  `retire_in: PR-foundation-elevator`), consistent with every other deferred
  mechanism in this file. Consequence stated plainly: `the_foundation ->
  basement` is free once the room is drafted and grid-reachable, so any number
  measured through it (including the batch/reachability numbers in the PR that
  landed this) is an upper bound, exactly like the other open stub gates.

- **2026-08-04, Rank-3 draft removal implemented; Rank-4 dynamic rarity left
  open**: the wiki's "90% chance the Foundation is removed from the draft pool"
  when drafting on Rank 3 is implemented as a single per-hand roll (not
  per-card, to keep the RNG-draw count independent of deck order — see
  `foundation-design.md`). The wiki's separate claim that the Foundation's
  rarity "adjusts dynamically after reaching Rank 4" is explicitly NOT
  implemented — no curve is invented for it. Act on this cold as: if this
  becomes load-bearing later, it needs its own wiki research pass before any
  code is written; do not infer a curve from the Rank-3 number, they are
  different mechanics.

- **2026-08-04, the north-door reward is +0.5, paid by either lever, once per
  day**: the objective becomes three-tier — Antechamber first arrival (+0.25,
  existing), the Antechamber's north door opening (+0.5, new), Room 46 first
  arrival (+1.0, existing, the win). Owner decision, on interview: both levers
  (Inner Sanctum's main lever, Throne Room's backup) pay the same +0.5, because
  they accomplish the identical thing and the reward should stay neutral about
  which route a policy learns. Implemented as a per-day EVENT flag
  (`GameState.north_door_opened`) set only at the two lever call sites (unified
  through one `Game._open_north_door()` helper so they cannot drift), **never**
  derived from the north segment's own door state — with
  `antechamber_levers=False` the segment is never sealed to begin with, so a
  state-derived reward would pay +0.5 for free on every day of that arm and
  silently corrupt the pre-lever baseline that config exists to reproduce (this
  is guarded by a dedicated test in `test_sanctum_route.py`). Two consequences
  worth acting on: the per-day reward ceiling rises from 1.25 to 1.75 (the
  earlier 1.25 note argued for staying close to today's scale; a 40% rise puts
  that back in play, and shaping constants are not rescaled here — check
  whether dense terms get drowned out in the first retrain); and the Throne
  Room (one room, +0.5) is now priced higher than the whole rank-9 grind to the
  Antechamber (+0.25), which is an honest consequence of pricing the door
  rather than the walk, but is watchable as a farming incentive — compare
  `P(north door opened)` against `P(reach Room 46)` in the first retrain; a wide
  gap is the signature.

- **2026-08-04, the three Basement doors are independent, Basement-Key-only
  locks**: the wiki treats `Basement_door` as a door *type* with three
  instances — the Grounds side (the drained Fountain's floor, feeding
  `well -> reservoir_south`), the Foundation's elevator (feeding
  `the_foundation -> basement`), and the Crate Tunnel (unmodelled). Each
  unlocks **permanently and independently** the first time a Basement Key is
  used on it; any other normal or special key, and the Lock Pick Kit, do not
  fit. Owner decision, on interview: gate the Foundation's own door
  (`basement_key_foundation`, a second `kind: "item"` gate alongside the
  existing `basement_key_well`, same shape) rather than reusing the Well's
  gate id, since the two doors are genuinely separate locks that happen to
  share one key item. Before this, `the_foundation -> basement` was gated only
  by the (open, stub) elevator mechanism, so an empty inventory could reach
  `basement` for free through the Foundation once it was drafted and
  grid-connected — measured at 5 hops from the house with the Foundation
  placed. That loophole is closed; holding the Basement Key restores the same
  5 hops (a Power Hammer via `sealed_entrance` remains a 3-hop alternative that
  needs no key at all).

  **Held-key modelling simplification, stated explicitly rather than left to
  look like an oversight**: the real rule is "this door has been unlocked,
  permanently, by a Basement Key at some point"; the sim instead checks "a
  Basement Key is currently held right now". The two coincide in practice
  because `basement_key` is `persistence: "permanent"` and is re-granted from
  the Antechamber pillar on first entry every day, so once earned it is always
  held for the rest of the save — there is no path by which the key is used
  and then given up. See `areas.md` for the full writeup and
  `foundation-design.md` for the corrected critical-path analysis.

- **2026-08-04, the Sealed Entrance break is unconditionally permanent**: the
  three area-graph gates that used to model this (`power_hammer_planks` on
  `grounds -> sealed_entrance`, `power_hammer_wall` on `sealed_entrance ->
  basement`, and `basement_sealed_entrance_return` on `basement ->
  sealed_entrance`) were all item/flag gates checked fresh every day, so
  despite their own `detail` text claiming "permanent once broken" nothing
  ever latched that — and `basement_sealed_entrance_return` was never even
  added to `_gate_ctx`'s flag set, per the docstring's own admission ("NOT
  modelled; never added here"). Replaced with one `sealed_entrance_broken`
  flag gate shared by all three edges, set permanently in `state` the first
  time the player arrives at `sealed_entrance` (`Game.travel_to`), carried
  across days the same way as `west_gate_unlatched`/`mine_south_visited`.

  The wiki's `Sealed_Entrance` page states a conditional the owner was shown
  and explicitly overrode: *"If just the Basement wall is destroyed, it will
  respawn on the next day, whereas if just the planks are destroyed, neither
  side will respawn."* Owner decision, on interview, having played the game:
  there is no such distinction — breaking either barrier is permanent. That
  plank-vs-wall conditional is deliberately **not** modelled; this is an
  unresolved discrepancy between the sim and the wiki's stated mechanic,
  recorded here to be re-tested in game rather than re-derived from memory.

- **2026-08-06, the Precipice is an EXIT from the Abandoned Mine, not an
  entrance.** Owner correction, from play: the mine is reached from the house
  side — the Catacombs via the Tomb, the drained Fountain plus the Basement
  Key, or the lowered Reservoir crossing from the north — and only then are the
  8 candlesticks lit to *lower* the stairway to the Precipice. The graph had one
  physical stairway as two edges with different rules (`mine_south -> precipice`
  behind an item gate, `precipice -> mine_south` ungated), making the Precipice
  a free front door.

  This was not only a free Upgrade Disk. The route
  `house -> grounds -> precipice -> mine_south -> reservoir_south` walked
  **around the `basement_key_well` door**, so a day-1 empty inventory reached
  `reservoir_south` (4 hops) and the `safehouse` (5) — a **Sanctum Key source**.
  All three are now unreachable without the key; holding it restores
  `reservoir_south` at 3 and `mine_south` at 4, so the legitimate routes are
  untouched.

  An item gate was the wrong instrument regardless: measured, gating the reverse
  edge on the old `candlestick_stairway` item gate left the mine unreachable
  with an empty inventory but reachable again in 3 steps while **merely carrying
  a torch**. Both directions now share a `candlestick_stairway_lit` **flag**
  gate, set through the existing ignition system (`mine_south` became an
  `"area": true` ignition target; `lit_targets` already persists across days).
  Act on this cold as: the held-item simplification that is fine for
  `basement_key` (holding ≈ having used) **breaks** whenever reaching the place
  to use the item is itself the difficulty.

- **2026-08-06, the Shelter and the Boudoir both grant the safe gem.** The
  assumed-solved doctrine covers the Shelter's real-time timed safe and the
  Boudoir's 1225 code exactly as it covers the Office/Study/Drawing Room codes.
  This **overrides** the earlier hold-back that excluded both pending a call.
  Because a safe is a fixture of the room it survives every upgrade, and room
  effects are NOT inherited through `variant_of`, so `boudoir__ix16/17/18` each
  carry the grant in their own right — without that, upgrading the Boudoir would
  silently delete its safe. The Shelter is an OUTER room: its grant rides
  `Game.travel_to`'s `Hook.ON_ENTER`, which was verified to fire before the edit
  was made rather than after.

- **2026-08-06, "Underground" in task 3 is Rotating Gear (upstairs).** Owner
  clarification of a name that matched no room id. It is a room off a hallway
  from the **Underpass**, opened by Boiler Room steam; **assume the player
  unlocks it permanently after entering the Boiler Room**. One step from the
  Underpass, holding **a gem** and the **Treasure Trove blackprint**, with a
  return step back down. It is **not** reachable from the existing
  `rotating_gear` node.

  This maps onto the existing `upper_rotating_gear` node and its
  `boiler_room_steam` gate (an open stub), so the work is making that gate real,
  not adding a node — and it settles the reverse-edge audit's open question:
  `boiler_room_steam` **is** permanent.

- **2026-08-06, the Treasure Trove permanently gains +5 coins every time it is
  drafted**, making it a very valuable room. The Key of Aries / black-chest
  mechanics are **explicitly deferred** — do not model them with this.

  **Clarified 2026-08-07, after the first implementation got it wrong.** The
  room accumulates a 5-coin pile per draft and **every draft collects the whole
  surface**, so the Nth draft this attempt pays **5 × N**:

  | draft | pays |
  |---|---|
  | 1st | 5 |
  | 2nd | 10 |
  | Nth (N ≤ 32) | 5 × N |
  | 32nd | 160 |
  | 33rd and every later one | **160** |

  The wiki's "maximum of 32 piles (160 Gold Coin total)" caps **what a single
  draft is worth, not what the room earns over an attempt**. Past 32 piles the
  payout stops *growing*; it does not stop. The first 32 drafts alone come to
  5 × (1+2+…+32) = **2640 coins**, which is what "a very valuable room" meant.

  The first implementation read the cap as ending the payout — a flat 5 per
  draft, 160 lifetime, then nothing — which is worth 6% of the real figure and
  would have made the room barely worth drafting. Act on this cold as: when a
  source gives a cap alongside a per-event gain, establish whether the cap
  bounds the *event* or the *total* before coding it; here the two readings
  differ by 16x. Pinned by `test_drafts_past_the_cap_keep_paying_160` and
  `test_attempt_total_is_not_capped_at_160`.

- **2026-08-06, `reservoir_south <-> mine_south` has a real Reservoir
  water-level requirement.** Owner. Model it as a stub gate folded into the
  deferred `PR-pump-room` set (task 11); **invent no number**. Until then that
  crossing is ungated and anything measured through it is an upper bound.

- **2026-08-06, `king` splits into per-colour tags.** The Banner of the King
  picks ONE colour per day, identical to the Royal Scepter, so emitting a bare
  `king` tag would fire all five category biases at once. The five entries
  become `king_blueprint` / `king_hallway` / `king_bedroom` / `king_shop` /
  `king_blackprint`, mirroring the `scepter_<colour>` shape. **The Banner item
  itself is deliberately not wired** — no source for how it is obtained exists
  in our data, so the tags are correctly shaped and stay inert.

- **2026-08-06, our datamined bias magnitudes win over the wiki.** Our data says
  blueprint 50% and shop 25%; the wiki says 40% and 30%. The decompiled sheet
  has beaten the wiki before on exact tables, so no numbers change; the
  disagreement is recorded in the affected entries' `meta.notes` to be
  re-tested rather than silently resolved.

- **2026-08-06, task 6 is audit-only, and its premise partly does not hold.**
  The audit's two removal candidates, `diary_key` and `file_cabinet_key`, are
  **both already `implemented: false` with zero Python references** — so
  removing them is pure decluttering (one id each in the 76-slot item
  observation vector), not the action-id-and-inventory-slot saving the task
  assumes. `file_cabinet_key` is additionally stranded: its one real payoff, the
  Archives Upgrade Disk, is already granted directly on entry
  (`upgrade_disk_archives`, `guaranteed_in: ["archives"]`) under this same
  doctrine.

  **`basement_key` is the verified counterexample and a KEEP**: it gates
  `basement_key_well` on `well -> reservoir_south` and `basement_key_foundation`
  on BOTH directions of `the_foundation <-> basement`, so holding it is the
  literal difference between those areas being reachable or not.
  `key_of_aries` and `sanctum_key` are **deferred** — the first because the
  Treasure Trove mechanic above is about to make its target real, the second
  because its destination (`sigil_chambers`) is `modelled: false` with no
  further edges, which is an unbuilt-destination problem rather than a
  puzzle-only-item one.

- **2026-08-06, task 6 ruled: `diary_key` is removed, everything else stays.**
  Owner, after the audit. Only `diary_key` goes — the wiki itself says it has
  "no other known use", and the sim double-sources it (a Tomb luck-roll spawn
  *and* an unconditional Tomb-ignition grant) for an item that then sits inert.
  Removing it is data-only; no Python references it. Its ignition-grant entry
  must go in the same change, because `validate_data.py` resolves every ignition
  grant id against the special-items table.

  **`file_cabinet_key` is now an explicit KEEP**, reversing the audit's
  recommendation. `basement_key` remains a KEEP for the reasons above.
  `sanctum_key` stays **deferred**: unlike `diary_key` it is genuinely consumed
  and genuinely gates traversal, and it fails the removal test only because
  Inner Sanctum is unbuilt — not because the item is inherently choice-free.
  With 8 chambers and non-unique keys it may present a real choice once that
  lands, so re-run the decisive test then rather than assuming the answer now.
  `key_of_aries` stays deferred pending the Treasure Trove work.

- **2026-08-06, the Reservoir water gate is a NEW `reservoir_north <->
  reservoir_south` edge, not a gate on the mine crossing.** Owner correction of
  an earlier ruling that named `reservoir_south <-> mine_south`: the two
  Reservoir halves are freely traversable in both directions once the water
  level is set, and `reservoir_south <-> mine_south` stays **free and ungated**.
  This is the level-13 side-to-side boat crossing task 11 already records as
  "not currently represented as a graph edge/gate at all" — a **different** gate
  from `rowboat_water_6` (level exactly 6, the Safehouse rowboat); both retire
  in `PR-pump-room`.

  **Also owner, from play: `mine_south <-> mine_north` can NEVER be traversed —
  a mine cart blocks the way.** The graph already has no such edge, so this
  needs no data change, but it is now a sourced fact rather than an accident and
  is recorded in `docs/areas.md` so nobody later "fixes" the missing edge.

  **This gate defaults CLOSED — a deliberate exception to the 2026-07-27
  "deferred gates default OPEN" convention**, and the reason is measured, not
  assumed. With an empty inventory and only `sealed_entrance_broken` set (a
  Power Hammer sets it; it carries across days), an *open* crossing puts
  `reservoir_south` at 5 hops from the house, `mine_south` at 6 and the
  **`safehouse` at 6 — a Sanctum Key source** — all of which need the Basement
  Key today. The free route is `house -> grounds -> sealed_entrance -> basement
  -> reservoir_north -> ...`, walking straight around `basement_key_well`; that
  is exactly the loophole the Precipice fix closed one entry above. The
  convention's own rationale ("closing a gate kills 8 of 36 nodes") does not
  apply, because the edge is **new**: closed, the reachable set is identical to
  today's, so nothing is deleted and there is no empty-action-mask risk. Act on
  this cold as: the stubs-default-open rule is about not deleting existing
  reachability — it is not a licence to *grant* reachability the real game
  gates.

- **2026-08-06, re-measure the reward terms before buying the retrain.** Owner,
  on being shown that the Antechamber diagnosis' ranked fixes **#2 (rebalance
  the path-preservation penalty against the rank-progress reward) and #3 (make
  idling costlier than exploring) were never applied** — `env/rewards.py` still
  carries `PATHS_ONE_PENALTY = -0.15` / `PATHS_ZERO_PENALTY = -1.0`. PR #63
  delivered only #1 (`_ante_paths` reading `grid_frontier_doorways`) and #4 (the
  missing win keys). Since the diagnosis measured expansion at net-negative EV
  (`path` -0.468/episode against `rank` +0.204), a retrain started now could buy
  the same 8-hour stall with better instrumentation. The re-measurement re-scores
  `foundation-v2`'s fixed behaviour under the current reward function, which
  answers "does the reward still price drafting negatively" — it does **not**
  predict what a freshly trained policy would do, and must not be read that way.

- **2026-08-07, the reward function was NOT the problem.** The re-measurement
  above came back and reversed its own premise. Measured policy-free on current
  main, across **6,153 real grid crossings**, exactly **zero** produced a nonzero
  path-term delta: PR #63's fix is validated at population scale. Under that
  corrected accounting `greedy_rank` nets **+0.435/episode** and **+0.041 per
  room placement**, reaching mean deepest rank **5.39** without dead-ending once
  in 500 episodes. **Expansion is not structurally punished, so the 2026-08-05
  recommendation to rebalance `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY` was
  retired unimplemented** — it rested on a trained-policy measurement that is no
  longer reproducible and predates the fix.

  Act on this cold as: the instrument matters more than the suspicion. A
  scripted, policy-free probe answered in minutes what a checkpoint could not
  answer at all, and it overturned a recommendation that would have cost a
  tuning cycle.

- **2026-08-07, `runs/foundation-v2` is permanently unusable.** The checkpoint
  deserializes but SB3 refuses to run it: `carryover` grew from 10 to 12 keys
  when PRs #61/#63 landed *after* training stopped. A fresh run
  (`runs/postfix-v1`, `--unlocks all --multi-day 200`) was started and then
  **deliberately killed at 50,000 episodes / 2.21M timesteps** once the bugs
  below surfaced — owner decision, on the reasoning that a run 3.5% in is nearly
  free to discard and expensive to discard later.

  Act on this cold as: an observation-space change kills every checkpoint
  trained before it, the moment it merges. Batch space-affecting changes and
  restart deliberately rather than merging them mid-run.

- **2026-08-07, the Tunnel chain deals THREE options, not one.** Owner, from
  play: the chain offers three rooms every time and merely *guarantees* a Tunnel
  is one of them. The sim dealt exactly ONE forced Tunnel and skipped the
  three-slot deal — its own docstring said so. Measured, 60 seeds: drafting
  north from a Tunnel dealt 1 option in 60/60; drafting south dealt 3.

  **This explains the apparent "Tunnel spam" completely, and it was never a
  reward exploit.** Across the 329 recorded episodes of `runs/postfix-v1` there
  were 210 Tunnel placements in 45 episodes: **exactly 45 genuine choices, one
  per episode, and 165 forced single-option hands (78.6%)**. No episode ever
  held two real Tunnel choices. A policy taking the only card it is dealt is not
  gaming anything, so **no reward change was made on this evidence**.

  The guaranteed Tunnel goes in **slot 0**, which **overrides the owner's own
  recollection** of a middle slot. The wiki's `Drafting/Advanced` says "a Tunnel
  is drawn into Slot 1", and that page is 1-indexed — its "Slot 1 always makes a
  Free Draw" matches this engine's free-only slot 0, and "a Library is drawn
  into Slot 3" matches the existing priority-draw index 2. The conflict was
  surfaced rather than silently resolved, and the owner ruled for the wiki.

  **Sourced but deliberately NOT implemented**: the same wiki line ends "This
  does not repeat on redraws" — redealing a chain hand should not re-guarantee
  the Tunnel. The code re-triggers on every redeal because it keys only off
  `from_room`/`direction`; distinguishing the initial deal needs new per-hand
  state.

- **2026-08-07, the Garage gets its Forced Draw; the other three precedence
  rooms do not.** Owner, from play: the Garage appears far more often in the
  real game, typically ranks 4-5 in column 0. Cause: `forced_draw_precedence`
  has been **dead data since the area work** — nothing in `src/` ever read it.

  Datamined rule, now implemented: forced into **slot 3** at **90%** (**92.5%**
  with the West Gate), gated on **Veteran Mode or Day 3**, blocked when the
  first two slots are both Dead Ends, **once per day**, with the roll retrying
  at each eligible doorway until it succeeds. Measured over 5000 episodes at
  every doorway where the Garage is legal: `greedy_rank` **17.61% → 53.59%**,
  `random` **39.06% → 78.31%**.

  The Garage's **placement rule was already correct** (West Wing, ranks 4-8,
  entered north or west — five legal tiles, wiki-verbatim), so the owner's
  "ranks 4-5" observation was about frequency, not geometry.

  **Scope is the Garage slice only**, for specific reasons: Conservatory sits
  behind the unmodelled Found Floorplan mechanic, Morning Room behind a Bacon &
  Eggs prerequisite of unverified completeness, and Utility Closet's own forced
  draw is *gated on the Garage having already been drafted*. The precedence list
  stays data. The Garage's separate **Day-5**-or-Veteran 3% passive priority
  draw is a **different gate** from the **Day-3** forced-draw gate and is
  deliberately not implemented — do not conflate the two thresholds.

  Two unsourced readings, recorded rather than buried: "or Slot 2 was not drawn
  by a normal draw" is read as slot 1's `DraftOption.forced` being False; and
  the forced draw is checked **before** the existing priority draws, because no
  source specifies precedence between the two systems. Note also that Forced
  Draws and Priority Draws are **different mechanics** — the wiki is explicit
  that one filters the deck for a round and the other pushes a room into slot 3.

- **2026-08-07, per-option orientation choice is NOT a mechanic.** `ALT_BASE`
  reserved three action ids nothing could ever select: `action_mask` never set
  them (verified live as all-False at every draft), and `apply_action` routed
  them through the identical `game.choose(slot)`, which takes no orientation
  argument. `GameConfig.orientation_choice` was read nowhere. Owner ruling: an
  option arrives with a rolled orientation, and rotation is a separate effect
  (Ornate Compass / Rotunda / Dovecote) already modelled by `ROTATE_ACTION`,
  which advances every option together. Both removed; `N_ACTIONS` 314 → 311.

  Act on this cold as: a dead id in a masked action space misleads every later
  investigation — this one survived long enough to be mistaken for a missing
  feature. `test_macro_actions.py::test_every_action_kind_has_a_masking_site`
  now asserts every declared `*_BASE`/`*_ACTION` has a write in `action_mask`.

- **2026-08-07, time pressure is priced per game-step, not per decision.** The
  flat `-0.001` per decision meant a travel hop consuming 4-8 steps cost the
  same as a 1-step move, while `out_of_steps` causes **68% of terminations** —
  so any action packing many steps into one decision was under-taxed per step.
  Now `0.001 * max(1, steps_spent)`, with step *gains* clamped to zero (food and
  the Orchard bonus would otherwise turn the term into a reward bonus) and a
  floor so zero-step decisions still pay the old flat rate.

  **Stated plainly: a principled correction, not a proven fix.** The policy
  behind the measurement had trained 50k episodes, and a barely-trained masked
  policy travels heavily regardless. The magnitude is **not** cosmetic either —
  measured across 329 episodes the mean per-episode time term moves
  **-0.04494 → -0.08257, ~1.84x**. `phased` got the identical change because its
  own docstring promised it matches `shaped`.

- **2026-08-07, the depth-vs-reachability question is DEFERRED, to be measured
  after the Tunnel fix.** A Tunnel corridor proves `deepest_rank` can reach 9
  while the Antechamber stays literally unreachable: a `straight` room drafted
  north is always N|S, so a Tunnel spine has **zero lateral connectivity by
  construction**, and a column-1 corridor can never reach the Antechamber in
  column 2. In the traced episode `distance_map()` reported the Antechamber
  unreachable from step 1 through termination while `deepest_rank` hit 9, and
  `antechamber_reached` stayed false throughout. `_phi_paths` misses it because
  it counts *global* frontier doorways, not whether a room added branching.
  Measured, Tunnel placements net **+0.109** each against **+0.030-0.033** for
  ordinary rooms — ~3.3x the reward density, risk-free and gem-free.

  That gap applies to a *chosen* Tunnel too, so it survives the drafting fix.
  **Owner decision: change no reward constants yet.** Once the Tunnel is one of
  three options, measure how often the policy actually **chooses** it; well
  above the ~33% base rate means the reward genuinely overvalues cheap depth and
  can then be tuned against evidence rather than a 50k-episode artifact.

- **2026-08-07, `replays.jsonl` is severely selection-biased — never use it to
  establish prevalence.** Best-of-window records are selected by
  `(win, deepest_rank, rooms_placed)`, so a depth-maximising pattern is exactly
  what they over-represent. Measured on `runs/postfix-v1`, 329 records:

  | population | n | mean deepest rank | mean rooms | rank-9 |
  |---|---|---|---|---|
  | `top_window` | 54 | **7.94** | 14.11 | 18 |
  | `random` | 275 | **2.84** | 6.70 | 1 |

  The buggy Tunnel chain fired in **74% of `top_window`** records but **0.7% of
  `random`** ones. Both owner observations that started these investigations
  came from browsing the Observatory's Runs list, which the starred records
  dominate — the observations were right about what the *curator* surfaces, not
  about what the policy typically does.

  Act on this cold as: split `random` from `top_window` before quoting any rate,
  and use `random` alone as the behavioural baseline. `EpisodeRecorder` does not
  feed back into PPO's buffer, so this is a **reporting** artifact, not a
  training feedback loop.

- **2026-08-08, Veteran Mode is the default, including on a fresh save.** Owner:
  the sim is written for experienced players, who trigger Veteran Mode on day 1
  by drafting the first three rooms out of the Entrance Hall quickly. **The
  trigger is not modelled — only its outcome**, the same assumed-solved doctrine
  applied to room puzzles.

  It gates three systems, and the effect differs sharply by preset because
  `all_unlocks_config` runs at day=20, where the day counter already satisfied
  two of them:

  | | all_unlocks (day 20) | fresh_save (day 1) |
  |---|---|---|
  | gem deck-size gates | already on via day >= 16 | **now active** |
  | Garage forced draw | already on via day >= 3 | **now active before day 3** |
  | Upgrade Disk slots | **veteran tables** | **veteran tables** |

  Non-veteran picks the first upgrade from a weighted table (Storeroom 35%,
  Courtyard 25%, then a tail); veteran is **uniform over all 16 slots** plus a
  **day-1 shortcut firing 70%** of the time.

  **Consequence worth acting on: a fresh save is no longer the loosest possible
  draw environment**, because the gem gates now bind from day 1. The
  `fresh_save_config` docstring previously claimed `gem_gate_active()` is off
  until day 16; that is no longer true and was removed. Veteran Mode is also
  **not a permanent unlock** — it is triggered per save by how the player opens
  day 1 — so it sits with `royal_scepter_found` under the deliberate exceptions,
  not with the earned unlocks.

- **2026-08-08, write rulings into this log immediately, not at session end.**
  Owner instruction, after a session accumulated six unrecorded rulings before
  writing any down. Decisions that live only in the conversation are lost to
  compaction, and the cost of losing one is re-litigating something already
  settled — the entire reason this log exists. Record the reasoning and any
  measurement that justified it, not just the outcome, and say explicitly when a
  ruling overrides the wiki or reverses an earlier assumption.

- **2026-08-08, three outer-area bugs found by PLAYING the Play tab, and the
  second run was discarded for them.** The owner played a day through the web
  interface and recorded it to `runs/postfix-v2/demos.jsonl` (seed 964156478,
  103 actions, `unlocks: fresh`). It replays with `divergence=None`, so all
  three reproduce exactly — the demo pipeline paid for itself here.

  **The outer draft was refused while standing on its own doorstep.**
  `outer_draft_available()` carried `if self.off_grid: return False`, but
  `west_path` IS the doorstep — `open_outer_draft()` opens with
  `travel_to("west_path")`. The session shows the cost: travel to West Path (3
  steps), forced back to House (2 steps), then "outer draft" auto-walks back to
  West Path. **Two steps burned to stand where the player already was.**

  **Dice could not reroll the outer-room hand**, which the owner reports is a
  common strategy for forcing the Tomb. Reproduced holding 5 dice:
  `_redraw_kind()` returned None before ever looking at them.

  **The Apple Orchard was unreachable and its +20 steps unearnable** — two
  problems stacked, which is why nothing the owner tried worked. `apple_orchard`
  AND `campsite` (its only approach) are both `modelled: false`, so neither is
  ever offered as a destination even though the graph path is fine and the
  `padlock_code` gate passes under the assumed-solved doctrine. Separately,
  `GameConfig.orchard_unlocked` is set only in the two `train.py` presets, so
  even arriving could not grant the bonus. Advertising the nodes alone would
  have left the player walking there for nothing.

  **`runs/postfix-v2` was killed at 122,500 episodes / 5.55M timesteps (39
  min)** — owner decision, the same reasoning as the first discard: bugs 1 and 2
  change which actions are legal during outer-room drafting, a once-per-day
  decision every single day, so a policy trained through them learns a game we
  know is wrong. The action-space SIZE was unchanged, so this was a correctness
  call rather than a forced one.

  Act on this cold as: **play the game through the Play tab before committing
  compute.** Three real modelling bugs surfaced in a single recorded day, none
  of which any amount of measurement against the sim would have found — every
  probe agrees with the engine, because the engine is what it measures.

- **2026-08-08, redraws work on the outer-room draft, from every source.**
  Owner: "Assume that the study works outdoors. I think the reroll works on all
  drafts" — clarified as the Study's **gem** rerolls specifically. So the
  `target_cell == -1` early-return in `_redraw_kind` goes away entirely rather
  than being narrowed to dice: the Classroom's free redraws, an ivory die, and
  the Study's 1-gem reroll (still capped at 8 per hand) all apply to an outer
  hand, with the existing cheapest-first precedence unchanged.

  **Recorded as owner-ruled and hedged ("I think"), not as sourced.** If the
  wiki later contradicts it, this is the entry to revisit.

  Not a one-line unblock, and worth knowing why: `Game.redraw()` also asserts on
  outer hands, and it calls `redeal()`, which runs the GRID pipeline
  (`_fill_options`: rarity rolls, decks, priority draws, the Tunnel chain) while
  outer hands come from a fixed pool of 8 shuffled on the `"outer_draft"` RNG
  label. Worse, `redeal()` opens with `state.grid[pending.from_cell]` and an
  outer hand has `from_cell = -1`, which Python does not reject — it silently
  reads the LAST grid cell. Lifting the assert alone would have dealt grid rooms
  into an outer hand from a fabricated "from room". The redeal needs its own
  outer path and its own RNG label, so the initial-deal sequence is untouched.

- **2026-08-08, the Apple Orchard becomes reachable and its +20 steps earnable.**
  Owner. `apple_orchard` and `campsite` flip to `modelled: true` so they are
  offered as travel destinations, and visiting the Orchard grants a permanent
  +20 starting steps through the carry-over machinery — the same shape as
  `west_gate_unlatched` and `sealed_entrance_broken`, which are likewise earned
  in-run rather than configured.

  Note this is a deliberate exception to the 2026-08-04 rule that a node only
  goes `modelled: true` if it "holds something worth walking to". The Orchard
  now does hold something: a permanent step bonus. The step-share measurement
  that rule exists to protect should be re-checked after it lands.

- **2026-08-08, the win rate is probably a CONTENT problem, not a learning
  problem.** Owner hypothesis, from playing: "the game is struggling to achieve
  the victory condition because there are exceedingly few implemented paths to
  victory." Measured, and it holds up.

  Reaching Room 46 needs an Antechamber door opened, which needs a lever room
  drafted AND entered. Over **400 `greedy_rank` days** on `all_unlocks_config`
  (mean 8.43 rooms placed):

  | lever room | placed |
  |---|---|
  | `weight_room` | 6.8% |
  | `great_hall` | 3.3% |
  | `greenhouse` | 1.3% |
  | `secret_garden` | 0.0% |
  | `throne_room` | 0.0% |
  | **any of them** | **11.0%** |

  `P(antechamber reached) = 0.000`, `P(room 46) = 0.000`.

  **So on ~89% of days no lever room is placed at all, and victory is
  structurally unreachable before the policy makes a single decision.** No
  amount of reward shaping fixes a day where the win condition cannot be
  opened. This reframes the standing `p_antechamber = 0.000` question, which
  three separate investigations have attacked from the reward side.

  Caveat, stated so the number is not over-read: `greedy_rank` pushes north and
  does not *seek* lever rooms, so 11.0% is "how often one turns up incidentally",
  not "how often a determined player could get one". `secret_garden` reads 0.0%
  because its key must first be found in the Attic or Music Room and this policy
  never pursues items — the key mechanism itself works (verified: holding
  `secret_garden_key` flips `satisfies_draft_conditions` from False to True).

  Act on this cold as: **before tuning the reward again, check whether the
  objective was reachable at all that day.** A win-rate denominator that
  includes structurally-unwinnable days is measuring room availability, not
  policy skill.

  Owner's plan is to re-measure after the Pump Room lands, since that opens
  routes the sim currently closes.

- **2026-08-09, training is parked; room fidelity is the only priority.** Owner,
  ruling on PR #84's open question. The Apple Orchard's off-grid step-share jump
  (35.67% -> 69.28%, 300 seeds, uniform-random masked play) is **accepted as-is**:
  both `campsite` and `apple_orchard` stay `modelled: true`. The reasoning is not
  that the tax is small -- it is that **the tax does not matter yet**, because
  "too few victory paths exist to make training worthwhile" (the 11.0% lever-room
  measurement one entry above). Optimising a training cost before the game is
  winnable is optimising the wrong thing.

  Two consequences to act on. First, this **suspends the usual "a node only goes
  `modelled: true` if it holds something worth walking to" discipline** (2026-08-04)
  for the duration of the audit -- but only suspends it: the step share must be
  re-measured, and this decision revisited, before any run is started. Second, the
  standing "do not start a training run mid-audit" rule now has a second and
  stronger reason behind it than checkpoint churn.

- **2026-08-09, task 15 sequencing: the test split ships FIRST, alone, to buy
  parallelism.** Owner. PR 1 is a pure reorganisation -- room-specific behaviour
  moves out of `test_game.py` / `test_effects*.py` / the scattered feature files
  into `tests/rooms/test_<room_id>.py`, one file per room. No behaviour change, no
  new assertions. It ships before any room fix because per-room files are what make
  the later PRs **genuinely disjoint**, and the repo rule is that parallel subagents
  need disjoint files including `tests/`. Without the split every room fix collides
  in `test_game.py` and the audit serialises.

  Granularity ruled: **one file per room, created as the audit reaches it**, not
  169 stubs up front and not per-category groupings. Rooms with no behaviour to pin
  get no file. The **absence** of a file is therefore a deliberate, readable record
  of what has not been audited yet -- the audit's own progress bar, kept in the test
  tree rather than in a document that can drift.

  After PR 1: identify sets of rooms whose behaviour is genuinely independent and
  give **each set its own PR**, rather than one large audit change.

- **2026-08-09, research doctrine for task 15: full wiki pass per room, with
  `effect_text` as a strongly-weighted prior.** Owner, refining the 2026-08-06
  "our datamined tables beat the wiki" ruling rather than repeating it. That ruling
  was about **magnitudes** -- exact percentages and payouts, where the decompiled
  sheet has won before. It does not extend to **coverage**: `meta.effect_text` is a
  single curated line and routinely elides an entire mechanic (the Secret Passage's
  five-colour choice, the Pantry's fruit). So every room gets a full wiki pass whose
  specific job is **finding mechanics the effect_text omits**, while `effect_text`
  stays authoritative on the numbers it does state.

  **Discrepancies are batched, not streamed.** Where the wiki and `effect_text`
  disagree on a *mechanic* (not a number), the room is parked and carried into a
  single consolidated question round put to the owner **before implementation
  begins** -- explicitly so the owner's involvement is one sitting rather than
  interruptions spread over hours. This is a process ruling with teeth: an agent
  that hits a discrepancy mid-implementation has already sequenced the work wrong.

- **2026-08-09, cross-day room mechanics are IN scope; "out of single-day scope"
  is retired as stale doctrine.** Owner, on being shown that seven rooms are
  unimplemented only because their own `meta.effect_text` annotates the mechanic
  as spanning days: `sauna`, `morning_room`, `master_bedroom`, `clock_tower`,
  `mail_room`, `freezer`, `break_room__ix11`.

  The annotation describes the simulator's past, not its present.
  `env/multiday.py:30` already carries 13 boolean flags across days plus
  `applied_upgrades`, `draft_counts`, `foundation_cell`/`foundation_doors`,
  `repellent_bans` and `carried_items`. The decisive precedent is one line in
  that same list, merged the previous day in PR #84:

      "orchard_unlocked",   # grants +20 starting steps next day

  which is exactly the shape `morning_room` ("+2 gems tomorrow") and `sauna`
  ("+20 STEPS tomorrow") need. All seven are implemented on that pattern.
  `mail_room` and `clock_tower` additionally need a small day-counter rather
  than a bool, which is new but shallow.

  **The stale annotations are corrected in the same work**, deliberately: an
  effect_text that wrongly says "out of scope" does not merely mislead a reader,
  it suppressed these rooms from THIS audit — several batches accepted the
  annotation and marked the room blocked. Two more of the same kind were found
  and are corrected with them: `throne_room` claims "entirely out of scope, no
  effect modeled" while `game.py:1510-1517` implements its north Antechamber
  lever, and `lost_and_found` claims the same while `special_items.py:499-668`
  implements its steal/gift. `trading_post` is a third (`shops.py` implements
  the full tier graph its metadata calls out of scope).

  Act on this cold as: **a scope annotation is a claim with an expiry date.**
  When the engine grows a capability, sweep the annotations that denied it.

  **Correction, same day: the Sauna grants STEPS, not coins.** The question
  round and the first version of this entry both said "+20 coins". The
  record's own `meta.glyph_resolution` resolves its glyph as `steps` at
  `datamined` confidence. The ruling is unchanged -- cross-day mechanics are
  in scope whatever the resource -- but the wrong resource would have been
  implemented from this entry.

  Act on this cold as: **never read a currency off the mojibake in
  `effect_text`.** Every ambiguous glyph carries its own
  `meta.glyph_resolution` entry with a confidence, and that is the
  authoritative resolver -- the ingest `GLYPH_MAP` resolves by UTF-8 byte
  value for exactly this reason. Three glyphs collide visually once the sheet
  is decoded: steps, coins and gems. `nurses_station__ix102` and
  `spare_master_bedroom__ix136` are steps too, not the coins they look like.

- **2026-08-09, a room stating an exact coin amount grants exactly that amount.**
  Owner. `items.guaranteed`'s `coins` count means *piles*, each rolling 1-5
  (`engine/items.py:92-106`, `items.json` `pile_min: 1, pile_max: 5`), so every
  room whose text promises a specific figure systematically misses it:

  | room | piles | range | mean | effect_text |
  |---|---|---|---|---|
  | `vault` | 8 | 8-40 | 24.0 | +40 coins |
  | `rumpus_room` | 2 | 2-10 | 6.0 | +8 coins |
  | `pantry` | 1 | 1-5 | 3.0 | +4 coins |

  The Vault is the case that decided it: a room the player spends keys to open,
  quietly worth **60%** of its advertised value. This needs a schema addition
  distinguishing "N coins" from "N piles"; the pile roll stays for rooms that
  genuinely scatter piles.

  **Note this is the sim disagreeing with BOTH sources, not a source conflict** —
  the wiki and the datamined effect_text agree on the numbers. It is therefore
  not covered by the 2026-08-06 "datamined beats the wiki" ruling, which
  arbitrates between sources and has nothing to say when they concur.

  Recorded because an earlier audit pass misread this as a data-entry slip
  ("count 2 against +8 coins, a fourfold under-grant"). It is not: 2 piles
  average 6, not 2. Act on this cold as: check what a count counts before
  calling it wrong.

- **2026-08-09, all 16 pool-name categories are corrected to real colours.**
  Owner. Task 15 recorded eight rooms carrying `category: "studio_addition"`;
  there are **sixteen** — the eight outer rooms carry `category: "outer"`, the
  identical fault.

      studio_addition: solarium, classroom, clock_tower, dormitory,
                       vestibule, casino, dovecote, the_kennel
      outer:           tomb, toolshed, root_cellar, shelter, hovel,
                       schoolhouse, shrine, trading_post

  The exclusion mechanism is `draft.py:302`, the category-targeted draw filter:
  a room whose category is a pool name can never be drawn by a category-targeted
  draw, which silently removes all 16 from the Secret Passage colour choice,
  scepter colours, `grant_per_category`, the Cloister/Terrace green boosts and
  every category bias.

  **It also left two branches unreachable**: `game.py:994` and `shops.py:359`
  both gate outer-room shop behaviour on `outer_room.category == "shop"`, which
  no outer room can satisfy. Verified behaviourally rather than by grep, per the
  standing lesson: all eight shops declared in `shops.json` are on-grid base
  rooms already carrying `category: "shop"`, and no outer room is a declared
  shop. This is the `forced_draw_precedence` shape again — a branch written for
  a condition the data never produces, silent in both directions. The Trading
  Post is the room it most likely concerns; its own effect_text opens "Counts as
  a Shop."

  Lands as its own PR: `Room.category` has 22 read sites, and this changes
  behaviour at `draft.py`, `tier1.py`, `state.py`, `special_items.py` and the
  `env/obs.py` category feature. **`CATEGORIES` in `env/obs.py` is left alone** —
  removing the now-inert `studio_addition`/`outer` slots would renumber every
  later category for no behavioural gain. `test_draft_stats.py` keys on rarity,
  not category, so it should be unaffected — confirm rather than assume.

- **2026-08-09, the assumed-solved doctrine extends to puzzle-reward rooms.**
  Owner. `gallery`, `room_8` and `parlor` grant their documented rewards on
  entry with no puzzle modelled, exactly as the room safes and the Shelter's
  real-time timed safe were ruled on 2026-08-06.

  **`great_hall` and `closed_exhibit` are deliberately excluded.** The
  distinction that decides it: in the three included rooms the reward IS the
  mechanic, so granting it loses nothing. The Great Hall's interior subchambers
  are a randomised *spatial* system behind Silver/Prism Key doors, and the
  Closed Exhibit's is a *lock* system — in both, flattening the mechanic to a
  constant would delete the structure, not approximate it. The Great Hall is
  a lever room at 3.3% placement, so the temptation to inflate it is real and
  is being declined on purpose.

- **2026-08-09, comments state what the code does, not what it used to do.**
  Owner, on PR #89. Code comments, docstrings and test docstrings must describe
  **current behaviour**. They must not narrate the previous behaviour, argue
  against a rejected alternative, or cite the bug that motivated the change.
  When behaviour changes, **delete the old description rather than contrasting
  with it**.

  The rationale, the rejected alternatives and the measurement belong in the
  **PR body and the commit message** -- those are the record of *why*. The
  source comment answers *what*. Test docstrings still state the property under
  test, which is a hard CLAUDE.md rule, but they state it directly: "a Coin
  Purse held on entry earns interest on the grant", not "this guards against
  the wrong fix that would have bypassed the purse hook".

  **#89 was merged carrying the violation**, deliberately: the owner's reason
  was that the habit is widespread rather than specific to that PR, so fixing
  one instance while the rest of the tree does it would be noise. The sweep is
  task 16, scheduled **after** the room-behaviour audit rather than interleaved
  with it -- a comment-only pass touching many files would collide with every
  in-flight room PR, which is the same disjointness argument that put the test
  split first.

  Act on this cold as: **put this constraint in every subagent implementation
  brief.** Agents narrate their reasoning into the code they write by default,
  so this recurs unless it is stated up front.

- **2026-08-09, model correctness outranks observation- and action-space
  stability.** Owner: "Do not worry about changing the observation vector or
  action vector. I need the game to function properly before we train anything
  meaningful."

  This **suspends** the standing caution that has shaped several earlier
  decisions -- the 2026-07-27 "an action slot exists for every node regardless,
  so switching an area on later is mask-only", the PR2/PR3 merge whose split
  existed to keep the action space frozen, and the 2026-08-07 note that an
  observation-space change kills every checkpoint the moment it merges. Those
  were correct while a run was live or imminent. No run is live, no checkpoint
  is being preserved, and the 11.0% lever-room measurement says a trained
  policy would be measuring room availability rather than skill.

  So during the room audit: **if widening the observation vector or adding an
  action is the natural model for a mechanic, do it.** Do not contort a design
  to preserve a vector nobody is training against.

  Two things this does NOT license, because neither is about checkpoints:

  - The carry-over vector and `upgrade_slots` must stay **sorted, never
    set-ordered**. Python randomises string hashing per process, so a
    set-ordered vector permutes between runs *within* a training session and
    silently corrupts learned field positions. That hazard is unchanged.
  - A dead action id is still a defect. `ALT_BASE` reserved three ids nothing
    could select and survived long enough to be mistaken for a missing feature
    (2026-08-07). `test_macro_actions.py` asserts every declared `*_BASE` has a
    masking site; keep it true.

  Act on this cold as: **record the width change even though it no longer
  blocks anything.** Whenever training resumes it forces a fresh run, and the
  cheapest time to know that is when it happens, not when a checkpoint fails to
  load.

- **2026-08-09, "tomorrow" bonuses are ONE-DAY PULSES; the Apple Orchard and the
  Gemstone Cavern are the permanent ones.** This corrects a framing error of
  mine, found by research rather than by review.

  I briefed the cross-day rooms as "the same shape as `orchard_unlocked`",
  meaning earned once and true forever. The wiki contradicts that for every one
  of them: the Sauna, the Morning Room's next-day half, the Freezer's carryover
  and the Break Room's keycard are **Tomorrow Rooms**, applying only to the
  single following day and needing to be re-earned. Each room's own
  `effect_text` says so plainly -- "**Tomorrow**, you will start the day with
  ..." -- and the wiki contrasts them explicitly against the Apple Orchard,
  which it singles out as genuinely permanent.

  Implementing my instruction literally would have made one Sauna visit worth
  +20 steps on every remaining day of a 200-day attempt.

  So the sim now has **two distinct cross-day shapes**, and picking the wrong
  one is a silent balance error rather than a crash:

  - **One-day pulse** -- a replace-per-day carry, the shape of `chapel_tithes`
    and `foundation_cell`. Sauna, Morning Room, Freezer, Break Room.
  - **Permanent once earned** -- an OR-forever flag in
    `DayChain._CARRYOVER_KEYS`. `orchard_unlocked`, `west_gate_unlatched`,
    `sealed_entrance_broken`, and now the Gemstone Cavern.

  **The Gemstone Cavern is permanent: +2 gems per day, beginning the day after
  it is first reached** (owner, from play). It is an area node, not a room --
  `gemstone_cavern` in `areas.json`, whose own name already records the mechanic
  ("Gemstone Cavern (2 gems/day - torch on ENTRY)") -- and it is
  `modelled: false`, so nothing has ever offered it as a destination. Its only
  approach, `campsite -> gemstone_cavern`, is gated on `vac_puzzle_lever`, a
  `kind: puzzle` gate that passes under the assumed-solved doctrine, and
  `campsite` became a modelled destination in PR #84. So the Cavern is reachable
  today and simply invisible.

  This is the exact shape of `orchard_unlocked`: flag set on first arrival in
  `Game.travel_to`, carried by `DayChain`, consulted in `Game.reset()`. It also
  satisfies the 2026-08-04 rule that a node only goes `modelled: true` when it
  "holds something worth walking to" -- a permanent per-day gem income
  qualifies, the same way the Orchard's step bonus did.

  Act on this cold as: **"tomorrow" in an effect text means exactly one
  tomorrow.** Before modelling any cross-day bonus, establish which of the two
  shapes it is; the wiki's Tomorrow Rooms category is the discriminator, and the
  Orchard and the Cavern are the known exceptions.

- **2026-08-10, room behaviour moves to a room-id-keyed registry in Python; NOT
  to a class per room.** Owner asked for research on giving every room a class
  derived from the JSON, with `when_drawn` / `when_drafted` / `when_entered` /
  `when_room_drafted` hooks over a base class, on the premise that "we have
  moved past the point where we can represent functionality in data files".
  Owner explicitly invited a negative answer. The memo accepts the diagnosis and
  rejects the prescription; owner ruled to execute it.

  **The diagnosis holds, measurably.** 56 distinct room ids are hardcoded across
  20 Python files; 18 rooms have their behaviour split across data AND Python;
  16 base-pool rooms have an effect text, no data behaviour, and their whole
  implementation in Python. And **13 of the 22 effect tags are used by exactly
  one room**, most named after that room -- `solarium_weights`, `study_redraws`,
  `coins_per_deadend`, `pay_gems_with_steps`. The codebase had already converged
  on per-room handlers; it just keyed them by a tag string that is a synonym for
  the room and routed the call through a JSON file to get there.

  **The inheritance argument -- the part that looks most obviously right -- is
  refuted by the data.** Of the 56 upgrade variants that have both a parent and
  an `effect_text`, **zero** share their parent's text. Of the six variants that
  model nothing while their parent models something, inheritance would be correct
  for exactly one; `empty_closet__ix41`'s text is literally "0 items" and would
  have silently inherited the Closet's two. PR #90's bug was **unauthored
  records**, and inheritance would have hidden it behind plausible numbers
  instead of exposing it as conspicuous zeros.

  **Three costs the class proposal does not account for.** Six sites read
  `room.effects` *generically* rather than executing it -- including
  `items.py::expected_yields`, which feeds both the greedy policy and the Play
  tab -- so opaque methods would need a duplicate second method surface. `Room`
  is frozen and the `Registry` is shared across episodes
  (`blueprince_env.py:132`), so room *instances* with methods invite a
  per-episode state leak that room-keyed *functions* cannot. And a base class
  would need ~14 hooks to cover the five distinct query signatures the engine
  already fires (`_in_classroom_context`, two different rotation predicates,
  drafting-from-Library, placement legality, action masking), leaving 169
  subclasses inheriting a dozen no-ops each.

  **Performance is not a factor in either direction**: `effects.fire` measured at
  **0.2%** of runtime (1,401 calls, 0.003s cumulative of 1.40s). The hot path is
  `obs.encode` at 31% and `action_mask` at 27%.

  **What ships instead**, in this order, each green at every commit:

  0. A **divergence validator** in `validate_data.py` -- flag any variant that
     models exactly its parent while its effect text differs, and any record with
     an effect text that models nothing. Emits ~112 findings today, which is a
     machine-generated task-15 worklist and strictly better than the current
     "absence of a test file" progress bar. **Ships first and stands alone**,
     independent of every other decision here.
  1. **Widen `Hook`**: `ON_DRAFT_FROM`, `ON_HAND_DEALT`, `ON_ARRIVE`,
     `ON_DAY_END`. Four members today is why the Classroom and Dovecote branches
     are hardcoded in `game.py` -- there is no hook for "drafting FROM this room"
     or "this room is in the current hand".
  2. A **room-id-keyed handler registry** alongside the existing tag registry,
     with per-handler opt-in inheritance (`inherit=True`) rather than a blanket
     loader rule, so the Boudoir's fixture safe inherits and the Closet's items
     do not.
  3. Migrate the **13 singleton tags** to room modules under
     `engine/effects/rooms/`, mirroring `tests/rooms/` one-to-one.
  4. Relocate the genuine room-behaviour branches out of `game.py`/`draft.py`.
     Placement conditions, deck membership, shop stock, upgrade slots and action
     masking deliberately stay put -- those are subsystem concerns keyed by room,
     not room behaviour.
  5. Retire the behaviour half of `ingest_sheet.py`'s tables.

  **The mixed-ownership boundary is the shared/singleton split**, and drawing it
  anywhere else is the failure mode: the 9 shared parametric tags (44 of 57
  effect instances, and everything `expected_yields` introspects) stay in data. A
  tag lives in data or in code, **never both** -- leaving `effects` in
  `rooms.json` while Python handlers also exist creates exactly the second source
  of truth this is meant to remove.

  Act on this cold as: **the JSON is a cache of a Python source of truth
  already.** `EFFECT_MAP` and `EFFECT_OVERRIDE` are hand-authored Python dicts,
  `rooms.json` is their build artifact, and `test_ingest_overrides.py` exists
  solely to prove the two agree. Moving behaviour into code deletes that whole
  apparatus -- but only if the field moves out of the JSON entirely.

- **2026-08-09, the audit worklist is worked lane by lane, not to a number.**
  Owner, after being shown that the "drop the divergence audit below 70
  findings" target could not be reached from cheap work alone. Of the 34 kind-1
  findings, roughly 21 are blocked on new engine capability rather than on
  authoring: 8 need "which rooms were drafted through THIS placed Cloister", 3
  need cross-day package delivery, 2 need the spread pipeline, 2 need items that
  do not exist, and 4 need genuinely new mechanics. Only about 10 were reachable
  by data plus a room module.

  So the goal is restated as **clear everything lane A can reach**, which lands
  near 85-90 findings rather than 70. The remaining gap is lane B and is worked
  on its own merits, not to hit a number. Act on this cold as: a metric target
  set before triage will usually price in work that does not exist at that
  price.

  **Lane A** is a room whose behaviour fits existing parametric tags or a
  `room_hook` module: disjoint files, so several agents run at once.
  **Lane B** is anything needing a new shared primitive, a new action, a new
  item, or cross-day machinery: it touches shared files and runs serially.
  **Lane C** is anything needing an owner ruling: parked and batched.

- **2026-08-09, lane B work is queued without waiting for per-PR approval.**
  Owner: "You can queue up all the changes on Lane B assuming I approve the
  merges because I generally make very few changes to your PRs."

  So a lane-B PR is built, reviewed by the orchestrator, and merged once all
  three gates are green, rather than blocking on an LGTM. Dependent work stacks
  on the branch immediately rather than waiting.

  **Three things this does NOT relax**, because none of them is about approval
  speed:

  - Anything needing a **ruling** is still parked and batched, never guessed.
    The owner's involvement is being spent on decisions, not on merges.
  - Every diff is still **reviewed by the orchestrator before merge**. That
    review has caught something in most rounds -- a test that pinned a bug as
    correct, a glyph read off the mojibake, a private-global import across a
    module boundary.
  - The **gates still bind**: tests, ruff, and validate_data at 0 errors and 0
    warnings, on every commit.

- **2026-08-09, allowance is a permanent accumulating total, and most of its
  sources are one-time.** Owner, prioritising it as the next lane-B item after
  noticing the Cloister's free token: "Most allowance tokens can only be
  collected once. Once collected, you cannot get another +2 boost from them
  again. The total accumulated allowance becomes your starting money the next
  day, so three +2 allowance tokens over seven days would result in 6 coins to
  start the eighth day."

  The wiki agrees: *"A set amount of gold granted at the beginning of each
  day"*, and *"As a permanent resource, allowance does not reset between each
  day and is generally never spent."* No base value and no cap are stated, so
  base 0 and no ceiling -- neither is invented. The packet appears in the
  Entrance Hall each morning; the sim starts the player there and assumes
  puzzles are solved, so granting it at `reset()` is the modelling
  simplification.

  **This settles task 10's open question** -- allowance is the daily gold
  packet, not a one-time grant -- and it makes the shape `orchard_unlocked`
  with an integer instead of a bool.

  **One-time sources need collection tracking, which uniqueness does not
  provide.** A unique item is only blocked while *held*; `remove(consumed=True)`
  records it in per-day state, so the source re-mints the next day. That exact
  bug was measured at 7 duplicate disks per day before `collected_disks` was
  added, so one-time allowance sources ride that same carried-set shape.

  Sourced from `https://blueprince.wiki.gg/wiki/Allowance`:

  - **One-time**: the Cloister (*"always present in the room until it is
    collected"*), Mora Jai boxes (*"do not respawn once solved"*), the
    Reservoir and Vault boxes (*"spawn only when their respective box are first
    unlocked and never again"*), the Entrance Hall vase.
  - **Repeatable**: Trading Post tier-5 trades, Jack Hammer digging, Room 8,
    the Quest Bedroom (owner: once per day maximum), Cloister of Lydia, Casino
    roulette (2 and 4 allowance prizes), the Guess Bedroom, the Laundry Room's
    Star/Allowance swap, and an "Experimental effect" worth +1.

  **Task 10 named the right three rooms; the mechanism is a Mora Jai box.** An
  earlier reading of this ruling claimed the Trading Post had no allowance
  source and that the Closed Exhibit was unsupported, because neither appears on
  the Allowance page. Both are wrong -- owner, from play: the Trading Post "has
  a Mora Jai box containing a +2 allowance token that can be opened exactly
  once", and the Closed Exhibit "has a Mora Jai box with a +2 allowance token".
  What the task got wrong was only the shape: it is a **one-time box**, not a
  standing per-day +2. The same is true of the Cloister's.

  **Mora Jai boxes are the general one-time allowance source.** From
  `https://blueprince.wiki.gg/wiki/Mora_Jai_Box`, ten standard locations, every
  one of which exists in our data:

  - **Master Bedroom** -- "one Allowance Token when completed"
  - **Solarium** -- allowance token
  - **Trading Post** -- owner-confirmed +2
  - **Closed Exhibit** -- owner-confirmed +2
  - **Tomb**, **Lost & Found**, **Tunnel**, **Throne Room** -- contents not stated
  - **Underpass** -- area node, contents not stated
  - **Inner Sanctum** -- area node, **8 boxes**, contents not stated

  Each is one-time: the Allowance page says Mora Jai boxes "do not respawn once
  solved". The endgame sets are explicitly excluded -- Aries Court's 8 boxes and
  Rough Draft's 46 contain "a note instead of an Allowance Token" and are not
  permanently opened.

  **Only the four confirmed boxes are implemented.** The six whose contents the
  wiki does not state are NOT assumed to match: inventing four to twelve more
  +2 sources on a pattern guess would move the economy invisibly. The Inner
  Sanctum matters most there -- eight boxes would be +16 from one area.

  Note `underpass` and `inner_sanctum` are area nodes, so `guaranteed_in` on a
  room record cannot reach them; the Abandoned Mine's disk uses
  `special_items.py::on_area_arrival` for exactly this case.

  Two things to check rather than carry forward: the wiki lists Vault box **53**
  alongside 149 and 233, which our data may not have; and the Entrance Hall vase
  is already modelled as a carry-over flag (`entrance_vase_broken`) that may not
  grant a token.

  Act on this cold as: **"the player gets a free X in room Y" needs its
  repeatability established before its magnitude.** A one-time pickup modelled
  as a standing bonus pays out forever, and nothing in a per-day test would show
  it.

- **2026-08-09, the Inner Sanctum's eight chambers are modelled separately, one
  per realm.** Owner: the Sanctum has "eight doors, each of which can be
  permanently opened by a Sanctum Key", and each Sanctum Key room needs its own
  model. `areas.json` currently collapses all eight into a single
  `sigil_chambers` node, whose own note already records the payoff: *"Each
  opened by 1 Sanctum Key (consumed), stays permanently open, grants +2
  allowance from its Mora Jai box."*

  The eight realms, from `https://blueprince.wiki.gg/wiki/Inner_Sanctum`:
  **Arch Aries**, **Corarica**, **Eraja**, **Fenn Aries**, **Mora Jai**,
  **Nuance**, **Orinda Aries**, **Verra**.

  Mechanics, verbatim from the same page and from
  `https://blueprince.wiki.gg/wiki/Sanctum_Key`:

  - *"Bringing a Sanctum Key here allows using it on one of the doors to
    permanently unlock that door."* *"The Sanctum Key is then consumed and
    cannot be used to open another door."*
  - *"There are a total of eight Sanctum Keys in the game."* Our data already
    carries exactly eight sources -- six `spawn_rooms` (`room_46`, `vault`,
    `clock_tower`, `throne_room`, `mechanarium`, `music_room`) plus two
    `absent_spawn_areas` (`reservoir_north`, `safehouse`).
  - *"Once used, the Sanctum Key is lost (and no longer spawns in the location
    it was obtained)."* Unused keys *"generally reappear in the same location on
    subsequent days"* unless stored in the Coat Check or retained by the Moon
    Pendant.
  - Each chamber holds a mechanism and a sigil puzzle; solving it reveals the
    rest of the chamber, which contains **a Mora Jai Box**. Under the
    assumed-solved doctrine that is a one-time +2 allowance per chamber, so
    **+16 across all eight**.

  **Open discrepancy, surfaced rather than resolved.** Owner: "The Sanctum Keys
  can only spawn after Room 46 has been reached for the first time." The wiki
  states that condition explicitly for **only one** key -- *"This Sanctum Key
  only spawns once Room 46 has been reached at least once"* -- and for the rest
  says merely that they are *"usually discovered around the same time Room 46
  has been reached for the first time."* The owner's rule is the stronger claim.
  Owner play outranks the wiki, but this one is worth re-checking in game before
  it is coded, because of the consequence below.

  **The consequence makes that gate load-bearing.** `P(room 46)` is currently
  **0.000** over 400 measured days. If all eight keys gate on having reached
  Room 46, the entire Inner Sanctum -- eight doors, eight Mora Jai boxes, +16
  allowance -- is unreachable content in every simulated day, and modelling it
  would produce a subsystem no policy can ever enter. If instead only one key
  carries that gate, seven remain collectable and the Sanctum is reachable
  before the win condition is.

  The owner also notes the first discoverable key sits in Room 46 alongside the
  Crown of the Blue Prince; the wiki adds that it *"can only be collected the
  second time the room is visited."*

  Act on this cold as: **check what a gate makes unreachable before implementing
  it.** A faithfully modelled subsystem behind a condition the sim never
  satisfies is indistinguishable, in every measurement, from not modelling it at
  all.

## 5. Throttle the training terminal output — DONE

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

Implemented as `--dashboard-every FRACTION` (default 0.05 = one line in 20; 0
disables the per-episode lines entirely). The per-episode chain note was the only
high-frequency terminal output — every other emit is lifecycle (checkpoint, stop
signal, resume banner, final summary) and stays unthrottled, and
`dashboard.deactivate()` still renders a true final frame.

Not yet measured: the throughput win is assumed, not quantified. Worth a timed
before/after on a real run.

## 6. Remove "puzzle only" items

Some items exist solely to open one specific thing and are consumed doing it. They
cost an inventory slot, a spawn roll, trade-tier membership and often an action id,
and return nothing an agent can reason about — the sim already assumes the player
solves the puzzle of any room they enter, so the *reward* can simply arrive on
entry. The Wind-up Key was removed on exactly this reasoning (design doc
simplification #17); apply the same test to the rest of the catalogue.

Candidates to audit: `diary_key` (opens the Sleep Diary only), `key_of_aries`
(opens the Treasure Trove box only), `file_cabinet_key` (one drawer each),
`basement_key`, `mora_jai`-adjacent records if any. For each: does holding it ever
present the agent with a *choice*? If not, delete the item and grant its payoff
directly.

**Audited and ruled 2026-08-06 — see the decisions log.** Outcome: **`diary_key`
removed; everything else kept or deferred.** `file_cabinet_key` KEEP,
`basement_key` KEEP, `sanctum_key` and `key_of_aries` DEFER. Two findings that
changed the task's premise: the removal candidates were already
`implemented: false` with zero Python references, so this frees an observation
dimension and a spawn slot — **not** the action id and inventory slot the task
assumed; and there is no `mora_jai` record at all, the item standing in for
"opens a Mora Jai box" is `sanctum_key`. The calibration example for the
decisive test is `basement_key`: holding it is the literal difference between
`reservoir_south` and the far side of the Basement being reachable or not.

## 7. Ignition candles in the Abandoned Mine

Blocked on task 4 (outside-area movement graph). Eight candlesticks stand in the
Abandoned Mine's circular room; lighting them all with an ignition tool (Torch or
Burning Glass) permanently sinks the floor into a stairway down to **the
Precipice**. So it is a graph edge, not just a reward — add it when the area graph
lands, as a permanent `abandoned_mine -> precipice` edge.

The Mine is also what connects the Reservoir's north and south halves, which is
the likely source of the earlier belief that the candles linked the Reservoir to
the Precipice. They do not: the Reservoir reaches the Precipice only by walking
through the Mine.

## 8. Model the Casino games

The Casino is a room of gambling minigames (slot machine, roulette). Two pieces:
1. **Expected value** for the reward function, so a policy can price entering.
2. **Outcome simulation** so those rewards actualize — seeded rolls, per-game odds
   in data.

Ties into the Broken Lever (its golden slot machine gives 5 bonus spins instead of
3) and the Allowance Token (roulette is a repeatable source).

## 9. The Antechamber needs a lever, not just a door

Landing this is the validation test for the Upgrade Disk work: Cloister of
Orinda opens a random Antechamber door, which is worthless while the Antechamber
has no locks, so Orinda's measured value should rise once this lands. How to
measure that — and why the comparison needs control upgrades and a fixed
instrument — is in
[`upgrade-value-measurement.md`](upgrade-value-measurement.md). Take the
pre-lock baseline **before** starting this task.

**Current model is wrong in an important way**: the run is resolved by walking into
the Antechamber, but in the real game its doors must first be opened by a lever
found in the **Secret Garden**, **Great Hall**, **Greenhouse** (with a Broken
Lever), or **Weight Room** (after breaking the wall with a Power Hammer). The
Greenhouse case is already modeled (PR #28) as opening the Antechamber's south
segment; the other three are not, and neither is the requirement itself.

This changes the shape of a winning run and therefore the reward landscape — treat
it as a design pass, not a patch. The north Antechamber door is a separate matter:
it opens only from the Throne Room and the Sanctum lever.

## 10. Allowance for assumed-solved puzzles

Because the sim assumes the player solves every puzzle in a room they enter,
several rooms should carry a standing **+2 allowance**: the **Cloister**, the
**Trading Post**, and the **Closed Exhibit**. Verify against the wiki whether this
is allowance (the daily gold packet) or a one-time grant, then encode it the same
way task 3's safes are.

## 11. Model the Pump Room's water levels

Write-up only (owner decision, 2026-08-04: gate the Basement doors on the
Basement Key now, take on the Pump Room next) — not built in this pass. Two
graph edges already carry stub gates waiting on this
(`pump_water_lte8`, `rowboat_water_6`, both `retire_in: "PR-pump-room"`), and a
third traversal condition (below) is not modelled at all yet.

**The room.** Six water sources, each with its own independent integer level
— there is no single estate-wide "water level":

| Source | Initial / max level |
|---|---|
| Fountain | 12 / 12 |
| Reservoir | 14 / 14 |
| Aquarium | 6 / 6 |
| Kitchen | 0 / 3 |
| Greenhouse | 1 / 5 |
| Pool | 8 / 9 |

Two tanks (capacity 4 each) and four pumps move water between a tank and any
one of the six sources: *"Switching a pump up causes water to drain from a
selected water source into a tank. Switching a pump down causes water to fill
a selected water source from a tank."*

**Persistence rule.** *"Changes to the water levels are permanent, although
the selected source and position of the pump levers will reset each day."*
So: the six integer levels need to live in carry-over state (permanent, like
`collected_disks`), while which source each pump currently targets and each
lever's position are ordinary per-day `GameState` (reset every `reset()`,
never carried).

**Gates this retires:**
- `pump_water_lte8` (`grounds -> well`): Fountain level `<= 8`.
- `rowboat_water_6` (`reservoir_south <-> safehouse`): Reservoir level
  `== 6`.
- `reservoir_water_13` (`reservoir_north <-> reservoir_south`): Reservoir level
  `== 13` lets the boat cross the Reservoir side-to-side. **The edge and gate now
  exist** (2026-08-06) — this entry used to say the crossing was "not represented
  as a graph edge/gate at all". Distinct from the Safehouse rowboat gate.

  **Unlike every other gate in this list it defaults CLOSED**, so retiring it
  *opens* a route rather than tightening one. That is the reverse of the usual
  stub-retirement direction and it must be re-measured, not assumed safe: an open
  crossing puts the `safehouse` (a Sanctum Key source) 6 key-free hops from the
  house. See `docs/areas.md` for the measurement and the reasoning.

**New traversal condition to add**, not currently modelled even as a stub:
`well -> reservoir_south` needs Fountain level `== 0`, checked on **every**
traversal (not just once) — *"this passage is only traversible while the
fountain water level is 0"* (Well). This is on top of the existing permanent
Basement Key unlock (`basement_key_well`); the two are independent conditions
(key unlocks the door permanently, water level gates whether the passage is
currently passable). See `areas.md` for the full edge-table writeup.

**Action-space consequence.** Setting pump target/direction is a player
action with no equivalent today — this is not a pure data/gate change like
the other stub retirements in this file, it adds to the action space and
therefore **belongs bundled with a retrain**, the same reasoning that governed
task 4's sequencing.

## 12. The Greenhouse's Power Hammer wall changes its layout

Write-up only — not built in this pass.

**The Greenhouse is the only room whose doors change when a Power Hammer wall
comes down** (owner, 2026-08-04). Quoting
`https://blueprince.wiki.gg/wiki/Greenhouse`:

- *"The Greenhouse, while initially a Dead End, has a hidden passage which
  includes an extra exit door. This hidden section can be permanently opened
  by using the Power Hammer on the brick wall to the left after entering."*
- *"After the wall is removed, the floorplan is updated to reveal the new
  door and the room permanently changes to an L-shape room."*
- *"if the wall was opened on a previous day, it no longer counts towards the
  total number of Dead Ends in the house."*

The sim already carries the destination shape: the `greenhouse` record in
`rooms.json` is `layout: "dead_end"` with `alt_layouts: ["corner"]`. What is
missing is anything that switches between them.

**The Weight Room is NOT this mechanism, and must not be folded into it.** Its
Power Hammer wall reveals *"a lever for the south Antechamber door as well as
two documents"* (`https://blueprince.wiki.gg/wiki/Weight_Room`), and the space
*"will always be accessible on future days"*. The room's own doors are
unchanged — it has no `alt_layouts` entry, and the wiki says nothing about its
shape. `Game._enter_lever_room` already models it correctly, as a permanent
lever unlock (`weight_room_wall_broken`) that opens the Antechamber's south
segment. Nothing about the Weight Room needs to change.

**Why the Greenhouse is harder than a doorway flip:**

- **Layout, not just doors.** A room's shape comes from an immutable `Room`
  record (`model.Registry.load()`) and is consumed by `legal_orientations` at
  draft/placement time. Nothing lets a room already on the grid swap its shape
  record mid-run, and nothing carries such a swap across the day boundary the
  way `foundation_cell` carries a placement.
- **Two distinct cases.** Breaking the wall today mutates a room already
  standing on the grid; on every later day the Greenhouse must instead be
  *drafted and placed* in its `corner` layout from the start. The second case
  is the easy one — it is a carry-over flag consulted at deck/placement time.
  The first needs live mutation of a placed room.
- **Dead End counting.** The Greenhouse starts as a Dead End and stops being
  one once broken, for the rest of the attempt. That count feeds the Tomb's
  `coins_per_deadend` effect (`effects/tier1.py`, which reads
  `ctx_room.layout == "dead_end"` at draft time) and the `dead_end`
  day-termination path (`game.py`). A layout change that does not also move
  the Dead End count would leave the Tomb paying out for a room that is no
  longer a Dead End.
- **Retroactive across days.** A wall broken on an earlier day stays broken
  and stays un-counted, so this needs the authoritative-once-set carry-over
  shape of `foundation_cell`, not a same-day flag like `garage_door_breaker`.

**Suggested shape for a future PR:** a `greenhouse_wall_broken` carry-over
flag, set when the player breaks the wall with a Power Hammer; consulted at
placement/legality time to substitute the `corner` layout for `dead_end`; plus
the matching correction to Dead End counting so the Tomb effect and the
termination path both stop seeing it as a Dead End.

## 13. Bound the Observatory's in-memory replay index — DONE

`web/server.py`'s `Observatory._records` was a `dict[episode -> full replay
record]`, ingested from `replays.jsonl` and never bounded. Measured against a
real run (`runs/foundation-v2/replays.jsonl`, 7,940 episodes, 4.68 MB on disk):
**3,089 bytes per episode — 5.24x the on-disk size**, i.e. ~31 GB at 10M
episodes. RAM, not disk, was the blocker on raising `--record-sample-rate`
toward 1.0.

Replaced with a two-part index, per owner decision (interview, 2026-08-05):

- **Offset index.** A `_RunMeta` NamedTuple holds the record's `(offset,
  length)` in `replays.jsonl` plus only the metadata `runs_index()` returns;
  `run_frames()` seeks and parses the single line on demand. The bulk — the
  `actions` list and `modes` string — is no longer resident. `reason` and
  `saved_at` are `sys.intern`ed, which is a large part of the win because
  timestamps and reasons repeat heavily across episodes.
- **Hard cap.** Ordinary records live in an `OrderedDict` capped at
  `--max-runs` (default 20000), evicted oldest-ingested-first; best-of-window
  (`why: "top_window"`) records are held in a separate dict and never evicted.

**Residual, stated rather than glossed:** the top-record dict is NOT capped. It
grows at one record per `--record-top-every` episodes (trainer default 1000),
so ~10k entries / a few MB at 10M episodes. `--record-top-every 1` would defeat
the cap.

**Known and deliberately not fixed here:** `/api/runs` returns one row per
retained episode with no pagination, and `refreshRuns()` in `app.js` builds the
whole list into `innerHTML`. The cap bounds that payload as a side effect, but
if `--max-runs` is raised far above the default the browser becomes the next
limit, not the server.

## 14. Category biases that nothing ever activates

Found while auditing the Cloister boosts (2026-08-05). `data/priority_draws.json`
declares **22 `category_biases` entries; only 8 can ever fire.**
`draft.py::_active_conditions` emits exactly three condition families —
`furnace_or_king` (from `state.furnace_placed`), `greenhouse_or_king` (from
`state.greenhouse_placed`), and `scepter_<color>` (from
`state.shops.scepter_color`). Verified by grep over all of `src/`: no other code
path produces any of the remaining tags.

The **14 inert entries**, spanning **9 distinct condition names**:

| Condition | Entries | Biases toward |
|---|---|---|
| `king` | 5 | blueprint, hallway, bedroom, shop, blackprint categories |
| `southern_cross_constellation` | 1 | `layout: cross`, 40% |
| `draxus_constellation` | 1 | `layout: dead_end`, 30% |
| `drafting_from_library` | 2 | the Bookshop (50%) and `rarity: rare` (100%) |
| `schoolhouse` | 1 | the Classroom, 35% |
| `electromagnet` | 1 | mechanical/rotunda, 40% |
| `chronograph` | 1 | tomorrow rooms, 40% |
| `adjacent_duct` | 1 | `flag: powered`, 40% |
| `adjacent_powered` | 1 | `flag: duct`, 40% |

**Owner decision (interview, 2026-08-05): fold the whole set into the Southern
Cross work** — build the activation plumbing once and light up every condition
that has a modelled source, leaving the rest documented as still-unsourced.

**Why Southern Cross is the one that matters for the upgrade study.** The two
Cloister boosts that already work bias by **category** (`green`); Southern Cross
biases by **layout** (`cross`). Every Cloister variant is `layout: cross`, but
`cloister_of_orinda__ix35` is `category: blackprint` and
`cloister_of_draxus__ix36` is `category: red` — so the two working boosts stop
applying to exactly the two variants the Orinda measurement cares about.
Southern Cross is the only one that does not.

**Research needed before any code**: what activates a constellation in the real
game (Observatory / Telescope?), whether it is per-day or permanent, and whether
`king` is the Banner of the King (`scepter_*` already cites the Royal Scepter as
having "the same effect as Banner of the King", which suggests the `king` tag and
the scepter tags may be the same mechanism entered from two directions). Do not
infer any of this from the existing table.

### Status after PR #60 and 2026-08-06 — the table above is stale

`_active_conditions` now also emits `schoolhouse`, `southern_cross_constellation`,
`draxus_constellation` and `drafting_from_library`, so most of the 14 are wired.
What actually remains:

- **`drafting_from_library` — DONE, and it was the wrong mechanism.** The Library
  does not bias a re-deal; it **replaces the rarity table outright** (Commonplace
  0%, Standard 0.01%, Unusual 49.99%, Rare 50%, datamined). Implemented in
  `decks.py::roll_rarity` with the table in `weights.json`; the inert
  `category_biases` signpost entry is deleted. The Bookshop 50% entry is separate
  and still a genuine category bias.
- **`schoolhouse` — the last small one.** `state.schoolhouse_placed` is read by
  `_active_conditions` but **nothing ever sets it**. It needs one `Hook.ON_PLACE`
  effect tag mirroring `greenhouse_bias`/`furnace_bias` in `effects/tier1.py`.
  The Schoolhouse record already has a working `inject_pool` ON_PLACE effect, so
  this is a second tag on an existing list. 35% Classroom bias is datamined.

  **Completeness gap worth flagging separately**: the wiki says the Schoolhouse
  also boosts the Library and Studio Addition: Dormitory, but our data encodes
  only the Classroom entry. That is a missing-entries problem, not a wrong
  magnitude — do not invent the other two percentages.
- **Still genuinely unsourced** (no modelled activation source): the five `king_*`
  tags, `electromagnet`, `chronograph`, `adjacent_duct`, `adjacent_powered`, and
  the two constellations' activation chains.
