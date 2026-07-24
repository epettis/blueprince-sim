# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

blueprince-sim is a Python simulator of the room-drafting system in the game **Blue Prince**, reproducing the datamined v1.3 draft algorithm and probability tables for strategy testing and reinforcement learning. See `README.md` for the full mechanics writeup and `HANDOFF.md` for build history and data provenance.

## Commands

Tools live in the project virtualenv (`.venv/`) and are **not on the base PATH** — activate it first or they appear "not found":

```bash
source .venv/bin/activate          # do this before pytest / ruff / blueprince-*
```

- Install (editable): `uv pip install -e ".[dev]"` (or `pip install -e ".[dev]"`). Extras: `.[rl]` adds numpy + sb3-contrib + torch for training; `.[ingest]` adds requests.
- Tests: `pytest` (or `python -m pytest tests/ -q`).
- Single test: `pytest tests/test_placement.py::test_garage_placement`.
- Lint: `ruff check .` (line length 100). Keep it clean before committing.
- **Validate data (run after any edit to `data/*.json`): `python tools/validate_data.py`** — must report 0 errors, 0 warnings.
- Regenerate `data/rooms.json` from the raw dump + `tools/supplemental_rooms.json`: `python tools/ingest_sheet.py` (rebuilds the file, overwriting manual JSON edits — see caveat below).
- Play / evaluate: `blueprince-sim play --seed 42`; `blueprince-sim batch --episodes 5000 --policy greedy_rank`. Any `GameConfig` field can be overridden with `--set key=value` or a `--config file.yaml`.
- Train: `blueprince-train --checkpoint-dir runs/<name>` (continuous MaskablePPO, auto-resumes from `latest.zip`, SIGTERM-graceful).
- Evaluate a released model: `blueprince-train --evaluate 2000 --model models/<name>/model.zip` (`--model` overrides the default `<checkpoint-dir>/latest.zip`).
- Cut a release: `python tools/make_release.py --checkpoint-dir runs/<name> --name <n> --tag <n> --trained-with-sha $(git rev-parse HEAD) [--publish]`. Model bytes ship as a GitHub Release asset; only provenance (`models/<name>/MANIFEST.json` + `metrics.jsonl`) is committed. `runs/` is gitignored; `models/` is tracked. See `models/README.md`.

## Architecture

**`engine/game.py::Game` is the single API surface.** Both the Gymnasium env and the CLI drive the engine only through `Game` (`reset`, `open_doorways`, `open_door`, `choose`, `redraw`, `move`, etc.) — never by touching the sub-modules directly. A day is one episode on a 5×9 grid from the Entrance Hall (rank 1 center) to the Antechamber (rank 9 center).

**Drafting and moving are distinct.** `open_door` + `choose` *places* a room behind a doorway but does not enter it; you pay no step and gain none of its resources until you `move` in. This split is fundamental to both the reward structure and the action space.

**The engine is data-driven and pure-stdlib.** All room stats and probabilities live in `data/*.json`; `model.Registry.load()` parses them into immutable frozen `Room` dataclasses. Prefer changing behavior by editing data over editing code. Data files: `rooms.json` (room table), `weights.json` (rarity roll tables), `priority_draws.json`, `items.json`, `locks.json` (locked/security door tables). Every record carries `meta.source` + `meta.confidence` (`datamined > wiki > inferred > placeholder`).

**The draft pipeline** (one option slot at a time): `decks.py` builds 8 solitaire decks (4 rarities × free/gem) from the enabled pools and does the rank/slot/stage/Solarium-keyed rarity roll → `draft.py` runs the 4-attempt draw procedure, priority draws, and forced-Closet fallback → `placement.py` filters by legality → `rotation.py` rolls the floorplan orientation. `items.py` handles the luck/item system; `effects/` holds Tier-1 room effects; `locks.py` rolls locked/security doors on doorway *segments* (state in `GameState.door_state` keyed by `locks.segment_key`; opening a locked door costs a key, security doors ride the keycard/power/offline-mode system worked from Security and the Utility Closet); `rng.py` provides seeded **named substreams** (determinism given a seed is a tested invariant).

**Grid conventions (`engine/grid.py`) — load-bearing invariants:**
- Flat cell index `cell = (rank-1)*5 + col`; ranks 1–9, cols 0–4.
- Door masks are 4-bit: `N=1, E=2, S=4, W=8`; `OPPOSITE` maps each.
- `entry_dir` is the direction the player **moved** to reach a cell, so the drafted room needs a door on the **opposite** side (facing back). A doorway can never point into the outer wall — this alone forces 4-way rooms off edges and restricts corners to L-shapes/Dead Ends.
- **A "wing" is a single outer column**: West Wing = col 0, East Wing = col 4 (`is_west_wing`/`is_east_wing`). "Wing" and "outer wall/edge" are the same thing. Interior/center = cols 1–3.

**Placement conditions.** `Room.draft_conditions` is a list of string tags that **all** must hold (AND semantics), interpreted room-agnostically in `placement.py::satisfies_draft_conditions` (spatial/key gates), while pure door-geometry is handled by `legal_orientations`. To add or change a room's placement rule:
1. Set the tag(s) in `data/rooms.json` (apply to upgrade variants too when they inherit the base's rule).
2. Handle the tag in `satisfies_draft_conditions` (reusable primitives: `no_corner`, `not_on_wing`, `interior_only`, `no_north_on_wing`, `rank_gte_N`/`rank_lte_N`; or a dedicated named condition for coupled wing+rank+direction rules like `garage`).
3. Register the tag in `KNOWN_CONDITIONS` in `tools/validate_data.py` (unknown tags are permissive but flagged as warnings).
4. Add a `satisfies_draft_conditions` test in `tests/test_placement.py`.

**Config.** `config.py::GameConfig` is an immutable dataclass of every unlock/rule flag (studio additions, upgrade disks, veteran mode/day/stage gates, item-gated `satisfied_conditions`, compass flags). It is the only thing that changes what pools and rules are active.

**Env layer (`env/`)** wraps `Game`: `obs.py` encodes the Dict observation (per-cell room ids + door masks, position, resources, current options with N/E/S/W bits, phase), `actions.py` is the masked flat `Discrete` space, `rewards.py` holds pluggable sparse/shaped rewards. `rl/` is MaskablePPO training with explore/exploit rollout mixing (`mixed_policy.py`).

## Testing & data notes

- `tests/test_draft_stats.py` is a chi-square suite asserting the engine reproduces the datamined rarity distributions — treat failures there as evidence the draft math regressed, not as flaky tests.
- **Test observable behaviors, not data contents.** Don't write change-detector tests that read `data/*.json` values back through a lookup function (e.g. asserting a table entry equals the JSON number) — schema/range/referential checks belong in `tools/validate_data.py`. Assert what a player or agent can observe instead: "rank 1–3 doors are never locked", "a Corridor's doors are always open", not "the table says 25".
- `tools/ingest_sheet.py` regenerates `rooms.json` from `tools/raw/` + `tools/supplemental_rooms.json`; hand-edits to `rooms.json` that aren't reflected in those sources will be lost on re-ingest. The ingest condition map does not encode the finer wing/rank/direction rules, so those refinements live directly in the committed `rooms.json`.
- Keep `rooms.json` diffs minimal: it is written with 1-space indent and `ensure_ascii=True` (currency glyphs stay as `\uXXXX` escapes).

## Known gaps and deferred work

- **Seven wiki rooms are absent from the sim entirely** (not in the datamined sheet or `supplemental_rooms.json`) — each needs special behavior modeled, not just a shape/stat record, so they were deferred rather than stubbed. Add with full records (rarity, gem cost, effects, flags, pool) plus their behavior: Mechanarium (cross), Planetarium (dead_end), Lost & Found (corner), Treasure Trove (corner), Tunnel (straight), Closed Exhibit (t), Throne Room (t).
- **Chamber of Mirrors** is stored as a cross, but its four arms only connect after each door is entered from outside; that gated traversal is not modeled (see its `meta.layout_note`).
- Room layouts were audited against `blueprince.wiki.gg` Category:Room shapes; two datamined rooms that disagreed with the wiki are corrected via `LAYOUT_OVERRIDE` in `tools/ingest_sheet.py`. Ambiguous currency glyphs in the raw sheet are resolved by UTF-8 byte value (`0x94`=key, `0x92`=gem) in the ingest `GLYPH_MAP`.
- Broader modeling simplifications (Antechamber entry model, step costs, week boundaries, luck curve, redraw semantics, out-of-scope room effects) are catalogued in the README "Known simplifications & open questions" section.

## Workflow

Per the repo convention, don't commit to `main` directly — branch, then open a PR. Before committing: `python tools/validate_data.py`, `pytest`, and `ruff check .` should all be green.
