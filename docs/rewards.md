# Reward functions

The Gymnasium env's reward is pluggable (`env/rewards.py`, selected with
`--reward sparse|shaped|phased` on `blueprince-train`). A reward function is
called once per env step with the game, a pre-step snapshot, and the
terminated flag; `REWARDS` maps names to functions.

## The three milestones

All three reward functions share one objective signal, paid on the **first**
occurrence of each event in a day (an event flag on `GameState`, not a
terminal-step test):

| Milestone | Reward | Why |
|---|---|---|
| Antechamber, first arrival of the day | `+0.25` | prerequisite; where the day has to end up anyway |
| North door open **and** Antechamber reached | `+0.50` | the thing standing between the estate and Room 46 |
| Room 46, first arrival of the day | `+1.00` | the win |

The ordering tracks a real dependency chain, not merely a numeric one: the
Sanctum route runs Antechamber → Sanctum → back to the Antechamber → Room 46,
and `0.25 < 0.5 < 1.0` pays each step of it in order.

All three are computed in one place, `rewards.py::_milestones`, which `sparse`,
`shaped` and `phased` all call — the objective signal is the one part of the
reward that must not vary between modes, and
`test_sanctum_route.py::test_every_reward_mode_pays_the_same_milestone_total`
pins them against each other.

**The north-door reward is for the door opening, not for standing in the
Sanctum**, and **both levers pay it** — the Inner Sanctum's main lever and the
Throne Room's backup. They accomplish the same thing, so the reward stays
neutral about which route a policy learns. It is set at the two lever call
sites, unified through one `Game._open_north_door()` helper so they cannot
drift, and is **never** derived from the north segment's own door state: with
`antechamber_levers=False` the segment is never sealed to begin with, so a
state-derived reward would pay `+0.5` for free on every day of the pre-lever
baseline that config exists to reproduce. A dedicated test in
`test_sanctum_route.py` guards it.

### The milestone is ordered behind the Antechamber

`rewards.py::_north_door_credited` requires **both** `north_door_opened` and
`antechamber_reached` before the `+0.5` is paid; whichever lands second earns
it, so the day's total does not depend on the order. An open north door that
nobody can walk to accomplishes nothing:

- `antechamber → room_46` is the **only** edge into Room 46
  (`data/areas.json`), so the door leads somewhere only for a player who can
  stand in the Antechamber.
- The segment is **re-sealed at every day start** under `antechamber_levers`
  (`Game.reset`), so a lever pulled on a day the Antechamber is never reached
  leaves nothing behind for tomorrow either.

Ungated, the Inner Sanctum lever was reachable **entirely off-grid**: one
`travel` hop to `inner_sanctum` from the area graph paid `+0.492` net on
**40 of 40** seeds under `all_unlocks_config()`, at deepest rank 1 with zero
rooms drafted. That made "leave the house and walk to the Sanctum" the single
highest-value action available to a policy that never plays the game, and it
repeated every day of an attempt. Measured over 60 seeds on
`all_unlocks_config()`, gating it moves a pure-travel trajectory's day return
from `+0.518` to `+0.018` while leaving `frontier_greedy` (`+0.694`) and
`greedy_rank` (`+0.521`) unchanged to four decimal places — including
`frontier_greedy`'s own milestone term, since every north-door credit it
earned was already paired with an Antechamber arrival.

The gate also resolves the "Throne Room is priced above the Antechamber"
inversion recorded under *Deliberate divergences*: drafting and entering the
Throne Room now pays `+0.5` only on a day the rank-9 grind also succeeded.

## `sparse`

The three milestones and nothing else. The cleanest signal — exactly the
objective — but with 50–70 decisions per episode and single-digit win
rates early in training, it is a needle-in-a-haystack signal for PPO.

## `shaped`

A dense signal that decomposes progress per decision, on top of the
milestones:

- **Rank progress**: `+0.1` per rank of new deepest-rank progress
  (`deepest_rank` delta). Reaching rank 9 from rank 1 is worth ~0.8 total —
  most of a win — spread over the run.
- **Resource delta**: `+0.01 ×` the value-weighted change in gems, keys,
  coins, dice **and held special-item value**. The weights come from
  `item_values` in `data/tuning.json` (key 3.0, gem 3.0, coin 1.0, die 4.0) —
  the same relative values the greedy policies use; they are hand-tuned, not
  game data. Including `inventory_value` is what makes a purchase read as a
  trade of coin value for item value rather than a pure loss. Spending
  resources (keys on locks, gems on rooms) is a small negative that the
  downstream progress reward has to justify.
- **Path preservation** (`phi_paths`): a potential encoding the two-open-paths
  doctrine — `0.0` while two or more routes to the Antechamber survive,
  `−0.15` at exactly one, `−1.0` at zero. The draft that seals the last route
  eats ~`−1.0`, dwarfing any dead-end room's payout, and reopening a route
  pays it back. On a winning step the Antechamber is already reachable, so the
  potential is 0 and the milestone rewards are undiluted. On any `terminated`
  step (`shaped`/`phased` both take the flag and read it here) the potential
  is forced to `0.0` regardless of the sealed state, so a `dead_end` day's
  summed `phi_paths` contribution telescopes to `phi(end) − phi(start) = 0`
  rather than ending on the sealing `−1.0`, removing the one-sided bias an
  uncancelled terminal potential would otherwise add to every such day. This
  is not exact potential-based-shaping invariance in Ng's sense: the delta
  here is undiscounted (`Phi(s') − Phi(s)`, not `γ·Phi(s') − Phi(s)`) while
  training runs `γ = 0.999`, so the zeroing removes the endpoint bias without
  making the term provably policy-invariant on its own. `phased` zeroes its
  two other potentials (`phi_keys`, `phi_frontier`) the same way and for the
  same reason.
- **Placement frontier**: `+0.01` per way forward a newly placed room opens
  into an empty in-grid cell (its own outgoing doors; the doorway it was
  drafted through faces an occupied cell, so the count is bounded by 3 and a
  Dead End scores 0). Paid at the *placement*, not on entry.

  This exists because every other positive term lands one decision **after**
  the risk. Choosing a room pays nothing until the player walks in, while the
  `phi_paths` charge for that choice is immediate. Measured over masked-random
  fresh-save days, that made `choose` a near-zero-mean action — mean `+0.0009`,
  sd `0.1353`, worst `−1.001`, with **8.9%** of placements at or below `−0.15`
  — against a certain, bounded `−0.002` for a travel hop. Touring dominated
  drafting on risk while giving up nothing on mean, and a policy bouncing
  between two outdoor areas was the measured result: over 100 random-sampled
  episodes of `runs/freshsave-v2`, 58 reached rank ≤ 2, spent **75%** of their
  actions travelling, and bounced `blackbridge_grotto`↔`campsite` **1,411**
  times. That loop pays `−0.002` a hop and gains nothing — it is avoidance,
  not farming.

  With the term, `choose` reads mean `+0.0098` and the `choose − travel` gap
  widens from `+0.0031` to `+0.0120`. The `−1.0` tail is untouched, because
  that is `phi_paths` doing its job.

  **Not potential-based**, so it does change the optimal policy — deliberately.
  It cannot be farmed: a cell is placed once and the grid holds 45, so the term
  is bounded by the board rather than by a cap. `phased` does **not** share it;
  it prices forward pathways through `_phi_frontier` instead.

- **Repetition brake**: a `(location, action)` pair may be applied
  `REPEAT_FREE_USES` (3) times a day for nothing; each further use costs
  `REPEAT_PENALTY_STEP` (0.01) more than the last, flattening after
  `REPEAT_PENALTY_CAP` (5) steps at `−0.05`. Location is the grid cell on-grid
  and the area node id off it, so the same switch in two rooms is two habits.

  **Only actions that spend no game step are counted.** That is the whole
  failure class: a step-spending action pays for itself out of the day's
  budget, while a zero-step one is bounded by nothing but `max_env_steps`.
  Measured over 60 fresh-save days of drafting play, **every** `(location,
  action)` pair used more than three times was a `move` — so charging
  step-spending actions would tax normal play for something already priced.

  The case that prompted it turned out to be an engine trap rather than a
  preference: one recorded episode spent **622 of its 687 actions** flipping
  the Darkroom breaker, but with 0 steps left it had **no other legal
  action** and the day could not end. `Game.settle_day` fixes that cause;
  this brake is what prices repetition the player actually chooses. Under the brake those 622 flips cost **−31.5** against a typical
  day's return near `+0.5`. A drafting trajectory accrues **0.0000** penalty
  per day, so the brake is invisible to play that is not looping.

  **The switches are now capped in the mask, not priced here.** Measured on
  `runs/freshsave-v8` at 1.09M episodes, pricing did not change behaviour: 96%
  of episodes never touched a switch while **4% flipped one 238–934 times**,
  and those few carried **100%** of all toggles. The penalty made those
  episodes expensive without making them rarer, and the resulting rare large
  negative returns are what the critic then had to fit — `explained_variance`
  fell `0.865 → 0.399` and deepest rank was flat at ~3.7 from episode 4,000 to
  976,000. `actions.SWITCH_ACTIONS` are capped at `SWITCH_USE_LIMIT` uses per
  `(location, action)` per day, which equals `REPEAT_FREE_USES` so a capped
  switch never reaches the priced range at all.

  This generalises two earlier point fixes of the same shape — the lock-menu
  abandon cap ([`locking.md`](locking.md)) and the area revisit cap
  ([`areas.md`](areas.md)) — which bound specific zero-step loops by masking.
  Those stay: a mask stops a loop outright, while this prices any future one
  the mask does not know about. `sparse` is deliberately exempt, being the
  milestones and nothing else.

- **Time pressure**: `−0.001 × max(1, steps_spent)` — priced against the
  resource that actually ends runs. Step *gains* (food, the Orchard bonus) are
  clamped to zero spent rather than turned into a bonus, and the floor of 1
  means a zero-step decision still pays the flat `−0.001`.

Steps are deliberately absent from the resource delta: step spend is
already priced through the time-pressure term and the fact that running dry
ends the day.

## `phased`

A two-phase variant of `shaped` built around the lock system: gather
resources in ranks 1–4, then spend keys and keep pathways open in the
upper ranks. Locks never roll by chance below rank 4 and climb from 25%
to 130% by ranks 8–9, so keys are worth far more late — the flat resource
delta in `shaped` can't express that. Three terms differ; the gems/coins/dice
and held-item deltas, the path-preservation potential, the step-scaled time
pressure and the three milestones are the same. The time-pressure term is kept
in lockstep with `shaped` deliberately — its own docstring promises they
match, and a silent divergence between reward modes surfaces months later as
an unreproducible run.

- **Back-loaded rank progress**: `+0.05` per rank through rank 4,
  `+0.15` per rank for ranks 5–9 (`0.90` total, vs `shaped`'s flat
  `0.8`). Racing upward is no longer the dominant early signal, and a
  late key spend that buys a rank stays net-positive.
- **Rank-appreciating key potential**: instead of pricing keys only at
  pickup, the key stock carries a potential
  `0.01 × keys × key_value × mult(deepest_rank)` where `mult` is `1.0`
  through rank 3 and grows `+0.5` per rank after (`4.0` at rank 9); the
  reward is the per-step *change* in that potential. Each new rank past 3
  pays `+0.015` per key held, so carrying keys deep is itself rewarded,
  spending one early forgoes the appreciation, and spending one at rank 8
  costs `~0.105` — justified only by the `+0.15` rank it unlocks. This is
  potential-based shaping (`Φ(s′) − Φ(s)`), so it can't create
  reward-farming loops.
- **Frontier-breadth potential**: `0.02 ×` the number of *passable*
  frontier doorways (open, locked with a key in hand, or
  security-openable) in the deepest two ranks, capped at 4 — again
  rewarded as the per-step change. This pays for keeping several live
  ways forward at the leading edge instead of tunneling a single
  corridor, and because a key in hand makes locked doorways count as
  passable, banked keys literally buy back frontier breadth. Lock states
  are rolled at placement and visible in the observation's lock planes,
  so raw doorway count would credit doors the agent can see are dead.

The base `key` weight in `data/tuning.json` is deliberately untouched —
it is shared with the greedy policies, and raising it would silently
shift their baselines.

## Snapshot mechanics

`snapshot(game)` captures `deepest_rank`, the resource counters, held
inventory value, the three milestone flags, and the potentials (`phi_keys`,
`phi_frontier`, `phi_paths`) before each action; the reward reads deltas
against it after the action resolves.
The env owns calling it — reward functions are pure and stateless, so new
shapes can be added by writing one function and registering it in
`REWARDS`.

## The horizon spans days

A mid-attempt day ending is reported as `terminated=False, truncated=True`
rather than `terminated=True`. SB3's `DummyVecEnv` turns that into
`info["TimeLimit.truncated"]=True`, which makes
`OnPolicyAlgorithm.collect_rollouts` bootstrap `V(terminal_observation)`, so
cross-day investment becomes real value the agent can discover. Only the final
day of an attempt (`current_day >= n_days`) is a true terminal.

This is the correct model rather than merely the cheap one: the day boundary is
genuinely non-absorbing. Per-day telemetry is unaffected — `EpisodeRecorder`,
`DraftStats`, `AreaStats` and the win-rate counter all fire on
`done = terminated | truncated`, which is still True at day end.

**Bootstrapping is only half of it.** `V(s)` also has to be able to tell a
heavily-upgraded attempt from a fresh one, so four observation keys expose what
was accumulated: `day` (`[current_day, days_remaining]`), `carryover` (the
carry-over bools, sorted — see
[`scoping-and-carryover.md`](scoping-and-carryover.md)), `upgrade_slots` (one
bit per slot, in `upgrades.all_slot_ids()` order), and `disks_spent` (how many
finite one-time disk sources are used up).

`gamma` is 0.999 and exposed as a `--gamma` flag. A day measures ~31 env steps,
so 0.999 already gives ~32 days of lookahead; the discount was never the
bottleneck. (`max_env_steps = 1000` is a safety cap, not a typical day, and
reasoning about the horizon from it gives the wrong answer.)

## Deliberate divergences

- **Credit propagates by one-step TD, not by GAE across the attempt.** The
  truncation bootstrap is unbiased but slower to propagate than multi-step
  returns; a within-attempt rollout would expose every cross-day transition to
  GAE at once. This is a convergence-speed cost, accepted, not a correctness
  one.
- **The per-day reward ceiling is 1.75, up from 1.25.** The shaping constants
  were *not* rescaled when the north-door tier was added. If a retrain shows
  the dense terms drowned out, this is the first place to look.
- **The north door is priced above the Antechamber, but no longer reachable
  without it.** Opening the door pays `+0.5` while the whole rank-9 grind pays
  `+0.25` — the honest consequence of pricing the door rather than the walk.
  What made that an incentive inversion was that either lever could be reached
  without the Antechamber; ordering the milestone behind
  `antechamber_reached` (see *The milestone is ordered behind the Antechamber*)
  means the `+0.5` is now only ever collected on top of the `+0.25`. Watch
  `P(north door opened)` against `P(reach Room 46)`; a wide gap is still the
  signature of the remaining half — a policy that opens the door and stops.
- **Time pressure was recalibrated on principle, not on proof.** Moving from a
  flat per-decision charge to a per-game-step one is a correction — a travel
  hop consuming 4–8 steps had cost the same as a 1-step move while
  `out_of_steps` causes 68% of terminations — but the measurement behind it
  came from a 50k-episode policy that travels heavily regardless. The
  magnitude is not cosmetic: measured across 329 episodes the mean per-episode
  time term moved `−0.04494 → −0.08257`, about 1.84×.
- **`item_values` are hand-tuned, not game data**, and the `key` weight in
  `data/tuning.json` is deliberately untouched — it is shared with the greedy
  policies, and raising it would silently shift their baselines.
- **Cheap depth is probably overpaid, and the constants stay unchanged until
  the policy's own choice rate says so.** `deepest_rank` can reach 9 while the
  Antechamber stays literally unreachable: a `straight` room drafted north is
  always N|S, so a Tunnel spine has zero lateral connectivity by construction
  and a column-1 corridor can never reach the Antechamber in column 2.
  `_phi_paths` cannot see that, because it counts *global* frontier doorways
  rather than whether a room added branching — in the traced episode
  `distance_map()` reported the Antechamber unreachable from step 1 to
  termination while `deepest_rank` hit 9. Measured, a Tunnel placement nets
  **+0.109** against **+0.030–0.033** for an ordinary room: ~3.3× the reward
  density, risk-free and gem-free, and the gap applies to a freely *chosen*
  Tunnel too. The test is behavioural, not arithmetic — once the Tunnel is one
  of three offered options, measure how often the policy picks it, and treat a
  rate well above the ~33% base as the evidence that cheap depth is
  overvalued. Tuning before that measurement is tuning against a 50k-episode
  artifact.

  **That behavioural test cannot be run on the training fixture.** The Tunnel
  is `pool: found_floorplan`, and of the eight rooms in that pool only three
  (Conservatory, Throne Room, Treasure Trove) have a modelled way to be found;
  the Tunnel has no unlock flag at all, so it enters the deck only when a
  config names it in `found_floorplans` directly. Measured: `frontier_greedy`
  over 40 `fresh_save_config()` days was offered a Tunnel in **0 of 785** dealt
  hands, and a 150-day fresh chain unlocks **no** found floorplan on any day.
  Under `all_unlocks_config()`, which lists all of them, the same policy saw
  one in 37 of 943 hands and placed 25. So the Tunnel — and with it the
  self-chaining `tunnel_chain` waiver in `engine/draft.py`, which is real and
  does deal a second Tunnel from a placed Tunnel's north doorway — is a
  property of that preset, not of a fresh save. The cheap-depth concern itself
  survives without it: `corridor` (base pool, gem-free, commonplace, `straight`)
  is the fresh-save floorplan with the same zero-lateral-connectivity shape,
  minus the self-chain.

## The constants this reward ships with are untuned, deliberately

**Owner ruling: the reward is good enough to train on as it stands.** With the
north-door milestone ordered behind the Antechamber, the owner accepted the
shape and authorised the retrain rather than tuning first. Two consequences
worth stating, because both are choices and not oversights:

- **No per-flag unlock bonus was added.** A fresh save earns its first carry
  flag one action deep (travel to `apple_orchard`), but the day that earns it
  scores `−0.004` and nothing else, so the flag's value reaches the policy only
  through the day-boundary bootstrap. Making it visible was considered and
  declined for now; the case against a flat acquisition bonus is the same one
  the upgrade proxy below fails, and any future attempt should start there.
- **`special_item_values`, the `PATHS_*` penalties and the scepter bias are
  unchanged.** They were set without multi-day run data behind them and still
  are. `runs/freshsave-v1` (fresh save, `--multi-day 1000`, 30 envs,
  `reward=shaped`) is the run generating the statistics they were always
  waiting on.

## The proposed investment bonus for permanent upgrades

Owner's proposal (2026-07-28): pay **+0.5** for acquiring a permanent upgrade —
inserting an Upgrade Disk, and the equivalent unlocks — reasoning that it is
"not enough to win, but enough to overpower most other options". The intent is
sound: the per-day horizon cannot see cross-day value (see
[`greedy-strategy.md`](greedy-strategy.md), "The reward horizon"), so a proxy is
needed. Three measurements argue against this particular shape.

**1. +0.5 does not sit below the win — it dwarfs it.** The premise assumes wins
are common. They are not. Under the shipped config (`door_locks=True`,
`antechamber_levers=True`), `greedy_rank`'s `P(reach Antechamber) = 0.975%`
(n=4000, seeds 0–3999, `all_unlocks_config()` — see
[`greedy-strategy.md`](greedy-strategy.md)'s baselines), so the entire expected
return from playing for the objective is **≈ 0.0098**. A guaranteed `+0.5` is
roughly **51x** that. This argument was first written against the pre-lock
measurement — `greedy_rank`'s `P(reach Antechamber) = 3.405%` over 20,000
paired episodes, taken before Antechamber locks shipped and under the pre-#364
`all_unlocks_config()`, so it is a separate fixture and not seed-comparable
with the number above — where `+0.5` was already ≈**15x** the ≈0.034 expected
return. The conclusion does not turn on the exact multiplier: at 51x the bonus
is still worth more than fifty attempts at the objective, so anything within an
order of magnitude of either measurement supports it. It is not a thumb on the
scale; it replaces the objective. The rational policy becomes "collect disks,
ignore the Antechamber", which is the opposite of the intent — the owner's
rule is *invest so you win more later*, not *stop winning*.

**2. It would pay for a no-op.** Of the 18 upgrade-variant groups, **13 are
engine-identical**: every variant carries the same effects and guaranteed items,
so nothing downstream can tell them apart. And the one upgrade measured
end-to-end, Cloister of Orinda, had **no detectable causal value** in the
pre-lock forced-upgrade A/B — see
[`upgrade-value-measurement.md`](upgrade-value-measurement.md)'s "Pre-lock
result" for the numbers — exactly as predicted while the Antechamber had no
locks. **The Antechamber lever gate has since shipped, but no post-lock
re-measurement was taken before it did** — see that document's status note for
why the paired before/after comparison this argument wanted can no longer be
run. Shaping toward upgrades on the strength of a stale pre-lock number risks
teaching a preference this repo can no longer verify either way.

**3. Potential-based shaping cannot express it.** The existing shaping terms
(`_phi_paths`) are potential-based, which is *why* they are safe: a potential
difference provably leaves the optimal policy unchanged. That guarantee is
exactly what makes it unable to create a lasting preference for disks. So a flat
`+0.5` is not shaping in the sense the rest of this file uses — it is a **second
objective competing with winning**, and should be understood and reviewed as one.

### What was done, in order

1. **Extended the horizon (done, 2026-07-29).** Day endings in multi-day
   (chain) mode are now reported as `terminated=False, truncated=True` rather
   than `terminated=True`. SB3's DummyVecEnv converts that into
   `info["TimeLimit.truncated"]=True`, which makes
   `OnPolicyAlgorithm.collect_rollouts` bootstrap `V(terminal_observation)`
   so cross-day value flows back through the value function. The final day of
   an attempt is still a true terminal. Two new observation keys (`day` and
   `carryover`) expose the day index and carried flags so `V(s)` can tell
   day 2 from day 190. Per-day episode telemetry is unchanged
   (`done = terminated | truncated` is still True at day end, so SB3's
   episode counter fires as before).
2. **Make upgrades matter first.** Write the variant effects, and land the
   Antechamber lever gate (done — [`antechamber-lever-design.md`](antechamber-lever-design.md)).
   There is no point rewarding the acquisition of an upgrade that changes
   nothing; fix the thing being measured before paying for it.
3. **Only then, if a proxy is still wanted**, calibrate it against the measured
   marginal win probability rather than against 1.0 — order `+0.02` to `+0.05`,
   not `+0.5` — cap it to once per upgrade slot per attempt so a repeatable
   source cannot farm it (`upgrade_disk_trade` is `persistence: permanent` and
   re-obtainable), and treat it as temporary scaffolding to delete once the
   horizon spans days.
