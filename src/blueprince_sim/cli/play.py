"""Interactive REPL for playing a day by hand."""

from __future__ import annotations

from ..config import GameConfig
from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, rank_of, col_of
from .render import render_grid, render_options, render_status


def play(cfg: GameConfig, seed: int) -> None:
    game = Game(cfg, seed=seed)
    print(f"Blue Prince drafting simulator - seed {seed}. "
          f"Reach the Antechamber (rank 9 center) before you run out of steps.")
    while game.phase is not Phase.TERMINAL:
        print()
        print(render_grid(game))
        print(render_status(game))
        if game.phase is Phase.NAVIGATE:
            doors = game.open_doorways()
            if not doors:
                game._check_termination()
                continue
            print("Doorways:")
            for i, (cell, d) in enumerate(doors):
                print(f"  [{i + 1}] rank {rank_of(cell)}, col {col_of(cell) + 1}, "
                      f"{DIR_NAMES[d]} door "
                      f"({game.registry.rooms[game.state.grid[cell]].name})")
            if game.outer_draft_available():
                print("  [o] outer-room draft (West Path)")
            cmd = input("open> ").strip().lower()
            if cmd == "q":
                return
            if cmd == "o" and game.outer_draft_available():
                game.open_outer_draft()
                continue
            try:
                game.open_door(*doors[int(cmd) - 1])
            except (ValueError, IndexError):
                print("  ? enter a doorway number, 'o', or 'q'")
        else:
            print("Draft options:")
            print(render_options(game))
            p = game.state.pending
            extras = ["[d] decline"]
            if p.redraws_left > 0:
                extras.append(f"[r] free redraw ({p.redraws_left})")
            elif game.state.dice > 0:
                extras.append(f"[r] redraw with die ({game.state.dice})")
            elif game.state.study_placed and game.state.gems >= 1 and p.study_redraws_used < 8:
                extras.append("[r] Study redraw (1 gem)")
            print("  " + "   ".join(extras))
            cmd = input("choose> ").strip().lower()
            if cmd == "q":
                return
            if cmd == "d":
                game.decline()
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
                if game.state.gems < game._effective_cost(room, opt):
                    print("  can't afford that")
                    continue
                game.choose(slot)
            except (ValueError, StopIteration):
                print("  ? enter an option number, 'r', 'd', or 'q'")
    print()
    print(render_grid(game))
    print(render_status(game))
    if game.success():
        print(f"*** You reached the Antechamber! ({game.rooms_placed} rooms, "
              f"{game.state.steps} steps left) ***")
    else:
        print(f"Day over: {game.termination_reason} "
              f"(deepest rank {game.deepest_rank}, {game.rooms_placed} rooms)")
