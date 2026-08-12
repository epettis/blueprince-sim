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

Opened 2026-08-09, from the PR #89 review. Runs independently of task 15: the
collision a comment-only pass creates with in-flight room PRs is a merge cost,
not a correctness one. See the 2026-08-11 scope ruling in the decisions log for
the four category calls and the measured sizes.

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

**Correction, 2026-08-11 (PR 1 of the sweep).** Two of the three instances
named above do not exist, and were verified line by line:

- **`KNOWN_GUARANTEED_ITEM_KINDS` carries no dated citation.** That comment is
  a clean present-tense description of item kinds. The only `2026-08-09`
  reference in `tools/validate_data.py` is the separate exact-coins paragraph
  in the guaranteed-items loop -- which *is* a genuine violation, and was
  fixed. The two were conflated when this task was written.
- **`items.py::grant_item`'s docstring is entirely present-tense.** Its
  "instead of" phrasing contrasts two currently-valid options, which the sweep's
  own carve-out classifies as a keep. It narrates no history, cites no date and
  no bug. **Left untouched.** If it wants a length trim, that is a different
  edit than this task authorises.

Only the third (`tests/rooms/test_vault.py`) survived scrutiny; it is PR 2's.
Recorded rather than silently deleted, because a task statement that names
non-existent work is the same failure this task exists to fix.

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

**Done.** CLAUDE.md no longer says "prefer changing behavior by editing data
over editing code" -- it carries the three-way guidance instead: tabular facts
in data, shared parametric tags in data, singleton behaviour in a room module.

## 18. Divergence worklist triage (2026-08-10) -- DONE

**The worklist is empty: 80 findings at its peak, 0 as of PR #195.** Every
one was either built, exempted through a guarded channel, or deferred with a
stated reason and its own liveness check. The audit is not merely quiet --
injecting an unmodelled effect into a non-exempt room still flags it.

The five exemption channels each carry a guard now, the data one having been
the last without: `_assert_data_exemptions_live` fails if a room stops
carrying the field its entry names, or if that field goes empty, which is
the likelier way such an entry rots.

All 62 findings were triaged in one pass. Three classes:

- **False positives** -- behaviour modelled in a channel the audit cannot see
  (`shops.py`, `special_items.py`, `locks.json`, `game.py`, a data flag). PR
  #138 cleared ten of these (the commerce rooms). Remaining candidates:
  `dovecote` (whose own effect_text names the engine functions that implement
  it), `chamber_of_mirrors`, `coat_check`, `utility_closet`, `the_foundation`,
  `lost_and_found`, `break_room__ix11`, `dining_room`, `lavatory`, plus the two
  already-known ones (`courtyard__ix49`, `electric_eel_aquarium__ix4`).
- **Stale annotations** -- see the ruling below.
- **Real gaps**, roughly 26, most of them cheap.

### Decisions log

- **2026-08-10, expired scope annotations are re-opened as real work.** Nine
  `meta.effect_text` values are not game text at all -- they are annotations
  this project wrote, and several have expired:

  | record | claims | why it is false now |
  |---|---|---|
  | `clock_tower` | "out of single-day scope" | multi-day has been in scope since `DayChain` |
  | `shrine` | "out of single-day scope" | same |
  | `the_kennel` | "lock system out of scope" | `locks.py` models locked doors |
  | `vestibule` | "on enter, 3 doors unlock and the 4th locks (lock system out of scope)" | same |
  | `lost_and_found` | "no effect modeled" | the steal/gift behaviour IS modelled (`special_items.py`), per CLAUDE.md |

  Owner decision, on interview: **implement them, and rewrite each annotation to
  say what is actually true.** This is the "a scope annotation is a claim with
  an expiry date" lesson firing for the second time -- the first cost seven
  rooms suppressed long after the sim grew multi-day support.

  Act on this cold as: an annotation asserting something is out of scope must
  be re-checked whenever that scope changes, because nothing else will
  invalidate it. Prefer a dated task entry in this file over a scope claim
  buried in a data record.

- **2026-08-10, `parlor__ix109` stays unmodelled, and the reason is recorded.**
  Its entire payload is "2 Wind-up Keys", and the Wind-up Key item was
  deliberately **removed** from the sim (design doc simplification #17:
  puzzle-only items are deleted and their payoff granted directly). So the
  variant references a concept that no longer exists.

  Owner decision, on interview: leave it inert rather than re-add the item or
  invent a substitute payoff. Act on this cold as: this is a **deliberate**
  permanent finding on the worklist, not an oversight -- do not "fix" it by
  reintroducing the Wind-up Key.

- **2026-08-10, the Aquarium counts as every colour via a data flag.** All three
  Aquarium records say "AQUARIUM is every color of room." `Room.category` is a
  single string, and category drives category biases, `grant_per_category`, the
  Cloister/Terrace green boosts and scepter colours.

  Owner decision, on interview: add a **`counts_as_all_colors`** flag honoured
  at each category-comparison site, rather than widening `category` itself or
  applying the rule only where convenient. One flag, consistent everywhere.

- **2026-08-10, the Cloister of Dauja and Veia need sourced room lists first.**
  Dauja pays "for each room with an animal", Veia gives dirt piles "in each room
  with a fireplace". Neither an animal nor a fireplace concept exists in
  `rooms.json`. Owner decision: research the wiki, then encode the result as
  data flags -- and **if the wiki does not publish the lists, come back rather
  than guessing which rooms qualify.**

- **2026-08-10, `guess_bedroom__ix70` gets a research pass, then an owner call
  if it is unsourced.** Its datamined text is "Hidden effect of a random BEDROOM
  in your draft pool?" -- with a literal question mark, so the datamine itself
  is unsure. Owner decision: research it; if the wiki is as vague as the
  datamine, leave it unmodelled and record the gap rather than invent a
  mechanic.

- **2026-08-10, the Laboratory is the big subsystem to take on.** Of the four
  large unmodelled subsystems on the worklist -- Throne Room (the "reclaim the
  crown" objective), Closed Exhibit (security-lock puzzle), Mechanarium (dynamic
  door count per Mechanical room) and Laboratory ("Experimental House Features")
  -- the owner chose the **Laboratory**. It gates several other mechanics
  already met elsewhere in this file: the Satellite Dish Pantry restock, the
  experimental dig-spot spread to the Grounds, and the apple-eating trigger.

  The other three stay unstarted; each needs its scope written up before it is
  picked, not during.

- **2026-08-10, work the cheap findings breadth-first.** Owner decision for an
  unattended day: clear the many small findings in batched PRs rather than
  going deep on one subsystem. Maximum findings cleared per unit of risk, and
  each PR stays reviewable.

## 19. Laboratory / Experiments -- scoping (2026-08-10) -- PHASES 0-4 DONE

**All twelve base triggers and all twelve base effects are live** (PRs
#162-#178, #182, #184-#187, #193). The Laboratory is playable: a setup
terminal with its own masking site, exposed in the Play tab.

Phases 5-8 (the Satellite Dish, the packet download flow, Packet Management
and the eight packet triggers/effects) remain **explicitly unauthorised**.
The packet pool's data is transcribed; its behaviour is not.

Owner picked the Laboratory as the big subsystem. Full scoping done; the
headline finding is that **it is not one subsystem.**

An experiment pairs an **experimental trigger** with an **experimental
effect**, set up at the Laboratory terminal: three of each are drawn uniformly
and the player picks one from each column. One experiment at a time, lasting
the day, pausable. Twelve triggers and twelve effects at base; the Satellite
Dish data packet permanently adds eight more of each.

**Phases 0-4 are the real subsystem** (~4-5 days) and deliver a playable,
trainable Laboratory: the data file, the core (offer/choose/start/pause/fire),
the eight pure-resource effects, the draft-site triggers, the interaction
triggers, and the persistence/availability layer. Phase 3 is what the
apple-eating trigger elsewhere in this file is waiting on.

**Phases 5-8 are four separate subsystems wearing an experiment costume** --
"model the Grounds' dig spots", "model Pantry stock", "model Dynamic Rarity",
"model the Satellite Dish unlock chain". Each is more honest as its own line
item. **Recommendation, awaiting the owner: commit to 0-4 as the Laboratory
work and re-scope 5-8 individually.**

Costs: action space **319 -> 327** plus a new `Phase.EXPERIMENT_PENDING`;
observation gains an `experiment` key, `phase` widens 4 -> 5, and `carryover`
widens 14 -> 16. That is three further width changes.

**Never model, recorded deliberately**: the 40-second real-time trigger and the
view-map trigger (meaningless in a simulator), the setup-reroll timing exploit,
Blessing of the Tinkerer cross-triggers, radiation level, Dare Mode, Research
Logs. Also **do not implement** the two rules the wiki has *commented out*
(a 30% crates-removal filter, a set-dice exclusion) -- its own editor note says
"a lot of the datamined info on experiments has been off or just straight up
wrong."

**Numbers the wiki does not give** -- flag, never invent: the key/gem/die
split; the 2/3/4 dig-spot distribution; the Antechamber-door preference
weights; the Pantry fruit mix (ordinal only); lockpicking skill magnitude; the
"gain 1 random item" pool (a live Cargo query, not in wikitext).

## 20. Research outcomes feeding the worklist (2026-08-10)

### Sourced room lists, previously thought unpublished

- **Cloister of Dauja's "rooms with an animal" -- six, enumerated**: Rumpus
  Room, Aquarium, Nursery, Bunk Room (**once only**, despite counting as two
  bedrooms elsewhere), Dovecote, The Kennel. Grants **2 stars** on draft.
  It is an **ad-hoc id list, not a room type** -- the wiki itself cannot
  explain why the Rumpus Room (a mounted fish) and Nursery (plushies) qualify
  while taxidermy rooms like the Trophy Room do not. **Do not derive membership
  from a semantic rule**; it gets both of those wrong.
- **Cloister of Veia's "rooms with a fireplace" -- seven draftable**: Parlor,
  Den, Trophy Room, Drawing Room, Furnace, The Armory, and the Dining Room
  **only when placed in the centre columns or on Rank 9** (on the wings or Rank
  1 it has windows instead). A dirt pile IS our `dig_spots`, and the grant is
  **+8 additive**, not "set to 8" -- which matters only for the Furnace, whose
  baseline is 1, so it reaches 9.

The Dining Room condition is placement-dependent, so `has_fireplace` cannot be
a static room flag for it.

### Conflicts found, unresolved

- **The trunk loot table diverges from the datamined one in two ways.** We
  carry coin totals **11, 13 and 14, which do not exist in the game**, and we
  make the key+gem+coin outcome **three times rarer** than it is (one entry at
  5% against the game's three at 1/20 each). We also do not model the wiki's
  "fall back to the option directly below" rule for already-owned items.
- **The Clock Tower's wiki page contradicts itself**: its infobox says "for
  each Tomorrow room **you draft today**", its prose says "for every Tomorrow
  room **present in the mansion**". Our own text picks neither and omits that
  the Clock Tower counts itself.
- **`spare_great_hall__ix139` has text byte-identical to `great_hall` but a
  different mechanic**: its 7th door is not necessarily locked, it has no side
  doorways, no Antechamber lever and no Upgrade Disk, and a different prize
  table. **They must not share an implementation.**
- **The Funeral Parlor's 30-step penalty applies only to the FIRST box opened**,
  not per empty box, and its gem count is read **when the box is opened**, not
  at draft. Our text implies otherwise on both counts.
- **`her_ladyships_chamber` omits a second effect entirely**: drafting it sets
  the Boudoir's and Walk-In Closet's Dynamic Rarity to Commonplace.

### Resolved, needing no owner call

- **`guess_bedroom__ix70` is fully documented** -- the trailing "?" is in-game
  flavour ("Your guess is as good as mine."), not datamine uncertainty, and
  "Guess Bedroom" is the canonical pun name beside Quest and Geist, not a typo.
  It mimics a random Bedroom in the draft pool, excluding itself, Her
  Ladyship's Chamber, the Master Bedroom and the Spare Bedroom line, and adds a
  once-per-day quiz-sheet guess for a random resource prize.
  **Deferred anyway**: it needs runtime effect and type inheritance from an
  arbitrary other room, which the engine has no mechanism for. The wiki itself
  records that the mimicry is inconsistent in-game.
- **The Aquarium is every room TYPE, not merely every colour** -- Red, Green,
  Hallway, Bedroom, Shop and Blackprint on top of its native Blueprint -- and
  it counts for **penalties as well as bonuses** (cursed, it loses 2 of every
  resource; the Dare Mode shop dare auto-fails on it).
  `electric_eel_aquarium__ix4` **additionally gains the Mechanical type**,
  which our record does not encode.
- **The Speakeasy is a genuine no-op in our model.** "Basic Addition" only
  makes the Dartboard Puzzle easier (one board, one ring, two numbers, addition
  only). We do not model the Dartboard Puzzle and we assume puzzles are solved,
  so there is nothing to implement.
- **The Vestibule's effect is rerollable for 2 steps** by leaving and
  re-entering, and the wiki frames that as the intended strategy. Worth
  watching as a farming incentive once it lands.

### Open question for the owner

- **Cloister of Joya's "permanent" Main Course bonus**: +5 steps to all five
  main courses, cumulative and uncapped, surviving a change of the Cloister's
  upgrade. The wiki never says whether "permanent" means the attempt or the
  whole save. Defaulting to **per attempt**, consistent with every other
  carry-over resetting on wrap -- flagged for confirmation rather than assumed
  silently.

## 21. Capability architecture: the engine provides, rooms declare

Opened 2026-08-10 on an owner ruling (see the decisions log entry of the same
date). **Started; the invariant is now measured rather than estimated.**

`tests/test_room_id_allowlist.py` (PR #188) AST-scans `engine/*.py` and
`engine/effects/*.py` for string literals equal to a real room id, against a
per-module allowlist. It fails in **both** directions: a new literal in an
unlisted module, and an allowlisted id that no longer appears. The second
half is what makes it a ratchet rather than a record.

**The measured starting point below is stale and was already wrong when
written** -- the real count at the time the test landed was 55 pairs, not 45,
because `draft.py` had grown and two modules with room-id literals did not
exist when that table was made. That gap is the argument for the test.

`Capability.LEVER` (PR #189) converted the first four rooms and taught us the
shape: `COMMERCE`'s plain boolean is not enough for a capability that needs a
per-room handler and a live cost query. **Expect locks and containers to need
parameterised handlers too.**

The ratchet has twice converted "just add it to the allowlist" into a better
design -- the Electro Magnet's category union and colour drafting's default
triples both moved to data rather than growing the list.

The target is three layers:

1. **Data (JSON)** -- tabular facts only. Room stats (rarity, layout, gem cost,
   category, deck copies, draft conditions, dig spots, flags) and subsystem
   tables (`shops.json` prices and stock, `locks.json` chances, container loot,
   `mail_packages`). Generated from the datamine wherever it can be.
2. **Engine capabilities** -- mechanisms that know nothing about specific rooms:
   drafting, locks, containers, commerce, digging, food, carry-over, terminals.
3. **Room modules** -- one per room at `effects/rooms/<id>.py`, declaring which
   capabilities the room uses and with what parameters, plus anything bespoke.

**The invariant: no engine module may branch on a room id.** Everything
room-specific is a registration.

The Shop is the pattern-setter. Today `game.py` reads:

```python
if room.category == "shop" or room.id == "workshop":
    shops.on_enter_shop(self, room)
```

which is the engine knowing which rooms are shops. Under the capability model
`shops.py` keeps the mechanism and `shops.json` keeps the table, but each shop
room module *registers* commerce for itself, and the Workshop's special-case
`or room.id == "workshop"` disappears.

### Measured starting point (2026-08-10)

Room ids are hardcoded in 20 modules outside `effects/rooms/`. The behaviour
targets, worst first:

| module | room ids |
|---|---|
| `engine/game.py` | 14 |
| `engine/shops.py` | 12 |
| `engine/special_items.py` | 9 |
| `engine/draft.py` | 7 |
| `engine/decks.py`, `engine/locks.py` | 2, 1 |

**Not targets, and not debt** -- these legitimately name rooms:
`engine/upgrades.py` (15, the disk selection tables), `engine/placement.py` (6,
where the ids are fixtures and named conditions and the tags are already
room-agnostic), `env/actions.py` / `env/obs.py` / `web/play.py` /
`cli/render.py` (env and UI wiring), `config.py` / `rl/train.py` (presets).

Only **27** rooms have a discoverable `effects/rooms/<id>.py` module today.

### Enforcement

A conventions test scanning engine modules for room-id literals against an
explicit allowlist, in the same spirit as `tests/test_conventions.py`'s
docstring rule. **The allowlist starts at today's count and may only shrink.**
That is what stops the architecture rotting back, and it turns "are we done?"
into a number rather than a judgement call.

### Sequencing

Capability by capability, each PR independently green, cheapest first.
Done: commerce (the pattern-setter), containers and digging, the Antechamber
levers. **Locks need nothing** -- `locks.py` reads `locks.json` and carries no
room-id branch at all, which the allowlist confirms.

Next, largest first: `shops.py`'s stock builders (12 ids), `draft.py`'s
named-constant branches, `special_items.py`'s (10). The two day-end branches
in `game.py` (`break_room__ix11`'s keycard pulse, `clock_tower`'s tally) want
one shared `Capability.DAY_END` between them.

### What it buys

- **`_AUDIT_PYTHON_EXEMPT_IDS` disappears.** That hand-maintained id-to-module
  map, added 2026-08-10 with a staleness guard, exists only because behaviour
  hides where the audit cannot see it. With every room registering,
  `registered_rooms()` is complete and the audit credits Python automatically.
- **The "four channels" gotcha collapses to two.** `effects: []` stops being
  ambiguous: stats and shared parametric tags in data, everything bespoke in
  one module per room.
- 24 of the 62 findings triaged on 2026-08-10 were false positives caused
  precisely by this scatter.
## 22. Item behaviour: registry migration (scoping)

Opened 2026-08-11, owner directive. The question, in their words: should items
be "broken out into a registry similarly to how we broke out the rooms"? The
stated reasoning -- "the engine can keep track of the capabilities while the
registry implements those capabilities for each item and special item", and it
"would also likely make it easier for you to stop re-litigating abilities".

Note **"each item and special item"**: two distinct systems are in scope,
`engine/items.py` (the luck / room-item yield system, 201 LOC) and
`engine/special_items.py` (the ~102 inventory items, 2,465 LOC).

**Measured starting point, 2026-08-11.** String literals in `engine/*.py`
(non-recursive) matched against the 102 ids in `special_items.json`:

| | count |
|---|---|
| `(module, item_id)` pairs | **58** -- `special_items.py` 42, `shops.py` 11, `game.py` 4, `placement.py` 1 |
| `(module, effect_tag)` pairs | **36**, over **37** distinct tags (corrected 2026-08-12: the original 35/38 scanned only `engine/*.py`, missing `effects/tier1.py`, and predates #199 deleting `ignition_tool`) |
| item-logic LOC | 4,440 -- `special_items.py` 2,465, `shops.py` 1,200, `upgrades.py` 574, `items.py` 201 |

**For comparison the room-id debt is 79 pairs and is held under an enforced
ratchet (`tests/test_room_id_allowlist.py`). The item debt of 58 is 73% of that,
and has no equivalent enforcement at all** -- it was unmeasured until
this entry.

The motivating link to task 16's neighbour work: `implemented: false` in
`special_items.json` is an *asserted* fact that has repeatedly gone stale (five
false `blocked_on` strings found the same day, two of them on items the engine
already grants or reads). A per-item module would make it *derivable*. Whether
it actually does is the test the recommendation has to pass.

An architecture pass is in flight. It must take a position on the item
equivalent of task 17's central call -- that migration moved 13 singleton tags
and **deliberately left 9 shared parametric ones in data** -- and must propose
an enforcement mechanism that ratchets down rather than only growing.


**Recommendation, 2026-08-12: qualified yes, in two parts.**

**`engine/items.py` is out of scope and already right.** It has zero item-id
branches and dispatches on eight resource kinds via `match`. That is what task
21 asks an engine capability to look like; there is nothing to break out.

**`special_items.py` + the item half of `shops.py` (~3,665 LOC): migrate.**

**The finding that decides the shape: items are the mirror image of rooms.**
Task 17 moved 13 singleton tags and left 9 shared parametric ones carrying 77%
of instances. Items are **30 singletons against 7 genuinely shared tags**
(16 instances). By task 17's own rule -- singleton behaviour belongs in a
module -- **items are a stronger migration candidate than rooms ever were.**

Two refinements to that count, both load-bearing:

- **`allowance` is a false shared tag.** All 19 instances are the same
  `+2 allowance` payload on 19 differently-*sourced* tokens; the variation is
  one-shot bookkeeping, not effect. It still stays in data -- `env/obs.py` and
  `env/multiday.py` read it.
- **`ignition_tool` is dead data.** Nothing reads the tag; `_ignition_tools()`
  reads `registry.special.ignition["tools"]`, a separate list in the same file
  naming the same items. Two sources of truth, one never consulted.

**The registration primitive must NOT be a `room_hook` clone.** A room has a
natural event boundary; an item does not. Item behaviour is overwhelmingly a
**fold over the inventory** -- `move_step_cost`, `gem_cost_modifier`,
`food_steps`, `shield_negates` all ask "does any held item modify this number".
Copying the hook shape yields 40 modules registered against a constantly-firing
hook, and makes fold *order* implicit in import order where today it is visible
as sequential lines. **A bad item registry is strictly worse than the current
2,465 lines, which are at least readable top to bottom.** The shape is
`provides(item_id, Capability, **params)` -- following `Capability.LEVER` --
with the **engine owning the fold and its order** as one explicit tuple, and
the item declaring only its contribution. Genuine hooks are the minority:
`ON_PICKUP`, `ON_ENTER_ROOM`, `ON_DAY_END`.

**Scope is ~40 modules, not 102.** The four id-prefix families
(`upgrade_disk_*` 16, `sanctum_key_*` 8, `vault_key_*` 4, `allowance_token*`
19 -- 47 items) stay generic; `upgrades.py` already matches them by prefix.

**What it does and does not buy.** It makes the *flag* derivable and kills
`implemented`/`blocked_on` for `coupon_book`, `microchip` and
`trophy_of_wealth`. **It does not make the *reason* derivable** -- a blocker is
a claim about a subsystem, not about the item, so `dowsing_rod` and
`crown_of_the_blueprints` stay asserted. Roughly 60% of the observed failure.
**Phase 0 catches more of it, sooner, than the migration does**, which is why
it comes first and stands alone.

**Phases** (each independently mergeable, gates green throughout):

**Phase 1 landed early, in #199**, before the phase table was written: that PR corrected all fourteen `blocked_on` strings, added `meta.reachability`, and deleted the `ignition_tool` tag. Six phases remain, not seven.

| Phase | Content | Size | Risk |
|---|---|---|---|
| 0 | Two scanners + allowlists (`item_id`, `effect_tag`), bidirectional. **No code moves.** | S | Low | **DONE in #200** |
| 1 | Truth pass on the 14 records; delete the `ignition_tool` tag | XS | Low | **DONE in #199** |
| 2 | `ItemCapability` primitives + `effects/items/`; migrate `coupon_book` as pattern-setter | S | Low | **DONE in #203** |
| 3 | Pure-query **singleton** capabilities (8 modules) | M | Low | **DONE in #204** |
| 4 | Item handlers on game events + the engine-owned priority tuples | M | **Med** | **DONE in #205** |
| 5 | Id-branch items with no tags (~15 modules) | M | Med |
| 6 | RNG-touching migrations, **last and alone** | M | **High** |
| 7 | Shrink both allowlists; delete `implemented`/`blocked_on` | S | Low |

**No phase is a retrain trigger provided the `items` array is never reordered
and nothing is inserted mid-array.** `env/obs.py` enumerates it positionally
for the `inventory` Box -- structurally identical to `Room.idx`. `env/actions.py`
is item-count-independent (`BUY_BASE` etc. are display slots), so the action
space is unaffected.

**Two constraints the scoping brief got wrong, corrected here:**

- **`special_items.json` is hand-maintained.** `ingest_sheet.py` touches only
  `rooms.json`, so the silent-revert hazard does not apply to item data.
- **RNG risk is narrower than feared.** `rng.py` substreams are independent per
  label, so only *same-label* ordering matters. Three item-relevant labels have
  multiple draw sites: `treasure_map` (two functions, one stream -- migrate
  alone), `lost_and_found` (contained), and **`extra_item_kind`, which spans
  `game.py` and `items.py`** -- in the module this plan puts out of scope, so
  it is a hazard for anything touching `roll_extra_items`, independent of this
  work.

**There is no item-side divergence audit at all.** The five guarded exemption
channels are room-only; the entire validation of item implementation status is
a check that `blocked_on` is non-empty -- never that it is *true*. A registry
does not create a sixth exemption channel, it creates the **first** item audit.

**Enforcement floor: ~10 of 58**, better than rooms will ever reach, because
**item ids and room ids are disjoint** -- none of the `"bedroom"`-is-also-a-
category ambiguity that permanently pins ~20 of the room allowlist. Two
separate scanners are required: **13 of the 38 effect tags are spelled
identically to an item id**, so a merged scanner would double-count. The tag
scanner gets a second job: **a tag with zero readers is a hard failure, not an
allowlist entry** -- that rule alone catches `ignition_tool` today.

**Cost: ~8 PRs, ~650 LOC moved, ~500 LOC new.** `special_items.py` should land
around 1,800 LOC.

## Decisions log

- **2026-08-12, the item-id allowlist is split into architecture and debt.**
  Pulled forward from phase 7 because phase 5's whole job is to drive the debt
  number down, and a conflated number cannot show that -- a successful
  migration and a wash looked identical.

  **`ITEM_ARCHITECTURE` = 37, `ITEM_DEBT` = 27** (sum 64, no overlap).
  `ITEM_DEBT_CAP = 27` enforces the asymmetry that makes the split worth
  having: **architecture may grow, debt may not.** Phase 5 will legitimately add
  priority-tuple members as chains extend; that must not be able to hide a
  failure to migrate anything.

  Architecture is four kinds: engine-owned priority tuples (the six `ItemHook`
  chains plus `DIG_PRIORITY` and the lockpick preference), id-prefix family
  constants, named draft conditions, and trade-graph/pipeline carve-outs.

  **The debt half is now a worklist, not a score:**

  - `game.py` (4): `keycard`, `paper_crown`, `power_hammer`, `silver_key`
  - `shops.py` (7): `car_keys`, `lunch_box`, `microchip`, `repellent`,
    `royal_scepter`, `silver_key`, `stopwatch`
  - `special_items.py` (16): `battery_pack`, `broken_lever`, `car_keys`,
    `compass`, `cursed_effigy`, `key_8`, `keycard`, `lunch_box`, `moon_pendant`,
    `royal_scepter`, `secret_garden_key`, `silver_key`, `sledge_hammer`,
    `sleeping_mask`, `treasure_map`, `watering_can`

  `treasure_map` and `moon_pendant` are **phase 6** (RNG-touching, migrate
  alone). `microchip` overlaps the Microchip branch.

  **Three corrections to my own taxonomy, all from reading the call sites:**

  1. **`sledge_hammer` is debt, not architecture.** Its only occurrence is the
     Mechanarium compartment fallback, on the same line and construct as
     `battery_pack` and `broken_lever` -- which I had already classified as
     debt. The same construct must classify the same way.
  2. **`compass` is debt.** It never appears in a priority ordering; it is a
     `_has_item_effect` tag-collision lookup. I had grouped it with the
     tool-preference question by association rather than by evidence.
  3. **`shops.py`'s `secret_garden_key` is architecture.** It sits in a
     `frozenset` beside three strings that are not item ids at all -- the same
     named-condition class as `placement.py`'s own exemption.

  **And a mislabel in my mutation plan worth remembering:** removing an entry
  for a still-present literal fires the *outside-the-allowlist* test, not the
  *stale-entry* test. The genuine stale-entry direction is only exercised by
  removing the literal from the **source** while keeping the dict entry. Both
  were verified separately; a plan that conflates them would let the stale-entry
  guard pass vacuously forever.

- **2026-08-12, phase 4 landed, and it moved the item-id debt UP -- correctly.**
  Numbers: **item tag pairs 27 -> 22**, **room id pairs 79 -> 78**, but
  **item id pairs 56 -> 64**.

  The increase is the design working, not a regression. The engine-owned
  priority tuples (`GEM_COST_PRIORITY`, `MOVE_STEP_COST_PRIORITY`,
  `COINS_GRANTED_PRIORITY`, `GEM_PAYMENT_WAIVER_PRIORITY`,
  `RED_ROOM_NEGATE_PRIORITY`, `FOOD_STEPS_PIPELINE`) **have to name their member
  item ids somewhere** -- that is what an explicit total order *is*. The
  alternative, a `priority=` number on each registration, is exactly what the
  owner rejected because it scatters the order across the modules it ranks.

  **Consequence: phase 0's "irreducible floor is ~8-10 of 58" is now wrong.**
  The floor is that plus the priority-tuple members -- call it **~18-22**. More
  importantly, **the item-id allowlist no longer measures one thing.** Part of
  it is genuine debt (an engine module branching on an item id) and part is
  permanent architecture (an arbitration order naming its members). A scoreboard
  that conflates the two stops measuring anything, which is the failure its own
  bidirectional check exists to prevent. **Phase 7 should split the allowlist
  into those two sections** rather than report one number.

  Bonus result: **the room-id debt fell without anyone targeting it.**
  `"hallway"` sat in `special_items.py` only for the Hall Pass's
  `is_category("hallway")` test; moving that into `hall_pass.py` (glob-excluded)
  removed a *room*-id literal from a scanned module.

- **2026-08-12, two stale-comment findings from phase 4, both pre-existing.**

  1. **My phase 4 brief mis-attributed the "never burn a Stopwatch charge on a
     free room" guard to `gem_cost_modifier`.** That function never touches
     `stopwatch_left` at all -- its own comment says the waiver happens at PAY
     time. The real guard is `stopwatch_waives_gems`'s own `cost > 0`
     condition. The principle was right and the function was wrong; the agent
     caught it and pinned the real guard with a test.
  2. **`gem_cost_modifier`'s docstring said "Emerald Bracelet first, then Hall
     Pass, then Stopwatch"** -- and the Stopwatch was never in that chain, as
     the function's own body comment stated two lines below. A stale docstring
     contradicted by the code beside it, surviving the task 16 sweep because it
     reads as a specification rather than as history. Now corrected.

- **2026-08-12, item handlers fire on game events, exactly like room handlers.
  The claim that "items have no natural event boundary" was wrong.** Owner
  challenged it directly and the challenge holds: a payment, a move, a coin
  grant and a red-room effect are game events, and an item handler on one is as
  legitimate as a room handler on `ON_ENTER`. The claim had been repeated across
  several PRs and shaped the phase 2 and 3 designs.

  **The real difference is arity and arbitration:**

  | | room handler | item handler |
  |---|---|---|
  | fire per event | exactly one | any number of held items |
  | signature | `(game, room, context_room) -> None` | must return a value |
  | conflict | impossible | routine, and rule-bearing |
  | order | irrelevant | decides the outcome |

  `fire(game, room, hook)` is called with *the* room the event is about and
  dispatches to that one room's handler. Two rooms never answer the same event,
  so **the room registry never needed arbitration -- the grid supplies
  exclusivity for free.** Items have no such guarantee: `gem_cost_modifier`
  must produce one number from N held items, and "only one waiver applies, no
  double-decrement" is a game rule something has to enforce.

  So the conclusion is not "avoid handlers" but **"use handlers, plus the one
  thing rooms never needed: explicit arbitration."**

- **2026-08-12, the phase 4 design, three owner rulings.**

  1. **Item modules register handlers on game events.** Item hooks
     (`ON_PAY`, `ON_MOVE`, `ON_COINS_GRANTED`, `ON_RED_EFFECT`, `ON_FOOD`),
     mirroring `Hook`. This is what makes the charge-consuming effects
     migratable at all -- an item that spends a Stopwatch charge cannot declare
     a value, it has to run code.
  2. **The engine owns one explicit priority tuple per chain**, in engine code:
     e.g. `GEM_WAIVER_ORDER = (EMERALD_BRACELET, FREE_HALLWAY_MOVES, STOPWATCH)`.
     Visible, diffable, testable in one place. **Never a `priority=` number on
     the registration** -- that would scatter the total order across 40 modules
     so no single place shows what beats what.
  3. **Context predicates belong to the item.** The Hall Pass registers its own
     hallway-from-hallway test rather than the engine hard-coding it, so each
     item's rule is self-contained. Accepted cost: item modules gain some grid
     and pending-draft knowledge.

  **What phase 4 actually covers, corrected.** The architecture pass called
  these six "folds", i.e. ordered reductions. **Five of six are first-match-wins
  priority chains and four mutate state** -- `move_step_cost` consumes a
  stopwatch charge, `on_coins_granted` accumulates `coin_interest`,
  `shield_negates` sets `shield_used`, `stopwatch_waives_gems` spends a charge.
  Only `food_steps` (Salt Shaker adds, then Silver Spoon doubles) is a genuine
  ordered fold. Anyone briefing this work from the word "fold" will build the
  wrong thing.

- **2026-08-12, the recorded phase table contradicted itself, and the
  contradiction is resolved against migrating shared tags.** The architecture
  pass listed phase 3 as migrating `luck_bonus`, `compass`, `dig_tool`,
  `lockpick`, `metal_detector_spawns` and `smash`, **and separately said those
  same six must stay in data** as shared parametric tags. Both statements were
  in this file.

  **Resolved: a tag carried by more than one item stays in data; singletons
  migrate.** Two reasons, the second decisive:

  1. The rooms rationale does not transfer. Task 17 kept shared parametric
     tags in data because `items.py::expected_yields` introspects them
     generically. **Nothing introspects item effect tags generically** --
     `SpecialItem.effect(tag)` is a keyed lookup, and every
     `for e in ... .effects` site in the engine iterates *room* effects.
  2. **`CLAUDE.md`'s standing rule settles it regardless: published tables go
     in data, not Python constants.** `lockpick` carries rates
     `[54, 35, 30, 19]`, `metal_detector_spawns` carries
     `{coins: 60, key: 25}`, `dig_tool` names three dig tables. Migrating them
     would put published numbers in Python -- which three earlier PRs had to
     undo in review.

  This also matches task 17's precedent exactly: singletons move, shared
  parametric stays. Phase 3's real scope was **8 tags, not ~12**.

- **2026-08-12, phase 3 landed: 8 pure-query singleton capabilities migrated.**
  `electromagnet`, `chronograph`, `ornate_compass`, `master_key`,
  `emerald_bracelet`, `food_multiplier`, `free_hallway_moves`,
  `coin_multiplier`. Added `item_capability_any` as the boolean sibling of
  phase 2's `item_capability_sum` -- both commutative, so neither exercises
  ordering. **Phase 4 remains the first real test of the fold-order design.**

  **Debt: tag pairs 37 -> 27, id pairs 60 -> 56.** Be precise about what that
  measures: **8 of the 10 tag pairs are genuine migrations; 2 are
  reclassifications.** `draft.py`'s `"electromagnet"` and `"chronograph"`
  literals are `priority_draws.json` **condition names**, which only ever
  counted as item-tag debt because they were spelled identically to item tags.
  Deleting the tags from data means the tag scanner correctly stops tracking
  those strings -- the literals remain in `draft.py`, legitimately, as
  condition names that no scanner covers because none ever did.

  **`powered_electromagnet` is a deliberate half-migration**: `electromagnet`
  moved to a module, while `compass` (multi-carrier), `auto_collect` and
  `locksmith_rob` stay as data tags. Its module docstring names the split in
  both directions. A half-migrated item is the most confusing state in the
  system, and the comment is what stops someone later "finishing the job"
  by moving a shared tag into Python.

- **2026-08-12, task 22 phase 2 landed, and the item registry is a fold, not a
  hook.** The primitive is `item_provides(item_id, ItemCapability, **params)`:
  the item declares only the *fact and its parameters*, and the **engine owns
  the fold** (`item_capability_sum` in `engine/effects/__init__.py`). No item
  module registers a handler function.

  This is the deliberate divergence from `room_hook`, and the reason it matters
  is worth keeping: a room has a natural event boundary -- the player standing
  in it -- so firing a handler there maps onto a real moment. **Items have no
  such boundary.** Item behaviour is overwhelmingly "the engine is about to
  charge N; ask every held item whether it changes N". Registering 40 modules
  against a constantly-firing hook would also make fold *order* implicit in
  import order, where today it is visible as sequential lines.

  **`SHOP_DISCOUNT` is a sum and therefore commutative, so phase 2 cannot by
  itself prove the ordering design.** The API is shaped so it does not need
  redesigning: params are stored per `(item_id, capability)` rather than
  pre-flattened, so phase 4's ordered folds become a *sibling* function walking
  the same registry in a caller-supplied order with a combine step. **Phase 4
  is where that gets tested for real** -- treat its ordered tuple as the
  load-bearing artefact and pin the current arithmetic before moving anything.

  **The data tag was deleted, not left alongside.** Once `coupon_book`
  registers the capability in a module, its `shop_discount` effect tag is a
  second source of truth for the same fact -- the defect deleted twice this
  week (`ignition_tool` #199, `silver_key_bias` #202). Building a registry
  while leaving the tag would have recreated the problem the registry exists
  to solve.

  **The tag allowlist shrank 6 -> 5 for `shops.py`: the first downward movement
  of the item debt**, and the measure phases 3-7 are judged by.

  **Brief error worth recording: there is no production call site for
  `validate_capability_registry` or `validate_room_registry`.** Both are
  exercised only by dedicated tests; nothing in `game.py` or
  `validate_data.py` invokes them. `validate_item_registry` follows that same
  pattern. So a typo'd id in any of the three registries is caught by the test
  suite, never by the data validator -- worth knowing before anyone assumes
  `tools/validate_data.py` covers it.

- **2026-08-12, delete the `silver_key_bias` effect record rather than wiring a
  reader.** Owner, resolving the binary question phase 0 raised.

  The silver-key draft bias is real and works, through an id branch:
  `game.py` tests `has(st, "silver_key")` and sets
  `state.special.silver_key_draft`, which `draft.py` reads. The
  `silver_key_bias` effect entry in `special_items.json` was a **second,
  never-consulted source of truth** for behaviour already implemented
  elsewhere -- the `ignition_tool` shape, but harder to detect, because the
  item is `implemented: true` with `blocked_on: null` so no existing check had
  anything to say about it.

  **Deleting is the right direction and worth stating as a general rule:
  when a record and an implementation disagree about where behaviour lives,
  and the implementation works, the record is what is redundant.** Wiring a
  reader purely to justify an existing record would be inventing a consumer
  for data nobody needs.

  Removed in four places -- the item's `effects` list (now `[]`),
  `KNOWN_ITEM_EFFECT_TAGS` in `validate_data.py`,
  `DEFERRED_UNREAD_TAGS` in the phase 0 tag scanner, and the tag inventory in
  `docs/special-items-design.md`. All 10 silver-key tests stay green; the
  mechanic never moved. **Zero-reader tags 4 -> 3**, and the three that remain
  (`crown_of_blueprints`, `dowsing_rod`, `gear_wrench`) are all legitimately
  deferred against real blockers.

  Note the deletion order was itself a check on the ratchet: removing the tag
  from the data made `test_deferred_unread_tags_are_real_tags` fail before the
  scanner was updated, which is the scanner refusing to let its own list go
  stale.

  **This closes the second of the two dead-tag findings.** `ignition_tool`
  went in #199; `silver_key_bias` here. Both were found by looking for tags
  nothing reads, and that check now exists permanently.

- **2026-08-12, `silver_key_bias` is a second dead effect tag, and nothing
  would ever have flagged it.** Found by task 22 phase 0's tag scanner.

  The tag has **zero readers** -- no code anywhere reads the string. The
  silver-key draft bias itself *is* implemented, but through an id branch:
  `game.py:521` tests `has(st, "silver_key")` and sets
  `state.special.silver_key_draft`, which `draft.py` then reads. The name
  `silver_key_bias` does appear at `draft.py:726` -- as a **local variable**,
  which is why a substring grep says the tag is read and an exact
  string-literal scan says it is not. My own measurement used the substring
  method and reported four dead tags; there are five.

  **This is the `ignition_tool` shape again** -- two sources of truth, one
  never consulted -- but strictly worse to detect: `ignition_tool` sat on
  records with `implemented: false`, whereas `silver_key` is
  `implemented: true` with `blocked_on: null`, so no existing check, audit or
  convention had anything to say about it.

  Parked in `DEFERRED_UNREAD_TAGS` because phase 0 moves no code or data,
  with a comment marking it as **not legitimately deferred** unlike the other
  four. The follow-up decision is binary: wire a reader, or delete the
  redundant effect record. **Deleting is probably right** -- the behaviour is
  real and works; it is the *record* that is redundant. Left as a decision
  rather than taken, because it is a data change with a live mechanic behind it.

  **Generalisable lesson: grep for a tag name gives false negatives when the
  tag is also spelled like an identifier.** Thirteen of the 37 item tags are
  spelled identically to an item id, and at least one to a local variable. Use
  an AST string-literal scan, which is what both phase 0 scanners do.

- **2026-08-12, how the Microchips actually work, from play. This invalidates
  the fix approved the day before, not just its details.** Owner, and it
  outranks both the wiki's wording and the audit built on it.

  1. **The third Microchip is already in the Blackbridge Grotto.** The player
     only ever needs to *bring two* -- the Entrance Hall vase chip and the West
     Path dig chip.
  2. **The Grotto's chip can be removed**, and once removed it can be traded at
     the Trading Post or lost in the Lost & Found.
  3. **Every Microchip respawns the next day at its starting location** if it
     was removed from the Grotto.

  **What this overturns.** The 2026-08-11 audit concluded the ceiling was two
  against a gate needing three, and called it a dead gate needing a third grant
  site. The ceiling of two is correct and was reproduced against the live
  engine; **the conclusion drawn from it was not.** Two is the right number to
  carry, and the defect is in the gate, not in the grant sites:
  `areas.json`'s `three_microchips` is `kind: "item", count: 3`, i.e. three held
  *in inventory*. It should be satisfied by **two held plus the Grotto's own
  chip in place**.

  So the approved bundle's first step -- "grant a microchip on Grotto arrival"
  -- **is wrong and must not be built.** The Grotto's chip is not a pickup that
  tops the player up to three; it is a chip already sitting in the pedestal.
  Granting it on arrival would model a fourth chip that does not exist.

  **The shape that fits all three facts:**

      gate opens when  (chips held) + (1 if grotto chip in place else 0) >= 3

  - Bring two, never touch the Grotto's chip: `2 + 1 = 3`, opens.
  - Take the Grotto's chip, hold all three: `3 + 0 = 3`, still opens.
  - Take it and trade or lose it: `2 + 0 = 2`, locked out **for that day only**
    -- rule 3 puts it back tomorrow.

  This needs one new piece of day-scoped state for whether the Grotto's chip has
  been removed, resetting daily rather than carrying over. Note the existing
  `entrance_vase_broken` / `outer_chip_dug` day-start re-grants are already
  exactly rule 3's respawn behaviour for the other two chips, so the convention
  is established and should be matched, not reinvented.

  **The wiki does not contradict this** -- "all three Microchips must be found
  and inserted into the pedestal" is consistent with one of the three being
  found *in situ*. Recorded because reading it as "hold three" is what produced
  the wrong plan.

- **2026-08-12, the room-id debt is 79 pairs, not 65.** `HANDOFF.md` and this
  file's task 22 entry both carried 65; `ALLOWLIST` in
  `tests/test_room_id_allowlist.py` contains 79 across 11 modules, and the test
  passes in both directions, so the live scan equals it exactly. Corrected in
  place above. Another instance of a number outliving its measurement -- and
  one I propagated myself the same day I opened the task warning about it.

- **2026-08-11, the stale-blocker retag widens to an audit of all 14
  unimplemented special items.** Owner. The queue named two records whose
  `meta.blocked_on` was false; verifying them turned up five, and three of the
  five are worse than merely stale because the engine already touches the item:

  - `dowsing_rod`, `crown_of_the_blueprints` -- `color_biased_drafting_not_modeled`,
    built in #193.
  - `coupon_book` -- `shop_purchases_not_modeled`, but `shops.py::buy` exists
    and its effect tag `shop_discount` is **already read** at `shops.py:384`.
  - `gear_wrench` -- `mechanical_room_rarity_not_modeled`, but the 8 Mechanical
    Rooms carry `extra_categories: ["mechanical"]` (fixed #159). The real gap is
    a rarity card-move, which the 2026-08-11 entry above establishes the repo
    already performs twice.
  - `microchip` -- `outer_areas_not_modeled`, but the 36-node area graph landed;
    and `shops.py:904/920` already **grant** the item while its record says
    unimplemented and its `effects` list is empty.

  So: audit the remaining nine as well (`battery_pack`, `magnifying_glass`,
  `telescope`, `prism_key`, `chronograph`, `trophy_of_wealth`, `the_axe`,
  `file_cabinet_key`, `key_of_aries`) rather than fixing only what was reported.
  A research pass first, then one data PR.

  **`implemented: false` is carrying two different meanings** -- "nothing in the
  engine touches this" and "the engine grants it but it does nothing" -- and
  that ambiguity is what let `coupon_book` and `microchip` sit miscategorised.
  The audit should say which of the two each record means.

  On `coupon_book` specifically: **trace the discount end to end before flipping
  the flag.** A wired effect tag is not proof; Room 8 was reachable on 2 of 45
  cells and granted nothing while looking built.

- **2026-08-11, what the Microchip actually does, from play.** Owner, and this
  outranks the wiki per the standing rule -- recorded because nothing in the
  repo captured it and the record's `effects` list is empty.

  **Microchips open the Orindian Ruins, behind the Blackbridge Grotto.** There
  are also **Trading Post trade mechanics involving them that should already be
  implemented** in `shops.py`'s trade graph.

  So `outer_areas_not_modeled` was not just stale, it was pointing away from the
  real work: the item has a concrete destination gate and an existing trade
  surface. Research pass to verify every use against the wiki and the datamine
  before authoring the effect.

- **2026-08-11, task 16's scope, in four rulings.** Owner. The brief in
  `HANDOFF.md` measured ~35-45 edits across ~25 files; re-measuring found ~74
  files, because two large categories were never enumerated. The raw greps do
  overstate as recorded -- 48 `#`-comment hits on history verbs reduce to about
  8 genuine ones, since "on an earlier day", "used to prove" and "rejected by
  the geometry gate" all describe the present. The extra size is real, not
  grep noise.

  **1. The 26 `tests/rooms/` "Split out of the old test_X.py" module
  docstrings: strip the history clause, keep the cross-reference.** The pointer
  ("see tests/rooms/test_dining_room.py for the Dining Room's main course") is
  live navigation and stays; where the file came from is not.

  **2. Dated references: strip the date, keep an undated pointer to
  `docs/open_tasks.md`.** "owner spec, docs/open_tasks.md decisions log
  2026-08-06" becomes "owner spec, see docs/open_tasks.md". A reader must still
  be able to find the reasoning behind a surprising rule; they do not need to
  know the day it was ruled. **Source-provenance stamps are exempt and keep
  their dates** -- "The wiki's Cargo Rooms table, fetched 2026-08-11" is the
  same kind of fact as `meta.source`/`meta.confidence`, and a fetch date is
  what makes a wiki claim auditable later.

  **3. The ~20 test docstrings that narrate the bug they pin get rewritten to
  state the property, not deleted down to their first clause.** Deleting only
  the trailing "-- previously this granted nothing" leaves "Hovel now
  qualifies" implying a change the reader cannot see. This is the highest-value
  part of the sweep and the only editorial part; every rewrite gets reviewed
  individually.

  **4. Two PRs: `src/` + `tools/` first (~17 files), then `tests/`.** Engine
  comments encode constraints the code must still honour and need the closer
  read; the test sweep is bulk and lower-risk.

  Also noted: `HANDOFF.md` §3's pointers to `engine/game.py:1359` and
  `config.py:249` are stale -- both line numbers now land on clean code. The
  named offenders in this task's own body (`tools/validate_data.py`,
  `engine/items.py`, `tests/rooms/test_vault.py`) were re-verified and are
  still there.

- **2026-08-11, three premises behind the `add_aquariums` scoping were wrong,
  and the groundwork is far smaller than costed.** Recorded because the owner
  accepted a cost estimate built on them.

  **1. `draft.py::_priority_draw` is NOT a first-match loop.** It rolls
  **every** entry independently and `continue`s past a failed roll, returning
  only on a roll that succeeded *and* yielded a draftable room. Measured over
  400k seeds, the two existing rows fire at **0.15606** against the wiki's
  stated **0.1561**. The compounding the Aquarium needs **already works**; no
  new mechanism is required. What is missing is only *day-scoping* of an
  entry, and `_apply_category_bias` already has the `condition` idiom to copy.

  **2. There is no deal-time rarity read, so a "rarity override channel" is
  the wrong shape.** `_deal_from_rarity` is handed a `rarity_idx` and never
  asks a card what rarity it is -- **a card's effective rarity IS the deck it
  sits in**. So "set Aquarium's Dynamic Rarity to Commonplace" is a *card
  move* between buckets, which the repo already does twice
  (`reroll_random_rarities` for the Conservatory, `apply_upgrade`'s
  cross-bucket path). **No rebuild of the decks is needed, and a mid-day
  rebuild would be actively unsafe** -- it resets all eight cursors, silently
  discarding today's upgrades, injections and Conservatory rerolls.

  **3. The Aquarium room record already exists.** The new record is a
  *second, distinct* floorplan (the experiment-added copy, which the wiki
  gives its own placement restriction), not the Aquarium itself.

  **Scheduling consequence, and it inverts what I told the owner: the room
  record is the retrain trigger, not the effect.** `obs.py` uses
  `len(registry.rooms)` as a Box high bound, and `Room.idx` is *position in
  rooms.json order* -- so a new record inserted mid-file shifts every later
  room's index and invalidates the policy's learned room embedding far more
  deeply than a bound change. **It must be appended at the end**, through
  `tools/supplemental_rooms.json` rather than a hand-edit.

  `decks.py::add_copies` is confirmed wrong for this effect: it reshuffles the
  whole deck and rewinds the cursor, by design, because it serves once-per-day
  callers. Firing it 40+ times a day would re-arm the entire bucket each time.
  The replacement inserts into the **undealt** region only.

- **2026-08-11, the Aquarium gets two separate condition-gated priority-draw
  rows, not a place in the existing ones.** Owner. The wiki says the effect
  "adds Aquarium to the 3/13% passive filters", but our `_priority_draw`
  resolves a row's `rooms` list by **fixed order, first draftable wins**,
  while the real game treats a priority draw as a *filter* and draws by deck
  order among the survivors.

  Joining the rows would therefore starve the Aquarium behind the Commissary
  and Observatory -- materially wrong once the Aquarium has 3, 6 or 9 copies
  in the deck against the Commissary's single card. Separate rows reproduce
  the published 15.61% exactly, at the cost of two extra RNG substreams.

  Act on this cold as: this is a **deliberate divergence from the wiki's
  literal wording, chosen because our priority-draw resolution differs from
  the game's.** If the resolution is ever fixed to draw by deck order among
  survivors, revisit -- joining the rows would then be both literal and
  correct.

- **2026-08-11, the priority-draw rows are already off-spec, and that is its
  own PR.** Owner. Independent of the Aquarium work: the wiki puts the
  **Garage** in the 3% row (excluded in early days) and says the **Secret
  Passage** sits in the 5% row *only while the Greenhouse is undrafted*,
  moving to 3% afterwards. Our data has the Classroom alone at 3% and the
  Secret Passage unconditionally at 5%.

  Fixed separately rather than inside the Aquarium PR, so a shift in draft
  odds has one attributable cause.

  **Two corrections to the research that scoped this, both verified against
  the wiki source and our own data, and both shrinking the job:**

  - **The Greenhouse gating tag already exists and is already consulted in
    the very function that needs it.** `_priority_draw` reads
    `state.greenhouse_placed` to swap in an entry's
    `chance_with_greenhouse`, and the Greenhouse room module sets that flag.
    Our 5%-to-50% boost is therefore already correct and already sourced.
    What is missing is only the Secret Passage's **conditional membership**
    of the two rows -- and the flag it keys on is in scope at that line.

    The published text (`Drafting/Advanced`) is:
    *"Patio, Veranda, Greenhouse, Morning Room: 5% chance, increased to 50%
    if a Greenhouse is active. Secret Passage is included if Greenhouse has
    not been drafted."* and *"Garage, Classroom: 3% chance. (Garage excluded
    in early days, Secret Passage included after Greenhouse effect is
    active)."*

  - **The Garage's absence from the 3% row is a known, documented gap, not a
    new finding.** `priority_draws.json`'s `forced_draws.garage.meta.notes`
    already records it: *"The separate Day-5-or-Veteran 3% passive Priority
    Draw for the Garage (wiki) is a different, unimplemented mechanic -- do
    not conflate the two gates."* Our note is more specific than the wiki's
    "early days". Leave that mechanic alone; it is not what this PR is for.

  So the job is one conditional rooms-list, not a new gating mechanism.

- **2026-08-11, the Mail Room's Dynamic Rarity deferral is re-opened.**
  Owner. It was deferred on 2026-08-09 with the stated reason that
  `decks.py` had no rarity-override channel and building one was its own work
  touching the draft hot path. **That reason expires the moment the Aquarium
  groundwork lands** -- the card-move primitive is exactly the channel it
  wanted. A waiting package setting the Mail Room to Commonplace becomes a
  few lines on the same primitive.

  Its own small PR, after the groundwork. Note the wiki publishes a ~25-room
  Dynamic Rarity table, none of it modelled; this re-opens the Mail Room
  specifically, not the table.

- **2026-08-11, Entrance Hall trunks are entirely per-day: 17 is a DAILY
  maximum, and nothing carries over.** Owner, from play. Neither the spawned
  trunks nor the spawn counter survives the night -- the effect can add up to
  17 trunks to the Entrance Hall each day, and the next day starts clean.

  This corrects an assumption I stated in the other direction. The wiki
  publishes a "maximum of 17" alongside a predetermined spawn order across the
  Entrance Hall's four walls, which reads like a lifetime cap on numbered
  physical objects; it is not.

  Act on this cold as: **this makes `entrance_hall_trunk` materially cheaper
  than scoped.** Everything lives in `SpecialItemsState`, which is rebuilt
  with `GameState` every day -- so there is **no `GameConfig` field, no
  `shops.py::carryover()` entry, and no `DayChain` merge**. The per-cell
  container overlay and the per-day spawn counter are the whole of it. Do not
  build the save-persistent counter the earlier scoping called for.

  The 17 remains shared with **The Twins** constellation within a day (the
  wiki: The Twins is "identical to triggering this effect twice"), so the
  counter must still be named for the Entrance Hall rather than for the
  experiment, so The Twins can reuse it when it lands.

  Still open and not settled by this ruling: whether trunks appear in the
  **Outer Entrance Hall** too (the wiki says they do under the Shrine's Monk
  blessing). Outer rooms have no grid cell, so a cell-keyed overlay cannot
  reach them; recorded as a gap.

- **2026-08-11, the four remaining base experiment effects get built.** Owner,
  rejecting the cheaper option of filtering them out of the setup draw. The
  Laboratory's `draw_offers` does not filter on `implemented`, so a player can
  be offered -- and pick -- an experiment that does nothing. That is the
  clearest failure of the "features are built to be PLAYED" bar in the
  subsystem: a day replay containing a chosen no-op experiment does not read
  clean.

  The four: `entrance_hall_trunk`, `spread_dig_spots`, `add_aquariums`,
  `mail_room_letter`.

  Act on this cold as: **two of these are subsystems wearing an experiment
  costume, and one may not be buildable at all.**
  - `mail_room_letter` looks cheapest -- the Mail Room family is fully
    modelled and the wiki publishes a 16-letter collection in fixed order.
  - `entrance_hall_trunk` needs **dynamic per-cell container counts**;
    `containers_in()` reads a static per-room table and the Entrance Hall has
    no entry.
  - `add_aquariums` needs live deck injection with a per-day rarity override,
    and it must defeat `draft.py::room_draftable`'s one-copy-on-grid rule --
    which is also the thing that currently makes it non-re-entrant with the
    shops/bedrooms/hallways/red triggers. **Re-verify that non-recursion
    argument before it goes live.**
  - `spread_dig_spots` is **blocked on off-grid dig spots**, which do not
    exist: `dig_all` reads `state.grid[cell]` only, and `areas.py` has no dig
    concept. Report back rather than inventing a model. Note the wiki also
    forbids pairing it with `trash_while_digging`, already encoded as
    `cross_column_exclude`.

- **2026-08-11, Blessing of the Tinkerer IS built -- reversing its
  never-model entry.** Owner, resolving a conflict between two of their own
  rulings. The Shrine ruling stubbed Tinkerer on "needs the experiments
  subsystem"; task 19 listed "Blessing of the Tinkerer cross-triggers" under
  *Deliberately never modelled* because it is a global modifier on the whole
  subsystem rather than a per-record rule.

  The blocker named in the Shrine ruling is gone, so that ruling now governs:
  any active experiment also triggers whenever a Mechanical Room is drafted,
  independent of the chosen trigger.

  Act on this cold as: **the eight Mechanical rooms are already typed**
  (`is_category("mechanical")`, landed in #159), so the detection is cheap.
  The care needed is at the fire site -- this is a second, unconditional path
  into `trigger_success` that bypasses the configured trigger's own gate, so
  it must respect the pause gate and any cap exactly as the normal path does.

- **2026-08-11, the jack hammer's unsourced vault keys are resolved by what
  they unlock.** Owner, on the four vault keys our dig table carries that the
  datamine does not list: *"Research the items blocked by the keys. Drop any
  keys that only block puzzles or story items. Model those that block items we
  do model, like gems."*

  So this is not a keep-all or delete-all call. Each of `vault_key_304`,
  `vault_key_149`, `vault_key_233` and `vault_key_370` is judged on its own
  vault's contents: a vault holding modelled resources justifies keeping its
  key in the table; a vault holding only puzzle or story content does not.

  Act on this cold as: this needs a research pass over what each vault
  contains before the full table reconciliation runs, and the outcome must be
  written into `dig.meta.note` so the next reader does not re-open it.

- **2026-08-11, the Spare Great Hall grants its published prize contents.**
  Owner, closing a question deliberately left open on 2026-08-10. Per the wiki
  the room has no side doorways, no Antechamber lever, no Upgrade Disk, and
  its far door is not necessarily locked -- so its entire published *effect*
  is invisible at our grid granularity. Rather than declare it permanently
  inert, it gets its published prize contents (four cyan gems / key + cyan gem
  + 5 coins / 20 coins) as an items roll.

  This clears two of the eleven divergence findings, and is the only option
  that leaves the room doing something a player can observe.

- **2026-08-11, two orchestrator decisions taken without escalation.**

  - **`servants_spare_quarters__ix134` gets `cap: 15`.** The base
    `servants_quarters` gained the published cap while the Guess Bedroom mimic
    was being built; the upgrade variant carries the same uncapped
    `grant_per_category` and was missed. Per CLAUDE.md a placement/behaviour
    rule applies to upgrade variants that inherit the base's rule. This is the
    same invisible-until-the-count-gets-large shape as the original.
  - **The divergence audit gains a fifth exemption channel,
    `_AUDIT_DEFERRED_EXEMPT_IDS`,** carrying an id and a reason, guarded
    against staleness the way the Python channel already is. The owner asked
    for Closed Exhibit / Throne Room / Pump Room to be marked deferred; there
    was never a mechanism that could express it, so it was never done -- and
    `parlor__ix109`, ruled permanent, is still counted too. Exempting those
    four takes the count **11 -> 7**, after which every remaining finding is
    genuinely actionable.

- **2026-08-11, the redraw cap is DROPPED. This reverses the 2026-08-11
  ruling above, and the reversal is my fault.** When I asked for that ruling I
  described `drawing_room_drawn` x `set_dice` as an unbounded zero-step loop.
  Measured in this engine, it is not: **mean 2.34 redraws, median 2, p90 3,
  p99 4, max 4 over 53 sampled hands; zero runs exceeded 8.** It is a decaying
  random walk, not a divergence.

  The closed form agrees. Each redraw spends a die and the Drawing Room
  reappears with probability p, so `E[length | 2 dice] = (2-p)/(1-p)^2`, which
  is 2.35 at the measured p = 0.10 and only diverges as p -> 1.

  **Both of the wiki's methods for driving p -> 1 are unavailable here.** The
  Chronograph is not modelled at all, and the Silver Key draft bias is cleared
  after the initial deal (`draft.py`, commented "Redraws clear the flag"), so
  the depleted-pool method cannot persist across redraws. An adversarial probe
  that reduced the commonplace/gem deck to the Drawing Room alone still
  produced 0 fires in the available redraws.

  **Owner ruling: drop the cap.** Do not add a per-hand redraw budget. The
  termination check in `redraw` still goes in -- it is a live bug independent
  of the cap.

  Act on this cold as: **a cap would have been a permanent, invented deviation
  from the game justified by a premise that was never true of our engine.**
  The wiki is explicit that the real game has no such limit: *"There is no
  limit to how many times floorplans can be redrawn in one draft."* The lesson
  is that "this looks unbounded" is a hypothesis to measure, not a fact to
  rule on -- especially when the proposed fix is a deviation.

- **2026-08-11, the Silver Key bias clearing on redraw is an OPEN question,
  held for play.** `draft.py` clears the Silver Key's cross/T draft bias after
  the initial deal, so it does not apply to redrawn hands. The wiki's
  description of the dice-farming exploit implies the real game's bias **does**
  persist -- that is what would make a Drawing Room appear on every draw and
  make the loop real.

  Owner is checking in play: draft with a Silver Key, redraw, and see whether
  the bias still applies to the new hand.

  Act on this cold as: **if the bias should persist, this is a fidelity bug and
  the redraw loop becomes genuinely unbounded**, which would re-open the cap
  ruling above. Until then the clearing behaviour stands. Do not change it
  speculatively.

- **2026-08-11, four `drawing_room_drawn` scoping calls made without
  escalation.**

  - **The trigger binds through `effects/rooms/drawing_room.py`**, a one-line
    `room_hook` at `ON_HAND_DEALT` delegating to `experiments`. The
    alternative -- an `on_hand_dealt` function called from three sites --
    would put a `"drawing_room"` literal inside an engine module, which the
    standing architectural rule forbids. The room module is where a room-id
    binding belongs, and `fire()` already runs per option at all three deal
    sites, so it needs no new call sites.
  - **The cap does not gate on `set_dice` being configured.** Action legality
    that depends on experiment configuration is opaque to both the agent and a
    human reading the mask. Moot now that the cap is dropped, recorded so it
    is not re-proposed.
  - **No observation change.** Neither `rotations_used` nor
    `study_redraws_used` is exposed today, the mask already makes an
    unavailable redraw unselectable in a MaskablePPO env, and widening
    `resources` would invalidate every released checkpoint.
  - **`_check_termination()` goes at the very end of `redraw`**, after the
    `ON_HAND_DEALT` loop, so a trigger firing on the redealt hand is what gets
    checked. Verified reachable today: `steps_for_gold` drives steps to 0
    inside a redraw and the day does not end.

  Also found: the hidden-Drawing-Room leak the owner accepted is **total, not
  partial, under the Archives**. Archives conceals exactly one slot, a hand
  holds at most one Drawing Room, and no other trigger fires at deal time --
  so a success-counter tick plus two visible non-Drawing-Rooms identifies the
  hidden card with certainty. Under the Darkroom it leaks only "one of these
  three". Suppressing the counter would not close it, since the effect's own
  result is observable too.

- **2026-08-11, redraws get a per-hand cap -- a deliberate deviation from the
  game.** Owner, on the `drawing_room_drawn` x `set_dice` loop. Each die-redraw
  spends a die; if the redealt hand contains the Drawing Room the trigger fires
  and `set_dice` resets dice to 2. Redraws cost **zero steps**, so dice never
  fall below 1 while the Drawing Room keeps appearing.

  The wiki documents this as a real farming exploit and states the intended
  payoff: *"As dice can be converted to experiment activations at a one-to-one
  rate, a method to obtain a lot of dice makes for an easy way to activate
  experiments hundreds of times as necessary. For example, this can be used
  with the allowance or star effects to farm a large amount of the permanent
  resources."* `permanent_allowance` and `gain_star` are both live.

  **The owner chose to cap rather than reproduce it**, mirroring the existing
  rotation budget cap, whose docstring already records why: a free cyclic
  action makes a deterministic argmax policy loop on it forever. Redraw is
  normally resource-bounded; `set_dice` removes the bound.

  Act on this cold as: **this is a knowing divergence from the game, chosen
  because the sim is an RL environment**, not a fidelity call. Record the cap
  as a simulation constraint in the README's simplifications section, not as a
  game rule.

- **2026-08-11, the `jack_hammer` dig table diverges from the datamine and gets
  a partial fix now.** Our table has **zero** trash entries, and
  `DIG_PRIORITY` auto-selects the jack hammer as the best tool -- so
  `trash_while_digging` would be silently unfireable for any player holding
  one. The wiki's datamined table gives it **18.4%** trash.

  Our `shovel` and `detector_shovel` tables reproduce the wiki row for row.
  `jack_hammer` alone does not: no trash, no `nothing`, no dice, no Stopwatch,
  and it **adds four vault keys the wiki does not list**, with nothing in
  `dig.meta.note` explaining any of it.

  **Owner ruling: add the six trash rows plus `nothing` at the wiki's weights
  now, and do the full table reconciliation as its own data PR** -- a real
  change to the dig economy should not be buried inside an experiments PR.

  Act on this cold as: the unsourced vault keys are the open question. They may
  be a deliberate addition nobody recorded, or an ingest artifact. Establish
  which before the full rebuild deletes them.

- **2026-08-11, a hidden Drawing Room counts as drawn.** Owner. The trigger
  fires on the floorplan being dealt into the hand, whether or not the Archives
  concealed it -- concealment is about display, not the deal.

  Known consequence, accepted: firing **leaks the concealed option's identity**
  through the experiment's success counter, which the observation exposes. An
  agent watching the counter tick learns what the face-down card is. This
  partially defeats the Archives whenever this trigger is configured.

- **2026-08-11, six phase 3 scoping calls made without escalation.**

  - **The `apples` trigger gets `game` threaded through `items.py`**, rather
    than a deferred counter drained at enclosing sites. Every leaf already has
    `game` reachable -- the "no game in scope" problem is a property of current
    signatures, not a real constraint -- and threading *removes* parameters
    (`grant_item`, `roll_room_items`, `roll_extra_items` each drop two or
    three). A missed thread is a `TypeError`; a missed drain is a silently
    misattributed effect that counts the wrong house. Threading also gives
    per-apple interleaving, which is the faithful shape.
  - **Termination gets four scoped insertions, not a blanket call**:
    `open_door`, `open_container`, `redraw`, and
    `_maybe_finish_experiment_setup` (the last already live since phase 1).
    Each is justified by a specific new fire site. **Not** inside
    `trigger_success`, which runs mid-`_place_room` before the placement is
    finished -- terminating there would fire ON_DAY_END against a
    half-constructed grid.
  - **The availability layer gets the two free `day_gate`s only.** `cfg.day`
    and `cfg.veteran_mode` already exist; `item_obtained_gate` needs a new
    persistent `shovel_ever_obtained` flag and is deferred. Note
    `veteran_mode` defaults to True, so all of this is a no-op by default. Any
    filter must never shrink the pool below 3, since `draw_offers` samples 3.
  - **The `security_door` trigger's "occasionally triggers an additional time,
    possibly due to a bug"** stays unmodelled, recorded as a `null` magnitude
    with the gap in `meta.notes`. The wiki hedges it and gives no rate.
  - **The dead `chest` container kind counts as a trunk** (the wiki says chest
    *is* trunk), so the gate is `kind in ("trunk", "chest")` and stays correct
    if a room ever gets one. **Vault deposit boxes do not count** -- a
    distinct mechanic.
  - **`trunks_opened` ships with its designed partner dead.** The wiki pairs
    it with the Entrance Hall trunk effect from both sides; that effect is
    inert and needs dynamic per-cell container counts, which
    `containers_in()` cannot express today.

  Also found: `docs/experiments-design.md`'s Status section went stale the
  moment PR #169 landed -- it still claims one live base trigger and a 25%
  offer rate. And `pantry_fruit`'s note about apples being less common is
  **not** in conflict with `items.json`'s fruit weights; they describe two
  different pools, which is worth one clarifying line so nobody re-opens it.

- **2026-08-11, our Archives is scoped wrong: the effect is house-wide for
  the day, not per-doorway.** Research triggered by the owner's archived/hidden
  correction. The wiki is unambiguous: *"The Archives ... will 'archive' one of
  the three floorplans drawn whenever a room is drafted after Archives"* --
  no from-room qualifier anywhere on the page. Our `draft.py::_hidden_count`
  keys off the room being drafted **from**, so archiving only happens through
  an Archives doorway.

  The owner's own sentence is the proof, independent of the wiki: under our
  model a Darkroom draft sets `from_room = Darkroom`, so no option could ever
  be archived -- yet the owner observes that one of a Darkroom's concealed
  options can be. That is only possible if the Archives effect is persistent
  and house-wide.

  Corroborated a third way: the Shelter interaction is worded *"drafting the
  Archives under the effect of the Shelter ... Archived floorplans do not
  appear"*, i.e. the negation is applied once at placement and suppresses
  archiving for the whole day. That only makes sense for a day-long
  capability.

  Our stored `meta.effect_text` for the Archives says *"While drafting from
  this room, one of the 3 floorplans is hidden (modeled: one fewer option)"* --
  wrong twice: the from-room scoping, and the parenthetical, which is a
  project annotation that is stale against the wiki **and** against our own
  code (nothing anywhere drops an option).

- **2026-08-11, neither the Archives nor the Darkroom reduces the option
  count -- both conceal.** The `reduce_draft_options` tag name asserts a
  mechanic the game does not have. Our runtime behaviour is right (we mark
  options hidden and keep them draftable); only the name and the annotation
  lie. Archived floorplans remain fully selectable, and the game deliberately
  preserves side channels: gem cost, Coat Check label, power lines, rotation
  (which leaks shape), the Furnace's red haze, and rarity when drafting
  through a security door.

  So **archived is a per-option-instance flag produced by a day-long
  house-wide capability**, while Darkroom concealment is a genuine from-room
  effect. The two compose independently. Split the tag: `archive_floorplan`
  for the Archives, `conceal_all_floorplans` for the Darkroom, and retire
  `reduce_draft_options`.

- **2026-08-11, the archived slot is uniformly random across all three.**
  Owner. We currently archive **slot 2 deterministically** and always keep
  slot 0 visible; the wiki only says "one of the three". The owner ruled
  random across all three, which is strictly harder than what we ship -- there
  is no longer a guaranteed fully-informed option. This materially changes
  agent play, so it needs a named RNG substream and a test.

- **2026-08-11, the Shelter's negation of the Archives is spent once, at
  placement.** Owner, matching the wiki's *"drafting the Archives under the
  effect of the Shelter"* wording: one charge when the Archives is drafted,
  and no archiving for the rest of the day. The alternative -- a charge per
  draft -- would drain all three Shelter charges in three doorways.

  Act on this cold as: `_red_negated` is currently never consulted on the
  `draft.py` path, so today a Shelter negates neither room. The trap is that
  every existing caller uses a per-event pattern; this one must latch into a
  day flag at placement or it silently drains the resource.

- **2026-08-11, the Darkroom light switch and the security-door rarity leak
  are both in scope.** Owner, on two published gaps found in the same pass.

  The Utility Closet can restore the Darkroom's lights, fully disabling its
  drafting penalty; we model that switch system but have **no Darkroom
  switch** anywhere in `src/` or `data/`. Without it the agent has no counter
  to a Darkroom at all. (The wiki also notes the fuse never blows if the
  switch is already off when the Darkroom is drafted, but flipping it off and
  on again beforehand does not prevent it.)

  Separately, the wiki says a concealed floorplan's **rarity is visible** when
  drafting through a security door. Our `env/obs.py` zeroes rarity for every
  hidden option unconditionally, so the agent loses information a real player
  has. Note `forced` is zeroed there too, which discards real information for
  no stated reason -- worth checking while in that code.

- **2026-08-11, "archived" is independent of "hidden" -- our data conflates
  two different mechanics.** Owner, correcting a question I asked badly. I
  offered a choice between counting only Archives-hidden options or any hidden
  option for the `archived_floorplan` experiment trigger. The owner rejected
  the framing: *"Archived is independent from hidden. You can't see rooms
  drafted from the Darkroom, but one of them can still be archived."*

  So `opt.hidden` is **the wrong signal entirely**. Being archived is a
  property a floorplan has; being hidden is a property of how it was dealt.
  A Darkroom draft hides its options from the player, and one of those hidden
  options may independently be archived.

  Our `rooms.json` gives the Archives and the Darkroom the **same effect tag**
  (`reduce_draft_options`, differing only in `amount`), so the engine cannot
  currently tell the two apart, and `opt.hidden` conflates them. The trigger
  needs a distinct archived marker, set by the Archives' mechanic only.

  Act on this cold as: this is a **modelling gap in the drafting system**, not
  just a blocked trigger. Whether the Darkroom's "you cannot see the options"
  is even correctly modelled as `reduce_draft_options` is now open --
  reducing the option count and concealing the options are different things.
  Worth a research pass before the trigger is built.

- **2026-08-11, experiment trigger and cap semantics.** Owner, on three of the
  twelve ambiguities raised while scoping experiment phases 2-3.

  **The "for each Bedroom after your second" trigger counts all of today's
  Bedrooms**, not only those drafted after the experiment started. The wiki's
  live text says the opposite -- *"It does matter whether those two initial
  Bedrooms are drafted before or after starting the experiment"* -- but that
  sentence has never been grammatically clean (created 2025-09-29 as "before
  or starting", repaired to "before or after" by a 2025-11-25 grammar edit
  that left "does matter" untouched), so a dropped "not" is at least as
  plausible as a deliberate "does". This is the harsher reading: a
  bedroom-heavy morning can burn the grace before the player reaches the
  Laboratory.

  **The "next 3 times you unlock and open a chest" trigger counts trunks
  only** -- not locked lockers, not free lockers, not the Garage car trunk,
  not Mechanarium compartments. The wiki uses "chest" to mean trunk and its
  Sledge Hammer clause describes trunks specifically. Including locked lockers
  would have let a single Locker Room visit burn the whole 3-trigger cap
  deterministically, since that room holds 17 in one cell.

  **A capped trigger counts fires, not qualifying events** -- so pausing the
  experiment preserves charges. This sets the precedent for the packet pool's
  `map_view`, the only other capped trigger.

- **2026-08-11, eight experiment scoping calls made without escalation.**
  Recorded so they are visible rather than buried in a PR.

  - The **Hovel kills the `gems_spent` trigger** (wiki: *"this trigger becomes
    useless with it on the estate"*). Our engine models the Hovel by paying
    gem costs in steps at 3:1 while `_effective_cost` still returns the gem
    number, so a naive `cost >= 2` check would fire on every expensive draft
    -- the exact opposite of the published behaviour.
  - **The Stopwatch's gem waiver does not count as spending.** Unpublished;
    consistent with the Emerald Bracelet rule, which the wiki does state.
  - **Outer-room drafts do not fire draft triggers.** Self-consistent: outer
    rooms are never in `st.grid`, so the counting effects already exclude
    them. The wiki says outer rooms count only under a Blessing, and
    Blessings are out of scope.
  - **The Red Rooms trigger's own 5-step loss is suppressed while paused**,
    which falls out for free from applying it inside `trigger_success` after
    the active gate.
  - **The `security_door` trigger fires at `open_door`**, not `choose` --
    matching "drafted from". The in-drafting site naturally lands after
    placement, the same way the game's two paths differ.
  - **Draft triggers fire between draft counting and `ON_PLACE`.** Both
    bounds are wiki-stated: after the grid write so the triggering room counts
    itself, and before `ON_PLACE` so the Weight Room halves the experiment's
    steps rather than the reverse.
  - **`gain_star` is flipped live** -- `state.stars` is already fully wired
    for carryover, so it is one line, and it drops the all-inert-offer rate
    from 4.55% to 1.8%.
  - **Availability gating is split into its own PR.** Under shipped defaults
    only the `spread_dig_spots`/`trash_while_digging` cross-column exclusion
    binds; the two gates needing new persistent config are bypassed by
    `veteran_mode`.

  Two data-file corrections also fall out: `bedrooms_after_second`'s note must
  quote the wiki verbatim and record the ruling above, and `security_door`'s
  note omits the published in-drafting clause entirely.

  **Deliberately not modelled:** the wiki's own hedge that `security_door`
  *"occasionally triggers an additional time, possibly due to a bug"* -- it
  gives no frequency. And Scraps of Paper, which Patch 1.6 added to the trash
  table, do not exist in `special_items.json`.

- **2026-08-10, the Guess Bedroom excludes the Aquarium family and treats a
  mimicked Bunk Room as a flat 2 Bedrooms.** Owner, on two ambiguities raised
  by the research pass. The Guess Bedroom loses its own +10 steps and instead
  secretly picks one Bedroom from today's draft pool when it is **drafted**,
  taking on that room's effect.

  **The Aquarium is out of the selectable set for now**, with the gap in
  `meta.blocked_on`. Mimicking it would require inheriting the Aquarium's
  extra colours, and `Room` is frozen -- so `Room.is_category` would have to
  become state-aware for one cell. That primitive backs category biases,
  `grant_per_category`, the Cloister/Terrace green boosts and scepter colours,
  which is a lot of load-bearing code to change for one room. The wiki records
  that the real game is buggy here too ("in rare cases, only some of the
  effects are applied, despite still mimicking an Aquarium"). Reversible.

  **A mimicked Bunk Room counts as 2 Bedrooms**, matching the real Bunk Room's
  existing `counts_as_bedrooms: 2`. The true behaviour is **unpublished** --
  the wiki carries its own open-question box saying it "is not consistent from
  effect to effect. For some effects, it still only counts as one Bedroom. For
  some, such as the Day Overview, it actually counts as three." A flat 2 is
  consistent with the rest of the codebase and wrong only where the wiki
  itself cannot say.

  The remaining four mimics are cheap, because every payload is already
  implemented on the source room: Bedroom (+2 steps, retriggerable, does not
  become an Entry Room), Boudoir (no effect), Nursery (the persistent
  +5-steps-per-Bedroom effect, including for itself; not a Drafting Room for
  the Classroom; own item spawns disabled), Servant's Quarters (keys equal to
  Bedrooms in the house, **cap 15** -- a cap the existing `servants_quarters`
  record does not have either, so that is a pre-existing gap).

  Published selection rules to honour: never the Guess Bedroom itself, Her
  Ladyship's Chamber, the Master Bedroom, or the Spare Bedroom and its
  upgrades; Repellent-banned floorplans are excluded **except the Hovel**,
  which can always be selected even if already drafted and even before unlock;
  rooms already on the estate are eligible if the Chamber of Mirrors returned
  them to the pool; the **upgraded** version is mimicked where an upgrade
  applies; and if no valid option exists and the Hovel was not chosen, the
  mimic fails and the room has no effect. Once one Guess Bedroom mimics an
  Aquarium every later one does too -- moot while the Aquarium is excluded,
  but it is why the chosen id has to be state, not a local.

  **UNPUBLISHED magnitude:** the wiki says Servant's Quarters is "more commonly
  selected than the other floorplans" and gives no number. Record as `null`
  with the gap in `meta.notes`; do not invent a weight.

  Also corrected by this work: `docs/open_tasks.md` previously recorded that
  the Guess Bedroom "gets a research pass, then an owner call if it is
  unsourced ... if the wiki is as vague as the datamine, leave it unmodelled."
  The wiki is **not** vague -- it is one of the better-documented upgrade
  pages on the site, with per-mimic sections. So this is implementable, not a
  shelve.

- **2026-08-10, the Great Hall locks all three grid doorways AND models the
  search cost.** Owner, choosing the more faithful of three options. The room's
  effect is "7 Locked Doors", but our grid has no subchambers: a `cross` has
  only 3 non-entry doorways. In the real game the far doorway is a genuinely
  locked drafting door, while the two side drafting doors are themselves
  unlocked but sit behind three locked inner doors each, only one of which is
  the passage.

  So all three doorways lock, and the side doorways additionally carry the
  expected cost of finding the right inner door. The wiki publishes a
  theoretical table for that search: edge doors 25% to be the doorway, the
  centre door 50%. The owner rejected the cheaper "lock all three, flat 1 key
  per side" option in favour of modelling it.

  Mechanism: `data/locks.json` already has `always_unlocked_rooms`, consumed at
  `engine/locks.py::roll_segment`. A symmetric `always_locked_rooms` is the
  natural counterpart. The lock roll happens inside `_place_room` before hooks
  fire, so this belongs in data, not a `room_hook`. A Foyer already on the
  estate correctly overrides it, matching "unless some other effect forces them
  to be unlocked".

- **2026-08-10, the Spare Great Hall's layout is `straight`, not `cross` --
  the wiki wins over the datamine.** Owner, on a conflict surfaced rather than
  resolved silently. Our datamine row says `4-Door`; the wiki says flatly that
  the Spare Great Hall **does not inherit the Great Hall's shape** and draws
  the consequence explicitly: *it may be drafted along the edges of the house*,
  which a 4-way can never be under `grid.py`'s outer-wall invariant.

  This is not cosmetic -- it changes which of the 45 cells the room can legally
  occupy. The change must go through `LAYOUT_OVERRIDE` in
  `tools/ingest_sheet.py`, **not** a hand-edit to `rooms.json`, or the next
  re-ingest reverts it. Precedent exists: two datamined rooms are already
  corrected this way.

  Still open, and deliberately not asked yet: whether the Spare Great Hall gets
  any modelled effect at all. Per the wiki it has no side doorways, no
  Antechamber lever, no Upgrade Disk, and -- despite its own effect text -- its
  far door is *not* necessarily locked. That would make its entire published
  effect invisible at grid granularity, i.e. the `parlor__ix109` treatment. Its
  prize contents are published and could be granted as an items roll if the
  room should do something.

- **2026-08-10, colour-selective drafting gets filter + default floorplans, no
  reserve copies.** Owner, choosing the middle of four options. The Secret
  Passage lets the player pick one of five colours (Bedroom, Hallway, Green
  Room, Shop, Red Room) and restricts the whole resulting hand to it.

  **No colour-selective machinery exists anywhere in the codebase** -- a grep
  for `color_selective|prism|color_filter` across `src/` returns zero hits. The
  nearest primitive, `draft.py::_apply_category_bias`, is a *bias* (roll a
  chance, try to swap one card), not a *filter*, and the wiki warns explicitly
  that the two must not be confused.

  Scope as ruled: restrict the deal to the chosen colour, and fall back to the
  published per-colour default triples when the pool is thin. Reserve copies
  are out. The owner rejected filter-only because the wiki says thin pools are
  *frequent* for Green Rooms and Shops, so filter-only would diverge often; and
  rejected full fidelity because it requires relaxing the out-drafting
  invariant in `placement.py`/`rotation.py`, which is load-bearing.

  This clears two findings and one item at once: `secret_passage`,
  `spare_secret_passage__ix138` (which reuses the same handler, as `foyer.py`
  already does for its Spare), and `prism_key`, whose `meta.blocked_on` is
  literally `color_biased_drafting_not_modeled`.

  Separate side finding, since **resolved in PR #190**: both Secret Passage
  ids now carry `rank_gte_2`/`rank_lte_8`, so the rank half is modelled and
  the stateful wing rule is recorded on both records as a named gap. What
  follows describes the state before that:
  `secret_passage.draft_conditions` was `[]` and nothing in `src/` referenced
  the room, so **none** of its published placement restrictions were modelled --
  it cannot be drafted on Rank 1 or 9, and is blocked from wing drafts leading
  north into Rank 8 or south into Rank 2 until another vertical wing draft
  occurs. The rank rule is two existing primitives away; the stateful wing rule
  is not.

- **2026-08-10, the Shrine is built, with five of eight blessings live.**
  Owner. Deposit 1-80 gold, receive one of eight blessings lasting 3-7 days;
  taking the gold back curses you for 2 days instead. The band table, the 8x5
  coin pairs, and all eight blessing effects are fully published.

  Buildable now: Dancer, High Roller, Gardener, General, Berry Picker. Stubbed
  with `meta.blocked_on`: Tinkerer (needs the experiments subsystem), Chef
  (needs Dining Room dishes), Monk (needs grounds drafting).

  **This is save-scoped state** -- blessings survive an attempt wrap, joining
  `stars` and `main_course_bonus`. It needs the `mail_transit_days` shape (a
  raw day count DayChain decays mechanically), not the allowance/stars
  "replaced wholesale" shape: a blessing id, a remaining-days count, a parallel
  curse-days count, and a monk-room key.

  Action space as ruled: expose 8 blessings x 5 durations = 40 actions and
  derive the coin cost, rather than 80 raw donation amounts. Nothing is lost --
  the wiki notes there is little reason to offer an even number of coins except
  to deliberately deprive oneself of gold.

  Two corrections fall out. Our stored `effect_text` is *"Donate money for
  multi-day blessings (out of single-day scope)"* -- not game text at all, but
  a project annotation whose scope claim expired when DayChain landed; the wiki
  infobox reads *"Make an offering, Receive a blessing."* And the curse path is
  the gate to `cursed_effigy_unlocked`, a flag that already exists in
  `config.py` and that today can never be set by play.

  **UNPUBLISHED, do not encode:** the Shrine page source carries a commented-out
  claim that the Veranda *does* incur the curse penalty when its cost is
  bypassed. Drafted by an editor, never published.

- **2026-08-10, the Mechanarium's door count is CONFIRMED fixed at draft.** The
  owner's claim from play -- "the number of doors is set when drafted; it does
  not add doors later for newly drafted engineering rooms" -- is confirmed
  verbatim by the wiki: *"The number and orientation of the doors in the
  Mechanarium are set in stone the moment it is drafted. Drafting more
  Mechanical Rooms after the Mechanarium has been drafted will not cause more
  doors in the Mechanarium to spawn."* Independently corroborated by
  `Template:Interactions/Mechanical Room`.

  This is what makes the room buildable at all. A count that grew would need
  live mutation of a placed room's door mask, and `placed_doors` is written in
  exactly three places, none of which any effect handler can reach. A count
  frozen at draft is an ordinary placement-time decision.

  **Owner ruling: build BOTH the doors and the four diagonal compartments.**

  **The eight Mechanical rooms**, all resolving to our ids: `utility_closet`,
  `boiler_room`, `pump_room`, `security`, `workshop`, `laboratory`,
  `electric_eel_aquarium__ix4`, `mechanarium`. All eight are `category:
  blueprint`, so this needs the multi-valued `extra_categories` field added
  earlier the same day -- and it **also unblocks** `priority_draws.json`'s
  dead `mechanical_or_rotanda` entry, whose own note records that it "matches
  nothing in rooms.json", plus the Gear Wrench and Powered Electromagnet.

- **2026-08-10, a Mechanarium doorway blocked by a neighbour's blank wall does
  not consume its slot.** Owner. The wiki says such a doorway is "skipped" and
  the room "tries again at the next position", without saying whether the slot
  is spent. An **unpublished** note in the page source lists blocking a side
  door as a way to reach the eighth door, which implies the count carries over.

  Act on this cold as: the supporting evidence is commented-out wiki source,
  not published text, so this is the owner's call resting on a hint rather than
  a statement. It makes the Mechanarium's door count depend on its neighbours'
  door masks at draft time, which is worth re-testing in play.

- **2026-08-10, the Southern Cross excludes the Mechanarium, the Chamber of
  Mirrors and every upgrade variant.** Owner, on a divergence found while
  scoping the Mechanarium. Our `priority_draws.json` keys the 40% draw on
  `layout: "cross"`, which sweeps in all 19 cross-layout rooms; the wiki's own
  query excludes the two rooms by name and filters `Type HOLDS "Upgrade"`, and
  the Mechanarium page repeats it independently ("It is also unaffected by the
  Southern Cross").

  Currently inert -- nothing sets `state.southern_cross_active` -- so this is
  wrong data rather than wrong behaviour, which is why it was safe to correct
  in passing.

- **2026-08-10, "gated mechanical arms" is unsourced and should not be
  repeated.** Both CLAUDE.md and `upgrade_disk_mechanarium.meta.simplification`
  describe the Mechanarium's Upgrade Disk as being behind "gated mechanical
  arms". A full pass over the Mechanarium page found **no wiki support for any
  arm mechanic**. The real gate is the diagonal-door spawn threshold: the disk
  sits behind the third diagonal door, which needs three more Mechanical rooms
  than spawned drafting doors, and the Sanctum Key sits behind the fourth.

  Act on this cold as: correct the wording when the compartments land. If the
  phrase came from play rather than the wiki it needs attributing, but nothing
  in the sources supports it as written.

- **2026-08-10, the Laboratory is GO for phases 0-4 only.** Owner. That
  delivers a playable, trainable Laboratory: the data file, the
  offer/choose/start/pause core, the eight pure-resource effects, the
  draft-site triggers and the interaction triggers -- the last of which is what
  the apple-eating trigger elsewhere in this file has been waiting on.

  **Phases 5-8 are explicitly NOT authorised.** They are four separate
  subsystems wearing an experiment costume ("model the Grounds' dig spots",
  "model Pantry stock", "model Dynamic Rarity", "model the Satellite Dish
  unlock chain") and each comes back as its own line item.

  Budgeted costs, all recorded in advance: action space **319 -> 327**, a new
  `Phase.EXPERIMENT_PENDING`, and three observation width changes (a new
  `experiment` key, `phase` 4 -> 5, `carryover` 14 -> 16). See task 19.

- **2026-08-10, the Clock Tower counts Tomorrow rooms PRESENT in the house.**
  Owner, resolving a page that contradicts itself: the infobox says "for each
  Tomorrow room **you draft today**", the prose says "for every Tomorrow room
  **present in the mansion**". The prose wins -- an end-of-day tally over what
  is actually standing, **including the Clock Tower itself**, which our own
  effect text omits.

  The two readings differ whenever a Tomorrow room enters the house without
  being drafted, which the Foundation already does by persisting across days.

- **2026-08-10, the Parlor's box is always the prize box.** Owner. The real
  Parlor is a deterministic logic puzzle the wiki says is *always* uniquely
  solvable, so there is no probability to sample: a perfect solver never opens
  an empty box, a guesser is wrong two times in three.

  The assumed-solved doctrine already governs every other puzzle room -- Mora
  Jai boxes, the room safes, Room 8 -- so the Parlor follows it. Consequence,
  stated rather than discovered later: **the Funeral Parlor's 30-step penalty
  never fires**, because it only applies to opening an empty box.

  This also unblocks the Parlor line without reviving the Wind-up Key, which
  stays removed. `parlor__ix109` ("2 Wind-up Keys") remains a deliberate
  permanent finding.

- **2026-08-10, the Mechanarium is the next big subsystem, and its door count
  is fixed at draft.** Owner, choosing it over the Closed Exhibit and the
  Throne Room: "The number of doors is set when drafted. It does not add doors
  later for newly drafted engineering rooms. Confirm this with the wiki."

  That claim is the crux -- a Mechanarium whose doorways grew as more
  Mechanical rooms were drafted would need live mutation of a placed room's
  layout, which the engine has no mechanism for; a count frozen at draft time
  is an ordinary placement-time decision. **Confirm against the wiki before
  building, and surface any disagreement rather than resolving it.**

- **2026-08-10, a room's colour is a SET of categories, not one value.** Owner:
  "It just means that color needs to be a set of enums instead of an enum.
  Maid's Quarters is another room -- both red and purple."

  `Room.extra_categories` is stored beside the primary `category`, and the
  derived `categories` property is what `is_category()` answers from.
  `counts_as_all_colors` -- a one-room escape hatch added hours earlier -- is
  deleted, because a set makes it unnecessary.

  **The evidence was already in our own data.** `maids_chamber`'s datamined
  `effect_text` reads "Counts as red room AND bedroom" while the record stored
  `category: "red"`, dropping the second membership silently. The raw sheet
  carries a **colour column** distinct from its two type columns, and the
  wiki's `Type=` field is a list -- the Aquarium's reads seven types.

  `categories` is **derived, not stored**, so it cannot drift from `category`.
  The first cut stored it, and `dataclasses.replace(room, category=X)` then
  left membership stale -- caught by a real test that builds a deliberately
  stale room exactly that way.

  Populated for two rooms only: the four Aquariums and Maid's Chamber.
  Enumerating every other multi-category room needs its own pass against the
  wiki's `Type=` lists; guessing would be inventing data.

- **2026-08-10, the Quest Bedroom is a Bedroom, not an objective room.** Owner:
  "Quest Bedroom is a bedroom, not an objective room. It rewards on an
  objective."

  The raw sheet's row settles it: colour **Purple**, type1 **Bedroom**, type2
  Objective. Our ingest let `type2 == "Objective"` override the real type, so
  the room landed as `category: "objective"` and **every Bedroom-counting
  mechanic silently skipped it** -- the per-Bedroom gem cost, Cloister of Mila,
  the Sleeping Mask, bedroom category biases.

  The ingest rule is now narrowed to the two rooms that *are* the objective,
  Antechamber and Room 46, which a separate name check already covered. Nothing
  else in the sheet changes category as a result.

  Act on this cold as: "Objective" in the sheet marks *pays out on reaching the
  objective*, which is a reward condition, not a room type. `objective` as a
  category now means exactly two rooms.

- **2026-08-10, 72 blueprints is correct, not a default bucket.** Owner, on my
  flagging that `blueprint` holds 43% of all rooms and looked like the
  catch-all bug task 15 found: "There are a lot of blueprints. That's why the
  game is called Blue Prince. It's a pun."

  Recorded so the count is not "fixed" later. The earlier task-15 finding was
  genuinely different -- eight rooms carried the **pool name**
  `studio_addition` where a colour belonged, which is not the same as a large,
  legitimate colour.

- **2026-08-10, the Patio spreads exactly one gem to each Green Room.**
  Owner, on a wiki that contradicts itself: the Gems page says it "spreads
  1 gem to **each** Green Room", the general Spread page says every room "has a
  **chance**" of receiving a spread item, and the Spare Patio page says it will
  "**often**" spread a gem to itself. No rate is published anywhere.

  Deterministic wins: every Green Room on the estate at the draft moment gets
  exactly one gem, the Patio itself included, and rooms drafted later get
  nothing. Gem colour is **mechanically inert** -- the wiki states the six
  colours "are purely cosmetic and are lost once the gems are collected" -- so
  the green-to-blue switch under a Conference Room needs no representation.

  The Spare Patio is identical, and unusually this is affirmatively sourced
  four separate ways rather than assumed from matching text. That matters
  because `spare_great_hall__ix139` has text byte-identical to `great_hall`
  and a materially different mechanic; identical text is not evidence.

- **2026-08-10, the Locker Room's key spread reuses the Secret Garden's
  room-count bucket.** Owner. The wiki publishes **no** count and no rate for
  this spread; its only quantitative claim is relative and unanchored -- each
  room has "a slightly lower chance of receiving a key than they do of
  receiving items from other spread effects", with that comparison class
  itself unquantified.

  So the bucket (0-9 rooms -> 3, 10-24 -> 4, 25+ -> 6) is borrowed from the one
  spreader that does have a published formula, marked `confidence: inferred`.

  Act on this cold as: the wiki says keys are **rarer** than other spread
  items, so this borrowed figure probably **overstates** the Locker Room. It is
  a placeholder chosen for consistency, not a measurement -- replace it the
  moment real play gives a number, and do not cite it as sourced.

- **2026-08-10, the Conference Room absorbs a spreader's self-item too.**
  Owner, on an asymmetry in the wiki: the Patio page explicitly says the
  redirected gems "**include the gem that would spread in the Patio itself**",
  while the Locker Room page says "any key that would be spread to **another
  room**", which read literally would leave its own self-key behind.

  Both spreaders behave the same way: everything they would have spread,
  including their own self-item, lands in the Conference Room. The Locker
  Room's wording is treated as loose rather than meaningful.

  Still unstated and still unresolved: **how many** keys land there. The wiki
  gives "a number of keys" with no quantity and, unlike the Patio, not even a
  dependency hint. The bucket above supplies the number by default.

- **2026-08-10, the Conservatory is a Green Room, and the Aquariums count as
  every colour.** Owner, on a Patio spread having to decide what "Green Room"
  means and our data disagreeing with the wiki twice.

  The Conservatory is `MainType=Green Room` on the wiki and was `blueprint`
  here -- a plain data error, now corrected. The four Aquarium records were
  also `blueprint`, with the `counts_as_all_colors` flag ruled in on
  2026-08-10 existing **only in prose**: a repo-wide grep found it in the
  ruling itself and in one "Not modelled" note, nowhere in code or data. It is
  now implemented, because a Patio spread is exactly the category-comparison
  site that ruling described.

  Measured before the fix: a Patio spread would have targeted **24** rooms
  where the wiki implies **29**, understating the payout by up to 5 gems in a
  large house.

  Act on this cold as: a ruling recorded but never implemented is
  indistinguishable from one never made. The `counts_as_all_colors` flag sat
  in the decisions log for a day while every category-keyed mechanic quietly
  ignored the Aquarium.

- **2026-08-10, stars are SAVE-scoped and accumulate toward a reroll trade.**
  Owner, on being shown that stars were still attempt-scoped after the Joya
  ruling: "Stars do not reset between days. They accumulate until you get the
  ability to trade them for rerolls."

  Day-to-day carry was already correct; what changed is the **attempt wrap**.
  `DayChain` no longer resets the star total on wrap, so stars now behave like
  the Cloister of Joya's Main Course bonus. Those two are the **only**
  save-scoped carried values; allowance, `chapel_tithes`, `collected_disks`,
  `lit_targets` and the rest are still attempt-scoped, and one test pins the
  pair together so adding a third is a deliberate edit rather than a slip.

  Act on this cold as: this settles stars but **not** the wider question. The
  same argument plausibly applies to applied Upgrade Disks, which the game
  treats as permanent progression and which we still clear on wrap. That is
  unasked and unresolved -- do not change it on the strength of this entry.

  **A sink now exists that we do not model.** The owner names trading stars for
  rerolls, which is a spend the sim has no representation for; the wiki says
  only that stars "are generally never spent" and gate which constellations
  appear. So the counter currently accumulates with nothing to spend it on,
  and any measurement of star totals is an upper bound on what a player would
  actually be holding. Worth its own research pass before the reroll trade is
  built.

- **2026-08-10, the Geist Bedroom's dice are picked up inside the room.**
  Owner: "Dice are on the table inside. You have to enter to pick them up."
  Confirms the entry-time reading the wiki only hinted at with the word
  "spawns", and matches every other resource grant in the engine. No change
  was needed; the open question is closed.

- **2026-08-10, the Cloister of Joya's Main Course bonus is SAVE-scoped, not
  attempt-scoped.** Owner: "permanently increases steps on the Dining Room's
  main course for all days going forward in the save game, similar to an
  allowance."

  **This corrects what shipped.** It was first implemented as attempt-scoped,
  resetting to the base preset on `DayChain`'s wrap like every other carried
  total, and flagged in task 20 as an assumption pending confirmation. It now
  survives the wrap.

  **It is the only carried value that does.** `allowance`, `stars`,
  `chapel_tithes`, `collected_disks`, `lit_targets` and the rest all reset to
  their base preset on wrap, and a test pins that this exception did not
  quietly loosen them.

  Act on this cold as: this opens a real question the ruling does not settle.
  Several other things the game treats as permanent across resets --
  **stars** in particular, which the wiki calls "a permanent resource" that
  "do not reset between each day", and arguably applied Upgrade Disks -- are
  attempt-scoped here. That inconsistency is now visible rather than uniform.
  **Do not change any of them on the strength of this entry**; ask, because
  "similar to an allowance" was said of Joya specifically and our allowance
  does reset on wrap.

- **2026-08-10, the Speakeasy is a no-op and is exempt from the worklist.**
  Owner: "speakeasy is a no-op because we assume they can solve puzzles."

  `speakeasy__ix10`'s effect ("Basic Addition") only makes the Dartboard Puzzle
  easier -- one board instead of two to five, one ring, two numbers, addition
  only. The puzzle is not modelled and its reward is assumed won, so an easier
  puzzle pays exactly what the Billiard Room already pays.

  Recorded through a new `_AUDIT_DOCTRINE_EXEMPT_IDS` table rather than left on
  the worklist, because "we model this as nothing, deliberately" is a claim
  worth stating once, not a gap worth re-triaging every pass. That is now the
  **fourth** exemption channel, alongside locks.json, hand-written Python
  branches, and texts that merely restate a field.

- **2026-08-10, the engine provides capabilities and rooms declare effects.**
  Owner, raised as a concern about "two radically different paths for room
  definitions" and settled in the same exchange: **tabular data stays tabular;
  complex functions belong in code.**

  So `rooms.json` is NOT converted to Python. Four reasons, recorded so the
  question does not reopen: it is **generated** by `tools/ingest_sheet.py` from
  the datamined dump, and converting it would break the re-ingest path that
  absorbs a future datamine and carries `meta.source`/`meta.confidence`; the
  content is densely tabular (169 rooms, with 47 carrying effects tags, 43
  flags, 37 draft conditions, 32 dig spots, 31 guaranteed items);
  `validate_data.py`'s cross-record schema and referential checks are natural
  over one document and awkward over 169 modules; and
  `test_ingest_overrides.py`'s round-trip guarantee only exists because the
  data is data.

  What the ruling *does* change is where **behaviour** lives -- see task 21 for
  the three layers, the measured starting point, the enforcement test and the
  sequencing.

  Act on this cold as: the inconsistency the owner named is real but sits one
  layer below where it first appears. It is not JSON versus Python -- it is
  that Python room behaviour is scattered across 20 modules while only 27 rooms
  have a discoverable module of their own. The fix is an invariant ("no engine
  module branches on a room id"), not a file-format migration.

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

- **2026-08-09, features are built to be PLAYED, not to be reachable by the
  policy.** Owner: "I realize that the RL algorithm is unlikely to reach that
  stage of the game on its own. That's why I'm going to play the game myself to
  teach it some expert judgement. I need you to implement the features so I can
  teach it."

  **This retires the objection raised one entry above** against modelling the
  Inner Sanctum. That objection was that `P(room 46)` is 0.000 over 400 measured
  days, so a Sanctum gated behind Room 46 would be content no policy can enter.
  The premise was that the policy has to get there unaided. It does not: the
  owner reaches it by playing, records the day through the Play tab, and the
  behavioural-cloning pipeline turns it into training signal.

  So **"unreachable by the current policy" is not a reason to defer a feature.**
  It is a reason the feature has to exist *before* the demonstrations that teach
  it, not after.

  **What this does change is the acceptance bar.** A feature is not done when the
  engine models it correctly -- it is done when the owner can *operate* it in a
  recorded session. Concretely, every feature of this kind needs:

  - a **player action** in `env/actions.py` with a masking site, not just engine
    state that some other code path mutates;
  - that action **exposed in the Play tab**, since that is where demonstrations
    are recorded;
  - the resulting day to **replay clean** (`divergence=None`), which is what
    makes a demo usable as training data.

  A correct mechanic with no action to drive it is unteachable, and the gap is
  invisible to every test that drives the engine directly.

  Act on this cold as: **ask "can the owner do this in a recorded session?"
  before calling a feature complete.** The three outer-area bugs found on
  2026-08-08 were all of exactly this kind -- the engine was right and the
  player could not act.

- **2026-08-09, all eight Sanctum Keys require Room 46, and simply do not
  spawn before it.** Owner, resolving the discrepancy surfaced two entries
  above: "All eight keys require reaching Room 46 for the first time. They
  simply do not spawn."

  **This overrides the wiki**, which states that condition for exactly one key
  (*"This Sanctum Key only spawns once Room 46 has been reached at least
  once"*) and says of the others only that they are *"usually discovered around
  the same time Room 46 has been reached for the first time."* Owner play
  outranks the wiki; the conflict is recorded here rather than resolved
  silently, so a later wiki edit does not look like it contradicts a bug.

  The gate mechanism already exists: `room46_reached` is a permanent carry-over
  flag, set on first arrival and carried by `DayChain`. No new state is needed
  for the gate itself -- keys check it at spawn time.

  **The consequence is deliberate, not a side effect.** Every Sanctum Key, all
  eight Sigil Chambers, and the +16 allowance behind them are unreachable until
  Room 46 is first reached -- and the measured `P(room 46)` is 0.000. That is
  acceptable under the ruling one entry above: the owner reaches Room 46 by
  playing, and the recorded day teaches the policy. The content exists so it can
  be demonstrated, not because the current policy will stumble into it.

  Act on this cold as: this is the first feature in the project built for the
  demonstration pipeline rather than for the policy's own exploration. Judge it
  by whether the owner can operate it in a recorded session, not by whether any
  measurement over untrained play ever exercises it -- none will.

- **2026-08-09, every Mora Jai box holds a +2 allowance token.** Owner, on the
  six locations whose contents the wiki leaves unstated: "They all include +2
  allowance tokens." So the pattern holds across all ten standard locations, and
  the earlier refusal to guess them is now resolved by ruling rather than by
  inference.

  The complete set, with the allowance each contributes once per save:

  | location | boxes | allowance | status |
  |---|---|---|---|
  | Cloister | 1 | +2 | landed |
  | Master Bedroom | 1 | +2 | landed |
  | Solarium | 1 | +2 | landed |
  | Trading Post | 1 | +2 | landed |
  | Closed Exhibit | 1 | +2 | landed |
  | Tomb | 1 | +2 | ruled here |
  | Lost & Found | 1 | +2 | ruled here |
  | Tunnel | 1 | +2 | ruled here |
  | Throne Room | 1 | +2 | ruled here |
  | Underpass (**area node**) | 1 | +2 | ruled here |
  | Inner Sanctum (**area node**) | **8** | **+16** | ruled here |

  **A fully explored save banks +36 allowance from Mora Jai boxes alone**, which
  is 36 coins at the start of every subsequent day, before any repeatable source
  (Cloister of Lydia, Trading Post trades, Jack Hammer digs, Casino roulette).
  That is a large permanent economy, and it is worth watching the first time a
  policy is trained against it: allowance is unspendable income that arrives
  before any decision is made, so it shifts what an early-day gem or key purchase
  is worth.

  **Two of the eleven cannot use `guaranteed_in`.** The Underpass and the Inner
  Sanctum are area nodes, not rooms, so a room record cannot reach them; the
  Abandoned Mine's Upgrade Disk solves the same problem through
  `special_items.py::on_area_arrival`, called from `Game.travel_to`.

  The endgame sets stay excluded: Aries Court's 8 boxes and Rough Draft's 46
  contain "a note instead of an Allowance Token" and are not permanently opened.

  Act on this cold as: the Inner Sanctum's eight boxes are **+16 of the +36**,
  so nearly half this economy sits behind Room 46 and the eight Sanctum Keys.
  Do not read a measured allowance figure from untrained play as representative
  -- none of it is reachable until Room 46 is.

- **2026-08-09, do not work on making Room 46 reachable by the policy.** Owner,
  asked directly whether the lever-room scarcity behind `P(room 46) = 0.000`
  should become a work item now that the Inner Sanctum, +16 of the +36 allowance
  and Room 8's reward all sit behind it. Answer: no -- keep authoring features so
  there is more to demonstrate. The 11.0% lever-room measurement stays a recorded
  fact rather than a task.

  This follows from the "features are built to be PLAYED" ruling: the owner
  reaches the late game by playing, so content value does not depend on the
  policy finding it unaided.

- **2026-08-09, work order and stop condition for unattended runs.** Owner, at a
  save-state interview: fruit items first, then Room 8 and
  `quest_bedroom__ix71`, then the Mail Room's three delivery variants, then drive
  off the divergence worklist cheapest-first. **When the queue empties, take the
  next item and keep going** -- do not stop and wait.

  Fruit is first because it is the only queued item that unblocks two
  owner-reported bugs at once: the Pantry's guaranteed fruit and the Secret
  Garden's spread, the latter being a lever room.

- **2026-08-09, `room_hook`'s `inherit=` parameter is removed.** It has had zero
  users across the Cloister, Sanctum and Closet features, all of which plausibly
  could have wanted it, and its docstring cites "the Boudoir's safe" as the
  example -- which is in fact a repeated data `grant`, not an inherited handler.
  So the parameter is unexercised and its only documentation points at code that
  does not exist.

  This is the `ALT_BASE` shape from 2026-08-07: an unused affordance that
  survives long enough to be mistaken for a working feature. Re-add it when
  something genuinely needs inheritance, with a real example.

  Owner selected both "tighten the docstring" and "remove entirely"; removal is
  the decisive reading and subsumes the other. Fall back to tightening only if
  removal turns out to be load-bearing.

  **Note the asymmetry this preserves**: the divergence audit's kind-1 check
  deliberately does NOT treat inherited coverage as authorship, and that
  reasoning stands on its own -- it is about what an inherited handler can
  demonstrate, not about whether the parameter exists.

- **2026-08-09, trophies are NOT modelled -- they are achievements only.**
  Owner, asked directly whether Room 8's Trophy 8 should be a flag or an item:
  "For Room 8, ignore the trophies. They are only intended as achievements."

  This **unblocks Room 8**, which was the one `[BLOCKING]` item in the queued
  work order. Room 8's completion reward is Trophy 8 plus Allowance Tokens, one
  fewer token once the trophy is held; with trophies out of scope, the trophy
  half is simply not represented and the "one fewer once held" clause becomes a
  plain first-solve-versus-later-solve distinction on the token count. No
  trophy flag, no trophy item, no trophy observation dimension.

  Act on this cold as: an achievement is not game state. Do not add a trophy
  concept later to "complete" Room 8 -- the reward that matters to a policy is
  the allowance, and that is already modelled (`GameState.allowance`).

  Note this also retires `tests/rooms/test_room_8.py`'s premise. Its docstring
  asserts the room grants nothing because "Allowance Tokens feed the allowance
  system, which this sim does not model" -- allowance has been modelled since
  the 2026-08-09 allowance ruling, so that test now pins known-wrong behaviour
  and must be replaced rather than kept green.

- **2026-08-09, apple = 2 steps, orange = 5 steps, banana = 3 -- the wiki
  AGREES with the owner.** Recorded because the numbers were reported from play
  and then independently confirmed, so neither source needs re-checking. The
  Food page states each value directly, and the Pantry page derives the same
  three from a note puzzle ("one apple, one banana, and one orange grant 10 in
  total"). Our data already carried banana = 3.

- **2026-08-09, the Secret Garden spreads apples and oranges, uniformly -- NOT
  bananas.** Owner, from play, asked to check TFMurphy's datamining first.
  Checked: `tools/raw/tfmurphy_room_table.md` is a room table only and carries
  the effect *text* with no spread mechanics at all, and the datamined box
  republished on the wiki's Secret Garden page gives only the **total** fruit
  count -- room-count bucket plus soil bonus, capped at 10 -- and never a
  per-type split. **So the datamining does not settle it in either direction.**

  **This overrides the wiki**, whose Food page states: *"The effect of the
  Secret Garden spreads all three fruits."* Owner play outranks the wiki; the
  conflict is recorded here rather than resolved silently, so a later wiki
  citation does not look like it contradicts a bug. Each spread fruit is a
  50/50 apple-or-orange roll, mean 3.5 steps.

  Note the one place bananas ARE datamined into a Secret Garden outcome is the
  Conference Room case, and even there the fixed payout is **4 apples + 3
  oranges** with no banana -- which is consistent with the owner's account and
  mildly against the wiki's prose.

- **2026-08-09, soil quality is a flat Good (+4) everywhere until a real map
  exists.** The Secret Garden's spread total adds a soil term (Poor +2, Good
  +4, Rich +6) keyed to the cell it was drafted on. **That map is not published
  anywhere in wiki text** -- it exists only as an image in the Gardener's
  Logbook, and "barren", named on the House page as the low end of the range,
  has no published bonus value at all.

  Owner decision, on interview: encode a single flat +4, marked
  `confidence: inferred` in data, rather than block the feature or invent a
  12-cell map. The Secret Garden is wing-only across ranks 3-8, so a real map
  needs just 12 cells and can replace the constant with no code change.

  Act on this cold as: every Secret Garden spread total measured before a real
  soil map lands is an **estimate, not a bound** -- unlike the open stub gates,
  it can err in either direction (a Poor cell would spread 2 fewer, a Rich cell
  2 more).

- **2026-08-09, Room 8 pays 2 Allowance Tokens on the first solve of an
  attempt and 1 on every later solve.** Owner, on interview, following the
  trophies-are-achievements ruling. The wiki's real discriminator is trophy
  *possession*, not solve ordinality: *"If Room 8's puzzle is solved without
  ever collecting the trophy, it awards two Allowance Tokens on every
  completion."* With no trophy concept the sim cannot tell those branches
  apart, so the owner picked the reading that matches how a real player
  behaves -- the trophy is taken on the first solve, so the first solve pays
  +4 allowance and each later one +2.

  Room 8 is **repeatable per draft**, not once per save: *"Unlike the Gallery,
  Room 8 resets each time it is drafted even after being solved."* Multiple
  Key 8s allow multiple simultaneous Room 8s, each paying.

  The first-solve flag is per **attempt**, matching every other carry-over.

- **2026-08-09, `room8_placement` was wrong and is widened to any Rank-8
  cell.** Owner, on interview, shown the mismatch. `placement.py` permitted
  Room 8 on exactly **two cells** -- rank 8 col 4 entered northward, rank 8
  col 0 entered southward -- and its comment stated that as the rule. The wiki
  says Key 8 works on *"any locked door that leads to a room on Rank 8"*; the
  two cases the code whitelisted are the wiki's enumeration of when the room is
  **mirrored** (*"resulting in the corner room pointing left instead of
  right"*), not of where it may be placed.

  The decisive evidence is the wiki's own "reliable" route: Room 8 *"can be
  reliably drafted from the far door in the Great Hall, as it is always
  locked"*. The Great Hall is `layout: cross` with no draft conditions, so it
  sits in any column including the centre three -- under the old rule that
  route was impossible. Room 8 was very nearly undraftable, which is why the
  reward being unmodelled never surfaced in play.

  Act on this cold as: a `draft_conditions` tag that encodes an *orientation*
  rule as a *legality* rule silently deletes most of a room's placements. The
  mirroring belongs in the orientation layer, not in
  `satisfies_draft_conditions`.

- **2026-08-09, the `carryover` observation vector grew from 13 to 14.** Recorded
  under the standing rule that model correctness outranks observation-space
  stability while no run is live, **but that every width change is written
  down**. The new entry is `room8_solved`, added to
  `DayChain._CARRYOVER_KEYS` so Room 8's first-solve reward survives the day
  boundary.

  `env/obs.py` derives both the Box shape and the fill order from
  `len(DayChain._CARRYOVER_KEYS)` and `sorted(...)`, so the width moved with no
  edit to `obs.py` at all. That is convenient and also the hazard: **adding a
  carry-over flag silently changes the observation space.** Act on this cold as:
  any PR touching `_CARRYOVER_KEYS` is an observation-space change, whether or
  not it touches `env/`, and it invalidates every checkpoint trained before it.

  No run was live, so nothing was lost. Cumulative since the last training run:
  this is the only width change.

- **2026-08-09, the Mail Room's package contents ARE fully datamined -- the
  "implement timing only" fallback does not apply.** This retires the standing
  `[ASSUMABLE]` open question, which assumed the contents were "a randomised
  weighted tree" that might not be pinnable. The wiki publishes a datamined
  per-slot algorithm with exact probabilities: three independently rolled
  slots, slot 2 with a 50% chance of 2 gems, slot 3 conditioned on what slot 2
  produced. Freight's construction is deterministic given availability. Every
  item involved already exists in `special_items.json`.

  Only one number is genuinely unsourced -- see the Freight entry below.

- **2026-08-09, the base Mail Room's own effect text is wrong, and the wiki
  wins.** The in-game string, faithfully copied into
  `mail_room.meta.effect_text`, says a package "will be delivered here the day
  after drafting this room". The wiki contradicts it flatly: *"Despite the
  wording of the Mail Room's effect text, it does not have to be drafted the
  day immediately after placing the order; the package can wait any number of
  days for the Mail Room to be drafted again, and cannot be 'missed'."*

  Owner decision, on interview: model the wiki's mechanic. So the base Mail
  Room is **not a countdown at all** -- it is a persistent per-attempt state
  (`empty` -> `awaiting delivery`) advanced by the next draft of a Mail Room,
  whenever that happens.

  Act on this cold as: an implementer coding to `effect_text` alone would build
  a one-day timer that loses the package, which is a strictly harsher room than
  the real one. The card text is a game string, not a spec.

- **2026-08-09, No Contact Delivery arrives as a day-start inventory
  injection.** Owner, on interview. The wiki has the package sitting "immediately
  to the right of the starting position" in the Entrance Hall, openable. Rather
  than model a physical container, the contents are injected through the
  existing `GameConfig.starting_items` carry vehicle.

  The simplification, stated plainly: the player cannot decline or fail to
  collect a No Contact package, whereas in the real game they could in principle
  walk past it. Since the sim has no "decline the loot" concept anywhere, that
  difference is unobservable today.

- **2026-08-09, the Mail Room's Dynamic Rarity effect is DEFERRED, explicitly.**
  A waiting package sets the Mail Room's rarity to Commonplace for the day,
  which makes the delivered room far easier to draw again -- a real strategic
  effect, not flavour. `decks.py` has no rarity-override channel of any kind, so
  building it is its own piece of work touching the draft hot path that
  `test_draft_stats.py` guards.

  Owner decision, on interview: ship the delivery mechanic without it and
  record the gap here so the omission is visible rather than silent. Act on this
  cold as: any measurement of how often a delivered package is actually
  collected is an **under**estimate until this lands.

- **2026-08-09, Freight's four resource items are a uniform 1/3 across the three
  configurations.** The wiki states the set -- 4 keys, or 2 keys + 2 gems, or 4
  gems -- and publishes **no weights**. This is the single genuine gap in an
  otherwise fully datamined algorithm. Owner decision, on interview: encode a
  uniform third each, `confidence: inferred`, with a note saying only the set is
  sourced. Replaceable by a data edit the moment a real weighting appears.

- **2026-08-09, the `mail` observation went 2 -> 3 wide, a SECOND width change.**
  Recorded under the standing every-width-change rule, and recorded as a
  mispredicton: the base Mail Room PR sized the key at 2 (`[cycle, transit
  days]`) explicitly claiming that would make it "one width change, not two".
  That was wrong. No Contact Delivery's outstanding order is genuinely
  independent of the cycle -- it is placed on every draft and never uses the
  two-state machine -- so folding it into the cycle code would have made one
  field mean two things.

  Final shape: `[cycle code, transit days remaining, No Contact ordered]`.
  Slot `[2]` reads the **forward-looking** flag (drafted today, package lands
  tomorrow), not "a package arrived this morning" -- these keys exist so `V(s)`
  can price a cross-day investment, and the investment is the order, not the
  already-collected payout.

  Act on this cold as: reserving a slot for a *known* future field works (slot
  `[1]` absorbed Freight with no further change); reserving against an
  *unanalysed* one does not. Cumulative since the last training run: two width
  changes, `carryover` 13 -> 14 and `mail` 2 -> 3.

- **2026-08-09, lazy `configure()` seeding has now caused three separate bugs.**
  `special_items.configure()` is what seeds config-carried running values onto
  `GameState`, and it is guarded to run once per episode. Its call sites have
  repeatedly been too narrow:

  - PR #122: reachable only from `on_enter`, so a day spent travelling off-grid
    never seeded the one-time gates and area grants re-paid.
  - PR #134: not called from `shops.carryover()`, so a day that never entered a
    drafted room reported an unseeded `mail_cycle` at day end and silently
    cancelled an outstanding Mail Room order.
  - PR #136: not called at reset, so a day's **first** observation reported the
    field default rather than the carried value -- an agent cannot learn from a
    state vector that lies at the start of every day.

  Fixed at the root in #136: `Game.reset` now calls it directly, alongside every
  other field it seeds from config. Act on this cold as: **a lazily-seeded
  value is a bug waiting for a code path that reads it early.** Anything added
  to `configure()` from now on is seeded at reset and needs no new call site --
  do not re-introduce a lazy one.

- **2026-08-09, the Mail Room's cycle state is shared across all three variants
  -- a known gap, not fixed.** `GameState.mail_cycle` and `mail_package_cell`
  are a single global slot. If an `awaiting` cycle placed by one variant is
  still standing when a *different* variant is drafted, that variant delivers
  its own contents against the other's order.

  Narrow: it needs two different Mail Room upgrades applied across one attempt,
  and only one Mail Room variant is normally active at a time. Recorded rather
  than patched so it is not rediscovered as a surprise. Fixing it means keying
  the cycle by variant id, which is only worth doing if upgrade-swapping turns
  out to be common in real play.

- **2026-08-09, the Mail Room family is fully modelled: 7 audit findings -> 0.**
  All four records (`mail_room`, `__ix89` Same Day, `__ix90` No Contact,
  `__ix91` Freight) carried both kind-1 and kind-2 findings. The worklist went
  79 -> 72 across four PRs. Note what cleared them: **a registered `room_hook`
  at the record's own id clears BOTH kinds** -- the mechanic is pure Python, and
  no `rooms.json` `effects` entry was added for any of the four.

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
