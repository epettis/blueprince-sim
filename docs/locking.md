# Locked doors and the security-door system

Both systems live in `engine/locks.py` with tables in `data/locks.json`
(datamined from TFMurphy's lock/security datamine, reddit `1lfxyex`, via
wiki.gg Doors). State is per doorway *segment* — the shared edge between two
cells — in `GameState.door_state`, keyed by `locks.segment_key`. The whole
system is disabled by `cfg.door_locks=false`.

## Locked doors

Every doorway segment rolls its lock state from a table keyed by rank and
orientation:

- Never locked below rank 4 by chance; 25% inside rank 4, climbing to
  110%/130% at ranks 8–9. Values over 100% are guaranteed locks at neutral
  bias.
- A daily **bias multiplier** softens streaks: hitting a locked door
  subtracts 0.385 (capped at 1), an unlocked one adds 0.35 (floored at 1),
  with datamined second-roll exemptions above 100% and below 31%.
- **Corridor and Corriyard doors are guaranteed unlocked.**

Opening a locked door consumes one key — at a frontier doorway when
drafting through it, or mid-walk when a path routes through a locked door
between placed rooms. The pathfinder is **key-aware**: a locked door en
route is keyed through or walked around, whichever the key and step budgets
allow. With no key, the detour distance is what counts — a lock can put the
Antechamber out of reach of your remaining steps.

**In-drafting opens doors free**: a drafted room whose floorplan has a door
facing an existing locked or security door swings it open without spending
a key.

## The unlock menu — how a lock is opened is a player decision

Trying a door is a distinct step from opening it, and the engine never picks
the method. Opening a `DOOR_LOCKED` segment parks the doorway in
`Phase.LOCK_PENDING` (a structural clone of the `COLOUR_PENDING` precedent)
and hands the choice to the player. Trying is free; only a menu choice spends
anything.

Nine action ids, `LOCK_MENU_BASE + 0` … `LOCK_MENU_BASE + 8` in `env/actions.py`
(the absolute width has rotted before and moves again with `N_ACTIONS`; see
[`rl-environment.md`](rl-environment.md) for the current register):

| offset | Row | Effect |
|---|---|---|
| `+0` | **Use a key** | spends `lock_open_cost` keys (base 1, plus a Great Hall side door's search surcharge); an active Stopwatch charge refunds it entirely, given ≥1 key in hand |
| `+1` | **Lockpick** | one Lock Pick Kit / Pick Sound Amplifier attempt; failure spends nothing and does **not** exit the menu |
| `+2` | **Abandon** | back to `NAVIGATE`, door still locked, nothing spent |
| `+3` … `+8` | **A special key** | `data/locks.json`'s `special_key_menu.order` |

**Abandon is always legal**, so the phase is never a dead end — and declining
is a real play: spending steps to find an unlocked door instead of spending a
key is a strategy the model has to be able to express.

**A special key may be used even when a regular key would work.** That is the
point of the menu, not a side effect: the special keys bias the draft pool
toward a room or a room type, so paying with one can be worth more than the
key it saves.

The six special-key rows are a **published fixed order**, held in
`data/locks.json` rather than a Python constant because it is a published
table: Basement Key, Secret Garden Key, Silver Key, Key 8, Master Key, Prism
Key. `env/actions.py`'s `LOCK_SPECIAL_KEY_BASE` range indexes that array 1:1.
Three rows are **reserved and permanently masked**: `secret_garden_key` and
`key_8` are modelled here as `draft_conditions` tags rather than door keys at
all, and `basement_key`'s `fits()` is always False because this sim has no
on-grid Basement door (the Basement is an area-graph destination — see
[`areas.md`](areas.md)). A reserved id costs one permanently-False mask slot
and never shifts later, which is what let the Prism Key go live with
`N_ACTIONS` unchanged.

**Door cost is observable.** `grid_search_cost` (a 9×5 plane in `env/obs.py`,
from `Game.door_search_cost`) exposes the Great Hall's side-door surcharge, so
a 3-key door is distinguishable from an ordinary 1-key one. Without it "spend
keys versus walk further" would be unlearnable at exactly the doors where it
matters most.

**One rule, four call sites, one test.** "Can this locked doorway be opened"
is asked by the action mask, `doorway_passable`, `frontier_doorway_triable`
and `_action_in_budget`'s end-of-day check. They drifted apart once — one copy
counted only regular keys and hardcoded a cost of 1 —
so `test_frontier_lock_affordability_agrees_with_the_lock_pending_menu` pins
all four against what the menu actually accepts. A rule written N times needs
an agreement test, not N careful edits.

### The Prism Key's colour

The Prism Key's colour is a property of the **room**, not a player pick: the
wiki's *"the color is chosen at random from all valid choices"* is read
literally, over the reroll clause that would have made it a de facto choice.
In a multi-colour room it is **one RNG draw**, which affects only 6 rooms (the
five Aquarium variants and `maids_chamber`); everywhere else the room forces
the colour and no draw happens.

So it threads a colour through `_continue_draft` rather than entering
`COLOUR_PENDING`, whose mask unconditionally offers all five colours for the
Secret Passage's genuine choice — and the Prism Key does not fit purely blue
or black rooms at all. A consequence falls out for free: `_continue_draft`
takes the Secret-Passage branch only when `colour is None`, so a Prism Key
used on a Secret Passage door **takes priority**, which is exactly what the
wiki specifies.

### Lockers

A locked locker costs exactly **one basic key**. The wiki is explicit that
lockers are not doors, so the Lock Pick Kit, Master Key, Stopwatch and the
smashers do nothing to them. This is what makes the Locker Room's key-spreading
load-bearing rather than flavour.

## Security doors

Doors of whitelisted mechanical rooms (Security, Workshop, Pump Room,
Archives, …) can spawn as keycard doors when close enough to the
Antechamber: `rand(0,75) > distance`, with a 60-unit cutoff. Spawns are
capped per day by the **security level** — low 3 / normal 4 / high 6, with
high forcing every whitelist door's chance to 100%. Keys never open
security doors.

Three interacting controls:

- The **Keycard** (found by chance in Archives/Office/Laboratory/Vault/…)
  opens security doors while the system is powered.
- The **Utility Closet** breaker toggles keycard power.
- The **Security terminal** sets the security level and its offline mode:
  unpowered doors open for free once Security has been visited (the sim
  assumes the player flips offline mode to Unlocked), and are sealed to
  everyone — keycard included — otherwise.

So the two winning configurations are: powered + keycard in hand, or
unpowered + offline mode Unlocked (requires a Security visit).

## The Antechamber's doors

Two arms, controlled by `cfg.antechamber_levers`:

- **Shipped default (`antechamber_levers=True`)**: all four of the
  Antechamber's doorway segments start `DOOR_SEALED` and open only by pulling
  a lever elsewhere in the house — the real game's bespoke Antechamber locks.
  See [`antechamber-lever-design.md`](antechamber-lever-design.md) for the
  lever sources and per-segment mechanics.
- **Legacy arm (`antechamber_levers=False`)**: the doorways instead roll on
  the ordinary rank 8↔9 lock table (130% ⇒ locked at neutral bias), and
  drafting a connecting room opens them via in-drafting, so entry stays free
  once connected. This reproduces the pre-lever model and exists for
  comparison (see `greedy-strategy.md`'s baselines).

## Deliberate divergences

- **Lock state is visible to the agent.** `env/obs.py` builds `grid_locked`,
  `grid_security` and `grid_sealed` as 9×5 direction-mask planes, set on both
  cells of every segment. The real game determines a door's lock state on
  first click and latches it, so "trying a door reveals whether it is locked"
  would be an observation **reduction**, not an addition — it removes
  information the agent has today and makes the learning problem strictly
  harder. Faithfulness bought with sample efficiency; not taken.
- Locks roll when the first door on a segment is *placed*, not lazily on
  first click as in the real game, so the bias sequence follows placement
  order.
- **`path_key_cost` is not Stopwatch-adjusted.** `_nav_bfs` models only the
  Master Key when costing a path; honouring the Stopwatch refund would mean
  simulating one global charge depleting in walk-order across every locked
  door en route. The menu's own `can_use_key_at_lock` does honour it, so the
  divergence is confined to path costing.
- **The Silver Key's bias is discarded on a Secret Passage doorway.** Using it
  there consumes the key and sets `state.special.silver_key_draft`, but
  `Game.open_door` resolves the Secret Passage's own colour pick before any
  deal happens and `draft.py`'s colour-selective draw does not consult the
  bias flag. The wiki settles only the *Prism* Key's Secret-Passage
  interaction, not the Silver Key's, so this is left as a named gap in
  `data/locks.json` rather than guessed at.
- The per-door Left/Forward/Right security table is collapsed to one chance
  per room (its strongest door).
- Not modeled: the "Set"-door double-trigger, the Shelter's unlock effect,
  and the Passageway high-security distance waiver. The Lock Pick Kit, the
  Master Key and the special keys are menu rows above; the Great Hall's
  guaranteed locks and side-door search cost, the Vestibule's per-entry
  re-lock, the Foyer's Hallway override and the Kennel's dig-unlock are all
  modelled and owned by [`rooms.md`](rooms.md).
- The Keycard is found by flat chance (25%, inferred) on first entry to a
  wiki-listed source room.
- Visiting Security always sets offline mode to Unlocked (the strategically
  dominant choice); toggles are free actions while standing in the room.
