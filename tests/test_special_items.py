"""Special items: core behavior (spawn, pickup effects, food pipeline, coins)."""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState


# ---------------------------------------------------------- helpers / fixtures

def _registry() -> Registry:
    return Registry.load()


def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _state_with_registry():
    """A fresh GameState plus the Registry (for unit-level tests that skip Game)."""
    reg = _registry()
    st = GameState()
    st.special.enabled = True
    return st, reg


# ---------------------------------------------------------- unique / stacking

def test_unique_items_never_stack():
    """Granting a unique item a second time is a no-op; inventory stays at 1.

    Uniqueness is the core invariant — a second grant must be silently dropped,
    not silently added, so the player never carries two copies of a one-of item.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "shovel", source="test")
    si.grant(st, reg, "shovel", source="test")
    assert st.inventory.get("shovel", 0) == 1


def test_nonunique_item_stacks():
    """Non-unique items (prism_key, repellent, …) can stack; each grant increments count."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "prism_key", source="test")
    si.grant(st, reg, "prism_key", source="test")
    assert st.inventory.get("prism_key", 0) == 2


# ---------------------------------------------------------- Cursed Effigy

def test_cursed_effigy_clamps_steps_from_above():
    """The Cursed Effigy sets steps to 13 only when the player currently has more.

    This is the "cursed" mechanic: picking it up from a high-step position caps
    your budget, but picking it up at or below 13 is harmless.
    """
    st, reg = _state_with_registry()
    st.special.gated_out = []  # allow cursed_effigy
    st.steps = 40
    si.grant(st, reg, "cursed_effigy", source="test")
    assert st.steps == 13


def test_cursed_effigy_does_not_clamp_from_below():
    """Picking up the Cursed Effigy with steps <= 13 leaves steps unchanged."""
    st, reg = _state_with_registry()
    st.special.gated_out = []
    st.steps = 10
    si.grant(st, reg, "cursed_effigy", source="test")
    assert st.steps == 10


# ---------------------------------------------------------- Watering Can

def test_watering_can_fills_on_pickup():
    """The Watering Can's water counter is set to its capacity (3) on pickup."""
    st, reg = _state_with_registry()
    assert st.special.water == 0
    si.grant(st, reg, "watering_can", source="test")
    assert st.special.water == 3


# ---------------------------------------------------------- Stopwatch

def test_stopwatch_activates_on_pickup():
    """Picking up the Stopwatch starts stopwatch_left and marks stopwatch_used."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "stopwatch", source="test")
    assert st.special.stopwatch_used is True
    assert st.special.stopwatch_left == 10


def test_stopwatch_not_re_obtainable_after_use():
    """The Stopwatch cannot be granted again after it has been used today.

    The spec says it is unobtainable again that day; grant() must silently drop
    a second attempt even if the item is not in inventory.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "stopwatch", source="test")
    si.remove(st, "stopwatch")  # player no longer holds it
    assert not si.has(st, "stopwatch")
    si.grant(st, reg, "stopwatch", source="test")  # should be blocked
    assert not si.has(st, "stopwatch")


# ---------------------------------------------------------- food pipeline

def test_food_steps_base_no_items():
    """Base food steps are returned unchanged when no food-modifying items are held."""
    st, reg = _state_with_registry()
    assert si.food_steps(st, reg, 3) == 3


def test_food_steps_salt_shaker():
    """Salt Shaker adds 1 step to food items: 3 -> 4."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "salt_shaker", source="test")
    assert si.food_steps(st, reg, 3) == 4


def test_food_steps_silver_spoon_doubles():
    """Silver Spoon doubles after the base: 3 -> 6 (no Salt Shaker)."""
    st, reg = _state_with_registry()
    # Silver Spoon has no spawn rooms (showroom only); bypass _on_pickup path
    st.inventory["silver_spoon"] = 1
    st.special.spawned_today.append("silver_spoon")
    assert si.food_steps(st, reg, 3) == 6


def test_food_steps_salt_then_spoon():
    """Food pipeline ordering: Salt Shaker (+1) then Silver Spoon (x2) gives 3->4->8.

    This is the wiki-documented banana-in-pocket sequence: order matters.
    """
    st, reg = _state_with_registry()
    si.grant(st, reg, "salt_shaker", source="test")
    st.inventory["silver_spoon"] = 1
    st.special.spawned_today.append("silver_spoon")
    assert si.food_steps(st, reg, 3) == 8


# ---------------------------------------------------------- Lunch Box

def test_lunch_box_consumed_at_rank_5_grants_food_steps():
    """Picking up the Lunch Box at rank >= 5 immediately consumes it and grants steps.

    The Lunch Box's steps_at_rank effect has steps=10; with no modifiers that is 10.
    """
    st, reg = _state_with_registry()
    st.special.gated_out = []  # allow lunch_box
    # Place the player at rank 5 (cell 20 = (5-1)*5 + 0)
    st.pos = 20
    steps_before = st.steps
    si.grant(st, reg, "lunch_box", source="test")
    # Lunch Box should be consumed (not in inventory)
    assert not si.has(st, "lunch_box")
    assert "lunch_box" in st.special.removed
    # Steps increased by food pipeline: base=10 (Lunch Box steps), no modifiers
    assert st.steps == steps_before + 10


def test_lunch_box_consumed_at_rank_5_with_salt_shaker():
    """Lunch Box consumed at rank 5 with Salt Shaker grants 11 steps (10+1)."""
    st, reg = _state_with_registry()
    st.special.gated_out = []
    st.pos = 20  # rank 5
    si.grant(st, reg, "salt_shaker", source="test")
    steps_before = st.steps
    si.grant(st, reg, "lunch_box", source="test")
    assert not si.has(st, "lunch_box")
    assert st.steps == steps_before + 11


def test_lunch_box_consumed_at_rank_5_with_salt_and_spoon():
    """Lunch Box consumed at rank 5 with Salt+Spoon grants 22 steps (10->11->22).

    Pipeline: base=10 (Lunch Box steps param), +1 Salt Shaker, x2 Silver Spoon.
    """
    st, reg = _state_with_registry()
    st.special.gated_out = []
    st.pos = 20  # rank 5
    si.grant(st, reg, "salt_shaker", source="test")
    st.inventory["silver_spoon"] = 1
    st.special.spawned_today.append("silver_spoon")
    steps_before = st.steps
    si.grant(st, reg, "lunch_box", source="test")
    assert not si.has(st, "lunch_box")
    assert st.steps == steps_before + 22


def test_lunch_box_stays_in_inventory_below_rank_5():
    """Picking up the Lunch Box below rank 5 keeps it in inventory without consuming it."""
    st, reg = _state_with_registry()
    st.special.gated_out = []
    st.pos = 2  # rank 1 (entrance)
    si.grant(st, reg, "lunch_box", source="test")
    assert si.has(st, "lunch_box")
    assert "lunch_box" not in st.special.removed


# ---------------------------------------------------------- coin interest

def test_coin_purse_interest_per_3():
    """Coin Purse pays 1 bonus coin per 3 collected; remainder carries across pickups."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "coin_purse", source="test")
    # 2 coins: no payout yet
    assert si.on_coins_granted(st, reg, 2) == 0
    assert st.special.coin_interest == 2
    # 1 more coin: crosses threshold -> 1 bonus, remainder 0
    assert si.on_coins_granted(st, reg, 1) == 1
    assert st.special.coin_interest == 0
    # 4 more: 1 bonus (floor div 3=1), remainder 1
    assert si.on_coins_granted(st, reg, 4) == 1
    assert st.special.coin_interest == 1


def test_lucky_purse_doubles_and_supersedes_coin_purse():
    """Lucky Purse doubles coins and takes priority over the Coin Purse interest rule.

    The wiki specifies Lucky Purse supersedes Coin Purse: no interest accumulates.
    """
    st, reg = _state_with_registry()
    # Lucky Purse has no spawn rooms; inject directly
    st.inventory["lucky_purse"] = 1
    st.special.spawned_today.append("lucky_purse")
    bonus = si.on_coins_granted(st, reg, 5)
    assert bonus == 5  # doubles: player gets 5+5=10 total
    # coin_interest must not have accumulated
    assert st.special.coin_interest == 0


# ---------------------------------------------------------- luck bonus

def test_luck_bonus_empty_inventory():
    """luck_bonus returns 0 fast when no items are held."""
    st, reg = _state_with_registry()
    assert si.luck_bonus(st, reg) == 0


def test_luck_bonus_rabbits_foot():
    """Rabbit's Foot raises effective luck by 3 per copy held."""
    st, reg = _state_with_registry()
    si.grant(st, reg, "lucky_rabbits_foot", source="test")
    assert si.luck_bonus(st, reg) == 3


def test_luck_bonus_lucky_purse():
    """Lucky Purse also grants +3 luck (its luck_bonus effect)."""
    st, reg = _state_with_registry()
    st.inventory["lucky_purse"] = 1
    st.special.spawned_today.append("lucky_purse")
    assert si.luck_bonus(st, reg) == 3


# ---------------------------------------------------------- Lost & Found

def test_lost_and_found_steals_one_item():
    """Entering the Lost & Found with a held item removes exactly one from inventory.

    The steal is the core of the room's penalty mechanic. We track held count
    separately from gifts (gifts may add items back to the pool).
    """
    reg = _registry()
    cfg = GameConfig(studio_additions=frozenset({"lost_and_found"}))
    g = Game(cfg, seed=42)
    # Inject two items directly so we have something to steal
    si.grant(g.state, reg, "shovel", source="test")
    si.grant(g.state, reg, "treasure_map", source="test")
    held_before = dict(g.state.inventory)  # snapshot before
    si.lost_and_found_on_enter(g)
    # Exactly one of the two items we injected must have been removed
    stolen = [iid for iid in ("shovel", "treasure_map")
              if held_before.get(iid, 0) > 0 and not si.has(g.state, iid)]
    assert len(stolen) == 1


def test_lost_and_found_grants_two_gifts():
    """Lost & Found grants exactly two draws from its pool (may include dice).

    The give-two-takes-one trade is the room's positive side.
    """
    cfg = GameConfig(studio_additions=frozenset({"lost_and_found"}))
    g = Game(cfg, seed=7)
    # Empty inventory so steal does nothing; gifts still fire
    log_before = len(g.state.items_found_log)
    si.lost_and_found_on_enter(g)
    # 2 gift draws should have been logged
    log_after = len(g.state.items_found_log)
    assert log_after - log_before == 2


def test_lost_and_found_does_not_steal_keycard():
    """The Lost & Found cannot steal the Keycard — it is PIPELINE_EXCLUDED.

    The Keycard is handled by locks.py; stealing it would break the security-door model.
    """
    cfg = GameConfig(studio_additions=frozenset({"lost_and_found"}))
    g = Game(cfg, seed=3)
    g.state.has_keycard = True
    g.state.inventory["keycard"] = 1
    si.lost_and_found_on_enter(g)
    assert g.state.inventory.get("keycard", 0) == 1


# ---------------------------------------------------------- spawn system

def test_special_spawn_disabled_when_special_items_off():
    """roll_special_spawn returns None immediately when special_items is disabled."""
    reg = _registry()
    rng = Rng(1)
    st = GameState()
    st.special.enabled = False
    room = reg.by_id["attic"]  # attic has several spawn-pool items
    result = si.roll_special_spawn(st, reg, room, rng)
    assert result is None


def test_special_spawn_determinism():
    """Same seed produces identical items_found_log across two complete Game runs.

    Determinism is a tested invariant: seeded runs must replay identically.
    Uses the batch runner (which handles locked doors, stalls, etc.) to drive two
    identical episodes and compares their pickup logs.
    """
    from blueprince_sim.cli.policies import greedy_rank
    cfg = GameConfig(special_items=True)
    # run_episode returns a summary dict but also plays through a seeded Game;
    # we create Game instances manually to compare items_found_log directly.
    import random
    g1 = Game(cfg, seed=999)
    g2 = Game(cfg, seed=999)
    rnd1 = random.Random(999)
    rnd2 = random.Random(999)
    from blueprince_sim.engine.game import Phase
    for g, rnd in ((g1, rnd1), (g2, rnd2)):
        decisions = 0
        while g.phase is not Phase.TERMINAL and decisions < 400:
            decisions += 1
            greedy_rank(g, rnd)
    assert g1.state.items_found_log == g2.state.items_found_log


def test_special_spawn_at_most_one_per_room():
    """At most one special item spawns per room per day via roll_special_spawn.

    spawn_room_done tracks the room.idx so a second proc in the same room is blocked.
    """
    reg = _registry()
    room = reg.by_id["attic"]
    st = GameState()
    st.special.enabled = True
    st.special.configured = True  # skip configure to avoid cfg dependency
    st.luck = 20  # high luck to maximise pool
    # First call: may or may not spawn something — drive until we get a spawn
    for _ in range(50):
        rng2 = Rng(_ + 1)
        st2 = GameState()
        st2.special.enabled = True
        st2.special.configured = True
        st2.luck = 20
        first = si.roll_special_spawn(st2, reg, room, rng2)
        if first is not None:
            # Second call on same state must return None (room already spawned)
            second = si.roll_special_spawn(st2, reg, room, rng2)
            assert second is None
            break


# ---------------------------------------------------------- config gates

def test_lunch_box_gated_without_unlock():
    """Lunch Box does not appear when lunch_box_unlocked is False (default).

    configure() populates gated_out; on_enter skips gated items; the Dining
    Room first-entry should not grant the Lunch Box without the unlock.
    """
    cfg = GameConfig(lunch_box_unlocked=False)
    g = Game(cfg, seed=1)
    reg = g.registry
    room = reg.by_id["dining_room"]
    cell = 7
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    si.on_enter(g, room, cell)
    assert not si.has(g.state, "lunch_box")


def test_lunch_box_guaranteed_in_dining_room_when_unlocked():
    """With lunch_box_unlocked=True, on_enter grants the Lunch Box in the Dining Room.

    This is a guaranteed-spawn rule: the room always contains it on first entry.
    """
    cfg = GameConfig(lunch_box_unlocked=True)
    g = Game(cfg, seed=1)
    reg = g.registry
    room = reg.by_id["dining_room"]
    cell = 7  # arbitrary cell — not entered yet
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    # Fire on_enter directly
    si.on_enter(g, room, cell)
    assert si.has(g.state, "lunch_box")


def test_cursed_effigy_gated_without_unlock():
    """Cursed Effigy is blocked from spawning without cursed_effigy_unlocked."""
    cfg = GameConfig(cursed_effigy_unlocked=False)
    g = Game(cfg, seed=1)
    si.configure(g.state, g.cfg)
    assert "cursed_effigy" in g.state.special.gated_out


def test_royal_scepter_always_gated_in_pr1():
    """Royal Scepter is always gated out in PR1 regardless of config."""
    cfg = GameConfig()
    g = Game(cfg, seed=1)
    si.configure(g.state, g.cfg)
    assert "royal_scepter" in g.state.special.gated_out


# ---------------------------------------------------------- configure idempotency

def test_configure_idempotent():
    """configure() called twice produces the same gated_out, not doubled entries."""
    cfg = GameConfig(lunch_box_unlocked=False, cursed_effigy_unlocked=False)
    g = Game(cfg, seed=1)
    si.configure(g.state, g.cfg)
    first = list(g.state.special.gated_out)
    si.configure(g.state, g.cfg)
    assert g.state.special.gated_out == first
