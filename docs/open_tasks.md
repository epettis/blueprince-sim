# Open tasks

Work the project owner has identified and that is NOT in `docs/plan.md`'s
delivered set -- each needs its own design pass. Sources so far: a review of the
special-items PR stack, recorded sessions of real play through the Training
Observatory, and the measurement work behind the RL training runs.

**The numbered sections below are the live list.** A task is deleted the day its
work lands, so what is present is exactly what remains. This header deliberately
carries no count and no task-number range: either would rot on the next merge
that closes a task, and has.

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

**The touring behaviour had a second cause, in the reward, and it is now
fixed.** The fixture was not the whole story: under `all_unlocks_config()` a
single `travel` hop to `inner_sanctum` pulled the Antechamber's north lever and
collected the full `+0.5` north-door milestone — `+0.492` net, on **40 of 40**
seeds, at deepest rank 1 with zero rooms drafted. That is the highest-value
single action on the board for a policy that never plays, and it repeats every
day of an attempt, since the segment is re-sealed at every day start. The
milestone is now ordered behind `antechamber_reached`
([`rewards.md`](rewards.md)); measured over 60 seeds, that moves a pure-travel
day return from `+0.518` to `+0.018` and leaves `frontier_greedy` (`+0.694`)
and `greedy_rank` (`+0.521`) untouched.

**Measured, the reward does not otherwise favour touring.** Per-action-class
mean reward under masked-uniform-random rollouts on a fresh save: `move`
`+0.0235`, `choose` `+0.0088`, `open(draft)` `+0.0022`, `travel` `−0.0021` —
travel is the only negative class. And on whole fresh-save days, cumulative
`shaped` return already ranks `greedy_rank` (`+0.506`) and `frontier_greedy`
(`+0.391`) above a pure-travel trajectory (`−0.049`). The `phi_paths` term is
not a spurious drafting tax either: `frontier_greedy` loses `−0.32` to it
because it genuinely seals the house on 16 of 60 fresh-save days
(`dead_end` terminations), which is the doctrine working.

**The Tunnel-spam report does not apply to this fixture.** `tunnel` is
`pool: found_floorplan` with no unlock flag of any kind, so it is draftable
only when a config names it in `found_floorplans`. It appeared in **0 of 785**
hands over 40 `frontier_greedy` days on `fresh_save_config()`, and a 150-day
fresh chain unlocks no found floorplan at all. Under `all_unlocks_config()` it
appears in 37 of 943 hands. See [`rewards.md`](rewards.md) for the standing
cheap-depth concern, which outlives the Tunnel.

**OWNER RULING: the reward is good enough to train on, and no unlock shaping
is added.** With the north-door gate landed, the owner ruled the reward
function sufficient and authorised the retrain. So the "shape toward the first
unlock" question is answered **not now**: no per-flag acquisition bonus, and
the fresh-save chain is left to progress on its own. The argument for a bonus
is preserved in [`rewards.md`](rewards.md)'s case against the `+0.5` upgrade
proxy, which is where any future attempt should start.

**The exploration worry was measured against scripted policies, and a learning
one behaves differently.** Every "no policy ever earns a carry flag" number in
this task comes from `cli/policies.py`, none of which travels. Within the first
165 chain-day transitions of `runs/freshsave-v1`, the exploring policy carries
`orchard_unlocked` on all but one, and some chains additionally carry
`conservatory_floorplan_found` (11) and the Entrance Hall vase (8). That is an
early read on a young run, not a settled result, but it is direct evidence that
the flat-chain prediction does not transfer from scripted play to PPO
exploration. **Re-check it as the run matures**: the failure mode to watch is
the carry set going flat at `orchard_unlocked` and staying there.

**What remains on this task is the reward calibration itself**, and the
statistics it was waiting on now exist. Measured on `runs/lockfix-v1`'s
checkpoint at ~1.37M episodes, over 600 chained fresh-save days, by
decomposing `shaped()` term by term -- the split was cross-checked against the
real function on 3000 consecutive rewards, 0 mismatches, worst absolute
difference 1.1e-16, so it is a decomposition rather than a reconstruction.

| term | total | per day | share of reward mass |
|---|---|---|---|
| `phi_paths` | **-406.0** | **-0.677** | **42.9%** |
| resources | +301.9 | +0.503 | 31.9% |
| rank | +144.1 | +0.240 | 15.2% |
| placement_frontier | +50.2 | +0.084 | 5.3% |
| time | -40.9 | -0.068 | 4.3% |
| repeat | -2.9 | -0.005 | 0.3% |
| milestones | 0.0 | 0.000 | 0.0% |

Net return is **+0.077 per day**, so the `phi_paths` term alone is roughly nine
times the size of everything the policy nets. Per action class, **`choose` --
placing a drafted room -- is `-0.041` per decision** across 6345 decisions,
while `travel` is *positive* at `+0.0035`. Drafting is the most punished thing
the agent can do and touring is safe, which is the behaviour observed.

**The whole of that term's net effect is decided by where the day ends.**
`phi_paths` is a potential, so its episode sum telescopes to
`phi(end) - phi(start)`. Every one of the 600 days starts at `ante_paths >= 3`,
i.e. `phi(start) = 0`. Days end at `paths=0` on 427, `paths=1` on 74, and
healthy on 99, which reproduces the measured total exactly:

```
427 x (-1.00)  +  74 x (-0.15)  =  -438.1
telescoped phi_paths, measured  =  -438.1
```

That equality is the telescoping identity holding, which is true of any
potential -- it is a consistency check on the measurement, not a finding in
itself. **The signal does arrive during play**, charged on the transition that
closes a route: over 400 days and 17060 decisions, `phi` changed on 738 of them
(-1.0 on 84, -0.85 on 172, -0.15 on 353, +0.15 on 129).

**What the potential is bad at is being a gradient.** It takes three values and
is exactly `0` on **78%** of decisions, changing at all on only **4.33%**. So
for the overwhelming majority of drafting decisions it says nothing, and the
agent hears from it only once the house is already one or zero routes from
sealed. It warns at the cliff edge rather than sloping away from it.

**That breaks the property the term is built on.** Potential-based shaping is
policy-invariant only when the potential is **zero at terminal states**. Here
`phi(terminal)` is `-1.0`, and `shaped()` takes a `terminated` argument it never
reads. The term is therefore not the provably-safe shaping it is designed as --
it is a real bias, and it points at drafting.

Two magnitudes to weigh together: sealing the house costs `-1.0`, exactly what
winning pays (`ROOM46_REWARD`), and sealing happens on 68% of days while
winning happens on ~0%. And the trained policy seals far more than the scripted
baseline it loses to -- `frontier_greedy` seals on 27% of fresh-save days
(16 of 60), against 68% here. It is not merely shallower than the baseline
(mean deepest rank 3.24 against 6.54); it is worse at keeping the house open
while being punished harder for it.

**A good target for the calibration work is the depth gap, not the win rate.**
Win rate is 4 events in ~2M episodes and cannot steer a decision; mean deepest
rank moves continuously, is cheap to measure, sits on the critical path to
every win, and has a demonstrated reference value in `frontier_greedy`'s 6.54.
This follows [`process.md`](process.md)'s "work lanes, not numbers".

What to do about the terminal bias needs an owner ruling -- see question (a) in
task 23.

## 50. The observatory timeline should be indexed by run number, not wall time

Owner request. Every time series on the Dashboard is keyed on wall-clock time,
which is the wrong axis for a project whose training runs are stopped and
restarted constantly: an idle stretch becomes an axis gap that means nothing, and
two runs of the same length look different because one sat paused overnight.

Concretely, `app.js::renderChart` derives its x from `m.sampled_at`, plotting
elapsed hours (`hrs()`) since the first sample, with tick labels in `h` and `d`;
`app.js::renderMetricSpark` keys on `sampled_at` the same way. The replacement
value is already recorded next to it -- checkpoint records carry `episodes` and
`timesteps`, and `renderChart` already reads `m.episodes` for the eval tooltip --
so this is a change of axis, not a change of what gets recorded.

**Restarts become annotations on the timeline rather than gaps in it.** The axis
stays continuous and monotonic across a restart, because the episode counter
resumes from the checkpoint; the restart is marked in place.

## 51. The Runs tab does not fit on a laptop screen

Owner report: the Runs display is too cluttered to see at once on a laptop.
Four specific changes, all in `web/static/index.html`, `app.js` and `style.css`.

- **Make the inventory display collapsible.** `#inventory` (`.inv-chips`) in the
  Runs detail panel grows without bound as items accumulate.
- **Shrink the vertical space taken by steps, gems, keys, coins, dice and luck.**
  `#resources` (`.resources`) in the same panel.
- **Put the outdoor graph behind the house map as a tab, switching automatically
  as the replay crosses between indoors and outdoors.** Today `#house-panel` and
  `#area-panel` are both always present in `view-runs`, side by side.
- **Add a "step forward one move" button to the VCR controls.** `#controls` has
  `#pb-start` ⏮, `#pb-back` ◀, `#pb-play` ▶, `#pb-speed`, `#pb-end` ⏭
  and the scrubber -- there is a step-back button and no step-forward
  counterpart.

**The tabbed-map behaviour already exists and should be reused, not rewritten.**
The Play tab implements exactly what is being asked for here:
`#play-map-tabs` with `#play-map-tab-house` / `#play-map-tab-area`, driven by
`updatePlayMapTab(frame)` and `renderPlayMapTabs()` in `app.js`. It already
handles the subtle part -- the view follows the player only on an actual
on-grid/off-grid *crossing* (`frame.area` null <-> non-null), so a manual tab
click is respected until the next real transition rather than being yanked back
every frame. Porting that to the Runs replay is the work; inventing a second
auto-follow rule is not.

## 52. Draft frequency plot should show realised returns, not expected ones

Owner request. The 👣🔑💎🪙🍀 badges on the Draft frequency bars
(`web/static/index.html`, the `#draft-bars` card) are **expected** values, not
observed ones: `web/replay.py:37` calls
`engine.items.expected_yields(room, registry)`, which computes guaranteed items
plus luck-rolled extras at day-start luck plus flat entry effects, with coin
piles taken at their size midpoint. The plot should show what each room
**actually returned** across recorded episodes instead.

**The data does not exist yet, and that is the bulk of the work.**
`draft_stats.jsonl` records only counts per 10k-seed bucket -- `drafts` and
`seeds_with`, keyed by room name. Nothing attributes a resource delta to a room.
The recorder has to start capturing realised per-room yields and bucketing them
the same way.

**Attribution needs a definition before any code, and it is not obvious.** A
room's realised return is not simply the resource delta on the step it was
entered. All of these are genuinely that room's yield and none of them land at
that moment:

- `ON_PLACE` grants, which land at draft time, before entry;
- luck-rolled items from `roll_room_items`, which land on first entry;
- parked resources -- the Locker Room's keys sit in other cells and are
  collected on arrival there, possibly many steps later;
- spread effects, collected by `_collect_spread` on every arrival;
- the Mail Room's Same Day Delivery, which pays out on reaching rank 8.

A per-step resource diff attributes all of those to the wrong room. Deciding what
"the room's return" means -- and whether the answer is one number or a split
between draft-time, entry-time and deferred -- is the design question this task
turns on. Settle it before touching the recorder, because it determines what gets
written to disk and a recorded quantity is expensive to change afterwards.

Keep the expected values available for comparison rather than deleting them:
expected-versus-realised is the more useful reading, and the gap between them is
itself a signal about the luck model.

## 53. Exhaustive audit of every room's special behaviour

Owner request. Research each room's special functions **beyond drop
frequencies** against the wiki, check that a unit test pins each function and
its edge cases, and produce a report of what is missing.

This is a research-and-report task, not an implementation task: the deliverable
is the report. Fixes it identifies are separate work, triaged into the lanes
[`process.md`](process.md) defines.

**Read [`process.md`](process.md)'s "Keep an audit's progress bar in the tree it
audits" before starting, and take its warning literally.** The absence of a
`tests/rooms/test_<room_id>.py` file is *not* evidence a room is unaudited: 69
room modules against 87 files in `tests/rooms/`, of which only 57 are paired --
12 modules have no mirrored file and 30 files have no module. The Boiler Room is
the measured counter-example: it has no per-room file, and deleting its steam
gate fails 2 tests in `test_upper_rotating_gear.py` while deleting its
`POWER_SOURCE` capability fails 29 in `test_power.py`. Both mechanisms are
pinned; a per-room file would have been pure duplication. **Reading the directory
listing as a to-do list produces exactly the wrong answer.**

So coverage must be established the way the rest of the repo establishes it:
**delete the behaviour and run the suite.** A behaviour whose removal breaks no
test is uncovered, wherever its test does or does not live. A room whose
behaviour is covered by a topic test file is covered.

The audit spans three sources that disagree, and the report must say which it
followed each time, per [`doctrine.md`](doctrine.md):

- the room's `effects` list in `data/rooms.json` and any
  `effects/rooms/<room_id>.py` module,
- the wiki's page for the room,
- what the engine actually does when the room is entered.

Known-inert records are a starting point rather than the whole list:
`tools/validate_data.py` prints the `implemented: false` census on every run, and
the "Known gaps" section of `CLAUDE.md` names the rooms whose behaviour is still
absent (Closed Exhibit's security puzzle, the Treasure Trove's black box, the
Chamber of Mirrors' gated arm traversal). Those are the gaps already known; the
audit's value is the ones that are not.

## 23. OPEN OWNER QUESTIONS

The single home for questions that need an owner ruling before the work they
block can start. A question is added as a lettered item, and cited from
elsewhere by that letter.

### (a) Should the path potential be split into guidance and penalty?

`phi_paths` currently does two jobs at once and does the second one by
accident. Measured in task 24: its net effect per episode is entirely
`phi(terminal)`, a `-1.0` on the 68% of days that end sealed -- and a non-zero
potential at a terminal state is exactly what removes the policy-invariance
guarantee that justifies shaping this way. The per-step warnings it gives
during play are real but sparse (it moves on 4.33% of decisions), so they are
not what the episode's arithmetic turns on.

The two jobs can be separated:

- **Guidance** -- keep `phi_paths` as a true potential, zeroed at terminal
  states. It then contributes exactly 0 over every episode and still orders
  the agent's learning during play, which is what potential-based shaping is
  for.
- **Penalty** -- if sealing the house should cost something (the owner's
  two-open-paths doctrine says it should), make that an *explicit* terminal
  penalty with a deliberately chosen magnitude, priced against
  `ROOM46_REWARD`, rather than falling out of a potential's endpoint.

The ruling needed is whether to make that split, and if so what the explicit
dead-end penalty should be worth relative to a win. Doing nothing is a real
option: the bias is against drafting, and the argument that the house-sealing
doctrine should bite hard is the owner's own.

## Decisions log

Every entry here is held for one reason only: **it specifies work that is not
built yet.** Each one leaves the log the day its work lands.


Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

### Pulling an Antechamber side lever pays a potential, not a milestone

**OWNER RULING.** Opening one of the Antechamber's three sealed side doors is
worth **50% of `ANTECHAMBER_REWARD`** (0.125 against today's 0.25), expressed
as a **shaping potential** rather than a milestone bonus, and **credited only
while a live path to the opened door still exists** -- so a later draft that
walls the door off takes the credit back at the moment it seals it.

This concerns the three **side** levers only. The north lever already pays
`NORTH_DOOR_REWARD`, gated behind `north_door_opened AND antechamber_reached`.

**What prompted it: the reward is currently flat across every lever pull.**
`_ante_paths` returns >= 2 before a pull and 99 after, and `_phi_paths` maps
both to 0.0, so the potential cannot see whether any door is open. Measured
over scripted play, the `phi_paths` delta on a lever pull was non-zero on
**0 of 40** fresh-save lever entries and **1 of 198** all-unlocks entries. The
step that converts an unreachable objective into a reachable one paid nothing.

**Why a potential and not a milestone.** Potential-based shaping cannot change
the optimal policy, only the speed of finding it -- and speed is the whole
goal here. A milestone can change it, and this project has twice paid for that:
the touring policy, and the `+0.5` north-door milestone a single travel hop
collected at rank 1 on 40 of 40 seeds. Both were fixed by ordering the reward
behind `antechamber_reached`. **That fix is unavailable here**, because a side
lever is the *precondition* for `antechamber_reached`; gating on it would pay
only once the payment is pointless. A potential sidesteps the question.

**Pay once per day, not once per lever.** Three side doors all lead into cell
42 and only one is needed, so a per-lever bonus would pay 0.375 for opening all
three -- more than the 0.25 for the arrival they exist to enable, inverting the
dependency chain. A potential expressed as a property of the day's board
("is the Antechamber enterable?") is paid once by construction. Measured, the
redundancy is currently small (8 of 400 all-unlocks days open a second door,
0 of 400 on a fresh save), so this is a correctness argument, not an urgent one.

**The implementation turns on a map that does not exist yet.** Neither existing
map can express the credit: `distance_map` respects seals but walks only placed
rooms under a key budget, and `optimistic_distances` deliberately ignores door
state entirely, so it cannot tell a route through an open east door from one
through a still-sealed south door. The term needs a third map -- empty cells
freely passable, placed rooms only through their own doors, sealed segments
impassable, locked and security segments passable-in-principle.

That map answers both halves of the ruling at once. Cell 42's only grid
entrances are the three side segments (the north edge leads to Room 46 and is
usable only from inside), so with no lever pulled it reports 42 unreachable and
the credit is absent for free -- there is no separate "is a door open?" test to
write. Two things to establish rather than assume: that no room or item can
deposit the player into the Antechamber directly, and the terminal-state
handling, since a potential non-zero at episode end biases the return
(`_phi_paths` already solved that for `PATHS_ZERO_PENALTY`). It is also a third
BFS per `door_version` on a path that is ~91% env-bound and was optimised in
#425, so it needs that PR's before/after throughput measurement and a cheap
early-out when no lever room is placed.

**Stated plainly so it is not oversold: this will not move the win rate on its
own.** A side door opens on 1.00% of fresh-save days, so a 0.125 potential gap
at that frequency perturbs a ~0.10 mean return by about 1%. It corrects a wrong
zero and makes self-sealing visibly bad; it creates almost no pressure toward
lever rooms, because the gradient only exists once the agent is already doing
the rare thing. Shaping the *approach* to a lever room is a separate and larger
question, and it has not been ruled on.

This entry moves into [`rewards.md`](rewards.md) when the work lands; the
retune it feeds is task 24.
