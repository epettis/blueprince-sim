"""Her Ladyship's Chamber and Her Ladyship's Spare Room: pre-armed one-shot
entry bonuses for the Boudoir and Walk-In Closet.

"Once drafted, Her Ladyship's Chamber grants resources for entering listed
rooms: The first time the Boudoir is entered, it gives 10 steps. The first
time the Walk-In Closet is entered, it gives 3 gems. These effects apply on
the first time the room is entered after Her Ladyship's Chamber has been
drafted."

her_ladyships_spare_room__ix135 carries the identical effect_text and, per
the wiki, stacks with the base Chamber rather than replacing it: with both on
the estate, entering a Boudoir pays both bonuses, one after the other. Each
source arms and pays independently (GameState's four
her_ladyships_{chamber,spare_room}_{boudoir,closet}_armed flags), so having
one already paid out never blocks the other.

Arming happens at ON_PLACE (the room's own draft); payment happens at
ON_ENTER of the target room, which the engine only ever fires once per cell
(Game._enter checks state.entered first) -- so a Boudoir/Walk-In Closet
already entered before either Chamber record is drafted never pays for that
source, matching "the first time the room is entered AFTER ... has been
drafted" rather than the room's own first-ever entry.

Boudoir's three upgrade variants (boudoir__ix16/17/18 -- the same room with a
stacked gem bonus, never renamed) count as "the Boudoir". Walk-In Closet has
no upgrade variants in rooms.json.

Not modeled: drafting either room also sets the Boudoir's and Walk-In
Closet's Dynamic Rarity to Commonplace (decks.py has no rarity-override
channel for this).
"""

from __future__ import annotations

from .. import Hook, room_hook
from ..tier1 import _grant

BOUDOIR_STEPS = 10  # from the shared effect_text
CLOSET_GEMS = 3  # from the shared effect_text


@room_hook("her_ladyships_chamber", Hook.ON_PLACE)
def arm_chamber(game, room, ctx_room) -> None:
    """Drafting Her Ladyship's Chamber arms its own Boudoir/Walk-In Closet bonus."""
    game.state.her_ladyships_chamber_boudoir_armed = True
    game.state.her_ladyships_chamber_closet_armed = True


@room_hook("her_ladyships_spare_room__ix135", Hook.ON_PLACE)
def arm_spare_room(game, room, ctx_room) -> None:
    """Drafting Her Ladyship's Spare Room arms its own, independently-stacking bonus."""
    game.state.her_ladyships_spare_room_boudoir_armed = True
    game.state.her_ladyships_spare_room_closet_armed = True


@room_hook("boudoir", Hook.ON_ENTER)
@room_hook("boudoir__ix16", Hook.ON_ENTER)
@room_hook("boudoir__ix17", Hook.ON_ENTER)
@room_hook("boudoir__ix18", Hook.ON_ENTER)
def pay_boudoir_bonus(game, room, ctx_room) -> None:
    """Pay each still-armed Her Ladyship's source's 10-step Boudoir bonus,
    once per source, on this Boudoir's first entry."""
    st = game.state
    if st.her_ladyships_chamber_boudoir_armed:
        st.her_ladyships_chamber_boudoir_armed = False
        _grant(game, "steps", BOUDOIR_STEPS)
    if st.her_ladyships_spare_room_boudoir_armed:
        st.her_ladyships_spare_room_boudoir_armed = False
        _grant(game, "steps", BOUDOIR_STEPS)


@room_hook("walk_in_closet", Hook.ON_ENTER)
def pay_closet_bonus(game, room, ctx_room) -> None:
    """Pay each still-armed Her Ladyship's source's 3-gem Walk-In Closet
    bonus, once per source, on this room's first entry."""
    st = game.state
    if st.her_ladyships_chamber_closet_armed:
        st.her_ladyships_chamber_closet_armed = False
        _grant(game, "gems", CLOSET_GEMS)
    if st.her_ladyships_spare_room_closet_armed:
        st.her_ladyships_spare_room_closet_armed = False
        _grant(game, "gems", CLOSET_GEMS)
