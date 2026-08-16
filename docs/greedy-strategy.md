# The greedy strategies

The scripted heuristic policies in `cli/policies.py`, used as batch-mode
baselines (`blueprince-sim batch --policy <name>`) and as the bar RL
policies must beat. A policy is `fn(game, rnd) -> None` executing one
decision against the Game API directly.

`POLICIES` exposes four: `random`, `greedy_rank`, `economy`, and
`frontier_greedy` (the strongest scripted baseline).

## Drafting: weighted option scoring (`_choose_best`)

All greedy variants score the affordable options of a hand and take the
best; with no affordable option they fall back to the guaranteed-free
slot 0 (opening a door commits you to a room — there is no decline). The
score of an option is:

- `connectivity`: + weight × the room's door count (more doors, more future
  frontier).
- `north`: + weight if the dealt orientation has a north door (progress
  toward the Antechamber).
- `items`: + weight × guaranteed item count (economy only).
- `cost`: − weight × effective gem cost (after Hovel/Terrace discounts).
- `red_penalty`: − weight for red rooms.

Weight sets: `greedy_rank`/`frontier_greedy` use
`{connectivity 1.5, north 2.5, cost 0.5, red_penalty 2.0}`. `economy` is a
**distinct** weight set, not a superset of it: `{connectivity 1.2, north 2.0,
items 0.8, cost 0.4, red_penalty 2.5, redraw_below 2.0}` — four of the shared
weights move, not only the two new ones (`items`, `redraw_below`). Hands
scoring below `redraw_below` are redrawn when a free redraw or a die is
available.

## Navigation: `greedy_rank` (push north)

One NAVIGATE decision, first match wins:

1. Step into the Antechamber if adjacent (win).
2. Move into a freshly drafted, not-yet-entered room (deepest rank first) —
   collect what you paid for.
3. Draft a doorway of the current room, north doors first.
4. Otherwise walk toward the deepest-rank neighbor.

`economy` shares this navigator and differs only in draft scoring.

## Navigation: `frontier_greedy` (best-first frontier expansion)

Instead of only drafting from the current room, it considers **every
reachable frontier doorway** in the house (via `Game.draft_from`, which
walks there and drafts):

1. If the Antechamber is connected and within the step budget, walk in and
   win.
2. Otherwise draft the frontier doorway minimizing
   `steps_to_reach + λ · h`, where `h` is the optimistic (ignoring walls)
   distance from the doorway's target cell to the Antechamber and `λ = 1.5`
   weights goal progress against walk cost. Doorways are skipped when they
   are locked beyond the key budget (key-aware: `key_cost_map` counts keys
   spent en route too) or are sealed security doors. A walled-off target
   scores `h = 99` — a last resort.
3. With nothing draftable, enter the nearest unentered room for its
   pickups.
4. With nothing free left underfoot either, take today's outer draft.

## The outer draft and the walk home (`_navigate_offgrid`)

`Game._action_in_budget` counts the once-per-day outer draft as a reason the
day is not over. A policy that never takes it therefore asks
`_check_termination` for an ending the engine will not give: the decision
changes nothing, `cli/batch.py`'s stall detector fires, and the episode is
recorded as `decision_limit` with steps still on the clock.

**It is deliberately the last resort, after even the free in-place actions.**
The trip costs the walk to the doorstep and lands the return leg at the
Entrance Hall, and no frontier doorway that was out of budget from where the
player stands can be in budget from there — the walk home is itself part of
that distance. So the outer draft is only ever taken on a house that has
nothing left to offer, where the steps would otherwise go unspent. Taking it
any earlier trades grid rooms for one off-grid room: `rooms_placed` counts
only grid placements (`Game._place_room`), and outer rooms are placed off it.

Off the grid the decision belongs to `_navigate_offgrid`, because every query
the frontier loop makes is a grid query and `state.pos` keeps naming the last
grid cell while the player is away. It takes the free actions underfoot (an
outer room can be a shop), steps into today's outer room for its ON_ENTER
item roll, then walks back onto the grid at the cheapest reachable anchor.
**The return leg is what makes the draft worth taking**: `west_path → grounds
→ house` is 2 steps and is always open by the time a policy is out there,
since arriving at the doorstep is itself the act that unlatches the west gate
(`Game.travel_to`) — so the shortcut home exists even on a save that had to
reach West Path the long way through the Garage.

Its destination list is built from the same predicate as the engine's
`_outer_action_in_budget` (modelled nodes, no self-travel, strict
`steps > cost`), for the same reason `_exhaust_in_place` iterates the engine's
own `_in_place_actions`: whatever the engine counts as work left, the policy
must be able to do, or the stall simply moves off the grid.

One subtlety the loop exists for: `cli/batch.py`'s stall detector watches
steps and `state.pos`, but not `state.area`. A Running Shoes hop can waive
every step of an area move, and off the grid `state.pos` does not change at
all, so a free hop moves nothing the detector reads. `_navigate_offgrid`
keeps walking within the one decision until the budget or the position
actually moves.

`_navigate_north` (`greedy_rank`, `economy`) has the same structural gap but
never reaches it: it always finds a move and walks until the step budget is
gone, so it never concedes a day the engine is holding open. Measured over
599 seeds on `all_unlocks_config()`, none of the three other policies records
a single `decision_limit` episode.

## The security doctrine (`_security_admin`, `_security_detour`)

Shared by all greedy navigators, one switch-flip per decision:

- **Utility Closet breaker**: without the Keycard, cut keycard power so
  every security door swings open once Security's offline mode is Unlocked
  (a Security visit sets that); with the Keycard, keep the readers powered
  so the card works.
- **Security terminal**: crank the level to *high* when security doors are
  effectively free doorways for us (more free doors!), drop it to *low*
  when they would just wall off the house.
- **Detour**: when drafting is blocked only by sealed security doors and a
  breaker flip would open them, walk to the Utility Closet.

## Baselines

Measured with `cli.batch` on `all_unlocks_config()` (day-20, every unlock and
every carry flag on, Treasure Trove held out via `banned_rooms`), seeds
0–3999, n=4000 per policy, under the shipped config (`door_locks=True`,
`antechamber_levers=True`):

| policy | P(reach Antechamber) | Wilson 95% CI | P(reach Room 46) | mean deepest rank | mean rooms placed |
|---|---|---|---|---|---|
| `frontier_greedy` | **6.675%** | 5.942%–7.491% | 0.000% | 7.19 | 23.99 |
| `greedy_rank` | **0.975%** | 0.714%–1.330% | 0.000% | 5.56 | 9.57 |
| `economy` | **0.675%** | 0.464%–0.980% | 0.000% | 4.83 | 8.28 |
| `random` | **0.000%** | 0.000%–0.096% | 0.000% | 3.04 | 9.16 |

**P(reach Room 46) = 0.000% for every scripted policy**, across all 16,000
episodes. "Win rate" is no longer quite the right word for this number: the
objective is two-tier (reach the Antechamber, then reach Room 46) and no
scripted policy reaches the second tier at all in this fixture.
`frontier_greedy` clears the field on the first tier — about 7x `greedy_rank`
and 10x `economy`, non-overlapping CIs — and ties them exactly, at zero, on the
second. **`greedy_rank` and `economy` are not separated by this measurement**:
their CIs overlap, so at n=4000 their order is not resolved and should not be
quoted as a ranking.

With `antechamber_levers=False` (the legacy pre-lever arm), same fixture,
seeds and n, `frontier_greedy`'s Antechamber rate rises to **~22%** (measured
22.050%, CI 20.792%–23.361%), `greedy_rank`'s to **5.100%** (CI
4.460%–5.826%) and `economy`'s to **3.375%** (CI 2.859%–3.981%); `random`
stays at **0.000%**, and Room 46 stays at 0.000% for all four. So the levers
cost each scoring policy a factor of 3.3–5.2 on its Antechamber rate, and cost
the second tier nothing it was reaching anyway. `frontier_greedy` remains the
strongest scripted policy under both arms. `random` exists to floor the
comparison; it drafts and walks uniformly among legal actions.

**Read the legacy arm's `frontier_greedy` row with a caveat the main arm does
not need.** 356 of its 4000 episodes (8.9%) end in `decision_limit` -- they hit
`run_episode`'s 800-decision cap and were cut off rather than played out. The
shipped arm truncates none. A truncated episode is scored on where it was
stopped, so 22.050% is a floor for that arm, not a measurement of it, and the
two arms' rates are not measured on quite the same footing. The factor of 3.3
for `frontier_greedy` is correspondingly a lower bound; `greedy_rank` and
`economy` truncate nothing under either arm, so their factors are clean.

Rates on this fixture are **not comparable to any rate measured on a narrower
`all_unlocks_config()`**: the preset's job is to enable every unlock, so the
draft pool and the reachable area graph are both part of the fixture, not a
constant across measurements. Quote the preset with the number.

## The owner's playbook (the human strategy the policies aspire to)

How the project owner actually plays, recorded 2026-07-28. The scripted
policies implement only parts of it. Each rule is annotated with what the
engine can express **today**, because several rules are currently
inexpressible and encoding them anyway would make a policy worse, not better.

1. **Prioritise permanent upgrades over winning today.** Unlock the Orchard,
   the Gemstone Cavern, the West Gate. Losing today is acceptable if it buys
   future wins. Insert any Upgrade Disk at a terminal immediately.
   → **Partly expressible.** `orchard_unlocked` has an in-run setter (set on
   Apple Orchard arrival, `game.py`), is a `_CARRYOVER_KEYS` member, and is
   read in more than just the day-start `+20` steps bonus (also folded into
   the carryover flags `Game` reports). `mine_unlocked` still matches the old
   claim: read only for the day-start `+2` gems and has **no in-run setter** —
   pure config. `west_gate_unlatched` *is* earnable in-run (PR #41). Disk
   insertion is fully modelled. See "The reward horizon spans the attempt"
   below for what actually blocks this rule now.
2. **The Power Hammer is the single best upgrade.** Build it, leave the house,
   break the Sealed Entrance — the fastest route to Reservoir North.
   → **Modelled.** The Power Hammer wall-break mechanic
   (`effects/rooms/weight_room.py`, `effects/rooms/greenhouse.py`) is fully
   built, and `sealed_entrance_broken` is earned in-run — latched on first
   arrival at Sealed Entrance while holding a Power Hammer — and carried
   across days via `_CARRYOVER_KEYS`. `basement` itself is `modelled: true`;
   only the `sealed_entrance` area node is a bare pass-through
   (`modelled: false`, no contents of its own). The route to Reservoir North
   this rule describes works end to end; no scripted policy specifically
   pursues it.
3. **Move the mine cart (Abandoned Mine South); light the four torches for
   Precipice access.**
   → **Partly modelled.** `mine_south_visited` is a live `GameConfig`/
   `GameState` field, a `_CARRYOVER_KEYS` member, and has an in-run setter (set
   on first Mine South arrival); `mine_south` itself is `modelled: true` — the
   Upgrade Disk sits openly there, obtainable without lighting candlesticks.
   The mine-cart move is modelled. The four torches and the cliffside elevator
   to the Precipice remain genuine stubs (`cliffside_elevator_down`/`_up`,
   `modelled: false`, "Passes (stub open)").
4. **Draft Security, Laboratory or Office until every Upgrade Disk is
   collected.**
   → **Expressible and unimplemented — the best available lever.** The disk
   terminals are exactly `laboratory`, `office`, `security`, `shelter`
   (`disk_reader` in `rooms.json`; Blackbridge Grotto is the fifth in the real
   game but has no room record). No scripted policy scores them at all.
   `Game.insert_disk()` / `choose_upgrade()` are callable directly, so unlike the
   RL-only action path a **scripted** policy can implement "insert immediately".
5. **Always pick up items in the room.**
   → **Mostly automatic.** First entry fires `roll_room_items()`. Some pickups
   are action-gated (digging, containers, shops) and are not attempted.
6. **Open every door of a room before moving on.**
   → **Expressible, but not free.** Drafting costs no step, but there is **no
   decline**: opening a doorway forces you to place one of three rooms. Opening
   everything burns deck draws and commits rooms into cells you may not want,
   which fights rule 7 directly.
7. **Keep at least two paths open.**
   → **Already in the reward, absent from the policies.** `_phi_paths` in
   `env/rewards.py` encodes exactly this doctrine (`PATHS_ONE_PENALTY = -0.15`,
   `PATHS_ZERO_PENALTY = -1.0`). The RL agent is shaped toward it; the scripted
   policies ignore it. Cheap, high-value addition.
8. **Draft heavily in ranks 1–4 to bank resources for the push north.**
   → **Expressible, and in tension with `greedy_rank`.** Its weights carry no
   `items` term at all; `economy` (`items 0.8`) is the closer baseline. Benchmarks
   of "the owner's strategy" against `greedy_rank` are measuring the wrong policy.

### The reward horizon spans the attempt

The horizon is not one day. A mid-attempt day ends with `terminated=False,
truncated=True` rather than a true terminal, so SB3 bootstraps
`V(terminal_observation)` and cross-day return flows back through the value
function; only the final day of an attempt (`current_day >= n_days`) is a true
terminal. See [`rewards.md`](rewards.md), "The horizon spans days", which owns
this. The Antechamber pays `+0.25` and Room 46 pays `+1.0`, both on first
arrival each day. Four observation keys — `day`, `carryover`, `upgrade_slots`
and `disks_spent` — let `V(s)` distinguish a heavily-upgraded attempt from a
fresh one, so "it may cost me a win today, but it will increase my wins in the
future" is representable in principle.

What actually blocks rule 1 today is on the **policy** side, not the reward
side: no scripted policy scores a disk terminal at all (see rule 4 above), so
nothing exists yet that would trade a day's win for an upgrade, even though
the value function could in principle credit the trade.
