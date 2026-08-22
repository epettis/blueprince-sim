"""Shrine: category correctness, donate/take-back actions, the eight
blessings, and the theft curse.

Wiki (blueprince.wiki.gg/wiki/Shrine): deposit 1-80 gold for a blessing
lasting 3-7 days (the day granted counts as day 1); taking the gold back
curses the player for 2 days instead. Only one blessing (or the curse) is
active at a time.
"""

from __future__ import annotations

import dataclasses
import json
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


def _with_mutated_curse(monkeypatch, reg, **curse_overrides) -> None:
    """Swap the cached ShrineRules for ``reg``'s data_dir with one whose curse
    is ``dataclasses.replace``d by ``curse_overrides``, restored automatically
    at the end of the test (monkeypatch.setitem)."""
    real_rules = shrine.load_shrine_rules(reg.data_dir)
    mutated_curse = dataclasses.replace(real_rules.curse, **curse_overrides)
    mutated_rules = dataclasses.replace(real_rules, curse=mutated_curse)
    monkeypatch.setitem(shrine._RULES_CACHE, reg.data_dir, mutated_rules)
    # load_shrine_rules also checks a one-slot identity memo ahead of this dict
    # (perf: skips hashing/normalising data_dir on the hot path) -- the call
    # above already warmed that memo with real_rules, so reset it too or the
    # next load_shrine_rules(reg.data_dir) would return the stale real rules
    # instead of consulting the dict this helper just mutated.
    monkeypatch.setattr(shrine, "_last_dir", None)
    monkeypatch.setattr(shrine, "_last_rules", None)


def test_curse_duration_follows_the_loaded_rules_data(monkeypatch):
    """The days actually applied by take_back() come from ShrineRules.curse
    .duration_days, not a fixed constant: swapping the loaded rules object for
    one with duration_days=99 makes take_back() curse for 99 days, proving the
    duration is read from parsed data rather than hardcoded."""
    reg = Registry.load()
    _with_mutated_curse(monkeypatch, reg, duration_days=99)

    g = Game(GameConfig(), seed=1, registry=reg)
    _at_shrine(g)
    g.state.coins = 999
    idx = shrine.rules(g).blessing_index["dancer"]
    g.donate_shrine(idx, 0)
    g.take_back_shrine_offering()
    assert g.state.shrine_curse_days == 99


def test_curse_exemption_follows_the_loaded_rules_data(monkeypatch):
    """A room added to ShrineRules.curse.exempt_room_ids stops being charged:
    the Hallway ordinarily loses a key while cursed (see
    test_curse_deducts_the_matching_resource_per_colour_drafted), but with the
    loaded rules mutated to exempt it, no key is lost -- proving the exemption
    list actually gates the loss rather than a hardcoded id check."""
    reg = Registry.load()
    real_rules = shrine.load_shrine_rules(reg.data_dir)
    _with_mutated_curse(
        monkeypatch, reg,
        exempt_room_ids=frozenset(real_rules.curse.exempt_room_ids | {"hallway"}),
    )

    g = Game(GameConfig(shrine_curse_days=2), seed=1, registry=reg)
    g.state.keys = 5
    _place_at(g, "hallway", 7)
    assert g.state.keys == 5


def test_curse_resource_loss_follows_the_loaded_rules_data(monkeypatch):
    """The resources deducted per colour come from ShrineRules.curse
    .resource_loss_per_category: mutating the Hallway category to cost 3 keys
    instead of 1 changes the actual deduction, proving the loss amount is
    read from parsed data rather than a hardcoded table."""
    reg = Registry.load()
    real_rules = shrine.load_shrine_rules(reg.data_dir)
    mutated_losses = dict(real_rules.curse.resource_loss_per_category)
    mutated_losses["hallway"] = {"keys": 3}
    _with_mutated_curse(monkeypatch, reg, resource_loss_per_category=mutated_losses)

    g = Game(GameConfig(shrine_curse_days=2), seed=1, registry=reg)
    g.state.keys = 5
    _place_at(g, "hallway", 7)
    assert g.state.keys == 2


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


def _outer_hand(g: Game, room_id: str) -> None:
    """Put the game into DRAFTING on a one-option outer hand offering ``room_id``.

    Built rather than dealt so the scenario never depends on which three of the
    eight outer rooms a seed happens to shuffle up. Reproduces exactly what
    Game.open_outer_draft leaves behind for Game.choose to consume: from_cell
    and target_cell both -1 (the sentinel that routes choose to _choose_outer),
    and the hand registered under the (-1, 0) doorway key _choose_outer deletes.
    """
    room = g.registry.by_id[room_id]
    pending = PendingDraft(from_cell=-1, direction=0, target_cell=-1)
    pending.options.append(
        DraftOption(room_idx=room.idx, orientation=room.door_mask, gem_cost=0, slot=0))
    g.doorway_drafts[(-1, 0)] = pending
    g.state.pending = pending
    g.phase = Phase.DRAFTING


def test_high_roller_grants_a_die_for_a_shop_drafted_at_the_outer_door():
    """Blessing of the High Roller pays on the once-per-day outer draft too.

    The Trading Post is a Shop in the outer pool, so it is only ever reachable
    through Game._choose_outer, never through the grid's Game._place_room. The
    blessing's trigger is "each time you draft a Shop" and reads nothing but the
    room's own categories, so the off-grid draft site must grant the die exactly
    as the grid site does -- the owner reported drafting the Trading Post under
    this blessing and receiving nothing.
    """
    g = Game(GameConfig(shrine_blessing_id="high_roller", shrine_blessing_days=3), seed=1)
    assert g.registry.by_id["trading_post"].is_category("shop"), (
        "setup: the Trading Post must be a Shop for this blessing to apply"
    )
    _outer_hand(g, "trading_post")
    before = g.state.dice
    g.choose(0)
    assert g.state.outer_room_drafted, "setup: the outer draft must have resolved"
    assert g.state.dice == before + 1


def test_high_roller_ignores_a_non_shop_drafted_at_the_outer_door():
    """The outer draft site is not a blanket die grant: the Root Cellar is a
    Green outer room, not a Shop, so the same blessing pays nothing for it.
    Pairs with the Trading Post case above to pin that the category check, not
    the draft site, is what decides."""
    g = Game(GameConfig(shrine_blessing_id="high_roller", shrine_blessing_days=3), seed=1)
    assert not g.registry.by_id["root_cellar"].is_category("shop"), (
        "setup: the Root Cellar must not be a Shop"
    )
    _outer_hand(g, "root_cellar")
    before = g.state.dice
    g.choose(0)
    assert g.state.dice == before


def test_shrine_curse_takes_its_category_loss_from_an_outer_draft():
    """The curse is the same draft-time hook as the blessing, so it must reach
    the outer draft symmetrically: drafting the Trading Post (a Shop) while
    cursed costs the published 1 coin. Without this, the outer door would be a
    free way to dodge the curse entirely."""
    g = Game(GameConfig(shrine_curse_days=2), seed=1)
    g.state.coins = 10
    _outer_hand(g, "trading_post")
    g.choose(0)
    assert g.state.coins == 9


def test_outer_draft_does_not_fire_the_grid_only_shrine_blessings():
    """No room in the outer pool is Red or Mechanical, so the General and
    Tinkerer blessings can never be triggered by an outer draft. This pins the
    blast radius of firing the Shrine's draft hook off-grid: exactly the High
    Roller and the curse, nothing else."""
    reg = Registry.load()
    outer = [r for r in reg.rooms if r.pool == "outer"]
    assert len(outer) == 8, "setup: the outer pool is the fixed 8 rooms"
    for room in outer:
        assert not room.is_category("red"), room.id
        assert not room.is_category("mechanical"), room.id


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


# --------------------------------------------------------------- data_dir cache


def test_load_shrine_rules_keeps_distinct_dirs_separate(tmp_path, registry):
    """load_shrine_rules memoises by data_dir identity for speed (a one-slot
    cache ahead of the path-keyed dict, skipping Path hashing on the hot path),
    but a genuinely different data_dir must still get its own answer: alternating
    calls between two dirs with different shrine.json contents must not return
    a stale value carried over from whichever dir was loaded most recently."""
    raw = json.loads((registry.data_dir / shrine.DATA_FILENAME).read_text())
    raw_bumped = json.loads(json.dumps(raw))  # deep copy
    for band in raw_bumped["bands"]:
        band["duration_days"] += 1

    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / shrine.DATA_FILENAME).write_text(json.dumps(raw))
    (dir_b / shrine.DATA_FILENAME).write_text(json.dumps(raw_bumped))

    rules_a = shrine.load_shrine_rules(dir_a)
    rules_b = shrine.load_shrine_rules(dir_b)
    assert rules_b.bands[0].duration_days == rules_a.bands[0].duration_days + 1

    # dir_a again, right after dir_b was the most recent call: must read
    # dir_a's own data, not the identity memo's leftover dir_b value.
    assert shrine.load_shrine_rules(dir_a).bands[0].duration_days == rules_a.bands[0].duration_days
