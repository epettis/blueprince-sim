"""Flat action space with masking.

Navigation is macro-based: the agent picks a destination (a frontier doorway
to draft, or a room to enter) and the engine walks the shortest connected
path, paying the normal one-step-per-room cost. Re-entering rooms grants
nothing, so free-form single-tile moves were retired.

Layout (Discrete(327)):
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
"""

from __future__ import annotations

from ..engine.game import Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES, DIRS, N_CELLS, rank_of
from ..engine.locks import DOOR_LOCKED, DOOR_SEALED, DOOR_SECURITY, SECURITY_LEVELS
from ..engine import shops as _shops
from ..engine import special_items as _si
from ..engine.effects import Capability, provides_capability
from ..engine.model import Registry

# ---------------------------------------------------------------------------
# Area-graph node ordering (derived from registry; never hand-maintained)
# ---------------------------------------------------------------------------

def _build_area_node_ids(registry: Registry) -> tuple[str, ...]:
    """Sorted tuple of area-graph node ids, alphabetical for determinism.

    The ordering is derived from registry.area_graph so it cannot drift from
    areas.json. The action index for a node is TRAVEL_BASE + the index here.
    Both the action space and the observation encoder use this single source.
    """
    return tuple(sorted(registry.area_graph.nodes.keys()))


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

# N_AREA_NODES: one travel slot per area-graph node. Asserted by tests via
# mask length, not a literal comparison.
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

# N_ACTIONS = first slot after the experiments block.
N_ACTIONS = TOGGLE_EXPERIMENT_ACTION + 1  # 326 + 1 = 327

DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


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
    req = target_cfg.get("requires_item")
    if req is not None and st.inventory.get(req, 0) <= 0:
        return False
    return True


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


def _cell_worth_entering(game: Game, cell: int) -> bool:
    """True when walking into ``cell`` accomplishes something (purposefulness gate).

    An unentered cell is always worth entering (first-entry pickups). An
    already-entered cell is worth entering only when it is a control room
    (Utility Closet / Security -- gated on ``game.cfg.door_locks``, since
    their switches only matter with door locking enabled) or one of the
    re-entry extensions: a buyable shop/Workshop, a Dining Room with a
    pending main course, an openable container, an openable vault deposit
    box, an unlit ignition target with a tool in hand, or a machine room
    with a broken_lever in hand.

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
            or _cell_has_machine(game, cell))


def action_mask(game: Game, prev_action: int | None = None) -> list[bool]:
    """Legality mask over the flat action space for the current phase.

    NAVIGATE off-grid (``game.off_grid``) permits only outer-area actions.
    On-grid NAVIGATE permits frontier drafts that arrive with a step (and,
    behind locked doors, a key) to spare, walks to unentered rooms and the
    control rooms, and the outer-draft/switch actions. DRAFTING permits
    affordable slots plus redraw/rotate when available. TERMINAL masks
    everything off.

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
        else:
            dist = game.distance_map()
            key_cost = game.key_cost_map()
            # Draft any reachable, openable frontier doorway; arriving must
            # leave >= 1 step (so the drafted room can still be entered) and,
            # for locked doorways, a key beyond those the walk itself spends.
            for cell, d in game.frontier_doorways():
                if not 0 <= dist[cell] <= st.steps - 1:
                    continue
                seg = game.door_state_of(cell, d)
                if seg == DOOR_SEALED:
                    continue  # sealed: no action can open it
                if seg == DOOR_LOCKED and st.keys < key_cost[cell] + game.lock_open_cost(cell, d):
                    continue
                if seg == DOOR_SECURITY and not game.security_openable():
                    continue
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
            if game.can_set_security_level():
                for i, level in enumerate(SECURITY_LEVELS):
                    if level != st.security_level:
                        mask[SET_LEVEL_BASE + i] = True
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
    # Security-setpoint repeat guard: if the last applied action was a
    # set-level id, mask all three off so the agent must do something else
    # before touching the setpoint again.
    if prev_action is not None and SET_LEVEL_BASE <= prev_action < SET_LEVEL_BASE + 3:
        for i in range(3):
            mask[SET_LEVEL_BASE + i] = False
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
    return f"action {action}"
