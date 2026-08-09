"""Allowance: a permanent, per-attempt gold total paid out at the start of
every future day.

Unlike the Tomorrow Rooms (Sauna, Morning Room, Freezer, Break Room), which
apply for exactly one following day and lapse, allowance is a running total
that keeps paying out every day once earned -- the same shape as
GameConfig.chapel_tithes and Game.reset's "+2 gems from mine_unlocked" bonus.
It is grown by two mechanisms:

- Allowance Token pickups (+2 each): a shared repeatable id
  ("allowance_token", Trading Post trades / Jack Hammer digging / the two
  Vault boxes) and several dedicated one-time ids, one per fixed find spot
  (a Mora Jai box or the Cloister's own token), gated permanently across days
  via GameConfig.collected_allowance_tokens so a specific spot cannot be
  re-collected once taken.
- Cloister of Lydia: +2 per Shop drafted from that Cloister (see
  tests/rooms/test_cloister.py for the room-hook coverage).

Tests drive the real DayChain carryover path (not just Game.reset()), because
reset() alone does not apply carryover and would give false negatives for the
day N+1 / day N+2 permanence claim.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.shops import carryover
from blueprince_sim.env.multiday import DayChain


def _place(state, registry, room_id: str, cell: int) -> None:
    """Put room_id on the grid at cell without going through the draft pipeline."""
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


# ---------------------------------------------------------------------------
# The daily packet: added to coins at reset(), inert when zero
# ---------------------------------------------------------------------------

def test_zero_allowance_grants_nothing_at_reset(registry):
    """cfg.allowance == 0 leaves both state.allowance and starting coins at 0.

    The wiki: the packet only appears when the total is nonzero; adding zero
    at reset() reproduces that without a conditional branch.
    """
    g = Game(GameConfig(allowance=0), seed=1, registry=registry)
    assert g.state.allowance == 0
    assert g.state.coins == 0


def test_nonzero_allowance_is_folded_into_starting_coins(registry):
    """cfg.allowance == 7 gives the day both state.allowance == 7 and 7 starting coins."""
    g = Game(GameConfig(allowance=7), seed=1, registry=registry)
    assert g.state.allowance == 7
    assert g.state.coins == 7


# ---------------------------------------------------------------------------
# Allowance Token: +2, and consumed rather than held
# ---------------------------------------------------------------------------

def test_allowance_token_grants_two_and_is_consumed(registry):
    """Picking up the shared allowance_token adds 2 to state.allowance and
    leaves nothing behind in inventory -- it converts straight to allowance."""
    g = Game(GameConfig(), seed=1, registry=registry)
    si.grant(g.state, g.registry, "allowance_token", source="test")
    assert g.state.allowance == 2
    assert g.state.inventory.get("allowance_token", 0) == 0


def test_two_allowance_tokens_stack_to_four(registry):
    """Two separate Allowance Token pickups the same day add up, not overwrite."""
    g = Game(GameConfig(), seed=1, registry=registry)
    si.grant(g.state, g.registry, "allowance_token", source="test")
    si.grant(g.state, g.registry, "allowance_token", source="test")
    assert g.state.allowance == 4


# ---------------------------------------------------------------------------
# Permanence: earned on day N, paid out on day N+1 AND day N+2
# ---------------------------------------------------------------------------

def test_allowance_pays_out_on_day_n_plus_1_and_n_plus_2_via_daychain(registry):
    """An Allowance Token earned on day 1 shows up as coins on day 2, and
    AGAIN on day 3 with no further action -- this is what distinguishes
    allowance from a Tomorrow Room's one-day pulse (sauna_bonus etc.)."""
    chain = DayChain(GameConfig(), n_days=200)

    # Day 1: earn +2 allowance, nothing else.
    g1 = Game(chain.next_config(), seed=1, registry=registry)
    si.grant(g1.state, g1.registry, "allowance_token", source="test")
    chain.advance(carryover(g1))

    # Day 2: the total pays out as starting coins, with no new gain today.
    day2_cfg = chain.next_config()
    assert day2_cfg.allowance == 2
    g2 = Game(day2_cfg, seed=2, registry=registry)
    assert g2.state.coins == 2
    assert g2.state.allowance == 2
    chain.advance(carryover(g2))

    # Day 3: still paying out the same total -- permanent, not a one-day pulse.
    day3_cfg = chain.next_config()
    assert day3_cfg.allowance == 2
    g3 = Game(day3_cfg, seed=3, registry=registry)
    assert g3.state.coins == 2
    assert g3.state.allowance == 2


def test_a_day_with_no_new_allowance_still_pays_the_accumulated_total():
    """DayChain.advance() with no "allowance" key leaves the running total
    untouched -- a quiet day does not reset the packet to zero."""
    chain = DayChain(GameConfig(), n_days=200)
    chain.advance({"allowance": 4})
    assert chain.next_config().allowance == 4

    chain.advance({})  # no allowance key this day: nothing new earned
    assert chain.next_config().allowance == 4


def test_allowance_clears_on_attempt_wrap():
    """A fresh attempt (DayChain wrap past n_days) drops the allowance total
    back to the base preset, the same as every other carry-over discovery."""
    chain = DayChain(GameConfig(), n_days=1)
    chain.advance({"allowance": 6})  # day 1 -> wraps immediately

    assert chain.current_day == 1
    assert chain.next_config().allowance == 0


# ---------------------------------------------------------------------------
# One-time sources: a Mora Jai box token cannot be re-collected on a later day
# ---------------------------------------------------------------------------

def test_master_bedroom_token_is_one_time_across_days(registry):
    """The Master Bedroom's Mora Jai box pays +2 allowance once; re-entering
    the room on a LATER day does not pay out a second time.

    Exercises GameConfig.collected_allowance_tokens end to end: carryover()
    reports the source id, DayChain accumulates it, and configure() gates it
    out of _is_available on the following day -- the same shape proven for
    collected_disks in tests/test_disk_respawn.py.
    """
    # Day 1: first entry pays out.
    g1 = Game(GameConfig(special_items=True), seed=1, registry=registry)
    _place(g1.state, g1.registry, "master_bedroom", 10)
    room = g1.registry.by_id["master_bedroom"]
    si.on_enter(g1, room, 10)
    assert g1.state.allowance == 2

    carry = carryover(g1)
    assert "allowance_token_master_bedroom" in carry["collected_allowance_tokens"]

    # Day 2: carried config gates the same source id out.
    day2_cfg = GameConfig(
        special_items=True,
        allowance=carry["allowance"],
        collected_allowance_tokens=frozenset(carry["collected_allowance_tokens"]),
    )
    g2 = Game(day2_cfg, seed=2, registry=registry)
    assert g2.state.allowance == 2  # carried total, no new gain yet

    _place(g2.state, g2.registry, "master_bedroom", 10)
    si.on_enter(g2, room, 10)
    assert g2.state.allowance == 2, (
        "a later day's entry must not re-pay the Master Bedroom's one-time token"
    )
