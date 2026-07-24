"""Game orchestrator: the single API surface used by the env and the CLI."""

from __future__ import annotations

from collections import deque
from enum import Enum
from heapq import heappop, heappush

from ..config import GameConfig
from . import effects
from .decks import build_decks, inject_rooms
from .draft import deal_draft, redeal
from .effects import Hook
from .grid import (ADJACENT, DIRS, ENTRANCE_CELL, N_CELLS, OPPOSITE, neighbor,
                   rank_of, rotate_mask)
from .items import roll_room_items
from .locks import (DOOR_LOCKED, DOOR_OPEN, DOOR_SECURITY, SECURITY_LEVELS,
                    roll_segment, segment_key)
from .locks import security_openable as _security_openable
from .model import Registry, Room
from .placement import legal_orientations
from .rng import Rng
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost

ANTECHAMBER_CELL = 42  # rank 9, center column


class Phase(Enum):
    NAVIGATE = 0
    DRAFTING = 1
    TERMINAL = 2


class RedrawKind(Enum):
    STUDY = "study"     # costs 1 gem, max 8 per draft
    FREE = "free"       # Classroom-style free redraws
    DIE = "die"         # spend 1 ivory die


class Game:
    def __init__(self, cfg: GameConfig | None = None, seed: int = 0,
                 registry: Registry | None = None) -> None:
        self.cfg = cfg or GameConfig()
        self.registry = registry or Registry.load(self.cfg.data_dir)
        # Registry-derived lookups (the registry is immutable, so build once).
        self.outer_rooms: tuple[Room, ...] = tuple(
            r for r in self.registry.rooms if r.pool == "outer")
        self._garage_ids: tuple[str, ...] = tuple(
            r.id for r in self.registry.rooms if r.id.startswith("garage"))
        self.seed = seed
        self.reset(seed)

    # ------------------------------------------------------------------ setup

    def reset(self, seed: int | None = None) -> None:
        """Start a fresh day: new seeded RNG, blank state, rebuilt solitaire decks.

        Places the Entrance Hall (rank 1 center, already entered) and the
        sealed Antechamber (rank 9 center), rolling the Antechamber's door
        locks. Passing ``seed`` reseeds; omitting it replays the same seed.
        """
        if seed is not None:
            self.seed = seed
        self.rng = Rng(self.seed)
        cfg = self.cfg
        st = GameState()
        st.steps = cfg.starting_steps + (20 if cfg.orchard_unlocked else 0)
        st.gems = 2 if cfg.mine_unlocked else 0
        st.day = cfg.day
        st.stage = cfg.resolved_stage()
        st.luck = self.registry.item_rules["luck"]["day_start"]
        st.decks = build_decks(self.registry, cfg, self.rng)
        self.state = st

        self.placed_ids: set[str] = set()
        # Lowest grid cell per placed room id (mirrors a low-to-high grid scan;
        # duplicates are only possible via the Chamber of Mirrors).
        self.room_cells: dict[str, int] = {}
        self.free_categories: set[str] = set()
        self.bedroom_bonus = 0
        self.red_negations = 0
        self.hovel_placed = False
        self.doorway_drafts: dict[tuple[int, int], PendingDraft] = {}
        self.phase = Phase.NAVIGATE
        self.termination_reason = ""
        self.rooms_placed = 0
        self.deepest_rank = 1

        entrance = self.registry.by_id["entrance_hall"]
        self._place_room(entrance, ENTRANCE_CELL, entrance.door_mask, entered=True)
        st.pos = ENTRANCE_CELL

        # The Antechamber is fixed at rank 9 center from the start of every
        # day (sealed until a drafted room connects a door to it). Modeled
        # with all four doors available; see README open questions.
        ante = self.registry.by_id["antechamber"]
        st.grid[ANTECHAMBER_CELL] = ante.idx
        st.placed_doors[ANTECHAMBER_CELL] = 0xF
        self.placed_ids.add(ante.id)
        self.room_cells[ante.id] = ANTECHAMBER_CELL
        # The Antechamber's doorways roll like any other (rank 8<->9 sits at
        # 130% base chance, so at bias 1 they start locked): walking in
        # normally costs a key, mirroring the real game's locked Antechamber.
        self._roll_new_segments(ante, ANTECHAMBER_CELL, 0xF)
        self._map_cache: tuple[tuple, dict] = ((), {})

    # ------------------------------------------------------------ connectivity

    def _connected(self, a: int, b: int, d: int) -> bool:
        """True if rooms at a and b share a usable door pair across direction d."""
        st = self.state
        return bool(st.placed_doors[a] & d) and bool(st.placed_doors[b] & OPPOSITE[d])

    def _maps(self) -> dict:
        """Memo dict for the BFS map functions, valid for the current layout.

        Keyed on a fingerprint of everything those functions read (player
        position, outer-area location, grid, door masks), so any state change
        - including tests poking ``state`` directly - starts a fresh dict.
        Cached values are shared between callers and must not be mutated.
        """
        st = self.state
        fp = (st.pos, st.outer_loc, tuple(st.grid), tuple(st.placed_doors),
              st.door_version, st.keys, self.security_openable())
        cached_fp, maps = self._map_cache
        if fp != cached_fp:
            maps = {}
            self._map_cache = (fp, maps)
        return maps

    def _nav_bfs(self) -> tuple[list[int], list[int], dict]:
        """Shortest walks from the player, spending at most ``st.keys`` keys.

        BFS over (cell, keys_spent) states: a locked segment costs one key to
        cross, a security segment passes only while :meth:`security_openable`,
        open segments are free. A locked door en route is therefore keyed
        through or walked around, whichever fits the step budget - and with
        no keys the detour distance is what counts against the budget.
        In-drafting keeps every naturally formed placed-room door pair open
        today, but honest distances here are groundwork for rooms that
        re-lock their own doors (Vestibule, not yet modeled).

        Returns (dist, key_cost, prev): per-cell walking distance (-1 empty
        or unreachable within the key budget), keys spent along the recorded
        shortest path, and the predecessor map used by :meth:`_path_dirs` -
        so a path promised here is always affordable in keys when walked.

        Results are cached; treat them as read-only.
        """
        maps = self._maps()
        cached = maps.get("nav")
        if cached is not None:
            return cached
        st = self.state
        grid, doors, door_state = st.grid, st.placed_doors, st.door_state
        keys_cap = min(st.keys,
                       sum(1 for v in door_state.values() if v == DOOR_LOCKED))
        sec_ok = self.security_openable()
        dist = [-1] * N_CELLS
        key_cost = [0] * N_CELLS
        best_spent = [keys_cap + 1] * N_CELLS  # cheapest key spend seen per cell
        dist[st.pos] = 0
        best_spent[st.pos] = 0
        prev: dict[tuple[int, int], tuple[int, int, int]] = {}
        # Frontier ordered by (steps, keys): a cell's first discovery is its
        # shortest walk, and among equally short walks the one spending the
        # fewest keys - so move_to never wastes a key a free path avoids.
        heap = [(0, 0, st.pos)]
        while heap:
            sdist, spent, cell = heappop(heap)
            cell_doors = doors[cell]
            for d, od, nb in ADJACENT[cell]:
                if grid[nb] < 0 or not (cell_doors & d and doors[nb] & od):
                    continue
                seg = door_state.get(segment_key(cell, d), DOOR_OPEN)
                nspent = spent
                if seg == DOOR_LOCKED:
                    nspent = spent + 1
                    if nspent > keys_cap:
                        continue
                elif seg == DOOR_SECURITY and not sec_ok:
                    continue
                # Keep only Pareto-optimal states: a later arrival is worth
                # exploring iff it spends strictly fewer keys (a longer but
                # cheaper path may unlock cells beyond a further locked door).
                if nspent >= best_spent[nb]:
                    continue
                best_spent[nb] = nspent
                if dist[nb] == -1:
                    dist[nb] = sdist + 1
                    key_cost[nb] = nspent
                prev[(nb, nspent)] = (cell, spent, d)
                heappush(heap, (sdist + 1, nspent, nb))
        maps["nav"] = (dist, key_cost, prev)
        return maps["nav"]

    def reachable_cells(self) -> set[int]:
        """Cells reachable from the player through passable door pairs.

        Returns a cached set; treat it as read-only.
        """
        maps = self._maps()
        cached = maps.get("reachable")
        if cached is None:
            dist = self._nav_bfs()[0]
            cached = {c for c, v in enumerate(dist) if v >= 0}
            maps["reachable"] = cached
        return cached

    def distance_map(self) -> list[int]:
        """Walking distance from the player to every placed cell.

        BFS through passable door pairs, one step per room (the cost
        :meth:`move_to` would pay); a locked door is keyed through when the
        key budget allows, otherwise the distance reflects walking around.
        -1 marks empty or unreachable cells; the player's own cell is 0.

        Returns a cached list; treat it as read-only.
        """
        return self._nav_bfs()[0]

    def key_cost_map(self) -> list[int]:
        """Keys spent along the shortest path :meth:`move_to` would walk.

        Meaningful only where :meth:`distance_map` is >= 0.
        Returns a cached list; treat it as read-only.
        """
        return self._nav_bfs()[1]

    def optimistic_distances(self) -> list[int]:
        """Per-cell optimistic distance to the Antechamber.

        Empty cells are treated as freely passable in every direction, while
        placed rooms still only pass through their existing doors (a solid
        wall stays a wall no matter what gets drafted later). -1 marks cells
        walled off from the Antechamber even under this assumption.

        Returns a cached list; treat it as read-only.
        """
        maps = self._maps()
        cached = maps.get("ante_dist")
        if cached is not None:
            return cached
        st = self.state
        grid, doors = st.grid, st.placed_doors
        dist = [-1] * N_CELLS
        dist[ANTECHAMBER_CELL] = 0
        q = deque([ANTECHAMBER_CELL])
        while q:
            cell = q.popleft()
            cell_doors = doors[cell]
            cell_empty = grid[cell] < 0
            for d, od, nb in ADJACENT[cell]:
                if dist[nb] != -1:
                    continue
                if ((cell_empty or cell_doors & d)
                        and (grid[nb] < 0 or doors[nb] & od)):
                    dist[nb] = dist[cell] + 1
                    q.append(nb)
        maps["ante_dist"] = dist
        return dist

    # ---------------------------------------------------------------- actions

    def open_doorways(self) -> list[tuple[int, int]]:
        """Closed doors of the CURRENT room that a draft can open.

        Drafting happens at the doorway of the room you are standing in, so
        this is scoped to ``st.pos``. Use :meth:`move` to travel to another
        placed room before drafting from its doorways.
        """
        st = self.state
        if self.phase is not Phase.NAVIGATE:
            return []
        if st.outer_loc > 0:
            return []
        cell = st.pos
        if st.grid[cell] < 0 or cell == ANTECHAMBER_CELL:
            return []
        return [(cell, d) for d in DIRS
                if st.placed_doors[cell] & d
                and (nb := neighbor(cell, d)) != -1 and st.grid[nb] < 0]

    def frontier_doorways(self) -> list[tuple[int, int]]:
        """Every closed door across all reachable rooms.

        These are the draft targets of :meth:`draft_from`; the list also
        drives dead-end detection.

        Returns a cached list; treat it as read-only.
        """
        st = self.state
        if st.outer_loc > 0:
            return []
        maps = self._maps()
        cached = maps.get("frontier")
        if cached is not None:
            return cached
        out = []
        grid, doors = st.grid, st.placed_doors
        for cell in self.reachable_cells():
            if grid[cell] < 0 or cell == ANTECHAMBER_CELL:
                continue
            cell_doors = doors[cell]
            for d, _od, nb in ADJACENT[cell]:
                if cell_doors & d and grid[nb] < 0:
                    out.append((cell, d))
        maps["frontier"] = out
        return out

    # ------------------------------------------------------- locks & security

    def door_state_of(self, cell: int, direction: int) -> int:
        """Lock state of the doorway segment (DOOR_OPEN/LOCKED/SECURITY)."""
        return self.state.door_state.get(segment_key(cell, direction), DOOR_OPEN)

    def security_openable(self) -> bool:
        """Can security doors be opened right now (keycard/power/offline mode)?"""
        return _security_openable(self.state)

    def doorway_passable(self, cell: int, direction: int) -> bool:
        """Can the doorway be opened from where it stands: a locked door with
        a key in hand, a security door while the system allows it, or any
        open/unlocked door. Path key costs are the caller's concern (see
        :meth:`key_cost_map`)."""
        state = self.door_state_of(cell, direction)
        if state == DOOR_LOCKED:
            return self.state.keys >= 1
        if state == DOOR_SECURITY:
            return self.security_openable()
        return True

    def _open_segment(self, cell: int, direction: int) -> None:
        """Set the segment to DOOR_OPEN, bumping door_version to invalidate nav caches."""
        self.state.door_state[segment_key(cell, direction)] = DOOR_OPEN
        self.state.door_version += 1

    def _unlock_for_passage(self, cell: int, direction: int) -> None:
        """Open the segment the player is about to pass, spending a key if locked."""
        st = self.state
        state = self.door_state_of(cell, direction)
        if state == DOOR_LOCKED:
            assert st.keys >= 1, "door is locked and you have no key"
            st.keys -= 1
            self._open_segment(cell, direction)
        elif state == DOOR_SECURITY:
            assert self.security_openable(), "security door cannot be opened"
            self._open_segment(cell, direction)

    def _security_toggle_helps(self) -> bool:
        """Would flipping the Utility Closet keycard power open security doors?

        Powered without the card: powering DOWN helps once the Security
        terminal's offline mode is Unlocked. Unpowered with the card in hand:
        powering UP makes the readers accept it again.
        """
        st = self.state
        if self._utility_closet_cell() < 0:
            return False
        return st.offline_unlocked if st.keycard_power_on else st.has_keycard

    def can_toggle_keycard_power(self) -> bool:
        """Standing at the Utility Closet breaker box, on the grid, mid-day."""
        return (self.phase is Phase.NAVIGATE and self.cfg.door_locks
                and self.state.outer_loc == 0
                and self.state.pos == self._utility_closet_cell() >= 0)

    def set_keycard_power(self, on: bool) -> None:
        """Flip the breaker's "Keycard Entry" switch (free, like the real game)."""
        assert self.can_toggle_keycard_power(), "must stand in the Utility Closet"
        self.state.keycard_power_on = on

    def can_set_security_level(self) -> bool:
        """Standing at the Security terminal, on the grid, mid-day."""
        return (self.phase is Phase.NAVIGATE and self.cfg.door_locks
                and self.state.outer_loc == 0
                and self.state.pos == self.room_cells.get("security", -1) >= 0)

    def set_security_level(self, level: str) -> None:
        """Set the security-door frequency (low/normal/high) at the terminal.

        Applies to doors rolled from now on; already-spawned doors keep their
        state. The daily spawn cap is checked at roll time, so raising the
        level mid-day re-opens headroom."""
        assert level in SECURITY_LEVELS, f"bad security level {level!r}"
        assert self.can_set_security_level(), "must stand in Security"
        self.state.security_level = level

    def open_door(self, cell: int, direction: int) -> PendingDraft:
        """Draft (but do not enter) through a doorway of the current room.

        Drafting only deals a hand and, on :meth:`choose`, places a room; it
        costs no step and grants no resources. The player pays the step and
        receives the room's effects only when they :meth:`move` into it.
        Opening a locked doorway consumes a key first; a security doorway
        needs the keycard system to allow it (:meth:`security_openable`).
        """
        assert self.phase is Phase.NAVIGATE, "not in NAVIGATE phase"
        st = self.state
        assert cell == st.pos, "can only draft from the room you are standing in"
        assert st.placed_doors[cell] & direction, "no door in that direction"
        target = neighbor(cell, direction)
        assert target != -1 and st.grid[target] < 0, "invalid doorway"
        self._unlock_for_passage(cell, direction)
        key = (cell, direction)
        pending = self.doorway_drafts.get(key)
        if pending is None:
            pending = deal_draft(st, self.registry, self.cfg, self.rng,
                                 self.placed_ids, cell, direction, target)
            pending.redraws_left = st.drafting_room_count if self._in_classroom_context() else 0
            self.doorway_drafts[key] = pending
        st.pending = pending
        self.phase = Phase.DRAFTING
        return pending

    def draft_from(self, cell: int, direction: int) -> PendingDraft | None:
        """Walk to ``cell`` (if needed) and draft through its ``direction`` door.

        A macro over :meth:`move_to` + :meth:`open_door`: the walk pays the
        normal one-step-per-room cost and collects first-entry pickups along
        the way, so the RNG stream is identical to issuing the moves by hand.
        Returns None if the walk ends the day before the draft can happen.
        """
        assert self.phase is Phase.NAVIGATE
        if cell != self.state.pos:
            self.move_to(cell)
        if self.phase is not Phase.NAVIGATE:
            return None
        return self.open_door(cell, direction)

    def _in_classroom_context(self) -> bool:
        """Is the player drafting from inside the Classroom (grants free redraws)?"""
        room_idx = self.state.grid[self.state.pos]
        return room_idx >= 0 and self.registry.rooms[room_idx].id == "classroom"

    # --------------------------------------------------------- outer rooms

    def _garage_cell(self) -> int:
        """Cell where the garage room (or a garage variant) is placed, or -1."""
        cells = [self.room_cells[rid] for rid in self._garage_ids
                 if rid in self.room_cells]
        return min(cells) if cells else -1

    def _utility_closet_cell(self) -> int:
        """Cell where utility_closet is placed, or -1."""
        return self.room_cells.get("utility_closet", -1)

    def _breaker_on(self) -> bool:
        """True if utility_closet is placed AND its cell has been entered."""
        cell = self._utility_closet_cell()
        return cell >= 0 and self.state.entered[cell]

    def _outer_route_cost(self) -> int | None:
        """Cheapest available route cost to reach the outer-area doorstep.

        Returns the step cost or None if no affordable route exists.
        Requires steps > cost (strict) so at least 1 step remains after arriving.
        """
        st = self.state
        dist = self.distance_map()
        costs = []
        # Entrance Hall route: always available if reachable
        eh_dist = dist[ENTRANCE_CELL]
        if eh_dist >= 0:
            costs.append(eh_dist + self.cfg.outer_path_entrance_cost)
        # Garage route: only if breaker on and garage placed and reachable
        garage_cell = self._garage_cell()
        if garage_cell >= 0 and self._breaker_on():
            g_dist = dist[garage_cell]
            if g_dist >= 0:
                costs.append(g_dist + self.cfg.outer_path_garage_cost)
        if not costs:
            return None
        best = min(costs)
        return best if st.steps > best else None

    def outer_draft_available(self) -> bool:
        """Can the once-per-day outer-room draft be started right now?

        Requires the unlock, no outer room drafted yet today, NAVIGATE phase
        on the grid, and an affordable route to the doorstep
        (see :meth:`_outer_route_cost`).
        """
        if not self.cfg.outer_rooms_unlocked:
            return False
        if self.state.outer_room_drafted:
            return False
        if self.phase is not Phase.NAVIGATE:
            return False
        if self.state.outer_loc != 0:
            return False
        return self._outer_route_cost() is not None

    def open_outer_draft(self) -> PendingDraft | None:
        """Walk to the outer-area doorstep and open the once-per-day outer-room draft.

        Outer rooms sit off the 5x9 grid; no rarity roll - the fixed pool of 8
        is shuffled and 3 are offered (wiki-documented mechanic).
        """
        assert self.outer_draft_available()
        st = self.state
        dist = self.distance_map()

        # Pick cheapest route (ties broken: EH first)
        eh_cost = (dist[ENTRANCE_CELL] + self.cfg.outer_path_entrance_cost
                   if dist[ENTRANCE_CELL] >= 0 else None)
        garage_cell = self._garage_cell()
        garage_cost = None
        if garage_cell >= 0 and self._breaker_on() and dist[garage_cell] >= 0:
            garage_cost = dist[garage_cell] + self.cfg.outer_path_garage_cost

        if garage_cost is not None and (eh_cost is None or garage_cost < eh_cost):
            access_cell = garage_cell
            offgrid_cost = self.cfg.outer_path_garage_cost
        else:
            access_cell = ENTRANCE_CELL
            offgrid_cost = self.cfg.outer_path_entrance_cost

        # Walk to the access cell (same bookkeeping as draft_from / move_to)
        if access_cell != st.pos:
            self.move_to(access_cell)
        if self.phase is not Phase.NAVIGATE:
            return None  # walk ended the day

        # Deduct the off-grid path cost (EH->doorstep or garage->doorstep)
        st.steps -= offgrid_cost
        st.outer_loc = 1

        key = (-1, 0)
        pending = self.doorway_drafts.get(key)
        if pending is None:
            outer = self.outer_rooms
            order = list(range(len(outer)))
            self.rng.shuffle("outer_draft", order)
            pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
            for slot, i in enumerate(order[:3]):
                room = outer[i]
                pending.options.append(DraftOption(
                    room_idx=room.idx, orientation=room.door_mask, gem_cost=0, slot=slot))
            self.doorway_drafts[key] = pending
        st.pending = pending
        self.phase = Phase.DRAFTING
        return pending

    def _choose_outer(self, opt) -> None:
        """Resolve choosing an outer-room option: place it off-grid, fire ON_PLACE.

        The player stays at the doorstep; the room's ON_ENTER effects and item
        rolls wait for :meth:`enter_outer_room`.
        """
        st = self.state
        room = self.registry.rooms[opt.room_idx]
        st.outer_room_drafted = True
        self.placed_ids.add(room.id)
        del self.doorway_drafts[(-1, 0)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        effects.fire(self, room, Hook.ON_PLACE)
        # Player stays at doorstep (outer_loc == 1); ON_ENTER fires when they enter.
        self._check_termination()

    def enter_outer_room(self) -> None:
        """Enter the outer room from the doorstep (costs 1 step, fires ON_ENTER once)."""
        st = self.state
        assert self.phase is Phase.NAVIGATE
        assert st.outer_loc == 1, "must be at doorstep to enter"
        assert st.outer_room_drafted, "no outer room drafted today"
        assert not st.outer_room_entered, "outer room already entered today"
        assert st.steps >= self.cfg.outer_enter_cost, "not enough steps"
        st.steps -= self.cfg.outer_enter_cost
        st.outer_loc = 2
        st.outer_room_entered = True
        outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
        if outer_room is not None:
            effects.fire(self, outer_room, Hook.ON_ENTER)
            roll_room_items(st, self.registry, outer_room, self.rng)
        self._check_termination()

    def return_from_outer(self, dest: str) -> None:
        """Walk back from the outer area to the grid.

        dest: "entrance_hall" or "garage"
        """
        st = self.state
        assert self.phase is Phase.NAVIGATE
        assert st.outer_loc > 0, "not in outer area"
        inside_penalty = 1 if st.outer_loc == 2 else 0

        match dest:
            case "entrance_hall":
                cost = self.cfg.outer_path_entrance_cost + inside_penalty
                dest_cell = ENTRANCE_CELL
            case "garage":
                assert self._breaker_on(), "garage route requires breaker"
                cost = self.cfg.outer_path_garage_cost + inside_penalty
                dest_cell = self._garage_cell()
                assert dest_cell >= 0, "garage not placed"
            case _:
                raise ValueError(f"unknown dest: {dest}")

        assert st.steps >= cost, "not enough steps"
        st.steps -= cost
        st.pos = dest_cell
        st.outer_loc = 0
        # If returning into a never-entered room, fire its first-entry effects
        if not st.entered[dest_cell]:
            self._enter(dest_cell)
        self._check_termination()

    def choose(self, slot: int) -> None:
        """Take the pending hand's option in ``slot``, pay its cost, place the room.

        DRAFTING-phase action; returns the game to NAVIGATE. Placing does not
        enter the room - no step is spent and none of its resources are gained
        until the player :meth:`move`s in. Outer-room drafts (target_cell -1)
        route to their off-grid placement instead.
        """
        assert self.phase is Phase.DRAFTING and self.state.pending is not None
        st = self.state
        pending = st.pending
        opts = [o for o in pending.options if o.slot == slot]
        assert opts, f"no option in slot {slot}"
        opt = opts[0]
        if pending.target_cell == -1:  # outer-room draft
            self._choose_outer(opt)
            return
        room = self.registry.rooms[opt.room_idx]
        assert self.affordable(room, opt), "cannot afford"
        self._pay(room, opt)

        # Drafting only PLACES the room behind the doorway. The player does
        # not enter it, pays no step, and gains none of its resources until
        # they move in (see :meth:`move`).
        self._place_room(room, pending.target_cell, opt.orientation)
        del self.doorway_drafts[(pending.from_cell, pending.direction)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        self._check_termination()

    def _effective_cost(self, room: Room, opt) -> int:
        """Gem cost of an option: slot 0 and free-category rooms cost nothing."""
        if opt.slot == 0:
            return 0
        if room.category in self.free_categories:
            return 0
        return resolve_gem_cost(room, self.state, self.registry.rooms)

    def affordable(self, room: Room, opt) -> bool:
        """Can the current draft option be paid for?

        With the Hovel placed, gem costs are paid entirely in steps at 3:1
        (leaving at least one step so the drafted room can still be entered).
        """
        cost = self._effective_cost(room, opt)
        if cost <= 0:
            return True
        if self.hovel_placed:
            return self.state.steps > 3 * cost
        return self.state.gems >= cost

    def _pay(self, room: Room, opt) -> None:
        """Deduct the option's gem cost - in steps at 3:1 when the Hovel is placed."""
        cost = self._effective_cost(room, opt)
        if cost <= 0:
            return
        if self.hovel_placed:
            self.state.steps -= 3 * cost
        else:
            self.state.gems -= cost

    # There is no decline: opening a door commits you to drafting one of the
    # dealt rooms. Slot 1 is always the free forced-Closet fallback, so an
    # affordable option always exists.

    def redraw(self, kind: RedrawKind) -> None:
        """Replace the whole pending hand via a Study, Classroom, or die redraw.

        STUDY costs 1 gem (needs the Study placed, max 8 per draft), FREE
        spends one of the hand's Classroom redraws, DIE spends an ivory die.
        Outer-room drafts cannot be redrawn.
        """
        assert self.phase is Phase.DRAFTING and self.state.pending is not None
        st = self.state
        pending = st.pending
        assert pending.target_cell != -1, "outer-room drafts cannot be redrawn"
        if kind is RedrawKind.STUDY:
            assert st.study_placed and st.gems >= 1 and pending.study_redraws_used < 8
            st.gems -= 1
            pending.study_redraws_used += 1
        elif kind is RedrawKind.FREE:
            assert pending.redraws_left > 0
            pending.redraws_left -= 1
        elif kind is RedrawKind.DIE:
            assert st.dice >= 1
            st.dice -= 1
        redeal(st, self.registry, self.cfg, self.rng, self.placed_ids, pending)

    def _rotation_source(self) -> bool:
        """Is a free-rotation source in play for the current hand?"""
        st = self.state
        if self.phase is not Phase.DRAFTING or st.pending is None:
            return False
        if st.pending.target_cell == -1:  # outer-room draft: no doorway to rotate against
            return False
        if self.cfg.ornate_compass or "rotunda" in self.placed_ids:
            return True
        return any(self.registry.rooms[o.room_idx].id == "dovecote"
                   for o in st.pending.options)

    def rotation_available(self) -> bool:
        """Can the current hand's floorplans be freely rotated?

        The Ornate Compass grants this on every draft while it is held; the
        Rotunda grants it while placed on the grid; the Dovecote grants it only
        while it is one of the drawn options. This overrides the random
        orientation roll - the player rotates the options at will.

        Outer-room drafts sit off the grid with a fixed orientation and no
        entry doorway (``target_cell == -1``), so rotation never applies there.

        Even with a source in play, each hand gets a finite rotation budget of
        ``max(legal orientations per option) - 1``. Rotation advances every
        option one position around its own legal cycle, so that many rotations
        already reach every orientation of every option - one more only revisits
        hand states already seen. Without the cap, rotation is a free cyclic
        action (period lcm <= 12; 1 when the doorway pins every option), and a
        deterministic policy whose argmax is "rotate" around the cycle loops on
        it forever.
        """
        if not self._rotation_source():
            return False
        st = self.state
        pending = st.pending
        budget = max(
            len(legal_orientations(self.registry.rooms[o.room_idx],
                                   pending.target_cell, pending.direction,
                                   st, self.cfg))
            for o in pending.options) - 1
        return pending.rotations_used < budget

    def rotate_options(self) -> None:
        """Spin every drawn floorplan into its next legal orientation (clockwise).

        Callable whenever a rotation source is in play, even if every option is
        pinned (a no-op), so episodes recorded before no-op rotates were masked
        out still replay.
        """
        assert self._rotation_source(), "no rotation source in play"
        st = self.state
        pending = st.pending
        pending.rotations_used += 1
        for opt in pending.options:
            room = self.registry.rooms[opt.room_idx]
            legal = legal_orientations(room, pending.target_cell, pending.direction,
                                       st, self.cfg)
            if len(legal) <= 1:
                continue
            mask = opt.orientation
            for _ in range(4):
                mask = rotate_mask(mask, 1)
                if mask in legal:
                    opt.orientation = mask
                    break

    def adjacent_moves(self) -> list[int]:
        """Directions from the current room into a connected, placed room."""
        st = self.state
        if self.phase is not Phase.NAVIGATE:
            return []
        if st.outer_loc > 0:
            return []
        out = []
        for d in DIRS:
            nb = neighbor(st.pos, d)
            if (nb != -1 and st.grid[nb] >= 0 and self._connected(st.pos, nb, d)
                    and self.doorway_passable(st.pos, d)):
                out.append(d)
        return out

    def move(self, direction: int) -> None:
        """Walk one room in ``direction``, entering the connected room there.

        This is the only action that spends a step and (on first entry) grants
        a room's resources. Walking into the Antechamber is how you win.
        """
        assert self.phase is Phase.NAVIGATE
        st = self.state
        nb = neighbor(st.pos, direction)
        assert nb != -1 and st.grid[nb] >= 0 and self._connected(st.pos, nb, direction), \
            "no connected room that way"
        assert st.steps >= 1, "out of steps"
        self._unlock_for_passage(st.pos, direction)
        st.steps -= 1
        st.pos = nb
        self._enter(nb)
        self._check_termination()

    def move_to(self, cell: int) -> None:
        """Walk the shortest connected path to ``cell``, one step per room."""
        assert self.phase is Phase.NAVIGATE
        path = self._path_dirs(cell)
        assert path is not None, "cell not reachable"
        for d in path:
            if self.phase is not Phase.NAVIGATE:
                break
            self.move(d)

    def _path_dirs(self, target: int) -> list[int] | None:
        """Directions of the shortest passable path from pos to target.

        Follows the exact path :meth:`_nav_bfs` recorded, so any locked doors
        along it fit in the current key budget.
        """
        st = self.state
        if target == st.pos:
            return []
        dist, key_cost, prev = self._nav_bfs()
        if dist[target] < 0:
            return None
        dirs = []
        cur, spent = target, key_cost[target]
        while cur != st.pos or spent != 0:
            pcell, pspent, pdir = prev[(cur, spent)]
            dirs.append(pdir)
            cur, spent = pcell, pspent
        dirs.reverse()
        return dirs

    # ---------------------------------------------------------------- internal

    def _roll_new_segments(self, room: Room, cell: int, orientation: int) -> None:
        """Roll lock/security state for the room's doors on fresh segments.

        The segment a room was drafted through is already DOOR_OPEN; a door
        facing an already-rolled locked or security segment opens it for free
        (in-drafting, as in the real game) - so a locked door can never sit
        between two connected placed rooms, and locks only ever gate frontier
        drafting. Only doors creating a segment for the first time roll.
        """
        if not self.cfg.door_locks:
            return
        st = self.state
        for d in DIRS:
            if not orientation & d or neighbor(cell, d) == -1:
                continue
            seg = segment_key(cell, d)
            existing = st.door_state.get(seg)
            if existing is not None:
                if existing != DOOR_OPEN:
                    st.door_state[seg] = DOOR_OPEN
                    st.door_version += 1
                continue
            st.door_state[seg] = roll_segment(
                st, self.registry.lock_rules, room, cell, d, self.rng)
            st.door_version += 1

    def _place_room(self, room: Room, cell: int, orientation: int,
                    entered: bool = False) -> None:
        """Put ``room`` on the grid at ``cell`` with the given door orientation.

        Rolls lock state for its fresh door segments, updates the placed-id /
        room-cell indexes and progress counters, then fires the room's
        ON_PLACE hook plus ON_DRAFT_ROOM on every other placed room
        (relational effects like the Nursery). ``entered=True`` is only used
        for the Entrance Hall at day start.
        """
        st = self.state
        st.grid[cell] = room.idx
        st.placed_doors[cell] = orientation
        st.entered[cell] = entered
        self._roll_new_segments(room, cell, orientation)
        self.placed_ids.add(room.id)
        prev = self.room_cells.get(room.id)
        if prev is None or cell < prev:
            self.room_cells[room.id] = cell
        self.rooms_placed += 1
        self.deepest_rank = max(self.deepest_rank, rank_of(cell))
        effects.fire(self, room, Hook.ON_PLACE)
        # Relational draft hooks on every other placed room (Nursery etc.).
        for other_cell, idx in enumerate(st.grid):
            if idx >= 0 and other_cell != cell:
                effects.fire(self, self.registry.rooms[idx], Hook.ON_DRAFT_ROOM,
                             context_room=room)

    def _enter(self, cell: int) -> None:
        """First-entry bookkeeping for ``cell``; no-op if already entered.

        Fires the room's ON_ENTER effects and item rolls exactly once. With
        door locks on, visiting Security unlocks the terminal's offline mode,
        and keycard source rooms roll their chance to hand over the Keycard.
        """
        st = self.state
        if st.entered[cell]:
            return
        st.entered[cell] = True
        room = self.registry.rooms[st.grid[cell]]
        effects.fire(self, room, Hook.ON_ENTER)
        roll_room_items(st, self.registry, room, self.rng)
        if self.cfg.door_locks:
            if room.id == "security":
                # Assume the player always flips the terminal's offline mode
                # to Unlocked when visiting Security: from now on, cutting the
                # power at the Utility Closet swings every security door open.
                st.offline_unlocked = True
            kc = self.registry.lock_rules["keycard"]
            if (not st.has_keycard and room.id in kc["source_rooms"]
                    and self.rng.chance("keycard", kc["chance"] / 100.0)):
                st.has_keycard = True
                st.items_found_log.append(("keycard", 1))

    def inject_rooms(self, room_ids: list[str]) -> None:
        inject_rooms(self.state, self.registry, room_ids, self.rng)

    def _terminate(self, reason: str) -> None:
        self.phase = Phase.TERMINAL
        self.termination_reason = reason

    def _check_termination(self) -> None:
        """End the day when won, out of steps, or no purposeful action remains.

        Called after every state-changing action. Winning requires standing
        IN the Antechamber (which may cost the last step); "dead_end" means no
        frontier doorway exists and the Antechamber is unreachable;
        "out_of_steps" also covers having steps left but nothing useful
        within the budget (see :meth:`_action_in_budget`).
        """
        st = self.state
        # You win only by walking INTO the Antechamber, not by connecting a
        # door to it. Reaching it may cost the last step you have.
        if st.pos == ANTECHAMBER_CELL:
            self._terminate("antechamber")
        elif st.steps <= 0:
            self._terminate("out_of_steps")
        elif st.outer_loc > 0:
            # Off-grid: check if any outer-area action is affordable
            if not self._outer_action_in_budget():
                self._terminate("out_of_steps")
        elif not self.frontier_doorways() and not self._antechamber_reachable():
            # No undrafted doors anywhere reachable and no path to walk into
            # the Antechamber: the day cannot progress.
            self._terminate("dead_end")
        elif not self._action_in_budget():
            # Steps remain, but nothing useful is within the step budget:
            # re-entering rooms grants nothing, so the day cannot progress.
            self._terminate("out_of_steps")

    def _outer_action_in_budget(self) -> bool:
        """True if any action is affordable while the player is off-grid."""
        st = self.state
        inside_penalty = 1 if st.outer_loc == 2 else 0
        # Can enter (if at doorstep and outer room drafted but not entered)?
        if st.outer_loc == 1 and st.outer_room_drafted and not st.outer_room_entered:
            if st.steps >= self.cfg.outer_enter_cost:
                return True
        # Can return to EH?
        if st.steps >= self.cfg.outer_path_entrance_cost + inside_penalty:
            return True
        # Can return via garage?
        garage_cell = self._garage_cell()
        if garage_cell >= 0 and self._breaker_on():
            if st.steps >= self.cfg.outer_path_garage_cost + inside_penalty:
                return True
        return False

    def _action_in_budget(self) -> bool:
        """True if any purposeful action still fits in the step budget.

        Purposeful: draft an openable frontier doorway (arriving with a step
        to spare so the drafted room can be entered), enter an unentered room
        (its pickups may include steps), walk into the Antechamber, or detour
        to the Utility Closet when flipping the keycard power would open a
        security doorway that is otherwise in reach.
        """
        st = self.state
        dist = self.distance_map()
        key_cost = self.key_cost_map()
        uc = self._utility_closet_cell()
        toggle_ok = (self._security_toggle_helps()
                     and 0 <= dist[uc] <= st.steps - 2 if uc >= 0 else False)
        for cell, d in self.frontier_doorways():
            if not 0 <= dist[cell] <= st.steps - 1:
                continue
            seg = self.door_state_of(cell, d)
            if seg == DOOR_LOCKED and st.keys < key_cost[cell] + 1:
                continue
            if seg == DOOR_SECURITY and not self.security_openable():
                if not toggle_ok:
                    continue
            return True
        for cell in range(N_CELLS):
            if 0 < dist[cell] <= st.steps and not st.entered[cell]:
                return True
        return self.outer_draft_available()

    def _antechamber_reachable(self) -> bool:
        return ANTECHAMBER_CELL in self.reachable_cells()

    # ------------------------------------------------------------------ info

    def is_done(self) -> tuple[bool, str]:
        """Return (day over?, reason); the reason is "" while the day is running."""
        return self.phase is Phase.TERMINAL, self.termination_reason

    def success(self) -> bool:
        """Did the day end by walking into the Antechamber?"""
        return self.termination_reason == "antechamber"
