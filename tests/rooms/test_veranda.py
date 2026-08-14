"""Veranda: a per-draft luck modifier (``draft_luck``), never a stored-luck
grant.

Wiki (Luck page DataMinedBox, https://blueprince.wiki.gg/wiki/Luck), the
framing that governs this whole channel: "When drafting a room, if the
condition is met, additional modifiers are applied for that draft (without
modifying the current luck value): Veranda: first one in a day gives +12,
all later ones give +6. Applied if the room you drafted is green."

Hard rule (same as test_luck_ladder.py): the expected magnitudes below are
hand-typed literals from the wiki quote, never derived by reading
data/rooms.json (the same file the engine reads) or by calling the function
under test for the EXPECTED side.
"""

from __future__ import annotations

from blueprince_sim.engine import items
from blueprince_sim.engine.game import Game

CELL = 7  # rank 2, col 2 (unconnected; draft_luck_bonus only reads state.grid)


def test_veranda_first_qualifying_draft_gives_twelve(registry, cfg):
    """"first one in a day gives +12 ... Applied if the room you drafted is
    green" -- the first green-room draft of the day, while a Veranda is
    placed, gets +12.
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = veranda.idx

    assert items.draft_luck_bonus(g, greenhouse) == 12


def test_veranda_later_qualifying_drafts_give_six(registry, cfg):
    """"...all later ones give +6." The SAME day's second (and any later)
    green-room draft, while a Veranda is placed, gets +6 instead of +12.
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    greenhouse = registry.by_id["greenhouse"]
    courtyard = registry.by_id["courtyard"]
    g.state.grid[CELL] = veranda.idx

    first = items.draft_luck_bonus(g, greenhouse)
    second = items.draft_luck_bonus(g, courtyard)  # a DIFFERENT green room
    third = items.draft_luck_bonus(g, greenhouse)
    assert (first, second, third) == (12, 6, 6)


def test_veranda_bonus_applies_only_to_green_rooms(registry, cfg):
    """"Applied if the room you drafted is green" -- a non-green room's draft
    gets nothing, and does not consume the day's first-use slot either.
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    office = registry.by_id["office"]  # category "blueprint", not green
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = veranda.idx

    assert items.draft_luck_bonus(g, office) == 0
    # The office draft above did not consume the day's first-use slot: the
    # NEXT green draft still gets the first-use +12, not +6.
    assert items.draft_luck_bonus(g, greenhouse) == 12


def test_veranda_bonus_is_per_draft_and_does_not_modify_stored_luck(registry, cfg):
    """"additional modifiers are applied for that draft (without modifying
    the current luck value)" -- this is the assertion that fails if Veranda
    is ever reimplemented as a ``grant`` (the sim's old, wrong modeling).
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = veranda.idx
    luck_before = g.state.luck

    bonus = items.draft_luck_bonus(g, greenhouse)

    assert bonus == 12
    assert g.state.luck == luck_before


def test_veranda_with_no_veranda_placed_gives_nothing(registry, cfg):
    """No Veranda (or Spare Veranda) on the grid: the channel contributes 0,
    even to a green room's draft.
    """
    g = Game(cfg, seed=0)
    greenhouse = registry.by_id["greenhouse"]
    assert items.draft_luck_bonus(g, greenhouse) == 0


def test_veranda_does_not_apply_to_its_own_draft(registry, cfg):
    """Veranda's own room page (https://blueprince.wiki.gg/wiki/Veranda):
    "When drafted, the Veranda will increase the chance of finding items
    inside any Green Room drafted after the Veranda." Its own draft is not
    "after the Veranda", so it gets nothing from itself.
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    g.state.grid[CELL] = veranda.idx

    assert items.draft_luck_bonus(g, veranda) == 0


def test_veranda_placed_but_not_entered_still_applies(registry, cfg):
    """Wiki (Veranda's own room page): "When drafted, the Veranda will
    increase the chance of finding items inside any Green Room drafted after
    the Veranda." The bonus is live once PLACED, whether or not the Veranda
    itself has been walked into yet (``draft_luck_bonus`` reads ``state.grid``,
    not ``state.entered``).
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = veranda.idx
    assert not g.state.entered[CELL]

    assert items.draft_luck_bonus(g, greenhouse) == 12
