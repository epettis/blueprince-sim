"""Interactive REPL for playing a day by hand."""

from __future__ import annotations

from ..config import GameConfig
from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, E, N, S, W, neighbor, rank_of
from .render import render_grid, render_options, render_status

_DIR_KEYS = {"n": N, "e": E, "s": S, "w": W}


def play(cfg: GameConfig, seed: int) -> None:
    game = Game(cfg, seed=seed)
    print(f"Blue Prince drafting simulator - seed {seed}. "
          f"Reach the Antechamber (rank 9 center) before you run out of steps.")
    while game.phase is not Phase.TERMINAL:
        print()
        print(render_grid(game))
        print(render_status(game))
        if game.phase is Phase.NAVIGATE:
            st = game.state
            doors = game.open_doorways()
            moves = game.adjacent_moves()
            if not doors and not moves:
                game._check_termination()
                continue
            here = game.registry.rooms[st.grid[st.pos]].name
            print(f"You are in the {here} (rank {rank_of(st.pos)}).")
            if doors:
                print("Draft a doorway:")
                for i, (_cell, d) in enumerate(doors):
                    print(f"  [{i + 1}] draft through the {DIR_NAMES[d]} door")
            if moves:
                print("Move:")
                for d in moves:
                    nb = neighbor(st.pos, d)
                    room = game.registry.rooms[st.grid[nb]]
                    tag = "" if st.entered[nb] else "  (not yet entered)"
                    print(f"  [{DIR_NAMES[d].lower()}] go {DIR_NAMES[d]} into "
                          f"the {room.name}{tag}")
            if game.outer_draft_available():
                print("  [o] outer-room draft (West Path)")
            cmd = input("move/draft> ").strip().lower()
            if cmd == "q":
                return
            if cmd == "o" and game.outer_draft_available():
                game.open_outer_draft()
                continue
            if cmd in _DIR_KEYS:
                d = _DIR_KEYS[cmd]
                if d in moves:
                    game.move(d)
                else:
                    print("  ? no connected room that way")
                continue
            try:
                game.open_door(*doors[int(cmd) - 1])
            except (ValueError, IndexError):
                print("  ? enter a doorway number, a move letter (n/e/s/w), 'o', or 'q'")
        else:
            print("Draft options (glyph shows door directions; "
                  "you must choose one - no backing out):")
            print(render_options(game))
            p = game.state.pending
            extras = []
            if p.redraws_left > 0:
                extras.append(f"[r] free redraw ({p.redraws_left})")
            elif game.state.dice > 0:
                extras.append(f"[r] redraw with die ({game.state.dice})")
            elif game.state.study_placed and game.state.gems >= 1 and p.study_redraws_used < 8:
                extras.append("[r] Study redraw (1 gem)")
            if game.rotation_available():
                extras.append("[t] rotate options")
            if extras:
                print("  " + "   ".join(extras))
            cmd = input("choose> ").strip().lower()
            if cmd == "q":
                return
            if cmd == "t" and game.rotation_available():
                game.rotate_options()
                continue
            if cmd == "r":
                if p.redraws_left > 0:
                    game.redraw(RedrawKind.FREE)
                elif game.state.dice > 0:
                    game.redraw(RedrawKind.DIE)
                elif game.state.study_placed and game.state.gems >= 1:
                    game.redraw(RedrawKind.STUDY)
                else:
                    print("  no redraw available")
                continue
            try:
                slot = int(cmd) - 1
                opt = next(o for o in p.options if o.slot == slot)
                room = game.registry.rooms[opt.room_idx]
                if not game.affordable(room, opt):
                    print("  can't afford that")
                    continue
                game.choose(slot)
            except (ValueError, StopIteration):
                print("  ? enter an option number, 'r', or 'q'")
    print()
    print(render_grid(game))
    print(render_status(game))
    if game.success():
        print(f"*** You reached the Antechamber! ({game.rooms_placed} rooms, "
              f"{game.state.steps} steps left) ***")
    else:
        print(f"Day over: {game.termination_reason} "
              f"(deepest rank {game.deepest_rank}, {game.rooms_placed} rooms)")
