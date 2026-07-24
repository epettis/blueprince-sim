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
  189      toggle the keycard power (standing at the Utility Closet breaker)
  190..192 set security level low/normal/high (standing at the Security
           terminal; the current level is masked out as a no-op)
  193      rotate the drawn floorplans to their next legal orientation
           (Ornate Compass held / Rotunda placed / Dovecote in hand;
           overrides the random roll)
  194      return to Entrance Hall (from outer area doorstep or inside)
  195      return via garage (from outer area; requires Utility Closet breaker)
  196..240 walk to cell (45): shortest connected path into an unentered
           reachable room (spends steps, first entry grants its resources),
           into the Antechamber (wins), or back into the Utility Closet /
           Security to work their switches
"""

from __future__ import annotations

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, DIRS, N_CELLS
from ..engine.locks import DOOR_LOCKED, DOOR_SECURITY, SECURITY_LEVELS

N_ACTIONS = 241
OPEN_BASE, CHOOSE_BASE, ALT_BASE = 0, 180, 183
REDRAW_ACTION, OUTER_DRAFT_ACTION = 186, 188
ENTER_OUTER_ACTION = 187   # enter outer room from doorstep
TOGGLE_POWER_ACTION = 189  # flip the Utility Closet "Keycard Entry" breaker
SET_LEVEL_BASE = 190       # 190..192: set security level low/normal/high
ROTATE_ACTION = 193
RETURN_EH_ACTION = 194     # return to Entrance Hall from outer area
RETURN_GARAGE_ACTION = 195 # return via garage from outer area (breaker-gated)
MOVE_TO_BASE = 196  # 196..240: walk to cell
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


def action_mask(game: Game) -> list[bool]:
    """Legality mask over the flat action space for the current phase.

    NAVIGATE off-grid (``outer_loc > 0``) permits only outer-area actions.
    On-grid NAVIGATE permits frontier drafts that arrive with a step (and,
    behind locked doors, a key) to spare, walks to unentered rooms and the
    control rooms, and the outer-draft/switch actions. DRAFTING permits
    affordable slots plus redraw/rotate when available. TERMINAL masks
    everything off.
    """
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
            key_cost = game.key_cost_map()
            # Draft any reachable, openable frontier doorway; arriving must
            # leave >= 1 step (so the drafted room can still be entered) and,
            # for locked doorways, a key beyond those the walk itself spends.
            for cell, d in game.frontier_doorways():
                if not 0 <= dist[cell] <= st.steps - 1:
                    continue
                seg = game.door_state_of(cell, d)
                if seg == DOOR_LOCKED and st.keys < key_cost[cell] + 1:
                    continue
                if seg == DOOR_SECURITY and not game.security_openable():
                    continue
                mask[OPEN_BASE + cell * 4 + DIR_INDEX[d]] = True
            # Walk to an unentered room (first entry grants its resources), the
            # Antechamber (never marked entered while the game is live), or a
            # control room (Utility Closet / Security) to work its switches.
            control_cells = set()
            if game.cfg.door_locks:
                control_cells = {c for c in (game.room_cells.get("utility_closet", -1),
                                             game.room_cells.get("security", -1))
                                 if c >= 0}
            for cell in range(N_CELLS):
                if 0 < dist[cell] <= st.steps and (not st.entered[cell]
                                                   or cell in control_cells):
                    mask[MOVE_TO_BASE + cell] = True
            if game.outer_draft_available():
                mask[OUTER_DRAFT_ACTION] = True
            if game.can_toggle_keycard_power():
                mask[TOGGLE_POWER_ACTION] = True
            if game.can_set_security_level():
                for i, level in enumerate(SECURITY_LEVELS):
                    if level != st.security_level:
                        mask[SET_LEVEL_BASE + i] = True
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
    """Cheapest redraw source available right now (free > die > study), or None.

    Outer-room drafts (``pending.target_cell == -1``) can never be redrawn;
    the Study source costs a gem and is capped at 8 uses per hand.
    """
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
    """Execute one flat action id against the Game API.

    Assumes the action is legal per :func:`action_mask`; the env checks the
    mask first and turns illegal actions into penalized no-ops instead.
    """
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
    elif action == TOGGLE_POWER_ACTION:
        game.set_keycard_power(not game.state.keycard_power_on)
    elif SET_LEVEL_BASE <= action < SET_LEVEL_BASE + len(SECURITY_LEVELS):
        game.set_security_level(SECURITY_LEVELS[action - SET_LEVEL_BASE])
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
    if action == TOGGLE_POWER_ACTION:
        state = "off" if game.state.keycard_power_on else "on"
        return f"turn keycard power {state}"
    if SET_LEVEL_BASE <= action < SET_LEVEL_BASE + len(SECURITY_LEVELS):
        return f"set security level {SECURITY_LEVELS[action - SET_LEVEL_BASE]}"
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
