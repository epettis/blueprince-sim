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

**What remains on this task is the reward calibration itself.** The fixture and
the north-door gate together explain why touring beat drafting; neither
calibrates `special_item_values`, `PATHS_ONE_PENALTY`/`PATHS_ZERO_PENALTY` or
the scepter bias. Those need statistics from a run that actually plays the
game, which `runs/freshsave-v1` is now generating.

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

## Decisions log

Every entry here is held for one reason only: **it specifies work that is not
built yet.** Each one leaves the log the day its work lands.


Everything each entry says about *shipped* behaviour is already stated in the
doc that owns it; when the remaining work lands, the entry goes.

The log is empty: the retrain it was holding has started
(`runs/freshsave-v1`, see task 24), and every other ruling recorded here has
reached the doc that owns its rule.
