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
| Antechamber north door opened | `+0.50` | the thing standing between the estate and Room 46 |
| Room 46, first arrival of the day | `+1.00` | the win |

The ordering tracks a real dependency chain, not merely a numeric one: the
Sanctum route runs Antechamber → Sanctum → back to the Antechamber → Room 46,
and `0.25 < 0.5 < 1.0` pays each step of it in order.

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
  potential is 0 and the milestone rewards are undiluted; a `dead_end`
  termination arrives with the sealing penalty already charged on the prior
  draft.
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
- **The Throne Room is priced above the Antechamber.** Drafting and entering
  one grid room pays `+0.5` while the whole rank-9 grind pays `+0.25`. That is
  the honest consequence of pricing the door rather than the walk, but it is an
  incentive inversion: it cannot repeat *within* a day, and nothing stops it
  repeating across the days of an attempt. Watch `P(north door opened)` against
  `P(reach Room 46)`; a wide gap is the signature.
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

## The proposed investment bonus for permanent upgrades

Owner's proposal (2026-07-28): pay **+0.5** for acquiring a permanent upgrade —
inserting an Upgrade Disk, and the equivalent unlocks — reasoning that it is
"not enough to win, but enough to overpower most other options". The intent is
sound: the per-day horizon cannot see cross-day value (see
[`greedy-strategy.md`](greedy-strategy.md), "The reward horizon"), so a proxy is
needed. Three measurements argue against this particular shape.

**1. +0.5 does not sit below the win — it dwarfs it.** The premise assumes wins
are common. They are not. Measured over 20,000 paired episodes of `greedy_rank`
on the all-unlocks day-20 config, `P(reach Antechamber) = 3.405%`, so the entire
expected return from playing for the objective is **≈ 0.034**. A guaranteed
`+0.5` is roughly **15x** that. It is not a thumb on the scale; it replaces the
objective. The rational policy becomes "collect disks, ignore the Antechamber",
which is the opposite of the intent — the owner's rule is *invest so you win
more later*, not *stop winning*.

**2. It would pay for a no-op.** Of the 18 upgrade-variant groups, **13 are
engine-identical**: every variant carries the same effects and guaranteed items,
so nothing downstream can tell them apart. And the one upgrade measured
end-to-end, Cloister of Orinda, has **no detectable causal value** pre-lock
(3.045% vs 3.405% control, deepest rank 5.51 vs 5.53 — see
[`upgrade-value-measurement.md`](upgrade-value-measurement.md)), exactly as
predicted while the Antechamber has no locks. Shaping toward upgrades today
teaches a preference for pressing a button that does nothing, which then has to
be unlearned once Task 9 and the upgrade effects land.

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
2. **Make upgrades matter first.** Write the variant effects and land the
   Antechamber lever (Task 9). There is no point rewarding the acquisition of an
   upgrade that changes nothing; fix the thing being measured before paying for
   it.
3. **Only then, if a proxy is still wanted**, calibrate it against the measured
   marginal win probability rather than against 1.0 — order `+0.02` to `+0.05`,
   not `+0.5` — cap it to once per upgrade slot per attempt so a repeatable
   source cannot farm it (`upgrade_disk_trade` is `persistence: permanent` and
   re-obtainable), and treat it as temporary scaffolding to delete once the
   horizon spans days.
