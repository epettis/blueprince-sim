# The RL environment: spaces, records and measurement

What the agent sees, what it can press, and what has to stay true for a
recorded episode to be replayable a month later. Code: `env/obs.py`,
`env/actions.py`, `env/blueprince_env.py`, `rl/train.py`,
`rl/behavioral_cloning.py`, `web/replay.py`.

Reward *shaping* — the milestones, the potential terms, the horizon — is owned
by [`rewards.md`](rewards.md). This document owns the **spaces**, the
**checkpoint and replay contract**, and **measurement discipline**.

## Widths are not frozen

[`doctrine.md`](doctrine.md) states the rule: model correctness outranks
observation- and action-space stability, and a retrain is the accepted price.
No run is live and no checkpoint is being preserved, so if widening the
observation vector or adding an action is the natural model for a mechanic,
**do it, and record it**.

Two things that rule does **not** license, because neither is about
checkpoints:

- **The carry-over vector and `upgrade_slots` must stay sorted, never
  set-ordered.** `env/obs.py` derives the `carryover` vector's length from
  `len(DayChain._CARRYOVER_KEYS)` and encodes the keys in `sorted()` order.
  Python randomises string hashing per process, so a set-ordered vector
  permutes between runs *within* a single training session and silently
  corrupts learned field positions. Every derived ordering in `obs.py` and
  `actions.py` — travel nodes, sigil doors, axe targets, special-key rows —
  uses the same discipline for the same reason.
- **A dead action id is still a defect.** See below.

## The width-change register

Two numbers define the spaces. **Record their current value and the reason
for the last change — never a historical list, which rots the day it is
written.** If you need the history, `git log -S "N_ACTIONS ="` has it and is
never wrong.

| width | value | where |
|---|---|---|
| `N_ACTIONS` | **481** | `env/actions.py` |
| `len(DayChain._CARRYOVER_KEYS)` | **19** | `env/multiday.py`, drives the `carryover` obs Box |

**Last change: `N_ACTIONS` 479 → 481, the Office's second terminal process
([`rooms.md`](rooms.md), "The Office's coins").** Two ids, appended after the Pump Room panel
block: 479 Spread Gold in Estate, 480 Run Payroll — both gated on standing at
the Office's cell (`Capability.OFFICE_TERMINAL`, `engine/effects/rooms/office.py`),
the same shape as `SECURITY_LEVEL`/`PUMP_PANEL`. Spread Gold in Estate IS a
spread (`GameState.spread_pending`/`Game._collect_spread`), redirected by a
placed Conference Room the same way the Patio/Locker Room/Secret Garden are;
Run Payroll is explicitly NOT a spread (the wiki states no Conference Room
interaction), so it pays out through a separate `GameState.payroll_pending`
dict keyed by room id instead. `_CARRYOVER_KEYS` stays at 19 — the weekly
payroll cooldown (`GameConfig.payroll_last_used`) rides the same non-bool
carry-over shape as `water_levels` (NOT SAVE-scoped), not a bool flag.

Previously: `N_ACTIONS` 458 → 479, the Pump Room panel (docs/areas.md's
Pump Room section). A factored two-step menu — pick a water source (6 ids,
`PUMP_SOURCE_BASE`), then pick its target level 0..14 (15 ids,
`PUMP_LEVEL_BASE`, `Phase.PUMP_LEVEL_PENDING`) — rather than a flat
source-by-level enumeration (53 ids), the same multi-phase-menu idiom as
`LOCK_MENU_BASE`/`UPGRADE_PENDING`/`COLOUR_PENDING`. The macro action sets a
level directly (owner ruling: the tank/pump water-pouring puzzle is assumed
solved, like every other room puzzle), so it loses no reachable state — the
wiki states every valid level per source is reachable this way. `_CARRYOVER_KEYS`
18 → 19, `reservoir_13_reached`: the Reservoir North<->South rowboat crossing
opens permanently the first time the Reservoir is set to exactly 13, unlike
the other two Pump Room gates (`pump_water_lte8`/`rowboat_water_6`), which
re-check the live level on every traversal instead of latching. The six water
levels themselves are NOT in `_CARRYOVER_KEYS` (bool-only) — they ride the
same non-bool carry-over shape as `permanent_rarity`/`draft_counts`
(`GameConfig.water_levels`, `DayChain.water_levels`/`next_config`/`advance`).

The constellation build itself (442 → 457, superseded by the above) landed at
once, inert: 13 activation ids, one per `data/constellations.json` record in
that file's ascending-star order — which includes a permanently masked slot
for the Spiral of Stars, so that build later lands at zero width and zero
extra retrain — plus one id to view the night sky and one dedicated id for
the Ink Well's star-redraw. That ruling is satisfied and closed: no PR in
that build may move an id inside it; activating a constellation is a
masking-site and encoder change only. It does not freeze ids outside the
block, including earlier ones like the Axe range above.

The Ink Well's separate id is the load-bearing part of that change, and the
reason generalises: every other redraw source spends a hand- or day-scoped
resource with a natural bound, while the Ink Well spends a **permanent,
save-scoped** one with no cap. Folding it into the existing redraw action would
put it behind an id the agent already presses reflexively; an agent that
learned "press REDRAW on a bad hand" would convert its entire star bank into
rerolls in a single day. **Resource scope is an action-space design input, not
just an engine detail.**

### The rules the register enforces

- **Every PR that moves either number states the before and after.** That is
  the retrain trigger, and the cheapest time to know a retrain is owed is when
  it happens — not when a checkpoint fails to load.
- **Append only. Never insert.** A mid-array insert invalidates a policy's
  learned embedding far more deeply than a bound change does, because every id
  after the insertion point silently means something else. Confirm no existing
  id shifted.
- **Any PR that touches `_CARRYOVER_KEYS` is an observation-space change**,
  whether or not it looks like one — see
  [`scoping-and-carryover.md`](scoping-and-carryover.md) for what that
  frozenset is and what does *not* belong in it.
- **A padded observation array's row cap is a width too.** Raising
  `TRADE_OFFER_ROWS`, `SHOP_STOCK_ROWS` or any similar cap is a retrain
  trigger on the same terms.

### Pinned-but-derived widths must assert their own agreement

Several `_N_*` constants in `env/actions.py` are **pinned** (a literal, so
`N_ACTIONS` stays importable with no `Registry` loaded) but correspond to a
count that is genuinely **derived** from a data file: `_N_AXE_TARGETS`
(`_build_axe_target_ids`, every room with a rarity and a nonzero gem cost),
`_N_AREA_NODES` (`_build_area_node_ids`, `areas.json`'s nodes),
`_N_LOCK_SPECIAL_KEYS` (`_build_lock_special_key_order`,
`data/locks.json`'s `special_key_menu.order`), `_N_PUMP_SOURCES`
(`_build_pump_source_ids`, `data/pump_room.json`'s water sources), and
`_N_CONSTELLATIONS` (`data/constellations.json`'s records, held at 13 by
`tools/validate_data.py` and cross-checked in `tests/test_constellations.py`).

**Nothing else enforces that the pin and the derived count agree**, and the
mask-building loop for each block has no bounds check — it enumerates the
derived tuple and writes `mask[BASE + i]` unconditionally. A content change
that grows the derived count past the pin does not raise or truncate: it
writes past the reserved block into the *next* block's first action id,
silently corrupting an unrelated action's legality bit. This is exactly what
happened to `_N_AXE_TARGETS` (see the width-change register above) — a
mask length check (`len(mask) == N_ACTIONS`) does **not** catch it, because
`mask` is always allocated at the full `N_ACTIONS` length regardless of what
gets written into it.

The fix, now applied to every registry-derived builder (`_build_axe_target_ids`,
`_build_area_node_ids`, `_build_lock_special_key_order`,
`_build_pump_source_ids`): **each asserts its own result's length against its
pinned constant before returning.** A future desync raises immediately,
everywhere the builder is called (mask building, dispatch, and every test that
builds a `Game`), instead of corrupting a mask bit silently. Each also has an explicit,
discoverable test pinning the same invariant
(`test_axe_target_count_matches_the_pinned_action_space_width`,
`test_area_node_count_matches_the_pinned_action_space_width`,
`test_special_key_menu_count_matches_the_pinned_action_space_width`,
`test_pump_source_count_matches_the_pinned_action_space_width`), the
same shape `test_constellations.py` already used for `_N_CONSTELLATIONS`.
The builder's own assertion fires only where it is called; the test fails
on any run.

## Reserved and dead action ids

**An id that no code path can ever mask legal is a defect**, and a
particularly expensive one: it survives long enough to be mistaken for a
missing feature. `ALT_BASE` reserved three ids for per-option orientation
choice; `action_mask` never set them (verified live as all-False at every
draft), and `apply_action` routed all three through the identical
`game.choose(slot)`, which takes no orientation argument. The
`GameConfig.orientation_choice` field they existed for was read nowhere. Both
were removed — see [`drafting.md`](drafting.md) on why per-option orientation
is not a mechanic at all.

**A dead id in a masked action space misleads every later investigation.** That
is the cost being paid, not the three wasted slots.

The guard is `test_every_action_kind_has_a_masking_site` in
`tests/test_macro_actions.py`, which scans `action_mask`'s own source for a
`mask[<NAME>` write for each declared action-kind name. **Know its limit before trusting it: the list
of names it checks is hand-maintained and does not automatically track the ~40
`*_BASE` / `*_ACTION` constants `env/actions.py` now declares.** A new id is
only covered once its name is added. Add it in the same PR that declares the
id, or the guard silently does not apply to the one id most likely to be dead.

A *deliberately* reserved id — one masked False on purpose to hold a slot for a
build that has already been committed to, like the Spiral of Stars slot above —
is the one legitimate exception, and it is legitimate only because it is an
owner ruling recorded here. It still has a masking site; the site just always
writes False.

**Reserving against a *known* future field works; reserving against an
*unanalysed* one does not.** An observation slot sized to absorb a named,
already-understood field did absorb it later with no further change. A slot
sized on the assumption that a second, unexamined fact would fold into the
first did not: the two facts turned out to be genuinely independent, and
folding them would have made one field mean two things — which costs more than
the width change it was trying to avoid.

## The config digest

A recorded episode is a seed plus an action sequence. In multi-day mode the
starting conditions vary per day, so the record also carries `day_config`, a
diff of the episode's `GameConfig` against the chain's base config. Replaying
the wrong config usually completes with **no illegal action at all** — so a
wrong reconstruction would silently produce a full set of (observation, action)
pairs carrying the wrong observation from step 0 onward.

`config.config_digest(cfg)` closes that hole unconditionally, at reconstruction
time, rather than hoping the replay goes visibly wrong. Its design:

- **Hash only non-default fields**, canonicalised (`frozenset` → sorted list,
  `dict` → key-sorted, `Path` → `str`), `json.dumps(sort_keys=True)` →
  `blake2b(digest_size=8)`.
- **Never `hash()`.** `PYTHONHASHSEED` randomises `str.__hash__` per process,
  so a hash-based digest is not stable across processes. (`GameConfig` is not
  frozen and has `__hash__ is None` in any case.)

**The non-default filter is what makes the corpus survivable.** `config.py`
took 47 commits in ten weeks, roughly forty of them field additions; hashing
every field would invalidate every stored record roughly weekly. Appending a
`GameConfig` field never changes the digest of a config that leaves it at
default, so a record stamped before the field existed still matches after.

**Known hole, accepted: a change to a field's *default* is invisible to the
digest.** A config left at the new default hashes identically to one left at
the old default. Two real instances in ten weeks, each a deliberate semantics
PR. **The mitigation is procedural — pair a default change with deleting the
corpus, the same convention `n_actions` already carries. Do not close it by
hashing defaults; that reintroduces the weekly churn.**

The digest also exposed a defect nobody had recorded: `_serialize_config_value`
dropped every value that was not `frozenset`/`bool`/`int`/`str`, so the
`dict`-typed `draft_counts` was **silently absent from every `day_config`
diff** — meaning multi-day replay was already inexact from day 2 onward on the
working trainer path. Measured over a 5-day chain: day 1 reconstructed exactly,
days 2–5 all mismatched. Shipped without that fix the digest would have fired
on 100% of legitimate multi-day records rather than 0%. **A new verifier's
first job is to tell you your existing pipeline was already broken; budget for
that before deciding the verifier is too noisy to ship.**

## Raise, don't default

A demo record that cannot be safely replayed is **refused, not guessed at**.
The whole family lives in `rl/behavioral_cloning.py` under one base
`DemoError`, and each exists because the silent alternative produces training
data that looks fine:

| error | condition |
|---|---|
| `StaleDemoError` | the record's `n_actions` ≠ the current action space |
| `UnstampedDemoError` | no `unlocks` field, so nothing says which preset `day_config` diffs against |
| `MixedPresetError` | a demo set mixes presets with no explicit filter |
| `ConfigDigestError` | no `config_digest`, or it does not match the reconstruction |
| `ReplayDivergenceError` | a recorded action was illegal on replay, or replay ended early |

Two of these deserve their reasoning stated rather than assumed. **Action ids
are positional**, so a record written against a different action space cannot
be replayed at all — the same integer names a different action now; replaying
it as nonsense is strictly worse than refusing. And **guessing an absent
`unlocks` stamp is exactly the tampering the wrong-preset test simulates**: a
fresh-save diff replayed onto the all-unlocks base drifts silently.

`ReplayDivergenceError` is the one that reads like a false positive and is not.
Both producers only ever record actions that were legal in the live mask at
record time, so a divergence means the *reconstructed config* is wrong, not
that the demo is corrupt busywork to paper over.

**The asymmetry with the replay UI is deliberate.** `web/replay.py` only
**flags** a mismatch in its `divergence` dict rather than raising, because
raising there would 500 the page. Refusal is the rule for the *training*
pipeline, where a bad record becomes bad gradients; a human looking at a
rendered house can be told instead.

## Padded arrays truncate silently

`env/obs.py` encodes several variable-length menus into fixed-height arrays,
and `env/actions.py` reserves a matching block of ids. **Beyond the cap an
entry is never encoded and never masked legal — no assertion, no log.**

The example that made the rule: `TRADE_OFFER_ROWS = 8` and `TRADE_BASE..+8`
against `shops.py::trade_offers`, which emitted **one offer per distinct held
inventory id**. Holding all 12 tier-5 items yielded 12 offers and left four
**unreachable**. Because offers sort alphabetically for a stable action index,
the truncated ones were not random: a wall of Sanctum Keys crowded an ordinary
tier-2 item off the menu, and one of the crowded-out entries was a Sanctum Key
itself.

Two rules follow, and the first is the general one:

- **A cap must be justified against the real maximum, not against a typical
  session.** The comment on `TRADE_OFFER_ROWS` calls 8 "generous"; it was, on
  the data that existed when it was written.
- **When a cap and a data change point at each other, the data change wins the
  race and nobody notices.** A note recorded that making all eight Sanctum Keys
  tradeable *would breach the 8-offer cap*. It was true when written. A later,
  better-informed, wiki-driven change set all eight to tier 5 and rewrote three
  tests without touching the note it invalidated. See
  [`process.md`](process.md) on telling a decayed note apart from a guard
  removed without reading it.

`trade_offers` now collapses same-item offers (a trade-offer identity key on
the *game* item rather than the sim id, see
[`special-items-behaviour.md`](special-items-behaviour.md)), which takes tier
5's worst case from 12 to 5 and the sixteen Upgrade Disks from 16 to 1, with
**no observation-width change and therefore no retrain trigger**. That is what
makes raising the cap not urgent rather than what makes it unnecessary: the
cap is still 8, still silent, and raising it is a width change on the terms
above. `test_full_tier5_inventory_fits_the_offer_row_cap` is the guard that
the worst held inventory stays under it.

## `replays.jsonl` is not a sample

`rl/train.py::EpisodeRecorder` writes finished episodes under two independent
retention policies, and every record is tagged with a `why` field saying which
one kept it:

- **`"random"`** — an unbiased `sample_rate` slice.
- **`"top_window"`** — the *best* episode of every `top_every`-episode window,
  scored `(win, deepest_rank, rooms_placed)`.

**Only `why == "random"` records are a sample of the policy's behaviour.** The
`top_window` records are selected on the outcome, so any statistic computed
over the whole file — win rate, mean rooms placed, how often a room is drafted
— is biased upward by construction. Filter on `why` before measuring anything,
and say which subset a reported number came from.

Two operational residuals of the same design:

- **The best-of-window set is not capped**, while the sampled index is
  (`--max-runs`, default 20000). It grows at one entry per `--record-top-every`
  episodes; `--record-top-every 1` defeats the cap entirely.
- **`/api/runs` has no pagination**, and the run list is built into `innerHTML`
  wholesale. The cap bounds that payload as a side effect; raise `--max-runs`
  far above the default and the browser becomes the next limit, not the server.

The index itself is a `(offset, length)` seek into the file with a single line
parsed on demand, which replaced a full-record in-memory dict measured at 3,089
bytes per episode — 5.24× the on-disk size, ~31 GB at 10M episodes. That was
the real blocker on raising the sample rate at all.

Where the sample rate genuinely obstructs a measurement, the answer is
**event-triggered logging, not a higher sample rate**: `upgrades.jsonl` records
every upgrade decision unsampled, a ~200× gain in captured events per simulated
day over the 0.005 default.

## Measurement discipline

### Check the objective was reachable before blaming the policy

**Win rate is a content problem before it is a learning problem.** Reaching
Room 46 needs an Antechamber door opened, which needs a lever room drafted
*and* entered. Over 400 `greedy_rank` days on `all_unlocks_config` (mean 8.43
rooms placed):

| lever room | placed |
|---|---|
| `weight_room` | 6.8% |
| `great_hall` | 3.3% |
| `greenhouse` | 1.3% |
| `secret_garden` | 0.0% |
| `throne_room` | 0.0% |
| **any of them** | **11.0%** |

`P(antechamber reached) = 0.000`, `P(room 46) = 0.000`. **On ~89% of days no
lever room is placed at all, and victory is structurally unreachable before the
policy makes a single decision.** No amount of reward shaping fixes a day where
the win condition cannot be opened.

Stated so the number is not over-read: `greedy_rank` pushes north and does not
*seek* lever rooms, so 11.0% is "how often one turns up incidentally", not "how
often a determined player could get one". `secret_garden` reads 0.0% because
its key must first be found and this policy never pursues items — the key
mechanism itself works.

**Before tuning the reward again, check whether the objective was reachable at
all that day.** A win-rate denominator that includes structurally unwinnable
days is measuring room availability, not policy skill.

### Randomise presentation order before reading a preference

A policy's choice distribution over an offered menu measures position and
identity together unless they are made independent by construction. Where
options are returned in a deterministic order correlated with identity — as
`offer_variants` returns upgrade options sorted by room index — **the
presentation order must be shuffled independently of which options were
sampled**, or "prefers slot 0" and "prefers low-index options" cannot be told
apart. Randomising the offered subset as well removes the choice-set confound.
With both, position and identity are independent by design and no statistical
correction is needed.

## Deliberate divergences

- **Reward shaping is deliberately not owned here.** The two documents split at
  the vector boundary: what the agent perceives and can press is this file;
  what it is paid is [`rewards.md`](rewards.md).
- **`web/replay.py` flags where the training pipeline raises.** Same mismatch,
  two responses, on purpose — see "Raise, don't default".
- **The digest cannot see default changes.** Accepted, with a procedural
  mitigation, rather than closed by hashing every field.
- **The demo corpus is treated as disposable**, and that is what licenses the
  digest design above. Real demo files live only under the gitignored `runs/`
  tree, never in the repo; the test suite develops against
  `synthetic_demo_records`, which writes the exact producer schema with
  `why: "synthetic"` as the one intentional difference.
- **`forced` is suppressed on a concealed draft option** even though the
  engine knows it. Exposing it would narrow a hidden card's identity far more
  than any in-game tell does; rarity is exposed only through a security door,
  which is a canon leak. See [`drafting.md`](drafting.md).
