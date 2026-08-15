# Measuring what an upgrade is worth — plan

Status: **the difference-in-differences design below needs replacing.** The
Antechamber lever gate ([`antechamber-lever-design.md`](antechamber-lever-design.md))
has shipped, which was meant to supply the "after" arm of Phase 1's paired
comparison. The **"before" (pre-lock) arm was taken** — see "Pre-lock result"
under Phase 1 below — but the paired **post-lock** re-measurement needed to
complete the before/after difference-in-differences was never taken before the
lever gate shipped, and there is no way to put a shipped attempt back into an
unlocked-Antechamber state to take it now. Phase 0, the Observatory plumbing
(Phase 2) and the sequencing rationale below are still accurate; the Phase 1
measurement plan itself needs a design that does not depend on a closed
window.

Companion to [`upgrade-disks-design.md`](upgrade-disks-design.md), which covers
the draw mechanism itself (merged in PR #33). This document covers how we decide
whether a given upgrade is any *good*, and how that surfaces in the Training
Observatory.

Disks shipped alone specifically so Cloister of Orinda's value could be measured
before Antechamber locks exist and again after: if Orinda does not become more
valuable once an Antechamber door is worth opening, either the upgrade model or
the lock model is wrong. That comparison was the validation signal, and this
document is about making it trustworthy — but see the status note above: only
the pre-lock arm was ever taken, and the window to take the paired post-lock
arm is now closed permanently.

## Four different questions, often confused

| Question | What it measures | Why it fails alone |
|---|---|---|
| **Availability** | How often the option is offered at all | Not a value signal — it is the *denominator* |
| **Preference** | Given offered, does the policy pick it | Confounded by what it was offered against |
| **Utilization** | Is the upgraded room actually drafted after | A high rate may just mean the base room was common |
| **Causal value** | Does holding the upgrade change outcomes | Requires intervention, not observation |

"How valuable does the agent *think* this is" is **preference**. "How valuable is
it *really*" is **causal value**. They are different numbers and only one of them
can currently move.

## Why preference is not measurable today

**Measured under real multi-day play** with `greedy_rank`, ~83,000 upgrade events
per arm (2026-07-27):

| Arm | Orinda offer rate | 95% CI (Wilson) |
|---|---|---|
| A — Catacombs locked (pre-#35) | 0.3705% | [0.3315%, 0.4141%] |
| B — as shipped, same-day Tomb gate | 0.4005% | [0.3499%, 0.4585%] |
| C — Catacombs always unlocked (ceiling) | 0.7094% | [0.6546%, 0.7688%] |

Paired A vs B lift is **1.11x at z = 1.06 — not significant**. Even the
always-unlocked ceiling is only **1.91x**.

### The bottleneck is Cloister's rarity

Not the Catacombs gate, and not the `min_drafts` bracket. Measured:

- P(Cloister offered, per day) = **5.87%**
- P(drafted | offered) under `greedy_rank` = **21.0%**
- P(`draft_counts['cloister'] >= 1`) at disk insert = **11.28%**

So 88.7% of upgrade events have never drafted a Cloister, which fails line 7's
`min_drafts` bracket before the Catacombs check is even consulted. But the bracket
is a *symptom*: the same rarity also starves lines 1 and 11.

**The decisive evidence is the policy contrast.** If `greedy_rank` were rejecting
the Cloister, a random policy would do better. It is **6x worse** (0.062%) — it
reaches fewer disk readers and accepts Cloister only 6.5% of the time versus
greedy's 21%. A purpose-built Cloister-seeking policy gains **1.03x**, inside the
noise. Policy is not the lever.

**This is not a modelling bug.** The wiki confirms Unusual rarity, 3 gems, and
placement restricted to the centre 21 tiles; `deck_copies=1` and the cross layout
match. The frequency boosts are the only levers that touch the real bottleneck,
and of the three only the **Southern Cross** is unmodelled — the **Terrace**
(making the Cloister free while on the estate) and the **Greenhouse** boost both
work today. See [`drafting.md`](drafting.md) for all three.

One structural detail: a failed bracket abandons the **entire** chain line, so
when Cloister's `min_drafts` fails on line 7, the parlor / aquarium / mail_room
entries behind it are never reached either.

### Consequence

Observing an Orinda decision naturally needs ~25,000 upgrade events (~73,000 days).
That figure is dominated by `--record-sample-rate`, which defaults to 0.005 — the
offers *do* occur (123 real ones in a 90,000-day run) and are simply discarded.
Event-triggered `upgrades.jsonl` logging now captures every upgrade decision
unsampled, which is a 200x gain in captured events per simulated day.

Even so, preference measurement should be **abandoned in favour of the
forced-upgrade A/B** below: it presets the variant and needs no offer, no bracket,
no Catacombs check, and no rare draw.

## Phase 0 — Uniformity check

**Value.** Answers one question cheaply: *has the policy learned anything about
upgrade choices?* The answer decides whether preference is usable at all, so this
runs before anything else is built.

**Method.** Roll out under normal play. At sampled mid/late-attempt steps, clone
the state, force `Phase.UPGRADE_PENDING`, inject a random 3-subset of a slot's
variants, encode the observation, and read the policy's distribution over the
three legal actions. About 20,000 decisions.

**The gotcha that would silently ruin it.** `offer_variants` returns options
sorted by room index, so presentation order is deterministic and correlated with
variant identity. The presentation order must be **shuffled independently of
which three were sampled**, or "prefers slot 0" and "prefers low-index variants"
cannot be told apart. With that randomization, position and identity are
independent by construction and both of these are unbiased:

- **Slot-position bias** — P(pick slot 0 / 1 / 2), marginalized over variants.
- **Variant preference** — P(pick *v* | *v* offered), marginalized over position.

Randomizing the offered subset is also what removes the choice-set confound —
Orinda is not penalized for happening to be drawn against a strong rival. This
is why no Bradley-Terry / Plackett-Luce fit is needed: randomization handles by
design what the model would have had to correct for statistically.

**Interpreting the result.**

- *Variant preference flat (~1/3 each when offered)* — no learned representation.
  Preference metrics are dead; fall back on Phase 1. **This is the expected
  outcome**, because the choose actions are slot indices, variant identity lives
  only in the observation, and masked actions receive no gradient at all — so
  the network has had essentially no signal connecting the two.
- *Slot bias strong, variant preference flat* — the network is responding to
  action position and ignoring the `upgrade_options` observation entirely.
- *Variant preference non-uniform* — **not yet evidence of learning.** Untrained
  output weights sit near initialization and produce a stable, reproducible
  ranking that looks exactly like a real preference.

**The discriminator.** Compare two training runs with **different init seeds**.
A learned preference agrees across runs; an initialization artifact does not.
This is the actual test, and it is why a million samples buys nothing: 20k
already gives about +/-1.1% per variant, far tighter than the validity of the
estimate.

## Phase 1 — Forced-upgrade A/B

**Value.** Measures what an upgrade is worth *to the world*, independent of
whether the policy knows it exists. This is the only one of the two measurements
that can deliver the task-9 signal.

**Method.**

- Fixed seed list, shared by both arms.
- Control arm: `upgrade_disks = frozenset()`.
- Treatment arm: `upgrade_disks = {variant_id}`.
- Same policy, same seeds, paired per-seed differences.

Presetting `upgrade_disks` survives into day 1 and across a chain wrap only
because of the `DayChain` fix in PR #33; before it, the preset was silently
wiped and this experiment would have measured nothing.

**Use the scripted `greedy_rank` policy as the primary instrument.** Comparing
Orinda before and after Antechamber locks requires a retrain in between, so a
learned-policy comparison is confounded by the measuring instrument changing
between the two measurements. A fixed scripted policy holds it constant — and,
usefully, needs no checkpoint, so Phase 1 can run without waiting for a retrain.
Run the learned policy as a secondary realism check.

**Pair the seeds.** The base rate is a property of the chosen instrument, not
of the config, and the two halves of the objective behave completely
differently. Under the shipped config (`door_locks=True`,
`antechamber_levers=True`) on `all_unlocks_config()` (n=4000, seeds 0–3999 —
see [`greedy-strategy.md`](greedy-strategy.md)'s baselines):

- **Antechamber.** `greedy_rank`, the instrument specified above, measures
  **0.975%** (Wilson 95% CI 0.714%–1.330%) — still under 1%, so the pairing
  argument holds for it. But `frontier_greedy` measures **6.625%** (CI
  5.895%–7.438%), which is not a low base rate in the same sense. Anyone
  switching instruments must redo the power calculation rather than inherit
  this one; the phrase "sub-1% base rate" below is about `greedy_rank`
  specifically.
- **Room 46.** **0.000% for every scripted policy tried, across 16,000
  episodes.** Unchanged, and not a matter of which instrument is chosen.

Comparing two independent Antechamber rates at `greedy_rank`'s level still
needs an enormous N. With identical seeds, seed-level difficulty cancels, most
pairs give exactly zero, and power comes from the discordant pairs (McNemar)
rather than from N directly — **but at a literal-zero Room-46 rate, a McNemar
design over that outcome has no discordant pairs at all**: both arms report
zero wins on every paired seed, so there is nothing to count. Room 46 is not a
usable McNemar outcome until some policy reaches it at least occasionally; this
is a design fact, not a sample-size problem, and it is the half of the
objective that no config change has yet moved off zero.

**Lead with deepest rank, not win rate.** At `greedy_rank`'s sub-1% base rate
the binary outcome is badly underpowered for the effect sizes in play, and
Room 46 in particular is unmeasurable this way for every scripted policy. Mean
deepest rank is near-continuous and much more sensitive. Report both; headline
the rank.

**Always run control upgrades alongside.** Measure two or three upgrades
unrelated to the Antechamber — Storeroom keys and Boudoir dice are good
candidates — in both epochs. The validating comparison is the
**difference-in-differences**, not Orinda's raw change.

**Reading it for the Antechamber lever comparison.**

- Orinda's delta rises while controls stay flat — upgrade and lock models agree.
- Orinda flat, controls flat — either locks do not make Antechamber doors
  valuable, or Orinda's effect never reaches the outcome. Both are real bugs,
  which is exactly why disks shipped alone.
- Everything moves together — global difficulty shift; inconclusive, re-baseline.

**Caveat to print next to every number.** A preset upgrade only puts the variant
in the deck; the agent still has to draft it. So the measured effect bundles
utilization, which is the honest real-world value — but a variant the agent
never drafts measures about zero even if it would be strong when used. Report
the post-upgrade draft rate beside every delta so that case is visible rather
than mysterious.

### Pre-lock result (2026-07-28)

The forced-upgrade A/B for Cloister of Orinda was run once, before the
Antechamber lever gate shipped (2026-07-30): treatment (Orinda preset)
P(reach Antechamber) **3.045%** vs. control **3.405%**, mean deepest rank
**5.51** vs. **5.53**. No detectable causal value, exactly as predicted while
the Antechamber had no locks worth opening. This is the "before" arm of the
paired before/after comparison described above — it **was** taken. What was
never taken, and can no longer be taken now that the lever gate has shipped
without a matching post-lock run, is the paired **post-lock** re-measurement
needed to compute the difference-in-differences.

## Phase 2 — Training Observatory (partly shipped)

The binding constraint: the Observatory server is **deliberately torch-free**.
It shells out to `blueprince-train --evaluate` as a subprocess precisely so torch
never loads into the web process. All computation therefore lands in that
subprocess; the server only renders.

**What has shipped is not what this section specifies.** `Observatory.upgrade_stats()`
(`web/server.py`) reads `upgrades.jsonl` (event-triggered, unsampled — see
"Consequence" above) and feeds a Dashboard-tab panel (`static/app.js`'s
`renderUpgradeStats()`) with three blocks: per-variant offered/chosen counts and
selection rate, a "disk economy over time" chart (mean disks held / mean slots
upgraded), and gate-context tiles (decisions, Catacombs-unlocked count,
zero-draft-count decisions). None of that is **preference** or **causal value**
in this document's sense — it is availability and utilization telemetry. The
`eval.jsonl`-based causal panel this section specifies below — `d_rank`,
`d_win`, `n_discordant`, `drafted_rate`, `slot_bias`, the delta-over-checkpoints
chart, and the Runs-tab `upgrade` frame field — remains unbuilt.

**Data channel.** Extend `eval.jsonl` — already written by the eval subprocess,
already read by `Observatory.eval` — with an `upgrades` block. Per variant:

- `d_rank`, `d_rank_ci95` — causal delta in mean deepest rank (primary).
- `d_win`, `d_win_ci95` — causal delta in win rate.
- `n_discordant` — discordant pair count, the real source of power.
- `drafted_rate` — post-upgrade draft rate, for the utilization caveat above.
- `p_choice`, `offered`, `chosen` — preference, when it becomes meaningful.

Plus one global `slot_bias` triple. No new plumbing is required.

**New "Upgrades" panel** on the Dashboard tab, following the established pattern:
a `<section class="card">` in `static/index.html`, a `render*()` function in
`static/app.js` called from `refreshDashboard()`, and a `case "/api/upgrades":`
branch on `Handler.do_GET()` in `web/server.py`.

One row per variant, sorted by `d_rank`. Two display requirements, both forced by
how rare these events are:

- an explicit **n** column, with low-sample rows greyed out;
- a visual distinction between **"measured about zero"** and **"never
  measured"**. Conflating those is the likeliest misreading, and for Orinda it is
  the difference between "this upgrade is worthless" and "we have no data".

**Delta-over-checkpoints time series.** Per-variant delta across checkpoints,
with Orinda and the control upgrades on the same chart. This is the task-9
validation view: the difference-in-differences reads directly off the picture,
and a global shift is immediately obvious.

**Runs tab.** Add an `upgrade` field to frames whose phase is `UPGRADE_PENDING`,
mirroring the existing `pending` draft-hand dict, so individual upgrade decisions
are inspectable in replay.

**Explicitly not in the server.** The A/B runner is a long compute job and
belongs on the existing eval-worker subprocess path.

## Phase 3 — Make preference learnable (conditional)

Only worth doing if preference should become a real tracked signal rather than a
diagnostic. The levers, in measured order of effect:

- **Model the Terrace and Southern Cross / Greenhouse frequency boosts.** These
  are the only levers that touch the actual bottleneck (Cloister's 5.87% per-day
  offer rate). Currently listed as known simplifications.
- **Raise disk supply**, which multiplies upgrade events per attempt and so the
  absolute count of Orinda observations, without changing the rate.
- Unlocking the Catacombs is worth at most **1.91x** and, under the shipped
  same-day Tomb gate, a statistically insignificant **1.11x**. It is not a lever.

With either or both, Phase 0 stops being an instrument check and becomes a
metric worth plotting over training.

## Sequencing

1. **Outside-area graph** — landed; see the argument below.
2. **Phase 1 harness with `greedy_rank`** — no retrain needed.
3. **Retrain on merged main** — required regardless, since PR #33 changed the
   action space to `Discrete(279)` and the phase observation to `Discrete(4)`,
   so no pre-#33 checkpoint loads.
4. **Phase 0 uniformity check** on the new checkpoint.
5. **Phase 2 Observatory panel**, once there is data to render.
6. ~~Antechamber locks, retrain, re-run Phase 1, compare
   difference-in-differences.~~ The locks have shipped, but no pre-lock
   baseline was taken before they did, so this step as designed can no longer
   run — see the status note at the top of this document.

### Why the area graph had to come first

- It supplies **Blackbridge Grotto**, the fifth disk-reader terminal, currently
  the one modelled terminal with no room record.
- It changed the action and observation spaces, so bundling it with the upgrade
  retrain cost **one** retrain instead of two.
- The pre-lock and post-lock measurements must differ **only** by locks, so it
  was safe before the baseline and unsafe between the two measurements. Before
  was the only cheap window, and it took it.

That precondition on step 2 is now met. **A different one replaces it**: the
Conservatory batch moved both spaces again, so a baseline is bankable only on a
checkpoint trained after that batch.

### What the Catacombs gate actually needs

The Catacombs unlock does **not** require the area graph. Access is gated on
drafting and entering the **Tomb**, which is already one of the eight modelled
outer rooms, and the sim already assumes the player solves any puzzle in a room
they enter. `catacombs_unlocked` is therefore a same-day check on the Tomb
(`flags.unlocks_catacombs`), landed ahead of the area graph.

This gate never needed the area graph either.

**The Catacombs gate was measured and does not deliver.** It was landed on the
strength of a projected 42x lift computed from synthetic contexts. Under real
play the realized paired lift is **1.11x (z = 1.06, not significant)** and the
always-unlocked ceiling is **1.91x** — see the measured table above. The gate is
correct modelling that does not move the number, because Cloister's rarity, not
the gate, is the constraint.

## Open decisions

- **Disk supply** — RESOLVED: all 16 sources are modelled. All 16
  `upgrade_disk` item records are `implemented: true`; `the_foundation` and
  `mine_south` are both `modelled: True` area nodes.
- **A/B scope** — all 16 upgrades per eval, or a watchlist of Orinda plus
  controls with an occasional full sweep? The watchlist is recommended.
