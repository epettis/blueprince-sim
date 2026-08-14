# Development plan — special items era and beyond

Living plan for the orchestrated development effort (updated 2026-07-25). This file
exists so any orchestrator — including a different model (Opus) picking up the
session — can resume without re-derivation. A parallel copy of the workflow
conventions lives in the assistant's project memory
(`blueprince-orchestration-handoff`); this file is the in-repo source of truth.

## Where things stand

Merged, in order:

- **PR #17** — special items: all ~64 wiki items as data (`data/special_items.json`),
  `engine/special_items.py` (inventory, spawn model, digging, Lost & Found,
  per-item effects). Design + every judgment call: `docs/special-items-schema.md` and
  `docs/special-items-behaviour.md`;
  wiki facts: `docs/research/special-items-wiki.md`.
- **PR #18** — commerce: `engine/shops.py` + `data/shops.json` (all 8 shops, the
  Locksmith special-key roll, Electromagnet robbery), Trading Post TRADE GRAPH
  (per-tier chains fixed on entry, `trades_per_day` 20 bounds milking loops),
  Workshop fabrication + free component, real Kitchen menu + Dining Room main
  course (rank-8 gated), Royal Scepter activation, microchips, `Game.carryover()`.
- **PR #19** — RL wiring: `Discrete(241) → Discrete(270)` (buy/trade/fabricate/
  scepter/smash actions, move-to re-entry for shops/Workshop/Dining Room) and six
  obs keys (inventory, item_state, grid_dig, shop_stock, trade_offers, fabricate).
  Interface map: assistant memory `blueprince-obs-action-space`.
- **PR #20** — reward: held items valued by Trading Post tier
  (`items.json special_item_values`, tunable).
- **PR #21** — reward: path-preservation potential (`phi_paths` in shaped AND
  phased): ≥2 open routes to the Antechamber free, 1 → −0.15, 0 → −1.0. Fixes
  policies drafting resource dead-ends that seal the run.
- **PR #22** — multi-day loop: `env/multiday.py::DayChain` (200-day chains of
  single-day episodes, `carryover()` feeds each next day, wrap to day 1),
  `blueprince-train --multi-day N`, dashboard chain notes,
  `royal_scepter_found` defaults True (its unlock puzzle is unmodeled).
- **PR #23** — Observatory UX: fixed draft-options slot, scrollable full-history
  action log (pin-to-bottom only when at bottom), scepter-color board tint.

Training: the user runs `blueprince-train --checkpoint-dir runs/<name> --reward
phased --multi-day 200` themselves; never touch live trainer processes. Old
checkpoints (pre-#19) are interface-incompatible — fresh checkpoint dir required.

## Delivered since (stacked PRs, merge top-down)

- **#25 (MERGED)** — multi-day ITEM persistence: `end_of_day_carry` (permanent /
  until_used records, Coat Check storage, Moon Pendant's two-item draw), a working
  Repellent (7-day floorplan bans riding `DayChain` into `GameConfig.banned_rooms`,
  honored by deck building incl. upgrade variants). Key 8 is modeled as a
  guaranteed daily Gallery find, NOT a carried item (owner correction: unlocking it
  makes it appear in the Gallery every day; the sim assumes entered rooms' puzzles
  are solved, so unlock and find collapse into one guaranteed spawn).
- **#26** — containers: trunks (smash free with a hammer / 1 key), chests (key only,
  never smashable), lockers (free), the Garage car trunk (Upgrade Disk until it is
  spent, then pool draws). Actions 270/271,
  `grid_containers` obs plane, walk-to re-entry.
- **#27** — Vault deposit boxes (the four numbered keys; key stays but is spent for
  good via `used_vault_keys` across days) and Parlor boxes (Wind-up Keys, inferred
  loot table, per-cell cap). Actions 272/273, `item_state` 10 -> 12.
- **#28** — ignition + machines: Torch / Burning Glass light the Chapel, Tomb
  and the Trading Post fuse (Upgrade Disk + 40 gold);
  the Broken Lever installs on the Greenhouse machine (opens the Antechamber's
  rank-8 doorway segment, `segment_key(37, N) == segment_key(42, S)`) and the
  Casino slot. Actions 274/275.

Suite: 692 tests green at #28. Every catalogued item now either functions or is
blocked only on an explicitly out-of-scope area (Grounds, Sanctum, Orindian Ruins,
lore documents) — `blocked_on` on each record names which.

### Stacked-PR merge discipline (learned the hard way)

Retarget a child PR to `main` BEFORE deleting its merged base branch. Deleting
first CLOSES the child and it cannot be reopened while the base ref is missing;
recovery is push the old base sha back, `gh pr reopen`, `gh pr edit --base main`,
delete again.

## Next (user-endorsed, not started)

- Reward calibration from multi-day training stats (all shaping constants are
  deliberate knobs: `special_item_values`, `PATHS_*_PENALTY`, scepter bias).
- Sanctum: the 8 Sanctum Keys have sources and persist, but the Inner Sanctum
  itself (8 doors, the area behind them) is unmodeled — the largest remaining
  system and worth its own design pass rather than a rushed PR.
- Out-of-scope areas that keep a handful of items inert: Grounds, Orindian Ruins,
  Precipice, lore documents. (`diary_key` used to be listed here; it was removed
  from the item table outright on 2026-08-06 — see `docs/open_tasks.md` task 6.)
- Freezer thaw: excluded from the ignition targets because the wiki calls it
  temporary/daily, which the one-shot `lit_targets` model cannot express.

## Workflow (proven over PRs #17–#23)

- One `EnterWorktree` per PR; branch renamed `feat/<name>` before push; the user
  merges PRs; delete remote branches after merge.
- Tests from a worktree:
  `PYTHONPATH=src <main-checkout>/.venv/bin/python -m pytest tests/ -q`
  (venv lives in the main checkout). Ruff from the same venv. After any data
  edit: `python3 tools/validate_data.py` must report 0 errors, 0 warnings.
- Implementation is delegated to `general-purpose` agents on **Sonnet** with
  exact file allowlists and per-function specs; the orchestrator reviews every
  diff before committing (this has caught real bugs in most rounds: free
  showroom grants, stopwatch charge leak on affordability queries, trade-loop
  early death, container-buy mask crash, log scroll yank).
- Style rules now in CLAUDE.md: comment every dataclass member; bulleted or
  commented-code-block data structures in docs; match/case over long if/elif
  value dispatch.
- The suite grows with every PR, so any count written in this file is historical.
  Get the current one from `pytest tests/ -q`.

## Maintenance sharp edges

- `N_ACTIONS` is asserted in four test files; any action-space change updates all.
- `tests/test_macro_actions.py::test_masked_rollout_never_revisits_pointlessly`
  hand-enumerates the walk-to re-entry predicates — extend it whenever a new
  re-entry reason is added.
- `data/special_items.json` must round-trip exactly through
  `json.dumps(indent=1, ensure_ascii=True)`; hand-written inline arrays break that
  and churn the next programmatic rewrite.
