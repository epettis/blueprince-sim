"""Tests for the Garage's Forced Draw and its car trunk.

The Forced Draw tests cover data/priority_draws.json "forced_draws"
(blueprince.wiki.gg/wiki/Garage). See draft.py's ``_forced_draw_garage`` /
``_garage_dead_end_gate``. Distinct from the pre-existing ``_priority_draw``
mechanism (patio group / commissary-observatory / classroom), which this does
not touch.

See tests/test_containers.py for the generic container-kind system
(trunks/chests/lockers), which uses other rooms (Attic, Locker Room) as
vehicles; the car trunk is a Garage-only mechanic and belongs here instead.
"""

from __future__ import annotations

from scipy import stats

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.draft import DraftContext, _garage_dead_end_gate
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import DraftOption, GameState
from blueprince_sim.env.actions import OPEN_CAR_TRUNK_ACTION, action_mask

GARAGE_ID = "garage"

# West Wing (col 0) cells, entered heading N -- legal Garage doorways (ranks 4-8).
SRC_A, TARGET_A = 15, 20   # rank4 -> rank5
SRC_B, TARGET_B = 25, 30   # rank6 -> rank7 (independent doorway, for the once-per-day test)

# Center column (col 2), entered heading N -- illegal for the Garage (not a wing),
# used to prove the mechanic never fires (and never even rolls) off-target.
CENTER_SRC, CENTER_TARGET = 17, 22


def _base_cfg(**kw) -> GameConfig:
    return GameConfig(door_locks=False, starting_steps=50, special_items=True, **kw)


def _place_corridor(game: Game, cell: int) -> None:
    """Hand-place an inert N|S corridor filler, mirroring test_foundation.py's
    ``_chain_to`` -- gives the source cell a north door without depending on
    what the ordinary draft RNG would have dealt there."""
    corridor = game.registry.by_id["corridor"]
    game._place_room(corridor, cell, N | S)


def _open_from(game: Game, cell: int, direction: int):
    game.state.pos = cell
    return game.open_door(cell, direction)


def _deal_at(cfg: GameConfig, seed: int, registry: Registry, src: int, direction: int):
    game = Game(cfg, seed=seed, registry=registry)
    _place_corridor(game, src)
    pending = _open_from(game, src, direction)
    return game, pending


def _offer_hits(cfg: GameConfig, registry: Registry, src: int, direction: int,
               n: int, seed0: int = 0) -> int:
    """Count, over ``n`` seeds, how many single-hand deals at ``(src, direction)``
    include the Garage among the dealt options."""
    garage_idx = registry.by_id[GARAGE_ID].idx
    hits = 0
    for seed in range(seed0, seed0 + n):
        game, pending = _deal_at(cfg, seed, registry, src, direction)
        if any(o.room_idx == garage_idx for o in pending.options):
            hits += 1
    return hits


def test_forced_draw_offer_rate_jumps_when_gate_satisfied(registry: Registry):
    """At a doorway where the Garage's placement conditions are always met (West
    Wing, rank 4->5, entered north), the offer rate goes from ~never (Day 2, gate
    unmet) to the wiki's ~90% (Day 5, gate met) -- pinning the Forced Draw as an
    actual behavior change in the real deal_draft pipeline, not just data.

    The Day-2 arm sets veteran_mode=False explicitly: the gate is "Veteran Mode
    OR Day 3", so leaving it to the config default would silently stop testing
    the day half of it once that default is veteran (which it now is).
    """
    n = 600
    before = _offer_hits(_base_cfg(day=2, veteran_mode=False), registry, SRC_A, N, n, seed0=0)
    after = _offer_hits(_base_cfg(day=5), registry, SRC_A, N, n, seed0=10_000_000)
    assert before < n * 0.05, f"Day 2 (gate unmet) offered the Garage {before}/{n} times"
    assert after > n * 0.6, f"Day 5 (gate met) only offered the Garage {after}/{n} times"


def test_forced_draw_blocked_before_day_3(registry: Registry):
    """The wiki's "Veteran Mode is active, or Day 3 has been reached" gate: Day 2
    with Veteran Mode off must not trigger the Forced Draw, even though the same
    doorway lights up dramatically on Day 3."""
    n = 400
    day2 = _offer_hits(_base_cfg(day=2, veteran_mode=False), registry, SRC_A, N, n, seed0=0)
    day3 = _offer_hits(_base_cfg(day=3, veteran_mode=False), registry, SRC_A, N, n,
                       seed0=10_000_000)
    assert day2 == 0, f"Forced Draw must not fire before Day 3: got {day2}/{n} on Day 2"
    assert day3 > n * 0.6, f"Forced Draw should be active on Day 3: got {day3}/{n}"


def test_forced_draw_veteran_mode_substitutes_for_day_gate(registry: Registry):
    """Veteran Mode alone (independent of the day counter) satisfies the same
    gate as Day 3+ -- the wiki phrases the two as alternatives ("or"), and a
    Day-2 veteran run must behave like the Day-5 case above, not the Day-2 one."""
    n = 400
    hits = _offer_hits(_base_cfg(day=2, veteran_mode=True), registry, SRC_A, N, n, seed0=0)
    assert hits > n * 0.6, f"Veteran Mode should unlock the Forced Draw pre-Day-3: {hits}/{n}"


def test_forced_draw_west_gate_boosts_success_chance(registry: Registry):
    """The wiki's West Gate boost (90% -> 92.5%) is a small but real, measurable
    increase in offer rate at the same always-legal doorway -- large N because the
    effect size is only 2.5 points, unlike the Day-3 gate's all-or-nothing jump."""
    n = 20_000
    without = _offer_hits(_base_cfg(day=5, west_gate_unlatched=False), registry, SRC_A, N, n,
                          seed0=0)
    with_gate = _offer_hits(_base_cfg(day=5, west_gate_unlatched=True), registry, SRC_A, N, n,
                            seed0=30_000_000)
    table = [[without, n - without], [with_gate, n - with_gate]]
    _, p, _, _ = stats.chi2_contingency(table)
    assert with_gate > without, (without, with_gate)
    assert p < 0.01, (
        f"West Gate boost not statistically distinguishable: without={without}/{n} "
        f"with={with_gate}/{n} p={p}"
    )


def test_forced_draw_never_fires_at_an_illegal_doorway(registry: Registry):
    """Off a doorway where the Garage's own draft conditions fail (here: center
    column, never a "wing"), the Forced Draw must not fire -- and must consume no
    randomness at all, so doorways where the Garage was never a candidate cannot
    perturb any other draw's RNG stream (see draft.py's eligibility-first design
    and the sibling "the Foundation" rank-3 mechanic's identical contract)."""
    cfg = _base_cfg(day=10, veteran_mode=True)  # gate wide open; only geometry should matter
    garage_idx = registry.by_id[GARAGE_ID].idx
    for seed in range(50):
        game, pending = _deal_at(cfg, seed, registry, CENTER_SRC, N)
        assert not any(o.room_idx == garage_idx for o in pending.options), (
            "Garage must never be dealt at a doorway where its own conditions fail"
        )
        # The "forced_draw_garage" RNG substream is created lazily on first use
        # (engine/rng.py::Rng.stream); if it was never created, the roll was
        # never attempted, proving zero perturbation of unrelated draws.
        assert "forced_draw_garage" not in game.rng._streams, (
            "an ineligible doorway must not consume the forced-draw RNG stream"
        )


def test_forced_draw_fires_at_most_once_per_day(registry: Registry):
    """Once the per-day flag is set (a real success already happened), the Forced
    Draw must not re-trigger at a second, independent legal doorway the same
    day -- the wiki: "they will no longer be available for Forced Draws" once
    the roll has succeeded, even on a fresh empty doorway elsewhere in the house."""
    cfg = _base_cfg(day=5, veteran_mode=False)
    garage_idx = registry.by_id[GARAGE_ID].idx
    game = Game(cfg, seed=7, registry=registry)
    game.state.garage_forced_draw_succeeded = True  # simulate an earlier success today
    _place_corridor(game, SRC_B)
    pending = _open_from(game, SRC_B, N)
    assert not any(o.room_idx == garage_idx and o.forced for o in pending.options), (
        "a second legal doorway must not force-draw the Garage once today's roll "
        "has already succeeded"
    )


def test_forced_draw_is_deterministic_for_a_given_seed(registry: Registry):
    """Same seed, same doorway -> identical dealt hand (room/orientation/cost/slot/
    forced/hidden for every option) -- the engine's seeded-replay invariant must
    hold for the new mechanic exactly like every other RNG-driven draft feature."""
    cfg = _base_cfg(day=5)

    def _snapshot(seed: int):
        _game, pending = _deal_at(cfg, seed, registry, SRC_A, N)
        return [(o.room_idx, o.orientation, o.gem_cost, o.slot, o.forced, o.hidden)
                for o in pending.options]

    for seed in (1, 2, 3, 42):
        assert _snapshot(seed) == _snapshot(seed), f"seed {seed} was not deterministic"


# ---------------------------------------------------------------------------
# _garage_dead_end_gate
# ---------------------------------------------------------------------------

def _gate_ctx(registry: Registry) -> DraftContext:
    """Minimal DraftContext for _garage_dead_end_gate, which only reads
    ``ctx.registry.rooms`` -- mirrors test_mechanarium.py's own ``_ctx``."""
    return DraftContext(GameState(), registry, GameConfig(), Rng(0), set(), None)


def _option(registry: Registry, room_id: str, orientation: int, slot: int,
            forced: bool = False) -> DraftOption:
    room_idx = registry.by_id[room_id].idx
    return DraftOption(room_idx=room_idx, orientation=orientation, gem_cost=0, slot=slot,
                       forced=forced)


def test_garage_gate_passes_when_a_corner_drafted_greenhouse_fills_a_dead_end_slot(
        registry: Registry):
    """The Greenhouse's frozen Room.layout is "dead_end", but a corner-oriented
    draft (door mask 3) has two doors and is not one. With it in slot 0 and a
    real Dead End (Closet) in slot 1, "both slots are Dead Ends" is false, so
    the gate passes (does not block the Forced Draw attempt)."""
    greenhouse = registry.by_id["greenhouse"]
    corner_mask = 3  # S|E -- one of the Greenhouse's gated corner rotations
    assert corner_mask in greenhouse.gated_rotations, "setup: corner rotation must be a real shape"
    closet = registry.by_id["closet"]
    assert closet.layout == "dead_end", "setup: Closet must be a Dead End"
    options = [
        _option(registry, "greenhouse", corner_mask, slot=0),
        _option(registry, "closet", closet.door_mask, slot=1),
    ]
    assert _garage_dead_end_gate(_gate_ctx(registry), options) is True


def test_garage_gate_blocks_when_a_dead_end_drafted_greenhouse_fills_a_dead_end_slot(
        registry: Registry):
    """The same Greenhouse, drafted in its one-door canonical orientation, IS
    a Dead End: paired with another Dead End (Closet) in slot 1 by a normal
    (non-forced) draw, the gate blocks the Forced Draw attempt -- the
    contrast with the corner case above proves the gate follows the drafted
    orientation, not a blanket exemption for the Greenhouse id."""
    greenhouse = registry.by_id["greenhouse"]
    closet = registry.by_id["closet"]
    options = [
        _option(registry, "greenhouse", greenhouse.door_mask, slot=0),
        _option(registry, "closet", closet.door_mask, slot=1),
    ]
    assert _garage_dead_end_gate(_gate_ctx(registry), options) is False


def test_garage_gate_passes_when_slot_1_dead_end_was_forced(registry: Registry):
    """Two Dead Ends in slots 0/1 only block the gate when slot 1 came from a
    normal roll-based draw -- ``forced=True`` (priority/forced draw, Tunnel
    chain, forced-Closet fallback) leaves the gate open."""
    closet = registry.by_id["closet"]
    options = [
        _option(registry, "closet", closet.door_mask, slot=0),
        _option(registry, "closet", closet.door_mask, slot=1, forced=True),
    ]
    assert _garage_dead_end_gate(_gate_ctx(registry), options) is True


def test_garage_gate_passes_when_a_lone_mechanarium_fills_a_dead_end_slot(registry: Registry):
    """A Mechanarium with no other Mechanical room on the estate is drafted
    with a genuine single-door mask (draft.py's _mechanarium_orientation),
    but its card is printed "cross", never "dead_end" -- the wiki is explicit
    that it never counts as a Dead End (see test_mechanarium.py). Paired with
    a real Dead End (Closet) in slot 1, the gate must still pass."""
    mechanarium = registry.by_id["mechanarium"]
    assert not mechanarium.is_dead_end_capable, "setup: Mechanarium must never be Dead-End-capable"
    closet = registry.by_id["closet"]
    options = [
        _option(registry, "mechanarium", N, slot=0),  # single-door mask, as if lone-drafted
        _option(registry, "closet", closet.door_mask, slot=1),
    ]
    assert _garage_dead_end_gate(_gate_ctx(registry), options) is True


# ---------------------------------------------------------------------------
# car trunk
# ---------------------------------------------------------------------------

def _state_with_registry():
    reg = Registry.load()
    st = GameState()
    st.special.enabled = True
    return st, reg


def _fake_game(state, registry, seed=0, cfg=None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    g.cfg = cfg or GameConfig()
    g._garage_ids = tuple(r.id for r in registry.rooms if r.id.startswith("garage"))
    return g


def _place_room(state, registry, room_id: str, cell: int) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


def test_garage_car_first_use_grants_upgrade_disk():
    """Car Keys first use () grants upgrade_disk_garage (unique per source)."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig())
    assert si.can_open_car_trunk(game)
    granted = si.open_car_trunk(game)
    assert "upgrade_disk_garage" in granted or st.inventory.get("upgrade_disk_garage", 0) > 0, \
        "first car trunk use must grant upgrade_disk_garage"


def test_garage_car_later_use_regranted_disk_when_not_spent():
    """Trunk opened on an earlier day but disk NOT spent: re-grants upgrade_disk_garage.

    The trunk re-locks nightly, so this re-open still costs Car Keys; what carries
    over is the disk, which returns until the player spends it (inserts at a
    terminal). Without the disk in collected_disks the engine re-grants it.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig()
    game = _fake_game(st, reg, seed=1, cfg=cfg)
    si.configure(st, cfg)
    si.open_car_trunk(game)
    assert st.inventory.get("upgrade_disk_garage", 0) == 1, (
        "trunk opened before but disk not spent -> disk re-granted from open trunk"
    )


def test_garage_car_draws_from_pool_after_disk_spent():
    """Once upgrade_disk_garage is spent, later trunk uses draw from the later_pool.

    With the disk id in collected_disks, the engine treats the disk as permanently
    gone and falls through to the pool-draw path (items + coins).
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig(
        collected_disks=frozenset({"upgrade_disk_garage"}),
    )
    game = _fake_game(st, reg, seed=1, cfg=cfg)
    si.configure(st, cfg)
    granted = si.open_car_trunk(game)
    later_pool = reg.special.containers.get("garage_car", {}).get("later_pool", [])
    later_gold = reg.special.containers.get("garage_car", {}).get("later_gold", 5)
    coins_granted = st.coins >= later_gold
    items_granted = any(iid in later_pool for iid in granted)
    assert coins_granted or items_granted, (
        "after disk spent, later trunk use must grant gold and/or pool items"
    )


def test_garage_car_once_per_day():
    """Car trunk can only be opened once per day; second call is blocked."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig())
    si.open_car_trunk(game)
    assert st.special.garage_car_opened is True
    assert not si.can_open_car_trunk(game), "car trunk already opened today"


def test_garage_car_requires_car_keys():
    """can_open_car_trunk is False without Car Keys even when standing in the Garage."""
    st, reg = _state_with_registry()
    _place_room(st, reg, "garage", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0)
    assert not si.can_open_car_trunk(game), "must hold Car Keys to open car trunk"


def test_garage_car_trunk_recognized_via_garage_ids_membership():
    """can_open_car_trunk keys off membership in game._garage_ids, not a literal
    "garage" id comparison.

    _garage_ids is built from every room id starting with "garage" (game.py),
    which already includes "garage" itself -- so a future garage upgrade variant
    id would be recognized purely by appearing in that tuple, with no extra
    code. This stands a non-garage room in for such a variant by overriding
    _garage_ids to include its id, proving the check is pure membership.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "car_keys", source="test")
    _place_room(st, reg, "corridor", 5)
    st.pos = 5

    game = _fake_game(st, reg, seed=0, cfg=GameConfig())
    game._garage_ids = ("corridor",)  # stand-in for a garage variant id
    assert si.can_open_car_trunk(game), (
        "membership in _garage_ids must be sufficient regardless of the room's own id"
    )


def test_open_car_trunk_action_masked():
    """OPEN_CAR_TRUNK_ACTION is True when Car Keys held in the Garage."""
    g = Game(GameConfig(starting_items=frozenset({"car_keys"})), seed=42)
    garage = g.registry.by_id["garage"]
    cell = 5
    g.state.grid[cell] = garage.idx
    g.state.placed_doors[cell] = garage.door_mask
    g.state.entered[cell] = True
    g.state.pos = cell
    mask = action_mask(g)
    assert mask[OPEN_CAR_TRUNK_ACTION]


def test_garage_disk_is_not_marked_collected_by_opening_alone():
    """Opening the trunk without inserting the disk leaves collected_disks empty.

    Only spending a disk at a terminal retires it. Opening the container is not
    itself consumption, so the next day must still be able to offer the disk.
    """
    from blueprince_sim.env.multiday import DayChain
    base = GameConfig(starting_items=frozenset({"car_keys"}))
    chain = DayChain(base, n_days=5)
    game = Game(chain.next_config(), seed=4)
    game.state.special.garage_car_opened = True  # the trunk was opened today
    chain.advance(game.carryover())
    assert "upgrade_disk_garage" not in chain.next_config().collected_disks, (
        "opening the trunk must not retire the disk; only spending it does"
    )
