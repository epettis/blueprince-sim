# Luck and item spawns

How rooms yield resources, and how luck drives the extra-item rolls. Code:
`engine/items.py`, `engine/effects/tier1.py`; data: `data/items.json`
(wiki-sourced: blueprince.wiki.gg Luck + Item Spawns).

## Item spawns

Each room's item content (`Room.items`) has two parts:

- **Guaranteed items** always spawn when the player first enters the room.
  The pseudo-item `random` (Closet, Walk-In Closet, Attic) spawns a fixed
  *count* of random items and is luck-immune.
- **Additional items**: up to `additional_max` extra items, whose count is
  rolled once per draft from the published item-count ladder (below), then
  clamped to `additional_max`.

Each extra item's kind is rolled from a weighted table — coins 40, key 25,
gem 25, die 10. The exact distribution is not datamined; these weights are
community-informed estimates (confidence: inferred). A coin drop is a pile
of 1–5 coins.

Items are granted when the player **moves into** the room, not when it is
drafted.

Not every room rolls the ladder. `data/items.json`'s `never_roll_rooms` names
the rooms (Entrance Hall, Rotunda, Room 8, Closet and its three Upgrade Closet
variants, Walk-in Closet, Attic, Chamber of Mirrors, Freezer, Antechamber,
Passageway, Locksmith, Showroom, Gift Shop, Vestibule, Mechanarium, Treasure
Trove, Toolshed, Shelter, Shrine) that skip `roll_ladder_count` entirely — no
Luck Penalty accrues for them either. A room with `additional_max == 0` that
is NOT on this list still rolls and discards the result, and still pays the
Luck Penalty for whatever band it lands in.

Five rooms transform the ladder's raw count before the `additional_max`
clamp (`data/items.json`'s `count_transforms`, wiki: each room's own page):
Nook and its three variants (`reduce_by_one_chance`), Study
(`zero_becomes_one`), Guest Bedroom/Guess Bedroom (`zero_becomes_one_or_gem`),
Den (`one_becomes_trunk`, resolved at grant time), Lost & Found
(`not_modeled`, a documented no-op).

## The item-count ladder

Luck starts each day at **10** (`data/items.json`'s `luck.day_start`).
`engine/items.py::roll_ladder_count` resolves a room's extra-item count from
the published step ladder (`item_ladder.bands`, wiki "Luck effects"
DataMinedBox), keyed on **effective luck** = `state.luck` + per-draft
modifiers (`special_items.luck_bonus`: Rabbit's Foot/Lucky Purse;
`engine/items.py::draft_luck_bonus`: Veranda/Spare Veranda, see below) −
`state.luck_penalty`:

| Effective luck | Outcome |
| --- | --- |
| ≤4 | 7% for 1 item, 93% for 0 |
| 5–10 | 1 item with a probability chosen by the first-matching condition (Room 46 reached → 15%; day ≥6 → 25%; Veteran Mode → 15%; day ≥3 → 20%; otherwise → 18%), else 0 |
| 11–15 | 1.6% variable, 38.4% for 1, 60% for 0 |
| 16–18 | 3.2% variable, 76.8% for 1, 20% for 0 |
| 19–22 | always variable |
| 23–28 | 3 items, +2 Luck Penalty |
| 29+ | 4 items, +3 Luck Penalty |

"Variable" re-resolves against the SAME effective luck (`item_ladder.variable`):
≤10 → 1 item; 11–16 → 2 items, +1 Luck Penalty; 17+ → 5% for 3 items (+3
Luck Penalty), 95% for 2 items (+1 Luck Penalty).

**Luck Penalty** (`state.luck_penalty`) is a separate per-day accumulator,
grown by the bands/outcomes above, then subtracted from luck to form the NEXT
draft's effective luck. It is not itself luck, is not clamped, and resets to
0 at day start alongside luck. The wiki mentions the Luck Penalty on exactly
three pages and **never states its reset scope**; per-day is an owner ruling.
Per-day also avoids a real cost: a per-save penalty would have needed a new
carry channel, because `DayChain._CARRYOVER_KEYS` holds bools only and cannot
hold an int (see [`scoping-and-carryover.md`](scoping-and-carryover.md)).

Effective luck can also decide a bonus special-item spawn: at
`spawn_rules.high_luck_at` (16) or above, a luck-proc's special-item pool
gains the room's high-luck entries (`engine/special_items.py::roll_special_spawn`,
same effective-luck formula as the ladder).

## Stored luck modifiers

Applied to `state.luck` itself, unclamped in either direction — negative
luck resolves through the ladder's lowest band the same as any other value:

- **Maid's Chamber** (`anti_luck`): −7 luck on placement (wiki DataMinedBox:
  "Maid's Chamber: -7 when drafted"). As a red-room penalty it is negated by
  Shelter.

  The magnitude is **provable, not a trust call**, and the proof is why the
  clamp above had to go. The Dowsing Rod's datamined box says its low-luck
  branch is reachable *"only ... having 4 Maid's Chambers drafted"*. At −7,
  four drafted gives `10 − 28 = −18` stored luck, `+32` (the Rod's own bonus)
  `= 14`, which is ≤18 and matches; three drafted gives 21, which does not. At
  −3 the same arithmetic gives 30 and the branch is unreachable at any count.
  Only −7 satisfies both halves, and reaching −18 is what requires luck to go
  unclamped. The derivation lives in `tests/rooms/test_maids_chamber.py`'s
  docstring so it cannot be "simplified" back.
- **Root Cellar**: no luck effect modelled. Its real effect spreads dig spots
  to other rooms, which needs a house-wide dig-spot model this sim does not
  have; the wiki's datamined luck-modifier list does not include it either.

## Per-draft luck modifiers

Wiki framing (Luck page DataMinedBox): "When drafting a room, if the
condition is met, additional modifiers are applied for that draft (without
modifying the current luck value)." These add into the effective-luck
formula above for one room's own item roll only; `state.luck` never changes.

- **Rabbit's Foot / Lucky Purse** (`special_items.luck_bonus`): +3 while
  either is held, applied to every draft.
- **Veranda** (`engine/items.py::draft_luck_bonus`, tag `draft_luck` with a
  `ladder` param): while placed, +12 for the first green room drafted each
  day, +6 for every later one (wiki: "first one in a day gives +12, all
  later ones give +6. Applied if the room you drafted is green"). The
  per-day use count lives in `state.special.draft_luck_uses`, keyed by the
  bearer room's id.
- **Spare Veranda** (same tag, flat `amount` param): while placed, +6 for
  every green room drafted, no first/later split (wiki: "+6 per. Applied if
  the room drafted is green").

`draft_luck` is read generically off every placed room's effects (category
check + ladder-or-flat amount) — no engine module branches on a room id for
this mechanic.

## Relative item values

`data/tuning.json` carries an `item_values` block (key 3.0, gem 3.0,
coin 1.0, die 4.0, step 0.5). These are **not game data** — they are the
relative resource values used by the shaped reward function and the greedy
policies (see [`rewards.md`](rewards.md) and
[`greedy-strategy.md`](greedy-strategy.md)). They live in `tuning.json` rather
than `items.json` precisely because `items.json` holds published game tables
only; mixing sim tuning into it is the filing error that made the luck data a
second source of truth.

## Deliberate divergences

- **Per-room count transforms are modelled for 5 rooms out of ~170.** The
  `/Luck` page states *"Most rooms don't use the item count given directly"*,
  and only Nook, Study, Guest Bedroom, Den and Lost & Found have a published
  transform. **A faithful ladder applied uniformly is still wrong for the
  other 165 — just wrong differently than before.** Accepted knowingly; play
  observation is the only path to the rest.
- **`additional_max` is not game data.** It is a per-category default in
  `tools/ingest_sheet.py`'s `ADDITIONAL_MAX_DEFAULT`, whose own comment admits
  the Item Spawns table is Cloudflare-blocked and the values are
  community-informed estimates. It is an honest stand-in for an unmodellable
  spawn-pool cap, not a published number.
- **The extra-item *kind* weights are inferred**, not datamined: coins 40,
  key 25, gem 25, die 10 (confidence: `inferred` in `data/items.json`). The
  ladder decides *how many*; nothing published decides *which*.
- **The Root Cellar has no luck effect.** Its real effect spreads dig spots to
  other rooms, which needs a house-wide dig-spot model this sim does not have.
  The wiki's datamined luck-modifier list does not include it either, so
  nothing is lost on the luck axis specifically.
- **Every expectation in the luck tests is a hard-coded wiki literal.** No test
  may derive an expectation by calling the function under test or by reading
  the same data file the engine reads — that anti-pattern produced two tests
  that passed for any value of the constant they claimed to pin.
