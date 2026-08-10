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

Implemented:
  - advance_mail_cycle (ON_PLACE) -- the state machine above.
  - deliver_package (ON_ENTER) -- rolls and grants the package's contents
    (data/special_items.json "mail_packages"; special_items.roll_mail_package)
    the first time the player enters the cell holding a delivered package.

Not modelled: a waiting package sets the Mail Room's Dynamic Rarity to
Commonplace for the day. decks.py has no rarity-override channel.
"""

from __future__ import annotations

from ... import special_items as si
from .. import Hook, room_hook

MAIL_EMPTY = "empty"
MAIL_AWAITING = "awaiting"


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
    st = game.state
    cell = game.room_cells.get(room.id, -1)
    if cell < 0 or st.mail_package_cell != cell:
        return
    grants = si.roll_mail_package(st, game.registry, game.rng)
    si.apply_grant_list(st, game.registry, game, grants)
    st.mail_package_cell = -1
