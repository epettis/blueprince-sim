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
  coins and dice. The weights come from `item_values` in `data/items.json`
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

The base `key` weight in `data/items.json` is deliberately untouched —
it is shared with the greedy policies, and raising it would silently
shift their baselines.

## Snapshot mechanics

`snapshot(game)` captures `deepest_rank`, the resource counters, and the
`phased` potentials (`phi_keys`, `phi_frontier`) before each action; the
reward reads deltas against it after the action resolves.
The env owns calling it — reward functions are pure and stateless, so new
shapes can be added by writing one function and registering it in
`REWARDS`.
