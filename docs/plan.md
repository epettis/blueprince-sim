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
  per-item effects). Design + every judgment call: `docs/special-items-design.md`;
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

## In flight (this branch)

1. **Security setpoint thrash guard**: the env must not allow changing the
   security level twice in a row (mask ids 190–192 when the previous applied
   action was one of them; a different action re-enables them). Motivation: runs
   with 861 actions (seed 1099560591) burning hundreds of steps toggling
   setpoints, killing learning throughput. Engine API unchanged — env-mask only.
   (Possible follow-up, not yet requested: the keycard power toggle, id 189, has
   the same free-toggle structure.)
2. **Observatory colors**: shops → obvious yellow, hallways → obvious orange
   (currently near-identical yellows in `app.js CAT_COLOR`); keep the
   `scepter-*` tint classes in `style.css` in sync.
3. **Observatory tiles**: spell out the full room name in the runs-view board
   (was 2-letter abbreviations), small wrapped text sized to the tile.

## Next (user-endorsed, not started)

- Coat Check / Moon Pendant item carry-over (extend `DayChain` + the
  `persistence` field already on every item record).
- Chest/trunk system (unblocks Sledge Hammer trunks, Car Keys, `blocked_on:
  trunks_not_modeled` records).
- Reward calibration from multi-day training stats (all shaping constants are
  deliberate knobs: `special_item_values`, `PATHS_*_PENALTY`, scepter bias).
- Larger deferred systems: Vault boxes, Parlor, candles/Torch, Antechamber
  levers, Sanctum; Repellent needs the multi-day wrapper's pool-removal support.

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
- Suite size at last green: 560 tests.
