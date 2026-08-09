"""Tests for The Foundation: the room itself (draft.py's per-hand Rank-3 removal,
persistence across days via GameConfig/GameState/carryover/DayChain, and that it
still behaves like an ordinary drafted room). See docs/foundation-design.md.

Route-related behavior (the Basement/Sanctum chain the room unlocks) is Part 2's
concern and is out of scope here.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.env.multiday import DayChain

FOUNDATION_ID = "the_foundation"
DISK_ID = "upgrade_disk_the_foundation"

# A straight north-south chain of filler cells climbing the center column from
# the (pre-placed) Entrance Hall, used to reach Foundation-legal doorways
# without depending on what the ordinary draft RNG deals along the way.
RANK2_CELL = 7    # rank 2, col 2
RANK3_CELL = 12   # rank 3, col 2
RANK4_CELL = 17   # rank 4, col 2
RANK5_CELL = 22   # rank 5, col 2


def _chain_to(game: Game, *cells: int) -> None:
    """Hand-place inert Corridor fillers (N|S) at each cell, connecting the
    Entrance Hall northward one hop at a time, via the same placement path
    (``_place_room``) ``choose()`` uses -- so placed_ids/room_cells stay correct."""
    corridor = game.registry.by_id["corridor"]
    for cell in cells:
        game._place_room(corridor, cell, N | S)


def test_rank3_removal_reduces_dealt_rate_versus_rank4(registry: Registry):
    """A Rank-3 doorway deals the Foundation in materially fewer hands than a
    Rank-4 doorway, over many seeds -- pinning the wiki's 90%-removal-at-Rank-3
    rule as an actual reduction in how often the real deal_draft pipeline hands
    it out, not just a claim in a docstring."""
    cfg = GameConfig(door_locks=False, starting_steps=50, special_items=True)
    n = 6000

    def dealt_count(target_rank3: bool, seed0: int) -> int:
        hits = 0
        for seed in range(seed0, seed0 + n):
            game = Game(cfg, seed=seed, registry=registry)
            if target_rank3:
                _chain_to(game, RANK2_CELL)
                game.state.pos = RANK2_CELL
                pending = game.open_door(RANK2_CELL, N)  # target: RANK3_CELL
            else:
                _chain_to(game, RANK2_CELL, RANK3_CELL)
                game.state.pos = RANK3_CELL
                pending = game.open_door(RANK3_CELL, N)  # target: RANK4_CELL
            ids = {game.registry.rooms[o.room_idx].id for o in pending.options}
            if FOUNDATION_ID in ids:
                hits += 1
        return hits

    rank4_hits = dealt_count(False, seed0=0)
    rank3_hits = dealt_count(True, seed0=10_000_000)  # disjoint seed range
    assert rank4_hits > 0, "sanity: the Foundation must be dealt at all at Rank 4"
    # A generous margin against a 90% reduction: require Rank 3's rate to be
    # under a third of Rank 4's. Measured on this data set the gap is ~14x
    # (83/6000 at Rank 4 against 6/6000 at Rank 3), so a working roll clears the
    # bound with room to spare while sampling noise cannot trip it. The margin is
    # deliberately loose; the per-hand contract is pinned by the draw-count test
    # below, not by tightening this ratio into brittleness.
    assert rank3_hits * 3 < rank4_hits, (
        f"Rank 3 should deal the Foundation much less often than Rank 4: "
        f"rank3={rank3_hits}/{n}, rank4={rank4_hits}/{n}"
    )


def _count_foundation_draws(game: Game, cell: int) -> tuple[int, int]:
    """Deal one hand northward from ``cell`` and return (slots dealt, draws taken
    from the "foundation_rank3" substream). Wraps the real substream's ``random``
    so the count comes from the production path, not a re-implementation."""
    draws: list[None] = []
    stream = game.rng.stream("foundation_rank3")
    real_random = stream.random
    stream.random = lambda: (draws.append(None), real_random())[1]
    game.state.pos = cell
    pending = game.open_door(cell, N)
    return len(pending.options), len(draws)


def test_rank3_removal_is_exactly_one_roll_per_hand(registry: Registry):
    """A Rank-3 hand consumes exactly ONE draw from the "foundation_rank3"
    substream however many slots it fills, and a Rank-4 hand consumes none:
    rolling per card would make the draw count depend on deck order and break
    the seeded-replay invariant (see docs/foundation-design.md)."""
    cfg = GameConfig(door_locks=False, starting_steps=50, special_items=True)

    game = Game(cfg, seed=1, registry=registry)
    _chain_to(game, RANK2_CELL)
    slots, draws = _count_foundation_draws(game, RANK2_CELL)  # target: RANK3_CELL
    assert slots >= 2, "setup: the hand must fill several slots or one-per-card is untestable"
    assert draws == 1, f"a Rank-3 hand filling {slots} slots took {draws} draws, not 1"

    game = Game(cfg, seed=1, registry=registry)
    _chain_to(game, RANK2_CELL, RANK3_CELL)
    _slots, draws = _count_foundation_draws(game, RANK3_CELL)  # target: RANK4_CELL
    assert draws == 0, "only Rank 3 rolls; other ranks must leave the substream untouched"


def test_foundation_persists_across_reset_and_is_not_redealt(registry: Registry):
    """A Game built with cfg.foundation_cell/foundation_doors set starts the day
    with the Foundation already on that cell in that orientation, un-entered --
    and it is never dealt again, because it is already in placed_ids like any
    other room on the grid (the existing one-copy-on-the-grid rule)."""
    foundation = registry.by_id[FOUNDATION_ID]
    mask = N | S
    cfg = GameConfig(door_locks=False, starting_steps=50, special_items=True,
                     foundation_cell=RANK4_CELL, foundation_doors=mask)

    game = Game(cfg, seed=0, registry=registry)
    st = game.state
    assert st.grid[RANK4_CELL] == foundation.idx, "Foundation must be pre-placed at reset"
    assert st.placed_doors[RANK4_CELL] == mask, "orientation must match the frozen door mask"
    assert not st.entered[RANK4_CELL], "pre-placement must not fire ON_ENTER"
    assert FOUNDATION_ID in game.placed_ids
    assert game.room_cells[FOUNDATION_ID] == RANK4_CELL

    # Deterministic check: with it already placed (and its own north door open,
    # per ``mask``), no hand dealt northward from it ever deals a second copy
    # of itself, across many seeds.
    for seed in range(300):
        game = Game(cfg, seed=seed, registry=registry)
        game.state.pos = RANK4_CELL  # the pre-placed Foundation itself
        pending = game.open_door(RANK4_CELL, N)  # target: RANK5_CELL, still empty
        ids = {game.registry.rooms[o.room_idx].id for o in pending.options}
        assert FOUNDATION_ID not in ids, "already-placed Foundation must never be re-dealt"


def test_carryover_reports_foundation_placement_after_drafting(registry: Registry):
    """carryover()['foundation_cell'/'foundation_doors'] are -1/0 before it is
    drafted and match its cell/orientation once _place_room has placed it --
    the same site choose() uses, so this pins the real placement-recording hook."""
    from blueprince_sim.engine import shops

    cfg = GameConfig(door_locks=False, starting_steps=50, special_items=True)
    game = Game(cfg, seed=0, registry=registry)
    report = shops.carryover(game)
    assert report["foundation_cell"] == -1
    assert report["foundation_doors"] == 0

    foundation = registry.by_id[FOUNDATION_ID]
    game._place_room(foundation, RANK4_CELL, N | S)
    report = shops.carryover(game)
    assert report["foundation_cell"] == RANK4_CELL
    assert report["foundation_doors"] == N | S


def test_daychain_carries_foundation_placement_and_clears_on_wrap():
    """DayChain.next_config() reflects the Foundation's cell/doors the day after
    they are reported by carryover(), and a chain wrap (attempt restart) clears
    them back to unplaced -- the same lifecycle as every other permanent carry-over."""
    chain = DayChain(GameConfig(), n_days=3)
    assert chain.next_config().foundation_cell == -1
    assert chain.next_config().foundation_doors == 0

    chain.advance({"foundation_cell": RANK4_CELL, "foundation_doors": N | S})
    cfg2 = chain.next_config()
    assert cfg2.foundation_cell == RANK4_CELL
    assert cfg2.foundation_doors == N | S

    # Day 3 -> advance wraps the attempt back to day 1 with a clean slate.
    chain.advance({"foundation_cell": RANK4_CELL, "foundation_doors": N | S})
    chain.advance({"foundation_cell": RANK4_CELL, "foundation_doors": N | S})
    cfg3 = chain.next_config()
    assert cfg3.foundation_cell == -1, "a fresh attempt must put the Foundation back undrafted"
    assert cfg3.foundation_doors == 0


def test_foundation_can_be_drafted_and_entered_for_its_disk(registry: Registry):
    """The Foundation goes through the ordinary open_door/choose/move pipeline
    like any room, and entering it for the first time grants its guaranteed
    Upgrade Disk -- proving the persistence machinery doesn't short-circuit its
    normal draft/pickup behavior."""
    cfg = GameConfig(door_locks=False, starting_steps=100, special_items=True)
    foundation = registry.by_id[FOUNDATION_ID]

    for seed in range(1500):
        game = Game(cfg, seed=seed, registry=registry)
        _chain_to(game, RANK2_CELL, RANK3_CELL)
        game.state.pos = RANK3_CELL
        pending = game.open_door(RANK3_CELL, N)  # target: RANK4_CELL
        matches = [o for o in pending.options if o.room_idx == foundation.idx]
        if not matches:
            continue

        game.choose(matches[0].slot)
        assert game.state.grid[RANK4_CELL] == foundation.idx
        assert game.state.inventory.get(DISK_ID, 0) == 0, "disk must not be granted before entry"

        game.move(N)
        assert game.state.entered[RANK4_CELL]
        assert game.state.inventory.get(DISK_ID, 0) == 1, (
            "entering the Foundation must grant exactly one Upgrade Disk"
        )
        return

    raise AssertionError("the Foundation was never dealt across 1500 seeds at a legal doorway")
