"""Coat Check: auto-storing the best held item overnight.

Split out of the old test_item_persistence.py, which keeps the generic
persistence-channel tests (day/permanent/until_used, Moon Pendant, Repellent)
that apply across items rather than to this one room.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import shops, special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env.multiday import DayChain


def _game(cfg: GameConfig | None = None, seed: int = 0) -> Game:
    return Game(cfg or GameConfig(royal_scepter_found=False), seed=seed)


def _game_with(*item_ids: str, seed: int = 0) -> Game:
    """Game whose inventory starts with the given item ids (no scepter noise)."""
    return _game(GameConfig(
        starting_items=frozenset(item_ids),
        royal_scepter_found=False,
    ), seed=seed)


def test_coat_check_stores_best_item():
    """Entering the Coat Check stores the highest-tier held item.

    Coat Check auto-selects the best item by Trading Post tier (highest tier
    wins; ties broken alphabetically by id).  Telescope (tier 4) beats
    shovel (tier 2), so telescope is stored.
    """
    g = _game_with("shovel", "telescope")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "telescope"


def test_coat_check_stored_item_appears_in_carry():
    """The Coat Check stored item appears in end_of_day_carry even if it is day-persistence.

    Telescope persistence is 'day', so it would normally be lost.  Entering
    the Coat Check overrides this — the item is conceptually held at the
    check room and returned tomorrow.
    """
    g = _game_with("telescope")
    si.coat_check_on_enter(g)
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "telescope" in carried


def test_coat_check_day_item_not_carried_without_coat_check():
    """Without the Coat Check room, a day-persistence item is not carried.

    Contrast with the test above: the Coat Check is what causes the carry,
    not the item's own persistence.
    """
    g = _game_with("telescope")
    # Do NOT call coat_check_on_enter
    carried = si.end_of_day_carry(g.state, g.registry, g.rng)
    assert "telescope" not in carried


def test_coat_check_tie_broken_alphabetically():
    """When two items share the same tier, coat_check_on_enter picks the alphabetically
    first id (deterministic tie-break).

    magnifying_glass (tier 1) and sleeping_mask (tier 1): 'm' < 's', so
    magnifying_glass is stored.
    """
    g = _game_with("magnifying_glass", "sleeping_mask")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "magnifying_glass"


def test_coat_check_only_once_per_day():
    """The second call to coat_check_on_enter in one day is a no-op.

    The game stores at most one item per day; a second entry to the Coat Check
    (or a second direct call) must not overwrite the first.
    """
    g = _game_with("telescope", "shovel")
    si.coat_check_on_enter(g)
    first = g.state.special.coat_check_item
    # Grant a higher-tier item and call again
    si.grant(g.state, g.registry, "watering_can", source="test")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == first  # unchanged


def test_coat_check_empty_inventory_no_op():
    """coat_check_on_enter with no held items leaves coat_check_item as None."""
    g = _game()
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item is None


def test_coat_check_carryover_in_daychain():
    """DayChain carries the Coat Check item into the next day's starting_items via carryover.

    This is the full observable path: coat_check_on_enter → end_of_day_carry →
    carryover() → DayChain.advance() → next_config().starting_items.
    """
    # Start with a shovel (day persistence) and trigger coat check
    g = _game_with("shovel")
    si.coat_check_on_enter(g)
    assert g.state.special.coat_check_item == "shovel"

    chain = DayChain(GameConfig(royal_scepter_found=False), n_days=10)
    co = shops.carryover(g)
    assert "shovel" in co["starting_items"]

    chain.advance(co)
    cfg2 = chain.next_config()
    # shovel should be in next day's starting_items
    assert "shovel" in cfg2.starting_items
