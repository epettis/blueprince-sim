"""Multi-day loop wrapper for the Blue Prince simulator.

Blue Prince is not a single-day game: each run sets the initial conditions for
the next and the next, for roughly 200 days, then restarts.  This module
provides ``DayChain``, a lightweight coordinator that tracks one such 200-day
attempt and vends a per-day ``GameConfig`` with the correct day counter and
carry-over flags already applied.

The RL environment stays a single-day Gymnasium env — one episode == one day.
``DayChain`` is the glue between episodes: on terminal step, the env calls
``advance(game.carryover())``, which merges any newly-discovered flags into the
chain's running state and increments the day counter.  After day *n_days* the
chain wraps: day resets to 1 and all carried flags are cleared (fresh attempt).

This module is intentionally engine-agnostic — it only imports ``GameConfig``
and uses ``dataclasses.replace``.  The env layer is responsible for creating a
``Game`` from the yielded config and threading the ``carryover()`` dict back in.
"""

from __future__ import annotations

import dataclasses

from ..config import GameConfig

# Keys that ``Game.carryover()`` can return and that map 1-to-1 onto
# ``GameConfig`` bool fields.  Keeping this list explicit (rather than
# introspecting GameConfig) makes the contract readable and testable.
_CARRYOVER_KEYS: frozenset[str] = frozenset({
    "lunch_box_unlocked",
    "cursed_effigy_unlocked",
    "entrance_vase_broken",
    "outer_chip_dug",
    "royal_scepter_found",
})


class DayChain:
    """Coordinator for a multi-day Blue Prince attempt.

    Each ``DayChain`` tracks:

    - ``base_cfg``: the immutable baseline ``GameConfig`` supplied at
      construction (day/carry-over flags are overridden per episode; all other
      fields stay from this base).
    - ``n_days``: total days in one attempt (default 200); after this many days
      the chain wraps to day 1 with a clean carry-over slate.
    - ``current_day``: 1-based in-game day counter (1 … n_days).
    - ``carried_flags``: ``dict[str, bool]`` of carry-over discoveries
      accumulated so far in this attempt; only True flags are stored (absent
      key == False).
    """

    def __init__(self, base_cfg: GameConfig, n_days: int = 200) -> None:
        self.base_cfg: GameConfig = base_cfg          # baseline; day/flags overridden each episode
        self.n_days: int = n_days                     # days per attempt before wrapping
        self.current_day: int = 1                     # 1-based; advances via advance()
        self.carried_flags: dict[str, bool] = {}      # only True values stored; False == absent

    def next_config(self) -> GameConfig:
        """Return the ``GameConfig`` for the current day.

        Merges ``carried_flags`` (all True) and the current day index into
        ``base_cfg`` via ``dataclasses.replace``.  The frozenset fields of
        ``GameConfig`` are unaffected — only the bool carry-over fields and
        ``day`` change.
        """
        return dataclasses.replace(
            self.base_cfg,
            day=self.current_day,
            **self.carried_flags,          # unpack only the True flags
        )

    def advance(self, carryover: dict[str, bool]) -> None:
        """Record this day's discoveries and advance the day counter.

        Only True values from ``carryover`` are merged — a False entry never
        un-discovers something that was already found (carry-over is strictly
        accumulative within an attempt).  Unknown keys outside
        ``_CARRYOVER_KEYS`` are silently ignored so callers can pass the full
        ``game.carryover()`` dict without filtering.

        After day ``n_days``, the chain wraps: ``current_day`` returns to 1
        and ``carried_flags`` is cleared, starting a fresh 200-day attempt.
        """
        for key, value in carryover.items():
            if key in _CARRYOVER_KEYS and value:
                self.carried_flags[key] = True

        self.current_day += 1
        if self.current_day > self.n_days:
            self.current_day = 1
            self.carried_flags = {}       # fresh attempt; all discoveries reset
