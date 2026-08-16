"""Conservatory: the drawing board (the remodel).

Drafting the Conservatory stocks its drawing board with three floorplans
(:func:`stock_drawing_board`, ``Hook.ON_PLACE``). Standing in the room, the
player may click each floorplan once and set that room's rarity to any of the
four levels (``Game.can_remodel``/``Game.remodel``), which writes the SAME
permanent record the Gear Wrench writes -- ``state.permanent_rarity``, via
``Game._write_permanent_rarity`` -- so the two mechanics share one slot rather
than two competing ones.

``Capability.DRAWING_BOARD`` is what ``Game.can_remodel`` resolves the board's
cell through, so ``game.py`` never names this room's id -- the same shape
``pump_room.py``'s ``Capability.PUMP_PANEL`` and ``office.py``'s
``Capability.OFFICE_TERMINAL`` use.

Three offers, drawn **uniformly at random with replacement** from the day's
remodel pool -- the owner's ruling from play, which settles what the datamine
left open ("the table presents three random rooms that passed the filters",
with no rarity term and no with/without-replacement statement). With
replacement means the three offers can name the same room twice; clicking both
slots simply sets that room's rarity twice, last write winning.

The pool is ``decks.eligible_pool`` (which already enforces "Studio Additions
must have been added", "Found Floorplans must have been found", Repellent bans
and Upgrade-Disk substitution) minus data/conservatory.json's own two lists.
It deliberately carries no "this room's rarity has already been changed"
exclusion: the owner ruled from play that a modified room stays eligible on
future days, so the pool never shrinks (docs/rooms.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...decks import eligible_pool
from .. import Capability, Hook, provides, room_hook

DATA_FILENAME = "conservatory.json"
CONSERVATORY_ID = "conservatory"

provides(CONSERVATORY_ID, Capability.DRAWING_BOARD)

#: Floorplans the board presents per stocking. The wiki's own effect text
#: ("re-rolls the rarity of 3 rooms in your pool") and the datamine ("three
#: random rooms") agree on three.
BOARD_OFFERS = 3

#: **ASSUMPTION, UNSOURCED.** How many times each presented floorplan may be
#: clicked before it stops responding. Neither the wiki nor the datamine says
#: whether the board is once per day, once per Conservatory, or unlimited, and
#: the owner's "a modified room can be modified in future days" ruling removes
#: the exclusion that would have made unlimited self-limiting. One click per
#: floorplan is the reading the wiki's "each time you draft it" phrasing
#: supports: the board is re-stocked by :func:`stock_drawing_board` on every
#: Conservatory draft (at most once a day, since a floorplan is drafted at most
#: once), and each of its three rows answers once.
#:
#: This constant is the whole bound. Any finite value terminates a Conservatory
#: day: the board offers at most ``BOARD_OFFERS * CLICKS_PER_FLOORPLAN``
#: actions between stockings, every click strictly increments
#: ``GameState.remodel_clicks``, and nothing ever decrements it. Raising it is
#: a one-line edit.
CLICKS_PER_FLOORPLAN = 1

#: RNG substream for the offer draw and for the deck moves a click makes.
RNG_LABEL = "conservatory_board"


@dataclass(frozen=True, slots=True)
class RemodelRules:
    always_excluded: frozenset[str]  # dropped from the pool unconditionally
    draft_gated: frozenset[str]      # dropped until drafted at least once


_RULES_CACHE: dict[Path, RemodelRules] = {}


def load_remodel_rules(data_dir: Path) -> RemodelRules:
    """Parse data/conservatory.json's offer-filter lists, cached per data_dir."""
    data_dir = Path(data_dir)
    cached = _RULES_CACHE.get(data_dir)
    if cached is not None:
        return cached
    raw = json.loads((data_dir / DATA_FILENAME).read_text())["remodel"]
    rules = RemodelRules(
        always_excluded=frozenset(raw["always_excluded"]),
        draft_gated=frozenset(raw["draft_gated"]),
    )
    _RULES_CACHE[data_dir] = rules
    return rules


def remodel_pool(game) -> list[str]:
    """Room ids the drawing board may offer right now, in registry order.

    ``decks.eligible_pool`` is the base: a room the day's decks do not contain
    has no rarity bucket to move between. data/conservatory.json's
    ``always_excluded`` and ``draft_gated`` lists then apply the datamined
    filters that survive the owner's ruling.

    Falls back to the unfiltered eligible pool when fewer than
    ``BOARD_OFFERS`` rooms survive, the datamine's own "presents three ignoring
    every filter" clause. Unreachable with today's data (the filters drop at
    most five rooms from a pool of ~90) and kept for the same reason the audit
    keeps any unreachable branch: the alternative is a silent empty board the
    day the data changes.
    """
    rules = load_remodel_rules(game.registry.data_dir)
    pool = [r.id for r in eligible_pool(game.registry, game.cfg)]
    filtered = [
        rid for rid in pool
        if rid not in rules.always_excluded
        and (rid not in rules.draft_gated or game.state.draft_counts.get(rid, 0) > 0)
    ]
    return filtered if len(filtered) >= BOARD_OFFERS else pool


def slot_available(state, slot: int) -> bool:
    """Is board row ``slot`` still answering clicks?

    False for a board that was never stocked (no Conservatory drafted today),
    for a row index outside the stocked board, and for a row already clicked
    ``CLICKS_PER_FLOORPLAN`` times.
    """
    if not 0 <= slot < len(state.remodel_offers):
        return False
    return state.remodel_clicks[slot] < CLICKS_PER_FLOORPLAN


def click_floorplan(game, slot: int, rarity_idx: int) -> None:
    """Resolve one click on board row ``slot``, setting that room's rarity.

    Writes the Gear Wrench's own permanent record through
    ``Game._write_permanent_rarity``, so a remodelled room starts every later
    day in the chosen bucket and a remodel can reset a wrench-set rarity, both
    of which the wiki requires of the shared slot.

    A no-op click -- picking the floorplan's own natal rarity -- is a click
    like any other (owner ruling: *"clicking a floorplan, even without actually
    changing the rarity, counts as changing the rarity"*). It consumes the row
    here and, exactly as a Gear Wrench pick of the natal rarity does, leaves no
    ``permanent_rarity`` entry behind, because the room's rarity genuinely is
    its natal one.
    """
    game._write_permanent_rarity(game.state.remodel_offers[slot], rarity_idx,
                                 label=RNG_LABEL)
    game.state.remodel_clicks[slot] += 1


@room_hook(CONSERVATORY_ID, Hook.ON_PLACE)
def stock_drawing_board(game, room, ctx_room) -> None:
    """Stock the board with ``BOARD_OFFERS`` floorplans drawn uniformly at
    random WITH replacement from :func:`remodel_pool`, and clear every row's
    click count.

    One independent ``randint(0, len(pool) - 1)`` per row off the ``RNG_LABEL``
    substream: each row is an independent uniform draw over the same unchanged
    pool, which is what "with replacement" means and is why a repeat is
    possible rather than special-cased.

    Re-stocking discards whatever the previous board held. Reachable only by
    drafting a second Conservatory in one day, which the one-copy-per-floorplan
    deck rule prevents today.
    """
    pool = remodel_pool(game)
    if not pool:
        return
    hi = len(pool) - 1
    game.state.remodel_offers = tuple(
        pool[game.rng.randint(RNG_LABEL, 0, hi)] for _ in range(BOARD_OFFERS))
    game.state.remodel_clicks = [0] * BOARD_OFFERS
