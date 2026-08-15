# Process

How to work on this repo. Every rule here was paid for once; the incident that
bought it is kept beside it, because a lesson without its evidence is just an
assertion.

Nothing here is about Blue Prince. Game mechanics, owner rulings and modelling
decisions live in the topic design doc that owns the rule, or in a comment
beside the code it governs. Only rulings for work that is **not built yet**
wait in [`open_tasks.md`](open_tasks.md)'s decisions log.

Organised by failure class, not by chronology:

1. [Claims that decay](#claims-that-decay)
2. [Tests that stop testing](#tests-that-stop-testing)
3. [Measurement instruments](#measurement-instruments)
4. [Search that lies](#search-that-lies)
5. [Orchestration](#orchestration)

## Claims that decay

**A claim about the future needs an expiry check, or it becomes a false claim
about the present.** Nothing revisits a note when the condition it names
arrives. Eight item records each carried *"obtainable when PR2 adds shop
actions"*; all eight were already obtainable through a generic `shops.py::buy`
wired into the mask and dispatch. That is not eight mistakes, it is one missing
mechanism: prefer a check that fails when the condition is met over prose that
predicts it.

**A scope annotation is a claim with an expiry date, and only the scope change
can invalidate it.** `meta.effect_text` values reading "out of single-day
scope" suppressed seven rooms long after the sim grew multi-day support. An
annotation asserting something is out of scope must be re-checked whenever that
scope changes. Prefer a dated task entry over a scope claim buried in a data
record.

**A liveness check is not a necessity check.** An audit-exemption entry named a
`draft.py` branch that still existed, so its liveness guard passed forever --
while the room had separately gained a `room_hook` the audit could see for
itself, making the exemption dead for months. Any exemption, allowlist or
suppression list needs the *second* question -- "would the audit still flag
this without me?" -- or it accretes entries that are individually defensible
and collectively dead. Test each entry by removing it against real data; of
fifteen, exactly one was dead.

**A hardcoded count in a comment rots by construction.** Measured examples from
one sweep: "76 `suppress_luck` sites" (there were 82), "three-tab SPA" (four),
"the only dict-typed `GameConfig` field" (two). **Drop the count, do not
correct it** -- and note that replacing a rotting count with a rotting
enumeration is the same bug wearing different clothes.

**When you fix a blocker, grep for everything that cited it -- including the
change you just merged.** A `meta.blocked_on` string was true when written and
false four hours later, falsified by its own author's next PR, with the warning
fresh.

**"The note decayed" and "the guard was removed without reading why" are
different failures, and `git log -S` is the only way to tell them apart.** A
note recorded that making all eight Sanctum Keys tradeable *would breach the
8-offer cap*. It was true when written. A later, better-informed, wiki-driven
change set all eight to tier 5 and rewrote three tests without touching the
note it invalidated -- so the prophecy came true and was ignored, because the
person who made it true never read it.

**A false claim in this repo's own docs is not inert.** One sentence -- "the
wiki lists the Spiral as this key's only location" -- was inherited by a
research brief, a PR body and a ruling record, each restatement making it look
better established. The wiki lists three sources and puts a different one
first; there had never been a conflict to resolve. It was caught only when a
scoping pass ran the code instead of re-reading the file. **Verify a claim
against its source before building a brief on it, especially a claim this repo
asserts about the outside world.**

**A size estimate is a hypothesis, and it decays as the surrounding code
changes. Re-measure before picking, not after committing.** An item sized XS by
one audit was genuinely cheap that week; by the time it was picked up, its only
pickup path ran through a function deliberately carrying no `rng`, and the
"one side effect" had become a signature change across every call site.

**A task statement that names non-existent work is the same failure the task
exists to fix.** A comment-sweep task named three violations; two did not exist
on inspection. Record the correction where the claim lives rather than quietly
dropping it.

**A refactor plan written before the measurement should be re-checked against
it, not executed on faith.** Three steps of one seven-phase plan changed on
contact with the code, and the final step was cancelled outright once measured:
the premise that a registry makes implementation status derivable held for 8 of
54 items, and could never derive *why* something was blocked.

**A pattern asserted from N instances needs each instance verified, not the
pattern.** A report generalised one crash as "reproduces under default data too
at other seeds", with no other seed verified. Measured: 0 crashes in 600
default seeds and 0 in ~3020 seeds under the exact reported config, the named
seed included.

## Tests that stop testing

**A green suite is evidence about the tests, not only about the code.** When a
fix makes tests fail, the first question is which of these four shapes you are
looking at -- only the first is repaired by rebuilding a setup:

1. **Passing BECAUSE of the bug.** Three category-bias tests targeted gem-cost
   rooms from a rank/gem cell where the real table gives ~0%; they passed only
   because a draw-order defect over-delivered gem rooms at low rank. Their
   properties were true, their setups were not.
2. **A helper EXPLOITING the bug** to construct its scenario -- one trimmed a
   deck below another's count so a size-sort would take the branch it wanted.
3. **A helper DOCUMENTING the bug** as its reason for a workaround. A lock test
   set `keys = 5` and named the budget-check defect in its docstring; removing
   the crutch made nine pre-existing tests fail without the fix.
4. **A test ASSERTING the bug as correct** -- a trophy price test pinned the
   defective sale-day value as expected.

Variety 4 needs the assertion inverted; varieties 2 and 3 need the crutch
removed, which is what proves the bug was real. **A test that only passes under
a bug is not a test.**

**Do not fix a vacuous test by choosing a seed that passes.** A cap assertion
passed only because its one seed happened to yield four offers; against `HEAD`,
36 of 60 seeds exceeded the cap. Picking a luckier seed is how the test became
vacuous in the first place. Replace it with the property that is actually true,
sweep seeds, and **assert that at least one seed exercises the branch**, so it
can never again pass without testing anything.

**No expectation may be derived by calling the function under test, or by
reading the same data file the engine reads.** A test that recomputes its
expected value from `registry.item_rules["luck"]` — the identical dict
`items.py` reads — passes for any value of the constants it claims to pin, and
it was the only test of `expected_yields`. Hard-code the published percentage as
a literal and quote the source line in the docstring. Found twice in this repo
under different disguises, so it is the pattern to look for, not the file.

**A seed is not a scenario constructor.** Build the scenario deterministically.
Hunting a replacement seed after a change is seed-tuning in disguise and will
rot again at the next change to the same draw.

**A rule written N times needs an agreement test, not N careful edits.** One
"can this locked doorway be opened" rule lived in four places and had drifted
in three; the durable output was not the fix but a test pinning all four paths
against what the menu actually accepts.

**Stripping history out of a docstring can leave it passing the convention gate
while explaining nothing.** Where the history *was* the only justification, the
rewrite has to establish the real mechanism first. A green gate measuring the
wrong thing is the failure this repo keeps re-learning.

## Measurement instruments

**A defect found through a bespoke harness is a claim about the harness until
it reproduces through the real entry point. Reproduce first, brief second.** A
reported engine crash was driven by a hand-rolled "`cli/batch.py`-style episode
loop"; the first attempt to rebuild that loop crashed on *every* seed for a
trivial driver reason (`phase` lives on `Game`, not `GameState`). A bug in the
driver reads exactly like a bug in the engine.

**The instrument's own setup can be the whole finding.** The Showroom's stock
is populated by `on_enter_shop` -> `_roll_showroom` **when a shop room is
entered**, never on a fresh `Game`. A harness that inspected `state.shops.stock`
on a new game across 60 seeds read the empty key as "hard to find a stocked
seed", when the key is simply never populated until entry.
`tests/test_shops.py::_place_shop` is the correct setup: write grid/pos state
directly, then call `on_enter_shop`.

**Two setup traps specific to this engine, both of which have silently voided a
measurement.** `GameConfig()` defaults to `day = 20`, so anything claiming to
measure day 1 must pass `GameConfig(day=1)` explicitly. And `state.pending` is
`None` after `reset()` — the hand is dealt by `Game.open_door`, not by reset —
so a probe that inspects the pending draft on a fresh `Game` reads an empty
field as "no hand was dealt". One attempt to measure a draft defect failed on
both at once.

**The composition of the fixture sets the number you measure.** A divergence
rate of 17% came from a synthetic fixture that was 73.5% travel actions, whose
legality is nearly config-independent. Real recorded play is 27.8% draft /
29.1% choose; re-run with a human-like mix, the same detector fires 71.7% of
the time. Quote the mix with the rate.

**Split selected populations from random ones before quoting any rate.**
Best-of-window replay records are chosen by `(win, deepest_rank, rooms_placed)`,
so they over-represent exactly what they select on: mean deepest rank 7.94
against 2.84 for random records, and a bug present in 74% of the former and
0.7% of the latter. Use the random population as the behavioural baseline.

**A scripted, policy-free probe beats a trained checkpoint for answering
questions about the model.** One such probe measured 6,153 real grid crossings
in minutes, validated a fix at population scale, and retired a rebalancing
recommendation that would have cost a tuning cycle -- a question no checkpoint
could answer at all. The instrument matters more than the suspicion.

**Play the game through the real UI before committing compute.** Three
modelling bugs surfaced in a single recorded day of play, none of which any
amount of measurement against the sim could have found: every probe agrees with
the engine, because the engine is what it measures.

**An observation- or action-space change kills every checkpoint trained before
it, the moment it merges.** Batch space-affecting changes and restart
deliberately rather than merging them mid-run. Two runs have been discarded for
exactly this, one at 50,000 episodes and one at 122,500 -- both cheap because
they were killed early, and both expensive to kill later. The same reasoning
gives the standing rule **do not start a training run mid-audit**: room
behaviour changes what the policy learns.

**Do not check line endings with `grep -c $'\r'` under git-bash** -- it reads
these files as LF-only and will report a clean file that is not. Use a
byte-level check:

```bash
python -c "b=open(P,'rb').read(); print(b.replace(b'\r\n',b'').count(b'\n'))"
```

which must print `0`. Note also that `sed -i` silently rewrites the whole file
to LF.

## Search that lies

**Compare execution, not source.** When a refactor moves an RNG draw behind a
constant, the literal stops being greppable and a string search reports it as
*removed* rather than relocated. What settles it is dynamic: patch
`Rng.{choice,shuffle,chance,roll_weighted,randint}` to log every
`(method, label, result)`, drive a full seeded game against both trees, and
diff the logs. Byte-identical across four seeds, plus a state digest over five,
is the standard. This hazard has recurred in four distinct forms -- a tag
hidden behind a same-named local, RNG labels behind constants, behaviour behind
a registry, and draw labels behind an id constant -- and every time a string
search returned a confident wrong answer.

**Verify existence by execution, not by reading.** A feature scoped as unbuilt
had been shipping since the original system; the check that settled it was
three printed lines of inventory before and after entry, not a file read.

**`effects: []` does not mean inert.** Behaviour also lives in the room and
item registries (`effects/rooms/`, `item_provides`/`item_hook`) and in
guaranteed items. Anything reading `effects` to judge whether something is
implemented must consult all of those too -- the registry migrations
deliberately moved behaviour out of that array.

**Scan with the AST, not with grep, when the question is "does anything read
this?"** A grep-based liveness scan of effect tags was wrong in both
directions; the deletions it proposed included live tags whose params are read.

## Orchestration

**One implementation agent per working tree at a time.** Git branches share a
tree, so creating a second branch mid-flight silently moved the first agent's
uncommitted work onto it, and two agents edited side by side for ~20 minutes.
Nothing was lost only because the file sets happened to be disjoint -- luck,
not design. The real cost: one of the two never had a clean full-suite gate
until the work was separated. Read-only research agents are safe to run
alongside; implementers are not.

**N implementation agents run in N git worktrees.** The rule above bounds
agents per tree, not agents total. A `git worktree` is fully isolated and the
single `.venv` in the main checkout serves every tree, **provided
`PYTHONPATH=src` is set so the worktree's own `src` beats the editable
install** -- otherwise imports resolve to the main checkout. Verified by
mutation in both directions, with all gates green inside a worktree.
Parallelism is therefore a file-contention question, not a tooling one: check
whether the queued work shares `env/actions.py` or another hot file first.

**Write a ruling down the moment it is made, into the document that owns the
rule.** Decisions that live only in the conversation are lost to compaction,
and the cost of losing one is re-litigating something already settled. Record
the reasoning and the measurement that justified it, not just the outcome, and
say explicitly when a ruling overrides the wiki or reverses an earlier
assumption. **A correction recorded only in a PR body does not reach the file
people read** — one ruling stated the wrong rule for days because the
implementing agent found the error, fixed the code, and wrote the correction
only into its own PR description.

**An unwritten ruling is indistinguishable from an unverified claim.** A brief
relayed a decision the owner had given in conversation and never recorded. The
implementing agent went looking for it, found the docs asserting the opposite,
and reported the brief as unsupported — correctly, because from where it sat
there was no difference between a real ruling and an invented one. The cost is
not only the decision that might have been lost, but the doubt cast on every
other claim in the same brief.

**A prose answer to a multiple-choice question is a rejection of the frame.**
Twice in one session the owner wrote prose instead of picking an option, and
both times the options were reasonable and the *question* was what was wrong.
When that happens, the prose is the ruling, and the first thing to look for is
which presupposition it discards. The related offering defect: **a multi-select
that looks like a radio group silently converts "I picked the one I cared
about" into "I declined the rest".** Ask one decision per question.

**Put the comments-state-current-behaviour rule in every implementation
brief.** Agents narrate their reasoning into the code they write by default, so
it recurs unless it is stated up front. Comments, docstrings and test
docstrings describe current behaviour; the rationale, the rejected alternatives
and the measurement belong in the PR body.

Four exemptions, each of which a sweep has had to defend at least once:

- **`docs/` is exempt.** Design documents exist partly to record why a rule
  holds, which a comment may not.
- **A comment explaining a non-obvious constraint the code must still honour
  describes the present, even when it sounds historical** — that `rooms.json`
  round-trips at 1-space indent, or that `_CARRYOVER_KEYS` is sorted because
  Python randomises string hashing per process.
- **Real-game patch history is allowed in a data note**, even where it reads
  like code history. "Changed in Patch 1.04.5" is a fact about Blue Prince, not
  about this repo, and so is every quoted wiki mechanic ("will no longer have
  any effect") — the largest false-positive class in the last sweep, ~60
  near-misses examined and cleared.
- **Source-provenance stamps keep their dates.** "The wiki's Cargo Rooms table,
  fetched 2026-08-11" is the same kind of fact as `meta.source`, and the fetch
  date is what makes the claim auditable later. Every *other* dated reference
  loses its date: a reader needs to find the reasoning behind a surprising
  rule, not the day it was ruled.

The hard part of such a sweep is never the stripping — it is *Stripping history
out of a docstring* above. The sweep's own worst case: one test justified
itself entirely by an invented rule that had since been deleted, so the real
mechanism had to be established before the history could go.

**Keep an audit's progress bar in the tree it audits, not in a document.** The
room-fidelity audit creates `tests/rooms/test_<room_id>.py` as it reaches each
room — one file per room, never a wall of stubs up front, and no file at all for
a room with nothing to pin. The **absence** of a file is therefore a readable
record of what has not been audited yet, and it cannot drift from the work the
way a checklist can. The split also has to ship *first* and alone, because
per-room files are what make the later PRs genuinely disjoint; without it every
room fix collides in one shared test file and the audit serialises.

**Work lanes, not numbers.** A metric target set before triage will usually
price in work that does not exist at that price: a "drop below 70 findings"
goal turned out to need engine capability for 21 of 34 findings, with only ~10
reachable by data plus a room module. The lanes:

- **Lane A** -- behaviour that fits existing parametric tags or a room module.
  Disjoint files, so several agents run at once.
- **Lane B** -- anything needing a new shared primitive, action, item, or
  cross-day machinery. Touches shared files; runs serially.
- **Lane C** -- anything needing an owner ruling. Parked and batched.

**Lane-B work is queued without waiting for per-PR approval** -- built,
reviewed by the orchestrator, merged once the gates are green, with dependent
work stacked on the branch immediately. Three things this does *not* relax:
anything needing a ruling is still parked rather than guessed; every diff is
still reviewed before merge (that review has caught something in most rounds);
and the gates still bind -- tests, ruff, and `validate_data.py` at 0 errors and
0 warnings on every commit.

**A debt ratchet steers design, it does not merely measure it.** An item's take
action was built beside its siblings in `shops.py` rather than in
`special_items.py` because the second home would have broken the item-id
allowlist -- and the first was the correct call path anyway. The cap made the
wrong home fail loudly. Any such allowlist should start at today's count and
only shrink, and should fail in **both** directions, so a stale entry is as
loud as a new violation.
