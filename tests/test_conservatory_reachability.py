"""Conservatory reachability: the Found Floorplan gate.

Owner rulings (docs/open_tasks.md, 2026-08-14 "OWNER RULINGS x4"): the
Conservatory is `rarity: "unusual"`, `gem_cost: 1`, `pool: "found_floorplan"`
(a dedicated pool value, not a reuse of `studio_addition`), and carries
`counts_as_drafting_room`. Its floorplan is found via a held-shovel condition
on campsite arrival (special_items.py::on_area_arrival), which permanently
sets `state.conservatory_floorplan_found` -- carried across days via
DayChain._CARRYOVER_KEYS -- and decks.py::eligible_pool reads the carried
GameConfig flag to add the room to the draft pool from the FOLLOWING day
onward (`build_decks` runs at day start, before same-day discoveries land).

This file pins reachability only. The remodel mechanic (drawing three rooms
uniformly at random, consuming Dynamic Rarity) and the 15% forced draw are
separate, out-of-scope builds; tests/rooms/test_conservatory.py already pins
the remodel's one-time reroll effect once the room is placed directly.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.decks import eligible_pool
from blueprince_sim.engine.game import Game
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain, _CARRYOVER_KEYS

CONSERVATORY_UNUSUAL_GEM_DECK = 5  # rarity_idx(unusual)=2 * 2 + gem_bit(1)
CONSERVATORY_UNUSUAL_FREE_DECK = 4  # rarity_idx(unusual)=2 * 2 + gem_bit(0)


# --------------------------------------------------------------- draft pool

def test_conservatory_absent_from_eligible_pool_without_flag(registry):
    """Without conservatory_floorplan_found, the Conservatory is not in
    decks.py::eligible_pool -- the room the ordinary draft can ever see."""
    pool = eligible_pool(registry, GameConfig())
    assert "conservatory" not in {r.id for r in pool}


def test_conservatory_in_eligible_pool_with_flag(registry):
    """With conservatory_floorplan_found=True, the Conservatory joins the
    eligible pool -- the same door treasure_trove_blackprint/throne_room_
    blueprint use for their own rooms."""
    pool = eligible_pool(registry, GameConfig(conservatory_floorplan_found=True))
    assert "conservatory" in {r.id for r in pool}


def test_conservatory_not_draftable_without_flag_real_deck_build(registry):
    """A real build_decks() run (not a data read) deals zero Conservatory
    cards into any of the eight solitaire decks without the flag."""
    g = Game(GameConfig(), seed=0, registry=registry)
    conservatory_idx = registry.by_id["conservatory"].idx
    assert all(conservatory_idx not in d.order for d in g.state.decks)


def test_conservatory_draftable_with_flag_real_deck_build(registry):
    """The same real build_decks() run deals Conservatory cards into a deck
    once conservatory_floorplan_found=True -- the room is really reachable
    through the ordinary deck, not merely flagged as eligible."""
    g = Game(GameConfig(conservatory_floorplan_found=True), seed=0, registry=registry)
    conservatory_idx = registry.by_id["conservatory"].idx
    assert any(conservatory_idx in d.order for d in g.state.decks)


def test_conservatory_gem_cost_routes_it_into_the_gem_deck_not_free(registry):
    """gem_cost=1 puts the Conservatory's cards in the GEM unusual deck
    (index 5), never the free unusual deck (index 4) -- confirming the fix
    really moved it out of the free decks, not just past eligible_pool."""
    g = Game(GameConfig(conservatory_floorplan_found=True), seed=0, registry=registry)
    conservatory = registry.by_id["conservatory"]
    assert conservatory.gem_cost == 1
    assert not conservatory.is_free
    gem_deck = g.state.decks[CONSERVATORY_UNUSUAL_GEM_DECK]
    free_deck = g.state.decks[CONSERVATORY_UNUSUAL_FREE_DECK]
    assert conservatory.idx in gem_deck.order
    assert conservatory.idx not in free_deck.order


# --------------------------------------------------------------- campsite arrival

def test_campsite_arrival_with_shovel_sets_the_flag(registry):
    """Arriving at the campsite while holding a shovel permanently sets
    state.conservatory_floorplan_found (special_items.py::on_area_arrival)."""
    g = Game(GameConfig(starting_items=frozenset({"shovel"})), seed=0, registry=registry)
    g.state.steps = 200
    g.state.area = "private_drive"
    g.travel_to("campsite")
    assert g.state.conservatory_floorplan_found is True


def test_campsite_arrival_without_shovel_does_not_set_the_flag(registry):
    """Arriving at the campsite empty-handed does not find the floorplan --
    the owner-ruled shovel-held condition, not an unconditional grant."""
    g = Game(GameConfig(), seed=0, registry=registry)
    g.state.steps = 200
    g.state.area = "private_drive"
    g.travel_to("campsite")
    assert g.state.conservatory_floorplan_found is False


# --------------------------------------------------------------- next-day availability

def test_floorplan_found_mid_day_is_absent_from_that_days_own_decks(registry):
    """build_decks runs at day start; finding the floorplan mid-day cannot
    retroactively populate the decks already dealt for today."""
    chain = DayChain(GameConfig(starting_items=frozenset({"shovel"})), n_days=3)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    conservatory_idx = registry.by_id["conservatory"].idx
    assert all(conservatory_idx not in d.order for d in g1.state.decks), (
        "setup: day 1 decks must not already carry the Conservatory"
    )

    g1.state.steps = 200
    g1.state.area = "private_drive"
    g1.travel_to("campsite")
    assert g1.state.conservatory_floorplan_found is True

    # Today's already-built decks are untouched by the discovery.
    assert all(conservatory_idx not in d.order for d in g1.state.decks), (
        "finding the floorplan mid-day must not inject it into today's decks"
    )


def test_floorplan_found_is_available_starting_the_following_day(registry):
    """The flag carries through DayChain.advance()/next_config() into day 2's
    GameConfig, and day 2's real build_decks() run deals the Conservatory."""
    chain = DayChain(GameConfig(starting_items=frozenset({"shovel"})), n_days=3)
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    g1.state.steps = 200
    g1.state.area = "private_drive"
    g1.travel_to("campsite")

    chain.advance(g1.carryover())
    cfg_day2 = chain.next_config()
    assert cfg_day2.conservatory_floorplan_found is True

    g2 = Game(cfg_day2, seed=2, registry=registry)
    conservatory_idx = registry.by_id["conservatory"].idx
    assert any(conservatory_idx in d.order for d in g2.state.decks)


# --------------------------------------------------------------- carryover plumbing

def test_carryover_keys_frozenset_includes_conservatory_floorplan_found():
    """DayChain._CARRYOVER_KEYS carries the flag as a bool entry, in the
    18-entry set that also holds throne_room_blueprint/
    treasure_trove_blackprint -- the same shape this flag follows."""
    assert "conservatory_floorplan_found" in _CARRYOVER_KEYS
    assert len(_CARRYOVER_KEYS) == 18


def test_carryover_flag_appears_in_the_carryover_observation():
    """A flag discovered on day 1 shows up at index sorted(_CARRYOVER_KEYS)
    .index('conservatory_floorplan_found') in day 2's 'carryover' obs vector --
    the real Box(shape=(len(_CARRYOVER_KEYS),)) encoding, not a dict read.
    Mirrors tests/test_reward_horizon.py::test_carryover_obs_reflects_
    discovery_next_day's injection-then-advance shape."""
    import numpy as np

    base = GameConfig(starting_steps=3)
    chain = DayChain(base, n_days=3)
    env = BluePrinceEnv(cfg=base, day_chain=chain)
    env.reset(seed=0)

    env.day_chain.carried_flags["conservatory_floorplan_found"] = True
    rng = np.random.default_rng(0)
    terminated = truncated = False
    while not (terminated or truncated):
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        action = int(rng.choice(legal))
        _, _, terminated, truncated, _ = env.step(action)

    obs2, _ = env.reset(seed=1)
    carryover_vec = obs2["carryover"]
    idx = sorted(_CARRYOVER_KEYS).index("conservatory_floorplan_found")
    assert carryover_vec[idx] == 1


# --------------------------------------------------------------- drafting-room fidelity

def test_conservatory_effects_list_carries_counts_as_drafting_room(registry):
    """The Conservatory's own effects list carries counts_as_drafting_room --
    the data-level fix the wiki's Drafting-Room typing calls for."""
    conservatory = registry.by_id["conservatory"]
    assert [eff.tag for eff in conservatory.effects] == ["counts_as_drafting_room"]


def test_conservatory_placement_grants_a_classroom_redraw(registry):
    """Placing the Conservatory raises state.drafting_room_count, so a
    Classroom drafted afterward grants a free redraw -- the real downstream
    effect counts_as_drafting_room implies, not merely the tag's presence
    (tier1.py::counts_as_drafting_room / classroom.py::grant_free_redraws).
    Mirrors tests/rooms/test_classroom.py's own placement/doorway shape."""
    from blueprince_sim.engine.game import Phase
    from blueprince_sim.engine.grid import N, S, W

    g = Game(GameConfig(), seed=0, registry=registry)
    conservatory = registry.by_id["conservatory"]
    classroom = registry.by_id["classroom"]

    g._place_room(conservatory, 0, S)
    assert g.state.drafting_room_count == 1, (
        "setup: placing the Conservatory alone must already raise the count -- "
        "it is its own counts_as_drafting_room source, same as Classroom/"
        "Drawing Room/Library/Greenhouse"
    )
    g._place_room(classroom, 7, N | S | W)  # placed north of the Entrance Hall
    g.state.pos = 7  # stand inside it without walking (bypasses ON_ENTER)
    g.phase = Phase.NAVIGATE
    g.state.steps = 999

    # N from cell 7 goes deeper into the house (cell 12); the Classroom's own
    # placement above raised the count a second time, so the redraw grant
    # reflects BOTH drafting rooms, not just the Classroom's own.
    pending = g.open_door(7, N)
    assert pending.redraws_left == 2 == g.state.drafting_room_count, (
        "the Conservatory's counts_as_drafting_room must feed the same "
        "house-wide count the Classroom's free redraws read"
    )
