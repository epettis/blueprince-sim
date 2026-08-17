"""Mutable per-episode state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .constellations import NightSky
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

    def insert_dealt(self, room_idx: int) -> None:
        """Insert one card just before the cursor, already marked dealt this cycle.

        Used when a card moves decks mid-cycle and was already dealt in its old
        deck (set_dynamic_rarity): it must stay dealt in its new deck too, so it
        lands in order[:pos] and pos advances with it. Position within the dealt
        prefix carries no meaning, so no ``at`` argument is needed.
        """
        self.order.insert(self.pos, room_idx)
        self.pos += 1

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
    hidden: bool = False   # face-down: identity/orientation concealed, still draftable
    archived: bool = False  # this floorplan was archived by an active Archives; implies hidden
    # The hand's first presented option is granted free: its gem cost is zeroed
    # whatever the room would ordinarily charge (owner ruling; see draft.py::
    # waive_first_option and Game._effective_cost, which honours this flag).
    cost_waived: bool = False


@dataclass(slots=True)
class PendingDraft:
    from_cell: int         # cell whose doorway was opened
    direction: int         # door direction opened (N/E/S/W bit)
    target_cell: int       # empty cell the drafted room will occupy
    options: list[DraftOption] = field(default_factory=list)  # dealt hand, one entry per slot
    study_redraws_used: int = 0  # Study redraws bought with gems on this hand (max 8)
    redraws_left: int = 0  # free redraws (Classroom etc.)
    rotations_used: int = 0  # free rotations spent on this hand (see Game.rotation_available)
    # Secret Passage colour-selective restriction (draft.py COLOUR_CATEGORIES), carried
    # across redraws of this same hand so a redraw stays locked to the chosen colour;
    # None for an ordinary (non-colour-selective) hand.
    colour: str | None = None
    # 1-indexed round counter for THIS draft (wiki: "a 'round' is the set of
    # three draws that get presented at once ... a 'draft' ... [is] made up of
    # one or more rounds"). The initial deal is round 1; draft.py::redeal bumps
    # it before re-filling, so a redraw (Study/Classroom/dice/Crown block) is
    # round 2, a second redraw round 3, etc. Unlike rotations_used above, this
    # does NOT reset on redraw -- it must keep climbing across the whole draft
    # for draft.py::_resolve_free_gem's "third round or later this draft"
    # Slot 3 Gem Draw rule (Drafting/Advanced) to ever fire.
    round_num: int = 1
    # The slot (0..2) the Dowsing Rod points at, or None while it is not held
    # / the hand ended up with no dealt options (draft.py::_pick_dowsing_slot,
    # called from _fill_options -- so this is recomputed on every fresh deal
    # AND every redraw, matching the wiki's "the Dowsing Rod will reselect
    # one of the new floorplans" after a redraw, and set for outer-room hands
    # by Game._deal_outer_options through the same helper). Read when the
    # option is taken -- Game.choose for a grid draft, Game._choose_outer for
    # an outer one -- to decide whether the drafted room's cell gets marked in
    # GameState.dowsing_marked_cells for its later item roll. An outer draft
    # marks the -1 sentinel, which is the cell roll_room_items is already
    # called with on outer-room entry.
    dowsed_slot: int | None = None
    # Chronograph REWIND stack: each entry is the hand a redeal (Game.
    # _redeal_pending -- Study/Classroom/dice redraw, or Crown of the
    # Blueprints' free redeal) just replaced, pushed there before the hand is
    # cleared and refilled. Free/unlimited/one-way (owner ruling): Game.rewind
    # pops the top entry back into ``options`` and re-fires ON_HAND_DEALT for
    # it (the wiki: rewinding "activat[es] effects that rely on drawing a
    # floorplan"), but never pushes what it leaves -- so repeated rewinds walk
    # strictly back through every prior hand to the original deal and then
    # stop, and can never oscillate. A shallow copy of ``options`` is pushed
    # (never a deepcopy): DraftOption is a slots dataclass whose fields are
    # only ever mutated in place on the CURRENTLY LIVE hand -- by
    # Game.rotate_options, and by draft.py::waive_first_option at deal time,
    # before the hand can have been stacked -- and each redeal builds an
    # entirely new set of DraftOption objects (draft.py::_fill_options/
    # _make_option), so a stacked hand's objects are never touched again once
    # superseded. Lives here, not on GameState or in
    # DayChain._CARRYOVER_KEYS: the Chronograph is persistence="day" and this
    # history is meaningless past the hand (and the day) it belongs to.
    rewind_stack: list[list[DraftOption]] = field(default_factory=list)


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
    # allowance. Spent 1 at a time by the Ink Well's star-redraw
    # (Game.redraw(RedrawKind.STAR), gated on ink_well_active below). What
    # stars also buy is the night sky: night_skies below resolves against
    # this live value, so a star earned mid-day enriches every sky viewed
    # after it.
    stars: int = 0
    # Frozen start-of-day star count. Seeded from cfg.stars at reset(), before
    # special_items.configure() runs, and never reassigned for the rest of the
    # day -- unlike ``stars`` above, which keeps growing as the Observatory/
    # Starfish Aquarium/Morning Star and experiments.py mutate it. Read by
    # effects/items/telescope.py::gate so a star earned mid-day cannot un-gate
    # the Telescope until tomorrow's snapshot reflects it.
    stars_at_day_start: int = 0
    # Words permanently added to the Spiral of Stars. Seeded from
    # cfg.spiral_words at reset(); grown in-run by constellations.generate_sky,
    # which adds one every time a sky it builds contains the Spiral. Reported
    # by carryover() and replaced wholesale into cfg.spiral_words by DayChain
    # each advance() -- the same shape as stars, and SAVE-scoped like it.
    #
    # It counts GENERATIONS, not activations: the Spiral's own wording suggests
    # a word arrives when it is activated, but a word arrives whenever a night
    # sky containing it is generated, whether or not the player activates it.
    # constellations.spiral_tier reads this to pick which tier of the record's
    # published effect table one activation pays out.
    spiral_words: int = 0
    # Night skies generated today, keyed by GRID CELL -- never by room id.
    # game.room_cells keeps only the LOWEST cell per room id (game.py's
    # _place_room: "if prev is None or cell < prev"), so with more than one
    # Observatory on the estate it cannot say which one a sky belongs to, and
    # up to four are reachable in a day via the Chamber of Mirrors.
    #
    # Each cell holds a list because one Observatory can be looked through
    # twice: its own telescope, plus a held Telescope, which "generates an
    # additional night sky for each Observatory it is used in". Activation is
    # tracked per sky (NightSky.activated), which is what lets the same
    # constellation fire once in each of them.
    #
    # Per-day only: a fresh GameState clears it every night, like
    # spread_pending. Nothing here is carried over -- env/multiday.py's
    # _CARRYOVER_KEYS is untouched, and only the star count itself persists.
    night_skies: dict[int, list[NightSky]] = field(default_factory=dict)
    # Cloister of Joya's permanent Main Course bonus: +5 (from its own
    # effect_text) for each Kitchen/Pantry/Furnace drafted from its own
    # doorway (effects/rooms/cloister.py), added to every one of the five
    # main-course dishes (special_items.py::_dish_base_steps), never to the
    # Lunch Box. Seeded from cfg.main_course_bonus at reset(); reported by
    # carryover() and replaced wholesale into cfg.main_course_bonus by
    # DayChain each advance() -- the same "replace" shape as allowance/stars,
    # per-ATTEMPT rather than a save-wide total (an owner-flagged reading of
    # the wiki's "permanently", since it never says "across the save").
    main_course_bonus: int = 0
    dice: int = 0  # redraw dice: spend one to redraw the current draft hand
    luck: int = 10  # banded against data/items.json's item_ladder (engine/items.py)
    # Luck Penalty (wiki: Luck page): subtracted from luck to get a draft's EFFECTIVE
    # luck (engine/items.py::roll_ladder_count), grown by high-luck item_ladder outcomes.
    # Owner-ruled PER-DAY (the wiki never states its reset scope): reset alongside luck
    # at day start (Game.reset), same as luck itself -- not in _CARRYOVER_KEYS, which is
    # a frozenset of bool fields and cannot carry an int across days anyway.
    luck_penalty: int = 0

    day: int = 20  # in-game day, copied from GameConfig at reset
    stage: str = "late"  # rarity-table stage (week1|week2|late) resolved from day
    # 1-indexed count of doorway drafts DEALT so far today (draft.py::deal_draft
    # increments this before dealing, so the hand being dealt sees its own
    # number). Distinct from draft_counts below: that dict is cumulative
    # per-room PLACEMENT counts across the whole attempt, never resets, and
    # says nothing about how many drafts have happened today. A redraw
    # (draft.py::redeal) does NOT bump this -- it is a new round of the SAME
    # draft, not a new draft (see PendingDraft.round_num). Read by
    # draft.py::_resolve_free_gem for the wiki's Free/Gem Draws "first N
    # drafts" rules (Drafting/Advanced). Per-day only: a fresh GameState
    # resets it to 0 every day like forced_draws_succeeded_today below.
    drafts_today: int = 0

    # decks: index = rarity_idx * 2 + (0 free | 1 gem)
    decks: list[DeckState] = field(default_factory=list)
    # Room id -> rarity index its live-deck cards currently sit in, set by
    # decks.py::set_dynamic_rarity when a room's cards are moved off Room.rarity
    # for the day; a room absent from this dict sits in its own rarity.
    dynamic_rarity: dict[str, int] = field(default_factory=dict)
    # Laboratory add_aquariums effect has fired today: activates the two
    # condition-gated Aquarium priority_draws.json entries (draft.py's
    # _active_conditions) and waives the one-copy-per-room rule for
    # aquarium__experiment (draft.py::room_draftable). Day-scoped like the
    # rest of ExperimentState/GameState — no carry-over field feeds it back in.
    add_aquariums_active: bool = False

    # cached house-effect flags (recomputed on placement)
    solarium_placed: bool = False  # Solarium: swaps in the special slot-2/3 rarity table
    greenhouse_placed: bool = False  # Greenhouse: green-room bias, boosts some priority draws
    furnace_placed: bool = False  # Furnace: red-room category bias on draws
    # Schoolhouse: Classroom category bias on draws (priority_draws.json "schoolhouse").
    # Set by the Schoolhouse's ON_PLACE room handler (effects/rooms/schoolhouse.py),
    # read by draft.py's _active_conditions. Per-day like greenhouse_placed/furnace_placed:
    # reset() builds a fresh GameState, and nothing carries this across days.
    schoolhouse_placed: bool = False
    # Southern Cross constellation active today: 4-way (layout: cross) room bias on draws
    # (priority_draws.json "southern_cross_constellation", which owns the 40%). Set by
    # activating the constellation from a night sky (constellations.py::apply_effect, keyed
    # on that record's own effect.condition), read by draft.py's _active_conditions.
    # Day-scoped: a fresh GameState clears it, and nothing carries it over.
    southern_cross_active: bool = False
    # Draxus constellation active today: Dead End (layout: dead_end) room bias on draws
    # (priority_draws.json "draxus_constellation", which owns the 30%). Same activation path
    # and same day scope as southern_cross_active. Not to be confused with
    # cloister_of_draxus__ix36's own, unrelated, deterministic "only Dead Ends draftable from
    # this room" rule.
    draxus_active: bool = False
    # Ink Well constellation active today: enables Game.can_redraw_with_star /
    # redraw(RedrawKind.STAR) -- 1 star per drafting-phase redraw, no per-draft
    # cap beyond the star balance. Set by activating the constellation from a
    # night sky (constellations.py::apply_effect). Day-scoped like
    # southern_cross_active/draxus_active: a fresh GameState clears it, and
    # nothing carries it over.
    ink_well_active: bool = False
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
    # segment (locks.segment_key) -> (times its lock menu was abandoned today,
    # `keys` held at the last of those abandons). At locks.LOCK_ABANDON_LIMIT
    # the doorway stops being triable, and holding MORE keys than at that last
    # abandon makes it triable again with a fresh tally
    # (Game.frontier_doorway_triable / abandon_lock). The key count is stored
    # per segment rather than compared against a global watermark so the
    # triable check stays a pure query -- the mask reads it, so a reset that
    # only happened on mutation could never be reached.
    # Day-scoped like door_state.
    lock_abandons: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    lock_bias: float = 1.0  # daily lock-chance multiplier (locks.json "bias")
    # security doors rolled so far today (capped by locks.json spawn_limit per security level)
    security_doors_spawned: int = 0
    security_level: str = "normal"    # low|normal|high (Security terminal)
    keycard_power_on: bool = True     # Utility Closet breaker, "Keycard Entry"
    offline_unlocked: bool = False    # Security terminal offline mode (set on visit)
    has_keycard: bool = False         # Keycard held: opens security doors while power is on
    # Utility Closet breaker, "Darkroom" -- initially on, like keycard_power_on.
    # Read live at every doorway draft FROM the Darkroom (engine/draft.py); flipped
    # off by effects/rooms/darkroom.py's ON_ENTER handler the first time the
    # Darkroom is entered today, unless it was already off or Shelter negates it.
    darkroom_lights_on: bool = True

    # special items held (item id -> count; most items are unique, see special_items.py)
    inventory: dict[str, int] = field(default_factory=dict)
    special: SpecialItemsState = field(default_factory=SpecialItemsState)
    # commerce/discovery bookkeeping (shop stock, trades, scepter; see shops.py)
    shops: ShopsState = field(default_factory=ShopsState)
    # Laboratory/Experiments bookkeeping (see engine/experiments.py); per-day only
    experiment: ExperimentState = field(default_factory=ExperimentState)

    pending: PendingDraft | None = None  # in-flight draft hand; None outside the drafting phase
    # Door mask of the room whose ON_DRAFT_ROOM hook is currently dispatching, set
    # immediately before firing by Game._place_room for a grid draft (both its own
    # self-fire and the broadcast to every other drafted room use the same
    # just-drafted room, so one assignment covers both) and by Game._choose_outer
    # for an outer draft. Handlers that need the room's actual drafted
    # orientation -- e.g. the Tomb's coins_per_deadend, Cloister of Draxus' dice grant
    # -- read this instead of Room.layout, which stays a room's canonical shape even
    # when an alt_layouts rotation was drafted (the Greenhouse's two-door corner).
    # Meaningless outside an ON_DRAFT_ROOM dispatch; nothing else reads it.
    draft_hook_orientation: int = 0
    # Secret Passage / Spare Secret Passage colour pick: the doorway (cell, direction)
    # awaiting Game.choose_colour(), set by Game.open_door instead of dealing a hand
    # when the doorway's from-room is a Secret Passage variant and this is its first
    # opening. -1 outside COLOUR_PENDING; direction is only meaningful while cell >= 0.
    pending_colour_cell: int = -1
    pending_colour_direction: int = 0
    outer_room_drafted: bool = False  # today's single outer-room draft has been used
    # area-graph node id the player stands on, or None when on the 5x9 grid (pos is authoritative)
    area: str | None = None
    outer_room_entered: bool = False  # True once ON_ENTER has fired for today's outer room
    # Set the first time the player reaches west_path today (only possible via the Garage
    # while the gate is still latched).  An IN-RUN discovery, deliberately NOT written back
    # to GameConfig: one config object is shared across every episode of a worker, so
    # mutating it would leak the unlock into later "fresh save" episodes.  carryover() ORs
    # this with cfg.west_gate_unlatched, the same shape as vase_smashed / chip_dug.
    west_gate_unlatched: bool = False
    # The Blackbridge Grotto pedestal's own microchip has been taken out today.
    # Day-scoped only: NO GameConfig field, NO _CARRYOVER_KEYS entry.  Unlike
    # west_gate_unlatched above, the Grotto chip records no discovery to carry
    # forward -- it starts in the pedestal on day 1 with no prerequisite, so the
    # owner's respawn-next-day rule is implemented for free by this field simply
    # defaulting False at every reset(), not by plumbing it through carryover().
    grotto_chip_taken: bool = False
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
    # Set the first time the player enters the Laboratory today. Same shape as
    # boiler_room_steam: an IN-RUN discovery recorded on STATE, never written
    # back to GameConfig. carryover() ORs this with cfg.lab_visited, opening the
    # "lab_visited" gate (Private Drive -> Blackbridge Grotto, docs/areas.md).
    # Unlike boiler_room_steam, DayChain carries the result on its own named
    # lab_visited attribute rather than in _CARRYOVER_KEYS, so the unlock is
    # SAVE-scoped and survives the attempt wrap.
    lab_visited: bool = False
    # Set the first time a placed Laboratory is powered today
    # (effects/rooms/laboratory.py's ON_DRAFT_ROOM hook). Same SAVE-scoped shape as
    # lab_visited, and the other half of the same one-time Grotto unlock:
    # carryover() ORs this with cfg.lab_powered to open the
    # "lab_steam_and_power" gate (docs/power.md).
    lab_powered: bool = False
    # Basement-door gate ids unlocked TODAY: added the moment the player stands
    # at that door holding a Basement Key (Game.travel_to). Same IN-RUN shape as
    # lab_visited -- recorded on STATE, never written back to GameConfig, and
    # ORed with cfg.basement_doors_open by carryover() -- but a SET rather than a
    # bool, since each door unlocks on its own visit and stays unlocked for the
    # rest of the save (docs/areas.md's "Basement doors").
    basement_doors_open: set[str] = field(default_factory=set)
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
    # True once the Billiard Room's Dartboard puzzle has paid out today (owner
    # ruling: solvable once per day). Day-scoped only: NO GameConfig field, NO
    # _CARRYOVER_KEYS entry -- same shape as grotto_chip_taken, since the
    # Dartboard offers no discovery to carry forward and simply resets False
    # at every reset(). Keyed to the day, not to a single cell, because
    # st.entered is per-cell and a second billiard_room id on the grid (see
    # game.py's "duplicates are only possible via the Chamber of Mirrors")
    # would otherwise pay out again.
    dartboard_solved_today: bool = False
    # Set on arrival at Upper Rotating Gear: the Treasure Trove blackprint has
    # been picked up. Same shape as west_gate_unlatched: recorded on STATE, never
    # written back to GameConfig. carryover() ORs this with
    # cfg.treasure_trove_blackprint; DayChain carries the result, permanently
    # adding the Treasure Trove to the draft pool from the following day.
    treasure_trove_blackprint: bool = False
    # Set on arrival at Orindian Ruins: the Throne Room blueprint has been
    # picked up. Same shape as west_gate_unlatched: recorded on STATE, never
    # written back to GameConfig. carryover() ORs this with
    # cfg.throne_room_blueprint; DayChain carries the result, permanently
    # adding the Throne Room to the draft pool from the following day.
    throne_room_blueprint: bool = False
    # Set on campsite arrival with a shovel held: the Conservatory's hidden dig
    # spot has been found. Same shape as west_gate_unlatched: recorded on
    # STATE, never written back to GameConfig. carryover() ORs this with
    # cfg.conservatory_floorplan_found; DayChain carries the result,
    # permanently adding the Conservatory to the draft pool
    # (decks.py::eligible_pool, pool == "found_floorplan") from the following
    # day.
    conservatory_floorplan_found: bool = False
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
    # Set when the Apple Orchard sundial is lit today (special_items.py::light(),
    # requires three held microchips + an ignition tool). Same shape as
    # west_gate_unlatched: an IN-RUN discovery recorded on STATE, never written
    # back to GameConfig. carryover() ORs this with cfg.satellite_dish_unlocked;
    # DayChain carries the result, permanently unlocking the Satellite Dish.
    satellite_dish_unlocked: bool = False
    # Set the moment Game.set_pump_level records the Reservoir at exactly 13.
    # Same shape as west_gate_unlatched: an IN-RUN discovery recorded on
    # STATE, never written back to GameConfig. Game._pump_carryover() ORs
    # this with cfg.reservoir_13_reached; DayChain carries the result,
    # permanently opening the reservoir_north<->reservoir_south rowboat
    # crossing (docs/areas.md) even after the level later moves away from 13
    # -- UNLIKE pump_water_lte8/rowboat_water_6, which re-check the live
    # level on every traversal instead of latching.
    reservoir_13_reached: bool = False
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
    # Set once by effects/rooms/archives.py's ON_PLACE handler, unless Shelter or
    # Knight's Shield negates it (consumed once, here, not per doorway). Unlike the
    # sauna_visited-shaped flags above this carries NO day-to-day meaning -- it is
    # read back out same-day, by every draft.deal_draft/redeal call, to archive one
    # option of the dealt hand (house-wide, non-stacking: a second Archives is a no-op).
    archives_active: bool = False
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

    # --- Forced Draws (data/priority_draws.json "forced_draws"; see draft.py) ---
    # Room ids whose forced-draw roll has already succeeded today, and whose entry
    # carries "once_per_day" (the Garage and the Utility Closet -- wiki: "Once the
    # roll succeeds ... they will no longer be available for Forced Draws" today).
    # An id lands here whether or not the room actually ended up placed in slot 3:
    # the roll can "succeed but fail" when the room already occupies an earlier slot
    # of the same hand. Keyed per room so one entry retiring never silences another.
    # Per-day only: a fresh GameState resets it every day like schoolhouse_placed.
    forced_draws_succeeded_today: set[str] = field(default_factory=set)
    # (room id, target cell, entry direction) triples whose forced-draw chance has
    # already been rolled today -- wiki: "If the chance to appear fails, it does not
    # try again on redraws, but can try again if drafting again in a new location."
    # A redraw re-fills the SAME doorway's hand (draft.py::redeal), so the doorway,
    # not the hand, is what a roll is spent against. An entry that never got as far
    # as its roll (blocked by a gate, or by a higher-precedence entry) is not
    # recorded, which is the same clause's "It can also try again if it didn't get a
    # chance on the first draw". Per-day only, like forced_draws_succeeded_today.
    forced_draws_rolled_today: set[tuple[str, int, int]] = field(default_factory=set)

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
    # Cells whose item roll is dowsed: the Dowsing Rod pointed at this slot
    # when its hand was last dealt/redealt AND the player drafted that slot
    # (draft.py::_pick_dowsing_slot marks PendingDraft.dowsed_slot; Game.choose
    # copies it here against the drafted cell). Consumed (discarded) by
    # engine/items.py::roll_room_items on that cell's first item roll -- same
    # parking-lot shape as closet_bonus_cells/cloister_mila_bonus_cells above.
    dowsing_marked_cells: set[int] = field(default_factory=set)
    # The Dowsing Rod's own Dowsing Penalty (wiki: Dowsing_Rod page's "exact
    # impacts on luck" DataMinedBox: "starts at 0 and can increase from
    # effects below. It does not impact anything outside this effect").
    # Distinct from state.luck_penalty (the "standard" Luck Penalty, which
    # Dowsing rolls still write into but never subtract -- see
    # engine/items.py::roll_dowsed_count). Owner-ruled per-day reset, the same
    # pattern already applied to luck_penalty (the wiki does not explicitly
    # scope either counter's reset window): a fresh GameState resets this
    # every day like luck_penalty. NOT in env/multiday.py's _CARRYOVER_KEYS
    # (a frozenset of bool fields) and never carried across days.
    dowsing_penalty: int = 0
    # The room id the Guess Bedroom (guess_bedroom__ix70) secretly mimics today,
    # rolled once on its first draft and shared by every Guess Bedroom placed
    # afterward; None when no Guess Bedroom has drafted a valid pick yet, or the
    # draw found no eligible Bedroom (mimic fails, room grants nothing). Per-day
    # only -- a fresh GameState resets it every day like geist_bedroom_tomb_cells.
    guess_bedroom_mimic_id: str | None = None

    # Resources parked in a cell, waiting for the player to walk in and collect them
    # (Secret Garden fruit spread today; Patio gems and Locker Room keys will reuse
    # this later). Cell -> list of (what, count) entries, drained in full on the
    # player's next arrival at that cell (Game._collect_spread), not gated on first
    # entry. ``what`` is either a food.dishes id ("apple", "orange", ...) or a
    # grant_item item kind ("key", "gem", "coins", ...) -- the two namespaces never
    # collide. Per-day only: a fresh GameState clears it every day, since spread
    # fruit does not survive the night.
    spread_pending: dict[int, list[tuple[str, int]]] = field(default_factory=dict)

    # Run Payroll's parked coin piles (effects/rooms/office.py), the same
    # "waiting for arrival" shape as spread_pending immediately above, but
    # keyed by ROOM ID instead of cell -- the target (Maid's Chamber/
    # Servant's Quarters) may not be drafted yet when the terminal is used,
    # so there is no cell to park at. Drained in full on the player's next
    # arrival at a cell whose room id matches a key here (Game.
    # _collect_payroll_pending), the same "arrival, not first entry" timing
    # as _collect_spread -- but deliberately NOT spread_pending itself: the
    # wiki states Run Payroll is not a spread and has no Conference Room
    # interaction, so it must never be redirected the way spread_pending
    # entries are. Per-day only: a fresh GameState clears it every day, same
    # as spread_pending (an un-collected pile does not survive the night).
    payroll_pending: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

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

    # Clock Tower's day-end tally: set by Game._terminate only when the Clock
    # Tower is present on the grid at day end, to the count of Tomorrow-category
    # rooms present in the mansion (including the Clock Tower itself); 0 on any
    # day the Clock Tower is not standing. Per-day only. Reported by
    # Game._room_pulse_carryover() as "clock_tower_tomorrow_keys" and carried by
    # DayChain into tomorrow's GameConfig.clock_tower_tomorrow_keys, which sets
    # tomorrow's starting keys at reset() -- the same one-day-pulse shape as
    # hallway_tomorrow_count/sauna_visited.
    clock_tower_tomorrow_keys: int = 0

    # The Axe: ordered tuple of floorplan-family root ids (upgrades.root_base_id)
    # whose gem cost has been permanently zeroed, capped at 3
    # (effects/items/the_axe.py::max_active). Seeded from cfg.axed_rooms at
    # Game.reset; grown (never shrunk) by Game.axe_room -- an ordered tuple,
    # not a set, see GameConfig.axed_rooms for why. resolve_gem_cost below is
    # the only reader; decks.py::build_decks never consults this, so an axed
    # room's cards never move between the free and gem decks (see that
    # function's own docstring).
    axed_rooms: tuple[str, ...] = ()

    # Gear Wrench: Mechanical Room id -> permanently-set rarity index
    # (engine/model.py RARITIES). Seeded from cfg.permanent_rarity at
    # Game.reset; grown/shrunk by Game.set_wrench_rarity (see
    # GameConfig.permanent_rarity for the SAVE-scoped shape). decks.py::
    # build_decks consults this at day-start bucket assignment; decks.py::
    # inject_rooms/inject_rooms_undealt/set_dynamic_rarity consult
    # dynamic_rarity below for the SAME-day bucket, which Game.reset seeds
    # from this dict right after build_decks -- so both the initial deck
    # build and every later mid-day deck mutation agree on where a wrenched
    # room's cards live, closing the corruption decks.py's own module
    # docstring warns about (a wrenched Pump Room injected by The Pool would
    # otherwise land in its un-wrenched natal bucket).
    permanent_rarity: dict[str, int] = field(default_factory=dict)

    # Pump Room: water source id -> permanently-set level (data/pump_room.json's
    # six sources: aquarium, fountain, greenhouse, kitchen, pool, reservoir).
    # Seeded from cfg.water_levels at Game.reset; changed only by
    # Game.set_pump_level. A source absent from this dict sits at its own
    # data-file "initial" value (Game.water_level resolves the fallback), so
    # this dict only ever records OVERRIDES, not the full six-source table.
    # Reported whole by Game._pump_carryover() -- NOT SAVE-scoped, unlike
    # permanent_rarity above (see GameConfig.water_levels for why).
    water_levels: dict[str, int] = field(default_factory=dict)

    # Telescope-in-Planetarium: ordered tuple of unlocked planet ids (the
    # data/special_items.json planetarium_planets table's own id order --
    # never re-sorted, since the wiki's reveal order is random except Mora
    # last, and this tuple records the order they were ACTUALLY revealed
    # in). Seeded from cfg.planetarium_planets at Game.reset; grown (never
    # shrunk) by special_items.use_telescope_in_planetarium. SAVE-scoped,
    # the third carve-out alongside GameState.stars/main_course_bonus (owner
    # ruling): survives the DayChain attempt wrap, unlike axed_rooms/
    # permanent_rarity above, which the wrap does NOT clear either -- but
    # unlike those two this is reported through shops.carryover() rather
    # than a separate Game._x_carryover() method, the same "replace
    # wholesale" dict entry shape as stars/main_course_bonus (see
    # tests/test_carryover.py::test_carryover_shape_is_complete, which pins
    # that pair together so this third key is a deliberate addition).
    planetarium_planets: tuple[str, ...] = ()

    # --- Shrine blessings/curse (engine/effects/rooms/shrine.py) ---
    # Seeded each day from the matching GameConfig.shrine_* fields (Game.reset);
    # a blessing/curse this GameState grants or clears is reported by
    # Game._shrine_carryover() and replaced+decayed into tomorrow's config the
    # same way as mail_cycle/mail_transit_days -- see GameConfig's own comment
    # for the save-scoped-but-daily-decayed shape.
    shrine_blessing_id: str = ""    # active blessing id; meaningful only while blessing_days > 0
    shrine_blessing_days: int = 0   # days left on the blessing, counting the day it was granted
    shrine_curse_days: int = 0      # days left on the Shrine curse (2 when freshly cursed)
    shrine_offered_coins: int = 0   # coins parked in the bowl; returned in full on take-back
    shrine_monk_room: int = -1      # reserved for Blessing of the Monk (not implemented): always -1

    # --- LOCK_PENDING (engine/game.py's Game.open_door / lock-menu resolvers) ---
    # The doorway (cell, direction) awaiting a lock-menu choice (use_key/lockpick/
    # a special key/abandon), set by Game.open_door instead of opening the segment
    # when it is DOOR_LOCKED. Same shape as pending_colour_cell/pending_colour_direction
    # above: -1 outside LOCK_PENDING; direction is only meaningful while cell >= 0.
    pending_lock_cell: int = -1
    pending_lock_direction: int = 0

    # --- WRENCH_PENDING (engine/game.py's Game.choose / Game.set_wrench_rarity) ---
    # The Mechanical Room id awaiting a Gear Wrench rarity pick, set by
    # Game.choose right after placing the room instead of returning to
    # NAVIGATE. Same shape as pending_upgrade_slot: None outside WRENCH_PENDING.
    pending_wrench_room_id: str | None = None

    # --- Conservatory drawing board (engine/effects/rooms/conservatory.py) ---
    # The floorplans today's board presents, as room ids, drawn uniformly WITH
    # replacement when the Conservatory is drafted (so the same id may appear
    # in two rows), plus each row's click count. Both are DAY-scoped: a fresh
    # GameState starts with an unstocked board and only
    # conservatory.stock_drawing_board fills them, so a board never survives
    # the night -- unlike the permanent_rarity entries its clicks write, which
    # are SAVE-scoped. remodel_clicks is index-parallel to remodel_offers; the
    # two are only ever resized together.
    remodel_offers: tuple[str, ...] = ()
    remodel_clicks: list[int] = field(default_factory=list)

    # --- PUMP_LEVEL_PENDING (engine/game.py's Game.set_pump_source / set_pump_level) ---
    # The water source id awaiting a target-level pick, set by Game.set_pump_source
    # instead of returning to NAVIGATE. Same shape as pending_wrench_room_id:
    # None outside PUMP_LEVEL_PENDING.
    pending_pump_source: str | None = None

    # --- Run Payroll cooldown (engine/effects/rooms/office.py) ---
    # Fixed cooldown-key ("office_payroll", office.PAYROLL_COOLDOWN_KEY) -> the
    # day it was last used. Seeded from cfg.payroll_last_used at Game.reset;
    # changed only by office.run_payroll. A plain dict, not in the
    # frozenset-coercion list, the same non-bool carry-over shape as
    # water_levels above (REPLACED, not merged, each advance() -- NOT
    # SAVE-scoped: a payroll cooldown has no more reason to survive an
    # attempt wrap than the Pump Room's levels do).
    payroll_last_used: dict[str, int] = field(default_factory=dict)

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


def _axe_root_id(room: Room, registry_rooms) -> str:
    """Walk ``room.variant_of`` up to its floorplan family's root id.

    Mirrors ``upgrades.root_base_id``, duplicated here rather than imported:
    that helper takes a full ``Registry`` (for ``by_id``), while
    ``resolve_gem_cost`` only ever receives the plain room sequence its two
    call sites already pass (``registry.rooms``) -- see that function's own
    docstring for why its signature does not grow to take a ``Registry``. The
    common case (a non-variant room) costs nothing extra: the id dict is only
    built when a chain actually needs walking.
    """
    if room.variant_of is None:
        return room.id
    by_id = {r.id: r for r in registry_rooms}
    current = room
    while current.variant_of is not None:
        parent = by_id.get(current.variant_of)
        if parent is None:
            break
        current = parent
    return current.id


def resolve_gem_cost(room: Room, state: GameState, registry_rooms) -> int:
    """Resolve a room's gem cost, evaluating dynamic modifiers.

    The Axe's discount is applied here, at cost-RESOLUTION time (both when a
    hand is dealt and when an option is paid for -- draft.py and game.py's
    _effective_cost both route through this one function): an axed floorplan
    family (its root id, via ``upgrades.root_base_id``) always costs 0,
    short-circuiting gem_cost_dynamic entirely. This is a payment-time price
    override, never a deck change -- decks.py::build_decks reads
    Room.gem_cost/is_free directly and never calls this function, matching
    the datamined rule that deck membership uses "the actual gem cost of the
    room, ignoring any modifiers like The Axe".
    """
    if state.axed_rooms and _axe_root_id(room, registry_rooms) in state.axed_rooms:
        return 0
    cost = room.gem_cost
    if room.gem_cost_dynamic == "plus_one_per_bedroom":
        n_bedrooms = sum(
            1 for idx in state.grid if idx >= 0 and registry_rooms[idx].is_category("bedroom")
        )
        cost += n_bedrooms
    return cost
