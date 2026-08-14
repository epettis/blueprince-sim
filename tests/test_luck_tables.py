"""Distributional guards for the two published tables PR-B adds on top of
data/items.json's item_ladder (engine/items.py's ``roll_room_items``):
``never_roll_rooms`` (rooms that skip the ladder roll entirely, including
the Luck Penalty increase) and ``count_transforms`` (Nook/Study/Guest
Bedroom/Den's per-room transforms of the ladder's raw extra-item count, plus
Lost & Found's deliberately-unwired entry).

Hard rule, followed throughout (same as test_luck_ladder.py): no expected
value here is derived by calling the function under test on ITSELF for its
own answer, nor by reading data/items.json (the same file engine/items.py
reads) to build an expectation. Every wiki percentage is a hand-typed
literal, with the verbatim wiki line quoted in the test that uses it.

Source: https://blueprince.wiki.gg/wiki/Luck, "Luck effects" DataMinedBox
(never_roll_rooms), plus the Nook/Study/Guest Bedroom/Den/Lost & Found wiki
pages' own DataMinedBoxes (count_transforms) -- all fetched directly during
this PR (raw wikitext, not rendered HTML).
"""

from __future__ import annotations

import math

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import items
from blueprince_sim.engine.game import Game

N = 200_000  # matches test_luck_ladder.py's per-band trial count


def _assert_within_binomial_ci(observed: int, n: int, p: float, where: str, z: float = 5.5) -> None:
    """Assert an observed count is within a z-sigma normal-approximation
    binomial interval of n*p (same z=5.5 generous margin as
    test_luck_ladder.py -- roughly a 1-in-20-million two-sided false-failure
    rate per assertion)."""
    mean = n * p
    sd = math.sqrt(n * p * (1 - p))
    margin = z * sd
    assert abs(observed - mean) <= margin, (
        f"{where}: observed {observed}/{n} = {observed / n:.5f}, expected {p:.5f} "
        f"+/- {margin / n:.5f} ({z} sigma)"
    )


@pytest.fixture()
def game(registry) -> Game:
    return Game(GameConfig(), seed=1234, registry=registry)


# ------------------------------------------------- 1. never_roll_rooms table

def test_never_roll_room_yields_zero_items_and_no_penalty_increase(game, registry):
    """Wiki: "Not every room rolls for luck. The rooms that don't completely
    skip this step, including the Luck Penalty increase. ... The following
    rooms never roll for luck: [Entrance Hall, ...]."

    Entrance Hall (additional_max=1, guaranteed=[]) at luck 30 -- the 29+
    "fixed" band, which would deterministically hand out 4 items and +3 Luck
    Penalty to any ROLLING room -- must still yield exactly 0 extra items
    and 0 Luck Penalty, across many seeds, because it never rolls at all.
    """
    room = registry.by_id["entrance_hall"]
    assert room.items.additional_max >= 1, "fixture must actually have a slot to leak from"
    for seed in range(50):
        g = Game(GameConfig(), seed=seed, registry=registry)
        g.state.luck = 30
        coins0, keys0, gems0, dice0 = g.state.coins, g.state.keys, g.state.gems, g.state.dice
        found = items.roll_room_items(g, room)
        assert found == 0, f"seed {seed}: never-roll room must yield 0 items"
        assert (g.state.coins, g.state.keys, g.state.gems, g.state.dice) == (
            coins0, keys0, gems0, dice0), f"seed {seed}: no resource may change"
        assert g.state.luck_penalty == 0, (
            f"seed {seed}: never-roll room must never touch the Luck Penalty")


def test_never_roll_vs_rolling_room_penalty_contrast(game, registry):
    """Wiki, same DataMinedBox: "(Rooms that do roll for luck and then
    discard the result still increase the Luck Penalty.)"

    Kitchen (additional_max=0, NOT in never_roll_rooms) at luck 30 (29+
    fixed band, deterministic +3 penalty) must still pay the Luck Penalty
    even though its additional_max=0 clamp discards every rolled item --
    the direct contrast with Entrance Hall's 0-penalty behaviour above.
    """
    kitchen = registry.by_id["kitchen"]
    assert kitchen.items.additional_max == 0, "fixture must actually discard its roll"
    for seed in range(20):
        g = Game(GameConfig(), seed=seed, registry=registry)
        g.state.luck = 30
        found = items.roll_room_items(g, kitchen)
        assert found == 0, "additional_max=0 discards the roll's items"
        assert g.state.luck_penalty == 3, (
            "a room that rolls and discards must still pay the 29+ band's +3 penalty")


def test_room_absent_from_both_tables_is_unaffected(registry):
    """Bedroom (additional_max=1, guaranteed=[]) is in neither
    never_roll_rooms nor count_transforms: at luck 25 (23-28 fixed band,
    deterministic 3 items + 2 penalty), it must show the ladder's plain,
    untransformed behaviour -- exactly 1 extra item (3 clamped to
    additional_max=1) and +2 Luck Penalty, with no table lookup altering
    either number.
    """
    registry_ = registry
    room = registry_.by_id["bedroom"]
    assert room.items.additional_max == 1
    for seed in range(20):
        g = Game(GameConfig(), seed=seed, registry=registry_)
        g.state.luck = 25
        found = items.roll_room_items(g, room)
        assert found == 1, "3-item ladder roll clamped to additional_max=1"
        assert g.state.luck_penalty == 2, "23-28 band's own +2 penalty, untouched by any transform"


# ---------------------------------------------------- 2. count_transforms

def test_nook_reduce_by_one_chance(game, registry):
    """Nook wiki (DataMinedBox): "This room uses the standard luck item
    spawning algorithm. There is a 20% chance to reduce the number of items
    by 1."

    Isolates _apply_count_transform (the function actually consulted by
    roll_room_items) at raw=1: ~20% of calls must reduce it to 0, the rest
    must leave it at 1, and the transform never grants a bonus item.
    """
    room = registry.by_id["nook"]
    reduced = 0
    for _ in range(N):
        raw, bonus = items._apply_count_transform(game, room, 1)
        assert bonus == 0
        assert raw in (0, 1)
        if raw == 0:
            reduced += 1
    _assert_within_binomial_ci(reduced, N, 0.20, "Nook reduce_by_one_chance")


def test_nook_reduce_by_one_chance_floors_at_zero(game, registry):
    """Same Nook transform, called at raw=0: "reduce ... by 1" must never
    take the count negative -- the room simply stays at 0 either way."""
    room = registry.by_id["nook"]
    for _ in range(1000):
        raw, bonus = items._apply_count_transform(game, room, 0)
        assert raw == 0
        assert bonus == 0


def test_study_zero_becomes_one(game, registry):
    """Study wiki (DataMinedBox): "This room uses the standard luck item
    spawning algorithm. If 0 items is selected, it provides 1 item
    instead."

    Deterministic (no chance roll): raw=0 must ALWAYS become 1; any other
    raw value must pass through unchanged.
    """
    room = registry.by_id["study"]
    for _ in range(200):
        raw, bonus = items._apply_count_transform(game, room, 0)
        assert (raw, bonus) == (1, 0), "raw=0 must deterministically become 1"
    for original in (1, 2, 3):
        raw, bonus = items._apply_count_transform(game, room, original)
        assert (raw, bonus) == (original, 0), "a non-zero raw count must pass through untouched"


def test_guest_bedroom_zero_becomes_one_or_gem(game, registry):
    """Guest Bedroom wiki (DataMinedBox): "The room uses luck to spawn items
    as usual. If 0 items is rolled, there is a 50% chance to increase it to
    1 item, or a 30% chance to spawn 1 gem."

    Read as sequential/first-match (items.json's count_transforms.meta
    documents this as a judgment call: the wiki does not independently
    state whether the two chances are exclusive): the 50% roll is checked
    first (-> 1 item, no bonus gem); only on failure is the 30% gem roll
    checked. That composition means, over many raw=0 calls: P(becomes 1
    item) = 50%, P(bonus gem, stays 0 items) = 50% * 30% = 15%, P(stays 0,
    nothing) = 50% * 70% = 35% -- these three literals are hand-derived
    from the two independently wiki-quoted percentages, not read back from
    the transform's own output distribution.
    """
    room = registry.by_id["guest_bedroom"]
    became_one = gem = neither = 0
    for _ in range(N):
        raw, bonus = items._apply_count_transform(game, room, 0)
        if raw == 1:
            assert bonus == 0
            became_one += 1
        elif bonus == 1:
            assert raw == 0
            gem += 1
        else:
            assert (raw, bonus) == (0, 0)
            neither += 1
    assert became_one + gem + neither == N
    _assert_within_binomial_ci(became_one, N, 0.50, "Guest Bedroom -> 1 item")
    _assert_within_binomial_ci(gem, N, 0.15, "Guest Bedroom -> bonus gem")
    _assert_within_binomial_ci(neither, N, 0.35, "Guest Bedroom -> neither")


def test_guest_bedroom_transform_only_fires_at_zero(game, registry):
    """The Guest Bedroom transform is gated on "If 0 items is rolled" -- a
    non-zero raw count must never be touched (no upgrade to more items, no
    bonus gem)."""
    room = registry.by_id["guest_bedroom"]
    for original in (1, 2, 3):
        raw, bonus = items._apply_count_transform(game, room, original)
        assert (raw, bonus) == (original, 0)


def test_den_one_becomes_trunk(registry):
    """Den wiki (DataMinedBox): "The room uses the standard luck item
    spawning algorithm, with the item pool being the items above (not
    including the trunk). If 1 item is selected, the item is always
    replaced with the trunk."

    Den's additional_max=1, so ANY raw ladder roll >=1 clamps to exactly 1
    extra item; luck=25 (23-28 fixed band) makes the raw roll a
    deterministic 3, so this always exercises the one-item slot. The trunk
    is resolved by instantly granting one of data/special_items.json's
    containers.kinds.trunk.loot entries (engine/items.py's
    _grant_trunk_loot) rather than the plain EXTRA_ITEM_TABLE roll -- and
    unlike EXTRA_ITEM_TABLE (which only ever grants exactly 1 of a single
    resource kind per extra-item slot), several trunk loot entries grant
    MULTIPLE resources from one slot, including a 2-dice grant that
    EXTRA_ITEM_TABLE's own "die" outcome (always exactly 1 die) can never
    produce. Seeing dice go up by exactly 2 in a single roll is therefore
    proof the trunk table -- not EXTRA_ITEM_TABLE -- is what actually paid
    out, without this test needing to read (or re-derive percentages from)
    special_items.json itself.
    """
    room = registry.by_id["den"]
    saw_double_dice = False
    for seed in range(300):
        g = Game(GameConfig(), seed=seed, registry=registry)
        g.state.luck = 25
        dice0 = g.state.dice
        items.roll_room_items(g, room)
        if g.state.dice - dice0 == 2:
            saw_double_dice = True
            break
    assert saw_double_dice, (
        "300 Den rolls at a forced 1-item slot never produced a 2-dice trunk grant -- "
        "the one_becomes_trunk transform does not appear to be live")


def test_lost_and_found_not_modeled_is_a_documented_no_op(registry):
    """Lost & Found wiki (DataMinedBox): "One item is added to the result,
    and the item count then clamped to be in 2-4." -- NOT wired live.
    items.json's count_transforms.meta records the judgment call: this sim
    already models Lost & Found's items through a separate, pre-existing
    mechanism (special_items.lost_and_found_on_enter, a fixed luck-
    independent pool draw) that bypasses additional_max/item_ladder
    entirely (additional_max=0 in rooms.json). Wiring the wiki's ladder
    clamp on top of that would double-grant items, so count_transforms
    records the room as "not_modeled" -- a deliberate no-op.

    This test pins that the ladder path still behaves exactly like an
    ordinary additional_max=0 room (0 extra items via this path, but the
    Luck Penalty still accrues per the general "rolls and discard" rule),
    NOT like the wiki's 2-4 item range -- i.e. the gap is real and this
    room's live item count still comes entirely from the separate
    lost_and_found_on_enter mechanism, untouched by this PR.
    """
    room = registry.by_id["lost_and_found"]
    assert room.items.additional_max == 0
    for seed in range(20):
        g = Game(GameConfig(), seed=seed, registry=registry)
        g.state.luck = 30  # 29+ fixed band: deterministic raw=4, +3 penalty
        found = items.roll_room_items(g, room)
        assert found == 0, "not_modeled must not grant the wiki's 2-4 items via this path"
        assert g.state.luck_penalty == 3, "still an ordinary roll-and-discard room, not never-roll"
