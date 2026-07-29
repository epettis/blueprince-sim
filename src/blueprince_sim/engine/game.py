"""Game orchestrator: the single API surface used by the env and the CLI."""

from __future__ import annotations

from collections import deque
from enum import Enum
from heapq import heappop, heappush

from ..config import GameConfig
from . import effects, shops, special_items
from .areas import GateContext, reachable
from .decks import apply_upgrade, build_decks, inject_rooms
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
from .upgrades import (SelectionContext, offer_variants, root_base_id,
                       select_slot, upgraded_slots)
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost

ANTECHAMBER_CELL = 42  # rank 9, center column


class Phase(Enum):
    NAVIGATE = 0
    DRAFTING = 1
    TERMINAL = 2
    UPGRADE_PENDING = 3


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
        st.special.enabled = cfg.special_items
        st.draft_counts = dict(cfg.draft_counts)
        st.applied_upgrades = set(cfg.upgrade_disks)
        st.pending_upgrade_slot = None
        st.pending_upgrade_options = ()
        self.state = st
        if cfg.special_items:
            for item_id in sorted(cfg.starting_items):
                special_items.grant(st, self.registry, item_id, source="config")
            # Cross-day discovery grants (Royal Scepter, Entrance Hall chip).
            shops.on_day_start(self)

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
        # Display names of every room drafted today, in draft order (the
        # pre-placed Entrance Hall and Antechamber are not drafts).
        self.drafted_rooms: list[str] = []

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
        fp = (st.pos, st.area, tuple(st.grid), tuple(st.placed_doors),
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
                    if not special_items.can_open_locked_free(self):
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
        if self.off_grid:
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
        if self.off_grid:
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
            return self.state.keys >= 1 or special_items.can_open_locked_free(self)
        if state == DOOR_SECURITY:
            return self.security_openable()
        return True

    def _open_segment(self, cell: int, direction: int) -> None:
        """Set the segment to DOOR_OPEN, bumping door_version to invalidate nav caches."""
        self.state.door_state[segment_key(cell, direction)] = DOOR_OPEN
        self.state.door_version += 1

    def _unlock_for_passage(self, cell: int, direction: int,
                            for_draft: bool = False) -> None:
        """Open the segment the player is about to pass, spending a key if locked.

        ``for_draft=True`` signals this is a frontier-draft opening (not movement):
        when the Silver Key is held, it is consumed instead of a regular key and
        the next deal is biased toward cross/t layouts.
        """
        st = self.state
        state = self.door_state_of(cell, direction)
        if state == DOOR_LOCKED:
            # Silver Key: consumed for drafting (not movement); does not return
            # to the spawn pool today (consumed=False keeps it pool-eligible tomorrow).
            if (for_draft and self.cfg.special_items
                    and special_items.has(st, "silver_key")):
                special_items.remove(st, "silver_key", consumed=False)
                st.special.silver_key_draft = True
            elif not (self.cfg.special_items and special_items.open_locked_free(self)):
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
                and not self.off_grid
                and self.state.pos == self._utility_closet_cell() >= 0)

    def set_keycard_power(self, on: bool) -> None:
        """Flip the breaker's "Keycard Entry" switch (free, like the real game)."""
        assert self.can_toggle_keycard_power(), "must stand in the Utility Closet"
        self.state.keycard_power_on = on

    def can_set_security_level(self) -> bool:
        """Standing at the Security terminal, on the grid, mid-day."""
        return (self.phase is Phase.NAVIGATE and self.cfg.door_locks
                and not self.off_grid
                and self.state.pos == self.room_cells.get("security", -1) >= 0)

    def set_security_level(self, level: str) -> None:
        """Set the security-door frequency (low/normal/high) at the terminal.

        Applies to doors rolled from now on; already-spawned doors keep their
        state. The daily spawn cap is checked at roll time, so raising the
        level mid-day re-opens headroom."""
        assert level in SECURITY_LEVELS, f"bad security level {level!r}"
        assert self.can_set_security_level(), "must stand in Security"
        self.state.security_level = level

    # ------------------------------------------------------------- commerce
    # Thin delegates into engine/shops.py (docs/special-items-design.md, PR2).
    # All shopping happens from menus in the real game: no step cost.

    def shop_stock(self) -> list | None:
        """Purchasable entries of the shop the player stands in (None if not
        in one); prices reflect sale days and a held Coupon Book."""
        return shops.stock_for(self)

    def buy(self, index: int) -> None:
        """Buy the current shop's stock entry ``index`` with coins."""
        assert self.cfg.special_items
        shops.buy(self, index)

    def trade_offers(self) -> list:
        """Trades available right now inside the Trading Post."""
        return shops.trade_offers(self)

    def trade(self, give_id: str) -> None:
        """Trade one held item at the Trading Post for its rolled return."""
        assert self.cfg.special_items
        shops.trade(self, give_id)

    def fabricate_options(self) -> list[str]:
        """Contraptions fabricable right now (in the Workshop, inputs held)."""
        return shops.fabricate_options(self)

    def fabricate(self, output_id: str) -> None:
        """Fabricate a contraption at the Workshop bench, consuming its inputs."""
        assert self.cfg.special_items
        shops.fabricate(self, output_id)

    def can_activate_scepter(self) -> bool:
        return shops.can_activate_scepter(self)

    def activate_scepter(self, color: str) -> None:
        """Pick the Royal Scepter's color for the day (once, irrevocable)."""
        assert self.cfg.special_items
        shops.activate_scepter(self, color)

    def can_smash_vase(self) -> bool:
        return shops.can_smash_vase(self)

    def smash_vase(self) -> None:
        """Smash the Entrance Hall's west vase with a Sledge Hammer (microchip)."""
        assert self.cfg.special_items
        shops.smash_vase(self)

    def can_open_container(self) -> bool:
        """At least one unopened container at the current cell can be opened."""
        return special_items.can_open_container(self, self.state.pos)

    def open_container(self) -> str | None:
        """Open the next container at the current cell; return what was granted."""
        assert self.cfg.special_items
        return special_items.open_container(self, self.state.pos)

    def can_open_car_trunk(self) -> bool:
        """Car Keys held, standing in the Garage, trunk not yet opened today."""
        return special_items.can_open_car_trunk(self)

    def open_car_trunk(self) -> list[str]:
        """Open the Garage car trunk with Car Keys."""
        assert self.cfg.special_items
        return special_items.open_car_trunk(self)

    def can_open_vault_box(self) -> bool:
        """A vault key is held, standing in the Vault, and the matching box is unopened."""
        return special_items.can_open_vault_box(self) is not None

    def open_vault_box(self) -> list[str]:
        """Open the vault deposit box for the first matching held vault key."""
        assert self.cfg.special_items
        return special_items.open_vault_box(self)

    def can_light(self) -> bool:
        """Holding an ignition tool (Torch/Burning Glass) in a lightable room."""
        return special_items.can_light(self)

    def light(self) -> None:
        """Light the ignition target in the current room; grant its rewards."""
        assert self.cfg.special_items
        special_items.light(self)

    def can_install_lever(self) -> bool:
        """Holding a Broken Lever in a machine room that hasn't been used today."""
        return special_items.can_install_lever(self)

    def install_lever(self) -> None:
        """Install the Broken Lever in the current machine room; apply its effect."""
        assert self.cfg.special_items
        special_items.install_lever(self)


    def can_use_repellent(self) -> bool:
        """Is using the Repellent available right now (held + NAVIGATE phase)?"""
        return shops.can_use_repellent(self)

    def use_repellent(self, room_id: str) -> None:
        """Consume a Repellent, banning ``room_id`` from the draft pool for 7 days.

        Illegal targets (entrance_hall, antechamber, room_46) are refused.
        The ban takes effect from the next day; today's decks are already built.
        """
        assert self.cfg.special_items
        shops.use_repellent(self, room_id)

    def carryover(self) -> dict:
        """Cross-day discoveries to feed into tomorrow's GameConfig."""
        return shops.carryover(self)

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
        self._unlock_for_passage(cell, direction, for_draft=True)
        key = (cell, direction)
        pending = self.doorway_drafts.get(key)
        if pending is None:
            pending = deal_draft(st, self.registry, self.cfg, self.rng,
                                 self.placed_ids, cell, direction, target)
            pending.redraws_left = st.drafting_room_count if self._in_classroom_context() else 0
            # Paper Crown: +1 free redraw on an all-non-red initial deal.
            # Hidden options are treated as potentially red (no crown bonus if any hidden).
            if (self.cfg.special_items and special_items.has(st, "paper_crown")
                    and not any(o.hidden for o in pending.options)
                    and all(self.registry.rooms[o.room_idx].category != "red"
                            for o in pending.options)):
                pending.redraws_left += 1
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

    @property
    def off_grid(self) -> bool:
        """True when the player is off the 5x9 grid (at the doorstep or inside an outer room)."""
        return self.state.area is not None

    @property
    def inside_outer_room(self) -> bool:
        """True when the player is physically inside today's drafted outer room."""
        outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
        return outer_room is not None and self.state.area == outer_room.id

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

    def _gate_ctx(self) -> GateContext:
        """Build the GateContext for area-graph traversal from current game state.

        Flags:
          "west_gate_unlatched" -- carried in from cfg, OR earned today the moment the
              player first reaches west_path (via the Garage route on a fresh save).
          "garage_door_breaker" -- Utility Closet placed and entered today (breaker on).
          "mine_south_visited" -- NOT modelled; never added here.
          "basement_sealed_entrance_return" -- NOT modelled; never added here.
        """
        st = self.state
        flags: set[str] = set()
        if self.cfg.west_gate_unlatched or st.west_gate_unlatched:
            flags.add("west_gate_unlatched")
        if self._breaker_on():
            flags.add("garage_door_breaker")
        # rooms_entered: grid cells entered today, plus the outer room if entered
        entered_room_ids: set[str] = set()
        for cell, was_entered in enumerate(st.entered):
            if was_entered and st.grid[cell] >= 0:
                entered_room_ids.add(self.registry.rooms[st.grid[cell]].id)
        if st.outer_room_entered:
            outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
            if outer_room is not None:
                entered_room_ids.add(outer_room.id)
        # outer_room_id: the drafted outer room id (None if not drafted yet today)
        outer_room_id: str | None = None
        if st.outer_room_drafted:
            outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
            if outer_room is not None:
                outer_room_id = outer_room.id
        return GateContext(
            held_items=st.inventory,
            flags=frozenset(flags),
            rooms_entered=frozenset(entered_room_ids),
            outer_room_id=outer_room_id,
        )

    def _grid_anchors(self) -> dict[str, int]:
        """Area node id -> grid cell for anchors currently reachable on the grid.

        "house" maps to ENTRANCE_CELL always.
        "garage" maps to the lowest garage cell only when the garage is placed.
        "the_foundation" has pool="none" and is never placed — excluded.
        """
        anchors: dict[str, int] = {"house": ENTRANCE_CELL}
        garage_cell = self._garage_cell()
        if garage_cell >= 0:
            anchors["garage"] = garage_cell
        return anchors

    def area_route_cost(self, dest: str) -> tuple[int, str] | None:
        """Cheapest total step cost to reach area node ``dest``, and the departure anchor id.

        On grid: runs BFS from each available anchor and picks the minimum of
        ``grid_distance[anchor_cell] + area_steps[dest]``, skipping anchors
        whose grid distance is -1 (unreachable). Tie-break: "house" first.
        Off grid: BFS from ``state.area`` in the area graph.
        Returns None when ``dest`` is unreachable.
        The departure anchor id is "" when the player is already off-grid.
        """
        graph = self.registry.area_graph
        ctx = self._gate_ctx()
        if self.off_grid:
            assert self.state.area is not None
            dist = reachable(graph, self.state.area, ctx)
            steps = dist.get(dest)
            if steps is None:
                return None
            return (steps, "")
        dist_grid = self.distance_map()
        best_cost: int | None = None
        best_anchor = ""
        # Try "house" first so ties break to Entrance Hall
        for anchor_id, anchor_cell in self._grid_anchors().items():
            g_dist = dist_grid[anchor_cell]
            if g_dist < 0:
                continue
            area_dist = reachable(graph, anchor_id, ctx)
            a_dist = area_dist.get(dest)
            if a_dist is None:
                continue
            cost = g_dist + a_dist
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_anchor = anchor_id
        if best_cost is None:
            return None
        return (best_cost, best_anchor)

    def travel_to(self, dest: str) -> None:
        """Pay steps and move the player to area-graph node ``dest``.

        On grid: walk to the departure anchor cell first (using existing move_to
        bookkeeping), then deduct the area-hop steps and set state.area.
        If the walk ends the day, aborts without setting area (caller must check).
        Off grid: deduct area-hop steps only.

        Special case — grid anchors ("house", "garage"):
        sets area=None and pos=<anchor cell>, then fires _enter() when the cell
        has not been entered yet (preserves ON_ENTER effects for the Garage).

        Special case — drafted outer room:
        when arriving at the today's outer room for the first time, marks it
        entered, fires ON_ENTER effects, rolls items, and runs special-item
        on_enter hooks (mirrors what the old enter_outer_room wrapper did).
        """
        result = self.area_route_cost(dest)
        assert result is not None, f"area node {dest!r} is not reachable"
        _cost, anchor_id = result
        st = self.state

        if self.off_grid:
            origin = st.area
        else:
            # Walk to the departure anchor first, on the grid and on the grid's budget.
            anchor_cell = self._grid_anchors()[anchor_id]
            if anchor_cell != st.pos:
                self.move_to(anchor_cell)
            if self.phase is not Phase.NAVIGATE:
                return  # walk ended the day; caller must check phase
            origin = anchor_id

        # Recomputed after the walk, because move_to may have entered rooms and so
        # changed the gate context.  Gates only ever OPEN as a day progresses (entering
        # a room adds flags and rooms_entered, never removes them), so dest cannot have
        # become unreachable in the meantime.  Assert instead of defaulting the distance
        # to 0, which would silently make an impossible move free.
        assert origin is not None
        area_dist = reachable(self.registry.area_graph, origin, self._gate_ctx())
        area_hop = area_dist.get(dest)
        assert area_hop is not None, f"area node {dest!r} unreachable from {origin!r}"
        st.steps -= area_hop

        anchors = self._grid_anchors()
        if dest in anchors:
            # Destination is a grid anchor, so the player lands back on the grid.
            dest_cell = anchors[dest]
            st.areas_visited.add(dest)  # grid anchors are area nodes too
            st.area = None
            st.pos = dest_cell
            if not st.entered[dest_cell]:
                self._enter(dest_cell)  # returning into a never-entered room fires ON_ENTER
        else:
            st.area = dest
            st.areas_visited.add(dest)
            # The west gate unlatches from the inside on the player's FIRST arrival
            # at west_path — which must come via the Garage route on a fresh save.
            # Afterwards the 2-step Grounds shortcut is permanently open; DayChain
            # carries it across days.  Recorded on STATE, never written back to cfg:
            # one config object is shared by every episode of a worker, so mutating
            # it would leak the unlock into later "fresh save" episodes.
            if dest == "west_path":
                st.west_gate_unlatched = True
            # Fire ON_ENTER the first time the player enters the drafted outer room.
            outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
            if (outer_room is not None and dest == outer_room.id
                    and not st.outer_room_entered):
                st.outer_room_entered = True
                effects.fire(self, outer_room, Hook.ON_ENTER)
                roll_room_items(st, self.registry, outer_room, self.rng)
                if self.cfg.special_items:
                    # Outer rooms spawn special items too (Toolshed's Gear Wrench,
                    # the Trading Post pool); -1 = off-grid, no cell hooks apply.
                    special_items.on_enter(self, outer_room, -1)
                    if outer_room.category == "shop":
                        shops.on_enter_shop(self, outer_room)
        self._check_termination()

    def _outer_route_cost(self) -> int | None:
        """Cheapest available route cost to the outer-area doorstep ("west_path").

        Returns the step cost or None if no affordable route exists.
        Requires steps > cost (strict) so at least 1 step remains after arriving.
        """
        result = self.area_route_cost("west_path")
        if result is None:
            return None
        cost, _ = result
        return cost if self.state.steps > cost else None

    def outer_draft_available(self) -> bool:
        """Can the once-per-day outer-room draft be started right now?

        Requires no outer room drafted yet today, NAVIGATE phase on the grid,
        and an affordable route to the doorstep (see :meth:`_outer_route_cost`).

        No config flag is checked: on a fresh save the Garage + breaker route
        to west_path is open from day 1 without any unlock. The west_gate_unlatched
        config field only opens the Grounds<->West Path shortcut, it does not gate
        the draft itself.
        """
        if self.state.outer_room_drafted:
            return False
        if self.phase is not Phase.NAVIGATE:
            return False
        if self.off_grid:
            return False
        return self._outer_route_cost() is not None

    def open_outer_draft(self) -> PendingDraft | None:
        """Walk to the outer-area doorstep and open the once-per-day outer-room draft.

        Outer rooms sit off the 5x9 grid; no rarity roll - the fixed pool of 8
        is shuffled and 3 are offered (wiki-documented mechanic).
        """
        assert self.outer_draft_available()
        self.travel_to("west_path")
        st = self.state
        if self.phase is not Phase.NAVIGATE:
            return None  # walk ended the day
        if self.cfg.special_items:
            # The West Path chip sits at the doorstep (same walking cost as
            # the Outer Room door): carry-over grant or first-time dig.
            shops.on_doorstep(self)

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
        self.drafted_rooms.append(room.name)
        del self.doorway_drafts[(-1, 0)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        effects.fire(self, room, Hook.ON_PLACE)
        # Player stays at the doorstep (area == "west_path"); ON_ENTER fires when they enter.
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
        """Gem cost of an option: slot 0 and free-category rooms cost nothing.

        Held items can waive or modify the remaining cost (Emerald Bracelet,
        Hall Pass, Stopwatch — see special_items.gem_cost_modifier)."""
        if opt.slot == 0:
            return 0
        if room.category in self.free_categories:
            return 0
        cost = resolve_gem_cost(room, self.state, self.registry.rooms)
        if self.cfg.special_items:
            cost = special_items.gem_cost_modifier(self, room, cost)
        return cost

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
        """Deduct the option's gem cost - in steps at 3:1 when the Hovel is placed.

        An active Stopwatch waives the payment (gems still required in hand;
        the waiver spends a charge here, at pay time, so affordability
        queries never consume it)."""
        cost = self._effective_cost(room, opt)
        if cost <= 0:
            return
        if self.cfg.special_items and special_items.stopwatch_waives_gems(self, cost):
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
        if special_items.ornate_compass_active(self) or "rotunda" in self.placed_ids:
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
        if self.off_grid:
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
        cost = 1
        if self.cfg.special_items:
            cost = special_items.move_step_cost(
                self, st.pos, direction, self.registry.rooms[st.grid[nb]])
        st.steps -= cost
        st.pos = nb
        self._enter(nb)
        if self.cfg.special_items:
            special_items.on_arrive(self, nb)
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
        if not entered:  # entered=True is only the pre-placed Entrance Hall; skip draft counting for it
            self.drafted_rooms.append(room.name)
            root_id = root_base_id(self.registry, room)
            self.state.draft_counts[root_id] = self.state.draft_counts.get(root_id, 0) + 1
        effects.fire(self, room, Hook.ON_PLACE)
        if self.cfg.special_items:
            special_items.on_place(self, room, cell)
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
        if self.cfg.special_items:
            special_items.on_enter(self, room, cell)
            if room.category == "shop" or room.id == "workshop":  # workshop needs first-entry roll
                shops.on_enter_shop(self, room)
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

    # ---------------------------------------------------------- upgrade disks

    def catacombs_unlocked(self) -> bool:
        """True when today's outer room grants Catacombs access AND has been entered today.

        The Catacombs are unlocked by drafting and physically entering the Tomb on the same
        day: the sim assumes the player solves any puzzle in a room they enter, so entering
        the Tomb solves the angel-statue puzzle. Same-day physical access is still required
        (owner decision 2026-07-27). The flag is NOT a permanent carry-over.
        """
        outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
        return (
            outer_room is not None
            and outer_room.unlocks_catacombs
            and self.state.outer_room_entered
        )

    def disk_reader_here(self) -> bool:
        """True when the player's current location has an Upgrade Disk terminal.

        Checks the grid room at the player's cell, or the outer room when inside it
        (inside_outer_room is True), since Shelter is an outer room with a terminal.
        """
        if self.inside_outer_room:
            outer_room = next((r for r in self.outer_rooms if r.id in self.placed_ids), None)
            return outer_room is not None and outer_room.disk_reader
        st = self.state
        if 0 <= st.pos < len(st.grid) and st.grid[st.pos] >= 0:
            return self.registry.rooms[st.grid[st.pos]].disk_reader
        return False

    def held_disk_ids(self) -> list[str]:
        """Item ids starting with 'upgrade_disk_', sorted for deterministic consumption order."""
        return sorted(
            item_id for item_id in self.state.inventory if item_id.startswith("upgrade_disk_")
        )

    def can_insert_disk(self) -> bool:
        """True when inserting a disk is a legal action right now."""
        return (
            self.phase is Phase.NAVIGATE
            and self.disk_reader_here()
            and bool(self.held_disk_ids())
        )

    def insert_disk(self) -> bool:
        """Insert the first held Upgrade Disk, triggering the selection algorithm.

        Builds a SelectionContext, calls select_slot, and if a slot is selectable
        consumes the disk, sets pending_upgrade_slot and pending_upgrade_options,
        and advances phase to UPGRADE_PENDING. Returns True if the disk was
        inserted (phase changed), False if no slot was selectable (disk NOT consumed).

        Inserting a disk costs no step and has no per-day limit — the wiki
        mentions neither constraint.
        """
        assert self.can_insert_disk(), "must hold a disk and stand at a disk reader"
        st = self.state
        ctx = SelectionContext(
            upgraded_slots=upgraded_slots(frozenset(st.applied_upgrades), self.registry),
            draft_counts=st.draft_counts,
            veteran=self.cfg.veteran_mode,
            day=self.cfg.day,
            catacombs_unlocked=self.catacombs_unlocked(),
        )
        slot = select_slot(self.registry.upgrade_tables, ctx, self.rng)
        if slot is None:
            return False

        # Consume the first held disk (sorted order is deterministic)
        disk_ids = self.held_disk_ids()
        special_items.remove(st, disk_ids[0], consumed=True)

        options = offer_variants(slot, frozenset(st.applied_upgrades), self.registry, self.rng)
        st.pending_upgrade_slot = slot
        st.pending_upgrade_options = tuple(options)
        self.phase = Phase.UPGRADE_PENDING
        return True

    def choose_upgrade(self, index: int) -> None:
        """Choose one of the three offered upgrade variants.

        Only legal in UPGRADE_PENDING with 0 <= index < 3. Adds the chosen
        variant to applied_upgrades, calls apply_upgrade on the live decks,
        clears the pending fields, and returns phase to NAVIGATE.
        """
        assert self.phase is Phase.UPGRADE_PENDING, "choose_upgrade only legal in UPGRADE_PENDING"
        assert 0 <= index < 3, f"index must be 0, 1, or 2; got {index}"
        st = self.state
        variant_id = st.pending_upgrade_options[index]
        st.applied_upgrades.add(variant_id)
        apply_upgrade(st, self.registry, variant_id, self.rng)
        st.pending_upgrade_slot = None
        st.pending_upgrade_options = ()
        self.phase = Phase.NAVIGATE

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
        elif self.off_grid:
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
        """True if any action is affordable while the player is off-grid.

        Checks whether the player can travel to any reachable destination with
        at least one step to spare on arrival (strict: steps > cost), using the
        same affordability contract as the travel action mask.
        """
        st = self.state
        graph = self.registry.area_graph
        for node_id in graph.nodes:
            if node_id == st.area:
                continue  # no self-travel
            result = self.area_route_cost(node_id)
            if result is not None and st.steps > result[0]:
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
