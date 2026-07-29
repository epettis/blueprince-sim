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
`{connectivity 1.5, north 2.5, cost 0.5, red_penalty 2.0}`; `economy` adds
`items 0.8` and a `redraw_below 2.0` threshold — hands scoring below it are
redrawn when a free redraw or a die is available.

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

`frontier_greedy` is the strongest scripted policy (≈36% win rate on the
all-unlocks config before door locks; ≈1.8% with door locks on — see the
lock PR notes). `random` exists to floor the comparison; it drafts and
walks uniformly among legal actions.

## The owner's playbook (the human strategy the policies aspire to)

How the project owner actually plays, recorded 2026-07-28. The scripted
policies implement only parts of it. Each rule is annotated with what the
engine can express **today**, because several rules are currently
inexpressible and encoding them anyway would make a policy worse, not better.

1. **Prioritise permanent upgrades over winning today.** Unlock the Orchard,
   the Gemstone Cavern, the West Gate. Losing today is acceptable if it buys
   future wins. Insert any Upgrade Disk at a terminal immediately.
   → **Mostly not expressible.** `orchard_unlocked` and `mine_unlocked` are read
   at exactly two lines (`game.py`, day-start `+20` steps and `+2` gems) and have
   **no in-run setter** — they are pure config. `west_gate_unlatched` *is*
   earnable in-run (PR #41). Disk insertion is fully modelled. See the reward
   horizon problem below, which is what really blocks this rule.
2. **The Power Hammer is the single best upgrade.** Build it, leave the house,
   break the Sealed Entrance — the fastest route to Reservoir North.
   → **Not modelled.** The `grounds -> sealed_entrance` and
   `sealed_entrance -> basement` edges exist, but those nodes are
   `modelled: false` with no contents, so travelling there is a pure step sink.
   If this is genuinely the strongest line in the real game, the sim is missing
   the owner's highest-value play entirely — a modelling priority, not a
   tuning one.
3. **Move the mine cart (Abandoned Mine South); light the four torches for
   Precipice access.**
   → **Not modelled.** `mine_south_visited` appears once in the codebase, in a
   comment reading "NOT modelled; never added here". The torch gates are stubs
   that pass unconditionally.
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

### The reward horizon is what actually blocks rule 1

An episode is **one day** and the return is **one day's reward** — the env
terminates at `Phase.TERMINAL` with `+1.0` for reaching the Antechamber *that
day*. `DayChain` carries discoveries across days; nothing carries *return*
across days.

So "it may cost me a win today, but it will increase my wins in the future" is
not merely unimplemented, it is **unrewardable**: an agent that invests scores
strictly worse and gradient descent removes the behaviour. Rules 1–4 cannot be
trained until the horizon spans the attempt. This is a reward-design problem,
not a policy problem, and it gates the rest.
