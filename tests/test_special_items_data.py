"""Data-level invariants for special_items.json that are not behaviour tests."""

import json
from pathlib import Path

import blueprince_sim.engine.model as _model

_DATA = Path(_model.__file__).resolve().parent.parent / "data" / "special_items.json"


def test_wont_implement_items_carry_a_reason_and_no_blocker():
    """An item decided against carries meta.wont_implement and no meta.blocked_on.

    The two are mutually exclusive by design: a blocker names something missing
    that could be built, while wont_implement records a decision that it never
    will be. Conflating them is what lets a permanent exclusion sit in the
    backlog forever looking like pending work.
    """
    items = json.loads(_DATA.read_text(encoding="utf-8"))["items"]
    wont = [i for i in items if i["meta"].get("wont_implement")]
    assert wont, "expected at least one deliberately-excluded item"
    for item in wont:
        assert not item["implemented"], f"{item['id']}: wont_implement needs implemented=false"
        assert not item["meta"].get("blocked_on"), (
            f"{item['id']}: wont_implement and blocked_on are mutually exclusive")
        assert str(item["meta"]["wont_implement"]).strip(), (
            f"{item['id']}: wont_implement must state the reason")


def test_magnifying_glass_still_spawns_so_the_burning_glass_stays_obtainable():
    """The Magnifying Glass keeps its spawn rooms despite being excluded.

    Its own effect is never being built, but it is the sole input to the
    Burning Glass, which has no spawn source of its own and is one of only two
    ignition tools -- so dropping it from the pools would silently remove an
    ignition path.
    """
    data = json.loads(_DATA.read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id["magnifying_glass"]["spawn_rooms"], "magnifying glass must keep spawning"
    bg = by_id["burning_glass"]
    assert not bg["spawn_rooms"] and not bg["guaranteed_in"], (
        "burning glass gained a source; this test's premise needs rechecking")
    recipe = [r for r in data["fabrication"] if r["output"] == "burning_glass"]
    assert recipe and "magnifying_glass" in recipe[0]["inputs"]
    assert "burning_glass" in data["ignition"]["tools"]


def test_telescope_spawn_rooms_excludes_lost_and_found_and_trading_post():
    """telescope.spawn_rooms holds only loose-on-the-floor rooms, not the two
    obtain-elsewhere channels it is also reachable through.

    Owner ruling: spawn_rooms means floor spawns only; purchasable/obtainable
    is modeled separately (shops.json trading, lost_and_found.pool) and must
    never also appear in spawn_rooms, or that channel double-counts and
    dilutes the floor-spawn room's own pool. telescope is confirmed reachable
    both other ways: it is tier 4 (Trading Post's tier-4 trade cycle includes
    every tier-4 item generically) and it is listed in lost_and_found.pool
    directly -- so dropping it from spawn_rooms does not orphan the item.
    """
    data = json.loads(_DATA.read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in data["items"]}
    telescope = by_id["telescope"]
    assert "lost_and_found" not in telescope["spawn_rooms"]
    assert "trading_post" not in telescope["spawn_rooms"]
    # The two channels that make dropping them safe:
    assert "telescope" in data["lost_and_found"]["pool"]
    assert telescope["tier"] == 4
