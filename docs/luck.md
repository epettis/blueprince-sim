# Luck and item spawns

How rooms yield resources, and how the self-balancing luck stat drives the
extra-item rolls. Code: `engine/items.py`; data: `data/items.json`
(wiki-sourced: blueprince.wiki.gg Luck + Item Spawns).

## Item spawns

Each room's item content (`Room.items`) has two parts:

- **Guaranteed items** always spawn when the player first enters the room.
  The pseudo-item `random` (Closet, Walk-In Closet, Attic) spawns a fixed
  *count* of random items and is luck-immune.
- **Additional items**: up to `additional_max` extra items, each spawning
  independently with the current luck probability. Fixed-content rooms
  (`additional_max == 0`) are unaffected by luck.

Each extra item's kind is rolled from a weighted table — coins 40, key 25,
gem 25, die 10. The exact distribution is not datamined; these weights are
community-informed estimates (confidence: inferred). A coin drop is a pile
of 1–5 coins.

Items are granted when the player **moves into** the room, not when it is
drafted.

## The luck curve

- Luck starts each day at **10**; the wiki documents that at **29** every
  room grants its maximum additional items.
- The spawn probability is interpolated **linearly** between the floor (0 →
  0%) and `max_effect_at` (29 → 100%). The real curve shape between those
  anchors is not documented; linear is an inferred placeholder, editable in
  `data/items.json`.
- **Self-balancing**: finding 2+ items in one room lowers luck by 1, so hot
  streaks cool off.

## Luck modifiers

- **Root Cellar**: +3 luck on entry.
- **Maid's Chamber** (`anti_luck`): approximated as −3 luck on placement,
  clamped at the floor of 0 so negative luck never misbehaves with the
  probability curve. As a red-room penalty it is negated by Shelter.
- **Rabbit's Foot**: the +3 bonus is in the data (`rabbits_foot_bonus`) but
  the item itself is out of scope for the sim.

## Relative item values

`data/items.json` also carries an `item_values` block (key 3.0, gem 3.0,
coin 1.0, die 4.0, step 0.5). These are **not game data** — they are the
relative resource values used by the shaped reward function and the greedy
policies (see `docs/rewards.md` and `docs/greedy-strategy.md`).
