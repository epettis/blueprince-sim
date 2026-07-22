"""Game orchestrator: the single API surface used by the env and the CLI."""

from __future__ import annotations

from collections import deque
from enum import Enum

from ..config import GameConfig
from . import effects
from .decks import build_decks, inject_rooms
from .draft import deal_draft, redeal
from .effects import Hook
from .grid import DIRS, ENTRANCE_CELL, OPPOSITE, neighbor, rank_of, rotate_mask
from .items import roll_room_items
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
        self.seed = seed
        self.reset(seed)

    # ------------------------------------------------------------------ setup

    def reset(self, seed: int | None = None) -> None:
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

    # ------------------------------------------------------------ connectivity

    def _connected(self, a: int, b: int, d: int) -> bool:
        """True if rooms at a and b share a usable door pair across direction d."""
        st = self.state
        return bool(st.placed_doors[a] & d) and bool(st.placed_doors[b] & OPPOSITE[d])

    def reachable_cells(self) -> set[int]:
        """Cells reachable from the player through connected door pairs."""
        st = self.state
        seen = {st.pos}
        q = deque([st.pos])
        while q:
            cell = q.popleft()
            for d in DIRS:
                nb = neighbor(cell, d)
                if nb == -1 or nb in seen or st.grid[nb] < 0:
                    continue
                if self._connected(cell, nb, d):
                    seen.add(nb)
                    q.append(nb)
        return seen

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
        cell = st.pos
        if st.grid[cell] < 0 or cell == ANTECHAMBER_CELL:
            return []
        return [(cell, d) for d in DIRS
                if st.placed_doors[cell] & d
                and (nb := neighbor(cell, d)) != -1 and st.grid[nb] < 0]

    def _frontier_doorways(self) -> list[tuple[int, int]]:
        """Every closed door across all reachable rooms (drives dead-end)."""
        st = self.state
        out = []
        for cell in self.reachable_cells():
            if st.grid[cell] < 0 or cell == ANTECHAMBER_CELL:
                continue
            for d in DIRS:
                if not st.placed_doors[cell] & d:
                    continue
                nb = neighbor(cell, d)
                if nb != -1 and st.grid[nb] < 0:
                    out.append((cell, d))
        return out

    def open_door(self, cell: int, direction: int) -> PendingDraft:
        """Draft (but do not enter) through a doorway of the current room.

        Drafting only deals a hand and, on :meth:`choose`, places a room; it
        costs no step and grants no resources. The player pays the step and
        receives the room's effects only when they :meth:`move` into it.
        """
        assert self.phase is Phase.NAVIGATE, "not in NAVIGATE phase"
        st = self.state
        assert cell == st.pos, "can only draft from the room you are standing in"
        assert st.placed_doors[cell] & direction, "no door in that direction"
        target = neighbor(cell, direction)
        assert target != -1 and st.grid[target] < 0, "invalid doorway"
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

    def _in_classroom_context(self) -> bool:
        room_idx = self.state.grid[self.state.pos]
        return room_idx >= 0 and self.registry.rooms[room_idx].id == "classroom"

    # --------------------------------------------------------- outer rooms

    def outer_draft_available(self) -> bool:
        return (self.cfg.outer_rooms_unlocked and not self.state.outer_room_drafted
                and self.phase is Phase.NAVIGATE
                and self.state.steps > self.cfg.outer_draft_step_cost)

    def open_outer_draft(self) -> PendingDraft:
        """Walk the West Path and draft 1 of 3 outer rooms (once per day).

        Outer rooms sit off the 5x9 grid; no rarity roll - the fixed pool of 8
        is shuffled and 3 are offered (wiki-documented mechanic).
        """
        assert self.outer_draft_available()
        key = (-1, 0)
        pending = self.doorway_drafts.get(key)
        if pending is None:
            outer = [r for r in self.registry.rooms if r.pool == "outer"]
            order = list(range(len(outer)))
            self.rng.shuffle("outer_draft", order)
            pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
            for slot, i in enumerate(order[:3]):
                room = outer[i]
                pending.options.append(DraftOption(
                    room_idx=room.idx, orientation=room.door_mask, gem_cost=0, slot=slot))
            self.doorway_drafts[key] = pending
        self.state.steps -= self.cfg.outer_draft_step_cost
        self.state.pending = pending
        self.phase = Phase.DRAFTING
        return pending

    def _choose_outer(self, opt) -> None:
        st = self.state
        room = self.registry.rooms[opt.room_idx]
        st.outer_room_drafted = True
        self.placed_ids.add(room.id)
        del self.doorway_drafts[(-1, 0)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        effects.fire(self, room, Hook.ON_PLACE)
        effects.fire(self, room, Hook.ON_ENTER)
        roll_room_items(st, self.registry, room, self.rng)
        self._check_termination()

    def choose(self, slot: int) -> None:
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

    def rotation_available(self) -> bool:
        """Can the current hand's floorplans be freely rotated?

        The Ornate Compass grants this on every draft while it is held; the
        Rotunda grants it while placed on the grid; the Dovecote grants it only
        while it is one of the drawn options. This overrides the random
        orientation roll - the player rotates the options at will.

        Outer-room drafts sit off the grid with a fixed orientation and no
        entry doorway (``target_cell == -1``), so rotation never applies there.
        """
        st = self.state
        if self.phase is not Phase.DRAFTING or st.pending is None:
            return False
        if st.pending.target_cell == -1:  # outer-room draft: no doorway to rotate against
            return False
        if self.cfg.ornate_compass or "rotunda" in self.placed_ids:
            return True
        return any(self.registry.rooms[o.room_idx].id == "dovecote"
                   for o in st.pending.options)

    def rotate_options(self) -> None:
        """Spin every drawn floorplan into its next legal orientation (clockwise)."""
        assert self.rotation_available(), "no rotation source in play"
        st = self.state
        pending = st.pending
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
        out = []
        for d in DIRS:
            nb = neighbor(st.pos, d)
            if nb != -1 and st.grid[nb] >= 0 and self._connected(st.pos, nb, d):
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
        """Directions of the shortest connected path from pos to target."""
        st = self.state
        if target == st.pos:
            return []
        prev: dict[int, tuple[int, int]] = {st.pos: (-1, -1)}
        q = deque([st.pos])
        while q:
            cell = q.popleft()
            for d in DIRS:
                nb = neighbor(cell, d)
                if nb == -1 or nb in prev or st.grid[nb] < 0:
                    continue
                if not self._connected(cell, nb, d):
                    continue
                prev[nb] = (cell, d)
                if nb == target:
                    dirs = []
                    cur = target
                    while cur != st.pos:
                        pcell, pdir = prev[cur]
                        dirs.append(pdir)
                        cur = pcell
                    dirs.reverse()
                    return dirs
                q.append(nb)
        return None

    # ---------------------------------------------------------------- internal

    def _place_room(self, room: Room, cell: int, orientation: int,
                    entered: bool = False) -> None:
        st = self.state
        st.grid[cell] = room.idx
        st.placed_doors[cell] = orientation
        st.entered[cell] = entered
        self.placed_ids.add(room.id)
        self.rooms_placed += 1
        self.deepest_rank = max(self.deepest_rank, rank_of(cell))
        effects.fire(self, room, Hook.ON_PLACE)
        # Relational draft hooks on every other placed room (Nursery etc.).
        for other_cell, idx in enumerate(st.grid):
            if idx >= 0 and other_cell != cell:
                effects.fire(self, self.registry.rooms[idx], Hook.ON_DRAFT_ROOM,
                             context_room=room)

    def _enter(self, cell: int) -> None:
        st = self.state
        if st.entered[cell]:
            return
        st.entered[cell] = True
        room = self.registry.rooms[st.grid[cell]]
        effects.fire(self, room, Hook.ON_ENTER)
        roll_room_items(st, self.registry, room, self.rng)

    def inject_rooms(self, room_ids: list[str]) -> None:
        inject_rooms(self.state, self.registry, room_ids, self.rng)

    def _terminate(self, reason: str) -> None:
        self.phase = Phase.TERMINAL
        self.termination_reason = reason

    def _check_termination(self) -> None:
        st = self.state
        # You win only by walking INTO the Antechamber, not by connecting a
        # door to it. Reaching it may cost the last step you have.
        if st.pos == ANTECHAMBER_CELL:
            self._terminate("antechamber")
        elif st.steps <= 0:
            self._terminate("out_of_steps")
        elif not self._frontier_doorways() and not self._antechamber_reachable():
            # No undrafted doors anywhere reachable and no path to walk into
            # the Antechamber: the day cannot progress.
            self._terminate("dead_end")

    def _antechamber_reachable(self) -> bool:
        return ANTECHAMBER_CELL in self.reachable_cells()

    # ------------------------------------------------------------------ info

    def is_done(self) -> tuple[bool, str]:
        return self.phase is Phase.TERMINAL, self.termination_reason

    def success(self) -> bool:
        return self.termination_reason == "antechamber"
