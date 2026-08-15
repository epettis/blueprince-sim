"""Casino: the slot machine and the roulette table (data/casino.json).

Both games are modelled as ordinary Casino shop-buy entries (BUY_BASE,
env/actions.py), registered via ``shops.register_stock_builder`` the same
shape ``gift_shop.py``/``locksmith.py`` use -- not a new Phase or a new
GameState field. ``commerce.py`` already grants the Casino
``Capability.COMMERCE`` (a no-op until now), so ``shops.on_enter_shop``
already fires on first entry and rolls this room's stock without any
game.py change: a "buy" is a single atomic action, fully resolved inside
one call, the same collapse-a-multi-step-mechanic-into-one-decision move
``pump_room.py``'s docstring documents for the water panel.

Slot machine: two repeatable entries, "quick spin" (0 bonus rerolls) and
"spin and reroll" (up to the room's own cap -- 3 normally, 5 once the
golden lever is fixed, ``state.special.machines_used`` day-scoped exactly
like the manor itself resets every day). Buying either pays the 1-coin base
spin through shops.py's generic price deduction; any bonus rerolls this
module decides to spend are additional 1-coin deductions made here,
resolved with a disclosed greedy heuristic (reroll a Dash first, then an
un-netted Snake) rather than the wiki's full published optimal-strategy
decision tree -- see data/casino.json's meta.notes.

Roulette: three tier entries (5/20/100 coins), each pricing the 50%-red /
uniform-among-6-prizes wheel data/casino.json publishes. "Once per day"
(wiki) is total across every tier, not per tier, so a play disables all
three entries via the same ``entry["disabled"]`` flag
``shops._priced_entry`` already treats as sold_out for the Locksmith's
Electromagnet robbery. Free spins resolve immediately on the same tier's
wheel and stack (data/casino.json's meta.notes quotes the wiki verbatim).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .. import Hook, room_hook
from ... import shops
from ... import special_items as si

DATA_FILENAME = "casino.json"
CASINO_ID = "casino"


@dataclass(frozen=True, slots=True)
class SlotRules:
    spin_cost: int
    bonus_spin_cost: int
    max_bonus_spins: int          # normal lever
    max_bonus_spins_golden: int   # lever fixed with a Broken Lever today
    symbols: tuple[str, ...]
    weights: tuple[float, ...]
    payouts: dict                 # three_coins/four_coins/.../double_multiplier


@dataclass(frozen=True, slots=True)
class RoulettePrize:
    kind: str                              # coins/keys/gems/dice/steps/allowance/free_spins/multi
    amount: int = 0
    grants: tuple["RoulettePrize", ...] = ()  # only populated when kind == "multi"


@dataclass(frozen=True, slots=True)
class RouletteTier:
    cost: int
    prizes: tuple[RoulettePrize, ...]  # exactly 6, data/casino.json's published row order


@dataclass(frozen=True, slots=True)
class CasinoRules:
    slot: SlotRules
    roulette_tiers: tuple[RouletteTier, ...]
    roulette_spots: int
    roulette_red_spots: int


_RULES_CACHE: dict[Path, CasinoRules] = {}


def _parse_prize(raw: dict) -> RoulettePrize:
    grants = tuple(_parse_prize(g) for g in raw.get("grants", []))
    return RoulettePrize(kind=raw["kind"], amount=raw.get("amount", 0), grants=grants)


def load_casino_rules(data_dir: Path) -> CasinoRules:
    """Parse data/casino.json's slot-machine and roulette tables, cached per data_dir."""
    data_dir = Path(data_dir)
    cached = _RULES_CACHE.get(data_dir)
    if cached is not None:
        return cached
    raw = json.loads((data_dir / DATA_FILENAME).read_text())
    sm = raw["slot_machine"]
    slot = SlotRules(
        spin_cost=sm["spin_cost"],
        bonus_spin_cost=sm["bonus_spin_cost"],
        max_bonus_spins=sm["max_bonus_spins"],
        max_bonus_spins_golden=sm["max_bonus_spins_golden"],
        symbols=tuple(sm["reels"]["symbols"]),
        weights=tuple(sm["reels"]["weights"]),
        payouts=dict(sm["payouts"]),
    )
    rl = raw["roulette"]
    tiers = tuple(
        RouletteTier(cost=t["cost"], prizes=tuple(_parse_prize(p) for p in t["prizes"]))
        for t in rl["tiers"]
    )
    rules = CasinoRules(
        slot=slot, roulette_tiers=tiers,
        roulette_spots=rl["spots"], roulette_red_spots=rl["red_spots"],
    )
    _RULES_CACHE[data_dir] = rules
    return rules


# --------------------------------------------------------------- slot machine

def _roll_reel(rng, slot: SlotRules) -> str:
    idx = rng.roll_weighted("casino_slot_reel", slot.weights)
    return slot.symbols[idx]


def _pick_reroll_target(symbols: list[str]) -> int | None:
    """Which reel index to spend the next bonus reroll on, or None to stop.

    Disclosed simplification (data/casino.json's meta.notes): a greedy
    heuristic, not the wiki's full published optimal-strategy decision tree.
    Dash never contributes to any payout, so it is always worth rerolling
    first; an un-netted Snake zeroes the whole payout, so it is the only
    other symbol this heuristic ever spends a coin chasing.
    """
    if "dash" in symbols:
        return symbols.index("dash")
    if "snake" in symbols and "net" not in symbols:
        return symbols.index("snake")
    return None


def score_slot(counts: Counter, payouts: dict) -> int:
    """Resolve one slot result's coin payout from its symbol counts.

    Order matches data/casino.json's meta.notes exactly: crown/coin/
    coin-stack/clover sum first, then Snake's zeroing (skipped entirely
    when a Net is present, in which case each snake instead adds
    ``net_per_snake``, not stacked across multiple nets -- the wiki's own
    disclosed duplicate-net simplification), then Double's multiplier last,
    stacking with itself.
    """
    base = 0
    if counts.get("crown", 0) == 4:
        base += payouts["four_crowns"]
    coins = counts.get("coin", 0)
    if coins == 4:
        base += payouts["four_coins"]
    elif coins == 3:
        base += payouts["three_coins"]
    stacks = counts.get("coin_stack", 0)
    if stacks == 4:
        base += payouts["four_coin_stacks"]
    elif stacks == 3:
        base += payouts["three_coin_stacks"]
    base += payouts["clover_each"] * counts.get("clover", 0)

    snakes = counts.get("snake", 0)
    nets = counts.get("net", 0)
    if nets >= 1:
        base += payouts["net_per_snake"] * snakes
    elif snakes >= 1:
        base = 0

    doubles = counts.get("double", 0)
    return base * (payouts["double_multiplier"] ** doubles)


def resolve_slot_purchase(game, entry: dict) -> None:
    """Resolve one slot-machine purchase: roll 4 reels, spend up to
    ``entry["max_bonus"]`` bonus rerolls (None = the room's own cap, 3 or 5
    while golden), then grant the payout. The base 1-coin spin price is
    already deducted by shops.buy() before this runs; bonus rerolls are
    additional 1-coin spends made here, capped by both the budget and
    affordability.
    """
    state = game.state
    rules = load_casino_rules(game.registry.data_dir)
    slot = rules.slot
    golden = CASINO_ID in state.special.machines_used
    room_cap = slot.max_bonus_spins_golden if golden else slot.max_bonus_spins
    cap = entry.get("max_bonus")
    cap = room_cap if cap is None else min(cap, room_cap)

    symbols = [_roll_reel(game.rng, slot) for _ in range(4)]
    used = 0
    while used < cap and state.coins >= slot.bonus_spin_cost:
        target = _pick_reroll_target(symbols)
        if target is None:
            break
        state.coins -= slot.bonus_spin_cost
        symbols[target] = _roll_reel(game.rng, slot)
        used += 1

    payout = score_slot(Counter(symbols), slot.payouts)
    if payout > 0:
        bonus = si.on_coins_granted(state, game.registry, payout)
        state.coins += payout + bonus
        state.items_found_log.append(("coins", payout))


# ------------------------------------------------------------------ roulette

def _grant_one(game, kind: str, amount: int) -> None:
    state = game.state
    match kind:
        case "coins":
            bonus = si.on_coins_granted(state, game.registry, amount)
            state.coins += amount + bonus
            state.items_found_log.append(("coins", amount))
        case "keys":
            state.keys += amount
            state.items_found_log.append(("key", amount))
        case "gems":
            state.gems += amount
            state.items_found_log.append(("gem", amount))
        case "dice":
            state.dice += amount
            state.items_found_log.append(("die", amount))
        case "steps":
            state.steps += amount
        case "allowance":
            state.allowance += amount


def _grant_prize(game, prize: RoulettePrize) -> None:
    if prize.kind == "multi":
        for sub in prize.grants:
            _grant_one(game, sub.kind, sub.amount)
    else:
        _grant_one(game, prize.kind, prize.amount)


def resolve_roulette_purchase(game, entry: dict, stored: list[dict]) -> None:
    """Resolve one roulette purchase at ``entry``'s tier: a 50% chance of a
    red (nothing) spot, else a uniform pick among that tier's 6 published
    prizes -- an equivalent distribution to 12 named spots (6 red, 6
    prizes), which the wiki never assigns individual positions to. A
    "free_spins" result queues 2 more immediate spins of the SAME wheel,
    stacking recursively (data/casino.json's meta.notes).

    "Once per day" (wiki) is total across every cost tier, so every
    ``casino_roulette`` entry in ``stored`` is disabled once this resolves,
    regardless of which tier was played.
    """
    rules = load_casino_rules(game.registry.data_dir)
    tier = next(t for t in rules.roulette_tiers if t.cost == entry["price"])
    rng = game.rng

    pending = 1
    while pending > 0:
        pending -= 1
        if rng.chance("casino_roulette_red", 0.5):
            continue
        idx = rng.randint("casino_roulette_prize", 0, len(tier.prizes) - 1)
        prize = tier.prizes[idx]
        if prize.kind == "free_spins":
            pending += prize.amount
        else:
            _grant_prize(game, prize)

    for e in stored:
        if e.get("kind") == "casino_roulette":
            e["disabled"] = True


# --------------------------------------------------------------- stock builder

def _build_casino_stock(game, table: dict) -> None:
    """Build the Casino's daily stock: two slot-machine entries (quick spin
    / spin-and-reroll) plus one entry per data/casino.json roulette tier.
    Ignores ``table`` (data/shops.json has no "casino" entry -- the whole
    stock comes from data/casino.json instead, the same shape
    ``pump_room.py`` reads its own dedicated data file rather than
    shops.json).
    """
    del table
    rules = load_casino_rules(game.registry.data_dir)
    entries = [
        {"id": "slot_quick_spin", "kind": "casino_slot",
         "price": rules.slot.spin_cost, "max_bonus": 0, "sold": 0},
        {"id": "slot_spin_and_reroll", "kind": "casino_slot",
         "price": rules.slot.spin_cost, "max_bonus": None, "sold": 0},
    ]
    for tier in rules.roulette_tiers:
        entries.append({
            "id": f"roulette_{tier.cost}", "kind": "casino_roulette",
            "price": tier.cost, "sold": 0,
        })
    game.state.shops.stock[CASINO_ID] = entries


shops.register_stock_builder(CASINO_ID, _build_casino_stock)


@room_hook(CASINO_ID, Hook.ON_ENTER)
def _mark_modelled(game, room, ctx_room) -> None:
    """Deliberate no-op, registered only so tools/validate_data.py's
    ``find_divergences`` (Kind 2) recognises the Casino as Python-modelled.

    The room's real behaviour -- both games, driven entirely by
    data/casino.json -- runs through shops.py's stock-builder pipeline
    (``commerce.py`` already grants ``Capability.COMMERCE``; game.py's
    generic on-enter dispatch calls ``shops.on_enter_shop`` for any COMMERCE
    room without naming "casino"), not through this hook and not through
    rooms.json's ``effects``/``items.guaranteed`` (both deliberately empty
    here). Without a room_hook registered at this id, none of the audit's
    three channels sees anything and it flags a false gap -- exactly the
    case its own docstring names: "a room can be modelled entirely in
    Python rather than in data".
    """
