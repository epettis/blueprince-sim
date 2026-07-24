"""Interactive REPL for playing a day by hand."""

from __future__ import annotations

from ..config import GameConfig
from ..engine import locks
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
            # Off-grid: outer-area actions only
            if st.outer_loc > 0:
                loc_name = "inside the outer room" if st.outer_loc == 2 else "at the doorstep"
                print(f"You are {loc_name}.")
                garage_cell = game._garage_cell()
                inside_penalty = 1 if st.outer_loc == 2 else 0
                if (st.outer_loc == 1 and st.outer_room_drafted and not st.outer_room_entered
                        and st.steps >= game.cfg.outer_enter_cost):
                    print("  [e] enter the outer room")
                print(f"  [h] return to Entrance Hall "
                      f"({game.cfg.outer_path_entrance_cost + inside_penalty} steps)")
                if garage_cell >= 0 and game._breaker_on():
                    print(f"  [g] return via garage "
                          f"({game.cfg.outer_path_garage_cost + inside_penalty} steps)")
                cmd = input("outer> ").strip().lower()
                match cmd:
                    case "q":
                        return
                    case "e" if (st.outer_loc == 1 and st.outer_room_drafted
                                 and not st.outer_room_entered
                                 and st.steps >= game.cfg.outer_enter_cost):
                        game.enter_outer_room()
                    case "h":
                        game.return_from_outer("entrance_hall")
                    case "g" if garage_cell >= 0 and game._breaker_on():
                        game.return_from_outer("garage")
                    case _:
                        print("  ? invalid command")
                continue
            doors = game.open_doorways()
            moves = game.adjacent_moves()
            if not doors and not moves:
                game._check_termination()
                continue
            here = game.registry.rooms[st.grid[st.pos]].name
            print(f"You are in the {here} (rank {rank_of(st.pos)}).")
            if doors:
                print("Draft a doorway:")
                for i, (cell, d) in enumerate(doors):
                    state = game.door_state_of(cell, d)
                    note = ""
                    if state == locks.DOOR_LOCKED:
                        note = " (locked: 1 key)" if st.keys else " (locked: no key!)"
                    elif state == locks.DOOR_SECURITY:
                        note = (" (security door)" if game.security_openable()
                                else " (security door: sealed)")
                    print(f"  [{i + 1}] draft through the {DIR_NAMES[d]} door{note}")
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
            if game.can_toggle_keycard_power():
                flip = "off" if st.keycard_power_on else "on"
                print(f"  [p] breaker box: turn keycard power {flip}")
            if game.can_set_security_level():
                print(f"  [v <low|normal|high>] security terminal "
                      f"(level now {st.security_level})")
            frontier = game.frontier_doorways()
            afar = [fd for fd in frontier if fd[0] != st.pos]
            if afar:
                print(f"Elsewhere: {len(afar)} draftable doorway(s) - "
                      f"[d <cell> <n|e|s|w>] walk there and draft, [g <cell>] walk to a room")
            cmd = input("move/draft> ").strip().lower()
            if cmd == "q":
                return
            if cmd == "o" and game.outer_draft_available():
                result = game.open_outer_draft()
                if result is None:
                    continue  # walk ended the day
                continue
            if cmd == "p" and game.can_toggle_keycard_power():
                game.set_keycard_power(not st.keycard_power_on)
                continue
            if cmd.startswith("v ") and game.can_set_security_level():
                level = cmd.split(None, 1)[1]
                if level in ("low", "normal", "high"):
                    game.set_security_level(level)
                else:
                    print("  ? usage: v <low|normal|high>")
                continue
            if cmd in _DIR_KEYS:
                d = _DIR_KEYS[cmd]
                if d in moves:
                    game.move(d)
                else:
                    print("  ? no connected room that way")
                continue
            parts = cmd.split()
            if parts and parts[0] in ("g", "d"):
                dist = game.distance_map()
                try:
                    cell = int(parts[1])
                except (IndexError, ValueError):
                    cell = -1
                if not 0 <= cell < len(dist):
                    print("  ? usage: g <cell 0-44> | d <cell 0-44> <n|e|s|w>")
                elif parts[0] == "g":
                    if 0 < dist[cell] <= st.steps:
                        game.move_to(cell)
                    else:
                        print("  ? not walkable within your steps")
                else:
                    d = _DIR_KEYS.get(parts[2]) if len(parts) > 2 else None
                    if (d is not None and (cell, d) in frontier
                            and 0 <= dist[cell] <= st.steps - 1):
                        if game.door_state_of(cell, d) == locks.DOOR_LOCKED \
                                and st.keys < game.key_cost_map()[cell] + 1:
                            print("  ? that door is locked and you lack the keys")
                        elif not game.doorway_passable(cell, d):
                            print("  ? that security door is sealed")
                        else:
                            game.draft_from(cell, d)
                    else:
                        print("  ? no draftable doorway there within your steps")
                continue
            try:
                cell, d = doors[int(cmd) - 1]
            except (ValueError, IndexError):
                print("  ? enter a doorway number, a move letter (n/e/s/w), "
                      "'g/d <cell>', 'o', 'p', 'v', or 'q'")
                continue
            if game.doorway_passable(cell, d):
                game.open_door(cell, d)
            elif game.door_state_of(cell, d) == locks.DOOR_LOCKED:
                print("  ? that door is locked and you have no key")
            else:
                print("  ? that security door is sealed")
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
