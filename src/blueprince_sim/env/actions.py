"""Flat action space with masking.

Navigation is macro-based: the agent picks a destination (a frontier doorway
to draft, or a room to enter) and the engine walks the shortest connected
path, paying the normal one-step-per-room cost. Re-entering rooms grants
nothing, so free-form single-tile moves were retired.

Layout (Discrete(479)):
  0..179   draft at doorway: cell (45) x direction (4: N,E,S,W) ->
           cell*4 + dir_index. Walks to the room first if needed. Legal for
           every frontier doorway reachable with at least one step to spare
           on arrival (the drafted room must still be enterable).
  180..182 choose option slot 0/1/2 (the dealt orientation; per-option
           orientation choice is not a real game mechanic -- each option
           arrives with a rolled orientation, and rotation is a separate
           effect, see ROTATE_ACTION)
  183      redraw (engine picks the cheapest available source: free > die > study)
  184      outer-room draft (walk the West Path; once per day, if unlocked)
  185      toggle the keycard power (standing at the Utility Closet breaker)
  186..188 set security level low/normal/high (standing at the Security
           terminal; the current level is masked out as a no-op)
  189      rotate the drawn floorplans to their next legal orientation
           (Ornate Compass held / Rotunda placed / Dovecote in hand;
           overrides the random roll)
  190..234 walk to cell (45): shortest connected path into an unentered
           reachable room (spends steps, first entry grants its resources),
           into the Antechamber (wins), or back into the Utility Closet /
           Security to work their switches; also re-enters shop cells with a
           buyable entry, the Workshop with fabricate options, a Dining
           Room whose main course is still pending once rank 8 is reached,
           a cell still holding a container the player can open, a Vault cell
           with an openable deposit box, an ignition target (chapel/tomb/trading_post)
           with a torch or burning_glass held, and a machine room (greenhouse/casino)
           with a broken_lever held.
  235..240 buy current shop display entry 0..5 (NAVIGATE; on-grid shop or
           inside outer shop (inside_outer_room))
  241..248 trade offer 0..7 (inside the Trading Post; offer index matches
           trade_offers() order)
  249..256 fabricate recipe 0..7 (standing in the Workshop; recipe order
           matches registry.special.fabrication)
  257..262 activate the Royal Scepter with color 0..5 (shops.SCEPTER_COLORS
           order: blueprint, green, red, bedroom, hallway, shop)
  263      smash the Entrance Hall vase
  264      open container at the current cell (trunk/chest/locker; one per action)
  265      open the Garage car trunk (standing in the Garage with Car Keys held)
  266      open vault deposit box (standing in the Vault with a matching vault key)
  267      light ignition target (standing in chapel/tomb/trading_post with torch or burning_glass)
  268      install broken lever in a machine room (greenhouse/casino)
  269      insert an Upgrade Disk (NAVIGATE; standing at a disk reader holding a disk)
  270..272 choose upgrade variant slot 0/1/2 (UPGRADE_PENDING only; exactly
           three options are always offered)
  273..310 travel to area-graph node (38 nodes, sorted by node id for
           determinism): TRAVEL_BASE + area_index. Legal when the destination
           is reachable, affordable (strictly more steps than cost so at least
           1 remains on arrival), and not the player's current position.
           Both on-grid and off-grid travel are permitted — returning to the
           grid is travel to "house" or "garage"; entering an outer room is
           travel to that room's node id. On-grid travel to a grid anchor
           (house/garage/the_foundation) is a walk to that anchor's cell, so
           it is additionally gated on that cell being worth entering (see
           _cell_worth_entering) -- unconditional off-grid, since that is the
           only way back onto the grid.
  311..318 use a held Sanctum Key on one of the Inner Sanctum's eight realm
           doors (special_items.SIGIL_REALMS order: arch_aries, corarica,
           eraja, fenn_aries, mora_jai, nuance, orinda_aries, verra).
           Standing at the inner_sanctum area node holding an unspent Sanctum
           Key, with that realm's door still sealed. Permanently unlocks the
           door and grants its one-time +2 allowance immediately.
  319      operate the Experimental Setup terminal (NAVIGATE; standing in the
           Laboratory, no experiment configured today) -- draws 3 triggers
           and 3 effects and enters EXPERIMENT_PENDING.
  320..322 choose experiment trigger slot 0/1/2 (EXPERIMENT_PENDING; legal
           until a trigger has been chosen this setup).
  323..325 choose experiment effect slot 0/1/2 (EXPERIMENT_PENDING; legal
           until an effect has been chosen this setup). Once both a trigger
           and an effect are chosen the experiment starts and phase returns
           to NAVIGATE.
  326      pause/resume the configured experiment (NAVIGATE; standing in the
           Laboratory with a configured experiment).
  327      toggle the Darkroom lights (standing at the Utility Closet breaker;
           see engine/effects/rooms/darkroom.py for the fuse-blow it guards).
  328..332 choose Secret Passage colour 0..4 (COLOUR_PENDING only; engine.draft.
           COLOUR_CATEGORIES order: bedroom, hallway, green, shop, red). Set by
           opening a doorway whose from-room is a Secret Passage variant for
           the first time (Game.open_door); restricts every option of the
           hand dealt right after the pick to that one colour.
  333..372 donate to the Shrine: blessing_idx*5 + duration_idx (8 blessings x
           5 durations; both in data/shrine.json order -- blessings: dancer,
           high_roller, gardener, tinkerer, general, chef, monk, berry_picker;
           durations: 3,4,5,6,7 days). Legal standing inside the drafted
           Shrine, with no blessing or curse already active, for an
           implemented blessing whose canonical (lower-of-pair) coin cost is
           affordable. Chef and Monk are never legal (unimplemented).
  373      take back the Shrine offering: refunds the parked coins, drops the
           active blessing, and curses the player for 2 days (resource loss
           on every colour drafted while cursed). Legal standing inside the
           drafted Shrine with a blessing currently active.
  374      pick a berry (Blessing of the Berry Picker): DRAFTING phase only,
           replaces choosing one of the three dealt options with a uniformly
           random legal room from the doorway's whole draft pool, disregarding
           rarity. Legal only for an on-grid hand (never an outer-room draft)
           with the blessing active and at least one affordable candidate.
  375      take the Blackbridge Grotto pedestal's microchip: legal standing at
           the blackbridge_grotto area node while the pedestal chip is still
           in place (not yet taken today). Grants one microchip and flips
           GameState.grotto_chip_taken, a one-shot per day (no double-take);
           the chip respawns at the pedestal next day (no carry-over).
  376..378 filter Red Room option slot 0/1/2 via the Crown of the Blueprints
           (DRAFTING; once per hand, unlimited hands per day): legal only for
           a slot whose dealt room is a Red Room (Room.is_category('red'))
           while the Crown is held and its filter has not already been spent
           on the current hand. Blocks that room id from every draw for the
           rest of today (no exemption for colour-selective drafts, the
           Silver Key, the Prism Key, or ducts -- owner ruling), grants 1
           gem, and redeals the hand for free (Game.crown_block).
  379..427 use The Axe on one of the 49 axeable floorplan families
           (_build_axe_target_ids order: every room with a rarity and a gem
           cost, reduced to its upgrades.root_base_id, sorted alphabetically):
           NAVIGATE, legal with an Axe held, the target not already axed, and
           the save-scoped 3-use cap not yet reached. Not gated on standing
           anywhere in particular (the wiki's "Room Directory" is a menu, not
           a physical room). Consumes the Axe and permanently zeroes the
           family's gem cost for the rest of the save -- a payment-time price
           override (engine/state.py::resolve_gem_cost), never a deck change
           (Game.can_axe_room/axe_room).
  428..436 the locked-door menu (Phase.LOCK_PENDING only), entered by
           opening a doorway (0..179 above) that turns out to be DOOR_LOCKED
           -- trying it is free, only a menu choice actually opens it (owner
           ruling: the player decides how, not the engine):
             428     use a key: spends lock_open_cost keys (base 1, plus a
                     Great Hall side door's search surcharge), or refunds
                     entirely to an active Stopwatch charge given >=1 key in
                     hand (Game.can_use_key_at_lock/use_key_at_lock).
             429     lockpick: one Lock Pick Kit / Pick Sound Amplifier
                     attempt; failure spends nothing and does not exit the
                     menu (Game.can_lockpick_at_lock/lockpick_at_lock).
             430     abandon: exits back to NAVIGATE, door still locked,
                     nothing spent -- always legal in LOCK_PENDING, so the
                     phase is never a dead end (Game.can_abandon_lock/
                     abandon_lock).
             431..436 a special key, data/locks.json's special_key_menu.order
                     (the wiki's published fixed row order: Basement Key,
                     Secret Garden Key, Silver Key, Key 8, Master Key, Prism
                     Key). secret_garden_key/key_8 are modelled in this sim
                     as draft_conditions tags rather than door keys -- both
                     are reserved ids, permanently masked off
                     (Game.can_use_special_key_at_lock). Basement Key's own
                     fits() is also always False: this sim has no on-grid
                     Basement door (see effects/items/basement_key.py). Prism
                     Key fits a held-and-colour-fitting room (Bedroom/Hallway/
                     Green Room/Shop/Red Room) and, once used, colour-restricts
                     the resulting draft (effects/items/prism_key.py) --
                     Silver Key, Master Key, and Prism Key are the rows ever
                     actually selectable today.
  437      REWIND last draft (the Chronograph), appended at the end so no
           earlier id shifts: DRAFTING only, legal while a Chronograph is
           held and ``pending.rewind_stack`` is non-empty (i.e. after at
           least one redraw this hand). Pops the hand a redraw most recently
           replaced back into the pending options for free, unlimited times,
           strictly backward through the stack to the original deal (never
           forward -- rewinding never pushes) -- see Game.can_rewind/rewind.
  438..441 choose the Gear Wrench's permanent rarity 0..3 (WRENCH_PENDING
           only), appended at the end so no earlier id shifts. Order matches
           engine.model.RARITIES (commonplace, standard, unusual, rare); all
           four are always offered, including the room's own current rarity
           (that IS how a player declines to change anything -- see
           Game.can_set_wrench_rarity). Entered from :meth:`Game.choose`
           when the just-placed room is a Mechanical Room
           (Room.is_category("mechanical")) and a Gear Wrench is held.
  442      use the Telescope in the Planetarium, appended at the end so no
           earlier id shifts: NAVIGATE only, legal standing in the
           Planetarium with a Telescope held, today's one-upgrade-per-day
           cap not yet spent, and at least one of the five planets still
           locked (see Game.can_use_telescope_planetarium/
           use_telescope_planetarium). Reveals one planet (random order,
           Mora always last) and grants its permanent payload; does not
           consume the Telescope.
  443..457 the constellation block, appended at the end so no earlier id
           shifts. Each id has its own predicate, so none is masked False
           unconditionally except the one record still reserved
           (spiral_of_stars -- docs/rl-environment.md licenses that reserved
           slot as a recorded owner ruling):
             443..455 activate one constellation, one id per
                     data/constellations.json record in file order (ascending
                     star value: north_star, the_twins, the_slice,
                     diamondus_minor, southern_cross, farmers_apple, clavis,
                     diamondus_major, draxus, the_sail, florealis, ink_well,
                     spiral_of_stars). A night sky is the unique set of
                     constellations whose star values SUM to the star count
                     it was first viewed at, so activation is per
                     constellation, never one "activate the sky" id.
             456     view the night sky: generate today's sky at this cell
                     (locked to the star count at that moment) or re-open the
                     one already generated there. An explicit action rather
                     than an on-entry auto-generation, because higher star
                     counts partition into strictly more value and the timing
                     of the look is the decision.
             457     redraw the dealt hand for 1 star (The Ink Well). Its own
                     id, never a source folded into REDRAW_ACTION -- see the
                     constant's comment. Legal once the Ink Well has been
                     activated (Game.can_redraw_with_star).
  458..463 the Pump Room panel, appended at the end so no earlier id
           shifts: pick a water source (data/pump_room.json's six sources,
           file order: aquarium, fountain, greenhouse, kitchen, pool,
           reservoir). NAVIGATE only, standing at the Pump Room's cell
           (Game.can_set_pump_source) -- no separate "open the panel" id,
           the same shape as SET_LEVEL_BASE. Parks Phase.PUMP_LEVEL_PENDING.
  464..478 pick the pending source's target level 0..14 (PUMP_LEVEL_PENDING
           only), masked to that source's own [min, max] (the Reservoir's
           min is 2, every other source's is 0; the Reservoir's own 2..14
           is the widest range of the six, which is why the menu is 15 ids
           wide). The macro action sets the level directly (docs/areas.md's
           Pump Room section: the "set source to level" owner ruling) -- no
           tank/pump puzzle to solve.
  479      Spread Gold in Estate (NAVIGATE; standing at the Office terminal,
           once per day): a random 3/4/5-coin pile into every currently
           drafted room, including the Office itself but never a room
           drafted afterward -- a spread (GameState.spread_pending,
           Game._collect_spread), so a placed Conference Room redirects
           every pile into its own cell, the same way it redirects the
           Patio/Locker Room/Secret Garden (docs/open_tasks.md task 1; owner
           ruling on the pile size, unpublished by the wiki).
  480      Run Payroll (NAVIGATE; standing at the Office terminal, weekly
           cooldown elapsed): 5-coin piles for the Maid's Chamber and the
           Servant's Quarters (10 coins total, both figures published). NOT
           a spread -- no Conference Room interaction (wiki, explicit) --
           paid out instead through GameState.payroll_pending, keyed by room
           id so a target drafted after the terminal is used still receives
           its pile (see effects/rooms/office.py). Cooldown resets the
           coming in-game Saturday after use (owner ruling; day % 7 == 0,
           Day One is Sunday).
"""

from __future__ import annotations

from ..engine.draft import COLOUR_CATEGORIES
from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, DIRS, N_CELLS, rank_of
from ..engine.locks import SECURITY_LEVELS
from ..engine import shops as _shops
from ..engine import special_items as _si
from ..engine.effects import Capability, provides_capability
from ..engine.effects.rooms import pump_room as _pump_room
from ..engine.effects.rooms import shrine as _shrine
from ..engine.model import RARITIES, Registry
from ..engine.upgrades import root_base_id

# ---------------------------------------------------------------------------
# Area-graph node ordering (derived from registry; never hand-maintained)
# ---------------------------------------------------------------------------

def _build_area_node_ids(registry: Registry) -> tuple[str, ...]:
    """Sorted tuple of area-graph node ids, alphabetical for determinism.

    The ordering is derived from registry.area_graph so it cannot drift from
    areas.json. The action index for a node is TRAVEL_BASE + the index here.
    Both the action space and the observation encoder use this single source.

    Asserts its own length against the pinned ``_N_AREA_NODES``: the action
    space reserves exactly that many slots (``TRAVEL_BASE..OPEN_SIGIL_DOOR_
    BASE``), and the mask-building loop that walks this tuple has no bounds
    check, so an area node added to areas.json without a matching bump here
    would silently write past the reserved block into OPEN_SIGIL_DOOR_BASE's
    mask bit -- the same corruption class _build_axe_target_ids's own
    assertion guards against, below.
    """
    result = tuple(sorted(registry.area_graph.nodes.keys()))
    assert len(result) == _N_AREA_NODES, (
        f"areas.json now has {len(result)} area-graph nodes but "
        f"_N_AREA_NODES is pinned at {_N_AREA_NODES} -- bump the constant "
        f"(and every action id from OPEN_SIGIL_DOOR_BASE onward, plus "
        f"N_ACTIONS) to match. This is a deliberate width change, never a "
        f"silent one."
    )
    return result


def _build_axe_target_ids(registry: Registry) -> tuple[str, ...]:
    """Sorted tuple of every floorplan family The Axe can target.

    A "family" is one Room.id keyed by ``upgrades.root_base_id``: axing
    "cloister" zeroes every Cloister upgrade variant's gem cost too, since the
    override lives on the family, not one specific room record (owner
    ruling, docs/special-items-behaviour.md). Derived from every room with a rarity and a
    gem cost, reduced to its root id, so this cannot drift from rooms.json;
    sorted alphabetically for determinism, matching
    _build_area_node_ids/special_items.SIGIL_REALMS. The action index for a
    target is AXE_TARGET_BASE + the index here. Both the action space and the
    observation encoder use this single source.

    Asserts its own length against the pinned ``_N_AXE_TARGETS`` on every
    call: the action space reserves exactly that many slots (``AXE_TARGET_
    BASE..LOCK_MENU_BASE``), and the mask-building loop that walks this tuple
    has no bounds check, so a room gaining a rarity and a nonzero gem cost
    without a matching bump here silently writes past the reserved block into
    LOCK_MENU_BASE's mask bit -- exactly what happened when the Conservatory
    (PR #329) did this, marking "use a key at a lock" legal outside any lock
    menu.
    """
    roots = {
        root_base_id(registry, r)
        for r in registry.rooms
        if r.rarity is not None and r.gem_cost > 0
    }
    result = tuple(sorted(roots))
    assert len(result) == _N_AXE_TARGETS, (
        f"the registry now has {len(result)} axe-eligible floorplan families "
        f"but _N_AXE_TARGETS is pinned at {_N_AXE_TARGETS} -- bump the "
        f"constant (and every action id from LOCK_MENU_BASE onward, plus "
        f"N_ACTIONS) to match. This is a deliberate width change, never a "
        f"silent one."
    )
    return result


def _build_mechanical_room_ids(registry: Registry) -> tuple[str, ...]:
    """Sorted tuple of every Mechanical Room id (Room.is_category("mechanical")).

    Obs-only (no action id is indexed by this -- WRENCH_RARITY_BASE offers a
    fixed 4-rarity menu, never a per-room choice): env/obs.py's own
    "wrench_rarity" key uses this order so it cannot drift from rooms.json.
    Kept alongside _build_axe_target_ids/_build_area_node_ids for the same
    reason those are: a single, sorted-for-determinism, registry-derived
    source shared by every caller (obs.py and blueprince_env.py's
    observation_space() width).
    """
    return tuple(sorted(r.id for r in registry.rooms if r.is_category("mechanical")))


# ---------------------------------------------------------------------------
# Action layout constants
# ---------------------------------------------------------------------------

OPEN_BASE, CHOOSE_BASE = 0, 180
REDRAW_ACTION    = 183
OUTER_DRAFT_ACTION = 184  # walk the West Path; once per day, if unlocked
TOGGLE_POWER_ACTION = 185  # flip the Utility Closet "Keycard Entry" breaker
SET_LEVEL_BASE = 186       # 186..188: set security level low/normal/high
ROTATE_ACTION = 189
MOVE_TO_BASE = 190  # 190..234: walk to cell
BUY_BASE = 235      # 235..240: buy current shop display entry 0..5
TRADE_BASE = 241    # 241..248: trade offer 0..7 (inside the Trading Post)
FABRICATE_BASE = 249  # 249..256: fabricate recipe 0..7 (in the Workshop)
SCEPTER_BASE = 257  # 257..262: activate the Royal Scepter color 0..5
SMASH_VASE_ACTION = 263
OPEN_CONTAINER_ACTION = 264  # open the next container at the current cell
OPEN_CAR_TRUNK_ACTION = 265  # open garage car trunk (Garage + Car Keys)
OPEN_VAULT_BOX_ACTION = 266  # open a vault deposit box (Vault + matching vault key)
LIGHT_ACTION = 267           # light ignition target (torch or burning_glass)
INSTALL_LEVER_ACTION = 268   # install broken_lever in a machine room
INSERT_DISK_ACTION = 269     # insert an Upgrade Disk at a disk reader (NAVIGATE)
CHOOSE_UPGRADE_BASE = 270    # 270..272: choose upgrade variant slot 0/1/2 (UPGRADE_PENDING)
TRAVEL_BASE = 273            # 273..310: travel to area-graph node (38 nodes)

# N_AREA_NODES: one travel slot per area-graph node. _build_area_node_ids
# asserts its own result agrees with this pin on every call (mask length
# alone would not catch a mismatch: mask is always built at N_ACTIONS
# entries regardless of what gets written into it).
_N_AREA_NODES = 38

# 311..318: use a held Sanctum Key on one of the Inner Sanctum's eight realm
# doors (special_items.SIGIL_REALMS order, sorted for determinism). Standing
# at the inner_sanctum area node holding an unspent key; permanently unlocks
# that realm's door and grants its one-time +2 allowance (game.open_sigil_door).
OPEN_SIGIL_DOOR_BASE = TRAVEL_BASE + _N_AREA_NODES  # 273 + 38 = 311
_N_SIGIL_REALMS = 8

# Experiments block; see the module docstring for the per-slot legality rules.
START_SETUP_ACTION = OPEN_SIGIL_DOOR_BASE + _N_SIGIL_REALMS  # 311 + 8 = 319
EXP_TRIGGER_BASE = START_SETUP_ACTION + 1    # 320..322
EXP_EFFECT_BASE = EXP_TRIGGER_BASE + 3       # 323..325
TOGGLE_EXPERIMENT_ACTION = EXP_EFFECT_BASE + 3  # 326
TOGGLE_DARKROOM_ACTION = TOGGLE_EXPERIMENT_ACTION + 1  # 327: flip the "Darkroom" breaker

# 328..332: choose Secret Passage colour 0..4 (COLOUR_PENDING only), appended
# at the end so no earlier id shifts. Order matches engine.draft.COLOUR_CATEGORIES.
CHOOSE_COLOUR_BASE = TOGGLE_DARKROOM_ACTION + 1  # 328

# 333..372: donate to the Shrine. Counts are fixed by the published wiki table
# shape (8 blessings x 5 duration bands), not derived from a variable-length
# registry the way area nodes are -- data/shrine.json's own blessings/bands
# lists carry exactly these lengths (validated by tools/validate_data.py).
DONATE_BASE = CHOOSE_COLOUR_BASE + len(COLOUR_CATEGORIES)  # 328 + 5 = 333
_N_SHRINE_BLESSINGS = 8
_N_SHRINE_DURATIONS = 5
# 373: take back the Shrine offering (refund + curse).
TAKE_BACK_OFFERING_ACTION = DONATE_BASE + _N_SHRINE_BLESSINGS * _N_SHRINE_DURATIONS  # 373
# 374: pick a berry (Blessing of the Berry Picker), DRAFTING phase only.
BERRY_PICK_ACTION = TAKE_BACK_OFFERING_ACTION + 1  # 374

# 375: take the Blackbridge Grotto pedestal's microchip, appended at the end
# so no earlier id shifts. Standing at blackbridge_grotto with the pedestal
# chip still in place (see Game.can_take_grotto_chip).
TAKE_GROTTO_CHIP_ACTION = BERRY_PICK_ACTION + 1  # 375

# 376..378: filter a dealt Red Room option via the Crown of the Blueprints,
# one id per option slot, appended at the end so no earlier id shifts.
# DRAFTING only; see Game.can_crown_block/crown_block.
CROWN_BLOCK_BASE = TAKE_GROTTO_CHIP_ACTION + 1  # 376

# 379..427: use The Axe on one of the 49 axeable floorplan families
# (_build_axe_target_ids order), appended at the end so no earlier id shifts.
# NAVIGATE only, not gated on position; see Game.can_axe_room/axe_room.
AXE_TARGET_BASE = CROWN_BLOCK_BASE + 3  # 379
_N_AXE_TARGETS = 49  # width pinned as a constant (like _N_AREA_NODES) so
                      # N_ACTIONS stays importable with no Registry loaded.
                      # _build_axe_target_ids asserts its own result agrees
                      # with this pin on every call -- a room gaining a
                      # rarity and a gem cost (the Conservatory, PR #329)
                      # once desynced the two silently and corrupted
                      # LOCK_MENU_BASE's mask bit; the assertion makes that
                      # loud instead.

# 428..436: the locked-door menu (Phase.LOCK_PENDING only), appended at the
# end so no earlier id shifts. See Game.can_use_key_at_lock/use_key_at_lock,
# can_lockpick_at_lock/lockpick_at_lock, can_use_special_key_at_lock/
# use_special_key_at_lock, can_abandon_lock/abandon_lock.
LOCK_MENU_BASE = AXE_TARGET_BASE + _N_AXE_TARGETS  # 428
LOCK_USE_KEY_ACTION = LOCK_MENU_BASE          # 428: spend a regular key (Stopwatch may refund it)
LOCK_LOCKPICK_ACTION = LOCK_MENU_BASE + 1     # 429: one Lock Pick Kit / Amplifier attempt
LOCK_ABANDON_ACTION = LOCK_MENU_BASE + 2      # 430: exit the menu; the door stays locked
LOCK_SPECIAL_KEY_BASE = LOCK_MENU_BASE + 3    # 431..436: a special key, data/locks.json's
                                               # special_key_menu.order (the wiki's published
                                               # fixed row order: Basement/Secret Garden/Silver/
                                               # Key 8/Master/Prism). secret_garden_key and key_8
                                               # are reserved ids, permanently masked off -- see
                                               # Game.can_use_special_key_at_lock.
_N_LOCK_SPECIAL_KEYS = 6  # width pinned as a constant, like _N_AREA_NODES/_N_AXE_TARGETS.
                          # _build_lock_special_key_order asserts agreement too.

# 437: REWIND last draft (the Chronograph), appended at the end so no earlier
# id shifts. DRAFTING only; see Game.can_rewind/rewind.
REWIND_ACTION = LOCK_SPECIAL_KEY_BASE + _N_LOCK_SPECIAL_KEYS  # 437

# 438..441: choose the Gear Wrench's permanent rarity (Phase.WRENCH_PENDING
# only), appended at the end so no earlier id shifts. Order matches
# engine.model.RARITIES. See Game.can_set_wrench_rarity/set_wrench_rarity.
WRENCH_RARITY_BASE = REWIND_ACTION + 1  # 438
_N_WRENCH_RARITIES = len(RARITIES)  # 4; RARITIES is a fixed model constant,
                                     # not registry-derived, so no width-pin
                                     # comment is needed the way _N_AXE_TARGETS
                                     # etc. carry one

# 442: use the Telescope in the Planetarium, appended at the end so no
# earlier id shifts. See Game.can_use_telescope_planetarium/
# use_telescope_planetarium.
USE_TELESCOPE_PLANETARIUM_ACTION = WRENCH_RARITY_BASE + _N_WRENCH_RARITIES  # 442

# 443..455: activate one constellation in the night sky, one id per
# data/constellations.json record in file order (ascending star value:
# north_star, the_twins, the_slice, diamondus_minor, southern_cross,
# farmers_apple, clavis, diamondus_major, draxus, the_sail, florealis,
# ink_well, spiral_of_stars), appended at the end so no earlier id shifts.
# That file's record order is the single source for this block and for
# env/obs.py's "constellations" key, the way data/locks.json's
# special_key_menu.order is for LOCK_SPECIAL_KEY_BASE.
ACTIVATE_CONSTELLATION_BASE = USE_TELESCOPE_PLANETARIUM_ACTION + 1  # 443
_N_CONSTELLATIONS = 13  # width pinned as a constant (like _N_AXE_TARGETS) so
                        # N_ACTIONS stays importable with no Registry loaded;
                        # tools/validate_data.py holds the record count at 13

# 456: view the night sky (generate or re-open today's sky at this cell).
VIEW_NIGHT_SKY_ACTION = ACTIVATE_CONSTELLATION_BASE + _N_CONSTELLATIONS  # 456

# 457: redraw the dealt hand by spending 1 star (The Ink Well). A dedicated
# id, never a source inside REDRAW_ACTION: every other redraw source spends a
# hand- or day-scoped resource with a natural bound, while a star is permanent
# and save-scoped with no cap, so folding it in would put an uncapped drain on
# an id the agent already presses reflexively.
REDRAW_WITH_STAR_ACTION = VIEW_NIGHT_SKY_ACTION + 1  # 457

# 458..463: pick a Pump Room water source (data/pump_room.json's six sources,
# file order = alphabetical by id: aquarium, fountain, greenhouse, kitchen,
# pool, reservoir), appended at the end so no earlier id shifts. NAVIGATE
# only, standing at the Pump Room's cell (Game.can_set_pump_source) -- no
# separate "open the panel" id, the same shape as SET_LEVEL_BASE offering
# Security's three levels directly while standing at its terminal. Picking a
# source parks Phase.PUMP_LEVEL_PENDING awaiting a target level next.
PUMP_SOURCE_BASE = REDRAW_WITH_STAR_ACTION + 1  # 458
_N_PUMP_SOURCES = 6  # width pinned as a constant (like _N_AXE_TARGETS) so
                     # N_ACTIONS stays importable with no Registry loaded;
                     # _build_pump_source_ids asserts its own result agrees.

# 464..478: pick the pending source's target level, 0..14 (PUMP_LEVEL_PENDING
# only), appended at the end so no earlier id shifts. 15 ids cover every
# source's range in one fixed-width menu -- the Reservoir's own max (14) is
# the widest -- with Game.can_set_pump_level masking each id to the pending
# source's own [min, max] (data/pump_room.json; the Reservoir's min is 2,
# every other source's is 0). The macro action sets the level directly
# (docs/areas.md's Pump Room section: the "set source to level" owner
# ruling): no tank/pump puzzle to solve, so this phase can never dead-end --
# the source's current level is always one of the legal ids.
PUMP_LEVEL_BASE = PUMP_SOURCE_BASE + _N_PUMP_SOURCES  # 464
_N_PUMP_LEVELS = 15  # levels 0..14

# 479: Spread Gold in Estate (NAVIGATE; standing at the Office terminal, once
# per day), appended at the end so no earlier id shifts. A spread -- see
# Game.spread_gold/effects/rooms/office.py -- so it is redirected the same
# way the Patio/Locker Room/Secret Garden are when a Conference Room is
# already placed (docs/open_tasks.md task 1).
SPREAD_GOLD_ACTION = PUMP_LEVEL_BASE + _N_PUMP_LEVELS  # 479

# 480: Run Payroll (NAVIGATE; standing at the Office terminal, weekly
# cooldown elapsed), appended at the end so no earlier id shifts. NOT a
# spread -- see Game.run_payroll/effects/rooms/office.py -- paid out through
# GameState.payroll_pending instead of spread_pending, with no Conference
# Room interaction (docs/open_tasks.md task 1).
RUN_PAYROLL_ACTION = SPREAD_GOLD_ACTION + 1  # 480

# N_ACTIONS = first slot after Run Payroll.
N_ACTIONS = RUN_PAYROLL_ACTION + 1  # 481

DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


def _build_lock_special_key_order(registry: Registry) -> tuple[str, ...]:
    """The special-keys-menu row order (data/locks.json's special_key_menu.order),
    a published wiki table rather than a Python constant. The action index for
    a row is LOCK_SPECIAL_KEY_BASE + the index here; both the action space and
    the observation encoder would use this single source (matching
    _build_area_node_ids/_build_axe_target_ids).

    Asserts its own length against the pinned ``_N_LOCK_SPECIAL_KEYS``, the
    same shape as the other two builders' guards: the mask-building loop that
    walks this tuple has no bounds check, so a row added to or removed from
    data/locks.json's special_key_menu.order without a matching bump here
    would silently write past the reserved block into REWIND_ACTION's mask
    bit.
    """
    result = tuple(registry.lock_rules["special_key_menu"]["order"])
    assert len(result) == _N_LOCK_SPECIAL_KEYS, (
        f"data/locks.json's special_key_menu.order now has {len(result)} "
        f"rows but _N_LOCK_SPECIAL_KEYS is pinned at {_N_LOCK_SPECIAL_KEYS} "
        f"-- bump the constant (and every action id from REWIND_ACTION "
        f"onward, plus N_ACTIONS) to match. This is a deliberate width "
        f"change, never a silent one."
    )
    return result


def _build_pump_source_ids(registry: Registry) -> tuple[str, ...]:
    """Pump Room water-source ids in data/pump_room.json's own file order
    (alphabetical by id). The action index for a source is PUMP_SOURCE_BASE +
    the index here; both the action space and the observation encoder use
    this single source.

    Asserts its own length against the pinned ``_N_PUMP_SOURCES``, the same
    shape as ``_build_lock_special_key_order``/``_build_axe_target_ids``: the
    mask-building loop that walks this tuple has no bounds check, so a source
    added to or removed from data/pump_room.json without a matching bump here
    would silently write past the reserved block into PUMP_LEVEL_BASE's mask bit.
    """
    result = tuple(s.id for s in _pump_room.load_sources(registry.data_dir))
    assert len(result) == _N_PUMP_SOURCES, (
        f"data/pump_room.json now has {len(result)} water sources but "
        f"_N_PUMP_SOURCES is pinned at {_N_PUMP_SOURCES} -- bump the "
        f"constant (and every action id from PUMP_LEVEL_BASE onward, plus "
        f"N_ACTIONS) to match. This is a deliberate width change, never a "
        f"silent one."
    )
    return result


def _cell_is_shop_re_enterable(game: Game, cell: int) -> bool:
    """True when ``cell`` holds a shop (or Workshop) that warrants re-entry.

    For regular shops: stock has been rolled AND at least one entry is buyable
    (not sold_out and affordable).  For the Workshop: stock rolled (marker
    present) and fabricate_options() is non-empty.  Uses state.shops.stock
    directly (position-independent) via shops.stock_display.
    """
    st = game.state
    room_idx = st.grid[cell]
    if room_idx < 0:
        return False
    room = game.registry.rooms[room_idx]

    if room.id == "workshop":
        # Workshop re-entry allowed when fabrication options exist
        if "workshop" not in st.shops.stock:
            return False  # not yet entered
        return bool(game.fabricate_options())

    if provides_capability(room.id, Capability.COMMERCE):
        # Regular shop: need a buyable (non-sold-out, affordable) entry
        if room.id not in st.shops.stock:
            return False  # not yet entered; stock not rolled
        display = _shops.stock_display(game, room.id)
        return any(not d["sold_out"] and d["affordable"] and not d["blocked"]
               for d in display)

    return False


def _dining_room_re_enterable(game: Game, cell: int) -> bool:
    """True when ``cell`` holds a Dining Room variant that can still serve.

    Conditions: special items enabled, course not yet served, rank-8 gate open
    (some entered cell at rank >= 8 -- mirrors _maybe_serve_main_course's check).
    """
    st = game.state
    room_idx = st.grid[cell]
    if room_idx < 0:
        return False
    room = game.registry.rooms[room_idx]
    if room.id != "dining_room" and room.variant_of != "dining_room":
        return False
    if not st.special.enabled:
        return False
    if st.special.dining_room_served:
        return False
    # Rank-8 gate: some entered cell must be at rank >= 8
    if not any(entered and rank_of(c) >= 8 for c, entered in enumerate(st.entered)):
        return False
    return True


def _cell_has_openable_container(game: Game, cell: int) -> bool:
    """True when ``cell`` has an openable container the player can still open.

    Allows re-entry to a placed room that still has containers available.
    """
    return _si.can_open_container(game, cell)


def _cell_has_vault_box(game: Game, cell: int) -> bool:
    """True when ``cell`` is the Vault and the player holds a key for an unopened box.

    Position-independent: used to enable walk-to re-entry so the agent can
    return to the Vault after picking up a vault key elsewhere.
    """
    st = game.state
    if st.grid[cell] < 0:
        return False
    room = game.registry.rooms[st.grid[cell]]
    if room.id != "vault":
        return False
    vault_boxes = game.registry.special.containers.get("vault_boxes", {})
    boxes = vault_boxes.get("boxes", {})
    used_keys = getattr(game.cfg, "used_vault_keys", frozenset())
    for key_id in boxes:
        if key_id in used_keys:
            continue
        if key_id in st.special.vault_boxes_opened:
            continue
        if st.inventory.get(key_id, 0) > 0:
            return True
    return False



def _cell_has_ignition_target(game: Game, cell: int) -> bool:
    """True when ``cell`` holds an unlit ignition target and the player holds a tool.

    Position-independent: enables walk-to re-entry so the agent can return to
    a chapel/tomb/trading_post after picking up a torch or burning_glass.
    """
    st = game.state
    if st.grid[cell] < 0:
        return False
    room = game.registry.rooms[st.grid[cell]]
    targets = game.registry.special.ignition.get("targets", {})
    if room.id not in targets:
        return False
    if room.id in st.special.lit_targets:
        return False
    tools = frozenset(game.registry.special.ignition.get("tools", []))
    if not any(st.inventory.get(t, 0) > 0 for t in tools):
        return False
    target_cfg = targets[room.id]
    return _si.ignition_requires_met(st.inventory, target_cfg)


def _cell_has_machine(game: Game, cell: int) -> bool:
    """True when ``cell`` holds a machine room usable with the broken_lever.

    Position-independent: enables walk-to re-entry so the agent can return
    to the greenhouse or casino after picking up a broken_lever.
    """
    st = game.state
    if st.grid[cell] < 0:
        return False
    room = game.registry.rooms[st.grid[cell]]
    machines = game.registry.special.machines
    machine_ids = {k for k in machines if k != "meta"}
    if room.id not in machine_ids:
        return False
    if room.id in st.special.machines_used:
        return False
    return _si.has(st, "broken_lever")


def _cell_has_telescope_planetarium_use(game: Game, cell: int) -> bool:
    """True when ``cell`` is the Planetarium and using the Telescope there is legal.

    Position-independent (checks ``cell`` directly, not ``game.state.pos``,
    the same shape as ``_cell_has_ignition_target``/``_cell_has_machine``
    above -- ``Game.can_use_telescope_planetarium`` cannot be reused here
    since it reads the player's CURRENT position via ``at_planetarium()``).
    Enables walk-to re-entry so the agent can return to the Planetarium
    after picking up a Telescope elsewhere, or after the day boundary resets
    today's one-upgrade-per-day cap. The Dauja Trunk re-entry case is
    already covered by ``_cell_has_openable_container`` above
    (effects/rooms/planetarium.py's ``container_kinds`` overlay folds it into
    the ordinary container read), so this predicate only needs to cover the
    telescope-use action.
    """
    st = game.state
    if st.grid[cell] < 0:
        return False
    if game.registry.rooms[st.grid[cell]].id != "planetarium":
        return False
    if not game.cfg.special_items:
        return False
    if not _si.has(st, "telescope"):
        return False
    if st.special.planetarium_telescope_used:
        return False
    return len(st.planetarium_planets) < len(game.registry.special.planetarium_planets)


def _cell_worth_entering(game: Game, cell: int) -> bool:
    """True when walking into ``cell`` accomplishes something (purposefulness gate).

    An unentered cell is always worth entering (first-entry pickups). An
    already-entered cell is worth entering only when it is a control room
    (Utility Closet / Security -- gated on ``game.cfg.door_locks``, since
    their switches only matter with door locking enabled) or one of the
    re-entry extensions: a buyable shop/Workshop, a Dining Room with a
    pending main course, an openable container, an openable vault deposit
    box, an unlit ignition target with a tool in hand, a machine room with a
    broken_lever in hand, or the Planetarium with a usable Telescope.

    Self-contained: computes the control-room cells itself so callers (the
    MOVE_TO loop and the travel-to-grid-anchor filter) need not thread any
    extra state through.
    """
    st = game.state
    if not st.entered[cell]:
        return True
    control_cells: set[int] = set()
    if game.cfg.door_locks:
        control_cells = {c for c in (game.room_cells.get("utility_closet", -1),
                                     game.room_cells.get("security", -1))
                         if c >= 0}
    if cell in control_cells:
        return True
    return (_cell_is_shop_re_enterable(game, cell)
            or _dining_room_re_enterable(game, cell)
            or _cell_has_openable_container(game, cell)
            or _cell_has_vault_box(game, cell)
            or _cell_has_ignition_target(game, cell)
            or _cell_has_machine(game, cell)
            or _cell_has_telescope_planetarium_use(game, cell))


def action_mask(game: Game, prev_action: int | None = None) -> list[bool]:
    """Legality mask over the flat action space for the current phase.

    NAVIGATE off-grid (``game.off_grid``) permits only outer-area actions.
    On-grid NAVIGATE permits frontier drafts that arrive with a step (and,
    behind locked doors, a key) to spare, walks to unentered rooms and the
    control rooms, and the outer-draft/switch actions. DRAFTING permits
    affordable slots plus redraw/rotate/Crown-block when available. TERMINAL
    masks everything off.

    Travel actions (TRAVEL_BASE + i) are legal when ALL of: the destination is
    reachable via area_route_cost, the player can strictly afford it (steps >
    cost), and the destination is not the player's current node. Travel is
    permitted both on-grid and off-grid. On-grid travel to a grid anchor
    (house/garage/the_foundation) is additionally gated on
    _cell_worth_entering(anchor_cell): it is just a walk to that cell, so it
    must clear the same purposefulness bar MOVE_TO enforces. This gate does
    NOT apply off-grid, where travel to a grid anchor is the only way back
    onto the grid.

    ``prev_action`` enables the security-setpoint repeat guard: when the
    previous *applied* action was a set-security-level id (SET_LEVEL_BASE
    <= prev_action < SET_LEVEL_BASE + 3), all three set-level ids are forced
    False regardless of position.  This prevents a policy from thrashing the
    setpoint back-and-forth for free.  Pass None (default) to omit the guard;
    existing callers that do not track ``prev_action`` are unaffected.
    """
    mask = [False] * N_ACTIONS
    if game.phase is Phase.NAVIGATE:
        st = game.state
        # Set outside the on-grid/off-grid split: three disk readers sit on the
        # grid but Shelter is an outer room, and can_insert_disk() already
        # resolves both cases. Putting it in either branch strands the other.
        if game.can_insert_disk():
            mask[INSERT_DISK_ACTION] = True

        # The Office's other terminal process (disk_reader is a third,
        # separate one, masked just above): both gate on standing at the
        # Office's own cell, which is always on-grid, so no off-grid case to
        # resolve here.
        if game.can_spread_gold():
            mask[SPREAD_GOLD_ACTION] = True
        if game.can_run_payroll():
            mask[RUN_PAYROLL_ACTION] = True

        # Also outside the split: most ignition targets (chapel, tomb,
        # trading_post) sit on the grid, but mine_south is an off-grid area
        # node -- can_light() already resolves both. Leaving this in the
        # on-grid-only branch below would strand the mine_south candlesticks
        # forever (soft-lock: the stairway could never be lit).
        if game.can_light():
            mask[LIGHT_ACTION] = True

        # Both predicates go through at_laboratory_terminal(), which is False
        # off-grid and inside outer rooms, so they need no separate guard.
        if game.can_start_setup():
            mask[START_SETUP_ACTION] = True
        if game.can_toggle_experiment():
            mask[TOGGLE_EXPERIMENT_ACTION] = True

        # Travel actions: legal on-grid AND off-grid. A destination is legal when
        # reachable, the player can strictly afford it (steps > cost, so at
        # least 1 step remains on arrival), and it is not the current location.
        # "Current location" covers two cases:
        #   - Off-grid: st.area == node_id (direct node match).
        #   - On-grid: a grid anchor (house/garage) whose route cost is 0
        #     means the player is already at that anchor cell — treat as
        #     self-travel so the agent does not pay 0 steps to stay put.
        # On-grid travel to a grid anchor (house/garage/the_foundation) is
        # ALSO just a walk to that anchor's cell, so it is subject to the same
        # purposefulness gate as MOVE_TO (_cell_worth_entering) -- otherwise it
        # is a back door around the move mask's own re-entry rule (e.g.
        # travelling to "house" to walk right back into an already-entered,
        # non-re-enterable Entrance Hall). This gate does NOT apply off-grid:
        # travel to a grid anchor off-grid is how the player gets back onto
        # the grid at all, so it must stay unconditional there.
        node_ids = _build_area_node_ids(game.registry)
        graph_nodes = game.registry.area_graph.nodes
        route_costs = game.area_route_costs()
        grid_anchors = None if game.off_grid else game._grid_anchors()
        for i, node_id in enumerate(node_ids):
            # Unmodelled areas have no contents to collect, so offering travel to
            # them is a pure step sink.  They stay in the graph and the pathfinder
            # still routes THROUGH them; they are just not advertised as
            # destinations until a later PR models what is there and flips the flag.
            # Keeping a slot for every node means that flip costs no retrain.
            if not graph_nodes[node_id].modelled:
                continue
            # Off-grid self-travel: already at this node.
            if st.area is not None and st.area == node_id:
                continue
            result = route_costs.get(node_id)
            if result is None:
                continue
            cost, _anchor = result
            # On-grid self-travel: route to a grid anchor with cost 0 means the
            # player is already standing at that anchor cell.
            if cost == 0:
                continue
            # On-grid only: travelling to a grid anchor is a walk to its cell,
            # so it must clear the same purposefulness bar as MOVE_TO.
            if grid_anchors is not None and node_id in grid_anchors:
                if not _cell_worth_entering(game, grid_anchors[node_id]):
                    continue
            # Strict affordability: steps > cost so at least 1 remains.
            if st.steps > cost:
                mask[TRAVEL_BASE + i] = True

        # Sigil Chamber doors: legal at the Inner Sanctum with an unspent
        # Sanctum Key, per sealed realm. can_open_sigil_door already checks
        # off_grid/area/inventory/already-open, so no extra guard is needed here.
        for i, realm in enumerate(_si.SIGIL_REALMS):
            if game.can_open_sigil_door(realm):
                mask[OPEN_SIGIL_DOOR_BASE + i] = True

        # The Axe: legal on-grid AND off-grid, like the Sigil doors above --
        # can_axe_room already checks phase/item/cap/target, no position guard.
        for i, target_id in enumerate(_build_axe_target_ids(game.registry)):
            if game.can_axe_room(target_id):
                mask[AXE_TARGET_BASE + i] = True

        if game.off_grid:
            # Off-grid: only outer-area actions are legal (besides travel above).
            # Buy actions are valid inside any outer shop (inside_outer_room)
            if game.inside_outer_room:
                stock = game.shop_stock()
                if stock is not None:
                    for i, entry in enumerate(stock):
                        if i >= 6:
                            break
                        if not entry["sold_out"] and entry["affordable"] and not entry["blocked"]:
                            mask[BUY_BASE + i] = True
            # Trade offers inside the Trading Post (inside_outer_room)
            offers = game.trade_offers()
            for i in range(min(len(offers), 8)):
                mask[TRADE_BASE + i] = True
            # Shrine donate/take-back (inside the drafted Shrine); can_donate_shrine
            # and can_take_back_shrine_offering already check position themselves.
            for bi in range(_N_SHRINE_BLESSINGS):
                for di in range(_N_SHRINE_DURATIONS):
                    if game.can_donate_shrine(bi, di):
                        mask[DONATE_BASE + bi * _N_SHRINE_DURATIONS + di] = True
            if game.can_take_back_shrine_offering():
                mask[TAKE_BACK_OFFERING_ACTION] = True
            # Grotto pedestal chip (blackbridge_grotto); can_take_grotto_chip
            # already checks position and the not-yet-taken-today flag.
            if game.can_take_grotto_chip():
                mask[TAKE_GROTTO_CHIP_ACTION] = True
        else:
            dist = game.distance_map()
            key_cost = game.key_cost_map()
            # Draft any reachable, triable frontier doorway; arriving must
            # leave >= 1 step (so the drafted room can still be entered) and
            # afford the WALK's own key spend (key_cost[cell], from crossing
            # other locked doors en route). Whether the doorway itself can be
            # TRIED at all (sealed never; security only while openable; a
            # locked one always -- trying it is free, it parks
            # Phase.LOCK_PENDING rather than spending anything) is
            # Game.frontier_doorway_triable's call, the single source shared
            # with Game.draft_from so the two cannot silently diverge.
            for cell, d in game.frontier_doorways():
                if not 0 <= dist[cell] <= st.steps - 1:
                    continue
                if not game.frontier_doorway_triable(cell, d):
                    continue
                if st.keys < key_cost[cell]:
                    continue  # can't even afford the walk there
                mask[OPEN_BASE + cell * 4 + DIR_INDEX[d]] = True
            # Walk to an unentered room (first entry grants its resources), the
            # Antechamber (never marked entered while the game is live), or a
            # control room (Utility Closet / Security) to work its switches.
            # Also re-enter shop cells with a buyable entry, the Workshop when
            # fabricate options exist, and a Dining Room with pending main course.
            # See _cell_worth_entering for the exact purposefulness rule.
            for cell in range(N_CELLS):
                if not (0 < dist[cell] <= st.steps):
                    continue
                if _cell_worth_entering(game, cell):
                    mask[MOVE_TO_BASE + cell] = True
            # Buy actions from an on-grid shop (current cell)
            stock = game.shop_stock()
            if stock is not None:
                for i, entry in enumerate(stock):
                    if i >= 6:
                        break
                    if not entry["sold_out"] and entry["affordable"] and not entry["blocked"]:
                        mask[BUY_BASE + i] = True
            # Fabricate actions (requires standing in the Workshop)
            if _shops._inside_workshop(game):
                fab_options = game.fabricate_options()
                for i, (inputs, output) in enumerate(game.registry.special.fabrication):
                    if i >= 8:
                        break
                    if output in fab_options:
                        mask[FABRICATE_BASE + i] = True
            # Scepter actions
            if game.can_activate_scepter():
                for i in range(len(_shops.SCEPTER_COLORS)):
                    mask[SCEPTER_BASE + i] = True
            # Vase smash
            if game.can_smash_vase():
                mask[SMASH_VASE_ACTION] = True
            if game.can_open_container():
                mask[OPEN_CONTAINER_ACTION] = True
            if game.can_use_telescope_planetarium():
                mask[USE_TELESCOPE_PLANETARIUM_ACTION] = True
            if game.can_open_car_trunk():
                mask[OPEN_CAR_TRUNK_ACTION] = True
            if game.can_open_vault_box():
                mask[OPEN_VAULT_BOX_ACTION] = True
            if game.can_install_lever():
                mask[INSTALL_LEVER_ACTION] = True
            if game.outer_draft_available():
                mask[OUTER_DRAFT_ACTION] = True
            if game.can_toggle_keycard_power():
                mask[TOGGLE_POWER_ACTION] = True
            if game.can_toggle_darkroom_lights():
                mask[TOGGLE_DARKROOM_ACTION] = True
            if game.can_set_security_level():
                for i, level in enumerate(SECURITY_LEVELS):
                    if level != st.security_level:
                        mask[SET_LEVEL_BASE + i] = True
            # Pump Room panel: all six sources are always offered together
            # while standing there, same shape as SET_LEVEL_BASE (no separate
            # "open the panel" id).
            if game.can_set_pump_source():
                for i in range(_N_PUMP_SOURCES):
                    mask[PUMP_SOURCE_BASE + i] = True
    elif game.phase is Phase.DRAFTING:
        pending = game.state.pending
        for opt in pending.options:
            room = game.registry.rooms[opt.room_idx]
            if game.affordable(room, opt):
                mask[CHOOSE_BASE + opt.slot] = True
        if _redraw_kind(game) is not None:
            mask[REDRAW_ACTION] = True
        if game.rotation_available():
            mask[ROTATE_ACTION] = True
        if game.can_berry_pick():
            mask[BERRY_PICK_ACTION] = True
        for i in range(3):
            if game.can_crown_block(i):
                mask[CROWN_BLOCK_BASE + i] = True
        if game.can_rewind():
            mask[REWIND_ACTION] = True
    elif game.phase is Phase.UPGRADE_PENDING:
        # Exactly three upgrade variants are always offered; enable all three.
        # No other actions are legal in this phase — the player must choose.
        for i in range(3):
            mask[CHOOSE_UPGRADE_BASE + i] = True
    elif game.phase is Phase.EXPERIMENT_PENDING:
        # Exactly three triggers and three effects are always offered; each
        # section masks off once its own pick has been made (the other
        # section stays open independently, so either can be picked first).
        ex = game.state.experiment
        if ex.trigger_id is None:
            for i in range(3):
                mask[EXP_TRIGGER_BASE + i] = True
        if ex.effect_id is None:
            for i in range(3):
                mask[EXP_EFFECT_BASE + i] = True
    elif game.phase is Phase.COLOUR_PENDING:
        # All five colours are always offered; no other action is legal here
        # -- the player must pick one (Game.choose_colour).
        for i in range(len(COLOUR_CATEGORIES)):
            mask[CHOOSE_COLOUR_BASE + i] = True
    elif game.phase is Phase.LOCK_PENDING:
        # abandon is unconditionally legal (the wiki's "option to exit the
        # menu") so this phase is never a dead end; the other rows depend on
        # what's held/affordable (Game.can_use_key_at_lock/can_lockpick_at_lock/
        # can_use_special_key_at_lock).
        if game.can_use_key_at_lock():
            mask[LOCK_USE_KEY_ACTION] = True
        if game.can_lockpick_at_lock():
            mask[LOCK_LOCKPICK_ACTION] = True
        for i, key_id in enumerate(_build_lock_special_key_order(game.registry)):
            if game.can_use_special_key_at_lock(key_id):
                mask[LOCK_SPECIAL_KEY_BASE + i] = True
        mask[LOCK_ABANDON_ACTION] = True
    elif game.phase is Phase.WRENCH_PENDING:
        # All four rarity levels are always offered (Game.can_set_wrench_rarity);
        # no other action is legal here -- the player must choose, and picking
        # the room's own current rarity is how they decline. This phase can
        # never dead-end.
        for i in range(_N_WRENCH_RARITIES):
            if game.can_set_wrench_rarity(i):
                mask[WRENCH_RARITY_BASE + i] = True
    elif game.phase is Phase.PUMP_LEVEL_PENDING:
        # The pending source's own [min, max] range (data/pump_room.json);
        # always at least one legal level (the source's current one is
        # always in range), so this phase can never dead-end -- no abandon
        # id needed, the same shape as WRENCH_PENDING/COLOUR_PENDING.
        for level in range(_N_PUMP_LEVELS):
            if game.can_set_pump_level(level):
                mask[PUMP_LEVEL_BASE + level] = True
    # Security-setpoint repeat guard: if the last applied action was a
    # set-level id, mask all three off so the agent must do something else
    # before touching the setpoint again.
    if prev_action is not None and SET_LEVEL_BASE <= prev_action < SET_LEVEL_BASE + 3:
        for i in range(3):
            mask[SET_LEVEL_BASE + i] = False
    # Night sky. Written here rather than inside the NAVIGATE branch above
    # because each Game predicate tests the phase itself -- which keeps every
    # declared id at exactly one masking site (docs/rl-environment.md's rule on
    # reserved versus dead ids).
    #
    # The eight unimplemented constellations come back False from
    # can_activate_constellation's own ``implemented`` test, so this loop needs
    # no skip list: data/constellations.json stays the single source for which
    # ids are live, and flipping a record's ``implemented`` is all it takes.
    for i in range(_N_CONSTELLATIONS):
        mask[ACTIVATE_CONSTELLATION_BASE + i] = game.can_activate_constellation(i)
    mask[VIEW_NIGHT_SKY_ACTION] = game.can_view_night_sky()
    mask[REDRAW_WITH_STAR_ACTION] = game.can_redraw_with_star()
    return mask


def _redraw_kind(game: Game) -> RedrawKind | None:
    """Cheapest redraw source available right now (free > die > study), or None.

    Applies to outer-room drafts (``pending.target_cell == -1``) the same as
    grid drafts (owner-ruled, externally corroborated -- see Game.redraw).
    The Study source costs a gem and is capped at 8 uses per hand; FREE
    (Classroom) redraws are only ever nonzero when drafting from inside the
    Classroom, which is impossible for an outer hand (no from-cell), so FREE
    naturally never applies there without any outer-specific carve-out.
    """
    st = game.state
    pending = st.pending
    if pending is None:
        return None
    if pending.redraws_left > 0:
        return RedrawKind.FREE
    if st.dice >= 1:
        return RedrawKind.DIE
    if st.study_placed and st.gems >= 1 and pending.study_redraws_used < 8:
        return RedrawKind.STUDY
    return None


def apply_action(game: Game, action: int) -> None:
    """Execute one flat action id against the Game API.

    Assumes the action is legal per :func:`action_mask`; the env checks the
    mask first and turns illegal actions into penalized no-ops instead.
    """
    if action < CHOOSE_BASE:
        cell, dir_idx = divmod(action, 4)
        game.draft_from(cell, DIRS[dir_idx])
    elif action < REDRAW_ACTION:
        game.choose(action - CHOOSE_BASE)
    elif action == REDRAW_ACTION:
        kind = _redraw_kind(game)
        assert kind is not None, "no redraw available"
        game.redraw(kind)
    elif action == OUTER_DRAFT_ACTION:
        game.open_outer_draft()
    elif action == TOGGLE_POWER_ACTION:
        game.set_keycard_power(not game.state.keycard_power_on)
    elif action == TOGGLE_DARKROOM_ACTION:
        game.set_darkroom_lights(not game.state.darkroom_lights_on)
    elif SET_LEVEL_BASE <= action < SET_LEVEL_BASE + len(SECURITY_LEVELS):
        game.set_security_level(SECURITY_LEVELS[action - SET_LEVEL_BASE])
    elif action == ROTATE_ACTION:
        game.rotate_options()
    elif MOVE_TO_BASE <= action < MOVE_TO_BASE + N_CELLS:
        game.move_to(action - MOVE_TO_BASE)
    elif BUY_BASE <= action < TRADE_BASE:
        game.buy(action - BUY_BASE)
    elif TRADE_BASE <= action < FABRICATE_BASE:
        offers = game.trade_offers()
        game.trade(offers[action - TRADE_BASE]["give"])
    elif FABRICATE_BASE <= action < SCEPTER_BASE:
        i = action - FABRICATE_BASE
        output = game.registry.special.fabrication[i][1]
        game.fabricate(output)
    elif SCEPTER_BASE <= action < SMASH_VASE_ACTION:
        color = _shops.SCEPTER_COLORS[action - SCEPTER_BASE]
        game.activate_scepter(color)
    elif action == SMASH_VASE_ACTION:
        game.smash_vase()
    elif action == OPEN_CONTAINER_ACTION:
        game.open_container()
    elif action == OPEN_CAR_TRUNK_ACTION:
        game.open_car_trunk()
    elif action == OPEN_VAULT_BOX_ACTION:
        game.open_vault_box()
    elif action == LIGHT_ACTION:
        game.light()
    elif action == INSTALL_LEVER_ACTION:
        game.install_lever()
    elif action == INSERT_DISK_ACTION:
        game.insert_disk()
    elif CHOOSE_UPGRADE_BASE <= action < CHOOSE_UPGRADE_BASE + 3:
        game.choose_upgrade(action - CHOOSE_UPGRADE_BASE)
    elif TRAVEL_BASE <= action < OPEN_SIGIL_DOOR_BASE:
        node_ids = _build_area_node_ids(game.registry)
        node_id = node_ids[action - TRAVEL_BASE]
        game.travel_to(node_id)
        # A grid walk inside travel_to can end the day; caller must check phase.
    elif OPEN_SIGIL_DOOR_BASE <= action < START_SETUP_ACTION:
        realm = _si.SIGIL_REALMS[action - OPEN_SIGIL_DOOR_BASE]
        game.open_sigil_door(realm)
    elif action == START_SETUP_ACTION:
        game.start_setup()
    elif EXP_TRIGGER_BASE <= action < EXP_EFFECT_BASE:
        game.choose_experiment_trigger(action - EXP_TRIGGER_BASE)
    elif EXP_EFFECT_BASE <= action < TOGGLE_EXPERIMENT_ACTION:
        game.choose_experiment_effect(action - EXP_EFFECT_BASE)
    elif action == TOGGLE_EXPERIMENT_ACTION:
        game.toggle_experiment()
    elif CHOOSE_COLOUR_BASE <= action < DONATE_BASE:
        game.choose_colour(COLOUR_CATEGORIES[action - CHOOSE_COLOUR_BASE])
    elif DONATE_BASE <= action < TAKE_BACK_OFFERING_ACTION:
        blessing_idx, duration_idx = divmod(action - DONATE_BASE, _N_SHRINE_DURATIONS)
        game.donate_shrine(blessing_idx, duration_idx)
    elif action == TAKE_BACK_OFFERING_ACTION:
        game.take_back_shrine_offering()
    elif action == BERRY_PICK_ACTION:
        game.berry_pick()
    elif action == TAKE_GROTTO_CHIP_ACTION:
        game.take_grotto_chip()
    elif CROWN_BLOCK_BASE <= action < AXE_TARGET_BASE:
        game.crown_block(action - CROWN_BLOCK_BASE)
    elif AXE_TARGET_BASE <= action < LOCK_MENU_BASE:
        target_ids = _build_axe_target_ids(game.registry)
        game.axe_room(target_ids[action - AXE_TARGET_BASE])
    elif action == LOCK_USE_KEY_ACTION:
        game.use_key_at_lock()
    elif action == LOCK_LOCKPICK_ACTION:
        game.lockpick_at_lock()
    elif action == LOCK_ABANDON_ACTION:
        game.abandon_lock()
    elif LOCK_SPECIAL_KEY_BASE <= action < REWIND_ACTION:
        key_id = _build_lock_special_key_order(game.registry)[action - LOCK_SPECIAL_KEY_BASE]
        game.use_special_key_at_lock(key_id)
    elif action == REWIND_ACTION:
        game.rewind()
    elif WRENCH_RARITY_BASE <= action < USE_TELESCOPE_PLANETARIUM_ACTION:
        game.set_wrench_rarity(action - WRENCH_RARITY_BASE)
    elif action == USE_TELESCOPE_PLANETARIUM_ACTION:
        game.use_telescope_planetarium()
    elif ACTIVATE_CONSTELLATION_BASE <= action < VIEW_NIGHT_SKY_ACTION:
        game.activate_constellation(action - ACTIVATE_CONSTELLATION_BASE)
    elif action == VIEW_NIGHT_SKY_ACTION:
        game.view_night_sky()
    elif action == REDRAW_WITH_STAR_ACTION:
        game.redraw(RedrawKind.STAR)
    elif PUMP_SOURCE_BASE <= action < PUMP_LEVEL_BASE:
        source_ids = _build_pump_source_ids(game.registry)
        game.set_pump_source(source_ids[action - PUMP_SOURCE_BASE])
    elif PUMP_LEVEL_BASE <= action < SPREAD_GOLD_ACTION:
        game.set_pump_level(action - PUMP_LEVEL_BASE)
    elif action == SPREAD_GOLD_ACTION:
        game.spread_gold()
    elif action == RUN_PAYROLL_ACTION:
        game.run_payroll()
    else:
        raise ValueError(f"unimplemented action {action}")


def _cell_name(cell: int) -> str:
    return f"r{cell // 5 + 1}c{cell % 5}"


def _room_name_at(game: Game, cell: int) -> str | None:
    """Name of the room placed at ``cell``, or None when there isn't one.

    None covers both the off-grid sentinel (``cell < 0``, e.g. an outer-room
    draft's ``from_cell``) and an on-grid cell whose room slot is empty
    (``grid[cell] < 0`` -- defensive; a doorway's source cell should always
    be occupied, but this mirrors the guard ``describe_action``'s ``move_to``
    branch already applies).
    """
    if cell < 0:
        return None
    idx = game.state.grid[cell]
    if idx < 0:
        return None
    return game.registry.rooms[idx].name


def describe_action(game: Game, action: int) -> str:
    """Concise human-readable form of ``action`` in the CURRENT (pre-step) state."""
    if action < CHOOSE_BASE:
        cell, dir_idx = divmod(action, 4)
        room_name = _room_name_at(game, cell)
        src = f"{room_name} ({_cell_name(cell)})" if room_name is not None else _cell_name(cell)
        return f"draft {DIR_NAMES[DIRS[dir_idx]]} door from {src}"
    if action < REDRAW_ACTION:
        slot = action - CHOOSE_BASE
        pending = game.state.pending
        if pending is not None and slot < len(pending.options):
            opt = pending.options[slot]
            name = "???" if opt.hidden else game.registry.rooms[opt.room_idx].name
            return f"choose #{slot + 1} {name}"
        return f"choose #{slot + 1}"
    if action == REDRAW_ACTION:
        return "redraw"
    if action == OUTER_DRAFT_ACTION:
        return "outer draft"
    if action == TOGGLE_POWER_ACTION:
        state = "off" if game.state.keycard_power_on else "on"
        return f"turn keycard power {state}"
    if action == TOGGLE_DARKROOM_ACTION:
        state = "off" if game.state.darkroom_lights_on else "on"
        return f"turn Darkroom lights {state}"
    if SET_LEVEL_BASE <= action < SET_LEVEL_BASE + len(SECURITY_LEVELS):
        return f"set security level {SECURITY_LEVELS[action - SET_LEVEL_BASE]}"
    if action == ROTATE_ACTION:
        return "rotate options"
    if MOVE_TO_BASE <= action < MOVE_TO_BASE + N_CELLS:
        cell = action - MOVE_TO_BASE
        idx = game.state.grid[cell]
        into = f" -> {game.registry.rooms[idx].name}" if idx >= 0 else ""
        return f"go to {_cell_name(cell)}{into}"
    if BUY_BASE <= action < TRADE_BASE:
        i = action - BUY_BASE
        stock = game.shop_stock()
        if stock is not None and i < len(stock):
            entry = stock[i]
            return f"buy {entry['id']} ({entry['price']}g)"
        return f"buy slot {i}"
    if TRADE_BASE <= action < FABRICATE_BASE:
        i = action - TRADE_BASE
        offers = game.trade_offers()
        if i < len(offers):
            o = offers[i]
            return f"trade {o['give']} -> {o['receive']}"
        return f"trade offer {i}"
    if FABRICATE_BASE <= action < SCEPTER_BASE:
        i = action - FABRICATE_BASE
        fab = game.registry.special.fabrication
        if i < len(fab):
            return f"fabricate {fab[i][1]}"
        return f"fabricate recipe {i}"
    if SCEPTER_BASE <= action < SMASH_VASE_ACTION:
        color = _shops.SCEPTER_COLORS[action - SCEPTER_BASE]
        return f"scepter: {color}"
    if action == SMASH_VASE_ACTION:
        return "smash the vase"
    if action == OPEN_CONTAINER_ACTION:
        return "open container"
    if action == OPEN_CAR_TRUNK_ACTION:
        return "open car trunk"
    if action == OPEN_VAULT_BOX_ACTION:
        return "open vault deposit box"
    if action == LIGHT_ACTION:
        return "light ignition target"
    if action == INSTALL_LEVER_ACTION:
        return "install broken lever"
    if action == INSERT_DISK_ACTION:
        return "insert upgrade disk"
    if CHOOSE_UPGRADE_BASE <= action < CHOOSE_UPGRADE_BASE + 3:
        i = action - CHOOSE_UPGRADE_BASE
        opts = game.state.pending_upgrade_options
        variant = opts[i] if i < len(opts) else "?"
        return f"choose upgrade #{i} ({variant})"
    if TRAVEL_BASE <= action < OPEN_SIGIL_DOOR_BASE:
        node_ids = _build_area_node_ids(game.registry)
        node_id = node_ids[action - TRAVEL_BASE]
        node = game.registry.area_graph.nodes.get(node_id)
        name = node.name if node is not None else node_id
        result = game.area_route_cost(node_id)
        cost = result[0] if result is not None else "?"
        return f"travel to {name} ({cost} steps)"
    if OPEN_SIGIL_DOOR_BASE <= action < START_SETUP_ACTION:
        realm = _si.SIGIL_REALMS[action - OPEN_SIGIL_DOOR_BASE]
        return f"open Sigil Chamber door: {realm.replace('_', ' ').title()}"
    if action == START_SETUP_ACTION:
        return "operate Experimental Setup terminal"
    if EXP_TRIGGER_BASE <= action < EXP_EFFECT_BASE:
        i = action - EXP_TRIGGER_BASE
        offered = game.state.experiment.offered_triggers
        text = game.registry.experiments.trigger_by_id[offered[i]].text if i < len(offered) else "?"
        return f"choose experiment trigger #{i}: {text}"
    if EXP_EFFECT_BASE <= action < TOGGLE_EXPERIMENT_ACTION:
        i = action - EXP_EFFECT_BASE
        offered = game.state.experiment.offered_effects
        text = game.registry.experiments.effect_by_id[offered[i]].text if i < len(offered) else "?"
        return f"choose experiment effect #{i}: {text}"
    if action == TOGGLE_EXPERIMENT_ACTION:
        return "resume experiment" if game.state.experiment.paused else "pause experiment"
    if CHOOSE_COLOUR_BASE <= action < DONATE_BASE:
        colour = COLOUR_CATEGORIES[action - CHOOSE_COLOUR_BASE]
        return f"choose colour: {colour}"
    if DONATE_BASE <= action < TAKE_BACK_OFFERING_ACTION:
        blessing_idx, duration_idx = divmod(action - DONATE_BASE, _N_SHRINE_DURATIONS)
        r = _shrine.rules(game)
        if blessing_idx < len(r.blessings) and duration_idx < len(r.bands):
            blessing = r.blessings[blessing_idx]
            days = r.bands[duration_idx].duration_days
            cost = blessing.costs[duration_idx]
            return f"donate {cost}g: {blessing.name} ({days} days)"
        return f"donate slot {blessing_idx}/{duration_idx}"
    if action == TAKE_BACK_OFFERING_ACTION:
        return "take back Shrine offering"
    if action == BERRY_PICK_ACTION:
        return "pick a berry"
    if action == TAKE_GROTTO_CHIP_ACTION:
        return "take the Grotto pedestal chip"
    if CROWN_BLOCK_BASE <= action < AXE_TARGET_BASE:
        slot = action - CROWN_BLOCK_BASE
        pending = game.state.pending
        if pending is not None and slot < len(pending.options):
            name = game.registry.rooms[pending.options[slot].room_idx].name
            return f"filter #{slot + 1} {name} (Crown of the Blueprints)"
        return f"filter #{slot + 1} (Crown of the Blueprints)"
    if AXE_TARGET_BASE <= action < LOCK_MENU_BASE:
        target_ids = _build_axe_target_ids(game.registry)
        target_id = target_ids[action - AXE_TARGET_BASE]
        room = game.registry.by_id.get(target_id)
        name = room.name if room is not None else target_id
        return f"axe {name} (The Axe)"
    if action == LOCK_USE_KEY_ACTION:
        return "use a key"
    if action == LOCK_LOCKPICK_ACTION:
        return "pick the lock"
    if action == LOCK_ABANDON_ACTION:
        return "abandon (leave the door locked)"
    if LOCK_SPECIAL_KEY_BASE <= action < REWIND_ACTION:
        key_id = _build_lock_special_key_order(game.registry)[action - LOCK_SPECIAL_KEY_BASE]
        item = game.registry.special.by_id.get(key_id)
        name = item.name if item is not None else key_id
        return f"use special key: {name}"
    if action == REWIND_ACTION:
        return "rewind last draft (Chronograph)"
    if WRENCH_RARITY_BASE <= action < USE_TELESCOPE_PLANETARIUM_ACTION:
        rarity = RARITIES[action - WRENCH_RARITY_BASE]
        return f"set Gear Wrench rarity: {rarity}"
    if action == USE_TELESCOPE_PLANETARIUM_ACTION:
        return "use Telescope in Planetarium"
    if ACTIVATE_CONSTELLATION_BASE <= action < VIEW_NIGHT_SKY_ACTION:
        record = game.registry.constellations.records[action - ACTIVATE_CONSTELLATION_BASE]
        return f"activate constellation: {record.name}"
    if action == VIEW_NIGHT_SKY_ACTION:
        return "view the night sky"
    if action == REDRAW_WITH_STAR_ACTION:
        return "redraw the hand for 1 star (Ink Well)"
    if PUMP_SOURCE_BASE <= action < PUMP_LEVEL_BASE:
        source_id = _build_pump_source_ids(game.registry)[action - PUMP_SOURCE_BASE]
        return f"Pump Room: select source {source_id}"
    if PUMP_LEVEL_BASE <= action < SPREAD_GOLD_ACTION:
        level = action - PUMP_LEVEL_BASE
        source_id = game.state.pending_pump_source or "?"
        return f"Pump Room: set {source_id} to level {level}"
    if action == SPREAD_GOLD_ACTION:
        return "Office: Spread Gold in Estate"
    if action == RUN_PAYROLL_ACTION:
        return "Office: Run Payroll"
    return f"action {action}"
