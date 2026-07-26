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
    "garage_car_used_before",
})

# Maximum active Repellent bans allowed simultaneously (wiki: 3).
_REPELLENT_MAX_BANS = 3


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
    - ``carried_items``: ``frozenset[str]`` of item ids that persist from the
      previous day (permanent/until_used self-persisters + Coat Check + Moon
      Pendant carry).  Injected into the next day's GameConfig.starting_items.
    - ``repellent_bans``: ``dict[str, int]`` mapping room_id to days remaining
      on the Repellent ban.  Decremented on each ``advance()``; expired bans
      (days_left == 0) are dropped.  The frozenset of active ban room ids is
      passed as ``GameConfig.banned_rooms`` to ``next_config()``.
    - ``_ban_order``: insertion-ordered list of room ids tracking which ban was
      added first (for the oldest-evict rule when the 3-ban cap is hit).
    """

    def __init__(self, base_cfg: GameConfig, n_days: int = 200) -> None:
        self.base_cfg: GameConfig = base_cfg          # baseline; day/flags overridden each episode
        self.n_days: int = n_days                     # days per attempt before wrapping
        self.current_day: int = 1                     # 1-based; advances via advance()
        self.carried_flags: dict[str, bool] = {}      # only True values stored; False == absent
        # Item ids to inject as starting_items on the next day; empty at attempt start.
        self.carried_items: frozenset[str] = frozenset()
        # Vault key ids permanently used: accumulate across all days; never reset within attempt.
        self.used_vault_keys: frozenset[str] = frozenset()
        # Repellent bans: room_id -> days_remaining (positive integer).
        # Decremented each advance(); 0 = expired (dropped before next_config).
        self.repellent_bans: dict[str, int] = {}
        # Insertion-ordered list for oldest-first eviction when the cap is hit.
        self._ban_order: list[str] = []

    def next_config(self) -> GameConfig:
        """Return the ``GameConfig`` for the current day.

        Merges ``carried_flags`` (all True), ``carried_items`` (as
        starting_items), and the active ``repellent_bans`` (as banned_rooms)
        into ``base_cfg`` via ``dataclasses.replace``.  The day index is also
        overridden.
        """
        active_bans = frozenset(
            rid for rid, days in self.repellent_bans.items() if days > 0
        )
        return dataclasses.replace(
            self.base_cfg,
            day=self.current_day,
            starting_items=(
                self.base_cfg.starting_items | self.carried_items
            ),
            banned_rooms=active_bans,
            used_vault_keys=self.used_vault_keys,
            **self.carried_flags,          # unpack only the True flags
        )

    def advance(self, carryover: dict) -> None:
        """Record this day's discoveries and advance the day counter.

        Handles three classes of carryover values:

        - **bool keys** (in ``_CARRYOVER_KEYS``): only True values are merged
          — a False entry never un-discovers something already found.
        - **``"starting_items"``** (list[str]): replaces ``carried_items``
          wholesale with a frozenset of the given ids (the full persistent-item
          computation is done by ``shops.carryover()``).
        - **``"banned_rooms"``** (dict[str, int]): new bans from this day's
          Repellent uses.  Merged into the running ``repellent_bans`` dict;
          if a room is already banned its counter is refreshed to the new
          (larger) value.  The 3-ban cap is enforced after merging: if more
          than 3 distinct room ids are active, the oldest (``_ban_order``-order)
          is evicted until the count is at most 3.

        After merging, all surviving ban counters are decremented by 1 and
        any counter reaching 0 is dropped (the ban expires).

        After day ``n_days``, the chain wraps: ``current_day`` returns to 1
        and ALL state (flags, items, bans) is cleared for a fresh attempt.

        Unknown keys outside ``_CARRYOVER_KEYS`` and the three special non-bool
        keys are silently ignored.
        """
        # --- bool flags ---
        for key, value in carryover.items():
            if key in _CARRYOVER_KEYS and value:
                self.carried_flags[key] = True

        # --- starting_items (item persistence carry) ---
        items_val = carryover.get("starting_items")
        if items_val is not None:
            self.carried_items = frozenset(items_val)

        # --- used_vault_keys (permanently-used vault key ids; accumulate forever within attempt) ---
        vk_val = carryover.get("used_vault_keys")
        if vk_val is not None:
            self.used_vault_keys = self.used_vault_keys | frozenset(vk_val)

        # --- banned_rooms (Repellent bans from this day) ---
        # Decrement PRE-EXISTING bans first (one day has elapsed for them),
        # then merge the NEW bans from this day.  New bans are not decremented
        # on the advance that introduces them: a ban of days=7 should be active
        # for exactly 7 next_config() calls after the advance that adds it.
        new_bans: dict[str, int] = carryover.get("banned_rooms") or {}

        # Step 1: decrement all currently-tracked bans; drop expired ones
        for rid in list(self.repellent_bans):
            self.repellent_bans[rid] -= 1
        expired = [rid for rid, days in self.repellent_bans.items() if days <= 0]
        for rid in expired:
            del self.repellent_bans[rid]
            if rid in self._ban_order:
                self._ban_order.remove(rid)

        # Step 2: merge new bans from today (with their full-day counts intact)
        for room_id, days in new_bans.items():
            if room_id not in self.repellent_bans:
                self._ban_order.append(room_id)
            # Refresh/add the ban (new use resets to the supplied days count)
            self.repellent_bans[room_id] = days

        # Enforce the 3-ban cap: evict oldest bans until at most 3 active
        active = [rid for rid in self._ban_order if rid in self.repellent_bans]
        while len(active) > _REPELLENT_MAX_BANS:
            oldest = active.pop(0)
            del self.repellent_bans[oldest]
        self._ban_order = active

        self.current_day += 1
        if self.current_day > self.n_days:
            self.current_day = 1
            self.carried_flags = {}       # fresh attempt; all discoveries reset
            self.carried_items = frozenset()
            self.used_vault_keys = frozenset()
            self.repellent_bans = {}
            self._ban_order = []
