# blueprince-sim

A Python simulator of **Blue Prince**'s room-drafting system, built for rapid
strategy testing and reinforcement learning. It implements the game's real
(datamined) drafting algorithm and probability tables so you can simulate
thousands of days per minute without launching the game.

- **Engine**: pure-stdlib implementation of the datamined draft procedure
  (~230 full episodes/sec, ~14k/min single-threaded).
- **Gymnasium env** (`BluePrince-v0`): masked flat action space, pluggable
  rewards — ready for MaskablePPO (sb3-contrib) or any masking-aware RL.
- **CLI**: interactive REPL to play a day by hand; batch Monte-Carlo mode to
  evaluate scripted policies with confidence intervals.
- **Data**: every room stat and probability lives in editable JSON under
  `src/blueprince_sim/data/`, annotated with source + confidence.

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"        # or: pip install -e ".[dev]"

# Play a day interactively
blueprince-sim play --seed 42

# Evaluate a policy over 5000 seeded days
blueprince-sim batch --episodes 5000 --policy greedy_rank

# Toggle unlocks (any GameConfig field)
blueprince-sim batch --episodes 2000 --policy economy \
    --set orchard_unlocked=true mine_unlocked=true outer_rooms_unlocked=true \
          studio_additions=solarium,classroom day=25

# RL environment
python - <<'PY'
import gymnasium, blueprince_sim
env = gymnasium.make("BluePrince-v0")
obs, info = env.reset(seed=0)
mask = info["action_mask"]          # or env.unwrapped.action_masks()
PY
```

Config can also come from YAML (`--config myrun.yaml`); keys = fields of
`blueprince_sim.config.GameConfig`.

## What is simulated

Each episode is one in-game day on the 5x9 grid: Entrance Hall (rank 1
center) to the Antechamber (rank 9 center). **Drafting and moving are
separate actions**: at a doorway of the room you are standing in you draft
1-of-3 rooms, which *places* a room behind that door but does not enter it —
you pay no step and gain none of its resources until you **move** in. Walking
into the Antechamber ends the day as a win; running out of steps or
dead-ending ends it as a loss.

The draft implements the decompiled v1.3 algorithm:

- **8 decks** (4 rarities x free/gem) built from the enabled pools; solitaire
  dealing — no room repeats until its deck depletes and reshuffles.
- Per option slot: **rarity roll** from the datamined weight tables (keyed by
  rank 1-9, slot 1 vs 2&3, game stage week1/week2/late, Solarium presence),
  then a uniform deal from that rarity's deck(s). **Slot 1 is always free.**
- **Four draw attempts** per slot, ending in a forced Closet.
- **Deck-size gates** (free >= 3; gem 5/5/4/4 once veteran/day-16/Room-46).
- **Priority draws** into slot 3 (Patio group 5% -> 50% with Greenhouse;
  Commissary/Observatory 13%; Classroom 3%).
- Placement filters: door-back rule, **doors can never face the outer wall**
  (so 4-way rooms never sit on an edge, corners take only L-shapes/Dead Ends,
  and a T against an edge is fixed), wing/corner draft conditions,
  cannot-draft-from-Library, gated rooms (Pool/Secret Garden/Room 8/...).
- **Orientation roll**: a floorplan with several legal orientations is rolled
  with datamined, south-door-biased weights that drift by day (e.g. a T needing
  a south door: 70/15/15 early -> 60/20/20 late). The **Compass** (`cfg.compass`)
  flips the bias toward north doors. Free rotation to any legal orientation is
  granted by the **Ornate Compass** (`cfg.ornate_compass`, every draft), the
  **Rotunda** (while placed), and the **Dovecote** (while drawn). See
  `engine/rotation.py`.
- **Redraws**: Study (1 gem, max 8/draft), Classroom (free = drafting-room
  count), Ivory Dice.
- **Resources**: steps, gems, keys, coins, dice; the luck system (start 10,
  max effect 29, self-balancing) drives extra item spawns.
- **Room effects** (Tier 1): resource grants, Solarium weight flip, Greenhouse
  bias, The Pool's injected rooms, Bunk Room double-bedroom, Nursery,
  red-room penalties (Weight Room, Gymnasium, Chapel, Archives), Shelter
  red-room negation, Hovel steps-for-gems (3:1), Tomb dead-end gold,
  Schoolhouse classroom flood, etc.

### Unlock toggles (GameConfig)

| Field | Effect |
|---|---|
| `orchard_unlocked` | +20 starting steps (50 -> 70) |
| `mine_unlocked` | +2 gems at day start (Gemstone Cavern) |
| `outer_rooms_unlocked` | 1/day West Path draft: pick 1 of 3 from the 8 outer rooms |
| `studio_additions` | set of the 8 Drafting Studio rooms added to the pool (incl. `solarium`, `classroom`) |
| `upgrade_disks` | upgrade-variant room ids that replace their base room |
| `veteran_mode`, `day`, `room46_reached` | stage selection + gem deck-size gates |
| `satisfied_conditions` | item-gated rooms: `breakfast`, `secret_garden_key`, `knight_chess_piece`, `room8_key` |
| `compass` | bias the orientation roll toward north-facing doors |
| `ornate_compass` | rotate-at-will (any legal orientation) on every draft |

## Data provenance

| File | Source | Confidence |
|---|---|---|
| `data/weights.json` | TFMurphy's decompiled v1.3 tables (Google Sheet `1DGozAX_yHmQqAvrWBegxNg5b92d5zigtPOshj_7FoZ8`), extracted verbatim 2026-07-20 | datamined |
| `data/rooms.json` (rooms 1-77 + upgrade variants) | same sheet's decompiled room table (`tools/raw/tfmurphy_room_table.md`); ambiguous currency glyphs resolved by byte inspection | datamined |
| `data/rooms.json` (red rooms, studio additions, outer rooms, gift shop) | `tools/supplemental_rooms.json`, wiki/community-sourced; rarity/cost/layout for red rooms are estimates | wiki / inferred |
| `data/priority_draws.json` | sheet constants block + wiki.gg Drafting/Advanced | datamined / wiki |
| `data/items.json` | wiki.gg Luck page; extra-item distribution is an estimate | wiki / inferred |

Every record carries `meta.source` and `meta.confidence`
(`datamined > wiki > inferred > placeholder`). To correct a value, edit the
data JSON (or regenerate: `python tools/ingest_sheet.py`, which rebuilds
`rooms.json` from the raw dump + `tools/supplemental_rooms.json`).
`python tools/validate_data.py` checks referential integrity.

## Verifying against the real game

1. `pytest` runs a chi-square suite (30k draws per table cell) proving the
   engine reproduces the datamined rarity distributions, plus placement,
   deck-semantics, determinism, and Gymnasium API tests.
2. To validate against your own copy of the game: record real drafts as
   `(rank, slot, rarity)` triples and compare frequencies against a
   same-stage simulation batch. Useful anchors: late-game slot 1 at rank 1
   is 91.8% commonplace; with a Solarium, slots 2-3 at rank 9 are
   10/20/50/20.

## Known simplifications & open questions

- **Antechamber entry**: modeled as pre-placed at rank 9 center with all
  doors usable; you win by **walking into** it (which costs the entry step),
  not merely by connecting a door — so you can fall one tile short. The real
  game's Antechamber door locks (keys/security) are not modeled.
- **Steps**: drafting a room is free; moving into a room costs 1 step (and is
  when that room's resources are granted). Starting steps 50 (community
  consensus, not datamined). No locked doors/keys-to-open-doors yet (keys are
  tracked but door locks are Tier 2).
- **Week boundaries**: day 1-7 / 8-14 / 15+ mapping to the sheet's
  Week 1 / Week 2 / late tables is inferred.
- **Orientation weights** (`engine/rotation.py`) are datamined for the South,
  West and East connecting-door cases (with their day columns); the North case
  is the published near-uniform 40/30/30 and the Compass column for North (and
  for the 50/50 North/South 2-way case) is unpublished, so it falls back to the
  base roll. The Compass (north bias) and Ornate Compass (rotate-at-will) are
  modeled as per-run flags rather than held items.
- **Redraws** redraw the whole 3-option hand (per-slot semantics unverified).
- **Luck curve** between 10 and 29 is linear (shape not documented); the
  extra-item type distribution (coins/key/gem/die) is an estimate.
- Rooms whose systems are out of scope (shop menus, dig spots/tools, Vault
  contents, cross-day "Tomorrow" effects, dartboard/parlor puzzles) have
  their draft presence and costs modeled but their effects reduced or
  no-op'd; see `meta.effect_text` in `rooms.json` for what the real room does.
- Red-room rarities/layouts and a few studio-addition costs are estimates
  (their wiki table is bot-blocked); marked `inferred` in data.

## Project layout

```
src/blueprince_sim/
  config.py          GameConfig (unlocks, stage, rule flags)
  data/              committed JSON datasets (see provenance above)
  engine/            pure-Python core: decks, draft, placement, effects, game
  env/               Gymnasium wrapper: obs encoding, masked actions, rewards
  cli/               play REPL, batch Monte-Carlo, policies, ASCII render
tools/               ingest + validation scripts, raw source dumps
tests/               chi-square stats, placement, decks, game, env API
```

## Continuous RL training (`blueprince-train`)

`pip install -e ".[rl]"` (numpy + sb3-contrib + torch), then:

```bash
# Run indefinitely: all unlocks, no room upgrades, checkpoint every 10,000 episodes
blueprince-train --checkpoint-dir runs/all-unlocks

# Stop gracefully at any time (finishes the current rollout, saves, exits 0):
kill <pid>            # the pid is printed at startup; Ctrl-C also works

# Restart later - resumes automatically from runs/all-unlocks/latest.zip:
blueprince-train --checkpoint-dir runs/all-unlocks

# Measure the current policy (deterministic, fresh seeds):
blueprince-train --checkpoint-dir runs/all-unlocks --evaluate 2000
```

What it does:

- **Algorithm**: MaskablePPO (sb3-contrib) over the masked `BluePrince-v0`
  env. The policy conditions on the full manor layout (room ids + door
  masks per cell), player position, resources (steps/gems/keys/coins/dice/
  luck/redraws), the current draft options - each with its four door
  directions exposed as separate N/E/S/W bits so orientation can drive the
  pick - and phase.
- **Scenario**: `all_unlocks_config()` - orchard (+20 steps), mine
  (+2 gems), outer rooms, all 8 studio additions; `upgrade_disks` empty.
- **Checkpointing**: every 10,000 completed episodes (`--checkpoint-every`),
  written atomically (temp file + rename) as `latest.zip` + `latest.json`
  (episode/timestep counters, rolling win rate). Every 5th checkpoint is
  also kept as a numbered snapshot (`--snapshot-every`, 0 disables).
- **Signal safety**: SIGINT/SIGTERM sets a flag; training stops at the next
  step boundary and saves. Maximum progress at risk = one PPO rollout
  (`n_envs x n_steps` env steps, ~2k steps ≈ seconds). A second signal
  force-exits.
- **Resume**: `latest.zip` restores weights + optimizer; `latest.json`
  restores the episode counter, so checkpoint cadence stays aligned.

Run it in the background on a desktop with any of:

```bash
nohup blueprince-train --checkpoint-dir runs/all-unlocks >> runs/train.log 2>&1 &
echo $! > runs/train.pid          # later: kill $(cat runs/train.pid)
```

or a user systemd unit (Linux) so it survives logouts and restarts cleanly:

```ini
# ~/.config/systemd/user/blueprince-train.service
[Unit]
Description=Blue Prince drafting policy training
[Service]
WorkingDirectory=%h/blueprince-sim
ExecStart=%h/blueprince-sim/.venv/bin/blueprince-train --checkpoint-dir %h/blueprince-sim/runs/all-unlocks
KillSignal=SIGTERM
TimeoutStopSec=120
Restart=on-failure
[Install]
WantedBy=default.target
```

`systemctl --user enable --now blueprince-train`; stop with
`systemctl --user stop blueprince-train` (sends SIGTERM -> graceful save).

Throughput on a modest CPU is ~1,100 env-steps/sec with 4 workers
(~50-60 episodes/sec), so a 10k-episode checkpoint lands every ~3 minutes
and a day of training is roughly 3-5M episodes. Expect the policy to need
millions of episodes to beat the scripted heuristics; track
`blueprince/win_rate_1k` in the logs (add `--tensorboard` for curves) and
compare periodically against `blueprince-sim batch --policy greedy_rank`
under the same config.

Tuning flags: `--n-envs` (parallel workers), `--n-steps` (rollout length -
also the progress-at-risk on stop), `--reward shaped|sparse` (shaped adds
rank-progress and resource terms; sparse is win-only), `--device` (default
cpu; the nets are tiny MLPs).

### Explore/exploit mixing

Rollout collection probabilistically mixes two behavior modes
(`rl/mixed_policy.py`):

- **Exploit** (`--exploit-prob`, default 0.9): sample the masked policy
  distribution at low temperature (`--exploit-temp` 0.5) - sharpened toward
  the best known action, softly enough to avoid brittleness.
- **Explore** (the rest): high temperature (`--explore-temp` 1.5) flattens
  the distribution so low-probability/low-confidence actions that still
  carry estimated value get real play, plus an `--explore-eps` (0.05)
  uniform floor over *legal* actions so even near-zero-probability moves
  occasionally get tried. Illegal actions stay at zero in both modes.

The mode is re-rolled **per decision** by default. A Blue Prince day is
50-70 decisions, so rolling explore/exploit *per episode* would make ~1 in 10
whole episodes a random walk that never reaches the Antechamber - drowning the
learning signal. Per-decision at 0.9 keeps each episode ~90% on-policy with a
light scatter of exploratory moves. `--mode-granularity episode` restores
coherent whole-episode exploration (best paired with a higher `--exploit-prob`).

With per-decision modes an episode can't be attributed to a single mode, so the
`win_rate_exploit_1k` / `win_rate_explore_1k` split is reported only under
`--mode-granularity episode`; `win_rate_1k` is always logged. `--evaluate`
remains deterministic argmax, unaffected by these settings.

Notes: with `--exploit-prob 1.0 --exploit-temp 1.0` the mechanism reduces
exactly to vanilla MaskablePPO. The stored log-probs are those of the
adjusted behavior distribution, so training is mildly off-policy relative to
the network's own distribution; PPO's ratio clipping bounds the bias (the
standard trade-off for explicit exploration mixing in PPO). Old checkpoints
made before this feature resume cleanly - the network is identical, only
rollout sampling differs.
