# Special items — design

Scope of this document: the special-item system landing across three PRs.
Source data: `docs/research/special-items-wiki.md`. Modeling status: PR1 (this branch)
makes every item exist, spawn, and — where its target system exists — function.
PR2 adds commerce (shop purchases, Trading Post trades, Workshop fabrication),
carry-over unlock flags' actions (Royal Scepter activation, vase/dig microchips,
item-use actions like Repellent), PR3 wires observation/action space.

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

`lockpick_attempts: int`, `lockpick_fails: int` (pity counter), `coin_interest: int`
(coins collected since last interest payout), `water: int` (Watering Can charges),
`stopwatch_left: int` (free cost events remaining; 0 = inactive), `stopwatch_used: bool`,
`moves_since_free: int` (Running Shoes trigger), `dug: dict[int, int]` (cell → spots
dug), `treasure_cell: int` (-1 = no map seen), `treasure_dug: bool`,
`silver_key_draft: bool` (next draw biased to cross/t), `shield_used: bool`
(Knight's Shield daily charge), `removed: list[str]` (ids taken by the Lost & Found or
consumed — excluded from spawn pools), `spawned_today: set[str]` (unique items already
spawned — a unique item spawns at most once per day).

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
  required in hand for Stopwatch, per the wiki).
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
`gear_wrench`, `dowsing_rod`, and everything on `implemented: false` records.

### Keycard

Stays on the existing locks.json mechanism (`has_keycard`); the `keycard` item record
exists with `meta.blocked_on: null` and a note that spawning/state are handled by
`engine/locks.py` — it is excluded from the generic spawn pipeline to avoid
double-spawning, and the Lost & Found cannot steal it (matches its resource-adjacent
handling in the real game's Security inventory... simplification, documented).

### Lost & Found room

The room already exists in rooms.json (`lost_and_found`, studio_addition pool,
unusual) — contrary to the stale CLAUDE.md note about seven absent rooms. PR1 adds
its entry effect: tag `lost_and_found` on the room record (in rooms.json AND the
ingest_sheet.py effect-overrides map, so re-ingest keeps it), delegating to
`special_items.lost_and_found_on_enter`: steal one uniformly random held special item
(keycard excluded; nothing if inventory empty), then grant two draws from the data
pool (excluding already-held uniques; `die` grants a die).

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
