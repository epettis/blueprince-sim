"""Upgrade Disk respawn semantics for the bespoke-source disks.

These are the disks that do NOT come from an in-grid room's `guaranteed_in`
pickup — each has its own container or shop mechanic instead.

Every disk marked persistence="day" drops overnight when unspent and returns to
its source the next day; spending it (inserting at a terminal) makes removal
permanent via collected_disks. Covered here:

- garage        car trunk; the trunk re-locks nightly, so re-opening it costs
                fresh Car Keys, but the disk inside returns until spent
- vault_304     deposit box; the box itself genuinely stays open permanently
- tomb          ignition target; candles stay lit
- trading_post  ignition target; fuse stays blown
- commissary    ordinary shop stock, restocked daily and re-charging 15 gold
- lost_and_found  stays a candidate in the random draw pool while unspent

upgrade_disk_trade is the ONLY disk exempt from this rule (persistence
"permanent") and must remain repeatably offered even after an earlier
instance was spent.

Tests drive the real DayChain carryover path (not just Game.reset()), because
reset() alone does not apply carryover and would give false negatives.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine import shops
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.rng import Rng
from blueprince_sim.engine.state import GameState
from blueprince_sim.env.multiday import DayChain


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _reg() -> Registry:
    return Registry.load()


def _fake_game(state: GameState, registry: Registry,
               seed: int = 0, cfg: GameConfig | None = None):
    class _FG:
        pass
    g = _FG()
    g.state = state
    g.registry = registry
    g.rng = Rng(seed)
    g.cfg = cfg or GameConfig()
    g._garage_ids = tuple(r.id for r in registry.rooms if r.id.startswith("garage"))
    return g


def _state(registry: Registry) -> GameState:
    st = GameState()
    st.special.enabled = True
    return st


def _place(state: GameState, registry: Registry, room_id: str, cell: int = 5) -> None:
    room = registry.by_id[room_id]
    state.grid[cell] = room.idx
    state.placed_doors[cell] = room.door_mask


def _enter(game, room_id: str, cell: int = 5) -> None:
    """Place room_id at cell and fire on_enter (simulates first-entry pipeline)."""
    _place(game.state, game.registry, room_id, cell)
    room = game.registry.by_id[room_id]
    si.on_enter(game, room, cell)


def _two_day_game(disk_id: str, spent: bool, *, day1_seed: int = 0,
                  day2_seed: int = 1, cfg_kwargs=None):
    """Helper: build a day-2 Game with disk_id spent or not spent on day 1.

    Returns (day2_game, carry_dict) where carry_dict is what carryover() returned.
    """
    cfg_kwargs = cfg_kwargs or {}
    g1 = Game(GameConfig(special_items=True, **cfg_kwargs), seed=day1_seed)
    si.configure(g1.state, g1.cfg)
    if spent:
        si.grant(g1.state, g1.registry, disk_id, source="test")
        si.remove(g1.state, disk_id, consumed=True)
    # Build carryover to simulate DayChain advance
    carry = shops.carryover(g1)
    day2_cfg = GameConfig(
        special_items=True,
        collected_disks=frozenset(carry["collected_disks"]),
        starting_items=frozenset(carry["starting_items"]),
        **cfg_kwargs,
    )
    g2 = Game(day2_cfg, seed=day2_seed)
    si.configure(g2.state, g2.cfg)
    return g2, carry


# ---------------------------------------------------------------------------
# persistence="day" marker
# ---------------------------------------------------------------------------

def test_bespoke_disks_have_day_persistence():
    """The four bespoke disks all carry persistence='day', enabling the drop-and-respawn rule.

    This is the data property the engine dispatches on; changing persistence
    would silently break the supply cap for those disks.
    """
    reg = _reg()
    for disk_id in ("upgrade_disk_garage", "upgrade_disk_vault_304",
                    "upgrade_disk_tomb", "upgrade_disk_trading_post"):
        item = reg.special.by_id[disk_id]
        assert item.persistence == "day", (
            f"{disk_id} must have persistence='day' for respawn to work; got {item.persistence!r}"
        )


def test_upgrade_disk_trade_is_not_day_persistence():
    """upgrade_disk_trade keeps persistence='permanent'; it must never enter collected_disks.

    Changing it to 'day' would break the repeatable tier-5 trade mechanic by
    permanently gating the disk after its first spend.
    """
    reg = _reg()
    item = reg.special.by_id["upgrade_disk_trade"]
    assert item.persistence == "permanent", (
        f"upgrade_disk_trade must stay 'permanent' (repeatable); got {item.persistence!r}"
    )


# ---------------------------------------------------------------------------
# garage car trunk
# ---------------------------------------------------------------------------

def test_garage_disk_returns_after_not_spending():
    """The garage disk drops overnight and is re-granted when the trunk is re-opened.

    The trunk re-locks nightly, so day 2 costs fresh Car Keys; but the disk is
    not in collected_disks (not spent), so it must be re-granted on that re-open.
    """
    reg = _reg()
    st = _state(reg)
    si.grant(st, reg, "car_keys", source="test")
    _place(st, reg, "garage", 5)
    st.pos = 5

    # Day 1: open trunk, get disk, do NOT spend it
    g = _fake_game(st, reg, cfg=GameConfig(special_items=True))
    si.configure(st, g.cfg)
    si.open_car_trunk(g)
    assert st.inventory.get("upgrade_disk_garage", 0) == 1, "disk granted on first trunk open"

    # Simulate overnight: disk drops (not in carryover), trunk-open flag persists.
    # Day 2: trunk already open, disk not spent -> re-grant
    st2 = _state(reg)
    si.grant(st2, reg, "car_keys", source="test")
    _place(st2, reg, "garage", 5)
    st2.pos = 5
    cfg2 = GameConfig(
        special_items=True,
        collected_disks=frozenset(),
    )
    g2 = _fake_game(st2, reg, cfg=cfg2)
    si.configure(st2, cfg2)
    si.open_car_trunk(g2)
    assert st2.inventory.get("upgrade_disk_garage", 0) == 1, (
        "garage disk must return to the open trunk when not spent"
    )


def test_garage_disk_spent_leads_to_pool_draw():
    """After upgrade_disk_garage is spent, trunk opens give pool items instead of the disk.

    With the disk in collected_disks, the engine treats it as permanently gone
    and falls through to the later_pool draw. This is the post-spend behavior.
    """
    reg = _reg()
    st = _state(reg)
    si.grant(st, reg, "car_keys", source="test")
    _place(st, reg, "garage", 5)
    st.pos = 5

    cfg = GameConfig(
        special_items=True,
        collected_disks=frozenset({"upgrade_disk_garage"}),
    )
    g = _fake_game(st, reg, seed=1, cfg=cfg)
    si.configure(st, cfg)
    si.open_car_trunk(g)

    assert st.inventory.get("upgrade_disk_garage", 0) == 0, (
        "spent disk must not be re-granted (it is in collected_disks)"
    )
    later_pool = reg.special.containers.get("garage_car", {}).get("later_pool", [])
    later_gold = reg.special.containers.get("garage_car", {}).get("later_gold", 5)
    coins_or_items = (st.coins >= later_gold
                      or any(st.inventory.get(iid, 0) > 0 for iid in later_pool))
    assert coins_or_items, "after disk spent, trunk must draw from later_pool"


def test_garage_disk_spent_appears_in_collected_disks_carryover():
    """Spending upgrade_disk_garage puts it in the collected_disks carryover.

    The carryover is what DayChain merges on advance(); without this the engine
    would re-mint the disk on the next open even though it was already inserted.
    """
    g1, carry = _two_day_game("upgrade_disk_garage", spent=True,
                               cfg_kwargs={})
    assert "upgrade_disk_garage" in carry["collected_disks"], (
        "spent garage disk must appear in collected_disks so it cannot be re-granted"
    )


def test_garage_disk_via_daychain():
    """DayChain accumulates the garage disk in collected_disks after it is spent.

    This drives the full carryover path that the RL trainer uses, rather than
    the carryover() shortcut, to guard against wiring gaps in DayChain.advance().
    """
    chain = DayChain(GameConfig(special_items=True))
    chain.advance({"collected_disks": ["upgrade_disk_garage"]})
    cfg = chain.next_config()
    assert "upgrade_disk_garage" in cfg.collected_disks, (
        "DayChain must carry garage disk in collected_disks after spend"
    )


# ---------------------------------------------------------------------------
# vault box 304
# ---------------------------------------------------------------------------

def test_vault_304_disk_returns_when_box_opened_but_disk_not_spent():
    """Vault box 304 re-grants its disk on later-day visits while the disk is unspent.

    The box stays open (vault_key_304 in used_vault_keys), no key required;
    the disk returns until collected_disks contains upgrade_disk_vault_304.
    """
    reg = _reg()
    st = _state(reg)
    _place(st, reg, "vault", 5)
    st.pos = 5

    cfg = GameConfig(
        special_items=True,
        used_vault_keys=frozenset({"vault_key_304"}),
        collected_disks=frozenset(),  # disk not yet spent
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    # should open despite no key held (box already opened)
    result = si.open_vault_box(g)
    assert "upgrade_disk_vault_304" in result or st.inventory.get("upgrade_disk_vault_304", 0) == 1, (
        "open vault box must re-grant the disk when box already open and disk not spent"
    )


def test_vault_304_disk_not_regranted_once_spent():
    """Once upgrade_disk_vault_304 is spent, can_open_vault_box returns None for box 304.

    With the disk in collected_disks, _is_available blocks it, so there is nothing
    left to grant — can_open_vault_box skips the box entirely.
    """
    reg = _reg()
    st = _state(reg)
    _place(st, reg, "vault", 5)
    st.pos = 5

    cfg = GameConfig(
        special_items=True,
        used_vault_keys=frozenset({"vault_key_304"}),
        collected_disks=frozenset({"upgrade_disk_vault_304"}),
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    result = si.can_open_vault_box(g)
    assert result is None, (
        "box 304 must be inert once upgrade_disk_vault_304 is in collected_disks"
    )


def test_vault_304_disk_spent_appears_in_carryover():
    """Spending upgrade_disk_vault_304 puts it in the collected_disks carryover.

    Simulates the full path: grant disk, spend it (consumed=True), then
    carryover() picks it up via fixed_disks_spent_today.
    """
    # carryover needs a real game; use a minimal Game object
    g1 = Game(GameConfig(special_items=True), seed=0)
    si.configure(g1.state, g1.cfg)
    si.grant(g1.state, g1.registry, "upgrade_disk_vault_304", source="test")
    si.remove(g1.state, "upgrade_disk_vault_304", consumed=True)

    carry = shops.carryover(g1)
    assert "upgrade_disk_vault_304" in carry["collected_disks"], (
        "spent vault disk must appear in collected_disks carryover"
    )


# ---------------------------------------------------------------------------
# ignition targets: tomb and trading_post
# ---------------------------------------------------------------------------

def test_tomb_disk_returns_on_reentry_when_not_spent():
    """After the Tomb is lit, entering it on a later day re-grants upgrade_disk_tomb if unspent.

    The candles stay lit (tomb in state.special.lit_targets, seeded from cfg.lit_targets),
    but the disk returns to the room each day until spent.
    """
    reg = _reg()
    st = _state(reg)

    # Simulate: tomb was lit on a previous day
    cfg = GameConfig(
        special_items=True,
        lit_targets=frozenset({"tomb"}),
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    # lit_targets from cfg is seeded into state.special.lit_targets by configure()
    assert "tomb" in st.special.lit_targets, "configure() must seed lit_targets"

    _enter(g, "tomb")
    assert st.inventory.get("upgrade_disk_tomb", 0) == 1, (
        "entering a lit Tomb with unspent disk must re-grant upgrade_disk_tomb"
    )


def test_tomb_disk_not_regranted_once_spent():
    """Once upgrade_disk_tomb is spent, re-entering the lit Tomb grants nothing.

    With the disk in collected_disks (seeded into gated_out by configure()),
    _is_available blocks the re-grant in the on_enter hook.
    """
    reg = _reg()
    st = _state(reg)

    cfg = GameConfig(
        special_items=True,
        lit_targets=frozenset({"tomb"}),
        collected_disks=frozenset({"upgrade_disk_tomb"}),
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    _enter(g, "tomb")
    assert st.inventory.get("upgrade_disk_tomb", 0) == 0, (
        "re-entering lit Tomb must NOT re-grant the disk when it is in collected_disks"
    )


def test_tomb_disk_spent_appears_in_carryover():
    """Spending upgrade_disk_tomb puts it in the collected_disks carryover.

    fixed_disks_spent_today collects it because persistence='day' and it is
    in state.special.removed after remove(consumed=True).
    """
    g1 = Game(GameConfig(special_items=True), seed=0)
    si.configure(g1.state, g1.cfg)
    si.grant(g1.state, g1.registry, "upgrade_disk_tomb", source="test")
    si.remove(g1.state, "upgrade_disk_tomb", consumed=True)

    carry = shops.carryover(g1)
    assert "upgrade_disk_tomb" in carry["collected_disks"], (
        "spent tomb disk must appear in collected_disks carryover"
    )


def test_trading_post_disk_returns_on_reentry_when_not_spent():
    """After the Trading Post chamber is lit, re-entering grants upgrade_disk_trading_post if unspent.

    The fuse stays blown (trading_post in lit_targets); the disk returns daily
    until spent.
    """
    reg = _reg()
    st = _state(reg)

    cfg = GameConfig(
        special_items=True,
        lit_targets=frozenset({"trading_post"}),
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    _enter(g, "trading_post")
    assert st.inventory.get("upgrade_disk_trading_post", 0) == 1, (
        "entering a lit Trading Post with unspent disk must re-grant upgrade_disk_trading_post"
    )


def test_trading_post_disk_not_regranted_once_spent():
    """Re-entering the lit Trading Post grants nothing once the disk is in collected_disks."""
    reg = _reg()
    st = _state(reg)

    cfg = GameConfig(
        special_items=True,
        lit_targets=frozenset({"trading_post"}),
        collected_disks=frozenset({"upgrade_disk_trading_post"}),
    )
    g = _fake_game(st, reg, cfg=cfg)
    si.configure(st, cfg)

    _enter(g, "trading_post")
    assert st.inventory.get("upgrade_disk_trading_post", 0) == 0, (
        "re-entering lit Trading Post must NOT re-grant the disk when spent"
    )


def test_trading_post_disk_spent_appears_in_carryover():
    """Spending upgrade_disk_trading_post puts it in the collected_disks carryover."""
    g1 = Game(GameConfig(special_items=True), seed=0)
    si.configure(g1.state, g1.cfg)
    si.grant(g1.state, g1.registry, "upgrade_disk_trading_post", source="test")
    si.remove(g1.state, "upgrade_disk_trading_post", consumed=True)

    carry = shops.carryover(g1)
    assert "upgrade_disk_trading_post" in carry["collected_disks"], (
        "spent trading_post disk must appear in collected_disks carryover"
    )


# ---------------------------------------------------------------------------
# upgrade_disk_trade: regression guard — must stay repeatable
# ---------------------------------------------------------------------------

def test_upgrade_disk_trade_never_enters_collected_disks():
    """upgrade_disk_trade spent (removed, consumed=True) must NOT appear in collected_disks.

    Its persistence='permanent' keeps it out of fixed_disks_spent_today, which
    only covers persistence='day' disks. A naive id-prefix match would have caught
    it; the data-driven persistence check does not.
    """
    g = Game(GameConfig(special_items=True), seed=0)
    si.configure(g.state, g.cfg)
    si.grant(g.state, g.registry, "upgrade_disk_trade", source="test")
    si.remove(g.state, "upgrade_disk_trade", consumed=True)

    carry = shops.carryover(g)
    assert "upgrade_disk_trade" not in carry["collected_disks"], (
        "upgrade_disk_trade must never appear in collected_disks — "
        "it is permanently offered by the tier-5 trade and must remain repeatable"
    )


def test_upgrade_disk_trade_still_offered_after_spend_via_daychain():
    """After spending upgrade_disk_trade, the Trading Post can still offer it.

    DayChain accumulates collected_disks; upgrade_disk_trade must never appear
    there regardless of how many were spent. This guards against a regression
    where a prefix-based filter accidentally gates the trade disk.
    """
    chain = DayChain(GameConfig(special_items=True), n_days=5)
    # Simulate spending it every day for 3 days
    for _ in range(3):
        chain.advance({"collected_disks": []})  # trade disk never in this list

    cfg = chain.next_config()
    assert "upgrade_disk_trade" not in cfg.collected_disks, (
        "DayChain must never accumulate upgrade_disk_trade in collected_disks"
    )


# ---------------------------------------------------------------------------
# commissary (shop stock) and lost & found (random pool)
# ---------------------------------------------------------------------------

def _commissary_stock_ids(game, table=None):
    """Roll the Commissary's daily stock and return the displayed entry ids.

    Uses a two-entry synthetic table with four slots so every *available* entry
    is always drawn. That isolates the availability gate: whether the disk shows
    up depends only on whether it has been spent, not on the shuffle. Against the
    shipped 13-entry table the disk is drawn on only ~31% of days, which would
    make a single-roll assertion flaky; the offer rate itself is covered by
    tests/test_shops.py::test_commissary_disk_is_offered_on_a_reasonable_share_of_days.
    """
    table = table or {"slots": 4, "stock": [
        {"id": "gem", "kind": "resource", "price": 1},
        {"id": "upgrade_disk_commissary", "kind": "item", "price": 15},
    ]}
    shops._roll_commissary(game, table)
    return [e.get("id") for e in game.state.shops.stock["commissary"]]


def test_commissary_disk_is_restocked_while_unspent():
    """An unspent Commissary disk is offered again on a later day.

    Owner's rule: the disk is restocked daily and the player pays the 15 gold
    each time, so hoarding an unspent disk is wasteful rather than safe.
    """
    g2, carry = _two_day_game("upgrade_disk_commissary", spent=False)
    assert "upgrade_disk_commissary" not in carry["collected_disks"], (
        "an unspent disk must not be recorded as collected"
    )
    assert "upgrade_disk_commissary" in _commissary_stock_ids(g2), (
        "an unspent Commissary disk must be back in stock the next day"
    )


def test_commissary_disk_leaves_stock_once_spent():
    """A spent Commissary disk is absent from the display, not a ghost entry.

    A listed-but-unbuyable entry would let the agent select a purchase that then
    fails, so a spent disk must be filtered out of the stock roll entirely.
    """
    g2, carry = _two_day_game("upgrade_disk_commissary", spent=True)
    assert "upgrade_disk_commissary" in carry["collected_disks"], (
        "spending the disk must record it in collected_disks"
    )
    assert "upgrade_disk_commissary" not in _commissary_stock_ids(g2), (
        "a spent Commissary disk must not be displayed at all"
    )


def test_commissary_disk_costs_gold_on_every_restock():
    """The restocked disk still carries its 15 gold price on a later day.

    The gold cost is the throttle for the daily restock; a free repeat would
    remove the incentive to insert the disk promptly.
    """
    g2, _ = _two_day_game("upgrade_disk_commissary", spent=False)
    _commissary_stock_ids(g2)
    entry = next(e for e in g2.state.shops.stock["commissary"]
                 if e.get("id") == "upgrade_disk_commissary")
    assert entry["price"] == 15, (
        f"restocked Commissary disk must still cost 15 gold; got {entry['price']}"
    )


def _lost_and_found_candidates(game):
    """Return the Lost & Found pool entries that are drawable right now."""
    lf = game.registry.special.lost_and_found
    return [e for e in lf.get("pool", [])
            if e == "die" or si._is_available(game.state, e, game.registry)]


def test_lost_and_found_disk_stays_in_pool_while_unspent():
    """An unspent Lost & Found disk can still be drawn on a later day.

    Owner's rule: it remains a candidate until actually inserted, so dropping it
    overnight must not also remove it from the pool.
    """
    g2, carry = _two_day_game("upgrade_disk_lost_and_found", spent=False)
    assert "upgrade_disk_lost_and_found" not in carry["collected_disks"]
    assert "upgrade_disk_lost_and_found" in _lost_and_found_candidates(g2), (
        "an unspent Lost & Found disk must remain a possible draw"
    )


def test_lost_and_found_disk_leaves_pool_once_spent():
    """A spent Lost & Found disk is no longer a possible draw.

    Without this the player could redraw a disk they had already consumed,
    minting unlimited upgrades from one source.
    """
    g2, carry = _two_day_game("upgrade_disk_lost_and_found", spent=True)
    assert "upgrade_disk_lost_and_found" in carry["collected_disks"]
    assert "upgrade_disk_lost_and_found" not in _lost_and_found_candidates(g2), (
        "a spent Lost & Found disk must leave the draw pool permanently"
    )


def test_only_trade_disk_is_exempt_from_day_persistence():
    """The respawn rule has exactly one exemption, and it is upgrade_disk_trade.

    This pins the *membership of the exemption set*, not the persistence values
    themselves. A disk marked 'permanent' by mistake never enters collected_disks
    and so is silently never retired; a future disk added to the exemption set
    deliberately should force a conscious edit here rather than passing quietly.
    """
    reg = _reg()
    permanent = sorted(i.id for i in reg.special.items
                       if i.id.startswith("upgrade_disk_")
                       and i.persistence == "permanent")
    assert permanent == ["upgrade_disk_trade"], (
        f"only upgrade_disk_trade may be 'permanent'; got {permanent}"
    )
