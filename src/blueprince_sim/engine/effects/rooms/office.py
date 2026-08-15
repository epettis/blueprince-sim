"""Office: registers the terminal capability shared by its two independent
processes -- Spread Gold in Estate (a spread) and Run Payroll (not one).

``Capability.OFFICE_TERMINAL`` is read by ``Game.can_spread_gold`` /
``Game.can_run_payroll`` (via ``Game._capability_cell``) to gate both actions
to this room's cell, without ``game.py`` naming this room's id directly --
the same shape as ``security.py``'s ``Capability.SECURITY_LEVEL`` /
``pump_room.py``'s ``Capability.PUMP_PANEL``. Distinct from the Office's
``flags.disk_reader`` (a different terminal process, already shipped).

Implemented:
  - spread_gold -- "Spread Gold in Estate" (docs/rooms.md): once
    per day, a pile of coins into every currently drafted room, including the
    Office itself but never a room drafted afterward. This IS a spread: piles
    are parked in ``GameState.spread_pending`` and paid out by
    ``Game._collect_spread`` on arrival, the same "arrival, not first entry"
    shape as the Patio/Locker Room/Secret Garden -- so a Conference Room
    already placed redirects every pile (including the Office's own) into its
    own cell instead, matching those three spreaders' own redirect branch.
    Pile size is a random 3, 4, or 5 coins per receiving room (owner ruling:
    the Office wiki page and the Spread page both omit a figure for this
    spread -- unlike the Tomb's flat 5 coins, which the wiki states outright
    -- so this reuses the Office's own published floor-item pile sizes as the
    game's own answer for what an Office coin pile looks like).
  - run_payroll -- "Run Payroll": puts 10 coins in each of the Maid's Chamber
    and the Servant's Quarters, as two piles of 5 (wiki, both figures
    published). The wiki names only these two rooms -- not the Servant's
    Spare Quarters upgrade variant (servants_spare_quarters__ix134), which is
    absent from every source describing this process. NOT a spread: the wiki
    states outright that it is not a spread effect and has no Conference Room
    interaction, so it does not touch ``spread_pending``. Paid out instead
    through a dedicated ``GameState.payroll_pending`` dict keyed by ROOM ID
    rather than cell (the target may not be drafted yet), collected by
    ``Game._collect_payroll_pending`` the same "arrival, not first entry" way
    ``_collect_spread`` pays out ``spread_pending`` -- so a target drafted
    AFTER the terminal is used still receives its pile (wiki: draft order
    does not matter). Weekly cooldown (owner ruling): unusable again until
    the next in-game Saturday after the day it was used. The wiki's Time page
    states Day One's date as 7 November 1993 (the Drafting Studio calendar);
    7 November 1993 was a Sunday on the real calendar, so in-game weeks run
    Sunday -> Saturday and every Saturday is exactly a multiple of 7 (days 7,
    14, 21, ...) -- see ``is_saturday``.

Not modelled (owner ruling, data/rooms.json's office.meta.simplification):
  - The wiki carries an open question box on this cooldown offering two
    readings ("may last until the coming Saturday or the Saturday
    afterwards, with no clear pattern between them") and a claimed removal
    "after Day 85". This models only the shorter "coming Saturday" reading,
    with no Day-85 special case.
"""

from __future__ import annotations

from .. import Capability, provides

provides("office", Capability.OFFICE_TERMINAL)

# Spread Gold in Estate: random pile size per receiving room -- see module docstring.
SPREAD_GOLD_PILE_MIN = 3
SPREAD_GOLD_PILE_MAX = 5

# Run Payroll: two fixed piles, one per target room -- see module docstring.
PAYROLL_PILE = 5
PAYROLL_TARGETS = ("maids_chamber", "servants_quarters")
PAYROLL_COOLDOWN_KEY = "office_payroll"


def spread_gold(game) -> None:
    """Park one random 3/4/5-coin pile per currently drafted room (including
    the Office) in ``GameState.spread_pending``, or redirect the whole batch
    into a placed Conference Room's own cell -- see the module docstring.

    Rolls happen in a fixed cell-ascending order regardless of the Conference
    Room redirect, from a named substream (``office_spread_gold``), so a
    seeded run's pile sizes stay reproducible either way. Marks today's
    once-per-day use.
    """
    state = game.state
    conference_cell = game.room_cells.get("conference_room")
    occupied = [i for i, idx in enumerate(state.grid) if idx >= 0]
    for cell in occupied:
        amount = game.rng.randint("office_spread_gold", SPREAD_GOLD_PILE_MIN, SPREAD_GOLD_PILE_MAX)
        dest = conference_cell if conference_cell is not None else cell
        state.spread_pending.setdefault(dest, []).append(("coins_exact", amount))
    state.special.office_spread_gold_used = True


def is_saturday(day: int) -> bool:
    """True on an in-game Saturday -- see the module docstring for the Day
    One = Sunday derivation. Day 7, 14, 21, ... are Saturdays; day 1 is not.
    """
    return day % 7 == 0


def _next_saturday_after(day: int) -> int:
    """Smallest day strictly greater than ``day`` with ``is_saturday`` True --
    the "coming Saturday" the cooldown reopens on (owner ruling; see the
    module docstring for the rejected "Saturday afterwards" reading).
    """
    return ((day // 7) + 1) * 7


def payroll_available(last_used: dict, today: int) -> bool:
    """True when Run Payroll's weekly cooldown has elapsed by ``today``.

    Never used (no ``PAYROLL_COOLDOWN_KEY`` entry) is always available.
    Otherwise available once ``today`` reaches the coming in-game Saturday
    strictly after the day it was last used.
    """
    last = last_used.get(PAYROLL_COOLDOWN_KEY)
    if last is None:
        return True
    return today >= _next_saturday_after(last)


def run_payroll(game) -> None:
    """Park a 5-coin pile for each of ``PAYROLL_TARGETS`` in
    ``GameState.payroll_pending`` (independent of ``spread_pending`` -- see
    the module docstring) and record today as the cooldown's last use.
    """
    state = game.state
    for room_id in PAYROLL_TARGETS:
        state.payroll_pending.setdefault(room_id, []).append(("coins_exact", PAYROLL_PILE))
    state.payroll_last_used[PAYROLL_COOLDOWN_KEY] = game.cfg.day
