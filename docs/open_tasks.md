# Open tasks

Features the project owner identified while reviewing the special-items PR stack
(2026-07-26). These are NOT in `docs/plan.md`'s delivered set — each needs its own
design pass. Ordered roughly by how self-contained they are.

The file reads in three parts: **open tasks** (numbered sections), then the
**open owner questions** in task 23, then the **decisions log**, which is always
the last section. Lessons about *how to work* are not here; they are in
[`process.md`](process.md).

## The decisions log is a waiting room, not an archive

**A ruling belongs in the design document that owns the mechanism, or in a
comment beside the code it governs — never here once the work has landed.**
Architectural decisions spanning many parts of the codebase go to a design doc;
a decision that explains why one function does something surprising goes in that
function, not in a doc and not here. A ruling whose work has shipped and whose
rule is already stated elsewhere is **deleted**; git keeps it.

What is left in the log is therefore only rulings for work that is **not yet
built**, where there is no code to comment and stating the rule in a design doc
would describe behaviour the engine does not have. Each one leaves the log the
day its work lands.

A completed task is deleted too, rather than marked DONE — but read it for live
remainders first. Sections have twice hidden real content under a DONE heading.

## How to cite this file

**An entry here records what was true when it was written; the topic docs
record what is true now.** Readers have repeatedly taken the first for the
second, and four false claims propagated out of this file in a single day
before a fifth was caught.

So a cross-reference in `src/`, `tests/`, `tools/`, `data/` or another doc must
point at **the doc that owns the rule**, never at the log. `open_tasks.md` may
be cited for exactly two things:

- a **numbered open task**, cited by number — `open_tasks.md` task 8;
- an **open owner question**, cited by its letter within task 23.

Anything else — a mechanic, a magnitude, a ruling, a doctrine, a deliberate
divergence — cites the topic doc that owns it. If nothing owns it yet, that is
the signal to create or extend a topic doc, not to cite the log. In particular
**do not write "owner ruling, see the decisions log"**: state the rule in the
topic doc and cite that, because the reason a rule holds is not the same fact
as who said it.

Current owners:
[`scoping-and-carryover.md`](scoping-and-carryover.md) (persistence scope and
the carry channels), [`doctrine.md`](doctrine.md) (sources of truth,
assumed-solved, trophies, the acceptance bar),
[`architecture.md`](architecture.md) (data-vs-code ownership, the registries,
the id allowlists), [`rl-environment.md`](rl-environment.md) (observation and
action spaces, the width register, replay and measurement discipline),
[`luck.md`](luck.md),
[`locking.md`](locking.md), [`rewards.md`](rewards.md) (reward shaping),
[`foundation-design.md`](foundation-design.md), [`areas.md`](areas.md),
[`rooms.md`](rooms.md) (per-room mechanics, the spread effects, the Mail
Room cycle),
[`drafting.md`](drafting.md) (the whole draft pipeline, concealment, redraws),
[`special-items-schema.md`](special-items-schema.md) (the
`special_items.json` data contract and its status flags),
[`special-items-behaviour.md`](special-items-behaviour.md) (per-item and
per-system item rules, commerce, containers, ignition),
[`experiments-design.md`](experiments-design.md),
[`upgrade-disks-design.md`](upgrade-disks-design.md),
[`greedy-strategy.md`](greedy-strategy.md), [`process.md`](process.md).

## 8. Model the Casino games

The Casino is a room of gambling minigames (slot machine, roulette). Two pieces:
1. **Expected value** for the reward function, so a policy can price entering.
2. **Outcome simulation** so those rewards actualize — seeded rolls, per-game odds
   in data.

Ties into the Broken Lever (its golden slot machine gives 5 bonus spins instead of
3) and the Allowance Token (roulette is a repeatable source).

**What already exists, so this reads as "the gambling mechanic is unmodelled"
rather than "nothing exists":** the Casino grants a guaranteed die on first
entry as a stand-in for the unmodelled spins (`rooms.json`'s `casino` record);
the Broken Lever's `slot_bonus` effect is wired to it; and `shops.py`'s
`_DISCOUNT_EXEMPT_SHOPS` already exempts the Casino from the Coupon Book's
blanket discount.

## 15. Room-behaviour fidelity: audit every room against the wiki

The divergence detector (`tools/validate_data.py::find_divergences`) and the
per-room test split are both in place; the detector currently reports 0
findings. **That means no room's behaviour is entirely absent from the
codebase — it is a presence check, not a correctness check.** It compares
`meta.effect_text` against `effects`/`items.guaranteed`/the room-hook
registry, so it cannot see a partially-implemented effect or a wrong
magnitude, only a room whose text claims something and every modelling
channel is empty.

**Test coverage is what remains incomplete.** 51 of 80 base-pool rooms have a
dedicated `tests/rooms/` file, out of 87 files in total. Of the 29 without
one, 4 carry an empty `meta.effect_text` and so have nothing to pin -- the
absence of a file is the record that a room needed none. `security` is the
one room with real behaviour and no file of its own, deliberately: its
offline-unlock, control-room gating and security-door truth table are pinned
in `tests/test_locks.py`, and its disk terminal in `tests/test_upgrade_env.py`.
Separately, `validate_data.py`'s
`_AUDIT_DEFERRED_EXEMPT_IDS` already carries 5 rooms/subsystems the audit
deliberately does not chase, each with a stated reason (`pump_room`,
`closed_exhibit`, `root_cellar`, `throne_room`, `parlor__ix109`).

**Do not start a training run mid-audit** — room behaviour changes what the
policy learns. The rule, and the two runs discarded for breaking it, are in
[`process.md`](process.md).

## 21. Capability architecture: the engine provides, rooms declare

PARTIAL, and the ratchet is not ratcheting. The doctrine, the three layers and
the enforcement invariant are stated in [`architecture.md`](architecture.md).
Commerce (the pattern-setter), containers, digging, and the Antechamber levers
have landed as capabilities.

`tests/test_room_id_allowlist.py` (PR #188) AST-scans `engine/*.py` and
`engine/effects/*.py` for string literals equal to a real room id, against a
per-module allowlist. It fails in **both** directions: a new literal in an
unlisted module, and an allowlisted id that no longer appears. That makes it a
ratchet against regrowth, but **the allowlist itself has sat flat at 78 pairs
across 11 modules since the test landed**, because — unlike the item side's
`ITEM_DEBT` split, which `ITEM_DEBT_CAP = 1` enforces as a genuine ratchet —
there is no cap test on the room side. Nothing fails when the count stays
where it is; only regrowth is caught. About **45** of the 78 pairs are genuine
per-room behaviour branches that a capability registration would remove; the
rest are architecture (fixtures, named conditions, id-prefix families) that
should stay.

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

### Current per-module counts

`ALLOWLIST` in `tests/test_room_id_allowlist.py`, largest first: `draft.py`
15, `upgrades.py` 15, `shops.py` 14, `game.py` 11, `experiments.py` 6,
`placement.py` 6, `special_items.py` 5, `effects/tier1.py` 2, `decks.py` 2,
`locks.py` 1, `state.py` 1 -- 78 total across 11 modules. `upgrades.py` (the
disk selection tables) and `placement.py` (named conditions and fixtures)
legitimately name rooms and are not migration targets; `env/actions.py` /
`env/obs.py` / `web/play.py` / `cli/render.py` / `config.py` / `rl/train.py`
name rooms too but sit outside the scan entirely (env and UI wiring, presets).

**51** rooms have a discoverable `effects/rooms/<id>.py` module today.

### Sequencing

Capability by capability, each PR independently green, cheapest first.
Done: commerce (the pattern-setter), containers and digging, the Antechamber
levers. **Locks need nothing** -- `locks.py` reads `locks.json` and carries no
room-id branch at all, which the allowlist confirms.

Next, largest first: `shops.py`'s stock builders, `draft.py`'s named-constant
branches, `special_items.py`'s remaining ones. The two day-end branches in
`game.py` (`break_room__ix11`'s keycard pulse, `clock_tower`'s tally) want one
shared `Capability.DAY_END` between them -- `Hook.ON_DAY_END` only fires for
the room the player is standing in, not grid-wide, so the Clock Tower's tally
needs its own grid-wide dispatch regardless of which capability carries it.

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

**None of this work touches `env/`.** It moves where behaviour lives, not
what an agent observes or can do, so no phase of this migration is a retrain
trigger.

## 24. Reward calibration

All shaping constants (`special_item_values`, `PATHS_ONE_PENALTY` /
`PATHS_ZERO_PENALTY`, scepter bias) are deliberate knobs, set without real
multi-day run data behind them. Calibrating them needs training statistics
from actual attempts, which do not exist yet.

## 23. OPEN OWNER QUESTIONS

The single home for questions that need an owner ruling before the work they
block can start. **Nothing is open here right now**; a new question is added as
a lettered item, and cited from elsewhere by that letter.

Answered questions are **deleted from this section, not annotated** -- a
question left in a questions list reads as open whatever note sits under it.
When one turns out to be answered, delete it here and record the answer in the
doc that owns the rule. **Do not restate the count in prose elsewhere**: this
header has already been wrong once, because a question was removed and the
count above it was not.

## Decisions log

Every entry here is held for one reason only: **it specifies work that is not
built yet.** Two subjects account for most of them.

- **The Conservatory** — undraftable today (`rarity: null`, `gem_cost: 0`, no
  `counts_as_drafting_room`), so its reachability build, its datamined filter
  chain, and the "all three, and a no-op click counts" rulings have no code to
  sit beside.
- **The constellations** — the width has landed and
  [`rl-environment.md`](rl-environment.md) owns it; what remains is the
  per-constellation build.

Plus two standalone unbuilt items: the **Mail Room's Dynamic Rarity** package,
now unblocked by `set_dynamic_rarity`, and the **jack hammer's four unsourced
vault keys**, which need a research pass before the table is rebuilt
(cited from [`special-items-behaviour.md`](special-items-behaviour.md)).

Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

- **2026-08-14, OWNER RULINGS x4: the Conservatory is fully specified for
  reachability. Nothing in that build is now blocked.**

  1. **Fix BOTH `rarity` and `gem_cost` to the wiki: `unusual` and `1`.** The
     repo's `rarity: null` was a misreading of *"the Conservatory cannot have
     its rarity changed"* -- which excludes it from its own re-rarity list, not
     from having a rarity. **This is a fidelity change, not a typo fix:**
     `gem_cost: 1` moves the room out of the free decks and into the **gem**
     decks, changing which slot can draw it and whether a gem-poor player can
     afford it.
  2. **Finding the floorplan REQUIRES A HELD SHOVEL.** *(Rejects the
     recommendation, which was unconditional-on-arrival following the Throne
     Room and Treasure Trove precedent.)* The wiki calls it a **hidden dig
     spot** at the campsite, and the owner ruled the dig is real. **The sim
     models no off-grid area digging at all today** -- dig tooling exists only
     for room dig spots -- so this introduces the first one. Scope it as a
     shovel-held condition on campsite arrival, not a new digging subsystem.
  3. **`pool` gets a NEW value, `found_floorplan`** -- not a reuse of
     `studio_addition`. Seven of the eight Found Floorplans currently sit under
     `studio_addition` because the repo conflates the two concepts; the new
     value stops entrenching that, and **re-filing the other seven is a
     separate later pass**, not part of this build.
  4. **Available from the NEXT day onward**, not the same day. `build_decks`
     runs at day start, so the deck is already built when the floorplan is
     found. Matches the Treasure Trove and Throne Room comments, and needs no
     `inject_rooms` call.

  5. **ADD `counts_as_drafting_room`.** The wiki types the Conservatory as a
     Drafting Room and its page carries that interaction template, so drafting
     it grants a Classroom redraw and a Dormitory step grant. **This is a real
     behaviour change on all-unlocks configs**, not just a tag.
  6. **Fix `priority_draws.json`'s decayed Morning Room clause in this work**,
     not in a later sweep. It currently tells the reader that the Bacon & Eggs
     prerequisite is **unbuilt**; it is built (`effects/rooms/nook.py` sets the
     `breakfast` condition and injects the room) and only the forced draw
     itself is missing. The note sits in the same file and block the
     Conservatory's forced-draw entry lands in.

  **CORRECTION to this entry as first written.** It recorded
  `counts_as_drafting_room` as **NOT added**, on the reading that an unselected
  option in a multi-select meant "declined". **That reading was wrong** -- the
  question was presented as multi-select and read as pick-one, so the omission
  carried no meaning. Re-asked as a single choice and answered **yes**.
  **The offering was the defect, not the answer**: a multi-select that looks
  like a radio group silently converts "I picked the one I cared about" into
  "I declined the rest". Ask one decision per question.

- **2026-08-14, OWNER RULINGS x8. The constellation width is now SETTLED at
  `N_ACTIONS` 442 -> 457, and two live defects are cleared to fix.**

  **TRADING**
  1. **Adopt the wiki's same-item collapse** for Sanctum Keys and Upgrade
     Disks. A trade-offer identity key (game item, not sim id) applied in
     `shops.py::trade_offers` **before the sort**. Takes tier 5's worst case
     from 12 offers to 5. **No obs-width change, so no retrain trigger** --
     and it makes "raise the 8-offer cap" stop being urgent.
  2. **Make the Keycard tradeable**, via the precedent that already exists:
     the Lost & Found steal path special-cases `keycard.held`/`keycard.steal`
     around the generic inventory logic, because the keycard lives in
     `state.has_keycard`, not `state.inventory`. Trading never got the
     equivalent. **A naive fix -- deleting the three exclusion checks -- would
     let a player give it away and KEEP door access**, and would write a
     phantom inventory entry no door code reads. Use the special-case shape.

  **CONSTELLATIONS -- the width is committed by PR1 and cannot move after**
  3. **14 action ids, reserving a permanently-masked slot for the Spiral of
     Stars**, so that build later lands at zero width and zero extra retrain.
  4. **The Ink Well gets its OWN action id**, not a silent `_redraw_kind`
     tail. **Reason, and it is the load-bearing one:** every other redraw
     source spends a hand- or day-scoped resource with a natural bound, while
     `STAR` spends a **permanent, save-scoped** one with no cap -- behind an id
     the agent already presses reflexively. An agent that learned "press
     REDRAW on a bad hand" would convert its entire star bank into rerolls in
     a single day and destroy the constellation engine it spent weeks
     building. **Total: 15 appended ids, `N_ACTIONS` 442 -> 457.**
  5. **Florealis is IN**, reversing the earlier "out to keep the PR down".
     The reversal is on corrected facts, not preference: the orchestrator
     reported it had "no primitive whatsoever" (zero hits for `flower` in
     `src/`). **The measurement was right and the conclusion was wrong** --
     `GameState.spread_pending` already parks per-cell payouts collected by
     `Game._collect_spread`, and `state.py` names this exact future use.
     **~40 lines of reuse, not a subsystem**, so the reason to defer expired.
  6. **The night sky needs an EXPLICIT VIEW ACTION**, not auto-generation on
     entry. Skies lock at the star count when first viewed and higher counts
     partition into strictly more value, so the optimal line is *draft every
     Observatory first, then walk in and look*. **Auto-generating silently
     deletes that timing decision.** Costs no extra id -- the view action
     exists for the Telescope regardless.
  7. **The Observatory's uncapped `+1 star per draft` stays uncapped.** It is
     verified faithful and no published cap exists, so capping it would be an
     invention. **Recorded as a known self-amplifying loop** (draft Observatory
     -> +1 star -> richer sky -> more resources -> more drafts, up to 4
     Observatories/day via the Chamber of Mirrors). The retrain reveals
     whether it dominates; the point is that it is known *before* the retrain.

  **CONSERVATORY**
  8. **Forced-draw blocking is POSITIONAL, not literal** -- a Forced Draw
     blocks later entries in the precedence order **only where its own
     conditions hold**, not merely by being in the pool. This was a 0%-or-100%
     switch on shipped behaviour: the literal reading would have erased the
     Garage's measured 17.6% -> 53.6% forced-draw gain the moment a
     Conservatory floorplan was found. The positional reading is the only one
     consistent with the sim's single global deck model, and the Morning
     Room's documented wings-only exception suggests the game works this way.
     **Conservatory and Garage are provably non-interacting**: corners
     `{0, 4, 40, 44}` vs West Wing `{15, 20, 25, 30, 35}`, disjoint.

- **2026-08-14, OWNER RULINGS x14 -- the queue is now UNBLOCKED. Plus new
  ground truth on the Basement Key that overrides the wiki.**

  **NEW GROUND TRUTH (owner play, supersedes the wiki):** *"Add the Basement
  Key to the Antechamber. It appears on a pedestal in the Antechamber when you
  enter the room, allowing you to take it and go through The Foundation or the
  fountain door to open a basement door permanently across an entire save,
  granting permanent access without needing to return to the Antechamber."*
  The wiki lists the **Spiral** as `basement_key`'s only location; **owner play
  outranks it.** Two consequences: (1) the Spiral is no longer any item's sole
  route, which may shrink that scoping question; (2) *"permanently across an
  entire save"* is a **save-scoped BOOLEAN** -- so this may be the first
  legitimate reason to grow `DayChain._CARRYOVER_KEYS` past **16**, where it
  has sat unchanged all session with every set-valued thing pushed to the
  separate channel. **That is a design question, not an implementation detail;
  it is being answered by a scoping pass, not decided in passing.**

  **CONSTELLATIONS**
  1. **Model the TRUE SUM-PARTITION**, not a `stars >= N` threshold. A
     threshold over-rewards stars and the star engine is what an RL agent will
     exploit.
  2. **Model the PER-CONSTELLATION CHOICE**, not auto-activate. *(Rejects the
     recommendation put to the owner.)* **~1000-1450 lines, 12 appended action
     ids: `N_ACTIONS` 442 -> 454, plus one NEW obs key.** Appended only; no
     existing id shifts. **A retrain is owed** -- see below.
  3. Florealis: not separately ruled; still open if the arm reaches it.

  **CONSERVATORY**
  4. **Build REACHABILITY FIRST** -- the 15% forced draw and the Found
     Floorplan gate -- *then* remodel. The room is undraftable today
     (`"rarity": null`), so remodelling first ships more dead code.
  5. **The wiki wins on "all three"**, not the owner's earlier "any of the
     three" -- explicitly reversing that reading.
  6. **A no-op click COUNTS as a use.** `permanent_rarity` cannot represent it
     (`set_wrench_rarity` *pops* the entry when the pick equals the natal
     rarity), so this needs a **second save-scoped set, ~40 lines + an obs
     key.**

  **DRAFTING FIDELITY**
  7. **Priority Draws are NOT Slot-3-only -- the two mechanisms were
     CONFLATED.** Remove the `slot == 2` gate; Forced Draws stay Slot-3-only.
  8. **BUILD the Day 1 opening draw** -- deterministically Bedroom, Closet,
     Hallway. The sim produced **292 distinct opening hands over 300 seeds**
     and no code for it exists, which already invalidated one queue entry's
     evidence.
  9. **The Commissary/Observatory 46:1 skew is a SECOND DEFECT** -- fix it.
     `_priority_draw` returns the first candidate in list order, so Observatory
     is unreachable by that route: a content gap, not a skew.
  10. **Fix both `priority_draws.json` data gaps** -- the 3% group is
      {Garage, Classroom}, and the Greenhouse moves Secret Passage 5% -> 3%.
  11. **Fix the card consumption WITH the slot-gate work** -- `_priority_draw`
      never calls `deal_next`, so a drawn floorplan stays in its deck.

  **ITEMS**
  12. **BUILD `morning_star`'s star grant on wiki confidence.** Wiki-only and
      unconfirmable by datamine, and the owner accepted that basis.
  13. **BUILD the contraption carry-over lockout.** The shape exists
      -- `collected_disks`/`collected_allowance_tokens`/`collected_sanctum_keys`
      all feed `gated_out`.
      **CORRECTION (this entry was wrong as first written).** It said "6 items"
      with "Dowsing Rod and Pick Sound Amplifier exempt". The wiki says the
      opposite: **every contraption blocks something**, those two included --
      the Dowsing Rod blocks the Compass, the Pick Sound Amplifier blocks the
      Lock Pick Kit. The shipped table (#297) has **8 entries**, and it blocks a
      **curated subset** of each recipe, not the whole recipe. The orchestrator
      briefed the exemptions inverted, the implementing agent checked the source
      and shipped the correct rule, and the correction was recorded in that PR
      body **but not here** -- so this record stated the wrong rule until a later
      agent noticed the doc and the code disagreed. **A correction recorded only
      in a PR body does not reach the file people read.**
  14. **REBUILD `running_shoes` to the real rule.** The `n=3` cadence is
      **invented**, not simplified, and the shoes are **inert off-grid** where
      the wiki gives them their highest rates.
  15. **SCOPE the Spiral and the Dartboard** (both, alongside the Basement Key).

  **SMALL**
  16. **Delete the dead `t5_special_chance` fallback of 50** -- no live reader.
  17. **Real-game patch history IS allowed in data notes**, even when it reads
      like code history. Settles the `experiments.json:417` precedent a sweep
      agent deliberately declined to set.
  18. **Fix the `laundry_room` coupon discount now** -- latent, symptomless
      only because laundry stock is empty.
  19. **`meta.confidence` stays as-is -- labels are ADVISORY.** The owner's
      reasoning: there may simply be more in the wiki than the datamine, and
      wiki interpretation is more reliable here. **Consequence: stop citing
      `confidence` as authority.** The measured inversion (items labelled
      `datamined` are the *least* complete) is therefore not a defect to chase.
  20. **RETRAIN ONCE, after the batch lands** -- not per change.
      `baseline-ep8275991` was trained against rules the sim no longer
      implements: the width change from ruling 2, the lockpick ladder fix, the
      priority-draw free/gem fix, and spawn rates moving up to 6.6x.

- **2026-08-14, CONSTELLATIONS researched. Four corrections to the
  orchestrator, and ITEMS HAVE NO FIDELITY AUDIT AT ALL.**

  Research was read-only and is **wiki-sourced throughout**: the repo's only
  raw datamine (`tools/raw/tfmurphy_room_table.md`) is the v1.3 **room** table
  and contains **zero** constellation data. So the owner's stated priority
  (datamine, then wiki) **could not be exercised here** -- there is no
  datamine to prefer and **no disagreement to report**. Say so when relaying;
  do not let "researched" imply "datamined".

  **Corrections to the orchestrator's brief, all verified:**
  1. **There are 13 constellations, not 11.** The 11 are the 0-49 base set;
     **The Ink Well (50)** and **Spiral of Stars (100)** are the other two.
     `open_tasks.md:1157-1161`'s "all eleven" silently drops them.
  2. **The two wired constellations ARE sourced -- thoroughly.**
     `priority_draws.json:180-207` carries `confidence: datamined`, a sheet
     constant, a wiki URL, the wiki's own selection query transcribed into
     `exclude_rooms`, and a note stating plainly that nothing sets the flag.
     The orchestrator's "wired but never sourced" premise was **wrong**. This
     is the repo's dominant failure mode **not** occurring; record it as such.
     Both magnitudes re-derived and **both are correct**.
  3. **The Telescope's planet arm is PR #264, not #260.** #260 is the
     Planetarium's `on_day_end` star change.
  4. **Unlock is a SUM-PARTITION, not a threshold.** The night sky shows a set
     of constellations whose star values sum **exactly** to the current star
     count. At 6 stars: Twins(2)+Diamondus Minor(4) -- **not** North Star, not
     Slice. Verified by checking the partition invariant across 0-49: **49 of
     50 sum exactly**, the sole exception n=0, which the wiki documents.

  **Why (4) matters more than the auto-vs-choice question it sits under:** a
  naive `stars >= N` gate grants all seven constellations at or below 25 stars;
  the true rule grants five and is strictly weaker. **Collapsing it to a
  threshold over-rewards stars**, and the Observatory/Aquarium/Planetarium star
  engine is exactly what an RL agent will find and exploit. This question is
  **upstream** of the owner's open constellation question and reframes it.

  **Scope, measured:** nothing is permanent except Spiral of Stars' word count.
  Everything else is immediate or day-scoped. **The constellation work does not move `_CARRYOVER_KEYS`**, a
  channel that is bool-only, though its length is not fixed (see
  [`scoping-and-carryover.md`](scoping-and-carryover.md)). Four of the eleven base
  constellations are **non-stacking**, so the Telescope's second sky is a
  **no-op for four of them** -- any cost case assuming it doubles everything is
  wrong.

  **Costs, for the ruling:** auto-activate ~650-950 lines / 8-10 files, and
  **`N_ACTIONS` stays 442** -- because `env/actions.py:840 _redraw_kind`
  already auto-selects the cheapest redraw source behind the single
  `REDRAW_ACTION`, so The Ink Well is a **zero-action-width** change (verified).
  Per-constellation choice: ~1000-1450 lines / 13-16 files, **12 appended
  ids, 442 -> 454**, plus one **new** obs key. No existing key resizes either
  way; day-scoped draft-bias flags are already invisible to the agent
  (`southern_cross_active`, `draxus_active`, `schoolhouse_placed`,
  `add_aquariums_active` appear nowhere in `env/obs.py`).

  **THE STRUCTURAL FINDING, and it is the important part of this entry.**
  Chasing a suspected `morning_star` gap turned up something larger:
  **`find_divergences` is entirely room-scoped.** Item records carry **no
  `meta.effect_text` field at all** -- verified across all **102** of them --
  so there is **no item text-vs-model fidelity audit in existence**. The item
  side has only a registry-consistency check, an empty-effects census, and a
  **hand-maintained `implemented` flag**.

  Therefore **"102 special items (1 unimplemented)" counts items whose FLAG
  says unimplemented -- not items verified complete.** Nothing would notice a
  half-implemented item. `morning_star` is the candidate instance:
  `implemented: true`, `effects: [{"tag": "smash"}]`, `blocked_on: null`, and
  per the wiki its text is *"Can knock the locks off chests and trunks.
  **Tomorrow morning, gain 1 Star**"* -- the star half absent and unflagged.
  **Wiki-sourced and UNCONFIRMED by datamine or owner play; treat as a
  candidate, not an established bug.**

  **This is the same shape as #270 one level up.** Rooms got a fidelity audit;
  items got a registry check that answers "is this id known?" and never asks
  "does the model match the published text?". A hand-maintained completeness
  flag with no detector behind it is a liveness check wearing a different hat.

  **Other findings:** the reconstructed 0-49 partition table was **never
  persisted** -- only `southern_cross` and `draxus` appear anywhere in the
  repo, so the table exists solely as a prose assertion at
  `open_tasks.md:1157-1161` and must be re-derived from scratch. And
  `special_items.json:647` claims *"Spiral has no wiki page at all"*; it has
  one. The conclusion it supports (keep Spiral out of `spawn_rooms`) is still
  right, but the stated reason is false and would mislead a re-deriver.

  **Florealis is unbuildable today**: zero hits for `flower` anywhere in
  `src/`. In = a new subsystem; out = 10 of 11 with a recorded reason.

- **2026-08-13, THE CONSERVATORY: researched to datamined ground truth, and it
  is CORRUPTING `gear_wrench` 14.3% of the time. Four rulings outstanding.**

  Owner set the research priority: *"Go with whatever comes from the data mining
  followed by the wiki in that order"*, and offered a hypothesis -- *"I suspect
  it's uniform random irrespective of rarity."*

  **The hypothesis is SUPPORTED.** The Conservatory page's `DataMinedBox` says
  *"the table presents three random rooms that passed the filters"*, with **no
  rarity term anywhere** -- unlike the normal draft (*"the game first chooses a
  rarity and then selects a room of that rarity"*) and matching the Duct Draw
  shape, which the wiki states outright as *"uniformly at random from the list
  (ignoring rarity and other modifiers)"*.

  **Two honest qualifications, recorded rather than smoothed over:** the
  datamine never uses the word "uniform", and it never says whether the three
  are drawn **with or without replacement**. The bug clause -- *"this list
  contains bugged entries that, if they appear, appear like one of the other
  entries already present"* -- implies the **fallback** path is not
  de-duplicated. Treat "uniform, without replacement" as the reading and
  "with replacement" as unverified.

  **The datamined filter chain, which belongs in DATA when this is built:** from
  86 rooms, drop any whose rarity has been changed **by any method** (so a
  wrenched room disappears from future offers); Studio Additions and Found
  Floorplans must have been added or found; Gift Shop drops if never drafted;
  Freezer, Pump Room and Dovecote always drop. **If fewer than 3 survive, it
  presents three from the full 86 ignoring every filter.**

  **The sim's matching concept lands at 85, not 86** -- `pool in {base,
  studio_addition}` = 95, minus the 16 named unchangeable rooms = 85. The 8
  outer rooms are already excluded. **The 1-room gap is unresolved** and was not
  worth chasing. *"Interior room" is the owner's term, not the game's*: the
  game-side concept is "rooms whose rarity can be changed", and 16 interior
  rooms are excluded, so interior alone is not the criterion.

  **The rarity change is ALL three, not any one** -- *"the player may interact
  with the drawing board to change the rarity of each one"*. **Surfaced as a
  possible conflict with the owner's "any of the three"**, which may be phrasing.

  **Three further datamined rules, each load-bearing:**
  - *"Clicking a floorplan, even without actually changing the rarity, counts as
    changing the rarity."* A no-op click consumes the room permanently.
  - It writes **the same permanent slot as the Gear Wrench**: *"If a room's
    rarity is ever set using the Conservatory and/or Gear Wrench (even if the
    rarity was not changed from the default), that room's Dynamic Rarity is
    permanently ignored."*
  - **Reset does not un-consume.** Resetting via the Room Directory *"acts like
    setting the rarity back to the base rarity, rather than as if the rarity was
    never set in the first place"* -- the room stays filtered out.

  **Frequency is unsourced.** Neither source says once per day, once per
  Conservatory, or unlimited. The likely reading is unlimited re-interaction with
  a shrinking offer list, but that is inference.

  ### The live bug the research found, fixed ahead of any remodel

  **`reroll_random_rarities` moved cards between rarity decks without writing
  `state.dynamic_rarity`** -- the dict every other deck helper consults. So a
  later `set_dynamic_rarity` looked in the **wrong bucket, found nothing, and
  silently dropped the move.** Reproduced at seed 0: `secret_passage` moved 2->0
  while `dynamic_rarity` stayed `{}`; the follow-up placed **0 copies** in the
  target while one stayed stuck.

  **It corrupts `gear_wrench`**: over 300 seeds the reroll moved a Mechanical
  Room in **43 (14.3%)**. A player who drafts the Conservatory then wrenches an
  affected room records a permanent rarity while the card sits elsewhere.

  **THE CONSERVATORY IS UNDRAFTABLE, and that is what masked it.** Its record has
  `"rarity": null`, and `eligible_pool` drops rarity-less rooms **before** it
  checks the pool, so it can never enter `build_decks`; its forced-draw entry is
  explicitly unbuilt. **The entire effect is dead code** -- and goes live the
  moment anyone makes the room reachable.

  **All six existing Conservatory tests were self-consistent with the buggy
  model.** They pin card conservation, deck perturbation, determinism and
  substream consumption; **none asserted anything about `dynamic_rarity`
  bookkeeping**, so the bug was invisible to them. Fixed by routing each move
  through `set_dynamic_rarity`, which already maintains it -- one implementation
  rather than two, same draw count and label.

  **Generalisable: dead code can still be a hazard, and being unreachable is not
  the same as being harmless.** This sat behind a `"rarity": null` that nobody had
  connected to it, and would have gone live silently.

  ### Rulings outstanding before any remodel
  1. **Is the Conservatory in scope at all, given it is undraftable?** Making it
     reachable needs its 15% forced draw and the Found Floorplan gate, neither of
     which exists. The remodel buys nothing until that lands.
  2. **Does "a click counts even with no change" get modelled?** It is the
     difference between reusing `permanent_rarity` and adding a second
     save-scoped set -- because `set_wrench_rarity` **pops** the entry when the
     pick equals the natal rarity, so `permanent_rarity` alone cannot express
     "consumed but unchanged".
  3. **"Any of the three" (owner) vs "all three" (wiki and datamine).**
  4. **Constellations: auto-activate, or model the per-constellation choice?**
     Auto halves the `telescope` constellation arm and removes an action-width
     change; the game explicitly makes activation optional.

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
