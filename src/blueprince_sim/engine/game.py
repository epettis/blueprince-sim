"""Game orchestrator: the single API surface used by the env and the CLI."""

from __future__ import annotations

from collections import deque
from enum import Enum
from heapq import heappop, heappush

from ..config import GameConfig
from . import constellations, effects, experiments, shops, special_items
from .areas import GateContext, path, reachable
from .decks import apply_upgrade, build_decks, inject_rooms, set_dynamic_rarity
from .draft import (COLOUR_CATEGORIES, SECRET_PASSAGE_IDS, DraftContext, deal_draft,
                    redeal, waive_first_option, _pick_dowsing_slot)
from .effects import Capability, Hook
from .effects.items import (basement_key, crown_of_the_blueprints, gear_wrench, keycard,
                            master_key, paper_crown, power_hammer, prism_key, running_shoes,
                            silver_key, telescope, the_axe)
from .effects.rooms import dovecote, foyer, mail_room, office, pump_room, shrine
from .effects.tier1 import _grant
from .grid import (ADJACENT, DIRS, E, ENTRANCE_CELL, N, N_CELLS, OPPOSITE, W,
                   neighbor, rank_of, rotate_mask)
from .items import EXTRA_ITEM_TABLE, grant_item, roll_room_items
from .locks import (DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, DOOR_SECURITY, SECURITY_LEVELS,
                    roll_segment, segment_key)
from .locks import security_openable as _security_openable
from .model import RARITIES, Registry, Room
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
    EXPERIMENT_PENDING = 4
    COLOUR_PENDING = 5  # Secret Passage: awaiting a colour pick before the hand is dealt
    LOCK_PENDING = 6  # locked doorway: awaiting use_key/lockpick/a special key/abandon
    WRENCH_PENDING = 7  # Gear Wrench: awaiting a permanent rarity pick for the Mechanical
                        # Room just placed (Game.choose/Game.set_wrench_rarity)
    PUMP_LEVEL_PENDING = 8  # Pump Room panel: a source has been picked, awaiting its
                            # target level (Game.set_pump_source/Game.set_pump_level)


class RedrawKind(Enum):
    STUDY = "study"     # costs 1 gem, max 8 per draft
    FREE = "free"       # Classroom-style free redraws
    DIE = "die"         # spend 1 ivory die
    STAR = "star"       # spend 1 permanent star (the Ink Well), no per-draft cap


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
        st.steps = (cfg.starting_steps + (20 if cfg.orchard_unlocked else 0)
                    + (20 if cfg.sauna_bonus else 0))
        st.gems = ((2 if cfg.mine_unlocked else 0) + (2 if cfg.morning_room_bonus else 0)
                   + cfg.frozen_gems)
        st.keys = cfg.clock_tower_tomorrow_keys
        # The allowance packet: the sim assumes the player is already standing in
        # the Entrance Hall at reset(), so the daily gold packet is granted here
        # unconditionally rather than modelled as a pickup action -- adding zero
        # when cfg.allowance is 0 reproduces "the packet only appears when
        # nonzero" without a branch. state.allowance tracks the permanent total
        # separately from today's spendable coins.
        st.coins = cfg.frozen_coins + cfg.allowance
        st.allowance = cfg.allowance
        st.stars = cfg.stars
        st.stars_at_day_start = cfg.stars
        st.experiment.letters_delivered = cfg.letters_delivered
        st.has_keycard = cfg.break_room_keycard
        st.day = cfg.day
        st.stage = cfg.resolved_stage()
        st.luck = self.registry.item_rules["luck"]["day_start"]
        st.luck_penalty = 0  # owner-ruled per-day (see GameState.luck_penalty)
        st.decks = build_decks(self.registry, cfg, self.rng)
        st.special.enabled = cfg.special_items
        st.draft_counts = dict(cfg.draft_counts)
        st.applied_upgrades = set(cfg.upgrade_disks)
        st.axed_rooms = tuple(cfg.axed_rooms)
        st.permanent_rarity = dict(cfg.permanent_rarity)
        st.water_levels = dict(cfg.water_levels)
        st.payroll_last_used = dict(cfg.payroll_last_used)
        st.planetarium_planets = tuple(cfg.planetarium_planets)
        # Seeds today's dynamic_rarity bucket bookkeeping with every
        # Gear-Wrench-set override, right after build_decks (which already
        # placed each wrenched room's cards in the matching bucket via this
        # same cfg dict) -- so decks.set_dynamic_rarity/inject_rooms/
        # inject_rooms_undealt's own dynamic_rarity fallback agrees with
        # build_decks from the first deal onward, and a same-day battery_pack/
        # Conservatory override on the SAME room is a transient overlay on
        # top of this permanent baseline (the wiki-documented, deliberately
        # unfixed Conservatory conflict -- see data/special_items.json's
        # gear_wrench meta.notes), not a corruption of it.
        st.dynamic_rarity = dict(cfg.permanent_rarity)
        st.pending_upgrade_slot = None
        st.pending_upgrade_options = ()
        st.shrine_blessing_id = cfg.shrine_blessing_id
        st.shrine_blessing_days = cfg.shrine_blessing_days
        st.shrine_curse_days = cfg.shrine_curse_days
        st.shrine_offered_coins = cfg.shrine_offered_coins
        st.shrine_monk_room = cfg.shrine_monk_room
        self.state = st
        # Blessing of the Gardener: 8 Courtyards, re-injected fresh every day the
        # blessing is active (decks are rebuilt from scratch every reset(), unlike
        # the day-count carry-over itself).
        shrine.apply_gardener_injection(self)
        # Seed the config-carried running values (mail cycle and transit days,
        # tithes, permanently gated item ids) before anything reads them, so the
        # day's first observation reports what was carried, not the field defaults.
        special_items.configure(st, cfg, self.registry)
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
        self.rotunda_placed = False  # Rotunda: free floorplan rotation while placed
        self.doorway_drafts: dict[tuple[int, int], PendingDraft] = {}
        # Extra keys (beyond the base 1) a locked segment costs to open, keyed by
        # locks.segment_key -- currently only an always-locked room's side doorways
        # (Great Hall) via locks.roll_segment; a missing entry means 0 extra. Read
        # by lock_open_cost; mutated only from _roll_new_segments.
        self.door_search_cost: dict[tuple[int, int], int] = {}
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
        # day (sealed until a drafted room connects a door to it). With
        # antechamber_levers=True its West/South/East doorways start SEALED
        # (impassable until the matching lever room is entered that day);
        # False reproduces the old open-door model for baseline comparisons.
        ante = self.registry.by_id["antechamber"]
        st.grid[ANTECHAMBER_CELL] = ante.idx
        st.placed_doors[ANTECHAMBER_CELL] = 0xF
        self.placed_ids.add(ante.id)
        self.room_cells[ante.id] = ANTECHAMBER_CELL
        # The Antechamber's doorways roll like any other (rank 8<->9 sits at
        # 130% base chance, so at bias 1 they start locked): walking in
        # normally costs a key, mirroring the real game's locked Antechamber.
        self._roll_new_segments(ante, ANTECHAMBER_CELL, 0xF)
        # Lever gate: West (41,E), South (37,N), East (43,W) start SEALED.
        # The sealed state overrides any lock roll on those segments.
        if cfg.antechamber_levers:
            for seg in (
                segment_key(41, E),  # West: Antechamber's W door, via col 1
                segment_key(37, N),  # South: Antechamber's S door, via rank 8 center
                segment_key(43, W),  # East: Antechamber's E door, via col 3
                segment_key(ANTECHAMBER_CELL, N),  # North: off-grid door to Room 46
            ):
                st.door_state[seg] = DOOR_SEALED
                st.door_version += 1

        # The Foundation does not reset day-to-day: once drafted (cfg.foundation_cell
        # set on an earlier day), re-place it at the same cell/orientation before the
        # day starts, same as the Entrance Hall / Antechamber above. Landing in
        # placed_ids/room_cells is what keeps it out of today's deck (the existing
        # one-copy-on-the-grid rule in draft.py::room_draftable) - no second exclusion
        # mechanism. Not entered: the player still has to walk there to collect
        # anything, so ON_ENTER must not fire here.
        if cfg.foundation_cell >= 0:
            foundation = self.registry.by_id["the_foundation"]
            st.grid[cfg.foundation_cell] = foundation.idx
            st.placed_doors[cfg.foundation_cell] = cfg.foundation_doors
            self._roll_new_segments(foundation, cfg.foundation_cell, cfg.foundation_doors)
            self.placed_ids.add(foundation.id)
            self.room_cells[foundation.id] = cfg.foundation_cell
        self._map_cache: tuple[tuple, dict] = ((), {})

    # ------------------------------------------------------------ connectivity

    def _connected(self, a: int, b: int, d: int) -> bool:
        """True if rooms at a and b share a usable door pair across direction d."""
        st = self.state
        return bool(st.placed_doors[a] & d) and bool(st.placed_doors[b] & OPPOSITE[d])

    def _maps(self) -> dict:
        """Memo dict for the BFS map functions, valid for the current layout.

        Keyed on a fingerprint of everything those functions read (player
        position, outer-area location, grid, door masks, keys, security
        access, and which cells have been entered - the last because a lever
        room's key drain only fires on first entry), so any state change -
        including tests poking ``state`` directly - starts a fresh dict.
        Cached values are shared between callers and must not be mutated.
        """
        st = self.state
        fp = (st.pos, st.area, tuple(st.grid), tuple(st.placed_doors),
              st.door_version, st.keys, self.security_openable(), tuple(st.entered))
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
        no keys the detour distance is what counts against the budget. Walking
        into an unentered lever room (see :meth:`lever_key_cost`) also drains
        a key on arrival, before any locked door further along the path, so
        that drain is charged to the route too.
        In-drafting keeps every naturally formed placed-room door pair open
        today, but honest distances here are groundwork for rooms that
        re-lock their own doors (Vestibule, not yet modeled).

        Returns (dist, key_cost, prev): per-cell walking distance (-1 empty
        or unreachable within the key budget), keys spent along the recorded
        shortest path (locked doors plus any lever-room drains), and the
        predecessor map used by :meth:`_path_dirs` - so a path promised here
        is always affordable in keys when walked.

        Results are cached; treat them as read-only.
        """
        maps = self._maps()
        cached = maps.get("nav")
        if cached is not None:
            return cached
        st = self.state
        grid, doors, door_state = st.grid, st.placed_doors, st.door_state
        search_cost = self.door_search_cost
        locked_and_drains = (
            sum(1 + search_cost.get(k, 0) for k, v in door_state.items() if v == DOOR_LOCKED)
            + sum(1 for c in range(N_CELLS) if not st.entered[c] and self.lever_key_cost(c))
        )
        keys_cap = min(st.keys, locked_and_drains)
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
                if seg == DOOR_SEALED:
                    continue  # sealed: impassable regardless of keys
                if seg == DOOR_LOCKED:
                    if not special_items.can_open_locked_free(self):
                        nspent = spent + 1 + search_cost.get(segment_key(cell, d), 0)
                        if nspent > keys_cap:
                            continue
                elif seg == DOOR_SECURITY and not sec_ok:
                    continue
                # Walking into a lever room drains a key on arrival (the Great Hall's
                # prize door). It never blocks passage - with nothing left to spend the
                # lever simply is not pulled - but it is spent BEFORE any locked door
                # further along the path, so the walk has to carry it.
                if not st.entered[nb]:
                    drain = self.lever_key_cost(nb)
                    if drain:
                        nspent = min(nspent + drain, keys_cap)
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

        Covers both locked segments crossed and any unentered lever room's
        on-arrival key drain (see :meth:`lever_key_cost`), so the number here
        is exactly what :meth:`move_to` would deduct from ``st.keys``.
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

        Door STATE is deliberately ignored here — locked, security and sealed
        segments are all treated as passable. This map answers "could a route
        exist at best?", which is what the navigation signal and the shaped
        reward's potential need; the costs of actually opening a door belong to
        the real traversal in ``_nav_bfs`` / ``doorway_passable``. Honouring the
        Antechamber's sealed doors here made it read as unreachable from day
        one, which flattened the reward gradient toward rank 9 and dropped the
        measured win rate to exactly zero.

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

    def grid_frontier_doorways(self) -> list[tuple[int, int]]:
        """Every closed door across all reachable rooms, wherever the player is.

        A property of the HOUSE, not of the player: walking off the 5x9 grid
        into an outer area does not change which doorways are still open, so
        this deliberately has no ``off_grid`` early return.  Callers that need
        "what can I draft right now" want :meth:`frontier_doorways` instead;
        callers reasoning about the house's connectivity (env/rewards.py's
        path-preservation and frontier potentials) want this one.

        ``reachable_cells`` is likewise ungated: it BFSes from ``state.pos``,
        which keeps the player's last on-grid cell for the whole of an
        off-grid excursion, so this list is unchanged by stepping outside.

        Returns a cached list; treat it as read-only.
        """
        st = self.state
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

    def frontier_doorways(self) -> list[tuple[int, int]]:
        """The draft targets of :meth:`draft_from`; also drives dead-end detection.

        Empty while off-grid: there is nothing to draft from out in an outer
        area.  That is a restriction on what the player may DO right now, not
        a statement about the house — see :meth:`grid_frontier_doorways`, of
        which this is the position-gated view.

        Returns a cached list; treat it as read-only.
        """
        if self.off_grid:
            return []
        return self.grid_frontier_doorways()

    # ------------------------------------------------------- locks & security

    def door_state_of(self, cell: int, direction: int) -> int:
        """Lock state of the doorway segment (DOOR_OPEN/LOCKED/SECURITY)."""
        return self.state.door_state.get(segment_key(cell, direction), DOOR_OPEN)

    def security_openable(self) -> bool:
        """Can security doors be opened right now (keycard/power/offline mode)?"""
        return _security_openable(self.state)

    def lock_open_cost(self, cell: int, direction: int) -> int:
        """Keys a locked segment costs to open: the base 1, plus an always-locked
        room's side-doorway search surcharge (locks.json's side_search_cost, see
        :meth:`_roll_new_segments`) if this segment rolled one. 0 for a segment
        that is not currently DOOR_LOCKED."""
        if self.door_state_of(cell, direction) != DOOR_LOCKED:
            return 0
        return 1 + self.door_search_cost.get(segment_key(cell, direction), 0)

    def doorway_passable(self, cell: int, direction: int) -> bool:
        """Can the doorway be WALKED through from where it stands: a locked
        door with enough keys in hand, a security door while the system
        allows it, or any open/unlocked door. Path key costs are the
        caller's concern (see :meth:`key_cost_map`). This is the MOVEMENT
        precondition (:meth:`move`'s ``_unlock_for_passage(for_draft=False)``
        auto-cascade into an already-placed room, e.g. walking into the
        Antechamber) -- for trying a FRESH frontier doorway (drafting), see
        :meth:`frontier_doorway_triable` instead: trying a locked door there
        is always free (Phase.LOCK_PENDING), so it does not budget keys."""
        state = self.door_state_of(cell, direction)
        if state == DOOR_SEALED:
            return False  # sealed: impassable, no item or key can open it
        if state == DOOR_LOCKED:
            return (self.state.keys >= self.lock_open_cost(cell, direction)
                    or special_items.can_open_locked_free(self))
        if state == DOOR_SECURITY:
            return self.security_openable()
        return True

    def frontier_doorway_triable(self, cell: int, direction: int) -> bool:
        """Can this frontier doorway (a placed room's boundary to an empty
        cell) be TRIED right now, i.e. is :meth:`open_door` legal on it?

        DOOR_SEALED: never. DOOR_SECURITY: only while the keycard system
        allows it (unaffected by this PR -- no menu, same as always).
        DOOR_LOCKED and DOOR_OPEN: always -- trying a locked door costs
        nothing and is how the player finds out it's locked at all
        (Phase.LOCK_PENDING); no key is budgeted here. The single source
        both :func:`env.actions.action_mask`'s OPEN_BASE range and
        :meth:`draft_from` read, so the two cannot silently diverge (the
        precise class of drift that produced the bug this feature fixes --
        see the Silver Key's old, unconditional auto-spend).
        """
        state = self.door_state_of(cell, direction)
        if state == DOOR_SEALED:
            return False
        if state == DOOR_SECURITY:
            return self.security_openable()
        return True

    def _open_segment(self, cell: int, direction: int) -> None:
        """Set the segment to DOOR_OPEN, bumping door_version to invalidate nav caches."""
        self.state.door_state[segment_key(cell, direction)] = DOOR_OPEN
        self.state.door_version += 1

    def _lock_segment(self, cell: int, direction: int) -> None:
        """Set the segment to DOOR_LOCKED, bumping door_version to invalidate nav caches."""
        self.state.door_state[segment_key(cell, direction)] = DOOR_LOCKED
        self.state.door_version += 1

    def _open_north_door(self) -> None:
        """Open the Antechamber's north segment and record the per-day reward event.

        The single call site for both north-door levers (Inner Sanctum in
        :meth:`travel_to`, Throne Room in ``effects.rooms.throne_room.pull_north_lever``),
        so they cannot drift.  Sets ``state.north_door_opened`` here — at the lever, not derived
        from the segment's door state — so env/rewards.py can pay NORTH_DOOR_REWARD
        exactly once without paying it "for free" under antechamber_levers=False,
        where the segment is never sealed to begin with. Also the single call
        site for the north lever's own antechamber_lever_pull firing (see
        experiments.on_lever_pulled) -- same reasoning, so the packet trigger
        cannot double-fire off two independent north-lever call sites either.
        """
        self._open_segment(ANTECHAMBER_CELL, N)
        self.state.north_door_opened = True
        experiments.on_lever_pulled(self, ANTECHAMBER_CELL, N)

    def _unlock_for_passage(self, cell: int, direction: int,
                            for_draft: bool = False) -> None:
        """Open the segment the player is about to pass, spending a key if locked.

        ``for_draft=True`` signals this is a frontier-draft opening (not movement):
        when the Silver Key is held, it is consumed instead of a regular key and
        the next deal is biased toward cross/t layouts. It also gates the
        security_door experiment trigger (site A): the wiki's "just unlocking
        security doors is not enough, a security door must be drafted from" --
        ``open_door`` passes ``for_draft=True``, ``move`` does not.
        """
        st = self.state
        state = self.door_state_of(cell, direction)
        if state == DOOR_LOCKED:
            # Silver Key: consumed for drafting (not movement). consumed=False
            # leaves it out of state.special.removed, which is the only thing
            # _is_available consults -- so it returns to the spawn pool
            # immediately and can be obtained again the same day.
            # open_locked_free (Master Key / Stopwatch / Lock Pick Kit) waives
            # the search surcharge along with the base key.
            used_silver_key = (for_draft and self.cfg.special_items
                                and silver_key.consume_for_draft(st))
            if not used_silver_key and not (self.cfg.special_items
                                             and special_items.open_locked_free(self)):
                cost = self.lock_open_cost(cell, direction)
                assert st.keys >= cost, f"door is locked and costs {cost} keys; holding {st.keys}"
                st.keys -= cost
            self._open_segment(cell, direction)
        elif state == DOOR_SECURITY:
            assert self.security_openable(), "security door cannot be opened"
            self._open_segment(cell, direction)
            # Idempotent by construction: ``state`` was read once, above, before
            # the segment was opened, so a second call on an already-open segment
            # takes neither branch here and cannot double-fire.
            if for_draft and st.experiment.trigger_id == "security_door":
                experiments.trigger_success(self)

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

    def can_toggle_darkroom_lights(self) -> bool:
        """Standing at the Utility Closet breaker box, on the grid, mid-day."""
        return (self.phase is Phase.NAVIGATE and self.cfg.door_locks
                and not self.off_grid
                and self.state.pos == self._utility_closet_cell() >= 0)

    def set_darkroom_lights(self, on: bool) -> None:
        """Flip the breaker's "Darkroom" switch (free, like the real game).

        Takes effect immediately for any doorway drafted from the Darkroom
        afterward (engine/draft.py reads the switch live); does not retroactively
        change a hand already dealt. See effects/rooms/darkroom.py for the
        first-entry fuse-blow this switch guards against.
        """
        assert self.can_toggle_darkroom_lights(), "must stand in the Utility Closet"
        self.state.darkroom_lights_on = on

    def can_set_security_level(self) -> bool:
        """Standing at the Security terminal, on the grid, mid-day."""
        return (self.phase is Phase.NAVIGATE and self.cfg.door_locks
                and not self.off_grid
                and self.state.pos == self._capability_cell(Capability.SECURITY_LEVEL) >= 0)

    def set_security_level(self, level: str) -> None:
        """Set the security-door frequency (low/normal/high) at the terminal.

        Applies to doors rolled from now on; already-spawned doors keep their
        state. The daily spawn cap is checked at roll time, so raising the
        level mid-day re-opens headroom."""
        assert level in SECURITY_LEVELS, f"bad security level {level!r}"
        assert self.can_set_security_level(), "must stand in Security"
        self.state.security_level = level

    # ------------------------------------------------------- Office terminal
    # docs/rooms.md (owner rulings): the Office runs two
    # independent terminal processes, both gated on standing at the same
    # ``Capability.OFFICE_TERMINAL`` cell -- see effects/rooms/office.py.

    def can_spread_gold(self) -> bool:
        """Standing at the Office terminal, on the grid, mid-day, not yet used today."""
        return (self.phase is Phase.NAVIGATE and not self.off_grid
                and self.state.pos == self._capability_cell(Capability.OFFICE_TERMINAL) >= 0
                and not self.state.special.office_spread_gold_used)

    def spread_gold(self) -> None:
        """Spread Gold in Estate: a random 3/4/5-coin pile into every currently
        drafted room (including the Office), once per day -- see office.spread_gold."""
        assert self.can_spread_gold(), "must stand in the Office, once per day"
        office.spread_gold(self)

    def can_run_payroll(self) -> bool:
        """Standing at the Office terminal, on the grid, mid-day, weekly cooldown elapsed."""
        return (self.phase is Phase.NAVIGATE and not self.off_grid
                and self.state.pos == self._capability_cell(Capability.OFFICE_TERMINAL) >= 0
                and office.payroll_available(self.state.payroll_last_used, self.cfg.day))

    def run_payroll(self) -> None:
        """Run Payroll: 5-coin piles for the Maid's Chamber and Servant's
        Quarters, paid on arrival whenever each is drafted and entered --
        see office.run_payroll. NOT a spread (no Conference Room redirect)."""
        assert self.can_run_payroll(), "must stand in the Office, cooldown must have elapsed"
        office.run_payroll(self)

    def _payroll_carryover(self) -> dict:
        """Cross-day carry for Run Payroll's weekly cooldown record.

        Reports the FULL current dict every day (state.payroll_last_used is
        seeded from cfg.payroll_last_used at reset() and only ever changed
        by office.run_payroll), the same "state already IS the accumulated
        total" shape as _pump_carryover's water_levels -- also NOT
        SAVE-scoped, so DayChain.advance() resets it at the attempt wrap.
        """
        return {"payroll_last_used": dict(self.state.payroll_last_used)}

    # --------------------------------------------------------- pump room panel
    # docs/areas.md's Pump Room section (owner ruling): the macro "set source
    # to level" action -- the player picks a source, then a target level, in
    # two decisions -- reaches every level the real (tank/pump) panel can reach.

    def _pump_source(self, source_id: str) -> pump_room.PumpSource | None:
        """The named water source's PumpSource record, or None if unknown."""
        for src in pump_room.load_sources(self.registry.data_dir):
            if src.id == source_id:
                return src
        return None

    def water_level(self, source_id: str) -> int:
        """Current level of ``source_id`` (0 for an unknown id).

        ``state.water_levels`` only ever records OVERRIDES (set by
        ``set_pump_level``); a source never touched this attempt falls back
        to its data/pump_room.json "initial" value.
        """
        if source_id in self.state.water_levels:
            return self.state.water_levels[source_id]
        src = self._pump_source(source_id)
        return src.initial if src is not None else 0

    def can_set_pump_source(self) -> bool:
        """Standing at the Pump Room panel, on the grid, mid-day, panel idle."""
        return (self.phase is Phase.NAVIGATE and not self.off_grid
                and self.state.pos == self._capability_cell(Capability.PUMP_PANEL) >= 0)

    def set_pump_source(self, source_id: str) -> None:
        """Select a water source at the panel; awaits a target-level pick next."""
        assert self.can_set_pump_source(), "must stand in the Pump Room"
        assert self._pump_source(source_id) is not None, f"unknown pump source {source_id!r}"
        self.state.pending_pump_source = source_id
        self.phase = Phase.PUMP_LEVEL_PENDING

    def can_set_pump_level(self, level: int) -> bool:
        """Legal to set the pending source to ``level`` right now.

        PUMP_LEVEL_PENDING only, with the pending source's own [min, max]
        range (data/pump_room.json) -- the Reservoir's min is 2, every other
        source's is 0. Always at least one legal level (the source's current
        one is always in range), so this phase can never dead-end.
        """
        if self.phase is not Phase.PUMP_LEVEL_PENDING:
            return False
        source_id = self.state.pending_pump_source
        if source_id is None:
            return False
        src = self._pump_source(source_id)
        return src is not None and src.min <= level <= src.max

    def set_pump_level(self, level: int) -> None:
        """Set the pending source's level, permanently, and return to NAVIGATE.

        Setting the Reservoir to exactly 13 also permanently opens the
        reservoir_north<->reservoir_south rowboat crossing
        (state.reservoir_13_reached; docs/areas.md) -- unlike
        pump_water_lte8/rowboat_water_6, which stay live checks against the
        current level rather than latching.
        """
        assert self.can_set_pump_level(level), f"level {level} not valid for the pending source"
        source_id = self.state.pending_pump_source
        self.state.water_levels[source_id] = level
        if source_id == "reservoir" and level == 13:
            self.state.reservoir_13_reached = True
        self.state.pending_pump_source = None
        self.phase = Phase.NAVIGATE

    def _pump_carryover(self) -> dict:
        """Cross-day carry for the Pump Room's water levels and the permanent
        Reservoir-13 crossing flag.

        Reports the FULL current water_levels dict every day (state.water_levels
        is seeded from cfg.water_levels at Game.reset and only ever changed by
        set_pump_level), the same "state already IS the accumulated total"
        shape as draft_counts/foundation_cell -- but NOT SAVE-scoped like
        permanent_rarity/axed_rooms: DayChain.advance() resets water_levels at
        the attempt wrap (see GameConfig.water_levels for why).
        reservoir_13_reached ORs cfg and state, the same shape as
        west_gate_unlatched/sealed_entrance_broken -- once the Reservoir has
        ever been set to 13 this attempt, the crossing stays open even after
        the level moves away.
        """
        return {
            "water_levels": dict(self.state.water_levels),
            "reservoir_13_reached": (
                self.cfg.reservoir_13_reached or self.state.reservoir_13_reached
            ),
        }

    # ------------------------------------------------------------- commerce
    # Thin delegates into engine/shops.py (docs/special-items-behaviour.md).
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

    def can_donate_shrine(self, blessing_idx: int, duration_idx: int) -> bool:
        """Legal at the Shrine, no blessing/curse active, for an affordable
        implemented blessing (``blessing_idx``/``duration_idx`` in shrine.json order)."""
        return shrine.can_donate(self, blessing_idx, duration_idx)

    def donate_shrine(self, blessing_idx: int, duration_idx: int) -> None:
        """Pay that blessing/duration's coin cost and grant it."""
        shrine.donate(self, blessing_idx, duration_idx)

    def can_take_back_shrine_offering(self) -> bool:
        """Legal at the Shrine while a blessing is currently active."""
        return shrine.can_take_back(self)

    def take_back_shrine_offering(self) -> None:
        """Refund the offering, drop the blessing, and curse the player for 2 days."""
        shrine.take_back(self)

    def can_berry_pick(self) -> bool:
        """Blessing of the Berry Picker: legal while DRAFTING an on-grid hand,
        with the blessing active and at least one affordable candidate room."""
        if self.phase is not Phase.DRAFTING or self.state.pending is None:
            return False
        if self.state.pending.target_cell == -1:  # no doorway/cell for an outer-room draft
            return False
        return shrine.berry_pick_available(self, self.state.pending)

    def berry_pick(self) -> None:
        """Draft a random legal room from the pool instead of a dealt option.

        Reuses :meth:`choose`'s cost/afford/pay/:meth:`_place_room` pipeline
        around a slot-2-shaped synthetic ``DraftOption`` (no discount is
        published for this path, so it prices like any other non-free pick).
        Checks termination at the end, same as :meth:`choose`.
        """
        assert self.can_berry_pick(), "berry pick not available"
        st = self.state
        pending = st.pending
        room, orientation = shrine.pick_berry(self, pending)
        opt = DraftOption(room_idx=room.idx, orientation=orientation, gem_cost=0, slot=2)
        opt.gem_cost = self._effective_cost(room, opt)
        assert self.affordable(room, opt), "cannot afford the berry-picked room"
        cost = self._effective_cost(room, opt)
        waived = self._pay(room, opt)
        self._place_room(room, pending.target_cell, orientation,
                         entry_dir=OPPOSITE[pending.direction],
                         gem_cost=0 if waived else cost, archived=False)
        del self.doorway_drafts[(pending.from_cell, pending.direction)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        self._check_termination()

    def can_open_container(self) -> bool:
        """At least one unopened container at the current cell can be opened."""
        return special_items.can_open_container(self, self.state.pos)

    def open_container(self) -> str | None:
        """Open the next container at the current cell; return what was granted.

        Checks termination at the end: opening a trunk can fire trunks_opened,
        whose configured effect may drain steps to 0 (e.g. steps_for_gold).
        """
        assert self.cfg.special_items
        result = special_items.open_container(self, self.state.pos)
        self._check_termination()
        return result

    def at_planetarium(self) -> bool:
        """True when the player is standing in a room providing
        ``Capability.TELESCOPE_REVEAL`` (the Planetarium).

        Same shape as :meth:`at_laboratory_terminal` -- the Telescope's
        Planetarium upgrade is specific to this one room, not a shared menu.
        The Planetarium has no upgrade variants and no outer-room presence.
        """
        if self.inside_outer_room or self.off_grid:
            return False
        st = self.state
        if not (0 <= st.pos < len(st.grid)) or st.grid[st.pos] < 0:
            return False
        return effects.provides_capability(
            self.registry.rooms[st.grid[st.pos]].id, Capability.TELESCOPE_REVEAL)

    def can_use_telescope_planetarium(self) -> bool:
        """True when using the Telescope in the Planetarium is legal right now.

        NAVIGATE, special items enabled, standing in the Planetarium, a
        Telescope held, today's one-upgrade-per-day cap not yet spent (wiki:
        "only one upgrade can be done per day"), and at least one planet
        still locked (wiki: "Once all five planets appear, the Telescope can
        no longer be used in the Planetarium").
        """
        if self.phase is not Phase.NAVIGATE:
            return False
        if not self.cfg.special_items:
            return False
        if not self.at_planetarium():
            return False
        if not telescope.held(self.state):
            return False
        if self.state.special.planetarium_telescope_used:
            return False
        return len(self.state.planetarium_planets) < len(self.registry.special.planetarium_planets)

    def use_telescope_planetarium(self) -> str:
        """Reveal one Planetarium planet and apply its permanent payload.

        Does not consume the Telescope (wiki). See
        special_items.use_telescope_in_planetarium for the reveal/payload
        logic; effects/rooms/planetarium.py re-applies every unlocked
        payload on later days.
        """
        assert self.can_use_telescope_planetarium(), "Telescope-in-Planetarium not available"
        return special_items.use_telescope_in_planetarium(self, self.state.pos)

    def _night_sky_cell(self) -> int:
        """The cell whose night sky the player can act on right now, or -1.

        A cell, not a room id: ``room_cells`` keeps only the lowest cell per
        id, so it cannot tell two Observatories apart (see
        GameState.night_skies).
        """
        st = self.state
        if self.inside_outer_room or self.off_grid:
            return -1
        if not (0 <= st.pos < len(st.grid)) or st.grid[st.pos] < 0:
            return -1
        room = self.registry.rooms[st.grid[st.pos]]
        if not effects.provides_capability(room.id, Capability.NIGHT_SKY):
            return -1
        return st.pos

    def can_view_night_sky(self) -> bool:
        """True when looking at a night sky is legal right now.

        NAVIGATE, standing in a room providing ``Capability.NIGHT_SKY``, an
        unspent viewing source at THIS cell (the room's own telescope, then a
        held Telescope), and today's ``max_skies_per_day`` not yet reached.

        Deliberately still legal once ``max_constellation_skies_per_day`` is
        spent: the wiki has the eighth sky VIEWED and coming back empty, not
        refused, so the empty sky is generated rather than the action masked.
        """
        if self.phase is not Phase.NAVIGATE:
            return False
        cell = self._night_sky_cell()
        if cell < 0:
            return False
        con = self.registry.constellations
        if constellations.skies_generated(self.state) >= con.max_skies_per_day:
            return False
        held = self.cfg.special_items and telescope.held(self.state)
        return constellations.unused_source(self.state, cell, held) is not None

    def view_night_sky(self) -> tuple[str, ...]:
        """Generate today's next night sky at this cell; return what it shows.

        The sky locks here, to the LIVE ``state.stars`` at this moment -- not
        ``cfg.stars``. Every Observatory drafted before this call has already
        added its star, which is exactly the timing decision the explicit view
        action exists to give the agent.
        """
        assert self.can_view_night_sky(), "night sky not available"
        cell = self._night_sky_cell()
        held = self.cfg.special_items and telescope.held(self.state)
        source = constellations.unused_source(self.state, cell, held)
        sky = constellations.generate_sky(self.registry.constellations, self.state, cell, source)
        return sky.constellation_ids

    def _activatable_sky(self, index: int):
        """The sky at this cell holding record ``index`` un-activated, or None.

        Scans this cell's skies in generation order, so a second sky only
        answers once the first one's copy is spent -- that is how the held
        Telescope's extra sky lets one constellation fire twice.
        """
        con = self.registry.constellations
        if not (0 <= index < len(con.records)):
            return None
        record = con.records[index]
        if not record.implemented:
            return None
        cell = self._night_sky_cell()
        if cell < 0:
            return None
        for sky in self.state.night_skies.get(cell, ()):
            if record.id in sky.constellation_ids and record.id not in sky.activated:
                return sky
        return None

    def can_activate_constellation(self, index: int) -> bool:
        """True when constellation ``index`` can be activated right now.

        ``index`` is a position in data/constellations.json record order, the
        same order ACTIVATE_CONSTELLATION_BASE indexes by. Needs NAVIGATE, a
        sky at the player's cell showing that constellation un-activated, and
        an ``implemented`` record -- the eight unimplemented ones can appear
        in a sky (they are part of the partition) but never activate.
        """
        if self.phase is not Phase.NAVIGATE:
            return False
        return self._activatable_sky(index) is not None

    def activate_constellation(self, index: int) -> str:
        """Activate constellation ``index`` from the sky at this cell.

        A record pays out one of two ways and the data says which. Its
        ``grant`` goes through the shared effects/tier1.py::_grant path, so
        constellations spend the same resource vocabulary (and the same
        clamping) as every room effect; its ``effect`` goes to
        constellations.py::apply_effect. An implemented record carries exactly
        one of the two, so the other call is a no-op, and every number comes
        from the record rather than from a constant here.

        The activation is recorded on its sky FIRST: apply_effect reads
        today's activation count to honour ``stacks``, and would otherwise
        miss the very activation it is being called for.
        """
        sky = self._activatable_sky(index)
        assert sky is not None and self.phase is Phase.NAVIGATE, "constellation not activatable"
        record = self.registry.constellations.records[index]
        sky.activated.add(record.id)
        _grant(self, record.grant_resource, record.grant_amount)
        constellations.apply_effect(self, record)
        return record.id

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
        """Holding an ignition tool (Torch/Burning Glass) at a lightable room
        or off-grid area (e.g. mine_south)."""
        return special_items.can_light(self)

    def light(self) -> None:
        """Light the ignition target at the current room/area; grant its rewards."""
        assert self.cfg.special_items
        special_items.light(self)

    def can_install_lever(self) -> bool:
        """Holding a Broken Lever in a machine room that hasn't been used today."""
        return special_items.can_install_lever(self)

    def install_lever(self) -> None:
        """Install the Broken Lever in the current machine room; apply its effect."""
        assert self.cfg.special_items
        special_items.install_lever(self)

    def can_open_sigil_door(self, realm: str) -> bool:
        """A Sanctum Key is held, standing at the Inner Sanctum, and ``realm``'s door is sealed."""
        return special_items.can_open_sigil_door(self, realm)

    def open_sigil_door(self, realm: str) -> bool:
        """Spend a held Sanctum Key to permanently unlock the Sigil Chamber door for ``realm``."""
        assert self.cfg.special_items
        return special_items.open_sigil_door(self, realm)

    def can_take_grotto_chip(self) -> bool:
        """Standing at the Blackbridge Grotto with the pedestal's chip still in place."""
        return shops.can_take_grotto_chip(self)

    def take_grotto_chip(self) -> None:
        """Take the Blackbridge Grotto pedestal's microchip into inventory."""
        assert self.cfg.special_items
        shops.take_grotto_chip(self)


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

    def can_axe_room(self, target_id: str) -> bool:
        """Is axing ``target_id`` legal right now?

        Requires: special items enabled, an Axe held, NAVIGATE phase, the
        save-scoped 3-use cap (the_axe.max_active) not yet reached,
        ``target_id`` not already axed, and ``target_id`` itself a real,
        currently gem-costed floorplan FAMILY root (``upgrades.root_base_id``
        of the room equals ``target_id`` -- so a variant id, or a free room,
        is never a legal target). Not gated on standing anywhere in
        particular: the wiki's "Room Directory" is a menu, not a physical
        room, and the sim has no Room Directory subsystem to stand in.
        """
        if self.phase is not Phase.NAVIGATE:
            return False
        if not self.cfg.special_items:
            return False
        if not the_axe.held(self.state):
            return False
        if target_id in self.state.axed_rooms:
            return False
        if len(self.state.axed_rooms) >= the_axe.max_active(self.registry):
            return False
        room = self.registry.by_id.get(target_id)
        if room is None or room.gem_cost <= 0:
            return False
        return root_base_id(self.registry, room) == target_id

    def axe_room(self, target_id: str) -> None:
        """Consume the held Axe and permanently zero ``target_id``'s
        floorplan family's gem cost for the rest of the save.

        The override itself lives in ``engine/state.py::resolve_gem_cost``,
        applied at cost-resolution time (both dealing and paying route
        through it); this method only records the permanent fact and spends
        the item. ``state.axed_rooms`` is an ordered tuple (see
        ``GameConfig.axed_rooms``), appended to, never rewritten.
        """
        assert self.can_axe_room(target_id), f"cannot axe {target_id!r} right now"
        the_axe.consume(self.state)
        self.state.axed_rooms = (*self.state.axed_rooms, target_id)

    def _axe_carryover(self) -> dict:
        """Cross-day carry for The Axe's permanent record.

        Reports the FULL current ordered tuple every day (state.axed_rooms is
        seeded from cfg at reset() and only ever grows via axe_room), so
        DayChain.advance() can replace its own running value from this the
        same "state already IS the accumulated total" shape as
        draft_counts/foundation_cell -- except, per the owner's SAVE-scoped
        ruling, DayChain must NOT clear this at the attempt wrap the way
        draft_counts/foundation_cell are cleared (see that module's own
        wrap-block comment).
        """
        return {"axed_rooms": list(self.state.axed_rooms)}

    def carryover(self) -> dict:
        """Cross-day discoveries to feed into tomorrow's GameConfig."""
        result = shops.carryover(self)
        result.update(self._room_pulse_carryover())
        result.update(self._sigil_carryover())
        result.update(self._shrine_carryover())
        result.update(self._axe_carryover())
        result.update(self._wrench_carryover())
        result.update(self._pump_carryover())
        result.update(self._payroll_carryover())
        return result

    def _wrench_carryover(self) -> dict:
        """Cross-day carry for the Gear Wrench's permanent rarity record.

        Reports the FULL current dict every day (state.permanent_rarity is
        seeded from cfg at reset() and only ever changed by
        set_wrench_rarity), so DayChain.advance() can replace its own
        running value from this the same "state already IS the accumulated
        total" shape as axed_rooms/draft_counts/foundation_cell -- except,
        per the owner's SAVE-scoped ruling (matching axed_rooms), DayChain
        must NOT clear this at the attempt wrap.
        """
        return {"permanent_rarity": dict(self.state.permanent_rarity)}

    def _shrine_carryover(self) -> dict:
        """Cross-day carry for the active Shrine blessing/curse.

        Today's ending value for each field; DayChain.advance() replaces its
        running value from this and then decays the two day-counts by 1 --
        the same mail_transit_days shape as ``shops.carryover``'s mail_cycle
        entry, but SAVE-scoped rather than reset at the attempt wrap (see
        DayChain's own comment). Kept here alongside :meth:`_room_pulse_carryover`
        and :meth:`_sigil_carryover` rather than in ``shops.carryover`` so every
        Shrine-specific read stays colocated with the rest of this module's
        Shrine call sites.
        """
        st = self.state
        return {
            "shrine_blessing_id": st.shrine_blessing_id,
            "shrine_blessing_days": st.shrine_blessing_days,
            "shrine_curse_days": st.shrine_curse_days,
            "shrine_offered_coins": st.shrine_offered_coins,
            "shrine_monk_room": st.shrine_monk_room,
        }

    def _sigil_carryover(self) -> dict:
        """Cross-day carry for consumed Sanctum Key sources and opened Sigil doors.

        Both are permanent, union-accumulated sets -- the same shape as
        ``collected_disks``/``collected_allowance_tokens`` in ``shops.carryover``.
        Kept here (rather than in shops.py) since this PR's file allowlist does
        not include shops.py.
        """
        st = self.state
        return {
            "collected_sanctum_keys": sorted(
                set(getattr(self.cfg, "collected_sanctum_keys", frozenset()))
                | special_items.fixed_sanctum_keys_spent_today(st, self.registry)
            ),
            "sigil_doors_open": sorted(
                set(getattr(self.cfg, "sigil_doors_open", frozenset()))
                | set(st.special.sigil_doors_opened)
            ),
        }

    def _room_pulse_carryover(self) -> dict:
        """One-day-pulse cross-day bonuses: Sauna, Morning Room, Freezer, Break Room,
        No Contact Delivery, Clock Tower.

        Unlike the permanent flags in ``shops.carryover`` (ORed with cfg so a
        discovery, once made, holds forever), these report only TODAY's own
        trigger with no OR against cfg -- DayChain replaces its running value
        from this each advance() rather than merging it in, so each bonus lands
        on exactly the FOLLOWING day and lapses again unless re-earned.
        """
        st = self.state
        return {
            "sauna_bonus": st.sauna_visited,
            "morning_room_bonus": st.morning_room_visited,
            "break_room_keycard": st.break_room_keycard,
            # None (not 0) means "no freeze today" -- 0 coins/gems held while
            # frozen is a real, distinct value from "not frozen at all".
            "frozen_coins": st.coins if st.freezer_frozen else None,
            "frozen_gems": st.gems if st.freezer_frozen else None,
            "no_contact_due": st.no_contact_drafted,
            "clock_tower_tomorrow_keys": st.clock_tower_tomorrow_keys,
        }

    def open_door(self, cell: int, direction: int) -> PendingDraft | None:
        """Try (but do not necessarily open) a doorway of the current room.

        Drafting only deals a hand and, on :meth:`choose`, places a room; it
        costs no step and grants no resources. The player pays the step and
        receives the room's effects only when they :meth:`move` into it.
        A security doorway needs the keycard system to allow it
        (:meth:`security_openable`); trying it is otherwise free.
        Checks termination at the end: the security_door trigger can fire from
        this method's own :meth:`_unlock_for_passage` call, and a steps-draining
        effect (e.g. steps_for_gold) could otherwise go unnoticed until the
        next NAVIGATE-phase action. A caller must check ``phase`` afterward,
        same as every other termination-checking action.

        Returns None, and enters LOCK_PENDING instead of unlocking, when the
        doorway is DOOR_LOCKED -- trying a locked door is how the player finds
        out it is locked at all (owner ruling); nothing is spent here, only
        :meth:`use_key_at_lock`/:meth:`lockpick_at_lock`/:meth:`use_special_key_at_lock`
        actually open it, or :meth:`abandon_lock` leaves it locked and returns
        to NAVIGATE. A structural clone of the COLOUR_PENDING branch below,
        parking ``st.pending_lock_cell``/``pending_lock_direction`` instead of
        ``pending_colour_*``.

        Returns None, and enters COLOUR_PENDING instead of dealing, when this
        is the FIRST opening of a doorway whose from-room is a Secret Passage
        variant (SECRET_PASSAGE_IDS) -- the player must :meth:`choose_colour`
        before a hand can be dealt. Reopening that same doorway once its
        colour has already been chosen (cached in doorway_drafts) skips the
        pick and returns the cached hand, same as any other doorway. A locked
        doorway resolves LOCK_PENDING first (above) -- there is no order to
        choose between the two, since a locked Secret Passage doorway cannot
        reach this check until the lock itself is opened.

        Also returns None, staying in NAVIGATE instead of entering DRAFTING,
        when the dealt hand comes up wholly empty (only reachable through a
        colour-selective draft whose published default triple is also
        exhausted -- see draft.py's draw_slot docstring). There is nothing to
        choose, so the draft never happened: a key or special key already
        spent resolving LOCK_PENDING (if the segment was locked) is NOT
        refunded, since the segment really is open now, independent of what
        the failed deal found behind it; no step is affected either way,
        since opening a doorway never costs one (see above). ``_deal_and_cache``
        never caches an empty result, so reopening this doorway later
        re-deals from scratch rather than replaying the same dead end.
        """
        assert self.phase is Phase.NAVIGATE, "not in NAVIGATE phase"
        st = self.state
        assert cell == st.pos, "can only draft from the room you are standing in"
        assert st.placed_doors[cell] & direction, "no door in that direction"
        target = neighbor(cell, direction)
        assert target != -1 and st.grid[target] < 0, "invalid doorway"
        if self.door_state_of(cell, direction) == DOOR_LOCKED:
            st.pending_lock_cell = cell
            st.pending_lock_direction = direction
            self.phase = Phase.LOCK_PENDING
            self._check_termination()
            return None
        self._unlock_for_passage(cell, direction, for_draft=True)
        return self._continue_draft(cell, direction, target)

    def _continue_draft(self, cell: int, direction: int, target: int,
                        colour: str | None = None) -> PendingDraft | None:
        """Shared tail of :meth:`open_door` (once past any lock) and every
        LOCK_PENDING resolver (:meth:`use_key_at_lock`/:meth:`lockpick_at_lock`/
        :meth:`use_special_key_at_lock`): the colour-pick check and dealing
        that used to sit directly in :meth:`open_door`. See that method's own
        docstring for the COLOUR_PENDING and empty-hand branches this mirrors.

        ``colour`` is set only by a resolved Prism Key use (see
        :meth:`use_special_key_at_lock`), which already knows its restriction
        and deals straight into it -- the from-room's own Secret Passage
        check below is skipped in that case (a Prism Key's colour takes
        priority over the Secret Passage's own pick, per the wiki: "the
        Prism Key takes priority and the Secret Passage's chosen color is
        ignored").
        """
        st = self.state
        key = (cell, direction)
        pending = self.doorway_drafts.get(key)
        if pending is None:
            if colour is None:
                from_room = self.registry.rooms[st.grid[cell]]
                if from_room.id in SECRET_PASSAGE_IDS:
                    st.pending_colour_cell = cell
                    st.pending_colour_direction = direction
                    self.phase = Phase.COLOUR_PENDING
                    self._check_termination()
                    return None
            pending = self._deal_and_cache(cell, direction, target, colour=colour)
        if not pending.options:
            st.pending = None
            self.phase = Phase.NAVIGATE
            self._check_termination()
            return None
        st.pending = pending
        self.phase = Phase.DRAFTING
        self._check_termination()
        return pending

    # ------------------------------------------------------------ LOCK_PENDING

    _RESERVED_SPECIAL_KEYS = frozenset({"secret_garden_key", "key_8"})

    def _lock_pending_target(self) -> tuple[int, int]:
        """The (cell, direction) doorway parked in LOCK_PENDING."""
        st = self.state
        assert st.pending_lock_cell >= 0, "not awaiting a lock choice"
        return st.pending_lock_cell, st.pending_lock_direction

    def can_use_key_at_lock(self) -> bool:
        """A regular key can be spent at the pending lock right now.

        The full :meth:`lock_open_cost` (base 1, plus a Great Hall side
        door's search surcharge) is required, UNLESS an active Stopwatch
        would refund the whole spend -- the wiki: "At least one key is still
        required for the option to use a key to appear, even though it
        isn't spent", so only >=1 key is then required.
        """
        if self.phase is not Phase.LOCK_PENDING:
            return False
        cell, direction = self._lock_pending_target()
        st = self.state
        refund = (self.cfg.special_items and st.special.stopwatch_left > 0)
        needed = 1 if refund else self.lock_open_cost(cell, direction)
        return st.keys >= needed

    def use_key_at_lock(self) -> PendingDraft | None:
        """Spend a regular key (or an active Stopwatch charge) to open the
        pending lock, then continue the draft. See :meth:`can_use_key_at_lock`
        for the Stopwatch refund rule; the Stopwatch itself is not a menu
        row (owner ruling), only a passive modifier of this one."""
        assert self.can_use_key_at_lock(), "no key to spend at this lock"
        cell, direction = self._lock_pending_target()
        st = self.state
        if self.cfg.special_items and st.special.stopwatch_left > 0 and st.keys >= 1:
            st.special.stopwatch_left -= 1
        else:
            st.keys -= self.lock_open_cost(cell, direction)
        return self._resolve_lock_open(cell, direction)

    def can_lockpick_at_lock(self) -> bool:
        """A Lock Pick Kit or Pick Sound Amplifier is held. Restricted to
        doors that take a regular key -- automatic here, since LOCK_PENDING
        is only ever entered on a DOOR_LOCKED segment, never a security
        door (see :meth:`open_door`)."""
        if self.phase is not Phase.LOCK_PENDING or not self.cfg.special_items:
            return False
        return special_items.can_attempt_lockpick(self.state, self.registry)

    def lockpick_at_lock(self) -> PendingDraft | None:
        """One Lock Pick Kit / Pick Sound Amplifier attempt at the pending lock.

        Success opens the door for free and continues the draft. Failure
        spends nothing, does not consume the tool (day-persistent per
        special_items.json), and does NOT exit the menu -- the player may
        retry, spend a key, try a special key, or :meth:`abandon_lock`. See
        :func:`special_items._attempt_lockpick` for the known simplification
        (global, not per-doorway, attempt tracking) this shares with the
        movement-path Lock Pick Kit. Returns None on failure (still LOCK_PENDING).
        """
        assert self.can_lockpick_at_lock(), "no lockpick tool held"
        cell, direction = self._lock_pending_target()
        if special_items._attempt_lockpick(self):
            return self._resolve_lock_open(cell, direction)
        self._check_termination()
        return None

    def can_abandon_lock(self) -> bool:
        """Always legal in LOCK_PENDING -- the wiki's "option to exit the
        menu", and this sim's own guarantee that the phase is never a dead
        end regardless of what is or isn't held."""
        return self.phase is Phase.LOCK_PENDING

    def abandon_lock(self) -> None:
        """Exit the lock menu without opening the door: back to NAVIGATE,
        the segment still DOOR_LOCKED, nothing spent."""
        assert self.can_abandon_lock(), "not awaiting a lock choice"
        self.state.pending_lock_cell = -1
        self.state.pending_lock_direction = 0
        self.phase = Phase.NAVIGATE
        self._check_termination()

    def _special_key_held(self, key_id: str) -> bool:
        if key_id == "master_key":
            return master_key.held(self.state, self.registry)
        if key_id == "silver_key":
            return silver_key.held(self.state)
        if key_id == "basement_key":
            return basement_key.held(self.state)
        if key_id == "prism_key":
            return prism_key.held(self.state)
        return False  # secret_garden_key / key_8: reserved (see below)

    def _special_key_fits(self, key_id: str, cell: int, direction: int) -> bool:
        if key_id == "master_key":
            return master_key.fits(self, cell, direction)
        if key_id == "silver_key":
            return silver_key.fits(self, cell, direction)
        if key_id == "basement_key":
            return basement_key.fits(self, cell, direction)
        if key_id == "prism_key":
            return prism_key.fits(self, cell, direction)
        return False  # secret_garden_key / key_8: reserved (see below)

    def can_use_special_key_at_lock(self, key_id: str) -> bool:
        """Is ``key_id`` a legal special-keys-menu row at the pending lock?

        ``secret_garden_key``/``key_8`` are modelled in this sim as
        draft_conditions tags rather than door keys (their menu behaviour is
        unimplemented in both directions) -- reserved action ids, permanently
        masked off, per data/locks.json's special_key_menu comment.
        ``prism_key`` is not reserved: it is legal exactly when held and
        ``fits`` (a Bedroom/Hallway/Green Room/Shop/Red Room -- see
        effects/items/prism_key.py::fits), same shape as master_key/silver_key.
        """
        if self.phase is not Phase.LOCK_PENDING or not self.cfg.special_items:
            return False
        if key_id in self._RESERVED_SPECIAL_KEYS:
            return False
        if not self._special_key_held(key_id):
            return False
        cell, direction = self._lock_pending_target()
        return self._special_key_fits(key_id, cell, direction)

    def use_special_key_at_lock(self, key_id: str) -> PendingDraft | None:
        """Use special key ``key_id`` on the pending lock, then continue the draft.

        ``prism_key`` resolves its colour restriction here (the room the key
        is used IN, or a single rng draw in a multi-colour room -- see
        effects/items/prism_key.py::consume_and_resolve_colour) and threads
        it straight to :meth:`_resolve_lock_open`, which skips Phase.
        COLOUR_PENDING entirely: that phase exists for the Secret Passage's
        player pick, and the Prism Key's colour is never a player pick.
        """
        assert self.can_use_special_key_at_lock(key_id), f"cannot use {key_id!r} here"
        cell, direction = self._lock_pending_target()
        colour = None
        if key_id == "silver_key":
            used = silver_key.consume_for_draft(self.state)
            assert used, "silver key vanished mid-resolution"
        elif key_id == "master_key":
            pass  # never consumed (wiki)
        elif key_id == "prism_key":
            colour = prism_key.consume_and_resolve_colour(self, cell)
        else:
            raise AssertionError(f"no resolver wired for {key_id!r}")
        return self._resolve_lock_open(cell, direction, colour=colour)

    def _resolve_lock_open(self, cell: int, direction: int,
                           colour: str | None = None) -> PendingDraft | None:
        """Common tail of every successful lock resolution: clear the pending
        target, open the segment, and continue the draft. ``colour`` threads
        a resolved Prism Key restriction straight to the deal (see
        :meth:`use_special_key_at_lock`); None for every other resolver."""
        self.state.pending_lock_cell = -1
        self.state.pending_lock_direction = 0
        self._open_segment(cell, direction)
        return self._continue_draft(cell, direction, neighbor(cell, direction), colour=colour)

    def _deal_and_cache(self, cell: int, direction: int, target: int,
                        colour: str | None = None) -> PendingDraft:
        """Deal a fresh hand for the ``cell``->``direction`` doorway and cache it.

        Shared tail of :meth:`open_door`'s ordinary path and
        :meth:`choose_colour`'s resumed deal, so both fire ON_DRAFT_FROM/
        ON_HAND_DEALT and apply the Paper Crown bonus identically. ``colour``
        restricts the deal to one category (Secret Passage variants only);
        None for an ordinary doorway.

        Battery Pack's Dynamic Rarity trigger(s) are drained first, before
        ``deal_draft`` reads the decks: this is the earliest point after
        pickup where ``self.rng`` is in scope, and ``dynamic_rarity`` is
        never surfaced to env/obs, so there is no observable moment between
        pickup and this resolution for a policy to exploit.

        A wholly empty ``pending.options`` (only reachable via a
        colour-selective draft whose default triple is also exhausted -- a
        modelling artifact of not implementing the wiki's reserve-copies
        tier, see draft.py's draw_slot docstring) is deliberately NOT cached
        here: callers (:meth:`open_door`/:meth:`choose_colour`) fall back to
        NAVIGATE instead of entering DRAFTING on an empty hand, and caching it
        would trap a later reopen of this same doorway in that dead result
        forever instead of letting it re-deal.
        """
        st = self.state
        if self.cfg.special_items:
            special_items.resolve_battery_pack(self)
        pending = deal_draft(st, self.registry, self.cfg, self.rng,
                             self.placed_ids, cell, direction, target, colour=colour)
        # Visible to ON_DRAFT_FROM handlers below (the Classroom's free-redraw
        # grant reads/adds to pending.redraws_left, which defaults to 0).
        st.pending = pending
        # ON_DRAFT_FROM fires once, on the initial deal only -- not on
        # redraws (see redraw(), which deliberately does not re-fire it).
        effects.fire(self, self.registry.rooms[st.grid[cell]], Hook.ON_DRAFT_FROM)
        for opt in pending.options:
            effects.fire(self, self.registry.rooms[opt.room_idx], Hook.ON_HAND_DEALT)
        # Paper Crown: +1 free redraw on an all-non-red initial deal.
        # Hidden options are treated as potentially red (no crown bonus if any hidden).
        if self.cfg.special_items and paper_crown.bonus_redraw(st, self.registry, pending):
            pending.redraws_left += 1
        if pending.options:
            self.doorway_drafts[(cell, direction)] = pending
        return pending

    def choose_colour(self, colour: str) -> PendingDraft | None:
        """Resolve the Secret Passage's colour pick and deal the restricted hand.

        Only legal in COLOUR_PENDING; ``colour`` must be one of
        COLOUR_CATEGORIES. Finishes exactly what :meth:`open_door` would have
        done for this doorway had a pick not been needed, restricted to
        ``colour``, then returns to DRAFTING. Checks termination at the end,
        same as :meth:`open_door` (colour_pending itself already checked
        termination on entry; this covers whatever the deal's own hooks do).

        Returns None, staying in NAVIGATE instead of entering DRAFTING, when
        the restricted deal comes up wholly empty (its default triple also
        exhausted) -- see :meth:`open_door`'s matching exhaustion branch,
        which this mirrors exactly; no key was spent here (the door was
        already unlocked when :meth:`open_door` first parked in
        COLOUR_PENDING), so there is nothing to account for beyond that.
        """
        assert self.phase is Phase.COLOUR_PENDING, "choose_colour only legal in COLOUR_PENDING"
        assert colour in COLOUR_CATEGORIES, f"unknown colour {colour!r}"
        st = self.state
        cell, direction = st.pending_colour_cell, st.pending_colour_direction
        target = neighbor(cell, direction)
        st.pending_colour_cell = -1
        st.pending_colour_direction = 0
        pending = self._deal_and_cache(cell, direction, target, colour=colour)
        if not pending.options:
            st.pending = None
            self.phase = Phase.NAVIGATE
            self._check_termination()
            return None
        st.pending = pending
        self.phase = Phase.DRAFTING
        self._check_termination()
        return pending

    def draft_from(self, cell: int, direction: int) -> PendingDraft | None:
        """Walk to ``cell`` (if needed) and draft through its ``direction`` door.

        A macro over :meth:`move_to` + :meth:`open_door`: the walk pays the
        normal one-step-per-room cost and collects first-entry pickups along
        the way, so the RNG stream is identical to issuing the moves by hand.
        Returns None if the walk ends the day before the draft can happen, if
        the walk itself gets stranded short of ``cell`` (see
        :meth:`move_to`), if arriving at ``cell`` changed the ``direction``
        doorway's own state out from under the caller's plan (the Vestibule
        can do this on its own arrival) so it is no longer triable (see
        :meth:`frontier_doorway_triable` -- a DOOR_SEALED or unopenable
        DOOR_SECURITY segment; a DOOR_LOCKED one is always triable), or if
        the doorway's from-room is a Secret Passage variant and this is its
        first opening -- see :meth:`open_door`, which enters COLOUR_PENDING
        in that case instead of dealing (or LOCK_PENDING first, if locked).
        """
        assert self.phase is Phase.NAVIGATE
        if cell != self.state.pos:
            self.move_to(cell)
        if self.phase is not Phase.NAVIGATE:
            return None
        if self.state.pos != cell or not self.frontier_doorway_triable(cell, direction):
            return None
        return self.open_door(cell, direction)

    # --------------------------------------------------------- outer rooms

    @property
    def off_grid(self) -> bool:
        """True when the player is off the 5x9 grid (at the doorstep or inside an outer room)."""
        return self.state.area is not None

    @property
    def drafted_outer_room(self) -> "Room | None":
        """Today's drafted outer room, or None before the outer draft happens.

        Exactly one outer room exists per day, which is why this is a single
        value rather than a set.
        """
        return next((r for r in self.outer_rooms if r.id in self.placed_ids), None)

    @property
    def inside_outer_room(self) -> bool:
        """True when the player is physically inside today's drafted outer room."""
        outer_room = self.drafted_outer_room
        return outer_room is not None and self.state.area == outer_room.id

    def _garage_cell(self) -> int:
        """Cell where the garage room (or a garage variant) is placed, or -1."""
        cells = [self.room_cells[rid] for rid in self._garage_ids
                 if rid in self.room_cells]
        return min(cells) if cells else -1

    def _capability_cell(self, capability: Capability) -> int:
        """Cell of the placed room registered for ``capability``, or -1 if none placed.

        Generalizes single-room cell lookups (the Utility Closet breaker box,
        the Security terminal) into a query over whichever room registers the
        capability via ``effects.provides``, instead of naming that room's id
        directly. Each capability queried this way is registered by exactly
        one room today, so the first placed match is unambiguous.
        """
        for room_id in effects.rooms_with_capability(capability):
            cell = self.room_cells.get(room_id, -1)
            if cell >= 0:
                return cell
        return -1

    def _utility_closet_cell(self) -> int:
        """Cell of the room providing ``Capability.BREAKER_BOX`` (the Utility
        Closet), or -1 if not placed."""
        return self._capability_cell(Capability.BREAKER_BOX)

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
          "mine_south_visited" -- carried in from cfg, OR earned today the moment the
              player reaches mine_south.  Permanently opens reservoir_north -> mine_north
              and rotating_gear -> underpass (the mine-cart simplification, docs/areas.md).
          "sealed_entrance_broken" -- carried in from cfg, OR earned today the moment the
              player first reaches sealed_entrance, OR live for today only while a Power
              Hammer is held.  The held-item term is what lets the FIRST break happen; the
              cfg/state terms are what make it permanent on this and later days.  Gates
              grounds<->sealed_entrance<->basement (docs/areas.md).  Owner decision: broken
              is broken, unconditionally -- the wiki's plank-vs-wall permanence distinction
              is deliberately not modelled (docs/areas.md's "Sealed Entrance permanence").
          "candlestick_stairway_lit" -- the player has lit the Abandoned Mine (South)'s
              eight candlesticks (the "mine_south" ignition target in special_items.json,
              flagged "area": true since mine_south has no rooms.json record).  Permanent
              once lit: checked against BOTH cfg.lit_targets (carried in) and
              state.special.lit_targets (earned today), same OR-from-cfg-or-state shape
              as the other permanent flags below -- state.special.lit_targets alone is
              NOT enough, because special_items.configure() only seeds it from cfg lazily
              on the first real room entry (special_items.on_enter), so a mask built
              before that first entry would otherwise see it as unset.  Gates BOTH
              mine_south<->precipice edges: the stairway is a single physical structure
              the player lowers from inside the mine, not a front door -- owner correction,
              docs/areas.md's "Corrections already applied".
          "boiler_room_steam" -- carried in from cfg, OR earned today the moment the
              player first enters the Boiler Room.  Same OR-from-cfg-or-state shape as
              west_gate_unlatched (a plain top-level GameState field, never lazily
              seeded the way state.special.lit_targets is, so checking cfg directly
              is already correct before any room is entered on a later day).
              Permanent once entered (owner decision, docs/areas.md's "graduated" section:
              "assume the player unlocks this room permanently after entering the
              Boiler Room").  Gates Underpass -> Upper Rotating Gear.
          "grotto_chip_in_place" -- the Blackbridge Grotto pedestal's own microchip has
              NOT been taken out today (st.grotto_chip_taken is False).  Day-scoped only,
              unlike the flags above: it defaults set on every reset() rather than being
              carried in from cfg, since the pedestal chip has no discovery to carry --
              it starts in place with no prerequisite and simply respawns each day.
              Contributes 1 to the three_microchips item gate's total (see
              areas.py::gate_open's counts_flag handling).
          "pump_water_lte8" -- Grounds -> Well: live check against the CURRENT Fountain
              level (Game.water_level("fountain") <= 8), re-derived every call rather
              than latched -- unlike every permanent flag above, this can go both true
              and false again within the same day as the panel is operated.
          "rowboat_water_6" -- Reservoir South <-> Safehouse: same live-check shape as
              pump_water_lte8, on the Reservoir's level (== 6).
          "fountain_water_0" -- Well -> Reservoir South, ADDITIONAL to the permanent
              basement_key_well item gate on that same edge: same live-check shape as
              pump_water_lte8, on the Fountain's level (== 0) -- "this passage is only
              traversible while the fountain water level is 0" (Well page), checked on
              EVERY traversal, never latched.
          "reservoir_water_13" -- Reservoir North <-> Reservoir South: carried in from
              cfg.reservoir_13_reached, OR earned today the moment Game.set_pump_level
              records the Reservoir at exactly 13 (state.reservoir_13_reached). Same
              OR-from-cfg-or-state permanent shape as west_gate_unlatched -- UNLIKE the
              three live checks above, this latches: once true, it stays open even
              after the level later moves away from 13.
        """
        st = self.state
        flags: set[str] = set()
        if self.cfg.west_gate_unlatched or st.west_gate_unlatched:
            flags.add("west_gate_unlatched")
        if self.cfg.mine_south_visited or st.mine_south_visited:
            flags.add("mine_south_visited")
        if self.cfg.boiler_room_steam or st.boiler_room_steam:
            flags.add("boiler_room_steam")
        if (self.cfg.sealed_entrance_broken or st.sealed_entrance_broken
                or (self.cfg.special_items and power_hammer.held(st))):
            flags.add("sealed_entrance_broken")
        if "mine_south" in st.special.lit_targets or "mine_south" in self.cfg.lit_targets:
            flags.add("candlestick_stairway_lit")
        if self._breaker_on():
            flags.add("garage_door_breaker")
        if not st.grotto_chip_taken:
            flags.add("grotto_chip_in_place")
        if self.water_level("fountain") <= 8:
            flags.add("pump_water_lte8")
        if self.water_level("reservoir") == 6:
            flags.add("rowboat_water_6")
        if self.water_level("fountain") == 0:
            flags.add("fountain_water_0")
        if self.cfg.reservoir_13_reached or st.reservoir_13_reached:
            flags.add("reservoir_water_13")
        # North door open: Inner Sanctum or Throne Room lever pulled this day.
        north_seg = segment_key(ANTECHAMBER_CELL, N)
        if self.state.door_state.get(north_seg) != DOOR_SEALED:
            flags.add("antechamber_north_door_open")
        # rooms_entered: grid cells entered today, plus the outer room if entered
        entered_room_ids: set[str] = set()
        for cell, was_entered in enumerate(st.entered):
            if was_entered and st.grid[cell] >= 0:
                entered_room_ids.add(self.registry.rooms[st.grid[cell]].id)
        if st.outer_room_entered:
            outer_room = self.drafted_outer_room
            if outer_room is not None:
                entered_room_ids.add(outer_room.id)
        # outer_room_id: the drafted outer room id (None if not drafted yet today)
        outer_room_id: str | None = None
        if st.outer_room_drafted:
            outer_room = self.drafted_outer_room
            if outer_room is not None:
                outer_room_id = outer_room.id
        return GateContext(
            # Snapshot, not alias: st.inventory is a plain mutable dict that tests
            # and item-granting code poke in place, so a live reference would make
            # a cached GateContext compare equal to itself forever even after the
            # inventory changed underneath it (area_route_costs' memo below relies
            # on GateContext equality catching exactly that).
            held_items=dict(st.inventory),
            flags=frozenset(flags),
            rooms_entered=frozenset(entered_room_ids),
            outer_room_id=outer_room_id,
        )

    def _grid_anchors(self) -> dict[str, int]:
        """Area node id -> grid cell for anchors currently reachable on the grid.

        "house" maps to ENTRANCE_CELL always.
        "garage" maps to the lowest garage cell only when the garage is placed.
        "antechamber" maps to ANTECHAMBER_CELL always (it's pre-placed each day).
        "the_foundation" maps to its grid cell only once it has been drafted (it does
        not reset day-to-day; see GameConfig.foundation_cell).
        """
        anchors: dict[str, int] = {"house": ENTRANCE_CELL, "antechamber": ANTECHAMBER_CELL}
        garage_cell = self._garage_cell()
        if garage_cell >= 0:
            anchors["garage"] = garage_cell
        foundation_cell = self.room_cells.get("the_foundation", -1)
        if foundation_cell >= 0:
            anchors["the_foundation"] = foundation_cell
        return anchors

    def area_route_costs(self) -> dict[str, tuple[int, str]]:
        """Cheapest total step cost to EVERY reachable area node, in one pass.

        Same semantics as :meth:`area_route_cost`, computed for every destination
        at once instead of one BFS sweep per call: off grid, a single
        :func:`reachable` from ``state.area``; on grid, one :func:`reachable`
        per anchor from :meth:`_grid_anchors`, combined via
        ``grid_distance[anchor_cell] + area_steps[node]`` with ties broken toward
        "house" (anchors are tried in :meth:`_grid_anchors` insertion order --
        "house" first -- with a strict ``<`` so an equal-cost later anchor never
        displaces an earlier one).

        Returns ``{node_id: (cost, departure_anchor_id)}``, containing only
        reachable nodes. The departure anchor id is ``""`` when the player is
        already off-grid.

        Memoized in :meth:`_maps` under ``"area_costs"``, keyed additionally on
        a freshly built :class:`GateContext` (the ``_maps`` fingerprint alone
        does not cover inventory, carry-over flags, rooms entered today, or
        the drafted outer room, all of which gates read).
        """
        maps = self._maps()
        ctx = self._gate_ctx()
        cached = maps.get("area_costs")
        if cached is not None and cached[0] == ctx:
            return cached[1]
        graph = self.registry.area_graph
        if self.off_grid:
            assert self.state.area is not None
            dist = reachable(graph, self.state.area, ctx)
            costs = {node_id: (steps, "") for node_id, steps in dist.items()}
        else:
            dist_grid = self.distance_map()
            costs = {}
            # Try "house" first so ties break to Entrance Hall
            for anchor_id, anchor_cell in self._grid_anchors().items():
                g_dist = dist_grid[anchor_cell]
                if g_dist < 0:
                    continue
                area_dist = reachable(graph, anchor_id, ctx)
                for node_id, a_dist in area_dist.items():
                    cost = g_dist + a_dist
                    existing = costs.get(node_id)
                    if existing is None or cost < existing[0]:
                        costs[node_id] = (cost, anchor_id)
        maps["area_costs"] = (ctx, costs)
        return costs

    def area_route_cost(self, dest: str) -> tuple[int, str] | None:
        """Cheapest total step cost to reach area node ``dest``, and the departure anchor id.

        On grid: runs BFS from each available anchor and picks the minimum of
        ``grid_distance[anchor_cell] + area_steps[dest]``, skipping anchors
        whose grid distance is -1 (unreachable). Tie-break: "house" first.
        Off grid: BFS from ``state.area`` in the area graph.
        Returns None when ``dest`` is unreachable.
        The departure anchor id is "" when the player is already off-grid.
        """
        return self.area_route_costs().get(dest)

    def travel_to(self, dest: str) -> None:
        """Pay steps and move the player to area-graph node ``dest``.

        On grid: walk to the departure anchor cell first (using existing move_to
        bookkeeping), then deduct the area-hop steps and set state.area.
        If the walk ends the day, aborts without setting area (caller must check).
        Off grid: deduct area-hop steps only.

        The area-hop deduction itself consults Running Shoes: one independent
        activation roll per area node entered along the route (skipping grid
        anchors), each waiving one of the area_hop steps -- see
        effects/items/running_shoes.py::area_arrival_steps_saved.

        Special case — grid anchors ("house", "garage"):
        sets area=None and pos=<anchor cell>, then fires _enter() when the cell
        has not been entered yet (preserves ON_ENTER effects for the Garage),
        then fires ON_ARRIVE unconditionally (every landing, including re-entry).

        Special case — drafted outer room:
        when arriving at the today's outer room for the first time, marks it
        entered, fires ON_ENTER effects, rolls items, and runs special-item
        on_enter hooks.
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
            if st.pos != anchor_cell:
                return  # move_to got stranded short of the anchor (see move_to)
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
        anchors = self._grid_anchors()
        saved = 0
        if self.cfg.special_items:
            route = path(self.registry.area_graph, origin, dest, self._gate_ctx())
            assert route is not None, f"area node {dest!r} unreachable from {origin!r}"
            saved = running_shoes.area_arrival_steps_saved(self, route, anchors)
        st.steps -= (area_hop - saved)

        if dest in anchors:
            # Destination is a grid anchor, so the player lands back on the grid.
            dest_cell = anchors[dest]
            st.areas_visited.add(dest)  # grid anchors are area nodes too
            st.area = None
            st.pos = dest_cell
            if not st.entered[dest_cell]:
                self._enter(dest_cell)  # returning into a never-entered room fires ON_ENTER
            # ON_ARRIVE fires on every arrival, including re-entry -- outside
            # the entered-gate above, same contract as the move() call site.
            effects.fire(self, self.registry.rooms[st.grid[dest_cell]], Hook.ON_ARRIVE)
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
            # Mine South visited: permanently opens reservoir_north -> mine_north and
            # rotating_gear -> underpass (mine-cart simplification, docs/areas.md).
            # Same shape as west_gate_unlatched: recorded on STATE, never on cfg.
            if dest == "mine_south":
                st.mine_south_visited = True
                if self.cfg.special_items:
                    special_items.on_area_arrival(self, dest)
            # Upper Rotating Gear: grants the gem and the Treasure Trove blackprint
            # (owner spec, docs/areas.md). Unlike the Abandoned Mine
            # (South) Upgrade Disk above, neither grant is an inventory item,
            # so this call is unconditional -- not gated on cfg.special_items.
            if dest == "upper_rotating_gear":
                special_items.on_area_arrival(self, dest)
            # Orindian Ruins: grants the Throne Room blueprint permanently
            # (owner spec, docs/areas.md). Not an inventory item, so this
            # call is unconditional -- not gated on cfg.special_items, same
            # shape as Upper Rotating Gear above.
            if dest == "orindian_ruins":
                special_items.on_area_arrival(self, dest)
            # Sanctum Key sources at reservoir_north/safehouse: off-grid, no
            # rooms.json record, same shape as mine_south's disk above. Not
            # currently offered as a travel destination (areas.json
            # modelled=false), so this fires only via a direct engine call
            # (e.g. a test) until a later PR flips that flag.
            if dest in ("reservoir_north", "safehouse") and self.cfg.special_items:
                special_items.on_area_arrival(self, dest)
            # Underpass Mora Jai box: off-grid, no rooms.json record, same shape
            # as the sources above. Not currently offered as a travel
            # destination (areas.json modelled=false), so this fires only via a
            # direct engine call (e.g. a test) until a later PR flips that flag.
            if dest == "underpass" and self.cfg.special_items:
                special_items.on_area_arrival(self, dest)
            # Campsite: the Conservatory's hidden dig spot (owner spec,
            # docs/areas.md), found only while a shovel is held. Gated on
            # cfg.special_items since the check reads an inventory item, the
            # same shape as mine_south's disk above.
            if dest == "campsite" and self.cfg.special_items:
                special_items.on_area_arrival(self, dest)
            # Sealed Entrance: the Power Hammer break is permanent once it happens.
            # Arriving here at all means the grounds->sealed_entrance edge already
            # passed (via the flag or a held Power Hammer), so this is the one
            # place that needs to latch it for the rest of the attempt. Owner
            # decision: unconditionally permanent, no plank-vs-wall distinction
            # (docs/areas.md's "Sealed Entrance permanence"). Recorded on STATE,
            # never on cfg -- same shape as west_gate_unlatched/mine_south_visited.
            if dest == "sealed_entrance":
                st.sealed_entrance_broken = True
            # Inner Sanctum main lever: opens the Antechamber's north door.
            if dest == "inner_sanctum":
                north_seg = segment_key(ANTECHAMBER_CELL, N)
                if st.door_state.get(north_seg) == DOOR_SEALED:
                    self._open_north_door()
            # Room 46: record first arrival (permanent via carryover; see shops.carryover).
            # It also holds two guaranteed items (Crown of the Blueprints, Sanctum
            # Key), and since it is an area node that is never placed on the grid,
            # this arrival is the only site that can grant them -- _enter/on_enter
            # never run for it. Gated on cfg.special_items like mine_south's disk,
            # both being inventory items; each item's own first-visit gate lives in
            # special_items.configure, not here.
            if dest == "room_46":
                st.room46_reached = True
                if self.cfg.special_items:
                    special_items.on_area_arrival(self, dest)
            # Apple Orchard: the +20 starting-steps bonus is permanent from first
            # arrival. Recorded on STATE, never on cfg -- same shape as
            # west_gate_unlatched/mine_south_visited/sealed_entrance_broken.
            # st.steps is only ever set once, at reset(), so this cannot top up
            # the CURRENT day's already-spent budget -- carryover()/DayChain
            # carry the flag so cfg.orchard_unlocked is True at next reset(),
            # which is where the +20 actually lands (see Game.reset).
            if dest == "apple_orchard":
                st.orchard_unlocked = True
            # Fire ON_ENTER the first time the player enters the drafted outer room.
            outer_room = self.drafted_outer_room
            if (outer_room is not None and dest == outer_room.id
                    and not st.outer_room_entered):
                st.outer_room_entered = True
                effects.fire(self, outer_room, Hook.ON_ENTER)
                roll_room_items(self, outer_room, -1)
                if self.cfg.special_items:
                    # Outer rooms spawn special items too (Toolshed's Gear Wrench,
                    # the Trading Post pool); -1 = off-grid, no cell hooks apply.
                    special_items.on_enter(self, outer_room, -1)
                    if effects.provides_capability(outer_room.id, Capability.COMMERCE):
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

        Requires no outer room drafted yet today, NAVIGATE phase, and an
        affordable route to the doorstep (see :meth:`_outer_route_cost`) from
        wherever the player currently is -- on the grid or already off it.
        West Path *is* the doorstep, so standing there makes the route free
        (cost 0) rather than unavailable: :meth:`_outer_route_cost` already
        handles the off-grid case correctly via :meth:`area_route_cost`
        (whose BFS includes the origin itself at distance 0), so there is no
        separate on-grid-only restriction to enforce here.

        No config flag is checked: on a fresh save the Garage + breaker route
        to west_path is open from day 1 without any unlock. The west_gate_unlatched
        config field only opens the Grounds<->West Path shortcut, it does not gate
        the draft itself.
        """
        if self.state.outer_room_drafted:
            return False
        if self.phase is not Phase.NAVIGATE:
            return False
        return self._outer_route_cost() is not None

    def _deal_outer_options(self, pending: PendingDraft, label: str) -> None:
        """Shuffle the fixed 8-room outer pool via RNG stream ``label``, deal 3
        into ``pending.options``, then point a held Dowsing Rod at one of them.

        No rarity roll: outer rooms are a fixed pool, shuffled and truncated
        to the first 3 (wiki-documented mechanic). Shared by the initial deal
        (:meth:`open_outer_draft`, label ``"outer_draft"``) and by redraws
        (:meth:`_redeal_pending`, a distinct label) so redrawing an outer hand
        can never perturb the initial deal's RNG sequence -- ``rng.py::
        Rng.stream`` seeds a fresh, independent generator per label.

        The Dowsing Rod pick reuses draft.py's ``_pick_dowsing_slot`` --
        the same helper the grid pipeline's ``_fill_options`` calls on every
        deal and redraw -- rather than a second copy of the selection logic.
        Its docstring's "drafting" framing is not grid-specific, and the wiki
        (West_Path page, Outer Room cave section) confirms the outer door
        "may be drafted from like the doors in the house" and that
        "[d]rafting effects not related to the draft pool ... still usually
        work when drafting on the grounds" -- the Dowsing Rod's slot-pointing
        is exactly such an effect (it never touches which rooms are dealt).
        A throwaway ``DraftContext`` supplies the fields ``_pick_dowsing_slot``
        actually reads (state/registry/cfg/rng); ``placed_ids``/``from_room``
        are irrelevant to it, so ``from_room=None`` (an outer draft has no
        from-room, same as the ON_HAND_DEALT firing below) is fine.
        """
        outer = self.outer_rooms
        order = list(range(len(outer)))
        self.rng.shuffle(label, order)
        for slot, i in enumerate(order[:3]):
            room = outer[i]
            pending.options.append(DraftOption(
                room_idx=room.idx, orientation=room.door_mask, gem_cost=0, slot=slot))
        waive_first_option(pending)
        ctx = DraftContext(self.state, self.registry, self.cfg, self.rng, self.placed_ids, None)
        _pick_dowsing_slot(ctx, pending)

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
            pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
            self._deal_outer_options(pending, "outer_draft")
            # No ON_DRAFT_FROM: outer drafts have no from-room (from_cell=-1).
            for opt in pending.options:
                effects.fire(self, self.registry.rooms[opt.room_idx], Hook.ON_HAND_DEALT)
            self.doorway_drafts[key] = pending
        st.pending = pending
        self.phase = Phase.DRAFTING
        return pending

    def _choose_outer(self, opt) -> None:
        """Resolve choosing an outer-room option: place it off-grid, fire ON_PLACE.

        The player stays at the doorstep; the room's ON_ENTER effects and item
        rolls wait for :meth:`enter_outer_room`.

        Mirrors :meth:`choose`'s Dowsing Rod mark for the grid pipeline, using
        the ``-1`` sentinel in place of a real cell: an outer draft's
        ``pending.target_cell`` is already ``-1`` (no grid cell), and
        ``roll_room_items`` is already called with ``cell=-1`` for an outer
        room's item roll (see the ON_ENTER branch above this method). So
        marking ``-1`` in ``state.dowsing_marked_cells`` here is read back by
        that exact existing check -- no new plumbing, and no width change.
        """
        st = self.state
        pending = st.pending
        room = self.registry.rooms[opt.room_idx]
        st.outer_room_drafted = True
        self.placed_ids.add(room.id)
        self.drafted_rooms.append(room.name)
        if pending is not None and pending.dowsed_slot == opt.slot:
            st.dowsing_marked_cells.add(-1)
        del self.doorway_drafts[(-1, 0)]
        st.pending = None
        self.phase = Phase.NAVIGATE
        effects.fire(self, room, Hook.ON_PLACE)
        # Player stays at the doorstep (area == "west_path"); ON_ENTER fires when they enter.
        self._check_termination()

    def choose(self, slot: int) -> None:
        """Take the pending hand's option in ``slot``, pay its cost, place the room.

        DRAFTING-phase action; returns the game to NAVIGATE, UNLESS the
        placed room is a Mechanical Room (Room.is_category("mechanical"))
        and a Gear Wrench is held -- then it parks Phase.WRENCH_PENDING
        instead (wiki: "before the drafting menu closes"), awaiting
        :meth:`set_wrench_rarity`. Placing does not enter the room - no
        step is spent and none of its resources are gained until the player
        :meth:`move`s in. Outer-room drafts (target_cell -1) route to their
        off-grid placement instead. This is also the site that detects the
        archived_floorplan experiment trigger -- it fires on *choosing* an
        archived option, not on its earlier deal, so ``opt``'s own
        ``archived`` flag is threaded into :meth:`_place_room`.
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
        cost = self._effective_cost(room, opt)
        waived = self._pay(room, opt)

        # Drafting only PLACES the room behind the doorway. The player does
        # not enter it, pays no step, and gains none of its resources until
        # they move in (see :meth:`move`).
        self._place_room(room, pending.target_cell, opt.orientation,
                         entry_dir=OPPOSITE[pending.direction],
                         gem_cost=0 if waived else cost, archived=opt.archived)
        if pending.dowsed_slot == slot:
            # The Dowsing Rod pointed at this slot when the hand was last
            # dealt/redealt (draft.py::_pick_dowsing_slot) and the player
            # drafted it: mark the cell so its item roll (engine/items.py::
            # roll_room_items, fired later on first ENTRY) uses the Dowsing
            # Rod's own item-count table instead of the ordinary ladder.
            st.dowsing_marked_cells.add(pending.target_cell)
        del self.doorway_drafts[(pending.from_cell, pending.direction)]
        st.pending = None
        if (self.cfg.special_items and room.is_category("mechanical")
                and gear_wrench.held(st)):
            st.pending_wrench_room_id = room.id
            self.phase = Phase.WRENCH_PENDING
        else:
            self.phase = Phase.NAVIGATE
        self._check_termination()

    def _effective_cost(self, room: Room, opt) -> int:
        """Gem cost of an option: slot 0, the hand's first presented option,
        and free-category rooms all cost nothing.

        ``opt.cost_waived`` is the deal's grant of a free first option
        (draft.py::waive_first_option, an owner ruling). It coincides with
        slot 0 on every hand that dealt one, and carries the waiver to slot 1
        or 2 on a colour-selective hand whose earlier slots came up unfilled.
        A synthetic option built outside a dealt hand (:meth:`berry_pick`)
        carries neither and prices normally.

        Held items can waive or modify the remaining cost (Emerald Bracelet,
        Hall Pass, Stopwatch — see special_items.gem_cost_modifier)."""
        if opt.slot == 0 or opt.cost_waived:
            return 0
        if any(room.is_category(c) for c in self.free_categories):
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

    def _pay(self, room: Room, opt) -> bool:
        """Deduct the option's gem cost - in steps at 3:1 when the Hovel is placed.

        An active Stopwatch waives the payment (gems still required in hand;
        the waiver spends a charge here, at pay time, so affordability
        queries never consume it). Returns True when a Stopwatch waived the
        payment, so callers can tell a waived cost from a genuinely spent one
        (the gems_spent experiment trigger cares about this distinction)."""
        cost = self._effective_cost(room, opt)
        if cost <= 0:
            return False
        if self.cfg.special_items and special_items.stopwatch_waives_gems(self, cost):
            return True
        if self.hovel_placed:
            self.state.steps -= 3 * cost
        else:
            self.state.gems -= cost
        return False

    # ------------------------------------------------------------ WRENCH_PENDING

    def can_set_wrench_rarity(self, rarity_idx: int) -> bool:
        """Is picking ``rarity_idx`` (0..3, engine.model.RARITIES order) legal
        right now?

        Only ``phase is WRENCH_PENDING`` gates this -- all four levels are
        always offered (wiki: "moved freely to any of the four rarity
        levels"), including the room's own current one (that IS how a
        player declines to change anything, since :func:`decks.
        set_dynamic_rarity` is a no-op when the target already matches), so
        this phase can never dead-end.
        """
        return self.phase is Phase.WRENCH_PENDING and 0 <= rarity_idx < len(RARITIES)

    def set_wrench_rarity(self, rarity_idx: int) -> None:
        """Resolve the Gear Wrench's rarity pick for the room parked in
        ``state.pending_wrench_room_id``, then return to NAVIGATE.

        Moves the room's live-deck cards via :func:`decks.set_dynamic_rarity`
        (the current bucket it reads is ``state.dynamic_rarity``'s own
        fallback to ``room.rarity_idx``, so this is correct whether the room
        starts the day in its natal bucket, a previously-wrenched one, or one
        a same-day battery_pack/Conservatory override already moved it to).
        Records the permanent choice in ``state.permanent_rarity``, popping
        the entry when ``rarity_idx`` matches the room's own natal rarity --
        the same idempotent-pop convention ``set_dynamic_rarity`` itself uses
        -- so the persisted dict only ever holds genuine overrides.
        """
        assert self.can_set_wrench_rarity(rarity_idx), f"cannot set rarity {rarity_idx} here"
        st = self.state
        room_id = st.pending_wrench_room_id
        assert room_id is not None, "not awaiting a wrench choice"
        room = self.registry.by_id[room_id]
        set_dynamic_rarity(st, self.registry, room_id, rarity_idx, self.rng,
                           label="gear_wrench_set_rarity")
        if rarity_idx == room.rarity_idx:
            st.permanent_rarity.pop(room_id, None)
        else:
            st.permanent_rarity[room_id] = rarity_idx
        st.pending_wrench_room_id = None
        self.phase = Phase.NAVIGATE
        self._check_termination()

    # There is no decline: opening a door commits you to drafting one of the
    # dealt rooms. The hand's first presented option is always granted free
    # (draft.py::waive_first_option), so an affordable option always exists --
    # and a hand that dealt nothing at all never enters DRAFTING in the first
    # place (see open_door/choose_colour).

    def can_redraw_with_star(self) -> bool:
        """True when the Ink Well's star-for-redraw option is legal right now:
        DRAFTING, a pending hand, the Ink Well activated today
        (``state.ink_well_active``), and at least 1 star. The star balance is
        the only bound -- there is no per-draft cap, and this predicate never
        compares the balance to 50.
        """
        if self.phase is not Phase.DRAFTING or self.state.pending is None:
            return False
        if not self.state.ink_well_active:
            return False
        return self.state.stars >= 1

    def redraw(self, kind: RedrawKind) -> None:
        """Replace the whole pending hand via a Study, Classroom, die, or star
        redraw.

        STUDY costs 1 gem (needs the Study placed, max 8 per draft), FREE
        spends one of the hand's Classroom redraws, DIE spends an ivory die,
        STAR spends 1 permanent star (the Ink Well) with no per-draft cap.
        Applies to outer-room drafts too: an outer hand is reshuffled from the
        fixed outer pool via :meth:`_deal_outer_options` rather than the grid
        pipeline, since it has no doorway/from-room to redraw against.

        Provenance recorded here since outdoor Study/Die reroll access is not
        obvious from the datamined tables alone. Owner ruling from play ("assume the Study
        works outdoors; I think the reroll works on all drafts"), corroborated
        by Fandom's Outer Room page: "Ivory Dice may be used to reroll the pool
        of Outer Rooms, as may Gems if you drafted a Study inside before you
        drafted an Outer Room" -- naming exactly DIE and STUDY. That page could
        not be fetched directly (HTTP 402); the quote comes from search snippets
        that agreed across two independent queries. blueprince.wiki.gg, this
        project's usual source, does not mention outer rerolls either way.
        So: owner-ruled, externally corroborated, not datamined.

        Checks termination at the end: the redealt hand's ON_HAND_DEALT fire
        can itself drain steps (e.g. steps_for_gold), so a caller must check
        ``phase`` afterward, same as every other termination-checking action.
        """
        assert self.phase is Phase.DRAFTING and self.state.pending is not None
        st = self.state
        pending = st.pending
        match kind:
            case RedrawKind.STUDY:
                assert st.study_placed and st.gems >= 1 and pending.study_redraws_used < 8
                st.gems -= 1
                pending.study_redraws_used += 1
            case RedrawKind.FREE:
                assert pending.redraws_left > 0
                pending.redraws_left -= 1
            case RedrawKind.DIE:
                assert st.dice >= 1
                st.dice -= 1
                if shrine.blessing_active(self, "high_roller"):
                    st.coins += 5
            case RedrawKind.STAR:
                assert st.stars >= 1
                st.stars -= 1
        self._redeal_pending(pending)
        self._check_termination()

    def _redeal_pending(self, pending: PendingDraft) -> None:
        """Redeal ``pending`` in place and re-fire ON_HAND_DEALT for its new options.

        Shared tail of :meth:`redraw` (STUDY/FREE/DIE, each a paid cost) and
        :meth:`crown_block` (free): both hand off here once their own cost/
        recording logic is done. Splits outer-room drafts (fixed pool,
        ``target_cell == -1``) from the grid pipeline exactly as
        :meth:`redraw` always has. Does not check termination itself --
        callers do that after, since a caller-specific action (spending a
        die, granting a gem) may itself need to run first.

        Pushes the hand about to be discarded onto ``pending.rewind_stack``
        first (a shallow copy -- see the field's docstring), unconditionally:
        the history costs nothing to keep and the Chronograph's REWIND is
        gated on holding the item at :meth:`can_rewind` time, not on whether
        it was held when the redraw happened.
        """
        pending.rewind_stack.append(list(pending.options))
        pending.options.clear()
        pending.rotations_used = 0  # fresh hand, fresh rotation budget
        if pending.target_cell == -1:  # outer-room draft: fixed pool, not the grid pipeline
            self._deal_outer_options(pending, "outer_redraw")
        else:
            redeal(self.state, self.registry, self.cfg, self.rng, self.placed_ids, pending)
        # ON_HAND_DEALT fires again for the freshly redealt options -- unlike
        # ON_DRAFT_FROM (initial deal only), a room re-entering the hand on a
        # redraw is itself the event this hook exists to model.
        for opt in pending.options:
            effects.fire(self, self.registry.rooms[opt.room_idx], Hook.ON_HAND_DEALT)

    def can_crown_block(self, slot: int) -> bool:
        """True when the Crown of the Blueprints' once-per-hand filter can be
        used on the room dealt in ``slot`` of the current hand.

        DRAFTING only, a real dealt slot, special items enabled, and
        crown_of_the_blueprints.block_offered's own gates (item held, its
        data record still carries the tag, not already spent this hand, and
        the dealt room is a Red Room).
        """
        if self.phase is not Phase.DRAFTING or self.state.pending is None:
            return False
        if not self.cfg.special_items:
            return False
        pending = self.state.pending
        if not (0 <= slot < len(pending.options)):
            return False
        room = self.registry.rooms[pending.options[slot].room_idx]
        return crown_of_the_blueprints.block_offered(self.state, self.registry, room)

    def crown_block(self, slot: int) -> None:
        """Spend the Crown of the Blueprints' once-per-hand filter on the Red
        Room dealt in ``slot``.

        Filters that room id from every draw for the rest of today (recorded
        in ``SpecialItemsState.crown_blocked_rooms``, read by
        draft.py::room_draftable -- a draw-time filter, never a deck removal,
        so deck sizes and rarity legality are untouched), grants 1 gem, and
        redeals the hand for free via :meth:`_redeal_pending` (which also
        resets ``crown_block_used`` so a later hand can use it again).
        """
        assert self.can_crown_block(slot), "Crown of the Blueprints filter not available"
        st = self.state
        pending = st.pending
        room_id = self.registry.rooms[pending.options[slot].room_idx].id
        if room_id not in st.special.crown_blocked_rooms:
            st.special.crown_blocked_rooms.append(room_id)
        st.special.crown_block_used = True
        st.gems += 1
        self._redeal_pending(pending)
        self._check_termination()

    def can_rewind(self) -> bool:
        """True when the Chronograph's REWIND option is available: DRAFTING,
        special items enabled, a Chronograph held, and at least one prior
        hand still on ``pending.rewind_stack``.

        Wiki (blueprince.wiki.gg/wiki/Chronograph): "after a redraw by any
        method, a new option appears to REWIND last draft" -- so the option
        is absent on the very first (un-redrawn) hand, when the stack is
        still empty.
        """
        if self.phase is not Phase.DRAFTING or self.state.pending is None:
            return False
        if not self.cfg.special_items:
            return False
        if not special_items.chronograph_active_from_state(self.state, self.registry):
            return False
        return bool(self.state.pending.rewind_stack)

    def rewind(self) -> None:
        """Pop the last hand off ``pending.rewind_stack`` and restore it as
        the pending options, re-firing ON_HAND_DEALT for each -- the wiki:
        rewinding "acts as a normal redraw but with the three rooms drawn
        being fixed, activating effects that rely on drawing a floorplan".

        NOT a state restore: no RNG is re-rolled, no resource is spent, and
        no deck/pool state is touched -- ``pending.options`` is simply
        overwritten from the remembered list (owner ruling: FREE, UNLIMITED,
        one-way). The hand being left is deliberately NOT pushed back onto
        the stack (unlike :meth:`_redeal_pending`'s own push), so repeated
        rewinds walk strictly backward through every prior hand to the
        original deal and then stop -- the stack can never oscillate.

        Resets ``rotations_used`` to 0, same as an ordinary redeal
        (:meth:`_redeal_pending`): the restored hand is once again the
        CURRENT hand, so it gets a fresh rotation budget on the same terms
        any other current hand would. ``round_num`` is left untouched -- it
        exists solely to gate draft.py::_resolve_free_gem's RNG-driven
        Free/Gem Draw roll, which a rewind never performs.
        """
        assert self.can_rewind(), "REWIND not available"
        pending = self.state.pending
        pending.options = pending.rewind_stack.pop()
        pending.rotations_used = 0  # fresh hand, fresh rotation budget
        for opt in pending.options:
            effects.fire(self, self.registry.rooms[opt.room_idx], Hook.ON_HAND_DEALT)
        self._check_termination()

    def _free_rotation_source(self) -> bool:
        """Is a free-rotation source in play for the current hand?"""
        st = self.state
        if self.phase is not Phase.DRAFTING or st.pending is None:
            return False
        if st.pending.target_cell == -1:  # outer-room draft: no doorway to rotate against
            return False
        if special_items.ornate_compass_active(self) or self.rotunda_placed:
            return True
        return dovecote.in_current_hand(self)

    def _dancer_rotation_source(self) -> bool:
        """Is Blessing of the Dancer's paid rotation (1 gem per spin) usable right now?

        Same phase/target-cell gating as :meth:`_free_rotation_source`, plus the
        blessing being active and at least 1 gem in hand.
        """
        st = self.state
        if self.phase is not Phase.DRAFTING or st.pending is None:
            return False
        if st.pending.target_cell == -1:  # outer-room draft: no doorway to rotate against
            return False
        return shrine.blessing_active(self, "dancer") and st.gems >= 1

    def rotation_available(self) -> bool:
        """Can the current hand's floorplans be rotated right now (free or paid)?

        The Ornate Compass grants this on every draft while it is held; the
        Rotunda grants it while placed on the grid; the Dovecote grants it only
        while it is one of the drawn options; Blessing of the Dancer grants it
        for 1 gem per spin (:meth:`_dancer_rotation_source`). This overrides the
        random orientation roll - the player rotates the options at will.

        Outer-room drafts sit off the grid with a fixed orientation and no
        entry doorway (``target_cell == -1``), so rotation never applies there.

        Even with a source in play, each hand gets a finite rotation budget of
        ``max(legal orientations per option) - 1``. Rotation advances every
        option one position around its own legal cycle, so that many rotations
        already reach every orientation of every option - one more only revisits
        hand states already seen. Without the cap, rotation is a free cyclic
        action (period lcm <= 12; 1 when the doorway pins every option), and a
        deterministic policy whose argmax is "rotate" around the cycle loops on
        it forever. The Dancer's per-spin gem cost is a further, independent
        brake on top of this budget.
        """
        if not (self._free_rotation_source() or self._dancer_rotation_source()):
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
        out still replay. Spends 1 gem when the only source in play is Blessing
        of the Dancer (a free source, if also present, is used instead).
        """
        free = self._free_rotation_source()
        assert free or self._dancer_rotation_source(), "no rotation source in play"
        if not free:
            self.state.gems -= 1
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
        # ON_ARRIVE fires on every arrival, including re-entry -- unlike
        # ON_ENTER (inside _enter, above), it is not gated on st.entered.
        effects.fire(self, self.registry.rooms[st.grid[nb]], Hook.ON_ARRIVE)
        if self.cfg.special_items:
            special_items.on_arrive(self, nb)
        self._check_termination()

    def move_to(self, cell: int) -> None:
        """Walk to ``cell``, one step per room, re-routing after every hop.

        The route is recomputed before each step rather than planned once
        and replayed: the Vestibule re-locks one of its own doors on every
        arrival, including possibly the very door a plan made before that
        arrival meant to use next, so a stale multi-hop plan can no longer
        be trusted past the first room that might do that. ``cell`` must be
        reachable right now (asserted, same contract as before); if a later
        hop's own arrival strands the walk before it gets there -- the only
        way that can happen is the same Vestibule re-lock, closing the one
        remaining way through -- this stops in place instead of asserting,
        leaving ``state.pos`` short of ``cell``. Callers that need the walk
        to have actually arrived must check ``state.pos`` themselves.
        """
        assert self.phase is Phase.NAVIGATE
        first = True
        while self.state.pos != cell:
            path = self._path_dirs(cell)
            if path is None:
                assert not first, "cell not reachable"
                return
            first = False
            self.move(path[0])
            if self.phase is not Phase.NAVIGATE:
                return

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

    def _roll_new_segments(self, room: Room, cell: int, orientation: int,
                           entry_dir: int | None = None) -> None:
        """Roll lock/security state for the room's doors on fresh segments.

        The segment a room was drafted through is already DOOR_OPEN; a door
        facing an already-rolled locked or security segment opens it for free
        (in-drafting, as in the real game) - so a locked door can never sit
        between two connected placed rooms, and locks only ever gate frontier
        drafting. Only doors creating a segment for the first time roll.
        ``entry_dir`` is this room's own doorway direction the player entered
        through (see grid.py entry_dir), passed straight to locks.roll_segment
        so an always-locked room (Great Hall) can price its side doorways.

        In-drafting into an already-rolled DOOR_SECURITY segment (site B of the
        security_door experiment trigger) fires it -- the wiki's "opening a
        security door in a different room by drafting into it also counts."
        A DOOR_LOCKED segment converted the same way does not fire anything:
        only unlocking/bypassing a *security* door counts. This can fire up to
        3 times in one call (one per fresh-but-already-rolled security segment
        the new room's orientation faces), which is expected, not a bug.
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
                # Sealed segments belong to the lever gate, not the lock system;
                # in-drafting (placing a room that faces the door) does NOT open
                # them. Only the lever room's ON_ENTER event can unseal.
                if existing not in (DOOR_OPEN, DOOR_SEALED):
                    st.door_state[seg] = DOOR_OPEN
                    st.door_version += 1
                    if existing == DOOR_SECURITY and st.experiment.trigger_id == "security_door":
                        experiments.trigger_success(self)
                continue
            state, extra = roll_segment(
                st, self.registry.lock_rules, room, cell, d, self.rng, entry_dir)
            st.door_state[seg] = state
            if extra:
                self.door_search_cost[seg] = extra
            st.door_version += 1

    def _place_room(self, room: Room, cell: int, orientation: int,
                    entered: bool = False, entry_dir: int | None = None,
                    gem_cost: int = 0, archived: bool = False) -> None:
        """Put ``room`` on the grid at ``cell`` with the given door orientation.

        Rolls lock state for its fresh door segments, updates the placed-id /
        room-cell indexes and progress counters, detects and fires any
        placement-site experiment trigger and any active Shrine blessing/curse
        effect (:func:`shrine.on_room_drafted`), then fires the room's ON_PLACE
        hook, its own ON_DRAFT_ROOM hook (effects opted in via include_self
        react to their own draft), and ON_DRAFT_ROOM on every other placed
        room (relational effects like the Nursery).
        ``entered=True`` is only used for the Entrance Hall at day start.
        ``entry_dir`` is this room's own doorway direction the player entered
        through (see :meth:`_roll_new_segments`); omitted by callers that
        place a room without drafting through it (day-start Entrance Hall,
        Foundation carryover). ``gem_cost`` is the nominal gem cost paid for
        this draft (0 if free, waived, or not drafted through :meth:`choose`)
        -- see :func:`experiments.on_room_drafted`. ``archived`` is the chosen
        ``DraftOption.archived`` flag (False for calls that bypass a real
        draft option, e.g. tests placing a room directly).
        """
        st = self.state
        st.grid[cell] = room.idx
        st.placed_doors[cell] = orientation
        st.entered[cell] = entered
        self._roll_new_segments(room, cell, orientation, entry_dir)
        self.placed_ids.add(room.id)
        if room.id == "the_foundation":
            # First (and only) time this attempt it is drafted: record where, so
            # carryover() -> next day's GameConfig.foundation_cell/doors can
            # re-place it at reset() on every later day (see above).
            st.foundation_cell = cell
            st.foundation_doors = orientation
        prev = self.room_cells.get(room.id)
        if prev is None or cell < prev:
            self.room_cells[room.id] = cell
        self.rooms_placed += 1
        self.deepest_rank = max(self.deepest_rank, rank_of(cell))
        if not entered:  # entered=True is only the pre-placed Entrance Hall; skip draft counting for it
            self.drafted_rooms.append(room.name)
            root_id = root_base_id(self.registry, room)
            self.state.draft_counts[root_id] = self.state.draft_counts.get(root_id, 0) + 1
            # After the grid write above (so a counting effect this fire may
            # trigger, e.g. keys_per_hallway_pair, sees the room that just
            # triggered it) and before ON_PLACE below (a Weight Room's own
            # step-halving must resolve after any experiment effect that
            # already touched steps). No currently live effect places a room,
            # deals a hand, opens a container, or digs -- add_aquariums
            # (implemented) is the wiki's own designed loop through these
            # triggers: an Aquarium is a Shop, Red, Hallway and Bedroom room at
            # once, so drafting one while any of those four triggers is
            # configured re-fires it, and each fire injects more Aquariums into
            # the decks. That loop cannot recurse WITHIN this call, because
            # apply_effect's add_aquariums arm only mutates deck/rarity state
            # (decks.inject_rooms_undealt, decks.set_dynamic_rarity) and never
            # calls _place_room, open_door, or choose. ACROSS separate calls
            # (one per doorway drafted) it is bounded by the finite grid: each
            # fire only makes MORE Aquariums draftable, it does not itself
            # place one, so the number of times this effect can fire in a day
            # is capped by the number of rooms the day can ever place -- at
            # most the 43 non-Entrance-Hall, non-Antechamber cells, usually far
            # fewer once the step budget runs out. draft.py::room_draftable's
            # one-copy rule still blocks every OTHER room id from repeating
            # (waived for aquarium__experiment specifically, once
            # add_aquariums has fired, and for the Chamber of Mirrors
            # globally). The same two guarantees (no live effect places a
            # room/deals/opens/digs; the grid is finite) cover
            # _roll_new_segments' own security_door fire above (site B), which
            # runs even earlier in this method -- before placed_ids, room_cells,
            # and rooms_placed are updated.
            experiments.on_room_drafted(self, room, cell, entry_dir, gem_cost, archived)
            shrine.on_room_drafted(self, room)
            self._park_florealis_gems(room, cell)
        effects.fire(self, room, Hook.ON_PLACE)
        if self.state.foyer_placed:
            # Covers a Hallway placed AFTER the Foyer: its own fresh segments
            # (just rolled above) come out unlocked too. A Hallway placed
            # BEFORE the Foyer is swept retroactively by foyer.py's own
            # ON_PLACE handler when the Foyer itself lands.
            foyer.unlock_hallway_segments(self, cell)
        if self.cfg.special_items:
            special_items.on_place(self, room, cell)
        # The room's own reaction to its own draft (Tomb's own Dead End,
        # Nursery's own Bedroom category) fires before the broadcast to other
        # rooms below. Passing context_room=room lets each ON_DRAFT_ROOM
        # handler tell a self-fire (room is ctx_room) from a relational one
        # and gate on the effect's include_self param. st.draft_hook_orientation
        # carries this same just-drafted room's actual orientation (see its
        # field doc) through both fires below, for handlers that need it.
        st.draft_hook_orientation = orientation
        effects.fire(self, room, Hook.ON_DRAFT_ROOM, context_room=room)
        # Relational draft hooks on every other placed room (Nursery etc.).
        for other_cell, idx in enumerate(st.grid):
            if idx >= 0 and other_cell != cell:
                effects.fire(self, self.registry.rooms[idx], Hook.ON_DRAFT_ROOM,
                             context_room=room)

    def _park_florealis_gems(self, room: Room, cell: int) -> None:
        """Park a newly drafted Green Room's gem flowers in its own cell.

        Called from the draft branch of :meth:`_place_room`, which is where the
        mechanic's trigger actually is: an active Florealis blooms "all newly
        drafted Green Rooms" and leaves every Green Room already on the estate
        alone, so there is nothing to do when the constellation is activated
        and everything to do at each later draft.

        That siting is also the whole of the idempotency. This runs once per
        drafted room because a cell is drafted once, so no per-cell record is
        needed and the number of Observatories on the estate cannot multiply
        the payout -- an activation-time sweep, or a broadcast hook like
        ON_DRAFT_ROOM (which fires once per placed room, not once per draft),
        would each have needed a guard to avoid paying N times.

        The gems land in ``spread_pending`` rather than in the player's hands:
        a drafted room is not entered, and its contents wait there until the
        player walks in (:meth:`_collect_spread`). No Conference Room redirect
        applies -- these are the room's own contents, not a spread reaching out
        to other cells, and nothing published says otherwise.
        """
        if not room.is_category("green"):
            return
        gems = constellations.green_room_gems(
            self.registry.constellations, self.state, root_base_id(self.registry, room))
        if gems:
            self.state.spread_pending.setdefault(cell, []).append(("gem", gems))

    def _collect_spread(self, cell: int) -> None:
        """Grant every resource parked in ``cell`` by GameState.spread_pending.

        Fires on EVERY arrival at ``cell``, including re-entry, not only first
        entry -- a room walked through before the Secret Garden spread into it
        must still pay out on the player's next arrival. Each entry's ``what``
        is either a food.dishes id, eaten via special_items.eat_food, or a
        grant_item item kind; the two namespaces never collide, so a plain
        membership check on the dish table decides the branch.
        """
        entries = self.state.spread_pending.pop(cell, None)
        if not entries:
            return
        dishes = self.registry.item_rules["food"]["dishes"]
        for what, count in entries:
            if what in dishes:
                special_items.eat_food(self, what, count)
            else:
                grant_item(self, what, count)

    def _collect_payroll_pending(self, cell: int) -> None:
        """Grant every resource GameState.payroll_pending owes THIS CELL's room id.

        Run Payroll's own arrival-not-first-entry payout -- deliberately
        separate from _collect_spread/spread_pending immediately above (see
        effects/rooms/office.py's module docstring for why Run Payroll must
        never touch spread_pending or the Conference Room). Keyed by room id
        rather than cell, so a target drafted AFTER the terminal was used
        still pays out here once it is entered. Fires on every arrival, the
        same "not gated on first entry" timing as _collect_spread.
        """
        idx = self.state.grid[cell]
        if idx < 0:
            return
        entries = self.state.payroll_pending.pop(self.registry.rooms[idx].id, None)
        if not entries:
            return
        for what, count in entries:
            grant_item(self, what, count)

    def _enter(self, cell: int) -> None:
        """First-entry bookkeeping for ``cell``; no-op if already entered.

        Fires the room's ON_ENTER effects and item rolls exactly once. With
        door locks on, visiting Security unlocks the terminal's offline mode,
        and keycard source rooms roll their chance to hand over the Keycard.
        """
        st = self.state
        if cell == ANTECHAMBER_CELL:
            st.antechamber_reached = True  # milestone: first arrival at rank 9 center
        # Parked resources pay out on every arrival, not just first entry.
        self._collect_spread(cell)
        self._collect_payroll_pending(cell)
        if rank_of(cell) >= 8:
            # Same Day Delivery's trigger; idempotent after the first Rank 8 arrival.
            mail_room.reach_rank8(self)
        if st.entered[cell]:
            return
        st.entered[cell] = True
        experiments.on_room_entered(self, cell)
        room = self.registry.rooms[st.grid[cell]]
        effects.fire(self, room, Hook.ON_ENTER)
        roll_room_items(self, room, cell)
        if cell in st.cloister_mila_bonus_cells:
            # Cloister of Mila's extra item: a guaranteed, luck-immune pull
            # from the same table roll_room_items uses for its own luck-
            # immune "random" guaranteed items (Closet/Walk-In/Attic).
            idx = self.rng.roll_weighted(
                "extra_item_kind", tuple(w for _, w in EXTRA_ITEM_TABLE))
            grant_item(self, EXTRA_ITEM_TABLE[idx][0], 1)
        if self.cfg.special_items:
            special_items.on_enter(self, room, cell)
            if effects.provides_capability(room.id, Capability.COMMERCE):
                shops.on_enter_shop(self, room)
        if self.cfg.door_locks:
            keycard.roll_source_room_grant(self, room)
        # Antechamber lever gate: entering a lever room opens its sealed segment.
        # Per the sim's "player solves the puzzle of any room they enter" doctrine,
        # entering the room pulls its lever subject to the access cost below.
        # Only fires when antechamber_levers is True (config gate). Each lever
        # room's own eligibility and cost logic lives in its effects/rooms
        # module (design doc antechamber-lever-design.md), registered via
        # Capability.LEVER. The Greenhouse's South lever is a separate path,
        # handled entirely by special_items.install_lever.
        if self.cfg.antechamber_levers and effects.provides_capability(room.id, Capability.LEVER):
            effects.pull_lever(self, room.id, cell)

    def lever_key_cost(self, cell: int) -> int:
        """Keys that pulling ``cell``'s Antechamber lever would spend right now.

        Only the Great Hall's locked prize-room side door costs a key; every
        other lever room is free (0), per its own registered cost function
        (Capability.LEVER). Deliberately ignores ``state.entered[cell]`` - the
        lever only fires on first entry, so a caller reasoning about a
        *future* walk must check ``state.entered`` itself.
        """
        st = self.state
        if not self.cfg.antechamber_levers:
            return 0
        if st.grid[cell] < 0:
            return 0
        room = self.registry.rooms[st.grid[cell]]
        if not effects.provides_capability(room.id, Capability.LEVER):
            return 0
        return effects.lever_key_cost(room.id, self, cell)

    def inject_rooms(self, room_ids: list[str]) -> None:
        inject_rooms(self.state, self.registry, room_ids, self.rng)

    # ---------------------------------------------------------- upgrade disks

    def catacombs_unlocked(self) -> bool:
        """True when today's outer room grants Catacombs access AND has been entered today.

        The Catacombs are unlocked by drafting and physically entering the Tomb on the same
        day: the sim assumes the player solves any puzzle in a room they enter, so entering
        the Tomb solves the angel-statue puzzle. Same-day physical access is still required
        (owner decision, see docs/rooms.md). The flag is NOT a permanent carry-over.
        """
        outer_room = self.drafted_outer_room
        return (
            outer_room is not None
            and outer_room.unlocks_catacombs
            and self.state.outer_room_entered
        )

    def disk_reader_here(self) -> bool:
        """True when the player's current location has an Upgrade Disk terminal.

        Checks the grid room at the player's cell, or the outer room when inside it
        (inside_outer_room is True), since Shelter is an outer room with a terminal.
        Off-grid and not inside the outer room, checks the current area-graph node's
        own disk_reader flag -- Blackbridge Grotto is the 5th terminal and has no
        rooms.json record, so it carries the flag on its areas.json node instead.
        """
        if self.inside_outer_room:
            outer_room = self.drafted_outer_room
            return outer_room is not None and outer_room.disk_reader
        st = self.state
        # Off-grid (and not inside the outer room): st.pos still holds the on-grid
        # cell the player departed from, so the area check must run BEFORE the grid
        # check below, or an off-grid stand at a non-reader area would wrongly read
        # off whatever room sits at that stale cell instead of the area's own flag.
        if st.area is not None:
            area = self.registry.area_graph.nodes.get(st.area)
            return area is not None and area.disk_reader
        if 0 <= st.pos < len(st.grid) and st.grid[st.pos] >= 0:
            return self.registry.rooms[st.grid[st.pos]].disk_reader
        return False

    def held_disk_ids(self) -> list[str]:
        """Item ids starting with 'upgrade_disk_', sorted for deterministic consumption order."""
        return sorted(
            item_id for item_id in self.state.inventory if item_id.startswith("upgrade_disk_")
        )

    def _terminal_room_id_here(self) -> str | None:
        """Id of the Upgrade Disk terminal at the player's current location.

        Mirrors :meth:`disk_reader_here`'s own outer-room/grid/off-grid split, for
        experiments.on_terminal_accessed's per-terminal dedup key. A room id
        on-grid or inside the outer room; the area-graph node id off-grid
        (Blackbridge Grotto's "blackbridge_grotto", which has no room id at
        all). None only where disk_reader_here() would be False, which
        insert_disk already rules out via can_insert_disk().
        """
        if self.inside_outer_room:
            outer_room = self.drafted_outer_room
            return outer_room.id if outer_room is not None else None
        st = self.state
        # Same off-grid-before-grid ordering as disk_reader_here(), and for the
        # same reason: st.pos still names the departure cell while off-grid.
        if st.area is not None:
            area = self.registry.area_graph.nodes.get(st.area)
            return area.id if area is not None and area.disk_reader else None
        if 0 <= st.pos < len(st.grid) and st.grid[st.pos] >= 0:
            return self.registry.rooms[st.grid[st.pos]].id
        return None

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
        A successful insert also fires the terminal_access experiment trigger
        (experiments.on_terminal_accessed) -- a failed one (no slot selectable)
        does not, since nothing was actually consumed or changed.

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
        experiments.on_terminal_accessed(self, self._terminal_room_id_here())
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

    # -------------------------------------------------------- experiments

    def at_laboratory_terminal(self) -> bool:
        """True when the player is standing in a room providing
        ``Capability.EXPERIMENT_TERMINAL`` (the Laboratory).

        Distinct from ``disk_reader_here()``: Security, Laboratory, Office and
        Shelter all carry ``flags.disk_reader``, but the Experimental Setup
        menu is specific to the Laboratory's own terminal, so this checks a
        dedicated capability rather than the shared disk-reader flag. The
        Laboratory has no upgrade variants and no outer-room presence, so an
        exact on-grid capability match is the whole check.
        """
        if self.inside_outer_room or self.off_grid:
            return False
        st = self.state
        if not (0 <= st.pos < len(st.grid)) or st.grid[st.pos] < 0:
            return False
        return effects.provides_capability(
            self.registry.rooms[st.grid[st.pos]].id, Capability.EXPERIMENT_TERMINAL)

    def can_start_setup(self) -> bool:
        """True when operating the Experimental Setup terminal is legal right now.

        Requires NAVIGATE, standing at the Laboratory terminal, and no
        experiment already configured today -- "only one experiment can be
        active on any given day" (wiki), so a second setup attempt while one
        is configured offers nothing new.
        """
        return (
            self.phase is Phase.NAVIGATE
            and self.at_laboratory_terminal()
            and not self.state.experiment.configured
        )

    def start_setup(self) -> None:
        """Operate the terminal: draw 3 triggers and 3 effects, enter EXPERIMENT_PENDING.

        Draws uniformly from the base pool only (draw_offers); the packet
        pool stays undrawable until the packet subsystem (phases 5-8) is
        authorised. A no-op if an experiment is already configured today --
        mirrors can_start_setup so a caller that skips the mask still can't
        redraw a live experiment's offers out from under it.
        """
        if not self.can_start_setup():
            return
        st = self.state
        offered_triggers, offered_effects = experiments.draw_offers(
            self.registry, self.rng, self.cfg, st)
        st.experiment.offered_triggers = offered_triggers
        st.experiment.offered_effects = offered_effects
        self.phase = Phase.EXPERIMENT_PENDING

    def choose_experiment_trigger(self, index: int) -> None:
        """Choose one of the three offered triggers.

        Only legal in EXPERIMENT_PENDING with 0 <= index < 3 and no trigger
        chosen yet this setup. Once both a trigger and an effect are chosen,
        the experiment starts (see _maybe_finish_experiment_setup).
        """
        st = self.state
        assert self.phase is Phase.EXPERIMENT_PENDING, \
            "choose_experiment_trigger only legal in EXPERIMENT_PENDING"
        assert st.experiment.trigger_id is None, "trigger already chosen this setup"
        assert 0 <= index < 3, f"index must be 0, 1, or 2; got {index}"
        st.experiment.trigger_id = st.experiment.offered_triggers[index]
        self._maybe_finish_experiment_setup()

    def choose_experiment_effect(self, index: int) -> None:
        """Choose one of the three offered effects.

        Only legal in EXPERIMENT_PENDING with 0 <= index < 3 and no effect
        chosen yet this setup. Once both a trigger and an effect are chosen,
        the experiment starts (see _maybe_finish_experiment_setup).
        """
        st = self.state
        assert self.phase is Phase.EXPERIMENT_PENDING, \
            "choose_experiment_effect only legal in EXPERIMENT_PENDING"
        assert st.experiment.effect_id is None, "effect already chosen this setup"
        assert 0 <= index < 3, f"index must be 0, 1, or 2; got {index}"
        st.experiment.effect_id = st.experiment.offered_effects[index]
        self._maybe_finish_experiment_setup()

    def _maybe_finish_experiment_setup(self) -> None:
        """Once both a trigger and an effect are chosen, start the experiment.

        Clears the offered lists, returns phase to NAVIGATE, and -- since the
        "immediately" trigger needs no separate firing site -- fires it right
        here, exactly once, the moment the experiment becomes active. Checks
        termination at the end: "immediately" paired with steps_for_gold can
        zero out steps on the spot.
        """
        st = self.state
        if st.experiment.trigger_id is None or st.experiment.effect_id is None:
            return
        st.experiment.offered_triggers = ()
        st.experiment.offered_effects = ()
        self.phase = Phase.NAVIGATE
        if st.experiment.trigger_id == "immediately":
            experiments.trigger_success(self)
        self._check_termination()

    def can_toggle_experiment(self) -> bool:
        """True when pausing/resuming the active experiment is legal right now.

        Requires NAVIGATE, standing at the Laboratory terminal, and a
        configured experiment -- "paused and resumed... from the terminal"
        (wiki).
        """
        return (
            self.phase is Phase.NAVIGATE
            and self.at_laboratory_terminal()
            and self.state.experiment.configured
        )

    def toggle_experiment(self) -> None:
        """Flip the configured experiment's paused flag."""
        assert self.can_toggle_experiment(), "must hold a configured experiment at the terminal"
        st = self.state
        st.experiment.paused = not st.experiment.paused

    def _terminate(self, reason: str) -> None:
        """End the day; this is the sole place Phase.TERMINAL is set.

        Every day-ending route in this module runs through here (called only
        from _check_termination), so it is the single fire site for
        ON_DAY_END and ON_DAY_END_ALL.
        """
        self.phase = Phase.TERMINAL
        self.termination_reason = reason
        st = self.state
        # An undelivered Same Day package falls back to AWAITING for a later day.
        mail_room.resolve_same_day_end(self)
        # The "current room" for day-end effects (Tomorrow Rooms): the
        # drafted outer room while standing inside it, otherwise the on-grid
        # room at the player's position. Off-grid but not inside the outer
        # room (e.g. at the doorstep) has no current room.
        room = None
        if self.inside_outer_room:
            room = self.drafted_outer_room
        elif not self.off_grid and st.grid[st.pos] >= 0:
            room = self.registry.rooms[st.grid[st.pos]]
        if room is not None:
            effects.fire(self, room, Hook.ON_DAY_END)
        # ON_DAY_END_ALL: broadcast to every room placed on the grid, regardless
        # of where the player ends the day -- the day-end counterpart to
        # ON_DRAFT_ROOM's broadcast in _place_room. Room-wide effects that need
        # the whole grid rather than just where the day ends (e.g. the Clock
        # Tower's Tomorrow-room tally, effects/rooms/clock_tower.py) hang off
        # this instead of ON_DAY_END.
        for idx in st.grid:
            if idx >= 0:
                effects.fire(self, self.registry.rooms[idx], Hook.ON_DAY_END_ALL)

    def _check_termination(self) -> None:
        """End the day when out of steps or no purposeful action remains.

        Called after every state-changing action. The day does NOT end when the
        player reaches the Antechamber — Room 46 is the objective. "dead_end"
        means no frontier doorway exists and the Antechamber is unreachable;
        "out_of_steps" also covers having steps left but nothing useful within
        the budget (see :meth:`_action_in_budget`).
        """
        st = self.state
        if st.steps <= 0:
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
        costs = self.area_route_costs()
        for node_id, result in costs.items():
            if node_id == st.area:
                continue  # no self-travel
            if st.steps > result[0]:
                return True
        return False

    def _frontier_lock_affordable(self, cell: int, direction: int,
                                  path_key_cost: int) -> bool:
        """Can the DOOR_LOCKED frontier segment at ``cell``->``direction``
        actually be opened, given ``path_key_cost`` regular keys already
        earmarked by :meth:`key_cost_map` to walk there?

        True when enough regular keys remain for this door's own
        :meth:`lock_open_cost` (the Great Hall side-door search surcharge
        included) -- or just 1 key when an active Stopwatch would refund the
        rest, the same rule :meth:`can_use_key_at_lock` applies at the
        pending lock itself (wiki: "At least one key is still required for
        the option to use a key to appear, even though it isn't spent").
        The Stopwatch refund is NOT applied to ``path_key_cost``: that value
        comes from :meth:`key_cost_map`, which earmarks keys for OTHER
        locked doors already crossed to reach ``cell`` -- a path-wide
        refund would mean simulating the Stopwatch's single global charge
        (``state.special.stopwatch_left``) draining in walk order across
        however many locked doors the path crosses, which is a separate,
        pre-existing gap in ``key_cost_map`` itself (it only ever discounts
        the Master Key there, see ``_nav_bfs``), not something this one
        doorway's own affordability check can or should correct. Here the
        refund is a single, one-time application to this one pending lock,
        exactly matching what ``can_use_key_at_lock`` does when the player
        actually reaches it.

        Also True when the door opens without spending a regular key: a
        held Master Key (:func:`special_items.can_open_locked_free`, the
        same deterministic predicate ``key_cost_map``'s own BFS already
        uses for path costs) or a fitting Silver Key / Prism Key (the
        LOCK_PENDING special-keys-menu's own held+fits rule --
        :meth:`_special_key_held`/:meth:`_special_key_fits`; the Basement
        Key's ``fits()`` is always False for an on-grid segment and the
        reserved secret_garden_key/key_8 rows are permanently masked, so
        only these two are worth asking here).

        Must stay pure (no RNG, no state mutation): :meth:`_action_in_budget`
        runs on every state-changing action via :meth:`_check_termination`.
        A held Lock Pick Kit / Pick Sound Amplifier is deliberately NOT
        counted: :func:`special_items.open_locked_free` rolls the RNG and
        mutates per-day attempt counters to resolve it, and it is
        probabilistic besides -- a failed pick still falls through to
        spending a real key, so a lockpick-only door is conservatively
        treated the same as an unopenable one here. Being permissive
        instead would risk the open/abandon-forever loop this check exists
        to prevent (trying a locked frontier door is always free, see
        :meth:`frontier_doorway_triable`).
        """
        st = self.state
        refund = (self.cfg.special_items and st.special.stopwatch_left > 0)
        needed = 1 if refund else self.lock_open_cost(cell, direction)
        if st.keys >= path_key_cost + needed:
            return True
        if special_items.can_open_locked_free(self):
            return True
        if not self.cfg.special_items:
            return False
        return any(self._special_key_held(key_id)
                   and self._special_key_fits(key_id, cell, direction)
                   for key_id in ("silver_key", "prism_key"))

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
            if seg == DOOR_SEALED:
                continue  # sealed: no key can open it; not a valid action
            if seg == DOOR_LOCKED and not self._frontier_lock_affordable(cell, d, key_cost[cell]):
                continue
            if seg == DOOR_SECURITY and not self.security_openable():
                if not toggle_ok:
                    continue
            return True
        for cell in range(N_CELLS):
            if 0 < dist[cell] <= st.steps and not st.entered[cell]:
                return True
        # Area travel to Room 46 (off-grid objective): counts as a purposeful action.
        if not self.off_grid:
            result = self.area_route_cost("room_46")
            if result is not None and st.steps >= result[0]:
                return True
        return self.outer_draft_available()

    def _antechamber_reachable(self) -> bool:
        return ANTECHAMBER_CELL in self.reachable_cells()

    # ------------------------------------------------------------------ info

    def is_done(self) -> tuple[bool, str]:
        """Return (day over?, reason); the reason is "" while the day is running."""
        return self.phase is Phase.TERMINAL, self.termination_reason

    def success(self) -> bool:
        """Did the player reach Room 46 today?"""
        return self.state.room46_reached
