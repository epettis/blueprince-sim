"""Aquarium upgrade variants: exact coin grant, the star bonus, and the Power Source flag.

Each of the three variants only ever repeats the base Aquarium's "AQUARIUM is
every color of room" text plus one addition of its own. Every test below
checks a variant against the base Aquarium in the same run, so a future edit
cannot let the two silently converge back to identical behaviour.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption, PendingDraft

# Every colour category the base Room.category field ever takes, other than
# "objective" (a room role -- Antechamber, Room 46, Quest Bedroom -- not a
# colour), so counts_as_all_colors never claims it.
COLOR_CATEGORIES = ("blueprint", "bedroom", "hallway", "green", "red", "shop", "blackprint")


def _game_with_room(room_id: str, cell: int, seed: int = 0) -> Game:
    """Return a Game with ``room_id`` placed at ``cell`` and luck floored, not yet entered.

    Luck is floored so ``additional_max``'s luck-rolled bonus item never
    fires, isolating each assertion from an unrelated probabilistic roll.
    Placed directly on the grid rather than via ``_place_room``, so this
    helper does not fire ON_PLACE -- callers that need the star grant use
    ``_place_room`` instead (see test_starfish_aquarium_grants_one_star_on_draft).
    """
    g = Game(GameConfig(), seed=seed)
    g.state.luck = 0
    room = g.registry.by_id[room_id]
    g.state.grid[cell] = room.idx
    g.state.placed_doors[cell] = room.door_mask
    return g


def test_goldfish_aquarium_grants_exactly_10_coins_every_seed():
    """goldfish_aquarium__ix2's "+10" is a literal coin figure, not a 1-5 pile roll.

    Swept across seeds because coding "+10 coins" as a pile count (rather
    than coins_exact) would pay a mean of 30, and it stays a distribution
    under RNG unless the literal-amount item kind is used. The base Aquarium
    is entered in the same loop and asserted to grant no coins, so the two
    records cannot silently converge.
    """
    cell = 5
    for seed in range(1, 31):
        base = _game_with_room("aquarium", cell, seed=seed)
        base._enter(cell)
        assert base.state.coins == 0, f"seed {seed}: base Aquarium should grant no coins"

        goldfish = _game_with_room("goldfish_aquarium__ix2", cell, seed=seed)
        goldfish._enter(cell)
        assert goldfish.state.coins == 10, (
            f"seed {seed}: expected exactly 10 coins, got {goldfish.state.coins}")


def test_starfish_aquarium_grants_one_star_on_draft_without_entering():
    """starfish_aquarium__ix3 grants exactly 1 star the moment it is drafted
    (ON_PLACE), before it is ever entered -- "Entering the Starfish Aquarium
    is not necessary to gain the star." The base Aquarium is placed the same
    way and asserted to grant no star, so the two records cannot silently
    converge.
    """
    cell = 5
    for seed in range(1, 31):
        base = Game(GameConfig(), seed=seed)
        base_room = base.registry.by_id["aquarium"]
        base._place_room(base_room, cell, N | S)
        assert base.state.stars == 0, f"seed {seed}: base Aquarium should grant no star"

        starfish = Game(GameConfig(), seed=seed)
        starfish_room = starfish.registry.by_id["starfish_aquarium__ix3"]
        starfish._place_room(starfish_room, cell, N | S)
        assert starfish.state.stars == 1, (
            f"seed {seed}: expected exactly 1 star, got {starfish.state.stars}")
        assert not starfish.state.entered[cell], "the star must not require entering the room"


def test_electric_eel_aquarium_is_powered_and_the_others_are_not():
    """electric_eel_aquarium__ix4's "Power Source" text sets flags.powered, mirroring the Boiler Room.

    The Boiler Room expresses "Power Source" purely as a data flag
    (flags.powered = true, no effects entry), and this variant is sourced
    from the raw sheet's own "Yes" powered column the same way. The base
    Aquarium and the other two variants are asserted unpowered in the same
    test so the flag cannot silently spread to the wrong record.
    """
    registry = Game(GameConfig(), seed=0).registry
    assert registry.by_id["aquarium"].powered is False
    assert registry.by_id["goldfish_aquarium__ix2"].powered is False
    assert registry.by_id["starfish_aquarium__ix3"].powered is False
    assert registry.by_id["electric_eel_aquarium__ix4"].powered is True


def test_aquarium_is_category_matches_every_colour_but_not_objective():
    """"AQUARIUM is every color of room": Room.is_category() must return True
    for the Aquarium against every colour the ``category`` field ever takes,
    and False against "objective" -- a room role, not a colour, so
    counts_as_all_colors never claims it.
    """
    registry = Game(GameConfig(), seed=0).registry
    aquarium = registry.by_id["aquarium"]
    for category in COLOR_CATEGORIES:
        assert aquarium.is_category(category), f"Aquarium should count as {category!r}"
    assert not aquarium.is_category("objective"), "Aquarium must not count as objective"


def test_ordinary_room_only_matches_its_own_category():
    """A room without counts_as_all_colors matches only its own category, not
    every colour -- the control case that pins is_category isn't a no-op."""
    registry = Game(GameConfig(), seed=0).registry
    boudoir = registry.by_id["boudoir"]  # category: bedroom, no counts_as_all_colors
    assert boudoir.counts_as_all_colors is False
    assert boudoir.is_category("bedroom")
    for category in ("blueprint", "hallway", "green", "red", "shop", "blackprint", "objective"):
        assert not boudoir.is_category(category), f"Boudoir should not count as {category!r}"


def test_paper_crown_treats_aquarium_as_red(monkeypatch):
    """Paper Crown's "no red room in hand" redraw bonus treats the Aquarium as
    red too: counts_as_all_colors covers penalties -- here, a bonus the
    Aquarium's presence blocks -- as well as bonuses, so a hand containing
    only the Aquarium must not grant the free redraw the way an all-non-red
    hand would.
    """
    g = Game(GameConfig(starting_items=frozenset(("paper_crown",))), seed=0)
    g.state.steps = 100
    aquarium = g.registry.by_id["aquarium"]
    fake_pending = PendingDraft(
        from_cell=2, direction=N, target_cell=7,
        options=[DraftOption(room_idx=aquarium.idx, orientation=aquarium.door_mask,
                             gem_cost=aquarium.gem_cost, slot=0)],
    )
    monkeypatch.setattr("blueprince_sim.engine.game.deal_draft", lambda *a, **k: fake_pending)
    pending = g.open_door(2, N)
    assert pending.redraws_left == 0, (
        "Paper Crown must not bonus a hand whose only option is the Aquarium")


def test_cloister_of_mila_bonus_fires_for_aquarium():
    """Cloister of Mila's "extra item in each BEDROOM you draft from this
    CLOISTER" fires for the Aquarium too, since counts_as_all_colors makes it
    a Bedroom as well as every other colour.
    """
    g = Game(GameConfig(), seed=0)
    cloister = g.registry.by_id["cloister_of_mila__ix33"]
    aquarium = g.registry.by_id["aquarium"]
    cloister_cell, aquarium_cell = 0, 1
    g._place_room(cloister, cloister_cell, cloister.door_mask)
    g.state.pending = PendingDraft(from_cell=cloister_cell, direction=N, target_cell=aquarium_cell)
    g._place_room(aquarium, aquarium_cell, aquarium.door_mask)
    assert aquarium_cell in g.state.cloister_mila_bonus_cells, (
        "Cloister of Mila should mark the Aquarium's cell for its Bedroom bonus item")
