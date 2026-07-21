# Session Handoff — blueprince-sim

Context file for continuing work in a fresh Claude Code session (or on a
desktop). Written 2026-07-20 at the end of the original build session.

## What this project is

A Python simulator of **Blue Prince**'s room-drafting system using real
(datamined) probabilities, built for strategy testing and reinforcement
learning. Owner: Eddie Pettis (github.com/epettis). Repo:
`epettis/blueprince-sim` (private).

- `src/blueprince_sim/engine/` — pure-stdlib engine implementing the
  decompiled v1.3 drafting algorithm: 8 decks (rarity x free/gem, solitaire
  dealing), rarity roll keyed by rank/slot/stage/Solarium, 4-attempt
  procedure with forced-Closet fallback, priority draws, placement rules
  (door masks, wings, corners), Tier-1 room effects, luck/item system.
  ~230 episodes/sec.
- `src/blueprince_sim/env/` — Gymnasium `BluePrince-v0`: Dict obs (grid room
  ids + door masks, position, resources, current options, phase), flat
  `Discrete(196)` masked actions (sb3-contrib MaskablePPO compatible),
  pluggable sparse/shaped rewards.
- `src/blueprince_sim/cli/` — `blueprince-sim play` (REPL) and
  `blueprince-sim batch` (Monte-Carlo policy evaluation, Wilson CIs).
- `src/blueprince_sim/rl/` — `blueprince-train`: continuous MaskablePPO,
  atomic checkpoints every 10k episodes, SIGTERM-graceful stop, auto-resume
  from `latest.zip`, explore/exploit mixed sampling (70% exploit temp 0.5 /
  30% explore temp 1.5 + 5% legal-action floor, per-episode modes,
  per-mode win-rate telemetry), `--evaluate N` mode.
- `tools/` — data ingestion (`ingest_sheet.py` + `supplemental_rooms.json`
  -> `data/rooms.json`), `validate_data.py`, `make_dashboard.py` (SVG
  win-rate dashboard from `runs/metrics.jsonl`).
- `tests/` — 59 passing (chi-square draw verification vs datamined tables,
  placement, decks, determinism, env API, mixed-policy sampling).

## Data provenance (the load-bearing research)

- **Rarity weight tables + room table (rooms 1-77 + upgrade variants):**
  TFMurphy's decompiled v1.3 Google Sheet
  (`docs.google.com/spreadsheets/d/1DGozAX_yHmQqAvrWBegxNg5b92d5zigtPOshj_7FoZ8`),
  extracted verbatim; raw dump in `tools/raw/tfmurphy_room_table.md`.
  Ambiguous key/gem currency glyphs resolved by UTF-8 byte inspection
  (0x94=key, 0x92=gem) — documented in the ingest script's GLYPH_MAP.
- **Red Rooms / Studio Additions / Outer Rooms / Gift Shop:** absent from
  the sheet; wiki/community-sourced in `tools/supplemental_rooms.json`.
  Red-room rarity/layout are flagged `inferred` estimates.
- Every record carries `meta.source` + `meta.confidence`
  (datamined > wiki > inferred). Fix data via the files, rerun
  `tools/ingest_sheet.py`, check with `tools/validate_data.py`.
- Known simplifications & open questions: README "Known simplifications"
  section (Antechamber entry model, step costs, week boundaries, luck curve,
  redraw semantics).

## Training state (cloud run, stopped)

- Final checkpoint: **281,096 episodes / 9,386,192 timesteps**
  (stopped gracefully 2026-07-20 ~17:44 UTC).
- Config: all unlocks (orchard +20 steps, mine +2 gems, outer rooms, all 8
  studio additions), **no upgrade disks**, day 20 (late tables), shaped
  reward, 70/30 explore-exploit.
- Learning signal so far: win rate still ~0.1-0.2% (noise level; heuristic
  baseline `greedy_rank` is ~7.9% default / ~16% all-unlocks), BUT mean
  episode length grew 21 -> 74 decisions and mean reward +43% — the policy
  is learning depth; wins need more compute (expect millions of episodes).
- Checkpoint + snapshots (50k/100k/150k/200k/255k) + metrics history +
  train log are in **`blueprince-checkpoint-281k.tar.gz`** (sent as a chat
  attachment; unpack into `runs/`).
- Resume anywhere:
  `pip install -e ".[rl]" && blueprince-train --checkpoint-dir runs/all-unlocks`
  (auto-resumes; `kill <pid>` stops gracefully with a final checkpoint).

## Dashboard

Live artifact (hourly-updated during the run, currently frozen at stop):
`https://claude.ai/code/artifact/c7c74b08-5603-47f4-846d-e9d560ac0467`.
Regenerate with `python tools/make_dashboard.py` (reads
`runs/metrics.jsonl`); republishing the same file path from the ORIGINAL
conversation keeps that URL — from a new conversation, pass the URL as the
Artifact tool's `url` parameter to update it in place.

## Immediate tasks for the new session

The original session could not push (repo access is fixed at session
creation; it predated the repo). The full history lives in
**`blueprince-sim.bundle`** (chat attachment; tip `d27413b`, signed,
rebased on the repo's `Initial commit`). In a session created WITH
`epettis/blueprince-sim` connected:

1. `git fetch <path-to-uploaded-bundle> main:claude/initial-simulator`
   (or clone the bundle and push), then
   `git push -u origin claude/initial-simulator`.
2. Open a PR against `main` titled "Blue Prince drafting simulator" for
   Eddie's review — **do not merge**.
3. Create release `v0.1.0` ("281k-episode checkpoint") and attach
   `blueprince-checkpoint-281k.tar.gz` as the release artifact.
4. Optional next work items (discussed, not started): Tier-2 effects
   (shops, dynamic gem costs, locked doors/keys), category-bias hooks
   (Furnace/King/constellations), datamine cross-check of red-room
   rarities, longer training + `--evaluate 2000` comparison vs
   `greedy_rank`, real-game validation protocol (README).

## Operational gotchas learned this session

- Cloud containers get reclaimed during idle periods: background processes
  die (SIGKILL, no graceful handler), disk survives. The trainer's atomic
  checkpoint + auto-resume design absorbs this (~3-4 min max loss); restart
  it on the kill notification.
- `docs.google.com` and `blueprince.wiki.gg` are egress-blocked from the
  sandbox (403); GitHub is allowed. The wiki tables were only reachable via
  WebSearch summaries; the sheet was read via a Google Drive connector.
- Local git signature verification shows false "Unverified"/bad: git
  verifies through the same `/tmp/code-sign` shim it signs with, which
  doesn't implement verify. Signatures were confirmed valid by independent
  ed25519 verification of the SSHSIG payload.
- Torch: use `--device cpu` (default) — CUDA probing on GPU-less
  containers can hang model init for minutes.
