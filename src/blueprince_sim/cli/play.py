"""Interactive REPL for playing a day by hand."""

from __future__ import annotations

from functools import partial

from ..config import GameConfig
from ..engine import locks
from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, E, N, S, W, neighbor, rank_of
from .render import render_grid, render_options, render_status

_DIR_KEYS = {"n": N, "e": E, "s": S, "w": W}


def _in_place_label(game: Game, action_id: str, do) -> str:
    """Readable menu text for one ``Game._in_place_actions()`` entry.

    ``do`` is either a bound ``Game`` method or a ``functools.partial`` around
    one; the partial's first positional arg is whichever index/id the action
    needs to disambiguate (which constellation, which shop row, which
    fabrication output, which sigil realm) -- pulled out here rather than
    re-derived, so a label can never name the wrong option.
    """
    arg = do.args[0] if isinstance(do, partial) and do.args else None
    if action_id == "open_container":
        return "open a container here"
    if action_id == "open_car_trunk":
        return "open the Garage car trunk"
    if action_id == "open_vault_box":
        return "open the matching Vault deposit box"
    if action_id == "install_lever":
        return "install the Broken Lever here"
    if action_id == "smash_vase":
        return "smash the Entrance Hall vase"
    if action_id == "spread_gold":
        return "Office terminal: Spread Gold"
    if action_id == "run_payroll":
        return "Office terminal: Run Payroll"
    if action_id == "view_night_sky":
        return "look at the night sky"
    if action_id == "activate_constellation":
        record = game.registry.constellations.records[arg]
        return f"activate the {record.name} constellation ({record.stars} star(s))"
    if action_id == "use_telescope_planetarium":
        return "use the Telescope in the Planetarium"
    if action_id == "take_grotto_chip":
        return "take the Grotto pedestal microchip"
    if action_id == "light":
        return "light the ignition target here"
    if action_id == "open_sigil_door":
        return f"open the {arg} sigil door with a Sanctum Key"
    if action_id == "buy":
        stock = game.shop_stock() or []
        if 0 <= arg < len(stock):
            entry = stock[arg]
            return f"buy {entry['id']} ({entry['price']} coin(s))"
        return "buy"
    if action_id == "fabricate":
        return f"fabricate {arg} at the Workshop bench"
    if action_id == "start_setup":
        return "operate the Laboratory terminal (Experimental Setup)"
    return action_id


def play(cfg: GameConfig, seed: int) -> None:
    """Run the interactive REPL for one day, printing the grid and prompting each decision.

    NAVIGATE offers moves, doorway drafts (numbered), far drafts (``d <cell> <dir>``),
    walks (``g <cell>``), in-place actions (``x <n>`` -- containers, shops, the
    Office/Workshop/Sanctum/night-sky/Laboratory terminals, anything
    :meth:`Game._in_place_actions` counts as work left with no walk needed),
    outer-area actions, and the security switches; EXPERIMENT_PENDING (entered
    by starting a Laboratory setup) offers the trigger then the effect;
    DRAFTING offers the option slots plus redraw/rotate. ``q`` at any prompt
    abandons the day. Returns after printing the end-of-day summary (win or
    termination reason).
    """
    game = Game(cfg, seed=seed)
    print(f"Blue Prince drafting simulator - seed {seed}. "
          f"Reach the Antechamber (rank 9 center) before you run out of steps.")
    while game.phase is not Phase.TERMINAL:
        print()
        print(render_grid(game))
        print(render_status(game))
        if game.phase is Phase.NAVIGATE:
            st = game.state
            # Off-grid: show reachable area destinations the player can afford.
            if game.off_grid:
                area_node = game.registry.area_graph.nodes.get(st.area or "")
                loc_name = area_node.name if area_node is not None else (st.area or "?")
                print(f"You are at: {loc_name}.")
                # Build a numbered list of reachable, affordable destinations.
                graph = game.registry.area_graph
                reachable_opts: list[tuple[str, int]] = []
                for node_id in sorted(graph.nodes.keys()):
                    if node_id == st.area:
                        continue  # no self-travel
                    result = game.area_route_cost(node_id)
                    if result is None:
                        continue
                    cost, _ = result
                    if st.steps > cost:  # strict: at least 1 step left on arrival
                        reachable_opts.append((node_id, cost))
                print("Travel to:")
                for i, (node_id, cost) in enumerate(reachable_opts):
                    dest_node = graph.nodes[node_id]
                    print(f"  [{i + 1}] {dest_node.name} ({cost} step(s))")
                cmd = input("outer> ").strip().lower()
                if cmd == "q":
                    return
                try:
                    choice = int(cmd) - 1
                    if 0 <= choice < len(reachable_opts):
                        game.travel_to(reachable_opts[choice][0])
                    else:
                        print("  ? invalid choice")
                except ValueError:
                    print("  ? enter a number or 'q'")
                continue
            doors = game.open_doorways()
            moves = game.adjacent_moves()
            in_place = list(game._in_place_actions())
            # Room 46 (the objective) sits off-grid through the Antechamber's
            # north door. _action_in_budget counts travelling there as
            # purposeful whenever it is reachable and affordable (steps >=
            # cost -- no step needs to be left over after winning, unlike the
            # off-grid "Travel to:" menu's own destinations), independent of
            # whatever else is offered above; mirror that exact test rather
            # than the broader off-grid menu, which lists every modelled area
            # node.
            room46_route = game.area_route_cost("room_46")
            room46_cost = (room46_route[0] if room46_route is not None
                           and st.steps >= room46_route[0] else None)
            if not doors and not moves and not in_place:
                # Nothing to draft, walk into, or act on right where the
                # player stands. _check_termination is authoritative on
                # whether the day is actually over: a frontier doorway or an
                # unentered room elsewhere in the house can still be
                # purposeful even with nothing local, and the "Elsewhere"/
                # 'g'/'d' walk options below already cover that case. Only
                # skip straight back to the top (ending the day, since the
                # while-loop condition then sees TERMINAL) when the engine
                # agrees nothing is left anywhere; otherwise fall through so
                # those walk options actually get shown instead of looping
                # on this same empty check forever.
                game._check_termination()
                if game.phase is Phase.TERMINAL:
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
            if in_place:
                print("Other actions:")
                for i, (action_id, do) in enumerate(in_place):
                    print(f"  [x{i + 1}] {_in_place_label(game, action_id, do)}")
            if room46_cost is not None:
                print(f"  [46] travel through the Antechamber's north door "
                      f"to Room 46 ({room46_cost} step(s))")
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
            if cmd.startswith("x") and cmd[1:].isdigit():
                idx = int(cmd[1:]) - 1
                if 0 <= idx < len(in_place):
                    in_place[idx][1]()
                else:
                    print("  ? invalid choice")
                continue
            if cmd == "46" and room46_cost is not None:
                game.travel_to("room_46")
                continue
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
                      "'g/d <cell>', 'x <n>', '46', 'o', 'p', 'v', or 'q'")
                continue
            if game.doorway_passable(cell, d):
                game.open_door(cell, d)
            elif game.door_state_of(cell, d) == locks.DOOR_LOCKED:
                print("  ? that door is locked and you have no key")
            else:
                print("  ? that security door is sealed")
        elif game.phase is Phase.EXPERIMENT_PENDING:
            # Reached only by the 'x <n>' start_setup action above. Picking
            # the trigger and the effect are two separate decisions;
            # _maybe_finish_experiment_setup returns to NAVIGATE once both
            # are chosen.
            ex = game.state.experiment
            reg = game.registry.experiments
            if ex.trigger_id is None:
                label = "trigger"
                offered = ex.offered_triggers
                choose = game.choose_experiment_trigger
                texts = [reg.trigger_by_id[tid].text for tid in offered]
            else:
                label = "effect"
                offered = ex.offered_effects
                choose = game.choose_experiment_effect
                texts = [reg.effect_by_id[eid].text for eid in offered]
            print(f"Experimental Setup - pick a {label}:")
            for i, text in enumerate(texts):
                print(f"  [{i + 1}] {text}")
            cmd = input(f"{label}> ").strip().lower()
            if cmd == "q":
                return
            try:
                choice = int(cmd) - 1
                if 0 <= choice < len(offered):
                    choose(choice)
                else:
                    print("  ? invalid choice")
            except ValueError:
                print("  ? enter a number or 'q'")
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
                elif game.state.study_placed and game.state.gems >= 1 and p.study_redraws_used < 8:
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
        print(f"*** You reached Room 46! ({game.rooms_placed} rooms, "
              f"{game.state.steps} steps left) ***")
    else:
        print(f"Day over: {game.termination_reason} "
              f"(deepest rank {game.deepest_rank}, {game.rooms_placed} rooms)")
