"""Flat action space with masking.

Layout (Discrete(196)):
  0..179   open door: cell (45) x direction (4: N,E,S,W) -> cell*4 + dir_index
  180..182 choose option slot 0/1/2 (as-dealt orientation)
  183..185 choose option slot 0/1/2 (alternate orientation; only legal when
           GameConfig.orientation_choice is enabled and an alternate exists)
  186      redraw (engine picks the cheapest available source: free > die > study)
  187      decline (back out of the draft; the hand persists on the doorway)
  188      outer-room draft (walk the West Path; once per day, if unlocked)
  189..195 reserved (Tier-2 shop menu)
"""

from __future__ import annotations

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIRS

N_ACTIONS = 196
OPEN_BASE, CHOOSE_BASE, ALT_BASE = 0, 180, 183
REDRAW_ACTION, DECLINE_ACTION, OUTER_DRAFT_ACTION = 186, 187, 188
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


def action_mask(game: Game) -> list[bool]:
    mask = [False] * N_ACTIONS
    if game.phase is Phase.NAVIGATE:
        st = game.state
        for cell, d in game.open_doorways():
            cost = game._path_cost(cell)
            if cost is not None and st.steps > cost:
                mask[OPEN_BASE + cell * 4 + DIR_INDEX[d]] = True
        if game.outer_draft_available():
            mask[OUTER_DRAFT_ACTION] = True
    elif game.phase is Phase.DRAFTING:
        pending = game.state.pending
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            if game.state.gems >= game._effective_cost(room, opt):
                mask[CHOOSE_BASE + opt.slot] = True
        if _redraw_kind(game) is not None:
            mask[REDRAW_ACTION] = True
        mask[DECLINE_ACTION] = True
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
        # Opening a doorway adjacent to the Antechamber is how the player
        # finally walks in: entering it is exposed as move, handled below.
    elif action < ALT_BASE:
        game.choose(action - CHOOSE_BASE)
    elif action < REDRAW_ACTION:
        game.choose(action - ALT_BASE)  # alternate orientation: Tier-2 refinement
    elif action == REDRAW_ACTION:
        kind = _redraw_kind(game)
        assert kind is not None, "no redraw available"
        game.redraw(kind)
    elif action == DECLINE_ACTION:
        game.decline()
    elif action == OUTER_DRAFT_ACTION:
        game.open_outer_draft()
    else:
        raise ValueError(f"unimplemented action {action}")
