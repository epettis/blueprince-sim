"""Quest Bedroom: an Allowance Token the first time the Antechamber is entered
after entering a Quest Bedroom.

Implemented:
  - arm_antechamber_bonus -- entering the Quest Bedroom arms the effect for
    the rest of the day. The +10 steps grant is the base Guest Bedroom's own
    "grant" data effect (see EFFECT_OVERRIDE in tools/ingest_sheet.py); this
    handler only tracks the Antechamber bonus.
  - pay_allowance_on_antechamber_arrival -- registered on the Antechamber
    itself, at Hook.ON_ARRIVE so it fires on every landing, including
    re-entry, not just the first. A prior Antechamber visit does not block
    the payout; only arriving before a Quest Bedroom has been entered does.
    Pays once per day: a second Quest Bedroom, or a later Antechamber
    arrival, does not pay again once GameState.quest_bedroom_allowance_paid_today
    is set.

Not modelled:
  - The wiki's rule is stated per-Antechamber ("The first time each
    Antechamber is entered..."). This sim has exactly one Antechamber, so
    per-day and per-Antechamber coincide here and the distinction has no
    observable effect.
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

ALLOWANCE_PER_TOKEN = 2  # an Allowance Token is worth +2 allowance


@room_hook("quest_bedroom__ix71", Hook.ON_ENTER)
def arm_antechamber_bonus(game, room, ctx_room) -> None:
    """"If you enter ANTECHAMBER today, add 2[coins] to your allowance."

    Arms today's bonus; the payout itself happens on the Antechamber's own
    ON_ARRIVE handler below.
    """
    game.state.quest_bedroom_entered_today = True


@room_hook("antechamber", Hook.ON_ARRIVE)
def pay_allowance_on_antechamber_arrival(game, room, ctx_room) -> None:
    """Pays the Quest Bedroom's Allowance Token on arrival at the Antechamber,
    once per day, provided a Quest Bedroom has already been entered today.
    """
    st = game.state
    if st.quest_bedroom_entered_today and not st.quest_bedroom_allowance_paid_today:
        _grant(game, "allowance", ALLOWANCE_PER_TOKEN)
        st.quest_bedroom_allowance_paid_today = True
