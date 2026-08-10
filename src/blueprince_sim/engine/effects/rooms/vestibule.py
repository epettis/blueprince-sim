"""Vestibule: closes and rerolls its own lock every time it is entered.

Wiki (blueprince.wiki.gg/wiki/Vestibule): "Whenever the Vestibule is
entered, all four of its doors close, including the door the player just
entered from. One of the four doors becomes locked at random, and the other
three become unlocked, regardless of which doors were previously locked or
unlocked." "Since the Vestibule's effect is an entry effect, it can be
retriggered by entering and leaving the room. This allows the player to
'reroll' the locked door if the desired path is locked at the cost of 2
steps per attempt." "unlike the Passageway, Vestibule doors are never
security-locked." "The effect of the Foyer overrides the Vestibule's,
forcing all four doors to remain unlocked. The doors still close whenever
the player enters."

Implemented:
  - reroll_lock is registered at Hook.ON_ARRIVE, which Game.move and
    Game.travel_to already fire unconditionally on every landing -- including
    re-entry, outside the ON_ENTER/state.entered gate -- so it needs no new
    dispatch in game.py: this is exactly the "entry effect ... retriggered by
    entering and leaving" contract (see effects/rooms/quest_bedroom.py's
    Antechamber handler for the same pattern). It reads the room's own
    placed door mask rather than assuming all four cardinal directions
    exist, since a doorway can never point into the outer wall.
  - With a Foyer or Spare Foyer on the estate (GameState.foyer_placed), the
    lock roll is skipped and every doorway is forced open instead, per "The
    effect of the Foyer overrides the Vestibule's".
  - The lock draws from a single fixed named RNG substream ("vestibule_lock"),
    so re-entering the room consumes the stream's next value -- a
    deterministic reroll a policy can farm by walking out and back in, 2
    steps per attempt. That trade is faithful to the game and is left
    uncapped on purpose.

Not modelled:
  - Security doors: the wiki states the Vestibule is never security-locked,
    so the roll only ever produces DOOR_LOCKED, never DOOR_SECURITY.
  - The "doors close" framing: this sim has no separate open/closed state,
    so forcing three doors open and one locked is the entire observable
    effect; there is nothing else to close.
"""

from __future__ import annotations

from ...grid import DIRS
from .. import Hook, room_hook


@room_hook("vestibule", Hook.ON_ARRIVE)
def reroll_lock(game, room, ctx_room) -> None:
    """Lock one randomly-chosen doorway and open the rest, on every arrival."""
    st = game.state
    cell = st.pos
    directions = [d for d in DIRS if st.placed_doors[cell] & d]
    if st.foyer_placed:
        for d in directions:
            game._open_segment(cell, d)
        return
    locked = game.rng.choice("vestibule_lock", directions)
    for d in directions:
        if d == locked:
            game._lock_segment(cell, d)
        else:
            game._open_segment(cell, d)
