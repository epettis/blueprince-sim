# Special items — design

Scope of this document: the special-item system, delivered across PRs #17–#20.
Source data: `docs/research/special-items-wiki.md`. Status: implemented — items
exist and spawn, commerce works (shop purchases, Trading Post trades, Workshop
fabrication), item-use actions work (Royal Scepter, Repellent), and the
observation/action space is wired. All 102 item records that are reachable in
play are `implemented: true`; the remainder carry a `meta.blocked_on` naming
what is missing and a `meta.reachability` of `inert` or `absent`.

**Observability requirements** (delivered; `env/obs.py` now encodes all of these):
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
- **Inert until modeled**: items whose target system is out of scope (Grounds,
  Sanctum, Orindian Ruins, lore) ship as full records with `"implemented": false`
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
      "no_receive": false,               // true: tradeable away, never offered back
      "unique": true,                    // at most one held (false: sanctum_key, microchip, file_cabinet_key)
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
lit_targets: list[str]   # ignition target room ids lit today (each lights at most once)
machines_used: list[str] # machine room ids that already took a Broken Lever today
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
  `state.luck` inside `items.roll_ladder_count` (effective luck, not stored).
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
(per/bonus), `food_bonus` (amount),
`free_move_interval` (Running Shoes, n=3, inferred),
`stopwatch` (free_costs: 10, inferred — turn-based stand-in for 60 real-time seconds),
`sleeping_mask` (steps: 5), `watering_can` (capacity: 3),
`dig_tool`
(table id), `treasure_map`, `metal_detector_spawns` (coin/key chances, inferred),
`auto_collect` (Electromagnet: implies metal_detector-style spawn grant),
`mask_red_room` (Knight's Shield), `paper_crown`, `set_steps_on_pickup`
(Cursed Effigy, value 13, only_if_above), `steps_at_rank` (Lunch Box, rank 5, +10,
food-typed), `negate_red_once_per_day`.

Tags NOT implemented in PR1 (records carry them for PR2+ or stay inert):
`smash` (Sledge Hammer / Morning Star / Power
Hammer — vase/trunks PR2+), `repellent`, `scepter`, `crown_of_blueprints`,
`gear_wrench`, `dowsing_rod`, `locksmith_rob`, and everything on `implemented: false`
records.

The Coupon Book no longer carries a `shop_discount` effect tag: its
discount is registered directly as `ItemCapability.SHOP_DISCOUNT` in
`engine/effects/items/coupon_book.py` (task 22's per-item capability
registry), which `shops.py` folds via `item_capability_sum`.

Eight more pure-boolean effects moved the same way, each into its own
`engine/effects/items/<item_id>.py` module folded via `item_capability_any`
(the boolean sibling of `item_capability_sum`) instead of a data tag:
`ItemCapability.ELECTROMAGNET` (Powered Electromagnet — its `auto_collect`
and `locksmith_rob` tags stay in data; its drafting bias moved),
`ItemCapability.CHRONOGRAPH` (Chronograph),
`ItemCapability.ORNATE_COMPASS` (Ornate Compass),
`ItemCapability.MASTER_KEY` (Master Key),
`ItemCapability.EMERALD_BRACELET` (Emerald Bracelet),
`ItemCapability.FOOD_MULTIPLIER` (Silver Spoon),
`ItemCapability.FREE_HALLWAY_MOVES` (Hall Pass), and
`ItemCapability.COIN_MULTIPLIER` (Lucky Purse — its `luck_bonus` tag stays
in data, shared with the Rabbit's Foot). None of these eight tags exist in
`special_items.json` any more.

A ninth capability, `ItemCapability.COMPASS_BIAS` (task 22 phase 5a), moved
the `compass` tag itself off both its carriers (Compass and Powered
Electromagnet); the tag no longer exists in `special_items.json`.

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
unusual). PR1 adds
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
12. Coat Check: the real game lets the player choose which item to store and
    retrieve it on any later day.  The sim auto-stores the highest-tier item
    (ties broken alphabetically by id) and auto-returns it exactly the NEXT day.
13. Moon Pendant: 2 uniformly random items are drawn from the full held set
    (pendant eligible; uses the named substream "moon_pendant_carry").  The wiki
    says "2 random inventory items"; we take this literally at end-of-day (not
    mid-day) regardless of what happened to the inventory during the day.
14. Repellent: today's already-built decks are not affected by a same-day use
    (the ban takes effect from the next day).  The ban counter starts at 7 and
    the advance() that FOLLOWS the day the repellent is used does NOT decrement
    it; each subsequent advance decrements once, so the ban is active for exactly
    7 `next_config()` calls (7 days) before dropping.

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
    "t5_special_chance": 50            // % a tier-5 trade offers allowance_token (disks are one-time per source)
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
- **buy(index)**: player must stand in the shop room (or be inside the Trading Post
  — `shops._inside_trading_post`). Coins spent; Coupon Book applies −1 per purchase (reduction,
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
  one order; the RECEIVABLE ids (`no_receive` false) in that order form a cycle, each
  pointing to the next receivable id and skipping over any give-only ids in between.
  Give-only ids (e.g. `microchip`, `treasure_map`, `watering_can` — wiki
  `{{Interactions/Trade|no-receive=y}}`) attach as extra sources into that same cycle,
  so they can be given but — since nothing's successor ever lands on them — never
  received. Then per-item `dice_chance%` replaces the successor with "dice" (this
  still applies to give-only sources — it never grants the give-only item itself) and
  (tier 5 only, checked first) `t5_special_chance%` replaces it with "allowance_token".
  (Upgrade Disks are one-time per source and are never generated by the repeatable
  trade path.) A tier with exactly one receivable id is a self-edge on that id — it
  cannot be traded. The graph is FIXED for the day (rolled once on first
  `trade_offers` call, substream "trade_graph").
  `trade_offers()` resolves each held item by walking the graph: starting from
  `trade_graph[X]`, the walk skips nodes that are held or unavailable
  (`_is_available` false), following each skipped node's own successor; sentinels
  ("dice"/"allowance_token") always terminate; a full loop back to the
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
- **Microchips**: three exist, and all three respawn at their starting location
  the next day. `smash_vase()` (standing in the Entrance Hall with any item
  carrying the `smash` tag -- the wiki says "a Sledge Hammer or equivalent",
  once) grants a `microchip` and records the vase discovery; with
  `entrance_vase_broken` the chip is instead granted at day start. West Path chip:
  with `outer_chip_dug`, granted on reaching the doorstep (`state.area == "west_path"` — same
  walking cost as the Outer Room door, per the game); the first-time dig happens
  automatically at the doorstep while holding a digging tool, recording the
  discovery. Grotto chip: it starts in the Blackbridge Grotto pedestal and is
  taken with `TAKE_GROTTO_CHIP`, legal there while `GameState.grotto_chip_taken`
  is False -- a day-scoped flag with no carry-over, which is what makes the chip
  reappear in the pedestal tomorrow.

  Both holders are modelled. `areas.json`'s `three_microchips` gate counts held
  chips **plus** the pedestal chip while it is in place (`counts_flag`), so two
  carried chips open the Orindian Ruins; taking the pedestal chip gives three
  held, which keeps that gate open and also lights the Apple Orchard sundial
  (`ignition.targets.apple_orchard`, `requires_items: {"microchip": 3}`).
  Chips are tier-2 give-only (`no_receive`) in the Trading Post graph, so they
  can be traded away or lost to the Lost & Found but never received.
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

## Multi-day loop (`env/multiday.py`, alongside PR2/PR3)

`DayChain(base_cfg, n_days=200)` coordinates a multi-day Blue Prince attempt.
Each call to `next_config()` returns a `GameConfig` with the correct `day` index
and any accumulated carry-over flags merged in.  `advance(carryover_dict)` merges
True flags from `Game.carryover()` and increments the day; after `n_days` days
the chain wraps to day 1 and clears all flags (fresh attempt).

`BluePrinceEnv` accepts an optional `day_chain: DayChain` kwarg.  When set:

- `reset()` calls `day_chain.next_config()` to build the day's `Game`, reusing
  the already-loaded registry to avoid re-parsing data files.
- Terminal/truncated `step()` calls `day_chain.advance(game.carryover())`.
- `info` dicts include `"day"` (1-based current day) and `"carryover"` (the
  flags active at episode START, stable even after `advance()` mutates the chain).

`blueprince-train --multi-day N` enables this: each worker constructs its own
`DayChain(cfg, N)` and the dashboard's event tail logs a compact one-liner per
episode: `[chain] env0 day 37/200 | carry: scepter,vase`.

`royal_scepter_found` defaults to `True` (changed alongside this PR): the Key of
Aries -> Treasure Trove unlock puzzle is unmodeled, so defaulting on is the only
way to exercise the scepter.  Pass `royal_scepter_found=False` to disable.

## PR3 — env wiring (the single retrain point)

Everything appends to the existing interface: no existing obs key changes shape and
no existing action id moves, so the diff is reviewable and old replays stay
decodable up to id 240. Trained checkpoints DO break (new obs keys + Discrete
grows) — that is this PR's purpose.

### Observation additions (`env/obs.py`, new Dict keys)

```python
"inventory":    Box(0, 99,  (n_items,),  int16)  # count per special item, registry order
"item_state":   Box(-1, 999, (10,),      int16)  # per-day counters, order below
"grid_dig":     Box(0, 9,   (9, 5),     uint8)  # dig spots REMAINING per cell
"shop_stock":   Box(-1, 999, (6, 5),     int16)  # current shop's display entries
"trade_offers": Box(-1, 999, (8, 2),     int16)  # inside the Trading Post
"fabricate":    Box(0, 1,   (n_recipes,), uint8) # buildable-now mask, recipe order
```

- `item_state` order: stopwatch_left, water, lockpick_attempts, lockpick_fails,
  shield_used, trades_left (trades_per_day − trades_done), scepter_color index+1
  (0 = not activated), treasure_cell+1 (0 = no map read), treasure_dug,
  dining_room_served.
- `shop_stock` row (rows −1 when absent / not in a shop): item registry idx+1
  (0 for resource entries), resource code (0 none, 1 coins, 2 keys, 3 gems,
  4 dice, 5 food — dish identity is not exposed, noted simplification), resolved
  price, sold_out, affordable. Display index i == buy action i.
- `trade_offers` row: give item idx+1, receive item idx+1 (0 = dice). Offer
  index i == trade action i.
- `fabricate` indexes `registry.special.fabrication` order (stable data order).

### Action additions (`env/actions.py`, appended; N_ACTIONS 241 → 270)

```python
BUY_BASE        = 241  # 241..246: buy current shop display entry 0..5
TRADE_BASE      = 247  # 247..254: trade offer 0..7 (inside the Trading Post)
FABRICATE_BASE  = 255  # 255..262: fabricate recipe 0..7 (in the Workshop)
SCEPTER_BASE    = 263  # 263..268: activate the Royal Scepter color 0..5
SMASH_VASE_ACTION = 269
```

- Masks: buy i ⇔ in a shop, i < len(stock), not sold_out, affordable; trade i ⇔
  offer i exists; fabricate i ⇔ standing in the Workshop and the recipe's output
  is in fabricate_options(); scepter i ⇔ can_activate_scepter(); vase ⇔
  can_smash_vase(). SCEPTER color order = shops.SCEPTER_COLORS.
- **Move-to re-entry extension**: the walk-to mask (196..240) previously allowed
  only unentered rooms and the control rooms. It now also allows re-entering:
  a shop cell whose stock still has a buyable entry, the Workshop while
  fabricate_options() is non-empty, and a Dining Room whose main course is still
  pending with the rank-8 gate open — otherwise the new actions are unreachable
  after first entry.
- Reward note: no reward change in PR3. The shaped/phased rewards value coins but
  not held items, so purchases look locally negative to them — a known watch-for
  for the first retrain, tune in a follow-up if it suppresses shopping.

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

## Multi-day item persistence (carried items and Repellent bans)

Implemented alongside `env/multiday.py::DayChain`.  Source:
`docs/research/special-items-wiki.md` "Taxonomy and global rules".

### Carry channels

The three channels are computed by `special_items.end_of_day_carry(state, registry, rng) -> list[str]`
and reported as `carryover()["starting_items"]`:

- **Self-persisting items**: any held item whose `SpecialItem.persistence` is
  `"permanent"` (key_8, allowance_token, microchip,
  upgrade_disk_vault_304/commissary/garage/trading_post/lost_and_found/tomb,
  basement_key) or `"until_used"` (sanctum_key, all four vault keys,
  file_cabinet_key, stopwatch, repellent).
- **Coat Check** (`room id: coat_check`): entering the Coat Check room calls
  `coat_check_on_enter(game)`, which sets `SpecialItemsState.coat_check_item`
  to the highest-tier held item (ties broken alphabetically).  The stored id is
  returned by `end_of_day_carry()` and appears in the next day's
  `starting_items`.  The item is NOT removed from today's inventory (the player
  keeps it for the rest of the day).
- **Moon Pendant** (`item id: moon_pendant`): if held at end of day, 2 uniformly
  random distinct held items (pendant itself eligible) are selected via the
  named rng substream `"moon_pendant_carry"` and included in the carry list.
  When ≤ 2 items are held, all carry automatically.

### DayChain integration

`DayChain.carried_items: frozenset[str]` holds the persistent item ids.
`next_config()` merges `base_cfg.starting_items | carried_items` so `Game.reset`
grants them at construction.  `advance()` replaces `carried_items` from
`carryover()["starting_items"]` each day.

### Repellent bans

`Game.use_repellent(room_id)` (delegates to `shops.use_repellent`):
- Asserts a Repellent is held; consumes it (`consumed=True`).
- Refuses `entrance_hall`, `antechamber`, `room_46` (wiki exclusions).
- Records the ban in `ShopsState.repellent_bans[room_id] = 7`.

`carryover()["banned_rooms"]` carries the `dict[str, int]` of new bans into
`DayChain.advance()`, which:

- Decrements all pre-existing ban counters first (one day has elapsed).
- Drops any counter that reaches ≤ 0 (expired).
- Merges the new bans at their original count (7) without decrementing them on
  the first advance, so the ban is active for exactly 7 subsequent
  `next_config()` calls (simplification #14 above).
- Enforces the 3-ban cap by evicting the oldest ban (insertion order) when more
  than 3 are active.

`DayChain.next_config()` passes `frozenset(active_ban_room_ids)` as
`GameConfig.banned_rooms`.  `engine/decks.py::eligible_pool` skips any room
whose id is in `cfg.banned_rooms` before building the eight solitaire decks.

## Containers (trunks, chests, lockers, garage car)

Source: `docs/research/special-items-wiki.md` (Sledge Hammer, Car Keys, and
per-item spawn-source entries mentioning trunks/lockers).

### Data schema — `data/special_items.json` `"containers"` section

```python
containers: {
  kinds: {
    trunk:  {locked: True, opener: ["smash", "key"], loot: [...]},
    chest:  {locked: True, opener: ["key"],           loot: [...]},
    locker: {locked: False, opener: [],               loot: [...]},
  },
  rooms: {room_id: {kind: count}},  # e.g. {"attic": {"trunk": 1}}
  garage_car: {
    first_loot: [{"kind": "item", "id": "upgrade_disk"}],
    later_pool: ["battery_pack", "keycard", ...],
    later_gold: 5,
    later_draws: 2,
  },
  meta: {source, confidence, notes},
}
```

### Engine surface

- `containers_in(registry, room_id) -> dict[str, int]` — container kinds and
  counts for a room (empty dict if none).
- `can_open_container(game, cell) -> bool` — True when at least one unopened
  container at `cell` is openable given current resources.
- `open_container(game, cell) -> str | None` — open ONE container, paying cost
  if required; roll loot from the kind's table on substream `"container"`;
  return a log string (e.g. `"coins:5"` or item id).
- `can_open_car_trunk(game) -> bool` / `open_car_trunk(game) -> list[str]` —
  Car Keys + standing in the Garage; first use grants the Upgrade Disk; later
  uses draw `later_draws` items from `later_pool` + `later_gold` coins.

Game delegates: `Game.can_open_container()`, `open_container()`,
`can_open_car_trunk()`, `open_car_trunk()`. The `can_*` predicates take the
cell explicitly at the engine layer so the env can query any cell for the
walk-to mask without moving the player.

Env wiring (this PR):
- Action ids 270 (`OPEN_CONTAINER_ACTION`) and 271 (`OPEN_CAR_TRUNK_ACTION`).
- Obs key `"grid_containers"` (9×5 uint8): unopened container count per cell.
- Walk-to re-entry extended via `_cell_has_openable_container`.

### Model decisions

- **Open order**: deterministic trunk → chest → locker (within a room, all
  trunks are opened before chests, chests before lockers).
- **No auto-open**: unlike dig spots (always free, auto-executed), opening can
  cost a key — so skipping is non-dominated. The agent picks `OPEN_CONTAINER_ACTION`
  explicitly.
- **Smash opener**: any item with the `smash` effect tag (Sledge Hammer, Morning
  Star, Power Hammer) opens trunks for free. Chests are never smashable.
- **Garage car `first_loot`**: the trunk re-locks every night, so Car Keys are
  required on every open. What decides the loot is whether the disk has been
  spent: while `upgrade_disk_garage` is absent from `GameConfig.collected_disks`
  the trunk yields the Upgrade Disk again, and once the disk is inserted at a
  terminal the trunk switches to the `later_pool` draw.
- **Keycard in later_pool**: the Car Keys wiki page lists Keycard as a possible
  trunk loot; it is handled by setting `state.has_keycard = True` (same as
  `locks.py`) rather than the generic `grant` pipeline.

### Simplification #15

Container loot tables are inferred from items whose wiki pages list trunks or
lockers as spawn sources (Battery Pack, Treasure Map, Lock Pick Kit, Magnifying
Glass, Silver Key, Vault Key 149, Running Shoes). Actual per-container loot
tables are not datamined. Trunk rooms sourced from wiki item-spawn lists
(attic, wine_cellar, storeroom, boiler_room); the remaining six (archives,
laboratory, servants_quarters, spare_room, rumpus_room, furnace) are `inferred`
from vague wiki mentions. Locker room counts (Locker Room ×3, Gymnasium ×2) are
`inferred` from the number of distinct item types mentioned as locker sources.
No room carries a **chest**: the kind is fully modeled and validated, but the
wiki documents no per-room chest assignments, so the `rooms` map has none. The
whole section is `meta.confidence: inferred` for this reason.

## Ignition targets and machines (Torch / Burning Glass / Broken Lever)

Source: `docs/research/special-items-wiki.md` (Torch and Burning Glass rows —
"lights candles/fuses, interchangeable"; Broken Lever — "no inherent function;
placeable on broken machines"; Diary Key — Tomb candle access).

These are the last two inert item systems from the catalogue. After this pass
every item either functions or is blocked only on an explicitly out-of-scope
area (Grounds, Sanctum, Orindian Ruins, lore documents).

### Data schema — `data/special_items.json` `"ignition"` section

```python
ignition: {
  tools: ["torch", "burning_glass"],   # either one lights any target
  targets: {                            # room id -> what lighting it yields
    chapel:       {candles: 2, grants: [{kind: "chapel_tithe_payout"}]},
    tomb:         {candles: 2, grants: [upgrade_disk_tomb, {dice: 4}]},
    trading_post: {fuse: True,  grants: [upgrade_disk_trading_post, {coins: 40}]},
  },
  meta: {source, confidence, absent_targets, notes},
}
# chapel_tithe_payout: special kind resolved in engine/special_items.light() as
# the accumulated chapel_tithes counter (coins the Chapel entry -1 penalty has
# ever banked).
```

### Data schema — `"machines"` section

```python
machines: {
  greenhouse: {item: "broken_lever", effect: "antechamber_lever", notes: ...},
  casino:     {item: "broken_lever", effect: "slot_bonus", grants: [...]},
  meta: {source, confidence, notes},
}
```

### Engine surface

- `can_light(game) -> bool` — standing in a target room, holding a tool, target
  unlit today, and `requires_item` satisfied when the target declares one.
- `light(game) -> None` — grants the target's rewards and appends the room id to
  `SpecialItemsState.lit_targets`. The tool is **not** consumed (a Torch relights
  all day); each target lights at most once per day.
- `can_install_lever(game) -> bool` — standing in a machine room holding a
  `broken_lever`, machine unused today.
- `install_lever(game) -> None` — consumes the lever via `remove(..., consumed=True)`,
  records the room in `SpecialItemsState.machines_used`, and dispatches the effect
  with `match`/`case`.

Game delegates: `Game.can_light()`, `light()`, `can_install_lever()`,
`install_lever()`. Env: `LIGHT_ACTION = 273`, `INSTALL_LEVER_ACTION = 274`
(`N_ACTIONS` 273 → 275); walk-to re-entry extended via
`_cell_has_ignition_target` and `_cell_has_machine`, so an agent can return to a
chapel or casino after picking up the enabling item.

### The Greenhouse lever and the Antechamber's south door

`antechamber_lever` unlocks the Antechamber's south doorway **segment** for free
via `Game._open_segment`, which also bumps `door_version` to invalidate the nav
caches. The direction here is a live trap worth stating explicitly:

- **N increases rank in this grid.** `neighbor(37, N) == 42` (the Antechamber).
- The Antechamber's own south door and cell 37's north door are the *same*
  segment: `segment_key(42, S) == segment_key(37, N) == (37, 1)`.

So the wiki's "south Antechamber lever" is modeled as `_open_segment(37, N)`.
Using `S` there would silently unlock `(32, 1)` — an unrelated door two ranks
away — and leave the Antechamber untouched. A test that seeds *and* asserts the
same `segment_key(37, <dir>)` cannot catch that inversion, which is why
`test_greenhouse_lever_opens_antechamber_south_segment` pins the identity
against `segment_key(ANTECHAMBER_CELL, S)`, and a second test asserts the
payoff behaviorally: passable with **zero** keys held, and no key consumed.

Because a rank-8↔9 segment sits at 130% base lock chance, the Antechamber
normally starts locked — so this is a genuinely useful late-run play rather
than a no-op.

### Simplification #16

Only `chapel`, `tomb`, and `trading_post` are modeled as ignition targets. The
Trading Post fuse reward is **wiki-documented** (dynamite barrels → a permanent
secret room holding an Upgrade Disk + 40 gold), collapsed here to an immediate
grant since the secret room itself is not modeled. Tomb rewards are
**wiki-documented**: near candles yield an Upgrade Disk + 4 dice; far candles
reveal Clara Epsen's resting place, containing the Diary Key. Both candle pairs
are collapsed into one ignition event granting the Upgrade Disk and dice; the
Diary Key itself is not modeled as a grant (see the removal note below). Chapel
reward: the Keeper of Tithes is an angelic piggy bank that banks each coin the
Chapel's -1 entry penalty takes;
lighting the altar pays out the accumulated total (see `chapel_tithes` in
SpecialItemsState and GameConfig). All ignition effects persist permanently
across days (stored in `GameConfig.lit_targets`; a lit target cannot be lit again).

The digest also lists Abandoned Mine (8 candles) and Crate Tunnel as targets;
both are absent from `rooms.json` and are recorded in `meta.absent_targets`,
mirroring how items record `absent_spawn_rooms`. The validator asserts anything
listed there genuinely *is* absent, so the list cannot rot silently if those
rooms are added later. The Freezer thaw is skipped deliberately: the wiki
describes it as temporary/daily, which the one-shot `lit_targets` model does not
express.

The Casino `slot_bonus` payout (20 coins + 2 gems) is `inferred` — the wiki says
5 bonus spins instead of 3 but gives no expected value. `diary_key` was removed
from the item table entirely (2026-08-06, project owner ruling): the wiki is
explicit that the key only unlocks Her Ladyship's Sleep Diary's flavour text and
has "no other known use," so — unlike the Wind-up Key precedent in
Simplification #17, which at least opens a box with real gems — there is no
mechanical payoff for an agent to reason about. The Tomb's ignition grants
(`upgrade_disk_tomb` + 4 dice) are unaffected and still fire unconditionally on
lighting.
## Parlor room

The Parlor room contains a box that always grants a fixed number of gems on
first entry — no loot roll, no key required:

- **Base Parlor**: 2 gems, encoded as `items.guaranteed` in `data/rooms.json`
  and delivered by the standard guaranteed-item pipeline in `special_items.on_enter`.
- **Parlor upgrade variant `parlor__ix108`** ("3ð Prize"): 3 gems. Identified by
  its datamined `effect_text` field ("3ð Prize") and internal_index 108. The
  other upgrade variants (`parlor__ix109` "2 Wind-up Keys", `funeral_parlor__ix110`)
  inherit the base 2-gem grant or no grant, respectively.

### Simplification #17 — Wind-up Key deliberately not modeled

In the real game the Parlor desk spawns Wind-up Keys which the player uses to
open the Parlor boxes (one key per box). The Wind-up Key has exactly one
purpose — solving the Parlor room puzzle — and is consumed once used. Rather
than widen the action space with a dedicated OPEN_PARLOR_BOX action (and the
required walk-to re-entry logic, box-cap tracking, and per-run key spawn
suppression), the gems are granted directly on first entry via the standard
`items.guaranteed` mechanism. A future reader should **not** "fix" this back to
the key-based model without weighing the action-space cost: the Wind-up Key
adds no strategy surface the agent needs to learn.