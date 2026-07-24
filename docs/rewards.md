# Reward functions

The Gymnasium env's reward is pluggable (`env/rewards.py`, selected with
`--reward sparse|shaped` on `blueprince-train`). A reward function is
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

## Snapshot mechanics

`snapshot(game)` captures `deepest_rank` and the resource counters before
each action; the reward reads deltas against it after the action resolves.
The env owns calling it — reward functions are pure and stateless, so new
shapes can be added by writing one function and registering it in
`REWARDS`.
