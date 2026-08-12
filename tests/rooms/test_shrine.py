"""Shrine: category correctness, donate/take-back actions, the eight
blessings, and the theft curse.

Wiki (blueprince.wiki.gg/wiki/Shrine): deposit 1-80 gold for a blessing
lasting 3-7 days (the day granted counts as day 1); taking the gold back
curses the player for 2 days instead. Only one blessing (or the curse) is
active at a time.
"""

from __future__ import annotations

import random

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.effects.rooms import shrine
from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.state import DraftOption, PendingDraft
from blueprince_sim.env import actions as A
from blueprince_sim.env.blueprince_env import BluePrinceEnv
from blueprince_sim.env.multiday import DayChain

# Published band -> duration table (blueprince.wiki.gg/wiki/Shrine), used
# directly rather than read back from data/shrine.json so this pins the wiki
# contract, not merely a copy of the JSON.
PUBLISHED_BANDS = [(1, 16, 3), (17, 32, 4), (33, 48, 5), (49, 64, 6), (65, 80, 7)]

IMPLEMENTED_BLESSINGS = (
    "dancer", "high_roller", "gardener", "tinkerer", "general", "berry_picker",
)
STUBBED_BLESSINGS = ("chef", "monk")


def test_shrine_category_does_not_activate_the_outer_shop_dead_branch():
    """Shrine's category is "blueprint", not "shop": entering it off-grid
    must not resolve a current_shop_id -- its donate/take-back mechanic is a
    bespoke action pair (Game.donate_shrine/take_back_shrine_offering), not
    the generic shops.py commerce path."""
    reg = Registry.load()
    shrine_room = reg.by_id["shrine"]
    assert shrine_room.category == "blueprint"

    # Seed 3's outer-room hand deals Shrine into slot 1 (verified by construction).
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=3, registry=reg)
    pending = g.open_outer_draft()
    opt = next(o for o in pending.options if o.slot == 1)
    assert g.registry.rooms[opt.room_idx].id == "shrine", (
        "setup: seed must deal Shrine into slot 1"
    )
    g.choose(1)
    g.travel_to("shrine")

    assert g.state.outer_room_entered
    assert shops.current_shop_id(g) is None


def _at_shrine(g: Game) -> Game:
    """Place the player inside the drafted Shrine, without an RNG-dependent
    outer draft -- mirrors what a real Choose+travel_to("shrine") produces."""
    room = g.registry.by_id["shrine"]
    g.placed_ids.add(room.id)
    g.state.outer_room_drafted = True
    g.state.area = room.id
    g.state.outer_room_entered = True
    return g


def _place_at(g: Game, room_id: str, cell: int) -> None:
    """Directly place ``room_id`` at ``cell``, firing ON_PLACE / draft-site hooks."""
    room = g.registry.by_id[room_id]
    g._place_room(room, cell, room.door_mask)


def _drafting_hand(g: Game, options: list[DraftOption], target: int = 7) -> PendingDraft:
    """Put the game into DRAFTING with a hand-built pending draft (no live deck)."""
    from blueprince_sim.engine.grid import N

    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=target)
    pd.options = options
    g.state.pending = pd
    return pd


# ------------------------------------------------------------------ band table

@pytest.mark.parametrize("duration_idx,lo,hi,days", [
    (i, lo, hi, days) for i, (lo, hi, days) in enumerate(PUBLISHED_BANDS)
])
def test_band_maps_its_coin_range_to_the_published_duration(duration_idx, lo, hi, days):
    """Each of the 5 bands charges a coin cost inside its own published range
    and grants exactly that band's published duration, boundaries included
    (band 0 is 1-16 coins/3 days, ..., band 4 is 65-80 coins/7 days)."""
    g = Game(GameConfig(), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    before = g.state.coins
    g.donate_shrine(idx, duration_idx)
    cost = before - g.state.coins
    assert lo <= cost <= hi
    assert g.state.shrine_blessing_days == days


def test_every_implemented_blessing_has_a_cost_inside_every_band():
    """The band/cost table applies uniformly across all 6 live blessings, not
    just one -- every (blessing, band) pair charges inside that band's range."""
    r = shrine.rules(Game(GameConfig(), seed=1))
    for blessing_id in IMPLEMENTED_BLESSINGS:
        blessing = r.blessings[r.blessing_index[blessing_id]]
        for (lo, hi, _days), cost in zip(PUBLISHED_BANDS, blessing.costs):
            assert lo <= cost <= hi, f"{blessing_id} band cost {cost} outside {lo}-{hi}"


# ------------------------------------------------------------------ duration / one-at-a-time

def test_blessing_lasts_its_full_duration_counting_the_day_granted_then_expires():
    """A 3-day blessing is active the day it is granted and the two days after,
    then reads inactive on the fourth day -- the wiki's own worked example."""
    chain = DayChain(GameConfig(special_items=True), n_days=20)
    g = Game(chain.next_config(), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    g.donate_shrine(idx, 0)  # 3-day band
    assert shrine.blessing_active(g, "dancer") and g.state.shrine_blessing_days == 3

    chain.advance(g.carryover())
    g = Game(chain.next_config(), seed=2)
    assert shrine.blessing_active(g, "dancer") and g.state.shrine_blessing_days == 2

    chain.advance(g.carryover())
    g = Game(chain.next_config(), seed=3)
    assert shrine.blessing_active(g, "dancer") and g.state.shrine_blessing_days == 1

    chain.advance(g.carryover())
    g = Game(chain.next_config(), seed=4)
    assert not shrine.blessing_active(g, "dancer")
    assert g.state.shrine_blessing_days == 0


def test_blessing_survives_an_attempt_wrap():
    """SAVE-scoped state: a blessing granted near the end of an attempt is
    still active (decayed by one day) after DayChain wraps to a fresh attempt,
    the same shape as stars/main_course_bonus, not mail_transit_days's reset."""
    chain = DayChain(GameConfig(special_items=True), n_days=1)
    g = Game(chain.next_config(), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    g.donate_shrine(idx, 3)  # 6-day band: long enough to survive the wrap

    chain.advance(g.carryover())
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    g2 = Game(chain.next_config(), seed=2)
    assert g2.state.shrine_blessing_id == "dancer"
    assert g2.state.shrine_blessing_days == 5, "decayed by one day, not reset by the wrap"


def test_only_one_blessing_at_a_time():
    """A second donation is refused while a blessing is already active."""
    g = Game(GameConfig(), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    g.donate_shrine(idx, 0)
    assert not g.can_donate_shrine(idx, 1)
    assert not g.can_donate_shrine(shrine.rules(g).blessing_index["general"], 0)


def test_cannot_donate_while_cursed():
    """No new blessing can be granted while the curse is active."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    assert not g.can_donate_shrine(idx, 0)


# ------------------------------------------------------------------ stubbed blessings

@pytest.mark.parametrize("blessing_id", STUBBED_BLESSINGS)
def test_stubbed_blessing_is_inert_and_documents_why(blessing_id):
    """Chef and Monk are recorded but never donatable, and each carries a
    blocked_on reason explaining why."""
    g = Game(GameConfig(), seed=1)
    _at_shrine(g)
    g.state.coins = 999
    r = shrine.rules(g)
    idx = r.blessing_index[blessing_id]
    blessing = r.blessings[idx]
    assert not blessing.implemented
    assert blessing.blocked_on
    for duration_idx in range(len(r.bands)):
        assert not g.can_donate_shrine(idx, duration_idx)


# ------------------------------------------------------------------ donate masking

def test_donate_masked_only_at_the_shrine():
    """Donate actions never appear in the mask unless the player is standing
    inside the drafted Shrine, even with unlimited coins."""
    g = Game(GameConfig(), seed=1)
    g.state.coins = 999
    mask = A.action_mask(g)
    assert not any(mask[A.DONATE_BASE:A.TAKE_BACK_OFFERING_ACTION])


def test_donate_masked_only_when_affordable():
    """At the Shrine with 0 coins, no donate action is legal; with ample
    coins, exactly the implemented blessings x 5 bands are legal."""
    g = Game(GameConfig(), seed=1)
    _at_shrine(g)
    g.state.coins = 0
    mask = A.action_mask(g)
    assert not any(mask[A.DONATE_BASE:A.TAKE_BACK_OFFERING_ACTION])

    g.state.coins = 999
    mask = A.action_mask(g)
    legal = sum(mask[A.DONATE_BASE:A.TAKE_BACK_OFFERING_ACTION])
    assert legal == len(IMPLEMENTED_BLESSINGS) * len(PUBLISHED_BANDS)


# ------------------------------------------------------------------ take-back / curse

def test_take_back_refunds_coins_and_curses_for_two_days():
    """Taking back the offering returns the exact coins parked, drops the
    blessing, and curses the player for 2 days."""
    g = Game(GameConfig(), seed=1)
    _at_shrine(g)
    g.state.coins = 100
    idx = shrine.rules(g).blessing_index["dancer"]
    g.donate_shrine(idx, 0)
    assert g.state.coins < 100, "setup: the donation must actually have spent coins"
    assert g.can_take_back_shrine_offering()

    g.take_back_shrine_offering()
    assert g.state.coins == 100  # fully refunded
    assert g.state.shrine_blessing_id == ""
    assert g.state.shrine_blessing_days == 0
    assert g.state.shrine_curse_days == 2
    assert "cursed_effigy_unlocked" in g.state.shops.gift_unlocks


def test_curse_deducts_the_matching_resource_per_colour_drafted():
    """Each single-colour category loses its own published resource while
    cursed: Bedroom->step, Hallway->key, Green->gem, Shop->coin, Red->all four."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    g.state.steps, g.state.keys, g.state.gems, g.state.coins = 50, 5, 5, 5

    _place_at(g, "guest_bedroom", 7)
    assert g.state.steps == 49
    _place_at(g, "hallway", 12)
    assert g.state.keys == 4
    _place_at(g, "terrace", 17)
    assert g.state.gems == 4
    _place_at(g, "locksmith", 22)
    assert g.state.coins == 4
    _place_at(g, "lavatory", 27)  # red: combines all four
    assert (g.state.steps, g.state.keys, g.state.gems, g.state.coins) == (48, 3, 3, 3)


def test_multicoloured_room_loses_resources_additively_across_its_colours():
    """The Maid's Chamber (primary red + extra bedroom) loses 2 steps, 1 key,
    1 gem and 1 coin -- the wiki's own worked example for multicoloured rooms."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    g.state.steps, g.state.keys, g.state.gems, g.state.coins = 50, 5, 5, 5
    _place_at(g, "maids_chamber", 7)
    assert (g.state.steps, g.state.keys, g.state.gems, g.state.coins) == (48, 4, 4, 4)


def test_veranda_is_exempt_from_the_curse():
    """The Veranda incurs no penalty while cursed (published wiki exemption)."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    g.state.gems = 5
    _place_at(g, "veranda", 7)
    assert g.state.gems == 5


def test_curse_loss_floors_at_zero_not_negative():
    """Losing a resource already at 0 leaves it at 0, never negative."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    g.state.keys = 0
    _place_at(g, "hallway", 7)
    assert g.state.keys == 0


def test_no_curse_no_loss():
    """Drafting any colour outside the curse loses nothing."""
    g = Game(GameConfig(), seed=1)
    g.state.keys = 5
    _place_at(g, "hallway", 7)
    assert g.state.keys == 5


# ------------------------------------------------------------------ Dancer

def test_dancer_rotation_costs_one_gem_per_spin():
    """Blessing of the Dancer: rotation is available for 1 gem, spends exactly
    that gem per spin, and stops being available once gems run out."""
    g = Game(GameConfig(shrine_blessing_id="dancer", shrine_blessing_days=3), seed=1)
    g.state.gems = 1
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    from blueprince_sim.engine.grid import E, S, W
    pd = _drafting_hand(g, [DraftOption(room_idx=troom.idx, orientation=E | S | W,
                                        gem_cost=0, slot=0)])
    assert g.rotation_available()
    before = pd.options[0].orientation
    g.rotate_options()
    assert g.state.gems == 0
    assert pd.options[0].orientation != before
    assert not g.rotation_available(), "no gems left for a second paid spin"


def test_dancer_inactive_without_the_blessing():
    """Without Dancer active, an ordinary hand with no other rotation source
    is not rotatable even with gems in hand."""
    g = Game(GameConfig(), seed=1)
    g.state.gems = 5
    troom = next(r for r in g.registry.rooms if r.layout == "t" and r.rarity)
    from blueprince_sim.engine.grid import E, S, W
    _drafting_hand(g, [DraftOption(room_idx=troom.idx, orientation=E | S | W,
                                   gem_cost=0, slot=0)])
    assert not g.rotation_available()


# ------------------------------------------------------------------ High Roller

def test_high_roller_grants_a_die_per_shop_drafted():
    """Blessing of the High Roller: drafting a Shop grants 1 die."""
    g = Game(GameConfig(shrine_blessing_id="high_roller", shrine_blessing_days=3), seed=1)
    before = g.state.dice
    _place_at(g, "locksmith", 7)
    assert g.state.dice == before + 1


def test_high_roller_grants_five_coins_per_die_roll():
    """Blessing of the High Roller: rolling a die (a die-source redraw)
    grants 5 extra coins, on top of the ordinary redraw."""
    g = Game(GameConfig(shrine_blessing_id="high_roller", shrine_blessing_days=3,
                        special_items=True), seed=1)
    doors = g.frontier_doorways()
    cell, d = doors[0]
    g.open_door(cell, d)
    g.state.dice = 1
    coins_before = g.state.coins
    g.redraw(RedrawKind.DIE)
    assert g.state.dice == 0
    assert g.state.coins == coins_before + 5


def test_high_roller_inactive_grants_no_bonus_coins():
    """Without High Roller active, a die redraw grants no coin bonus."""
    g = Game(GameConfig(special_items=True), seed=1)
    doors = g.frontier_doorways()
    cell, d = doors[0]
    g.open_door(cell, d)
    g.state.dice = 1
    coins_before = g.state.coins
    g.redraw(RedrawKind.DIE)
    assert g.state.coins == coins_before


# ------------------------------------------------------------------ Gardener

def _courtyard_count(g: Game) -> int:
    courtyard = g.registry.by_id["courtyard"]
    deck = g.state.deck(courtyard.rarity_idx, not courtyard.is_free)
    return deck.order.count(courtyard.idx)


def test_gardener_injects_eight_courtyards_every_active_day():
    """Blessing of the Gardener: 8 extra Courtyards in the live decks, on top
    of whatever the base draft pool already carries, re-injected fresh each
    active day since decks do not persist day to day."""
    baseline = Game(GameConfig(), seed=7)
    blessed = Game(
        GameConfig(shrine_blessing_id="gardener", shrine_blessing_days=3), seed=7)
    assert _courtyard_count(blessed) == _courtyard_count(baseline) + 8


def test_gardener_injection_stops_once_the_blessing_expires():
    """A carried-in blessing that has already decayed to 0 days no longer injects."""
    baseline = Game(GameConfig(), seed=7)
    expired = Game(
        GameConfig(shrine_blessing_id="gardener", shrine_blessing_days=0), seed=7)
    assert _courtyard_count(expired) == _courtyard_count(baseline)


# ------------------------------------------------------------------ Tinkerer

def test_tinkerer_cross_triggers_any_active_experiment_on_a_mechanical_draft():
    """Blessing of the Tinkerer: drafting a Mechanical Room fires the
    currently configured experiment, independent of its own chosen trigger."""
    g = Game(GameConfig(shrine_blessing_id="tinkerer", shrine_blessing_days=3,
                        special_items=True), seed=1)
    g.state.experiment.trigger_id = "shops"       # a trigger a Mechanical Room never satisfies
    g.state.experiment.effect_id = "gain_star"
    stars_before = g.state.stars
    _place_at(g, "utility_closet", 7)              # Mechanical, not a Shop
    assert g.state.experiment.success_count == 1
    assert g.state.stars == stars_before + 1


def test_tinkerer_inactive_does_not_cross_trigger():
    """Without Tinkerer active, drafting a Mechanical Room does not fire an
    experiment configured on an unrelated trigger."""
    g = Game(GameConfig(special_items=True), seed=1)
    g.state.experiment.trigger_id = "shops"
    g.state.experiment.effect_id = "gain_star"
    _place_at(g, "utility_closet", 7)
    assert g.state.experiment.success_count == 0


# ------------------------------------------------------------------ General

def test_general_grants_five_gems_once_five_ranks_hold_red_rooms():
    """Blessing of the General: +5 gems after drafting a Red Room brings the
    count of distinct ranks holding Red Rooms to 5 or more, and keeps firing
    on every further qualifying draft."""
    g = Game(GameConfig(shrine_blessing_id="general", shrine_blessing_days=3), seed=1)
    for cell in (7, 12, 17, 22):  # ranks 2-5: only 4 distinct ranks so far
        _place_at(g, "lavatory", cell)
    assert g.state.gems == 0

    _place_at(g, "lavatory", 27)  # rank 6: 5th distinct rank -- fires
    assert g.state.gems == 5

    _place_at(g, "lavatory", 32)  # rank 7: still >=5 ranks -- fires again
    assert g.state.gems == 10


def test_general_inactive_grants_no_gems():
    """Without General active, the same red-room spread grants no gems."""
    g = Game(GameConfig(), seed=1)
    for cell in (7, 12, 17, 22, 27):
        _place_at(g, "lavatory", cell)
    assert g.state.gems == 0


# ------------------------------------------------------------------ Berry Picker

def test_berry_pick_drafts_a_room_from_a_pool_larger_than_the_dealt_hand():
    """Blessing of the Berry Picker: the pool berry_pick draws from is not
    limited to the 3 dealt options."""
    g = Game(GameConfig(shrine_blessing_id="berry_picker", shrine_blessing_days=3,
                        special_items=True), seed=3)
    doors = g.frontier_doorways()
    cell, d = doors[0]
    g.open_door(cell, d)
    candidates = shrine._berry_candidates(g, g.state.pending)
    assert len(candidates) > len(g.state.pending.options)


def test_berry_pick_places_a_room_and_clears_the_hand():
    """Picking a berry places a room at the target cell and returns to NAVIGATE,
    the same end state as an ordinary choose()."""
    g = Game(GameConfig(shrine_blessing_id="berry_picker", shrine_blessing_days=3,
                        special_items=True), seed=3)
    doors = g.frontier_doorways()
    cell, d = doors[0]
    g.open_door(cell, d)
    assert g.can_berry_pick()
    target_cell = g.state.pending.target_cell

    g.berry_pick()
    assert g.phase is Phase.NAVIGATE
    assert g.state.pending is None
    assert g.state.grid[target_cell] >= 0


def test_berry_pick_unavailable_without_the_blessing():
    """Without Berry Picker active, the action is never legal."""
    g = Game(GameConfig(special_items=True), seed=3)
    doors = g.frontier_doorways()
    cell, d = doors[0]
    g.open_door(cell, d)
    assert not g.can_berry_pick()
    mask = A.action_mask(g)
    assert not mask[A.BERRY_PICK_ACTION]


# ------------------------------------------------------------------ replay

def test_day_replays_clean_through_shrine_interactions():
    """A masked-random rollout that starts standing at the Shrine with ample
    coins reaches a normal termination with no crash and no illegal action,
    exercising donate/take-back alongside ordinary navigation."""
    rng = random.Random(13)
    for seed in range(5):
        cfg = GameConfig(special_items=True)
        env = BluePrinceEnv(cfg)
        env.reset(seed=seed)
        _at_shrine(env.game)
        env.game.state.coins = 200
        for _ in range(400):
            mask = env.action_masks()
            legal = [i for i, ok in enumerate(mask) if ok]
            assert legal, f"seed {seed}: all-zero mask in phase {env.game.phase.name}"
            action = rng.choice(legal)
            _, _, term, trunc, _ = env.step(action)
            if term or trunc:
                break
        assert env.game.phase is Phase.TERMINAL
