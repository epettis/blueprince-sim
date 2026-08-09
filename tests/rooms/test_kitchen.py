"""Kitchen: per-dish step resolution and stock rolling.

Split out of the old test_food.py -- see tests/rooms/test_dining_room.py for
the Dining Room's main course, which used to share that file.
"""

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game


# ------------------------------------------------------------------ helpers

def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(), seed=seed)


def _enter_kitchen(game: Game, cell: int = 7) -> object:
    """Place the Kitchen at ``cell``, roll its stock, and return the Room."""
    reg = game.registry
    room = reg.by_id["kitchen"]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    state.entered[cell] = True
    state.pos = cell
    shops.on_enter_shop(game, room)
    return room


def _place_room(game: Game, room_id: str, cell: int) -> object:
    """Place a room on the grid without entering it. Returns the Room."""
    reg = game.registry
    room = reg.by_id[room_id]
    state = game.state
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask
    return room


def _buy_dish(game: Game, dish_id: str) -> None:
    """Buy the named dish from the current kitchen stock (player must be in kitchen)."""
    stock = shops.stock_for(game)
    assert stock is not None, "not in a shop"
    entry = next((i, d) for i, d in enumerate(stock) if d["id"] == dish_id)
    shops.buy(game, entry[0])


# ---------------------------------------------------------------- banana / club sandwich

def test_banana_grants_3_steps():
    """Buying one banana from the Kitchen adds exactly 3 steps (base food value).

    Banana is the simplest food: no modifiers, no dynamics — purely a +3 steps grant.
    """
    g = _game(GameConfig(day=15), seed=0)
    _enter_kitchen(g)
    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "banana")
    assert g.state.steps == steps_before + 3


def test_club_sandwich_grants_15_steps():
    """Buying the Club Sandwich from the Kitchen adds exactly 15 steps.

    Club Sandwich has the highest flat step value among kitchen items and is offered
    with a limit of 1, so it can be bought exactly once.
    """
    g = _game(GameConfig(day=15), seed=0)
    _enter_kitchen(g)
    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "club_sandwich")
    assert g.state.steps == steps_before + 15


def test_banana_costs_2_coins():
    """The banana price is exactly 2 gold (matching the wiki-documented menu price)."""
    g = _game(GameConfig(day=15), seed=0)
    _enter_kitchen(g)
    g.state.coins = 10
    coins_before = g.state.coins
    _buy_dish(g, "banana")
    assert g.state.coins == coins_before - 2


def test_club_sandwich_costs_8_coins():
    """The Club Sandwich price is exactly 8 gold (wiki-documented)."""
    g = _game(GameConfig(day=15), seed=0)
    _enter_kitchen(g)
    g.state.coins = 20
    coins_before = g.state.coins
    _buy_dish(g, "club_sandwich")
    assert g.state.coins == coins_before - 8


# ---------------------------------------------------------------- kitchen stock structure

def test_kitchen_stock_always_has_banana_and_sandwich():
    """Kitchen stock always contains banana and club_sandwich as static entries.

    These two are the fixed menu items; the third entry is the rolled daily special.
    """
    for seed in range(30):
        g = _game(seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        assert "banana" in ids, f"seed={seed}: banana missing"
        assert "club_sandwich" in ids, f"seed={seed}: club_sandwich missing"


def test_kitchen_stock_has_exactly_one_special():
    """Kitchen stock has exactly 3 entries: banana, club_sandwich, and one special.

    The daily special (bacon_and_eggs/chef_salad/tomato_soup) is rolled once on
    first entry; there is never more or fewer than one special per day.
    """
    specials = {"bacon_and_eggs", "chef_salad", "tomato_soup"}
    for seed in range(30):
        g = _game(seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        assert len(ids) == 3, f"seed={seed}: expected 3 entries, got {ids}"
        special_ids = [i for i in ids if i in specials]
        assert len(special_ids) == 1, f"seed={seed}: expected 1 special, got {special_ids}"


def test_kitchen_special_distribution_40_30_30():
    """Bacon & Eggs appears ~40%, Chef Salad ~30%, Tomato Soup ~30% across seeds.

    Wide tolerance (±15pp) over 300 seeds to avoid a flaky test while still
    verifying the roll is actually drawing from the 40/30/30 distribution.
    """
    counts: dict[str, int] = {"bacon_and_eggs": 0, "chef_salad": 0, "tomato_soup": 0}
    n = 300
    specials = set(counts)
    for seed in range(n):
        g = _game(seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        for sid in ids:
            if sid in specials:
                counts[sid] += 1
    bacon_rate = counts["bacon_and_eggs"] / n
    chef_rate = counts["chef_salad"] / n
    soup_rate = counts["tomato_soup"] / n
    assert 0.25 <= bacon_rate <= 0.55, f"Bacon & Eggs rate {bacon_rate:.2%} not in [25%, 55%]"
    assert 0.15 <= chef_rate <= 0.45, f"Chef Salad rate {chef_rate:.2%} not in [15%, 45%]"
    assert 0.15 <= soup_rate <= 0.45, f"Tomato Soup rate {soup_rate:.2%} not in [15%, 45%]"


def test_kitchen_stock_deterministic_per_seed():
    """Same seed produces identical kitchen stock on two separate Game instances.

    Seeded RNG determinism is a foundational engine invariant; kitchen must not break it.
    """
    g1 = _game(seed=42)
    g2 = _game(seed=42)
    _enter_kitchen(g1)
    _enter_kitchen(g2)
    ids1 = [e["id"] for e in g1.state.shops.stock["kitchen"]]
    ids2 = [e["id"] for e in g2.state.shops.stock["kitchen"]]
    assert ids1 == ids2


# ---------------------------------------------------------------- chef salad / tomato soup

def test_chef_salad_steps_per_green_room():
    """Chef Salad grants +5 steps per green room currently on the grid.

    With 2 green rooms placed before eating, the step gain must be exactly 10.
    Chef Salad counts rooms *at eat time* (the wiki's phrasing), so the grid
    state at purchase is what matters.
    """
    g = _game(GameConfig(day=15), seed=0)
    # Place 2 green rooms (patio at cells 10 and 11 — just need two grid slots)
    green_ids = [r.id for r in g.registry.rooms if r.category == "green"
                 and not r.variant_of and r.id != "dining_room"]
    assert len(green_ids) >= 2, "need at least 2 distinct green rooms"
    _place_room(g, green_ids[0], 10)
    _place_room(g, green_ids[1], 11)

    # Ensure chef_salad is today's special (seed-search)
    seed = 0
    while True:
        g = _game(GameConfig(day=15), seed=seed)
        _place_room(g, green_ids[0], 10)
        _place_room(g, green_ids[1], 11)
        _enter_kitchen(g, cell=7)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        if "chef_salad" in ids:
            break
        seed += 1

    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "chef_salad")
    # 2 green rooms × 5 steps each = 10 steps
    assert g.state.steps == steps_before + 10


def test_chef_salad_zero_steps_with_no_green_rooms():
    """Chef Salad grants 0 steps when no green rooms are on the grid.

    The step count is strictly proportional to the green room count at eat time.
    """
    seed = 0
    while True:
        g = _game(GameConfig(day=15), seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        if "chef_salad" in ids:
            break
        seed += 1

    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "chef_salad")
    assert g.state.steps == steps_before + 0


def test_tomato_soup_steps_per_red_room():
    """Tomato Soup grants +5 steps per red room on the grid at eat time.

    With 1 red room placed, the step gain must be exactly 5.
    """
    red_ids = [r.id for r in Game().registry.rooms if r.category == "red"
               and not r.variant_of and r.id != "dining_room"]
    assert len(red_ids) >= 1, "need at least 1 red room"

    seed = 0
    while True:
        g = _game(GameConfig(day=15), seed=seed)
        _place_room(g, red_ids[0], 10)
        _enter_kitchen(g, cell=7)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        if "tomato_soup" in ids:
            break
        seed += 1

    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "tomato_soup")
    assert g.state.steps == steps_before + 5


# ---------------------------------------------------------------- bacon and eggs

def test_bacon_and_eggs_grants_10_steps():
    """Buying Bacon & Eggs grants exactly +10 steps (no food modifiers held).

    The flat +10 step value is checked independently of the Morning Room injection.
    """
    seed = 0
    while True:
        g = _game(GameConfig(day=15), seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        if "bacon_and_eggs" in ids:
            break
        seed += 1

    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "bacon_and_eggs")
    assert g.state.steps == steps_before + 10


def test_bacon_and_eggs_injects_morning_room():
    """Buying Bacon & Eggs satisfies the 'breakfast' gate, making Morning Room draftable.

    The Morning Room has draft_conditions ['breakfast', 'morning_room']. The 'breakfast'
    condition is a gate that normally blocks it. Eating Bacon & Eggs must add 'breakfast'
    to state.special.extra_conditions so the room becomes placeable mid-run.
    """
    seed = 0
    while True:
        g = _game(GameConfig(day=15), seed=seed)
        _enter_kitchen(g)
        ids = [e["id"] for e in g.state.shops.stock["kitchen"]]
        if "bacon_and_eggs" in ids:
            break
        seed += 1

    g.state.coins = 50
    assert "breakfast" not in g.state.special.extra_conditions, \
        "breakfast was already satisfied before Bacon & Eggs purchase"
    _buy_dish(g, "bacon_and_eggs")
    assert "breakfast" in g.state.special.extra_conditions, \
        "'breakfast' condition not satisfied after Bacon & Eggs purchase"


# ---------------------------------------------------------------- salt shaker / silver spoon

def test_salt_shaker_adds_1_to_food_steps():
    """Salt Shaker adds +1 to each food item's step value.

    Banana base is 3; with Salt Shaker it becomes 4. The +1 is applied before
    Silver Spoon's ×2, per wiki order.
    """
    g = _game(GameConfig(day=15, starting_items=frozenset({"salt_shaker"})), seed=0)
    _enter_kitchen(g)
    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "banana")
    assert g.state.steps == steps_before + 4  # 3 + 1


def test_silver_spoon_doubles_food_steps():
    """Silver Spoon doubles the step value of each food item consumed.

    Banana base 3 → doubled to 6. Applied after Salt Shaker (+1 first), per wiki.
    """
    g = _game(GameConfig(day=15, starting_items=frozenset({"silver_spoon"})), seed=0)
    _enter_kitchen(g)
    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "banana")
    assert g.state.steps == steps_before + 6  # 3 × 2


def test_salt_shaker_then_silver_spoon_ordering():
    """Salt Shaker (+1) is applied before Silver Spoon (×2): banana → 3+1=4 → ×2=8.

    Order matters: the opposite order (×2 then +1) would yield 7, not 8.
    """
    g = _game(GameConfig(day=15, starting_items=frozenset({"salt_shaker", "silver_spoon"})),
              seed=0)
    _enter_kitchen(g)
    g.state.coins = 50
    steps_before = g.state.steps
    _buy_dish(g, "banana")
    assert g.state.steps == steps_before + 8  # (3 + 1) × 2
