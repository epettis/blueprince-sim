"""The Axe: a Room-Directory action that consumes the held item to permanently
zero one floorplan family's gem cost, capped at 3 simultaneously-axed
families for the whole save.

Grouped in its own file (mirroring tests/test_inner_sanctum.py's shape) since
the mechanic touches several concerns at once -- a consumed-use item, a new
engine action, save-scoped permanent state threaded through DayChain
(including the attempt wrap), an observation key, and a shop gate -- rather
than fitting any one existing thematic file. The deck-composition guard
(the trap this item is most likely to fall into) lives in
tests/test_decks.py instead, next to build_decks/eligible_pool.
"""

from __future__ import annotations

import dataclasses

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.state import DraftOption
from blueprince_sim.engine.upgrades import root_base_id
from blueprince_sim.env import obs as O
from blueprince_sim.env.actions import AXE_TARGET_BASE, _build_axe_target_ids, action_mask, apply_action
from blueprince_sim.env.multiday import DayChain


def _game(cfg: GameConfig | None = None, seed: int = 0, registry=None) -> Game:
    """An Axe-holding Game (special items on), NAVIGATE phase, day-start state."""
    base = cfg or GameConfig(special_items=True)
    if "the_axe" not in base.starting_items:
        base = dataclasses.replace(base, starting_items=base.starting_items | {"the_axe"})
    return Game(base, seed=seed, registry=registry)


def _enter_shop(game: Game, room_id: str, cell: int = 7) -> None:
    """Place and enter a shop, rolling its stock (mirrors test_shops.py's own helper)."""
    reg = game.registry
    room = reg.by_id[room_id]
    st = game.state
    st.grid[cell] = room.idx
    st.placed_doors[cell] = room.door_mask
    st.entered[cell] = True
    st.pos = cell
    shops.on_enter_shop(game, room)


def _axe_option(game: Game, room_id: str, slot: int = 1) -> DraftOption:
    """A synthetic slot>=1 DraftOption for ``room_id``, matching how draft.py
    deals a hand (gem_cost resolved at deal time via resolve_gem_cost)."""
    room = game.registry.by_id[room_id]
    return DraftOption(room_idx=room.idx, orientation=room.door_mask,
                       gem_cost=room.gem_cost, slot=slot)


# ---------------------------------------------------------------- legality


def test_can_axe_room_true_when_held_and_target_is_a_gem_root(registry):
    """A held Axe legalizes axing any real, gem-costed floorplan root, e.g.
    kitchen -- the common one-family case."""
    g = _game(registry=registry)
    assert g.can_axe_room("kitchen") is True


def test_can_axe_room_false_without_the_item(registry):
    """No Axe held: axing is illegal even for an otherwise-valid target."""
    g = Game(GameConfig(special_items=True), seed=0, registry=registry)
    assert g.can_axe_room("kitchen") is False


def test_can_axe_room_false_for_a_variant_id(registry):
    """A specific upgrade variant id is never a legal target -- only its
    family's ROOT id is (upgrades.root_base_id), even though the variant
    itself carries a gem cost."""
    g = _game(registry=registry)
    variant_id = "cloister_of_rynna__ix29"
    assert root_base_id(g.registry, g.registry.by_id[variant_id]) == "cloister"
    assert g.can_axe_room(variant_id) is False


def test_can_axe_room_false_for_a_free_room(registry):
    """A room with no gem cost at all (closet, gem_cost 0) can never be an
    Axe target -- there is nothing to zero."""
    g = _game(registry=registry)
    assert g.registry.by_id["closet"].gem_cost == 0
    assert g.can_axe_room("closet") is False


def test_can_axe_room_false_for_an_already_axed_target(registry):
    """The same root cannot be axed twice -- it is already permanently free."""
    g = _game(registry=registry)
    g.axe_room("kitchen")
    g.state.inventory["the_axe"] = 1  # pretend a second Axe was bought
    assert g.can_axe_room("kitchen") is False


def test_can_axe_room_requires_navigate_phase(registry):
    """Illegal while DRAFTING (or any non-NAVIGATE phase) -- mirrors every
    other consumed-item action's phase guard."""
    from blueprince_sim.engine.game import Phase
    g = _game(registry=registry)
    g.phase = Phase.DRAFTING
    assert g.can_axe_room("kitchen") is False


# -------------------------------------------------------------- consumption


def test_axe_room_consumes_the_item_for_good():
    """axe_room removes the Axe from inventory and marks it consumed (never
    returned to the spawn pool), the same shape as Repellent/Sledge Hammer."""
    g = _game()
    assert si.count(g.state, "the_axe") == 1
    g.axe_room("kitchen")
    assert si.count(g.state, "the_axe") == 0
    assert "the_axe" in g.state.special.removed


def test_axe_room_records_target_in_ordered_axed_rooms():
    """The target lands in state.axed_rooms, an ordered tuple (not a set),
    preserving insertion order for a future un-modelled 4th-axe rule."""
    g = _game()
    g.state.inventory["the_axe"] = 3
    g.axe_room("kitchen")
    g.axe_room("attic")
    assert g.state.axed_rooms == ("kitchen", "attic")


def test_axe_room_asserts_when_illegal():
    """axe_room refuses to run outside can_axe_room's own legality (no silent
    no-op that would desync the item count from the permanent record)."""
    g = Game(GameConfig(special_items=True), seed=0)  # no Axe held
    try:
        g.axe_room("kitchen")
        assert False, "expected an AssertionError"
    except AssertionError:
        pass


# ------------------------------------------------------------------- cap


def test_cap_of_three_blocks_a_fourth_axe():
    """can_axe_room goes False once 3 families are already axed, even with a
    4th Axe held and a brand-new valid target -- the published max_active cap."""
    g = _game()
    g.state.inventory["the_axe"] = 4
    for room_id in ("kitchen", "attic", "ballroom"):
        assert g.can_axe_room(room_id)
        g.axe_room(room_id)
    assert len(g.state.axed_rooms) == 3
    assert g.can_axe_room("bookshop") is False


# ------------------------------------------------------------ charged cost


def test_charged_cost_reads_zero_for_an_axed_room():
    """After axing kitchen, _effective_cost (what choose()/_pay() actually
    charge) reads 0 for a kitchen draft option that otherwise costs gems."""
    g = _game()
    room = g.registry.by_id["kitchen"]
    opt = _axe_option(g, "kitchen")
    assert g._effective_cost(room, opt) == room.gem_cost > 0

    g.axe_room("kitchen")
    assert g._effective_cost(room, opt) == 0


def test_charged_cost_reads_zero_for_an_axed_familys_upgrade_variant():
    """Axing the ROOT family also zeroes an upgrade variant's charged cost --
    'cloister' covers every Cloister-of-* variant, per the owner ruling."""
    g = _game()
    variant = g.registry.by_id["cloister_of_rynna__ix29"]
    opt = _axe_option(g, variant.id)
    assert g._effective_cost(variant, opt) == variant.gem_cost > 0

    g.axe_room("cloister")
    assert g._effective_cost(variant, opt) == 0


def test_dynamic_cost_room_also_reads_zero_once_axed(registry):
    """resolve_gem_cost short-circuits an axed family to 0 BEFORE evaluating
    gem_cost_dynamic, rather than 0 + the bedroom bonus. No shipped room
    currently carries a dynamic cost (asserted below as the empirical fact
    that makes this synthetic construction necessary): resolve_gem_cost takes
    the Room object directly rather than re-looking it up by id, so a copy of
    kitchen with gem_cost_dynamic patched on still exercises the real
    short-circuit branch."""
    assert not any(r.gem_cost_dynamic for r in registry.rooms), (
        "a real dynamic-cost room now exists in the data; prefer it to this synthetic one"
    )
    from blueprince_sim.engine.state import resolve_gem_cost
    base = registry.by_id["kitchen"]
    dynamic_room = dataclasses.replace(base, gem_cost_dynamic="plus_one_per_bedroom")
    g = _game(registry=registry)
    assert resolve_gem_cost(dynamic_room, g.state, registry.rooms) == dynamic_room.gem_cost

    g.axe_room("kitchen")
    assert resolve_gem_cost(dynamic_room, g.state, registry.rooms) == 0


# --------------------------------------------------------------- carryover


def test_carryover_reports_the_full_ordered_tuple():
    """Game.carryover()['axed_rooms'] is the full ordered history, ready for
    DayChain.advance() to replace its own running value from."""
    g = _game()
    g.state.inventory["the_axe"] = 2
    g.axe_room("kitchen")
    g.axe_room("attic")
    assert g.carryover()["axed_rooms"] == ["kitchen", "attic"]


def test_axed_rooms_survive_daychain_advance_into_tomorrow():
    """A room axed today stays axed (and still costs 0) for a Game built from
    tomorrow's next_config() -- the same end-to-end DayChain path
    test_inner_sanctum.py uses for sigil_doors_open."""
    chain = DayChain(GameConfig(special_items=True), n_days=5)
    g1 = _game(chain.next_config(), seed=1)
    g1.axe_room("kitchen")
    chain.advance(g1.carryover())

    cfg2 = chain.next_config()
    assert "kitchen" in cfg2.axed_rooms
    g2 = Game(cfg2, seed=2, registry=g1.registry)
    kitchen = g2.registry.by_id["kitchen"]
    opt = _axe_option(g2, "kitchen")
    assert g2._effective_cost(kitchen, opt) == 0


def test_axed_rooms_survive_a_daychain_attempt_wrap():
    """Unlike draft_counts/foundation_cell (cleared at the wrap), axed_rooms
    is SAVE-scoped: it survives a DayChain attempt wrap, the same carve-out
    as stars/main_course_bonus/the shrine_* fields."""
    chain = DayChain(GameConfig(special_items=True), n_days=1)
    g1 = _game(chain.next_config(), seed=1)
    g1.axe_room("kitchen")
    chain.advance(g1.carryover())
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"

    assert "kitchen" in chain.next_config().axed_rooms


def test_the_cap_also_survives_a_daychain_attempt_wrap():
    """The 3-use cap is enforced against the SAME save-scoped tuple across a
    wrap: three families axed before a wrap still read as 3 after it, so a
    fresh attempt cannot re-sell past the cap."""
    chain = DayChain(GameConfig(special_items=True), n_days=1)
    g1 = _game(chain.next_config(), seed=1)
    g1.state.inventory["the_axe"] = 3
    for room_id in ("kitchen", "attic", "ballroom"):
        g1.axe_room(room_id)
    chain.advance(g1.carryover())

    cfg2 = chain.next_config()
    assert len(cfg2.axed_rooms) == 3
    g2 = Game(cfg2, seed=2, registry=g1.registry)
    g2.state.inventory["the_axe"] = 1
    assert g2.can_axe_room("bookshop") is False


def test_carryover_keys_frozenset_is_unaffected():
    """DayChain._CARRYOVER_KEYS stays a 19-entry frozenset of bool GameConfig
    fields only -- axed_rooms is ordered/set-valued permanent state and lives
    in the separate channel next_config()/advance() thread explicitly, the
    same way sigil_doors_open/collected_sanctum_keys do, never in this set."""
    assert len(DayChain._CARRYOVER_KEYS) == 19
    assert "axed_rooms" not in DayChain._CARRYOVER_KEYS


# -------------------------------------------------------------------- mask


def test_axe_target_action_masked_on_for_a_valid_target():
    """AXE_TARGET_BASE + i is legal exactly when can_axe_room(target_ids[i])
    is True -- proven for kitchen's own index."""
    g = _game()
    target_ids = _build_axe_target_ids(g.registry)
    i = target_ids.index("kitchen")
    mask = action_mask(g)
    assert mask[AXE_TARGET_BASE + i] is True


def test_axe_target_action_masked_off_without_the_item():
    """No Axe held: every one of the 48 AXE_TARGET ids is masked off."""
    g = Game(GameConfig(special_items=True), seed=0)
    target_ids = _build_axe_target_ids(g.registry)
    mask = action_mask(g)
    assert not any(mask[AXE_TARGET_BASE:AXE_TARGET_BASE + len(target_ids)])


def test_axe_target_action_masked_off_once_already_axed():
    """A target already axed drops out of the mask even with more Axes held."""
    g = _game()
    g.axe_room("kitchen")
    g.state.inventory["the_axe"] = 1
    target_ids = _build_axe_target_ids(g.registry)
    i = target_ids.index("kitchen")
    mask = action_mask(g)
    assert mask[AXE_TARGET_BASE + i] is False


def test_axe_target_mask_matches_per_target_legality_with_axe_held():
    """With the Axe held and one family already axed, EVERY AXE_TARGET mask
    bit -- not just kitchen's -- must equal can_axe_room(that target) exactly:
    kitchen (spent) reads False, an untouched family (attic) still reads True.
    Guards can_axe_any_room (the hoisted, target-independent guard the mask
    loop now checks once before iterating) from a bug that folds a per-target
    fact -- e.g. 'something has been axed' instead of 'THIS target is axed' --
    into the shared guard, which would silently mask off every other target
    the moment any one family is spent."""
    g = _game()
    g.state.inventory["the_axe"] = 2
    g.axe_room("kitchen")
    g.state.inventory["the_axe"] = 1
    target_ids = _build_axe_target_ids(g.registry)
    mask = action_mask(g)
    for i, target_id in enumerate(target_ids):
        assert mask[AXE_TARGET_BASE + i] == g.can_axe_room(target_id), target_id
    assert mask[AXE_TARGET_BASE + target_ids.index("kitchen")] is False
    assert mask[AXE_TARGET_BASE + target_ids.index("attic")] is True


def test_apply_action_axe_dispatches_to_axe_room():
    """Dispatching an AXE_TARGET id through apply_action (not calling
    Game.axe_room directly) consumes the item and records the target."""
    g = _game()
    target_ids = _build_axe_target_ids(g.registry)
    i = target_ids.index("kitchen")
    apply_action(g, AXE_TARGET_BASE + i)
    assert g.state.axed_rooms == ("kitchen",)
    assert si.count(g.state, "the_axe") == 0


def test_describe_action_axe_mentions_room_name():
    """describe_action for an AXE_TARGET id names the target room, matching
    the 'filter #n <name>' convention CROWN_BLOCK's describe uses."""
    from blueprince_sim.env.actions import describe_action
    g = _game()
    target_ids = _build_axe_target_ids(g.registry)
    i = target_ids.index("kitchen")
    desc = describe_action(g, AXE_TARGET_BASE + i)
    assert g.registry.by_id["kitchen"].name in desc


# --------------------------------------------------------------------- obs


def test_axed_rooms_observation_flips_on_for_the_axed_target():
    """The axed_rooms observation bit for kitchen's index flips on after
    axing it, and every other bit stays 0 -- same shape as
    test_sigil_doors_open_observation_reflects_todays_and_carried_openings."""
    g = _game()
    target_ids = _build_axe_target_ids(g.registry)
    obs_before = O.encode(g)
    assert obs_before["axed_rooms"].sum() == 0

    g.axe_room("kitchen")
    obs_after = O.encode(g)
    i = target_ids.index("kitchen")
    assert obs_after["axed_rooms"][i] == 1
    assert obs_after["axed_rooms"].sum() == 1


def test_axed_rooms_observation_width_matches_target_count(registry):
    """The observation vector's width is exactly the number of axeable
    families, matching the action space's own AXE_TARGET range."""
    from blueprince_sim.env.actions import _N_AXE_TARGETS
    g = Game(GameConfig(special_items=True), seed=0, registry=registry)
    obs = O.encode(g)
    assert len(obs["axed_rooms"]) == _N_AXE_TARGETS == 49


def test_axe_target_count_matches_the_pinned_action_space_width(registry):
    """_build_axe_target_ids' own length agrees with the pinned _N_AXE_TARGETS
    (the action space's own AXE_TARGET_BASE..LOCK_MENU_BASE width) -- the
    ACTION side of the invariant test_axed_rooms_observation_width_matches_
    target_count above only pins on the observation side. A room gaining a
    rarity and a nonzero gem cost without a matching bump here desyncs the two
    and silently corrupts LOCK_MENU_BASE's mask bit (see
    _build_axe_target_ids' own docstring and assertion); this test -- and that
    assertion -- are what would have caught the Conservatory (PR #329) doing
    exactly that before it shipped."""
    from blueprince_sim.env.actions import _N_AXE_TARGETS
    assert len(_build_axe_target_ids(registry)) == _N_AXE_TARGETS == 49


# --------------------------------------------------------------- shop gate


def test_armory_sells_the_axe_below_the_cap():
    """A fresh save's Armory lists The Axe among its 4 static entries (no
    families axed yet, cap not reached)."""
    g = Game(GameConfig(special_items=True, day=15), seed=0)
    _enter_shop(g, "the_armory")
    entries = g.state.shops.stock["the_armory"]
    assert "the_axe" in [e["id"] for e in entries]


def test_armory_stops_selling_the_axe_once_the_cap_is_spent():
    """Once 3 families have been axed (cfg.axed_rooms at max_active), the
    Armory's stock no longer offers The Axe -- the gated_out shop gate."""
    cfg = GameConfig(special_items=True, day=15,
                     axed_rooms=("kitchen", "attic", "ballroom"))
    g = Game(cfg, seed=0)
    _enter_shop(g, "the_armory")
    entries = g.state.shops.stock["the_armory"]
    assert "the_axe" not in [e["id"] for e in entries]
    assert len(entries) == 3
