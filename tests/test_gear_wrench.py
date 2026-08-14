"""Gear Wrench: drafting a Mechanical Room while held offers a permanent
rarity pick over the FOUR RARITY LEVELS (not which room to target; the
room is always whichever Mechanical Room was just drafted).

Grouped in its own file (mirroring tests/test_the_axe.py's shape) since the
mechanic touches several concerns at once -- a reusable non-consumed item, a
new engine phase/action range, save-scoped permanent state threaded through
DayChain (including the attempt wrap), an observation key, and scripted-
policy dispatch -- rather than fitting any one existing thematic file. The
deck-bucket guard for the reachable Pump-Room-plus-Pool hazard lives in
tests/test_decks.py instead, next to build_decks/inject_rooms, the same
split test_the_axe.py's own docstring describes for its deck-composition
guard.
"""

from __future__ import annotations

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.model import RARITIES
from blueprince_sim.engine.state import DraftOption, PendingDraft
from blueprince_sim.env import obs as O
from blueprince_sim.env.actions import (WRENCH_RARITY_BASE, _build_mechanical_room_ids,
                                        action_mask, apply_action, describe_action)
from blueprince_sim.env.multiday import DayChain


def _game(cfg: GameConfig | None = None, seed: int = 0, registry=None) -> Game:
    """A Gear-Wrench-holding Game (special items on), NAVIGATE phase, day-start state."""
    base = cfg or GameConfig(special_items=True)
    if "gear_wrench" not in base.starting_items:
        import dataclasses
        base = dataclasses.replace(base, starting_items=base.starting_items | {"gear_wrench"})
    return Game(base, seed=seed, registry=registry)


def _draft_room(game: Game, room_id: str, cell: int = 2, direction: int = N,
                target_cell: int = 7, slot: int = 0) -> None:
    """Force ``room_id`` into the dealt hand and choose it -- a synthetic
    slot-0 (free) DraftOption, matching test_game.py's own PendingDraft
    construction shape, so the trigger under test (Game.choose) is exercised
    without depending on what the real deal pipeline happens to deal."""
    room = game.registry.by_id[room_id]
    game.state.pos = cell
    game.phase = Phase.DRAFTING
    pending = PendingDraft(from_cell=cell, direction=direction, target_cell=target_cell)
    pending.options = [DraftOption(room_idx=room.idx, orientation=room.door_mask,
                                   gem_cost=0, slot=slot)]
    game.state.pending = pending
    game.doorway_drafts[(cell, direction)] = pending
    game.choose(slot)


# ------------------------------------------------------------------- trigger


def test_choosing_a_mechanical_room_while_held_parks_wrench_pending():
    """Drafting a Mechanical Room (utility_closet: Room.is_category
    ('mechanical')) while a Gear Wrench is held parks Phase.WRENCH_PENDING
    instead of returning to NAVIGATE, with the drafted room's id recorded as
    the pending target."""
    g = _game()
    assert g.registry.by_id["utility_closet"].is_category("mechanical")
    _draft_room(g, "utility_closet")
    assert g.phase is Phase.WRENCH_PENDING
    assert g.state.pending_wrench_room_id == "utility_closet"


def test_choosing_a_mechanical_room_without_the_wrench_returns_to_navigate():
    """No Gear Wrench held: the same Mechanical Room draft returns to
    NAVIGATE as normal -- the trigger requires the item, not just the room."""
    g = Game(GameConfig(special_items=True), seed=0)
    _draft_room(g, "utility_closet")
    assert g.phase is Phase.NAVIGATE
    assert g.state.pending_wrench_room_id is None


def test_choosing_a_non_mechanical_room_never_triggers_wrench_pending():
    """A held Gear Wrench does nothing for a non-Mechanical Room draft --
    closet carries no 'mechanical' category."""
    g = _game()
    assert not g.registry.by_id["closet"].is_category("mechanical")
    _draft_room(g, "closet")
    assert g.phase is Phase.NAVIGATE


# ------------------------------------------------------------------- choice


def test_can_set_wrench_rarity_true_for_every_level_in_wrench_pending():
    """All four rarity levels (engine.model.RARITIES order) are legal in
    WRENCH_PENDING, including the room's own current one -- the wiki's
    "moved freely to any of the four rarity levels"."""
    g = _game()
    _draft_room(g, "utility_closet")
    for i in range(len(RARITIES)):
        assert g.can_set_wrench_rarity(i) is True


def test_can_set_wrench_rarity_false_outside_wrench_pending():
    """The choice is illegal in any other phase -- e.g. NAVIGATE."""
    g = _game()
    assert g.phase is Phase.NAVIGATE
    assert g.can_set_wrench_rarity(0) is False


def test_set_wrench_rarity_records_a_genuine_override():
    """Picking a rarity different from the room's own natal one records it
    in state.permanent_rarity and returns to NAVIGATE."""
    g = _game()
    room = g.registry.by_id["utility_closet"]
    target = (room.rarity_idx + 1) % len(RARITIES)
    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(target)
    assert g.state.permanent_rarity == {"utility_closet": target}
    assert g.phase is Phase.NAVIGATE
    assert g.state.pending_wrench_room_id is None


def test_set_wrench_rarity_choosing_the_natal_rarity_declines():
    """Picking the room's own current rarity is how a player declines to
    change anything: no entry is recorded (the wiki's "may permanently
    adjust", implying it need not be exercised every time)."""
    g = _game()
    room = g.registry.by_id["utility_closet"]
    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(room.rarity_idx)
    assert g.state.permanent_rarity == {}


def test_set_wrench_rarity_pops_a_prior_override_back_to_natal():
    """Re-drafting the same wrenched room and picking its natal rarity again
    removes the earlier override -- the persisted dict only ever holds
    genuine deviations from natal, matching set_dynamic_rarity's own
    idempotent-pop convention."""
    g = _game()
    g.state.inventory["gear_wrench"] = 1
    room = g.registry.by_id["utility_closet"]
    target = (room.rarity_idx + 1) % len(RARITIES)
    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(target)
    assert "utility_closet" in g.state.permanent_rarity

    _draft_room(g, "utility_closet", cell=7, direction=N, target_cell=12)
    g.set_wrench_rarity(room.rarity_idx)
    assert "utility_closet" not in g.state.permanent_rarity


def test_set_wrench_rarity_asserts_when_illegal():
    """set_wrench_rarity refuses to run outside can_set_wrench_rarity's own
    legality (no silent no-op outside WRENCH_PENDING)."""
    g = _game()
    try:
        g.set_wrench_rarity(0)
        assert False, "expected an AssertionError"
    except AssertionError:
        pass


def test_wrench_is_not_consumed_and_stays_reusable():
    """Unlike The Axe, the Gear Wrench is never spent: it is still held and
    usable again after resolving a rarity pick."""
    g = _game()
    assert si.count(g.state, "gear_wrench") == 1
    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(0)
    assert si.count(g.state, "gear_wrench") == 1

    _draft_room(g, "boiler_room", cell=7, direction=N, target_cell=12)
    assert g.phase is Phase.WRENCH_PENDING, "still usable on a second Mechanical Room this day"


# --------------------------------------------------------------- carryover


def test_carryover_reports_the_full_permanent_rarity_dict():
    """Game.carryover()['permanent_rarity'] is the full current record,
    ready for DayChain.advance() to replace its own running value from."""
    g = _game()
    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(3)
    assert g.carryover()["permanent_rarity"] == {"utility_closet": 3}


def test_wrench_rarity_survives_daychain_advance_into_tomorrow():
    """A room wrenched today stays wrenched for a Game built from tomorrow's
    next_config() -- the same end-to-end DayChain path test_the_axe.py uses
    for axed_rooms."""
    chain = DayChain(GameConfig(special_items=True), n_days=5)
    g1 = _game(chain.next_config(), seed=1)
    _draft_room(g1, "utility_closet")
    g1.set_wrench_rarity(3)
    chain.advance(g1.carryover())

    cfg2 = chain.next_config()
    assert cfg2.permanent_rarity == {"utility_closet": 3}
    g2 = Game(cfg2, seed=2, registry=g1.registry)
    assert g2.state.permanent_rarity == {"utility_closet": 3}


def test_wrench_rarity_survives_a_daychain_attempt_wrap():
    """Unlike draft_counts/foundation_cell (cleared at the wrap),
    permanent_rarity is SAVE-scoped: it survives a DayChain attempt wrap,
    the same carve-out as axed_rooms/stars/main_course_bonus."""
    chain = DayChain(GameConfig(special_items=True), n_days=1)
    g1 = _game(chain.next_config(), seed=1)
    _draft_room(g1, "utility_closet")
    g1.set_wrench_rarity(3)
    chain.advance(g1.carryover())
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"

    assert chain.next_config().permanent_rarity == {"utility_closet": 3}


def test_carryover_keys_frozenset_is_unaffected():
    """DayChain._CARRYOVER_KEYS stays a 16-entry frozenset of bool
    GameConfig fields only -- permanent_rarity is dict-valued permanent
    state and lives in the separate channel next_config()/advance() thread
    explicitly, the same way axed_rooms/draft_counts do, never in this set."""
    assert len(DayChain._CARRYOVER_KEYS) == 16
    assert "permanent_rarity" not in DayChain._CARRYOVER_KEYS


def test_dynamic_rarity_is_seeded_from_permanent_rarity_at_reset():
    """Game.reset seeds state.dynamic_rarity from cfg.permanent_rarity right
    after build_decks, so decks.py's own dynamic_rarity fallback (set_
    dynamic_rarity/inject_rooms/inject_rooms_undealt) agrees with the
    build-time bucket assignment from the very first deal."""
    cfg = GameConfig(special_items=True, permanent_rarity={"utility_closet": 3})
    g = Game(cfg, seed=0)
    assert g.state.dynamic_rarity == {"utility_closet": 3}


# -------------------------------------------------------------------- mask


def test_wrench_pending_action_mask_offers_all_four_and_nothing_else():
    """Every WRENCH_RARITY id is legal in WRENCH_PENDING and nothing outside
    that range is -- the phase can never dead-end.

    ``not mask[i:]`` on the tail slice is a truthiness check on the LIST
    object, not its contents -- always False for a non-empty slice
    regardless of what it holds. It happened to work only while WRENCH_RARITY
    was the last action range (an empty tail slice IS falsy); appending
    USE_TELESCOPE_PLANETARIUM_ACTION after it made the tail non-empty and
    exposed the bug. ``not any(...)`` actually checks every element.
    """
    g = _game()
    _draft_room(g, "utility_closet")
    mask = action_mask(g)
    assert mask[WRENCH_RARITY_BASE:WRENCH_RARITY_BASE + len(RARITIES)] == [True] * len(RARITIES)
    assert any(mask), "WRENCH_PENDING must never be a dead end"
    assert not any(mask[WRENCH_RARITY_BASE + len(RARITIES):])


def test_wrench_rarity_action_masked_off_outside_wrench_pending():
    """No WRENCH_RARITY id is legal while NAVIGATE, even with the item held."""
    g = _game()
    mask = action_mask(g)
    assert not any(mask[WRENCH_RARITY_BASE:WRENCH_RARITY_BASE + len(RARITIES)])


def test_apply_action_wrench_dispatches_to_set_wrench_rarity():
    """Dispatching a WRENCH_RARITY id through apply_action (not calling
    Game.set_wrench_rarity directly) records the same override."""
    g = _game()
    _draft_room(g, "utility_closet")
    apply_action(g, WRENCH_RARITY_BASE + 3)
    assert g.state.permanent_rarity == {"utility_closet": 3}
    assert g.phase is Phase.NAVIGATE


def test_describe_action_wrench_names_the_rarity():
    """describe_action for a WRENCH_RARITY id names the rarity level."""
    g = _game()
    _draft_room(g, "utility_closet")
    desc = describe_action(g, WRENCH_RARITY_BASE + 3)
    assert "rare" in desc


# --------------------------------------------------------------------- obs


def test_wrench_rarity_observation_flips_to_the_chosen_level():
    """The wrench_rarity observation entry for utility_closet's index reads
    (rarity_idx + 1) after wrenching it, and every other entry stays 0."""
    g = _game()
    room_ids = _build_mechanical_room_ids(g.registry)
    obs_before = O.encode(g)
    assert obs_before["wrench_rarity"].sum() == 0

    _draft_room(g, "utility_closet")
    g.set_wrench_rarity(3)
    obs_after = O.encode(g)
    i = room_ids.index("utility_closet")
    assert obs_after["wrench_rarity"][i] == 4  # rare = index 3, encoded +1
    assert obs_after["wrench_rarity"].sum() == 4


def test_wrench_rarity_observation_width_matches_mechanical_room_count(registry):
    """The observation vector's width is exactly the number of Mechanical
    Room ids (8 today), matching _build_mechanical_room_ids."""
    g = Game(GameConfig(special_items=True), seed=0, registry=registry)
    obs = O.encode(g)
    assert len(obs["wrench_rarity"]) == len(_build_mechanical_room_ids(registry)) == 8


# ------------------------------------------------------------- scripted policies


def test_scripted_policies_resolve_wrench_pending_without_crashing():
    """Every scripted policy (cli/policies.py) must handle WRENCH_PENDING --
    a policy that falls through to _choose_best would crash reading
    game.state.pending.options (None in this phase, the pending draft
    having already been cleared by Game.choose). Regression for the exact
    failure mode the brief calls out: 'every policy crashed in a new phase
    when the locked-door PR landed'."""
    from blueprince_sim.cli.policies import POLICIES

    for name, policy in POLICIES.items():
        g = _game(seed=1)
        _draft_room(g, "utility_closet")
        assert g.phase is Phase.WRENCH_PENDING
        rnd = random.Random(0)
        policy(g, rnd)  # must not raise
        assert g.phase is not Phase.WRENCH_PENDING, f"{name} made no progress in WRENCH_PENDING"
