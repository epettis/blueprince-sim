"""Flat action space with masking.

Navigation is macro-based: the agent picks a destination (a frontier doorway
to draft, or a room to enter) and the engine walks the shortest connected
path, paying the normal one-step-per-room cost. Re-entering rooms grants
nothing, so free-form single-tile moves were retired.

Layout (Discrete(241)):
  0..179   draft at doorway: cell (45) x direction (4: N,E,S,W) ->
           cell*4 + dir_index. Walks to the room first if needed. Legal for
           every frontier doorway reachable with at least one step to spare
           on arrival (the drafted room must still be enterable).
  180..182 choose option slot 0/1/2 (as-dealt orientation)
  183..185 choose option slot 0/1/2 (alternate orientation; only legal when
           GameConfig.orientation_choice is enabled and an alternate exists)
  186      redraw (engine picks the cheapest available source: free > die > study)
  187      enter outer room (from doorstep; fires ON_ENTER once per day)
  188      outer-room draft (walk the West Path; once per day, if unlocked)
  189..192 retired (were single-tile moves N/E/S/W; see 196..240)
  193      rotate the drawn floorplans to their next legal orientation
           (Ornate Compass held / Rotunda placed / Dovecote in hand;
           overrides the random roll)
  194      return to Entrance Hall (from outer area doorstep or inside)
  195      return via garage (from outer area; requires Utility Closet breaker)
  196..240 walk to cell (45): shortest connected path into an unentered
           reachable room (spends steps, first entry grants its resources)
           or into the Antechamber (wins)
"""

from __future__ import annotations

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, DIRS, N_CELLS

N_ACTIONS = 241
OPEN_BASE, CHOOSE_BASE, ALT_BASE = 0, 180, 183
REDRAW_ACTION, OUTER_DRAFT_ACTION = 186, 188
ENTER_OUTER_ACTION = 187   # enter outer room from doorstep
MOVE_BASE = 189  # 189..192: retired single-tile moves (never legal)
ROTATE_ACTION = 193
RETURN_EH_ACTION = 194     # return to Entrance Hall from outer area
RETURN_GARAGE_ACTION = 195 # return via garage from outer area (breaker-gated)
MOVE_TO_BASE = 196  # 196..240: walk to cell
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


def action_mask(game: Game) -> list[bool]:
    mask = [False] * N_ACTIONS
    if game.phase is Phase.NAVIGATE:
        st = game.state
        if st.outer_loc > 0:
            # Off-grid: only outer-area actions are legal
            inside_penalty = 1 if st.outer_loc == 2 else 0
            # Enter outer room (only from doorstep, if drafted but not entered)
            if (st.outer_loc == 1 and st.outer_room_drafted and not st.outer_room_entered
                    and st.steps >= game.cfg.outer_enter_cost):
                mask[ENTER_OUTER_ACTION] = True
            # Return to EH
            if st.steps >= game.cfg.outer_path_entrance_cost + inside_penalty:
                mask[RETURN_EH_ACTION] = True
            # Return via garage
            garage_cell = game._garage_cell()
            if (garage_cell >= 0 and game._breaker_on()
                    and st.steps >= game.cfg.outer_path_garage_cost + inside_penalty):
                mask[RETURN_GARAGE_ACTION] = True
        else:
            dist = game.distance_map()
            # Draft any reachable frontier doorway; arriving must leave >= 1 step
            # so the drafted room can still be entered.
            for cell, d in game.frontier_doorways():
                if 0 <= dist[cell] <= st.steps - 1:
                    mask[OPEN_BASE + cell * 4 + DIR_INDEX[d]] = True
            # Walk to an unentered room (first entry grants its resources) or the
            # Antechamber (never marked entered while the game is live).
            for cell in range(N_CELLS):
                if 0 < dist[cell] <= st.steps and not st.entered[cell]:
                    mask[MOVE_TO_BASE + cell] = True
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
        game.draft_from(cell, DIRS[dir_idx])
    elif action < ALT_BASE:
        game.choose(action - CHOOSE_BASE)
    elif action < REDRAW_ACTION:
        game.choose(action - ALT_BASE)  # alternate orientation: Tier-2 refinement
    elif action == REDRAW_ACTION:
        kind = _redraw_kind(game)
        assert kind is not None, "no redraw available"
        game.redraw(kind)
    elif action == ENTER_OUTER_ACTION:
        game.enter_outer_room()
    elif action == OUTER_DRAFT_ACTION:
        game.open_outer_draft()
    elif action == ROTATE_ACTION:
        game.rotate_options()
    elif action == RETURN_EH_ACTION:
        game.return_from_outer("entrance_hall")
    elif action == RETURN_GARAGE_ACTION:
        game.return_from_outer("garage")
    elif MOVE_TO_BASE <= action < MOVE_TO_BASE + N_CELLS:
        game.move_to(action - MOVE_TO_BASE)
    else:
        raise ValueError(f"unimplemented action {action}")


def _cell_name(cell: int) -> str:
    return f"r{cell // 5 + 1}c{cell % 5}"


def describe_action(game: Game, action: int) -> str:
    """Concise human-readable form of ``action`` in the CURRENT (pre-step) state."""
    if action < CHOOSE_BASE:
        cell, dir_idx = divmod(action, 4)
        return f"draft {DIR_NAMES[DIRS[dir_idx]]} door @ {_cell_name(cell)}"
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
    if action == ENTER_OUTER_ACTION:
        return "enter outer room"
    if action == OUTER_DRAFT_ACTION:
        return "outer draft"
    if action == ROTATE_ACTION:
        return "rotate options"
    if action == RETURN_EH_ACTION:
        return "return to Entrance Hall"
    if action == RETURN_GARAGE_ACTION:
        return "return via garage"
    if MOVE_TO_BASE <= action < MOVE_TO_BASE + N_CELLS:
        cell = action - MOVE_TO_BASE
        idx = game.state.grid[cell]
        into = f" -> {game.registry.rooms[idx].name}" if idx >= 0 else ""
        return f"go to {_cell_name(cell)}{into}"
    return f"action {action}"
