# Reward functions

The Gymnasium env's reward is pluggable (`env/rewards.py`, selected with
`--reward sparse|shaped|phased` on `blueprince-train`). A reward function is
called once per env step with the game, a pre-step snapshot, and the
terminated flag; `REWARDS` maps names to functions.

## `sparse`

`1.0` on the terminal step of a won day (the player walked into the
Antechamber), `0.0` everywhere else. The cleanest signal — exactly the
objective — but with 50–70 decisions per episode and single-digit win
rates early in training, it is a needle-in-a-haystack signal for PPO.

## `shaped`

A dense signal that decomposes progress per decision:

- **Rank progress**: `+0.1` per rank of new deepest-rank progress
  (`deepest_rank` delta). Reaching rank 9 from rank 1 is worth ~0.8 total —
  most of a win — spread over the run.
- **Resource delta**: `+0.01 ×` the value-weighted change in gems, keys,
  coins and dice. The weights come from `item_values` in `data/tuning.json`
  (key 3.0, gem 3.0, coin 1.0, die 4.0) — the same relative values the
  greedy policies use; they are hand-tuned, not game data. Spending
  resources (keys on locks, gems on rooms) is a small negative that the
  downstream progress reward has to justify.
- **Time pressure**: `−0.001` per decision, a light incentive to finish.
- **Win bonus**: `+1.0` on the terminal step of a won day, same as sparse.

Steps are deliberately absent from the resource delta: step spend is
already priced implicitly through the time-pressure term and the fact that
running dry ends the day.

## `phased`

A two-phase variant of `shaped` built around the lock system: gather
resources in ranks 1–4, then spend keys and keep pathways open in the
upper ranks. Locks never roll by chance below rank 4 and climb from 25%
to 130% by ranks 8–9, so keys are worth far more late — the flat resource
delta in `shaped` can't express that. Three terms differ; gems/coins/dice
deltas, the `−0.001` time pressure, and the `+1.0` win bonus are the same.

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

`snapshot(game)` captures `deepest_rank`, the resource counters, and the
`phased` potentials (`phi_keys`, `phi_frontier`) before each action; the
reward reads deltas against it after the action resolves.
The env owns calling it — reward functions are pure and stateless, so new
shapes can be added by writing one function and registering it in
`REWARDS`.

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
