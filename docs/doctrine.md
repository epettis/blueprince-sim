# Doctrine

The standing rules about *what this sim models and on whose authority*. They
are cited by reference from the topic docs, the data records and the tests, so
each is stated once, here.

Rules about *how to work* — process, review, escalation — live in
[`process.md`](process.md). Rules about how long a fact lives live in
[`scoping-and-carryover.md`](scoping-and-carryover.md).

## Sources of truth, in order

**The datamined tables beat the wiki prose on exact magnitudes.** The
decompiled sheet has beaten the wiki article before on precise numbers, so
where the two give different figures the datamine is coded and the
disagreement is recorded in the affected record's `meta.notes` to be re-tested
— not silently resolved. The standing example: our data gives the blueprint
draft bias 50% and the shop bias 25% where the wiki says 40% and 30%; the
datamined values are what ship.

**Owner play is a tie-breaker, not an automatic win.** An owner play-report
outranks the wiki when the two genuinely conflict, but it is evidence, not a
trump card, and the owner has themselves ruled *against* their own observation
when the published text was stronger. A single play-report cannot distinguish
"this tool is required" from "this tool happened to be in my hand". So:
**surface the conflict and let it be ruled, rather than resolving it silently
in either direction** — surfacing is what makes the weaker-evidence call
possible.

**Multiple sources of truth means we have none.** Before adding a field, ask
"could two places disagree about this fact?" If yes, that is the disease, not
the design.

**The datamine's authority covers magnitudes, not coverage.** It wins on exact
percentages and payouts. It says nothing about whether a mechanic exists at
all, and neither does `meta.effect_text`: that field is a single curated line
and routinely elides a whole mechanic — the Secret Passage's five-colour
choice, the Pantry's fruit. So a room or item gets a **full wiki pass whose
specific job is finding what the curated text omits**, with `effect_text`
treated as a strongly-weighted prior on the numbers it does state and no
authority on the ones it does not mention.

**Discrepancies about a *mechanic* are batched, not streamed.** Where the wiki
and the curated text disagree on what something does — as opposed to on a
number — the record is parked and carried into a single consolidated question
round put to the owner **before implementation begins**. An agent that hits
such a discrepancy mid-implementation has already sequenced the work wrong.

## Supplemental-sourced rooms must be edited in both files

Room records come from two places: the ingested `tools/raw/` tables, and
`tools/supplemental_rooms.json` for rooms the raw tables do not carry (the
Throne Room and the Maid's Chamber are examples). Editing
`src/blueprince_sim/data/rooms.json` alone for a supplemental-sourced room is
**silently reverted by the next re-ingest** — no error, no diff, the fix simply
disappears.

So: before hand-editing a room record, check whether its id appears in
`tools/supplemental_rooms.json`. If it does, both files change together, and
both must still parse with the room count and order unchanged.

## Puzzles are assumed solved

The sim does not model player-skill puzzles. A room whose reward sits behind a
puzzle grants that reward on entry as though the puzzle were solved. This
covers the room safes, the Shelter's real-time timed safe, and the
puzzle-*reward* rooms `gallery`, `room_8` and `parlor`.

**`great_hall` and `closed_exhibit` are deliberately excluded**, and the
distinction that decides it is worth keeping: in the included rooms **the
reward is the mechanic**, so granting it directly loses nothing. The Great
Hall's interior subchambers are a randomised *spatial* system behind
Silver/Prism Key doors and the Closed Exhibit's is a *lock* system — flattening
either to a constant would delete the structure, not approximate it. The Great
Hall is a lever room at 3.3% placement, so the temptation to inflate it is real
and is declined on purpose.

The corollary, applied via `_AUDIT_DOCTRINE_EXEMPT_IDS`: a room whose entire
effect is *making a puzzle easier* is a modelled no-op, not a gap. The
Speakeasy's "Basic Addition" only simplifies the Dartboard Puzzle, which is
already assumed won, so it pays exactly what the Billiard Room already pays.
"We model this as nothing, deliberately" is a claim worth stating once rather
than a gap worth re-triaging every audit pass.

## Trophies are achievements, not game state

A trophy is not modelled as a flag, an item, or an observation dimension.
Room 8's completion reward is Trophy 8 plus Allowance Tokens, one fewer token
once the trophy is held; with trophies out of scope the trophy half is simply
not represented and the clause becomes a plain first-solve-versus-later-solve
distinction on the token count. **Do not add a trophy concept later to
"complete" a room** — the reward that matters to a policy is the allowance, and
that is already modelled (`GameState.allowance`).

The one carve-out is a purchase, not an achievement: `trophy_of_wealth` is a
100-coin Showroom item (`data/shops.json`), offered only once all four
displayed items have been bought, and it is modelled as an ordinary special
item because it is a coin sink the player can act on.

## Features are built to be PLAYED

A feature is not deferred because the current policy cannot reach it. The owner
plays the game to record expert demonstrations, and the behavioural-cloning
pipeline turns those into training signal — so **"unreachable by the current
policy" is a reason the feature has to exist *before* the demonstrations that
teach it, not a reason to defer it.**

What this changes is the acceptance bar. A feature is done when the owner can
*operate* it in a recorded session, not when the engine models it correctly.
Concretely, every feature of this kind needs:

- a **player action** in `env/actions.py` with a masking site, not just engine
  state that some other code path mutates;
- that action **exposed in the Play tab**, since that is where demonstrations
  are recorded;
- the resulting day to **replay clean** (`divergence=None`), which is what
  makes a demo usable as training data.

A correct mechanic with no action to drive it is unteachable, and the gap is
invisible to every test that drives the engine directly. Ask **"can the owner
do this in a recorded session?"** before calling a feature complete.

## Model correctness outranks observation- and action-space stability

Changing the observation vector or the action vector is an accepted cost of
getting the game right. Widths are not frozen; a retrain is the price. State
the before-and-after (`N_ACTIONS`, `len(_CARRYOVER_KEYS)`, any resized obs key)
so the retrain trigger is visible in review, and then make the change.

## Deliberate divergences

- **`implemented: true` does not mean "complete".** A record with a partial gap
  keeps `implemented: true` and **requires** a `meta.simplification` naming
  what is missing, which keeps the gap machine-*readable* rather than
  prose-only -- but no validator scans for the pairing today, so a record
  that omits `meta.simplification` on a partial gap goes uncaught.
  `implemented` keeps meaning *reachable and functional*.
- **A disclosure must live on the record it concerns.** A pointer from
  somewhere else does not count: a disclosure a reader cannot reach is not a
  disclosure.
- **`spawn_rooms` means loose-on-the-floor only.** Purchasability is a separate
  concept modelled in `shops.json`. The wiki's single `Locations` field mixes
  the two; the sim keeps them as separate fields so the ambiguity never has to
  be re-litigated.
