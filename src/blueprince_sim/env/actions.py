"""Flat action space with masking.

Layout (Discrete(196)):
  0..179   open door (draft only): cell (45) x direction (4: N,E,S,W) ->
           cell*4 + dir_index. Legal only for the current room's doorways;
           drafting costs no step, so it needs no step budget.
  180..182 choose option slot 0/1/2 (as-dealt orientation)
  183..185 choose option slot 0/1/2 (alternate orientation; only legal when
           GameConfig.orientation_choice is enabled and an alternate exists)
  186      redraw (engine picks the cheapest available source: free > die > study)
  187      reserved (formerly decline; opening a door now commits you to a draft)
  188      outer-room draft (walk the West Path; once per day, if unlocked)
  189..192 move one room N/E/S/W into the connected placed room (spends a
           step, enters it, grants its resources; entering the Antechamber wins)
  193      rotate the drawn floorplans to their next legal orientation
           (Ornate Compass held / Rotunda placed / Dovecote in hand;
           overrides the random roll)
  194..195 reserved (Tier-2 shop menu)
"""

from __future__ import annotations

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, DIRS, neighbor

N_ACTIONS = 196
OPEN_BASE, CHOOSE_BASE, ALT_BASE = 0, 180, 183
REDRAW_ACTION, OUTER_DRAFT_ACTION = 186, 188  # 187 reserved (was decline)
MOVE_BASE = 189  # 189..192: move N/E/S/W
ROTATE_ACTION = 193
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


def action_mask(game: Game) -> list[bool]:
    mask = [False] * N_ACTIONS
    if game.phase is Phase.NAVIGATE:
        st = game.state
        # Drafting is free (no step cost), so any current-room doorway is legal.
        for cell, d in game.open_doorways():
            mask[OPEN_BASE + cell * 4 + DIR_INDEX[d]] = True
        # Moving into a connected room costs one step.
        if st.steps >= 1:
            for d in game.adjacent_moves():
                mask[MOVE_BASE + DIR_INDEX[d]] = True
        if game.outer_draft_available():
            mask[OUTER_DRAFT_ACTION] = True
    elif game.phase is Phase.DRAFTING:
        pending = game.state.pending
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            if game.affordable(room, opt):
                mask[CHOOSE_BASE + opt.slot] = True
        if _redraw_kind(game) is not None:
            mask[REDRAW_ACTION] = True
        if game.rotation_available():
            mask[ROTATE_ACTION] = True
    return mask


def _redraw_kind(game: Game) -> RedrawKind | None:
    st = game.state
    pending = st.pending
    if pending is None or pending.target_cell == -1:
        return None  # outer-room drafts cannot be redrawn
    if pending.redraws_left > 0:
        return RedrawKind.FREE
    if st.dice >= 1:
        return RedrawKind.DIE
    if st.study_placed and st.gems >= 1 and pending.study_redraws_used < 8:
        return RedrawKind.STUDY
    return None


def apply_action(game: Game, action: int) -> None:
    if action < CHOOSE_BASE:
        cell, dir_idx = divmod(action, 4)
        game.open_door(cell, DIRS[dir_idx])
    elif action < ALT_BASE:
        game.choose(action - CHOOSE_BASE)
    elif action < REDRAW_ACTION:
        game.choose(action - ALT_BASE)  # alternate orientation: Tier-2 refinement
    elif action == REDRAW_ACTION:
        kind = _redraw_kind(game)
        assert kind is not None, "no redraw available"
        game.redraw(kind)
    elif action == OUTER_DRAFT_ACTION:
        game.open_outer_draft()
    elif MOVE_BASE <= action < MOVE_BASE + 4:
        game.move(DIRS[action - MOVE_BASE])
    elif action == ROTATE_ACTION:
        game.rotate_options()
    else:
        raise ValueError(f"unimplemented action {action}")


def _cell_name(cell: int) -> str:
    return f"r{cell // 5 + 1}c{cell % 5}"


def describe_action(game: Game, action: int) -> str:
    """Concise human-readable form of ``action`` in the CURRENT (pre-step) state."""
    if action < CHOOSE_BASE:
        cell, dir_idx = divmod(action, 4)
        return f"open door {DIR_NAMES[DIRS[dir_idx]]} @ {_cell_name(cell)}"
    if action < REDRAW_ACTION:
        slot = action - (CHOOSE_BASE if action < ALT_BASE else ALT_BASE)
        alt = " alt" if action >= ALT_BASE else ""
        pending = game.state.pending
        if pending is not None and slot < len(pending.options):
            opt = pending.options[slot]
            name = "???" if opt.hidden else game.registry.rooms[opt.room_idx].name
            return f"choose #{slot + 1}{alt} {name}"
        return f"choose #{slot + 1}{alt}"
    if action == REDRAW_ACTION:
        return "redraw"
    if action == OUTER_DRAFT_ACTION:
        return "outer draft"
    if MOVE_BASE <= action < MOVE_BASE + 4:
        d = DIRS[action - MOVE_BASE]
        target = neighbor(game.state.pos, d)
        idx = game.state.grid[target] if target >= 0 else -1
        into = f" -> {game.registry.rooms[idx].name}" if idx >= 0 else ""
        return f"move {DIR_NAMES[d]}{into}"
    if action == ROTATE_ACTION:
        return "rotate options"
    return f"action {action}"
