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
