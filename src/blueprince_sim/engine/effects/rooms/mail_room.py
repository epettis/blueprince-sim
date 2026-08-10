"""Mail Room: the order-and-deliver cycle, and the package it delivers.

Effect text: "A package will be delivered here the day after drafting this
room." The cycle is not a countdown: the package waits for the Mail Room to
be drafted again, however many days that takes, and cannot be missed by
skipping a day.

  - EMPTY + draft -> an order is placed; the cycle becomes AWAITING. Nothing
    else happens.
  - AWAITING + draft -> the package is delivered into that Mail Room's own
    cell; the cycle returns to EMPTY. Walking into the cell grants the
    package. Leaving it uncollected loses it: the next day's floorplan is a
    fresh draft with no memory of an unentered cell.

Same Day Delivery (mail_room__ix89) card text: "The package will be
delivered here after you reach rank 8." Drafting it arms this cell to
deliver the moment Rank 8 is entered (immediately if Rank 8 has already
been reached today). If Rank 8 is never reached, the room falls back
overnight to the base cycle's AWAITING state: the next draft of it delivers
immediately, places no new order, and a later Rank 8 arrival does not
deliver a second package.

No Contact Delivery (mail_room__ix90) card text: "The package will be
dropped off on the entrance steps the day after drafting this room." Every
draft places an order. Modelled as a day-start grant rather than a physical
pickup -- the package is rolled and added to the inventory outright at the
start of the following day, so it cannot be missed or left uncollected.

Freight Shipping (mail_room__ix91) card text: "A very large package will be
delivered here 3 days after drafting this room." Wiki: drafting on an empty
cycle places an order and starts a two-day TRANSIT state, during which
drafting the room has no effect at all (no re-order, no delivery). Once the
two transit days have elapsed, the package is ready and -- like the base
cycle's AWAITING state -- waits any number of days for the room to be
drafted again, which delivers it into that draft's own cell. Freight's
contents are rolled at draft time (not entry time), since "the items are
immediately available."

  - EMPTY + draft -> an order is placed; the cycle becomes TRANSIT with
    ``FREIGHT_TRANSIT_DAYS`` remaining.
  - TRANSIT + draft -> no effect.
  - TRANSIT, transit days exhausted -> next_mail_cycle promotes the cycle to
    AWAITING (computed once per day in shops.carryover(), the same cadence
    as the transit-day decrement in DayChain.advance()).
  - AWAITING + draft -> the package's contents are rolled and delivered into
    that draft's own cell; the cycle returns to EMPTY.

Implemented:
  - advance_mail_cycle (ON_PLACE, "mail_room") -- the base cycle above.
  - deliver_package (ON_ENTER, "mail_room") -- rolls and grants the
    package's contents (data/special_items.json "mail_packages";
    special_items.roll_mail_package) the first time the player enters the
    cell holding a delivered package.
  - same_day_arm (ON_PLACE, "mail_room__ix89") -- arms or immediately
    delivers per the state machine above.
  - same_day_deliver_package (ON_ENTER, "mail_room__ix89") -- the same grant
    as deliver_package, for the Same Day cell.
  - reach_rank8 (called from Game._enter) -- delivers an armed Same Day
    package the first time the player enters a Rank >= 8 cell today.
  - resolve_same_day_end (called from Game._terminate) -- an armed but
    undelivered Same Day package falls back to the base AWAITING state for
    tomorrow.
  - no_contact_order (ON_PLACE, "mail_room__ix90") -- records today's order.
  - resolve_no_contact_delivery (called from shops.on_day_start) -- grants
    yesterday's No Contact order at the start of today.
  - freight_order (ON_PLACE, "mail_room__ix91") -- the transit/deliver cycle
    above; rolls and stores the package's contents
    (special_items.roll_freight_package) at draft time.
  - freight_deliver_package (ON_ENTER, "mail_room__ix91") -- grants the
    already-rolled contents on first entry into the delivered cell.
  - next_mail_cycle (called from shops.carryover()) -- the readiness
    decision: promotes a TRANSIT cycle to AWAITING once its transit days
    are spent.

Not modelled: a waiting package sets the Mail Room's Dynamic Rarity to
Commonplace for the day. decks.py has no rarity-override channel.
"""

from __future__ import annotations

from ... import special_items as si
from .. import Hook, room_hook

MAIL_EMPTY = "empty"
MAIL_AWAITING = "awaiting"
MAIL_TRANSIT = "transit"

SAME_DAY_ID = "mail_room__ix89"
NO_CONTACT_ID = "mail_room__ix90"
FREIGHT_ID = "mail_room__ix91"

FREIGHT_TRANSIT_DAYS = 2  # wiki: two days of transit after an order is placed


def _deliver_into_cell(game, room) -> None:
    """Grants the delivered package's contents on first entry into ``room``'s cell.

    Shared by the base Mail Room and Same Day Delivery: both mark a
    delivered package the same way, via ``state.mail_package_cell``.
    """
    st = game.state
    cell = game.room_cells.get(room.id, -1)
    if cell < 0 or st.mail_package_cell != cell:
        return
    grants = si.roll_mail_package(st, game.registry, game.rng)
    si.apply_grant_list(st, game.registry, game, grants)
    st.mail_package_cell = -1


@room_hook("mail_room", Hook.ON_PLACE)
def advance_mail_cycle(game, room, ctx_room) -> None:
    """Advances the order/deliver cycle on each Mail Room draft.

    An outer-room draft of this id has no cell in ``game.room_cells``
    (outer placement never records one); delivery is skipped in that case
    and the cycle stays AWAITING for the next placement.
    """
    si.configure(game.state, game.cfg)
    st = game.state
    if st.mail_cycle == MAIL_EMPTY:
        st.mail_cycle = MAIL_AWAITING
        return
    cell = game.room_cells.get(room.id, -1)
    if cell < 0:
        return
    st.mail_package_cell = cell
    st.mail_cycle = MAIL_EMPTY


@room_hook("mail_room", Hook.ON_ENTER)
def deliver_package(game, room, ctx_room) -> None:
    """Grants the delivered package's contents on first entry into its cell."""
    _deliver_into_cell(game, room)


# ------------------------------------------------------------ Same Day Delivery

@room_hook(SAME_DAY_ID, Hook.ON_PLACE)
def same_day_arm(game, room, ctx_room) -> None:
    """Arms this cell to deliver the moment Rank 8 is reached.

    A carried AWAITING cycle (last night's fallback) delivers into this
    cell immediately instead of arming, places no new order, and resets the
    cycle to EMPTY. Otherwise, if Rank 8 has already been reached today the
    package delivers immediately; if not, the cell is armed for
    ``reach_rank8`` to deliver into later.
    """
    si.configure(game.state, game.cfg)
    st = game.state
    cell = game.room_cells.get(room.id, -1)
    if cell < 0:
        return
    if st.mail_cycle == MAIL_AWAITING:
        st.mail_package_cell = cell
        st.mail_cycle = MAIL_EMPTY
    elif st.rank8_reached:
        st.mail_package_cell = cell
    else:
        st.mail_same_day_armed_cell = cell


@room_hook(SAME_DAY_ID, Hook.ON_ENTER)
def same_day_deliver_package(game, room, ctx_room) -> None:
    """Grants the delivered package's contents on first entry into its cell."""
    _deliver_into_cell(game, room)


def reach_rank8(game) -> None:
    """Delivers an armed Same Day Delivery package the first time Rank 8 is entered today.

    Idempotent via ``state.rank8_reached``, so a later Rank 8+ arrival
    cannot deliver a second package.
    """
    st = game.state
    if st.rank8_reached:
        return
    st.rank8_reached = True
    cell = st.mail_same_day_armed_cell
    if cell < 0:
        return
    st.mail_same_day_armed_cell = -1
    st.mail_package_cell = cell


def resolve_same_day_end(game) -> None:
    """An armed but undelivered Same Day package falls back to the base
    AWAITING cycle for tomorrow's Mail Room draft.
    """
    st = game.state
    if st.mail_same_day_armed_cell >= 0:
        st.mail_cycle = MAIL_AWAITING
    st.mail_same_day_armed_cell = -1


# ---------------------------------------------------------- No Contact Delivery

@room_hook(NO_CONTACT_ID, Hook.ON_PLACE)
def no_contact_order(game, room, ctx_room) -> None:
    """Records today's order; the package grants at the start of the
    following day (``resolve_no_contact_delivery``).
    """
    game.state.no_contact_drafted = True


def resolve_no_contact_delivery(game) -> None:
    """Grants yesterday's No Contact Delivery order outright at day start."""
    if not game.cfg.no_contact_due:
        return
    si.configure(game.state, game.cfg)
    grants = si.roll_mail_package(game.state, game.registry, game.rng)
    si.apply_grant_list(game.state, game.registry, game, grants)


# -------------------------------------------------------------- Freight Shipping

@room_hook(FREIGHT_ID, Hook.ON_PLACE)
def freight_order(game, room, ctx_room) -> None:
    """Freight Shipping's order/transit/deliver cycle.

    EMPTY + draft -> an order is placed; the cycle enters TRANSIT for
    ``FREIGHT_TRANSIT_DAYS``. TRANSIT + draft -> no effect at all: no
    re-order, no delivery, no counter change. AWAITING + draft (transit
    already spent, promoted by ``next_mail_cycle``) -> the package's
    contents are rolled now and delivered into this cell; the cycle returns
    to EMPTY.
    """
    si.configure(game.state, game.cfg)
    st = game.state
    if st.mail_cycle == MAIL_EMPTY:
        st.mail_cycle = MAIL_TRANSIT
        st.mail_transit_days = FREIGHT_TRANSIT_DAYS
        return
    if st.mail_cycle == MAIL_TRANSIT:
        return
    cell = game.room_cells.get(room.id, -1)
    if cell < 0:
        return
    st.mail_freight_grants = si.roll_freight_package(st, game.registry, game.rng)
    st.mail_package_cell = cell
    st.mail_cycle = MAIL_EMPTY


@room_hook(FREIGHT_ID, Hook.ON_ENTER)
def freight_deliver_package(game, room, ctx_room) -> None:
    """Grants the already-rolled package contents on first entry into its cell."""
    st = game.state
    cell = game.room_cells.get(room.id, -1)
    if cell < 0 or st.mail_package_cell != cell:
        return
    si.apply_grant_list(st, game.registry, game, st.mail_freight_grants)
    st.mail_package_cell = -1
    st.mail_freight_grants = []


def next_mail_cycle(state) -> str:
    """Tomorrow's mail cycle value (called from shops.carryover()).

    Promotes a Freight order from TRANSIT to AWAITING once its transit days
    are spent; every other cycle value passes through unchanged.
    """
    if state.mail_cycle == MAIL_TRANSIT and state.mail_transit_days <= 0:
        return MAIL_AWAITING
    return state.mail_cycle
