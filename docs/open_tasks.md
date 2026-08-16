# Open tasks

Work the project owner has identified and that is NOT in `docs/plan.md`'s
delivered set -- each needs its own design pass. Two sources so far: a review of
the special-items PR stack, and a recorded session of real play through the
Training Observatory. That first session's findings have shipped; a second
session produced tasks 44-48, of which 48 remains.

**Play findings outrank the wiki**, per [`doctrine.md`](doctrine.md) -- but where
one contradicts a published rule, surface the conflict rather than silently
picking a side.

The file reads in three parts: **open tasks** (numbered sections), then the
**open owner questions** in task 23, then the **decisions log**, which is always
the last section. Lessons about *how to work* are not here; they are in
[`process.md`](process.md).

## The decisions log is a waiting room, not an archive

**A ruling belongs in the design document that owns the mechanism, or in a
comment beside the code it governs — never here once the work has landed.**
Architectural decisions spanning many parts of the codebase go to a design doc;
a decision that explains why one function does something surprising goes in that
function, not in a doc and not here. A ruling whose work has shipped and whose
rule is already stated elsewhere is **deleted**; git keeps it.

What is left in the log is therefore only rulings for work that is **not yet
built**, where there is no code to comment and stating the rule in a design doc
would describe behaviour the engine does not have. Each one leaves the log the
day its work lands.

A completed task is deleted too, rather than marked DONE — but read it for live
remainders first. Sections have twice hidden real content under a DONE heading.

## How to cite this file

**An entry here records what was true when it was written; the topic docs
record what is true now.** Readers have repeatedly taken the first for the
second, and four false claims propagated out of this file in a single day
before a fifth was caught.

So a cross-reference in `src/`, `tests/`, `tools/`, `data/` or another doc must
point at **the doc that owns the rule**, never at the log. `open_tasks.md` may
be cited for exactly two things:

- a **numbered open task**, cited by its number;
- an **open owner question**, cited by its letter within task 23.

Anything else — a mechanic, a magnitude, a ruling, a doctrine, a deliberate
divergence — cites the topic doc that owns it. If nothing owns it yet, that is
the signal to create or extend a topic doc, not to cite the log. In particular
**do not write "owner ruling, see the decisions log"**: state the rule in the
topic doc and cite that, because the reason a rule holds is not the same fact
as who said it.

Current owners:
[`scoping-and-carryover.md`](scoping-and-carryover.md) (persistence scope and
the carry channels), [`doctrine.md`](doctrine.md) (sources of truth,
assumed-solved, trophies, the acceptance bar),
[`architecture.md`](architecture.md) (data-vs-code ownership, the registries,
the id allowlists), [`rl-environment.md`](rl-environment.md) (observation and
action spaces, the width register, replay and measurement discipline),
[`luck.md`](luck.md),
[`locking.md`](locking.md), [`rewards.md`](rewards.md) (reward shaping),
[`foundation-design.md`](foundation-design.md), [`areas.md`](areas.md),
[`power.md`](power.md) (the steam-power rule, the powered-room lists),
[`rooms.md`](rooms.md) (per-room mechanics, the spread effects, the Mail
Room cycle),
[`drafting.md`](drafting.md) (the whole draft pipeline, concealment, redraws),
[`special-items-schema.md`](special-items-schema.md) (the
`special_items.json` data contract and its status flags),
[`special-items-behaviour.md`](special-items-behaviour.md) (per-item and
per-system item rules, commerce, containers, ignition),
[`experiments-design.md`](experiments-design.md),
[`upgrade-disks-design.md`](upgrade-disks-design.md),
[`greedy-strategy.md`](greedy-strategy.md), [`process.md`](process.md).

## 24. Reward calibration

All shaping constants (`special_item_values`, `PATHS_ONE_PENALTY` /
`PATHS_ZERO_PENALTY`, scepter bias) are deliberate knobs, set without real
multi-day run data behind them.

**The statistics now exist, and they are the finding.** `runs/postplay-v1`
(`--multi-day 1000 --unlocks all`, 30 envs) reached **1.4M episodes across 66
full 1000-day chains with zero tracebacks** -- the engine holds up over long
chains. But **`win_rate` is 0.0 for every one of those episodes**: the policy
has never once reached the Antechamber. `ep_rew_mean` drifted 0.669 -> 0.764
while `ep_len_mean` stayed near 15.6 actions per day, against
`frontier_greedy`'s 24.3 rooms placed per day.

**The cause is measured, and it is the fixture, not the constants.**
Evaluating `ep1700003.zip` on the same `all_unlocks_config()` the run trains
against:

| measure | trained policy | `frontier_greedy` | `random` |
|---|---|---|---|
| mean deepest rank | **1.00** | 7.19 | 3.04 |
| mean rooms placed | **1.00** | 23.99 | 9.16 |
| P(reach Antechamber) | 0.000% | 6.675% | 0.000% |

Rank 1.00 and one room placed means **the Entrance Hall and nothing else**:
the policy never drafts. It is not merely losing, it is doing worse than
`random`. This is not a deterministic-evaluation artifact -- sampling the
stochastic policy instead only moves rank to 1.20.

What it does instead is leave the house and tour the grounds. Its three most
frequent actions are travel to `blackbridge_grotto`, `mine_south` and
`upper_rotating_gear`, and over 40 episodes it visited
`blackbridge_grotto`, `mine_south`, `upper_rotating_gear` and `west_path` in
**40 of 40**. Two independent measurements agree on this: the action
histogram and `state.areas_visited`.

The fixture is what makes that possible. Counting legal travel actions on the
first step of day 1:

- `all_unlocks_config()` -- **9** targets, including `blackbridge_grotto`,
  `mine_south`, `upper_rotating_gear` and `basement`
- `fresh_save_config()` -- **3**: `apple_orchard`, `campsite`, `private_drive`

Because the preset's job is to set every carry flag, the whole area graph is
open from the first decision, and touring it pays shaping reward with no
drafting required. The agent found the highest-reward-per-step loop available
and it does not involve playing the game. That is why `ep_rew_mean` rises
while rank does not.

**This answers the owner's own question** -- *"I would ask why that is called
for the training baseline instead of a `default_config()`"*. Empirically, it
should not be: `all_unlocks_config()` is correct as a spec (it must enable
every unlock) but it is a degenerate training fixture.

**The single most-taken action in that policy was travel to
`blackbridge_grotto`**, whose edge passed on a POWER conjunct that stood in for
an unbuilt mechanism. Both of its conjuncts are now real and independently
load-bearing ([`power.md`](power.md)), so that action is gated.

So calibration does not start from the constants. The fixture is settled and
POWER is built; **what is left is the retune, and it needs statistics from a
run that actually plays the game.**

**OWNER RULING: stop the run and train from a fresh save.** `runs/postplay-v1`
was stopped at ~1.85M episodes; its checkpoints remain on disk. *"The training
should start from a fresh save. The default config should just be a fresh
save."* So `--unlocks` and `make_single_env` default to `none`, and there is no
third `default_config()` -- fresh save **is** the default.
`all_unlocks_config()` remains correct as a spec and stays available as an
explicit preset; it simply stops being what training starts from.

The fixture is only the *starting* state: `DayChain` carries earned flags
forward, so a chain can in principle reach the late game by playing into it.
Measured, the default now starts with **1 of 19 carry flags and 3 legal travel
targets** instead of 19 and 9.

**But no policy we have ever plays into it, and that is measured.** Over a
250-day fresh-save chain, `frontier_greedy` reaches rank 9 and averages 6.54 --
it drafts well -- and earns **0 of the 19 carry flags, on every day**. Over 60
fresh-save days each, `greedy_rank`, `economy` and `random` also earn **none**.

The carryover plumbing is not the problem: all 19 keys appear in
`Game.carryover()`'s output, so anything earned would be carried. Nothing is
ever earned. The unlocks need specific rooms drafted *and* deliberate off-grid
routing (reaching `west_path`, `mine_south`, the Orchard), and drafting-led
policies never go there.

**So a fresh-save run has an exploration problem, not just a calibration one.**
A 1000-day chain from a fresh save currently replays day 1 a thousand times.
The fixture ruling stands -- `all_unlocks_config()` is degenerate for the
opposite reason, handing the whole map over for free -- but the retune cannot
assume the chain will progress on its own. Whether to shape toward the first
unlock, seed the chain part-way, or accept a long flat start is the open
question, and it should be settled before committing a long run.

**The first unlock is one action deep, which makes shaping the cheapest
option.** A fresh save offers three travel targets, and one of them earns a
flag outright: travelling to `apple_orchard` sets `orchard_unlocked` in
**40 of 40** fresh saves. It costs a single action on day 1, never fails, and
pays +20 starting steps on every later day, so it compounds. No scripted
policy takes it, because none of them travels.

**The carryover machinery is ruled out as a cause.** All 19 keys appear in
`Game.carryover()`'s output and each carries when its state term is set. Two
apparent defects -- `reservoir_13_reached` missing from the builder, and
`royal_scepter_found` having no state term -- were both misreadings, the second
because that flag defaults to True in `GameConfig`. Only 4 of the 19 gate an
area edge (`west_gate_unlatched`, `mine_south_visited`,
`sealed_entrance_broken`, `boiler_room_steam`); the rest gate pools and items.

**What remains on this task is the reward calibration itself.** The fixture
explains why touring beat drafting; it does not calibrate
`special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY` or the scepter
bias. Those still need statistics from a run that actually plays the game, so
this task stays open behind the next one.

## 48. A colour-selective draft loses a slot when a default is already placed

> "I was only able to draft *two* yellow rooms instead of *three* from a Secret
> Passage on the east wing (r4c4). I had already drafted the Commissary. Inspect
> what yellow rooms are draftable in r5c4."

**Reproduced, and the owner is right: the sim is wrong.** "Yellow" is the
**shop** colour -- the game's borders are violet/bedroom, orange/hallway,
green, **yellow/shop**, red, black/blackprint, which maps onto the engine's five
categories exactly (blueprince.wiki.gg). The Commissary is a shop, so the report
is a shop-colour draft with a shop already on the grid.

Dealing the shop hand at r5c4 (cell 24) entering north, over 200 seeds:

| Commissary already placed | slots dealt |
|---|---|
| no | **3** in 200/200 |
| yes | **2** in 159/200, 3 in 41/200 |

In 159 of those the hand is exactly `(kitchen, locksmith)` -- the two survivors
of shop's published default triple `[commissary, kitchen, locksmith]`.

**Root cause, and it is already written down.** A colour-locked slot draws from
the rank/rarity pool, then falls back to that default triple, which for a
colour-locked slot is the *final* fallback. The wiki's other thin-pool
fallback -- **reserve copies**, tried between the pool and the triple -- is
deliberately unmodelled. [`drafting.md`](drafting.md) predicted this exact
outcome: *"That branch is reachable only because reserve copies are unmodelled:
it is a modelling artifact, not a game rule."*

So this is not deck depletion and not geometry -- the earlier enumeration found
7 legal shop rooms at that cell. It is the unmodelled reserve-copy tier, firing
in the common case rather than a rare one.

**It is not shop-specific, and green is worse.** Placing each colour's first
default and dealing that colour, 100 seeds:

| colour | first default | slots dealt |
|---|---|---|
| bedroom | Bedroom | 3 in 100/100 |
| red | Gymnasium | 3 in 98/100 |
| hallway | Hallway | 3 in 87/100 |
| shop | Commissary | **2 in 75/100** |
| green | Courtyard | **1 in 61/100**, 2 in 25/100 |

**The fix is to model reserve copies, and their rules are now researched** --
see [`drafting.md`](drafting.md)'s colour-selective section, which owns the gap.
The answer to the question this task asked is that a reserve is **not** filtered
by the one-copy-per-grid rule (*"may be duplicates of rooms in the estate"*),
which is exactly why it fills a slot the defaults cannot.

Because that relaxes the one-copy invariant for one draw tier and moves the
draft distribution, building it needs a ruling first: **question (a)** below.
Until then a thin colour keeps dealing short hands whenever one of its three
defaults is on the grid.

## 23. OPEN OWNER QUESTIONS

The single home for questions that need an owner ruling before the work they
block can start. A question is added as a lettered item, and cited from
elsewhere by that letter.

## Decisions log

Every entry here is held for one reason only: **it specifies work that is not
built yet.** Each one leaves the log the day its work lands.

- **The Conservatory's 15% forced draw** — its reachability and its drawing board have both shipped.

Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

- **The Conservatory's 15% forced draw.** Its Found Floorplan gate and its
  remodel have both shipped; the forced-draw entry has not, and
  [`drafting.md`](drafting.md) records that gap.

- **The retrain is owed, and is held on the owner's explicit say-so alone.**
  `baseline-ep8275991` was trained against rules the sim no longer implements —
  it was built at `N_ACTIONS` 196 against today's width, so by
  [`rl-environment.md`](rl-environment.md)'s own rule it cannot load. **Retrain
  once, after the batch lands**, not per change. Task 24's reward calibration is
  blocked behind it.
