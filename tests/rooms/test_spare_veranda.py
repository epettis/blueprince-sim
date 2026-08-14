"""Spare Veranda (spare_veranda__ix140), a second-level upgrade variant whose
display name differs from its variant_of parent (Spare Greenroom). Because
the ingest pipeline's EFFECT_MAP keys off the base slug, a display-name
mismatch like this one needs its own explicit entry to carry an effect,
despite promising the same "Greater chance of finding items in Green Rooms"
text as the base Veranda.

Wiki (Luck page DataMinedBox, https://blueprince.wiki.gg/wiki/Luck): "Spare
Veranda: +6 per. Applied if the room drafted is green." -- flat, no
first/later split (unlike the base Veranda, see test_veranda.py), and (same
framing as every entry in that DataMinedBox list) per-draft only, never
written to stored luck.
"""

from __future__ import annotations

from blueprince_sim.engine import items
from blueprince_sim.engine.game import Game

CELL = 7  # rank 2, col 2


def test_spare_greenroom_parent_has_no_luck_effect(registry, cfg):
    """spare_greenroom__ix132, the un-upgraded parent, carries no draft_luck
    effect of its own -- the effect is Spare Veranda's alone.
    """
    g = Game(cfg, seed=0)
    parent = registry.by_id["spare_greenroom__ix132"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = parent.idx

    assert items.draft_luck_bonus(g, greenhouse) == 0


def test_spare_veranda_grants_six_flat_every_qualifying_draft(registry, cfg):
    """"+6 per" -- flat, every time, no day-count decay (contrast the base
    Veranda's first-vs-later split).
    """
    g = Game(cfg, seed=0)
    variant = registry.by_id["spare_veranda__ix140"]
    greenhouse = registry.by_id["greenhouse"]
    courtyard = registry.by_id["courtyard"]
    g.state.grid[CELL] = variant.idx

    first = items.draft_luck_bonus(g, greenhouse)
    second = items.draft_luck_bonus(g, courtyard)
    third = items.draft_luck_bonus(g, greenhouse)
    assert (first, second, third) == (6, 6, 6)


def test_spare_veranda_bonus_applies_only_to_green_rooms(registry, cfg):
    """"Applied if the room drafted is green" -- a non-green draft gets 0."""
    g = Game(cfg, seed=0)
    variant = registry.by_id["spare_veranda__ix140"]
    office = registry.by_id["office"]  # category "blueprint", not green
    g.state.grid[CELL] = variant.idx

    assert items.draft_luck_bonus(g, office) == 0


def test_spare_veranda_bonus_is_per_draft_and_does_not_modify_stored_luck(registry, cfg):
    """Same assertion as the base Veranda's: this fails if Spare Veranda is
    ever reimplemented as a ``grant`` (the sim's old, wrong modeling)."""
    g = Game(cfg, seed=0)
    variant = registry.by_id["spare_veranda__ix140"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = variant.idx
    luck_before = g.state.luck

    bonus = items.draft_luck_bonus(g, greenhouse)

    assert bonus == 6
    assert g.state.luck == luck_before


def test_veranda_and_spare_veranda_stack(registry, cfg):
    """Both are read generically off ``room.effects`` (no engine module
    branches on either room's id -- doctrine), so their contributions to the
    same qualifying draft simply sum: 12 (Veranda, first use) + 6 (Spare
    Veranda, flat) = 18.
    """
    g = Game(cfg, seed=0)
    veranda = registry.by_id["veranda"]
    variant = registry.by_id["spare_veranda__ix140"]
    greenhouse = registry.by_id["greenhouse"]
    g.state.grid[CELL] = veranda.idx
    g.state.grid[CELL + 1] = variant.idx

    assert items.draft_luck_bonus(g, greenhouse) == 18
