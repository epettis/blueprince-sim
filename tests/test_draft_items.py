"""Draft-side special-item behavior: compass unification, paper crown, knight's shield,
silver key, Crown of the Blueprints, placement-condition gates from held
items, and the Battery Pack's deferred Dynamic Rarity flip/toggle.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items
from blueprince_sim.engine.draft import COLOUR_CATEGORIES, DraftContext, redeal, room_draftable
from blueprince_sim.engine.effects.items import crown_of_the_blueprints as cob
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.locks import DOOR_LOCKED, segment_key
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DraftOption, GameState


# ----------------------------------------------------------------------- helpers

def _game(registry, items=(), seed=1, **cfg_kw) -> Game:
    """Create a Game with ``items`` pre-granted via starting_items."""
    return Game(GameConfig(starting_items=frozenset(items), **cfg_kw),
                seed=seed, registry=registry)


def _force_locked(g: Game, cell: int, direction: int) -> None:
    """Force a doorway segment to DOOR_LOCKED and bump the version cache."""
    g.state.door_state[segment_key(cell, direction)] = DOOR_LOCKED
    g.state.door_version += 1


# ---------------------------------------------------------------- compass_active

def test_compass_active_via_held_compass(registry):
    """compass_active returns True when the Compass item is held, even without the config flag."""
    g = _game(registry, items=("compass",))
    assert special_items.compass_active(g)


def test_compass_active_via_electromagnet(registry):
    """compass_active returns True when the Powered Electromagnet is held (it carries the compass tag)."""
    g = _game(registry, items=("powered_electromagnet",))
    assert special_items.compass_active(g)


def test_compass_active_false_without_item_or_flag(registry):
    """compass_active is False when neither the config flag nor any compass item is held."""
    g = _game(registry)
    assert not special_items.compass_active(g)


def test_compass_active_via_config_flag(registry):
    """compass_active returns True when the config flag is set, regardless of inventory."""
    g = _game(registry, compass=True)
    assert special_items.compass_active(g)


def _dealt_north_doors(registry, items, n=300):
    """Across n seeds, how many dealt options carry a north door (of total dealt).

    The compass only changes the orientation roll, not which rooms are dealt,
    so runs over the same seeds differ only in orientations.
    """
    north = total = 0
    for seed in range(1, n + 1):
        g = _game(registry, items=items, seed=seed)
        g.state.steps = 100
        pending = g.open_door(2, N)  # Entrance Hall north door
        for o in pending.options:
            total += 1
            if o.orientation & N:
                north += 1
    return north, total


def test_orientation_roll_north_biased_with_held_compass(registry):
    """Holding the Compass ITEM (no config flag) shifts the draw-time orientation
    roll toward north-facing doors, same as cfg.compass would."""
    plain_north, total = _dealt_north_doors(registry, items=())
    item_north, _ = _dealt_north_doors(registry, items=("compass",))
    # The datamined Compass column flips the south bias hard; over 900 dealt
    # options the gap is wide (measured ~207 vs ~334), so a 15% margin is safe.
    assert item_north > plain_north * 1.15


def test_ornate_compass_active_via_held_item(registry):
    """ornate_compass_active returns True when the Ornate Compass is held."""
    g = _game(registry, items=("ornate_compass",))
    assert special_items.ornate_compass_active(g)


def test_ornate_compass_inactive_without_item(registry):
    """ornate_compass_active is False when neither config flag nor item is present."""
    g = _game(registry)
    assert not special_items.ornate_compass_active(g)


# ------------------------------------------------------------------ paper crown

def test_paper_crown_grants_extra_redraw_on_nonred_hand(registry):
    """Paper Crown grants +1 redraws_left on the initial deal when no option is red.

    The redraws_left baseline is 0 (outside a Classroom); Crown adds 1 when the
    entire dealt hand is free of red-category rooms.
    """
    # Run multiple seeds until we get one with no red option in the hand
    for seed in range(1, 200):
        g = _game(registry, items=("paper_crown",), seed=seed)
        g.state.steps = 100
        # Entrance Hall is at cell 2 (rank 1, col 2), open north door
        doors = g.open_doorways()
        if not doors:
            continue
        cell, direction = doors[0]
        pending = g.open_door(cell, direction)
        has_red = any(g.registry.rooms[o.room_idx].category == "red"
                      for o in pending.options if not o.hidden)
        has_hidden = any(o.hidden for o in pending.options)
        if not has_red and not has_hidden:
            assert pending.redraws_left == 1, (
                f"seed={seed}: expected 1 redraw from Paper Crown, got {pending.redraws_left}")
            return
    raise AssertionError("could not find a non-red, non-hidden hand in 200 seeds")


def test_paper_crown_no_bonus_when_red_option_present(registry):
    """Paper Crown gives no extra redraw when at least one option is a red room."""
    # Run multiple seeds to find a hand containing a red option
    for seed in range(1, 500):
        g = _game(registry, items=("paper_crown",), seed=seed)
        g.state.steps = 100
        doors = g.open_doorways()
        if not doors:
            continue
        cell, direction = doors[0]
        pending = g.open_door(cell, direction)
        has_red = any(g.registry.rooms[o.room_idx].category == "red"
                      for o in pending.options)
        if has_red:
            assert pending.redraws_left == 0, (
                f"seed={seed}: Crown should not fire when red option exists")
            return
    raise AssertionError("could not find a hand with a red option in 500 seeds")


# --------------------------------------------------------------- knight's shield

def test_knights_shield_negates_first_red_room_penalty(registry):
    """Knight's Shield auto-negates the first negative red-room effect each day;
    the shield_used flag is set and the second red-room effect applies normally.
    """
    g = _game(registry, items=("knights_shield",))
    g.state.steps = 50

    # Find the Gymnasium (category=red, grants -2 steps on entry)
    gym = registry.by_id.get("gymnasium")
    assert gym is not None, "gymnasium not found in registry"

    from blueprince_sim.engine import effects
    from blueprince_sim.engine.effects import Hook

    # First red room: shield should fire and block the step loss
    before = g.state.steps
    effects.fire(g, gym, Hook.ON_ENTER)
    assert g.state.steps == before, "Shield should have negated the first step loss"
    assert g.state.special.shield_used, "shield_used flag must be set after first fire"

    # Second red room: no shield left, normal penalty applies
    before2 = g.state.steps
    effects.fire(g, gym, Hook.ON_ENTER)
    assert g.state.steps < before2, "Second red-room penalty must apply (shield spent)"


def test_knights_shield_not_used_without_item(registry):
    """Without the Knight's Shield, red-room penalties apply immediately."""
    g = _game(registry)
    g.state.steps = 50
    gym = registry.by_id.get("gymnasium")

    from blueprince_sim.engine import effects
    from blueprince_sim.engine.effects import Hook

    before = g.state.steps
    effects.fire(g, gym, Hook.ON_ENTER)
    assert g.state.steps < before, "Penalty must apply when shield is not held"
    assert not g.state.special.shield_used


# ------------------------------------------------------------------- silver key

def test_silver_key_consumed_and_sets_draft_flag_on_locked_door(registry):
    """Opening a locked frontier door for drafting while holding the Silver Key
    consumes the key (not a regular key) and sets silver_key_draft=True.
    """
    g = _game(registry, items=("silver_key",), seed=1, door_locks=True)
    g.state.steps = 100
    g.state.keys = 0  # no regular keys; silver key must cover it

    # Force the north door of the Entrance Hall to be locked
    _force_locked(g, 2, N)

    assert special_items.has(g.state, "silver_key")
    g.open_door(2, N)

    assert not special_items.has(g.state, "silver_key"), "Silver Key must be consumed"
    assert g.state.keys == 0, "No regular key should have been spent"


def test_silver_key_draft_flag_cleared_after_deal(registry):
    """silver_key_draft is False after the initial hand is dealt."""
    g = _game(registry, items=("silver_key",), seed=1, door_locks=True)
    g.state.steps = 100

    _force_locked(g, 2, N)
    g.open_door(2, N)

    assert not g.state.special.silver_key_draft, (
        "silver_key_draft must be cleared after the initial deal")


def test_silver_key_hand_biased_toward_cross_t(registry):
    """A hand dealt through a Silver-Key-opened door is all cross/t layouts
    (the entrance's rank-2 interior target always has qualifying cards), while
    normal deals at the same doorway mix in other shapes.
    """
    cross_t_count_normal = 0
    total = 30

    for seed in range(1, total + 1):
        # With silver key: locked door — every dealt option must be cross/t
        g = _game(registry, items=("silver_key",), seed=seed, door_locks=True)
        g.state.steps = 100
        _force_locked(g, 2, N)
        pending = g.open_door(2, N)
        assert pending.options, f"seed={seed}: empty hand"
        for o in pending.options:
            assert registry.rooms[o.room_idx].layout in ("cross", "t"), (
                f"seed={seed}: non-cross/t {registry.rooms[o.room_idx].id} in silver-key hand")

        # Normal (no silver key, unlocked door): count cross/t for contrast
        g2 = _game(registry, seed=seed, door_locks=False)
        g2.state.steps = 100
        pending2 = g2.open_door(2, N)
        cross_t_count_normal += sum(
            1 for o in pending2.options
            if registry.rooms[o.room_idx].layout in ("cross", "t"))

    # Sanity: the normal deal is NOT all cross/t, so the property above is the bias.
    assert cross_t_count_normal < total * 3


# ------------------------------------------------------------------- dig spots

def test_courtyard_dig_spot_dug_exactly_once(registry):
    """A shovel-holder auto-digs the Courtyard's dig spot (new wiki-sourced data)
    on arrival, and a repeat arrival never re-digs it."""
    g = _game(registry, items=("shovel",))
    court = registry.by_id["courtyard"]
    assert court.items.dig_spots == 1  # observable premise: the spot exists
    cell = 22
    g.state.grid[cell] = court.idx

    special_items.dig_all(g, cell)
    assert g.state.special.dug.get(cell, 0) == 1

    log_len = len(g.state.items_found_log)
    special_items.dig_all(g, cell)  # re-arrival: nothing new dug or granted
    assert g.state.special.dug.get(cell, 0) == 1
    assert len(g.state.items_found_log) == log_len


# ------------------------------------------------------------------ battery pack

def test_battery_pack_pickup_records_pending_without_touching_decks(registry):
    """Picking up the Battery Pack only increments the pending-trigger counter;
    it must not itself touch dynamic_rarity or move any deck cards, since the
    50/50 is deferred to the next deal (grant() has no rng in scope)."""
    g = _game(registry, seed=3)
    before = [list(d.order) for d in g.state.decks]
    special_items.grant(g.state, g.registry, "battery_pack", source="test")
    assert g.state.special.battery_pack_pending == 1
    assert g.state.dynamic_rarity == {}
    assert [list(d.order) for d in g.state.decks] == before


def test_battery_pack_first_deal_moves_workshop_cards_and_drains_pending(registry):
    """After the first hand is dealt following pickup, the Workshop's cards sit
    in the chosen rarity's deck and the pending counter is back to 0 -- pins
    that Game._deal_and_cache's resolve_battery_pack call actually fires.

    Seed 2 is pinned because it draws index 0 ("standard") on the
    "battery_pack_rarity" substream -- a bucket that differs from the
    Workshop's own static "unusual" rarity, so the move is observable.
    """
    workshop = registry.by_id["workshop"]
    g = _game(registry, items=("battery_pack",), seed=2)
    assert g.state.special.battery_pack_pending == 1
    g.state.steps = 100
    doors = g.open_doorways()
    cell, direction = doors[0]
    g.open_door(cell, direction)

    assert g.state.special.battery_pack_pending == 0
    assert g.state.dynamic_rarity == {"workshop": 1}  # 1 == standard
    standard_deck = g.state.deck(1, not workshop.is_free)
    unusual_deck = g.state.deck(workshop.rarity_idx, not workshop.is_free)
    assert workshop.idx in standard_deck.order
    assert workshop.idx not in unusual_deck.order


def test_battery_pack_landing_on_static_bucket_is_a_noop(registry):
    """When the flip picks the Workshop's own static rarity (Unusual), the
    resolution is a documented no-op: dynamic_rarity stays empty and no card
    moves -- the "roughly half of all firings are free" property from
    set_dynamic_rarity's own idempotency guard.

    Seed 0 is pinned because it draws index 1 ("unusual") on the
    "battery_pack_rarity" substream, matching the Workshop's own rarity.
    """
    workshop = registry.by_id["workshop"]
    assert workshop.rarity == "unusual"  # premise: static bucket is Unusual
    g = _game(registry, items=("battery_pack",), seed=0)
    before = [list(d.order) for d in g.state.decks]
    g.state.steps = 100
    doors = g.open_doorways()
    cell, direction = doors[0]
    g.open_door(cell, direction)

    assert g.state.special.battery_pack_pending == 0
    assert g.state.special.battery_pack_last_rarity == 1  # unusual chosen
    assert g.state.dynamic_rarity == {}  # no override recorded: no-op
    assert [list(d.order) for d in g.state.decks] == before  # no card moved


def test_battery_pack_second_pickup_same_day_toggles_to_the_other_option(registry):
    """The wiki rule the item's own notes omit: a second (or later) trigger in
    the same day does not re-roll -- it deterministically switches to the
    other option. Reachable despite unique=True because grant() only blocks a
    re-grant while the item is currently held (fabricating it away frees the
    next grant), mirrored here with remove(consumed=True)."""
    g = _game(registry, items=("battery_pack",), seed=2)
    special_items.resolve_battery_pack(g)
    first_choice = g.state.special.battery_pack_last_rarity
    assert first_choice != -1  # premise: the first trigger actually resolved

    # Fabricate the pack away (consumed=True, same as shops.fabricate does),
    # then a second pickup -- unique=True does not block it since it is no
    # longer held.
    special_items.remove(g.state, "battery_pack", consumed=True)
    special_items.grant(g.state, g.registry, "battery_pack", source="test")
    assert g.state.special.battery_pack_pending == 1
    special_items.resolve_battery_pack(g)

    options = g.registry.special.battery_pack["options"]
    second_choice = g.state.special.battery_pack_last_rarity
    assert second_choice == (first_choice + 1) % len(options)


def test_battery_pack_first_trigger_is_roughly_uniform_over_seeds(registry):
    """The first trigger of the day is a genuine 50/50, checked as a
    proportion over many seeds (not a chi-square -- that machinery already
    lives in test_draft_stats.py and this suite must not duplicate it)."""
    n = 200
    standard_count = 0
    for seed in range(n):
        g = _game(registry, seed=seed)
        special_items.grant(g.state, g.registry, "battery_pack", source="test")
        special_items.resolve_battery_pack(g)
        if g.state.special.battery_pack_last_rarity == 0:
            standard_count += 1
    proportion = standard_count / n
    assert 0.35 < proportion < 0.65, f"proportion choosing 'standard': {proportion}"


def test_battery_pack_pickup_fires_via_container_grant_path(registry):
    """The deferred pickup effect fires identically through a non-spawn grant
    path (special_items._apply_grant's "item" case, the same one containers
    use), proving the deferral to resolve_battery_pack is path-independent
    rather than something only the spawn pipeline triggers."""
    g = _game(registry, seed=5)
    tag = special_items._apply_grant(
        g.state, g.registry, g, {"kind": "item", "id": "battery_pack"})
    assert tag == "battery_pack"
    assert g.state.special.battery_pack_pending == 1


def test_battery_pack_resolution_is_deterministic_for_a_fixed_seed(registry):
    """Two independent games built from the identical seed resolve the same
    rarity choice -- the determinism every rng-consuming feature in this
    engine must hold, since golden transcripts depend on it."""
    def _resolve(seed: int) -> int:
        g = _game(registry, seed=seed)
        special_items.grant(g.state, g.registry, "battery_pack", source="test")
        special_items.resolve_battery_pack(g)
        return g.state.special.battery_pack_last_rarity

    assert _resolve(7) == _resolve(7)
# ------------------------------------------------------------- crown of the blueprints

def _force_red_slot0(g: Game, cell: int = 2, direction: int = N):
    """Open a real doorway (so the pending hand's cell/direction/colour are
    correctly scoped for a later redeal), then overwrite slot 0 with a known
    Red Room, deterministically -- no seed-hunting for a hand that happens
    to contain one. ``pool == "base"`` so the room is an actual deck member
    (not an upgrade_variant, which only ever gets injected into a deck once
    its base room is upgraded) -- load-bearing for deck-composition tests."""
    pending = g.open_door(cell, direction)
    red = next(r for r in g.registry.rooms
              if r.is_category("red") and r.rarity is not None and r.pool == "base")
    pending.options[0] = DraftOption(room_idx=red.idx, orientation=red.door_mask,
                                     gem_cost=0, slot=0)
    return pending, red


def test_room_draftable_denies_crown_blocked_room_unconditionally(registry, cfg):
    """A crown-blocked room fails room_draftable even for an ordinary
    (non-colour-selective) draft -- the base case the colour-exemption test
    below builds on."""
    gym = registry.by_id["gymnasium"]  # category=='red' literally, no colour trick needed
    state = GameState()
    ctx = DraftContext(state, registry, cfg, Rng(0), set(), None)
    assert room_draftable(ctx, gym, 12, N, set()), "sanity: unblocked gym must be draftable"
    state.special.crown_blocked_rooms.append(gym.id)
    assert not room_draftable(ctx, gym, 12, N, set())


def test_room_draftable_denies_crown_blocked_aquarium_under_every_colour(registry, cfg):
    """Owner ruling 2026-08-12: the Crown's filter has NO colour exemption.
    The Aquarium normally passes room_draftable's colour gate for all five
    colours (Room.is_category matches every one); once crown-blocked it must
    fail for every one of them too -- the wiki's claim that colour-selective
    drafts (and, by the same mechanism, the Silver Key/Prism Key) stay
    exempt is what this pins as wrong. This is the assertion the brief flags
    as most likely to be gotten wrong.
    """
    aquarium = registry.by_id["aquarium"]
    for colour in COLOUR_CATEGORIES:
        state = GameState()
        ctx = DraftContext(state, registry, cfg, Rng(0), set(), None, colour=colour)
        assert room_draftable(ctx, aquarium, 12, N, set()), (
            f"sanity: unblocked aquarium must be draftable under colour={colour}")
        state.special.crown_blocked_rooms.append(aquarium.id)
        assert not room_draftable(ctx, aquarium, 12, N, set()), (
            f"crown block was not enforced under colour={colour}")


def test_crown_blocked_room_never_dealt_across_many_colour_selective_redeals(registry, cfg):
    """End-to-end version of the ruling-1 guarantee: with the Aquarium
    crown-blocked, 30 successive colour='red' redeals of the same Secret
    Passage hand (one fixed seed, not a seed hunt) never include it -- every
    slot instead falls back to another red-category room or the Closet."""
    g = Game(cfg, seed=1, registry=registry)
    secret_passage = registry.by_id["secret_passage"]
    g._place_room(secret_passage, 7, N | S)
    g.state.pos = 7
    g.state.steps = 100
    g.state.special.crown_blocked_rooms.append("aquarium")
    g.open_door(7, N)
    assert g.phase is Phase.COLOUR_PENDING
    pending = g.choose_colour("red")
    for _ in range(30):
        redeal(g.state, g.registry, g.cfg, g.rng, g.placed_ids, pending)
        dealt_ids = {g.registry.rooms[o.room_idx].id for o in pending.options}
        assert "aquarium" not in dealt_ids


def test_block_offered_gates_on_item_tag_hand_use_and_red_category(registry):
    """crown_of_the_blueprints.block_offered's four independent gates: the
    item must be held, its data record must still carry the tag, the
    filter must not already be spent this hand, and the room must be Red."""
    state = GameState()
    gym = registry.by_id["gymnasium"]
    closet = registry.by_id["closet"]
    assert not cob.block_offered(state, registry, gym), "no item held"
    state.inventory[cob.ITEM_ID] = 1
    assert cob.block_offered(state, registry, gym)
    assert not cob.block_offered(state, registry, closet), "closet is not a Red Room"
    state.special.crown_block_used = True
    assert not cob.block_offered(state, registry, gym), "already spent this hand"


def test_crown_block_grants_gem_and_records_the_blocked_room(registry):
    """Game.crown_block grants exactly 1 gem and appends the drafted room's
    id to crown_blocked_rooms."""
    g = _game(registry, items=("crown_of_the_blueprints",), seed=1)
    g.state.steps = 100
    pending, red = _force_red_slot0(g)
    gems_before = g.state.gems
    assert g.can_crown_block(0)
    g.crown_block(0)
    assert g.state.gems == gems_before + 1
    assert g.state.special.crown_blocked_rooms == [red.id]


def test_crown_block_redeals_the_hand_and_never_redeals_the_blocked_room(registry):
    """crown_block redeals the whole hand (Game.redraw's own path, reused),
    and -- since the block is recorded before the redeal runs -- the just-
    blocked room can never reappear in the freshly dealt hand."""
    g = _game(registry, items=("crown_of_the_blueprints",), seed=2)
    g.state.steps = 100
    pending, red = _force_red_slot0(g)
    g.crown_block(0)
    assert pending.options, "the redeal must still produce a hand"
    assert all(g.registry.rooms[o.room_idx].id != red.id for o in pending.options)


def test_crown_block_never_removes_a_card_from_any_deck(registry):
    """Deck sizes (order length, every rarity x free/gem deck) are bit-for-
    bit identical before and after crown_block -- pinning 'filter, not
    removal', since a removal would change deck sizes and therefore which
    rarities rarity_deck_ok allows for the rest of the day."""
    g = _game(registry, items=("crown_of_the_blueprints",), seed=3)
    g.state.steps = 100
    pending, red = _force_red_slot0(g)
    sizes_before = [d.size() for d in g.state.decks]
    g.crown_block(0)
    sizes_after = [d.size() for d in g.state.decks]
    assert sizes_after == sizes_before, (
        f"deck sizes changed: {sizes_before} -> {sizes_after}")


def test_crown_block_used_blocks_reuse_until_a_new_hand_is_dealt(registry):
    """The once-per-hand flag, written directly to construct the
    'already spent this hand' state (the public API always redeals in the
    same call, so this state is never otherwise externally observable):
    can_crown_block goes False while set, then True again once a fresh hand
    is dealt (Game.redraw resets it via the shared _fill_options path)."""
    g = _game(registry, items=("crown_of_the_blueprints",), seed=4)
    g.state.steps = 100
    pending, red = _force_red_slot0(g)
    assert g.can_crown_block(0)
    g.state.special.crown_block_used = True
    assert not g.can_crown_block(0)
    pending.redraws_left = 1  # a free (Classroom-style) redraw source
    g.redraw(RedrawKind.FREE)
    assert not g.state.special.crown_block_used
