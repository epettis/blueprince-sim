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
from ..engine.shops import REPELLENT_MAX_BANS  # single authoritative definition

# Keys that ``Game.carryover()`` can return and that map 1-to-1 onto
# ``GameConfig`` bool fields.  Keeping this list explicit (rather than
# introspecting GameConfig) makes the contract readable and testable.
_CARRYOVER_KEYS: frozenset[str] = frozenset({
    "lunch_box_unlocked",
    "cursed_effigy_unlocked",
    "entrance_vase_broken",
    "outer_chip_dug",
    "royal_scepter_found",
    "west_gate_unlatched",   # set on first west_path arrival; opens Grounds shortcut
    "mine_south_visited",    # set on mine_south arrival; opens the underpass route
    "sealed_entrance_broken",  # set on sealed_entrance arrival; opens the Basement route
    "weight_room_wall_broken",  # Power Hammer wall break: permanent on future days
    "room46_reached",             # Room 46 first visited: permanent gem-deck gate
    "room8_solved",             # Room 8 first solved: later solves pay the repeat-solve reward
    "boiler_room_steam",       # set on Boiler Room entry; opens the Upper Rotating Gear route
    "treasure_trove_blackprint",  # set on Upper Rotating Gear arrival; adds Treasure Trove to pool
    "orchard_unlocked",        # set on apple_orchard arrival; grants +20 starting steps next day
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

    # Carry-over bool flag keys: the set of GameConfig fields that persist across
    # days within an attempt.  Exposed as a class attribute so obs.py can derive
    # the ``carryover`` observation vector length from it without a parallel list --
    # adding a key here automatically extends the observation space.
    _CARRYOVER_KEYS: frozenset[str] = _CARRYOVER_KEYS

    def __init__(self, base_cfg: GameConfig, n_days: int = 200) -> None:
        self.base_cfg: GameConfig = base_cfg          # baseline; day/flags overridden each episode
        self.n_days: int = n_days                     # days per attempt before wrapping
        self.current_day: int = 1                     # 1-based; advances via advance()
        self.carried_flags: dict[str, bool] = {}      # only True values stored; False == absent
        # Item ids to inject as starting_items on the next day; empty at attempt start.
        self.carried_items: frozenset[str] = frozenset()
        # Vault key ids permanently used: accumulate across all days; never reset within attempt.
        self.used_vault_keys: frozenset[str] = frozenset()
        # Ignition targets permanently lit: accumulated union across all days.  Once lit,
        # a target cannot be lit again in any later day within the same attempt.
        self.lit_targets: frozenset[str] = frozenset()
        # Fixed-location Upgrade Disk ids spent (inserted at a terminal): accumulated
        # union across all days. An unspent disk drops overnight and returns to its room;
        # only a spent disk is permanently gone.  This set gates _is_available so the
        # room's guaranteed_in grant cannot re-mint a disk that was already consumed.
        self.collected_disks: frozenset[str] = frozenset()
        # Keeper of Tithes: running sum of coins banked by the Chapel entry penalty.
        # Accumulated across all days until the Chapel altar is lit (one-time-ever);
        # after payout the counter stays 0 (state.special.chapel_tithes cleared to 0).
        self.chapel_tithes: int = 0
        # Allowance: running permanent total, replaced (not merged) from each
        # day's own carryover value every advance() -- state.allowance already
        # IS the accumulated figure by day end, the same shape as chapel_tithes.
        self.allowance: int = base_cfg.allowance
        # Stars: running permanent total, replaced (not merged) from each
        # day's own carryover value every advance() -- state.stars already IS
        # the accumulated figure by day end, the same shape as allowance.
        # SAVE-scoped: survives the attempt wrap below, so stars accumulate
        # across the whole save rather than resetting with a fresh attempt.
        self.stars: int = base_cfg.stars
        # Cloister of Joya's Main Course bonus: running permanent total,
        # replaced (not merged) from each day's own carryover value every
        # advance() -- state.main_course_bonus already IS the accumulated
        # figure by day end, the same shape as allowance/stars. SAVE-scoped,
        # like stars above.
        self.main_course_bonus: int = base_cfg.main_course_bonus
        # Experiment letters delivered to the Mail Room: running permanent
        # total, replaced (not merged) from each day's own carryover value --
        # state.experiment.letters_delivered already IS the accumulated figure
        # by day end. SAVE-scoped, like stars and main_course_bonus above.
        self.letters_delivered: int = base_cfg.letters_delivered
        # Mail Room order/delivery cycle: REPLACED (not merged) from each
        # day's own carryover value every advance(), the same shape as
        # allowance/chapel_tithes -- state.mail_cycle already IS the day's
        # ending value ("empty" or "awaiting").
        self.mail_cycle: str = base_cfg.mail_cycle
        # Freight Shipping (mail_room__ix91) transit countdown: REPLACED from
        # each day's own carryover value every advance(), the same shape as
        # mail_cycle, then mechanically decayed by 1 (floored at 0) -- this
        # class does not interpret what the count means for the mail cycle,
        # only carries and decays it (see effects/rooms/mail_room.py for the
        # readiness decision).
        self.mail_transit_days: int = base_cfg.mail_transit_days
        # Tomorrow Hallway (hallway__ix76) carry: REPLACED (not merged) from each
        # day's own carryover value every advance(), the same shape as mail_cycle/
        # mail_transit_days -- a one-day pulse of extra Hallway copies for the
        # immediately following day's draft pool, not a running total.
        self.hallway_tomorrow_extra: int = base_cfg.hallway_tomorrow_extra
        # Fixed-source Allowance Token ids collected (ever, across all days):
        # a Mora Jai box or the Cloister's own token, each with its own id.
        # Union-merged across days, same shape as collected_disks.
        self.collected_allowance_tokens: frozenset[str] = frozenset(
            base_cfg.collected_allowance_tokens
        )
        # Sanctum Key source ids permanently spent: accumulate across all days,
        # same shape as collected_disks/collected_allowance_tokens.
        self.collected_sanctum_keys: frozenset[str] = frozenset(
            base_cfg.collected_sanctum_keys
        )
        # Inner Sanctum realm ids whose door is permanently open: accumulate
        # across all days, same shape as collected_sanctum_keys.
        self.sigil_doors_open: frozenset[str] = frozenset(base_cfg.sigil_doors_open)
        # Repellent bans: room_id -> days_remaining (positive integer).
        # Decremented each advance(); 0 = expired (dropped before next_config).
        self.repellent_bans: dict[str, int] = {}
        # Insertion-ordered list for oldest-first eviction when the cap is hit.
        self._ban_order: list[str] = []
        # Upgrade Disks: variant ids applied this attempt; union-merged across days.
        # Seeded from the base config rather than empty, because unlike the other
        # carry-over fields this one is also a legitimate configuration input —
        # a preset upgrade would otherwise be wiped on day 1.
        self.applied_upgrades: frozenset[str] = frozenset(base_cfg.upgrade_disks)
        # Draft counts: cumulative by root base room id; replaced from carryover each advance.
        self.draft_counts: dict[str, int] = dict(base_cfg.draft_counts)
        # The Foundation's permanent placement: once drafted it never moves again this
        # attempt. -1/0 = not yet drafted. Not bool-valued, so handled explicitly here
        # (and in advance()/next_config()) rather than through _CARRYOVER_KEYS.
        self.foundation_cell: int = base_cfg.foundation_cell
        self.foundation_doors: int = base_cfg.foundation_doors
        # One-day-pulse room bonuses (Sauna/Morning Room/Break Room/Freezer): each
        # is REPLACED (not OR-merged) from that day's own carryover every advance(),
        # so the bonus lands on exactly the following day and lapses again unless
        # re-earned. Not bool-valued-forever like _CARRYOVER_KEYS, so handled
        # explicitly here (same shape as chapel_tithes/foundation_cell).
        self.sauna_bonus: bool = False          # Sauna entered yesterday: +20 steps today
        self.morning_room_bonus: bool = False   # Morning Room entered yesterday: +2 gems today
        self.break_room_keycard: bool = False   # day ended in Break Room yesterday: keycard today
        self.frozen_coins: int = 0              # Freezer carry: coins to start today with (0 = none)
        self.frozen_gems: int = 0               # Freezer carry: gems to start today with (0 = none)
        self.no_contact_due: bool = False       # No Contact Delivery drafted yesterday: package today

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
            lit_targets=self.lit_targets,
            collected_disks=self.collected_disks,
            chapel_tithes=self.chapel_tithes,
            allowance=self.allowance,
            stars=self.stars,
            main_course_bonus=self.main_course_bonus,
            letters_delivered=self.letters_delivered,
            mail_cycle=self.mail_cycle,
            mail_transit_days=self.mail_transit_days,
            hallway_tomorrow_extra=self.hallway_tomorrow_extra,
            collected_allowance_tokens=self.collected_allowance_tokens,
            collected_sanctum_keys=self.collected_sanctum_keys,
            sigil_doors_open=self.sigil_doors_open,
            upgrade_disks=self.applied_upgrades,
            draft_counts=dict(self.draft_counts),
            foundation_cell=self.foundation_cell,
            foundation_doors=self.foundation_doors,
            sauna_bonus=self.sauna_bonus,
            morning_room_bonus=self.morning_room_bonus,
            break_room_keycard=self.break_room_keycard,
            frozen_coins=self.frozen_coins,
            frozen_gems=self.frozen_gems,
            no_contact_due=self.no_contact_due,
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
        - **one-day-pulse keys** (``sauna_bonus``, ``morning_room_bonus``,
          ``break_room_keycard``, ``frozen_coins``, ``frozen_gems``): REPLACED
          from this day's own value every call, never merged with the running
          total — each reports only whether TODAY earned the bonus, so a day
          that doesn't re-earn it clears what the previous day set. This is
          what keeps them one-day pulses instead of permanent unlocks.

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

        # --- lit_targets (permanently-lit ignition targets; accumulate forever within attempt) ---
        lt_val = carryover.get("lit_targets")
        if lt_val is not None:
            self.lit_targets = self.lit_targets | frozenset(lt_val)

        # --- collected_disks (spent fixed-location Upgrade Disks; accumulate forever within attempt) ---
        cd_val = carryover.get("collected_disks")
        if cd_val is not None:
            self.collected_disks = self.collected_disks | frozenset(cd_val)

        # --- chapel_tithes (Keeper of Tithes running total; accumulate until payout) ---
        # After the altar is lit the counter is cleared to 0; subsequent days carry 0.
        ct_val = carryover.get("chapel_tithes")
        if ct_val is not None:
            self.chapel_tithes = ct_val

        # --- allowance (running permanent total; replace each advance) ---
        av_val = carryover.get("allowance")
        if av_val is not None:
            self.allowance = av_val

        # --- stars (running permanent total; replace each advance) ---
        star_val = carryover.get("stars")
        if star_val is not None:
            self.stars = star_val

        # --- main_course_bonus (running permanent total; replace each advance) ---
        letters_val = carryover.get("letters_delivered")
        if letters_val is not None:
            self.letters_delivered = letters_val
        # --- main_course_bonus (running permanent total; replace each advance) ---
        mcb_val = carryover.get("main_course_bonus")
        if mcb_val is not None:
            self.main_course_bonus = mcb_val

        # --- mail_cycle (Mail Room order/delivery state; replace each advance) ---
        mc_val = carryover.get("mail_cycle")
        if mc_val is not None:
            self.mail_cycle = mc_val

        # --- mail_transit_days (Freight Shipping transit countdown) ---
        # Replace with today's ending value, then one day elapses: decrement by
        # 1, floored at 0 -- the same decrementing-counter shape as
        # repellent_bans, applied to a single running count instead of a dict.
        mtd_val = carryover.get("mail_transit_days")
        if mtd_val is not None:
            self.mail_transit_days = mtd_val
        self.mail_transit_days = max(0, self.mail_transit_days - 1)

        # --- hallway_tomorrow_extra (Tomorrow Hallway pulse; replace each advance) ---
        hte_val = carryover.get("hallway_tomorrow_extra")
        if hte_val is not None:
            self.hallway_tomorrow_extra = hte_val

        # --- collected_allowance_tokens (fixed one-time sources; accumulate as union) ---
        cat_val = carryover.get("collected_allowance_tokens")
        if cat_val is not None:
            self.collected_allowance_tokens = self.collected_allowance_tokens | frozenset(cat_val)

        # --- collected_sanctum_keys (Sanctum Key sources spent; accumulate forever within attempt) ---
        csk_val = carryover.get("collected_sanctum_keys")
        if csk_val is not None:
            self.collected_sanctum_keys = self.collected_sanctum_keys | frozenset(csk_val)

        # --- sigil_doors_open (Inner Sanctum doors unlocked; accumulate forever within attempt) ---
        sdo_val = carryover.get("sigil_doors_open")
        if sdo_val is not None:
            self.sigil_doors_open = self.sigil_doors_open | frozenset(sdo_val)

        # --- upgrade_disks (variant ids applied this attempt; accumulate as union) ---
        ud_val = carryover.get("upgrade_disks")
        if ud_val is not None:
            self.applied_upgrades = self.applied_upgrades | frozenset(ud_val)

        # --- draft_counts (cumulative attempt draft counts; replace each advance) ---
        dc_val = carryover.get("draft_counts")
        if dc_val is not None:
            self.draft_counts = dict(dc_val)

        # --- foundation_cell / foundation_doors (permanent placement; replace each advance) ---
        # shops.carryover() already resolves "cfg wins once set", so this is a
        # straight replace, same shape as chapel_tithes.
        fc_val = carryover.get("foundation_cell")
        if fc_val is not None:
            self.foundation_cell = fc_val
        fd_val = carryover.get("foundation_doors")
        if fd_val is not None:
            self.foundation_doors = fd_val

        # --- one-day-pulse room bonuses (Sauna/Morning Room/Break Room/Freezer/
        #     No Contact Delivery) ---
        # Unconditional REPLACE (not OR-merge): each key reports only whether TODAY
        # earned the bonus, so a day that does not re-earn it must clear the running
        # value rather than keep yesterday's True forever (that would make the
        # bonus permanent, which none of these rooms are).
        self.sauna_bonus = bool(carryover.get("sauna_bonus"))
        self.morning_room_bonus = bool(carryover.get("morning_room_bonus"))
        self.break_room_keycard = bool(carryover.get("break_room_keycard"))
        self.frozen_coins = carryover.get("frozen_coins") or 0
        self.frozen_gems = carryover.get("frozen_gems") or 0
        self.no_contact_due = bool(carryover.get("no_contact_due"))

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
        while len(active) > REPELLENT_MAX_BANS:
            oldest = active.pop(0)
            del self.repellent_bans[oldest]
        self._ban_order = active

        self.current_day += 1
        if self.current_day > self.n_days:
            self.current_day = 1
            self.carried_flags = {}           # fresh attempt; all discoveries reset
            self.carried_items = frozenset()
            self.used_vault_keys = frozenset()
            self.lit_targets = frozenset()    # fresh attempt; ignition history reset
            self.collected_disks = frozenset()  # fresh attempt; disks back in the house
            self.chapel_tithes = 0            # fresh attempt; tithe bank reset
            self.allowance = self.base_cfg.allowance  # fresh attempt; back to the base preset
            # stars, main_course_bonus and letters_delivered are deliberately
            # absent here: all three are save-scoped and carry through the wrap
            # into the next attempt, unlike every other value reset above.
            self.mail_cycle = self.base_cfg.mail_cycle  # fresh attempt; back to the base preset
            self.mail_transit_days = self.base_cfg.mail_transit_days  # fresh attempt; back to base
            self.hallway_tomorrow_extra = self.base_cfg.hallway_tomorrow_extra  # fresh attempt
            self.collected_allowance_tokens = frozenset(
                self.base_cfg.collected_allowance_tokens
            )
            self.collected_sanctum_keys = frozenset(self.base_cfg.collected_sanctum_keys)
            self.sigil_doors_open = frozenset(self.base_cfg.sigil_doors_open)
            self.repellent_bans = {}
            self._ban_order = []
            self.sauna_bonus = False          # fresh attempt; no "yesterday" to carry a pulse from
            self.morning_room_bonus = False
            self.break_room_keycard = False
            self.frozen_coins = 0
            self.frozen_gems = 0
            self.no_contact_due = False
            # Fresh attempt: drop everything earned in-run, but keep whatever the
            # base config presets, which is the same baseline day 1 started from.
            self.applied_upgrades = frozenset(self.base_cfg.upgrade_disks)
            self.draft_counts = dict(self.base_cfg.draft_counts)
            # Fresh attempt: The Foundation goes back to being undrafted, same
            # baseline as day 1 originally started from.
            self.foundation_cell = self.base_cfg.foundation_cell
            self.foundation_doors = self.base_cfg.foundation_doors
