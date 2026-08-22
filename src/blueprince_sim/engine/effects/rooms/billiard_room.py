"""Billiard Room: the Dartboard puzzle inside it, solved once per day for a
day-banded prize.

Data: data/billiard_room.json (day bands, per-outcome weights, fallback
notes). The Dartboard is a puzzle object inside the Billiard Room, never a
room of its own -- it has no rooms.json record. Solving it is a player-skill
act and this sim assumes puzzles are solved (docs/doctrine.md), so there is
no action id for it: entering a freshly-drafted Billiard Room auto-solves the
Dartboard and grants its prize, at most once per day across every Billiard
Room cell (GameState.dartboard_solved_today) -- not per cell via
st.entered[cell], since a second billiard_room id can appear on the grid
(game.py: "duplicates are only possible via the Chamber of Mirrors") and
would otherwise pay out again.

Reward roll: Rng.roll_weighted picks one of four outcomes (Secret Garden Key,
Silver Key, Keycard, 2 keys) from today's band. Bands are checked in the
wiki's own top-to-bottom order -- the open-ended Veteran Mode / Room 46
reached / high-day band first, then each finite day range. Secret Garden Key
and Silver Key fall back to the Keycard when unavailable (special_items'
own uniqueness/removed-today gating); the Keycard itself falls back to 2
keys when already held -- the wiki's own published fallback chain
("Keycard -> 2 keys"), generalised to every rolled outcome rather than
hardcoded to the two Key items.

Scoped to the base "billiard_room" id only: room_hook fires for exactly one
room id, never its upgrade variants (speakeasy__ix10, break_room__ix11,
pool_hall__ix12 are not wired up here).

Not modelled: the Bullseye Trophy (40 lifetime solves) -- needs a save-scoped
counter, unruled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import Hook, room_hook
from ..items import keycard
from ... import special_items as si

DATA_FILENAME = "billiard_room.json"
BILLIARD_ROOM_ID = "billiard_room"

SECRET_GARDEN_KEY_ID = "secret_garden_key"
SILVER_KEY_ID = "silver_key"
KEYCARD_OUTCOME = "keycard"
TWO_KEYS_OUTCOME = "two_keys"

REWARD_ROLL_LABEL = "billiard_room_dartboard_reward"


@dataclass(frozen=True, slots=True)
class DartboardBand:
    id: str                   # data-file band id, e.g. "day_1_7"
    min_day: int               # inclusive lower bound of the band
    max_day: int | None        # inclusive upper bound, or None = open-ended
    outcomes: tuple[str, ...]  # fixed order matching `weights` below
    weights: tuple[float, ...]  # need not sum to 100; roll_weighted normalises


_BANDS_CACHE: dict[Path, tuple[DartboardBand, ...]] = {}
_last_dir: Path | None = None    # identity memo: the data_dir object from the last call
_last_bands: tuple[DartboardBand, ...] | None = None  # ...and the bands it resolved to


def load_bands(data_dir: Path) -> tuple[DartboardBand, ...]:
    """Parse data/billiard_room.json's band table, cached per data_dir.

    Checks by identity first (Registry.data_dir is the same object for a whole
    run, so this never hashes a Path on the hot path) before falling back to
    the path-keyed dict for the case data_dir actually varies between calls.
    """
    global _last_dir, _last_bands
    orig_dir = data_dir
    if orig_dir is _last_dir:
        return _last_bands
    data_dir = Path(data_dir)
    cached = _BANDS_CACHE.get(data_dir)
    if cached is not None:
        _last_dir, _last_bands = orig_dir, cached
        return cached
    raw = json.loads((data_dir / DATA_FILENAME).read_text())
    bands = tuple(
        DartboardBand(
            id=b["id"], min_day=b["min_day"], max_day=b.get("max_day"),
            outcomes=tuple(b["weights"].keys()), weights=tuple(b["weights"].values()),
        )
        for b in raw["bands"]
    )
    _BANDS_CACHE[data_dir] = bands
    _last_dir, _last_bands = orig_dir, bands
    return bands


def _band_for(game) -> DartboardBand:
    """Today's reward band, checked in the wiki's own top-to-bottom order: the
    open-ended Veteran Mode / Room 46 / high-day band first (by config flag OR
    reaching its own min_day), then each finite day range in turn."""
    bands = load_bands(game.registry.data_dir)
    cfg, st = game.cfg, game.state
    open_band = next(b for b in bands if b.max_day is None)
    if cfg.veteran_mode or cfg.room46_reached or st.day >= open_band.min_day:
        return open_band
    for band in bands:
        if band.max_day is not None and band.min_day <= st.day <= band.max_day:
            return band
    return open_band  # safety net: every day is covered by a finite band above open_band.min_day


def _roll_outcome(game, band: DartboardBand) -> str:
    """Rolls one of ``band``'s outcomes on this puzzle's own RNG substream."""
    idx = game.rng.roll_weighted(REWARD_ROLL_LABEL, band.weights)
    return band.outcomes[idx]


def _grant_reward(game, outcome: str) -> str:
    """Grants ``outcome``, applying the wiki's published fallback chain
    (Secret Garden Key / Silver Key -> Keycard -> 2 keys) whenever the rolled
    prize cannot be handed over as rolled. Returns the outcome actually
    granted, which may differ from ``outcome`` after falling through."""
    state, registry = game.state, game.registry
    if outcome in (SECRET_GARDEN_KEY_ID, SILVER_KEY_ID) and si._is_available(
            state, outcome, registry):
        si.grant(state, registry, outcome, source="dartboard")
        return outcome
    if outcome != TWO_KEYS_OUTCOME and not keycard.held(state):
        keycard.grant(state)
        return KEYCARD_OUTCOME
    state.keys += 2
    state.items_found_log.append(("key", 2))
    return TWO_KEYS_OUTCOME


@room_hook(BILLIARD_ROOM_ID, Hook.ON_ENTER)
def solve_dartboard(game, room, ctx_room) -> None:
    """Auto-solves the Dartboard on first entry and grants its day-banded
    prize, at most once per day (GameState.dartboard_solved_today)."""
    st = game.state
    if st.dartboard_solved_today:
        return
    st.dartboard_solved_today = True
    band = _band_for(game)
    outcome = _roll_outcome(game, band)
    _grant_reward(game, outcome)
