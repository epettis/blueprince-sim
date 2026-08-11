"""Mutable per-episode state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .experiments import ExperimentState
from .model import Room
from .shops import ShopsState
from .special_items import SpecialItemsState


@dataclass(slots=True)
class DeckState:
    """One solitaire deck: a shuffled list of room indices dealt from a cursor.

    Cards before ``pos`` have been dealt this cycle. ``deal_next`` scans from
    ``pos`` for the first card passing a predicate, swaps it to ``pos`` and
    advances, so no card repeats until the deck depletes and is reshuffled.
    """

    order: list[int] = field(default_factory=list)  # shuffled cards; each is a Room.idx
    pos: int = 0  # deal cursor: cards before pos are already dealt this cycle

    def remaining(self) -> int:
        """Number of undealt cards left in this cycle."""
        return len(self.order) - self.pos

    def size(self) -> int:
        return len(self.order)

    def deal_next(self, predicate) -> int | None:
        """Deal the first undealt card for which ``predicate(card)`` is true.

        Returns the room idx and marks it dealt (swap-to-cursor), or None when
        no undealt card qualifies - the caller decides whether to reshuffle.
        """
        for i in range(self.pos, len(self.order)):
            card = self.order[i]
            if predicate(card):
                self.order[i] = self.order[self.pos]
                self.order[self.pos] = card
                self.pos += 1
                return card
        return None

    def reshuffle(self, shuffler, drop: set[int] | None = None) -> None:
        """Reshuffle the whole deck and reset the cursor; ``drop`` removes cards for good."""
        if drop:
            self.order = [c for c in self.order if c not in drop]
        shuffler(self.order)
        self.pos = 0

    def replace_card(self, old_idx: int, new_idx: int) -> int:
        """Rewrite every card equal to ``old_idx`` as ``new_idx``; return count changed.

        Covers dealt cards as well as undealt ones. An Upgrade Disk retires the
        base floorplan from the pool outright, and ``deal_next``'s attempt-3
        reshuffle resets the cursor to 0 — so leaving a dealt base card behind
        would let the un-upgraded room be drafted again later the same day.
        No card moves position and the cursor is untouched.
        """
        count = 0
        for i, card in enumerate(self.order):
            if card == old_idx:
                self.order[i] = new_idx
                count += 1
        return count

    def remove_card(self, room_idx: int) -> int:
        """Drop every card equal to ``room_idx``; return how many were removed.

        Removals before the cursor drag it back with them, so ``order[:pos]``
        keeps meaning "already dealt this cycle". Same rationale as
        :meth:`replace_card`: the retired floorplan must not survive a reshuffle.
        """
        kept, removed, new_pos = [], 0, self.pos
        for i, card in enumerate(self.order):
            if card == room_idx:
                removed += 1
                if i < self.pos:
                    new_pos -= 1
            else:
                kept.append(card)
        self.order[:] = kept
        self.pos = new_pos
        return removed

    def insert_undealt(self, room_idx: int, at: int) -> None:
        """Insert one card at absolute index ``at``, which must be in [pos, len(order)].

        Leaves order[:pos] and pos untouched. The caller is responsible for
        choosing at within [pos, len(order)] so the insert lands in the undealt slice.
        """
        self.order.insert(at, room_idx)

    def add_copies(self, room_idx: int, n: int, shuffler) -> None:
        """Shuffle ``n`` copies of a room into the deck (mid-day injection).

        The whole deck reshuffles and the cursor resets, so cards already
        dealt this cycle become dealable again.
        """
        self.order.extend([room_idx] * n)
        shuffler(self.order)
        self.pos = 0


@dataclass(slots=True)
class DraftOption:
    room_idx: int          # index into Registry.rooms
    orientation: int       # door mask as dealt
    gem_cost: int          # resolved cost (dynamic costs evaluated at deal time)
    slot: int              # 0..2
    forced: bool = False   # placed by a priority/forced draw
    hidden: bool = False   # Archives: face-down "mystery" room, still draftable


@dataclass(slots=True)
class PendingDraft:
    from_cell: int         # cell whose doorway was opened
    direction: int         # door direction opened (N/E/S/W bit)
    target_cell: int       # empty cell the drafted room will occupy
    options: list[DraftOption] = field(default_factory=list)  # dealt hand, one entry per slot
    study_redraws_used: int = 0  # Study redraws bought with gems on this hand (max 8)
    redraws_left: int = 0  # free redraws (Classroom etc.)
    rotations_used: int = 0  # free rotations spent on this hand (see Game.rotation_available)


@dataclass(slots=True)
class GameState:
    # grid: -1 empty, else room idx; placed_doors: effective door mask of placed room
    grid: list[int] = field(default_factory=lambda: [-1] * 45)
    placed_doors: list[int] = field(default_factory=lambda: [0] * 45)
    opened: list[int] = field(default_factory=lambda: [0] * 45)  # mask of used doorways per cell
    # True once the player stepped into the cell (ON_ENTER effects/items fire only then)
    entered: list[bool] = field(default_factory=lambda: [False] * 45)
    pos: int = 2  # player cell (entrance)

    steps: int = 50  # step budget left today (moving costs steps; day ends at 0)
    gems: int = 0  # spent to draft gem-cost rooms and on Study redraws
    keys: int = 0  # spendable keys; opening a locked door costs one
    coins: int = 0  # money from coin piles etc.; only feeds resource_value (shops not modeled)
    # Permanent allowance total (the wiki's "packet" that appears at Entrance Hall
    # every day it's nonzero). Seeded from cfg.allowance at reset(); grown in-run
    # by Allowance Tokens (+2 each, special_items.py) and Cloister of Lydia (+2
    # per Shop drafted from it, effects/rooms/cloister.py). Reported by
    # carryover() and replaced wholesale into cfg.allowance by DayChain each
    # advance() -- the same shape as chapel_tithes. Never itself spent; its
    # value is what gets folded into coins at the start of every future day.
    allowance: int = 0
    # Permanent star total. Seeded from cfg.stars at reset(); grown in-run by
    # the Observatory and Starfish Aquarium (both +1 per draft, effects/rooms/
    # observatory.py and aquarium.py). Reported by carryover() and replaced
    # wholesale into cfg.stars by DayChain each advance() -- the same shape as
    # allowance. Never itself spent; stars are a pure permanent counter (the
    # telescope/constellation system that would consume them is out of scope).
    stars: int = 0
    # Cloister of Joya's permanent Main Course bonus: +5 (from its own
    # effect_text) for each Kitchen/Pantry/Furnace drafted from its own
    # doorway (effects/rooms/cloister.py), added to every one of the five
    # main-course dishes (special_items.py::_resolve_food_base), never to the
    # Lunch Box. Seeded from cfg.main_course_bonus at reset(); reported by
    # carryover() and replaced wholesale into cfg.main_course_bonus by
    # DayChain each advance() -- the same "replace" shape as allowance/stars,
    # per-ATTEMPT rather than a save-wide total (an owner-flagged reading of
    # the wiki's "permanently", since it never says "across the save").
    main_course_bonus: int = 0
    dice: int = 0  # redraw dice: spend one to redraw the current draft hand
    luck: int = 10  # scales bonus-item odds between items.json floor and max_effect_at

    day: int = 20  # in-game day, copied from GameConfig at reset
    stage: str = "late"  # rarity-table stage (week1|week2|late) resolved from day

    # decks: index = rarity_idx * 2 + (0 free | 1 gem)
    decks: list[DeckState] = field(default_factory=list)

    # cached house-effect flags (recomputed on placement)
    solarium_placed: bool = False  # Solarium: swaps in the special slot-2/3 rarity table
    greenhouse_placed: bool = False  # Greenhouse: green-room bias, boosts some priority draws
    furnace_placed: bool = False  # Furnace: red-room category bias on draws
    # Schoolhouse: Classroom category bias on draws (priority_draws.json "schoolhouse").
    # Set by the Schoolhouse's ON_PLACE room handler (effects/rooms/schoolhouse.py),
    # read by draft.py's _active_conditions. Per-day like greenhouse_placed/furnace_placed:
    # reset() builds a fresh GameState, and nothing carries this across days.
    schoolhouse_placed: bool = False
    # Southern Cross constellation active tonight: 4-way (layout: cross) room bias on draws
    # (priority_draws.json "southern_cross_constellation"). Day-scoped stub: no star-count /
    # night-sky / Observatory-eyepiece subsystem is modeled anywhere in the engine, so nothing
    # sets this flag during play. Exists so the bias is testable/reachable (set it directly)
    # rather than dead code; real activation is out of scope here.
    southern_cross_active: bool = False
    # Draxus constellation active tonight: Dead End (layout: dead_end) room bias on draws
    # (priority_draws.json "draxus_constellation"). Same day-scoped stub as
    # southern_cross_active — no activation source is modeled; set only by tests/research
    # callers. Not to be confused with cloister_of_draxus__ix36's own, unrelated, deterministic
    # "only Dead Ends draftable from this room" rule.
    draxus_active: bool = False
    drafting_room_count: int = 0  # grants that many free redraws when drafting from the Classroom
    study_placed: bool = False  # Study: pay 1 gem to redraw (max 8 per hand)
    library_placed: bool = False  # Library in the house (obs flag; Library draws key off position)
    # Foyer/Spare Foyer: forces every Hallway-category room's doors unlocked for
    # the rest of the day, including security doors and the Foyer's own doors.
    # Set by effects/rooms/foyer.py's ON_PLACE handler and consulted by
    # Game._place_room on every later placement, so a Hallway drafted after the
    # Foyer comes out unlocked too. Per-day like solarium_placed/schoolhouse_placed.
    foyer_placed: bool = False

    # --- door locks & security doors (see engine.locks) ---
    # segment (locks.segment_key) -> DOOR_LOCKED/DOOR_SECURITY; DOOR_OPEN
    # entries mark rolled-or-opened segments, missing means never rolled
    # (freely passable). Mutate via Game helpers so door_version is bumped.
    door_state: dict[tuple[int, int], int] = field(default_factory=dict)
    door_version: int = 0  # cache stamp for the navigation maps
    lock_bias: float = 1.0  # daily lock-chance multiplier (locks.json "bias")
    # security doors rolled so far today (capped by locks.json spawn_limit per security level)
    security_doors_spawned: int = 0
    security_level: str = "normal"    # low|normal|high (Security terminal)
    keycard_power_on: bool = True     # Utility Closet breaker, "Keycard Entry"
    offline_unlocked: bool = False    # Security terminal offline mode (set on visit)
    has_keycard: bool = False         # Keycard held: opens security doors while power is on

    # special items held (item id -> count; most items are unique, see special_items.py)
    inventory: dict[str, int] = field(default_factory=dict)
    special: SpecialItemsState = field(default_factory=SpecialItemsState)
    # commerce/discovery bookkeeping (shop stock, trades, scepter; see shops.py)
    shops: ShopsState = field(default_factory=ShopsState)
    # Laboratory/Experiments bookkeeping (see engine/experiments.py); per-day only
    experiment: ExperimentState = field(default_factory=ExperimentState)

    pending: PendingDraft | None = None  # in-flight draft hand; None outside the drafting phase
    outer_room_drafted: bool = False  # today's single outer-room draft has been used
    # area-graph node id the player stands on, or None when on the 5x9 grid (pos is authoritative)
    # Equivalences with the old outer_loc int: None=0, "west_path"=1, <outer_room_id>=2
    area: str | None = None
    outer_room_entered: bool = False  # True once ON_ENTER has fired for today's outer room
    # Set the first time the player reaches west_path today (only possible via the Garage
    # while the gate is still latched).  An IN-RUN discovery, deliberately NOT written back
    # to GameConfig: one config object is shared across every episode of a worker, so
    # mutating it would leak the unlock into later "fresh save" episodes.  carryover() ORs
    # this with cfg.west_gate_unlatched, the same shape as vase_smashed / chip_dug.
    west_gate_unlatched: bool = False
    # Set the first time the player reaches mine_south today.  Same shape as
    # west_gate_unlatched: an IN-RUN discovery recorded on STATE, never written
    # back to GameConfig (one config object is shared by every episode of a
    # worker).  carryover() ORs this with cfg.mine_south_visited; DayChain
    # carries the result, permanently opening reservoir_north -> mine_north and
    # rotating_gear -> underpass for the rest of the attempt.
    mine_south_visited: bool = False
    # Set the first time the player reaches sealed_entrance today (whether via the
    # Power Hammer or an already-broken barrier from a prior day). Same shape as
    # west_gate_unlatched: an IN-RUN discovery recorded on STATE, never written back
    # to GameConfig. carryover() ORs this with cfg.sealed_entrance_broken; DayChain
    # carries the result, permanently opening grounds<->sealed_entrance<->basement.
    sealed_entrance_broken: bool = False
    # Set the first time the player enters the Boiler Room today. Same shape as
    # west_gate_unlatched: an IN-RUN discovery recorded on STATE, never written
    # back to GameConfig. carryover() ORs this with cfg.boiler_room_steam; DayChain
    # carries the result, permanently opening the "boiler_room_steam" gate
    # (Underpass -> Upper Rotating Gear, docs/areas.md).
    boiler_room_steam: bool = False
    # True once today's single gem from arriving at Upper Rotating Gear has been
    # granted. Per-day only -- deliberately NOT carried over (a fresh GameState
    # resets it every day, unlike the permanent flags above).
    upper_rotating_gear_gem_granted: bool = False
    # True once a Quest Bedroom has been entered today, arming its Antechamber
    # allowance effect. Per-day only -- deliberately NOT carried over (a fresh
    # GameState resets it every day; the effect re-arms each day by re-entering
    # a Quest Bedroom that day).
    quest_bedroom_entered_today: bool = False
    # True once today's single Quest Bedroom allowance payout has been granted,
    # so a second Quest Bedroom or a later Antechamber arrival does not pay
    # again. Per-day only -- deliberately NOT carried over, same shape as
    # quest_bedroom_entered_today above.
    quest_bedroom_allowance_paid_today: bool = False
    # Set on arrival at Upper Rotating Gear: the Treasure Trove blackprint has
    # been picked up. Same shape as west_gate_unlatched: recorded on STATE, never
    # written back to GameConfig. carryover() ORs this with
    # cfg.treasure_trove_blackprint; DayChain carries the result, permanently
    # adding the Treasure Trove to the draft pool from the following day.
    treasure_trove_blackprint: bool = False
    # Set the first time Room 8 is solved today (see effects/rooms/room_8.py).
    # Same shape as west_gate_unlatched: an IN-RUN discovery recorded on
    # STATE, never written back to GameConfig (one config object is shared by
    # every episode of a worker, so mutating it would leak the flag into
    # later episodes). carryover() ORs this with cfg.room8_solved; the room's
    # own handler reads that same OR to tell a day's first solve from a later
    # one, whether the flag came from today or from a carried-over attempt.
    room8_solved: bool = False
    # Set the first time the player arrives at apple_orchard today. Same shape as
    # west_gate_unlatched: an IN-RUN discovery recorded on STATE, never written
    # back to GameConfig. carryover() ORs this with cfg.orchard_unlocked; DayChain
    # carries the result, so the +20 starting-steps bonus (Game.reset) applies
    # from the FOLLOWING day onward -- a same-day visit does not retroactively
    # top up steps already spent this attempt, since st.steps is only set once
    # at reset().
    orchard_unlocked: bool = False
    # Set the first time the player enters a Sauna today. Unlike orchard_unlocked
    # this is a ONE-DAY pulse, not a permanent unlock: carryover() reports only
    # today's own value (never ORed with cfg.sauna_bonus), and DayChain replaces
    # sauna_bonus each advance() instead of merging it forever, so the +20 starting
    # steps land on exactly the FOLLOWING day and require a fresh Sauna visit to
    # repeat.
    sauna_visited: bool = False
    # Set the first time the player enters a Morning Room today. Same one-day
    # pulse shape as sauna_visited; grants +2 starting gems on the FOLLOWING day
    # only. The same-day +2 gems is a separate, already-modelled mechanic
    # (items.guaranteed on the room record).
    morning_room_visited: bool = False
    # Set the first time the player enters the Freezer today. Same one-day pulse
    # shape as sauna_visited: today's ending coins/gems (read by carryover() at
    # day end) carry into tomorrow's starting balance instead of resetting to the
    # normal day-start amount. See GameConfig.frozen_coins/frozen_gems.
    freezer_frozen: bool = False
    # Set by Game._terminate when the day ends while the player is standing in
    # Break Room. Same one-day pulse shape as sauna_visited; grants a starting
    # keycard on the FOLLOWING day only.
    break_room_keycard: bool = False
    # Set the first time a No Contact Delivery Mail Room (mail_room__ix90) is
    # drafted today. Same one-day pulse shape as sauna_visited; carryover()
    # reports this as GameConfig.no_contact_due, which grants the package
    # outright at the start of the FOLLOWING day.
    no_contact_drafted: bool = False
    # chronological (item id, count) pickups this run, for CLI/replay reporting
    items_found_log: list[tuple[str, int]] = field(default_factory=list)

    # areas entered today, for the Observatory's aggregate heat; reset per day like GameState
    areas_visited: set[str] = field(default_factory=set)

    antechamber_reached: bool = False  # True the first time the player steps onto cell 42 this day
    room46_reached: bool = False       # True the first time the player enters Room 46 this day
    # Per-day EVENT flag (no carry-over): True once the Antechamber's north door has
    # been opened today by either lever (Inner Sanctum or Throne Room).  Set only at
    # the lever sites (Game._open_north_door), never derived from the door segment's
    # own state -- with antechamber_levers=False the segment is never sealed to begin
    # with, so a state-derived flag would pay the reward for free every such day.
    north_door_opened: bool = False

    # --- upgrade disks (engine/upgrades.py) ---
    draft_counts: dict[str, int] = field(default_factory=dict)  # cumulative attempt-wide draft counts by root base room id; seeded from cfg.draft_counts, incremented on placement
    applied_upgrades: set[str] = field(default_factory=set)     # variant ids applied so far this attempt; seeded from cfg.upgrade_disks
    pending_upgrade_slot: str | None = None                      # slot awaiting the player's upgrade choice; None when not mid-upgrade
    pending_upgrade_options: tuple[str, ...] = ()                # the three offered variant ids; empty when not mid-upgrade

    # --- The Foundation (does not reset day-to-day; see GameConfig.foundation_cell) ---
    foundation_cell: int = -1     # cell it was placed at today, if drafted today; -1 = not yet
    foundation_doors: int = 0     # its door mask as drafted today; 0 = not yet drafted

    # --- Garage Forced Draw (data/priority_draws.json "forced_draws"; see draft.py) ---
    # True once today's Garage forced-draw roll has succeeded (wiki: "Once the roll
    # succeeds ... they will no longer be available for Forced Draws" today), whether
    # or not the Garage actually ended up placed in slot 3 (it can "succeed but fail"
    # when the Garage already occupies an earlier slot of the same hand). Per-day only:
    # a fresh GameState resets it every day like schoolhouse_placed/greenhouse_placed.
    garage_forced_draw_succeeded: bool = False

    # Grid cells holding a Bedroom-category room owed one guaranteed extra item on
    # its own first entry, because it was drafted from a placed Cloister of Mila
    # (cloister_of_mila__ix33; see effects/rooms/cloister.py). The bonus cannot be
    # granted at draft time -- the room is only entered later, possibly far from the
    # Cloister -- so it is parked here and consumed by Game._enter. Append-only: a
    # cell is never removed, but Game._enter's own entered[cell] guard already
    # prevents a second grant on re-entry, so nothing re-reads a stale entry.
    cloister_mila_bonus_cells: set[int] = field(default_factory=set)
    # Her Ladyship's Chamber / Her Ladyship's Spare Room (her_ladyships_chamber__ix135):
    # "Once drafted ... The first time the BOUDOIR is entered, gain 10 steps. The
    # first time the WALK-IN CLOSET is entered, gain 3 gems." Each is armed True
    # at its own draft (effects/rooms/her_ladyships_chamber.py, ON_PLACE) and
    # cleared back to False the first time the matching room's ON_ENTER hook
    # fires -- which the engine only ever fires once per cell (Game._enter), so
    # a Boudoir/Walk-In Closet already entered before the Chamber is drafted
    # never re-pays. The two sources are independent (both present pays both,
    # sequentially) rather than a single shared flag, since the wiki states they
    # stack. Per-day only: a fresh GameState resets every day like
    # quest_bedroom_entered_today.
    her_ladyships_chamber_boudoir_armed: bool = False
    her_ladyships_chamber_closet_armed: bool = False
    her_ladyships_spare_room_boudoir_armed: bool = False
    her_ladyships_spare_room_closet_armed: bool = False
    # Cells holding a Closet-family variant whose adjacency bonus condition held
    # at placement; popped when that cell is first entered and the bonus paid.
    closet_bonus_cells: set[int] = field(default_factory=set)
    # Cells holding a Geist Bedroom (geist_bedroom__ix69) that already had a
    # Tomb on the estate at the moment it was drafted -- "The additional 4
    # dice only spawns if the Tomb was drafted before the Geist Bedroom"
    # (effects/rooms/guest_bedroom.py). Marked at ON_PLACE, read at ON_ENTER;
    # same shape as closet_bonus_cells/cloister_mila_bonus_cells above.
    geist_bedroom_tomb_cells: set[int] = field(default_factory=set)

    # Resources parked in a cell, waiting for the player to walk in and collect them
    # (Secret Garden fruit spread today; Patio gems and Locker Room keys will reuse
    # this later). Cell -> list of (what, count) entries, drained in full on the
    # player's next arrival at that cell (Game._collect_spread), not gated on first
    # entry. ``what`` is either a food.dishes id ("apple", "orange", ...) or a
    # grant_item item kind ("key", "gem", "coins", ...) -- the two namespaces never
    # collide. Per-day only: a fresh GameState clears it every day, since spread
    # fruit does not survive the night.
    spread_pending: dict[int, list[tuple[str, int]]] = field(default_factory=dict)

    # Mail Room order/delivery cycle: "empty" (no order outstanding) or
    # "awaiting" (an order has been placed and the next Mail Room draft
    # delivers it). Seeded each day from GameConfig.mail_cycle by
    # special_items.configure(); advanced by effects/rooms/mail_room.py.
    mail_cycle: str = "empty"
    # Freight Shipping (mail_room__ix91): days remaining in the "transit"
    # cycle state, counting down to 0 (package ready). Seeded each day from
    # GameConfig.mail_transit_days by special_items.configure(); decremented
    # by env/multiday.py::DayChain.advance() at each day boundary. 0 outside
    # of a transit order.
    mail_transit_days: int = 0
    # Grid cell holding a delivered, uncollected package today; -1 = none.
    # Set when the cycle above delivers; cleared on that cell's first entry
    # (the package's contents are rolled and granted then). Per-day only: an
    # uncollected package does not survive to the next day's fresh floorplan.
    mail_package_cell: int = -1
    # Freight Shipping's package contents, rolled at draft time (not entry
    # time) and held here until the player enters mail_package_cell. Empty
    # when no Freight delivery is pending.
    mail_freight_grants: list[dict] = field(default_factory=list)
    # Same Day Delivery (mail_room__ix89): the cell of a Same Day Mail Room
    # drafted today, armed to deliver into mail_package_cell the moment Rank 8
    # is reached; -1 = not armed (not drafted today, delivered immediately at
    # draft time, or already delivered on Rank 8 arrival). Set by
    # effects/rooms/mail_room.py::same_day_arm, consumed by ::reach_rank8.
    mail_same_day_armed_cell: int = -1
    # True once the player has entered a Rank >= 8 cell today (Same Day
    # Delivery's trigger). Set by Game._enter; per-day only.
    rank8_reached: bool = False

    # Tomorrow Hallways (hallway__ix76) drafted today; incremented by
    # effects/rooms/hallway.py at ON_PLACE. Per-day only -- a fresh GameState
    # resets it every day. Reported by shops.carryover() as
    # "hallway_tomorrow_extra" and carried by DayChain into tomorrow's
    # GameConfig.hallway_tomorrow_extra, which injects that many extra
    # Hallway copies into tomorrow's draft pool at day start.
    hallway_tomorrow_count: int = 0

    def deck(self, rarity_idx: int, is_gem: bool) -> DeckState:
        return self.decks[rarity_idx * 2 + (1 if is_gem else 0)]

    def resource_value(self, values: dict) -> float:
        """Weighted worth of the resources on hand, for reward shaping/reporting.

        ``values`` maps resource name to per-unit worth; missing entries fall
        back to the defaults below (key/gem 3, coin 1, die 4, step 0.5).
        """
        return (
            self.keys * values.get("key", 3.0)
            + self.gems * values.get("gem", 3.0)
            + self.coins * values.get("coin", 1.0)
            + self.dice * values.get("die", 4.0)
            + self.steps * values.get("step", 0.5)
        )


def resolve_gem_cost(room: Room, state: GameState, registry_rooms) -> int:
    """Resolve a room's gem cost, evaluating dynamic modifiers."""
    cost = room.gem_cost
    if room.gem_cost_dynamic == "plus_one_per_bedroom":
        n_bedrooms = sum(
            1 for idx in state.grid if idx >= 0 and registry_rooms[idx].is_category("bedroom")
        )
        cost += n_bedrooms
    return cost
