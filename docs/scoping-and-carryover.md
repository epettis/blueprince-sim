# Scoping and carry-over

How long a fact lives, and which channel carries it there. Code:
`env/multiday.py` (`DayChain`), `engine/shops.py::carryover`,
`engine/special_items.py::end_of_day_carry`, `config.py` (`GameConfig`).

This document is authoritative for persistence scope. Confusing two scopes, or
reaching for the wrong channel, is the single most repeated modelling error in
this repo — so the rule is stated once, here, and cited from everywhere else.

## The four scopes

| Scope | Lives for | Reset by | Where it lives |
|---|---|---|---|
| **Immediate** | one decision | resolved on the spot | a local, or a `GameState` field cleared in the same step |
| **Day** | one in-game day | `Game.reset()` at day start | a `GameState` field with **no** `GameConfig` twin |
| **Attempt** | one 200-day attempt | `DayChain.advance()`'s wrap block | a `GameConfig` field, cleared in the wrap block |
| **Save** | forever | nothing | a `GameConfig` field **deliberately absent** from the wrap block |

The distinction that keeps costing time: **attempt-scoped is not permanent.**
`DayChain.advance()` wraps after `n_days` (default 200) — `current_day` returns
to 1 and everything named in the wrap block goes back to its `base_cfg` value.
"Carried across days" and "permanent across the save" are different claims.

## The three carry channels

Everything that crosses a day boundary goes through one dict:
`Game.carryover()` (assembled in `engine/shops.py::carryover`) is handed to
`DayChain.advance()`, and `DayChain.next_config()` folds the result into the
next day's `GameConfig`. There are exactly three channel shapes, and the first
question about any new cross-day fact is which one it belongs in.

### 1. `DayChain._CARRYOVER_KEYS` — bool fields, attempt-scoped

`env/multiday.py:30`. A `frozenset` of **17** names, every one of them a `bool`
field on `GameConfig`:

    lunch_box_unlocked        cursed_effigy_unlocked    entrance_vase_broken
    outer_chip_dug            royal_scepter_found       west_gate_unlatched
    mine_south_visited        sealed_entrance_broken    weight_room_wall_broken
    room46_reached            room8_solved              boiler_room_steam
    treasure_trove_blackprint orchard_unlocked          throne_room_blueprint
    satellite_dish_unlocked   conservatory_floorplan_found

`conservatory_floorplan_found` is the most recent addition (16 → 17): set on
campsite arrival while holding a shovel (`special_items.py::on_area_arrival`),
same shape as `treasure_trove_blackprint`/`throne_room_blueprint` — a
`GameConfig` flag `decks.py::eligible_pool` reads to add a room to the draft
pool from the following day. **This channel does still grow**: it is bool-only
and attempt-scoped forever, but its *length* is not frozen — see the
properties below.

Merge rule: **only `True` merges**, so a flag can never un-discover something
already found. Cleared wholesale at the wrap (`self.carried_flags = {}`).

Three properties of this channel, each of which has been got wrong at least
once:

- **It is bool-only.** An int, a string, a set or a dict cannot go in it. A
  running counter, a per-room rarity map, an ordered history — none of them
  fit, and "grow `_CARRYOVER_KEYS`" is never the answer for them. They go in
  channel 2.
- **It is attempt-scoped, not save-scoped.** There is **no save-scoped bool
  channel in this codebase at all**; adding one would be a new mechanism, not
  an extra key. A bool that must survive the wrap is modelled as a save-scoped
  *set* instead (`sigil_doors_open` is the template).
- **Its length is an observation width.** `env/obs.py` derives the `carryover`
  vector's length from `len(DayChain._CARRYOVER_KEYS)` and encodes the keys in
  `sorted()` order. The sort is load-bearing: Python randomises string hashing
  per process, so a set-ordered vector would permute between training runs and
  silently invalidate a checkpoint's learned field positions. **Any PR that
  touches `_CARRYOVER_KEYS` is an observation-space change**, whether or not it
  looks like one.

### 2. The explicit non-bool fields

Anything that is not a bool is a named attribute on `DayChain`, threaded into
`next_config()` and handled by its own block in `advance()`. Four merge
disciplines, and choosing the wrong one is a silent balance error rather than a
crash:

- **Union-merge** — accumulates forever within the attempt, never shrinks:
  `used_vault_keys`, `lit_targets`, `collected_disks`,
  `collected_allowance_tokens`, `collected_sanctum_keys`, `sigil_doors_open`,
  `applied_upgrades`.
- **Replace** — today's value already *is* the running total, because the
  `GameState` field was seeded from the config at `reset()` and only ever
  grown: `allowance`, `stars`, `main_course_bonus`, `letters_delivered`,
  `chapel_tithes`, `draft_counts`, `foundation_cell`/`foundation_doors`,
  `axed_rooms`, `permanent_rarity`, `planetarium_planets`, `mail_cycle`.
- **Replace, then decay** — a counter that one elapsed day reduces:
  `mail_transit_days`, `shrine_blessing_days` and `shrine_curse_days` each
  decrement by 1 floored at 0. `repellent_bans` is the same shape spread over a
  dict of per-room counters: decrement, drop at zero, cap at 3 active with
  oldest-first eviction.
- **One-day pulse** — unconditional replace, **never** an OR-merge:
  `sauna_bonus`, `morning_room_bonus`, `break_room_keycard`, `frozen_coins`,
  `frozen_gems`, `no_contact_due`. Each reports only whether *today* earned the
  bonus, so a day that does not re-earn it must clear what yesterday set. That
  is exactly what keeps them pulses instead of permanent unlocks (see
  "One-day pulse versus permanent" below).

### 3. `carried_items` — items with `persistence: "permanent"`

An item's own record carries its persistence:

    data/special_items.json `persistence`
      -> engine/special_items.py::end_of_day_carry
      -> carryover()["starting_items"]
      -> DayChain.carried_items
      -> next day's GameConfig.starting_items

It carries `permanent` and `until_used` self-persisters plus the Coat Check and
Moon Pendant carries. This is the channel that makes an *item* survive the
night, and it is the one most often missed when someone proposes a 17th
`_CARRYOVER_KEYS` member to make something "permanent" — an item that is
already `persistence: "permanent"` needs no flag at all.

It is **attempt-scoped**: `carried_items` is cleared at the wrap.

## The save-scoped carve-outs

These are the `DayChain` fields deliberately **absent** from the wrap block, so
they survive into the next attempt:

- `stars` — accumulate across the whole save toward a reroll trade.
- `main_course_bonus` — the Cloister of Joya's permanent Dining Room bonus.
- `letters_delivered` — experiment letters delivered to the Mail Room.
- `shrine_blessing_id`, `shrine_blessing_days`, `shrine_curse_days`,
  `shrine_offered_coins`, `shrine_monk_room` — the five Shrine fields.
- `axed_rooms` — The Axe's ordered record of permanently-axed floorplan roots.
- `permanent_rarity` — the Gear Wrench's room-id → rarity-index map.
- `planetarium_planets` — the Telescope-in-Planetarium's unlocked planets.

`tests/test_carryover.py` pins this set deliberately, so adding a fourteenth
member is an explicit edit rather than a slip. That test is the guard: a
carve-out is a claim about the *game*, not a convenience, and each one above
was ruled individually.

## What the attempt wrap clears

Everything else. `advance()` resets, at the wrap: `carried_flags`,
`carried_items`, `used_vault_keys`, `lit_targets`, `collected_disks`,
`chapel_tithes`, `allowance`, `mail_cycle`, `mail_transit_days`,
`hallway_tomorrow_extra`, `clock_tower_tomorrow_keys`,
`collected_allowance_tokens`, `collected_sanctum_keys`, `sigil_doors_open`,
`repellent_bans`, the six one-day pulses, `applied_upgrades`, `draft_counts`,
and `foundation_cell`/`foundation_doors`.

Note the asymmetry it produces: `allowance` resets to its base preset while
`stars` does not, even though both are running permanent totals in the game's
own language. That is deliberate — each was ruled on its own evidence — but it
means "similar to an allowance" is not a scoping argument.

## Cross-day mechanics are in scope

A mechanic spanning days is **not** a reason to leave a room unimplemented.
Seven rooms were once blocked purely because their own `meta.effect_text`
annotated the mechanic as cross-day (`sauna`, `morning_room`,
`master_bedroom`, `clock_tower`, `mail_room`, `freezer`, `break_room__ix11`);
all seven are implemented on the `orchard_unlocked` pattern — flag or counter
set on the triggering event, carried by `DayChain`, consulted in
`Game.reset()`.

The general rule that follows: **a scope annotation is a claim with an expiry
date.** When the engine grows a capability, sweep the annotations that denied
it, because a stale "out of scope" note does not merely mislead a reader — it
suppresses the room from future audits.

## One-day pulse versus permanent

There are two cross-day shapes and they look identical in an effect text:

- **One-day pulse** — applies to exactly the following day and must be
  re-earned. The Sauna (+20 steps tomorrow), the Morning Room's next-day half
  (+2 gems), the Freezer's coin/gem carry, the Break Room's keycard. The wiki's
  **Tomorrow Rooms** category is the discriminator, and each room's own
  `effect_text` says "**Tomorrow**, you will start the day with ...".
- **Permanent once earned** — an OR-forever flag in `_CARRYOVER_KEYS`.
  `orchard_unlocked`, `west_gate_unlatched`, `sealed_entrance_broken`, and the
  Gemstone Cavern's +2 gems per day from the day after first arrival.

**"Tomorrow" in an effect text means exactly one tomorrow.** Establish which
shape a bonus is before modelling it: implementing a Sauna visit as permanent
would pay +20 steps on every remaining day of a 200-day attempt.

## Deliberate divergences

- **The West Gate is save-level in the game and attempt-scoped here.**
  Unlatching it is permanent across the whole save (owner-confirmed, from
  play), but `west_gate_unlatched` is a `_CARRYOVER_KEYS` bool, so it clears at
  the wrap and must be re-earned via the Garage on day 1 of each new attempt.
  Honouring it does not shift the measurement baseline — day-1 outer-room
  access is unchanged either way.
- **`carried_items` is narrower than "across an entire save".** An item that is
  `persistence: "permanent"` is permanent within the attempt only. The visible
  consequence is the Basement Key: on day 1 of a new attempt the basement doors
  re-lock until the agent walks back to the Antechamber. Closing it would need
  a save-scoped **set** (`basement_doors_open`, built like `sigil_doors_open`),
  not a bool — the ruling was "open *a* basement door", singular, and there are
  three. Not built: the divergence window is a few days at the start of each
  attempt.
- **Applied Upgrade Disks reset on wrap.** The game treats them as permanent
  progression; `applied_upgrades` is cleared to the base preset. Unasked and
  unresolved — this is not covered by the `stars` or Joya rulings, both of
  which were made about their own field specifically.
- **The star sink is not modelled.** Stars accumulate save-wide toward a reroll
  trade that has no representation here, so any measured star total is an upper
  bound on what a player would actually be holding.
