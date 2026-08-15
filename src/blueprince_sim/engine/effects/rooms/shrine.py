"""Shrine: the offering bowl -- eight blessings and the theft curse.

Data: data/shrine.json (band table, per-blessing coin costs, blessing text,
curse resource-loss table). Deposit 1-80 gold at the Shrine to receive one
of eight blessings lasting 3-7 days (the granting day counts as day 1 of
its duration); taking the offering back curses the player for 2 days
instead. Only one blessing (or the curse) can be active at a time.

Six of eight blessings are live: Dancer, High Roller, Gardener, Tinkerer,
General, Berry Picker. Chef (needs per-day spread-dish tracking on the
Dining Room) and Monk (needs grounds drafting) stay inert, carrying
``implemented: false`` on their own records in data/shrine.json.

This module owns the room's identity (id/state queries, the donate/take-back
action bodies, the curse's resource-loss table, Berry Picker's random-pick
pool). The mechanics that hook into an EXISTING per-draft/per-redraw/
per-rotation call site live at that site in game.py instead, so this module
never duplicates game.py's own dispatch: Game._place_room calls
:func:`on_room_drafted` (curse loss, High Roller's die-on-Shop, Tinkerer's
cross-trigger, General's gem bonus), Game.redraw's DIE branch checks
:func:`blessing_active` directly for High Roller's +5 coins, and
Game.rotation_available/rotate_options check it directly for Dancer's paid
rotation source. Game.reset() checks it directly (after building the day's
decks) for Gardener's 8-Courtyard injection, since decks do not persist
day to day and so must be re-injected every day the blessing is active.

Save-scoped, day-decayed state (GameConfig/GameState shrine_* fields; see
their own comments): the blessing id, its two day-counts (blessing/curse)
and the parked coin amount survive an attempt wrap the way stars/
main_course_bonus do, but decay day to day via env/multiday.py::DayChain the
same mechanical way mail_transit_days does (replace from today's carryover,
then decrement by 1, floored at 0).

Not modelled (published wiki refinements, out of scope for this pass):
the Corriyard counting as Hallway only (not Green Room) and colour-changing
Cloister upgrades still counting as Green Room, for curse purposes --
see data/shrine.json's own curse.notes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ... import experiments
from ...grid import OPPOSITE, rank_of

DATA_FILENAME = "shrine.json"
SHRINE_ROOM_ID = "shrine"


@dataclass(frozen=True, slots=True)
class ShrineBand:
    min_coins: int   # inclusive lower bound of the offering band
    max_coins: int   # inclusive upper bound of the offering band
    duration_days: int  # blessing duration this band grants, counting the day granted


@dataclass(frozen=True, slots=True)
class ShrineBlessing:
    id: str            # stable snake_case id, unique across shrine.json
    name: str           # wiki display name ("Blessing of the Dancer")
    text: str           # wiki effect wording, verbatim
    costs: tuple[int, ...]  # canonical coin cost per band (band order); the lower
                            # of each published two-coin pair -- see data/shrine.json
    implemented: bool  # False = inert; can_donate always refuses it
    blocked_on: str | None  # reason it is inert, or None when implemented


@dataclass(frozen=True, slots=True)
class ShrineCurse:
    duration_days: int  # days the curse lasts once triggered
    # per-colour-category resource loss, additive across every colour a
    # drafted room carries (Room.is_category) -- see data/shrine.json's own
    # curse.notes for the two published worked examples this reproduces
    resource_loss_per_category: dict[str, dict[str, int]]
    exempt_room_ids: frozenset[str]  # room ids the curse never charges


@dataclass(frozen=True)
class ShrineRules:
    bands: tuple[ShrineBand, ...]           # 5 bands, ascending duration
    blessings: tuple[ShrineBlessing, ...]   # 8 blessings, data-file order
    blessing_index: dict[str, int]          # blessing id -> its index in blessings
    curse: ShrineCurse                      # theft-curse duration/loss/exemption rules


_RULES_CACHE: dict[Path, ShrineRules] = {}


def load_shrine_rules(data_dir: Path) -> ShrineRules:
    """Parse data/shrine.json into the frozen rules object, cached per data_dir."""
    data_dir = Path(data_dir)
    cached = _RULES_CACHE.get(data_dir)
    if cached is not None:
        return cached
    raw = json.loads((data_dir / DATA_FILENAME).read_text())
    bands = tuple(
        ShrineBand(b["min_coins"], b["max_coins"], b["duration_days"]) for b in raw["bands"]
    )
    blessings = tuple(
        ShrineBlessing(
            id=b["id"], name=b["name"], text=b["text"], costs=tuple(b["costs"]),
            implemented=bool(b.get("implemented", False)),
            blocked_on=b.get("meta", {}).get("blocked_on"),
        )
        for b in raw["blessings"]
    )
    raw_curse = raw["curse"]
    curse = ShrineCurse(
        duration_days=raw_curse["duration_days"],
        resource_loss_per_category={
            cat: dict(deltas) for cat, deltas in raw_curse["resource_loss_per_category"].items()
        },
        exempt_room_ids=frozenset(raw_curse["exempt_room_ids"]),
    )
    parsed = ShrineRules(
        bands=bands, blessings=blessings,
        blessing_index={b.id: i for i, b in enumerate(blessings)},
        curse=curse,
    )
    _RULES_CACHE[data_dir] = parsed
    return parsed


def rules(game) -> ShrineRules:
    """This game's Shrine rules, loaded from its own registry's data directory."""
    return load_shrine_rules(game.registry.data_dir)


# ------------------------------------------------------------------ position/state

def at_shrine(game) -> bool:
    """True when the player is standing inside the drafted Shrine."""
    if not game.inside_outer_room:
        return False
    outer_room = game.drafted_outer_room
    return outer_room is not None and outer_room.id == SHRINE_ROOM_ID


def blessing_active(game, blessing_id: str) -> bool:
    """True while ``blessing_id`` is today's active blessing (days remaining > 0)."""
    st = game.state
    return st.shrine_blessing_days > 0 and st.shrine_blessing_id == blessing_id


def curse_active(game) -> bool:
    """True while the Shrine curse is in effect today."""
    return game.state.shrine_curse_days > 0


# ------------------------------------------------------------------ donate / take back

def can_donate(game, blessing_idx: int, duration_idx: int) -> bool:
    """Legal exactly at the Shrine, with no blessing or curse already active, for
    an implemented blessing whose canonical coin cost is currently affordable."""
    if not at_shrine(game):
        return False
    st = game.state
    if st.shrine_blessing_days > 0 or st.shrine_curse_days > 0:
        return False
    r = rules(game)
    if not (0 <= blessing_idx < len(r.blessings) and 0 <= duration_idx < len(r.bands)):
        return False
    blessing = r.blessings[blessing_idx]
    if not blessing.implemented:
        return False
    return st.coins >= blessing.costs[duration_idx]


def donate(game, blessing_idx: int, duration_idx: int) -> None:
    """Pay the canonical coin cost and grant that blessing for its band's duration."""
    assert can_donate(game, blessing_idx, duration_idx), "cannot donate to the Shrine"
    st = game.state
    r = rules(game)
    blessing = r.blessings[blessing_idx]
    band = r.bands[duration_idx]
    cost = blessing.costs[duration_idx]
    st.coins -= cost
    st.shrine_blessing_id = blessing.id
    st.shrine_blessing_days = band.duration_days
    st.shrine_offered_coins = cost


def can_take_back(game) -> bool:
    """Legal at the Shrine while a blessing is currently active."""
    return at_shrine(game) and game.state.shrine_blessing_days > 0


def take_back(game) -> None:
    """Refund the parked coins, drop the blessing, and curse the player for the
    data-file's curse duration (data/shrine.json's curse.duration_days).

    Also permanently unlocks the Gift Shop's Cursed Coffers (state.shops.gift_unlocks,
    the same one-time-forever list shops.py already reads for cursed_effigy_unlocked):
    the wiki's own trigger is clicking the curse icon on the Blueprint screen, which has
    no analogue here, so becoming cursed this way stands in for it.
    """
    assert can_take_back(game), "no active blessing to take back"
    st = game.state
    st.coins += st.shrine_offered_coins
    st.shrine_offered_coins = 0
    st.shrine_blessing_id = ""
    st.shrine_blessing_days = 0
    st.shrine_curse_days = rules(game).curse.duration_days
    st.shops.gift_unlocks.append("cursed_effigy_unlocked")


# ------------------------------------------------------------------ Gardener

GARDENER_ROOM_ID = "courtyard"
GARDENER_ROOM_COPIES = 8  # wiki: "Add 8 Courtyards to your draft pool"


def apply_gardener_injection(game) -> None:
    """Inject 8 Courtyards into today's live decks, while Gardener is active.

    Called from Game.reset() right after ``self.state`` is assigned (decks
    do not persist day to day, so the injection must repeat every morning
    the blessing is still active, unlike the day-count carry-over itself).
    A no-op on any day the blessing is not active.
    """
    from ...decks import inject_rooms_undealt

    st = game.state
    if not (st.shrine_blessing_days > 0 and st.shrine_blessing_id == "gardener"):
        return
    inject_rooms_undealt(st, game.registry, [GARDENER_ROOM_ID] * GARDENER_ROOM_COPIES,
                         game.rng, label="shrine_gardener_inject")


# ------------------------------------------------------------------ curse resource loss

def _curse_loss_for(game, room) -> dict[str, int]:
    """Per-resource loss curse-drafting ``room`` incurs, additive across its colours."""
    curse = rules(game).curse
    if room.id in curse.exempt_room_ids:
        return {}
    totals: dict[str, int] = {}
    for category, deltas in curse.resource_loss_per_category.items():
        if room.is_category(category):
            for res, amt in deltas.items():
                totals[res] = totals.get(res, 0) + amt
    return totals


def _apply_curse_loss(game, room) -> None:
    st = game.state
    loss = _curse_loss_for(game, room)
    if not loss:
        return
    st.steps = max(0, st.steps - loss.get("steps", 0))
    st.keys = max(0, st.keys - loss.get("keys", 0))
    st.gems = max(0, st.gems - loss.get("gems", 0))
    st.coins = max(0, st.coins - loss.get("coins", 0))


# ------------------------------------------------------------------ draft-time blessings

def _maybe_general_bonus(game) -> None:
    """Blessing of the General: +5 gems after a Red Room draft with >=5 red-holding ranks."""
    st = game.state
    ranks = {
        rank_of(cell) for cell, idx in enumerate(st.grid)
        if idx >= 0 and game.registry.rooms[idx].is_category("red")
    }
    if len(ranks) >= 5:
        st.gems += 5


def on_room_drafted(game, room) -> None:
    """Fire every draft-time Shrine effect for a freshly-placed on-grid room.

    Called from Game._place_room, once per real on-grid draft (never the
    day-start Entrance Hall/Antechamber/Foundation placements). The four
    checks are independent, not a match/case: a multicoloured room, or a room
    that is simultaneously Shop and Mechanical, can fire more than one.
    """
    if curse_active(game):
        _apply_curse_loss(game, room)
    if blessing_active(game, "high_roller") and room.is_category("shop"):
        game.state.dice += 1
    if blessing_active(game, "tinkerer") and room.is_category("mechanical"):
        experiments.trigger_success(game)
    if blessing_active(game, "general") and room.is_category("red"):
        _maybe_general_bonus(game)


# ------------------------------------------------------------------ Berry Picker

def _berry_candidates(game, pending) -> list:
    """Legal, still-available, currently-affordable rooms at ``pending``'s doorway,
    disregarding rarity -- the pool Berry Picker draws from uniformly.

    Filtered by affordability up front so a random pick can never land on a
    room the player cannot pay for: ordinary drafting always keeps a free
    option in slot 0/1, but Berry Picker's random pick has no such built-in
    guarantee.
    """
    from ...draft import DraftContext, room_draftable
    from ...state import DraftOption

    st = game.state
    registry = game.registry
    cell = pending.target_cell
    entry_dir = OPPOSITE[pending.direction]
    from_idx = st.grid[pending.from_cell]
    from_room = registry.rooms[from_idx] if from_idx >= 0 else None
    ctx = DraftContext(st, registry, game.cfg, game.rng, game.placed_ids, from_room,
                       colour=pending.colour)
    out = []
    for room in registry.rooms:
        if room.rarity is None:
            continue
        if not room_draftable(ctx, room, cell, entry_dir, set()):
            continue
        deck = st.deck(room.rarity_idx, not room.is_free)
        if room.idx not in deck.order[deck.pos:]:
            continue
        probe = DraftOption(room_idx=room.idx, orientation=room.door_mask, gem_cost=0, slot=2)
        if not game.affordable(room, probe):
            continue
        out.append(room)
    return out


def berry_pick_available(game, pending) -> bool:
    """True while Berry Picker is active and at least one candidate room exists."""
    if not blessing_active(game, "berry_picker"):
        return False
    return bool(_berry_candidates(game, pending))


def pick_berry(game, pending):
    """Uniformly choose a room disregarding rarity, deal its card, and roll one
    of its legal orientations (own RNG substreams, distinct from the ordinary
    rarity-weighted deal). Returns ``(room, orientation)``.
    """
    from ...placement import legal_orientations

    candidates = _berry_candidates(game, pending)
    assert candidates, "no room available to berry-pick"
    room = game.rng.choice("shrine_berry_room", candidates)
    deck = game.state.deck(room.rarity_idx, not room.is_free)
    deck.deal_next(lambda card, target=room.idx: card == target)
    cell = pending.target_cell
    entry_dir = OPPOSITE[pending.direction]
    orientations = legal_orientations(room, cell, entry_dir, game.state, game.cfg)
    orientation = game.rng.choice("shrine_berry_orientation", orientations)
    return room, orientation
