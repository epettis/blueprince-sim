# Special items — design

Scope of this document: the special-item system landing across three PRs.
Source data: `docs/research/special-items-wiki.md`. Modeling status: PR1 (this branch)
makes every item exist, spawn, and — where its target system exists — function.
PR2 adds commerce (shop purchases, Trading Post trades, Workshop fabrication),
carry-over unlock flags' actions (Royal Scepter activation, vase/dig microchips,
item-use actions like Repellent), PR3 wires observation/action space.

**PR3 observability requirements** (nothing item-related is observable today —
`env/obs.py` encodes no inventory):
- inventory vector (per-item held flags/counts, indexed by registry order);
- the Treasure Map X cell once a map has been read (`special.treasure_cell` — as a
  grid plane or cell index feature) plus `treasure_dug`;
- per-day counters an agent must plan around: `stopwatch_left`, `water`,
  `lockpick_attempts`/`lockpick_fails`, `shield_used`;
- (PR2 data, observed in PR3) shop stock/prices per placed shop and the scepter color;
- `fabricate_options()` (valid anywhere — lets a policy see that its items could
  become, say, a lockpick upgrade before walking to the Workshop) and, inside the
  Trading Post, the trade offers with their resolved `receive`.

## Principles

- **Data-driven**: every item is a record in `data/special_items.json`; behavior is
  keyed by effect tags interpreted in `engine/special_items.py`. Unknown tags no-op
  (like room effects), so partial data coverage degrades gracefully.
- **One module**: all special-item behavior lives in `engine/special_items.py` (per-item
  logic reviewable and testable in isolation). `game.py` only gains thin call sites.
- **Inert until modeled**: items whose target system is out of scope (Vault, Parlor,
  trunks, candles, basement, lore) ship as full records with `"implemented": false`
  and a `meta.blocked_on` note. They can spawn, be held, be stolen by the Lost &
  Found, and (PR2) traded — their *use* is just absent.
- **Determinism**: every roll uses named rng substreams (`special_spawn`,
  `special_kind`, `lockpick`, `dig`, `dig_kind`, `lost_and_found`, `treasure_map`).

## Data schema — `data/special_items.json`

```jsonc
{
  "items": [
    {
      "id": "lock_pick_kit",            // snake_case, unique
      "name": "Lock Pick Kit",
      "kind": "standard",               // standard|special_key|contraption|showroom|armory|unique
      "tier": 3,                         // 1-5 Trading Post tier; null = untradeable
      "unique": true,                    // at most one held (false: wind_up_key, sanctum_key, microchip, file_cabinet_key)
      "persistence": "day",             // day|until_used|permanent (informational in PR1; PR2 carry-over uses it)
      "spawn_rooms": ["archives", ...], // sim room ids where it can spawn on first entry
      "spawn_rooms_high_luck": [...],   // additional pool entries at luck >= spawn.high_luck_at
      "guaranteed_in": [...],           // room ids that ALWAYS contain it on first entry
      "effects": [{"tag": "lockpick", "rates": [54, 35, 30, 19], "denominator": 101, "pity": 3}],
      "implemented": true,
      "meta": {
        "source": "https://blueprince.wiki.gg/wiki/Lock_Pick_Kit",
        "confidence": "datamined",     // datamined|wiki|inferred|placeholder
        "absent_spawn_rooms": ["darkroom", "toolshed", "closed_exhibit"],  // wiki rooms not in the sim
        "blocked_on": null              // for implemented:false — what system is missing
      }
    }
  ],
  "spawn": {
    // Modeling assumption (confidence: inferred): when a luck-rolled additional item
    // procs in a room, it resolves to a special item from the room's pool with
    // probability special_share (else the usual EXTRA_ITEM_TABLE kind). At most one
    // special item spawns per room per day. Pool entries already held (unique items),
    // consumed-for-good, or removed by the Lost & Found are excluded.
    "special_share": 25,               // percent
    "high_luck_at": 16                 // luck threshold enabling spawn_rooms_high_luck
  },
  "dig": {
    // outcome kinds: junk|nothing|coins|gold_coin|turnip|key|item; "item" carries "id".
    "tables": {
      "shovel": [{"weight": 28.8, "kind": "junk"}, ...],
      "detector_shovel": [...],
      "jack_hammer": [...]
    },
    "coin_pile_split": [45, 38, 15, 2],   // 1..4 coins sub-roll for the shovel "coins" outcome
    "turnip_steps": 6
  },
  "treasure_map": {
    "cells": [22, 27, ...],            // the 8 possible X cells as flat indices
    "rewards": [{"coins": 40}, {"gems": 8}, {"coins": 25, "gems": 3}]
  },
  "lost_and_found": {"gives": 2, "pool": ["die", "gear_wrench", ...]},  // "die" = resource
  "fabrication": [{"inputs": ["lock_pick_kit", "metal_detector"], "output": "pick_sound_amplifier"}, ...],
  "trading": {"dice_chance": 10}       // tier data lives on the items; used by PR2
}
```

Validator (`tools/validate_data.py`): unique ids; kinds/persistence/confidence from the
valid sets; every `spawn_rooms`/`guaranteed_in`/`lost_and_found.pool` (bar `die`) /
`fabrication` id resolves (rooms against rooms.json, items against items);
`meta.absent_spawn_rooms` entries must NOT exist in rooms.json (else they belong in
`spawn_rooms`); dig table weights sum to ~100; `implemented: false` requires
`meta.blocked_on`; effect tags outside `KNOWN_ITEM_EFFECT_TAGS` warn.

## Engine surface

- `engine/special_items.py` — everything below.
- `GameState.inventory: dict[str, int]` (item id → count) and
  `GameState.special: SpecialItemsState` (per-day counters; defined in special_items.py).
- `model.Registry.special: SpecialItemsRegistry` (frozen records parsed at load).
- `GameConfig`: `special_items: bool = True` master toggle; `starting_items:
  frozenset[str] = frozenset()` (held at day start — RL curricula, tests, and the PR2
  carry-over wrapper all use this); `lunch_box_unlocked: bool = False` (Dining Room
  daily spawn); `cursed_effigy_unlocked: bool = False` (Shrine spawn, PR2 room).
  PR2 adds: `entrance_vase_broken`, `outer_chip_dug`, `royal_scepter_found`, and
  end-of-day carry-over reporting.

### SpecialItemsState (mutable, per-episode)

```python
enabled: bool            # GameConfig.special_items, copied at reset (gates spawning)
lockpick_attempts: int   # picks tried today (indexes the per-day rate table)
lockpick_fails: int      # consecutive fails, for the Lock Pick Kit pity rule
coin_interest: int       # coins collected since the last Coin Purse interest payout
water: int               # Watering Can charges left (set to capacity on pickup)
stopwatch_left: int      # free cost events remaining (0 = stopwatch inactive)
stopwatch_used: bool     # a Stopwatch already ran today (unobtainable again)
moves_since_free: int    # Running Shoes cadence counter
dug: dict[int, int]      # cell -> dig spots already dug
treasure_cell: int       # Treasure Map X cell; -1 = no map read today
treasure_dug: bool       # the map's one-per-day treasure dig happened
silver_key_draft: bool   # next draw biased toward cross/t layouts
shield_used: bool        # Knight's Shield daily red-room negation spent
removed: list[str]       # ids gone for the day (steals/consumed) — spawn pools skip them
spawned_today: list[str] # unique ids already spawned (at most once per day each)
gated_out: list[str]     # ids excluded by config unlock flags (populated by configure())
configured: bool         # True once configure() ran this episode
spawn_room_done: int     # room.idx that already spawned a special item; -1 = none
```

### Public API (duck-typed `game`, mirroring `effects/` handlers)

- `load_special_items(data_dir) -> SpecialItemsRegistry` (called by `Registry.load`).
- `has(state, item_id) -> bool`; `count(state, item_id) -> int`.
- `grant(game, item_id, source: str) -> None` — inventory add + `items_found_log`
  append (`(item_id, 1)`) + pickup effects (Cursed Effigy steps-to-13, Lunch Box
  rank-5 check, Stopwatch activation...).
- `remove(game, item_id, *, consumed: bool) -> None` — decrement; consumed-for-good
  items enter `state.special.removed`.
- `roll_special_spawn(game, room, cell) -> str | None` — called from
  `items.roll_room_items` when an additional-item proc resolves; returns the item id
  granted or None. Handles `guaranteed_in` separately (always granted, before rolls).
- `on_enter(game, room, cell) -> None` — called from `Game._enter` after
  `roll_room_items`: guaranteed spawns, Lost & Found steal+gifts, Sleeping Mask,
  Watering Can, auto-dig (below), Lunch Box rank check (also checked in `move`).
- `on_place(game, room, cell) -> None` — called from `Game._place_room`: Metal
  Detector / Powered Electromagnet extra key/coin spawns in the newly drafted room.
- `move_step_cost(game, from_cell, direction, to_room) -> int` — 1, or 0 via Hall Pass
  (hallway→hallway), Running Shoes (every 3rd room, `inferred` from the 2.2
  room-length trigger), or Stopwatch. Called from `Game.move`.
- `try_lockpick(game) -> bool` — Lock Pick Kit / Pick Sound Amplifier attempt with
  datamined rates + pity; called from `Game._unlock_for_passage` before spending a
  key. Master Key and active Stopwatch open locked doors at no key cost (key still
  required in hand for Stopwatch, per the wiki). All of these apply to REGULAR key
  locks only — security doors stay exclusively on the keycard/power/offline system
  (the Master Key never opens one; enforced by wiring these hooks into the
  DOOR_LOCKED branches only, and pinned by a test).
- `gem_cost_modifier(game, room, cost) -> int` — Emerald Bracelet waiver, Hall Pass
  free hallway-from-hallway drafts, Stopwatch waiver. Called from
  `Game._effective_cost` (after slot-0/free-category logic).
- `luck_bonus(state, registry) -> int` — Rabbit's Foot / Lucky Purse +3; added to
  `state.luck` inside `items.luck_probability` (effective luck, not stored).
- `on_coins_granted(game, amount) -> int` — Coin Purse (+1 per 3) / Lucky Purse (×2)
  interest; returns bonus coins. Called from `items.grant_item`.
- `food_steps(game, base) -> int` — Salt Shaker +1 then Silver Spoon ×2; `items.grant_item`
  gains a `food` kind whose base step value comes from items.json (`food: {steps: 3}`).
- `compass_active(game) -> bool` / `ornate_compass_active(game) -> bool` — config flag
  OR held item (Powered Electromagnet also activates the plain compass). Used by
  `rotation.py` / `Game._rotation_source`.
- `dig_all(game, cell) -> None` — auto-dig: whenever the player is in a room with
  undug `dig_spots` while holding a digging tool (Shovel > Detector Shovel > Jack
  Hammer picks the best table), all remaining spots are dug (digging is free in the
  real game, so an action would be strictly dominated; simplification documented).
  Treasure Map: entering the marked cell with a digging tool triggers the treasure
  roll (once/day).
- `satisfied_condition_items(state) -> set[str]` — draft-condition gates granted by
  held items: `key_8` → `room8_key`, `secret_garden_key` → `secret_garden_key`.
  Consulted wherever `cfg.satisfied_conditions` is read (placement); the Secret
  Garden Key is consumed when the Secret Garden is drafted; Key 8 is not.

### Item effect tags (PR1 functional set)

`lockpick` (rates/denominator/pity), `luck_bonus` (amount), `coin_interest`
(per/bonus), `coin_multiplier`, `food_bonus` (amount), `food_multiplier`,
`free_hallway_moves`, `free_move_interval` (Running Shoes, n=3, inferred),
`stopwatch` (free_costs: 10, inferred — turn-based stand-in for 60 real-time seconds),
`sleeping_mask` (steps: 5), `watering_can` (capacity: 3), `master_key`,
`silver_key_bias`, `compass`, `ornate_compass`, `emerald_bracelet`, `dig_tool`
(table id), `treasure_map`, `metal_detector_spawns` (coin/key chances, inferred),
`auto_collect` (Electromagnet: implies metal_detector-style spawn grant),
`mask_red_room` (Knight's Shield), `paper_crown`, `set_steps_on_pickup`
(Cursed Effigy, value 13, only_if_above), `steps_at_rank` (Lunch Box, rank 5, +10,
food-typed), `negate_red_once_per_day`.

Tags NOT implemented in PR1 (records carry them for PR2+ or stay inert):
`shop_discount` (Coupon Book — PR2), `smash` (Sledge Hammer / Morning Star / Power
Hammer — vase/trunks PR2+), `repellent`, `scepter`, `chronograph`, `crown_of_blueprints`,
`gear_wrench`, `dowsing_rod`, `locksmith_rob`, and everything on `implemented: false`
records.

`locksmith_rob` (Powered Electromagnet, PR2): approaching the Locksmith while holding
the Electromagnet robs it —
- auto-collects the 24 basic wall keys (four racks of 6 each; occasionally fewer in
  the real game — modeled as a flat 24, the `keys` param);
- the Locksmith's SPECIAL key (Silver/Secret Garden/Prism/Car Keys slot) is NOT
  collected: special keys are never auto-collected by the Electromagnet;
- both key purchase options (1 key / set of 3) are disabled for the rest of the day.
Source: https://blueprince.wiki.gg/wiki/Powered_Electromagnet.

### Keycard

Stays on the existing locks.json mechanism (`has_keycard`); the `keycard` item record
exists with a note that spawning/state are handled by `engine/locks.py`. It is
excluded from the generic SPAWN pipeline (to avoid double-spawning), but the Lost &
Found CAN steal it — the steal special-cases `state.has_keycard` (set to False;
re-findable later via the locks.py source-room rolls, standing in for the pool-return
of other stolen items).

### Lost & Found room

The room already exists in rooms.json (`lost_and_found`, studio_addition pool,
unusual) — contrary to the stale CLAUDE.md note about seven absent rooms. PR1 adds
its entry effect: tag `lost_and_found` on the room record (in rooms.json AND the
ingest_sheet.py effect-overrides map, so re-ingest keeps it), delegating to
`special_items.lost_and_found_on_enter`: steal one uniformly random held special item
(the Keycard included, via `has_keycard`; nothing if nothing is held), then grant two
draws from the data pool (excluding already-held uniques; `die` grants a die).

## Simplifications introduced (all documented in README known-simplifications + here)

1. Special-item spawn rate: luck-proc share model, `special_share` 25% (inferred).
2. Stopwatch: 60 real-time seconds → 10 free cost events (data knob).
3. Running Shoes: 2.2 room-length trigger → every 3rd move free (data knob).
4. Auto-dig / auto-treasure-dig instead of a dig action (digging is free → dominated).
5. Auto-pickup: spawned special items are always taken (no leave-behind choice).
6. Knight's Shield auto-applies to the first red room entered that day (no choice).
7. Prism Key: opens a locked door and recycles; its color-draft trigger is deferred
   (needs color-biased drafting, PR2+).
8. Metal Detector extra-spawn chances are not datamined: coins 60%, key 25% per
   drafted room (inferred, data knobs).
9. Stopwatch cost waivers spend a charge only when a cost is actually paid
   (`stopwatch_waives_gems` fires in `Game._pay`); affordability queries are pure.
10. Silver Key: the cross/t bias applies to the initial deal only (redraws of
    that hand use normal odds); consuming it for a locked frontier door takes
    priority over the lockpick/stopwatch chain.
11. Dig-spot counts: the wiki's Dig Spot list names rooms but not counts, so
    every listed room carries dig_spots=1 (inferred) except the datamined
    Tomb (2) and Tunnel (3).

## PR2 — commerce and carry-over

New module `engine/shops.py` (mirrors special_items.py: frozen rules from
`data/shops.json`, a mutable `ShopsState` on GameState, hook/action functions taking
duck-typed `game`). game.py gains thin action methods; env untouched until PR3.

### Data schema — `data/shops.json`

```jsonc
{
  "sale": {"days": [20, 21]},          // prices halved (round up) on these days
  "trading": {
    "trades_per_day": 20,              // wiki-undocumented; generous: the graph is learned by trading
    "dice_chance": 10,                 // % an offer resolves to a die
    "t5_special_chance": 50            // % a tier-5 trade offers allowance_token/upgrade_disk
  },
  "shops": {                           // keyed by room id
    "commissary": {
      "slots": 4,                      // distinct stock entries offered per day
      "stock": [
        // kind: resource (grants coins/keys/gems/food) | item (special item id)
        {"id": "gem", "kind": "resource", "grant": {"gems": 1}, "price": 3, "limit": 5},
        {"id": "magnifying_glass", "kind": "item", "price": 4}   // limit 1 implied for items
      ]
    },
    "locksmith": {
      "stock": ["...unlimited key entries..."],
      "special_key": {                 // one per day, 8g: priority lists rolled 30/40/30
        "price": 8,
        "rolls": [
          {"chance": 30, "order": ["silver_key", "secret_garden_key", "prism_key"]},
          {"chance": 40, "order": ["secret_garden_key", "prism_key", "silver_key"]},
          {"chance": 30, "order": ["prism_key", "secret_garden_key", "silver_key"]}
        ],
        "fallback": "car_keys"         // then a duplicate silver_key
      }
    },
    "showroom": {"tier_a": ["...20-30g ids..."], "tier_b": ["...50-80g ids..."],
                  "trophy": {"id": "trophy_of_wealth", "price": 100}},
    "gift_shop": {},                    // lunch_box 15g one-time; cursed_coffers (inferred price)
    "the_armory": {}, "bookshop": {}, "laundry_room": {}
    "kitchen": {
      "stock": [banana 2g/limit5, club_sandwich 8g/limit1],  // always offered
      "special_roll": [  // one chosen per day; weights sum to 100
        {"id": "bacon_and_eggs", "chance": 40, ...},          // +10 steps + Morning Room
        {"id": "chef_salad", "chance": 30, ...},              // +5 steps per green room at eat time
        {"id": "tomato_soup", "chance": 30, ...}              // +5 steps per red room at eat time
      ]
    }
  }
}
```

### Model decisions (confidence noted)

- **Stock rolls** happen on FIRST entry to each placed shop (seeded substream
  `shop_stock`); the Commissary offers `slots` distinct available entries uniformly
  (the real game's 7 fixed combinations A–G are unpublished — inferred). Owned or
  consumed special items never stock; the Showroom picks 2 from tier_a + 2 from
  tier_b avoiding owned, and shows the Trophy once all four displayed items are
  bought.
- **buy(index)**: player must stand in the shop room (or be inside the Trading Post,
  `outer_loc == 2`). Coins spent; Coupon Book applies −1 per purchase (reduction,
  not refund — an item priced 1 above your gold is buyable); sale days halve prices
  rounded up.
- **Electromagnet Locksmith robbery** (`locksmith_rob`): on first entry to the
  Locksmith while holding it: +24 keys, key/set-of-keys stock disabled for the day,
  the special key NOT taken (wiki-verified).
- **Gift Shop**: buying `lunch_box` (one-time; only offered when not
  `lunch_box_unlocked`) or `cursed_coffers` (needs a Sledge Hammer; grants the
  `cursed_effigy` immediately, its steps-to-13 pickup effect applies) records the
  discovery for carry-over.
- **Trading Post trades**: `trade(give_id)`: give one held tradeable item of tier T.
  On entering the Trading Post, the game generates a fixed trade graph for the day
  (confidence: `inferred` — the wiki does not document the generator; mechanic described
  by the user from observation). For each tier 1–5 the tradeable items are shuffled into
  one cycle: `ids[i] → ids[(i+1) % n]`; then per-item `dice_chance%` replaces the
  successor with "dice" and (tier 5 only, checked first) `t5_special_chance%` replaces
  it with "allowance_token" or "upgrade_disk" (50/50). A 1-item tier cycle is a
  self-edge — that item cannot be traded. The graph is FIXED for the day (rolled once on
  first `trade_offers` call, substream "trade_graph").
  `trade_offers()` resolves each held item by walking the graph: starting from
  `trade_graph[X]`, the walk skips nodes that are held or unavailable
  (`_is_available` false), following each skipped node's own successor; sentinels
  ("dice"/"allowance_token"/"upgrade_disk") always terminate; a full loop back to the
  start yields no offer (untradeable). The player sees the resolved receive before
  committing (matching the real-game UI). `trade(give_id)` re-resolves at execution
  time (the just-removed give_id is no longer held). Traded items return to the spawn
  pool (`removed` NOT set); max `trades_per_day`. The `trades_per_day` knob (20) is
  THE hard bound on any milking loop (e.g. an A→B→A 2-cycle): trade returns
  deliberately bypass the spawn pipeline's `spawned_today` uniqueness so the loop
  works as in the real game. The cap is generous because the graph is only
  discoverable by experimenting — players burn trades learning the chains.
- **Workshop**: `fabricate(output_id)` consumes the recipe inputs
  (special_items.json fabrication list) and grants the contraption, any time the
  player stands in the Workshop. First Workshop entry spawns one free component
  (uniform over available components; fallback 5 coins) — wiki-documented.
- **Royal Scepter**: with `royal_scepter_found`, granted at day start (the Entrance
  Hall daily spawn; the hall is pre-entered, so reset-time grant).
  `activate_scepter(color)` — color ∈ {blueprint, green, red, bedroom, hallway,
  shop} — once per day, irrevocable for the day; sets a `scepter_<color>` condition
  consumed by the existing data-driven `category_biases` machinery
  (priority_draws.json entries; chance 40, magnitude unpublished — inferred).
- **Microchips**: `smash_vase()` (standing in the Entrance Hall with a Sledge
  Hammer, once) grants a `microchip` and records the vase discovery; with
  `entrance_vase_broken` the chip is instead granted at day start. West Path chip:
  with `outer_chip_dug`, granted on reaching the doorstep (`outer_loc` 1 — same
  walking cost as the Outer Room door, per the game); the first-time dig happens
  automatically at the doorstep while holding a digging tool, recording the
  discovery. Chip holders/placement are not modeled (outer areas out of scope) —
  chips stay inert, tier-2 tradeable.
- **Carry-over report**: `Game.carryover() -> dict[str, bool]` — today's discoveries
  for a multi-day wrapper to feed into tomorrow's GameConfig: keys
  `lunch_box_unlocked`, `cursed_effigy_unlocked`, `entrance_vase_broken`,
  `outer_chip_dug`, `royal_scepter_found` (True when newly discovered today OR
  already configured). Persistent-item inventory carry-over (Key 8, Sanctum Keys,
  Coat Check, Moon Pendant) stays deferred.
- **Repellent stays deferred**: its only effect is next-day pool removal —
  meaningless inside a single-day episode; inert until the multi-day wrapper.
- **Kitchen menu** (wiki-sourced): `_roll_kitchen` runs on first entry using substream
  `shop_stock`. Static stock: 5 bananas at 2g each and 1 Club Sandwich at 8g. Exactly
  one daily special is drawn by a 40/30/30 cumulative roll: Bacon & Eggs (8g, +10 steps,
  injects the Morning Room into today's draft decks immediately on purchase), Chef Salad
  (5g, +5 steps per green room on the grid *at eat time*), Tomato Soup (5g, +5 steps per
  red room on the grid at eat time). Sources: https://blueprince.wiki.gg/wiki/Kitchen.
- **Dining Room main course** (wiki-sourced; rank-8 gated per the real game): the
  day's Main Course is served automatically and free while standing in the Dining
  Room (or any variant), but only once the player has REACHED Rank 8 (some entered
  cell at rank >= 8). An early visit serves nothing — returning after reaching Rank
  8 serves it (checked on every arrival); a Dining Room drafted at rank 8/9 serves
  immediately on first entry. The dish is a
  deterministic five-day cycle indexed by `day % 5`: 0 → Wood-fired Pizza (Furnace
  boost), 1 → Lemon Glazed Salmon (Aquarium), 2 → Porterhouse Steak (Showroom), 3 →
  Country Stew Pie (Boiler Room), 4 → Stuffed Wild Quail (Trophy Room). Each is 20
  base steps, or 30 when its boost room is anywhere on the estate (checked via
  `state.grid`; duplicates of the same room cannot appear, so no stacking). Salt
  Shaker / Silver Spoon modify the final step count normally. The course is served
  exactly once per day (`state.special.dining_room_served` flag). Source:
  https://blueprince.wiki.gg/wiki/Dining_Room.
- **PR1 gap fixed in PR2**: `enter_outer_room` now calls `special_items.on_enter`,
  so outer rooms spawn items (Toolshed's guaranteed Gear Wrench, Trading Post pool).

### ShopsState (mutable, per-episode)

```python
stock: dict[str, list]         # shop room id -> rolled stock entries (mutable sold/limit state)
special_key_offer: str | None  # today's Locksmith special-key id (rolled with stock)
locksmith_robbed: bool         # Electromagnet robbery fired (key purchases disabled)
trades_done: int               # Trading Post trades used today
scepter_color: str | None      # activated color (category); None = not yet activated
vase_smashed: bool             # Entrance Hall vase smashed today (discovery)
chip_dug: bool                 # West Path chip dug today (discovery)
gift_unlocks: list[str]        # one-time Gift Shop purchases made today (carry-over feed)
```

## Test plan (per CLAUDE.md conventions: observable behavior, docstrings)

- `tests/test_special_items.py` — core: spawn determinism per seed; unique items never
  duplicate; Lost & Found steals exactly one and gives two; pickup effects (Effigy
  13-step clamp, Lunch Box at rank 5); food pipeline ordering (Salt Shaker before
  Silver Spoon: banana 3→4→8); coin purse interest ratios.
- `tests/test_special_items_movement.py` — Hall Pass hallway chains cost 0; Running
  Shoes cadence; Stopwatch waives then expires; Master Key opens locked doors without
  spending keys; lockpick rates within tolerance + pity guarantee; Emerald Bracelet
  drafts gem rooms at 0 gems while gems remain untouched.
- `tests/test_digging.py` — dig tables chi-square-lite (seeded, wide tolerance);
  auto-dig once per spot per day; treasure map digs exactly once and pays one of the
  three rewards; Detector Shovel uses its own table.
- `tests/test_placement.py` additions — key_8 / secret_garden_key inventory gating.
- Determinism: same seed + config ⇒ identical `items_found_log` (extends the existing
  invariant test).
